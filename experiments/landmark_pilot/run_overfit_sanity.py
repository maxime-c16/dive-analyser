"""
Phase F — Overfit Sanity Test (DIVER_DETECTOR_SANITY_V1)

Purpose: Prove that the training pipeline can memorize clean data.
Expected outcome: high-confidence detections on training images,
very high train recall, low loss, confidence >> 0.013.

If this fails: training pipeline is broken. Diagnose before generalization.
"""

import json
import os
import sys
import time
import hashlib
from pathlib import Path

SCRATCHPAD = Path("/private/tmp/claude-501/-Users-maximecauchy--perso-diveanalyzer/41096d47-755f-4843-9b56-3aecdee13d2e/scratchpad")
D3_WORK = SCRATCHPAD / "d3_work"
SANITY = D3_WORK / "DIVER_DETECTOR_SANITY_V1"
RUNS_DIR = SCRATCHPAD / "runs"
RUN_NAME = "DIVER_DETECTOR_SANITY_V1_OVERFIT"

# Controlled overfit recipe:
# - No mosaic (augmentation=off pattern)
# - No mixup, no flipud, low augmentation
# - Many epochs so model has time to memorize
# - Small LR for stability
# - Batch size 4 (tiny dataset)
# - imgsz matching training images (202x360 portrait → use 640 with letterbox)
# - Seed 42 for reproducibility

TRAIN_ARGS = {
    "data": str(SANITY / "dataset.yaml"),
    "epochs": 100,
    "batch": 4,
    "imgsz": 640,
    "device": "mps",
    "project": str(RUNS_DIR),
    "name": RUN_NAME,
    "exist_ok": True,
    "optimizer": "SGD",
    "lr0": 0.005,
    "lrf": 0.1,
    "momentum": 0.9,
    "weight_decay": 0.0,    # no regularization for overfit test
    "warmup_epochs": 3,
    "patience": 40,         # allow model time to fit
    "seed": 42,
    "verbose": True,
    # Minimal augmentation — we want clean memorization
    "mosaic": 0.0,
    "mixup": 0.0,
    "copy_paste": 0.0,
    "flipud": 0.0,
    "fliplr": 0.5,          # OK to flip left-right
    "degrees": 5.0,         # minimal rotation
    "translate": 0.05,
    "scale": 0.2,
    "shear": 0.0,
    "perspective": 0.0,
    "hsv_h": 0.015,
    "hsv_s": 0.4,
    "hsv_v": 0.3,
    "rect": False,
    "close_mosaic": 0,
}

print("=" * 70)
print("Phase F — Overfit Sanity Test")
print(f"Dataset: DIVER_DETECTOR_SANITY_V1 (13 train, 2 val)")
print(f"Device: mps")
print(f"Epochs: {TRAIN_ARGS['epochs']}, Batch: {TRAIN_ARGS['batch']}")
print("=" * 70)

from ultralytics import YOLO

# Verify base weights exist
base_weights = Path("/Users/maximecauchy/.perso/diveanalyzer/yolov8n.pt")
if not base_weights.exists():
    # Try to find yolov8n.pt
    import subprocess
    result = subprocess.run(["find", str(Path.home()), "-name", "yolov8n.pt", "-type", "f"],
                          capture_output=True, text=True, timeout=10)
    candidates = result.stdout.strip().splitlines()
    if candidates:
        base_weights = Path(candidates[0])
        print(f"Found weights at: {base_weights}")
    else:
        base_weights = "yolov8n.pt"  # will download
        print("No local yolov8n.pt found, will use default (downloads if needed)")

print(f"Base weights: {base_weights}")

t0 = time.time()
model = YOLO(str(base_weights))

results = model.train(**TRAIN_ARGS)

elapsed = time.time() - t0
print(f"\nTraining elapsed: {elapsed:.1f}s")

# Get best model path
run_dir = RUNS_DIR / RUN_NAME
best_pt = run_dir / "weights" / "best.pt"
last_pt = run_dir / "weights" / "last.pt"

print(f"best.pt exists: {best_pt.exists()}")
print(f"last.pt exists: {last_pt.exists()}")

if best_pt.exists():
    sha256 = hashlib.sha256(best_pt.read_bytes()).hexdigest()
    print(f"best.pt SHA256: {sha256}")

