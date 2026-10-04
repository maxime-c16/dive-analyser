"""F0 frame-level flight lattice + F1 flight-seed bidirectional extension.

Identity-free, GT-free, appearance-free. Nodes are frozen D5 floor
candidates (frame PTS, bbox, confidence); no pre-existing PersonTrack
membership is required for decoding. PersonTrack IDs appear nowhere in
inference (kept only as evaluation-side diagnostics by the runner).

F0: temporally stratified multi-start beam over frame-level candidates
    with an explicit NULL (no-observation) state; flight cores are
    contiguous subsegments ranked by a flight-motion objective Q that
    rewards coherent high-motion arcs (excursion, descent progression,
    smoothness, compactness) and penalizes static occupancy and missing
    observations. Long static preparation cannot score well by design.

F1: each frozen F0 core is extended backward (prep recovery) and forward
    (entry/post recovery) with generic continuity only. Final order is
    the F0 Q order; extension is subordinate and never reranks cores.

No GT, no identity, no appearance, no media, no learning. Deterministic.
"""
from __future__ import annotations

import hashlib
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'landmark_pilot'))
import r5_tracklets_v1 as r5
import subject_reference_acquisition_v2 as v2
import phase_subject_candidate_quality_v3 as v3
# NOTE: frozen Event Logic V3-C0 enters only via multi_track_action_v1.describe
# (post-selection output replay); this module never calls it during decoding.
# Only its frozen interpolation limit is reused as the NULL-run bound.
from proposer_event_logic_v3_c0 import PARAMS_V3C0
import multi_track_action_v1 as base

F3_VERSION = 'FLIGHT_ANCHORED_TRAJECTORY_V3_1_BUGFIX_SUSTAINED_CANDIDATE'
F0_BEAM = 'F0_FRAME_LEVEL_FLIGHT_LATTICE'
F1_BEAM = 'F1_FLIGHT_SEED_BIDIRECTIONAL_EXTENSION'

# --- Reused frozen scales (no new thresholds) --------------------------------
RADIUS = v3.SUPPORT_RADIUS  # 0.06 generic agreement distance scale
NULL_MAX_S = PARAMS_V3C0['interp_max_gap_s']  # 0.30 frozen interp limit
V_MAX_CY_S = r5.V_MAX_CY_S  # 1.5 frozen rate cap
V_MAX_CX_S = r5.V_MAX_CX_S  # 1.2 frozen rate cap
SIZE_TOL = r5.LOG_SIZE_MAX + r5.JITTER_S  # frozen size agreement
VEL_ALPHA = r5.DEP_VEL_ALPHA  # 0.35 frozen EWMA velocity update
GATE_BASE = r5.DEP_GATE_BASE  # 0.05 frozen base match radius
GATE_VEL = r5.DEP_GATE_VEL  # 1.0 frozen velocity-proportional radius
VEL_MAX = r5.DEP_VEL_MAX  # 1.4 frozen absolute velocity cap
ACC_NORM = r5.DEP_ACC_MAX  # 3.5 frozen acceleration normalizer
RANGE_NORM = 0.5  # frozen V2 RANGE_SCALE_CY vertical normalization

