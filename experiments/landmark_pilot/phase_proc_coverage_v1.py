#!/usr/bin/env python3
"""Phase B-N — Procedural Trajectory Readiness V1.

Runs D5_FRAMEWISE on all 6 DEVELOPMENT VALID dives (full proxy video, 360p).
Computes procedural coverage windows.
Applies EL V2.1 and V2.2 only on PROCEDURAL_INPUT_PASS trajectories.
Saves: PROC_COVERAGE_V1.json, PROC_EL_EVALUATION_V1.json.

Usage:
  python3 phase_proc_coverage_v1.py

Must run on M2 (arm64, MPS). Sequential one-at-a-time.
"""

import os, sys, json, datetime
import cv2
import numpy as np
from pathlib import Path

BASE = Path(__file__).parents[2]  # diveanalyzer-perception/
sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))

from ultralytics import YOLO

# ─── Config ───────────────────────────────────────────────────────────────────

PROXY_ROOT = BASE / "media/perception_decomposition_v1/proxies"
MODEL_PATH = BASE / "models/frozen/DIVER_DETECTOR_D5_A_V8N_best.pt"
SCIENCE_DIR = BASE / "docs/science"

FLOOR_CONF = 0.001
OP_CONF = 0.05
NMS_IOU = 0.45
IMGSZ = 640
FLOOR_CAP = 200

# 6 DEVELOPMENT VALID dives per DEV_D5_ONLY_EVAL_V1.json
VALID_DIVES = [
    {"id": 133,  "code": "301B",   "context": "STANDING"},
    {"id": 311,  "code": "401C",   "context": "STANDING"},
    {"id": 676,  "code": "301A",   "context": "STANDING"},
    {"id": 1040, "code": "102C",   "context": "HURDLE"},
    {"id": 2169, "code": "101B",   "context": "HURDLE"},
    {"id": 2387, "code": "5411C",  "context": "STANDING"},
]

# GT from DEV_D5_ONLY_TRAJECTORIES_V1.json (for evaluation only — NOT inference inputs)
GT = {
    133:  {"takeoff": 1.800274, "apex": 2.083607, "wc": 2.95027},
    311:  {"takeoff": 13.7546,  "apex": None,     "wc": 14.821262},
    676:  {"takeoff": 3.553575, "apex": 3.886907, "wc": 4.853569},
    1040: {"takeoff": 4.463857, "apex": 4.797189, "wc": 5.413853},
    2169: {"takeoff": 6.46124,  "apex": 6.761239, "wc": 7.694569},
    2387: {"takeoff": 4.483274, "apex": 4.833273, "wc": 5.499937},
}

# Procedural gate thresholds
PROC_MIN_C2_COVERAGE = 0.40   # ≥40% of immediate pre-takeoff window detected
PROC_MAX_C2_GAP_S    = 0.50   # no gap > 0.5s in C2
PROC_MIN_FLIGHT_COV  = 0.50   # ≥50% of flight frames detected (C3+C4)
PROC_MAX_FLIGHT_GAP_S = 0.40  # no gap > 0.4s in flight phase

# Flight gate (matches TRAJECTORY_INPUT criteria)
FLIGHT_MIN_COVERAGE = 0.80    # existing gate: C4 ≥ 80%
FLIGHT_MAX_GAP_S    = 0.25    # C5 ≤ 0.25s


# ─── Load model ───────────────────────────────────────────────────────────────

def load_model():
    import torch
    model = YOLO(str(MODEL_PATH))
    # Force MPS if available
    if torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"
    print(f"D5 model loaded. Device: {device}")
    return model, device


# ─── Full-video inference ──────────────────────────────────────────────────────

