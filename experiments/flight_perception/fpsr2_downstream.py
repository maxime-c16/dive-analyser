#!/usr/bin/env python3
"""Fresh FPSR2 HUMAN holdout through the unchanged FSR flight-search funnel.

Causal question: if detector proposals improve, does candidate/path recall improve
WITHOUT changing the trajectory algorithm? The downstream is the frozen
FLIGHT_SEARCH_RECOVERY_V1 stack (fsr_search_v1 / fsr_rank_v1 / fsr_pipeline_v1 and
the evaluation-only graph oracle of fsr_final_eval_v1), imported unchanged. Only the
candidate source is redirected: `use_detector(key)` points `fsr_common_v1.frames`
at this packet's caches (CAND_<key>_<rep>.json) and the pool cache at a
detector-specific directory. Every search/rank constant stays the frozen protocol's.

Metrics per authority dive:
  proposal level (per HUMAN flight anchor): presence within the frozen 0.06 radius,
  best IoU vs the HUMAN box, subject confidence, subject confidence-rank in frame,
  margin vs the best non-subject candidate, subject presence at conf >= 0.05/0.10/0.25;
  continuity (diagnostic, labelled INTERP): per flight frame between the first and
  last anchor, presence near the linear interpolation of the HUMAN anchors, runs/breaks;
  funnel: S0 raw, S1 lattice, S2 graph oracle, S3 pool, S3b extracted, top-K surfaced.

Authority: FLIGHT_GT_HUMAN_V3_HOLDOUT. `load_holdout()` refuses until the
recovery protocol is committed at HEAD with the expected SHA.

Usage: python3 fpsr2_downstream.py <detector_key> FGT3H <protocol_sha>
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'subject_resolution'))
import fpsr2_media as fm  # noqa: E402
import fsr_common_v1 as C  # noqa: E402
import fsr_final_eval_v1 as FE  # noqa: E402
import fsr_pipeline_v1 as P  # noqa: E402
import fsr_pool_cache_v1 as PC  # noqa: E402
import fsr_search_v1 as S  # noqa: E402

KS = (1, 3, 5, 10, 20)
CONF_LEVELS = (0.05, 0.10, 0.25)
PROTOCOL_DOC = 'FLIGHT_PERCEPTION_RECOVERY_V2_PROTOCOL.md'
HOLDOUT_DIR = fm.DOC / 'localization_annotations_v1/FLIGHT_GT_HUMAN_V3_HOLDOUT'
OUT = fm.RUNS / 'downstream'
_STATE = {}


def use_detector(key):
    """Redirect the frozen stack's candidate source; nothing else changes."""
    caches = {}

    def _load(rep):
        if rep not in caches:
            p = fm.RUNS / 'caches' / f'CAND_{key}_{rep}.json'
            caches[rep] = json.loads(p.read_text())['dives'] if p.exists() else {}
            for d, row in caches[rep].items():
                fm.assert_allowed(d)
                assert row['proxy_sha256'] == fm.registry()[d]['proxy_sha256'], (key, rep, d)
        return caches[rep]

    def frames(d, rep='360'):
        fm.assert_allowed(d)
        if rep == 'mix':
            a, b = frames(d, '360'), frames(d, 'hq')
            return [{'fi': x['fi'], 'pts_s': x['pts_s'], 'c': x['c'] + y['c']} for x, y in zip(a, b)]
        src = _load(rep)[d]['frames']
        return [{'fi': f['fi'], 'pts_s': f['pts_s'], 'c': [{k: c[k] for k in C.WHITELIST} for c in f['c']]}
                for f in src]
    C.frames = frames
    PC.DIR = fm.RUNS / 'pool_cache' / key
    hq = set(_load('hq'))
    C.HQ_DIVES = sorted(hq)
    _STATE.update(key=key, hq=hq, load=_load)


# ------------------------------------------------------------- authorities --

def fgt1_authority():
    return C.load_eval_authority(FE.PROTOCOL_SHA)