# --- Preregistered F3 constants (protocol-frozen before GT evaluation) --------
FRAME_CAP = 50  # per-frame candidate cap by confidence (compute bound)
MOVER_KEEP = 10  # extra per-frame candidates kept by forward motion (GT-free)
SEED_TOP = 12  # seed candidates per start frame (top confidence)
SEED_MOVERS = 6  # extra seeds per start frame (top movers)
START_STRIDE = 30  # frames between temporal strata (~0.5-1.0 s)
SEARCH_BEAM_WIDTH = 64  # live hypotheses per start (search, not product)
STATIC_SLOTS = 32  # beam slots open to all paths, ranked by cost
DYNAMIC_SLOTS = 32  # beam slots reserved for latched movers, ranked by cost
SPEED_LATCH = 0.15  # EWMA speed (norm/s) latching a path as a mover
LATCH_GRACE_FRAMES = 3  # young paths are dynamic-eligible before latching
W_DYN = 1.0  # per-frame motion advantage in dynamic-slot ranking: sustained
# movers outrank stationary paths for dynamic slots by construction, so
# fast-motion hypotheses survive regardless of static competition.
POOL_PER_START = 8  # paths kept per start for core extraction
MAX_SUCC_PER_PATH = 6  # successor fan-out per path per frame
NULL_COST = 0.20  # per-frame cost of the NULL (no-observation) state:
# above a good match (residual ~0.02-0.05 + small size/accel terms) so any
# plausible continuation is preferred, below teleport/hijack jumps (~0.2+)
# so bounded true disappearances stay representable without hijacking.
W_SIZE = 0.5  # box size-change term weight in transition cost
W_ACC = 0.10  # acceleration-change term weight in transition cost
W_CONF_CONT = 0.05  # confidence support weight in transition cost
W_MOVE = 0.05  # coherent-motion bonus weight in transition cost (GT-free)
MOVE_NORM = 0.8  # speed (norm units/s) at which the motion bonus saturates
FLOW_TOP = 20  # top-confidence candidates voting for per-step camera flow
CORE_MIN_S = 0.30  # shortest meaningful flight core (domain envelope)
CORE_MAX_S = 3.00  # longest flight core (generous physics envelope)
W_EXCURSION = 1.0  # flight objective: vertical excursion weight
W_DESCENT = 0.5  # flight objective: descent-progression weight
W_LATERAL = 0.25  # flight objective: coherent lateral displacement weight
W_SMOOTH = 0.25  # flight objective: acceleration penalty weight
W_NULL = 1.0  # flight objective: missing-observation fraction penalty
W_STATIC = 0.5  # flight objective: static-occupancy fraction penalty
W_CONF = 0.10  # flight objective: mean-confidence support weight
STATIC_SPEED = 0.05  # norm-center speed below which a step is static
FINAL_TOP_K = 5  # retained product tracks (1-5 product shape)
DUP_AGREE = 0.95  # near-duplicate suppression agreement (V2 convention)

PROTOCOL_CONSTANTS = {
    'F3_VERSION': F3_VERSION,
    'FRAME_CAP': FRAME_CAP, 'MOVER_KEEP': MOVER_KEEP,
    'SEED_TOP': SEED_TOP, 'SEED_MOVERS': SEED_MOVERS,
    'START_STRIDE': START_STRIDE,
    'SEARCH_BEAM_WIDTH': SEARCH_BEAM_WIDTH, 'STATIC_SLOTS': STATIC_SLOTS,
    'DYNAMIC_SLOTS': DYNAMIC_SLOTS, 'SPEED_LATCH': SPEED_LATCH,
    'LATCH_GRACE_FRAMES': LATCH_GRACE_FRAMES, 'W_DYN': W_DYN,
    'POOL_PER_START': POOL_PER_START,
    'MAX_SUCC_PER_PATH': MAX_SUCC_PER_PATH, 'NULL_COST': NULL_COST,
    'NULL_MAX_S': NULL_MAX_S, 'W_SIZE': W_SIZE, 'W_ACC': W_ACC,
    'W_CONF_CONT': W_CONF_CONT, 'W_MOVE': W_MOVE, 'MOVE_NORM': MOVE_NORM,
    'FLOW_TOP': FLOW_TOP,
    'CORE_MIN_S': CORE_MIN_S,
    'CORE_MAX_S': CORE_MAX_S, 'W_EXCURSION': W_EXCURSION,
    'W_DESCENT': W_DESCENT, 'W_LATERAL': W_LATERAL, 'W_SMOOTH': W_SMOOTH,
    'W_NULL': W_NULL, 'W_STATIC': W_STATIC, 'W_CONF': W_CONF,
    'STATIC_SPEED': STATIC_SPEED, 'FINAL_TOP_K': FINAL_TOP_K,
    'DUP_AGREE': DUP_AGREE,
    'reused_frozen': {'RADIUS': RADIUS, 'V_MAX_CY_S': V_MAX_CY_S,
                      'V_MAX_CX_S': V_MAX_CX_S, 'SIZE_TOL': SIZE_TOL,
                      'VEL_ALPHA': VEL_ALPHA, 'GATE_BASE': GATE_BASE,
                      'GATE_VEL': GATE_VEL, 'VEL_MAX': VEL_MAX,
                      'ACC_NORM': ACC_NORM, 'RANGE_NORM': RANGE_NORM},
}


def inference_view(frames):
    """Same explicit whitelist as V1/V2; strips cache annotations."""
    return base.inference_view(frames)


