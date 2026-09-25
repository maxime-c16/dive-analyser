"""Required tests for DIVE_ANALYZER_FLIGHT_PATH_CANDIDATE_RECALL_AUDIT_V1."""
import copy
import hashlib
import inspect
import json
import math
import random
import subprocess
from pathlib import Path

import numpy as np
import pytest

import audit_flight_path_recall_v1 as au
import flight_anchored_traj_v3 as f3
import run_multi_track_action_v1 as v1run

ROOT = au.ROOT
REPORT = ROOT / 'docs/science/DIVE_ANALYZER_FLIGHT_PATH_CANDIDATE_RECALL_AUDIT_V1.json'


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------- authority
def test_canonical_authority_reconciliation():
    for c in ('509f4a925cad01e492bafa551c030e63069bd0cb',   # V2 science
              'd3ab6c43acf4971ab914547f0dd373f097771b0a',   # V2 canonical merge
              au.V3_PROTOCOL_COMMIT, au.V3_SCIENCE_COMMIT,
              'f043f6382defdda5acecfe8db66da7305c175d98',   # V3 canonical merge
              '8964f7d1258d5160c0f42e6db80521a12a148747'):  # V1 merge / stale mirror
        subprocess.check_call(['git', 'merge-base', '--is-ancestor', c, 'HEAD'], cwd=ROOT)


def test_protocol_hash_identity():
    for name in ('experiments/subject_resolution/flight_anchored_traj_v3.py',
                 'experiments/subject_resolution/run_flight_anchored_traj_v3.py',
                 'docs/science/FLIGHT_ANCHORED_TRAJECTORY_V3_PROTOCOL.md'):
        frozen = subprocess.check_output(['git', 'show', f'{au.V3_SCIENCE_COMMIT}:{name}'], cwd=ROOT)
        assert sha_bytes(frozen) == sha_bytes((ROOT / name).read_bytes()), name
    proto = (ROOT / 'docs/science/FLIGHT_ANCHORED_TRAJECTORY_V3_PROTOCOL.md').read_text()
    for k, v in f3.PROTOCOL_CONSTANTS.items():
        if k != 'reused_frozen':
            assert repr(v) in proto, k


def test_d5_frozen_identity():
    for group, path in v1run.CACHES.items():
        h = hashlib.sha256(path.read_bytes()).hexdigest()
        assert h == v1run.CACHE_SHAS[group]
    assert v1run.MODEL_SHA.startswith('82b420c4')


def test_event_logic_frozen_identity():
    name = 'experiments/landmark_pilot/proposer_event_logic_v3_c0.py'
    frozen = subprocess.check_output(['git', 'show', f'{v1run.START}:{name}'], cwd=ROOT)
    assert sha_bytes(frozen) == sha_bytes((ROOT / name).read_bytes())
    assert sha_bytes(frozen).startswith('9c507719')


# ---------------------------------------------------------------- GT boundary
GT_TOKENS = ('anchor', 'subject_anchors', 'flight_window', 'yaml', 'landmarks',
             'takeoff', 'water_contact', 'L1A', 'L1B', 'CHAIN', 'HURDLE_SEEDS',
             'strict_human', 'correspondence', 'diver_id')


def test_gt_absent_from_capture():
    src = inspect.getsource(au.capture)
    for tok in GT_TOKENS:
        assert tok not in src, tok


def test_event_gt_absent_from_inference():
    src = inspect.getsource(f3)
    for tok in ('yaml', 'landmarks', 'pilot_annotations', 'subject_anchors', 'timestamp_seconds'):
        assert tok not in src, tok


def test_capture_precedes_gt_in_audit_dive():
    src = inspect.getsource(au.audit_dive)
    assert src.index('capture(frames, fps)') < src.index('subject_anchors')
    assert src.index('capture(frames, fps)') < src.index('flight_window')
    assert src.index('capture(frames, fps)') < src.index('strict_human_anchors')


