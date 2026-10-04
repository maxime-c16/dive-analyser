#!/usr/bin/env python3
"""Phase P — Paris D5 External Test.

Breaks Paris seal for D5-A detector evaluation.
Runs D5-A (and D4 for comparison) on Paris anchor frames.
Paris firewall: evaluating ONLY, no training signal flows back.

Paris media: IMG_1937.mov, dive 2819, SHA d122262b...
Anchor frames (native 1080p):
  takeoff:       frame 187  (~3.12s)
  apex:          frame 214  (~3.57s)
  water_contact: frame 253  (~4.22s)

GT boxes (from Paris D4 eval):
  takeoff:       [1220.7, 116.1, 1382.2, 444.0]   IoU=0.387 D4 match
  apex:          [1036.8, 312.3, 1266.6, 689.4]   D4 rank=10
  water_contact: [1169.8, 556.4, 1366.1, 736.3]   D4 rank=5 (center_dist match)
"""
import os, json, glob, datetime, hashlib
import cv2
import numpy as np
from ultralytics import YOLO

BASE     = "/tmp/diveanalyzer-exp"
DATA     = f"{BASE}/data"
RESULTS  = f"{BASE}/results"
MODEL_D4 = f"{DATA}/DIVER_DETECTOR_D4_A_V8N_best.pt"
MODEL_D5 = f"{BASE}/models/DIVER_DETECTOR_D5_A_V8N_best.pt"

# Paris video
PARIS_VIDEO_PATH = f"{DATA}/IMG_1937.mov"
PARIS_SHA_CANONICAL = "d122262be8e7a8721ab2f6a71721bb3544403da78324138d026360ef9820eaae"

FLOOR_CONF = 0.001
FLOOR_CAP  = 200
IOU_MATCH  = 0.30
DIST_MATCH = 0.05

# Paris anchor frames and GT boxes — from Phase H PARIS_RERANKER_EVAL_V1
# Video: 1080x1920 portrait. Frame indices from pts_s decoding (same as Phase H).
# GT boxes in portrait pixel coords (W=1080, H=1920), from canonical PARIS annotations.
PARIS_ANCHORS = {
    "takeoff":       {"frame_idx": 176, "gt_box": [522.9270633397313, 542.7207293666027, 819.9616122840691, 892.4280230326295]},
    "apex":          {"frame_idx": 201, "gt_box": [495.2015355086372, 353.478886756238,  665.7581573896354, 657.2360844529751]},
    "water_contact": {"frame_idx": 238, "gt_box": [302.1880998080614, 687.1785028790787, 525.8781190019193, 1076.6026871401152]},
}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def box_iou(b1, b2):
    x1 = max(b1[0], b2[0]); y1 = max(b1[1], b2[1])
    x2 = min(b1[2], b2[2]); y2 = min(b1[3], b2[3])
    inter = max(0, x2-x1) * max(0, y2-y1)
    a1 = (b1[2]-b1[0])*(b1[3]-b1[1])
    a2 = (b2[2]-b2[0])*(b2[3]-b2[1])
    return inter / (a1 + a2 - inter + 1e-9)


def center_dist_norm(b1, b2, W, H):
    c1x = (b1[0]+b1[2])/2/W; c1y = (b1[1]+b1[3])/2/H
    c2x = (b2[0]+b2[2])/2/W; c2y = (b2[1]+b2[3])/2/H
    return ((c1x-c2x)**2 + (c1y-c2y)**2) ** 0.5


def match_gt(pred_box, gt_box, W, H):
    iou = box_iou(pred_box, gt_box)
    dist = center_dist_norm(pred_box, gt_box, W, H)
    matched = iou >= IOU_MATCH or dist <= DIST_MATCH
    return matched, float(iou), float(dist)


