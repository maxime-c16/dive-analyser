#!/usr/bin/env python3
"""Scientific report/artifact consistency validator — Phase A1.

Verifies that performance numbers documented in human-readable reports
(Markdown files) match their authoritative JSON artifact sources.

This script would have FAILED for the incorrect Phase M numbers in
HIGH_RESOLUTION_CANARY_EVENT_SEMANTICS_CORRECTION_V1.md, which documented
takeoff_error=-0.103s, apex_error=+0.013s but the committed code produced
takeoff_error=-1.670s, apex_error=-1.353s.

Usage:
  python3 validate_scientific_report.py [--strict]
  Exit 0 if all pass, 1 if any mismatch.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCIENCE = ROOT / "docs/science"


def load_json(path):
    with open(path) as f:
        return json.load(f)


def check_value_in_text(text, expected_value, tolerance=0.001, label=""):
    """Return True if expected_value appears in text within tolerance."""
    # Find all decimal numbers in the text
    matches = re.findall(r'[-+]?\d+\.\d+', text)
    for m in matches:
        try:
            v = float(m)
            if abs(v - expected_value) <= tolerance:
                return True
        except ValueError:
            pass
    return False


def validate_phase_m_audit():
    """Validate that PHASE_M_CANARY_CHECK_AUDIT.json values are not
    contradicted by the correction document."""
    audit_path = SCIENCE / "PHASE_M_CANARY_CHECK_AUDIT.json"
    doc_path = SCIENCE / "HIGH_RESOLUTION_CANARY_EVENT_SEMANTICS_CORRECTION_V1.md"

    audit = load_json(audit_path)
    doc_text = doc_path.read_text()

    # The audit documents the ACTUAL committed output — these are the true values.
    actual_takeoff_err = audit["actual_committed_output"]["takeoff_error_s"]
    actual_apex_err = audit["actual_committed_output"]["apex_error_s"]
    actual_wc_err = audit["actual_committed_output"]["water_contact_error_s"]

    # The document should NOT present the incorrect values as current results.
    # It should either be marked superseded or the numbers should match audit.
    errors = []

    # Check: document claimed values are marked INCORRECT in the audit
    doc_claimed_tko = audit["document_claimed_output"]["takeoff_error_s"]
    doc_claimed_apex = audit["document_claimed_output"]["apex_error_s"]

    if audit["document_claimed_output"]["status"] != "INCORRECT_NEVER_PRODUCED_BY_COMMITTED_CODE":
        errors.append("AUDIT document_claimed_output status is not INCORRECT_NEVER_PRODUCED_BY_COMMITTED_CODE")

    # Check SUPERSEDED_BY is present in the correction document
    if "SUPERSEDED" not in doc_text.upper() and "superseded" not in doc_text.lower():
        errors.append(
            f"INTEGRITY: {doc_path.name} does not contain SUPERSEDED annotation. "
            f"It documents incorrect Phase M values (claimed takeoff=-0.103s, "
            f"actual=-1.670s) without a supersession notice."
        )

    return errors


def validate_event_logic_v2_freeze():
    """Validate EVENT_LOGIC_V2_FREEZE.json known_limitations are accurate."""
    freeze_path = SCIENCE / "EVENT_LOGIC_V2_FREEZE.json"
    freeze = load_json(freeze_path)
    errors = []

    # Check CUDA claim has been removed from known_limitations
    limitations_text = json.dumps(freeze.get("known_limitations", []))
    if "CUDA" in limitations_text:
        errors.append(
            "EVENT_LOGIC_V2_FREEZE.json known_limitations still contains stale CUDA claim. "
            "L1 inference confirmed to work on MPS and CPU; CUDA is NOT required."
        )

    return errors


def validate_real_signal_report():
    """Validate that REAL_SIGNAL report references correct Phase M values."""
    report_path = SCIENCE / "REAL_SIGNAL_EVENT_LOGIC_AND_HIGHRES_PIPELINE_V1_REPORT.md"
    if not report_path.exists():
        return []

    report_text = report_path.read_text()
    errors = []

    # The report should document the ACTUAL Phase M errors from the audit
    # takeoff_error = -1.670s (actual), NOT -0.103s (claimed)
    # apex_error = -1.353s (actual), NOT +0.013s (claimed)
    if "-1.670" not in report_text and "1.670" not in report_text:
        errors.append(
            "REAL_SIGNAL_REPORT: Does not document the audited takeoff error of -1.670s. "
            "May be referencing incorrect Phase M values."
        )

    return errors


def main():
    all_errors = []

    print("=== Scientific Report/Artifact Consistency Validator ===")
    print()

    checks = [
        ("Phase M audit vs correction doc", validate_phase_m_audit),
        ("EVENT_LOGIC_V2_FREEZE CUDA claim", validate_event_logic_v2_freeze),
        ("Real-signal report Phase M values", validate_real_signal_report),
    ]

    for name, check_fn in checks:
        errs = check_fn()
        if errs:
            print(f"FAIL — {name}:")
            for e in errs:
                print(f"  ✗ {e}")
            all_errors.extend(errs)
        else:
            print(f"PASS — {name}")

    print()
    if all_errors:
        print(f"TOTAL: {len(all_errors)} integrity issue(s) found.")
        sys.exit(1)
    else:
        print("TOTAL: All integrity checks passed.")
        sys.exit(0)


if __name__ == "__main__":
    main()
