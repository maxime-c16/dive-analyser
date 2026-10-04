"""DIVE_ANALYZER_FLIGHT_SEARCH_RECOVERY_V1 — confidence-agnostic ballistic micro-tracklet
chaining (BMC). POST-SEALED design (v2 line): motivated by the sealed diagnosis that the
airborne subject has LOWER D5 confidence than nearby people, so every evidence-driven
search (v1) prefers them. Confidence plays no role in construction here.

1. Micro-tracklets (local motion hypotheses, jitter-robust): for node n at frame f and
   the frames f-, f+ nearest to t_f -/+ HALF_S, a pair (a, b) such that n lies at the
   midpoint of a and b within MID_TOL box sizes, sizes agree (frozen SIZE_TOL), speed
   |b - a| / (t_b - t_a) in [V_MIN, V_MAX]; accepted only if the intermediate frames
   support the line (a node within SUP_TOL box sizes of the interpolated position on at
   least SUP_MIN of them). Random clutter essentially never has dense support.
2. Ballistic linking: micro-tracklet m1 -> m2 (0 < dt <= LINK_MAX_S) iff constant-
   acceleration consistent: |p2 - p1 - (v1 + v2) dt / 2| <= LINK_TOL box sizes,
   |a_x| <= AX_MAX, AY_MIN <= a_y <= AY_MAX (image y down: gravity is positive).
3. DP over the micro-tracklet DAG (score = support frames, gap cost per second without
   a micro-tracklet), best-through chains per micro-tracklet, novelty dedup; each chain
   is expanded to a node path (one node per frame: the support node closest to the
   chain's piecewise-linear centre track).
"""
from __future__ import annotations

import numpy as np

import fsr_search_v1 as v1

SEARCH_VERSION = 'FLIGHT_SEARCH_RECOVERY_V1_BMC'
SIZE_TOL = v1.SIZE_TOL
SCALE_CAP = v1.SCALE_CAP
HALF_S = 0.10
MID_TOL = 0.03  # absolute (normalized) midpoint tolerance
SUP_TOL = 0.025  # absolute support tolerance: ~subject jitter; random clutter hit ~11%/frame
SUP_MIN = 0.5
V_MIN, V_MAX = 0.25, 2.5
LINK_MAX_S = 0.35
LINK_TOL = 0.6
AX_MAX = 3.0
AY_MIN, AY_MAX = -3.0, 10.0
GAP_COST_S = 10.0  # support frames lost per second of chain without a micro-tracklet
POOL_MAX = 60
NOVEL_MIN_S = v1.NOVEL_MIN_S
T_MIN = 4.0

PROTOCOL_CONSTANTS = dict(
    SEARCH_VERSION=SEARCH_VERSION, SIZE_TOL=SIZE_TOL, SCALE_CAP=SCALE_CAP, HALF_S=HALF_S,
    MID_TOL=MID_TOL, SUP_TOL=SUP_TOL, SUP_MIN=SUP_MIN, V_MIN=V_MIN, V_MAX=V_MAX,
    LINK_MAX_S=LINK_MAX_S, LINK_TOL=LINK_TOL, AX_MAX=AX_MAX, AY_MIN=AY_MIN, AY_MAX=AY_MAX,
    GAP_COST_S=GAP_COST_S, POOL_MAX=POOL_MAX, NOVEL_MIN_S=NOVEL_MIN_S, T_MIN=T_MIN,
    STATIC_OFFS_S=v1.STATIC_OFFS_S, STATIC_R=v1.STATIC_R, N_MAX=v1.N_MAX)

lattice = v1.lattice
path_obs = v1.path_obs
path_id = v1.path_id


def _scale(a):
    return np.minimum(np.sqrt(a[:, 2] * a[:, 3]), SCALE_CAP)


