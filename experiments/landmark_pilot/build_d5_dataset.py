#!/usr/bin/env python3
"""Phase M — Build D5 YOLO detector dataset.

Combines:
  - D4 training annotations (existing DEVELOPMENT_DESIGN/*.json, all visible+bbox)
  - D5 new annotations (D5_ANNOTATION_COMPLETE_MANIFEST.json, visible+bbox only)
  - Excludes: Paris (dive 2819 / IMG_1937.mov) — firewall enforced

Outputs YOLO v8 format:
  d5_dataset/
    images/train/*.jpg
    images/val/*.jpg
    labels/train/*.txt   (one line: 0 cx cy w h, normalized)
    labels/val/*.txt
    dataset.yaml

Grouped split strategy:
  - Inherit D4 split (DEV_TRAIN / DEV_VAL dives)
  - New D5 frames assigned to same split as their dive (or train if ambiguous)
  - DEV_VAL holds out same dives as R1 reranker: 2341, 2353

Paris firewall: verified — no Paris frames in any split.
"""
import os, json, shutil, glob, hashlib, datetime
import cv2
import numpy as np

BASE       = "/tmp/diveanalyzer-exp"
DATA       = f"{BASE}/data"
RESULTS    = f"{BASE}/results"
ANNOT_DIR  = f"{DATA}/DEVELOPMENT_DESIGN"
VIDEO_DIR  = f"{DATA}/proxy_videos"
D5_FRAMES  = f"{BASE}/d5_frames"
OUT_DIR    = f"{BASE}/d5_dataset"
MODEL_PT   = f"{DATA}/DIVER_DETECTOR_D4_A_V8N_best.pt"

D5_MANIFEST = f"{RESULTS}/D5_ANNOTATION_COMPLETE_MANIFEST.json"

# Grouped split — same as R1 reranker
DEV_VAL_DIVES   = {2341, 2353}
PARIS_DIVES     = {2819}

# ── helpers ────────────────────────────────────────────────────────────────

def bbox_to_yolo(bbox_xyxy, W, H):
    """Convert [x1,y1,x2,y2] pixel bbox to YOLO [cx, cy, w, h] normalized."""
    x1, y1, x2, y2 = bbox_xyxy
    cx = (x1 + x2) / 2 / W
    cy = (y1 + y2) / 2 / H
    w  = (x2 - x1) / W
    h  = (y2 - y1) / H
    return cx, cy, w, h