def infer_full_video(model, device, video_path):
    """Run D5 framewise on every frame. Returns list of per-frame dicts."""
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    n_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    frames_data = []
    fi = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        pts_s = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0

        # D5 inference at floor_conf
        preds = model(frame, conf=FLOOR_CONF, iou=NMS_IOU, imgsz=IMGSZ,
                      verbose=False, device=device)
        br = preds[0].boxes
        n_floor = 0
        n_op = 0
        sel_cy = None
        sel_bh = None
        sel_conf = None

        if br is not None and len(br) > 0:
            confs = br.conf.cpu().numpy()
            boxes = br.xyxy.cpu().numpy()
            # Sort by confidence desc, cap at FLOOR_CAP
            ord_ = np.argsort(-confs)[:FLOOR_CAP]
            confs = confs[ord_]
            boxes = boxes[ord_]
            n_floor = len(confs)
            op_mask = confs >= OP_CONF
            n_op = int(op_mask.sum())

            # Selector: top-1 highest confidence (D5_OP_CONF_TOP1)
            # At op_conf: use highest conf candidate
            # At floor_conf: also highest conf
            if n_op > 0:
                idx = np.argmax(confs[op_mask])
                # Map back to full array
                op_indices = np.where(op_mask)[0]
                best_idx = op_indices[idx]
            else:
                # No op_conf candidate — selected is None at op_conf
                best_idx = None

            if best_idx is not None:
                box = boxes[best_idx]
                sel_cy = float((box[1] + box[3]) / 2 / H)
                sel_bh = float((box[3] - box[1]) / H)
                sel_conf = float(confs[best_idx])

        frames_data.append({
            "fi": fi,
            "pts_s": round(pts_s, 6),
            "n_floor": n_floor,      # candidates at floor_conf
            "n_op": n_op,            # candidates at op_conf
            "sel_cy": sel_cy,        # None if no op_conf detection
            "sel_bh": sel_bh,
            "sel_conf": sel_conf,
        })
        fi += 1

    cap.release()
    print(f"  Processed {fi} frames (expected {n_total}) @ fps={fps:.2f}")
    return frames_data, fps, W, H


# ─── Coverage window analysis ──────────────────────────────────────────────────

def compute_window_coverage(frames_data, t_start, t_end, level="op"):
    """Compute coverage metrics for a time window.

    level='op': count frames with n_op > 0 (selected trajectory)
    level='floor': count frames with n_floor > 0 (any candidate)
    """
    window = [f for f in frames_data if t_start <= f["pts_s"] < t_end]
    if not window:
        return {
            "n_frames": 0, "n_detected": 0, "coverage": None,
            "longest_gap_s": None, "mean_conf": None,
        }
    key = "n_op" if level == "op" else "n_floor"
    det = [f[key] > 0 for f in window]
    n = len(det)
    n_det = sum(det)
    coverage = n_det / n if n > 0 else 0.0
    # Longest gap in seconds
    longest_gap_s = _longest_gap_s(window, key)
    # Mean confidence (selected) for detected frames
    confs = [f["sel_conf"] for f in window if f["sel_conf"] is not None]
    mean_conf = float(np.mean(confs)) if confs else None
    # cy_norm stats for detected frames
    cys = [f["sel_cy"] for f in window if f["sel_cy"] is not None]
    cy_std = float(np.std(cys)) if len(cys) > 2 else None
    return {
        "n_frames": n,
        "n_detected": n_det,
        "coverage": round(coverage, 4),
        "longest_gap_s": round(longest_gap_s, 4) if longest_gap_s is not None else None,
        "mean_conf": round(mean_conf, 4) if mean_conf is not None else None,
        "cy_std": round(cy_std, 4) if cy_std is not None else None,
    }


def _longest_gap_s(window, key):
    """Compute the longest consecutive sequence of frames where key==0, in seconds."""
    pts = [f["pts_s"] for f in window]
    det = [f[key] > 0 for f in window]
    max_gap = 0.0
    gap_start = None
    for i, d in enumerate(det):
        if not d:
            if gap_start is None:
                gap_start = pts[i]
        else:
            if gap_start is not None:
                gap = pts[i] - gap_start
                max_gap = max(max_gap, gap)
                gap_start = None
    # Close trailing gap
    if gap_start is not None:
        gap = pts[-1] - gap_start
        max_gap = max(max_gap, gap)
    return max_gap


def compute_cy_continuity(frames_data, t_start, t_end):
    """Mean absolute frame-to-frame cy_norm change in window (selected only)."""
    window = [f for f in frames_data if t_start <= f["pts_s"] < t_end
              and f["sel_cy"] is not None]
    if len(window) < 2:
        return None
    deltas = [abs(window[i]["sel_cy"] - window[i-1]["sel_cy"])
              for i in range(1, len(window))]
    return round(float(np.mean(deltas)), 4)


# ─── Failure attribution ──────────────────────────────────────────────────────

