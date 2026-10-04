#!/usr/bin/env python3
"""Phase H/G — DEVELOPMENT selector evaluation V2: S0 vs S1 vs S3.

Evaluates selector trajectories from runs/target_selection_v1/ (S0/S1) and
runs/target_selection_v2/ (S3) against human spatial reference frames.

Reports per-dive and aggregate metrics, split by STANDING/HURDLE context.
Phase G: separately reports RAW_DETECTOR_CEILING vs SELECTOR_CONDITIONAL_ACCURACY.
"""
import json, sys, os
import numpy as np

sys.path.insert(0, os.path.expanduser("~/dive-analyser/experiments/landmark_pilot"))
from proposer_event_logic_v2_1 import classify_context as _classify_context

ANNOT_DIR = "docs/science/localization_annotations_v1/DEVELOPMENT_DESIGN"
V1_DIR = "experiments/landmark_pilot/runs/target_selection_v1"
V2_DIR = "experiments/landmark_pilot/runs/target_selection_v2"
PHASES = ["takeoff", "apex", "water_contact"]
STATIC_LOCK_STD_THRESHOLD = 0.01

DIVE_CODE = {
    133: "301B", 311: "401C", 524: "103B", 676: "301A", 1040: "102C",
    2169: "101B", 2341: "101B", 2387: "5411C", 2541: "5111B", 2555: "5132D",
    2625: "103B", 2680: "010C",
}
DIVE_CONTEXT = {did: _classify_context(code) for did, code in DIVE_CODE.items() if code}
DIVE_CONTEXT[2341] = _classify_context("101B")  # hurdle
DIVE_CONTEXT[2541] = _classify_context("5111B")  # hurdle

def iou_xyxy(a, b):
    ax1,ay1,ax2,ay2 = a; bx1,by1,bx2,by2 = b
    ix1,iy1,ix2,iy2 = max(ax1,bx1),max(ay1,by1),min(ax2,bx2),min(ay2,by2)
    iw,ih = max(0,ix2-ix1),max(0,iy2-iy1)
    inter = iw*ih
    ua,ub = max(0,ax2-ax1)*max(0,ay2-ay1),max(0,bx2-bx1)*max(0,by2-by1)
    return inter/(ua+ub-inter) if (ua+ub-inter)>0 else 0.0

def center(box):
    return ((box[0]+box[2])/2,(box[1]+box[3])/2)

def eval_dive_selector(dive_id, sel_name, sel_path):
    if not os.path.exists(sel_path):
        return {"status":"MISSING"}
    sel = json.load(open(sel_path))
    points = sel["points"]
    n = len(points)
    cy_vals = [p["selected"]["cy_norm"] for p in points if p["selected"] is not None]
    n_null = sum(1 for p in points if p["selected"] is None)
    coverage = 1.0 - n_null/max(1,n)

    longest_gap_s = 0.0; gap_start = None; gap_end = 0.0
    for p in points:
        if p["selected"] is None:
            if gap_start is None:
                gap_start = p["pts_s"] if p["pts_s"] is not None else p["frame_index"]
            gap_end = p["pts_s"] if p["pts_s"] is not None else p["frame_index"]
        else:
            if gap_start is not None:
                longest_gap_s = max(longest_gap_s, gap_end-gap_start)
                gap_start = None
    if gap_start is not None:
        longest_gap_s = max(longest_gap_s, gap_end-gap_start)

    std_cy = float(np.std(cy_vals)) if len(cy_vals)>1 else 0.0
    near_zero_variance_lock = std_cy < STATIC_LOCK_STD_THRESHOLD

    phase_results = {}
    for phase in PHASES:
        annot_path = f"{ANNOT_DIR}/{dive_id}_{phase}.json"
        if not os.path.exists(annot_path):
            phase_results[phase] = {"available":False}; continue
        annot = json.load(open(annot_path))
        if annot.get("bbox") is None:
            phase_results[phase] = {"available":True,"verdict":"NOT_ANNOTATED"}; continue
        fidx = annot["frame_index"]
        aw,ah = annot["width"],annot["height"]
        gt_bbox_px = annot["bbox"]
        gt_norm = [gt_bbox_px[0]/aw,gt_bbox_px[1]/ah,gt_bbox_px[2]/aw,gt_bbox_px[3]/ah]
        gt_c = center(gt_norm)
        if fidx >= n:
            phase_results[phase] = {"available":True,"verdict":"FRAME_OUT_OF_RANGE"}; continue
        chosen = points[fidx]["selected"]
        if chosen is None:
            phase_results[phase] = {"available":True,"verdict":"NULL_AT_REFERENCE"}; continue
        cx,cy2 = chosen["cx_norm"],chosen["cy_norm"]
        d = ((cx-gt_c[0])**2+(cy2-gt_c[1])**2)**0.5
        chosen_norm = [cx-chosen["bw_norm"]/2,cy2-chosen["bh_norm"]/2,
                       cx+chosen["bw_norm"]/2,cy2+chosen["bh_norm"]/2]
        iou = iou_xyxy(chosen_norm, gt_norm)
        match = (iou>=0.30) or (d<=0.05)
        phase_results[phase] = {
            "available":True,"center_dist_norm":round(d,4),"iou":round(iou,4),
            "conf":round(chosen["conf"],4),
            "verdict":"MATCH" if match else "WRONG_TARGET",
        }

    return {
        "status":"EVALUATED","n_frames":n,"coverage":round(coverage,4),
        "longest_null_gap_s":round(longest_gap_s,3),"std_cy_norm":round(std_cy,5),
        "near_zero_variance_lock":near_zero_variance_lock,"phases":phase_results,
    }