def sha256_short(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def get_frame_from_video(video_path, frame_idx, out_path):
    cap = cv2.VideoCapture(video_path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        return False
    cv2.imwrite(out_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return True


# ── collect D4 training samples ────────────────────────────────────────────

def collect_d4_samples():
    """Load all visible+bbox DEVELOPMENT_DESIGN annotations as (img_path, bbox_xyxy, dive_id, frame_id)."""
    samples = []
    for ann_path in sorted(glob.glob(f"{ANNOT_DIR}/*.json")):
        ann = json.load(open(ann_path))
        frame_id = os.path.splitext(os.path.basename(ann_path))[0]
        if ann.get("visibility") != "visible":
            continue
        if ann.get("bbox") is None:
            continue
        dive_id = ann.get("dive_id")
        if dive_id in PARIS_DIVES:
            print(f"  FIREWALL: skipping Paris frame {frame_id}")
            continue

        media_key  = ann["media_key"]
        frame_idx  = ann["frame_index"]
        bbox_xyxy  = ann["bbox"]          # already in pixel coords
        W          = ann.get("width", 640)
        H          = ann.get("height", 360)

        video_path = f"{VIDEO_DIR}/{media_key}.mp4"
        if not os.path.exists(video_path):
            print(f"  SKIP {frame_id} — video missing")
            continue

        samples.append({
            "frame_id":  frame_id,
            "dive_id":   dive_id,
            "source":    "D4",
            "video_path": video_path,
            "frame_idx": frame_idx,
            "bbox_xyxy": bbox_xyxy,
            "W": W, "H": H,
        })
    return samples


def collect_d5_samples():
    """Load visible+bbox D5 annotations."""
    manifest = json.load(open(D5_MANIFEST))
    samples  = []
    for fr in manifest["frames"]:
        ann = fr.get("annotation") or {}
        if ann.get("state") != "HUMAN_REVIEWED":
            continue
        if ann.get("visibility") != "visible":
            continue
        if ann.get("bbox") is None:
            continue
        dive_id = fr["dive_id"]
        if dive_id in PARIS_DIVES:
            print(f"  FIREWALL: skipping Paris frame {fr['frame_id']}")
            continue

        frame_id  = fr["frame_id"]
        img_path  = f"{D5_FRAMES}/{frame_id}.jpg"
        if not os.path.exists(img_path):
            print(f"  SKIP {frame_id} — image missing")
            continue
        img = cv2.imread(img_path)
        H, W = img.shape[:2]

        samples.append({
            "frame_id":  frame_id,
            "dive_id":   dive_id,
            "source":    "D5",
            "img_path":  img_path,
            "bbox_xyxy": ann["bbox"],
            "W": W, "H": H,
        })
    return samples


# ── build dataset ─────────────────────────────────────────────────────────

def main():
    print("Phase M — D5 YOLO Dataset Construction")
    print("="*60)

    # Paris firewall
    print("Paris firewall: IMG_1937.mov / dive 2819 excluded from all splits.\n")

    d4_samples = collect_d4_samples()
    d5_samples = collect_d5_samples()
    all_samples = d4_samples + d5_samples

    print(f"D4 samples: {len(d4_samples)}")
    print(f"D5 samples: {len(d5_samples)}")
    print(f"Total:      {len(all_samples)}")

    # Grouped split
    train_samples = [s for s in all_samples if s["dive_id"] not in DEV_VAL_DIVES]
    val_samples   = [s for s in all_samples if s["dive_id"] in DEV_VAL_DIVES]

    # Confirm no Paris
    for s in train_samples + val_samples:
        assert s["dive_id"] not in PARIS_DIVES, f"Paris leak: {s['frame_id']}"

    print(f"\nSplit:")
    print(f"  Train: {len(train_samples)} frames (dives: {sorted({s['dive_id'] for s in train_samples})})")
    print(f"  Val:   {len(val_samples)}   frames (dives: {sorted({s['dive_id'] for s in val_samples})})")

    # Create directories
    for split in ("train", "val"):
        os.makedirs(f"{OUT_DIR}/images/{split}", exist_ok=True)
        os.makedirs(f"{OUT_DIR}/labels/{split}", exist_ok=True)

    # Export each sample
    stats = {"train": 0, "val": 0, "errors": 0}
    manifest_rows = []

    for split, samples in [("train", train_samples), ("val", val_samples)]:
        print(f"\nExporting {split} ({len(samples)} samples)...")
        for s in samples:
            fid = s["frame_id"]
            img_out = f"{OUT_DIR}/images/{split}/{fid}.jpg"
            lbl_out = f"{OUT_DIR}/labels/{split}/{fid}.txt"

            # Copy or extract image
            if s.get("img_path") and os.path.exists(s["img_path"]):
                shutil.copy2(s["img_path"], img_out)
                ok = True
            else:
                ok = get_frame_from_video(s["video_path"], s["frame_idx"], img_out)

            if not ok:
                print(f"  ✗ FAIL extract {fid}")
                stats["errors"] += 1
                continue

            # Read actual dims from saved image (may differ from annotation)
            img = cv2.imread(img_out)
            H, W = img.shape[:2]

            # Write YOLO label
            bbox = s["bbox_xyxy"]
            cx, cy, bw, bh = bbox_to_yolo(bbox, W, H)
            # Clamp to [0, 1]
            cx = max(0.0, min(1.0, cx))
            cy = max(0.0, min(1.0, cy))
            bw = max(0.001, min(1.0, bw))
            bh = max(0.001, min(1.0, bh))
            with open(lbl_out, "w") as lf:
                lf.write(f"0 {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}\n")

            stats[split] += 1
            manifest_rows.append({
                "frame_id": fid,
                "dive_id":  s["dive_id"],
                "source":   s["source"],
                "split":    split,
                "W": W, "H": H,
                "bbox_yolo": [round(cx,6), round(cy,6), round(bw,6), round(bh,6)],
            })

    print(f"\nExport complete: train={stats['train']} val={stats['val']} errors={stats['errors']}")

    # Write dataset.yaml
    yaml_path = f"{OUT_DIR}/dataset.yaml"
    with open(yaml_path, "w") as f:
        f.write(f"path: {OUT_DIR}\n")
        f.write(f"train: images/train\n")
        f.write(f"val:   images/val\n")
        f.write(f"nc: 1\n")
        f.write(f"names: ['diver']\n")
    print(f"\ndataset.yaml: {yaml_path}")

    # Save manifest
    dataset_manifest = {
        "label":   "DIVER_LOCALIZATION_DATASET_D5",
        "date":    datetime.date.today().isoformat(),
        "n_train": stats["train"],
        "n_val":   stats["val"],
        "n_errors": stats["errors"],
        "sources": {"D4": len(d4_samples), "D5": len(d5_samples)},
        "grouped_split": {
            "DEV_TRAIN_dives": sorted({s["dive_id"] for s in train_samples}),
            "DEV_VAL_dives":   sorted(DEV_VAL_DIVES),
        },
        "paris_firewall": "VERIFIED — Paris dive 2819 / IMG_1937.mov excluded from all splits",
        "dataset_yaml":  yaml_path,
        "samples": manifest_rows,
    }
    mpath = f"{RESULTS}/D5_DATASET_MANIFEST.json"
    with open(mpath, "w") as f:
        json.dump(dataset_manifest, f, indent=2)
    print(f"Dataset manifest: {mpath}")
    return dataset_manifest


if __name__ == "__main__":
    main()
