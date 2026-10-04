#!/usr/bin/env python3
"""Phase T — D3.1 Threshold-Calibration and Perception V4 Tests

New tests added this cycle (SUPERVISOR_REVIEW_AFTER_CROSS_VENUE_PERCEPTION_V4):
1.  D3.1 operating-point freeze authority
2.  D3.1 conf frozen before Paris evaluation
3.  Paris trajectory gate PASS (D3.1 @ conf=0.05)
4.  Paris firewall maintained (Phase B)
5.  Detection-region sanity (0% spectator, cy < 0.70)
6.  N0 vs N1 target-selection documented
7.  Full-trajectory coverage
8.  Event Logic V2.1 real-signal failure documented
9.  EL failure root-cause recorded
10. EL identity unchanged (SHA preserved)
11. AMP=False training authority maintained
12. Phase R decisions present
13. Phase B trajectory gate supersedes Phase M (conf=0.10)
14. Calibration data sealed (internal only, Paris not used)
"""

import json
import pytest
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCIENCE = Path(__file__).parent.parent.parent / "docs" / "science"
SCRATCHPAD_OLD = Path(
    "/private/tmp/claude-501/-Users-maximecauchy--perso-diveanalyzer/"
    "41096d47-755f-4843-9b56-3aecdee13d2e/scratchpad"
)

D3_1_OP_FREEZE = SCIENCE / "D3_1_OPERATING_POINT_FREEZE.json"
CALIBRATION    = SCIENCE / "D3_THRESHOLD_CALIBRATION_V1.json"
PHASE_B_PARIS  = SCIENCE / "PHASE_B_PARIS_D3_1_FREEZE.json"
PHASE_B_VERIFY = SCIENCE / "PHASE_B_DETECTION_VERIFY.json"
PHASE_MN       = SCIENCE / "PHASE_MN_TARGET_SELECTION.json"
PHASE_O_FULL   = SCIENCE / "PHASE_O_FULL_TRAJECTORY.json"
PHASE_P_REAL   = SCIENCE / "PHASE_P_EVENT_LOGIC_V2_1_REAL.json"
PHASE_R        = SCIENCE / "PHASE_R_DECISIONS.json"
D3_FREEZE      = SCIENCE / "DIVER_DETECTOR_D3_FREEZE.json"
EL_FREEZE      = SCIENCE / "EVENT_LOGIC_V2_1_FREEZE.json"

CANARY_SHA = "d122262be8e7a8721ab2f6a71721bb3544403da78324138d026360ef9820eaae"
D3_WEIGHTS_SHA = "bf6415fb63aa311f45262e555899d3023dd3d05d43a5e0d69b5e86c342e1a77d"
EL_SHA         = "63cfadebfc8039319857c0497e5423754b7d575c45e26355f2f77e4c051cb073"


# ===========================================================================
# 1. D3.1 operating-point freeze authority
# ===========================================================================

def test_d31_freeze_exists():
    """D3.1 operating-point freeze must be present."""
    assert D3_1_OP_FREEZE.exists(), f"Missing: {D3_1_OP_FREEZE}"


def test_d31_weights_sha_matches_d3():
    """D3.1 weights SHA must equal D3 weights SHA (weights unchanged)."""
    op = json.loads(D3_1_OP_FREEZE.read_text())
    assert op["weights_sha256"] == D3_WEIGHTS_SHA, (
        f"D3.1 weights SHA mismatch: {op['weights_sha256']}"
    )


def test_d31_conf_is_005():
    """D3.1 frozen operating threshold must be conf=0.05."""
    op = json.loads(D3_1_OP_FREEZE.read_text())
    assert op["conf_threshold"] == 0.05, (
        f"Expected conf=0.05, got {op['conf_threshold']}"
    )


def test_d31_frozen_before_paris():
    """D3.1 operating point must state it was frozen using INTERNAL data."""
    op = json.loads(D3_1_OP_FREEZE.read_text())
    note = op.get("note", "")
    assert "Paris" in note and "NOT" in note, (
        "D3.1 freeze note must state Paris was NOT used for calibration"
    )


