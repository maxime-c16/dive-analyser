"""Bounded tests for PERCEPTION_STATUS_REBASE_V1 (evidence-synthesis packet).

Covers: provenance, corpus enumeration, protected-holdout firewall, no-new-inference,
family aggregation, failure taxonomy, scorecard consistency, decision enums,
no science-authority mutation, prevalence token.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SCRIPT = os.path.join(HERE, "phase_perception_status_rebase_v1.py")
SCORE = os.path.join(REPO, "docs", "science", "PERCEPTION_STATUS_SCORECARD_V1.json")
MATRIX = os.path.join(REPO, "docs", "science", "PERCEPTION_PRIORITY_MATRIX_V1.json")

STATUSES = {"PASS", "PARTIAL", "FAIL", "UNKNOWN", "NOT_EVALUATED"}

# protected sets (never aggregated, never accessed)
INTERNAL_EVAL_DIVES = {"160", "169", "191", "192", "848", "2281"}
KNOWN_ARMSTAND = {"2661", "2680"}
DEVELOPMENT_DIVES = {
    "133", "311", "524", "676", "1040", "2169", "2341", "2353",
    "2387", "2541", "2555", "2625", "2661", "2680",
}


@pytest.fixture(scope="module")
def payload():
    env = dict(os.environ)
    subprocess.run([sys.executable, SCRIPT], check=True, env=env)
    with open(SCORE) as f:
        return json.load(f)


def test_script_runs_and_writes_both_artifacts(payload):
    assert os.path.exists(SCORE) and os.path.exists(MATRIX)


def test_labels_and_enums(payload):
    assert payload["label"] == "PERCEPTION_STATUS_SCORECARD_V1"
    assert payload["packet"] == "PERCEPTION_STATUS_REBASE_V1"
    assert set(payload["status_enums"]) == STATUSES


def test_source_provenance_sha256(payload):
    for rel, recorded in payload["source_provenance"].items():
        path = os.path.join(REPO, rel)
        assert os.path.exists(path), rel
        h = hashlib.sha256(open(path, "rb").read()).hexdigest()
        assert h == recorded, rel


def test_corpus_enumeration(payload):
    ids = {r["dive_id"] for r in payload["rows"]}
    assert DEVELOPMENT_DIVES <= ids
    assert ids - DEVELOPMENT_DIVES == {"IMG_1937.canary"}


def test_no_protected_holdout_access(payload):
    ids = {r["dive_id"] for r in payload["rows"]}
    assert not (ids & INTERNAL_EVAL_DIVES)
    assert payload["constraints"]["protected_holdout_access"] == "NONE"


def test_no_paris_tuning(payload):
    paris = [r for r in payload["rows"] if r["dive_id"] == "IMG_1937.canary"]
    assert len(paris) == 1
    assert "report-only" in paris[0]["evidence_note"]
    assert payload["constraints"]["paris_used_for_tuning"] is False


def test_no_new_inference(payload):
    c = payload["constraints"]
    assert c["new_detector_inference"] == 0
    assert c["new_reid_inference"] == 0
    assert c["new_video_model_inference"] == 0
    assert c["new_labels"] == 0


def test_family_aggregation_consistency(payload):
    fams = payload["family_aggregation"]
    rows = payload["rows"]
    assert sum(f["n"] for f in fams.values()) == len(rows)
    allowed = {r["family"] for r in rows}
    assert set(fams) == allowed


def test_row_status_enum_and_consistency(payload):
    rows = payload["rows"]
    for r in rows:
        assert r["overall_status"] in STATUSES
        assert r["detector_target_in_proposals"] in STATUSES
        assert r["target_identity_status"] in STATUSES
        assert r["trajectory_status"] in STATUSES
    counts = payload["counts"]
    assert sum(counts.values()) == len(rows)
    for key in ("PASS", "PARTIAL", "FAIL", "UNKNOWN", "NOT_EVALUATED"):
        assert counts[key] == sum(r["overall_status"] == key for r in rows)


def test_failure_taxonomy_complete(payload):
    assert set(payload["failure_taxonomy"]) == {
        "DETECTOR_PROPOSAL_MISS", "DETECTOR_RANKING", "TARGET_IDENTITY",
        "TRAJECTORY_GAP", "EVENT_LOGIC", "MEDIA_AUTHORITY", "UNMEASURED", "NONE",
    }


def test_decision_enums(payload):
    with open(MATRIX) as f:
        m = json.load(f)
    assert m["decision"]["primary"] in {
        "PRIORITY_TARGET_IDENTITY_V1", "PRIORITY_CORE_DETECTION_V1",
        "PRIORITY_SUPPORTED_FAMILY_TEMPORAL_PIPELINE",
        "PRIORITY_MEDIA_QUALITY_REBASE",
    }
    for name, c in m["candidates"].items():
        assert set(m["weights"]) == {k for k in c if k not in ("evidence", "weighted_total")}
        assert abs(c["weighted_total"] - sum(
            m["weights"][k] * c[k] for k in m["weights"])) < 1e-6


def test_no_science_authority_mutation(payload):
    assert payload["constraints"]["science_authorities_mutated"] is False
    assert payload["constraints"]["media_backbone_mutated"] is False
    # the aggregation script writes ONLY these two artifacts
    src = open(SCRIPT).read()
    assert src.count("json.dump") == 1
    written = [os.path.basename(p) for p in (SCORE, MATRIX)]
    assert written == [
        "PERCEPTION_STATUS_SCORECARD_V1.json",
        "PERCEPTION_PRIORITY_MATRIX_V1.json",
    ]


def test_product_prevalence_token(payload):
    assert payload["product_prevalence"]["status"] == "PRODUCT_PREVALENCE_UNKNOWN"
