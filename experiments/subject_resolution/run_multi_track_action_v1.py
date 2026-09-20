"""Cache-only orchestration and isolated post-inference HUMAN evaluation."""
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
import multi_track_action_v1 as action

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'runs/multi_track_action_v1'
DOC = ROOT / 'docs/science'
START = '1d49bbead2c230b44ab42c76958c24eac5fe1a35'
PROTOCOL = '95d1de59261526d423fadd3f979607fd7e3d7156'
GROUPS = {'hurdle': ['1040', '2169', '2341', '2353', '2541'],
          'cohort': ['133', '311', '676', '2387'],
          'indep': ['1304', '2204', '2223', '2526', '2583', '2839']}
CACHE_ROOT = ROOT.parent
CACHES = {
 'hurdle': CACHE_ROOT / 'diveanalyzer-cand-quality-v3/runs/hurdle_identity_v1/R5_FULLCLIP_CANDIDATES_V1.json',
 'cohort': CACHE_ROOT / 'diveanalyzer-cand-quality-v3/runs/subject_resolution/R5_FULLCLIP_CANDIDATES_COHORT_V1.json',
 'indep': CACHE_ROOT / 'diveanalyzer-independent-gt/runs/subject_resolution/R5_FULLCLIP_CANDIDATES_INDEP_V1.json'}
CACHE_SHAS = {'hurdle': '3bed1aafb3d55353372260466ae0683acc62b188d75e6ef2587d936c150e0d83',
 'cohort': 'b2f01e4116466a6ac7f48de7361c3f9d5586a0902ad3f2a68d55b5348b53403f',
 'indep': 'd945fc04001569c620dee8817bf11ad894373000437bfc6516b6b2540a5f8d8f'}
CHAIN = CACHE_ROOT / 'diveanalyzer-cand-quality-v3/runs/hurdle_identity_v1/target_chains_v1.json'
COHORT = sorted(d for group in GROUPS.values() for d in group)
MODEL_SHA = '82b420c4583f8271b1eb3429b14dadf0a1e27477249de7b6a0b9d42a788dcf25'
FROZEN_FILES = ['experiments/subject_resolution/subject_reference_acquisition_v2.py',
 'experiments/subject_resolution/phase_subject_candidate_quality_v3.py',
 'experiments/landmark_pilot/r5_tracklets_v1.py',
 'experiments/landmark_pilot/proposer_event_logic_v3_c0.py',
 'experiments/landmark_pilot/proposer_event_logic_v2_1.py']


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
    result = {'starting_head': START, 'protocol_commit': PROTOCOL, 'cohort': COHORT,
              'files': {}, 'caches': {}, 'gt': {}}
    for name in FROZEN_FILES:
        expected = hashlib.sha256(subprocess.check_output(['git', 'show', START + ':' + name], cwd=ROOT)).hexdigest()
        assert sha(ROOT / name) == expected, name
        result['files'][name] = expected
    for group, path in CACHES.items():
        actual = sha(path)
        assert actual == CACHE_SHAS[group], (group, actual)
        result['caches'][group] = {'path': str(path), 'sha256': actual}
    assert sha(CHAIN) == '11d075bed7a4967e66ddf881cbaa6529e9ca0862d86786269d1398cb194c6b15'
    result['gt']['hurdle_chains'] = sha(CHAIN)
    for suffix, prefix, expected in [('A_STANDING', 'L1A', 'd805aac2b46e52f002de2842b56bb9a1b0ced808f0862a4c559f5ffe9099a75e'),
                                    ('B_INDEPENDENT', 'L1B', 'dc958909435ad043a1284064b5dd6f85ca4b8eb365ed643289943f679c83a9df')]:
        directory = DOC / ('localization_annotations_v1/SUBJECT_GT_LEVEL_' + suffix + '_V1')
        hashes = {p.name: sha(p) for p in sorted(directory.glob(prefix + '_*.json'))}
        digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
        assert digest == expected, suffix
        result['gt'][prefix] = {'sha256': digest, 'count': len(hashes)}
    for dive in COHORT:
        path = DOC / f'pilot_annotations_v2/DEVELOPMENT_DESIGN/dive_{dive}.yaml'
        if path.exists():
            result['gt']['event_' + dive] = sha(path)
    return result