# ===========================================================================
# 2. Calibration dataset fingerprint
# ===========================================================================

def test_calibration_exists():
    """Threshold calibration document must be present."""
    assert CALIBRATION.exists(), f"Missing: {CALIBRATION}"


def test_calibration_sealed_internal():
    """Calibration must state Paris was sealed."""
    cal = json.loads(CALIBRATION.read_text())
    note = cal.get("note", "")
    assert "Paris" in note and "sealed" in note.lower(), (
        "Calibration note must confirm Paris was sealed"
    )


def test_calibration_includes_holdout_recall():
    """Calibration must report holdout recall at the chosen threshold."""
    op = json.loads(D3_1_OP_FREEZE.read_text())
    # Check calibration decision rationale has holdout recall
    rat = op.get("calibration_decision_rationale", {})
    assert "conf=0.05_holdout_recall" in rat, "Missing conf=0.05 holdout recall in rationale"
    assert rat["conf=0.05_holdout_recall"] >= 0.90, (
        f"Holdout recall at conf=0.05 expected >= 0.90, got {rat['conf=0.05_holdout_recall']}"
    )


# ===========================================================================
# 3. Paris trajectory gate PASS (Phase B)
# ===========================================================================

def test_phase_b_paris_exists():
    """Phase B Paris re-evaluation result must be present."""
    assert PHASE_B_PARIS.exists(), f"Missing: {PHASE_B_PARIS}"


def test_phase_b_trajectory_gate_pass():
    """D3.1 Paris trajectory gate must be TRAJECTORY_INPUT_PASS."""
    r = json.loads(PHASE_B_PARIS.read_text())
    assert r["trajectory_gate"] == "TRAJECTORY_INPUT_PASS", (
        f"Expected TRAJECTORY_INPUT_PASS, got {r['trajectory_gate']}"
    )


def test_phase_b_action_window_coverage_100():
    """Phase B action window coverage must be 100%."""
    r = json.loads(PHASE_B_PARIS.read_text())
    assert r["action_window_coverage"] == 1.0, (
        f"Expected 100% coverage, got {r['action_window_coverage']:.1%}"
    )


def test_phase_b_all_landmarks_detected():
    """All three GT landmarks must be detected in Phase B."""
    r = json.loads(PHASE_B_PARIS.read_text())
    assert r["gt_takeoff_detected"], "GT takeoff not detected"
    assert r["gt_apex_detected"],    "GT apex not detected"
    assert r["gt_wc_detected"],      "GT water_contact not detected"


# ===========================================================================
# 4. Paris firewall maintained
# ===========================================================================

def test_phase_b_paris_firewall():
    """Phase B must be marked read-only / no-tuning."""
    r = json.loads(PHASE_B_PARIS.read_text())
    firewall = r.get("firewall", "")
    assert "NO_TUNING" in firewall or "no_tuning" in firewall.lower(), (
        f"Paris firewall metadata missing: '{firewall}'"
    )


def test_phase_b_canary_sha_matches():
    """Phase B must reference the correct canary SHA256."""
    r = json.loads(PHASE_B_PARIS.read_text())
    assert r.get("canary_sha256") == CANARY_SHA, (
        f"Canary SHA mismatch in Phase B: {r.get('canary_sha256')}"
    )


# ===========================================================================
# 5. Detection-region sanity (0% spectator)
# ===========================================================================

def test_phase_b_zero_spectator_detections():
    """Phase B verification must show 0 spectator-region detections."""
    if not PHASE_B_VERIFY.exists():
        pytest.skip("Phase B verification file not found")
    v = json.loads(PHASE_B_VERIFY.read_text())
    action_spec = v.get("action_dets_spectator", 1)
    outside_spec = v.get("outside_dets_spectator", 1)
    assert action_spec == 0, f"Action window spectator hits: {action_spec} (expected 0)"
    assert outside_spec == 0, f"Outside window spectator hits: {outside_spec} (expected 0)"


def test_phase_b_diver_region_primary_100():
    """Phase B verification must show 100% diver-region primary candidate in action window."""
    if not PHASE_B_VERIFY.exists():
        pytest.skip("Phase B verification file not found")
    v = json.loads(PHASE_B_VERIFY.read_text())
    pct = v.get("action_window_diver_region_pct", 0)
    assert pct == 1.0, f"Expected 100% diver-region primary, got {pct:.1%}"


