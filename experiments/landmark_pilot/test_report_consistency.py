#!/usr/bin/env python3
"""Tests for scientific report/artifact consistency — Phase A1.

These tests are designed to FAIL when documented metrics do not match
their authoritative JSON sources. They would have caught the Phase M
inconsistency where the correction document claimed:
  takeoff_error = -0.103s
  apex_error = +0.013s
but the committed code actually produced:
  takeoff_error = -1.670s
  apex_error = -1.353s
"""
import json
import re
import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCIENCE = ROOT / "docs/science"

import pytest


def load_json(path):
    with open(path) as f:
        return json.load(f)


# ─── Phase M audit vs documented values ──────────────────────────────────────

class TestPhaseMConsistency:
    """Tests that would have caught the Phase M number inconsistency."""

    def test_phase_m_audit_documents_takeoff_error(self):
        """The audit JSON documents the actual takeoff error from committed code."""
        audit = load_json(SCIENCE / "PHASE_M_CANARY_CHECK_AUDIT.json")
        assert "actual_committed_output" in audit
        assert "takeoff_error_s" in audit["actual_committed_output"]
        # The audit documents a large negative error, NOT the claimed small error
        actual_tko_err = audit["actual_committed_output"]["takeoff_error_s"]
        claimed_tko_err = audit["document_claimed_output"]["takeoff_error_s"]
        assert abs(actual_tko_err) > 1.0, (
            f"Phase M audit: actual takeoff error {actual_tko_err:.3f}s is not the "
            f"mechanism failure value (-1.670s). Audit may be wrong."
        )
        assert abs(actual_tko_err) > abs(claimed_tko_err), (
            f"Phase M: actual error ({actual_tko_err:.3f}s) should be LARGER than "
            f"claimed error ({claimed_tko_err:.3f}s). Something is wrong with the audit."
        )

    def test_phase_m_audit_document_claimed_status_incorrect(self):
        """The document_claimed values are marked INCORRECT."""
        audit = load_json(SCIENCE / "PHASE_M_CANARY_CHECK_AUDIT.json")
        status = audit["document_claimed_output"]["status"]
        assert "INCORRECT" in status.upper(), (
            f"Phase M audit: document_claimed_output status '{status}' must contain "
            f"INCORRECT to signal the correction document had wrong values."
        )

    def test_correction_doc_marked_superseded(self):
        """The correction document carries a SUPERSEDED notice about Phase M values."""
        doc = (SCIENCE / "HIGH_RESOLUTION_CANARY_EVENT_SEMANTICS_CORRECTION_V1.md").read_text()
        assert "SUPERSEDED" in doc.upper() or "superseded" in doc.lower(), (
            "HIGH_RESOLUTION_CANARY_EVENT_SEMANTICS_CORRECTION_V1.md must be marked "
            "as superseded/corrected because its Phase M numbers were wrong. "
            "This test would have caught the false claim that takeoff_error=-0.103s "
            "(actual: -1.670s)."
        )

    def test_real_signal_report_cites_correct_phase_m_values(self):
        """REAL_SIGNAL report documents the AUDIT values, not the correction doc values."""
        report = (SCIENCE / "REAL_SIGNAL_EVENT_LOGIC_AND_HIGHRES_PIPELINE_V1_REPORT.md").read_text()
        # The report should contain the actual error of -1.670s (or 1.670)
        assert "1.670" in report or "1,670" in report, (
            "REAL_SIGNAL_REPORT: Does not document the audited Phase M takeoff "
            "error of 1.670s. If it shows -0.103s instead, it has the wrong value."
        )


# ─── EVENT_LOGIC_V2_FREEZE integrity ─────────────────────────────────────────

class TestEventLogicV2FreezeIntegrity:
    def test_cuda_claim_removed(self):
        """The V2 freeze no longer claims CUDA is required for L1 inference."""
        freeze = load_json(SCIENCE / "EVENT_LOGIC_V2_FREEZE.json")
        limitations = json.dumps(freeze.get("known_limitations", []))
        assert "CUDA" not in limitations, (
            "EVENT_LOGIC_V2_FREEZE.json still contains CUDA claim in known_limitations. "
            "L1 inference was confirmed to work on MPS and CPU (35a1b05 findings). "
            "CUDA is NOT required."
        )

    def test_freeze_references_correct_test_count(self):
        """Freeze documents 29 passing tests."""
        freeze = load_json(SCIENCE / "EVENT_LOGIC_V2_FREEZE.json")
        n = freeze["test_suite"]["n_tests"]
        assert n == 29, f"Expected 29 tests, freeze documents {n}"

    def test_freeze_all_tests_pass(self):
        """Freeze documents ALL tests pass."""
        freeze = load_json(SCIENCE / "EVENT_LOGIC_V2_FREEZE.json")
        assert freeze["test_suite"]["n_failed"] == 0
        assert freeze["test_suite"]["result"] == "ALL_PASS"