def main():
    os.chdir(os.path.expanduser("~/dive-analyser"))
    dive_ids = sorted(DIVE_CONTEXT.keys())
    report = {}
    selectors = {
        "s0": (V1_DIR, "s0"), "s1": (V1_DIR, "s1"), "s3": (V2_DIR, "s3"),
    }
    for did in dive_ids:
        report[did] = {"context":DIVE_CONTEXT[did],"code":DIVE_CODE.get(did)}
        for sel_name, (sdir, sfx) in selectors.items():
            path = f"{sdir}/{did}_{sfx}.json"
            report[did][sel_name] = eval_dive_selector(did, sel_name, path)

    # Phase G: raw ceiling vs conditional accuracy
    # Raw ceiling from phase_a (at conf=0.05 as proxy for D3_PROPOSAL_V1)
    ceiling_data = json.load(open(f"{V2_DIR}/phase_a_threshold_sweep.json"))
    ceiling_at_0_05 = ceiling_data["conf_0.05"]
    ceiling_at_0_005 = ceiling_data["conf_0.005"]

    # Aggregate per selector, split by context
    agg = {}
    for sel_name in selectors:
        agg[sel_name] = {}
        for ctx in ["STANDING","HURDLE","ALL"]:
            rows = [report[d][sel_name] for d in dive_ids
                    if report[d][sel_name].get("status")=="EVALUATED"
                    and (ctx=="ALL" or report[d]["context"]==ctx)]
            if not rows:
                agg[sel_name][ctx] = {"n_dives":0}; continue
            n_dives = len(rows)
            correct = sum(1 for r in rows for p in r["phases"].values()
                          if p.get("verdict")=="MATCH")
            avail = sum(1 for r in rows for p in r["phases"].values()
                        if p.get("available") and p.get("verdict") not in ("NOT_ANNOTATED",))
            null_ref = sum(1 for r in rows for p in r["phases"].values()
                           if p.get("verdict")=="NULL_AT_REFERENCE")
            wrong = sum(1 for r in rows for p in r["phases"].values()
                        if p.get("verdict")=="WRONG_TARGET")
            static_lock_n = sum(1 for r in rows if r["near_zero_variance_lock"])
            mean_cov = float(np.mean([r["coverage"] for r in rows]))
            agg[sel_name][ctx] = {
                "n_dives":n_dives,
                "correct_selection_rate":round(correct/max(1,avail),4),
                "n_correct":correct,"n_available":avail,
                "n_null_at_reference":null_ref,"n_wrong_target":wrong,
                "near_zero_variance_lock_rate":round(static_lock_n/n_dives,4),
                "mean_target_coverage":round(mean_cov,4),
            }

    # Phase G decomposition: raw ceiling vs conditional accuracy
    # Use phase_c recall data (at conf=0.05, the D3_PROPOSAL_V1)
    phase_c = json.load(open(f"{V1_DIR}/phase_c_candidate_recall.json"))
    frames_with_candidate = sum(
        1 for d in phase_c["dives"].values()
        for p in d.get("phases",{}).values()
        if p.get("verdict") in ("TARGET_DETECTED_BUT_NOT_SELECTED","TARGET_SELECTED_CORRECTLY")
    )
    frames_evaluable_pc = sum(
        1 for d in phase_c["dives"].values()
        for p in d.get("phases",{}).values()
        if p.get("verdict") not in (None,"NOT_ANNOTATED",)
        and p.get("available",False)
    )

    # Conditional accuracy: given candidate exists, did S3 select it?
    cond_correct_s3 = 0; cond_total_s3 = 0
    for did in dive_ids:
        dive_pc = phase_c["dives"].get(str(did),{})
        if not dive_pc or dive_pc.get("status")=="RAW_MISSING": continue
        dive_s3 = report[did]["s3"]
        if dive_s3.get("status")!="EVALUATED": continue
        for phase in PHASES:
            pc_phase = dive_pc.get("phases",{}).get(phase,{})
            if pc_phase.get("verdict") in ("TARGET_DETECTED_BUT_NOT_SELECTED","TARGET_SELECTED_CORRECTLY"):
                cond_total_s3 += 1
                s3_phase = dive_s3["phases"].get(phase,{})
                if s3_phase.get("verdict")=="MATCH":
                    cond_correct_s3 += 1

    phase_g = {
        "raw_detector_ceiling": {
            "at_conf_0_05": round(frames_with_candidate/max(1,frames_evaluable_pc),4),
            "n_candidate_present": frames_with_candidate,
            "n_evaluable": frames_evaluable_pc,
            "at_conf_0_005": ceiling_at_0_005["summary"]["raw_target_recall"],
            "note": "Includes ambiguous frames; conf=0.005 uses partial data (full-video low-conf inference not run for all dives, only 2541 miss frames)"
        },
        "S3_conditional_accuracy": {
            "given_candidate_exists": round(cond_correct_s3/max(1,cond_total_s3),4),
            "n_correct_given_exists": cond_correct_s3,
            "n_with_candidate": cond_total_s3,
        },
        "S3_overall_correct_rate": agg["s3"]["ALL"].get("correct_selection_rate"),
    }

    # Also compute conditional for S0 and S1 for comparison
    for sel_name in ["s0","s1"]:
        cc=0; ct=0
        for did in dive_ids:
            dive_pc = phase_c["dives"].get(str(did),{})
            if not dive_pc or dive_pc.get("status")=="RAW_MISSING": continue
            dive_sel = report[did][sel_name]
            if dive_sel.get("status")!="EVALUATED": continue
            for phase in PHASES:
                pc_phase = dive_pc.get("phases",{}).get(phase,{})
                if pc_phase.get("verdict") in ("TARGET_DETECTED_BUT_NOT_SELECTED","TARGET_SELECTED_CORRECTLY"):
                    ct+=1
                    sel_phase = dive_sel["phases"].get(phase,{})
                    if sel_phase.get("verdict")=="MATCH":
                        cc+=1
        phase_g[f"{sel_name}_conditional_accuracy"] = {
            "given_candidate_exists":round(cc/max(1,ct),4),"n":ct,"n_correct":cc
        }

    out = {
        "phase_g_raw_ceiling_vs_conditional": phase_g,
        "aggregate": agg,
        "per_dive": report,
    }
    out_path = f"{V2_DIR}/phase_h_selector_v2_comparison.json"
    json.dump(out, open(out_path,"w"), indent=1)
    print(json.dumps({"phase_g": phase_g, "aggregate": agg}, indent=2))
    print(f"\nWritten: {out_path}")

if __name__ == "__main__":
    main()
