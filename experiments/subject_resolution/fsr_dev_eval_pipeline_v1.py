"""DEV-authority evaluation of the surfaced ranked candidate set (design-time only)."""
import sys

import fsr_common_v1 as C
import fsr_pipeline_v1 as P


def run(configs):
    for name, reps in configs:
        res = {}
        for d in C.EVENT_DIVES:
            fr = C.frames(d, '360')
            pts = [f['pts_s'] for f in fr]
            A = C.in_window(C.dev_anchors(d, pts), pts, C.event_window(d))
            out = P.surface(d, reps)
            rec = [t['rank'] for t in out if C.score_track(t['obs'], A)['recovered']]
            res[d] = rec[0] if rec else None
        line = '  '.join(f'top{k} {sum(1 for v in res.values() if v and v <= k)}' for k in (1, 3, 5, 10, 20, 50))
        print(f'{name:10s} {line}  | ' + ' '.join(f'{d}:{v}' for d, v in res.items()), flush=True)


if __name__ == '__main__':
    run([('360', ('360',)), ('hq', ('hq',)), ('360+hq', ('360', 'hq'))])
