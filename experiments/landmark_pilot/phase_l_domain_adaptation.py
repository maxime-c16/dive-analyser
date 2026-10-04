#!/usr/bin/env python3
"""Phase L: Domain-adaptation feasibility study.
Fine-tune YOLOv8n (one class: diver) on 38 DEVELOPMENT localization frames.
Dive-level train/val split to avoid leakage. Max 2 model configs.
Frozen detector weights (F1/F2) are NOT modified — this is a new candidate only.
Do not tune F1/F2. Do not alter frozen predictions."""
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PERCP = ROOT  # perception repo root
LABELS_DIR = ROOT / "docs/science/localization_annotations_v1/DEVELOPMENT_DESIGN"
IMAGES_DIR = ROOT / "media/perception_decomposition_v1/localization/DEVELOPMENT_DESIGN"
SCIENCE_DIR = ROOT / "docs/science"
SCRATCHPAD = Path("/private/tmp/claude-501/-Users-maximecauchy--perso-diveanalyzer"
                  "/f70bb3f5-c40f-41fd-ae6c-5b4acb452b35/scratchpad")
DATASET_DIR = SCRATCHPAD / "phase_l_yolo_dataset"

# Dive-level split: no same-dive leakage
# Val: 133 (success), 311 (partial-vis), 2387 (collapse) — 3 diverse dives
VAL_DIVES = {133, 311, 2387}
# Train: all remaining DEVELOPMENT_DESIGN dives
ALL_DIVES = {133, 311, 524, 676, 1040, 2169, 2341, 2353, 2387, 2541, 2555, 2625, 2661, 2680}
TRAIN_DIVES = ALL_DIVES - VAL_DIVES  # 11 dives

VALID_VIS = {"visible", "partial"}


def get_image_size(img_path: Path) -> tuple[int, int]:
    """Return (width, height) using file command."""
    result = subprocess.run(["file", str(img_path)], capture_output=True, text=True)
    import re
    m = re.search(r"(\d+) x (\d+)", result.stdout)
    if m:
        return int(m.group(1)), int(m.group(2))
    raise ValueError(f"Could not parse size from: {result.stdout}")


def load_annotations() -> list[dict]:
    """Load all valid DEVELOPMENT_DESIGN annotations."""
    records = []
    for json_path in sorted(LABELS_DIR.glob("*.json")):
        stem = json_path.stem  # e.g. "133_takeoff"
        data = json.loads(json_path.read_text())
        dive_id = data.get("dive_id")
        phase = data.get("phase")
        bbox = data.get("bbox")
        vis = data.get("visibility")
        if bbox is None or vis not in VALID_VIS:
            continue
        img_path = IMAGES_DIR / f"{stem}.png"
        if not img_path.exists():
            print(f"  WARNING: image not found: {img_path.name}")
            continue
        records.append({
            "stem": stem,
            "dive_id": dive_id,
            "phase": phase,
            "bbox_xyxy": bbox,
            "visibility": vis,
            "img_path": img_path,
        })
    return records


def create_yolo_label(bbox_xyxy: list, img_w: int, img_h: int) -> str:
    """Convert [x1, y1, x2, y2] to YOLO format: 0 cx cy w h (normalized)."""
    x1, y1, x2, y2 = bbox_xyxy
    # Clamp to image bounds
    x1, x2 = max(0, min(x1, img_w)), max(0, min(x2, img_w))
    y1, y2 = max(0, min(y1, img_h)), max(0, min(y2, img_h))
    cx = (x1 + x2) / 2 / img_w
    cy = (y1 + y2) / 2 / img_h
    w = (x2 - x1) / img_w
    h = (y2 - y1) / img_h
    return f"0 {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}"


def build_dataset(records: list[dict]) -> dict:
    """Build YOLO dataset on disk. Returns split stats."""
    # Clean and create
    if DATASET_DIR.exists():
        shutil.rmtree(DATASET_DIR)
    for split in ("train", "val"):
        (DATASET_DIR / "images" / split).mkdir(parents=True)
        (DATASET_DIR / "labels" / split).mkdir(parents=True)

    stats = {"train": 0, "val": 0}
    for rec in records:
        did = rec["dive_id"]
        split = "val" if did in VAL_DIVES else "train"
        stem = rec["stem"]
        src_img = rec["img_path"]
        dst_img = DATASET_DIR / "images" / split / f"{stem}.png"
        dst_lbl = DATASET_DIR / "labels" / split / f"{stem}.txt"

        shutil.copy2(src_img, dst_img)
        img_w, img_h = get_image_size(src_img)
        label_line = create_yolo_label(rec["bbox_xyxy"], img_w, img_h)
        dst_lbl.write_text(label_line + "\n")
        stats[split] += 1

    # Write dataset.yaml
    yaml_content = (
        f"path: {DATASET_DIR}\n"
        f"train: images/train\n"
        f"val: images/val\n"
        f"nc: 1\n"
        f"names: ['diver']\n"
    )
    (DATASET_DIR / "dataset.yaml").write_text(yaml_content)
    print(f"  Dataset: train={stats['train']} val={stats['val']} images", flush=True)
    return stats