def micro_tracklets(L, pts):
    pa = np.asarray(pts)
    n = len(L)
    out = []  # dict(f, j, t, x, y, vx, vy, s, nodes, sup)
    for f in range(n):
        N = L[f]
        if not len(N):
            continue
        fa = int(np.argmin(np.abs(pa - (pa[f] - HALF_S))))
        fb = int(np.argmin(np.abs(pa - (pa[f] + HALF_S))))
        if fa >= f or fb <= f or not len(L[fa]) or not len(L[fb]):
            continue
        A, B = L[fa], L[fb]
        ta, tb = pa[fa], pa[fb]
        w = (pa[f] - ta) / (tb - ta)
        sn = _scale(N)
        # for every (n, a) the ideal b = a + (n - a) / w
        bx = A[None, :, 0] + (N[:, None, 0] - A[None, :, 0]) / w
        by = A[None, :, 1] + (N[:, None, 1] - A[None, :, 1]) / w
        d = np.hypot(bx[:, :, None] - B[None, None, :, 0], by[:, :, None] - B[None, None, :, 1])
        kb = np.argmin(d, axis=2)
        db = np.take_along_axis(d, kb[..., None], 2)[..., 0]
        ok = db <= MID_TOL
        la = np.log(np.maximum(N[:, 2] * N[:, 3], 1e-9))
        ok &= np.abs(np.log(np.maximum(A[:, 2] * A[:, 3], 1e-9))[None, :] - la[:, None]) <= SIZE_TOL
        lb = np.log(np.maximum(B[kb, 2] * B[kb, 3], 1e-9))
        ok &= np.abs(lb - la[:, None]) <= SIZE_TOL
        vx = (B[kb, 0] - A[None, :, 0]) / (tb - ta)
        vy = (B[kb, 1] - A[None, :, 1]) / (tb - ta)
        sp = np.hypot(vx, vy)
        ok &= (sp >= V_MIN) & (sp <= V_MAX)
        ii, jj = np.nonzero(ok)
        if not len(ii):
            continue
        # support check on intermediate frames
        mids = [g for g in range(fa + 1, fb) if g != f]
        best = {}
        for i, j in zip(ii, jj):
            k = int(kb[i, j])
            ax_, ay_ = A[j, 0], A[j, 1]
            bx_, by_ = B[k, 0], B[k, 1]
            nodes = [(fa, int(j)), (f, int(i)), (fb, k)]
            sup = 0
            for g in mids:
                G = L[g]
                if not len(G):
                    continue
                u = (pa[g] - ta) / (tb - ta)
                px, py = ax_ + (bx_ - ax_) * u, ay_ + (by_ - ay_) * u
                dd = np.hypot(G[:, 0] - px, G[:, 1] - py)
                q = int(np.argmin(dd))
                if dd[q] <= SUP_TOL:
                    sup += 1
                    nodes.append((g, q))
            if mids and sup < SUP_MIN * len(mids):
                continue
            score = sup + 3
            if i not in best or score > best[i]['sup']:
                best[i] = {'f': f, 'j': int(i), 't': float(pa[f]), 'x': float(N[i, 0]), 'y': float(N[i, 1]),
                           'vx': float(vx[i, j]), 'vy': float(vy[i, j]), 's': float(sn[i]),
                           'nodes': sorted(nodes), 'sup': score}
        out.extend(best[i] for i in sorted(best))
    return out


