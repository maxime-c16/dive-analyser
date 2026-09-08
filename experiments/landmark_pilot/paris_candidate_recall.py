#!/usr/bin/env python3
"""Phase N — Paris raw D3.1 candidate recall against the human-boxed 14 Paris frames.
Same match rule as experiments/landmark_pilot/candidate_recall.py (MATCH iou>=0.30,
AMBIGUOUS 0.10<=iou<0.30, else NOT_DETECTED), applied to the native-resolution PARIS
raw candidates (PARIS_native_raw.json) against the human PARIS labels.
"""
import json, glob, os

ANNOT_DIR = "docs/science/localization_annotations_v1/PARIS"
RAW_PATH = "experiments/landmark_pilot/runs/target_selection_v1/PARIS_native_raw.json"


def iou_xyxy(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    aarea = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    barea = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = aarea + barea - inter
    return inter / union if union > 0 else 0.0


def center(box):
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def main():
    raw = json.load(open(RAW_PATH))
    frames = raw["frames"]
    w, h = raw["width"], raw["height"]
    results = {}
    for f in sorted(glob.glob(f"{ANNOT_DIR}/*.json")):
        annot = json.load(open(f))
        rid = annot["id"]
        if annot.get("bbox") is None:
            results[rid] = {"available": True, "verdict": "OCCLUDED_NO_GT_BOX",
                             "visibility": annot.get("visibility")}
            continue
        fidx = annot["frame_index"]
        aw, ah = annot["width"], annot["height"]
        gt_bbox_px = annot["bbox"]
        gt_norm = [gt_bbox_px[0] / aw, gt_bbox_px[1] / ah, gt_bbox_px[2] / aw, gt_bbox_px[3] / ah]
        gt_c = center(gt_norm)
        if fidx >= len(frames):
            results[rid] = {"available": True, "verdict": "FRAME_OUT_OF_RANGE"}
            continue
        fr = frames[fidx]
        cands = fr["all_candidates"]
        if not cands:
            results[rid] = {"available": True, "verdict": "TARGET_NOT_DETECTED", "n_candidates": 0}
            continue
        cands_sorted = sorted(cands, key=lambda c: -c["conf"])
        best = None
        best_iou = -1.0
        for c in cands_sorted:
            cbox = [c["cx_norm"] - c["bw_norm"] / 2, c["cy_norm"] - c["bh_norm"] / 2,
                    c["cx_norm"] + c["bw_norm"] / 2, c["cy_norm"] + c["bh_norm"] / 2]
            iou = iou_xyxy(cbox, gt_norm)
            if iou > best_iou:
                best_iou = iou
                best = c
        cd = ((best["cx_norm"] - gt_c[0]) ** 2 + (best["cy_norm"] - gt_c[1]) ** 2) ** 0.5
        rank = cands_sorted.index(best) + 1
        # what did the frozen N0 selector actually choose at this frame?
        sel = fr["selected"]
        sel_matches_best = (sel is not None and sel["cx_norm"] == best["cx_norm"]
                             and sel["cy_norm"] == best["cy_norm"])
        if best_iou >= 0.30 or cd <= 0.05:
            verdict = "TARGET_SELECTED_CORRECTLY" if sel_matches_best else "TARGET_DETECTED_BUT_NOT_SELECTED"
        elif best_iou >= 0.10:
            verdict = "AMBIGUOUS_REFERENCE"
        else:
            verdict = "TARGET_NOT_DETECTED"
        results[rid] = {
            "available": True, "frame_index": fidx, "n_candidates": len(cands),
            "best_iou": round(best_iou, 4), "best_center_dist_norm": round(cd, 4),
            "best_candidate_conf": round(best["conf"], 4), "best_candidate_conf_rank": rank,
            "selected_conf": round(sel["conf"], 4) if sel else None,
            "selected_matches_best": sel_matches_best, "verdict": verdict,
        }
    counts = {}
    for r in results.values():
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    out = {"per_frame": results, "counts": counts}
    json.dump(out, open("experiments/landmark_pilot/runs/target_selection_v1/phase_n_paris_candidate_recall.json", "w"), indent=1)
    print(json.dumps(counts, indent=1))
    for rid, r in results.items():
        print(rid, r.get("verdict"), "iou=", r.get("best_iou"), "rank=", r.get("best_candidate_conf_rank"))


if __name__ == "__main__":
    main()
