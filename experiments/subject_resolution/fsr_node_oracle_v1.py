"""Design-time diagnostic: is each subject node's OWN best-through path a flight recovery?

Separates representation (the DP's per-node path follows the subject) from readout
(pool ordering/novelty). DEV authority only.
"""
import sys
import math
import importlib
import numpy as np
import fsr_common_v1 as C


def node_paths(mod, fr):
    pts = [f['pts_s'] for f in fr]
    L = mod.lattice(fr)
    Ff, BFf, BJf, _, _, EV = mod._dp(L, pts)
    n = len(L)
    Fr, BFr, BJr, _, _, _ = mod._dp(L[::-1], [-t for t in pts[::-1]])
    T = [Ff[f] + Fr[n - 1 - f] for f in range(n)]

    def through(f, j):
        back = mod._backtrack(BFf, BJf, f, j)
        fr_ = mod._backtrack(BFr, BJr, n - 1 - f, j)
        return back + [(n - 1 - g, k) for g, k in fr_[::-1]][1:]
    allT = np.sort(np.concatenate([t for t in T if len(t)]))[::-1]
    return L, T, through, allT


if __name__ == '__main__':
    mod = importlib.import_module(sys.argv[1])
    rep = sys.argv[2]
    for d in (sys.argv[3:] or C.EVENT_DIVES):
        fr = C.frames(d, rep)
        pts = [f['pts_s'] for f in fr]
        w = C.event_window(d)
        A = C.in_window(C.dev_anchors(d, pts), pts, w)
        L, T, through, allT = node_paths(mod, fr)
        res = []
        for fp, a in sorted(A.items()):
            if not len(L[fp]):
                res.append('noNode')
                continue
            dist = np.hypot(L[fp][:, 0] - a[0], L[fp][:, 1] - a[1])
            js = [int(j) for j in np.nonzero(dist <= C.RADIUS)[0]]
            if not js:
                res.append('noNode')
                continue
            j = max(js, key=lambda k: T[fp][k])
            path = through(fp, j)
            sc = C.score_track(mod.path_obs(path, L), A)
            rank = int(np.searchsorted(-allT, -T[fp][j]))
            res.append(f"{'REC' if sc['recovered'] else 'no'}(c{sc['coverage']:.2f},p{(sc['purity'] or 0):.2f},T{T[fp][j]:.0f},rk{rank})")
        print(d, rep, ' '.join(res), flush=True)
