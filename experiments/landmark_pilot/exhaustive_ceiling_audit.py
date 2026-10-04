#!/usr/bin/env python3
"""D3 Exhaustive Raw Ceiling Audit — Phase B of DETECTOR_D4_REOPEN packet.

Runs D3 at conf=0.001 (diagnostic floor) on all 31 DEVELOPMENT reference frames.
Produces D3_EXHAUSTIVE_RAW_CEILING_V1 with top-K analysis and failure taxonomy.

Detection taxonomy:
  TARGET_AVAILABLE:         At conf>=0.05 operating point, IoU>=0.30 or center_dist<=0.05
  BELOW_THRESHOLD_TARGET:   At conf>=0.001 floor, IoU>=0.30 or center_dist<=0.05; not at conf>=0.05
  TARGET_NOT_LOCALIZED:     Even at conf=0.001, no candidate achieves IoU>=0.30 or center_dist<=0.05
  AMBIGUOUS_PARTIAL:        IoU in [0.10,0.30) at operating point; resolves to BELOW_THRESHOLD or NOT_LOCALIZED at floor

Paris firewall: this script operates on DEVELOPMENT only. No Paris data.
"""
import json, os, sys, math, cv2
import numpy as np

os.chdir(os.path.expanduser("~/dive-analyser"))

ANNOT_DIR = "docs/science/localization_annotations_v1/DEVELOPMENT_DESIGN"
RAW_DIR = "experiments/landmark_pilot/runs/target_selection_v1"
WEIGHTS = "models/frozen/DIVER_DETECTOR_D3_V8N_best.pt"
OUT_DIR = "experiments/landmark_pilot/runs/target_selection_v2"
DIAGNOSTIC_FLOOR = 0.001
OPERATING_CONF = 0.05
IOU_MATCH = 0.30
DIST_MATCH = 0.05
TOP_K = [1, 3, 5, 10, 20]

DIVES = [133, 311, 524, 676, 1040, 2387, 2625, 2680, 2169, 2341, 2541, 2555]
PHASES = ["takeoff", "apex", "water_contact"]

MEDIA_HASH = {
    1040: "9cb42af1a2aa79bb3a11a07c8b29baaf8c00d5ebda68826eb4c52c5a9202324e",
    133:  "c26271fda2aaa252e1dd9eb3c43a8f5374f69fea667b07fdcd1768240a9649eb",
    2169: "85c81842b1f892d0919d8db1dcaee3ed01a93d294d3cc350643b198988e844b0",
    2341: "3e01c635ade0139c1ad3eb39fed14790c06d7c64972169af1b8ced04d0aeeafc",
    2387: "e7bb8646edf66df370f0ff4958c1bf4736cb41df0e461428084fa6fa6486fc4a",
    2541: "cf92e9a817dfb9e5ad0ff553bb545cc63719fa25770514ec11126618c0578358",
    2555: "dd7a8621a89bd00af627560e2121dec4bacecb313d8b5ecd5027d91f2f9c9e44",
    2625: "4dc9064e1692518c412a4e6e55f67f92d26959d2bfecb3147617e914da3d84fd",
    2680: "d887b0fd8e173c80885dcd5fd15222c6202998a53bc6d493c571656a3f6661a1",
    311:  "dc1d176ed1ed24e004a6634f0ee91ae3e5150645a85380f33db399f55bedf10c",
    524:  "552d34613e606af9241e4a561c65a3dfb374479205b2dd76543fbdb8a376029f",
    676:  "2b512f91e6b244198942b974b9438163a12ece12c1422aa33dd93c966304d1f6",
}

def video_path(dive_id):
    mk = MEDIA_HASH[dive_id]
    return os.path.expanduser(f"~/dive-analyser/media/cache/proxy_360p/{mk[:2]}/{mk[2:4]}/{mk}.mp4")

