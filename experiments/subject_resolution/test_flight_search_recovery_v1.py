"""Tests for DIVE_ANALYZER_FLIGHT_SEARCH_RECOVERY_V1."""
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path

import numpy as np
import pytest

import fsr_common_v1 as C
import fsr_hq_cache_v1 as HQ
import fsr_pipeline_v1 as P
import fsr_rank_v1 as R
import fsr_search_v1 as S

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROTO = ROOT / 'docs/science' / S.PROTOCOL_DOC


def _src(name):
    return (HERE / name).read_text()


@pytest.mark.parametrize('mod', ['fsr_search_v1.py', 'fsr_search_v2.py', 'fsr_search_v3.py',
                                 'fsr_search_v4.py', 'fsr_rank_v1.py', 'fsr_pipeline_v1.py'])
def test_inference_path_is_gt_free(mod):
    s = _src(mod)
    for tok in ('FLIGHT_GT_HUMAN', 'localization_annotations', 'pilot_annotations', 'load_eval_authority',
                'dev_anchors', 'chain_anchors', 'yaml'):
        assert tok not in s, (mod, tok)


def test_protocol_constants_frozen_in_doc():
    doc = PROTO.read_text()
    blob = json.loads(re.search(r'```json\n(.*?)\n```', doc, re.S).group(1))
    assert blob['SEARCH'] == json.loads(json.dumps(S.PROTOCOL_CONSTANTS, default=list))
    assert blob['RANK'] == R.RANK_CONSTANTS
    for k, v in blob['PIPELINE'].items():
        assert getattr(P, k) == v


def test_eval_authority_guard_refuses_uncommitted_or_wrong_protocol():
    with pytest.raises(AssertionError):
        C.load_eval_authority('0' * 64)


def test_eval_authority_integrity_and_shape():
    import fsr_final_eval_v1 as FE
    auth = C.load_eval_authority(FE.PROTOCOL_SHA)
    assert set(auth) == set(C.COHORT)
    man = json.loads((C.EVAL_DIR / 'MANIFEST.json').read_text())
    assert man['digest'] == C.EVAL_DIGEST
    for d, a in auth.items():
        t0, t1, src = a['window']
        assert 0.3 <= t1 - t0 <= 2.5, (d, t1 - t0)
        assert src.startswith('FLIGHT_GT_HUMAN_V1') == (d in C.GROUPS['indep'])
        assert len(a['anchors']) >= 3


def test_protected_data_firewall():
    assert not (set(C.COHORT) & {'524', '2555', '160', '169', '191', '192', '2281', '848'})
    with pytest.raises(AssertionError):
        C.frames('524')


def test_static_mask_masks_static_keeps_moving():
    pts = [i / 30 for i in range(40)]
    frames = []
    for i, t in enumerate(pts):
        frames.append({'pts_s': t, 'c': [
            {'conf': 0.5, 'cx': 0.2, 'cy': 0.2, 'bw': 0.1, 'bh': 0.1},  # static
            {'conf': 0.5, 'cx': 0.3 + 0.4 * t, 'cy': 0.5, 'bw': 0.1, 'bh': 0.1}]})  # moving 0.4 norm/s
    A = S._full(frames)
    M = S.static_mask(A, pts)
    mid = 20
    xs = A[mid][:, 0]
    assert M[mid][np.argmin(np.abs(xs - 0.2))]
    assert not M[mid][np.argmin(np.abs(xs - (0.3 + 0.4 * pts[mid])))]


def _synthetic_clip(seed=0, n=60, fps=30.0):
    rng = np.random.default_rng(seed)
    pts = [i / fps for i in range(n)]
    frames = []
    for i, t in enumerate(pts):
        c = [{'conf': float(rng.uniform(0.001, 0.02)), 'cx': float(rng.uniform(0, 1)),
              'cy': float(rng.uniform(0, 1)), 'bw': 0.1, 'bh': 0.1} for _ in range(40)]
        if 10 <= i < 45:  # ballistic diver
            tt = t - pts[10]
            c.append({'conf': 0.2, 'cx': 0.2 + 0.25 * tt + float(rng.normal(0, 0.004)),
                      'cy': 0.3 - 0.4 * tt + 0.8 * tt * tt + float(rng.normal(0, 0.004)),
                      'bw': 0.12, 'bh': 0.12})
        frames.append({'pts_s': t, 'c': c})
    truth = {i: (0.2 + 0.25 * (pts[i] - pts[10]), 0.3 - 0.4 * (pts[i] - pts[10]) + 0.8 * (pts[i] - pts[10]) ** 2)
             for i in range(12, 43, 3)}
    return frames, truth


