#!/usr/bin/env python3
"""Phase F/G — Event Logic V2.1 and V2.2 real Paris test (corrected).

Reads frozen Paris trajectory from PARIS_FULL_TRAJECTORY_V1.json.
Applies EL V2.1 (propose_events) and EL V2.2 S1 (propose_events_s1_body_scale).
GT: takeoff=3.120s, apex=3.570s, water_contact=4.220s.
"""
import os, sys, json, datetime
import numpy as np

BASE = os.path.expanduser("~/dive-analyser")
sys.path.insert(0, f"{BASE}/experiments/landmark_pilot")

TRAJ_PATH = f"{BASE}/docs/science/PARIS_FULL_TRAJECTORY_V1.json"
RESULTS_DIR = f"{BASE}/docs/science"

GT = {"takeoff_s": 3.120, "apex_s": 3.570, "water_contact_s": 4.220}
DIVE_CODE = "5122D"

print("Phase F/G — Event Logic Real Test on Paris Trajectory")
print("="*60)

if not os.path.exists(TRAJ_PATH):
    print(f"ERROR: {TRAJ_PATH} not found. Phase D must complete first.")
    sys.exit(1)

traj_data = json.load(open(TRAJ_PATH))
gate = traj_data.get("trajectory_gate", "UNKNOWN")
print(f"Trajectory gate: {gate}")

if gate != "TRAJECTORY_INPUT_PASS":
    print(f"\nTrajectory gate is {gate}. Skipping EL evaluation.")
    out = {
        "label": "PARIS_EVENT_LOGIC_REAL_TEST_V1",
        "date": datetime.date.today().isoformat(),
        "trajectory_gate": gate,
        "status": "SKIPPED_PERCEPTION_FAIL",
        "note": "EL evaluation requires TRAJECTORY_INPUT_PASS.",
    }
    with open(f"{RESULTS_DIR}/PARIS_EVENT_LOGIC_REAL_TEST_V1.json", "w") as f:
        json.dump(out, f, indent=2)
    sys.exit(0)

# Build input arrays from trajectory
traj = traj_data["trajectory"]
# Include all frames (None for missing cy_norm)
pts_arr = [t["pts_s"] for t in traj]
y_arr   = [t.get("selected_cy_norm") for t in traj]
bh_arr  = [t.get("selected_bbox_h_norm") for t in traj]
conf_arr= [t.get("selected_conf") if t.get("selected_conf") is not None else 0.0 for t in traj]

print(f"Trajectory: {len(pts_arr)} frames, t={pts_arr[0]:.2f}–{pts_arr[-1]:.2f}s")
n_valid = sum(1 for y in y_arr if y is not None)
print(f"Non-None cy_norm: {n_valid}/{len(pts_arr)} = {n_valid/len(pts_arr):.1%}")

# ── Event Logic V2.1 ──────────────────────────────────────────────────────────
print("\n── Phase F: EL V2.1 ──")
from proposer_event_logic_v2_1 import propose_events, PARAMS_E1, classify_context

context = classify_context(DIVE_CODE)
print(f"  Context: {context}")

try:
    v21 = propose_events(y_arr, pts_arr, conf_arr, DIVE_CODE, PARAMS_E1)
    v21_takeoff = v21.get("takeoff_t")
    v21_apex    = v21.get("apex_t")
    v21_wc      = v21.get("water_contact_t")
    v21_prep_end= v21.get("prep_end_t")
    v21_coverage= v21.get("coverage", 0)
    v21_context = v21.get("context", "?")

    def fmt(pred, gt):
        if pred is None: return f"NOT_FOUND (GT={gt}s)"
        return f"{pred:.3f}s  err={pred-gt:+.3f}s  |err|={abs(pred-gt):.3f}s"

    print(f"  prep_end:    {v21_prep_end}")
    print(f"  takeoff:     {fmt(v21_takeoff, GT['takeoff_s'])}")
    print(f"  apex:        {fmt(v21_apex, GT['apex_s'])}")
    print(f"  wc:          {fmt(v21_wc, GT['water_contact_s'])}")
    print(f"  coverage:    {v21_coverage:.1%}")
    # Trace state transitions
    for key in ["prep_end_idx","takeoff_idx","apex_idx","water_contact_idx"]:
        idx = v21.get(key)
        if idx is not None:
            print(f"  {key}: frame {idx} @ t={pts_arr[idx]:.3f}s")
except Exception as e:
    import traceback; traceback.print_exc()
    v21 = {}; v21_takeoff = v21_apex = v21_wc = None; v21_coverage = 0