# ---------------------------------------------------------------- synthetic lattice
def synth_frames(n=40, seed=0, movers=2, statics=6):
    rng = random.Random(seed)
    frames = []
    traj = [(0.2 + 0.1 * k, 0.3) for k in range(movers)]
    for f in range(n):
        c = []
        for k in range(statics):
            c.append({'cx': 0.1 + 0.12 * k + rng.uniform(-.003, .003), 'cy': 0.8 + rng.uniform(-.003, .003),
                      'bw': .05, 'bh': .1, 'conf': .5 + .05 * k})
        for k in range(movers):
            x0, y0 = traj[k]
            t = f / 30.0
            if rng.random() < 0.85:
                c.append({'cx': x0 + 0.2 * t, 'cy': y0 - 0.6 * t + 0.9 * t * t,
                          'bw': .05, 'bh': .09, 'conf': .3 + .1 * k})
        frames.append({'fi': f + 1, 'pts_s': f / 30.0, 'c': c})
    return frames


def lattice_of(frames):
    clean = f3.inference_view(frames)
    pts = [f['pts_s'] for f in clean]
    _, off = f3.compute_flow(clean, pts)
    kept, _ = f3.build_frame_lattice(clean, off)
    return clean, pts, kept, f3._frame_arrays(kept)


def mini_beam(kept, kept_arr, pts, s):
    """Re-implementation of one V3 start using au.gated (full successor set)
    truncated to MAX_SUCC_PER_PATH + NULL + frozen _prune_dual."""
    n = len(pts)
    live = []
    seeded = set()
    for j in range(min(f3.SEED_TOP, len(kept[s]))):
        live.append(f3._Path([(s, j)], kept[s][j][7], kept[s][j][8], 0.0, 0.0, -f3.W_CONF_CONT * kept[s][j][5]))
        seeded.add(kept[s][j][0])
    movers = sorted((kept[s][j][6], j) for j in range(len(kept[s]))
                    if kept[s][j][6] is not None and kept[s][j][0] not in seeded)
    for _, j in movers[:f3.SEED_MOVERS]:
        live.append(f3._Path([(s, j)], kept[s][j][7], kept[s][j][8], 0.0, 0.0, -f3.W_CONF_CONT * kept[s][j][5]))
    for f in range(s + 1, n):
        nxt = []
        for p in live:
            lp, lj = p.obs[-1]
            succ, must = au.gated(lp, lj, p.lx, p.ly, p.vx, p.vy, f, kept, kept_arr, pts)
            for j, c, nvx, nvy in succ[:f3.MAX_SUCC_PER_PATH]:
                nxt.append(f3._Path(p.obs + [(f, j)], float(kept_arr[f][j, 0]), float(kept_arr[f][j, 1]),
                                    nvx, nvy, p.cost + c, max(p.maxspeed, math.hypot(nvx, nvy))))
            if not must:
                nxt.append(f3._Path(list(p.obs), p.lx, p.ly, p.vx, p.vy, p.cost + f3.NULL_COST, p.maxspeed))
        if not nxt:
            return []
        live = f3._prune_dual(nxt, f - s)
    return sorted(tuple(q.obs) for q in live)


@pytest.mark.parametrize('seed', [0, 1, 2])
def test_graph_transition_function_equals_v3(seed):
    frames = synth_frames(seed=seed)
    clean, pts, kept, kept_arr = lattice_of(frames)
    rec = {}
    orig = f3._prune_dual

    def prune(nxt, age):
        out = orig(nxt, age)
        if out:
            rec[out[0].obs[0][0]] = (age, out)
        return out
    f3._prune_dual = prune
    try:
        f3._extend_starts(kept, kept_arr, pts, [0])
    finally:
        f3._prune_dual = orig
    v3_live = sorted(tuple(q.obs) for q in rec[0][1])
    assert mini_beam(kept, kept_arr, pts, 0) == v3_live


