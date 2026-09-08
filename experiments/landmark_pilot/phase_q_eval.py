#!/usr/bin/env python3
"""Phase Q/Q1 -- DEVELOPMENT Event Logic V2.1/V2.2 re-evaluation on the S1-selected,
gate-clean DEVELOPMENT trajectories (target selection repaired this cycle).

Clean = every AVAILABLE reference-frame verdict for S1 is MATCH (no material wrong-
target lock at any checkpoint that was annotated), per
experiments/landmark_pilot/runs/target_selection_v1/phase_j_selector_comparison.json.
NOT tuned: V2.1 and V2.2 (S1_BODY_SCALE variant) run with their frozen params,
unchanged.
"""
import json, sys, os, yaml

sys.path.insert(0, "experiments/landmark_pilot")
from proposer_event_logic_v2_1 import propose_events as propose_v21, PARAMS_E1, classify_context
from proposer_event_logic_v2_2 import propose_events_s1_body_scale, PARAMS_S1

RAW_DIR = "experiments/landmark_pilot/runs/target_selection_v1"
GT_YAML_DIR = "docs/science/pilot_annotations_v2/DEVELOPMENT_DESIGN"

DIVE_CODE = {
    133: "301B", 311: "401C", 524: "103B", 676: "301A", 1040: "102C",
    2169: "101B", 2341: "101B", 2387: "5411C", 2541: "5111B", 2555: "5132D",
    2625: "103B", 2680: "010C",
}

comparison = json.load(open(f"{RAW_DIR}/phase_j_selector_comparison.json"))
per_dive = comparison["per_dive"]

CLEAN = []
for did_str, rec in per_dive.items():
    did = int(did_str)
    s1 = rec.get("s1", {})
    if s1.get("status") != "EVALUATED":
        continue
    phases = s1.get("phases", {})
    avail = [p for p in phases.values() if p.get("available") and p.get("verdict") not in ("NOT_ANNOTATED",)]
    if not avail:
        continue
    if all(p.get("verdict") == "MATCH" for p in avail):
        CLEAN.append(did)

print("CLEAN dives (S1, no material wrong-target lock at any available reference):", CLEAN)
print("contexts:", {d: classify_context(DIVE_CODE[d]) for d in CLEAN})

results = []
for did in CLEAN:
    traj = json.load(open(f"{RAW_DIR}/{did}_s1.json"))
    gt = yaml.safe_load(open(f"{GT_YAML_DIR}/dive_{did}.yaml"))["landmarks"]
    pts_arr = [p["pts_s"] for p in traj["points"]]
    y_arr = [p["selected"]["cy_norm"] if p["selected"] else None for p in traj["points"]]
    bh_arr = [p["selected"]["bh_norm"] if p["selected"] else None for p in traj["points"]]
    conf_arr = [p["selected"]["conf"] if p["selected"] else None for p in traj["points"]]
    code = DIVE_CODE[did]
    ctx = classify_context(code)

    v21 = propose_v21(y_arr, pts_arr, conf_arr, code, PARAMS_E1)
    v22 = propose_events_s1_body_scale(y_arr, bh_arr, pts_arr, conf_arr, code, PARAMS_S1)

    def err(landmark, key_t):
        g = gt.get(landmark)
        if g is None:
            return None, None
        gt_t = g.get("timestamp_seconds")
        pred_t = key_t
        if gt_t is None or pred_t is None:
            return gt_t, None
        return gt_t, round(pred_t - gt_t, 4)

    gt_to, v21_to_err = err("takeoff", v21["takeoff_t"])
    gt_ap, v21_ap_err = err("apex", v21["apex_t"])
    gt_wc, v21_wc_err = err("water_contact", v21["water_contact_t"])
    _, v22_to_err = err("takeoff", v22["takeoff_t"])
    _, v22_ap_err = err("apex", v22["apex_t"])
    _, v22_wc_err = err("water_contact", v22["water_contact_t"])

    results.append({
        "dive_id": did, "dive_code": code, "context": ctx,
        "gt": {"takeoff": gt_to, "apex": gt_ap, "water_contact": gt_wc},
        "v21": {"takeoff_t": v21["takeoff_t"], "apex_t": v21["apex_t"], "wc_t": v21["water_contact_t"],
                "err_takeoff": v21_to_err, "err_apex": v21_ap_err, "err_wc": v21_wc_err,
                "confident": v21["confident"]},
        "v22_s1_body_scale": {"takeoff_t": v22["takeoff_t"], "apex_t": v22["apex_t"], "wc_t": v22["water_contact_t"],
                              "err_takeoff": v22_to_err, "err_apex": v22_ap_err, "err_wc": v22_wc_err},
    })

for r in results:
    print(json.dumps(r, indent=1))

def summarize(key, subkey):
    vals = [abs(r[key][subkey]) for r in results if r[key][subkey] is not None]
    return {"n": len(vals), "median": sorted(vals)[len(vals)//2] if vals else None,
            "values": vals}

summary = {
    "n_clean": len(results),
    "n_hurdle": sum(1 for r in results if r["context"] == "HURDLE"),
    "n_standing": sum(1 for r in results if r["context"] == "STANDING"),
    "v21": {k: summarize("v21", f"err_{k}") for k in ("takeoff", "apex", "wc")},
    "v22_s1_body_scale": {k: summarize("v22_s1_body_scale", f"err_{k}") for k in ("takeoff", "apex", "wc")},
}
print("SUMMARY:", json.dumps(summary, indent=1))

out = {"clean_dives": results, "summary": summary}
json.dump(out, open(f"{RAW_DIR}/phase_q_development_event_logic_reeval.json", "w"), indent=1)
