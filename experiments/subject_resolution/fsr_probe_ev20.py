"""DIVE_ANALYZER_FLIGHT_SEARCH_RECOVERY_V1 — global motion DP flight search (M-DP).

Replaces V3's stratified beam (seeding strata + dual-population pruning + end-of-clip
harvest) with an exhaustive, deterministic dynamic program over ALL frozen D5 floor
candidates:

  F[n] = max(0, max_{i -> n} F[i] + s(i, n))      forward: best path ENDING at n
  B[n] = same recursion on the time-reversed clip   backward: best path STARTING at n
  T[n] = F[n] + B[n]                               best path THROUGH n

Step score s(i, n) = W_PROGRESS * (d . u_i) - W_RESID * e_rel * scale - GAP_COST * missed
                     - W_SIZE * |log area ratio|
  d      = displacement i -> n (normalized image units)
  u_i    = unit heading of i's smoothed (EWMA) velocity; 0 while |v_i| < V_HEADING_MIN,
           so a path earns nothing until it has a heading: box jitter (successive
           displacements negatively correlated) earns ~0 or less, sustained motion
           earns its travelled distance. Static clutter therefore never outranks motion.
  e_rel  = |n - (i + v_i dt)| / scale, scale = mean geometric box size (sqrt(bw*bh)):
           the jitter tolerance is RELATIVE TO BOX SIZE, applied to POSITION, never a
           per-second cap applied to a single-frame velocity (V3/r5 unit defect).
Gates: e_rel <= E_REL_MAX, |log area ratio| <= SIZE_TOL (frozen r5), gap <= NULL_MAX_S
(frozen V3-C0 interpolation limit), smoothed speed <= V_SMOOTH_MAX (physical cap on
the EWMA, not on raw single-frame displacement).

Every node gets its own best-through path, so the three V3 search leaks are removed by
construction: no seeding strata (every candidate can start a path), no beam eviction
(nothing is pruned), no harvest timing (paths are read out per node, not from the beam
alive at the clip end). Pool = distinct best-through paths in T order (duplicate
suppression by node agreement), ranked by T. GT-free, identity-free, appearance-free.
"""
from __future__ import annotations

import hashlib
import math

import numpy as np

SEARCH_VERSION = 'PROBE_EV2.0'
# Ablation modes (all evaluated on DEV authority; none promoted, see report):
#   EVIDENCE      track-before-detect: node evidence ln(conf/C_BG), linear residual cost
#   MOTION_GATED  evidence earned only while the slow velocity moves (V_MOVE0..V_MOVE1)
#   LLR           same-object vs clutter step log-likelihood ratio + KAPPA * evidence
MODE = 'EVIDENCE'
PROTOCOL_DOC = 'FLIGHT_SEARCH_RECOVERY_V1_PROTOCOL.md'

# --- reused frozen scales ----------------------------------------------------
NULL_MAX_S = 0.30  # frozen V3-C0 interp_max_gap_s (longest bridged absence)
SIZE_TOL = math.log(2.2) + 0.010  # frozen r5 LOG_SIZE_MAX + JITTER_S
VEL_ALPHA = 0.35  # frozen r5 DEP_VEL_ALPHA (EWMA velocity update)
RADIUS = 0.06  # frozen agreement distance (dedupe scale)

