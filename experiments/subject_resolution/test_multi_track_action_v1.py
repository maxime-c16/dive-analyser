"""Packet contracts, genuine boundary/association behavior, artifact replay."""
import copy
import inspect
import json
from pathlib import Path

import pytest
import multi_track_action_v1 as m
import run_multi_track_action_v1 as run


def track(tid, rows):
    return m.r5.Tracklet(tid, sorted(rows), {i: m.r5.Cand(x, y, .1, .2, .8) for i, (x,y) in rows.items()})


def test_canonical_cohort_and_protected_firewall():
    assert set(run.COHORT) == {'1040','2169','2341','2353','2541','133','311','676','2387','1304','2204','2223','2526','2583','2839'}
    assert len(run.COHORT) == 15
    assert not {'524','2555'} & set(run.COHORT)
    assert all('DEVELOPMENT_DESIGN' in str(run.DOC / f'pilot_annotations_v2/DEVELOPMENT_DESIGN/dive_{d}.yaml') for d in run.COHORT)


def test_frozen_d5_v3_event_logic_gt_identities():
    a = run.authorities()
    assert a['files']['experiments/subject_resolution/phase_subject_candidate_quality_v3.py'] == '9fc8dcbc9d9040cc7c216bcff45a2995d08322043da8b6ff703eeed4b9694fcb'
    assert a['files']['experiments/landmark_pilot/proposer_event_logic_v3_c0.py'] == '9c5077191699416e0148f868bd0d2fc6f19fd5a823102eeb1bdd5e0f129a8438'
    assert a['gt']['L1A']['count'] == 63 and a['gt']['L1B']['count'] == 180


def test_no_identity_gt_training_or_media_in_inference():
    code = inspect.getsource(m)
    for forbidden in ['diver_id', 'subject_conditioned_identity_l0', 'load_anchors',
                      'gt_eval_only', 'torch', 'VideoCapture', 'boto3', '.fit(', 'read_text', 'open(']:
        assert forbidden not in code
    assert list(inspect.signature(m.infer).parameters) == ['frames', 'fps']


def test_metadata_cannot_cross_boundary():
    clean = [{'fi': i + 1, 'pts_s': i / 10, 'c': [{'cx': .2, 'cy': .2, 'bw': .1, 'bh': .2, 'conf': .8}]} for i in range(12)]
    poisoned = copy.deepcopy(clean)
    for f in poisoned:
        f.update(diver_id=123, gt_eval_only={'takeoff': 8}, family='HURDLE')
        f['c'][0]['subject_gt'] = True
    assert m.infer(clean, 10) == m.infer(poisoned, 10)


def test_overlapping_tracks_preserved():
    frames = [{'fi': i + 1, 'pts_s': i / 30, 'c': [dict(cx=x, cy=.2, bw=.1, bh=.2, conf=.8) for x in [.2,.8]]} for i in range(36)]
    result = m.infer(frames, 30)
    assert result['person_track_count'] == 2
    assert len(result['tracks']) == 2
    assert result['tracks'][0]['temporal_extent'] == result['tracks'][1]['temporal_extent']
    assert result['tracks'][0]['track_id'] != result['tracks'][1]['track_id']


def test_fragment_association_determinism_and_pts():
    pts = [0., .1, .2, .3, .4, .5]
    a = track(1, {0:(.2,.2),1:(.21,.2)})
    b = track(2, {3:(.23,.2),4:(.24,.2)})
    far = track(3, {3:(.8,.2),4:(.81,.2)})
    merged, edges = m.associate([a,b,far], pts)
    assert len(merged) == 1 and merged[0][1] == [1,2]
    assert edges == m.associate([far,b,a], pts)[1]
    assert not m.associate([a,b], [0.,.1,.2,1.,1.1,1.2])[0]
    assert a.starts == [0,1] and b.starts == [3,4]


def test_overlap_never_merged():
    a = track(1, {0:(.2,.2),1:(.21,.2),2:(.22,.2)})
    b = track(2, {1:(.21,.2),2:(.22,.2),3:(.23,.2)})
    assert not m.associate([a,b], [0.,.1,.2,.3])[0]