def iou_xyxy_norm(a, b):
    """IoU of two [x1,y1,x2,y2] normalized boxes."""
    ix1, iy1 = max(a[0],b[0]), max(a[1],b[1])
    ix2, iy2 = min(a[2],b[2]), min(a[3],b[3])
    iw, ih = max(0, ix2-ix1), max(0, iy2-iy1)
    inter = iw*ih
    ua = max(0,a[2]-a[0])*max(0,a[3]-a[1])
    ub = max(0,b[2]-b[0])*max(0,b[3]-b[1])
    denom = ua+ub-inter
    return inter/denom if denom > 0 else 0.0

def center_dist(a, b):
    """Euclidean distance between centers of two [x1,y1,x2,y2] normalized boxes."""
    ac = ((a[0]+a[2])/2, (a[1]+a[3])/2)
    bc = ((b[0]+b[2])/2, (b[1]+b[3])/2)
    return math.sqrt((ac[0]-bc[0])**2 + (ac[1]-bc[1])**2)

def extract_frame(vpath, frame_idx):
    """Extract a single frame by index. Returns (frame_bgr, width, height) or (None,0,0)."""
    cap = cv2.VideoCapture(vpath)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        return None, 0, 0
    h, w = frame.shape[:2]
    return frame, w, h

def run_d3(model, frame_bgr, conf_floor, w, h):
    """Run D3 at conf_floor. Returns sorted-by-conf list of normalized candidates."""
    res = model.predict(frame_bgr, conf=conf_floor, iou=0.45, imgsz=640,
                        classes=[0], verbose=False, device="cpu")[0]
    cands = []
    for b in res.boxes:
        xyxy = b.xyxy[0].tolist()  # pixel coords
        conf = float(b.conf[0])
        x1n, y1n = xyxy[0]/w, xyxy[1]/h
        x2n, y2n = xyxy[2]/w, xyxy[3]/h
        cands.append({
            "conf": conf,
            "xyxy_norm": [x1n, y1n, x2n, y2n],
            "cx_norm": (x1n+x2n)/2,
            "cy_norm": (y1n+y2n)/2,
            "bw_norm": x2n-x1n,
            "bh_norm": y2n-y1n,
        })
    cands.sort(key=lambda c: -c["conf"])
    return cands

def match_gt(cands, gt_norm):
    """Score each candidate against GT. Return list of (iou, dist, conf, rank_by_conf)."""
    scored = []
    for rank_idx, c in enumerate(cands):
        iou = iou_xyxy_norm(c["xyxy_norm"], gt_norm)
        dist = center_dist(c["xyxy_norm"], gt_norm)
        scored.append({
            "rank_by_conf": rank_idx+1,
            "conf": c["conf"],
            "iou": round(iou, 4),
            "dist": round(dist, 4),
            "cx_norm": round(c["cx_norm"], 4),
            "cy_norm": round(c["cy_norm"], 4),
        })
    return scored

def find_best_match(scored):
    """Find candidate with best IoU in scored list."""
    if not scored:
        return None
    return max(scored, key=lambda s: s["iou"])

def is_match(s):
    """Positive match criterion: IoU>=0.30 OR center_dist<=0.05."""
    return s["iou"] >= IOU_MATCH or s["dist"] <= DIST_MATCH

def target_in_topk(scored, k):
    """Is there a matching candidate within the top-k by confidence?"""
    for s in scored[:k]:
        if is_match(s):
            return True
    return False

def classify_frame(scored_at_floor, scored_at_op):
    """
    Apply detection taxonomy:
      TARGET_AVAILABLE:        Match at op threshold (conf>=0.05)
      BELOW_THRESHOLD_TARGET:  Match at floor (conf>=0.001) but not at op
      TARGET_NOT_LOCALIZED:    No match even at floor

    scored_at_op: candidates at conf>=0.05 only (rank by conf, sorted)
    scored_at_floor: all candidates at conf>=0.001 (sorted by conf)
    """
    op_match = any(is_match(s) for s in scored_at_op)
    if op_match:
        return "TARGET_AVAILABLE"
    floor_match = any(is_match(s) for s in scored_at_floor)
    if floor_match:
        return "BELOW_THRESHOLD_TARGET"
    return "TARGET_NOT_LOCALIZED"