def test_graph_oracle_does_not_modify_graph_and_is_isolated():
    frames = synth_frames(seed=3)
    clean, pts, kept, kept_arr = lattice_of(frames)
    before = (copy.deepcopy(kept), [a.copy() for a in kept_arr])
    anchors = {f: (0.2 + 0.2 * f / 30, 0.3 - 0.6 * f / 30 + 0.9 * (f / 30) ** 2) for f in range(10, 30, 3)}
    flight = {'anchors': anchors, 't0': pts[10], 't1': pts[29], 'frames': (10, 29)}
    cap = {'kept': kept, 'kept_arr': kept_arr, 'pts': pts, 'anchors': anchors, 'off': [(0, 0)] * len(pts)}
    r = au.graph_oracle(cap, flight)
    assert kept == before[0]
    assert all(np.array_equal(a, b) for a, b in zip(kept_arr, before[1]))
    # every oracle step is a legal V3 transition over existing nodes
    obs = r['obs']
    assert obs and all(0 <= j < len(kept[p]) for p, j in obs)
    assert r['eval']['coverage'] > 0.5


def test_search_pool_and_final_ranking_identity_real_dive():
    # small real clip: capture twice -> identical pool/ranking; top-K == frozen artifact
    group = 'indep'
    raw = json.loads(v1run.CACHES[group].read_text())
    doc = raw['dives']['1304']
    frames = f3.inference_view(doc['frames'])
    a = au.capture(frames, float(doc['fps']))
    b = au.capture(frames, float(doc['fps']))
    sig = lambda c: json.dumps([list(map(list, p.obs)) for p in c['pool']])
    assert sig(a) == sig(b)
    assert [round(c[0], 9) for c in a['cores']] == [round(c[0], 9) for c in b['cores']]
    ref = json.loads((ROOT.parent / 'diveanalyzer-flight-v3/runs/flight_anchored_traj_v3/1304.json').read_text())
    assert [t['path_score'] for t in a['output']['tracks']] == [t['path_score'] for t in ref['tracks']]
    assert [t['track_id'] for t in a['output']['tracks']] == [t['track_id'] for t in ref['tracks']]


# ---------------------------------------------------------------- report-level
@pytest.fixture(scope='module')
def report():
    if not REPORT.exists():
        pytest.skip('report not yet generated')
    return json.loads(REPORT.read_text())


def test_v3_reproduction(report):
    assert report['V3_REPRODUCTION']['all_15_outputs_identical'] is True
    assert report['V3_REPRODUCTION']['flight_recall'] == {'recovered_clips': 1, 'evaluable_clips': 9}


def test_retention_funnel_determinism(report):
    import build_flight_path_recall_report_v1 as br
    if not any(br.RUNS.glob('*.json')):
        pytest.skip('run artifacts (git-ignored) not present')
    assert br.funnel(br.load_runs(), 'FROZEN_V3_AUTHORITY') == report['RETENTION_FUNNEL']['FROZEN_V3_AUTHORITY']


def test_protected_data_firewall(report):
    cohort = set(v1run.COHORT)
    assert '524' not in cohort and '2555' not in cohort
    src = Path(au.__file__).read_text()
    for tok in ('INTERNAL_EVAL', 'FINAL_HOLDOUT', 'Paris', 'paris'):
        assert tok not in src
    assert report['protected_data']['INTERNAL_EVAL'] == 'NOT_ACCESSED'


def test_no_training_labels_b2(report):
    src = Path(au.__file__).read_text()
    for tok in ('ultralytics', 'YOLO(', '.train(', 'boto', 'b2sdk', 'torch', 'cv2', 'ffmpeg'):
        assert tok not in src, tok
    r = report['resources']
    assert (r['D5_inference'], r['new_embeddings'], r['training'], r['new_labels'], r['B2_writes']) == (0, 0, 0, 0, 0)
    assert git('status', '--porcelain', '--', 'docs/science/localization_annotations_v1',
               'docs/science/pilot_annotations_v2') == ''