def run_inference():
    started = time.monotonic()
    frozen = authorities()
    write(OUT / 'authorities.json', frozen)
    for group, ids in GROUPS.items():
        raw = json.loads(CACHES[group].read_text())
        assert raw['model_sha256'] == MODEL_SHA
        assert (raw['floor_conf'], raw['nms_iou'], raw['imgsz'], raw['floor_cap']) == (.001, .45, 640, 200)
        for dive in ids:
            doc = raw['dives'][dive]
            # Only whitelisted detections, recorded PTS, and nominal fps cross boundary.
            result = action.infer(action.inference_view(doc['frames']), float(doc['fps']))
            result['clip_id'] = dive
            result['frame_pts'] = [f['pts_s'] for f in doc['frames']]
            result['input_proxy_sha256'] = doc.get('proxy_sha256')
            write(OUT / f'{dive}.json', result)
            print(dive, result['person_track_count'], result['merged_hypothesis_count'],
                  {k: sum(t['status'] == k for t in result['tracks']) for k in ['DIVE_LIKE','NON_DIVE','AMBIGUOUS']}, flush=True)
        del raw
    assert authorities() == frozen
    write(OUT / 'resources.json', {'runtime_s': time.monotonic() - started,
          'peak_ram_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
          'D5_inference': 0, 'new_embeddings': 0, 'training': 0, 'new_labels': 0,
          'B2_reads': 0, 'B2_writes': 0, 'media_decodes': 0})


def subject_anchors(dive, pts):
    if dive in GROUPS['hurdle']:
        chains = json.loads(CHAIN.read_text())['dives'][dive]['chain']
        anchors = {}
        for c in chains:
            if c['status'] != 'GT':
                continue
            # PTS nearest alignment, never fps multiplication. Existing chain PTS
            # are from these same proxies; reject mismatches beyond half frame.
            pos = min(range(len(pts)), key=lambda i: abs(pts[i] - c['pts_s']))
            local_dt = pts[min(pos + 1, len(pts) - 1)] - pts[max(pos - 1, 0)]
            assert abs(pts[pos] - c['pts_s']) <= max(local_dt / 2, 1e-6)
            anchors.setdefault(pos, (c['cx'], c['cy']))
        return anchors
    suffix, prefix = ('A_STANDING', 'L1A') if dive in GROUPS['cohort'] else ('B_INDEPENDENT', 'L1B')
    directory = DOC / ('localization_annotations_v1/SUBJECT_GT_LEVEL_' + suffix + '_V1')
    anchors = {}
    for p in sorted(directory.glob(f'{prefix}_{dive}_*.json')):
        a = json.loads(p.read_text())
        assert a['authority'] == 'HUMAN_REVIEWED'
        if a.get('visibility', 'visible') != 'visible':
            continue
        x1, y1, x2, y2 = a['bbox']
        anchors[a['frame_index']] = ((x1 + x2) / 2 / a['width'], (y1 + y2) / 2 / a['height'])
    return anchors


def correspondence(track, anchors):
    overlap = hits = 0
    matches = []
    for point in track['trajectory']:
        fi = point['frame_index']
        if fi not in anchors:
            continue
        overlap += 1
        cx, cy = point['bbox_cxcywh_norm'][:2]
        if math.hypot(cx - anchors[fi][0], cy - anchors[fi][1]) <= action.v3.SUPPORT_RADIUS:
            hits += 1
            matches.append(fi)
    purity = hits / overlap if overlap else None
    return {'overlapping_anchors': overlap, 'matching_anchors': hits,
            'purity': purity, 'matched_anchor_coverage': hits / len(anchors),
            'is_subject': hits >= 2 and purity >= .75,
            'observed_non_subject_anchor_count': overlap - hits,
            'matched_frames': matches}