def main():
    from ultralytics import YOLO
    print("Loading D3 model...")
    model = YOLO(WEIGHTS)

    results = {}
    summary = {
        "canonical_denominator": 0,
        "target_available_count": 0,
        "below_threshold_count": 0,
        "not_localized_count": 0,
        "topk": {str(k): {"count": 0} for k in TOP_K},
        "topk_all": 0,
        "frames": []
    }

    for dive_id in DIVES:
        vpath = video_path(dive_id)
        if not os.path.exists(vpath):
            print(f"  SKIP {dive_id}: video not found at {vpath}")
            continue

        raw_path = f"{RAW_DIR}/{dive_id}_raw.json"
        raw_data = json.load(open(raw_path)) if os.path.exists(raw_path) else {}
        # Build frame->candidates dict from raw (conf>=0.05)
        frame_to_op_cands = {}
        for entry in raw_data.get("frames", []):
            fi = entry.get("frame_index", entry.get("frame", -1))
            frame_to_op_cands[fi] = entry.get("candidates", [])

        for phase in PHASES:
            annot_path = f"{ANNOT_DIR}/{dive_id}_{phase}.json"
            if not os.path.exists(annot_path):
                continue
            annot = json.load(open(annot_path))
            frame_idx = annot["frame_index"]
            aw = annot["width"]
            ah = annot["height"]
            gt_bbox = annot.get("bbox")  # [x1, y1, x2, y2] in annotation frame pixels
            visibility = annot.get("visibility", "visible")
            # Exclude: null bbox (can't define GT) or ambiguous (annotator uncertain of location)
            # Include: "visible" and "partial" (partially visible but bbox IS known)
            if gt_bbox is None or visibility == "ambiguous":
                print(f"  SKIP {dive_id}_{phase}: visibility={visibility} bbox={gt_bbox}")
                continue
            gt_norm = [gt_bbox[0]/aw, gt_bbox[1]/ah, gt_bbox[2]/aw, gt_bbox[3]/ah]

            summary["canonical_denominator"] += 1

            # Extract frame and run at diagnostic floor
            frame_bgr, w, h = extract_frame(vpath, frame_idx)
            if frame_bgr is None:
                print(f"  ERROR: Could not extract frame {frame_idx} from {vpath}")
                continue

            # Run at floor
            cands_floor = run_d3(model, frame_bgr, DIAGNOSTIC_FLOOR, w, h)
            scored_floor = match_gt(cands_floor, gt_norm)

            # Filter to op-threshold
            scored_op = [s for s in scored_floor if s["conf"] >= OPERATING_CONF]

            # Classify
            taxonomy = classify_frame(scored_floor, scored_op)

            # Top-K analysis
            topk_results = {}
            for k in TOP_K:
                topk_results[str(k)] = target_in_topk(scored_floor, k)
            topk_all = any(is_match(s) for s in scored_floor)

            # Find best match info
            best = find_best_match(scored_floor)
            best_at_op = find_best_match(scored_op) if scored_op else None

            # Target rank (rank of best-matching candidate by conf)
            target_rank = None
            target_conf = None
            if topk_all and best:
                # Find rank of the best-IoU candidate
                for i, s in enumerate(scored_floor):
                    if s["rank_by_conf"] == best["rank_by_conf"]:
                        target_rank = i+1
                        target_conf = best["conf"]
                        break

            frame_result = {
                "key": f"{dive_id}_{phase}",
                "dive_id": dive_id,
                "phase": phase,
                "frame_index": frame_idx,
                "gt_norm": [round(x, 4) for x in gt_norm],
                "taxonomy": taxonomy,
                "total_candidates_at_floor": len(cands_floor),
                "total_candidates_at_op": len(scored_op),
                "target_conf": round(target_conf, 4) if target_conf else None,
                "target_rank_by_conf": target_rank,
                "best_iou_at_floor": round(best["iou"], 4) if best else 0.0,
                "best_dist_at_floor": round(best["dist"], 4) if best else 1.0,
                "best_iou_at_op": round(best_at_op["iou"], 4) if best_at_op else 0.0,
                "topk": topk_results,
                "topk_all": topk_all,
                "all_candidates_at_floor": [
                    {
                        "rank": s["rank_by_conf"],
                        "conf": round(s["conf"], 4),
                        "iou": s["iou"],
                        "dist": s["dist"],
                        "cx": s["cx_norm"],
                        "cy": s["cy_norm"],
                    }
                    for s in scored_floor
                ]
            }

            print(f"  {dive_id}_{phase}: {taxonomy} | n_floor={len(cands_floor)} n_op={len(scored_op)} | best_iou={frame_result['best_iou_at_floor']} | topk_all={topk_all}")

            summary["frames"].append(frame_result)

            if taxonomy == "TARGET_AVAILABLE":
                summary["target_available_count"] += 1
            elif taxonomy == "BELOW_THRESHOLD_TARGET":
                summary["below_threshold_count"] += 1
            else:
                summary["not_localized_count"] += 1

            if topk_all:
                summary["topk_all"] += 1
            for k in TOP_K:
                if topk_results[str(k)]:
                    summary["topk"][str(k)]["count"] += 1

    # Final summary
    n = summary["canonical_denominator"]
    avail = summary["target_available_count"]
    below = summary["below_threshold_count"]
    no_loc = summary["not_localized_count"]

    print("\n=== D3_EXHAUSTIVE_RAW_CEILING_V1 SUMMARY ===")
    print(f"Canonical denominator (annotated frames): {n}")
    print(f"TARGET_AVAILABLE (at conf>=0.05):         {avail}/{n} = {avail/n:.3f}")
    print(f"BELOW_THRESHOLD_TARGET (at 0.001<0.05):  {below}/{n} = {below/n:.3f}")
    print(f"TARGET_NOT_LOCALIZED (no match at floor): {no_loc}/{n} = {no_loc/n:.3f}")
    print(f"Exhaustive ceiling (avail+below):         {avail+below}/{n} = {(avail+below)/n:.3f}")
    print(f"True ceiling (topk_all):                  {summary['topk_all']}/{n}")
    print()
    for k in TOP_K:
        cnt = summary["topk"][str(k)]["count"]
        print(f"  Top-{k:2d}: {cnt}/{n} = {cnt/n:.3f}")

    summary_out = {
        "label": "D3_EXHAUSTIVE_RAW_CEILING_V1",
        "date": "2026-09-08",
        "model": "DIVER_DETECTOR_D3_V8N",
        "weights_sha256": "bf6415fb63aa311f45262e555899d3023dd3d05d43a5e0d69b5e86c342e1a77d",
        "diagnostic_floor_conf": DIAGNOSTIC_FLOOR,
        "operating_conf": OPERATING_CONF,
        "iou_match_threshold": IOU_MATCH,
        "dist_match_threshold": DIST_MATCH,
        "canonical_denominator": n,
        "target_available_count": avail,
        "below_threshold_count": below,
        "not_localized_count": no_loc,
        "exhaustive_ceiling": round((avail+below)/n, 4) if n > 0 else 0,
        "target_available_rate": round(avail/n, 4) if n > 0 else 0,
        "topk_all": summary["topk_all"],
        "topk_results": {str(k): {"count": summary["topk"][str(k)]["count"], "rate": round(summary["topk"][str(k)]["count"]/n, 4)} for k in TOP_K},
        "frames": summary["frames"],
        "paris_firewall": "DEVELOPMENT_ONLY — Paris data not used",
        "taxonomy_note": "AMBIGUOUS (IoU 0.10-0.30 at op-conf) resolved at floor: if floor gives IoU>=0.30 or dist<=0.05 -> BELOW_THRESHOLD_TARGET; else TARGET_NOT_LOCALIZED",
    }

    out_path = f"{OUT_DIR}/D3_EXHAUSTIVE_RAW_CEILING_V1.json"
    with open(out_path, "w") as f:
        json.dump(summary_out, f, indent=2)
    print(f"\nSaved to {out_path}")

if __name__ == "__main__":
    main()
