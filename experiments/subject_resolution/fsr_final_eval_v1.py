"""DIVE_ANALYZER_FLIGHT_SEARCH_RECOVERY_V1 — sealed final evaluation (FLIGHT_GT_HUMAN_V1).

Usage:
  python3 fsr_final_eval_v1.py mine          # frozen pipeline funnel, 360 / hq / 360+hq
  python3 fsr_final_eval_v1.py v3 <dive> <rep>  # frozen V3 funnel for one dive (parallelizable)
The authority loads only if the frozen protocol doc is committed at HEAD.
"""
import json
import math
import sys

import numpy as np

import fsr_common_v1 as C
import fsr_pipeline_v1 as P
import fsr_pool_cache_v1 as PC
import fsr_search_v1 as S

PROTOCOL_SHA = '5c3fb3444e99b3aa4f08237f8aa607e50278150bf619d353218d8a77fd6e515c'
KS = (1, 3, 5, 10, 20)
D5_MINED_COINCIDENT = {('2353', 368), ('311', 432)}
OUT = C.RUNS / 'final_eval'


def flight_anchors(auth, d, pts, strict=False):
    a = auth[d]
    anchors = {fp: v for fp, v in a['anchors'].items()}
    fl = C.in_window(anchors, pts, a['window'])
    if strict:
        fl = {fp: v for fp, v in fl.items() if (d, fp) not in D5_MINED_COINCIDENT}
    return fl


def presence_frac(cands_per_frame, A):
    if not A:
        return 0.0
    h = 0
    for fp, a in A.items():
        if any(math.hypot(c[0] - a[0], c[1] - a[1]) <= C.RADIUS for c in cands_per_frame[fp]):
            h += 1
    return h / len(A)


def oracle_dp(L, pts, A, lead_s=0.3):
    """Evaluation-only GT-guided best path over the SAME gated graph as the search
    (v1 gates; velocity carried along the best predecessor). GT selects edges only."""
    fa = sorted(A)
    wa, wb = fa[0], fa[-1]
    lo = next(i for i, t in enumerate(pts) if t >= pts[wa] - lead_s)
    hi = wb
    # linear GT guide for tie-breaking between anchors
    def guide(f):
        prev = [x for x in fa if x <= f]
        nxt = [x for x in fa if x >= f]
        if prev and nxt and prev[-1] != nxt[0]:
            a, b = prev[-1], nxt[0]
            w = (f - a) / (b - a)
            return ((1 - w) * A[a][0] + w * A[b][0], (1 - w) * A[a][1] + w * A[b][1])
        x = prev[-1] if prev else nxt[0]
        return A[x][0], A[x][1]
    F, VX, VY, BF, BJ = {}, {}, {}, {}, {}
    for f in range(lo, hi + 1):
        a = L[f]
        if not len(a):
            continue
        gx, gy = guide(f)
        rew = np.zeros(len(a))
        if f in A:
            dd = np.hypot(a[:, 0] - A[f][0], a[:, 1] - A[f][1])
            rew = np.where(dd <= C.RADIUS, 1.0, -1.0)
        tie = -1e-3 * np.hypot(a[:, 0] - gx, a[:, 1] - gy)
        best = rew + tie  # fresh start
        bvx = np.zeros(len(a)); bvy = np.zeros(len(a))
        bf = np.full(len(a), -1); bj = np.full(len(a), -1)
        sj = np.minimum(np.sqrt(a[:, 2] * a[:, 3]), S.SCALE_CAP)
        areaj = np.maximum(a[:, 2] * a[:, 3], 1e-9)
        g = f - 1
        while g >= lo and pts[f] - pts[g] <= S.NULL_MAX_S + 1e-9:
            if g in F:
                p = L[g]
                dt = pts[f] - pts[g]
                vx, vy = VX[g][:, None], VY[g][:, None]
                dx = a[None, :, 0] - p[:, None, 0]
                dy = a[None, :, 1] - p[:, None, 1]
                scale = 0.5 * (np.minimum(np.sqrt(p[:, 2] * p[:, 3]), S.SCALE_CAP)[:, None] + sj[None, :])
                erel = np.hypot(dx - vx * dt, dy - vy * dt) / np.maximum(scale, 1e-6)
                lsz = np.abs(np.log(areaj[None, :] / np.maximum(p[:, 2] * p[:, 3], 1e-9)[:, None]))
                nvx = S.VEL_ALPHA * dx / dt + (1 - S.VEL_ALPHA) * vx
                nvy = S.VEL_ALPHA * dy / dt + (1 - S.VEL_ALPHA) * vy
                ok = (erel <= S.E_REL_MAX) & (lsz <= S.SIZE_TOL) & (np.hypot(nvx, nvy) <= S.V_SMOOTH_MAX)
                cand = np.where(ok, F[g][:, None] + rew[None, :] + tie[None, :], -np.inf)
                i = np.argmax(cand, axis=0)
                ar = np.arange(len(a))
                val = cand[i, ar]
                upd = val > best
                best = np.where(upd, val, best)
                bvx = np.where(upd, nvx[i, ar], bvx); bvy = np.where(upd, nvy[i, ar], bvy)
                bf = np.where(upd, g, bf); bj = np.where(upd, i, bj)
            g -= 1
        F[f], VX[f], VY[f], BF[f], BJ[f] = best, bvx, bvy, bf, bj
    bestv, arg = -np.inf, None
    for f, v in F.items():
        j = int(np.argmax(v))
        if v[j] > bestv:
            bestv, arg = v[j], (f, j)
    path = [arg]
    f, j = arg
    while BF[f][j] >= 0:
        f, j = int(BF[f][j]), int(BJ[f][j])
        path.append((f, j))
    return S.path_obs(path[::-1], L)