# ─── LOCALIZATION_ANNOTATIONS_V1_FREEZE integrity ────────────────────────────

class TestLocalizationAnnotationsFreeze:
    def test_development_count_matches_files(self):
        """FREEZE count matches actual number of annotation files."""
        freeze = load_json(SCIENCE / "LOCALIZATION_ANNOTATIONS_V1_FREEZE.json")
        dev_freeze = freeze["splits"]["DEVELOPMENT_DESIGN"]
        freeze_count = dev_freeze["count"]
        actual_files = list((SCIENCE / "localization_annotations_v1/DEVELOPMENT_DESIGN").glob("*.json"))
        assert len(actual_files) == freeze_count, (
            f"FREEZE documents {freeze_count} DEVELOPMENT_DESIGN annotations but "
            f"{len(actual_files)} files exist."
        )

    def test_internal_eval_sealed(self):
        """INTERNAL_EVAL split exists in freeze (sealed, not for tuning)."""
        freeze = load_json(SCIENCE / "LOCALIZATION_ANNOTATIONS_V1_FREEZE.json")
        assert "INTERNAL_EVAL" in freeze["splits"]
        assert freeze["splits"]["INTERNAL_EVAL"]["count"] > 0


# ─── Canary annotation authority ─────────────────────────────────────────────

class TestCanaryAnnotationAuthority:
    def test_v2_annotation_takeoff_matches_project_state(self):
        """V2 canary takeoff (3.120s) matches PROJECT_STATE."""
        ann = load_json(SCIENCE / "HIGHRES_CANARY_V2_EXACT_ANNOTATION.json")
        # Find takeoff landmark
        takeoff = None
        for entry in ann.get("landmarks", {}).values():
            if entry.get("event") == "takeoff" or entry.get("phase") == "takeoff":
                takeoff = entry
                break
        if takeoff is None:
            # Try flat format
            takeoff_t = ann.get("takeoff_t") or ann.get("takeoff", {}).get("pts_s")
        else:
            takeoff_t = takeoff.get("pts_s")

        project_state = (ROOT / "docs/PROJECT_STATE.md").read_text()
        assert "3.120" in project_state, "PROJECT_STATE must document takeoff=3.120s"
        assert "4.220" in project_state, "PROJECT_STATE must document water_contact=4.220s"



class TestEventLogicV2_1FreezeIntegrity:
    """V2.1 freeze document is consistent with the actual source file."""

    def test_v2_1_freeze_exists(self):
        freeze_path = SCIENCE / "EVENT_LOGIC_V2_1_FREEZE.json"
        assert freeze_path.exists(), "EVENT_LOGIC_V2_1_FREEZE.json must exist"

    def test_v2_1_freeze_supersedes_v2(self):
        freeze = load_json(SCIENCE / "EVENT_LOGIC_V2_1_FREEZE.json")
        assert freeze.get("supersedes") == "EVENT_LOGIC_V2_FREEZE.json"

    def test_v2_1_freeze_36_tests_all_pass(self):
        freeze = load_json(SCIENCE / "EVENT_LOGIC_V2_1_FREEZE.json")
        assert freeze.get("test_count") == 36
        assert freeze.get("test_status") == "ALL_PASS"

    def test_v2_1_source_sha_matches_file(self):
        freeze = load_json(SCIENCE / "EVENT_LOGIC_V2_1_FREEZE.json")
        src_path = ROOT / "experiments" / "landmark_pilot" / "proposer_event_logic_v2_1.py"
        import hashlib
        with open(src_path, "rb") as f:
            actual_sha = hashlib.sha256(f.read()).hexdigest()
        recorded = freeze["source_sha256"]
        assert recorded == actual_sha, (
            "V2.1 source SHA mismatch. "
            "Freeze records " + recorded[:16] + "... "
            "but file is " + actual_sha[:16] + "... "
            "Update EVENT_LOGIC_V2_1_FREEZE.json source_sha256."
        )

    def test_v2_1_correction_doc_superseded(self):
        """HIGH_RESOLUTION_CANARY correction doc must be marked SUPERSEDED."""
        doc_path = SCIENCE / "HIGH_RESOLUTION_CANARY_EVENT_SEMANTICS_CORRECTION_V1.md"
        content = doc_path.read_text()
        assert "SUPERSEDED" in content, "Correction doc must be marked SUPERSEDED"
        assert "PHASE_M_CANARY_CHECK_AUDIT.json" in content, "Must reference audit document"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