# --- search constants (design-time, DEV authority only) ----------------------
N_MAX = 200  # candidates per frame (= frozen D5 floor cap; nothing dropped)
STATIC_OFFS_S = (0.1, 0.2)  # static-persistence probes: +-0.1 s and +-0.2 s
STATIC_R = 0.008  # a node is STATIC if a candidate within this (Chebyshev) distance
# exists at all four probes; static nodes cannot carry flight (DEV: removes ~45% of
# candidates, keeps 99-100% of subject flight anchors)
C_BG = 0.003  # background confidence (median of all frozen-floor candidates, DEV)
EV_MIN, EV_MAX = -1.0, 2.0
REF_DT = 1 / 30  # evidence is accrued per 1/30 s of observation (fps-invariant)
E_REL_MAX = 0.6  # max prediction residual in box sizes (subject p95 0.42, DEV chains)
SCALE_CAP = 0.20  # box-size scale is capped: giant low-conf boxes get no giant gates
V_SMOOTH_MAX = 2.5  # physical cap on the smoothed (EWMA) speed, norm/s (subject max 2.3)
GAP_COST_S = 30.0  # evidence cost per second of missing observation (1 per 1/30 s)
SIG_REL = 0.15  # same-object residual std in box sizes (DEV subject chains: p50 0.11)
LAMBDA = 55.0  # clutter density: non-static candidates per unit normalized area (DEV)
P_D = 0.8  # detection probability per 1/30 s (miss cost = -ln(1 - P_D) per missed 1/30 s)
KAPPA = 0.3  # weight of the confidence log-ratio in the node evidence
TAU_SLOW_S = 0.20  # time constant of the slow (jitter-robust) velocity EWMA
V_MOVE0, V_MOVE1 = 0.12, 0.35  # slow speed (norm/s) ramp: evidence counts 0 below V_MOVE0,
# fully above V_MOVE1 (DEV subject flight 0.2 s-baseline speed p50 0.26-0.53; box jitter
# averaged over 0.2 s ~0.05). Positive evidence is only earned while the path MOVES.
W_RESID = 1.0  # evidence cost per unit residual (in box sizes) per step
W_SIZE = 0.5  # evidence cost per unit |log area ratio| per step
POOL_MAX = 60  # distinct best-through paths read out per clip
T_MIN = 3.0  # minimum through-evidence to enter the pool
NOVEL_MIN_S = 0.25  # a path enters the pool only if it contributes >= this much observation
# time on nodes no kept path owns (novelty, not overlap ratio: a subject flight that shares
# a long approach prefix with a hijacked path must still be read out)
TOP_K = (1, 3, 5, 10)  # surfaced-set sizes reported

PROTOCOL_CONSTANTS = dict(
    SEARCH_VERSION=SEARCH_VERSION, MODE=MODE, NULL_MAX_S=NULL_MAX_S, SIZE_TOL=SIZE_TOL, VEL_ALPHA=VEL_ALPHA,
    RADIUS=RADIUS, N_MAX=N_MAX, STATIC_OFFS_S=STATIC_OFFS_S, STATIC_R=STATIC_R, C_BG=C_BG,
    EV_MIN=EV_MIN, EV_MAX=EV_MAX, REF_DT=REF_DT, E_REL_MAX=E_REL_MAX, SCALE_CAP=SCALE_CAP,
    V_SMOOTH_MAX=V_SMOOTH_MAX, GAP_COST_S=GAP_COST_S, TAU_SLOW_S=TAU_SLOW_S,
    V_MOVE0=V_MOVE0, V_MOVE1=V_MOVE1, W_RESID=W_RESID, W_SIZE=W_SIZE, SIG_REL=SIG_REL, LAMBDA=LAMBDA, P_D=P_D, KAPPA=KAPPA,
    POOL_MAX=POOL_MAX, T_MIN=T_MIN, NOVEL_MIN_S=NOVEL_MIN_S, TOP_K=TOP_K)


def _full(frames):
    out = []
    for f in frames:
        cs = sorted(f['c'], key=lambda c: (-c['conf'], c['cx'], c['cy'], c['bw'], c['bh']))[:N_MAX]
        out.append(np.array([[c['cx'], c['cy'], c['bw'], c['bh'], c['conf']] for c in cs],
                            dtype=np.float64).reshape(-1, 5))
    return out


def static_mask(A, pts):
    """True where a node has a near-identical candidate at every static probe."""
    n = len(A)
    pa = np.array(pts)
    out = []
    for f in range(n):
        m = np.ones(len(A[f]), dtype=bool)
        for o in STATIC_OFFS_S:
            for sgn in (-1.0, 1.0):
                t = pts[f] + sgn * o
                g = int(np.argmin(np.abs(pa - t)))
                if g == f or abs(pa[g] - t) > 0.05 or not len(A[g]) or not len(A[f]):
                    m &= False
                    continue
                d = np.abs(A[f][:, None, :2] - A[g][None, :, :2]).max(-1).min(1)
                m &= d < STATIC_R
        out.append(m)
    return out


def lattice(frames):
    """Per-frame arrays [cx, cy, bw, bh, conf] of NON-static candidates (deterministic)."""
    A = _full(frames)
    M = static_mask(A, [f['pts_s'] for f in frames])
    return [a[~m] for a, m in zip(A, M)]