# ── Event Logic V2.2 ──────────────────────────────────────────────────────────
print("\n── Phase G: EL V2.2 (S1_BODY_SCALE) ──")
from proposer_event_logic_v2_2 import propose_events_s1_body_scale, PARAMS_S1

try:
    v22 = propose_events_s1_body_scale(y_arr, bh_arr, pts_arr, conf_arr, DIVE_CODE, PARAMS_S1)
    v22_takeoff = v22.get("takeoff_t")
    v22_apex    = v22.get("apex_t")
    v22_wc      = v22.get("water_contact_t")
    v22_ref_h   = v22.get("ref_bbox_h_norm")
    v22_coverage= v22.get("coverage", 0)

    print(f"  ref_bbox_h_norm: {v22_ref_h}")
    print(f"  takeoff:     {fmt(v22_takeoff, GT['takeoff_s'])}")
    print(f"  apex:        {fmt(v22_apex, GT['apex_s'])}")
    print(f"  wc:          {fmt(v22_wc, GT['water_contact_s'])}")
    print(f"  coverage:    {v22_coverage:.1%}")
except Exception as e:
    import traceback; traceback.print_exc()
    v22 = {}; v22_takeoff = v22_apex = v22_wc = None; v22_coverage = 0

# ── Phase H: Comparison ────────────────────────────────────────────────────────
print("\n── Phase H: V2.1 vs V2.2 comparison ──")

def ae(p, g): return abs(p-g) if p is not None else None

v21_errs = [ae(v21_takeoff, GT["takeoff_s"]), ae(v21_apex, GT["apex_s"]), ae(v21_wc, GT["water_contact_s"])]
v22_errs = [ae(v22_takeoff, GT["takeoff_s"]), ae(v22_apex, GT["apex_s"]), ae(v22_wc, GT["water_contact_s"])]

v21_complete = all(e is not None for e in v21_errs)
v22_complete = all(e is not None for e in v22_errs)
v21_sum = sum(e for e in v21_errs if e is not None)
v22_sum = sum(e for e in v22_errs if e is not None)

print(f"  V2.1: takeoff={v21_errs[0]}, apex={v21_errs[1]}, wc={v21_errs[2]} | sum={v21_sum:.3f}s | complete={v21_complete}")
print(f"  V2.2: takeoff={v22_errs[0]}, apex={v22_errs[1]}, wc={v22_errs[2]} | sum={v22_sum:.3f}s | complete={v22_complete}")

if v21_complete and v22_complete:
    comparison = "V2_2_BETTER" if v22_sum < v21_sum-0.05 else ("V2_1_BETTER" if v21_sum < v22_sum-0.05 else "EQUIVALENT")
elif v21_complete: comparison = "V2_1_BETTER"
elif v22_complete: comparison = "V2_2_BETTER"
else: comparison = "BOTH_FAIL"
print(f"  Comparison (Paris only): {comparison}")
print(f"  NOTE: Paris cannot choose EL parameters — development evidence is primary.")

out = {
    "label": "PARIS_EVENT_LOGIC_REAL_TEST_V1",
    "date": datetime.date.today().isoformat(),
    "dive_code": DIVE_CODE,
    "paris_gt": GT,
    "trajectory_gate": gate,
    "n_trajectory_frames": len(pts_arr),
    "n_valid_cy_norm": n_valid,
    "V2_1": {
        "context": v21.get("context"),
        "prep_end_t": v21.get("prep_end_t"),
        "takeoff_t": v21_takeoff,
        "apex_t": v21_apex,
        "water_contact_t": v21_wc,
        "takeoff_err_s": v21_errs[0],
        "apex_err_s": v21_errs[1],
        "wc_err_s": v21_errs[2],
        "total_abs_err_s": round(v21_sum,4),
        "complete": v21_complete,
        "coverage": v21_coverage,
    },
    "V2_2": {
        "context": v22.get("context"),
        "ref_bbox_h_norm": v22.get("ref_bbox_h_norm"),
        "takeoff_t": v22_takeoff,
        "apex_t": v22_apex,
        "water_contact_t": v22_wc,
        "takeoff_err_s": v22_errs[0],
        "apex_err_s": v22_errs[1],
        "wc_err_s": v22_errs[2],
        "total_abs_err_s": round(v22_sum,4),
        "complete": v22_complete,
        "coverage": v22_coverage,
    },
    "paris_comparison": comparison,
    "note": "Paris is external evaluation only. EL parameter selection requires DEVELOPMENT evidence.",
}
with open(f"{RESULTS_DIR}/PARIS_EVENT_LOGIC_REAL_TEST_V1.json", "w") as f:
    json.dump(out, f, indent=2)
print(f"\nSaved: {RESULTS_DIR}/PARIS_EVENT_LOGIC_REAL_TEST_V1.json")