# ===========================================================================
# 6. N0 vs N1 target-selection documented
# ===========================================================================

def test_phase_mn_exists():
    """Phase M/N target-selection result must be present."""
    assert PHASE_MN.exists(), f"Missing: {PHASE_MN}"


def test_phase_mn_both_methods_evaluated():
    """Phase M/N must evaluate both N0 (framewise) and N1 (ByteTrack)."""
    r = json.loads(PHASE_MN.read_text())
    assert "n0_metrics" in r, "Missing N0 metrics"
    assert "n1_metrics" in r, "Missing N1 metrics"


def test_phase_mn_preferred_recorded():
    """Phase M/N must record which method was preferred and why."""
    r = json.loads(PHASE_MN.read_text())
    assert r.get("preferred_method") in {"N0_FRAMEWISE", "N1_BYTETRACK"}, (
        f"Invalid preferred method: {r.get('preferred_method')}"
    )


def test_phase_mn_n0_gate_pass():
    """N0 must also pass trajectory gate."""
    r = json.loads(PHASE_MN.read_text())
    n0 = r["n0_metrics"]
    assert n0["trajectory_gate"] == "TRAJECTORY_INPUT_PASS"


# ===========================================================================
# 7. Full-trajectory coverage
# ===========================================================================

def test_phase_o_trajectory_exists():
    """Phase O full trajectory must be present."""
    assert PHASE_O_FULL.exists(), f"Missing: {PHASE_O_FULL}"


def test_phase_o_gate_pass():
    """Phase O trajectory gate must be TRAJECTORY_INPUT_PASS."""
    r = json.loads(PHASE_O_FULL.read_text())
    assert r["trajectory_gate"] == "TRAJECTORY_INPUT_PASS"


def test_phase_o_trajectory_covers_full_video():
    """Phase O trajectory must cover the full video (not just action window)."""
    r = json.loads(PHASE_O_FULL.read_text())
    pts = r["trajectory_pts_s"]
    assert pts[0] < 0.5, f"Trajectory starts too late: {pts[0]:.3f}s (expected < 0.5s)"
    assert pts[-1] > 4.0, f"Trajectory ends too early: {pts[-1]:.3f}s (expected > 4.0s)"


# ===========================================================================
# 8. Event Logic V2.1 real-signal failure documented
# ===========================================================================

def test_phase_p_real_exists():
    """Phase P real-signal EL result must be present."""
    assert PHASE_P_REAL.exists(), f"Missing: {PHASE_P_REAL}"


def test_phase_p_canary_result_is_fail():
    """Phase P canary result must be REAL_SIGNAL_CANARY_FAIL."""
    r = json.loads(PHASE_P_REAL.read_text())
    assert r["canary_result"] == "REAL_SIGNAL_CANARY_FAIL", (
        f"Expected REAL_SIGNAL_CANARY_FAIL, got {r['canary_result']}"
    )


def test_phase_p_all_landmarks_were_detected():
    """Event Logic must have produced predictions for all three landmarks (to document errors)."""
    r = json.loads(PHASE_P_REAL.read_text())
    # Even in a fail, all_detected should be True (errors reported)
    # (Logic found events, just at wrong times)
    assert r.get("all_detected"), "Expected all_detected=True (errors should be documented)"


def test_phase_p_systematic_error_documented():
    """Phase P must document systematic offset (all errors in same direction)."""
    r = json.loads(PHASE_P_REAL.read_text())
    errs = r.get("errors", {})
    for name, e in errs.items():
        if e is not None:
            assert e > 0, f"Expected positive error (too late), got {name}={e}"


# ===========================================================================
# 9. EL failure root-cause recorded
# ===========================================================================

