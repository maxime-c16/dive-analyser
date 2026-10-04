#!/usr/bin/env python3
"""Prepare D5 annotation server manifest and script.

Runs D4 detector on each of the 44 D5 frames to generate detection hints.
Creates the manifest JSON and server script.
"""
import os, json, datetime, glob
import numpy as np
import cv2
from ultralytics import YOLO

BASE          = "/tmp/diveanalyzer-exp"
RESULTS       = f"{BASE}/results"
D5_FRAMES_DIR = f"{BASE}/d5_frames"
MODEL_PT      = f"{BASE}/data/DIVER_DETECTOR_D4_A_V8N_best.pt"

BATCH_MANIFEST_PATH = f"{RESULTS}/D5_ANNOTATION_BATCH_MANIFEST.json"

# Server-side paths (on Debian server)
SERVER_BATCH_DIR   = "/home/mcauchy/dive-analyser/docs/science/localization_annotations_v1/D5_ANNOTATION_BATCH"
SERVER_FRAMES_DIR  = f"{SERVER_BATCH_DIR}/frames"
SERVER_MANIFEST    = f"{SERVER_BATCH_DIR}/manifest.json"

def main():
    print("Loading D5 annotation batch manifest …")
    batch = json.load(open(BATCH_MANIFEST_PATH))
    frames_in_batch = batch["frames"]
    print(f"  {len(frames_in_batch)} frames to process")

    print("Loading D4 model for detection hints …")
    model = YOLO(MODEL_PT)

    server_manifest = {
        "batch": "D5_ANNOTATION_BATCH",
        "date":  datetime.date.today().isoformat(),
        "n_frames": len(frames_in_batch),
        "frames": [],
    }

    for i, fb in enumerate(frames_in_batch):
        frame_id = fb["frame_id"]
        img_path = f"{D5_FRAMES_DIR}/{frame_id}.jpg"

        if not os.path.exists(img_path):
            print(f"  SKIP {frame_id} — image not found")
            continue

        frame_bgr = cv2.imread(img_path)
        H, W = frame_bgr.shape[:2]

        # Run D4 at conf=0.05 for hints
        results = model(frame_bgr, conf=0.05, iou=0.45, imgsz=640, verbose=False)
        preds = results[0].boxes
        hints = []
        if preds is not None and len(preds) > 0:
            boxes = preds.xyxy.cpu().numpy()
            confs = preds.conf.cpu().numpy()
            for j in range(min(5, len(confs))):  # top-5 at most
                hints.append({
                    "xyxy_px": boxes[j].tolist(),
                    "conf": float(confs[j]),
                })

        entry = {
            "frame_id":          frame_id,
            "frame_file":        f"{frame_id}.jpg",
            "dive_id":           fb["dive_id"],
            "phase":             fb["phase"],
            "frame_index":       fb["frame_index"],
            "gt_frame_index":    fb["gt_frame_index"],
            "offset_from_gt":    fb["offset_from_gt"],
            "source_failure_rank": fb["source_failure_rank"],
            "reason":            fb["reason"],
            "width":             W,
            "height":            H,
            "pts_approx_s":      None,
            "purpose":           f"D5_MINING_{fb['phase'].upper()}_RANK{fb['source_failure_rank']}",
            "has_diver_hint":    None,    # unknown until annotated
            "d4_hints_at_conf005": hints,
            "annotation":        None,
        }
        server_manifest["frames"].append(entry)
        print(f"  [{i+1:2d}/{len(frames_in_batch)}] {frame_id:45s} D4_hints={len(hints)}")

    # Save Mac-local server manifest
    server_manifest_local = f"{RESULTS}/D5_SERVER_MANIFEST.json"
    with open(server_manifest_local, "w") as f:
        json.dump(server_manifest, f, indent=2)
    print(f"\nServer manifest saved locally: {server_manifest_local}")
    return server_manifest

if __name__ == "__main__":
    main()
