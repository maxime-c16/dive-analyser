#!/usr/bin/env python3
"""One bounded S2 fine-tune using consumed V2 OOD HUMAN boxes.

S2 and D5 source weights remain immutable. Selection uses FGT1 and consumed
V2 diagnostics only; the fresh V3 holdout is not loaded before a final freeze.
"""
import datetime
import json
import shutil
import time
from pathlib import Path

import torch
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / 'runs/flight_perception_recovery_v2'
DS = RUN / 'datasets/DS2_DS1_FGT2_OOD'
OUT = RUN / 'models/S3_S2init_DS2_OOD'
S2 = ROOT.parent / 'diveanalyzer-flight-perception-successor/runs/flight_perception_successor_v1/models/S2_COCOinit_DS1/weights/last.pt'
S2_SHA = 'd3ba0b035e7a8eb20bb5af66db62984bfb4682075b0c1267677d293e0e9d9c7f'
D5 = ROOT.parent / 'diveanalyzer-flight-perception-successor/models/frozen/DIVER_DETECTOR_D5_A_V8N_best.pt'
D5_SHA = '82b420c4583f8271b1eb3429b14dadf0a1e27477249de7b6a0b9d42a788dcf25'


def sha(p):
    import hashlib
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


def main():
    assert sha(S2) == S2_SHA and sha(D5) == D5_SHA
    man = json.loads((DS / 'FPSR2_MANIFEST.json').read_text())
    assert not man['fresh_v3_holdout_read']
    assert not OUT.exists(), 'checkpoint already exists; keep it immutable'
    init = RUN / 'models/S3_init_copy.pt'
    init.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(S2, init)
    t0 = time.time()
    model = YOLO(str(init))
    model.train(data=str(DS / 'dataset.yaml'), epochs=20, imgsz=640, batch=16,
                device='mps' if torch.backends.mps.is_available() else 'cpu', amp=False,
                workers=2, patience=0, project=str(OUT.parent), name=OUT.name,
                exist_ok=False, seed=0, deterministic=True, plots=False, verbose=False,
                lr0=0.001, lrf=0.01, mosaic=0.3, mixup=0.0, degrees=10.0,
                translate=0.1, scale=0.5, flipud=0.0, fliplr=0.5,
                hsv_h=0.015, hsv_s=0.4, hsv_v=0.3, close_mosaic=5)
    assert sha(S2) == S2_SHA and sha(D5) == D5_SHA
    ck = OUT / 'weights/last.pt'
    reg = {'label': OUT.name, 'path': str(ck), 'sha256': sha(ck),
           'init_sha256': S2_SHA, 'dataset_digest': man['digest'],
           'fresh_holdout_read': False, 'epochs': 20, 'imgsz': 640, 'batch': 16,
           'device': 'mps' if torch.backends.mps.is_available() else 'cpu',
           'runtime_s': round(time.time()-t0, 1),
           'created': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    (RUN / 'MODEL_S3_REGISTRY.json').write_text(json.dumps(reg, indent=2, sort_keys=True))
    print(json.dumps(reg, indent=2), flush=True)


if __name__ == '__main__':
    main()
