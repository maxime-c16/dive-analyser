"""DIVE_ANALYZER_FLIGHT_SEARCH_RECOVERY_V1 — GT-free ballistic flight score for pool ranking.

A dive flight is the only common scene motion with a physical signature: with a fixed
camera the centre of mass follows a ballistic arc — y(t) quadratic with DOWNWARD
curvature (image y grows downward) and a sustained drop into the water. Spectators,
walkers and swimmers have ~0 drop; a board bounce rises and falls back to board level.

For every path and every observation segment [i, j] with duration in
[SEG_MIN_S, SEG_MAX_S] (endpoint stride SEG_STRIDE observations), least squares
y = c + d t + e t^2 and x = a + b t are solved in closed form from prefix sums
(vectorized). The segment score is

  Q = drop - W_FIT * rms_rel - W_MISS * miss_frac

  drop     = y_fit(t_end) - min_{segment} y_fit      (fitted descent into the entry)
  rms_rel  = RMS(xy residual) / median box size
  miss_frac= 1 - observed / spanned frames
subject to E_MIN <= e <= E_MAX (downward image acceleration; generous envelope around
DEV 0.5-2 norm/s^2). A path's flight score is its best segment; paths without a valid
segment rank after all others (by their search order). Replaces V3's Q, whose
excursion term grows monotonically with segment length (core-length saturation).
"""
from __future__ import annotations

import numpy as np

SEG_MIN_S = 0.35
SEG_MAX_S = 2.5
SEG_STRIDE = 2
E_MIN, E_MAX = 0.2, 6.0  # norm/s^2
W_FIT = 0.10
W_MISS = 0.10
W_EV = 0.1  # weight of the segment's mean detection evidence clip(ln(conf/C_BG), -1, 4)
C_BG = 0.003
MIN_SEG_OBS = 6
Q_SEG_MIN = 0.05  # weakest segment surfaced as a flight candidate
SEGS_PER_PATH = 3  # time-disjoint flight segments read out per path
SEG_OVERLAP = 0.3

RANK_CONSTANTS = dict(SEG_MIN_S=SEG_MIN_S, SEG_MAX_S=SEG_MAX_S, SEG_STRIDE=SEG_STRIDE,
                      E_MIN=E_MIN, E_MAX=E_MAX, W_FIT=W_FIT, W_MISS=W_MISS, W_EV=W_EV, C_BG=C_BG, MIN_SEG_OBS=MIN_SEG_OBS,
                      Q_SEG_MIN=Q_SEG_MIN, SEGS_PER_PATH=SEGS_PER_PATH, SEG_OVERLAP=SEG_OVERLAP)


def flight_segments(path, L, pts, k_max=None):
    """All locally best, time-disjoint ballistic segments of a path (best first).

    Returns [(Q, (i, j), parts)] with Q >= Q_SEG_MIN; segments overlapping an already
    selected one by more than SEG_OVERLAP of the shorter are skipped.
    """
    Q, ii, jj, parts = _segment_table(path, L, pts)
    if Q is None:
        return []
    k_max = k_max or SEGS_PER_PATH
    order = np.argsort(-Q, kind='stable')
    t = np.array([pts[f] for f, _ in path])
    chosen = []
    for k in order:
        if not np.isfinite(Q[k]) or Q[k] < Q_SEG_MIN or len(chosen) >= k_max:
            break
        a0, a1 = t[ii[k]], t[jj[k]]
        if any(min(a1, b1) - max(a0, b0) > SEG_OVERLAP * min(a1 - a0, b1 - b0) for _, _, (b0, b1) in chosen):
            continue
        chosen.append((k, (int(ii[k]), int(jj[k])), (a0, a1)))
    return [(float(Q[k]), seg, parts(k)) for k, seg, _ in chosen]


def flight_score(path, L, pts):
    """Best segment only: (Q, (i, j), parts) or (-inf, None, None)."""
    segs = flight_segments(path, L, pts, k_max=1)
    return segs[0] if segs else (float('-inf'), None, None)


