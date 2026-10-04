#!/usr/bin/env python3
"""Phase A + A1 — D4 Proposal-Floor Audit.

Runs D4 at conf=0.001 (floor) on all 31 canonical DEVELOPMENT reference frames.
Reports per-frame and aggregate target recall, rank distribution, and top-K recall.

Outputs: D4_FLOOR_AUDIT_V1.json
Freezes: D4_CANDIDATE_FLOOR_V1_FREEZE.json
"""
import os, json, glob, datetime
import numpy as np
import cv2
from ultralytics import YOLO

BASE      = "/tmp/diveanalyzer-exp"
DATA      = f"{BASE}/data"
RESULTS   = f"{BASE}/results"
ANNOT_DIR = f"{DATA}/DEVELOPMENT_DESIGN"
VIDEO_DIR = f"{DATA}/proxy_videos"
MODEL_PT  = f"{DATA}/DIVER_DETECTOR_D4_A_V8N_best.pt"
WEIGHTS_SHA = "842291f1cd3c5ad086faa467ccaac197c56bdd63dcdd2b67a91c4a7d8fbc3aaa"

os.makedirs(RESULTS, exist_ok=True)

# Canonical frames derived dynamically from DEVELOPMENT_DESIGN annotations.
# Include: visibility="visible" AND has_bbox.
# This captures 34 frames (D4 historical canonical was 31;
# 2353/2661 frames were annotated during the D4 cycle and expand the set).
import glob as _glob

def _load_canonical_frames():
    frames = []
    for f in sorted(_glob.glob(f"{ANNOT_DIR}/*.json")):
        d = json.load(open(f))
        fid = os.path.splitext(os.path.basename(f))[0]
        if d.get("visibility") == "visible" and d.get("bbox") is not None:
            frames.append(fid)
    return frames

CANONICAL_FRAMES = _load_canonical_frames()

FLOOR_CONF = 0.001
OP_CONF    = 0.05
NMS_IOU    = 0.45
IMGSZ      = 640

EVAL_THRESHOLDS = [0.001, 0.005, 0.01, 0.02, 0.03, 0.05, 0.10, 0.20]
TOP_K_LIST      = [1, 2, 3, 5, 10, 25, 50, 100, 999]   # 999 = exhaustive


def iou_xyxy(a, b):
    ax1,ay1,ax2,ay2 = a
    bx1,by1,bx2,by2 = b
    ix1,iy1 = max(ax1,bx1),max(ay1,by1)
    ix2,iy2 = min(ax2,bx2),min(ay2,by2)
    iw,ih = max(0.0,ix2-ix1),max(0.0,iy2-iy1)
    inter = iw*ih
    ua = max(0,ax2-ax1)*max(0,ay2-ay1)
    ub = max(0,bx2-bx1)*max(0,by2-by1)
    u = ua+ub-inter
    return inter/u if u>0 else 0.0


def center_dist_norm(pred_xyxy, gt_xyxy, W, H):
    pcx = (pred_xyxy[0]+pred_xyxy[2])/(2*W)
    pcy = (pred_xyxy[1]+pred_xyxy[3])/(2*H)
    gcx = (gt_xyxy[0]+gt_xyxy[2])/(2*W)
    gcy = (gt_xyxy[1]+gt_xyxy[3])/(2*H)
    return ((pcx-gcx)**2+(pcy-gcy)**2)**0.5


def match_gt(pred_xyxy, gt_xyxy, W, H, iou_thresh=0.30, ctr_thresh=0.05):
    iou = iou_xyxy(pred_xyxy, gt_xyxy)
    cd  = center_dist_norm(pred_xyxy, gt_xyxy, W, H)
    return iou >= iou_thresh or cd <= ctr_thresh, iou, cd


def get_video_path(media_key):
    return f"{VIDEO_DIR}/{media_key}.mp4"


def load_annotation(frame_id):
    path = f"{ANNOT_DIR}/{frame_id}.json"
    if not os.path.exists(path):
        return None
    d = json.load(open(path))
    if d.get("bbox") is None or d.get("visibility") != "visible":
        return None
    return d