def compute_flow(frames, pts):
    """GT-free per-step camera-flow estimate (R5 flow-compensation analogue).

    flow[f] = robust component-wise median velocity of the top-FLOW_TOP
    confidence candidates' nearest-forward displacement between frame f
    and f+1. off[f] = cumulative flow offset at frame f (off[0] = 0).
    Compensated coordinates (x - off) measure motion relative to the
    world background, so a camera-tracked diver keeps its true excursion
    while static crowds collapse to near-zero.
    """
    n = len(frames)
    flow = [(0.0, 0.0)] * n
    for f in range(n - 1):
        dt = pts[f + 1] - pts[f]
        if dt <= 1e-9 or not frames[f]['c'] or not frames[f + 1]['c']:
            continue
        a = frames[f]['c']
        b = frames[f + 1]['c']
        top = sorted(range(len(a)), key=lambda k: -a[k]['conf'])[:FLOW_TOP]
        dxs, dys = [], []
        for k in top:
            j = min(range(len(b)),
                    key=lambda m: (b[m]['cx'] - a[k]['cx']) ** 2
                    + (b[m]['cy'] - a[k]['cy']) ** 2)
            dxs.append((b[j]['cx'] - a[k]['cx']) / dt)
            dys.append((b[j]['cy'] - a[k]['cy']) / dt)
        dxs.sort()
        dys.sort()
        m = len(dxs) // 2
        med = (lambda v: v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2)
        flow[f] = (med(dxs), med(dys))
    off = [(0.0, 0.0)] * n
    ox = oy = 0.0
    for f in range(n):
        off[f] = (ox, oy)
        if f + 1 < n:
            dt = max(pts[f + 1] - pts[f], 1e-9)
            ox += flow[f][0] * dt
            oy += flow[f][1] * dt
    return flow, off


def build_frame_lattice(frames, off):
    """Deterministic per-frame candidate cap. Returns (kept, full_counts).

    kept[f] = list of (orig_idx, cx, cy, bw, bh, conf, mover_rank, ccx, ccy)
    with (ccx, ccy) flow-compensated coordinates; dynamics (gates, speeds,
    Q) use compensated coordinates, outputs use raw boxes. Mover ranking
    is flow-relative nearest-forward displacement per second.
    """
    n = len(frames)
    pts = [f['pts_s'] for f in frames]
    kept, full_counts = [], []
    for f in range(n):
        cf = frames[f]['c']
        order = sorted(range(len(cf)),
                       key=lambda k: (-cf[k]['conf'], cf[k]['cx'],
                                      cf[k]['cy'], cf[k]['bw'], cf[k]['bh']))
        full_counts.append(len(order))
        # flow-relative forward motion from the full floor
        motion = {}
        if f + 1 < n and cf:
            dt = max(pts[f + 1] - pts[f], 1e-9)
            nxt = frames[f + 1]['c']
            ox, oy = off[f]
            ox1, oy1 = off[f + 1]
            for k in range(len(cf)):
                ckx, cky = cf[k]['cx'] - ox, cf[k]['cy'] - oy
                best = min(math.hypot((d['cx'] - ox1) - ckx,
                                      (d['cy'] - oy1) - cky) for d in nxt) \
                    if nxt else 0.0
                motion[k] = best / dt
        mover_order = sorted(motion, key=lambda k: (-motion[k], -cf[k]['conf'],
                                                   cf[k]['cx'], cf[k]['cy']))
        mover_rank = {k: r for r, k in enumerate(mover_order[:MOVER_KEEP])}
        conf_set = set(order[:FRAME_CAP])
        conf_rank = {k: r for r, k in enumerate(order)}
        base = conf_set | set(mover_rank)
        # deterministic lattice order: conf members first, then movers
        lat = sorted(base, key=lambda k: (0 if k in conf_set else 1,
                                          conf_rank[k] if k in conf_set
                                          else mover_rank[k]))
        ox, oy = off[f]
        kept.append([(k, cf[k]['cx'], cf[k]['cy'], cf[k]['bw'],
                      cf[k]['bh'], cf[k]['conf'], mover_rank.get(k),
                      cf[k]['cx'] - ox, cf[k]['cy'] - oy) for k in lat])
    return kept, full_counts


def _frame_arrays(kept):
    """Numpy views per frame for vectorized gating (compensated coords)."""
    arr = []
    for lst in kept:
        if lst:
            a = np.array([[c[7], c[8], c[3], c[4], c[5]] for c in lst],
                         dtype=np.float64)
        else:
            a = np.zeros((0, 5), dtype=np.float64)
        arr.append(a)
    return arr


