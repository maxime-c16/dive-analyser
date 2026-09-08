#!/usr/bin/env python3
"""Phase G/H/I/J — DEVELOPMENT selector evaluation: S0 vs S1 vs S2.

For each dive and each selector's trajectory JSON, computes:
  - per-phase (takeoff/apex/water_contact) identity match at the human reference frame
    (same iou/center-dist rule as candidate_recall.py, applied to the SELECTOR's own
    choice rather than the best raw candidate)
  - whole-trajectory diagnostics: coverage (non-NULL fraction), longest NULL gap
    (frames and seconds), std(cy_norm) over non-NULL points (the static/wrong-lock
    proxy already validated in REAL_TRAJECTORY_EVENT_LOGIC_V2_2_REPORT.md, where a
    genuine wrong-target lock measured std=0.0002-0.0016 and real dive motion is
    expected to be at least an order of magnitude larger)
  - context (STANDING/HURDLE) pulled from a small manifest below (dive apparatus/code
    known from PROJECT_STATE.md/REAL_TRAJECTORY_EVENT_LOGIC_V2_2_REPORT.md Section 2/D1)

STATIC_LOCK_STD_THRESHOLD = 0.01 chosen as a conservative cutoff well above the
confirmed false-positive std (<=0.0016 in every case seen so far) and well below any
genuine flight trajectory's std observed in this corpus so far (dive 133 alone has
std well over 0.05 across its full flight window).
"""
import json, sys, os
import numpy as np

ANNOT_DIR = "docs/science/localization_annotations_v1/DEVELOPMENT_DESIGN"
RAW_DIR = "experiments/landmark_pilot/runs/target_selection_v1"
PHASES = ["takeoff", "apex", "water_contact"]
SELECTORS = ["s0", "s1", "s2"]
STATIC_LOCK_STD_THRESHOLD = 0.01

# context per dive_id: HURDLE vs STANDING. Springboard dives without an explicit
# hurdle marker in the existing science docs default to STANDING (documented
# assumption -- see report Section "context distribution").
# Corrected this cycle: derived from the REAL dive codes (DIVE_CODE below, sourced
# from dev_analysis.py's previously-committed authority) via the frozen Event Logic
# V2.1 classify_context() function itself -- NOT a hand guess. The prior draft of
# this file wrongly hardcoded 10 STANDING / 2 HURDLE; the real split is 4/8.
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(__file__))
from proposer_event_logic_v2_1 import classify_context as _classify_context
DIVE_CONTEXT = {did: _classify_context(code) for did, code in {
    133: "301B", 311: "401C", 524: "103B", 676: "301A", 1040: "102C",
    2169: "101B", 2341: "101B", 2387: "5411C", 2541: "5111B", 2555: "5132D",
    2625: "103B", 2680: "010C",
}.items()}
DIVE_CODE = {
    133: "301B", 311: "401C", 524: "103B", 676: "301A", 1040: "102C",
    2387: "5411C", 2625: "103B", 2680: "010C", 2169: "101B", 2341: None,
    2541: None, 2555: "5132D",
}


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


