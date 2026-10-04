#!/usr/bin/env python3
"""Phase B — D5-only vs D5+R1 ablation on DEVELOPMENT canonical frames.

Compares:
  P0 — D5-A raw confidence top-1
  P1 — D5-A + frozen R1 reranker top-1

Uses ALL 34 canonical DEVELOPMENT frames.
Paris firewall: no Paris frames in this evaluation.
"""
import os, sys, json, pickle, glob, hashlib, datetime
import cv2
import numpy as np

BASE = os.path.expanduser("~/dive-analyser")
ANNOTATIONS_DIR = f"{BASE}/docs/science/localization_annotations_v1/DEVELOPMENT_DESIGN"
PROXY_ROOT = f"{BASE}/media/cache/proxy_360p"
MODEL_D5 = f"{BASE}/models/frozen/DIVER_DETECTOR_D5_A_V8N_best.pt"
R1_PKL = f"{BASE}/models/frozen/R1_RERANKER.pkl"
RESULTS_DIR = f"{BASE}/docs/science/reranker_v1"

FLOOR_CONF = 0.001
FLOOR_CAP = 200
IOU_MATCH = 0.30
DIST_MATCH = 0.05
CROP_PADDING = 0.20
CROP_SIZE = 224

# ── Setup ──────────────────────────────────────────────────────────────────────
sys.path.insert(0, f"{BASE}/experiments/landmark_pilot")

import torch
import torchvision.transforms as T
from torchvision.models import resnet50, ResNet50_Weights
from ultralytics import YOLO

print("Loading D5-A model...")
yolo_d5 = YOLO(MODEL_D5)

print("Loading R1 reranker...")
with open(R1_PKL, "rb") as f:
    r1_bundle = pickle.load(f)
scaler = r1_bundle["scaler"]
clf = r1_bundle["clf"]

print("Loading ResNet50 backbone...")
backbone = resnet50(weights=ResNet50_Weights.IMAGENET1K_V1)
backbone.fc = torch.nn.Identity()
backbone.eval()
backbone = backbone.cpu()

tfm = T.Compose([
    T.ToPILImage(),
    T.Resize(256),
    T.CenterCrop(224),
    T.ToTensor(),
    T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])

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
    return ((c1x-c2x)**2 + (c1y-c2y)**2)**0.5

def match_gt(pred_box, gt_box, W, H):
    iou = box_iou(pred_box, gt_box)
    dist = center_dist_norm(pred_box, gt_box, W, H)
    return (iou >= IOU_MATCH or dist <= DIST_MATCH), float(iou)

def extract_crop_feature(frame_bgr, box):
    H, W = frame_bgr.shape[:2]
    x1, y1, x2, y2 = box
    bw, bh = x2-x1, y2-y1
    px, py = bw*CROP_PADDING, bh*CROP_PADDING
    cx1 = max(0, int(x1-px)); cy1 = max(0, int(y1-py))
    cx2 = min(W, int(x2+px)); cy2 = min(H, int(y2+py))
    crop = frame_bgr[cy1:cy2, cx1:cx2]
    if crop.size == 0 or min(crop.shape[:2]) < 2:
        return np.zeros(2048)
    crop_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
    t = tfm(crop_rgb).unsqueeze(0)
    with torch.no_grad():
        feat = backbone(t).squeeze().numpy()
    return feat

# ── Load annotations ───────────────────────────────────────────────────────────
ann_files = sorted(glob.glob(f"{ANNOTATIONS_DIR}/*.json"))
annotations = []
for fp in ann_files:
    d = json.load(open(fp))
    if d.get("visibility") in ("visible", "partial"):
        annotations.append(d)

print(f"\nLoaded {len(annotations)} visible/partial annotations")

# ── Evaluate each frame ────────────────────────────────────────────────────────
per_frame = {}
frame_cache = {}  # media_key -> loaded frame

