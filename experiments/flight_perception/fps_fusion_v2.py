#!/usr/bin/env python3
"""GT-free union of frozen S2 and D5 proposals for the frozen FSR input.

S2 wins only when boxes overlap; D5 retains its independent low-confidence
observations. The FSR 200-candidate frame cap remains unchanged. No confidence
calibration, search parameter, or representation-specific rule is introduced.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / 'runs/flight_perception_successor_v1'
D5_SHA = '82b420c4583f8271b1eb3429b14dadf0a1e27477249de7b6a0b9d42a788dcf25'
S2_SHA = 'd3ba0b035e7a8eb20bb5af66db62984bfb4682075b0c1267677d293e0e9d9c7f'
KEY = 'F1_S2_D5_UNION'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def iou(a, b):
    ax0, ay0, ax1, ay1 = a['cx']-a['bw']/2, a['cy']-a['bh']/2, a['cx']+a['bw']/2, a['cy']+a['bh']/2
    bx0, by0, bx1, by1 = b['cx']-b['bw']/2, b['cy']-b['bh']/2, b['cx']+b['bw']/2, b['cy']+b['bh']/2
    w, h = max(0, min(ax1, bx1)-max(ax0, bx0)), max(0, min(ay1, by1)-max(ay0, by0))
    inter = w*h
    return inter / (a['bw']*a['bh']+b['bw']*b['bh']-inter) if inter else 0.0


def fuse_frame(d5, s2):
    # A matching D5 box is the same observation; retain S2's better-localized
    # box and its unmodified confidence. Distinct people/locations stay distinct.
    extra = [c for c in d5 if not any(iou(c, s) >= .30 for s in s2)]
    out = sorted(s2 + extra, key=lambda c: (-c['conf'], c['cx'], c['cy'], c['bw'], c['bh']))
    return out[:200]


def build(rep, ids=None):
    paths = {k: RUN / 'caches' / f'CAND_{k}_{rep}.json' for k in ('D5', 'S2_COCOinit_DS1')}
    src = {k: json.loads(p.read_text()) for k, p in paths.items()}
    assert src['D5']['model_sha256'] == D5_SHA
    assert src['S2_COCOinit_DS1']['model_sha256'] == S2_SHA
    a, b = src['D5']['dives'], src['S2_COCOinit_DS1']['dives']
    ids = ids or sorted(set(a) & set(b), key=int)
    out = {'label': f'CAND_{KEY}_{rep}', 'packet': 'DIVE_ANALYZER_FLIGHT_PERCEPTION_RECOVERY_V2',
           'strategy': 'S2-first IoU>=0.30 dedup, raw confidence unchanged, top 200 per frame',
           'inputs': {k: {'path': str(p), 'sha256': sha(p), 'model_sha256': src[k]['model_sha256']}
                      for k, p in paths.items()},
           'representation': rep, 'gt_payload': 'NONE', 'dives': {}}
    for d in ids:
        af, bf = a[d]['frames'], b[d]['frames']
        assert len(af) == len(bf), d
        frames = []
        for x, y in zip(af, bf):
            assert x['fi'] == y['fi'] and x['pts_s'] == y['pts_s'], d
            c = fuse_frame(x['c'], y['c'])
            frames.append({'fi': x['fi'], 'pts_s': x['pts_s'], 'n': len(c), 'c': c})
        out['dives'][d] = {'frames': frames, 'proxy_sha256': a[d]['proxy_sha256']}
    dest = RUN / 'caches' / f'CAND_{KEY}_{rep}.json'
    dest.write_text(json.dumps(out))
    print(dest, len(ids), sha(dest), flush=True)


if __name__ == '__main__':
    build(sys.argv[1], sys.argv[2:])
