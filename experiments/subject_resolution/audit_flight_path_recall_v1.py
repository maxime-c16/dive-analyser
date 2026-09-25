"""DIVE_ANALYZER_FLIGHT_PATH_CANDIDATE_RECALL_AUDIT_V1.

Audit / localization only. Frozen V3 (F0 + F1) is executed UNCHANGED via
flight_anchored_traj_v3.infer; pass-through wrappers record intermediate
stages (per-start final beam, decoded pool). No V3 constant or function is
modified. HUMAN subject/event GT enters only in the evaluation section,
after every stage for a dive is frozen in memory.

Stages (actual implementation stages):
  S0  RAW_FLOOR_UNION        full D5 floor (conf>=0.001, cap 200), any cand
  S1  CAPPED_FRAME_LATTICE   build_frame_lattice (50 conf + 10 movers)
  S2  GRAPH_ORACLE           best path through S1 nodes under V3's exact
                             transition function (gates, caps, NULL<=0.30 s),
                             without search restrictions (start strata, seed
                             caps, fan-out, beam). Evaluation-only; adds no
                             node or edge.
  S3a BEAM_FINAL             each start's final live beam (<=64), pre-triage
  S3  F0_POOL_PATHS          decoded pool (POOL_PER_START triage, dedup)
  S3c F0_POOL_CORES          best-Q core per pool path (the ranked objects)
  S4  F0_TOPK_CORES          diversity-deduped Q order, first FINAL_TOP_K
  S5  F1_EXTENDED_CANDIDATES in V3 == S6 (extend_core runs on top-K only);
                             an evaluation-only counterfactual applies the
                             frozen extend_core to EVERY pool core (S5cf)
  S6  F1_FINAL_TOPK          retained V3 tracks
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

import flight_anchored_traj_v3 as f3
import run_flight_anchored_traj_v3 as r3
import run_multi_track_action_v1 as v1run

AUDIT = 'DIVE_ANALYZER_FLIGHT_PATH_CANDIDATE_RECALL_AUDIT_V1'
GATE = 'SUPERVISOR_REVIEW_AFTER_FLIGHT_PATH_CANDIDATE_RECALL_AUDIT_V1'
ROOT = r3.ROOT
OUT = ROOT / 'runs/flight_path_recall_audit_v1'
DOC = ROOT / 'docs/science'
V3_REPORT = DOC / 'DIVE_ANALYZER_FLIGHT_ANCHORED_TRAJECTORY_V3.json'
V3_PROTOCOL_COMMIT = 'd252f7b3954bd3eed4399a561dc0a1dc565043f1'
V3_SCIENCE_COMMIT = '3e889f2c9a4cd2b97f989f64b96544f9f987cefc'
EVENT_COHORT = ['1040', '2169', '2341', '2353', '2541', '133', '311', '676', '2387']
COVER = r3.RECOVERY_COVERAGE  # 0.75, frozen V3 recovery criterion
PAD = r3.FLIGHT_PAD_S

# Evaluation-only oracle budget (does not touch V3 search).
ORACLE_BEAM = 1024
ORACLE_SUCC = 16
ORACLE_LEAD_S = 0.5
ORACLE_SEED_R = 2 * f3.RADIUS


# =========================== GT-FREE CAPTURE ================================

def capture(frames, fps):
    """Run frozen f3.infer with pass-through recorders. GT-free."""
    rec = {'last_live': {}, 'pool': None, 'lattice': None}
    orig_prune, orig_es, orig_lat = f3._prune_dual, f3._extend_starts, f3.build_frame_lattice

    def prune(nxt, age):
        out = orig_prune(nxt, age)
        if out:
            rec['last_live'][out[0].obs[0][0]] = (age, list(out))
        return out

    def extend_starts(kept, kept_arr, pts, starts):
        pool = orig_es(kept, kept_arr, pts, starts)
        rec['pool'] = list(pool)
        return pool

    def lattice(fr, off):
        res = orig_lat(fr, off)
        rec['lattice'] = res
        return res

    f3._prune_dual, f3._extend_starts, f3.build_frame_lattice = prune, extend_starts, lattice
    try:
        out = f3.infer(frames, fps)
    finally:
        f3._prune_dual, f3._extend_starts, f3.build_frame_lattice = orig_prune, orig_es, orig_lat
    clean = f3.inference_view(frames)
    pts = [f['pts_s'] for f in clean]
    kept, full_counts = rec['lattice']
    kept_arr = f3._frame_arrays(kept)
    _, off = f3.compute_flow(clean, pts)
    pool = rec['pool']
    # replicate infer's (frozen) tail to expose the ranked / deduped cores
    cores = []
    for q_path in pool:
        best = f3.extract_flight_core(q_path, kept, pts)
        if best is None:
            continue
        q, i, j, parts = best
        cores.append((q, q_path, i, j, parts))
    cores.sort(key=lambda c: (-round(c[0], 9), tuple(o for o in c[1].obs)))
    diverse, suppressed_by = [], {}
    for ci, (q, q_path, i, j, parts) in enumerate(cores):
        obs = q_path.obs
        agrees = [f3._agree(obs, kept, d[1], kept) for d in diverse]
        if all(a < f3.DUP_AGREE for a in agrees):
            diverse.append((q, obs, i, j, parts, ci))
        else:
            k = next(x for x, a in enumerate(agrees) if a >= f3.DUP_AGREE)
            suppressed_by[ci] = (k, agrees[k])
        if len(diverse) >= f3.FINAL_TOP_K * 4:
            break
    n = len(pts)
    starts = list(range(0, n, f3.START_STRIDE))
    start_info = []
    for s in starts:
        eligible = s < n and pts[-1] - pts[s] >= f3.CORE_MIN_S
        age, live = rec['last_live'].get(s, (None, []))
        start_info.append({'start': s, 'eligible': eligible,
                           'survived_to_clip_end': bool(eligible and age == n - 1 - s),
                           'collapse_frame': (None if not eligible or age == n - 1 - s
                                              else (s + (age or 0) + 1)),
                           'final_live': len(live) if age == n - 1 - s else 0})
    beam_final = [p for s in starts
                  for (age, live) in [rec['last_live'].get(s, (None, []))]
                  if age == n - 1 - s for p in live]
    return {'output': out, 'clean': clean, 'pts': pts, 'kept': kept,
            'kept_arr': kept_arr, 'off': off, 'full_counts': full_counts,
            'pool': pool, 'beam_final': beam_final, 'cores': cores,
            'diverse': diverse, 'suppressed_by': suppressed_by,
            'start_info': start_info}


def successors_all(lp, lx, ly, vx, vy, f, kept, kept_arr, pts):
    """V3 transition function, verbatim math from f3._extend_starts, without
    the MAX_SUCC_PER_PATH fan-out cap. Returns (idx, costs, vx_new, vy_new,
    must_match). Equivalence to V3 (first MAX_SUCC by stable cost order) is
    source- and behaviour-tested."""
    arr = kept_arr[f]
    dt = pts[f] - pts[lp]
    must_match = dt > f3.NULL_MAX_S + 1e-9
    px, py = lx + vx * dt, ly + vy * dt
    speed = math.hypot(vx, vy)
    if not len(arr):
        return np.zeros(0, int), np.zeros(0), np.zeros(0), np.zeros(0), must_match
    resid = np.hypot(arr[:, 0] - px, arr[:, 1] - py)
    gate = f3.GATE_BASE + f3.GATE_VEL * speed * dt
    ok = resid <= gate
    if dt > 0:
        vx_new = (arr[:, 0] - lx) / dt
        vy_new = (arr[:, 1] - ly) / dt
        ok = ok & (np.abs(vy_new) <= f3.V_MAX_CY_S + f3.r5.JITTER_C) \
            & (np.abs(vx_new) <= f3.V_MAX_CX_S + f3.r5.JITTER_C) \
            & (np.hypot(vx_new, vy_new) <= f3.VEL_MAX)
    else:
        vx_new = np.zeros(len(arr))
        vy_new = np.zeros(len(arr))
    return (np.nonzero(ok)[0], resid, vx_new, vy_new, must_match, arr, dt)


def gated(lp, lj, lx, ly, vx, vy, f, kept, kept_arr, pts):
    """Full gated successor set (idx, cost-ordered) + V3 costs/velocities."""
    r = successors_all(lp, lx, ly, vx, vy, f, kept, kept_arr, pts)
    if len(r) == 5:
        return [], r[4]
    idx, resid, vx_new, vy_new, must_match, arr, dt = r
    lrow = kept[lp][lj]
    larea = max(lrow[3] * lrow[4], 1e-9)
    area = np.maximum(arr[:, 2] * arr[:, 3], 1e-9)
    size = np.abs(np.log(area / larea))
    ok = np.zeros(len(arr), bool)
    ok[idx] = True
    ok &= size <= f3.SIZE_TOL
    idx = np.nonzero(ok)[0]
    if not len(idx):
        return [], must_match
    acc = np.hypot(vx_new[idx] - vx, vy_new[idx] - vy) / max(dt, 1e-6)
    acc_pen = np.minimum(acc / f3.ACC_NORM, 2.0)
    spd_new = np.hypot(vx_new[idx], vy_new[idx])
    spd_old = math.hypot(vx, vy)
    if spd_old < f3.STATIC_SPEED or np.all(spd_new < f3.STATIC_SPEED):
        agree = np.where(spd_new >= f3.STATIC_SPEED, 1.0, 0.0)
    else:
        cos = (vx_new[idx] * vx + vy_new[idx] * vy) / np.maximum(spd_new * spd_old, 1e-9)
        agree = np.maximum(0.0, cos)
    move_bonus = np.minimum(spd_new, f3.MOVE_NORM) / f3.MOVE_NORM * agree
    costs = (resid[idx] + f3.W_SIZE * size[idx] + f3.W_ACC * acc_pen
             - f3.W_CONF_CONT * arr[idx, 4] - f3.W_MOVE * move_bonus)
    order = np.argsort(costs, kind='stable')
    out = []
    for r_ in order:
        j = int(idx[int(r_)])
        nvx = f3.VEL_ALPHA * float(vx_new[j]) + (1 - f3.VEL_ALPHA) * vx
        nvy = f3.VEL_ALPHA * float(vy_new[j]) + (1 - f3.VEL_ALPHA) * vy
        out.append((j, float(costs[int(r_)]), nvx, nvy))
    return out, must_match


# =========================== GT-ONLY EVALUATION ==============================

HURDLE_SEEDS = v1run.CACHE_ROOT / 'diveanalyzer-cand-quality-v3/runs/hurdle_identity_v1/target_anchors_v1.json'


def strict_human_anchors(dive, pts):
    """Robustness authority: only HUMAN-drawn subject boxes. L1A/L1B are
    HUMAN_REVIEWED already (identical to the frozen authority). Hurdle chains
    are evaluator/candidate-densified, so only their HUMAN_GT, visible,
    non-ambiguous seed boxes are kept (PTS-nearest frame, half-frame check)."""
    if dive not in v1run.GROUPS['hurdle']:
        return v1run.subject_anchors(dive, pts)
    seeds = json.loads(HURDLE_SEEDS.read_text())['dives'][dive]['anchors']
    out = {}
    for x in seeds:
        if x['source'] != 'HUMAN_GT' or x.get('ambiguous') or x.get('visibility', 'visible') != 'visible':
            continue
        pos = min(range(len(pts)), key=lambda i: abs(pts[i] - x['t_s']))
        local = pts[min(pos + 1, len(pts) - 1)] - pts[max(pos - 1, 0)]
        if abs(pts[pos] - x['t_s']) <= max(local / 2, 1e-6):
            out.setdefault(pos, (x['cx'], x['cy']))
    return out


def flight_frames(window, pts):
    t0, t1 = window['takeoff_s'] - PAD, window['water_contact_s'] + PAD
    fr = [i for i, t in enumerate(pts) if t0 <= t <= t1]
    return fr[0], fr[-1]


def path_eval(obs, kept, pts, anchors, flight):
    """Flight + full-action correspondence for an obs list [(pos, lat_idx)].
    Same semantics as r3.flight_correspondence / v1run.correspondence."""
    tr = {p: (kept[p][j][1], kept[p][j][2]) for p, j in obs}
    ov = hits = 0
    for fi, (ax, ay) in flight['anchors'].items():
        if fi in tr:
            ov += 1
            if math.hypot(tr[fi][0] - ax, tr[fi][1] - ay) <= f3.RADIUS:
                hits += 1
    nfl = len(flight['anchors'])
    pur = hits / ov if ov else None
    t0, t1 = flight['t0'] - PAD, flight['t1'] + PAD
    ob = sorted(pts[p] for p in tr if t0 <= pts[p] <= t1)
    b = [t0] + ob + [t1]
    gap = max(b2 - b1 for b1, b2 in zip(b, b[1:]))
    aov = ahits = 0
    for fi, (ax, ay) in anchors.items():
        if fi in tr:
            aov += 1
            if math.hypot(tr[fi][0] - ax, tr[fi][1] - ay) <= f3.RADIUS:
                ahits += 1
    cov = hits / nfl if nfl else 0.0
    subj = hits >= 2 and (pur or 0) >= .75
    return {'coverage': cov, 'purity': pur, 'hits': hits, 'overlap': ov,
            'off_subject': ov - hits, 'longest_gap_s': gap, 'is_subject': subj,
            'qualifies': bool(subj and cov >= COVER),
            'full_action_coverage': ahits / len(anchors) if anchors else 0.0,
            'full_action_purity': ahits / aov if aov else None}


def _key(e):
    return (e['qualifies'], e['coverage'], e['purity'] or 0.0, -e['off_subject'], -e['longest_gap_s'])


def best_of(items):
    """items: list of (meta, eval). Returns (meta, eval) of best or (None, None)."""
    if not items:
        return None, None
    return max(items, key=lambda it: _key(it[1]))


def guide(flight, lo, hi):
    """GT subject position per frame (raw coords), linear between anchors."""
    fa = sorted(flight['anchors'])
    g = {}
    for f in range(lo, hi + 1):
        prev = [a for a in fa if a <= f]
        nxt = [a for a in fa if a >= f]
        if prev and nxt:
            a, b = prev[-1], nxt[0]
            if a == b:
                g[f] = flight['anchors'][a]
            else:
                w = (f - a) / (b - a)
                g[f] = tuple((1 - w) * flight['anchors'][a][k] + w * flight['anchors'][b][k] for k in (0, 1))
        else:
            g[f] = flight['anchors'][prev[-1] if prev else nxt[0]]
    return g


def graph_oracle(cap, flight):
    """Evaluation-only best subject path through the frozen lattice under the
    exact V3 transition function. GT only selects among existing edges."""
    kept, kept_arr, pts = cap['kept'], cap['kept_arr'], cap['pts']
    wa, wb = flight['frames']
    ls = min(i for i, t in enumerate(pts) if t >= pts[wa] - ORACLE_LEAD_S)
    g = guide(flight, ls, wb)
    fl = flight['anchors']

    def gd(f, j):
        return math.hypot(kept[f][j][1] - g[f][0], kept[f][j][2] - g[f][1])

    def score(h):
        return (-h['hits'], h['off'], round(h['gsum'], 9), h['obs'])

    live, done = [], []
    for f in range(ls, wb + 1):
        nxt = []
        for h in live:
            succ, must = gated(h['lp'], h['lj'], h['lx'], h['ly'], h['vx'], h['vy'],
                               f, kept, kept_arr, pts)
            succ = sorted(succ, key=lambda s: (gd(f, s[0]), s[0]))[:ORACLE_SUCC]
            for j, _, nvx, nvy in succ:
                hit = off = 0
                if f in fl:
                    if math.hypot(kept[f][j][1] - fl[f][0], kept[f][j][2] - fl[f][1]) <= f3.RADIUS:
                        hit = 1
                    else:
                        off = 1
                nxt.append({'lp': f, 'lj': j, 'lx': kept_arr[f][j, 0], 'ly': kept_arr[f][j, 1],
                            'vx': nvx, 'vy': nvy, 'hits': h['hits'] + hit, 'off': h['off'] + off,
                            'gsum': h['gsum'] + gd(f, j), 'obs': h['obs'] + ((f, j),)})
            if not must:
                nxt.append({**h, 'gsum': h['gsum'] + ORACLE_SEED_R})
            elif not succ:
                done.append(h)
        for j in range(len(kept[f])):
            if gd(f, j) <= ORACLE_SEED_R:
                hit = off = 0
                if f in fl:
                    if math.hypot(kept[f][j][1] - fl[f][0], kept[f][j][2] - fl[f][1]) <= f3.RADIUS:
                        hit = 1
                    else:
                        off = 1
                nxt.append({'lp': f, 'lj': j, 'lx': kept_arr[f][j, 0], 'ly': kept_arr[f][j, 1],
                            'vx': 0.0, 'vy': 0.0, 'hits': hit, 'off': off, 'gsum': gd(f, j),
                            'obs': ((f, j),)})
        best = {}
        for h in nxt:
            k = (h['lp'], h['lj'], round(h['vx'], 3), round(h['vy'], 3))
            if k not in best or score(h) < score(best[k]):
                best[k] = h
        live = sorted(best.values(), key=score)[:ORACLE_BEAM]
    cands = live + done
    evals = [(h, path_eval(list(h['obs']), kept, pts, cap['anchors'], flight)) for h in cands]
    h, e = best_of(evals)
    return {'eval': e, 'obs': [list(o) for o in h['obs']] if h else [],
            'n_obs': len(h['obs']) if h else 0}


def link_feasibility(cap, flight):
    """State-independent edge diagnostics on consecutive-frame subject links:
    for each pair of adjacent frames (f, f+1) both with a lattice node within
    RADIUS of the GT guide, does ANY such node pair pass the frozen velocity
    caps and size tolerance? Also GT-guide kinematics in compensated coords."""
    kept, pts, off = cap['kept'], cap['pts'], cap['off']
    wa, wb = flight['frames']
    g = guide(flight, wa, wb)
    near = {f: [j for j in range(len(kept[f]))
                if math.hypot(kept[f][j][1] - g[f][0], kept[f][j][2] - g[f][1]) <= f3.RADIUS]
            for f in range(wa, wb + 1)}
    pairs = vel_block = size_block = passable = 0
    for f in range(wa, wb):
        if not near[f] or not near[f + 1]:
            continue
        pairs += 1
        dt = pts[f + 1] - pts[f]
        vok = sok = both = False
        for a in near[f]:
            for b in near[f + 1]:
                A, B = kept[f][a], kept[f + 1][b]
                vx, vy = (B[7] - A[7]) / dt, (B[8] - A[8]) / dt
                v_ok = (abs(vy) <= f3.V_MAX_CY_S + f3.r5.JITTER_C and abs(vx) <= f3.V_MAX_CX_S + f3.r5.JITTER_C
                        and math.hypot(vx, vy) <= f3.VEL_MAX)
                s_ok = abs(math.log(max(B[3] * B[4], 1e-9) / max(A[3] * A[4], 1e-9))) <= f3.SIZE_TOL
                vok |= v_ok
                sok |= s_ok
                both |= v_ok and s_ok
        vel_block += not vok
        size_block += not sok
        passable += both
    # GT anchor-to-anchor kinematics (compensated), consecutive anchors only
    fa = sorted(flight['anchors'])
    sp = []
    for a, b in zip(fa, fa[1:]):
        dt = pts[b] - pts[a]
        (ax, ay), (bx, by) = flight['anchors'][a], flight['anchors'][b]
        vx = ((bx - off[b][0]) - (ax - off[a][0])) / dt
        vy = ((by - off[b][1]) - (ay - off[a][1])) / dt
        sp.append((math.hypot(vx, vy), abs(vx), abs(vy), dt))
    return {'adjacent_subject_pairs': pairs, 'pairs_passable': passable,
            'pairs_velocity_blocked': vel_block, 'pairs_size_blocked': size_block,
            'gt_max_speed': max((s[0] for s in sp), default=None),
            'gt_max_abs_vy': max((s[2] for s in sp), default=None),
            'gt_max_abs_vx': max((s[1] for s in sp), default=None),
            'gt_steps_over_VEL_MAX': sum(s[0] > f3.VEL_MAX for s in sp),
            'gt_steps': len(sp)}


def audit_dive(dive):
    t_start = time.monotonic()
    group = next(g for g, ids in v1run.GROUPS.items() if dive in ids)
    raw = json.loads(v1run.CACHES[group].read_text())
    doc = raw['dives'][dive]
    fps = float(doc['fps'])
    frames = f3.inference_view(doc['frames'])
    proxy = doc.get('proxy_sha256')
    del raw
    # ---- GT-free stage capture (frozen before any GT is loaded) ----
    cap = capture(frames, fps)
    out = cap['output']
    out['clip_id'] = dive
    out['frame_pts'] = [f['pts_s'] for f in doc['frames']]
    out['input_proxy_sha256'] = proxy
    ref_path = ROOT.parent / 'diveanalyzer-flight-v3/runs/flight_anchored_traj_v3' / f'{dive}.json'
    ref = json.loads(ref_path.read_text())
    identical = json.dumps(ref, sort_keys=True) == json.dumps(out, sort_keys=True)
    lattice_sig = hashlib.sha256(json.dumps(
        [[list(c[:6]) for c in fr] for fr in cap['kept']]).encode()).hexdigest()
    pool_sig = hashlib.sha256(json.dumps([list(map(list, p.obs)) for p in cap['pool']]).encode()).hexdigest()
    rank_sig = hashlib.sha256(json.dumps([[round(c[0], 9), c[2], c[3]] for c in cap['cores']]).encode()).hexdigest()
    # diverse[:K] must equal the retained tracks (Q order, core spans)
    pts = cap['pts']
    for t, d in zip(out['tracks'], cap['diverse'][:f3.FINAL_TOP_K]):
        assert t['path_score'] == round(d[0], 6)
        assert t['flight_core_interval'] == [pts[d[1][d[2]][0]], pts[d[1][d[3]][0]]]
    res = {'dive': dive, 'group': group,
           'v3_output_identical_to_frozen_artifact': identical,
           'lattice_sha256': lattice_sig, 'pool_sha256': pool_sig, 'core_rank_sha256': rank_sig,
           'lattice': out['lattice'],
           'starts': cap['start_info'],
           'starts_eligible': sum(s['eligible'] for s in cap['start_info']),
           'starts_survived': sum(s['survived_to_clip_end'] for s in cap['start_info']),
           'beam_final_paths': len(cap['beam_final']), 'pool_paths': len(cap['pool']),
           'cores': len(cap['cores']), 'diverse_cores': len(cap['diverse']),
           'suppressed_cores': len(cap['suppressed_by'])}
    # ---- GT-only evaluation (after freeze) ----
    window = r3.flight_window(dive, out['frame_pts'])
    res['flight_window'] = window
    if window['status'] != 'SCORED':
        res['runtime_s'] = time.monotonic() - t_start
        return res
    kept = cap['kept']
    # frozen stage object lists [(meta, obs)] -- built once, GT-free
    pool_idx = {id(p): k for k, p in enumerate(cap['pool'])}
    div_rank = {d[5]: r for r, d in enumerate(cap['diverse'], 1)}
    st = {'S3a': [({'start': p.obs[0][0], 'n_obs': len(p.obs)}, p.obs) for p in cap['beam_final']],
          'S3': [({'pool_index': k, 'start': p.obs[0][0], 'n_obs': len(p.obs)}, p.obs)
                 for k, p in enumerate(cap['pool'])],
          'S3c': [], 'S5cf': [], 'S6': []}
    for ci, (q, qp, i, j, parts) in enumerate(cap['cores']):
        sup = cap['suppressed_by'].get(ci)
        st['S3c'].append(({'core_rank_by_Q': ci + 1, 'Q': q, 'pool_index': pool_idx[id(qp)],
                           'core_span_s': [pts[qp.obs[i][0]], pts[qp.obs[j][0]]],
                           'diverse_rank': div_rank.get(ci),
                           'suppressed_by_diverse_rank': sup[0] + 1 if sup else None,
                           'suppression_agreement': sup[1] if sup else None,
                           '_full': qp.obs}, qp.obs[i:j + 1]))
        core_obs = qp.obs[i:j + 1]
        (a1, b1), (a2, b2) = core_obs[0], core_obs[1]
        ddt = pts[a2] - pts[a1]
        vel0 = ((kept[a2][b2][7] - kept[a1][b1][7]) / max(ddt, 1e-9),
                (kept[a2][b2][8] - kept[a1][b1][8]) / max(ddt, 1e-9))
        full = f3.extend_core(core_obs, kept, cap['kept_arr'], pts, vel0)
        st['S5cf'].append(({'core_rank_by_Q': ci + 1, 'diverse_rank': div_rank.get(ci)}, full))
        if div_rank.get(ci) and div_rank[ci] <= f3.FINAL_TOP_K:
            st['S6'].append(({'path_rank': div_rank[ci], 'core_span_s': [pts[core_obs[0][0]], pts[core_obs[-1][0]]]}, full))
    st['S6'].sort(key=lambda x: x[0]['path_rank'])
    assert len(st['S6']) == len(out['tracks'])
    for (m, obs), t in zip(st['S6'], out['tracks']):
        assert [p for p, _ in obs] == [x['frame_index'] for x in t['trajectory']]
    res['Q_rank5'] = cap['diverse'][min(len(cap['diverse']), f3.FINAL_TOP_K) - 1][0] if cap['diverse'] else None
    authorities = {'FROZEN_V3_AUTHORITY': v1run.subject_anchors(dive, out['frame_pts']),
                   'STRICT_HUMAN_SEEDS': strict_human_anchors(dive, out['frame_pts'])}
    res['authorities'] = {}
    for aname, anchors in authorities.items():
        fl = {fi: v for fi, v in anchors.items()
              if window['takeoff_s'] - PAD <= out['frame_pts'][fi] <= window['water_contact_s'] + PAD}
        r = {'flight_anchor_count': len(fl), 'visible_subject_anchors': len(anchors),
             'flight_anchor_frames': sorted(fl)}
        res['authorities'][aname] = r
        if not fl:
            r['status'] = 'NO_FLIGHT_AUTHORITY'
            continue
        r['status'] = 'SCORED'
        flight = {'anchors': fl, 't0': window['takeoff_s'], 't1': window['water_contact_s'],
                  'frames': flight_frames(window, pts)}
        cap['anchors'] = anchors
        r['S0_raw_union'] = sum(any(math.hypot(c['cx'] - a[0], c['cy'] - a[1]) <= f3.RADIUS
                                    for c in cap['clean'][fi]['c']) for fi, a in fl.items()) / len(fl)
        r['S1_capped_lattice_union'] = sum(any(math.hypot(c[1] - a[0], c[2] - a[1]) <= f3.RADIUS
                                               for c in kept[fi]) for fi, a in fl.items()) / len(fl)
        r['S2_graph_oracle'] = graph_oracle(cap, flight)
        r['link_feasibility'] = link_feasibility(cap, flight)
        ev = {k: [(m, path_eval(o, kept, pts, anchors, flight)) for m, o in v] for k, v in st.items()}

        def pack(meta, e):
            return None if e is None else {**{k: v for k, v in meta.items() if k != '_full'}, **e}
        r['S3a_beam_final_best'] = pack(*best_of(ev['S3a']))
        r['S3_pool_path_best'] = pack(*best_of(ev['S3']))
        bm, be = best_of(ev['S3c'])
        r['S3c_pool_core_best'] = pack(bm, be)
        if bm is not None:
            r['S3c_pool_core_best']['full_path_eval'] = path_eval(bm['_full'], kept, pts, anchors, flight)
        r['S3c_pool_cores_qualifying'] = sum(e['qualifies'] for _, e in ev['S3c'])
        r['S3c_pool_cores_qualifying_ranks'] = [m['core_rank_by_Q'] for m, e in ev['S3c'] if e['qualifies']][:30]
        r['S3c_qualifying_diverse_or_suppressed'] = [
            {'core_rank_by_Q': m['core_rank_by_Q'], 'diverse_rank': m['diverse_rank'],
             'suppressed_by_diverse_rank': m['suppressed_by_diverse_rank'],
             'suppression_agreement': m['suppression_agreement'], 'Q': m['Q'],
             'coverage': e['coverage'], 'purity': e['purity']}
            for m, e in ev['S3c'] if e['qualifies']][:30]
        r['S3_pool_paths_qualifying'] = sum(e['qualifies'] for _, e in ev['S3'])
        r['S3a_beam_final_qualifying'] = sum(e['qualifies'] for _, e in ev['S3a'])
        tk = [(m, e) for m, e in ev['S3c'] if m['diverse_rank'] and m['diverse_rank'] <= f3.FINAL_TOP_K]
        r['S4_f0_topk_core_best'] = pack(*best_of(tk))
        r['S4_f0_topk_cores'] = [{**{k: v for k, v in m.items() if k != '_full'},
                                  **{k: e[k] for k in ('coverage', 'purity', 'hits', 'off_subject')}}
                                 for m, e in sorted(tk, key=lambda x: x[0]['diverse_rank'])]
        r['S5cf_f1_all_cores_best'] = pack(*best_of(ev['S5cf']))
        r['S5cf_f1_all_cores_qualifying'] = sum(e['qualifies'] for _, e in ev['S5cf'])
        r['S6_f1_final_best'] = pack(*best_of(ev['S6']))
        r['S6_f1_final_tracks'] = [{**m, **e} for m, e in ev['S6']]
        if aname == 'FROZEN_V3_AUTHORITY':
            # identity with the frozen V3 evaluator on the actual tracks
            for (m, e), t in zip(ev['S6'], out['tracks']):
                fe = r3.flight_correspondence(t, anchors, window, out['frame_pts'])
                assert abs(fe['matched_anchor_coverage'] - e['coverage']) < 1e-12
                assert fe['purity'] == e['purity']
                assert abs(r3.longest_missing_gap(t, window, out['frame_pts']) - e['longest_gap_s']) < 1e-9
                assert abs(v1run.correspondence(t, anchors)['matched_anchor_coverage'] - e['full_action_coverage']) < 1e-12
    res['runtime_s'] = time.monotonic() - t_start
    return res


def run(dives, workers):
    OUT.mkdir(parents=True, exist_ok=True)
    with Pool(workers) as p:
        for r in p.imap_unordered(audit_dive, dives):
            (OUT / f"{r['dive']}.json").write_text(json.dumps(r, indent=1, sort_keys=True, default=float) + '\n')
            print(r['dive'], 'identical', r['v3_output_identical_to_frozen_artifact'],
                  'rt', round(r['runtime_s']), flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('dives', nargs='*', default=v1run.COHORT)
    ap.add_argument('--workers', type=int, default=4)
    a = ap.parse_args()
    run(a.dives, a.workers)