def load_holdout(protocol_sha):
    """Sealed FRESH holdout. Refuses unless the successor protocol is committed at HEAD."""
    doc = fm.DOC / PROTOCOL_DOC
    assert fm.sha256_file(doc) == protocol_sha, 'protocol doc changed since commit'
    committed = subprocess.check_output(['git', 'show', f'HEAD:docs/science/{PROTOCOL_DOC}'], cwd=fm.ROOT)
    assert hashlib.sha256(committed).hexdigest() == protocol_sha, 'protocol not committed at HEAD'
    man = json.loads((HOLDOUT_DIR / 'MANIFEST.json').read_text())
    assert man['split_authority'] == 'FLIGHT_PERCEPTION_RECOVERY_SPLIT_V2'
    assert man['sealed'] is True
    for name, h in man['files'].items():
        assert fm.sha256_file(HOLDOUT_DIR / name) == h, name
    digest = hashlib.sha256(json.dumps(man['files'], sort_keys=True).encode()).hexdigest()
    assert digest == man['digest']
    events = json.loads((HOLDOUT_DIR / 'FGT3H_EVENTS.json').read_text())
    auth = {}
    for p in sorted(HOLDOUT_DIR.glob('FGT3H_*_f*.json')):
        if p.name.endswith('_R.json'):
            continue
        a = json.loads(p.read_text())
        d = str(a['dive_id'])
        auth.setdefault(d, {'anchors': {}, 'unobserved': {}})
        if a['visibility'] in ('visible', 'partial') and a['bbox']:
            x1, y1, x2, y2 = a['bbox']
            auth[d]['anchors'][a['frame_index']] = ((x1 + x2) / 2 / a['width'], (y1 + y2) / 2 / a['height'],
                                                    'FLIGHT_GT_HUMAN_V3_HOLDOUT', a['flight_fraction'],
                                                    a['visibility'], (x2 - x1) / a['width'], (y2 - y1) / a['height'])
        else:
            auth[d]['unobserved'][a['frame_index']] = a['visibility']
    for d in auth:
        auth[d]['window'] = (events[f'FGT3H_EV_{d}_takeoff']['pts_s'], events[f'FGT3H_EV_{d}_water_contact']['pts_s'],
                             'FLIGHT_GT_HUMAN_V3_HOLDOUT_EVENTS')
    expected = {str(x['dive_id']) for x in fm.split()['dives']}
    assert set(auth) <= expected
    return auth, man['digest']


# ------------------------------------------------------------- metrics -----

def iou(a, b):
    ax0, ay0, ax1, ay1 = a[0] - a[2] / 2, a[1] - a[3] / 2, a[0] + a[2] / 2, a[1] + a[3] / 2
    bx0, by0, bx1, by1 = b[0] - b[2] / 2, b[1] - b[3] / 2, b[0] + b[2] / 2, b[1] + b[3] / 2
    iw, ih = max(0.0, min(ax1, bx1) - max(ax0, bx0)), max(0.0, min(ay1, by1) - max(ay0, by0))
    inter = iw * ih
    u = a[2] * a[3] + b[2] * b[3] - inter
    return inter / u if u > 0 else 0.0


def proposal_metrics(fr, A):
    """Per-anchor proposal quality. A: {fp: (cx, cy, tier, frac, vis, w, h)} (normalized proxy frame)."""
    rows = []
    for fp, a in sorted(A.items()):
        cs = fr[fp]['c']
        gt = (a[0], a[1], a[5], a[6]) if len(a) >= 7 else None
        near = [c for c in cs if math.hypot(c['cx'] - a[0], c['cy'] - a[1]) <= C.RADIUS]
        sub = max(near, key=lambda c: c['conf']) if near else None
        order = sorted(cs, key=lambda c: -c['conf'])
        rank = order.index(sub) if sub else None
        others = [c for c in cs if math.hypot(c['cx'] - a[0], c['cy'] - a[1]) > 2 * C.RADIUS]
        best_other = max((c['conf'] for c in others), default=0.0)
        ious = [iou((c['cx'], c['cy'], c['bw'], c['bh']), gt) for c in cs] if gt else []
        rows.append({'fp': fp, 'frac': a[3], 'present': sub is not None,
                     'subject_conf': sub['conf'] if sub else 0.0, 'rank': rank,
                     'margin_vs_other': (sub['conf'] if sub else 0.0) - best_other,
                     'best_iou': max(ious, default=0.0),
                     'iou_of_subject_cand': iou((sub['cx'], sub['cy'], sub['bw'], sub['bh']), gt) if (sub and gt) else None,
                     **{f'present_conf{t:.2f}': bool(sub and sub['conf'] >= t) for t in CONF_LEVELS}})
    return rows


