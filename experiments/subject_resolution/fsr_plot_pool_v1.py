"""Diagnostic: space-time plot of a search pool vs DEV anchors (design-time only)."""
import sys
import importlib
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import fsr_common_v1 as C


def plot(mod, d, rep, out, k=6):
    fr = C.frames(d, rep)
    pts = [f['pts_s'] for f in fr]
    w = C.event_window(d)
    A = C.dev_anchors(d, pts)
    CH = C.chain_anchors(d, pts)
    pool, L = mod.search(fr)
    lo, hi = w[0] - 1.5, w[1] + 1.0
    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
    for ax, ci, lab in [(axes[0], 1, 'cy'), (axes[1], 0, 'cx')]:
        T, V = [], []
        for f in range(len(L)):
            if lo <= pts[f] <= hi:
                for c in L[f]:
                    T.append(pts[f]); V.append(c[ci])
        ax.scatter(T, V, s=2, c='0.8')
        for fp, a in CH.items():
            if lo <= pts[fp] <= hi:
                ax.plot(pts[fp], a[ci], 'r.', ms=3)
        cols = plt.cm.tab10(np.arange(k))
        for r, (t, path) in enumerate(pool[:k]):
            P = np.array([[pts[f], L[f][j][ci]] for f, j in path if lo <= pts[f] <= hi])
            if len(P):
                ax.plot(P[:, 0], P[:, 1], '-', color=cols[r], lw=1.2, label=f'r{r+1} T={t:.0f} n={len(path)}')
        for fp, a in A.items():
            if lo <= pts[fp] <= hi:
                ax.plot(pts[fp], a[ci], 'kx', ms=10, mew=2)
        ax.axvline(w[0], color='k', ls='--'); ax.axvline(w[1], color='k', ls='--')
        if lab == 'cy':
            ax.invert_yaxis()
        ax.set_ylabel(lab)
        ax.legend(fontsize=7, loc='upper right')
    axes[0].set_title(f'{d} {rep} {mod.__name__}: non-static lattice (grey), chain (red), DEV human (x)')
    plt.tight_layout(); plt.savefig(out, dpi=70); plt.close()


if __name__ == '__main__':
    mod = importlib.import_module(sys.argv[1])
    for d in sys.argv[3:]:
        plot(mod, d, sys.argv[2], f'../../runs/flight_search_recovery_v1/diag/pool_{mod.__name__}_{d}_{sys.argv[2]}.png')