class _Path:
    __slots__ = ('obs', 'lx', 'ly', 'vx', 'vy', 'cost', 'maxspeed', 'motion')

    def __init__(self, obs, lx, ly, vx, vy, cost, maxspeed=0.0, motion=0.0):
        self.obs = obs  # list of (frame_pos, lattice_idx)
        self.lx, self.ly = lx, ly  # last observed center
        self.vx, self.vy = vx, vy  # EWMA velocity (norm units / s)
        self.cost = cost
        self.maxspeed = maxspeed  # max EWMA speed latched so far
        self.motion = motion  # BF-D: sustained motion credit (observed frames)


def _prune_dual(nxt, age):
    """Dual-population retention: static slots (all paths by cost) plus
    dynamic slots reserved for latched movers, ranked by cost with a
    per-frame motion advantage. Fast-motion hypotheses can never be
    eliminated by stationary ones alone."""
    nxt.sort(key=lambda q: (round(q.cost, 9),
                            tuple(o for o in q.obs)))
    uniq, seenkey = [], set()
    for q in nxt:
        k = tuple(o for o in q.obs)
        if k in seenkey:
            continue
        seenkey.add(k)
        uniq.append(q)
    stat = uniq[:STATIC_SLOTS]
    kept_keys = {tuple(o for o in q.obs) for q in stat}
    dyn = [q for q in uniq
           if tuple(o for o in q.obs) not in kept_keys
           and (q.maxspeed >= SPEED_LATCH or age <= LATCH_GRACE_FRAMES)]
    # BF-D: sustained-motion advantage accrues per OBSERVED frame from the
    # current EWMA speed (not age x max-ever speed, which latches spikes).
    dyn.sort(key=lambda q: (round(q.cost - W_DYN * q.motion, 9),
                            tuple(o for o in q.obs)))
    return stat + dyn[:DYNAMIC_SLOTS]


def _harvest(live, pool, seen, pts, t_lo=None):
    """Frozen V3 pool triage (static head + mover head). BF-C: optionally
    truncates each path to observations at/after t_lo (the recent core
    horizon) so a snapshot harvest keeps cores that later beam competition
    would overwrite."""
    live = sorted(live, key=lambda q: (round(q.cost / max(len(q.obs), 1), 9),
                                       tuple(o for o in q.obs)))
    dyn = [q for q in live if q.maxspeed >= SPEED_LATCH]
    stat = [q for q in live if q.maxspeed < SPEED_LATCH]
    half = POOL_PER_START // 2
    for q in (dyn[:half] + stat[:POOL_PER_START - min(len(dyn), half)]):
        if t_lo is not None:
            obs = [o for o in q.obs if pts[o[0]] >= t_lo]
            q = _Path(obs, q.lx, q.ly, q.vx, q.vy, q.cost, q.maxspeed, q.motion)
        if len(q.obs) >= 3:
            k = tuple(o for o in q.obs)
            if k not in seen:
                seen.add(k)
                pool.append(q)