def eval_dive_selector(dive_id, sel_name, sel_path):
    if not os.path.exists(sel_path):
        return {"status": "MISSING"}
    sel = json.load(open(sel_path))
    points = sel["points"]
    n = len(points)
    cy_vals = [p["selected"]["cy_norm"] for p in points if p["selected"] is not None]
    n_null = sum(1 for p in points if p["selected"] is None)
    coverage = 1.0 - n_null / max(1, n)

    # longest NULL gap in seconds
    longest_gap_s = 0.0
    gap_start = None
    for p in points:
        if p["selected"] is None:
            if gap_start is None:
                gap_start = p["pts_s"] if p["pts_s"] is not None else p["frame_index"]
            end = p["pts_s"] if p["pts_s"] is not None else p["frame_index"]
        else:
            if gap_start is not None:
                longest_gap_s = max(longest_gap_s, end - gap_start)
                gap_start = None
    if gap_start is not None:
        longest_gap_s = max(longest_gap_s, end - gap_start)

    std_cy = float(np.std(cy_vals)) if len(cy_vals) > 1 else 0.0
    near_zero_variance_lock = std_cy < STATIC_LOCK_STD_THRESHOLD

    phase_results = {}
    for phase in PHASES:
        annot_path = f"{ANNOT_DIR}/{dive_id}_{phase}.json"
        if not os.path.exists(annot_path):
            phase_results[phase] = {"available": False}
            continue
        annot = json.load(open(annot_path))
        if annot.get("bbox") is None:
            phase_results[phase] = {"available": True, "verdict": "NOT_ANNOTATED"}
            continue
        fidx = annot["frame_index"]
        aw, ah = annot["width"], annot["height"]
        gt_bbox_px = annot["bbox"]
        gt_norm = [gt_bbox_px[0] / aw, gt_bbox_px[1] / ah, gt_bbox_px[2] / aw, gt_bbox_px[3] / ah]
        gt_c = center(gt_norm)
        if fidx >= n:
            phase_results[phase] = {"available": True, "verdict": "FRAME_OUT_OF_RANGE"}
            continue
        chosen = points[fidx]["selected"]
        if chosen is None:
            phase_results[phase] = {"available": True, "verdict": "NULL_AT_REFERENCE"}
            continue
        w, h = sel.get("width"), sel.get("height")
        # candidate xyxy already in raw video pixel space (same rendition); normalize directly
        cx, cy = chosen["cx_norm"], chosen["cy_norm"]
        d = ((cx - gt_c[0]) ** 2 + (cy - gt_c[1]) ** 2) ** 0.5
        # approximate iou using normalized boxes (bw/bh norm available on candidate)
        chosen_norm_box = [cx - chosen["bw_norm"] / 2, cy - chosen["bh_norm"] / 2,
                            cx + chosen["bw_norm"] / 2, cy + chosen["bh_norm"] / 2]
        iou = iou_xyxy(chosen_norm_box, gt_norm)
        match = (iou >= 0.30) or (d <= 0.05)
        phase_results[phase] = {
            "available": True, "center_dist_norm": round(d, 4), "iou": round(iou, 4),
            "conf": round(chosen["conf"], 4), "verdict": "MATCH" if match else "WRONG_TARGET",
        }

    return {
        "status": "EVALUATED", "n_frames": n, "coverage": round(coverage, 4),
        "longest_null_gap_s": round(longest_gap_s, 3), "std_cy_norm": round(std_cy, 5),
        "near_zero_variance_lock": near_zero_variance_lock, "phases": phase_results,
    }


def main():
    dive_ids = list(DIVE_CONTEXT.keys())
    report = {}
    for did in dive_ids:
        report[did] = {"context": DIVE_CONTEXT[did], "code": DIVE_CODE.get(did)}
        for sel in SELECTORS:
            path = f"{RAW_DIR}/{did}_{sel}.json"
            report[did][sel] = eval_dive_selector(did, sel, path)

    # aggregate per selector, split by context
    agg = {}
    for sel in SELECTORS:
        agg[sel] = {}
        for ctx in ["STANDING", "HURDLE", "ALL"]:
            rows = [report[d][sel] for d in dive_ids
                    if report[d][sel].get("status") == "EVALUATED"
                    and (ctx == "ALL" or report[d]["context"] == ctx)]
            if not rows:
                agg[sel][ctx] = {"n_dives": 0}
                continue
            n_dives = len(rows)
            correct_frames = sum(1 for r in rows for p in r["phases"].values()
                                  if p.get("verdict") == "MATCH")
            avail_frames = sum(1 for r in rows for p in r["phases"].values() if p.get("available") and p.get("verdict") != "NOT_ANNOTATED")
            static_lock_n = sum(1 for r in rows if r["near_zero_variance_lock"])
            mean_coverage = float(np.mean([r["coverage"] for r in rows]))
            agg[sel][ctx] = {
                "n_dives": n_dives,
                "correct_selection_rate": round(correct_frames / max(1, avail_frames), 4),
                "near_zero_variance_lock_rate": round(static_lock_n / n_dives, 4),
                "mean_target_coverage": round(mean_coverage, 4),
            }

    out = {"per_dive": report, "aggregate": agg}
    json.dump(out, open(sys.argv[1] if len(sys.argv) > 1 else f"{RAW_DIR}/phase_j_selector_comparison.json", "w"), indent=1)
    print(json.dumps(agg, indent=1))


if __name__ == "__main__":
    main()
