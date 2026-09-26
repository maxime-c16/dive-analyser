#!/usr/bin/env python3
"""GT-free detector quality route, keeping FSR and both baselines unchanged.

For a representation with no S2 detection >= 0.30 anywhere in the clip, use
the full D5 floor cache; otherwise use S2. The threshold was chosen on consumed
V2 development evidence and is fixed for every resolution. This retains all
legitimate people proposed by the selected detector, not one identity.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / 'runs/flight_perception_successor_v1'
KEY = 'F2_S2_D5_ROUTE'
THRESHOLD = .30


def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


def build(rep, ids=None):
    paths = {k: RUN / 'caches' / f'CAND_{k}_{rep}.json' for k in ('D5', 'S2_COCOinit_DS1')}
    src = {k: json.loads(p.read_text()) for k, p in paths.items()}
    assert src['D5']['model_sha256'] == '82b420c4583f8271b1eb3429b14dadf0a1e27477249de7b6a0b9d42a788dcf25'
    assert src['S2_COCOinit_DS1']['model_sha256'] == 'd3ba0b035e7a8eb20bb5af66db62984bfb4682075b0c1267677d293e0e9d9c7f'
    ids = ids or sorted(set(src['D5']['dives']) & set(src['S2_COCOinit_DS1']['dives']), key=int)
    out = {'label': f'CAND_{KEY}_{rep}', 'strategy': 'S2 if any clip detection confidence >= 0.30, else D5',
           'threshold': THRESHOLD, 'representation': rep, 'gt_payload': 'NONE',
           'inputs': {k: {'sha256': sha(p), 'model_sha256': src[k]['model_sha256']} for k, p in paths.items()},
           'routes': {}, 'dives': {}}
    for d in ids:
        frames = src['S2_COCOinit_DS1']['dives'][d]['frames']
        max_conf = max((c['conf'] for f in frames for c in f['c']), default=0.0)
        key = 'S2_COCOinit_DS1' if max_conf >= THRESHOLD else 'D5'
        out['routes'][d] = {'key': key, 's2_max_conf': max_conf}
        out['dives'][d] = src[key]['dives'][d]
    p = RUN / 'caches' / f'CAND_{KEY}_{rep}.json'
    p.write_text(json.dumps(out))
    print(p, len(ids), out['routes'], sha(p), flush=True)


if __name__ == '__main__':
    build(sys.argv[1], sys.argv[2:])
