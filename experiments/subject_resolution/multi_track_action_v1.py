"""Identity-free multi-track inference. No GT, product metadata, or media I/O.

Frozen R5 forms PersonTracks. Bounded mutual-best association adds hypotheses.
Frozen V3 support and V3-C0 provide the two preregistered eligibility views.
"""
from __future__ import annotations

import hashlib
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'landmark_pilot'))
import r5_tracklets_v1 as r5
import subject_reference_acquisition_v2 as v2
import phase_subject_candidate_quality_v3 as v3
import proposer_event_logic_v3_c0 as el


def inference_view(frames):
    """Explicit whitelist; strips cache annotations and all clip metadata."""
    return [{'fi': int(f['fi']), 'pts_s': float(f['pts_s']),
             'c': [{k: float(c[k]) for k in ('cx', 'cy', 'bw', 'bh', 'conf')}
                   for c in f['c']]} for f in frames]


def associate(tracks, pts):
    """Mutual-nearest endpoint prediction; originals preserved by caller."""
    tracks = sorted(tracks, key=lambda t: t.tid)
    by_start = {}
    for b in tracks:
        by_start.setdefault(b.first(), []).append(b)
    edges = []
    for a in tracks:
        end = a.last()
        aa = a.boxes[end]
        vx = vy = 0.0
        if len(a.starts) >= 2:
            prev = a.starts[-2]
            dt = pts[end] - pts[prev]
            vx = (aa.cx - a.boxes[prev].cx) / dt
            vy = (aa.cy - a.boxes[prev].cy) / dt
        for pos in range(end + 1, len(pts)):
            gap = pts[pos] - pts[end]
            if gap > el.PARAMS_V3C0['interp_max_gap_s']:
                break
            for b in by_start.get(pos, []):
                bb = b.boxes[pos]
                if not r5._gate_ok(aa, bb, gap):
                    continue
                residual = math.hypot(bb.cx - aa.cx - vx * gap,
                                      bb.cy - aa.cy - vy * gap)
                if residual <= v3.SUPPORT_RADIUS:
                    edges.append((residual, gap, a.tid, b.tid))
    outgoing, incoming = {}, {}
    for e in sorted(edges):
        outgoing.setdefault(e[2], e)
        incoming.setdefault(e[3], e)
    selected = [e for e in outgoing.values() if incoming[e[3]] == e]
    nxt = {e[2]: e[3] for e in selected}
    prev = {e[3] for e in selected}
    lookup = {t.tid: t for t in tracks}
    merged = []
    for a in tracks:
        if a.tid in prev or a.tid not in nxt:
            continue
        refs = [a.tid]
        while refs[-1] in nxt:
            refs.append(nxt[refs[-1]])
        boxes = {i: b for tid in refs for i, b in lookup[tid].boxes.items()}
        merged.append((r5.Tracklet(tid=a.tid, starts=sorted(boxes), boxes=boxes), refs))
    return merged, [{'from': e[2], 'to': e[3], 'gap_s': e[1],
                     'prediction_residual': e[0]} for e in sorted(selected)]


def quality(tr, clip):
    # Exact frozen V3 generic support; unused A0/A1 feature fields are zero.
    neutral = dict(a0_score=0., excursion_cy=0., peak_down_cys=0., stable_s=0.,
                   entry_like=False, tau_start=0., tau_end=0.,
                   stable_pos_fcy=0., terminal_fcy=0.)
    q = v3.quality_measures(tr, clip, neutral)
    return {k: v for k, v in q.items() if k not in
            {'A0', 'A1', 'excursion_cy', 'peak_down_cys', 'stable_s',
             'entry_like', 'tau_start', 'tau_end', 'span_s'}}


