#!/usr/bin/env python3
"""Phase N — Paris EXTERNAL evaluation of the V3-E0 candidate (report-only).

Loads docs/science/PARIS_FULL_TRAJECTORY_V2.json trajectory arrays (frozen,
PTS-equivalent) and runs V3-D0 AND V3-E0 on IDENTICAL arrays. Reports
predictions vs the documented Paris GT (takeoff 3.120 / apex 3.570 /
water_contact 4.220) with the internal per-crossing trace (which neg->non-neg
crossing was accepted/rejected and why), prep_end behaviour, board recontact,
and final takeoff/apex/water-contact.

ABSOLUTE RULE: no tuning after seeing Paris. The Paris numbers reported here
must not and do not feed any parameter (the candidate and its parameters are
fully determined by the DEVELOPMENT artifacts; the freeze decision was made
BEFORE this evaluation — see V3E_FREEZE_GATE_FAILED_V1.json /
V3E_DEVELOPMENT_COMPARISON_V1.json). GT is report-only and never an input.

Output: docs/science/PARIS_EXTERNAL_V3E_EVAL_V1.json
        (field paris_role: "EXTERNAL_REPORT_ONLY")

Usage: .venv/bin/python experiments/landmark_pilot/phase_v3e_paris_eval.py
"""

import sys, json, hashlib, datetime
from pathlib import Path

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))

from proposer_event_logic_v3_d0 import propose_events_v3d0, PARAMS_V3D0
from proposer_event_logic_v3_e0 import propose_events_v3e0, PARAMS_V3E0

PARIS_TRAJ  = BASE / "docs/science/PARIS_FULL_TRAJECTORY_V2.json"
OUT_PATH    = BASE / "docs/science/PARIS_EXTERNAL_V3E_EVAL_V1.json"

PARIS_DIVE_CODE = "5122D"
PARIS_GT = {"takeoff": 3.120, "apex": 3.570, "water_contact": 4.220}


def sha256_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def err(pred_t, gt_t):
    if pred_t is None or gt_t is None:
        return None
    return round(abs(pred_t - gt_t), 4)


