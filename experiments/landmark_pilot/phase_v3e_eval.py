#!/usr/bin/env python3
"""Phase K — DEVELOPMENT evaluation: V3-D0 vs V3-E0 on identical trajectories.

Runs both proposers on exactly the same arrays from the two frozen trajectory
caches (DEV_HURDLE_TRAJ_CACHE_V2.json HURDLE 7 dives; STANDING_TRAJ_CACHE_V2.json
4 dives). GT event times are used ONLY for error reporting — never as inputs.

Outputs:
  - per-dive HURDLE table (raw, every dive, incl. 2353 flagged drill) and
    STANDING table: predicted to/apex/wc times + absolute errors vs GT;
  - catastrophic count (to_err > 2.5s) and complete-triplet count;
  - K2 protection: assert STANDING results byte-identical V3-D0 vs V3-E0;
  - freeze_gate assessment block covering the Phase L criteria;
  - v3_e1 gate decision (T3).

Output file: docs/science/V3E_DEVELOPMENT_COMPARISON_V1.json

Usage: .venv/bin/python experiments/landmark_pilot/phase_v3e_eval.py
"""

import sys, json, hashlib, datetime
from pathlib import Path

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))

from proposer_event_logic_v3_d0 import propose_events_v3d0, PARAMS_V3D0
from proposer_event_logic_v3_e0 import propose_events_v3e0, PARAMS_V3E0
import build_hurdle_traj_cache_v2 as T1

OUT_PATH    = BASE / "docs/science/V3E_DEVELOPMENT_COMPARISON_V1.json"
HURDLE_CACHE = BASE / "docs/science/DEV_HURDLE_TRAJ_CACHE_V2.json"
STANDING_CACHE = BASE / "docs/science/STANDING_TRAJ_CACHE_V2.json"
BASELINE_DOC   = BASE / "docs/science/V3D0_HURDLE_CORPUS_BASELINE_V1.json"
BOARD_AUDIT    = BASE / "docs/science/BOARD_REFERENCE_AUDIT_V1.json"
TWOD_AUDIT     = BASE / "docs/science/TWOD_APPROACH_AUDIT_V1.json"

CATASTROPHIC_TO_ERR_S = 2.5
FM1_DIVE = "311"
FM1_WC_ERR_MAX_S = 0.1
WC_REGRESSION_MAX_S = 0.25   # terminal-WC stability tolerance


def sha256_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def err(pred_t, gt_t):
    if pred_t is None or gt_t is None:
        return None
    return round(abs(pred_t - gt_t), 4)


def run_variant(fn, params, y, pts, conf, code):
    return fn(y, pts, conf, code, params)


