"""FAT3 S3 floor caches (GT-free inference; no HUMAN data read).

Dives: 16/251/1491/1716/2519/2742 (queued) + 735 (reserve). Proxy-only
(no HQ arm this round). Schema identical to the FAT2 SELECTED_TRACK caches
(frames: pts_s, fi (1-based), n, c; floor conf 0.001, NMS 0.45, imgsz 640,
cap 200). Proxy SHA asserted vs the frozen queue table; decode PTS asserted
vs PROXY_REGISTRY_FAT3 (same cv2 method as the proxy build).
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

WORKROOT = Path('/Users/maximecauchy/.perso/diveanalyzer-fullaction-fat3')
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROXIES = WORKROOT / 'runs' / 'fat3_media' / 'proxies'
REGISTRY = WORKROOT / 'runs' / 'fat3_media' / 'PROXY_REGISTRY_FAT3.json'
WEIGHTS = WORKROOT / 'runs' / 's3_weights' / 'S3_S2init_DS2_OOD_last.pt'
MODEL_SHA = '3dc07f69cbe3824490f73c14a59ed328ff35fc2da48da2fd4e324acf9bcc4e9a'
OUT = WORKROOT / 'runs' / 'full_action_fat3' / 'caches'

DIVES_360 = ('16', '251', '1491', '1716', '2519', '2742', '735')

PROXY_SHA = {
    '16': '0bd5b9cfc001ffdf4963fec2ce1533449513fa61edf81ca8959a355ad99d69cc',
    '251': 'd2d1d784fb55bcef35d1de9ee3459834bea6225e4cc9442a8f14be3017afcbbc',
    '1491': 'a9f1fbfb6ae1eb19caf85a44120c57f50a4105b69ad1055719624aec9d67c49c',
    '1716': 'ada7c0845050ce69bbe8a25a62d254210d4ed615c7c78eee6640eeaaa023606f',
    '2519': '210bf6d389cdcd87deeceb611e153fbf47d88b7ceb02fe2938978ccb3f52495a',
    '2742': 'fa0d464752db46dad67f6bc2c9577519c62e1f2b0ac4822968595793bd09692c',
    '735': 'e96a90d6261793f1c6137295b87a24cba2cd0e97b30d32def7a74bc42d25368c',
}


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
    out360 = OUT / 'CAND_S3_FAT3_360.json'
    out = json.loads(out360.read_text()) if out360.exists() else {
        'label': 'FAT3_FRESH_S3_360_DEVELOPMENT', 'model_sha256': MODEL_SHA,
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
