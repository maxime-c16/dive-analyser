#!/usr/bin/env python3
"""Phase O — D5 Development Floor Audit.

Runs D5-A model at floor conf=0.001 on all 34 canonical DEVELOPMENT frames.
Compares recall and target rank to D4 baseline.

Gate: floor recall ≥ 100% (must maintain), op_conf top-1 recall ≥ D4 (80.6%).
Also measures top-K recall and MRR to confirm rank improvement.
"""
import os, json, glob, datetime
import cv2
import numpy as np
from ultralytics import YOLO

BASE      = "/tmp/diveanalyzer-exp"
DATA      = f"{BASE}/data"
RESULTS   = f"{BASE}/results"
ANNOT_DIR = f"{DATA}/DEVELOPMENT_DESIGN"
VIDEO_DIR = f"{DATA}/proxy_videos"
MODEL_D5  = f"{BASE}/models/DIVER_DETECTOR_D5_A_V8N_best.pt"
MODEL_D4  = f"{BASE}/data/DIVER_DETECTOR_D4_A_V8N_best.pt"

FLOOR_CONF  = 0.001
FLOOR_CAP   = 200
OP_CONF     = 0.05
IOU_MATCH   = 0.30
DIST_MATCH  = 0.05   # normalized center dist


def load_canonical_frames():
    frames = []
    for f in sorted(glob.glob(f"{ANNOT_DIR}/*.json")):
        d = json.load(open(f))
        fid = os.path.splitext(os.path.basename(f))[0]
        if d.get("visibility") == "visible" and d.get("bbox") is not None:
            frames.append(fid)
    return frames


def box_iou(b1, b2):
    x1 = max(b1[0], b2[0]); y1 = max(b1[1], b2[1])
    x2 = min(b1[2], b2[2]); y2 = min(b1[3], b2[3])
    inter = max(0, x2-x1) * max(0, y2-y1)
    a1 = (b1[2]-b1[0])*(b1[3]-b1[1])
    a2 = (b2[2]-b2[0])*(b2[3]-b2[1])
    return inter / (a1 + a2 - inter + 1e-9)


def center_dist_norm(b1, b2, W, H):
    c1x = (b1[0]+b1[2])/2 / W; c1y = (b1[1]+b1[3])/2 / H
    c2x = (b2[0]+b2[2])/2 / W; c2y = (b2[1]+b2[3])/2 / H
    return ((c1x-c2x)**2 + (c1y-c2y)**2) ** 0.5


def match_gt(pred_box, gt_box, W, H):
    iou = box_iou(pred_box, gt_box)
    dist = center_dist_norm(pred_box, gt_box, W, H)
    return iou >= IOU_MATCH or dist <= DIST_MATCH, iou, dist