def _extend_starts(kept, kept_arr, pts, starts):
    """Stratified multi-start beam. Returns completed path dicts."""
    n = len(pts)
    pool = []
    seen = set()
    for s in starts:
        if s >= n:
            continue
        if pts[-1] - pts[s] < CORE_MIN_S:
            continue  # cannot host a flight core
        live = []
        seeded = set()
        for j in range(min(SEED_TOP, len(kept[s]))):
            cx, cy = kept[s][j][7], kept[s][j][8]
            p = _Path([(s, j)], cx, cy, 0.0, 0.0,
                      -W_CONF_CONT * kept[s][j][5])
            live.append(p)
            seeded.add(kept[s][j][0])
        movers = [(kept[s][j][6], j) for j in range(len(kept[s]))
                  if kept[s][j][6] is not None and kept[s][j][0] not in seeded]
        movers.sort()
        for _, j in movers[:SEED_MOVERS]:
            cx, cy = kept[s][j][7], kept[s][j][8]
            p = _Path([(s, j)], cx, cy, 0.0, 0.0,
                      -W_CONF_CONT * kept[s][j][5])
            live.append(p)
        for f in range(s + 1, n):
            nxt = []
            arr = kept_arr[f]
            pf = pts[f]
            for p in live:
                lp, _ = p.obs[-1]
                dt = pf - pts[lp]
                must_match = dt > NULL_MAX_S + 1e-9
                px = p.lx + p.vx * dt
                py = p.ly + p.vy * dt
                speed = math.hypot(p.vx, p.vy)
                best = []
                if len(arr):
                    dx = arr[:, 0] - px
                    dy = arr[:, 1] - py
                    resid = np.hypot(dx, dy)
                    gate = GATE_BASE + GATE_VEL * speed * dt
                    ok = resid <= gate
                    if dt > 0:
                        vx_new = (arr[:, 0] - p.lx) / dt
                        vy_new = (arr[:, 1] - p.ly) / dt
                        # BF-A: caps are physical per-second rates; detector
                        # jitter is a per-step POSITION allowance (GATE_BASE),
                        # not a per-second velocity allowance.
                        ddx = np.abs(arr[:, 0] - p.lx)
                        ddy = np.abs(arr[:, 1] - p.ly)
                        ok = ok & (ddy <= V_MAX_CY_S * dt + GATE_BASE) \
                            & (ddx <= V_MAX_CX_S * dt + GATE_BASE) \
                            & (np.hypot(ddx, ddy) <= VEL_MAX * dt + GATE_BASE)
                    else:
                        vx_new = np.zeros(len(arr))
                        vy_new = np.zeros(len(arr))
                    # frozen size agreement vs last observed box
                    lrow = kept[p.obs[-1][0]][p.obs[-1][1]]
                    larea = max(lrow[3] * lrow[4], 1e-9)
                    area = np.maximum(arr[:, 2] * arr[:, 3], 1e-9)
                    size = np.abs(np.log(area / larea))
                    ok = ok & (size <= SIZE_TOL)
                    idx = np.nonzero(ok)[0]
                    if len(idx):
                        acc = np.hypot(vx_new[idx] - p.vx,
                                       vy_new[idx] - p.vy) / max(dt, 1e-6)
                        acc_pen = np.minimum(acc / ACC_NORM, 2.0)
                        spd_new = np.hypot(vx_new[idx], vy_new[idx])
                        spd_old = math.hypot(p.vx, p.vy)
                        if spd_old < STATIC_SPEED or np.all(spd_new < STATIC_SPEED):
                            agree = np.where(spd_new >= STATIC_SPEED, 1.0, 0.0)
                        else:
                            cos = (vx_new[idx] * p.vx + vy_new[idx] * p.vy) \
                                / np.maximum(spd_new * spd_old, 1e-9)
                            agree = np.maximum(0.0, cos)
                        move_bonus = (np.minimum(spd_new, MOVE_NORM)
                                      / MOVE_NORM * agree)
                        costs = (resid[idx] + W_SIZE * size[idx]
                                 + W_ACC * acc_pen
                                 - W_CONF_CONT * arr[idx, 4]
                                 - W_MOVE * move_bonus)
                        order = np.argsort(costs, kind='stable')[:MAX_SUCC_PER_PATH]
                        for r in order:
                            j = int(idx[int(r)])
                            nvx = (VEL_ALPHA * float(vx_new[j])
                                   + (1 - VEL_ALPHA) * p.vx)
                            nvy = (VEL_ALPHA * float(vy_new[j])
                                   + (1 - VEL_ALPHA) * p.vy)
                            q = _Path(p.obs + [(f, j)], float(arr[j, 0]),
                                      float(arr[j, 1]), nvx, nvy,
                                      p.cost + float(costs[int(r)]),
                                      max(p.maxspeed, math.hypot(nvx, nvy)),
                                      p.motion + min(math.hypot(nvx, nvy), MOVE_NORM) / MOVE_NORM)
                            best.append(q)
                if not must_match:
                    q = _Path(list(p.obs), p.lx, p.ly, p.vx, p.vy,
                              p.cost + NULL_COST, p.maxspeed, p.motion)
                    best.append(q)
                nxt.extend(best)
            if not nxt:
                live = []
                break
            live = _prune_dual(nxt, f - s)
            if False:  # BF-C disabled in this attribution variant
                # BF-C snapshot: horizon = one stride + longest core
                t_lo = pts[max(f - START_STRIDE, s)] - CORE_MAX_S
                _harvest(live, pool, seen, pts, t_lo)
        live.sort(key=lambda q: (round(q.cost / max(len(q.obs), 1), 9),
                                 tuple(o for o in q.obs)))
        # pool triage preserves both populations: static head + mover head
        dyn = [q for q in live if q.maxspeed >= SPEED_LATCH]
        stat = [q for q in live if q.maxspeed < SPEED_LATCH]
        half = POOL_PER_START // 2
        for q in (dyn[:half] + stat[:POOL_PER_START - min(len(dyn), half)]):
            if len(q.obs) >= 3:
                k = tuple(o for o in q.obs)
                if k not in seen:
                    seen.add(k)
                    pool.append(q)
    return pool


