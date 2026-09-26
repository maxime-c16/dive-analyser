"""S3 full-clip 360p proposal cache for the five preregistered DEVELOPMENT dives."""
import datetime
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import torch
from ultralytics import YOLO

import selected_track_annotation_v1 as A

ROOT = A.ROOT
WEIGHTS = ROOT.parent / 'diveanalyzer-flight-perception-recovery-v2/runs/flight_perception_recovery_v2/models/S3_S2init_DS2_OOD/weights/last.pt'
MODEL_SHA = '3dc07f69cbe3824490f73c14a59ed328ff35fc2da48da2fd4e324acf9bcc4e9a'
OUT = ROOT / 'runs/selected_divetrack_v1/caches/CAND_S3_S2init_DS2_OOD_360.json'


def main():
    assert hashlib.sha256(WEIGHTS.read_bytes()).hexdigest() == MODEL_SHA
    out = json.loads(OUT.read_text()) if OUT.exists() else {
        'label': 'SELECTED_TRACK_S3_360_DEVELOPMENT', 'model_sha256': MODEL_SHA,
        'floor_conf': .001, 'nms_iou': .45, 'imgsz': 640, 'floor_cap': 200,
        'representation': '360', 'coordinate_frame': 'PROXY_NORMALIZED',
        'timeline': 'PROXY frame timeline', 'gt_payload': 'NONE', 'dives': {}}
    assert out['model_sha256'] == MODEL_SHA
    model = YOLO(str(WEIGHTS))
    device = 'mps' if torch.backends.mps.is_available() else 'cpu'
    for d in A.DIVES:
        if d in out['dives']:
            continue
        path, sha = A.Media.verified_proxy(d)
        pts = A.Media.proxy_pts(d)
        cap = cv2.VideoCapture(str(path))
        rows = []
        i = 0
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
            rows.append({'pts_s': pts[i], 'fi': i + 1, 'n': len(cs), 'c': cs})
            i += 1
        cap.release()
        assert i == len(pts), (d, i, len(pts))
        out['dives'][d] = {'source': str(path), 'proxy_sha256': sha,
                           'n_frames': i, 'frames': rows}
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(out))
        print(d, i, len(rows), datetime.datetime.now(datetime.timezone.utc).isoformat(), flush=True)


if __name__ == '__main__':
    main()
