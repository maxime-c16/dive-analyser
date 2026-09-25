"""DEV-authority evaluation of a flight search (design-time only; never loads FLIGHT_GT_HUMAN_V1).

Usage: python3 fsr_dev_eval_v1.py <module> [rep ...]   (module exposes search(frames) -> (pool, L))
"""
import importlib
import json
import sys
import time

import fsr_common_v1 as C


def evaluate(mod, reps=('360', 'hq'), dives=None, quiet=False):
    rows = {}
    for rep in reps:
        for d in dives or C.EVENT_DIVES:
            fr = C.frames(d, rep)
            pts = [f['pts_s'] for f in fr]
            w = C.event_window(d)
            A = C.in_window(C.dev_anchors(d, pts), pts, w)
            CH = C.in_window(C.chain_anchors(d, pts), pts, w)
            t = time.time()
            pool, L = mod.search(fr)
            el = time.time() - t
            scored = []
            for rank, (T, path) in enumerate(pool, 1):
                obs = mod.path_obs(path, L)
                sa = C.score_track(obs, A)
                sc = C.score_track(obs, CH) if CH else None
                scored.append((rank, T, sa, sc))
            rec = [r for r, _, sa, _ in scored if sa['recovered']]
            best = max(scored, key=lambda x: (x[2]['coverage'], x[2]['purity'] or 0, -x[0]), default=None)
            bestc = max(scored, key=lambda x: (x[3]['coverage'] if x[3] else 0), default=None) if CH else None
            row = {'anchors': len(A), 'pool': len(pool), 'first_recovered_rank': rec[0] if rec else None,
                   'best_cov': round(best[2]['coverage'], 3) if best else 0, 'best_pur': best[2]['purity'] if best else None,
                   'best_rank': best[0] if best else None,
                   'chain_best_cov': round(bestc[3]['coverage'], 3) if bestc else None,
                   'chain_best_rank': bestc[0] if bestc else None, 'runtime_s': round(el, 1)}
            for k in (1, 3, 5, 10):
                row[f'top{k}'] = bool(rec and rec[0] <= k)
            row['pool_recovered'] = bool(rec)
            rows[(d, rep)] = row
            if not quiet:
                print(d, rep, row, flush=True)
    for rep in reps:
        rs = [v for (d, r), v in rows.items() if r == rep]
        print(f'== {rep}: pool {sum(r["pool_recovered"] for r in rs)}/{len(rs)}  '
              + '  '.join(f'top{k} {sum(r[f"top{k}"] for r in rs)}' for k in (1, 3, 5, 10)))
    return rows


if __name__ == '__main__':
    mod = importlib.import_module(sys.argv[1])
    reps = tuple(sys.argv[2:]) or ('360', 'hq')
    evaluate(mod, reps)