def eval_mine():
    auth = C.load_eval_authority(PROTOCOL_SHA)
    res = {}
    for d in C.COHORT:
        base = C.frames(d, '360')
        pts = [f['pts_s'] for f in base]
        per = {'window': auth[d]['window'][:2], 'window_source': auth[d]['window'][2],
               'unobserved_items': auth[d]['unobserved']}
        for strict in (False, True):
            A = flight_anchors(auth, d, pts, strict)
            tag = 'strict' if strict else 'all'
            per[f'flight_anchors_{tag}'] = len(A)
            for rep in ('360', 'hq', '360+hq'):
                reps = tuple(rep.split('+'))
                if 'hq' in reps and d not in C.HQ_DIVES:
                    continue
                row = {}
                if rep != '360+hq':
                    fr = C.frames(d, rep)
                    L = S.lattice(fr)
                    row['S0_raw_presence'] = presence_frac([[(c['cx'], c['cy']) for c in f['c']] for f in fr], A)
                    row['S1_lattice_presence'] = presence_frac([[tuple(x[:2]) for x in a] for a in L], A)
                    orc = C.score_track(oracle_dp(L, pts, A), A) if len(A) >= 2 else None
                    row['S2_graph_oracle'] = orc
                    pool, L2 = PC.pool(S, d, rep)
                    pe = [C.score_track(S.path_obs(p, L2), A) for _, p in pool]
                    row['S3_pool_recovered'] = any(e['recovered'] for e in pe)
                    row['S3_pool_best_cov'] = max((e['coverage'] for e in pe), default=0.0)
                else:
                    fr_all = [C.frames(d, r) for r in reps]
                    row['S0_raw_presence'] = presence_frac(
                        [[(c['cx'], c['cy']) for fr in fr_all for c in fr[k]['c']] for k in range(len(pts))], A)
                cands = P.surface(d, reps, max_surfaced=100000)
                ranks = [c['rank'] for c in cands if C.score_track(c['obs'], A)['recovered']]
                row['S3b_candidates'] = len(cands)
                row['S3b_any_candidate_recovered'] = bool(ranks)
                row['first_recovered_rank'] = ranks[0] if ranks else None
                best = max(cands, key=lambda c: C.score_track(c['obs'], A)['coverage'], default=None)
                row['best_candidate'] = C.score_track(best['obs'], A) if best else None
                for k in KS:
                    row[f'top{k}'] = bool(ranks and ranks[0] <= k)
                per[f'{tag}:{rep}'] = row
        res[d] = per
        print(d, {k: (v['first_recovered_rank'], round(v.get('S0_raw_presence', 0), 2),
                      (v.get('S2_graph_oracle') or {}).get('recovered'), v.get('S3_pool_recovered'))
                  for k, v in per.items() if k.startswith('all:')}, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'mine.json').write_text(json.dumps(res, indent=1, sort_keys=True, default=str))


def eval_v3(d, rep):
    import audit_flight_path_recall_v1 as AU
    import flight_anchored_traj_v3 as f3
    auth = C.load_eval_authority(PROTOCOL_SHA)
    frames = f3.inference_view(C.frames(d, rep))
    cap = AU.capture(frames, C.fps(d))  # GT-free, before any GT use below
    pts = cap['pts']
    out = {}
    for strict in (False, True):
        A = flight_anchors(auth, d, pts, strict)
        tag = 'strict' if strict else 'all'
        flight = {'anchors': {fp: (v[0], v[1]) for fp, v in A.items()},
                  't0': auth[d]['window'][0], 't1': auth[d]['window'][1],
                  'frames': AU.flight_frames({'takeoff_s': auth[d]['window'][0],
                                              'water_contact_s': auth[d]['window'][1]}, pts)}
        cap['anchors'] = flight['anchors']
        kept = cap['kept']
        row = {'flight_anchors': len(A)}
        row['S0_raw_presence'] = presence_frac([[(c['cx'], c['cy']) for c in f['c']] for f in cap['clean']], A)
        row['S1_lattice_presence'] = presence_frac([[(x[1], x[2]) for x in k] for k in kept], A)
        row['S2_graph_oracle'] = AU.graph_oracle(cap, flight)['eval'] if len(A) >= 2 else None
        obs_of = lambda obs: {p: (kept[p][j][1], kept[p][j][2]) for p, j in obs}
        pe = [C.score_track(obs_of(q.obs), A) for q in cap['pool']]
        row['S3_pool_recovered'] = any(e['recovered'] for e in pe)
        row['S3_pool_best_cov'] = max((e['coverage'] for e in pe), default=0.0)
        f0 = [C.score_track(obs_of(dv[1]), A) for dv in cap['diverse'][:f3.FINAL_TOP_K]]
        row['F0_topK_recovered'] = any(e['recovered'] for e in f0)
        f1 = []
        for t in cap['output']['tracks']:
            obs = {p['frame_index']: tuple(p['bbox_cxcywh_norm'][:2]) for p in t['trajectory']}
            f1.append((t['path_rank'], C.score_track(obs, A)))
        rr = [r for r, e in f1 if e['recovered']]
        row['F1_final_first_recovered_rank'] = min(rr) if rr else None
        row['F1_final_best_cov'] = max((e['coverage'] for _, e in f1), default=0.0)
        out[tag] = row
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f'v3_{d}_{rep}.json').write_text(json.dumps(out, indent=1, sort_keys=True, default=str))
    print(d, rep, {k: (v['S2_graph_oracle'] or {}).get('qualifies') if v['S2_graph_oracle'] else None for k, v in out.items()},
          out['all']['F1_final_first_recovered_rank'], flush=True)


if __name__ == '__main__':
    if sys.argv[1] == 'mine':
        eval_mine()
    else:
        eval_v3(sys.argv[2], sys.argv[3])
