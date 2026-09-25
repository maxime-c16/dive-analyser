"""DIVE_ANALYZER_FLIGHT_SEARCH_RECOVERY_V1 — locally optimal multi-track search (G-MT).

Why not a global DP: the DEV node oracle shows that a globally optimal path through a
subject node inherits a duration bias — after water entry (and sometimes mid-flight) a
longer-lived, higher-confidence person always adds more total score than the weak
airborne target, so the best path through the subject hops onto them. Locally optimal
paths have no such incentive: each step only asks "which detection best continues THIS
object?".

Construction (deterministic, GT-free, identity-free, appearance-free):
- nodes = NON-static frozen D5 floor candidates (static-persistence mask of v1);
- every node not continued by a live track starts a new track (no seeding strata);
- each live track greedily takes, at each frame, its best gated successor by the
  same-object step score  -e_rel^2 / (2 SIG_REL^2) - W_SIZE |log area ratio|
  + KAPPA ln(conf / C_BG); residual gate relative to box size (capped), never a
  per-second cap on single-frame velocity; absences are bridged up to NULL_MAX_S;
- tracks may share detections; two tracks on the same detection with the same motion
  (|dv| <= MERGE_DV) are merged (the younger stops) and the merge is RECORDED, so the
  absorbed track's history + the survivor's continuation is still read out;
- the same pass runs on the time-reversed clip; pool = forward + backward paths,
  novelty-deduplicated. No pruning, no beam, no harvest timing.
"""
from __future__ import annotations

import hashlib
import math

import numpy as np

import fsr_search_v1 as v1

SEARCH_VERSION = 'FLIGHT_SEARCH_RECOVERY_V1_GMT'
PROTOCOL_DOC = v1.PROTOCOL_DOC

NULL_MAX_S = v1.NULL_MAX_S  # frozen V3-C0 interp limit
SIZE_TOL = v1.SIZE_TOL  # frozen r5 size agreement
VEL_ALPHA = v1.VEL_ALPHA  # frozen r5 EWMA
C_BG = v1.C_BG
EV_MIN, EV_MAX = v1.EV_MIN, v1.EV_MAX
SCALE_CAP = v1.SCALE_CAP
SIG_REL = 0.15  # same-object residual std in box sizes (DEV subject chains p50 0.11)
E_REL_MAX = 0.6  # residual gate in box sizes (DEV subject p95 0.42)
W_SIZE = 0.5
KAPPA = 0.3
V_SMOOTH_MAX = v1.V_SMOOTH_MAX
MERGE_DV = 0.3  # norm/s: tracks on one detection with velocities this close are the same
MIN_OBS_S = 0.20  # shortest path read out (observation time)
NOVEL_MIN_S = v1.NOVEL_MIN_S
POOL_MAX = 400

PROTOCOL_CONSTANTS = dict(
    SEARCH_VERSION=SEARCH_VERSION, NULL_MAX_S=NULL_MAX_S, SIZE_TOL=SIZE_TOL, VEL_ALPHA=VEL_ALPHA,
    C_BG=C_BG, EV_MIN=EV_MIN, EV_MAX=EV_MAX, SCALE_CAP=SCALE_CAP, SIG_REL=SIG_REL,
    E_REL_MAX=E_REL_MAX, W_SIZE=W_SIZE, KAPPA=KAPPA, V_SMOOTH_MAX=V_SMOOTH_MAX, MERGE_DV=MERGE_DV,
    MIN_OBS_S=MIN_OBS_S, NOVEL_MIN_S=NOVEL_MIN_S, POOL_MAX=POOL_MAX,
    STATIC_OFFS_S=v1.STATIC_OFFS_S, STATIC_R=v1.STATIC_R, N_MAX=v1.N_MAX)

lattice = v1.lattice
path_obs = v1.path_obs