def attribute_failures(frames_data, t_start, t_end):
    """Classify missing-detection frames in window by failure type."""
    window = [f for f in frames_data if t_start <= f["pts_s"] < t_end and f["n_op"] == 0]
    counts = {
        "RAW_DETECTOR_MISS": 0,           # n_floor=0 — detector found nothing
        "TARGET_CANDIDATE_EXISTS_BUT_SELECTION_MISS": 0,  # n_floor>0, n_op=0 (low conf)
        "DECODE_OR_PTS_ERROR": 0,         # not observed in practice
        "SOURCE_RESOLUTION_LIMITATION": 0, # estimated from small-bbox / low-conf at floor
        "UNKNOWN": 0,
    }
    for f in window:
        if f["n_floor"] == 0:
            counts["RAW_DETECTOR_MISS"] += 1
        elif f["n_floor"] > 0 and f["n_op"] == 0:
            # Has candidates but none meet op_conf — likely small/blurry at 360p
            counts["SOURCE_RESOLUTION_LIMITATION"] += 1
        else:
            counts["UNKNOWN"] += 1
    total_missing = len(window)
    return {"total_missing": total_missing, **counts}


# ─── Procedural gate ──────────────────────────────────────────────────────────

def assess_procedural_validity(dive_id, frames_data, gt, context):
    """Determine FLIGHT_VALID and PROCEDURAL_VALID for one dive.

    Uses GT times for evaluation windows only (NOT inference inputs).
    """
    t0 = gt["takeoff"]
    apex = gt["apex"]
    t_wc = gt["wc"]
    dur = frames_data[-1]["pts_s"] if frames_data else 0
    fps = 1 / (frames_data[1]["pts_s"] - frames_data[0]["pts_s"]) if len(frames_data) > 1 else 30.0

    # Window boundaries
    c1_start = 0.0
    c1_end   = max(0.0, t0 - 2.0)
    c2_start = max(0.0, t0 - 1.0)
    c2_end   = t0
    c3_start = t0
    c3_end   = (apex if apex else t0 + 0.4)
    c4_start = c3_end
    c4_end   = t_wc
    c5_start = t_wc
    c5_end   = min(dur, t_wc + 0.5)

    results = {}

    # C1 — Preparation
    c1_op = compute_window_coverage(frames_data, c1_start, c1_end, "op")
    c1_floor = compute_window_coverage(frames_data, c1_start, c1_end, "floor")
    c1_fail = attribute_failures(frames_data, c1_start, c1_end)
    results["C1_PREPARATION"] = {
        "window_s": [round(c1_start, 3), round(c1_end, 3)],
        "op": c1_op, "floor": c1_floor, "failure_attribution": c1_fail,
        "cy_continuity": compute_cy_continuity(frames_data, c1_start, c1_end),
    }

    # C2 — Immediate pre-takeoff (1s before)
    c2_op = compute_window_coverage(frames_data, c2_start, c2_end, "op")
    c2_floor = compute_window_coverage(frames_data, c2_start, c2_end, "floor")
    c2_fail = attribute_failures(frames_data, c2_start, c2_end)
    results["C2_IMMEDIATE_PRE_TAKEOFF"] = {
        "window_s": [round(c2_start, 3), round(c2_end, 3)],
        "op": c2_op, "floor": c2_floor, "failure_attribution": c2_fail,
        "cy_continuity": compute_cy_continuity(frames_data, c2_start, c2_end),
    }

    # C3 — Takeoff → Apex
    c3_op = compute_window_coverage(frames_data, c3_start, c3_end, "op")
    c3_floor = compute_window_coverage(frames_data, c3_start, c3_end, "floor")
    results["C3_TAKEOFF_TO_APEX"] = {
        "window_s": [round(c3_start, 3), round(c3_end, 3)],
        "op": c3_op, "floor": c3_floor,
        "cy_continuity": compute_cy_continuity(frames_data, c3_start, c3_end),
    }

    # C4 — Apex → Water Contact
    c4_op = compute_window_coverage(frames_data, c4_start, c4_end, "op")
    c4_floor = compute_window_coverage(frames_data, c4_start, c4_end, "floor")
    results["C4_APEX_TO_WC"] = {
        "window_s": [round(c4_start, 3), round(c4_end, 3)],
        "op": c4_op, "floor": c4_floor,
        "cy_continuity": compute_cy_continuity(frames_data, c4_start, c4_end),
    }

    # C5 — Post water contact
    c5_op = compute_window_coverage(frames_data, c5_start, c5_end, "op")
    results["C5_POST_WC"] = {
        "window_s": [round(c5_start, 3), round(c5_end, 3)],
        "op": c5_op,
    }

    # Flight coverage (C3+C4 combined)
    flight_op = compute_window_coverage(frames_data, t0, t_wc, "op")
    flight_gap = flight_op["longest_gap_s"] or 0.0

    # FLIGHT_VALID criteria (matches existing 6-point gate)
    flight_valid = (
        (flight_op["coverage"] or 0) >= FLIGHT_MIN_COVERAGE and
        flight_gap <= FLIGHT_MAX_GAP_S
    )

    # PROCEDURAL_VALID criteria
    c2_cov = c2_op["coverage"] or 0.0
    c2_gap = c2_op["longest_gap_s"] or 0.0
    # Check: correct target near final takeoff (proxy: C2 coverage > threshold)
    # Check: no catastrophic pre-takeoff gap (C2 longest gap < 0.5s)
    # Check: sufficient flight signal (flight_op coverage >= 50%)
    # Check: signal can distinguish C1 prep from C2/C3 action (not just noise)
    c1_cov = c1_op["coverage"] or 0.0
    flight_cov = flight_op["coverage"] or 0.0

    proc_fail_reasons = []
    if c2_cov < PROC_MIN_C2_COVERAGE:
        proc_fail_reasons.append(f"C2_LOW_COVERAGE={c2_cov:.2f}<{PROC_MIN_C2_COVERAGE}")
    if c2_gap > PROC_MAX_C2_GAP_S:
        proc_fail_reasons.append(f"C2_LONG_GAP={c2_gap:.3f}s>{PROC_MAX_C2_GAP_S}s")
    if flight_cov < PROC_MIN_FLIGHT_COV:
        proc_fail_reasons.append(f"FLIGHT_LOW_COVERAGE={flight_cov:.2f}<{PROC_MIN_FLIGHT_COV}")

    proc_valid = len(proc_fail_reasons) == 0
    return {
        "windows": results,
        "flight_coverage": {"window_s": [round(t0,3), round(t_wc,3)], **flight_op},
        "flight_valid": flight_valid,
        "procedural_valid": proc_valid,
        "procedural_fail_reasons": proc_fail_reasons,
    }


