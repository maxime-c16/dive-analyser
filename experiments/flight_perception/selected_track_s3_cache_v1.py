"""S3 full-clip 360p proposal cache for the five preregistered DEVELOPMENT dives."""
import datetime
import hashlib
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import torch
from ultralytics import YOLO

import selected_track_annotation_v1 as A

ROOT = A.ROOT
WEIGHTS = ROOT.parent / 'diveanalyzer-flight-perception-recovery-v2/runs/flight_perception_recovery_v2/models/S3_S2init_DS2_OOD/weights/last.pt'
MODEL_SHA = '3dc07f69cbe3824490f73c14a59ed328ff35fc2da48da2fd4e324acf9bcc4e9a'
REGISTRY = A.SOURCE / 'runs/flight_perception_successor_v1/HQ_REGISTRY_V1.json'
ALIGNMENT = A.SOURCE / 'runs/flight_perception_successor_v1/HQ_ALIGNMENT_VERIFY_V1.json'


def main():
    rep = sys.argv[1] if len(sys.argv) > 1 else '360'
    assert rep in ('360', 'hq')
    out_path = ROOT / f'runs/selected_divetrack_v1/caches/CAND_S3_S2init_DS2_OOD_{rep}.json'
    assert hashlib.sha256(WEIGHTS.read_bytes()).hexdigest() == MODEL_SHA
    out = json.loads(out_path.read_text()) if out_path.exists() else {
        'label': f'SELECTED_TRACK_S3_{rep}_DEVELOPMENT', 'model_sha256': MODEL_SHA,
        'floor_conf': .001, 'nms_iou': .45, 'imgsz': 640, 'floor_cap': 200,
        'representation': rep, 'coordinate_frame': 'PROXY_NORMALIZED',
        'timeline': 'PROXY frame timeline', 'gt_payload': 'NONE', 'dives': {}}
    assert out['model_sha256'] == MODEL_SHA
    model = YOLO(str(WEIGHTS))
    device = 'mps' if torch.backends.mps.is_available() else 'cpu'
    for d in A.DIVES:
        if d in out['dives']:
            continue
        proxy_path, sha = A.Media.verified_proxy(d)
        pts = A.Media.proxy_pts(d)
        if rep == 'hq':
            assert json.loads(ALIGNMENT.read_text())[d]['pass'], d
            source = json.loads(REGISTRY.read_text())[d]
            assert source['status'] == 'VERIFIED' and source['map'] == {
                'dt': 0.0, 'x_off': 0.0, 'x_span': 1.0, 'y_off': 0.0, 'y_span': 1.0}, d
            path = Path(source['path'])
            assert hashlib.sha256(path.read_bytes()).hexdigest() == source['sha256'], d
        else:
            path = proxy_path
        cap = cv2.VideoCapture(str(path))
        rows = []
        source_pts = []
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
            source_pts.append(cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0)
            rows.append(cs)
            i += 1
        cap.release()
        if rep == '360':
            assert [round(t, 6) for t in source_pts] == pts, d
            mapped = rows
        else:
            assert i == json.loads(ALIGNMENT.read_text())[d]['hq_frames'], d
            ha = np.array(source_pts)
            mapped = []
            for t in pts:
                j = int(np.argmin(np.abs(ha - t)))
                mapped.append(rows[j] if abs(ha[j] - t) <= .5 / 24 else [])
        assert len(mapped) == len(pts), (d, len(mapped), len(pts))
        frames = [{'pts_s': t, 'fi': k + 1, 'n': len(c), 'c': c} for k, (t, c) in enumerate(zip(pts, mapped))]
        out['dives'][d] = {'source': str(path), 'proxy_sha256': sha,
                           'n_frames': len(frames), 'frames': frames}
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out))
        print(rep, d, i, len(frames), datetime.datetime.now(datetime.timezone.utc).isoformat(), flush=True)


if __name__ == '__main__':
    main()