def _dp(M, reverse=False):
    """DP over micro-tracklets in time order (or reversed). Returns (F, BP)."""
    m = len(M)
    order = sorted(range(m), key=lambda k: (M[k]['t'], M[k]['j']), reverse=reverse)
    t = np.array([M[k]['t'] for k in range(m)])
    x = np.array([M[k]['x'] for k in range(m)]); y = np.array([M[k]['y'] for k in range(m)])
    vx = np.array([M[k]['vx'] for k in range(m)]); vy = np.array([M[k]['vy'] for k in range(m)])
    s = np.array([M[k]['s'] for k in range(m)]); sup = np.array([M[k]['sup'] for k in range(m)], dtype=float)
    F = sup.copy()
    BP = np.full(m, -1)
    done = []  # processed indices, time-sorted
    tsort = t[order]
    pos = {k: r for r, k in enumerate(order)}
    for r, k in enumerate(order):
        # candidate predecessors: processed with |dt| in (0, LINK_MAX_S]
        lo = r - 1
        prev = []
        while lo >= 0 and abs(tsort[r] - tsort[lo]) <= LINK_MAX_S + 1e-9:
            if abs(tsort[r] - tsort[lo]) > 1e-9:
                prev.append(order[lo])
            lo -= 1
        if not prev:
            continue
        P = np.array(prev)
        dt = t[k] - t[P]  # negative when reversed
        adt = np.abs(dt)
        res = np.hypot(x[k] - x[P] - (vx[P] + vx[k]) * dt / 2, y[k] - y[P] - (vy[P] + vy[k]) * dt / 2)
        sc = 0.5 * (s[P] + s[k])
        axx = (vx[k] - vx[P]) / dt
        ayy = (vy[k] - vy[P]) / dt
        ok = (res <= LINK_TOL * sc) & (np.abs(axx) <= AX_MAX) & (ayy >= AY_MIN) & (ayy <= AY_MAX)
        if not ok.any():
            continue
        # support frames already counted by the predecessor overlap ours: count time gain
        val = F[P] + sup[k] * np.minimum(adt / (2 * HALF_S), 1.0) - GAP_COST_S * np.maximum(adt - 2 * HALF_S, 0)
        val = np.where(ok, val, -np.inf)
        q = int(np.argmax(val))
        if val[q] > F[k]:
            F[k] = val[q]
            BP[k] = P[q]
    return F, BP


def _chain(BP, k):
    c = [k]
    while BP[c[-1]] >= 0:
        c.append(int(BP[c[-1]]))
    return c


def search(frames):
    pts = [f['pts_s'] for f in frames]
    if any(b <= a for a, b in zip(pts, pts[1:])):
        raise ValueError('strictly increasing PTS required')
    L = lattice(frames)
    M = micro_tracklets(L, pts)
    if not M:
        return [], L
    Ff, Bf = _dp(M)
    Fr, Br = _dp(M, reverse=True)
    sup = np.array([mm['sup'] for mm in M], dtype=float)
    T = Ff + Fr - sup
    order = sorted(range(len(M)), key=lambda k: (-round(float(T[k]), 9), M[k]['t'], M[k]['j']))
    n = len(L)
    fdt = [(pts[f + 1] - pts[f]) if f + 1 < n else (pts[f] - pts[f - 1]) for f in range(n)]
    pool, owned_m = [], set()
    kept_pos = {}  # frame -> list of (x, y) of kept paths
    for k in order:
        if len(pool) >= POOL_MAX or T[k] < T_MIN:
            break
        if k in owned_m:
            continue
        chain = _chain(Bf, k)[::-1] + _chain(Br, k)[1:]
        chain.sort(key=lambda q: M[q]['t'])
        # centre track: micro-tracklet centres; per frame pick support node closest to it
        ct = np.array([M[q]['t'] for q in chain])
        cx = np.array([M[q]['x'] for q in chain]); cy = np.array([M[q]['y'] for q in chain])
        cand = {}
        for q in chain:
            for g, j in M[q]['nodes']:
                cand.setdefault(g, set()).add(j)
        path = []
        for g in sorted(cand):
            px, py = np.interp(pts[g], ct, cx), np.interp(pts[g], ct, cy)
            j = min(cand[g], key=lambda jj: (L[g][jj][0] - px) ** 2 + (L[g][jj][1] - py) ** 2)
            path.append((g, int(j)))
        owned_m.update(chain)
        novel = sum(fdt[g] for g, j in path
                    if all((L[g][j][0] - x0) ** 2 + (L[g][j][1] - y0) ** 2 > v1.RADIUS ** 2
                           for x0, y0 in kept_pos.get(g, ())))
        if novel < NOVEL_MIN_S:
            continue
        for g, j in path:
            kept_pos.setdefault(g, []).append((float(L[g][j][0]), float(L[g][j][1])))
        pool.append((float(T[k]), path))
    return pool, L


