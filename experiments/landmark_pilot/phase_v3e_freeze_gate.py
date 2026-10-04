#!/usr/bin/env python3
"""Phase M — freeze decision writer for the V3-E0 candidate (DEVELOPMENT).

Reads docs/science/V3E_DEVELOPMENT_COMPARISON_V1.json (Phase K) and:
  - if the freeze gate PASSES: writes docs/science/EVENT_LOGIC_V3_E_FREEZE.json
    (status FROZEN / DEVELOPMENT_FROZEN_NOT_PRODUCTION),
  - if the gate FAILS: writes docs/science/V3E_FREEZE_GATE_FAILED_V1.json with
    the failed criteria and the packet decision string
    (MORE_HURDLE_GT_REQUIRED when HURDLE GT evidence remains too small).

This is a DEVELOPMENT freeze decision; production promotion stays pending.
No Paris data is read here (Paris is external, report-only, Phase N).

Usage: .venv/bin/python experiments/landmark_pilot/phase_v3e_freeze_gate.py
"""

import sys, json, hashlib, datetime, subprocess
from pathlib import Path

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))

COMPARISON = BASE / "docs/science/V3E_DEVELOPMENT_COMPARISON_V1.json"
FREEZE_OK  = BASE / "docs/science/EVENT_LOGIC_V3_E_FREEZE.json"
FREEZE_FAIL = BASE / "docs/science/V3E_FREEZE_GATE_FAILED_V1.json"
BOARD_AUDIT = BASE / "docs/science/BOARD_REFERENCE_AUDIT_V1.json"
HURDLE_CACHE = BASE / "docs/science/DEV_HURDLE_TRAJ_CACHE_V2.json"
STANDING_CACHE = BASE / "docs/science/STANDING_TRAJ_CACHE_V2.json"

BASE_COMMIT = "5177924"   # uiux-overhaul-pro-app HEAD at candidate creation