def train_config(name: str, freeze: int, epochs: int = 100) -> dict:
    """Train one YOLO config. Returns result dict."""
    from ultralytics import YOLO
    weights = PERCP / "media/perception_decomposition_v1/yolov8n.pt"
    run_dir = SCRATCHPAD / f"phase_l_{name}"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)

    print(f"\n  Training {name}: freeze={freeze} epochs={epochs}", flush=True)
    began = time.monotonic()

    model = YOLO(str(weights))
    results = model.train(
        data=str(DATASET_DIR / "dataset.yaml"),
        epochs=epochs,
        imgsz=640,
        batch=4,
        workers=0,
        freeze=freeze,
        device="mps",
        project=str(run_dir),
        name="train",
        verbose=False,
        save=True,
        plots=False,
        exist_ok=True,
        patience=20,      # early stopping
        lr0=0.01 if freeze > 0 else 0.001,
        lrf=0.01,
        # Conservative augmentation for micro-dataset
        hsv_h=0.015, hsv_s=0.4, hsv_v=0.3,
        degrees=0, translate=0.05, scale=0.3, shear=0.0,
        flipud=0.0, fliplr=0.5, mosaic=0.0, mixup=0.0,
        copy_paste=0.0,
    )
    elapsed = round(time.monotonic() - began, 2)

    # Extract metrics from results
    best_weights = run_dir / "train/weights/best.pt"

    # Evaluate best weights on val
    val_model = YOLO(str(best_weights))
    val_results = val_model.val(
        data=str(DATASET_DIR / "dataset.yaml"),
        split="val",
        verbose=False,
        device="mps",
    )

    # Get metrics
    try:
        mp = float(val_results.box.mp)       # mean precision
        mr = float(val_results.box.mr)       # mean recall
        map50 = float(val_results.box.map50)  # mAP@0.5
        map5095 = float(val_results.box.map)  # mAP@0.5:0.95
    except Exception:
        mp = mr = map50 = map5095 = None

    result = {
        "name": name,
        "freeze_layers": freeze,
        "epochs_requested": epochs,
        "seconds": elapsed,
        "best_weights": str(best_weights),
        "val_metrics": {
            "mean_precision": mp,
            "mean_recall": mr,
            "mAP50": map50,
            "mAP50_95": map5095,
        }
    }
    print(f"  {name}: mAP50={map50:.3f} recall={mr:.3f} ({elapsed:.0f}s)", flush=True)
    return result


def main():
    print("=== Phase L: Domain-adaptation feasibility ===", flush=True)
    print(f"Train dives ({len(TRAIN_DIVES)}): {sorted(TRAIN_DIVES)}", flush=True)
    print(f"Val dives ({len(VAL_DIVES)}): {sorted(VAL_DIVES)}", flush=True)

    records = load_annotations()
    print(f"Loaded {len(records)} valid annotations", flush=True)

    train_records = [r for r in records if r["dive_id"] in TRAIN_DIVES]
    val_records = [r for r in records if r["dive_id"] in VAL_DIVES]
    print(f"  Train samples: {len(train_records)}, Val samples: {len(val_records)}", flush=True)

    dataset_stats = build_dataset(records)

    # L1: Fine-tune with frozen backbone (freeze first 10 layers)
    l1_result = train_config("L1_frozen_backbone", freeze=10, epochs=100)

    # L2: Fine-tune all layers
    l2_result = train_config("L2_all_layers", freeze=0, epochs=100)

    # Frozen F1 baseline recall for comparison (from existing DEVELOPMENT evaluation)
    # F1 IoU50 recall on DEVELOPMENT: 3/36 = 0.083 (from PERCEPTION_DETECTOR_ONLY_DEVELOPMENT_V1.json)
    frozen_f1_iou50_recall = 3 / 36

    feasibility = (
        "VIABLE" if (
            l1_result["val_metrics"].get("mAP50") is not None and
            l2_result["val_metrics"].get("mAP50") is not None and
            max(l1_result["val_metrics"]["mAP50"], l2_result["val_metrics"]["mAP50"])
            > frozen_f1_iou50_recall * 2
        ) else "NOT_VIABLE"
    )

    output = {
        "phase": "L",
        "description": "Domain-adaptation feasibility: YOLOv8n fine-tune on DEVELOPMENT localization boxes",
        "dataset": {
            "train_dives": sorted(TRAIN_DIVES),
            "val_dives": sorted(VAL_DIVES),
            "train_samples": dataset_stats["train"],
            "val_samples": dataset_stats["val"],
            "split_strategy": "dive-level to avoid same-dive leakage",
        },
        "frozen_f1_iou50_recall_development": frozen_f1_iou50_recall,
        "configs": {
            "L1_frozen_backbone": l1_result,
            "L2_all_layers": l2_result,
        },
        "feasibility_verdict": feasibility,
        "feasibility_criterion": "max(mAP50) > 2x frozen F1 IoU50 recall",
    }

    out_path = SCIENCE_DIR / "PHASE_L_DOMAIN_ADAPTATION_V1.json"
    out_path.write_text(json.dumps(output, indent=2) + "\n")
    print(f"\nSaved: {out_path}", flush=True)
    print(f"Feasibility verdict: {feasibility}", flush=True)


if __name__ == "__main__":
    main()
