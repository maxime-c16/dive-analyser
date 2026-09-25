"""V3 packet contracts: lattice determinism, NULL mechanics, GT isolation."""
import hashlib
import inspect
import json
from pathlib import Path

import pytest
import flight_anchored_traj_v3 as F
import run_flight_anchored_traj_v3 as run


def arc_frames(n=90, fps=30, x0=0.5, excursion=0.35, gap=None):
    """Single arcing person (takeoff-high to water-low) + static crowd."""
    out = []
    for i in range(n):
        if gap and gap[0] <= i <= gap[1]:
            c = []
        else:
            t = i / fps
            u = t / (n / fps)
            y = 0.25 + excursion * u * u
            c = [{'cx': x0 + 0.05 * u, 'cy': y, 'bw': .08, 'bh': .12,
                  'conf': .5}]
        c += [{'cx': .15, 'cy': .35, 'bw': .1, 'bh': .15, 'conf': .9},
              {'cx': .85, 'cy': .40, 'bw': .1, 'bh': .15, 'conf': .85}]
        out.append({'fi': i + 1, 'pts_s': i / fps, 'c': c})
    return out


def two_arc_frames(n=90, fps=30):
    out = []
    for i in range(n):
        t = i / fps
        u = t / (n / fps)
        y = 0.25 + 0.35 * u * u
        c = [{'cx': 0.3 + 0.05 * u, 'cy': y, 'bw': .08, 'bh': .12,
              'conf': .5},
             {'cx': 0.7 - 0.05 * u, 'cy': y, 'bw': .08, 'bh': .12,
              'conf': .48},
             {'cx': .5, 'cy': .35, 'bw': .1, 'bh': .15, 'conf': .9}]
        out.append({'fi': i + 1, 'pts_s': i / fps, 'c': c})
    return out


def test_canonical_cohort_and_protected_firewall():
    assert set(run.v1run.COHORT) == {'1040', '2169', '2341', '2353', '2541', '133',
                                     '311', '676', '2387', '1304', '2204', '2223',
                                     '2526', '2583', '2839'}
    assert not {'524', '2555'} & set(run.v1run.COHORT)
    assert F.FINAL_TOP_K <= 5
    assert F.FINAL_TOP_K >= 1


def test_frozen_authorities():
    a = run.authorities()
    assert a['files']['experiments/landmark_pilot/proposer_event_logic_v3_c0.py'] == \
        '9c5077191699416e0148f868bd0d2fc6f19fd5a823102eeb1bdd5e0f129a8438'
    assert a['files']['experiments/subject_resolution/phase_subject_candidate_quality_v3.py'] == \
        '9fc8dcbc9d9040cc7c216bcff45a2995d08322043da8b6ff703eeed4b9694fcb'
    assert a['gt']['L1A']['count'] == 63 and a['gt']['L1B']['count'] == 180
    v1 = json.loads((run.DOC / run.V1DOC).read_text())
    assert v1['KNOWN_DIVE_TRACK_RECALL'] == {'correct_clips': 1, 'evaluable_clips': 15}
    assert run.v1run.MODEL_SHA == '82b420c4583f8271b1eb3429b14dadf0a1e27477249de7b6a0b9d42a788dcf25'


def test_no_identity_gt_appearance_training_or_media_in_inference():
    code = inspect.getsource(F)
    for forbidden in ['diver_id', 'subject_anchors', 'correspondence',
                      'load_anchors', 'landmarks', 'takeoff', 'water_contact',
                      'torch', 'cosine', 'embedding', 'osnet', 'VideoCapture',
                      'boto3', '.fit(', 'yaml']:
        assert forbidden not in code, forbidden
    params = list(inspect.signature(F.infer).parameters)
    assert params[:2] == ['frames', 'fps']


def test_no_event_logic_in_core_selection():
    code = inspect.getsource(F)
    # Event Logic replay lives only in _describe_extended (post-freeze output)
    assert code.count('propose_events_v3c0') == 0
    assert 'el.' not in code


def test_pts_authority():
    bad = arc_frames()
    bad[5], bad[6] = bad[6], bad[5]  # break strictly increasing PTS
    with pytest.raises(ValueError):
        F.infer(bad, 30.0)
    bad2 = arc_frames()
    bad2[3]['fi'] = 99  # break sequential frame cache
    with pytest.raises(ValueError):
        F.infer(bad2, 30.0)


def test_flight_decoder_determinism():
    frames = arc_frames()
    h = lambda: hashlib.sha256(
        json.dumps(F.infer(frames, 30.0)['tracks'], sort_keys=True).encode()
    ).hexdigest()
    assert h() == h()


def test_null_state_bridges_bounded_gap_deterministically():
    frames = arc_frames(gap=(40, 44))  # 5 missing frames @30fps = 0.167s
    out = F.infer(frames, 30.0)
    assert out['retained_path_count'] >= 1
    assert out['tracks'][0]['trajectory_coverage'] < 1.0
    h = lambda: hashlib.sha256(
        json.dumps(F.infer(frames, 30.0)['tracks'], sort_keys=True).encode()).hexdigest()
    assert h() == h()
    # NULL cost is preregistered and positive
    assert F.NULL_COST > 0
    assert F.NULL_MAX_S == pytest.approx(0.30)


def test_top_k_preservation_and_diversity():
    out = F.infer(two_arc_frames(), 30.0)
    assert 1 <= out['retained_path_count'] <= 5
    ids = [t['path_id'] for t in out['tracks']]
    assert len(set(ids)) == len(ids)
    ranks = [t['path_rank'] for t in out['tracks']]
    assert ranks == sorted(ranks)


def test_simultaneous_path_representation():
    out = F.infer(two_arc_frames(), 30.0)
    assert out['retained_path_count'] >= 2
    # two retained paths overlap in time with disjoint boxes
    a, b = out['tracks'][0], out['tracks'][1]
    assert a['temporal_extent'][0] < b['temporal_extent'][1] and \
        b['temporal_extent'][0] < a['temporal_extent'][1]
    am = {p['frame_index']: p['bbox_cxcywh_norm'][:2] for p in a['trajectory']}
    bm = {p['frame_index']: p['bbox_cxcywh_norm'][:2] for p in b['trajectory']}
    common = set(am) & set(bm)
    assert common
    import math
    assert any(math.hypot(am[i][0] - bm[i][0], am[i][1] - bm[i][1]) > F.RADIUS
               for i in common)


def test_protocol_constants_frozen_in_doc():
    proto = (run.DOC / run.PROTOCOL_DOC).read_text()
    assert F.F3_VERSION in proto
    for k, v in F.PROTOCOL_CONSTANTS.items():
        if k in ('F3_VERSION', 'reused_frozen'):
            continue
        assert repr(v) in proto, k


def test_zero_training_b2_and_resource_budget():
    r = json.loads((run.OUT / 'resources.json').read_text())
    assert r['D5_inference'] == 0 and r['new_embeddings'] == 0
    assert r['training'] == 0 and r['new_labels'] == 0
    assert r['B2_reads'] == 0 and r['B2_writes'] == 0
    assert r['peak_ram_bytes'] < 20 * 1024 ** 3


def test_event_logic_frozen_identity():
    assert run.sha(run.ROOT / 'experiments/landmark_pilot/proposer_event_logic_v3_c0.py') == \
        '9c5077191699416e0148f868bd0d2fc6f19fd5a823102eeb1bdd5e0f129a8438'
