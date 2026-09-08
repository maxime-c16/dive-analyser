#!/usr/bin/env python3
"""Train DIVER_DETECTOR_D4_A — Phase G.

D4-A: Fresh COCO-pretrained YOLOv8n on DIVER_LOCALIZATION_DATASET_D4.
Fixes D3's confidence calibration failure (BELOW_THRESHOLD frames for failure dives).

Required: amp=False (MPS AMP suppresses classification gradient — D2-like collapse).
"""
import os, json, datetime, hashlib, time

REPO = os.path.expanduser("~/dive-analyser")
os.chdir(REPO)

DATASET_YAML = "/tmp/d4_work/DIVER_LOCALIZATION_DATASET_D4/dataset.yaml"
OUT_DIR = "/tmp/d4_work/runs/DIVER_DETECTOR_D4_A"
WEIGHTS_OUT = "models/frozen/DIVER_DETECTOR_D4_A_V8N_best.pt"

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs("models/frozen", exist_ok=True)

from ultralytics import YOLO

print("=" * 60)
print("DIVER_DETECTOR_D4_A training")
print("Base weights: yolov8n.pt (COCO-pretrained, fresh)")
print("amp=False (MPS AMP fix)")
print("=" * 60)

model = YOLO("yolov8n.pt")

t0 = time.time()
results = model.train(
    data=DATASET_YAML,
    epochs=150,
    imgsz=640,
    batch=8,
    device="mps",
    amp=False,           # CRITICAL: MPS AMP causes gradient collapse
    patience=25,         # early stop after 25 epochs no improvement
    project=OUT_DIR,
    name="train",
    exist_ok=True,
    save_period=-1,      # only save best/last
    verbose=True,
    workers=0,           # avoid multiprocessing on Mac
    cache=False,
    # Mild augmentation — avoid degrading good proposals
    hsv_h=0.015, hsv_s=0.7, hsv_v=0.4,
    fliplr=0.5,
    degrees=0.0,         # no rotation (diver always upright)
    translate=0.1,
    scale=0.5,
    mosaic=0.5,          # reduce mosaic for small val set
)

elapsed = time.time() - t0
print(f"\nTraining complete: {elapsed:.1f}s")

# Find best weights
best_pt = f"{OUT_DIR}/train/weights/best.pt"
if not os.path.exists(best_pt):
    best_pt = f"{OUT_DIR}/train/weights/last.pt"
    print("WARNING: best.pt not found, using last.pt")

# SHA256 of best weights
h = hashlib.sha256()
with open(best_pt,'rb') as f:
    for chunk in iter(lambda: f.read(1<<20), b''): h.update(chunk)
weights_sha = h.hexdigest()
weights_sz = os.path.getsize(best_pt)

# Copy to frozen location
import shutil
shutil.copy2(best_pt, WEIGHTS_OUT)
print(f"Frozen weights: {WEIGHTS_OUT}")
print(f"  SHA256: {weights_sha}")
print(f"  Size: {weights_sz} bytes")

# Extract best metrics from results
try:
    best_map50 = float(results.results_dict.get('metrics/mAP50(B)', 0))
    best_precision = float(results.results_dict.get('metrics/precision(B)', 0))
    best_recall = float(results.results_dict.get('metrics/recall(B)', 0))
except:
    best_map50 = best_precision = best_recall = 0.0

# Find best epoch from CSV
import csv
csv_path = f"{OUT_DIR}/train/results.csv"
best_epoch = 0
best_map = 0.0
if os.path.exists(csv_path):
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            m = float(row.get('metrics/mAP50(B)',0).strip() or 0)
            ep = int(row.get('epoch',0))
            if m > best_map:
                best_map = m
                best_epoch = ep
    best_map50 = best_map

train_json = {
    "label": "DIVER_DETECTOR_D4_A_V8N_TRAIN",
    "date": datetime.date.today().isoformat(),
    "model": "yolov8n",
    "base_weights": "yolov8n.pt (COCO-pretrained, fresh start)",
    "dataset": "DIVER_LOCALIZATION_DATASET_D4",
    "device": "mps",
    "amp": False,
    "repair": "amp=False (MPS AMP causes gradient collapse — same fix as D3)",
    "imgsz": 640,
    "batch": 8,
    "epochs_trained": 150,
    "best_epoch": best_epoch,
    "best_map50": round(best_map50, 5),
    "best_precision": round(best_precision, 5),
    "best_recall": round(best_recall, 5),
    "elapsed_s": round(elapsed, 2),
    "best_weights_sha256": weights_sha,
    "best_weights_size": weights_sz,
    "best_weights_path": WEIGHTS_OUT,
    "train_split": {"positive": 45, "negative": 17, "total": 62},
    "val_split": {"positive": 7, "negative": 3, "total": 10},
    "training_goal": "Fix confidence calibration: push BELOW_THRESHOLD failure frames to TARGET_AVAILABLE",
    "key_addition": "19 annotated frames from failure dives 2341(->holdout) 2555,2680,676,2541(->train)",
}

out_json = "docs/science/DIVER_DETECTOR_D4_A_V8N_TRAIN.json"
with open(out_json,'w') as f: json.dump(train_json, f, indent=2)
print(f"\nTrain record: {out_json}")
print(f"Best mAP50: {best_map50:.4f}  Precision: {best_precision:.4f}  Recall: {best_recall:.4f}")
print("DONE")