def eval_on_paris(model, model_label, frames):
    results = {}
    for phase, anchor in PARIS_ANCHORS.items():
        gt_box    = anchor["gt_box"]
        frame_bgr = frames[phase]
        H, W = frame_bgr.shape[:2]

        preds = model(frame_bgr, conf=FLOOR_CONF, iou=0.45, imgsz=640, verbose=False)
        boxes_raw = preds[0].boxes
        if boxes_raw is None or len(boxes_raw) == 0:
            results[phase] = {"rank": None, "n_candidates": 0, "matched": False}
            continue

        confs = boxes_raw.conf.cpu().numpy()
        boxes = boxes_raw.xyxy.cpu().numpy()
        order = np.argsort(-confs)
        confs = confs[order][:FLOOR_CAP]
        boxes = boxes[order][:FLOOR_CAP]

        target_rank = None
        best_iou    = 0.0
        best_dist   = 999.0
        for i, (box, conf) in enumerate(zip(boxes, confs)):
            matched, iou, dist = match_gt(box.tolist(), gt_box, W, H)
            if matched and target_rank is None:
                target_rank = i + 1
            if iou > best_iou:
                best_iou = iou
            if dist < best_dist:
                best_dist = dist

        results[phase] = {
            "rank":        target_rank,
            "matched":     target_rank is not None,
            "best_iou":    round(best_iou, 4),
            "best_dist":   round(best_dist, 4),
            "n_candidates": len(confs),
        }
        status = f"rank={target_rank}" if target_rank else "NOT_FOUND"
        print(f"    {phase:15s}: {status}  IoU={best_iou:.3f}  n={len(confs)}")

    return results


def main():
    print("Phase P — Paris D5 External Test")
    print("="*60)
    print("PARIS FIREWALL: Breaking seal for EVALUATION ONLY.")
    print("No training signal from Paris will flow back.\n")

    if not os.path.exists(PARIS_VIDEO_PATH):
        print(f"ERROR: Paris video not found: {PARIS_VIDEO_PATH}")
        return None

    # Verify SHA
    actual_sha = sha256_file(PARIS_VIDEO_PATH)
    sha_ok = actual_sha == PARIS_SHA_CANONICAL
    print(f"Paris SHA: {actual_sha[:16]}... {'✓' if sha_ok else '✗ MISMATCH'}")

    # Load Paris anchor frames
    print("\nLoading Paris anchor frames (1080p)...")
    frames = {}
    cap = cv2.VideoCapture(PARIS_VIDEO_PATH)
    for phase, anchor in PARIS_ANCHORS.items():
        fi = anchor["frame_idx"]
        cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
        ret, frame = cap.read()
        if not ret:
            print(f"  FAIL to read frame {fi} ({phase})")
            return None
        frames[phase] = frame
        H, W = frame.shape[:2]
        print(f"  {phase}: frame {fi}, {W}x{H}")
    cap.release()

    # Evaluate D4
    print("\nD4 baseline:")
    model_d4 = YOLO(MODEL_D4)
    d4_results = eval_on_paris(model_d4, "D4", frames)

    # Evaluate D5-A
    print("\nD5-A:")
    model_d5 = YOLO(MODEL_D5)
    d5_results = eval_on_paris(model_d5, "D5_A", frames)

    # Trajectory gate
    def traj_gate(results, label):
        covered = sum(1 for v in results.values() if v.get("matched"))
        gate = "TRAJECTORY_INPUT_PASS" if covered >= 3 else "TRAJECTORY_INPUT_FAIL"
        print(f"\n{label} trajectory gate: {gate} ({covered}/3 covered)")
        return gate, covered

    print("\n" + "="*60)
    d4_gate, d4_cov = traj_gate(d4_results, "D4")
    d5_gate, d5_cov = traj_gate(d5_results, "D5-A")

    # Compare per-phase rank improvement
    print("\nRank comparison:")
    for phase in ["takeoff", "apex", "water_contact"]:
        d4r = d4_results[phase].get("rank", "—")
        d5r = d5_results[phase].get("rank", "—")
        delta = ""
        if isinstance(d4r, int) and isinstance(d5r, int):
            delta = f" ({'+' if d5r > d4r else ''}{d5r - d4r:+d})" if d5r != d4r else " (same)"
        elif isinstance(d4r, int) and d5r is None:
            delta = " (REGRESSION — D5 lost this phase)"
        elif d4r is None and isinstance(d5r, int):
            delta = " (RECOVERED)"
        print(f"  {phase:15s}: D4={d4r}  D5={d5r}{delta}")

    out = {
        "label":              "PARIS_D5_EVAL",
        "date":               datetime.date.today().isoformat(),
        "paris_media_sha":    actual_sha,
        "sha_verified":       sha_ok,
        "paris_firewall":     "Paris evaluated post-freeze. No training signal flows back.",
        "D4_results":         d4_results,
        "D5_A_results":       d5_results,
        "D4_trajectory_gate": d4_gate,
        "D5_trajectory_gate": d5_gate,
        "D5_covered":         d5_cov,
    }
    path = f"{RESULTS}/PARIS_D5_EVAL.json"
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nSaved: {path}")
    return out


if __name__ == "__main__":
    main()