def _dp(L, pts):
    """Forward track-before-detect DP. Returns per-frame arrays F, bp_f, bp_j, vx, vy.

    F[n] = max(evn(n), max_i F[i] - cost(i, n) + gain(i, n)): best score of a path ENDING
    at n, gain = max(ev, 0) * motion(v_slow) + min(ev, 0).
    """
    n = len(L)
    EV = []
    for f, a in enumerate(L):
        fdt = (pts[f + 1] - pts[f]) if f + 1 < n else (pts[f] - pts[f - 1])
        ev = np.clip(np.log(np.maximum(a[:, 4], 1e-6) / C_BG), EV_MIN, EV_MAX) if len(a) else np.zeros(0)
        EV.append(ev * (abs(fdt) / REF_DT))
    F = [np.zeros(len(a)) for a in L]
    VX = [np.zeros(len(a)) for a in L]
    VY = [np.zeros(len(a)) for a in L]
    SX = [np.zeros(len(a)) for a in L]  # slow velocity (motion evidence gate)
    SY = [np.zeros(len(a)) for a in L]
    BF = [np.full(len(a), -1, dtype=np.int64) for a in L]
    BJ = [np.full(len(a), -1, dtype=np.int64) for a in L]
    for f in range(1, n):
        a = L[f]
        if not len(a):
            continue
        ar = np.arange(len(a))
        bvx = np.zeros(len(a))
        bvy = np.zeros(len(a))
        bsx = np.zeros(len(a))
        bsy = np.zeros(len(a))
        bf = np.full(len(a), -1, dtype=np.int64)
        bj = np.full(len(a), -1, dtype=np.int64)
        evp = np.maximum(EV[f], 0.0)
        evn = np.minimum(EV[f], 0.0)
        best = evn.copy() if MODE == 'MOTION_GATED' else np.zeros(len(a))  # fresh-start value
        # velocity bootstrap for fresh starts: least-cost gated predecessor
        seed_best = np.full(len(a), -np.inf)
        svx = np.zeros(len(a))
        svy = np.zeros(len(a))
        ssx = np.zeros(len(a))
        ssy = np.zeros(len(a))
        sj = np.minimum(np.sqrt(a[:, 2] * a[:, 3]), SCALE_CAP)
        areaj = np.maximum(a[:, 2] * a[:, 3], 1e-9)
        g = f - 1
        while g >= 0 and pts[f] - pts[g] <= NULL_MAX_S + 1e-9:
            p = L[g]
            if len(p):
                dt = pts[f] - pts[g]
                vx, vy = VX[g][:, None], VY[g][:, None]
                dx = a[None, :, 0] - p[:, None, 0]
                dy = a[None, :, 1] - p[:, None, 1]
                scale = 0.5 * (np.minimum(np.sqrt(p[:, 2] * p[:, 3]), SCALE_CAP)[:, None] + sj[None, :])
                erel = np.hypot(dx - vx * dt, dy - vy * dt) / np.maximum(scale, 1e-6)
                lsz = np.abs(np.log(areaj[None, :] / np.maximum(p[:, 2] * p[:, 3], 1e-9)[:, None]))
                nvx = VEL_ALPHA * dx / dt + (1 - VEL_ALPHA) * vx
                nvy = VEL_ALPHA * dy / dt + (1 - VEL_ALPHA) * vy
                a_s = min(dt / TAU_SLOW_S, 1.0)
                nsx = a_s * dx / dt + (1 - a_s) * SX[g][:, None]
                nsy = a_s * dy / dt + (1 - a_s) * SY[g][:, None]
                if MODE == 'LLR':  # same-object vs clutter step log-likelihood ratio
                    sig = SIG_REL * scale
                    gain = (np.log(1.0 / (2 * np.pi * sig ** 2 * LAMBDA)) - erel ** 2 / (2 * SIG_REL ** 2)
                            + KAPPA * EV[f][None, :])
                elif MODE == 'MOTION_GATED':
                    mf = np.clip((np.hypot(nsx, nsy) - V_MOVE0) / (V_MOVE1 - V_MOVE0), 0.0, 1.0)
                    gain = evp[None, :] * mf + evn[None, :]
                else:
                    gain = EV[f][None, :] + 0.0 * erel
                ok = (erel <= E_REL_MAX) & (lsz <= SIZE_TOL) & (np.hypot(nvx, nvy) <= V_SMOOTH_MAX)
                missed = dt - (pts[f] - pts[f - 1])
                if MODE == 'LLR':
                    cost = W_SIZE * lsz + (-np.log(1 - P_D)) * missed / REF_DT
                else:
                    cost = W_RESID * erel + W_SIZE * lsz + GAP_COST_S * missed
                cand = np.where(ok, F[g][:, None] - cost + gain, -np.inf)
                i = np.argmax(cand, axis=0)
                val = cand[i, ar]
                upd = val > best
                best = np.where(upd, val, best)
                bvx = np.where(upd, nvx[i, ar], bvx)
                bvy = np.where(upd, nvy[i, ar], bvy)
                bsx = np.where(upd, nsx[i, ar], bsx)
                bsy = np.where(upd, nsy[i, ar], bsy)
                bf = np.where(upd, g, bf)
                bj = np.where(upd, i, bj)
                sc = np.where(ok, -cost, -np.inf)
                i2 = np.argmax(sc, axis=0)
                v2 = sc[i2, ar]
                take = np.isfinite(v2) & (v2 > seed_best)
                seed_best = np.where(take, v2, seed_best)
                svx = np.where(take, nvx[i2, ar], svx)
                svy = np.where(take, nvy[i2, ar], svy)
                ssx = np.where(take, nsx[i2, ar], ssx)
                ssy = np.where(take, nsy[i2, ar], ssy)
            g -= 1
        fresh = bf < 0
        bvx = np.where(fresh, svx, bvx)
        bvy = np.where(fresh, svy, bvy)
        bsx = np.where(fresh, ssx, bsx)
        bsy = np.where(fresh, ssy, bsy)
        # best already includes the motion-gated gain of a continued path; a fresh
        # start earns only its non-positive evidence
        if MODE == 'EVIDENCE':
            F[f] = np.where(fresh, EV[f], best)  # fresh start earns its own evidence
        else:
            F[f] = np.where(fresh, evn if MODE == 'MOTION_GATED' else 0.0, best)
        VX[f], VY[f], SX[f], SY[f], BF[f], BJ[f] = bvx, bvy, bsx, bsy, bf, bj
    return F, BF, BJ, VX, VY, EV