def test_search_recovers_synthetic_ballistic_track_and_is_deterministic():
    frames, truth = _synthetic_clip()
    pool, L = S.search(frames)
    pool2, _ = S.search(frames)
    assert [p for _, p in pool] == [p for _, p in pool2]
    ok = [C.score_track(S.path_obs(p, L), truth)['recovered'] for _, p in pool]
    assert any(ok)


def test_ranker_v2_fixes_junk_continuation_weakness_of_v1_on_synthetic_clips():
    import fsr_rank_v2 as R2
    wins = {R: 0 for R in (R, R2)}
    for seed in range(10):
        frames, truth = _synthetic_clip(seed)
        pool, L = S.search(frames)
        pts = [f['pts_s'] for f in frames]
        for rk in wins:
            top = rk.rank_pool(pool, L, pts)[0]
            wins[rk] += C.score_track(S.path_obs(top[2], L), truth)['recovered']
    # documented: v1 extends segments into junk continuations (6/10); v2 trims (8/10)
    assert wins[R2] > wins[R] and wins[R2] >= 8


def test_ballistic_score_prefers_drop_over_horizontal():
    pts = [i / 30 for i in range(30)]
    L = []
    for t in pts:
        L.append(np.array([[0.2 + 0.2 * t, 0.3 - 0.3 * t + 0.9 * t * t, 0.1, 0.1, 0.1],
                           [0.1 + 0.3 * t, 0.8, 0.1, 0.1, 0.1]]))
    arc = [(f, 0) for f in range(30)]
    walk = [(f, 1) for f in range(30)]
    qa = R.flight_score(arc, L, pts)[0]
    qw = R.flight_score(walk, L, pts)[0]
    assert qa > 0.1 and (qw == float('-inf') or qw < qa - 0.1)


def test_hq_spatial_map_roundtrip_and_311_refinement():
    m = HQ.MAPS['676']
    for px, py in [(0.1, 0.1), (0.5, 0.4), (0.9, 0.55)]:
        hx, hy = m['x_off'] + px * m['x_span'], m['y_off'] + py * m['y_span']
        assert abs((hx - m['x_off']) / m['x_span'] - px) < 1e-12
        assert abs((hy - m['y_off']) / m['y_span'] - py) < 1e-12
    assert HQ.MAPS['311']['dt'] == 12.145
    assert all(HQ.MAPS[d]['dt'] == 0.0 for d in HQ.HQ if d != '311')
    assert '524' not in HQ.HQ and '2555' not in HQ.HQ


@pytest.mark.skipif(not C.HQ_CACHE.exists(), reason='host HQ cache absent')
def test_hq_cache_on_frozen_proxy_timeline_and_recipe():
    raw = json.loads(C.HQ_CACHE.read_text())
    assert raw['model_sha256'].startswith('82b420c4')
    assert (raw['floor_conf'], raw['nms_iou'], raw['imgsz'], raw['floor_cap']) == (0.001, 0.45, 640, 200)
    for d in C.HQ_DIVES:
        assert [f['pts_s'] for f in raw['dives'][d]['frames']] == [f['pts_s'] for f in C.frames(d, '360')]


def test_frozen_v3_and_caches_unchanged():
    exp = subprocess.check_output(['git', 'show', '3e889f2:experiments/subject_resolution/flight_anchored_traj_v3.py'], cwd=ROOT)
    assert hashlib.sha256(exp).hexdigest() == C.sha256_file(HERE / 'flight_anchored_traj_v3.py')
    for g, p in C.CACHES.items():
        assert C.sha256_file(p) == C.CACHE_SHAS[g]


def test_annotation_queue_rule_fractions():
    import fsr_flight_gt_annotation_v1 as A
    q = A.build_queue({'items': {}, 'events': {}})
    ev = [i for i in q['items'] if i['window_source'].startswith('HUMAN_EVENT_YAML') and not i.get('repeat_of')]
    assert len(ev) == 63 and {i['dive_id'] for i in ev} == set(A.EVENT_DIVES)
    assert all(i['flight_fraction'] in {f'{k}/8' for k in range(1, 8)} for i in ev)
    assert len([i for i in q['items'] if i.get('repeat_of')]) == 6


def test_annotation_tool_ui_never_serves_detections():
    s = _src('fsr_flight_gt_annotation_v1.py')
    ui = s[s.index('_UI = r"""'):s.index('"""', s.index('_UI = r"""') + 10)]
    for tok in ("'conf'", 'cands', 'draft', 'D5'):
        assert tok not in ui