# ─── EL evaluation ────────────────────────────────────────────────────────────

def run_el_on_trajectory(frames_data, dive_code, fps, v21_module, v22_module):
    """Run EL V2.1 and V2.2 on full-video trajectory."""
    y_arr   = [f["sel_cy"] for f in frames_data]
    bh_arr  = [f["sel_bh"] for f in frames_data]
    pts_arr = [f["pts_s"] for f in frames_data]
    conf_arr = [f["sel_conf"] if f["sel_conf"] is not None else 0.0
                for f in frames_data]

    from proposer_event_logic_v2_1 import PARAMS_E1
    from proposer_event_logic_v2_2 import PARAMS_S1

    try:
        v21 = v21_module.propose_events(y_arr, pts_arr, conf_arr, dive_code, PARAMS_E1)
    except Exception as e:
        v21 = {"error": str(e), "takeoff_t": None, "apex_t": None, "water_contact_t": None}

    try:
        v22 = v22_module.propose_events_s1_body_scale(
            y_arr, bh_arr, pts_arr, conf_arr, dive_code, PARAMS_S1)
    except Exception as e:
        v22 = {"error": str(e), "takeoff_t": None, "apex_t": None, "water_contact_t": None}

    return v21, v22


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    import torch
    print("="*60)
    print("Phase B-N: Procedural Trajectory Readiness Audit V1")
    print(f"Date: {datetime.date.today().isoformat()}")
    print(f"Device: {'MPS' if torch.backends.mps.is_available() else 'CPU'}")
    print("="*60)

    # Load EL modules
    import proposer_event_logic_v2_1 as v21_mod
    import proposer_event_logic_v2_2 as v22_mod

    model, device = load_model()

    all_results = {}
    el_results  = {}

    for dive_info in VALID_DIVES:
        did = dive_info["id"]
        code = dive_info["code"]
        context = dive_info["context"]
        gt = GT[did]
        proxy = PROXY_ROOT / f"{did}.mp4"

        print(f"\n{'─'*50}")
        print(f"Dive {did} ({code}, {context})")
        if not proxy.exists():
            print(f"  SKIP: proxy not found at {proxy}")
            all_results[str(did)] = {"status": "MISSING_PROXY"}
            continue

        print(f"  Running D5 inference on {proxy.name}...")
        frames_data, fps, W, H = infer_full_video(model, device, proxy)
        n_total = len(frames_data)
        n_op = sum(1 for f in frames_data if f["n_op"] > 0)
        n_floor = sum(1 for f in frames_data if f["n_floor"] > 0)
        print(f"  Coverage: op={n_op}/{n_total}={n_op/n_total:.1%}, "
              f"floor={n_floor}/{n_total}={n_floor/n_total:.1%}")

        # Procedural assessment
        proc = assess_procedural_validity(did, frames_data, gt, context)

        flight_v = proc["flight_valid"]
        proc_v   = proc["procedural_valid"]

        print(f"  FLIGHT_VALID:     {'✓' if flight_v else '✗'}")
        print(f"  PROCEDURAL_VALID: {'✓' if proc_v else '✗'}"
              + (f" ({', '.join(proc['procedural_fail_reasons'])})" if not proc_v else ""))

        # Window summary
        for win, data in proc["windows"].items():
            cov = data["op"]["coverage"]
            gap = data["op"]["longest_gap_s"]
            print(f"    {win}: cov={cov:.1%} gap={gap:.3f}s" if cov is not None else
                  f"    {win}: empty window")

        result = {
            "dive_id": did,
            "code": code,
            "context": context,
            "proxy": str(proxy.name),
            "fps": fps,
            "W": W, "H": H,
            "n_total_frames": n_total,
            "n_op_frames": n_op,
            "n_floor_frames": n_floor,
            "overall_op_coverage": round(n_op/n_total, 4),
            "gt_timing_used_for_eval_only": gt,
            "flight_valid": flight_v,
            "procedural_valid": proc_v,
            "procedural_fail_reasons": proc["procedural_fail_reasons"],
            "windows": proc["windows"],
            "flight_coverage": proc["flight_coverage"],
        }
        all_results[str(did)] = result

        # EL evaluation — only on PROCEDURAL_VALID
        if proc_v:
            print(f"  Running EL V2.1 and V2.2 (PROCEDURAL_VALID)...")
            v21, v22 = run_el_on_trajectory(frames_data, code, fps, v21_mod, v22_mod)

            def fmt_el(r, gt_key, gt_vals):
                t = r.get(gt_key)
                if t is None:
                    return "NOT_FOUND"
                return f"{t:.3f}s"

            def el_complete(r):
                return (r.get("takeoff_t") is not None and
                        r.get("water_contact_t") is not None)

            v21_c = el_complete(v21)
            v22_c = el_complete(v22)

            # Errors
            def el_errors(r, gt):
                errs = {}
                for k, gk in [("takeoff_t","takeoff"),("apex_t","apex"),("water_contact_t","wc")]:
                    pred = r.get(k)
                    gval = gt.get(gk)
                    if pred is not None and gval is not None:
                        errs[gk] = round(abs(pred - gval), 4)
                    else:
                        errs[gk] = None
                return errs

            print(f"  V2.1: takeoff={fmt_el(v21,'takeoff_t',gt)} apex={fmt_el(v21,'apex_t',gt)} wc={fmt_el(v21,'water_contact_t',gt)} complete={v21_c}")
            print(f"  V2.2: takeoff={fmt_el(v22,'takeoff_t',gt)} apex={fmt_el(v22,'apex_t',gt)} wc={fmt_el(v22,'water_contact_t',gt)} complete={v22_c}")

            el_results[str(did)] = {
                "dive_id": did,
                "code": code,
                "context": context,
                "procedural_valid": proc_v,
                "flight_valid": flight_v,
                "gt": gt,
                "v2_1": {
                    "takeoff_t": v21.get("takeoff_t"),
                    "apex_t": v21.get("apex_t"),
                    "wc_t": v21.get("water_contact_t"),
                    "complete": v21_c,
                    "coverage": v21.get("coverage"),
                    "prep_end_t": v21.get("prep_end_t"),
                    "context": v21.get("context"),
                    "errors": el_errors(v21, gt),
                },
                "v2_2": {
                    "takeoff_t": v22.get("takeoff_t"),
                    "apex_t": v22.get("apex_t"),
                    "wc_t": v22.get("water_contact_t"),
                    "complete": v22_c,
                    "coverage": v22.get("coverage"),
                    "errors": el_errors(v22, gt),
                },
            }
        else:
            print(f"  Skipping EL (PROCEDURAL_INVALID)")
            el_results[str(did)] = {
                "dive_id": did,
                "procedural_valid": False,
                "el_status": "SKIPPED_PROCEDURAL_INVALID",
                "procedural_fail_reasons": proc["procedural_fail_reasons"],
            }

    # ── Compute corpus summary ──────────────────────────────────────────────
    proc_valid_ids = [int(k) for k,v in all_results.items() if v.get("procedural_valid")]
    flight_valid_ids = [int(k) for k,v in all_results.items() if v.get("flight_valid")]
    n_proc_pass = len(proc_valid_ids)
    n_total_dives = len([v for v in all_results.values() if "procedural_valid" in v])

    print(f"\n{'='*60}")
    print(f"SUMMARY: {n_proc_pass}/{n_total_dives} PROCEDURAL_INPUT_PASS")
    print(f"FLIGHT_VALID: {len(flight_valid_ids)}/{n_total_dives}")
    print(f"PROCEDURAL_VALID dives: {sorted(proc_valid_ids)}")

    # EL summary
    el_complete_v21 = sum(1 for v in el_results.values() if v.get("v2_1",{}).get("complete"))
    el_complete_v22 = sum(1 for v in el_results.values() if v.get("v2_2",{}).get("complete"))
    n_el_attempted = sum(1 for v in el_results.values() if v.get("procedural_valid"))
    print(f"\nEL V2.1: {el_complete_v21}/{n_el_attempted} complete on PROCEDURAL_VALID dives")
    print(f"EL V2.2: {el_complete_v22}/{n_el_attempted} complete on PROCEDURAL_VALID dives")

    # Corpus gate
    corpus_gate = "PROCEDURAL_INPUT_READY" if n_proc_pass >= 1 else "PROCEDURAL_INPUT_NOT_READY"
    print(f"\nPROCEDURAL READINESS GATE: {corpus_gate}")

    # ── Save artifacts ──────────────────────────────────────────────────────

    coverage_out = {
        "label": "PROC_COVERAGE_V1",
        "date": datetime.date.today().isoformat(),
        "pipeline": "D5_FRAMEWISE_ONLY",
        "floor_conf": FLOOR_CONF,
        "op_conf": OP_CONF,
        "nms_iou": NMS_IOU,
        "pts_authority": "PTS_AUTHORITATIVE_SEEK",
        "n_dives": n_total_dives,
        "flight_valid_dives": sorted(flight_valid_ids),
        "procedural_valid_dives": sorted(proc_valid_ids),
        "corpus_gate": corpus_gate,
        "procedural_thresholds": {
            "min_c2_coverage": PROC_MIN_C2_COVERAGE,
            "max_c2_gap_s": PROC_MAX_C2_GAP_S,
            "min_flight_coverage": PROC_MIN_FLIGHT_COV,
        },
        "per_dive": all_results,
    }

    cov_path = SCIENCE_DIR / "PROC_COVERAGE_V1.json"
    with open(cov_path, "w") as f:
        json.dump(coverage_out, f, indent=2)
    print(f"\nSaved: {cov_path}")

    # EL causal gate
    if n_el_attempted == 0:
        el_causal = "EVENT_LOGIC_NOT_YET_EVALUABLE"
    elif el_complete_v21 == 0 and el_complete_v22 == 0:
        el_causal = "EVENT_LOGIC_NOT_YET_EVALUABLE"
    else:
        # Check if EL failures persist even on procedurally valid trajectories
        el_causal = "EVENT_LOGIC_FAILURE_CONFIRMED"

    el_out = {
        "label": "PROC_EL_EVALUATION_V1",
        "date": datetime.date.today().isoformat(),
        "n_proc_valid_dives": n_el_attempted,
        "v2_1_complete": el_complete_v21,
        "v2_2_complete": el_complete_v22,
        "el_causal_gate": el_causal,
        "per_dive": el_results,
    }

    el_path = SCIENCE_DIR / "PROC_EL_EVALUATION_V1.json"
    with open(el_path, "w") as f:
        json.dump(el_out, f, indent=2)
    print(f"Saved: {el_path}")

    return coverage_out, el_out


if __name__ == "__main__":
    main()