def extract_flight_core(path, kept, pts):
    """Best-Q contiguous subsegment with duration in [CORE_MIN_S, CORE_MAX_S].

    Vectorized expanding-window scan per start observation. Returns
    (Q, i, j, parts) with obs indices i..j, or None if no window qualifies.
    """
    obs = path.obs
    m = len(obs)
    if m < 2:
        return None
    pos = np.array([o[0] for o in obs])
    cy = np.array([kept[o[0]][o[1]][8] for o in obs])
    cx = np.array([kept[o[0]][o[1]][7] for o in obs])
    conf = np.array([kept[o[0]][o[1]][5] for o in obs])
    t = np.array([pts[o[0]] for o in obs])
    # per-step speeds and accelerations (time-based)
    dt = np.diff(t)
    dt = np.where(dt > 1e-9, dt, 1e-9)
    step_dist = np.hypot(np.diff(cx), np.diff(cy))
    speed = step_dist / dt
    acc = np.abs(np.diff(speed)) / np.maximum(dt[1:], 1e-9)
    best = None
    for i in range(m - 1):
        dur_ok = (t - t[i])
        valid = np.nonzero((dur_ok >= CORE_MIN_S) & (dur_ok <= CORE_MAX_S))[0]
        valid = valid[valid > i]
        if not len(valid):
            continue
        # expanding max/min over cy/cx from i
        cymx = np.maximum.accumulate(cy[i:])
        cymn = np.minimum.accumulate(cy[i:])
        cxmx = np.maximum.accumulate(cx[i:])
        cxmn = np.minimum.accumulate(cx[i:])
        rel = valid - i
        excursion = (cymx[rel] - cymn[rel]) / RANGE_NORM
        descent = np.maximum(0.0, cy[valid] - cy[i]) / RANGE_NORM
        lateral = np.abs(cx[valid] - cx[i]) / RANGE_NORM
        nobs = rel + 1
        # frame positions are dense indices into pts, so span+1 works
        nframes = pos[valid] - pos[i] + 1
        null_frac = 1.0 - nobs / np.maximum(nframes, 1)
        # smoothness over steps i..j-1 (acc has m-2 entries; guard the tail)
        acc_mean = np.array([float(np.mean(acc[i:k])) if k > i and i < len(acc)
                             and len(acc[i:k]) else 0.0 for k in valid])
        smooth_pen = np.minimum(acc_mean / ACC_NORM, 2.0)
        stat = np.array([float(np.mean(speed[i:k] < STATIC_SPEED)) if k > i
                         else 0.0 for k in valid])
        mean_conf = np.array([float(np.mean(conf[i:k + 1])) for k in valid])
        q = (W_EXCURSION * excursion + W_DESCENT * descent
             + W_LATERAL * lateral - W_SMOOTH * smooth_pen
             - W_NULL * null_frac - W_STATIC * stat + W_CONF * mean_conf)
        b = int(np.argmax(q))
        if best is None or float(q[b]) > best[0]:
            j = int(valid[b])
            parts = {'excursion': float(excursion[b]),
                     'descent': float(descent[b]),
                     'lateral': float(lateral[b]),
                     'smooth_pen': float(smooth_pen[b]),
                     'null_frac': float(null_frac[b]),
                     'static_frac': float(stat[b]),
                     'mean_conf': float(mean_conf[b]),
                     'duration_s': float(t[j] - t[i]),
                     'n_obs': int(nobs[b]), 'n_frames': int(nframes[b])}
            best = (float(q[b]), i, j, parts)
    return best


def _agree(a_obs, a_kept, b_obs, b_kept):
    """Box-agreement fraction over common observed frames."""
    am = {p: (a_kept[p][j][1], a_kept[p][j][2]) for p, j in a_obs}
    bm = {p: (b_kept[p][j][1], b_kept[p][j][2]) for p, j in b_obs}
    common = set(am) & set(bm)
    if not common:
        return 0.0
    hit = sum(math.hypot(am[p][0] - bm[p][0], am[p][1] - bm[p][1]) <= RADIUS
              for p in common)
    return hit / len(common)