def main():
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    hc = json.load(open(HURDLE_CACHE))
    sc = json.load(open(STANDING_CACHE))
    baseline = json.load(open(BASELINE_DOC))

    # ── HURDLE corpus ─────────────────────────────────────────────────────────
    hurdle = {}
    for spec in T1.DIVES:
        did = spec["id"]
        entry = hc["per_dive"][did]
        y, pts, conf = T1.traj_arrays(entry["frames"])
        gt = entry["gt"]          # error reporting only
        r_d0 = run_variant(propose_events_v3d0, PARAMS_V3D0, y, pts, conf,
                           entry["code"])
        r_e0 = run_variant(propose_events_v3e0, PARAMS_V3E0, y, pts, conf,
                           entry["code"])

        def pack(r, variant):
            return {
                "predicted": {
                    "prep_end_t": r["prep_end_t"],
                    "takeoff_t":  r["takeoff_t"],
                    "apex_t":     r["apex_t"],
                    "water_contact_t": r["water_contact_t"],
                },
                "errors": {
                    "to_err":  err(r["takeoff_t"], gt["takeoff"]),
                    "apex_err": err(r["apex_t"], gt["apex"]),
                    "wc_err":  err(r["water_contact_t"], gt["water_contact"]),
                },
                "complete_triplet": all(
                    r[k] is not None for k in
                    ("takeoff_t", "apex_t", "water_contact_t")),
                "coverage": r["coverage"],
                **({"board_ref": r["board_ref"],
                    "board_ref_mode": r["board_ref_mode"],
                    "board_ref_n_support": r["board_ref_n_support"]}
                   if variant == "V3E0" else {}),
            }

        doc = baseline["hurdle_results"].get(did, {})
        d0_doc = doc.get("errors", {}).get("to_err")
        d0_repro = (d0_doc is not None and
                    abs(pack(r_d0, "V3D0")["errors"]["to_err"] - d0_doc) <= 5e-4)

        hurdle[did] = {
            "code": entry["code"],
            "drill": bool(entry.get("drill", False)),
            "gt": gt,
            "v3d0": pack(r_d0, "V3D0"),
            "v3e0": pack(r_e0, "V3E0"),
            "v3d0_reproduces_documented_baseline": d0_repro,
            "delta": {
                "to_err": (round(pack(r_e0, "V3E0")["errors"]["to_err"]
                                 - pack(r_d0, "V3D0")["errors"]["to_err"], 4)
                           if pack(r_e0, "V3E0")["errors"]["to_err"] is not None
                           and pack(r_d0, "V3D0")["errors"]["to_err"] is not None
                           else None),
                "behavior_changed": any(
                    pack(r_d0, "V3D0")["predicted"][k] !=
                    pack(r_e0, "V3E0")["predicted"][k]
                    for k in pack(r_d0, "V3D0")["predicted"]),
            },
        }

    # ── STANDING corpus (byte-identity asserted) ─────────────────────────────
    standing = {}
    for spec in T1.STANDING_DIVES:
        did = spec["id"]
        entry = sc["per_dive"][did]
        y, pts, conf = T1.traj_arrays(entry["frames"])
        gt = spec["gt"]           # error reporting only
        r_d0 = run_variant(propose_events_v3d0, PARAMS_V3D0, y, pts, conf,
                           spec["code"])
        r_e0 = run_variant(propose_events_v3e0, PARAMS_V3E0, y, pts, conf,
                           spec["code"])
        # K2 protection: STANDING must be byte-identical between variants.
        for k in ("prep_end_t", "takeoff_t", "apex_t", "water_contact_t"):
            assert r_d0[k] == r_e0[k], (
                f"K2 STANDING regression: dive {did} {k} "
                f"{r_d0[k]} != {r_e0[k]}")
        standing[did] = {
            "code": spec["code"],
            "gt": gt,
            "v3d0": {
                "predicted": {k: r_d0[k] for k in
                              ("prep_end_t", "takeoff_t", "apex_t",
                               "water_contact_t")},
                "errors": {"to_err": err(r_d0["takeoff_t"], gt["takeoff"]),
                           "apex_err": err(r_d0["apex_t"], gt["apex"]),
                           "wc_err": err(r_d0["water_contact_t"],
                                         gt["water_contact"])},
            },
            "v3e0_identical_to_v3d0": True,
        }

    # ── aggregates ───────────────────────────────────────────────────────────
    def cat_count(d0_or_e0):
        n_all = n_nd = 0
        for did, rec in hurdle.items():
            e = rec[d0_or_e0]["errors"]["to_err"]
            if e is not None and e > CATASTROPHIC_TO_ERR_S:
                n_all += 1
                if not rec["drill"]:
                    n_nd += 1
        return {"all": n_all, "non_drill": n_nd}

    def trip_count(d0_or_e0):
        n = sum(1 for rec in hurdle.values() if rec[d0_or_e0]["complete_triplet"])
        return f"{n}/{len(hurdle)}"

    improved_nd = [did for did, rec in hurdle.items()
                   if not rec["drill"]
                   and rec["delta"]["to_err"] is not None
                   and rec["delta"]["to_err"] < -1e-9]
    regressed_nd = [did for did, rec in hurdle.items()
                    if not rec["drill"]
                    and rec["delta"]["to_err"] is not None
                    and rec["delta"]["to_err"] > 1e-9]
    changed = [did for did, rec in hurdle.items() if rec["delta"]["behavior_changed"]]

    wc_regressed_nd = [did for did, rec in hurdle.items()
                       if not rec["drill"]
                       and rec["v3e0"]["errors"]["wc_err"] is not None
                       and rec["v3d0"]["errors"]["wc_err"] is not None
                       and rec["v3e0"]["errors"]["wc_err"]
                       - rec["v3d0"]["errors"]["wc_err"] > WC_REGRESSION_MAX_S]

    fm1_wc_err = standing[FM1_DIVE]["v3d0"]["errors"]["wc_err"]

    # ── freeze gate (Phase L criteria) ────────────────────────────────────────
    criteria = {
        "hurdle_improvement_beyond_single_dive": {
            "pass": len(improved_nd) >= 1 and len(regressed_nd) == 0
                    and len(improved_nd) >= 2,
            "improved_non_drill": improved_nd,
            "regressed_non_drill": regressed_nd,
            "behavior_changed_dives": changed,
            "note": ("Requires generalizable HURDLE improvement (more than one "
                     "dive, no non-drill regression). V3-E0 changes behaviour "
                     "on {0} only and REGRESSES it (V3-D0 1.9947 -> V3-E0 "
                     "{1}); zero dives improved.").format(
                         changed, hurdle["1040"]["v3e0"]["errors"]["to_err"])
                    if changed == ["1040"] else
                    f"improved={improved_nd} regressed={regressed_nd}",
        },
        "no_standing_regression": {
            "pass": all(rec["v3e0_identical_to_v3d0"] for rec in standing.values()),
            "note": "K2 byte-identity assertion passed on all 4 STANDING dives.",
        },
        "fm1_closed": {
            "pass": fm1_wc_err is not None and fm1_wc_err <= FM1_WC_ERR_MAX_S,
            "wc_err": fm1_wc_err,
            "threshold": FM1_WC_ERR_MAX_S,
            "note": f"Dive {FM1_DIVE} wc_err must stay <= {FM1_WC_ERR_MAX_S}s "
                    "(A1+A2 unchanged in V3-E0).",
        },
        "terminal_wc_stable": {
            "pass": len(wc_regressed_nd) == 0,
            "regressed_non_drill": wc_regressed_nd,
            "tolerance_s": WC_REGRESSION_MAX_S,
            "note": "No non-drill HURDLE wc_err may worsen by more than "
                    f"{WC_REGRESSION_MAX_S}s. 1040 wc_err 2.511 -> "
                    f"{hurdle['1040']['v3e0']['errors']['wc_err']}.",
        },
        "mechanism_physically_interpretable": {
            "pass": True,
            "note": "B1r is a physical board level (robust stable-support "
                    "cluster median of raw cy); the gate keeps the D0 "
                    "board-rise invariant semantics.",
        },
        "no_paris_influence": {
            "pass": True,
            "note": "DEVELOPMENT-only derivation; Paris firewall verified "
                    "statically by test_event_logic_v3_e.py (forbidden "
                    "constant set + no reference to the Paris trajectory "
                    "artifact in this eval script).",
        },
    }
    gate_pass = all(c["pass"] for c in criteria.values())

    # ── T3: V3-E1 gate decision ───────────────────────────────────────────────
    # (a) Is there a non-drill HURDLE dive with to_err > 2.0s that is NOT a
    #     V3-D0 failure caused by unrecoverable target corruption?
    #     1040 (5.7463) and 2555 (2.6137): failures driven by target-switch /
    #     oscillation corruption (1040 documented unrecoverable at 360p;
    #     2555 raw cy oscillates 0.2-0.8) -> excluded by (a).
    #     2541: non-diver-plateau type, excluded explicitly (degrade gracefully).
    #     524 (4.7436, unchanged): sub-threshold hurdle + early prep_end ->
    #     condition (a) is arguably met via 524.
    # (b) Does an audit validate a bounded, camera-agnostic end-of-board cue?
    #     TWOD_APPROACH_AUDIT_V1: NO dive qualifies as
    #     APPROACH_END_OBSERVABLE_FROM_2D_TRAJECTORY (2 MIXED, 5 NOT_RELIABLE
    #     verdicts); s(t) is not reliably extractable at 360p. The audit's
    #     terminal-region detections are classifications, not a validated
    #     end-of-board context cue, and 2555 was not audited at all.
    #     BOARD_REFERENCE_AUDIT_V1 validates only the B1r board LEVEL (already
    #     used by V3-E0), not an end-of-board REGION.
    #     -> (b) NOT met; building V3-E1 would require an unvalidated cue.
    v3_e1 = {
        "decision": "NOT_JUSTIFIED_BY_DEVELOPMENT_EVIDENCE",
        "condition_a_resolved_to_err_gt_2s": [
            did for did, rec in hurdle.items()
            if not rec["drill"] and rec["v3e0"]["errors"]["to_err"] is not None
            and rec["v3e0"]["errors"]["to_err"] > 2.0],
        "condition_a_note": (
            "Partially met at most: 2541 excluded by rule (non-diver plateau); "
            "1040 (5.7463) and 2555 (2.6137) are target-corruption-family "
            "failures; only 524 (4.7436, unchanged from V3-D0) is a candidate."),
        "condition_b_note": (
            "NOT met: TWOD_APPROACH_AUDIT_V1 found no dive "
            "APPROACH_END_OBSERVABLE_FROM_2D_TRAJECTORY (Phase H precondition "
            "failed); BOARD_REFERENCE_AUDIT_V1 validates only the B1r board "
            "level. No GT-blind, camera-agnostic end-of-board context cue is "
            "validated for 524/2555; building V3-E1 would require an "
            "unvalidated cue, which the gate forbids."),
        "built": False,
    }

    out = {
        "label": "V3E_DEVELOPMENT_COMPARISON_V1",
        "date": now,
        "variants": {"v3d0": "PARAMS_V3D0", "v3e0": "PARAMS_V3E0"},
        "params_v3e0": PARAMS_V3E0,
        "params_delta_vs_v3d0": {
            k: {"v3d0": PARAMS_V3D0.get(k, "<absent>"),
                "v3e0": PARAMS_V3E0.get(k, "<absent>")}
            for k in sorted(set(PARAMS_V3D0) | set(PARAMS_V3E0))
            if PARAMS_V3D0.get(k, "<absent>") != PARAMS_V3E0.get(k, "<absent>")
        },
        "inputs": {
            "hurdle_cache": str(HURDLE_CACHE.relative_to(BASE)),
            "hurdle_cache_sha256": sha256_file(HURDLE_CACHE),
            "standing_cache": str(STANDING_CACHE.relative_to(BASE)),
            "standing_cache_sha256": sha256_file(STANDING_CACHE),
            "documented_baseline": str(BASELINE_DOC.relative_to(BASE)),
            "documented_baseline_sha256": sha256_file(BASELINE_DOC),
            "board_reference_audit": str(BOARD_AUDIT.relative_to(BASE)),
            "board_reference_audit_sha256": sha256_file(BOARD_AUDIT),
            "twod_approach_audit": str(TWOD_AUDIT.relative_to(BASE)),
            "twod_approach_audit_sha256": sha256_file(TWOD_AUDIT),
        },
        "gt_role": "error reporting only; never a detector input",
        "hurdle_results": hurdle,
        "standing_results": standing,
        "aggregates": {
            "hurdle_catastrophic_to_err_gt_2p5s": {
                "v3d0": cat_count("v3d0"), "v3e0": cat_count("v3e0"),
            },
            "hurdle_complete_triplets": {
                "v3d0": trip_count("v3d0"), "v3e0": trip_count("v3e0"),
            },
            "improved_non_drill_dives": improved_nd,
            "regressed_non_drill_dives": regressed_nd,
            "behavior_changed_dives": changed,
        },
        "k2_standing_identity": "PASS (byte-identical, asserted)",
        "freeze_gate": {
            "criteria": criteria,
            "gate_result": "PASS" if gate_pass else "FAIL",
            "decision": ("DEVELOPMENT_FROZEN_NOT_PRODUCTION" if gate_pass
                         else "MORE_HURDLE_GT_REQUIRED"),
            "note": ("HURDLE evidence remains too small: the B1r reference is "
                     "valid (audit) but the D0 first-valid-crossing semantics "
                     "convert the corrected board level into a LATER false "
                     "acceptance on 1040 (post-water-contact flicker crossing "
                     "at 9.343s, cy_apex=0.1949 < B1r 0.2208). One behavioural "
                     "change on one dive, and it is a regression."),
        },
        "v3_e1": v3_e1,
        "paris_role": "not evaluated here; external read-only evaluation is "
                      "phase_v3e_paris_eval.py (post-freeze-decision)",
    }

    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=1)

    print(f"[saved] {OUT_PATH}")
    print(f"gate_result={out['freeze_gate']['gate_result']} "
          f"decision={out['freeze_gate']['decision']}")
    for did, rec in hurdle.items():
        d0e = rec["v3d0"]["errors"]; e0e = rec["v3e0"]["errors"]
        print(f"  {did:>5} {rec['code']:<6} drill={int(rec['drill'])} "
              f"mode={rec['v3e0']['board_ref_mode']:<19} "
              f"D0 to={d0e['to_err']} E0 to={e0e['to_err']} "
              f"changed={rec['delta']['behavior_changed']}")
    for did, rec in standing.items():
        print(f"  {did:>5} {rec['code']:<6} STANDING identical "
              f"to={rec['v3d0']['errors']['to_err']}")


if __name__ == "__main__":
    main()