def sha256_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def sha256_file_or_none(p):
    try:
        return sha256_file(p)
    except OSError:
        return None


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    comp = json.load(open(COMPARISON))
    gate = comp["freeze_gate"]
    params = comp["params_v3e0"]

    def head_commit():
        try:
            return subprocess.run(
                ["git", "rev-parse", "--short=7", "HEAD"],
                cwd=BASE, capture_output=True, text=True, check=True
            ).stdout.strip()
        except Exception:
            return None

    def comp_hurdle_proxy(did):
        # proxy sha256 recorded inside the frozen trajectory cache entry
        cache = json.load(open(HURDLE_CACHE))
        return cache["per_dive"][did]["proxy_sha256"]

    common = {
        "date": now.isoformat(),
        "variant": params["variant"],
        "base_commit": BASE_COMMIT,
        "head_commit_at_writing": head_commit(),
        "canonical_sources": {
            "candidate": {
                "file": "experiments/landmark_pilot/proposer_event_logic_v3_e0.py",
                "sha256": sha256_file(BASE / "experiments/landmark_pilot/proposer_event_logic_v3_e0.py"),
            },
            "parent_v3_d0": {
                "file": "experiments/landmark_pilot/proposer_event_logic_v3_d0.py",
                "sha256": sha256_file(BASE / "experiments/landmark_pilot/proposer_event_logic_v3_d0.py"),
                "note": "frozen V3-D0 source (unmodified)",
            },
            "evaluation": {
                "file": "experiments/landmark_pilot/phase_v3e_eval.py",
                "sha256": sha256_file(BASE / "experiments/landmark_pilot/phase_v3e_eval.py"),
            },
            "tests": {
                "file": "experiments/landmark_pilot/test_event_logic_v3_e.py",
                "sha256": sha256_file_or_none(BASE / "experiments/landmark_pilot/test_event_logic_v3_e.py"),
            },
        },
        "pts_authority": "PTS_EQUIVALENT (360p proxies share PTS timestamps "
                         "with HQ originals; Paris trajectory PTS_EQUIVALENT "
                         "per PARIS_FULL_TRAJECTORY_V2.json)",
        "perception_identity": {
            "detector": "D5-A (YOLOv8n)",
            "weights": "DIVER_DETECTOR_D5_A_V8N_best.pt",
            "floor_conf": 0.001,
            "op_conf": 0.05,
            "target_selection": "highest confidence at op_conf threshold",
            "signal_primitive": "cy_norm (bbox center-y / frame height, 202x360 360p proxy)",
            "note": "identical to the V3-D0 frozen perception identity; no "
                    "HQ-derived parameter anywhere in V3-E0",
        },
        "representation": "cy_norm 202x360 360p proxy (frozen D5 recipe)",
        "board_level_semantics": {
            "recipe": "B1r: stable-support cluster = frames [0, prep_end] of "
                      "the RAW cy signal (prep_end from _find_preparation_end "
                      "on the V3 smoothed signal) with valid cy, conf >= 0.10 "
                      "and |vel_raw| <= 0.02; B1r = median of cluster after "
                      "rejecting |x - median| > 1.5 * MAD (recompute median). "
                      "Verbatim BOARD_REFERENCE_AUDIT_V1.json cluster_constants "
                      "(vel_max=0.02, conf_min=0.10, mad_k=1.5).",
            "fallback_rule": "if the cluster is empty or n < "
                             "board_ref_min_support_n (=5), fall back to the "
                             "historical V3-D0 y_prep (smoothed cy at prep_end) "
                             "and flag board_ref_mode=HISTORICAL_FALLBACK "
                             "(2541-type non-diver low-conf plateaus degrade "
                             "gracefully to exact V3-D0 behaviour).",
            "support_justification": "1040 is the smallest credible cluster on "
                                     "a scored audit dive (n_samples=5) and its "
                                     "B1r matched the dominant raw level within "
                                     "0.0003.",
        },
        "parameters": params,
        "development_corpus_fingerprint": {
            "hurdle_dives": ["1040", "2169", "524", "2341", "2353", "2541",
                             "2555"],
            "hurdle_proxy_sha256": {
                did: comp_hurdle_proxy(did)
                for did in ("1040", "2169", "524", "2341", "2353", "2541",
                            "2555")
            },
            "standing_dives": ["133", "311", "676", "2387"],
            "standing_cache_sha256": sha256_file(STANDING_CACHE),
            "hurdle_cache_sha256": sha256_file(HURDLE_CACHE),
            "gt_role": "error reporting only; never a detector input",
        },
        "tests_summary": {
            "file": "experiments/landmark_pilot/test_event_logic_v3_e.py",
            "note": "self-runner suite (T6); counts recorded at gate time by "
                    "the test run output",
        },
        "paris_external_test": {
            "status": "READ_ONLY (post-freeze-decision evaluation only)",
            "artifact": "docs/science/PARIS_EXTERNAL_V3E_EVAL_V1.json",
            "note": "Paris GT (3.120/3.570/4.220) is report-only and never an "
                    "input; no tuning after seeing Paris.",
        },
    }

    if gate["gate_result"] == "PASS":
        out = dict(common)
        out.update({
            "label": "EVENT_LOGIC_V3_E_FREEZE",
            "status": "FROZEN",
            "freeze_gate": gate,
            "promotion_status": "DEVELOPMENT_FROZEN_NOT_PRODUCTION",
            "promotion_note": "production promotion pending Phase N Paris "
                              "external (report-only) evaluation",
        })
        path = FREEZE_OK
    else:
        failed = {k: v for k, v in gate["criteria"].items() if not v["pass"]}
        out = {
            "label": "V3E_FREEZE_GATE_FAILED_V1",
            "status": "GATE_FAILED",
            "date": now.isoformat(),
            "variant": params["variant"],
            "base_commit": BASE_COMMIT,
            "failed_criteria": failed,
            "passed_criteria": {k: v for k, v in gate["criteria"].items()
                                if v["pass"]},
            "decision": gate["decision"],
            "decision_note": (
                "HURDLE DEVELOPMENT evidence remains too small: V3-E0 changes "
                "behaviour on exactly one dive (1040) and the change is a "
                "regression (to_err 1.9947 -> 5.7463: the corrected B1r board "
                "level lets a post-water-contact flicker crossing at 9.343s, "
                "cy_apex=0.1949 < B1r=0.2208, pass the D0 board-rise gate). "
                "Zero HURDLE dives improved. Additional HURDLE GT dives are "
                "required before any board-reference semantic can be frozen."),
            "v3_e1": comp["v3_e1"],
            "canonical_sources": common["canonical_sources"],
            "perception_identity": common["perception_identity"],
            "parameters": params,
            "development_corpus_fingerprint": common["development_corpus_fingerprint"],
            "comparison_artifact": {
                "file": str(COMPARISON.relative_to(BASE)),
                "sha256": sha256_file(COMPARISON),
            },
            "next_steps": [
                "Phase N Paris external evaluation still executed READ-ONLY on "
                "the V3-E0 candidate for the record "
                "(docs/science/PARIS_EXTERNAL_V3E_EVAL_V1.json);",
                "collect more HURDLE GT dives (MORE_HURDLE_GT_REQUIRED) before "
                "re-attempting any board-reference freeze;",
                "candidate default remains frozen V3-D0 (EVENT_LOGIC_V3_D0_FREEZE.json).",
            ],
        }
        path = FREEZE_FAIL

    out["label"] = out.get("label") or path.stem
    with open(path, "w") as f:
        json.dump(out, f, indent=1)
    print(f"[saved] {path} status={out['status']} decision={out.get('decision')}")


if __name__ == "__main__":
    main()
