"""PERCEPTION_STATUS_REBASE_V1 — deterministic evidence aggregation.

Reads existing durable science artifacts ONLY (JSON). Zero inference.
Produces:
  docs/science/PERCEPTION_STATUS_SCORECARD_V1.json
  docs/science/PERCEPTION_PRIORITY_MATRIX_V1.json

Status enums: PASS / PARTIAL / FAIL / UNKNOWN / NOT_EVALUATED
No protected holdout access. No Paris tuning input. No freezes.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

REPO = os.environ.get(
    "DIVE_ANALYSER_REPO",
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
)
SCIENCE = os.path.join(REPO, "docs", "science")

LABEL = "PERCEPTION_STATUS_REBASE_V1"
DATE = "2026-09-11"

# Family assignment comes from the human-annotated approach context recorded in
# EL_V3C_DEVELOPMENT_EVAL_V1.json / V3D0_HURDLE_CORPUS_BASELINE_V1.json and the
# HURDLE corpus expansion section of docs/PROJECT_STATE.md (drill flag from baseline).
FAMILY = {
    "133": "STANDING", "311": "STANDING", "676": "STANDING", "2387": "STANDING",
    "1040": "HURDLE_ORDINARY", "2169": "HURDLE_ORDINARY",
    "2341": "HURDLE_ORDINARY", "2541": "HURDLE_ORDINARY",
    "2353": "HURDLE_DRILL",
    "2555": "HURDLE_STRESS_SCREEN_RECORDING",
    "524": "HURDLE_AUTHORITY_CONFLICT_524",
    "2625": "NO_TAKEOFF_GT",
    "2661": "ARMSTAND", "2680": "ARMSTAND",
}
PARIS = "EXTERNAL_CANARY_PARIS_FIREWALL_PROTECTED"

# Evidence threshold: EL error <= 0.5s => PASS at the landmark.
PASS_TOL_S = 0.5

SOURCES = [
    "docs/science/DOMAIN_INVENTORY_V1.json",
    "docs/science/HURDLE_TARGET_IDENTITY_CLASSIFICATION_V1.json",
    "docs/science/V3D0_HURDLE_CORPUS_BASELINE_V1.json",
    "docs/science/HURDLE_FM2_RECLASSIFICATION_V1.json",
    "docs/science/HURDLE_M_524_MAPPING_AUDIT_V1.json",
    "docs/science/EL_V3C_DEVELOPMENT_EVAL_V1.json",
    "docs/science/TEMPORAL_LANDMARK_INTERNAL_EVAL_V1.json",
]


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load(rel: str):
    with open(os.path.join(REPO, rel)) as f:
        return json.load(f)


def _landmark(status: str, err) -> str:
    if err is None:
        return "UNKNOWN"
    s = "PASS" if err <= PASS_TOL_S else "FAIL"
    return f"{s}({err:.3f}s)"


def build_rows() -> list[dict]:
    classification = load(SOURCES[1])
    base = load(SOURCES[2])
    hurdle = base["hurdle_results"]
    standing = base["standing_results"]
    rows: list[dict] = []

    def add(dive_id, family, media, in_prop, identity, traj, to, ap, wc, overall, failure, note):
        rows.append({
            "dive_id": dive_id, "family": family, "media_authority": media,
            "detector_target_in_proposals": in_prop,
            "target_identity_status": identity, "trajectory_status": traj,
            "takeoff_status": to, "apex_status": ap, "water_contact_status": wc,
            "overall_status": overall, "primary_failure_family": failure,
            "evidence_note": note,
        })

    # STANDING: anchor-frame D5-only validity documented (DEV_D5_ONLY_EVAL_V1);
    # full-video GT-free identity never classified for standing dives -> PARTIAL.
    for dv in ("133", "311", "676", "2387"):
        e = standing[dv]["errors"]
        to_s = _landmark("PASS" if e["to_err"] <= PASS_TOL_S else "FAIL", e["to_err"])
        ap_s = _landmark("UNKNOWN", e.get("apex_err"))
        wc_s = _landmark("PASS" if e["wc_err"] <= PASS_TOL_S else "FAIL", e["wc_err"])
        overall = ("PASS" if (e["to_err"] <= PASS_TOL_S
                              and (e.get("apex_err") is None or e["apex_err"] <= PASS_TOL_S)
                              and e["wc_err"] <= PASS_TOL_S)
                   else ("PARTIAL" if e["wc_err"] <= PASS_TOL_S else "FAIL"))
        failure = "NONE" if overall == "PASS" else "EVENT_LOGIC"
        add(dv, FAMILY[dv], "proxy_360p+PTS_AUTHORITATIVE_SEEK", "PASS", "PARTIAL",
            "PASS", to_s, ap_s, wc_s, overall, failure,
            "EL complete on frozen V3-C0/V3-D0 baseline; identity valid at annotated "
            "anchor frames only")

    # HURDLE rows: identity from per-frame GT chains; trajectory/EL from frozen baseline.
    for dv in ("1040", "2169", "2341", "2541", "2353", "2555"):
        e = hurdle[dv]["errors"]
        top1 = classification["dives"][dv]["a3"]["top1_correct_rate"]
        identity = "PASS" if top1 >= 0.9 else ("PARTIAL" if top1 >= 0.4 else "FAIL")
        to_s = _landmark("PASS" if e["to_err"] <= PASS_TOL_S else "FAIL", e["to_err"])
        ap_s = _landmark("PASS" if e["apex_err"] <= PASS_TOL_S else "FAIL", e["apex_err"])
        wc_s = _landmark("PASS" if e["wc_err"] <= PASS_TOL_S else "FAIL", e["wc_err"])
        if dv == "2169":
            traj, overall, failure = "PARTIAL", "PARTIAL", "TRAJECTORY_GAP"
        elif dv == "2555":
            traj, overall, failure = "PARTIAL", "FAIL", "TARGET_IDENTITY"
        else:
            traj, overall, failure = "FAIL", "FAIL", "TARGET_IDENTITY"
        add(dv, FAMILY[dv], "proxy_360p+PTS_AUTHORITATIVE_SEEK", "PASS",
            identity, traj, to_s, ap_s, wc_s, overall, failure,
            "V3-D0 frozen baseline full-trajectory EL; identity from "
            "HURDLE_TARGET_IDENTITY_CLASSIFICATION_V1 (avail_floor=1.000)")

    # 524: mapping authority conflict (MEDIA_AUTHORITY).
    add("524", FAMILY["524"],
        "proxy_360p; HQ 524 mapping authority conflict", "UNKNOWN", "NOT_EVALUATED",
        "PARTIAL",
        _landmark("FAIL", hurdle["524"]["errors"]["to_err"]),
        _landmark("FAIL", hurdle["524"]["errors"]["apex_err"]),
        _landmark("FAIL", hurdle["524"]["errors"]["wc_err"]),
        "FAIL", "MEDIA_AUTHORITY",
        "HURDLE_M_524_MAPPING_AUDIT_V1 verdict 524_MAPPING_AUTHORITY_CONFLICT_CONFIRMED; "
        "no usable GT anchors; identity experiments out of scope until authority repaired")

    # 2625: excluded from HURDLE corpus (no takeoff GT).
    add("2625", FAMILY["2625"], "proxy_360p", "PASS", "NOT_EVALUATED", "UNKNOWN",
        "NOT_EVALUATED", "FAIL(no GT)", "PARTIAL", "NOT_EVALUATED", "UNMEASURED",
        "no takeoff GT; anchor apex/wc captured in DEV_D5_ONLY_EVAL_V1")

    # armstand family: never run through the frozen pipeline.
    for dv in ("2661", "2680"):
        add(dv, FAMILY[dv], "proxy_360p", "NOT_EVALUATED", "NOT_EVALUATED", "NOT_EVALUATED",
            "NOT_EVALUATED", "NOT_EVALUATED", "NOT_EVALUATED", "NOT_EVALUATED", "UNMEASURED",
            "armstand family; no current-pipeline evidence")

    # Paris external canary: report-only, firewall protected, never a tuning input.
    add("IMG_1937.canary", PARIS, "external original; FIREWALL_PROTECTED", "PASS",
        "NOT_EVALUATED", "PASS",
        _landmark("FAIL", 1.685), _landmark("FAIL", 1.952), _landmark("PASS", 0.183),
        "PARTIAL", "EVENT_LOGIC",
        "TRAJECTORY_INPUT_PASS (C1-C6) on GT-anchored trajectory; FM2 open; report-only")

    return rows


def aggregate(rows: list[dict]) -> dict:
    fam: dict[str, dict] = {}
    for r in rows:
        f = fam.setdefault(r["family"], {
            "n": 0, "proposal_recall_pass": 0, "identity_pass": 0, "identity_partial": 0,
            "trajectory_pass": 0, "takeoff_pass": 0, "apex_pass": 0, "wc_pass": 0,
            "overall_pass": 0, "overall_partial": 0, "overall_fail": 0,
            "overall_unevaluated": 0,
        })
        f["n"] += 1
        f["proposal_recall_pass"] += r["detector_target_in_proposals"] == "PASS"
        f["identity_pass"] += r["target_identity_status"] == "PASS"
        f["identity_partial"] += r["target_identity_status"] == "PARTIAL"
        f["trajectory_pass"] += r["trajectory_status"] == "PASS"
        f["takeoff_pass"] += str(r["takeoff_status"]).startswith("PASS")
        f["apex_pass"] += str(r["apex_status"]).startswith("PASS")
        f["wc_pass"] += str(r["water_contact_status"]).startswith("PASS")
        f["overall_pass"] += r["overall_status"] == "PASS"
        f["overall_partial"] += r["overall_status"] == "PARTIAL"
        f["overall_fail"] += r["overall_status"] == "FAIL"
        f["overall_unevaluated"] += r["overall_status"] == "NOT_EVALUATED"
    return fam


FAILURE_TAXONOMY = {
    "DETECTOR_PROPOSAL_MISS": "0 measured (target in floor proposals 100% on all classified dives)",
    "DETECTOR_RANKING": ("mechanism of the identity failure on 1040/2341/2353/2541 "
                         "(+2555 partial); reported under TARGET_IDENTITY"),
    "TARGET_IDENTITY": "5 dives: 1040, 2341, 2353, 2541, 2555 (2169 exception: top-1 0.963)",
    "TRAJECTORY_GAP": "2 dives: 676 (FM3 360p noise), 2169 (cy 0.262->0.711 artifact at 6.406s)",
    "EVENT_LOGIC": "3 dives with EL-caused or unresolved EL failures: 676, 2387 (+Paris FM2, report-only)",
    "MEDIA_AUTHORITY": "1 dive: 524 (HQ mapping authority conflict, confirmed)",
    "UNMEASURED": "3 development dives (2625, 2661, 2680) + all 2793 non-annotated product dives",
    "NONE": "2 dives fully clean: 133, 311",
}


def main() -> int:
    rows = build_rows()
    fams = aggregate(rows)

    inv = load(SOURCES[0])
    apparatus = inv["apparatus"]
    hurdle_proxy = inv["execution"]["hurdle_dives_approx"]

    scorecard = {
        "label": "PERCEPTION_STATUS_SCORECARD_V1",
        "packet": LABEL,
        "date": DATE,
        "status_enums": ["PASS", "PARTIAL", "FAIL", "UNKNOWN", "NOT_EVALUATED"],
        "counts": {
            "PASS": sum(r["overall_status"] == "PASS" for r in rows),
            "PARTIAL": sum(r["overall_status"] == "PARTIAL" for r in rows),
            "FAIL": sum(r["overall_status"] == "FAIL" for r in rows),
            "UNKNOWN": sum(r["overall_status"] == "UNKNOWN" for r in rows),
            "NOT_EVALUATED": sum(r["overall_status"] == "NOT_EVALUATED" for r in rows),
        },
        "rows": rows,
        "family_aggregation": fams,
        "failure_taxonomy": FAILURE_TAXONOMY,
        "product_prevalence": {
            "status": "PRODUCT_PREVALENCE_UNKNOWN",
            "hurdle_proxy_lower_bound": hurdle_proxy,
            "corpus_dives": apparatus["total"],
            "proxy_note": ("caption grammar encodes no approach field; code-group proxy "
                           "(156/2803, 5.6%) is hurdle-mandatory-by-code and is a lower bound; "
                           "annotated counterexample 2387 (5411C, context STANDING) shows the "
                           "proxy is imperfect"),
        },
        "source_provenance": {rel: sha256(os.path.join(REPO, rel)) for rel in SOURCES},
        "constraints": {
            "new_detector_inference": 0, "new_reid_inference": 0,
            "new_video_model_inference": 0, "new_labels": 0,
            "protected_holdout_access": "NONE",
            "paris_used_for_tuning": False,
            "science_authorities_mutated": False,
            "media_backbone_mutated": False,
        },
    }

    matrix = {
        "label": "PERCEPTION_PRIORITY_MATRIX_V1",
        "date": DATE,
        "scale": ("1-5, higher is better; cost/risk dims pre-inverted so "
                  "higher=cheaper/lower-risk"),
        "weights": {
            "product_impact": 0.25, "expected_information_gain": 0.20,
            "dependency_readiness": 0.10, "data_readiness": 0.10,
            "implementation_cost": 0.10, "compute_cost": 0.05,
            "scientific_uncertainty_resolved": 0.10, "low_overfit_risk": 0.10,
        },
        "candidates": {
            "TARGET_IDENTITY_V1_LEARNED": {
                "product_impact": 3, "expected_information_gain": 4,
                "dependency_readiness": 4, "data_readiness": 4,
                "implementation_cost": 3, "compute_cost": 4,
                "scientific_uncertainty_resolved": 3, "low_overfit_risk": 2,
                "evidence": ("OSNet frozen features discriminative at 360p (margin 0.203, "
                             "AUC 0.902) yet GT-free association failed; GT chains exist for "
                             "6 dives; V2-V4 GT-free gates all FAILED "
                             "(V4_FREEZE_GATE_VERDICT: GATE_FAILED 0/4); single athlete/venue, "
                             "6 labeled dives -> overfit risk high"),
            },
            "CORE_DETECTION_V1": {
                "product_impact": 5, "expected_information_gain": 5,
                "dependency_readiness": 4, "data_readiness": 2,
                "implementation_cost": 3, "compute_cost": 3,
                "scientific_uncertainty_resolved": 3, "low_overfit_risk": 4,
                "evidence": ("packet North Star (detect -> rough clip -> refine); "
                             "family-agnostic; frozen D5 floor coverage 100% suggests spotting "
                             "feasibility; NOT_STARTED today; media backbone P10 provides "
                             "durable original bytes; no raw-session event labels exist"),
            },
            "SUPPORTED_FAMILY_TEMPORAL_PIPELINE": {
                "product_impact": 3, "expected_information_gain": 3,
                "dependency_readiness": 5, "data_readiness": 5,
                "implementation_cost": 4, "compute_cost": 4,
                "scientific_uncertainty_resolved": 4, "low_overfit_risk": 4,
                "evidence": ("STANDING: EL complete 4/4 on frozen V3-C0 baseline; but 2/4 "
                             "dives have takeoff err > 2s; capped by trajectory authority; "
                             "no new deps; limited new science"),
            },
            "MEDIA_QUALITY_PERCEPTION_REBASE": {
                "product_impact": 2, "expected_information_gain": 2,
                "dependency_readiness": 4, "data_readiness": 4,
                "implementation_cost": 4, "compute_cost": 5,
                "scientific_uncertainty_resolved": 4, "low_overfit_risk": 5,
                "evidence": ("HQ_REPRESENTATION_DECISION_V1 already frozen (360p production, "
                             "HQ archival); remaining gap is an ops decision (durable 360p "
                             "tier in B2), not science"),
            },
        },
        "decision": {
            "primary": "PRIORITY_CORE_DETECTION_V1",
            "secondary_parallel": (
                "TARGET_IDENTITY_V1_LEARNED background line: assemble crop/embedding dataset "
                "from existing GT chains + OSNet cache; evaluation-only, no freeze"),
        },
    }

    for name, c in matrix["candidates"].items():
        c["weighted_total"] = round(
            sum(matrix["weights"][k] * c[k] for k in matrix["weights"]), 3)

    for path, payload in (
        (os.path.join(SCIENCE, "PERCEPTION_STATUS_SCORECARD_V1.json"), scorecard),
        (os.path.join(SCIENCE, "PERCEPTION_PRIORITY_MATRIX_V1.json"), matrix),
    ):
        with open(path, "w") as f:
            json.dump(payload, f, indent=1)
        print("wrote", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
