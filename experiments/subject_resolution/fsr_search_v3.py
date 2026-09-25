"""DIVE_ANALYZER_FLIGHT_SEARCH_RECOVERY_V1 — windowed track-before-detect DP (W-DP).

v1 (global evidence DP) builds clean subject paths where the subject is the strongest
local object, but a globally optimal path inherits a duration bias: after entry (and
sometimes mid-flight) a longer-lived, higher-confidence person adds more total evidence
than the weak airborne target, so the best path through a subject node hops onto them.
v2 (locally greedy tracks) removes the bias but fragments the flight.

W-DP bounds the bias instead of removing optimality: the v1 EVIDENCE recursion runs
independently inside overlapping windows of WIN_S seconds (stride STRIDE_S). Any flight
(<= ~2 s) fits entirely inside some window, and a hijack can gain at most the evidence of
the remaining window time. Every node of every window gets its best-through path (no
seeding strata, no pruning, no harvest timing); pool = novelty-deduplicated union over
windows, read out in through-evidence order. GT-free, identity-free, appearance-free.
"""
from __future__ import annotations

import numpy as np

import fsr_search_v1 as v1

SEARCH_VERSION = 'FLIGHT_SEARCH_RECOVERY_V1_WDP'
PROTOCOL_DOC = v1.PROTOCOL_DOC
WIN_S = 2.5  # window length (covers the longest DEV flight 1.97 s + margins)
STRIDE_S = 0.5  # window stride
PER_WINDOW = 40  # distinct best-through paths read out per window
NOVEL_MIN_S = v1.NOVEL_MIN_S
POOL_MAX = 400
T_MIN = v1.T_MIN

PROTOCOL_CONSTANTS = dict(v1.PROTOCOL_CONSTANTS, SEARCH_VERSION=SEARCH_VERSION, WIN_S=WIN_S,
                          STRIDE_S=STRIDE_S, PER_WINDOW=PER_WINDOW, POOL_MAX=POOL_MAX)

lattice = v1.lattice
path_obs = v1.path_obs
path_id = v1.path_id


def _window_paths(L, pts, lo, hi):
    """Best-through paths of nodes in frames [lo, hi) using v1's recursion on the slice."""
    sub = L[lo:hi]
    sp = pts[lo:hi]
    m = len(sub)
    Ff, BFf, BJf, _, _, EV = v1._dp(sub, sp)
    Fr, BFr, BJr, _, _, _ = v1._dp(sub[::-1], [-t for t in sp[::-1]])
    order = []
    for f in range(m):
        T = Ff[f] + Fr[m - 1 - f] - EV[f]
        for j in np.nonzero(T >= T_MIN)[0]:
            order.append((float(T[j]), f, int(j)))
    order.sort(key=lambda x: (-round(x[0], 9), x[1], x[2]))
    return order, (BFf, BJf, BFr, BJr, m)


def search(frames):
    pts = [f['pts_s'] for f in frames]
    if any(b <= a for a, b in zip(pts, pts[1:])):
        raise ValueError('strictly increasing PTS required')
    L = lattice(frames)
    n = len(L)
    fdt = [(pts[f + 1] - pts[f]) if f + 1 < n else (pts[f] - pts[f - 1]) for f in range(n)]
    pa = np.array(pts)
    starts = np.arange(pts[0], max(pts[-1] - WIN_S, pts[0]) + STRIDE_S / 2, STRIDE_S)
    cands = []
    for t0 in starts:
        lo = int(np.searchsorted(pa, t0))
        hi = int(np.searchsorted(pa, t0 + WIN_S, side='right'))
        if hi - lo < 2:
            continue
        order, (BFf, BJf, BFr, BJr, m) = _window_paths(L, pts, lo, hi)
        owned, got = set(), 0
        for T, f, j in order:
            if got >= PER_WINDOW:
                break
            if (f, j) in owned:
                continue
            back = v1._backtrack(BFf, BJf, f, j)
            fr_ = v1._backtrack(BFr, BJr, m - 1 - f, j)
            fwd = [(m - 1 - g, k) for g, k in fr_[::-1]]
            path = [(lo + g, k) for g, k in back + fwd[1:]]
            novel = sum(fdt[g] for g, k in path if (g - lo, k) not in owned)
            if novel < NOVEL_MIN_S:
                continue
            owned.update((g - lo, k) for g, k in path)
            cands.append((T, path))
            got += 1
    # global readout: through-evidence order, novelty across windows
    cands.sort(key=lambda c: (-round(c[0], 9), c[1][0]))
    pool, owned = [], set()
    for T, p in cands:
        if len(pool) >= POOL_MAX:
            break
        novel = sum(fdt[f] for f, j in p if (f, j) not in owned)
        if novel < NOVEL_MIN_S:
            continue
        owned.update(p)
        pool.append((T, p))
    return pool, L