def _pass(L, pts):
    """One greedy multi-track pass in increasing `pts`. Returns list of node paths."""
    n = len(L)
    pts = np.asarray(pts, dtype=np.float64)
    EV = [np.clip(np.log(np.maximum(a[:, 4], 1e-6) / C_BG), EV_MIN, EV_MAX) if len(a) else np.zeros(0)
          for a in L]
    tracks = []  # dict: nodes, x, y, vx, vy, area, scale, last_f, alive, merged_into, merge_at
    live = []
    for f in range(n):
        a = L[f]
        taken = np.zeros(len(a), dtype=bool)
        if len(a) and live:
            sj = np.minimum(np.sqrt(a[:, 2] * a[:, 3]), SCALE_CAP)
            areaj = np.maximum(a[:, 2] * a[:, 3], 1e-9)
            T = [tracks[k] for k in live]
            lf = np.array([t['last_f'] for t in T])
            dt = pts[f] - pts[lf]
            px = np.array([t['x'] for t in T]) + np.array([t['vx'] for t in T]) * dt
            py = np.array([t['y'] for t in T]) + np.array([t['vy'] for t in T]) * dt
            sc = 0.5 * (np.array([t['scale'] for t in T])[:, None] + sj[None, :])
            erel = np.hypot(a[None, :, 0] - px[:, None], a[None, :, 1] - py[:, None]) / np.maximum(sc, 1e-6)
            lsz = np.abs(np.log(areaj[None, :] / np.array([t['area'] for t in T])[:, None]))
            ok = (erel <= E_REL_MAX) & (lsz <= SIZE_TOL)
            score = np.where(ok, -erel ** 2 / (2 * SIG_REL ** 2) - W_SIZE * lsz + KAPPA * EV[f][None, :], -np.inf)
            best = np.argmax(score, axis=1)
            got = np.isfinite(score[np.arange(len(T)), best])
            # update tracks that found a successor
            owner = {}
            for r, k in enumerate(live):
                t = tracks[k]
                if not got[r]:
                    continue
                j = int(best[r])
                d = dt[r]
                nvx = (a[j, 0] - t['x']) / d
                nvy = (a[j, 1] - t['y']) / d
                al = 1.0 if len(t['nodes']) == 1 else VEL_ALPHA
                vx = al * nvx + (1 - al) * t['vx']
                vy = al * nvy + (1 - al) * t['vy']
                if math.hypot(vx, vy) > V_SMOOTH_MAX:
                    continue
                t.update(x=float(a[j, 0]), y=float(a[j, 1]), vx=vx, vy=vy,
                         area=float(areaj[j]), scale=float(sj[j]), last_f=f)
                t['nodes'].append((f, j))
                taken[j] = True
                owner.setdefault(j, []).append(k)
            # merge duplicates: same detection, same motion -> the younger stops
            for j, ks in owner.items():
                if len(ks) < 2:
                    continue
                ks = sorted(ks, key=lambda k: (-len(tracks[k]['nodes']), k))
                keep = [ks[0]]
                for k in ks[1:]:
                    t = tracks[k]
                    s = next((tracks[q] for q in keep
                              if math.hypot(tracks[q]['vx'] - t['vx'], tracks[q]['vy'] - t['vy']) <= MERGE_DV), None)
                    if s is None:
                        keep.append(k)
                        continue
                    t['alive'] = False
                    t['merged_into'] = next(q for q in keep if tracks[q] is s)
                    t['merge_at'] = len(s['nodes']) - 1  # survivor index of the shared node
        # retire tracks whose absence exceeds the bridge limit
        live = [k for k in live if tracks[k]['alive'] and pts[f] - pts[tracks[k]['last_f']] <= NULL_MAX_S + 1e-9]
        # seed untaken nodes
        for j in np.nonzero(~taken)[0]:
            j = int(j)
            k = len(tracks)
            tracks.append({'nodes': [(f, j)], 'x': float(a[j, 0]), 'y': float(a[j, 1]), 'vx': 0.0, 'vy': 0.0,
                           'area': float(max(a[j, 2] * a[j, 3], 1e-9)),
                           'scale': float(min(math.sqrt(a[j, 2] * a[j, 3]), SCALE_CAP)),
                           'last_f': f, 'alive': True, 'merged_into': None, 'merge_at': None})
            live.append(k)
    # materialize paths: own nodes + survivor continuation after a merge
    out = []
    for k, t in enumerate(tracks):
        nodes = list(t['nodes'])
        cur, seen = t, {k}
        while cur['merged_into'] is not None and cur['merged_into'] not in seen:
            s = tracks[cur['merged_into']]
            seen.add(cur['merged_into'])
            nodes += s['nodes'][cur['merge_at'] + 1:]
            cur = s
        out.append(nodes)
    return out


def search(frames):
    pts = [f['pts_s'] for f in frames]
    if any(b <= a for a, b in zip(pts, pts[1:])):
        raise ValueError('strictly increasing PTS required')
    L = lattice(frames)
    n = len(L)
    fwd = _pass(L, pts)
    bwd = _pass(L[::-1], [-t for t in pts[::-1]])
    bwd = [[(n - 1 - f, j) for f, j in reversed(p)] for p in bwd]
    fdt = [(pts[f + 1] - pts[f]) if f + 1 < n else (pts[f] - pts[f - 1]) for f in range(n)]
    cands = []
    for p in fwd + bwd:
        obs_s = sum(fdt[f] for f, _ in p)
        if obs_s >= MIN_OBS_S:
            cands.append((obs_s, p))
    # deterministic readout order: longest observation first
    cands.sort(key=lambda c: (-round(c[0], 9), c[1][0], len(c[1])))
    pool, owned = [], set()
    for obs_s, p in cands:
        if len(pool) >= POOL_MAX:
            break
        novel = sum(fdt[f] for f, j in p if (f, j) not in owned)
        if novel < NOVEL_MIN_S:
            continue
        owned.update(p)
        pool.append((obs_s, p))
    return pool, L


def path_id(path, L):
    sig = SEARCH_VERSION + '|' + ','.join(f'{f}:{L[f][j][0]:.6f},{L[f][j][1]:.6f}' for f, j in path)
    return 'fsr-' + hashlib.sha256(sig.encode()).hexdigest()[:16]