def evaluate():
    frozen = authorities()
    results = {}
    for dive in COHORT:
        artifact = OUT / f'{dive}.json'
        output = json.loads(artifact.read_text())
        anchors = subject_anchors(dive, output['frame_pts'])
        assert anchors
        scored = [{**t, 'evaluation': correspondence(t, anchors)} for t in output['tracks']]
        subject = [t for t in scored if t['evaluation']['is_subject']]
        per_form = {}
        for form in ['D0', 'D1']:
            positives = [t for t in scored if t[form] == 'DIVE_LIKE']
            retained = [t for t in positives if t['evaluation']['is_subject']]
            per_form[form] = {'DIVE_LIKE': len(positives),
                'NON_DIVE': sum(t[form] == 'NON_DIVE' for t in scored),
                'AMBIGUOUS': sum(t[form] == 'AMBIGUOUS' for t in scored),
                'subject_retained': bool(retained),
                'subject_rank': min((t['rank'] for t in retained), default=None),
                'subject_track_ids': [t['track_id'] for t in retained],
                'unmatched_positive_hypotheses': len(positives) - len(retained),
                'strong_subject_retained': any(t['evaluation']['matched_anchor_coverage'] >= .75 for t in retained)}
        valid = [t for t in subject if t['D1'] == 'DIVE_LIKE']
        best = max(valid or subject, key=lambda t: (t['evaluation']['matched_anchor_coverage'],
                   t['evaluation']['purity'], -t['rank']), default=None)
        raw_matches = [t for t in scored if len(t['person_track_refs']) == 1 and t['evaluation']['matching_anchors'] > 0]
        merged_matches = [t for t in scored if len(t['person_track_refs']) > 1 and t['evaluation']['matching_anchors'] > 0]
        event_eval = {'status': 'NO_HUMAN_EVENT_AUTHORITY'}
        event_path = DOC / f'pilot_annotations_v2/DEVELOPMENT_DESIGN/dive_{dive}.yaml'
        if event_path.exists():
            event_gt = yaml.safe_load(event_path.read_text())
            assert event_gt['split'] == 'DEVELOPMENT_DESIGN'
            assert output['input_proxy_sha256'] == event_gt['input_media_sha256'], 'Event timebase media mismatch'
            event_eval = {'status': 'SCORED' if valid else 'NO_RETAINED_SUBJECT_DIVETRACK',
                          'authority': str(event_path.relative_to(ROOT)), 'errors': {}}
            for name in ['takeoff', 'apex', 'water_contact']:
                gt = event_gt['landmarks'][name]
                if not gt['state'].startswith('HUMAN'):
                    event_eval['errors'][name] = {'status': gt['state'], 'signed_error_s': None, 'absolute_error_s': None}
                    continue
                pred = best['procedural_events'][name] if valid else None
                event_eval['errors'][name] = {'prediction_pts_s': pred,
                    'human_timestamp_s': gt['timestamp_seconds'],
                    'human_frame_pts_s': gt.get('frame_pts_seconds'),
                    'signed_error_s': pred - gt['timestamp_seconds'] if pred is not None else None,
                    'absolute_error_s': abs(pred - gt['timestamp_seconds']) if pred is not None else None}
        compact = [{k: t[k] for k in ('track_id', 'rank', 'person_track_refs', 'temporal_extent',
                     'status', 'D0', 'D1', 'procedural_events', 'procedural_sequence', 'evaluation',
                     'trajectory_coverage', 'longest_observation_gap_s')} for t in scored
                   if t['D0'] == 'DIVE_LIKE' or t['evaluation']['is_subject']]
        best_summary = None if best is None else {k: best[k] for k in ('track_id','rank','status','evaluation',
              'person_track_refs','trajectory_coverage','longest_observation_gap_s','procedural_events')}
        results[dive] = {'PersonTracks': output['person_track_count'],
             'merged_hypotheses': output['merged_hypothesis_count'], **per_form,
             'visible_subject_anchors': len(anchors), 'raw_subject_fragments': len(raw_matches),
             'merged_action_fragments_touching_subject': len(merged_matches),
             'raw_subject_union_anchor_coverage': len({i for t in raw_matches for i in t['evaluation']['matched_frames']}) / len(anchors),
             'best_raw_subject_anchor_coverage': max((t['evaluation']['matched_anchor_coverage'] for t in raw_matches if t['evaluation']['is_subject']), default=0.),
             'best_merged_subject_anchor_coverage': max((t['evaluation']['matched_anchor_coverage'] for t in merged_matches if t['evaluation']['is_subject']), default=0.),
             'supported_person_tracks': sum(len(t['person_track_refs']) == 1 and t['quality']['support_count'] > 0 for t in scored),
             'merged_subject_correspondence_count': sum(t['evaluation']['is_subject'] for t in merged_matches),
             'positive_overlap_pairs': sum(a['temporal_extent'][0] < b['temporal_extent'][1] and b['temporal_extent'][0] < a['temporal_extent'][1]
                  for i,a in enumerate(scored) if a['D1'] == 'DIVE_LIKE'
                  for b in scored[i+1:] if b['D1'] == 'DIVE_LIKE'),
             'best_subject_hypothesis': best_summary, 'subject_event_accuracy': event_eval,
             'identity_switch_contamination': 'ONLY_ANCHOR_MISMATCH_OBSERVABLE; BETWEEN_ANCHORS_UNVERIFIED',
             'other_legitimate_diver_tracks_retained': 'UNVERIFIED_NO_EXHAUSTIVE_HUMAN_ACTION_AUTHORITY',
             'false_DiveTrack_count': None,
             'false_DiveTrack_count_reason': 'Non-subject does not imply non-dive; no exhaustive other-action labels',
             'false_hypothesis_upper_bound': per_form['D1']['unmatched_positive_hypotheses'],
             'product_state': output['product_state'], 'ambiguity_state': output['ambiguity_state'],
             'inspectable_tracks': compact, 'inference_artifact_sha256': sha(artifact)}
        print(dive, 'recall', per_form['D1']['subject_retained'], 'rank', per_form['D1']['subject_rank'], flush=True)
    report = {'packet': 'DIVE_ANALYZER_MULTI_TRACK_DIVE_ACTION_V1', 'authorities': frozen,
              'primary_formulation': 'D1', 'D1_QUALITY_RESULTS': 'EXECUTED',
              'KNOWN_DIVE_TRACK_RECALL': {'correct_clips': sum(r['D1']['subject_retained'] for r in results.values()), 'evaluable_clips': len(results)},
              'D0_recall': sum(r['D0']['subject_retained'] for r in results.values()),
              'strong_coverage_recall': sum(r['D1']['strong_subject_retained'] for r in results.values()),
              'per_dive': results, 'resources': json.loads((OUT / 'resources.json').read_text()),
              'identity_line': 'FROZEN_DEFERRED', 'reference_acquisition': 'REFERENCE_ACQUISITION_DEFERRED',
              'scientific_authorities_mutated': 'NO', 'media_backbone_mutated': 'NO',
              'V1_STATUS': 'MULTI_TRACK_DIVE_ACTION_V1_NOT_READY',
              'NEXT_RESEARCH_DECISION': 'IMPROVE_TRACK_ASSOCIATION_NEXT',
              'SYNCHRO_REPRESENTATION': 'SYNCHRO_REPRESENTABLE',
              'OVERLAY_READINESS': 'TRACK_STABILITY_INSUFFICIENT_FOR_OVERLAY',
              'current_true_bottleneck': 'Action-spanning trajectory association; complete fallback event sequences do not establish a real dive. No subject hypothesis has >=75% anchor coverage and D1 eligibility.',
              'metric_caveat': '1/15 anchor-correspondence recall is not proof of a correctly isolated action: the sole retained track covers 23% of subject anchors and has early event errors. Strong-coverage recall is 0/15.',
              'protected_data': {'524':'AUTHORITY_CONFLICT_EXCLUDED','2555':'SCREEN_RECORDING_STRESS_CASE',
                 'Paris':'EXTERNAL_ONLY','INTERNAL_EVAL':'NOT_ACCESSED','FINAL_HOLDOUT':'NOT_ACCESSED'},
              'gate':'SUPERVISOR_REVIEW_AFTER_MULTI_TRACK_DIVE_ACTION_V1'}
    assert authorities() == frozen
    write(DOC / 'DIVE_ANALYZER_MULTI_TRACK_DIVE_ACTION_V1.json', report)


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
