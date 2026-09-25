"""POST-SEALED design evaluation on FLIGHT_GT_HUMAN_V1 (burned for v2 design; disclosed).

The frozen v1 result on this authority is final (fsr_final_eval_v1). Anything evaluated
here after that is ADAPTIVE and must be confirmed on a fresh held-out authority.
"""
import sys

import fsr_common_v1 as C
import fsr_final_eval_v1 as FE
import fsr_pipeline_v1 as P
import fsr_pool_cache_v1 as PC

_AUTH = None


def auth():
    global _AUTH
    if _AUTH is None:
        _AUTH = C.load_eval_authority(FE.PROTOCOL_SHA)
    return _AUTH


def evaluate(mod, reps_list=(('360',), ('hq',), ('360', 'hq')), dives=None, label=''):
    A_ = auth()
    summary = {}
    for reps in reps_list:
        res = {}
        pool_rec = 0
        for d in dives or C.COHORT:
            if 'hq' in reps and d not in C.HQ_DIVES:
                continue
            pts = [f['pts_s'] for f in C.frames(d, '360')]
            A = FE.flight_anchors(A_, d, pts)
            for rep in reps:
                pool, L = PC.pool(mod, d, rep)
                if any(C.score_track({f: tuple(L[f][j]) for f, j in p}, A)['recovered'] for _, p in pool):
                    pool_rec += 1
                    break
            out = P.surface(d, reps, mod=mod, max_surfaced=100000)
            rec = [c['rank'] for c in out if C.score_track(c['obs'], A)['recovered']]
            res[d] = rec[0] if rec else None
        n = len(res)
        line = f'pool {pool_rec}/{n} ' + ' '.join(f'top{k} {sum(1 for v in res.values() if v and v <= k)}' for k in (1, 5, 10, 20)) + \
            f' any {sum(1 for v in res.values() if v)}'
        print(f'{label} {"+".join(reps):7s} {line} | ' + ' '.join(f'{d}:{v}' for d, v in res.items()), flush=True)
        summary['+'.join(reps)] = res
    return summary


if __name__ == '__main__':
    import importlib
    evaluate(importlib.import_module(sys.argv[1]), label=sys.argv[1])
