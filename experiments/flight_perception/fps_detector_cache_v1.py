#!/usr/bin/env python3
"""DIVE_ANALYZER_FLIGHT_PERCEPTION_SUCCESSOR_V1 — full-clip candidate caches for any detector.

Same recipe as every frozen D5 floor cache (R5_FULLCLIP_CANDIDATES_*, HQ_D5_CANDIDATES_V1):
conf floor 0.001, NMS 0.45, imgsz 640, cap 200, device mps, sequential cv2 decode
from frame 0, full clip (no GT window). Only the weights and the input pixels vary:

- rep '360': the production 202x360 proxy.
- rep 'hq': the verified HQ edited rendition (fps_media_v1 registry), boxes mapped into
  the PROXY-normalized frame and onto the proxy timeline (nearest PTS under the
  verified map, tolerance 0.5/24 s), exactly as fsr_hq_cache_v1.

Output schema == frozen caches ({'dives': {d: {'frames': [{pts_s, fi, n, c:[{conf,cx,cy,bw,bh}]}]}}}),
so fsr_search_v1/fsr_rank_v1 consume it unchanged. No GT is read.

Usage: caffeinate -i -s python3 fps_detector_cache_v1.py <model_key> <rep> [dive ...]
"""
from __future__ import annotations

import datetime
import json
import resource
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fps_media_v1 as fm  # noqa: E402

FLOOR_CONF, NMS_IOU, IMGSZ, FLOOR_CAP = 0.001, 0.45, 640, 200
MODELS = {
    'D5': (fm.ROOT / 'models/frozen/DIVER_DETECTOR_D5_A_V8N_best.pt',
           '82b420c4583f8271b1eb3429b14dadf0a1e27477249de7b6a0b9d42a788dcf25'),
}
SUCC_REG = fm.RUNS / 'MODEL_REGISTRY_V1.json'  # successor checkpoints (outside Git), sha-pinned


def model_spec(key):
    if key in MODELS:
        return MODELS[key]
    reg = json.loads(SUCC_REG.read_text())
    return Path(reg[key]['path']), reg[key]['sha256']


def cache_path(key, rep):
    return fm.RUNS / 'caches' / f'CAND_{key}_{rep}.json'


def load_cache(key, rep):
    return json.loads(cache_path(key, rep).read_text())


def main():
    key, rep, ids = sys.argv[1], sys.argv[2], sys.argv[3:]
    assert rep in ('360', 'hq')
    import torch
    from ultralytics import YOLO
    mpath, msha = model_spec(key)
    assert fm.sha256_file(mpath) == msha, 'model identity'
    device = 'mps' if torch.backends.mps.is_available() else 'cpu'
    model = YOLO(str(mpath))
    out_p = cache_path(key, rep)
    out = json.loads(out_p.read_text()) if out_p.exists() else {
        'label': f'CAND_{key}_{rep}', 'packet': 'DIVE_ANALYZER_FLIGHT_PERCEPTION_SUCCESSOR_V1',
        'model': str(mpath), 'model_sha256': msha, 'floor_conf': FLOOR_CONF, 'nms_iou': NMS_IOU,
        'imgsz': IMGSZ, 'floor_cap': FLOOR_CAP, 'representation': rep,
        'coordinate_frame': 'PROXY_NORMALIZED', 'timeline': 'PROXY frame timeline',
        'gt_payload': 'NONE', 'dives': {}, 'runs': {}}
    assert out['model_sha256'] == msha
    for d in ids:
        fm.assert_allowed(d)
        if d in out['dives']:
            print('[skip]', d)
            continue
        if rep == 'hq' and not fm.hq_ok(d):
            print('[no-hq]', d)
            continue
        t0 = time.time()
        m = fm.hq_entry(d)['map'] if rep == 'hq' else {'dt': 0.0, 'x_off': 0.0, 'x_span': 1.0, 'y_off': 0.0, 'y_span': 1.0}

        def detect(fr):
            H, W = fr.shape[:2]
            pr = model(fr, conf=FLOOR_CONF, iou=NMS_IOU, imgsz=IMGSZ, verbose=False, device=device)[0].boxes
            c = []
            if pr is not None and len(pr):
                confs = pr.conf.cpu().numpy()
                boxes = pr.xyxy.cpu().numpy()
                for i in np.argsort(-confs)[:FLOOR_CAP]:
                    x1, y1, x2, y2 = boxes[i]
                    c.append({'conf': round(float(confs[i]), 6),
                              'cx': round(float(((x1 + x2) / 2 / W - m['x_off']) / m['x_span']), 6),
                              'cy': round(float(((y1 + y2) / 2 / H - m['y_off']) / m['y_span']), 6),
                              'bw': round(float((x2 - x1) / W / m['x_span']), 6),
                              'bh': round(float((y2 - y1) / H / m['y_span']), 6)})
            return c
        ppath, psha = fm.verified_proxy(d)
        src = ppath if rep == '360' else Path(fm.hq_entry(d)['path'])
        spts, sdet, SW, SH = fm.read_frames(src, detect)
        ppts = fm.proxy_pts(d)
        if rep == '360':
            assert [round(t, 6) for t in spts] == ppts, (d, 'proxy PTS drift')
            frames = [{'pts_s': t, 'fi': i + 1, 'n': len(c), 'c': c} for i, (t, c) in enumerate(zip(ppts, sdet))]
        else:
            ha = np.array(spts)
            frames = []
            for i, tp in enumerate(ppts):
                j = int(np.argmin(np.abs(ha - (tp - m['dt']))))
                ok = abs(ha[j] - (tp - m['dt'])) <= 0.5 / 24
                c = sdet[j] if ok else []
                frames.append({'pts_s': tp, 'fi': i + 1, 'n': len(c), 'c': c, 'hq_frame': j if ok else None})
        out['dives'][d] = {'source': str(src), 'proxy_sha256': psha, 'source_size': [SW, SH],
                           'n_frames': len(frames), 'frames': frames}
        out['runs'][d] = {'device': device, 'runtime_s': round(time.time() - t0, 1),
                          'peak_rss_gb': round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1 << 30), 2),
                          'at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(out))
        print('[cached]', key, rep, d, out['runs'][d], flush=True)


if __name__ == '__main__':
    main()