def _backtrack(BF, BJ, f, j):
    path = [(f, j)]
    while BF[f][j] >= 0:
        f, j = int(BF[f][j]), int(BJ[f][j])
        path.append((f, j))
    return path[::-1]


def search(frames):
    """GT-free M-DP flight search. Returns ranked pool of paths [(T, [(frame, idx)...])] + lattice."""
    pts = [f['pts_s'] for f in frames]
    if any(b <= a for a, b in zip(pts, pts[1:])):
        raise ValueError('strictly increasing PTS required')
    L = lattice(frames)
    Ff, BFf, BJf, _, _, EV = _dp(L, pts)
    n = len(L)
    Lr = L[::-1]
    ptsr = [-t for t in pts[::-1]]
    Fr, BFr, BJr, _, _, _ = _dp(Lr, ptsr)
    # through score (the node's own gain appears in both passes; one node, negligible)
    T = []
    for f in range(n):
        T.append(Ff[f] + Fr[n - 1 - f])
    order = sorted(((float(T[f][j]), f, j) for f in range(n) for j in range(len(L[f]))
                    if T[f][j] >= T_MIN), key=lambda x: (-round(x[0], 9), x[1], x[2]))
    frame_dt = [(pts[f + 1] - pts[f]) if f + 1 < n else (pts[f] - pts[f - 1]) for f in range(n)]
    pool, owned = [], {}
    for t, f, j in order:
        if len(pool) >= POOL_MAX:
            break
        if (f, j) in owned:
            continue
        back = _backtrack(BFf, BJf, f, j)
        fr_ = _backtrack(BFr, BJr, n - 1 - f, j)  # reversed-time path ending at (f, j)
        fwd = [(n - 1 - g, k) for g, k in fr_[::-1]]  # forward-time continuation from (f, j)
        path = back + fwd[1:]
        novel = [o for o in path if o not in owned]
        novel_s = sum(frame_dt[o[0]] for o in novel)
        if novel_s < NOVEL_MIN_S:
            continue
        for o in path:
            owned.setdefault(o, len(pool))
        pool.append((t, path))
    return pool, L


def path_obs(path, L):
    """{frame_pos: (cx, cy, bw, bh, conf)}"""
    return {f: tuple(float(v) for v in L[f][j]) for f, j in path}


def path_id(path, L):
    sig = SEARCH_VERSION + '|' + ','.join(f'{f}:{L[f][j][0]:.6f},{L[f][j][1]:.6f}' for f, j in path)
    return 'fsr-' + hashlib.sha256(sig.encode()).hexdigest()[:16]
