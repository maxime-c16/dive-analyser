#!/usr/bin/env python3
"""Phase N — D5 Detector Training.

D5-A: Transfer from frozen D4 weights (DIVER_DETECTOR_D4_A_V8N_best.pt).
      YOLOv8n, amp=False (MPS stability), imgsz=640.
      Max 150 epochs, patience=25.

Runs on Mac M2 (MPS). Syncs results to server after training.

Output: models/D5A_best.pt, D5_TRAIN_RESULT.json
"""
import os, json, datetime, shutil
from ultralytics import YOLO

BASE       = "/tmp/diveanalyzer-exp"
RESULTS    = f"{BASE}/results"
MODEL_PT   = f"{BASE}/data/DIVER_DETECTOR_D4_A_V8N_best.pt"
DATASET    = f"{BASE}/d5_dataset/dataset.yaml"
MODELS_DIR = f"{BASE}/models"
os.makedirs(MODELS_DIR, exist_ok=True)

PROJECT    = f"{BASE}/runs_d5"
RUN_NAME   = "D5A_transfer"


def main():
    print("Phase N — D5 Detector Training (D5-A transfer from D4)")
    print("="*60)
    print(f"  Base weights: {MODEL_PT}")
    print(f"  Dataset:      {DATASET}")
    print(f"  Device:       mps")
    print(f"  amp:          False (MPS stability)")
    print()

    model = YOLO(MODEL_PT)

    results = model.train(
        data       = DATASET,
        epochs     = 150,
        patience   = 25,
        imgsz      = 640,
        batch      = 8,
        device     = "mps",
        amp        = False,
        project    = PROJECT,
        name       = RUN_NAME,
        exist_ok   = True,
        # Standard augmentation — no aggressive mosaic for small dataset
        mosaic     = 0.5,
        mixup      = 0.0,
        degrees    = 5.0,
        flipud     = 0.0,
        fliplr     = 0.5,
        hsv_h      = 0.015,
        hsv_s      = 0.4,
        hsv_v      = 0.2,
        verbose    = True,
    )

    run_dir    = f"{PROJECT}/{RUN_NAME}"
    best_pt    = f"{run_dir}/weights/best.pt"
    last_pt    = f"{run_dir}/weights/last.pt"

    # Copy best to models dir
    dst_best   = f"{MODELS_DIR}/DIVER_DETECTOR_D5_A_V8N_best.pt"
    shutil.copy2(best_pt, dst_best)
    print(f"\nBest weights: {dst_best}")

    # Extract metrics from results
    metrics = results.results_dict if hasattr(results, "results_dict") else {}
    box_map50 = metrics.get("metrics/mAP50(B)", None)
    box_map5095 = metrics.get("metrics/mAP50-95(B)", None)

    print(f"\nD5-A final metrics:")
    print(f"  mAP50:    {box_map50}")
    print(f"  mAP50-95: {box_map5095}")

    # Save training result
    result_json = {
        "label":     "D5_TRAIN_RESULT_A",
        "date":      datetime.date.today().isoformat(),
        "base_weights": "DIVER_DETECTOR_D4_A_V8N_best.pt",
        "run":       RUN_NAME,
        "epochs_ran": int(results.epoch) if hasattr(results, "epoch") else "?",
        "mAP50":     box_map50,
        "mAP50_95":  box_map5095,
        "best_pt":   dst_best,
        "device":    "mps",
        "amp":       False,
    }
    out = f"{RESULTS}/D5_TRAIN_RESULT_A.json"
    with open(out, "w") as f:
        json.dump(result_json, f, indent=2)
    print(f"\nResult saved: {out}")
    return result_json


if __name__ == "__main__":
    main()
