"""DIVE_ANALYZER_FLIGHT_SEARCH_RECOVERY_V1 — surfaced multi-track flight candidates.

surface(d, reps): per representation run the search, rank its pool by the ballistic flight
score, then merge representations by flight score with cross-representation duplicate
suppression (two paths agreeing within RADIUS on >= XREP_AGREE of their common frames are
one hypothesis; the better-scored survives). Output: ranked candidate DiveTracks in the
PROXY coordinate frame/timeline, each with its flight segment. GT-free.
"""
from __future__ import annotations

import math

import numpy as np

import fsr_common_v1 as C
import fsr_rank_v1 as R
import fsr_search_v1 as S
import fsr_pool_cache_v1 as PC

PIPELINE_VERSION = 'FLIGHT_SEARCH_RECOVERY_V1_PIPELINE'
XREP_AGREE = 0.8
MAX_SURFACED = 50
PRE_S = 1.0  # surfaced track = flight segment extended backward (takeoff->apex rise)
POST_S = 0.5  # ... and forward (entry)
DUP_AGREE = 0.7  # surfaced tracks agreeing on >= this of common frames are duplicates
DUP_OVERLAP = 0.5  # ... when they also overlap >= this fraction of the shorter span


def _agree(a, b):
    common = set(a) & set(b)
    if not common:
        return 0.0
    return sum(math.hypot(a[f][0] - b[f][0], a[f][1] - b[f][1]) <= C.RADIUS for f in common) / len(common)


def _dup(a, b):
    fa, fb = set(a['obs']), set(b['obs'])
    common = fa & fb
    if not common or len(common) < DUP_OVERLAP * min(len(fa), len(fb)):
        return False
    return _agree(a['obs'], b['obs']) >= DUP_AGREE


def surface(d, reps=('360', 'hq'), mod=S, max_surfaced=None):
    """Ranked, deduplicated flight candidates (DiveTracks) over the requested representations."""
    cands = []
    for rep in reps:
        if rep == 'hq' and d not in C.HQ_DIVES:
            continue
        fr = C.frames(d, rep)
        pts = [f['pts_s'] for f in fr]
        pool, L = PC.pool(mod, d, rep)
        for pr, (T, p) in enumerate(pool, 1):
            for q, seg, parts in R.flight_segments(p, L, pts):
                lo, hi = parts['t0'] - PRE_S, parts['t1'] + POST_S
                obs = {f: tuple(float(v) for v in L[f][j]) for f, j in p if lo <= pts[f] <= hi}
                cands.append({'rep': rep, 'pool_rank': pr, 'Q': q, 'T': T, 'obs': obs,
                              'flight_segment': parts, 'n_obs': len(obs)})
    cands.sort(key=lambda z: (-z['Q'], z['pool_rank'], z['rep']))
    out = []
    for c in cands:
        if len(out) >= (max_surfaced or MAX_SURFACED):
            break
        if any(_dup(c, o) for o in out):
            continue
        out.append(c)
    for r, c in enumerate(out, 1):
        c['rank'] = r
    return out
