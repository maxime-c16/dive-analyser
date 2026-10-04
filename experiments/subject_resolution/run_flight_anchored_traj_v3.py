"""V3 orchestration: GT-free inference, GT-only evaluation.

Inference path (infer) touches no GT: frozen D5 floor caches + frozen
detector floor + F0 frame-level flight lattice + F1 bidirectional
extension + frozen V3-C0 replay. Evaluation (evaluate) uses HUMAN
subject/event authorities only after paths are frozen and the protocol
commit exists.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import resource
import subprocess
import time
from pathlib import Path

import yaml
import flight_anchored_traj_v3 as f3
import run_multi_track_action_v1 as v1run

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'runs/flight_anchored_traj_v3'
DOC = ROOT / 'docs/science'
V1DOC = 'DIVE_ANALYZER_MULTI_TRACK_DIVE_ACTION_V1.json'
V2DOC = 'DIVE_ANALYZER_ACTION_SPANNING_TRACK_ASSOCIATION_V2.json'
PROTOCOL_DOC = 'FLIGHT_ANCHORED_TRAJECTORY_V3_PROTOCOL.md'

RECOVERY_COVERAGE = 0.75  # exploratory flight-recovery criterion (preserved)
FLIGHT_PAD_S = 0.05  # flight-window pad around HUMAN takeoff/water-contact


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, sort_keys=True) + '\n')


def authorities():
    result = v1run.authorities()
    result['v2_report'] = sha(DOC / V2DOC)
    result['f3_implementation'] = sha(
        ROOT / 'experiments/subject_resolution/flight_anchored_traj_v3.py')
    result['f3_runner'] = sha(
        ROOT / 'experiments/subject_resolution/run_flight_anchored_traj_v3.py')
    result['f3_protocol_constants'] = dict(f3.PROTOCOL_CONSTANTS)
    result['packet'] = 'DIVE_ANALYZER_FLIGHT_ANCHORED_TRAJECTORY_V3'
    return result


def run_inference():
    started = time.monotonic()
    frozen = authorities()
    write(OUT / 'authorities.json', frozen)
    for group, ids in v1run.GROUPS.items():
        raw = json.loads(v1run.CACHES[group].read_text())
        assert raw['model_sha256'] == v1run.MODEL_SHA
        assert (raw['floor_conf'], raw['nms_iou'], raw['imgsz'], raw['floor_cap']) == (.001, .45, 640, 200)
        for dive in ids:
            doc = raw['dives'][dive]
            result = f3.infer(f3.inference_view(doc['frames']), float(doc['fps']))
            result['clip_id'] = dive
            result['frame_pts'] = [f['pts_s'] for f in doc['frames']]
            result['input_proxy_sha256'] = doc.get('proxy_sha256')
            write(OUT / f'{dive}.json', result)
            print(dive, result['person_track_count'], result['retained_path_count'],
                  result['lattice'], flush=True)
        del raw
    assert authorities() == frozen
    write(OUT / 'resources.json', {'runtime_s': time.monotonic() - started,
          'peak_ram_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
          'D5_inference': 0, 'new_embeddings': 0, 'training': 0, 'new_labels': 0,
          'B2_reads': 0, 'B2_writes': 0, 'media_decodes': 0})


def flight_window(dive, frame_pts):
    """GT-zone: HUMAN takeoff->water-contact window or GT_UNAVAILABLE."""
    path = DOC / f'pilot_annotations_v2/DEVELOPMENT_DESIGN/dive_{dive}.yaml'
    if not path.exists():
        return {'status': 'GT_UNAVAILABLE'}
    gt = yaml.safe_load(path.read_text())
    try:
        t0 = gt['landmarks']['takeoff']
        t1 = gt['landmarks']['water_contact']
        if not (t0['state'].startswith('HUMAN') and t1['state'].startswith('HUMAN')):
            return {'status': 'GT_UNAVAILABLE'}
    except KeyError:
        return {'status': 'GT_UNAVAILABLE'}
    return {'status': 'SCORED',
            'takeoff_s': t0['timestamp_seconds'],
            'water_contact_s': t1['timestamp_seconds']}


def flight_correspondence(track, anchors, window, frame_pts):
    """GT-zone: correspondence over ALL flight-window anchors.

    Denominator is every HUMAN subject anchor inside the flight window
    (by recorded frame PTS), never intersected with the track's own
    frames: a path that misses the window scores 0, a partial span is
    not inflated.
    """
    t0, t1 = window['takeoff_s'], window['water_contact_s']
    fl = {fi: v for fi, v in anchors.items()
          if t0 - FLIGHT_PAD_S <= frame_pts[fi] <= t1 + FLIGHT_PAD_S}
    if not fl:
        return {'flight_anchors': 0, 'overlapping_anchors': 0,
                'matching_anchors': 0, 'purity': None,
                'matched_anchor_coverage': 0.0, 'is_subject': False,
                'observed_non_subject_anchor_count': 0, 'matched_frames': []}
    tr = {p['frame_index']: p['bbox_cxcywh_norm'][:2] for p in track['trajectory']}
    overlap = hits = 0
    matches = []
    for fi in fl:
        if fi not in tr:
            continue
        overlap += 1
        if math.hypot(tr[fi][0] - fl[fi][0], tr[fi][1] - fl[fi][1]) <= f3.RADIUS:
            hits += 1
            matches.append(fi)
    purity = hits / overlap if overlap else None
    return {'flight_anchors': len(fl), 'overlapping_anchors': overlap,
            'matching_anchors': hits, 'purity': purity,
            'matched_anchor_coverage': hits / len(fl),
            'is_subject': hits >= 2 and (purity or 0) >= .75,
            'observed_non_subject_anchor_count': overlap - hits,
            'matched_frames': matches}


def longest_missing_gap(track, window, frame_pts):
    """GT-zone: longest flight-window interval without an observation."""
    t0, t1 = window['takeoff_s'] - FLIGHT_PAD_S, window['water_contact_s'] + FLIGHT_PAD_S
    obs = sorted(p['pts_s'] for p in track['trajectory'] if t0 <= p['pts_s'] <= t1)
    bounds = [t0] + obs + [t1]
    return max((b - a for a, b in zip(bounds, bounds[1:])), default=t1 - t0)


def subject_event_accuracy(dive, best, output):
    """Frozen HUMAN event authority scoring on the recovered subject path."""
    path = DOC / f'pilot_annotations_v2/DEVELOPMENT_DESIGN/dive_{dive}.yaml'
    if not path.exists():
        return {'status': 'NO_HUMAN_EVENT_AUTHORITY'}
    gt = yaml.safe_load(path.read_text())
    assert gt['split'] == 'DEVELOPMENT_DESIGN'
    assert output['input_proxy_sha256'] == gt['input_media_sha256'], 'Event timebase media mismatch'
    evald = {'status': 'SCORED' if best is not None else 'NO_RETAINED_SUBJECT_PATHTRACK',
             'authority': str(path.relative_to(ROOT)), 'errors': {}}
    for name in ['takeoff', 'apex', 'water_contact']:
        g = gt['landmarks'][name]
        if not g['state'].startswith('HUMAN'):
            evald['errors'][name] = {'status': g['state'], 'signed_error_s': None,
                                     'absolute_error_s': None}
            continue
        pred = best['procedural_events'][name] if best is not None else None
        evald['errors'][name] = {'prediction_pts_s': pred,
            'human_timestamp_s': g['timestamp_seconds'],
            'human_frame_pts_s': g.get('frame_pts_seconds'),
            'signed_error_s': pred - g['timestamp_seconds'] if pred is not None else None,
            'absolute_error_s': abs(pred - g['timestamp_seconds']) if pred is not None else None}
    return evald


def _dive_group(dive):
    return next(g for g, ids in v1run.GROUPS.items() if dive in ids)


def flight_floor_inclusion(dive, group, anchors, window, frame_pts):
    """GT-zone: fraction of flight-window anchors with ANY full-floor
    candidate within RADIUS (raw observation upper bound in-window)."""
    raw = json.loads(v1run.CACHES[group].read_text())
    doc = raw['dives'][dive]
    frames = f3.inference_view(doc['frames'])
    t0, t1 = window['takeoff_s'], window['water_contact_s']
    fl = [fi for fi in anchors
          if t0 - FLIGHT_PAD_S <= frame_pts[fi] <= t1 + FLIGHT_PAD_S]
    if not fl:
        return 0.0
    hit = 0
    for fi in fl:
        for c in frames[fi]['c']:
            if math.hypot(c['cx'] - anchors[fi][0],
                          c['cy'] - anchors[fi][1]) <= f3.RADIUS:
                hit += 1
                break
    return hit / len(fl)


def frame_union_at_cap(dive, group):
    """GT-zone: subject-anchor coverage by the capped frame lattice (any
    lattice candidate within RADIUS) vs full-floor union from V1 report."""
    raw = json.loads(v1run.CACHES[group].read_text())
    doc = raw['dives'][dive]
    frames = f3.inference_view(doc['frames'])
    pts = [f['pts_s'] for f in frames]
    anchors = v1run.subject_anchors(dive, pts)
    _, off = f3.compute_flow(frames, pts)
    kept, _ = f3.build_frame_lattice(frames, off)
    matched = set()
    for fi, lst in enumerate(kept):
        cfi = frames[fi]['fi'] - 1
        if cfi not in anchors:
            continue
        for (_, cx, cy, _, _, _, _, _, _) in lst:
            if math.hypot(cx - anchors[cfi][0], cy - anchors[cfi][1]) <= f3.RADIUS:
                matched.add(cfi)
                break
    return len(matched) / len(anchors), len(anchors)


def evaluate():
    frozen = authorities()
    # protocol freeze integrity: constants committed before GT evaluation
    proto = (DOC / PROTOCOL_DOC).read_text()
    assert f3.F3_VERSION in proto, 'protocol doc missing version'
    for k, v in f3.PROTOCOL_CONSTANTS.items():
        if k == 'reused_frozen':
            continue
        assert repr(v) in proto, f'protocol doc missing {k}={v!r}'
    v1 = json.loads((DOC / V1DOC).read_text())
    v2 = json.loads((DOC / V2DOC).read_text())
    results = {}
    for dive in v1run.COHORT:
        group = _dive_group(dive)
        artifact = OUT / f'{dive}.json'
        output = json.loads(artifact.read_text())
        anchors = v1run.subject_anchors(dive, output['frame_pts'])
        assert anchors
        scored = [{**t, 'evaluation': v1run.correspondence(t, anchors)}
                  for t in output['tracks']]
        window = flight_window(dive, output['frame_pts'])
        if window['status'] == 'SCORED':
            fscored = [{**t, 'flight_evaluation': flight_correspondence(t, anchors, window, output['frame_pts'])}
                       for t in scored]
            fsubj = [t for t in fscored if t['flight_evaluation']['is_subject']]
            frecovered = [t for t in fsubj
                          if t['flight_evaluation']['matched_anchor_coverage'] >= RECOVERY_COVERAGE]
            fbest = max(fsubj, key=lambda t: (t['flight_evaluation']['matched_anchor_coverage'],
                        t['flight_evaluation']['purity'] or 0, -t['path_rank']), default=None)
        else:
            fscored, fsubj, frecovered, fbest = scored, [], [], None
        subject = [t for t in scored if t['evaluation']['is_subject']]
        recovered = [t for t in subject
                     if t['evaluation']['matched_anchor_coverage'] >= RECOVERY_COVERAGE]
        best = max(subject, key=lambda t: (t['evaluation']['matched_anchor_coverage'],
                   t['evaluation']['purity'], -t['path_rank']), default=None)
        v1dive = v1['per_dive'][dive]
        v2dive = v2['per_dive'][dive]
        cap_union, _ = frame_union_at_cap(dive, group)
        # extension breakdown for the best full-action subject path
        if best is not None and window['status'] == 'SCORED':
            core = best['flight_core_interval']
            t0, t1 = window['takeoff_s'], window['water_contact_s']
            fi2pts = {p['frame_index']: p['pts_s'] for p in best['trajectory']}
            prep = {fi: v for fi, v in anchors.items()
                    if fi in fi2pts and fi2pts[fi] < t0 - FLIGHT_PAD_S}
            fl = {fi: v for fi, v in anchors.items()
                  if fi in fi2pts and t0 - FLIGHT_PAD_S <= fi2pts[fi] <= t1 + FLIGHT_PAD_S}
            post = {fi: v for fi, v in anchors.items()
                    if fi in fi2pts and fi2pts[fi] > t1 + FLIGHT_PAD_S}

            def cov(sub):
                if not sub:
                    return None
                h = sum(1 for fi, (ax, ay) in sub.items()
                        for p in [next(pp for pp in best['trajectory'] if pp['frame_index'] == fi)]
                        if math.hypot(p['bbox_cxcywh_norm'][0] - ax,
                                      p['bbox_cxcywh_norm'][1] - ay) <= f3.RADIUS)
                return h / len(sub)
            extension = {'prep_coverage': cov(prep), 'flight_coverage': cov(fl),
                         'post_coverage': cov(post),
                         'full_action_coverage': best['evaluation']['matched_anchor_coverage']}
        else:
            extension = {'prep_coverage': None, 'flight_coverage': None,
                         'post_coverage': None, 'full_action_coverage': None}
        # perception vs representation (preregistered protocol cutoffs:
        # flight-window observation < 0.50 -> OBSERVATION_LIMITED)
        union = v1dive['raw_subject_union_anchor_coverage']
        flight_obs = (flight_floor_inclusion(dive, group, anchors, window, output['frame_pts'])
                      if window['status'] == 'SCORED' else None)
        if window['status'] != 'SCORED':
            limitation = 'GT_UNAVAILABLE'
        elif flight_obs is not None and flight_obs < 0.5:
            limitation = 'FLIGHT_OBSERVATION_LIMITED'
        elif fbest is not None and fbest['flight_evaluation']['matched_anchor_coverage'] >= RECOVERY_COVERAGE:
            if best is not None and best['evaluation']['matched_anchor_coverage'] >= RECOVERY_COVERAGE:
                limitation = 'RECOVERED'
            else:
                limitation = 'FULL_ACTION_EXTENSION_LIMITED'
        elif union >= 0.75:
            limitation = 'FLIGHT_ASSOCIATION_LIMITED'
        else:
            limitation = 'MIXED'
        per = {
            'visible_subject_anchors': len(anchors),
            'formulation': output['lattice'].get('formulation', f3.F0_BEAM),
            'lattice': {k: output['lattice'][k] for k in
                        ('nodes', 'frames', 'full_floor_candidates', 'starts',
                         'decoded_paths', 'decoded_cores')},
            'union_subject_coverage': union,
            'frame_cap_union_subject_coverage': cap_union,
            'flight_floor_inclusion': flight_obs,
            'v2_union_subject_coverage': v2dive['union_subject_coverage'],
            'v2_pool_best_subject_coverage': v2dive['pool_best_subject_coverage'],
            'v2_best_subject_coverage': v2dive['best_subject_coverage'],
            'flight_window': window,
            'flight_anchors': (fbest and fbest['flight_evaluation']['flight_anchors']
                               or (flight_correspondence(scored[0], anchors, window, output['frame_pts'])['flight_anchors']
                                   if window['status'] == 'SCORED' and scored else 0)),
            'best_flight_rank': fbest['path_rank'] if fbest else None,
            'best_flight_coverage': fbest['flight_evaluation']['matched_anchor_coverage'] if fbest else 0.0,
            'best_flight_purity': fbest['flight_evaluation']['purity'] if fbest else None,
            'best_flight_contamination': fbest['flight_evaluation']['observed_non_subject_anchor_count'] if fbest else None,
            'flight_recovered': bool(frecovered),
            'longest_missing_flight_gap_s': longest_missing_gap(fbest, window, output['frame_pts']) if fbest and window['status'] == 'SCORED' else None,
            'best_subject_path_rank': min((t['path_rank'] for t in subject), default=None),
            'recovered': bool(recovered),
            'best_subject_coverage': best['evaluation']['matched_anchor_coverage'] if best else 0.0,
            'best_subject_purity': best['evaluation']['purity'] if best else None,
            'full_action_extension': extension,
            'limitation': limitation,
            'subject_event_accuracy': subject_event_accuracy(
                dive, best if recovered else None, output),
            'alternative_paths': len(scored),
        }
        # multi-path preservation among retained paths
        ext = [t['temporal_extent'] for t in scored]
        synchro = False
        for i in range(len(scored)):
            for j in range(i + 1, len(scored)):
                a, b = scored[i], scored[j]
                if a['temporal_extent'][0] < b['temporal_extent'][1] and \
                   b['temporal_extent'][0] < a['temporal_extent'][1]:
                    synchro = True
        per['synchro_representable'] = synchro
        results[dive] = per
        print(dive, 'flight_rec', per['flight_recovered'],
              'frank', per['best_flight_rank'],
              'fcov', round(per['best_flight_coverage'], 3),
              'fpur', per['best_flight_purity'],
              'union', round(union, 3), 'capunion', round(cap_union, 3),
              'lim', limitation, flush=True)
    flight_evaluable = [d for d in results if results[d]['flight_window']['status'] == 'SCORED']
    flight_recall = sum(results[d]['flight_recovered'] for d in flight_evaluable)
    readiness = {'TRAJECTORY_NOT_READY': 0,
                 'FLIGHT_TRAJECTORY_RECOVERED_ONLY': 0,
                 'ACTION_TRAJECTORY_RECOVERED_EVENT_UNVERIFIED': 0,
                 'TRAJECTORY_AND_EVENTS_PLAUSIBLE': 0}
    for d, p in results.items():
        fl = p['flight_recovered']
        act = (p['recovered'] and p['flight_recovered']
               and (p['full_action_extension']['full_action_coverage'] or 0) >= RECOVERY_COVERAGE)
        # Phase-14 hierarchy: good prep + bad flight is NOT a recovered
        # DiveTrack, so action classes require flight recovery as well.
        if fl and act:
            seq = [t for t in json.loads((OUT / f'{d}.json').read_text())['tracks']
                   if t['path_rank'] == p['best_flight_rank']]
            if seq and seq[0]['procedural_sequence'] == 'COMPLETE_DIVE_SEQUENCE':
                readiness['TRAJECTORY_AND_EVENTS_PLAUSIBLE'] += 1
            else:
                readiness['ACTION_TRAJECTORY_RECOVERED_EVENT_UNVERIFIED'] += 1
        elif fl:
            readiness['FLIGHT_TRAJECTORY_RECOVERED_ONLY'] += 1
        else:
            readiness['TRAJECTORY_NOT_READY'] += 1
    report = {'packet': 'DIVE_ANALYZER_FLIGHT_ANCHORED_TRAJECTORY_V3',
              'authorities': frozen,
              'F0': f3.F0_BEAM,
              'F1': f3.F1_BEAM,
              'TOP_K': f3.FINAL_TOP_K,
              'ANALYTICS_READINESS': readiness,
              'FLIGHT_PHASE_SUBJECT_TRAJECTORY_RECALL': {'recovered_clips': flight_recall,
                'evaluable_clips': len(flight_evaluable)},
              'ACTION_SPANNING_SUBJECT_TRAJECTORY_RECALL': {
                'recovered_clips': sum(r['recovered'] for r in results.values()),
                'evaluable_clips': len(results)},
              'per_dive': results,
              'resources': json.loads((OUT / 'resources.json').read_text()),
              'identity_line': 'FROZEN_DEFERRED',
              'reference_acquisition': 'DEFERRED',
              'scientific_authorities_mutated': 'NO',
              'media_backbone_mutated': 'NO',
              'protected_data': {'524': 'AUTHORITY_CONFLICT_EXCLUDED',
                 '2555': 'SCREEN_RECORDING_STRESS_CASE', 'Paris': 'EXTERNAL_ONLY',
                 'INTERNAL_EVAL': 'NOT_ACCESSED', 'FINAL_HOLDOUT': 'NOT_ACCESSED'},
              'gate': 'SUPERVISOR_REVIEW_AFTER_FLIGHT_ANCHORED_TRAJECTORY_V3'}
    assert authorities() == frozen
    write(DOC / 'DIVE_ANALYZER_FLIGHT_ANCHORED_TRAJECTORY_V3.json', report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['preflight', 'infer', 'evaluate'])
    command = parser.parse_args().command
    if command == 'preflight':
        write(OUT / 'authorities.json', authorities())
        print(json.dumps(authorities(), indent=1))
    elif command == 'infer':
        run_inference()
    else:
        evaluate()