def _segment_table(path, L, pts):
    """Vectorized ballistic scores of every candidate segment of a path."""
    fr = np.array([f for f, _ in path])
    t = np.array([pts[f] for f in fr])
    x = np.array([L[f][j][0] for f, j in path])
    y = np.array([L[f][j][1] for f, j in path])
    s = np.array([np.sqrt(L[f][j][2] * L[f][j][3]) for f, j in path])
    m = len(t)
    if m < MIN_SEG_OBS:
        return None, None, None, None
    t0 = t[0]
    tc = t - t0
    P = lambda v: np.concatenate([[0.0], np.cumsum(v)])
    S0 = P(np.ones(m)); S1 = P(tc); S2 = P(tc ** 2); S3 = P(tc ** 3); S4 = P(tc ** 4)
    Y0 = P(y); Y1 = P(y * tc); Y2 = P(y * tc ** 2); YY = P(y * y)
    X0 = P(x); X1 = P(x * tc); XX = P(x * x)
    ii, jj = [], []
    for i in range(0, m, SEG_STRIDE):
        lo = np.searchsorted(t, t[i] + SEG_MIN_S)
        hi = np.searchsorted(t, t[i] + SEG_MAX_S, side='right')
        js = np.arange(max(lo, i + MIN_SEG_OBS - 1), min(hi, m), SEG_STRIDE)
        ii.append(np.full(len(js), i)); jj.append(js)
    if not ii:
        return None, None, None, None
    ii = np.concatenate(ii); jj = np.concatenate(jj)
    if not len(ii):
        return None, None, None, None
    a, b = ii, jj + 1  # half-open prefix-sum bounds
    n0 = S0[b] - S0[a]; n1 = S1[b] - S1[a]; n2 = S2[b] - S2[a]; n3 = S3[b] - S3[a]; n4 = S4[b] - S4[a]
    y0 = Y0[b] - Y0[a]; y1 = Y1[b] - Y1[a]; y2 = Y2[b] - Y2[a]; yy = YY[b] - YY[a]
    x0 = X0[b] - X0[a]; x1 = X1[b] - X1[a]; xx = XX[b] - XX[a]
    M = np.stack([np.stack([n0, n1, n2], -1), np.stack([n1, n2, n3], -1), np.stack([n2, n3, n4], -1)], -2)
    rhs = np.stack([y0, y1, y2], -1)
    ok = np.abs(np.linalg.det(M)) > 1e-12
    coef = np.zeros((len(ii), 3))
    coef[ok] = np.linalg.solve(M[ok], rhs[ok][..., None])[..., 0]
    c, d, e = coef[:, 0], coef[:, 1], coef[:, 2]
    # y residual sum of squares: yy - 2 coef.rhs + coef^T M coef
    ssy = yy - 2 * (coef * rhs).sum(-1) + np.einsum('ni,nij,nj->n', coef, M, coef)
    # x linear fit
    det2 = n0 * n2 - n1 ** 2
    ok2 = np.abs(det2) > 1e-12
    bx = np.where(ok2, (n0 * x1 - n1 * x0) / np.where(ok2, det2, 1), 0.0)
    ax = np.where(n0 > 0, (x0 - bx * n1) / np.maximum(n0, 1), 0.0)
    ssx = xx - 2 * (ax * x0 + bx * x1) + ax ** 2 * n0 + 2 * ax * bx * n1 + bx ** 2 * n2
    rms = np.sqrt(np.maximum(ssy + ssx, 0) / np.maximum(n0, 1))
    med_s = np.median(s)
    ta, tb = tc[ii], tc[jj]
    # fitted minimum over the segment (vertex if inside, else endpoints)
    tv = np.where(e != 0, -d / np.where(e != 0, 2 * e, 1), ta)
    yf = lambda tt: c + d * tt + e * tt ** 2
    ymin = np.minimum(yf(ta), yf(tb))
    inside = (tv > ta) & (tv < tb)
    ymin = np.where(inside, np.minimum(ymin, yf(tv)), ymin)
    drop = yf(tb) - ymin
    span = fr[jj] - fr[ii] + 1
    miss = 1.0 - (jj - ii + 1) / np.maximum(span, 1)
    ev = np.clip(np.log(np.maximum(np.array([L[f][j][4] for f, j in path]), 1e-6) / C_BG), -1.0, 4.0)
    EVc = P(ev)
    mean_ev = (EVc[b] - EVc[a]) / np.maximum(jj - ii + 1, 1)
    Q = drop - W_FIT * rms / max(med_s, 1e-6) - W_MISS * miss + W_EV * mean_ev
    valid = ok & (e >= E_MIN) & (e <= E_MAX)
    Q = np.where(valid, Q, -np.inf)

    la = np.log(np.maximum(s, 1e-6) ** 2)
    cf = np.array([L[f][j][4] for f, j in path])

    def parts(k):
        a_, b_ = ii[k], jj[k] + 1
        return {'drop': float(drop[k]), 'rms_rel': float(rms[k] / max(med_s, 1e-6)),
                'rms_abs': float(rms[k]), 'size_med': float(np.median(s[a_:b_])),
                'larea_std': float(np.std(la[a_:b_])), 'conf_med': float(np.median(cf[a_:b_])),
                'n_seg': int(b_ - a_),
                'miss_frac': float(miss[k]), 'accel': float(e[k]), 't0': float(t[ii[k]]),
                't1': float(t[jj[k]])}
    return Q, ii, jj, parts


def rank_pool(pool, L, pts):
    """pool [(T, path)] -> [(Q, T, path, seg, parts)] in flight-score order (stable)."""
    scored = []
    for r, (T, p) in enumerate(pool):
        q, seg, parts = flight_score(p, L, pts)
        scored.append((q, T, p, seg, parts, r))
    scored.sort(key=lambda z: (-(z[0] if np.isfinite(z[0]) else -1e9), z[5]))
    return [z[:5] for z in scored]