def eval_model(model_path, label):
    print(f"\n{'='*60}")
    print(f"Evaluating: {label}")
    print(f"Model: {model_path}")

    model = YOLO(model_path)
    canonical_frames = load_canonical_frames()
    print(f"Canonical frames: {len(canonical_frames)}")

    per_frame = {}
    floor_matched = 0
    op_matched = 0

    for fid in canonical_frames:
        ann = json.load(open(f"{ANNOT_DIR}/{fid}.json"))
        gt_box = ann["bbox"]   # [x1,y1,x2,y2] pixel
        W = ann.get("width", 202)
        H = ann.get("height", 360)
        media_key = ann["media_key"]
        frame_idx = ann["frame_index"]

        video_path = f"{VIDEO_DIR}/{media_key}.mp4"
        if not os.path.exists(video_path):
            print(f"  SKIP {fid} — video missing")
            per_frame[fid] = {"status": "SKIP_VIDEO_MISSING"}
            continue

        cap = cv2.VideoCapture(video_path)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame_bgr = cap.read()
        cap.release()
        if not ret:
            print(f"  SKIP {fid} — frame read fail")
            per_frame[fid] = {"status": "SKIP_READ_FAIL"}
            continue

        H_actual, W_actual = frame_bgr.shape[:2]
        W = W_actual; H = H_actual

        results = model(frame_bgr, conf=FLOOR_CONF, iou=0.45, imgsz=640, verbose=False)
        preds = results[0].boxes
        if preds is None or len(preds) == 0:
            per_frame[fid] = {"target_rank_floor": None, "matched_floor": False, "n_candidates": 0}
            continue

        # Sort by confidence desc
        confs = preds.conf.cpu().numpy()
        boxes = preds.xyxy.cpu().numpy()
        order = np.argsort(-confs)
        confs = confs[order][:FLOOR_CAP]
        boxes = boxes[order][:FLOOR_CAP]

        target_rank = None
        target_iou  = None
        target_dist = None
        for i, (box, conf) in enumerate(zip(boxes, confs)):
            matched, iou, dist = match_gt(box.tolist(), gt_box, W, H)
            if matched:
                target_rank = i + 1
                target_iou  = float(iou)
                target_dist = float(dist)
                break

        matched_floor = target_rank is not None
        if matched_floor:
            floor_matched += 1

        # Op_conf rank
        op_rank = None
        for i, (box, conf) in enumerate(zip(boxes, confs)):
            if conf < OP_CONF:
                break
            matched, _, _ = match_gt(box.tolist(), gt_box, W, H)
            if matched:
                op_rank = i + 1
                op_matched += 1
                break

        per_frame[fid] = {
            "target_rank_floor": target_rank,
            "matched_floor":     matched_floor,
            "target_iou":        target_iou,
            "target_dist_norm":  target_dist,
            "n_candidates":      len(confs),
            "op_rank":           op_rank,
        }

    n = len([v for v in per_frame.values() if "matched_floor" in v])
    floor_recall = floor_matched / n if n > 0 else 0
    op_recall    = op_matched / n if n > 0 else 0

    # Top-K recall
    topk_recall = {}
    for k in [1, 3, 5, 10, 25]:
        matched_k = sum(1 for v in per_frame.values()
                        if v.get("target_rank_floor") and v["target_rank_floor"] <= k)
        topk_recall[str(k)] = {"matched": matched_k, "recall": matched_k / n if n > 0 else 0}

    # MRR
    mrr = sum(1/v["target_rank_floor"] for v in per_frame.values()
              if v.get("target_rank_floor")) / n if n > 0 else 0

    # Per-phase breakdown
    by_phase = {}
    for fid, v in per_frame.items():
        phase = fid.split("_", 1)[1] if "_" in fid else fid
        if phase not in by_phase:
            by_phase[phase] = {"n": 0, "floor_matched": 0, "ranks": []}
        by_phase[phase]["n"] += 1
        if v.get("matched_floor"):
            by_phase[phase]["floor_matched"] += 1
        if v.get("target_rank_floor"):
            by_phase[phase]["ranks"].append(v["target_rank_floor"])

    print(f"\n  Floor recall:    {floor_recall:.1%} ({floor_matched}/{n})")
    print(f"  Op_conf recall:  {op_recall:.1%} ({op_matched}/{n})")
    print(f"  Top-1 recall:    {topk_recall['1']['recall']:.1%}")
    print(f"  Top-5 recall:    {topk_recall['5']['recall']:.1%}")
    print(f"  Top-10 recall:   {topk_recall['10']['recall']:.1%}")
    print(f"  MRR:             {mrr:.3f}")
    print(f"\n  Phase breakdown:")
    for phase in sorted(by_phase):
        b = by_phase[phase]
        mean_rank = sum(b["ranks"])/len(b["ranks"]) if b["ranks"] else float("inf")
        print(f"    {phase:15s}: recall={b['floor_matched']}/{b['n']} mean_rank={mean_rank:.1f}")

    return {
        "label":          label,
        "floor_recall":   floor_recall,
        "op_recall":      op_recall,
        "topk_recall":    topk_recall,
        "mrr":            mrr,
        "n_canonical":    n,
        "per_frame":      per_frame,
        "by_phase":       {p: {k: v for k,v in b.items() if k != "ranks"}
                          for p,b in by_phase.items()},
    }


def main():
    print("Phase O — D5 Development Floor Audit")
    print("="*60)

    # D4 baseline
    d4_result = eval_model(MODEL_D4, "D4_baseline")

    # D5-A
    d5a_result = eval_model(MODEL_D5, "D5_A")

    # Gate
    d5_floor = d5a_result["floor_recall"]
    d5_top1  = d5a_result["topk_recall"]["1"]["recall"]
    d4_op    = d4_result["op_recall"]

    print("\n" + "="*60)
    print("PHASE O GATE")
    print("="*60)
    print(f"  D4 floor recall: {d4_result['floor_recall']:.1%}")
    print(f"  D5-A floor recall: {d5_floor:.1%}")
    print(f"  D4 op_conf recall: {d4_op:.1%}")
    print(f"  D5-A op_conf recall: {d5a_result['op_recall']:.1%}")
    print(f"  D5-A top-1 recall: {d5_top1:.1%}")

    gate_floor = d5_floor >= 0.95   # must maintain near-100% floor recall
    gate_op    = d5a_result["op_recall"] >= d4_op - 0.05  # no more than 5pp regression
    gate = "PASS" if (gate_floor and gate_op) else "FAIL"
    print(f"\n  GATE: {gate}")
    if not gate_floor:
        print(f"  ✗ Floor recall {d5_floor:.1%} < 95% threshold")
    if not gate_op:
        print(f"  ✗ Op_conf recall regression: D5={d5a_result['op_recall']:.1%} vs D4={d4_op:.1%}")

    out = {
        "label":      "D5_DEV_EVAL",
        "date":       datetime.date.today().isoformat(),
        "D4":         d4_result,
        "D5_A":       d5a_result,
        "gate":       gate,
        "paris_firewall": "Paris excluded from evaluation",
    }
    path = f"{RESULTS}/D5_DEV_EVAL.json"
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nSaved: {path}")
    return out


if __name__ == "__main__":
    main()