def describe(tr, refs, clip):
    pts = clip.pts_s
    first, last = tr.first(), tr.last()
    times = pts[first:last + 1]
    ys = [tr.boxes[i].cy if i in tr.boxes else None for i in range(first, last + 1)]
    confs = [tr.boxes[i].conf if i in tr.boxes else 0. for i in range(first, last + 1)]
    span = pts[last] - pts[first]
    gap = max((pts[j] - pts[i] for i, j in zip(tr.starts, tr.starts[1:])), default=0.)
    q = quality(tr, clip)
    events = el.propose_events_v3c0(ys, times, confs, '') if span >= v2.MIN_TRACKLET_SPAN_S else {}
    names = ('takeoff', 'apex', 'water_contact')
    ev = {name: events.get(name + '_t') for name in names}
    complete = all(v is not None for v in ev.values()) and ev['takeoff'] < ev['apex'] < ev['water_contact']
    sequence = 'COMPLETE_DIVE_SEQUENCE' if complete else ('PARTIAL_DIVE_SEQUENCE' if any(v is not None for v in ev.values()) else 'NO_VALID_DIVE_SEQUENCE')
    descent = 0.
    if complete:
        arc = [tr.boxes[i].cy for i in tr.starts if ev['apex'] <= pts[i] <= ev['water_contact']]
        if arc:
            descent = max(y - min(arc[:i + 1]) for i, y in enumerate(arc))
    vertical_range = max(tr.boxes[i].cy for i in tr.starts) - min(tr.boxes[i].cy for i in tr.starts)
    coherent = span >= v2.MIN_TRACKLET_SPAN_S and gap <= el.PARAMS_V3C0['interp_max_gap_s']
    d0 = 'AMBIGUOUS'
    if coherent and complete and descent >= v2.ENTRY_EXTREME_MARGIN_CY:
        d0 = 'DIVE_LIKE'
    elif coherent and vertical_range < v2.ENTRY_EXTREME_MARGIN_CY and not complete:
        d0 = 'NON_DIVE'
    d1 = 'AMBIGUOUS' if not v3.q0_tier(q) else d0
    prefix = 'p' if len(refs) == 1 else 'm'
    stable = prefix + '-' + hashlib.sha256(','.join(map(str, refs)).encode()).hexdigest()[:16]
    representative = max(tr.starts, key=lambda i: (tr.boxes[i].conf, -i))
    trajectory = [{'frame_index': clip.cache_idx[i], 'pts_s': pts[i],
                   'bbox_cxcywh_norm': [tr.boxes[i].cx, tr.boxes[i].cy, tr.boxes[i].bw, tr.boxes[i].bh],
                   'confidence': tr.boxes[i].conf} for i in tr.starts]
    return {'track_id': stable, 'person_track_refs': refs,
            'temporal_extent': [pts[first], pts[last]],
            'association_provenance': 'FROZEN_R5_RAW' if len(refs) == 1 else 'PTS_MUTUAL_BEST_FRAGMENT_CHAIN',
            'quality': q, 'trajectory_coverage': len(tr.starts) / (last - first + 1),
            'longest_observation_gap_s': gap, 'D0': d0, 'D1': d1,
            'status': d1, 'action_evidence': {'downward_arc_cy': descent,
                'vertical_range_cy': vertical_range, 'coherent': coherent},
            'procedural_events': ev, 'procedural_sequence': sequence,
            'events_available': any(x is not None for x in ev.values()),
            'analysis_available': False,
            'representative_frame': {'frame_index': clip.cache_idx[representative], 'pts_s': pts[representative]},
            'trajectory': trajectory}


def infer(frames, fps):
    clean = inference_view(frames)
    pts = [f['pts_s'] for f in clean]
    if not pts or any(b <= a for a, b in zip(pts, pts[1:])):
        raise ValueError('Strictly increasing recorded PTS required')
    if [f['fi'] for f in clean] != list(range(1, len(clean) + 1)):
        raise ValueError('Frozen one-based sequential frame cache required')
    clip = v2.Clip('', clean, fps)
    raw = r5.build_tracklets_full(clip.cands, fps)
    merged, edges = associate(raw, pts)
    rows = [describe(t, [t.tid], clip) for t in raw]
    rows += [describe(t, refs, clip) for t, refs in merged]
    rows.sort(key=lambda r: (-int(r['status'] == 'DIVE_LIKE'),
                             -r['quality']['support_frac'],
                             -r['action_evidence']['downward_arc_cy'], r['track_id']))
    for rank, row in enumerate(rows, 1):
        row['rank'] = rank
    n = sum(r['status'] == 'DIVE_LIKE' for r in rows)
    return {'person_track_count': len(raw), 'merged_hypothesis_count': len(merged),
            'association_edges': edges, 'tracks': rows,
            'product_state': 'NO_DIVE_TRACK_FOUND' if not n else ('ONE_DIVE_TRACK_FOUND' if n == 1 else 'MULTIPLE_DIVE_TRACKS_FOUND'),
            'ambiguity_state': 'AMBIGUOUS_TRACKS' if any(r['status'] == 'AMBIGUOUS' for r in rows) else None}
