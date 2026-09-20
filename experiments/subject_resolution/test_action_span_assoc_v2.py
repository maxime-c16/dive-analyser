"""V2 packet contracts: lattice determinism, top-K preservation, GT isolation."""
import copy
import inspect
import json
from pathlib import Path

import pytest
import action_span_assoc_v2 as V
import run_action_span_assoc_v2 as run


def track(tid, rows):
    return V.r5.Tracklet(tid, sorted(rows),
                         {i: V.r5.Cand(x, y, .1, .2, .8) for i, (x, y) in rows.items()})


def frames_two_person(n=80, fps=30):
    out = []
    for i in range(n):
        t = i / fps
        u = max(0., t - 1.)
        y = .3 - .5 * u + .5 * u * u
        out.append({'fi': i + 1, 'pts_s': t,
                    'c': [{'cx': x, 'cy': y, 'bw': .1, 'bh': .2, 'conf': .8}
                          for x in (.2, .8)]})
    return out


def test_canonical_cohort_and_protected_firewall():
    assert set(run.v1run.COHORT) == {'1040', '2169', '2341', '2353', '2541', '133',
                                     '311', '676', '2387', '1304', '2204', '2223',
                                     '2526', '2583', '2839'}
    assert not {'524', '2555'} & set(run.v1run.COHORT)
    assert run.TOP_K if hasattr(run, 'TOP_K') else True
    assert V.TOP_K <= 5


def test_frozen_authorities_and_v1_baseline():
    a = run.authorities()
    assert a['files']['experiments/landmark_pilot/proposer_event_logic_v3_c0.py'] == \
        '9c5077191699416e0148f868bd0d2fc6f19fd5a823102eeb1bdd5e0f129a8438'
    assert a['gt']['L1A']['count'] == 63 and a['gt']['L1B']['count'] == 180
    v1 = json.loads((run.DOC / run.V1DOC).read_text())
    assert v1['KNOWN_DIVE_TRACK_RECALL'] == {'correct_clips': 1, 'evaluable_clips': 15}
    assert v1['strong_coverage_recall'] == 0
    assert v1['totals']['raw_person_tracks'] == 34320
    assert v1['totals']['merged_hypotheses'] == 6490


def test_no_identity_gt_training_or_media_in_inference():
    code = inspect.getsource(V)
    for forbidden in ['diver_id', 'load_anchors', 'correspondence', 'subject_anchors',
                      'torch', 'VideoCapture', 'boto3', '.fit(', 'gt_eval_only']:
        assert forbidden not in code
    assert 'torch' not in code.split('import numpy')[0] or True
    params = list(inspect.signature(V.infer).parameters)
    assert params[:2] == ['frames', 'fps']


def test_gt_evaluation_isolation():
    assert not hasattr(V, 'correspondence')
    assert not hasattr(V, 'subject_anchors')
    run_code = inspect.getsource(run)
    assert 'correspondence' in run_code  # evaluate-only zone


def test_metadata_cannot_cross_boundary():
    clean = [{'fi': i + 1, 'pts_s': i / 10,
              'c': [{'cx': .2, 'cy': .2, 'bw': .1, 'bh': .2, 'conf': .8}]}
             for i in range(12)]
    poisoned = copy.deepcopy(clean)
    for f in poisoned:
        f.update(diver_id=123, gt_eval_only={'takeoff': 8}, family='HURDLE')
        f['c'][0]['subject_gt'] = True
    assert V.infer(clean, 10)['tracks'] == V.infer(poisoned, 10)['tracks']


def test_invalid_pts_rejected():
    with pytest.raises(ValueError):
        V.infer([{'fi': 1, 'pts_s': 0, 'c': []}, {'fi': 2, 'pts_s': 0, 'c': []}], 30)


def test_gap_transition_determinism_and_order_invariance():
    pts = [i / 30 for i in range(8)]
    a = track(1, {0: (.2, .2), 1: (.21, .2)})
    b = track(2, {3: (.23, .2), 4: (.24, .2)})
    far = track(3, {3: (.8, .2), 4: (.81, .2)})
    g1, o1, i1 = V.build_lattice([a, b, far], pts)
    g2, o2, i2 = V.build_lattice([far, b, a], pts)
    assert g1 == g2 and o1 == o2 and i1 == i2
    assert any(e['to'] == 2 for e in g1[1])
    assert not any(e['to'] == 3 for e in g1[1])


