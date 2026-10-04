"""A0 continuity path decoder over PersonTrack fragments. Identity-free.

Nodes are frozen R5 raw PersonTrack fragments. Edges are overlap-aware
handoff transitions and bounded gap transitions, all gated by frozen R5 /
V3-C0 / V3-support constants only. Decoding is deterministic beam search
that preserves a bounded top-K set of alternative action-spanning paths.
No connected-component collapse. No GT, identity, media, or learning.
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
import multi_track_action_v1 as base

# --- Frozen reused gates (no new thresholds) ---------------------------------
GAP_MAX_S = el.PARAMS_V3C0['interp_max_gap_s']  # 0.30 frozen V3-C0 interp limit
RADIUS = v3.SUPPORT_RADIUS  # 0.06 frozen support radius
SIZE_TOL = r5.LOG_SIZE_MAX + r5.JITTER_S  # frozen size agreement

# --- Decoder implementation bounds (generic, documented, not tuned) -----------
TOP_K = 5  # predetermined multi-path bound
BEAM_WIDTH = 512  # partial-path beam bound
MAX_FRAGMENTS_PER_PATH = 64  # path length bound (finite clip termination aid)
MAX_OUTGOING_PER_FRAGMENT = 24  # per-node edge fan-out bound
W_SUPPORT = 0.25  # support bonus weight (dimensionless, predetermined)
W_RANGE = 1.0  # incremental vertical-range motion weight (predetermined)
RANGE_SCALE_CY = 0.5  # vertical-range normalization (same scale as excursion)

# Edge kinds
GAP = 'gap'
OVERLAP = 'overlap'
INTERLEAVE = 'interleave'

# Action-motion bonus (identity-free, predetermined): a retained DiveTrack must
# plausibly span an action, so excursion/sequence evidence from the frozen
# V3-C0 replay contributes on the same [0,1] scale as completeness. Static
# full-clip spectator fragments score ~0 here; complete dive-like arcs ~1.
ACTION_EXCURSION_SCALE_CY = 0.5
ACTION_SEQUENCE_BONUS = 0.25

# A1 local-appearance compatibility (frozen OSNet, no gallery, no learning):
# "Do fragment A and nearby fragment B appear locally compatible?" Mean
# cosine over cross-carrier box pairs adjacent to the handoff. Predetermined
# weight on the same dimensionless scale as the other score terms.
W_APP = 1.0
APP_WINDOW_FRAMES = 2  # handoff-adjacent frame window (predetermined)
APP_BEAM = 'A1_CONTINUITY_PLUS_LOCAL_APPEARANCE'
A0_BEAM = 'A0_CONTINUITY_PATH_DECODER'

OSNET_FILES = {
    'cohort': 'diveanalyzer-cand-quality-v3/runs/subject_resolution/osnet_emb_cohort_v1.npz',
    'indep': 'diveanalyzer-independent-gt/runs/subject_resolution/osnet_emb_indep_v1.npz',
}
_CACHE_ROOT = Path(__file__).resolve().parents[3]
_VEC_STORE = {}  # dive -> (key->vec) for the dive currently being inferred


def _load_vecs(dive, group):
    """Frozen OSNet vectors for one dive (cache-only, disk-backed, LRU-1)."""
    if dive in _VEC_STORE:
        return _VEC_STORE[dive]
    _VEC_STORE.clear()
    rel = OSNET_FILES.get(group)
    if rel is None:
        return None
    path = _CACHE_ROOT / rel
    if not path.exists():
        return None
    import numpy as np
    z = np.load(str(path))
    keys, vecs = z['keys'], z['vecs']
    prefix = dive + '|'
    store = {}
    for k, v in zip(keys.tolist(), vecs):
        if k.startswith(prefix):
            store[k] = v
    del keys, vecs, z
    _VEC_STORE[dive] = store
    return store


class AppCtx:
    """Handoff-local appearance compatibility from frozen embeddings."""

    def __init__(self, dive, group, cands, pts):
        self.dive = dive
        self.group = group
        self.store = _load_vecs(dive, group)
        self.pts = pts
        # per-frame rounded-box -> candidate index for cache-key mapping
        self.keymap = []
        for fi, cl in enumerate(cands):
            m = {}
            for ci, c in enumerate(cl):
                m[(round(c.cx, 6), round(c.cy, 6), round(c.bw, 6), round(c.bh, 6))] = ci
            self.keymap.append(m)

    @property
    def available(self):
        return self.store is not None

    def _vec(self, box, fi):
        if self.store is None or fi < 0 or fi >= len(self.keymap):
            return None
        ci = self.keymap[fi].get((round(box.cx, 6), round(box.cy, 6),
                                  round(box.bw, 6), round(box.bh, 6)))
        if ci is None:
            return None
        # cache keys are "dive|fi|k"; cohort cache uses 0-based fi while the
        # independent cache uses 1-based fi (frozen conventions, verified).
        key_fi = fi if self.group == 'cohort' else fi + 1
        return self.store.get('%s|%d|%d' % (self.dive, key_fi, ci))

    def compat(self, S, T, kind, key):
        """Mean cross-carrier cosine adjacent to the handoff (None if empty)."""
        if self.store is None:
            return None
        if kind == GAP:
            lo, hi = S.last() - APP_WINDOW_FRAMES, T.first() + APP_WINDOW_FRAMES
        elif kind == OVERLAP:
            lo = hi = key
            lo, hi = key - APP_WINDOW_FRAMES, key + APP_WINDOW_FRAMES
        else:
            lo, hi = key[0] - APP_WINDOW_FRAMES, key[1] + APP_WINDOW_FRAMES
        import numpy as np
        sims = []
        for i in S.starts:
            if i < lo or i > hi:
                continue
            vi = self._vec(S.boxes[i], i)
            if vi is None:
                continue
            for j in T.starts:
                if j < lo or j > hi:
                    continue
                vj = self._vec(T.boxes[j], j)
                if vj is None:
                    continue
                sims.append(float(np.dot(vi, vj)))
        if not sims:
            return None
        return sum(sims) / len(sims)


def inference_view(frames):
    """Same explicit whitelist as V1; strips cache annotations and metadata."""
    return base.inference_view(frames)


def _velocity(boxes, starts, pts, idx, backward=False):
    """Local constant velocity at frame idx from nearest two observations."""
    if backward:
        obs = [i for i in starts if i <= idx]
        if len(obs) < 2:
            return None
        i1, i0 = obs[-1], obs[-2]
    else:
        obs = [i for i in starts if i >= idx]
        if len(obs) < 2:
            return None
        i0, i1 = obs[0], obs[1]
    dt = pts[i1] - pts[i0]
    if dt <= 0:
        return None
    a, b = boxes[i0], boxes[i1]
    return ((b.cx - a.cx) / dt, (b.cy - a.cy) / dt)


def build_lattice(tracks, pts):
    """Deterministic fragment lattice. Returns (gap_edges, overlap_edges).

    gap_edges: list of dicts {from,to,gap_s,residual,cost}.
    overlap_edges: list of dicts {from,to,handoff,cost}.
    """
    by_tid = {t.tid: t for t in tracks}
    by_start = {}
    for t in tracks:
        by_start.setdefault(t.first(), []).append(t)
    n = len(pts)
    fps_nom = n / (pts[-1] - pts[0]) if pts[-1] > pts[0] else 30.0
    gap_window = int(math.ceil(GAP_MAX_S * fps_nom)) + 1

    gap_out = {t.tid: [] for t in tracks}
    # --- gap transitions: reuse V1 edge gates, drop mutual-best restriction --
    for a in sorted(tracks, key=lambda t: t.tid):
        end = a.last()
        aa = a.boxes[end]
        va = _velocity(a.boxes, a.starts, pts, end, backward=True)
        for pos in range(end + 1, min(n, end + 1 + gap_window)):
            gap = pts[pos] - pts[end]
            if gap > GAP_MAX_S:
                break
            for b in by_start.get(pos, []):
                if b.last() <= end:
                    continue
                bb = b.boxes[pos]
                if not r5._gate_ok(aa, bb, gap):
                    continue
                vx, vy = va if va is not None else (0.0, 0.0)
                residual = math.hypot(bb.cx - aa.cx - vx * gap,
                                      bb.cy - aa.cy - vy * gap)
                if residual <= RADIUS:
                    cost = residual / RADIUS + gap / GAP_MAX_S
                    gap_out[a.tid].append({'from': a.tid, 'to': b.tid,
                                           'gap_s': gap, 'prediction_residual': residual,
                                           'cost': cost})
    for tid in gap_out:
        gap_out[tid].sort(key=lambda e: (e['cost'], e['to']))
        del gap_out[tid][MAX_OUTGOING_PER_FRAGMENT:]

    # --- overlap transitions: handoff only on locally agreeing observations --
    overlap_out = {t.tid: [] for t in tracks}
    # per-frame occupancy
    occ = [[] for _ in range(n)]
    for t in tracks:
        for i in t.starts:
            occ[i].append(t.tid)
    # candidate handoffs keyed by ordered pair
    cand = {}
    for h in range(n):
        tids = occ[h]
        m = len(tids)
        if m < 2:
            continue
        for x in range(m):
            for y in range(x + 1, m):
                t1, t2 = (tids[x], tids[y]) if tids[x] < tids[y] else (tids[y], tids[x])
                A, B = by_tid[t1], by_tid[t2]
                ba, bb = A.boxes[h], B.boxes[h]
                dist = math.hypot(bb.cx - ba.cx, bb.cy - ba.cy)
                if dist > RADIUS:
                    continue
                area_a = max(ba.bw * ba.bh, 1e-9)
                area_b = max(bb.bw * bb.bh, 1e-9)
                size = abs(math.log(area_b / area_a))
                if size > SIZE_TOL:
                    continue
                key = (t1, t2)
                prev = cand.get(key)
                cur = (dist + size, h)
                if prev is None or cur < prev:
                    cand[key] = cur
    for (t1, t2), (_, h) in cand.items():
        A, B = by_tid[t1], by_tid[t2]
        ba, bb = A.boxes[h], B.boxes[h]
        dist = math.hypot(bb.cx - ba.cx, bb.cy - ba.cy)
        area_a = max(ba.bw * ba.bh, 1e-9)
        area_b = max(bb.bw * bb.bh, 1e-9)
        size = abs(math.log(area_b / area_a))
        base_cost = dist / RADIUS + size / SIZE_TOL
        for (S, T) in ((A, B), (B, A)):
            if S.first() > T.first():
                continue
            if T.last() <= h:
                continue
            # motion-direction consistency: predict S forward, compare to T.
            vel_cost = 0.0
            vs = _velocity(S.boxes, S.starts, pts, h, backward=True)
            nxt = [i for i in T.starts if i > h]
            if vs is not None and nxt:
                j = nxt[0]
                dt = pts[j] - pts[h]
                if dt > 0:
                    sb = S.boxes[h]
                    tb = T.boxes[j]
                    res = math.hypot(tb.cx - sb.cx - vs[0] * dt,
                                     tb.cy - sb.cy - vs[1] * dt)
                    if res > RADIUS:
                        continue
                    vel_cost = res / RADIUS
            cost = base_cost + vel_cost
            overlap_out[S.tid].append({'from': S.tid, 'to': T.tid,
                                       'handoff': h, 'cost': cost})
    for tid in overlap_out:
        overlap_out[tid].sort(key=lambda e: (e['cost'], e['to'], e['handoff']))
        del overlap_out[tid][MAX_OUTGOING_PER_FRAGMENT:]

    # --- interleave transitions: overlapping alternatives with NO common ----
    # observed frame (strict frame alternation). Handoff pair (i, j) with a
    # small positive time step, gated by the frozen same-object displacement
    # and size gates under a zero-order hold (adjacent-frame motion is small
    # relative to the frozen radius). Only for interval-overlapping pairs;
    # disjoint pairs are gap transitions.
    inter_out = {t.tid: [] for t in tracks}
    window_s = r5.MISS_MAX_S  # frozen R5 gap tolerance as handoff window
    pair_best = {}
    for h in range(n):
        for i in (h + 1, h + 2):
            if i >= n:
                continue
            dt = pts[i] - pts[h]
            if dt <= 0 or dt > window_s:
                continue
            for t1 in occ[h]:
                A = by_tid[t1]
                ba = A.boxes[h]
                for t2 in occ[i]:
                    if t2 == t1:
                        continue
                    B = by_tid[t2]
                    # interval overlap required (truly interleaved alternatives)
                    if not (A.first() <= B.last() and B.first() <= A.last()):
                        continue
                    bb = B.boxes[i]
                    if not r5._gate_ok(ba, bb, dt):
                        continue
                    dist = math.hypot(bb.cx - ba.cx, bb.cy - ba.cy)
                    if dist > RADIUS:
                        continue
                    key = (t1, t2, i)
                    cur = (dist / RADIUS + dt / window_s, h)
                    prev = pair_best.get(key)
                    if prev is None or cur < prev:
                        pair_best[key] = cur
    for (t1, t2, j), (cost, h) in pair_best.items():
        B = by_tid[t2]
        if B.last() <= h:
            continue
        inter_out[t1].append({'from': t1, 'to': t2, 'handoff': (h, j),
                              'cost': cost})
    for tid in inter_out:
        inter_out[tid].sort(key=lambda e: (e['cost'], e['to'], e['handoff']))
        del inter_out[tid][MAX_OUTGOING_PER_FRAGMENT:]
    return gap_out, overlap_out, inter_out


def _path_boxes(tids, kinds, keys, by_tid):
    """Merge carrier boxes along a path. Returns dict frame->box.

    Each carrier contributes only its own segment between consecutive
    handoffs: (prev_key, key] for overlap handoffs (incoming carrier owns
    the handoff frame), (prev_time, S.last] for gap carriers. No
    interpolation: simultaneously inconsistent boxes are never concatenated
    as one person, and a carrier's boxes outside its segment (possibly a
    different person after an R5 switch) never enter the path.
    """
    boxes = {}
    seg_start = None  # exclusive lower frame bound owned by current carrier
    cur = tids[0]
    for k, key, nxt in zip(kinds, keys, tids[1:]):
        S = by_tid[cur]
        for i in S.starts:
            if seg_start is not None and i < seg_start:
                continue
            if k == OVERLAP and i >= key:
                continue
            if k == INTERLEAVE and i > key[0]:
                continue
            if i not in boxes:
                boxes[i] = S.boxes[i]
        if k == GAP:
            seg_start = by_tid[nxt].first()
        elif k == OVERLAP:
            seg_start = key
        else:
            seg_start = key[1]
        cur = nxt
    last = by_tid[cur]
    for i in last.starts:
        if (seg_start is None or i >= seg_start) and i not in boxes:
            boxes[i] = last.boxes[i]
    return boxes


def _score_path(tids, kinds, costs, boxes, pts, n_frames, apps=None):
    starts = sorted(boxes)
    span = pts[starts[-1]] - pts[starts[0]] if len(starts) > 1 else 0.0
    dur = pts[-1] - pts[0] if pts[-1] > pts[0] else 1.0
    coverage = len(starts) / (starts[-1] - starts[0] + 1) if len(starts) > 1 else 1.0
    mean_edge = sum(costs) / len(costs) if costs else 0.0
    mean_conf = sum(boxes[i].conf for i in starts) / len(starts)
    completeness = (span / dur + coverage) / 2.0
    # Incremental motion evidence: vertical range accumulated so far. Action
    # paths (dives) accumulate range as they extend; static prefixes do not.
    # Identity-free, available at every prefix, guides the beam toward
    # action-following hypotheses without any GT or identity signal.
    cys = [boxes[i].cy for i in starts]
    vrange = max(cys) - min(cys) if cys else 0.0
    motion = min(vrange / RANGE_SCALE_CY, 1.0)
    # A1 local appearance: running mean handoff compatibility (frozen OSNet,
    # no gallery/identity). Missing-cache handoffs contribute nothing.
    app_mean = 0.0
    if apps:
        known = [a for a in apps if a is not None]
        if known:
            app_mean = sum(known) / len(known)
    return completeness + W_SUPPORT * mean_conf + W_RANGE * motion + W_APP * app_mean - mean_edge


def decode_topk(tracks, pts, app=None):
    """Beam search over fragment paths. Returns ranked path dicts.

    app is an optional AppCtx (A1); None selects pure A0 continuity.
    """
    by_tid = {t.tid: t for t in tracks}
    gap_out, overlap_out, inter_out = build_lattice(tracks, pts)
    n_frames = len(pts)

    def outgoing(tid):
        for e in gap_out.get(tid, []):
            yield (GAP, e['to'], e['gap_s'], e['cost'])
        for e in overlap_out.get(tid, []):
            yield (OVERLAP, e['to'], e['handoff'], e['cost'])
        for e in inter_out.get(tid, []):
            yield (INTERLEAVE, e['to'], e['handoff'], e['cost'])

    # state: (score_so_far_tuple..., tids, kinds, keys, costs, time)
    partials = []
    for t in tracks:
        boxes = {i: t.boxes[i] for i in t.starts}
        s = _score_path([t.tid], [], [], boxes, pts, n_frames, [])
        partials.append({'tids': [t.tid], 'kinds': [], 'keys': [],
                         'costs': [], 'apps': [], 'time': t.last(), 'score': s})
    complete = {}

    def record(p):
        key = tuple(p['tids'])
        if key not in complete or p['score'] > complete[key]['score']:
            complete[key] = p

    for p in partials:
        record(p)
    for _ in range(MAX_FRAGMENTS_PER_PATH):
        nxt_partials = []
        extended_any = False
        for p in partials:
            tid = p['tids'][-1]
            used = set(p['tids'])
            extended = False
            for kind, to, key, cost in outgoing(tid):
                if to in used:
                    continue
                T = by_tid[to]
                if kind == GAP:
                    if T.first() <= p['time']:
                        continue
                    new_time = T.last()
                elif kind == OVERLAP:
                    if key <= p['time']:
                        continue
                    if T.last() <= key:
                        continue
                    new_time = key
                else:
                    if key[1] <= p['time']:
                        continue
                    if T.last() < key[1]:
                        continue
                    new_time = key[1]
                if new_time <= p['time']:
                    continue
                boxes = _path_boxes(p['tids'] + [to], p['kinds'] + [kind],
                                    p['keys'] + [key], by_tid)
                compat = app.compat(by_tid[p['tids'][-1]], T, kind, key) if app is not None else None
                s = _score_path(p['tids'] + [to], p['kinds'] + [kind],
                                p['costs'] + [cost], boxes, pts, n_frames,
                                p['apps'] + [compat])
                nxt_partials.append({'tids': p['tids'] + [to],
                                     'kinds': p['kinds'] + [kind],
                                     'keys': p['keys'] + [key],
                                     'costs': p['costs'] + [cost],
                                     'apps': p['apps'] + [compat],
                                     'time': new_time, 'score': s})
                record(nxt_partials[-1])
                extended = True
                extended_any = True
            if not extended:
                record(p)
        if not extended_any:
            break
        nxt_partials.sort(key=lambda p: (-p['score'], p['tids']))
        partials = nxt_partials[:BEAM_WIDTH]
    for p in partials:
        record(p)

    ranked = sorted(complete.values(), key=lambda p: (-p['score'], p['tids']))
    # materialize boxes for every decoded path (full ranking happens in
    # infer() after the frozen V3-C0 replay contributes motion evidence).
    mats = []
    for p in ranked:
        boxes = _path_boxes(p['tids'], p['kinds'], p['keys'], by_tid)
        mats.append({**p, 'boxes': boxes})
    gap_n = sum(len(v) for v in gap_out.values())
    ov_n = sum(len(v) for v in overlap_out.values())
    in_n = sum(len(v) for v in inter_out.values())
    return mats, {'nodes': len(tracks), 'gap_edges': gap_n,
                  'overlap_edges': ov_n, 'interleave_edges': in_n,
                  'decoded_paths': len(mats)}


def select_topk(mats):
    """Diverse top-K selection over fully scored paths (deterministic)."""
    ordered = sorted(mats, key=lambda p: (-p['full_score'], p['tids']))
    selected = []
    for p in ordered:
        keep = True
        for q in selected:
            common = [i for i in p['boxes'] if i in q['boxes']]
            if not common:
                sim = 0.0
            else:
                agree = sum(1 for i in common
                            if math.hypot(p['boxes'][i].cx - q['boxes'][i].cx,
                                          p['boxes'][i].cy - q['boxes'][i].cy) <= RADIUS)
                sim = agree / len(common)
            if sim >= 0.95:
                keep = False
                break
        if keep:
            selected.append(p)
        if len(selected) >= TOP_K:
            break
    if len(selected) < TOP_K:
        seen = {tuple(p['tids']) for p in selected}
        for p in ordered:
            if tuple(p['tids']) not in seen:
                selected.append(p)
                seen.add(tuple(p['tids']))
            if len(selected) >= TOP_K:
                break
    return selected


def action_bonus(row):
    """Identity-free motion evidence from frozen V3-C0 replay (no GT)."""
    bonus = min(row['action_evidence']['downward_arc_cy'] / ACTION_EXCURSION_SCALE_CY, 1.0)
    if row['procedural_sequence'] == 'COMPLETE_DIVE_SEQUENCE':
        bonus += ACTION_SEQUENCE_BONUS
    return bonus


def describe_path(refs, boxes, clip):
    """Frozen V1 trajectory description on decoded path boxes (Event Logic
    V3-C0 replay unchanged)."""
    tr = r5.Tracklet(tid=-1, starts=sorted(boxes), boxes=dict(boxes))
    return base.describe(tr, list(refs), clip)


def infer(frames, fps, dive='', group=''):
    clean = inference_view(frames)
    pts = [f['pts_s'] for f in clean]
    if not pts or any(b <= a for a, b in zip(pts, pts[1:])):
        raise ValueError('Strictly increasing recorded PTS required')
    if [f['fi'] for f in clean] != list(range(1, len(clean) + 1)):
        raise ValueError('Frozen one-based sequential frame cache required')
    clip = v2.Clip('', clean, fps)
    raw = r5.build_tracklets_full(clip.cands, fps)
    # A1 iff frozen local embeddings cover this dive (cache-only lookup by
    # clip identity, the already-authorized cache-row semantics). Hurdle and
    # cache-miss dives fall back to pure A0 continuity. No GT anywhere.
    app = AppCtx(dive, group, clip.cands, pts) if dive else None
    formulation = A0_BEAM
    if app is not None and not app.available:
        app = None
    if app is not None:
        formulation = APP_BEAM
    paths, stats = decode_topk(raw, pts, app)
    stats['formulation'] = formulation
    # Frozen V3-C0 replay on every decoded path, then identity-free ranking:
    # continuity/support/completeness score plus frozen motion evidence.
    for p in paths:
        row = describe_path(p['tids'], p['boxes'], clip)
        p['full_score'] = p['score'] + action_bonus(row)
        p['row'] = row
    selected = select_topk(paths)
    rows = []
    for rank, p in enumerate(selected, 1):
        row = p['row']
        row['path_rank'] = rank
        row['path_score'] = p['full_score']
        row['continuity_score'] = p['score']
        row['association_provenance'] = 'A0_CONTINUITY_PATH' if app is None else 'A1_CONTINUITY_APPEARANCE_PATH'
        known_apps = [a for a in p['apps'] if a is not None]
        row['mean_handoff_appearance'] = sum(known_apps) / len(known_apps) if known_apps else None
        row['handoff_count'] = len(p['kinds'])
        row['overlap_handoff_count'] = sum(k == OVERLAP for k in p['kinds'])
        row['interleave_handoff_count'] = sum(k == INTERLEAVE for k in p['kinds'])
        row['handoff_provenance'] = [
            {'kind': k, 'from': a, 'to': b,
             'key': list(key) if isinstance(key, tuple) else key}
            for k, a, b, key in zip(p['kinds'], p['tids'][:-1], p['tids'][1:], p['keys'])]
        rows.append(row)
    n = sum(r['status'] == 'DIVE_LIKE' for r in rows)
    return {'person_track_count': len(raw),
            'lattice': stats,
            'retained_path_count': len(rows),
            'tracks': rows,
            'product_state': 'NO_DIVE_TRACK_FOUND' if not n else ('ONE_DIVE_TRACK_FOUND' if n == 1 else 'MULTIPLE_DIVE_TRACKS_FOUND'),
            'ambiguity_state': 'AMBIGUOUS_TRACKS' if any(r['status'] == 'AMBIGUOUS' for r in rows) else None}
