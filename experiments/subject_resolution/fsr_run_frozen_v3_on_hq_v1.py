#!/usr/bin/env python3
"""Frozen V3 (flight_anchored_traj_v3.infer, byte-unchanged) on the HQ D5 caches.

Isolates the resolution effect on the *current* pipeline: same code, same
constants, same D5 recipe; only the candidate cache differs (HQ pixels mapped to
the proxy frame/timeline). GT-free. Outputs runs/flight_search_recovery_v1/v3_on_hq/.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import flight_anchored_traj_v3 as f3  # noqa: E402
import run_multi_track_action_v1 as v1run  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'runs/flight_search_recovery_v1/v3_on_hq'
CACHE = ROOT / 'runs/flight_search_recovery_v1/HQ_D5_CANDIDATES_V1.json'


def main(ids):
    raw = json.loads(CACHE.read_text())
    fps, pts360 = {}, {}
    for g, p in v1run.CACHES.items():
        r = json.loads(p.read_text())
        for d, x in r['dives'].items():
            fps[d] = float(x['fps'])
            pts360[d] = [f['pts_s'] for f in x['frames']]
    OUT.mkdir(parents=True, exist_ok=True)
    for d in ids or sorted(raw['dives']):
        doc = raw['dives'][d]
        t = time.time()
        # HQ cache frames carry extra provenance keys; inference_view strips them
        assert [f['pts_s'] for f in doc['frames']] == pts360[d], (d, 'proxy timeline mismatch')
        res = f3.infer(f3.inference_view(doc['frames']), fps[d])
        res['clip_id'] = d
        res['frame_pts'] = [f['pts_s'] for f in doc['frames']]
        res['input'] = 'HQ_D5_CANDIDATES_V1'
        (OUT / f'{d}.json').write_text(json.dumps(res, indent=1, sort_keys=True))
        print(d, round(time.time() - t, 1), res['lattice'], flush=True)


if __name__ == '__main__':
    main(sys.argv[1:])