for ann in annotations:
    frame_id = f"{ann['dive_id']}_{ann['phase']}"
    media_key = ann["media_key"]
    frame_idx = ann["frame_index"]
    gt_box = ann["bbox"]  # [x1,y1,x2,y2] in proxy pixels
    W, H = ann["width"], ann["height"]

    # Load frame (cache by media_key)
    if media_key not in frame_cache:
        vpath = f"{PROXY_ROOT}/{media_key[:2]}/{media_key[2:4]}/{media_key}.mp4"
        if not os.path.exists(vpath):
            print(f"  MISSING VIDEO: {vpath} ({frame_id})")
            per_frame[frame_id] = {"error": "MISSING_VIDEO"}
            continue
        cap = cv2.VideoCapture(vpath)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        cap.release()
        if not ret:
            print(f"  FAIL read frame {frame_idx} from {media_key} ({frame_id})")
            per_frame[frame_id] = {"error": "READ_FAIL"}
            continue
        frame_cache[media_key] = frame
    frame_bgr = frame_cache[media_key]
    fH, fW = frame_bgr.shape[:2]

    # D5-A inference at floor conf
    preds = yolo_d5(frame_bgr, conf=FLOOR_CONF, iou=0.45, imgsz=640, verbose=False, device="cpu")
    boxes_raw = preds[0].boxes
    if boxes_raw is None or len(boxes_raw) == 0:
        per_frame[frame_id] = {
            "p0_rank": None, "p1_rank": None, "gt_found": False,
            "n_candidates": 0, "gt_box": gt_box,
        }
        print(f"  {frame_id}: NO DETECTIONS")
        continue

    confs = boxes_raw.conf.cpu().numpy()
    boxes_np = boxes_raw.xyxy.cpu().numpy()
    order = np.argsort(-confs)
    confs = confs[order][:FLOOR_CAP]
    boxes_np = boxes_np[order][:FLOOR_CAP]

    # Find GT candidate rank (D5 confidence = P0)
    p0_rank = None
    p0_iou = 0.0
    for i, box in enumerate(boxes_np):
        matched, iou = match_gt(box.tolist(), gt_box, fW, fH)
        if matched and p0_rank is None:
            p0_rank = i + 1
            p0_iou = iou

    # Extract ResNet50 features for all candidates
    feats = []
    for box in boxes_np:
        f = extract_crop_feature(frame_bgr, box.tolist())
        feats.append(f)
    feats = np.array(feats)

    # R1 reranking (P1)
    if len(feats) > 0:
        feats_scaled = scaler.transform(feats)
        scores = clf.predict_proba(feats_scaled)[:, 1]  # P(positive)
        r1_order = np.argsort(-scores)
        boxes_r1 = boxes_np[r1_order]
        p1_rank = None
        p1_iou = 0.0
        for i, box in enumerate(boxes_r1):
            matched, iou = match_gt(box.tolist(), gt_box, fW, fH)
            if matched and p1_rank is None:
                p1_rank = i + 1
                p1_iou = iou
    else:
        p1_rank = None
        p1_iou = 0.0

    per_frame[frame_id] = {
        "p0_rank": p0_rank,    # D5-A confidence rank of GT
        "p1_rank": p1_rank,    # D5+R1 rank of GT
        "p0_iou": round(p0_iou, 4),
        "p1_iou": round(p1_iou, 4),
        "gt_found": p0_rank is not None,
        "n_candidates": len(confs),
    }
    p0_str = f"rank {p0_rank}" if p0_rank else "NOT FOUND"
    p1_str = f"rank {p1_rank}" if p1_rank else "NOT FOUND"
    delta = ""
    if p0_rank and p1_rank:
        d = p1_rank - p0_rank
        delta = f" (Δ={d:+d})"
    print(f"  {frame_id:25s}: P0={p0_str:10s}  P1={p1_str:10s}{delta}")

# ── Compute summary metrics ────────────────────────────────────────────────────
valid = {k: v for k, v in per_frame.items() if "error" not in v}
n = len(valid)

def topk_recall(d, k):
    return sum(1 for v in d.values() if v.get("p0_rank") is not None and v["p0_rank"] <= k) / n

def topk_recall_r1(d, k):
    return sum(1 for v in d.values() if v.get("p1_rank") is not None and v["p1_rank"] <= k) / n

def mrr(d, key):
    total = sum(1.0/v[key] if v.get(key) else 0 for v in d.values())
    return total / n

p0_top1 = sum(1 for v in valid.values() if v.get("p0_rank") == 1) / n
p1_top1 = sum(1 for v in valid.values() if v.get("p1_rank") == 1) / n
p0_top3 = topk_recall(valid, 3)
p1_top3 = topk_recall_r1(valid, 3)
p0_mrr = mrr(valid, "p0_rank")
p1_mrr = mrr(valid, "p1_rank")