def extend_core(core_obs, kept, kept_arr, pts, vel0):
    """F1 greedy bidirectional continuity rollout from a frozen core.

    Returns (full_obs, pre_span, post_span). Rank-subordinate: no scoring.
    """
    n = len(pts)
    pos2idx = {p: j for p, j in core_obs}

    def gate_match(f, lx, ly, vx, vy, last_area, dt_sign):
        arr = kept_arr[f]
        if not len(arr):
            return None
        dt = abs(dt_sign)
        px, py = lx + vx * dt_sign, ly + vy * dt_sign
        resid = np.hypot(arr[:, 0] - px, arr[:, 1] - py)
        gate = GATE_BASE + GATE_VEL * math.hypot(vx, vy) * dt
        idx = np.nonzero(resid <= gate)[0]
        cand = []
        for j in idx:
            ji = int(j)
            ddx = abs(float(arr[ji, 0]) - lx)
            ddy = abs(float(arr[ji, 1]) - ly)
            if ddx > V_MAX_CX_S * dt + GATE_BASE or \
               ddy > V_MAX_CY_S * dt + GATE_BASE or \
               math.hypot(ddx, ddy) > VEL_MAX * dt + GATE_BASE:
                continue
            area = max(float(arr[ji, 2]) * float(arr[ji, 3]), 1e-9)
            if abs(math.log(area / last_area)) > SIZE_TOL:
                continue
            cand.append((float(resid[ji]) - W_CONF_CONT * float(arr[ji, 4]), ji))
        if not cand:
            return None
        cand.sort()
        return cand[0][1]

    pre = list(core_obs)
    # backward
    f0, j0 = core_obs[0]
    lx, ly = kept[f0][j0][7:9]
    last_area = max(kept[f0][j0][3] * kept[f0][j0][4], 1e-9)
    vx, vy = vel0[0], vel0[1]  # BF-B: dt_sign<0 already reverses time
    last = f0
    f = f0 - 1
    while f >= 0:
        dt = pts[last] - pts[f]
        if dt > NULL_MAX_S + 1e-9:
            break
        got = gate_match(f, lx, ly, vx, vy, last_area, -(pts[last] - pts[f]))
        if got is None:
            f -= 1
            continue
        pre.insert(0, (f, got))
        pos2idx[f] = got
        lx, ly = float(kept_arr[f][got, 0]), float(kept_arr[f][got, 1])
        last_area = max(float(kept_arr[f][got, 2]) * float(kept_arr[f][got, 3]), 1e-9)
        last = f
        f -= 1
    # forward
    f0, j0 = core_obs[-1]
    lx, ly = kept[f0][j0][7:9]
    last_area = max(kept[f0][j0][3] * kept[f0][j0][4], 1e-9)
    if len(core_obs) >= 2:
        (f1, j1), (f2, j2) = core_obs[-2], core_obs[-1]
        ddt = pts[f2] - pts[f1]
        vx, vy = ((kept[f2][j2][7] - kept[f1][j1][7]) / max(ddt, 1e-9),
                  (kept[f2][j2][8] - kept[f1][j1][8]) / max(ddt, 1e-9))  # BF-B
    else:
        vx, vy = vel0
    last = f0
    f = f0 + 1
    while f < n:
        dt = pts[f] - pts[last]
        if dt > NULL_MAX_S + 1e-9:
            break
        got = gate_match(f, lx, ly, vx, vy, last_area, pts[f] - pts[last])
        if got is None:
            f += 1
            continue
        pre.append((f, got))
        pos2idx[f] = got
        lx, ly = float(kept_arr[f][got, 0]), float(kept_arr[f][got, 1])
        last_area = max(float(kept_arr[f][got, 2]) * float(kept_arr[f][got, 3]), 1e-9)
        last = f
        f += 1
    full = sorted(set(pre), key=lambda o: o[0])
    return full