def test_two_simultaneous_divetracks_with_real_frozen_event_logic():
    frames = []
    for i in range(80):
        t = i / 30
        u = max(0., t - 1.)
        y = .3 - .5 * u + .5 * u * u
        frames.append(dict(fi=i+1, pts_s=t, c=[dict(cx=x,cy=y,bw=.1,bh=.2,conf=.8) for x in [.2,.8]]))
    result = m.infer(frames, 30)
    positives = [t for t in result['tracks'] if t['status'] == 'DIVE_LIKE']
    assert len(positives) == 2
    assert result['product_state'] == 'MULTIPLE_DIVE_TRACKS_FOUND'
    assert positives[0]['temporal_extent'] == positives[1]['temporal_extent']
    assert positives[0]['person_track_refs'] != positives[1]['person_track_refs']


def test_invalid_pts_rejected():
    with pytest.raises(ValueError):
        m.infer([{'fi': 1, 'pts_s': 0, 'c': []}, {'fi': 2, 'pts_s': 0, 'c': []}], 30)


def test_d0_quality_independence_d1_quality_gate():
    frames = [dict(fi=i+1, pts_s=i/30, c=[dict(cx=.2,cy=.2,bw=.1,bh=.2,conf=.001)]) for i in range(36)]
    low = m.infer(frames,30)['tracks'][0]
    for f in frames:
        f['c'][0]['conf'] = .8
    high = m.infer(frames,30)['tracks'][0]
    assert low['D0'] == high['D0'] == 'NON_DIVE'
    assert low['D1'] == 'AMBIGUOUS' and high['D1'] == 'NON_DIVE'


def test_known_subject_recall_semantics():
    row = {'trajectory':[{'frame_index':i,'bbox_cxcywh_norm':[.2,.3,.1,.2]} for i in range(4)]}
    gt = {i:(.2,.3) for i in range(4)}
    assert run.correspondence(row, gt)['is_subject']
    gt.update({0:(.9,.9),1:(.9,.9)})
    assert not run.correspondence(row, gt)['is_subject']
    assert run.correspondence(row, {0:(.2,.3)})['is_subject'] is False


def test_artifact_preservation_recall_and_frozen_replay():
    report = json.loads((run.DOC / 'DIVE_ANALYZER_MULTI_TRACK_DIVE_ACTION_V1.json').read_text())
    assert set(report['per_dive']) == set(run.COHORT)
    assert report['KNOWN_DIVE_TRACK_RECALL']['correct_clips'] == sum(r['D1']['subject_retained'] for r in report['per_dive'].values())
    before = copy.deepcopy(m.el.PARAMS_V3C0)
    for d in run.COHORT:
        output = json.loads((run.OUT / f'{d}.json').read_text())
        rows = output['tracks']
        assert sum(len(r['person_track_refs']) == 1 for r in rows) == output['person_track_count']
        assert len({r['track_id'] for r in rows}) == len(rows)
        assert all(r['status'] in {'DIVE_LIKE','NON_DIVE','AMBIGUOUS'} for r in rows)
        for r in rows:
            if r['status'] != 'DIVE_LIKE':
                continue
            assert r['procedural_sequence'] == 'COMPLETE_DIVE_SEQUENCE'
            pts = [t for t in output['frame_pts'] if r['temporal_extent'][0] <= t <= r['temporal_extent'][1]]
            points = {p['pts_s']:p for p in r['trajectory']}
            ys = [points[t]['bbox_cxcywh_norm'][1] if t in points else None for t in pts]
            conf = [points[t]['confidence'] if t in points else 0. for t in pts]
            events = m.el.propose_events_v3c0(ys, pts, conf, '')
            assert r['procedural_events'] == {k:events[k+'_t'] for k in r['procedural_events']}
    assert before == m.el.PARAMS_V3C0


def test_full_clip_determinism():
    cache = json.loads(run.CACHES['hurdle'].read_text())['dives']['1040']
    replay = m.infer(cache['frames'], cache['fps'])
    original = json.loads((run.OUT / '1040.json').read_text())
    assert all(replay[k] == original[k] for k in replay)


def test_zero_training_b2_and_resource_budget():
    resources = json.loads((run.OUT / 'resources.json').read_text())
    assert all(resources[k] == 0 for k in ['D5_inference','new_embeddings','training','new_labels','B2_reads','B2_writes','media_decodes'])
    assert resources['peak_ram_bytes'] < 20_000_000_000
