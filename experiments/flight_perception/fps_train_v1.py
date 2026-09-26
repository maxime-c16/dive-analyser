#!/usr/bin/env python3
"""DIVE_ANALYZER_FLIGHT_PERCEPTION_SUCCESSOR_V1 — bounded D5-successor training.

One recipe family, few justified variants (registered by name below). Frozen D5 is never
modified: training starts from a COPY of its weights (or COCO yolov8n for the init
ablation) and writes a new, sha-pinned experimental checkpoint outside Git
(runs/flight_perception_successor_v1/models/<name>/weights/last.pt) + MODEL_REGISTRY_V1.

M2 safety: one training at a time, caffeinate, MPS, amp=False (known MPS AMP bug, D3 packet),
workers 2, fixed epochs (no early stopping on the validation set; the checkpoint used is
`last.pt` so selection happens only through the flight funnel on MODEL_SELECTION_VALIDATION).

Usage: caffeinate -i -s python3 fps_train_v1.py <variant>
"""
from __future__ import annotations

import datetime
import json
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fps_media_v1 as fm  # noqa: E402

D5 = fm.ROOT / 'models/frozen/DIVER_DETECTOR_D5_A_V8N_best.pt'
D5_SHA = '82b420c4583f8271b1eb3429b14dadf0a1e27477249de7b6a0b9d42a788dcf25'
COCO_N = fm.PERSO / 'diveanalyzer/yolov8n.pt'
BASE_AUG = dict(mosaic=0.5, mixup=0.0, degrees=10.0, translate=0.1, scale=0.5, flipud=0.0, fliplr=0.5,
                hsv_h=0.015, hsv_s=0.4, hsv_v=0.3, close_mosaic=10)
VARIANTS = {
    # pilot: existing labels only (HIST + FGT1 event boxes), D5 init
    'S0_pilot_DS0': dict(dataset='DS0_HIST_FGT1', init='D5', epochs=60, imgsz=640, batch=16, aug=BASE_AUG),
}


def main():
    name = sys.argv[1]
    v = VARIANTS[name]
    from ultralytics import YOLO
    ds = fm.RUNS / 'datasets' / v['dataset']
    man = json.loads((ds / 'MANIFEST.json').read_text())
    assert not man['holdout_read']
    init = {'D5': D5, 'COCO': COCO_N}[v['init']]
    if v['init'] == 'D5':
        assert fm.sha256_file(init) == D5_SHA
    work = fm.RUNS / 'models'
    if (work / name).exists():
        shutil.rmtree(work / name)
    init_copy = work / f'{name}_init.pt'
    work.mkdir(parents=True, exist_ok=True)
    shutil.copy(init, init_copy)  # never train on the frozen file path itself
    t0 = time.time()
    model = YOLO(str(init_copy))
    model.train(data=str(ds / 'dataset.yaml'), epochs=v['epochs'], imgsz=v['imgsz'], batch=v['batch'],
                device='mps', amp=False, workers=2, patience=0, project=str(work), name=name, exist_ok=True,
                seed=0, deterministic=True, plots=False, verbose=False, **v['aug'])
    assert fm.sha256_file(D5) == D5_SHA, 'frozen D5 mutated'
    ck = work / name / 'weights/last.pt'
    reg = json.loads(fps_reg().read_text()) if fps_reg().exists() else {}
    reg[name] = {'path': str(ck), 'sha256': fm.sha256_file(ck), 'variant': v, 'dataset_digest': man['digest'],
                 'init_sha256': fm.sha256_file(init_copy), 'status': 'EXPERIMENTAL',
                 'train_runtime_s': round(time.time() - t0, 1),
                 'created': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    fps_reg().write_text(json.dumps(reg, indent=1, sort_keys=True))
    print('registered', name, reg[name]['sha256'][:16], reg[name]['train_runtime_s'], 's')


def fps_reg():
    return fm.RUNS / 'MODEL_REGISTRY_V1.json'


if __name__ == '__main__':
    main()
