"""FAT2 fresh S3 floor caches (GT-free inference; no HUMAN data read).

Dives: 1190 (360 + strictly-aligned HQ), 1279 (360, decode-recorded PTS),
2838 (360). Backup 1194 built only if needed. Schema identical to the FAT1
SELECTED_TRACK caches (frames: pts_s, fi (1-based), n, c; floor conf 0.001,
NMS 0.45, imgsz 640, cap 200; hq mapped to proxy timeline by nearest time).
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

MAC = Path('/Users/maximecauchy/.perso')
SUCCESSOR = MAC / 'diveanalyzer-flight-perception-successor'
PROXIES = SUCCESSOR / 'media/fps_v1/proxies'
PTS_INDEX = SUCCESSOR / 'runs/flight_perception_successor_v1/PROXY_PTS_INDEX_V1.json'
REGISTRY = SUCCESSOR / 'runs/flight_perception_successor_v1/HQ_REGISTRY_V1.json'
ALIGNMENT = SUCCESSOR / 'runs/flight_perception_successor_v1/HQ_ALIGNMENT_VERIFY_V1.json'
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPLIT = ROOT / 'docs' / 'science' / 'FLIGHT_PERCEPTION_SUCCESSOR_SPLIT_V1.json'
WEIGHTS = ROOT / 'runs' / 's3_weights' / 'S3_S2init_DS2_OOD_last.pt'
MODEL_SHA = '3dc07f69cbe3824490f73c14a59ed328ff35fc2da48da2fd4e324acf9bcc4e9a'
OUT = ROOT / 'runs' / 'full_action_fax_v1' / 'caches'

DIVES_360 = ('1190', '1279', '2838')
DIVES_HQ = ('1190',)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def proxy_sha_expected(d):
    for x in json.loads(SPLIT.read_text())['roles']['FRESH_FLIGHT_HOLDOUT']['dives']:
        if str(x['dive_id']) == d:
            return x['proxy_360p_sha256']
    return None


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
    pts_index = json.loads(PTS_INDEX.read_text())
    out360 = OUT / 'CAND_S3_FAT2_360.json'
    out = json.loads(out360.read_text()) if out360.exists() else {
        'label': 'FAT2_FRESH_S3_360_DEVELOPMENT', 'model_sha256': MODEL_SHA,
        'floor_conf': .001, 'nms_iou': .45, 'imgsz': 640, 'floor_cap': 200,
        'representation': '360', 'coordinate_frame': 'PROXY_NORMALIZED',
        'timeline': 'PROXY frame timeline', 'gt_payload': 'NONE', 'dives': {}}
    assert out['model_sha256'] == MODEL_SHA
    for d in DIVES_360:
        if d in out['dives']:
            print('360', d, 'cached, skip', flush=True)
            continue
        proxy = PROXIES / f'{d}.mp4'
        expected = proxy_sha_expected(d)
        if expected is not None:
            assert sha(proxy) == expected, (d, 'proxy SHA mismatch')
            pts = pts_index[d]['pts']
            assert pts_index[d]['size'] == [202, 360], d
        else:
            pts = None  # 1279: decode-recorded timeline (no upstream index)
        rows, spts = infer(proxy, device, model)
        if pts is None:
            assert all(b > a for a, b in zip(spts, spts[1:])), (d, 'non-monotonic decode PTS')
            pts = [round(t, 6) for t in spts]
            print(d, 'decode-recorded PTS, n=', len(pts), 'proxy_sha256=', sha(proxy), flush=True)
        else:
            assert [round(t, 6) for t in spts] == pts, (d, 'decode PTS != index')
        frames = [{'pts_s': t, 'fi': k + 1, 'n': len(c), 'c': c} for k, (t, c) in enumerate(zip(pts, rows))]
        out['dives'][d] = {'source': str(proxy), 'proxy_sha256': sha(proxy),
                           'n_frames': len(frames), 'frames': frames}
        OUT.mkdir(parents=True, exist_ok=True)
        out360.write_text(json.dumps(out))
        print('360', d, len(frames), datetime.datetime.now(datetime.timezone.utc).isoformat(), flush=True)
    # HQ for 1190 (strict alignment only)
    alignment = json.loads(ALIGNMENT.read_text())
    registry = json.loads(REGISTRY.read_text())
    outhq = OUT / 'CAND_S3_FAT2_hq.json'
    outh = json.loads(outhq.read_text()) if outhq.exists() else dict(out, label='FAT2_FRESH_S3_hq_DEVELOPMENT',
                                                                     representation='hq', dives={})
    for d in DIVES_HQ:
        if d in outh['dives']:
            print('hq', d, 'cached, skip', flush=True)
            continue
        assert alignment[d]['pass'], d
        src = registry[d]
        assert src['status'] == 'VERIFIED' and src['map'] == {
            'dt': 0.0, 'x_off': 0.0, 'x_span': 1.0, 'y_off': 0.0, 'y_span': 1.0}, d
        path = Path(src['path'])
        assert sha(path) == src['sha256'], d
        pts = pts_index[d]['pts']
        rows, spts = infer(path, device, model)
        ha = np.array(spts)
        assert len(rows) == alignment[d]['hq_frames'], d
        mapped = []
        for t in pts:
            j = int(np.argmin(np.abs(ha - t)))
            mapped.append(rows[j] if abs(ha[j] - t) <= .5 / 24 else [])
        assert len(mapped) == len(pts), d
        frames = [{'pts_s': t, 'fi': k + 1, 'n': len(c), 'c': c} for k, (t, c) in enumerate(zip(pts, mapped))]
        outh['dives'][d] = {'source': str(path), 'proxy_sha256': out['dives'][d]['proxy_sha256'],
                            'n_frames': len(frames), 'frames': frames}
        outhq.write_text(json.dumps(outh))
        print('hq', d, len(frames), datetime.datetime.now(datetime.timezone.utc).isoformat(), flush=True)


if __name__ == '__main__':
    main()
