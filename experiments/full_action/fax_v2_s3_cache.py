"""FAX2 S3 floor caches (GT-free inference; no HUMAN data read).

Dives: 16/251/1491/1716/2519/2742 (queued) + 735 (reserve). Proxy-only
(no HQ arm this round). Schema identical to the FAT2 SELECTED_TRACK caches
(frames: pts_s, fi (1-based), n, c; floor conf 0.001, NMS 0.45, imgsz 640,
cap 200). Proxy SHA asserted vs the frozen queue table; decode PTS asserted
vs PROXY_REGISTRY_FAX2 (same cv2 method as the proxy build).
Model SHA asserted before and after inference.
"""
import datetime
import hashlib
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import torch
from ultralytics import YOLO

WORKROOT = Path('/Users/maximecauchy/.perso/diveanalyzer-selected-flight-cycle')
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROXIES = WORKROOT / 'runs' / 'fax_v2_media' / 'proxies'
REGISTRY = WORKROOT / 'runs' / 'fax_v2_media' / 'PROXY_REGISTRY_FAX_V2.json'
WEIGHTS = Path('/Users/maximecauchy/.perso/diveanalyzer-fullaction-fat3/runs/s3_weights') / 'S3_S2init_DS2_OOD_last.pt'
MODEL_SHA = '3dc07f69cbe3824490f73c14a59ed328ff35fc2da48da2fd4e324acf9bcc4e9a'
OUT = WORKROOT / 'runs' / 'full_action_fax_v2' / 'caches'

DIVES_360 = ('205', '1751', '1621', '1363', '1440')

PROXY_SHA = {d: x['proxy_sha256'] for d, x in json.loads(REGISTRY.read_text()).items()}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def infer(path, device, model):
    cap = cv2.VideoCapture(str(path))
    rows, source_pts = [], []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        h, w = frame.shape[:2]
        boxes = model(frame, conf=.001, iou=.45, imgsz=640, verbose=False, device=device)[0].boxes
        cs = []
        if boxes is not None and len(boxes):
            xyxy = boxes.xyxy.cpu().numpy()
            conf = boxes.conf.cpu().numpy()
            for j in np.argsort(-conf)[:200]:
                x0, y0, x1, y1 = xyxy[j]
                cs.append({'conf': round(float(conf[j]), 6),
                           'cx': round(float((x0 + x1) / (2 * w)), 6),
                           'cy': round(float((y0 + y1) / (2 * h)), 6),
                           'bw': round(float((x1 - x0) / w), 6),
                           'bh': round(float((y1 - y0) / h), 6)})
        source_pts.append(cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0)
        rows.append(cs)
    cap.release()
    return rows, source_pts


def main():
    assert sha(WEIGHTS) == MODEL_SHA
    model = YOLO(str(WEIGHTS))
    assert sha(WEIGHTS) == MODEL_SHA
    device = 'mps' if torch.backends.mps.is_available() else 'cpu'
    print('device:', device, flush=True)
    reg = json.loads(REGISTRY.read_text())
    out360 = OUT / 'CAND_S3_FAX2_360.json'
    out = json.loads(out360.read_text()) if out360.exists() else {
        'label': 'FAX2_FRESH_S3_360_DEVELOPMENT', 'model_sha256': MODEL_SHA,
        'floor_conf': .001, 'nms_iou': .45, 'imgsz': 640, 'floor_cap': 200,
        'representation': '360', 'coordinate_frame': 'PROXY_NORMALIZED',
        'timeline': 'PROXY frame timeline', 'gt_payload': 'NONE', 'dives': {}}
    assert out['model_sha256'] == MODEL_SHA
    for d in DIVES_360:
        if d in out['dives']:
            print('360', d, 'cached, skip', flush=True)
            continue
        proxy = PROXIES / f'{d}.mp4'
        assert sha(proxy) == PROXY_SHA[d], (d, 'proxy SHA mismatch')
        pts = list(reg[d]['pts'])
        rows, spts = infer(proxy, device, model)
        assert [round(t, 6) for t in spts] == pts, (d, 'decode PTS != registry')
        frames = [{'pts_s': t, 'fi': k + 1, 'n': len(c), 'c': c} for k, (t, c) in enumerate(zip(pts, rows))]
        out['dives'][d] = {'source': str(proxy), 'proxy_sha256': sha(proxy),
                           'n_frames': len(frames), 'frames': frames}
        OUT.mkdir(parents=True, exist_ok=True)
        out360.write_text(json.dumps(out))
        print('360', d, len(frames), datetime.datetime.now(datetime.timezone.utc).isoformat(), flush=True)


if __name__ == '__main__':
    main()