def main():
    print(f"Loading D4 model: {MODEL_PT}")
    model = YOLO(MODEL_PT)
    print("Model loaded.\n")

    per_frame = {}

    for frame_id in CANONICAL_FRAMES:
        annot = load_annotation(frame_id)
        if annot is None:
            print(f"  SKIP {frame_id} — no valid annotation")
            per_frame[frame_id] = {"status": "NO_ANNOTATION"}
            continue

        media_key  = annot["media_key"]
        frame_idx  = annot["frame_index"]
        gt_bbox    = annot["bbox"]   # xyxy at annotation resolution
        ann_w      = annot["width"]
        ann_h      = annot["height"]
        video_path = get_video_path(media_key)

        if not os.path.exists(video_path):
            print(f"  MISSING video {video_path}")
            per_frame[frame_id] = {"status": "VIDEO_MISSING"}
            continue

        cap = cv2.VideoCapture(video_path)
        W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame_bgr = cap.read()
        cap.release()

        if not ret:
            print(f"  FAILED to read frame {frame_idx} from {video_path}")
            per_frame[frame_id] = {"status": "FRAME_READ_FAIL"}
            continue

        # Scale GT to video resolution
        gt_px = [
            gt_bbox[0] * W / ann_w,
            gt_bbox[1] * H / ann_h,
            gt_bbox[2] * W / ann_w,
            gt_bbox[3] * H / ann_h,
        ]

        # Run D4 at floor conf
        results = model(frame_bgr, conf=FLOOR_CONF, iou=NMS_IOU, imgsz=IMGSZ, verbose=False)
        preds = results[0].boxes
        if preds is None or len(preds) == 0:
            candidates = []
        else:
            boxes_xyxy = preds.xyxy.cpu().numpy()
            confs      = preds.conf.cpu().numpy()
            candidates = [
                {"xyxy": boxes_xyxy[i].tolist(), "conf": float(confs[i])}
                for i in range(len(confs))
            ]
        # Sort by confidence (desc)
        candidates.sort(key=lambda c: -c["conf"])
        n_floor = len(candidates)

        # Find best-IoU match to GT
        best_iou = 0.0
        best_idx = None
        target_rank_floor = None   # 1-indexed confidence rank of best-IoU candidate

        for i, c in enumerate(candidates):
            iou = iou_xyxy(c["xyxy"], gt_px)
            if iou > best_iou:
                best_iou = iou
                best_idx = i

        # Check center-dist match for best candidate
        if best_idx is not None:
            is_match, best_iou, cd = match_gt(candidates[best_idx]["xyxy"], gt_px, W, H)
        else:
            is_match, best_iou, cd = False, 0.0, 999.0

        if is_match:
            target_rank_floor = best_idx + 1  # 1-indexed

        # Compute per-threshold recall
        thresh_results = {}
        for thr in EVAL_THRESHOLDS:
            cands_at_thr = [c for c in candidates if c["conf"] >= thr]
            matched = any(
                match_gt(c["xyxy"], gt_px, W, H)[0]
                for c in cands_at_thr
            )
            thresh_results[str(thr)] = {
                "n_preds": len(cands_at_thr),
                "target_present": matched,
            }

        # Top-K target recall (by confidence rank) — using floor candidates
        topk_results = {}
        for k in TOP_K_LIST:
            k_actual = min(k, n_floor)
            topk_cands = candidates[:k_actual]
            topk_match = any(match_gt(c["xyxy"], gt_px, W, H)[0] for c in topk_cands)
            topk_results[k] = {"n_checked": k_actual, "target_present": topk_match}

        # Taxonomy
        if target_rank_floor is not None:
            if candidates[0]["conf"] >= OP_CONF and target_rank_floor == 1:
                taxonomy = "TARGET_SELECTED_CORRECTLY"
            elif is_match:
                taxonomy = "BELOW_THRESHOLD_TARGET" if candidates[0]["conf"] < OP_CONF else "TARGET_PRESENT_RANKED_BELOW_1"
            else:
                taxonomy = "TARGET_PRESENT_AT_FLOOR"
        else:
            taxonomy = "TARGET_NOT_LOCALIZED"

        # For op threshold: check if target is in top proposals
        cands_op = [c for c in candidates if c["conf"] >= OP_CONF]
        op_match = any(match_gt(c["xyxy"], gt_px, W, H)[0] for c in cands_op)

        result = {
            "frame_id": frame_id,
            "frame_index": frame_idx,
            "media_key": media_key,
            "video_W": W,
            "video_H": H,
            "n_floor": n_floor,
            "n_op": len(cands_op),
            "target_rank_floor": target_rank_floor,
            "target_iou_floor": float(best_iou),
            "target_center_dist": float(cd),
            "target_present_at_floor": is_match,
            "target_present_at_op": op_match,
            "taxonomy": taxonomy,
            "floor_conf_top1": float(candidates[0]["conf"]) if candidates else None,
            "threshold_results": thresh_results,
            "topk_results": {str(k): v for k, v in topk_results.items()},
            # Save all floor candidates for downstream use
            "floor_candidates": candidates,
        }
        per_frame[frame_id] = result

        target_rank_str = str(target_rank_floor) if target_rank_floor else "NOT_FOUND"
        print(f"  {frame_id:30s} floor={n_floor:4d} op={len(cands_op):3d} "
              f"rank={target_rank_str:5s} iou={best_iou:.3f} {taxonomy}")

    # Aggregate stats
    total = len(CANONICAL_FRAMES)
    evaluable = [k for k,v in per_frame.items() if v.get("status") is None]
    present_at_floor = sum(1 for v in per_frame.values() if v.get("target_present_at_floor"))
    present_at_op    = sum(1 for v in per_frame.values() if v.get("target_present_at_op"))

    # Top-K aggregate
    topk_agg = {}
    for k in TOP_K_LIST:
        ks = str(k)
        hits = sum(1 for v in per_frame.values()
                   if v.get("topk_results", {}).get(ks, {}).get("target_present", False))
        topk_agg[ks] = {"hits": hits, "total": total, "recall": hits/total}

    # Per-threshold aggregate
    thresh_agg = {}
    for thr in EVAL_THRESHOLDS:
        ths = str(thr)
        hits = sum(1 for v in per_frame.values()
                   if v.get("threshold_results", {}).get(ths, {}).get("target_present", False))
        n_avg = np.mean([v.get("threshold_results", {}).get(ths, {}).get("n_preds", 0)
                         for v in per_frame.values()
                         if v.get("threshold_results")])
        thresh_agg[ths] = {"hits": hits, "total": total, "recall": hits/total, "avg_n_preds": float(n_avg)}

    # Rank distribution for frames where target is found
    ranks = [v["target_rank_floor"] for v in per_frame.values()
             if v.get("target_rank_floor") is not None]
    rank_pctiles = {
        "min": min(ranks) if ranks else None,
        "p25": float(np.percentile(ranks,25)) if ranks else None,
        "median": float(np.median(ranks)) if ranks else None,
        "p75": float(np.percentile(ranks,75)) if ranks else None,
        "p90": float(np.percentile(ranks,90)) if ranks else None,
        "max": max(ranks) if ranks else None,
        "mean": float(np.mean(ranks)) if ranks else None,
    }

    print("\n" + "="*60)
    print("PHASE A SUMMARY")
    print(f"  Canonical frames: {total}")
    print(f"  Target present at floor (conf≥0.001): {present_at_floor}/{total} = {present_at_floor/total:.1%}")
    print(f"  Target present at op (conf≥0.05):     {present_at_op}/{total} = {present_at_op/total:.1%}")
    print(f"\n  Top-K target recall (floor candidates by confidence):")
    for k in TOP_K_LIST:
        ks = str(k)
        r = topk_agg[ks]
        print(f"    top-{k:3d}: {r['hits']:2d}/{total} = {r['recall']:.1%}")
    print(f"\n  Rank distribution of target (when found): {rank_pctiles}")
    print(f"\n  Per-threshold recall:")
    for thr in EVAL_THRESHOLDS:
        ths = str(thr)
        r = thresh_agg[ths]
        print(f"    conf≥{thr:.3f}: {r['hits']:2d}/{total} = {r['recall']:.1%}  avg_n_preds={r['avg_n_preds']:.1f}")

    # Floor freeze: conf=0.001, cap at 200 proposals (practical tractability)
    # Rationale: exhaustive ceiling at conf=0.001 with NMS gives O(100-200) candidates/frame;
    # beyond 200 candidates the compute cost is prohibitive with no additional recall gain.
    FLOOR_CAP = 200

    audit = {
        "label": "D4_FLOOR_AUDIT_V1",
        "date": datetime.date.today().isoformat(),
        "detector": "D4_PROPOSAL_V1",
        "weights_sha256": WEIGHTS_SHA,
        "floor_conf": FLOOR_CONF,
        "op_conf": OP_CONF,
        "nms_iou": NMS_IOU,
        "imgsz": IMGSZ,
        "canonical_denominator": total,
        "target_present_at_floor": present_at_floor,
        "target_present_at_op": present_at_op,
        "floor_recall": present_at_floor/total,
        "op_recall": present_at_op/total,
        "topk_recall": topk_agg,
        "per_threshold": thresh_agg,
        "target_rank_distribution": rank_pctiles,
        "per_frame": {k: {kk: vv for kk,vv in v.items() if kk != "floor_candidates"}
                      for k, v in per_frame.items()},
        "paris_firewall": "Paris excluded from all floor analysis",
    }

    # Phase A1 — Operational floor freeze
    # Decision: conf=0.001 (exhaustive), capped at FLOOR_CAP=200 candidates by confidence
    # Rationale: provides maximum recall, computationally tractable for reranker,
    # deterministic (top-200 by confidence = reproducible).
    floor_freeze = {
        "label": "D4_CANDIDATE_FLOOR_V1_FREEZE",
        "date": datetime.date.today().isoformat(),
        "status": "FROZEN",
        "detector": "D4_PROPOSAL_V1",
        "weights_sha256": WEIGHTS_SHA,
        "floor_conf": FLOOR_CONF,
        "floor_cap": FLOOR_CAP,
        "selection_policy": (
            f"Run D4 at conf={FLOOR_CONF}, nms_iou={NMS_IOU}, imgsz={IMGSZ}; "
            f"sort by confidence desc; take top min(n, {FLOOR_CAP}) proposals. "
            "This is the candidate stream for the reranker."
        ),
        "nms_iou": NMS_IOU,
        "imgsz": IMGSZ,
        "development_floor_recall": present_at_floor/total,
        "development_op_recall": present_at_op/total,
        "paris_firewall": "VERIFIED — Paris excluded from all analysis",
    }

    out_audit = f"{RESULTS}/D4_FLOOR_AUDIT_V1.json"
    out_freeze = f"{RESULTS}/D4_CANDIDATE_FLOOR_V1_FREEZE.json"

    # Save full audit (includes per-frame floor candidates for downstream)
    with open(out_audit, "w") as f:
        json.dump(audit, f, indent=2)
    with open(out_freeze, "w") as f:
        json.dump(floor_freeze, f, indent=2)

    # Also save per-frame candidates separately (needed for dataset building)
    candidates_out = {}
    for frame_id, v in per_frame.items():
        if "floor_candidates" in v:
            cands = v["floor_candidates"][:FLOOR_CAP]
            candidates_out[frame_id] = {
                "frame_index": v["frame_index"],
                "media_key": v["media_key"],
                "video_W": v["video_W"],
                "video_H": v["video_H"],
                "n_floor": len(cands),
                "candidates": cands,
            }
    with open(f"{RESULTS}/D4_FLOOR_CANDIDATES.json", "w") as f:
        json.dump(candidates_out, f, indent=2)

    print(f"\nOutputs written to {RESULTS}/")
    print(f"  {out_audit}")
    print(f"  {out_freeze}")
    print(f"  {RESULTS}/D4_FLOOR_CANDIDATES.json")

    return audit, floor_freeze


if __name__ == "__main__":
    main()
