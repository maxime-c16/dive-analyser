"""V2 orchestration: GT-free inference, GT-only evaluation.

Inference path (infer) touches no GT: candidate caches + frozen detector
floor + A0 continuity decoder + frozen V3-C0 replay. Evaluation (evaluate)
uses HUMAN subject/event authorities only after paths are frozen.
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
import action_span_assoc_v2 as assoc
import run_multi_track_action_v1 as v1run

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'runs/action_span_assoc_v2'
DOC = ROOT / 'docs/science'
V1DOC = 'DIVE_ANALYZER_MULTI_TRACK_DIVE_ACTION_V1.json'

RECOVERY_COVERAGE = 0.75  # exploratory recovery criterion preserved from V1


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
    result['v1_implementation_unchanged'] = sha(ROOT / 'experiments/subject_resolution/multi_track_action_v1.py')
    expected_v1 = subprocess.check_output(
        ['git', 'show', '8964f7d1258d5160c0f42e6db80521a12a148747:experiments/subject_resolution/multi_track_action_v1.py'],
        cwd=ROOT)
    assert result['v1_implementation_unchanged'] == hashlib.sha256(expected_v1).hexdigest()
    result['v1_report'] = sha(DOC / V1DOC)
    assert result['v1_report'] == hashlib.sha256(
        subprocess.check_output(['git', 'show',
                                 '8964f7d1258d5160c0f42e6db80521a12a148747:docs/science/' + V1DOC],
                                cwd=ROOT)).hexdigest()
    result['packet'] = 'DIVE_ANALYZER_ACTION_SPANNING_TRACK_ASSOCIATION_V2'
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
            result = assoc.infer(assoc.inference_view(doc['frames']), float(doc['fps']),
                                  dive=dive, group=group)
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


def subject_event_accuracy(dive, best, output):
    """Frozen HUMAN event authority scoring on the recovered subject path."""
    event_path = DOC / f'pilot_annotations_v2/DEVELOPMENT_DESIGN/dive_{dive}.yaml'
    if not event_path.exists():
        return {'status': 'NO_HUMAN_EVENT_AUTHORITY'}
    event_gt = yaml.safe_load(event_path.read_text())
    assert event_gt['split'] == 'DEVELOPMENT_DESIGN'
    assert output['input_proxy_sha256'] == event_gt['input_media_sha256'], 'Event timebase media mismatch'
    evald = {'status': 'SCORED' if best is not None else 'NO_RETAINED_SUBJECT_PATHTRACK',
             'authority': str(event_path.relative_to(ROOT)), 'errors': {}}
    for name in ['takeoff', 'apex', 'water_contact']:
        gt = event_gt['landmarks'][name]
        if not gt['state'].startswith('HUMAN'):
            evald['errors'][name] = {'status': gt['state'], 'signed_error_s': None,
                                     'absolute_error_s': None}
            continue
        pred = best['procedural_events'][name] if best is not None else None
        evald['errors'][name] = {'prediction_pts_s': pred,
            'human_timestamp_s': gt['timestamp_seconds'],
            'human_frame_pts_s': gt.get('frame_pts_seconds'),
            'signed_error_s': pred - gt['timestamp_seconds'] if pred is not None else None,
            'absolute_error_s': abs(pred - gt['timestamp_seconds']) if pred is not None else None}
    return evald


def _dive_group(dive):
    return next(g for g, ids in v1run.GROUPS.items() if dive in ids)


def union_and_raw(dive, group):
    """GT-zone: union subject-anchor coverage recomputed from frozen R5 raw
    tracklets (same caches as V1). Returns (union, raw_tracklets, clip)."""
    raw = json.loads(v1run.CACHES[group].read_text())
    doc = raw['dives'][dive]
    frames = assoc.inference_view(doc['frames'])
    pts = [f['pts_s'] for f in frames]
    anchors = v1run.subject_anchors(dive, pts)
    clip = assoc.v2.Clip('', frames, float(doc['fps']))
    trax = assoc.r5.build_tracklets_full(clip.cands, float(doc['fps']))
    matched = set()
    for t in trax:
        for i in t.starts:
            fi = frames[i]['fi'] - 1
            if fi in anchors:
                b = t.boxes[i]
                if math.hypot(b.cx - anchors[fi][0], b.cy - anchors[fi][1]) <= assoc.RADIUS:
                    matched.add(fi)
    return len(matched) / len(anchors), trax, clip, frames, pts, anchors


def lattice_transition_recall(trax, frames, pts, anchors):
    """GT-zone: fraction of consecutive matched-anchor transitions that are
    same-fragment or directly edge-linked in the A0 lattice."""
    by_tid = {t.tid: t for t in trax}
    gap_out, ov_out, inter_out = assoc.build_lattice(trax, pts)
    edges = {}
    for d in (gap_out, ov_out, inter_out):
        for a, lst in d.items():
            for e in lst:
                edges.setdefault(a, set()).add(e['to'])
    match = {}
    for t in trax:
        for i in t.starts:
            fi = frames[i]['fi'] - 1
            if fi in anchors:
                b = t.boxes[i]
                if math.hypot(b.cx - anchors[fi][0], b.cy - anchors[fi][1]) <= assoc.RADIUS:
                    match.setdefault(fi, set()).add(t.tid)
    afis = sorted(match)
    same = linked = unlinked = 0
    for f1, f2 in zip(afis, afis[1:]):
        s1, s2 = match[f1], match[f2]
        if s1 & s2:
            same += 1
        elif any(b in edges.get(a, ()) for a in s1 for b in s2):
            linked += 1
        else:
            unlinked += 1
    tot = same + linked + unlinked
    return {'same_fragment': same, 'edge_linked': linked, 'unlinked': unlinked,
            'transition_recall': (same + linked) / tot if tot else 0.0}


def pool_best_subject(dive, group, trax, clip, pts, anchors, retained_ids):
    """GT-zone: best subject-corresponding path over the FULL decoded pool
    (deterministic re-decode; asserts retained top-K reproducibility)."""
    app = assoc.AppCtx(dive, group, clip.cands, pts)
    if not app.available:
        app = None
    paths, stats = assoc.decode_topk(trax, pts, app)
    for p in paths:
        row = assoc.describe_path(p['tids'], p['boxes'], clip)
        p['full_score'] = p['score'] + assoc.action_bonus(row)
        p['row'] = row
    selected = assoc.select_topk(paths)
    sel_ids = [p['row']['track_id'] for p in selected]
    assert sel_ids == list(retained_ids), 'retained top-K not reproducible'
    best = None
    n_subject_pool = 0
    for p in paths:
        ev = v1run.correspondence(p['row'], anchors)
        if ev['is_subject']:
            n_subject_pool += 1
            key = (ev['matched_anchor_coverage'], ev['purity'], -p['full_score'])
            if best is None or key > best[0]:
                best = (key, p, ev)
    return paths, stats, n_subject_pool, best


def flight_stats(dive, frames, anchors):
    """GT-zone: HUMAN flight-window anchor stats where HUMAN event authority
    exists; otherwise NO_HUMAN_FLIGHT_AUTHORITY."""
    path = DOC / f'pilot_annotations_v2/DEVELOPMENT_DESIGN/dive_{dive}.yaml'
    if not path.exists():
        return {'status': 'NO_HUMAN_FLIGHT_AUTHORITY'}
    gt = yaml.safe_load(path.read_text())
    try:
        t0 = gt['landmarks']['takeoff']
        t1 = gt['landmarks']['water_contact']
        if not (t0['state'].startswith('HUMAN') and t1['state'].startswith('HUMAN')):
            return {'status': 'NO_HUMAN_FLIGHT_AUTHORITY'}
    except KeyError:
        return {'status': 'NO_HUMAN_FLIGHT_AUTHORITY'}
    fi2pts = {f['fi'] - 1: f['pts_s'] for f in frames}
    fl = {fi: v for fi, v in anchors.items()
          if t0['timestamp_seconds'] - 0.05 <= fi2pts[fi] <= t1['timestamp_seconds'] + 0.05}
    return {'status': 'SCORED', 'flight_anchors': len(fl),
            'flight_fraction_of_anchors': len(fl) / len(anchors)}


def evaluate():
    frozen = authorities()
    v1 = json.loads((DOC / V1DOC).read_text())
    results = {}
    for dive in v1run.COHORT:
        group = _dive_group(dive)
        artifact = OUT / f'{dive}.json'
        output = json.loads(artifact.read_text())
        anchors = v1run.subject_anchors(dive, output['frame_pts'])
        assert anchors
        scored = [{**t, 'evaluation': v1run.correspondence(t, anchors)}
                  for t in output['tracks']]
        subject = [t for t in scored if t['evaluation']['is_subject']]
        recovered = [t for t in subject
                     if t['evaluation']['matched_anchor_coverage'] >= RECOVERY_COVERAGE]
        best = max(subject, key=lambda t: (t['evaluation']['matched_anchor_coverage'],
                   t['evaluation']['purity'], -t['path_rank']), default=None)
        v1dive = v1['per_dive'][dive]
        union, trax, clip, frames, pts, _anchors = union_and_raw(dive, group)
        assert abs(union - v1dive['raw_subject_union_anchor_coverage']) < 0.06, \
            (dive, union, v1dive['raw_subject_union_anchor_coverage'])
        trans = lattice_transition_recall(trax, frames, pts, anchors)
        pool_paths, pool_stats, n_pool_subj, pool_best = pool_best_subject(
            dive, group, trax, clip, pts, anchors,
            [t['track_id'] for t in output['tracks']])
        per = {
            'visible_subject_anchors': len(anchors),
            'formulation': output['lattice'].get('formulation', assoc.A0_BEAM),
            'lattice': {k: output['lattice'][k] for k in
                        ('nodes', 'gap_edges', 'overlap_edges', 'interleave_edges',
                         'decoded_paths')},
            'union_subject_coverage': union,
            'v1_union_subject_coverage': v1dive['raw_subject_union_anchor_coverage'],
            'best_v1_coverage': max(v1dive['best_raw_subject_anchor_coverage'],
                                    v1dive['best_merged_subject_anchor_coverage']),
            'lattice_transition_recall': trans,
            'decoded_pool_subject_paths': n_pool_subj,
            'pool_best_subject_coverage': pool_best[2]['matched_anchor_coverage'] if pool_best else 0.0,
            'pool_best_subject_purity': pool_best[2]['purity'] if pool_best else None,
            'pool_best_nfragments': len(pool_best[1]['tids']) if pool_best else 0,
            'retained_paths': len(scored),
            'subject_path_ranks': sorted(t['path_rank'] for t in subject),
            'best_subject_path_rank': min((t['path_rank'] for t in subject), default=None),
            'recovered': bool(recovered),
            'best_subject_coverage': best['evaluation']['matched_anchor_coverage'] if best else 0.0,
            'best_subject_purity': best['evaluation']['purity'] if best else None,
            'best_subject_path': None if best is None else {
                k: best[k] for k in ('path_rank', 'path_score', 'track_id',
                'person_track_refs', 'temporal_extent', 'trajectory_coverage',
                'longest_observation_gap_s', 'handoff_count',
                'overlap_handoff_count', 'handoff_provenance', 'procedural_events',
                'procedural_sequence', 'D0', 'D1', 'status', 'evaluation')},
            'longest_gap_s': best['longest_observation_gap_s'] if best else None,
            'observed_contamination': best['evaluation']['observed_non_subject_anchor_count'] if best else None,
            'subject_event_accuracy': subject_event_accuracy(
                dive, best if recovered else None, output),
            'flight_phase': flight_stats(dive, frames, anchors),
        }
        # perception vs association from recomputed union and pool headroom
        if union < 0.5:
            per['limitation'] = 'PERCEPTION_LIMITED'
        elif not per['recovered'] and union >= 0.75:
            per['limitation'] = 'ASSOCIATION_LIMITED'
        elif per['recovered']:
            per['limitation'] = 'RECOVERED'
        else:
            per['limitation'] = 'MIXED'
        # multi-path preservation among retained paths
        ext = [t['temporal_extent'] for t in scored]
        overlap_pairs = sum(a[0] < b[1] and b[0] < a[1]
                            for i, a in enumerate(ext) for b in ext[i + 1:])
        per['alternative_paths'] = len(scored)
        per['temporal_overlap_pairs'] = overlap_pairs
        # synchro: two retained paths overlapping in time with disjoint boxes
        synchro = False
        for i in range(len(scored)):
            for j in range(i + 1, len(scored)):
                a, b = scored[i], scored[j]
                if a['temporal_extent'][0] < b['temporal_extent'][1] and \
                   b['temporal_extent'][0] < a['temporal_extent'][1]:
                    synchro = True
        per['synchro_representable'] = synchro
        results[dive] = per
        print(dive, 'recovered', per['recovered'], 'rank', per['best_subject_path_rank'],
              'retcov', round(per['best_subject_coverage'], 3),
              'poolcov', round(per['pool_best_subject_coverage'], 3),
              'union', round(union, 3), 'trans', round(trans['transition_recall'], 3), flush=True)
    recall = sum(r['recovered'] for r in results.values())
    report = {'packet': 'DIVE_ANALYZER_ACTION_SPANNING_TRACK_ASSOCIATION_V2',
              'authorities': frozen,
              'A0': assoc.A0_BEAM,
              'A1': assoc.APP_BEAM,
              'A1_applied_dives': sorted(d for d in v1run.COHORT
                                         if results[d]['formulation'] == assoc.APP_BEAM),
              'TOP_K': assoc.TOP_K,
              'ACTION_SPANNING_SUBJECT_TRAJECTORY_RECALL': {'recovered_clips': recall,
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
              'gate': 'SUPERVISOR_REVIEW_AFTER_ACTION_SPANNING_TRACK_ASSOCIATION_V2'}
    assert authorities() == frozen
    write(DOC / 'DIVE_ANALYZER_ACTION_SPANNING_TRACK_ASSOCIATION_V2.json', report)


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