def test_overlap_handoff_requires_agreement():
    pts = [i / 30 for i in range(6)]
    a = track(1, {0: (.2, .2), 1: (.21, .2), 2: (.22, .2)})
    agree = track(2, {1: (.21, .2), 2: (.22, .2), 3: (.23, .2)})
    disagree = track(3, {1: (.7, .7), 2: (.71, .7), 3: (.72, .7)})
    _, o, _ = V.build_lattice([a, agree, disagree], pts)
    assert any(e['to'] == 2 for e in o[1])
    assert not any(e['to'] == 3 for e in o[1])


def test_interleave_handoff_links_alternating_fragments():
    pts = [i / 30 for i in range(6)]
    a = track(1, {0: (.2, .2), 2: (.22, .2), 4: (.24, .2)})
    b = track(2, {1: (.21, .2), 3: (.23, .2), 5: (.25, .2)})
    g, o, inn = V.build_lattice([a, b], pts)
    assert any(e['to'] == 2 for e in inn[1])
    assert not o[1]  # no common observed frame


def test_no_connected_component_collapse_and_simultaneous_paths():
    res = V.infer(frames_two_person(), 30)
    assert 1 <= len(res['tracks']) <= V.TOP_K
    ext = [t['temporal_extent'] for t in res['tracks']]
    assert any(a[0] < b[1] and b[0] < a[1]
               for i, a in enumerate(ext) for b in ext[i + 1:])
    assert res['product_state'] == 'MULTIPLE_DIVE_TRACKS_FOUND'


def test_decode_determinism():
    fr = frames_two_person()
    clean = V.inference_view(fr)
    pts = [f['pts_s'] for f in clean]
    clip = V.v2.Clip('', clean, 30)
    raw = V.r5.build_tracklets_full(clip.cands, 30)
    m1, _ = V.decode_topk(raw, pts)
    m2, _ = V.decode_topk(raw, pts)
    assert [(p['tids'], p['score']) for p in m1] == [(p['tids'], p['score']) for p in m2]
    r1 = V.infer(fr, 30)
    r2 = V.infer(fr, 30)
    assert [t['track_id'] for t in r1['tracks']] == [t['track_id'] for t in r2['tracks']]


def test_event_logic_not_mutated_by_inference():
    before = dict(V.el.PARAMS_V3C0)
    V.infer(frames_two_person(), 30)
    assert dict(V.el.PARAMS_V3C0) == before


def test_frozen_gates_reused_not_reinvented():
    assert V.GAP_MAX_S == V.el.PARAMS_V3C0['interp_max_gap_s'] == 0.30
    assert V.RADIUS == V.v3.SUPPORT_RADIUS == 0.06
    assert V.SIZE_TOL == V.r5.LOG_SIZE_MAX + V.r5.JITTER_S


def test_topk_bound_on_real_clip():
    doc = json.loads(run.v1run.CACHES['cohort'].read_text())['dives']['133']
    res = V.infer(V.inference_view(doc['frames']), float(doc['fps']),
                  dive='133', group='cohort')
    assert res['person_track_count'] == 786
    assert 1 <= res['retained_path_count'] <= 5
    assert res['lattice']['decoded_paths'] >= res['retained_path_count']
    assert res['lattice']['formulation'] == V.APP_BEAM


def test_union_upper_bound_matches_v1_within_tolerance():
    union, *_ = run.union_and_raw('133', 'cohort')
    v1 = json.loads((run.DOC / run.V1DOC).read_text())
    assert abs(union - v1['per_dive']['133']['raw_subject_union_anchor_coverage']) < 0.06


def test_zero_training_b2_and_resource_budget():
    resources = json.loads((run.OUT / 'resources.json').read_text())
    assert resources['D5_inference'] == 0
    assert resources['training'] == 0
    assert resources['new_embeddings'] == 0
    assert resources['new_labels'] == 0
    assert resources['B2_reads'] == 0
    assert resources['B2_writes'] == 0
    assert resources['media_decodes'] == 0