def test_phase_r_el_failure_root_cause():
    """Phase R must record root cause of EL failure."""
    assert PHASE_R.exists(), f"Missing: {PHASE_R}"
    r = json.loads(PHASE_R.read_text())
    fail_analysis = r.get("event_logic_failure_analysis", {})
    root_cause = fail_analysis.get("root_cause", "")
    assert root_cause == "VELOCITY_RESOLUTION_INSUFFICIENT_AT_360P", (
        f"Unexpected root cause: '{root_cause}'"
    )


def test_phase_r_next_work_documented():
    """Phase R must document at least one next required work item."""
    r = json.loads(PHASE_R.read_text())
    nrw = r.get("next_required_work", [])
    assert len(nrw) >= 1, "No next required work items documented"


# ===========================================================================
# 10. Event Logic identity unchanged
# ===========================================================================

def test_el_sha_unchanged():
    """Event Logic V2.1 SHA must be unchanged."""
    if not EL_FREEZE.exists():
        pytest.skip("EL freeze not found")
    el = json.loads(EL_FREEZE.read_text())
    assert el.get("source_sha256") == EL_SHA, (
        f"EL V2.1 SHA mismatch: {el.get('source_sha256')}"
    )


def test_phase_p_el_sha_matches_freeze():
    """Phase P must reference the correct EL V2.1 SHA."""
    r = json.loads(PHASE_P_REAL.read_text())
    assert r.get("event_logic_sha256") == EL_SHA, (
        f"Phase P EL SHA mismatch: {r.get('event_logic_sha256')}"
    )


def test_el_not_modified_after_paris():
    """Phase P must confirm Event Logic was not modified after seeing Paris results."""
    r = json.loads(PHASE_P_REAL.read_text())
    # The EL failure analysis in Phase R must state no modification
    phase_r = json.loads(PHASE_R.read_text())
    fa = phase_r.get("event_logic_failure_analysis", {})
    assert fa.get("event_logic_NOT_modified") is True, (
        "Phase R must confirm EL was not modified"
    )


# ===========================================================================
# 11. AMP=False training authority maintained
# ===========================================================================

def test_amp_false_recorded_in_d3_freeze():
    """D3 freeze must record amp=False."""
    if not D3_FREEZE.exists():
        pytest.skip("D3 freeze not found")
    r = json.loads(D3_FREEZE.read_text())
    assert r.get("amp") is False, f"Expected amp=False in D3 freeze, got: {r.get('amp')}"


# ===========================================================================
# 12. Phase R decisions
# ===========================================================================

def test_phase_r_detector_decision():
    """Phase R must record a valid detector decision."""
    r = json.loads(PHASE_R.read_text())
    valid = {
        "D3_THRESHOLD_WAS_SUFFICIENT",
        "OPEN_VOCABULARY_GENERALIZES",
        "D4_CROSS_DOMAIN_GENERALIZES",
        "D4_IN_DOMAIN_ONLY",
        "MORE_EXTERNAL_DOMAINS_REQUIRED",
        "DETECTION_FAMILY_REDESIGN_REQUIRED",
    }
    assert r.get("detector_decision") in valid, (
        f"Invalid detector decision: {r.get('detector_decision')}"
    )


def test_phase_r_event_logic_decision():
    """Phase R must record a valid Event Logic decision."""
    r = json.loads(PHASE_R.read_text())
    valid = {"NOT_EVALUABLE", "REAL_SIGNAL_CANARY_PASS", "REAL_SIGNAL_CANARY_FAIL"}
    assert r.get("event_logic_decision") in valid, (
        f"Invalid EL decision: {r.get('event_logic_decision')}"
    )


# ===========================================================================
# 13. Phase B supersedes Phase M (conf=0.10) result
# ===========================================================================

def test_phase_b_conf_higher_recall_than_phase_m():
    """Phase B (conf=0.05) must show higher coverage than old Phase M (conf=0.10)."""
    r = json.loads(PHASE_B_PARIS.read_text())
    # conf=0.10 gave 7.5% action-window coverage (old result)
    old_coverage = 0.075
    assert r["action_window_coverage"] > old_coverage, (
        f"Phase B coverage {r['action_window_coverage']:.1%} not higher than old 7.5%"
    )


if __name__ == "__main__":
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v"],
        cwd=str(Path(__file__).parent)
    )
    sys.exit(result.returncode)