# Collect training metrics
try:
    import csv
    results_csv = run_dir / "results.csv"
    with open(results_csv) as f:
        rows = list(csv.DictReader(f))

    # Get metrics at best epoch and final epoch
    print(f"\nFinal epoch metrics:")
    final = rows[-1]
    for k, v in final.items():
        print(f"  {k.strip()}: {v.strip()}")

    best_epoch = None
    best_map50 = -1
    for row in rows:
        try:
            m = float(row.get("metrics/mAP50(B)", "0").strip())
            if m > best_map50:
                best_map50 = m
                best_epoch = int(row.get("epoch", "0").strip())
        except:
            pass
    print(f"\nBest epoch: {best_epoch} with mAP50={best_map50:.4f}")

except Exception as e:
    print(f"Could not read results.csv: {e}")

# Run inference on training images to check confidence
print("\n" + "=" * 50)
print("Inference on training images (key sanity check):")
print("Expected: high confidence (>> 0.013) on positive images")
print("=" * 50)

if best_pt.exists():
    infer_model = YOLO(str(best_pt))
    train_imgs = sorted((SANITY / "images" / "train").glob("*.jpg"))

    pos_imgs = [i for i in train_imgs if not i.stem.startswith("neg_")]
    neg_imgs = [i for i in train_imgs if i.stem.startswith("neg_")]

    pos_confidences = []
    neg_confidences = []

    for img_path in pos_imgs:
        preds = infer_model.predict(str(img_path), conf=0.001, verbose=False)
        confs = [float(b.conf.max()) for b in preds[0].boxes if len(b.conf) > 0] if preds[0].boxes else []
        max_conf = max(confs) if confs else 0.0
        pos_confidences.append(max_conf)
        n_det = len(confs)
        print(f"  [POS] {img_path.name}: n_det={n_det}, max_conf={max_conf:.4f}")

    for img_path in neg_imgs:
        preds = infer_model.predict(str(img_path), conf=0.001, verbose=False)
        confs = [float(b.conf.max()) for b in preds[0].boxes if len(b.conf) > 0] if preds[0].boxes else []
        max_conf = max(confs) if confs else 0.0
        neg_confidences.append(max_conf)
        n_det = len(confs)
        print(f"  [NEG] {img_path.name}: n_det={n_det}, max_conf={max_conf:.4f}")

    mean_pos_conf = sum(pos_confidences) / len(pos_confidences) if pos_confidences else 0
    mean_neg_conf = sum(neg_confidences) / len(neg_confidences) if neg_confidences else 0

    print(f"\nPositive images: mean_max_conf={mean_pos_conf:.4f}, min={min(pos_confidences):.4f}, max={max(pos_confidences):.4f}")
    print(f"Negative images: mean_max_conf={mean_neg_conf:.4f}")

    # PASS/FAIL criteria
    # PASS: max conf on positives >> 0.013 (e.g. > 0.25)
    # FAIL: max conf stays near 0.013 (uniform degenerate)
    high_conf_pos = sum(1 for c in pos_confidences if c > 0.25)
    verdict = "TRAINING_PIPELINE_CAN_OVERFIT" if high_conf_pos >= 5 else "TRAINING_PIPELINE_BROKEN"

    print(f"\nPositive images with conf > 0.25: {high_conf_pos}/{len(pos_confidences)}")
    print(f"\n{'='*50}")
    print(f"SANITY VERDICT: {verdict}")
    print(f"{'='*50}")

    # Save result JSON
    result_json = {
        "label": "DIVER_DETECTOR_SANITY_V1_RESULT",
        "date": "2026-09-07",
        "dataset": "DIVER_DETECTOR_SANITY_V1",
        "train_n_positive": len(pos_imgs),
        "train_n_negative": len(neg_imgs),
        "best_epoch": best_epoch,
        "best_map50": best_map50,
        "elapsed_s": elapsed,
        "device": "mps",
        "inference_positive": [{"file": p.name, "max_conf": c} for p, c in zip(pos_imgs, pos_confidences)],
        "inference_negative": [{"file": n.name, "max_conf": c} for n, c in zip(neg_imgs, neg_confidences)],
        "mean_pos_conf": mean_pos_conf,
        "mean_neg_conf": mean_neg_conf,
        "high_conf_positives": high_conf_pos,
        "verdict": verdict,
        "best_weights": str(best_pt),
        "best_weights_sha256": sha256 if best_pt.exists() else None,
    }

    out_path = D3_WORK / "DIVER_DETECTOR_SANITY_V1_RESULT.json"
    out_path.write_text(json.dumps(result_json, indent=2))
    print(f"\nResult saved to: {out_path}")