def main():
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    doc = json.load(open(PARIS_TRAJ))

    # ── identical arrays for both variants (GT-blind construction) ──────────
    traj = doc["trajectory"]
    y_arr    = [f["selected_cy_norm"] for f in traj]
    pts_arr  = [f["pts_s"] for f in traj]
    conf_arr = [f["selected_conf"] if f["selected_conf"] is not None else 0.0
                for f in traj]

    r_d0 = propose_events_v3d0(y_arr, pts_arr, conf_arr, PARIS_DIVE_CODE,
                               PARAMS_V3D0)
    r_e0 = propose_events_v3e0(y_arr, pts_arr, conf_arr, PARIS_DIVE_CODE,
                               PARAMS_V3E0)

    def pack(r):
        return {
            "predicted": {k: r[k] for k in
                          ("prep_end_t", "takeoff_t", "apex_t",
                           "water_contact_t")},
            "errors": {"to_err": err(r["takeoff_t"], PARIS_GT["takeoff"]),
                       "apex_err": err(r["apex_t"], PARIS_GT["apex"]),
                       "wc_err": err(r["water_contact_t"],
                                     PARIS_GT["water_contact"])},
        }

    # ── E0 internal crossing trace (which crossing was accepted/rejected) ───
    trace = r_e0.get("hurdle_trace") or []
    accepted = [t for t in trace if t.get("accepted")]
    board_recontact_t = accepted[0]["t"] if accepted else None

    out = {
        "label": "PARIS_EXTERNAL_V3E_EVAL_V1",
        "paris_role": "EXTERNAL_REPORT_ONLY",
        "date": now,
        "absolute_rule": ("no tuning after seeing Paris; the Paris numbers in "
                          "this artifact never feed any parameter; the V3-E0 "
                          "candidate and its parameters were fully determined "
                          "by DEVELOPMENT artifacts BEFORE this evaluation "
                          "(freeze-decision artifact: "
                          "V3E_FREEZE_GATE_FAILED_V1.json, decision "
                          "MORE_HURDLE_GT_REQUIRED)"),
        "gt": PARIS_GT,
        "gt_role": "report-only error referencing; never an input",
        "input": {
            "file": str(PARIS_TRAJ.relative_to(BASE)),
            "sha256": sha256_file(PARIS_TRAJ),
            "dive_code": PARIS_DIVE_CODE,
            "n_frames": len(traj),
            "pts_span_s": [pts_arr[0], pts_arr[-1]],
            "video_size": doc.get("video_size"),
            "fps": doc.get("fps"),
        },
        "params_used": {
            "v3d0": PARAMS_V3D0,
            "v3e0": PARAMS_V3E0,
            "note": "identical to the DEVELOPMENT-evaluated parameter dicts; "
                    "no Paris-derived value anywhere",
        },
        "approach_progression_note": (
            "Phase H precondition not met (TWOD_APPROACH_AUDIT_V1: no dive "
            "qualifies as APPROACH_END_OBSERVABLE_FROM_2D_TRAJECTORY; s(t) not "
            "reliably extractable at 360p). No 2D approach-progress gate is "
            "used; the Paris pre-hurdle walk dynamics remain a known failure "
            "mode of the D0 first-valid-crossing semantics (documented in "
            "EVENT_LOGIC_V3_D0_FREEZE.json). Report-only observation here."),
        "v3d0": pack(r_d0),
        "v3e0": {
            **pack(r_e0),
            "board_ref": r_e0["board_ref"],
            "board_ref_mode": r_e0["board_ref_mode"],
            "board_ref_n_support": r_e0["board_ref_n_support"],
            "board_recontact_t": board_recontact_t,
            "crossing_trace": [
                {"t": t["t"], "cy_apex": t["cy_apex"],
                 "board_ref": t["board_ref"], "rise_cy": t["rise_cy"],
                 "gate_passed": t["gate_passed"], "accepted": t["accepted"]}
                for t in trace],
            "crossing_trace_summary": (
                f"{len(trace)} neg->non-neg crossings scanned after guard_end; "
                f"{len(accepted)} accepted "
                + (f"(first accepted at t={accepted[0]['t']}s, cy_apex="
                   f"{accepted[0]['cy_apex']:.4f}, rise_cy="
                   f"{accepted[0]['rise_cy']})" if accepted else "")
                + "; the D0 semantics accept the FIRST gate-passing crossing "
                  "and then search sustained negative velocity from the "
                  "recontact, so a pre-hurdle prep-walk rise that passes the "
                  "gate captures the whole downstream chain."),
        },
        "prep_end_behaviour": {
            "v3d0_prep_end_t": r_d0["prep_end_t"],
            "v3e0_prep_end_t": r_e0["prep_end_t"],
            "note": "prep_end is shared V2.1 semantics; identical in both "
                    "variants on the same arrays.",
        },
        "verdict": "report-only; Paris is an external canary and is never "
                   "used for parameter selection (Paris firewall)",
    }

    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=1)
    print(f"[saved] {OUT_PATH}")
    print("V3-D0:", out["v3d0"]["predicted"], out["v3d0"]["errors"])
    print("V3-E0:", out["v3e0"]["predicted"], out["v3e0"]["errors"],
          "mode", out["v3e0"]["board_ref_mode"])
    for t in out["v3e0"]["crossing_trace"]:
        print("   cross t=%s cy_apex=%s ref=%s rise=%s passed=%s accepted=%s"
              % (t["t"], round(t["cy_apex"], 4) if t["cy_apex"] is not None else None,
                 round(t["board_ref"], 4) if t["board_ref"] is not None else None,
                 t["rise_cy"], t["gate_passed"], t["accepted"]))


if __name__ == "__main__":
    main()