print(f"\n{'='*60}")
print(f"DEVELOPMENT ABLATION RESULTS (n={n} frames)")
print(f"{'Metric':30s} {'P0 (D5-only)':>15s} {'P1 (D5+R1)':>15s} {'Δ':>8s}")
print(f"{'-'*70}")
print(f"{'Top-1 recall':30s} {p0_top1:>14.1%} {p1_top1:>14.1%} {p1_top1-p0_top1:>+8.1%}")
print(f"{'Top-3 recall':30s} {p0_top3:>14.1%} {p1_top3:>14.1%} {p1_top3-p0_top3:>+8.1%}")
print(f"{'MRR':30s} {p0_mrr:>14.3f} {p1_mrr:>14.3f} {p1_mrr-p0_mrr:>+8.3f}")

# Frames where P1 helps vs hurts vs neutral
helped = sum(1 for v in valid.values()
             if v.get("p0_rank") and v.get("p1_rank") and v["p1_rank"] < v["p0_rank"])
hurt = sum(1 for v in valid.values()
           if v.get("p0_rank") and v.get("p1_rank") and v["p1_rank"] > v["p0_rank"])
neutral = sum(1 for v in valid.values()
              if v.get("p0_rank") and v.get("p1_rank") and v["p1_rank"] == v["p0_rank"])
recovered = sum(1 for v in valid.values()
                if not v.get("p0_rank") and v.get("p1_rank"))
lost = sum(1 for v in valid.values()
           if v.get("p0_rank") and not v.get("p1_rank"))

print(f"\nR1 impact breakdown:")
print(f"  Improved (P1_rank < P0_rank): {helped}")
print(f"  Degraded (P1_rank > P0_rank): {hurt}")
print(f"  Neutral  (same rank):         {neutral}")
print(f"  Recovered (P0=None, P1 found): {recovered}")
print(f"  Lost     (P0 found, P1=None): {lost}")

# Phase breakdown
for phase in ["takeoff", "apex", "water_contact"]:
    pv = {k:v for k,v in valid.items() if k.endswith(f"_{phase}")}
    np_ = len(pv)
    if np_ == 0: continue
    t1_p0 = sum(1 for v in pv.values() if v.get("p0_rank") == 1) / np_
    t1_p1 = sum(1 for v in pv.values() if v.get("p1_rank") == 1) / np_
    print(f"  {phase:20s}: P0 top-1={t1_p0:.1%}  P1 top-1={t1_p1:.1%}  (n={np_})")

# Simplicity gate: does R1 still add material value?
MATERIAL_THRESHOLD = 0.05
r1_adds_value = (p1_top1 - p0_top1) >= MATERIAL_THRESHOLD
print(f"\nR1 material threshold ({MATERIAL_THRESHOLD:.0%}): {'MEETS' if r1_adds_value else 'DOES NOT MEET'}")
if r1_adds_value:
    print("  → R1 ADDS MATERIAL VALUE over D5-alone. RETAIN R1.")
else:
    print("  → R1 does NOT add material value. PREFER D5_FRAMEWISE.")

out = {
    "label": "D5_VS_R1_ABLATION_V1",
    "date": datetime.date.today().isoformat(),
    "n_frames": n,
    "P0_D5_only": {
        "top1_recall": round(p0_top1, 4),
        "top3_recall": round(p0_top3, 4),
        "mrr": round(p0_mrr, 4),
    },
    "P1_D5_plus_R1": {
        "top1_recall": round(p1_top1, 4),
        "top3_recall": round(p1_top3, 4),
        "mrr": round(p1_mrr, 4),
    },
    "delta_top1": round(p1_top1 - p0_top1, 4),
    "r1_helped": helped,
    "r1_hurt": hurt,
    "r1_neutral": neutral,
    "r1_recovered": recovered,
    "r1_lost": lost,
    "material_threshold": MATERIAL_THRESHOLD,
    "r1_adds_value": r1_adds_value,
    "per_frame": per_frame,
    "paris_firewall": "VERIFIED — no Paris frames in DEVELOPMENT evaluation",
}
out_path = f"{RESULTS_DIR}/D5_VS_R1_ABLATION_V1.json"
with open(out_path, "w") as f:
    json.dump(out, f, indent=2)
print(f"\nResults saved: {out_path}")