# ---------------------------------------------------------------- greedy chaining (BMC-G)
def _link_cost(M, k, P):
    """Normalized ballistic link residual from micro-tracklet k to candidates P (inf if gated out)."""
    mk = M[k]
    out = []
    for q in P:
        mq = M[q]
        dt = mq['t'] - mk['t']
        rx = mq['x'] - mk['x'] - (mk['vx'] + mq['vx']) * dt / 2
        ry = mq['y'] - mk['y'] - (mk['vy'] + mq['vy']) * dt / 2
        res = (rx * rx + ry * ry) ** 0.5
        axx = (mq['vx'] - mk['vx']) / dt
        ayy = (mq['vy'] - mk['vy']) / dt
        sc = 0.5 * (mk['s'] + mq['s'])
        if res <= LINK_TOL * sc and abs(axx) <= AX_MAX and AY_MIN <= ayy <= AY_MAX:
            out.append(res / sc + 0.5 * abs(dt) / LINK_MAX_S)
        else:
            out.append(float('inf'))
    return out


def greedy_chains(M):
    order = sorted(range(len(M)), key=lambda k: (M[k]['t'], M[k]['j']))
    t = [M[k]['t'] for k in order]
    import bisect
    succ, pred = {}, {}
    for r, k in enumerate(order):
        hi = bisect.bisect_right(t, M[k]['t'] + LINK_MAX_S + 1e-9)
        P = [order[q] for q in range(r + 1, hi) if M[order[q]]['t'] > M[k]['t'] + 1e-9]
        if P:
            c = _link_cost(M, k, P)
            b = min(range(len(P)), key=lambda i: (c[i], i))
            if c[b] < float('inf'):
                succ[k] = P[b]
        lo = bisect.bisect_left(t, M[k]['t'] - LINK_MAX_S - 1e-9)
        Q = [order[q] for q in range(lo, r) if M[order[q]]['t'] < M[k]['t'] - 1e-9]
        if Q:
            # backward: reuse the forward metric with roles swapped
            c = []
            for q in Q:
                c.append(_link_cost(M, q, [k])[0])
            b = min(range(len(Q)), key=lambda i: (c[i], i))
            if c[b] < float('inf'):
                pred[k] = Q[b]
    chains = []
    for k in range(len(M)):
        ch = [k]
        seen = {k}
        while ch[-1] in succ and succ[ch[-1]] not in seen:
            ch.append(succ[ch[-1]]); seen.add(ch[-1])
        back = []
        c = k
        while c in pred and pred[c] not in seen:
            c = pred[c]; back.append(c); seen.add(c)
        chains.append(back[::-1] + ch)
    return chains


def search_greedy(frames):
    pts = [f['pts_s'] for f in frames]
    L = lattice(frames)
    M = micro_tracklets(L, pts)
    if not M:
        return [], L
    chains = greedy_chains(M)
    n = len(L)
    fdt = [(pts[f + 1] - pts[f]) if f + 1 < n else (pts[f] - pts[f - 1]) for f in range(n)]
    scored = []
    for ch in chains:
        sup = sum(M[q]['sup'] for q in ch)
        scored.append((sup, ch))
    scored.sort(key=lambda z: (-z[0], M[z[1][0]]['t'], z[1][0]))
    pool, kept_pos = [], {}
    for sup, ch in scored:
        if len(pool) >= POOL_MAX:
            break
        ct = np.array([M[q]['t'] for q in ch])
        cx = np.array([M[q]['x'] for q in ch]); cy = np.array([M[q]['y'] for q in ch])
        cand = {}
        for q in ch:
            for g, j in M[q]['nodes']:
                cand.setdefault(g, set()).add(j)
        path = []
        for g in sorted(cand):
            px, py = np.interp(pts[g], ct, cx), np.interp(pts[g], ct, cy)
            j = min(cand[g], key=lambda jj: (L[g][jj][0] - px) ** 2 + (L[g][jj][1] - py) ** 2)
            path.append((g, int(j)))
        novel = sum(fdt[g] for g, j in path
                    if all((L[g][j][0] - x0) ** 2 + (L[g][j][1] - y0) ** 2 > v1.RADIUS ** 2
                           for x0, y0 in kept_pos.get(g, ())))
        if novel < NOVEL_MIN_S:
            continue
        for g, j in path:
            kept_pos.setdefault(g, []).append((float(L[g][j][0]), float(L[g][j][1])))
        pool.append((float(sup), path))
    return pool, L