def _describe_extended(full_obs, kept, clip, q, parts, core_span, rank):
    """Frozen describe + F3 flight fields. Event Logic replay unchanged."""
    boxes = {}
    for p, j in full_obs:
        _, cx, cy, bw, bh, conf, _, _, _ = kept[p][j]
        boxes[p] = r5.Cand(cx, cy, bw, bh, conf)
    tr = r5.Tracklet(tid=-1, starts=sorted(boxes), boxes=boxes)
    row = base.describe(tr, [], clip)
    sig = F3_VERSION + '|' + ','.join(
        f"{p}:{kept[p][j][1]:.6f},{kept[p][j][2]:.6f},{kept[p][j][3]:.6f},"
        f"{kept[p][j][4]:.6f}" for p, j in full_obs)
    tid = 'f3-' + hashlib.sha256(sig.encode()).hexdigest()[:16]
    row['track_id'] = tid
    row['path_id'] = tid
    row['path_rank'] = rank
    row['path_score'] = round(q, 6)
    row['flight_objective_parts'] = {k: round(v, 6) for k, v in parts.items()}
    row['flight_core_interval'] = list(core_span)
    row['person_track_refs'] = []
    row['association_provenance'] = 'F3_FRAME_LATTICE_FLIGHT_CORE'
    row['formulation'] = F1_BEAM
    # frame-level handoff provenance (gap entries mark NULL runs)
    handoffs, null_runs = [], 0
    obs_pos = sorted(boxes)
    for a, b in zip(obs_pos, obs_pos[1:]):
        gap = clip.pts_s[b] - clip.pts_s[a]
        step = b - a
        if step > 1:
            null_runs += 1
            handoffs.append({'kind': 'gap', 'from': a, 'to': b,
                             'gap_s': round(gap, 6),
                             'null_frames': step - 1})
        else:
            handoffs.append({'kind': 'frame', 'from': a, 'to': b,
                             'gap_s': round(gap, 6)})
    row['handoff_provenance'] = handoffs
    row['handoff_count'] = len(handoffs)
    row['null_run_count'] = null_runs
    return row


def infer(frames, fps):
    """GT-free F0 decode + F1 extension. Returns V2-compatible artifact."""
    clean = inference_view(frames)
    pts = [f['pts_s'] for f in clean]
    if not pts or any(b <= a for a, b in zip(pts, pts[1:])):
        raise ValueError('Strictly increasing recorded PTS required')
    if [f['fi'] for f in clean] != list(range(1, len(clean) + 1)):
        raise ValueError('Frozen one-based sequential frame cache required')
    _, off = compute_flow(clean, pts)
    kept, full_counts = build_frame_lattice(clean, off)
    kept_arr = _frame_arrays(kept)
    n = len(pts)
    starts = list(range(0, n, START_STRIDE))
    pool = _extend_starts(kept, kept_arr, pts, starts)
    # F0 core extraction over the decoded pool
    cores = []
    for q_path in pool:
        best = extract_flight_core(q_path, kept, pts)
        if best is None:
            continue
        q, i, j, parts = best
        cores.append((q, q_path, i, j, parts))
    cores.sort(key=lambda c: (-round(c[0], 9),
                              tuple(o for o in c[1].obs)))
    # diversity: keep spatially distinct cores
    diverse = []
    for q, q_path, i, j, parts in cores:
        obs = q_path.obs
        if all(_agree(obs, kept, kept_obs, kept) < DUP_AGREE
               for _, kept_obs, _, _, _ in diverse):
            diverse.append((q, obs, i, j, parts))
        if len(diverse) >= FINAL_TOP_K * 4:
            break
    # F1 extension of the top diverse cores; final order = F0 Q order
    clip = v2.Clip('', clean, fps)
    tracks = []
    for rank, (q, obs, i, j, parts) in enumerate(diverse[:FINAL_TOP_K], 1):
        core_obs = obs[i:j + 1]
        # core-end velocity for the backward seed (compensated coords)
        if len(core_obs) >= 2:
            (f1, j1), (f2, j2) = core_obs[0], core_obs[1]
            ddt = pts[f2] - pts[f1]
            vel0 = ((kept[f2][j2][7] - kept[f1][j1][7]) / max(ddt, 1e-9),
                    (kept[f2][j2][8] - kept[f1][j1][8]) / max(ddt, 1e-9))
        else:
            vel0 = (0.0, 0.0)
        full = extend_core(core_obs, kept, kept_arr, pts, vel0)
        core_span = [pts[core_obs[0][0]], pts[core_obs[-1][0]]]
        tracks.append(_describe_extended(full, kept, clip, q, parts,
                                         core_span, rank))
    nodes = sum(len(k) for k in kept)
    return {'person_track_count': nodes,
            'retained_path_count': len(tracks),
            'lattice': {'nodes': nodes,
                        'frames': n,
                        'full_floor_candidates': sum(full_counts),
                        'starts': len(starts),
                        'decoded_paths': len(pool),
                        'decoded_cores': len(cores),
                        'formulation': F0_BEAM},
            'tracks': tracks,
            'protocol': dict(PROTOCOL_CONSTANTS)}