def continuity_interp(fr, A, pts):
    """DIAGNOSTIC (labelled INTERP): dense presence near the linear interpolation of HUMAN anchors."""
    fa = sorted(A)
    if len(fa) < 2:
        return None
    out = {}
    for t in (0.001, 0.05):
        seq = []
        for f in range(fa[0], fa[-1] + 1):
            prev = max(x for x in fa if x <= f)
            nxt = min(x for x in fa if x >= f)
            w = 0.0 if nxt == prev else (pts[f] - pts[prev]) / (pts[nxt] - pts[prev])
            gx = (1 - w) * A[prev][0] + w * A[nxt][0]
            gy = (1 - w) * A[prev][1] + w * A[nxt][1]
            seq.append(any(c['conf'] >= t and math.hypot(c['cx'] - gx, c['cy'] - gy) <= C.RADIUS for c in fr[f]['c']))
        runs, cur = [], 0
        for s in seq:
            if s:
                cur += 1
            elif cur:
                runs.append(cur)
                cur = 0
        if cur:
            runs.append(cur)
        out[f'conf{t}'] = {'frames': len(seq), 'present_frac': sum(seq) / len(seq), 'n_runs': len(runs),
                           'longest_run_frac': max(runs, default=0) / len(seq)}
    return out


def evaluate(key, authority, protocol_sha=None, dives=None, reps=('360', 'hq')):
    use_detector(key)
    assert authority == 'FGT3H'
    auth, digest = load_holdout(protocol_sha)
    res = {'detector': key, 'authority': authority, 'authority_digest': digest,
           'dives': {}, 'excluded_lt2_visible_flight_anchors': {}}
    for d in dives or sorted(auth, key=int):
        base = C.frames(d, '360')
        pts = [f['pts_s'] for f in base]
        A = FE.flight_anchors(auth, d, pts)
        if len(A) < 2:
            res['excluded_lt2_visible_flight_anchors'][d] = len(A)
            continue
        per = {'role': 'FRESH_HELD_OUT_DEVELOPMENT', 'n_flight_anchors': len(A),
               'unobserved': len(auth[d]['unobserved']),
               'median_human_box_height_norm': statistics.median(a[6] for a in A.values())}
        use_reps = [r for r in reps if r == '360' or d in _STATE['hq']]
        for rep in use_reps:
            fr = C.frames(d, rep)
            row = {'proposal': proposal_metrics(fr, A), 'continuity_INTERP': continuity_interp(fr, A, pts)}
            L = S.lattice(fr)
            row['S0_raw_presence'] = FE.presence_frac([[(c['cx'], c['cy']) for c in f['c']] for f in fr], A)
            row['S1_lattice_presence'] = FE.presence_frac([[tuple(x[:2]) for x in a] for a in L], A)
            row['S2_graph_oracle'] = C.score_track(FE.oracle_dp(L, pts, A), A) if len(A) >= 2 else None
            pool, L2 = PC.pool(S, d, rep)
            pe = [C.score_track(S.path_obs(p, L2), A) for _, p in pool]
            row['S3_pool_recovered'] = any(e['recovered'] for e in pe)
            row['S3_pool_best_cov'] = max((e['coverage'] for e in pe), default=0.0)
            per[rep] = row
        for rtag in ['360'] + (['hq', '360+hq'] if 'hq' in use_reps else []):
            reps_ = tuple(rtag.split('+'))
            cands = P.surface(d, reps_, max_surfaced=100000)
            ranks = [c['rank'] for c in cands if C.score_track(c['obs'], A)['recovered']]
            s = per.setdefault(rtag, {})
            s['S3b_candidates'] = len(cands)
            s['S3b_any_candidate_recovered'] = bool(ranks)
            s['first_recovered_rank'] = ranks[0] if ranks else None
            for k in KS:
                s[f'top{k}'] = bool(ranks and ranks[0] <= k)
        res['dives'][d] = per
        print(key, authority, d, {r: (per[r].get('first_recovered_rank'), round(per[r].get('S0_raw_presence', -1), 2),
                                      (per[r].get('S2_graph_oracle') or {}).get('recovered'), per[r].get('S3_pool_recovered'))
                                  for r in ('360', 'hq', '360+hq') if r in per}, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f'{key}_{authority}.json').write_text(json.dumps(res, indent=1, sort_keys=True, default=str))
    return res


if __name__ == '__main__':
    evaluate(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
