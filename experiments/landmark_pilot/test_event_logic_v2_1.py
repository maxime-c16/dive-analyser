#!/usr/bin/env python3
"""Tests for Event Logic V2.1 — cy_norm convention throughout.

All trajectory fixtures use cy_norm (0=top, 1=bottom):
  - Rising diver: y decreases (negative velocity)
  - Falling diver: y increases (positive velocity)
  - Apex: minimum y value (highest physical point)
  - Water contact: y > water_line_cy_norm

Tests cover:
  - H1: standing springboard (no hurdle)
  - H2: hurdle springboard (preparation → hurdle → board loading → final takeoff)
  - H3: long static preparation + hurdle sequence
  - Phase M regression: canary-style check with corrected trajectory
  - All original logic tests with cy_norm-correct fixtures
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
import math
import pytest
import copy

from proposer_event_logic_v2_1 import (
    classify_context,
    pts_aware_velocity,
    rolling_variance_time,
    pts_aware_smooth,
    interpolate_gaps_time,
    _find_preparation_end,
    _detect_takeoff,
    _detect_apex,
    _detect_water_contact,
    propose_events,
    PARAMS_E1,
    PARAMS_E2,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def make_uniform_pts(n, fps=30.0):
    return [i / fps for i in range(n)]


def make_pts_vfr(n, rates=(1/60.0, 1/54.5)):
    pts = [0.0]
    for i in range(1, n):
        pts.append(pts[-1] + rates[i % 2])
    return pts


# ─── H1: Standing springboard fixture (cy_norm convention) ───────────────────

def make_h1_standing_trajectory(fps=60.0):
    """Standing springboard in cy_norm convention.

    Phases:
      0.0 – 0.5s  : Static preparation at y=0.40
      0.5 – 0.6s  : Board compression (y increases slightly to 0.43)
      0.6 – 1.1s  : Takeoff + ascent: y DECREASES 0.43 → 0.15 (diver rises)
      1.1 – 1.6s  : Apex region at y=0.15 (minimum, then hover)
      1.6 – 2.5s  : Descent: y INCREASES 0.15 → 0.54 (diver falls)
      2.5 – 3.0s  : Post-entry: y~0.55 (in water)

    Expected:
      takeoff_t ≈ 0.60s   (start of sustained rise)
      apex_t    ≈ 1.10s   (minimum y)
      water_contact_t ≈ 2.0s  (y > 0.50)
    """
    total = 3.5
    n = int(total * fps) + 1
    pts = [i / fps for i in range(n)]
    y = []
    conf = []
    for i, t in enumerate(pts):
        if t <= 0.50:
            # Static
            y.append(0.40)
            conf.append(0.85)
        elif t <= 0.60:
            # Board compression: y increases slightly
            frac = (t - 0.50) / 0.10
            y.append(0.40 + 0.03 * frac)
            conf.append(0.85)
        elif t <= 1.10:
            # Ascent: y decreases (diver rises)
            frac = (t - 0.60) / 0.50
            y.append(0.43 - 0.28 * frac)  # 0.43 → 0.15
            conf.append(0.80)
        elif t <= 1.60:
            # Apex: y stable near minimum
            y.append(0.15)
            conf.append(0.75)
        elif t <= 2.50:
            # Descent: y increases (diver falls)
            frac = (t - 1.60) / 0.90
            y.append(0.15 + 0.40 * frac)  # 0.15 → 0.55
            conf.append(0.70)
        else:
            # Post-entry
            y.append(0.55 + 0.02 * (t - 2.50))
            conf.append(0.30)
    return pts, y, conf


# ─── H2: Hurdle springboard fixture (cy_norm convention) ─────────────────────

def make_h2_hurdle_trajectory(fps=60.0):
    """Hurdle springboard in cy_norm convention.

    Phases:
      0.0 – 0.5s  : Static preparation at y=0.40
      0.5 – 1.0s  : Hurdle ascent: y DECREASES 0.40 → 0.18 (diver jumps up)
      1.0 – 1.8s  : Hurdle descent: y INCREASES 0.18 → 0.44 (diver returns)
      1.8 – 2.5s  : Board loading: y≈0.44 (stable, near-zero velocity)
      2.5 – 3.1s  : Final takeoff ascent: y DECREASES 0.44 → 0.12 (diver launches)
      3.1 – 3.5s  : Approach to apex: y at 0.12 (minimum)
      3.5 – 4.5s  : Descent: y INCREASES 0.12 → 0.55
      4.5 – 5.0s  : Post-entry: y~0.56

    Expected:
      takeoff_t ≈ 2.5s   (start of final ascent, after board loading)
      apex_t    ≈ 3.5s   (minimum y during flight)
      water_contact_t ≈ 4.2s  (y > 0.50)
    """
    total = 5.5
    n = int(total * fps) + 1
    pts = [i / fps for i in range(n)]
    y = []
    conf = []
    for i, t in enumerate(pts):
        if t <= 0.50:
            y.append(0.40)
            conf.append(0.85)
        elif t <= 1.00:
            # Hurdle ascent: y decreases
            frac = (t - 0.50) / 0.50
            y.append(0.40 - 0.22 * frac)  # 0.40 → 0.18
            conf.append(0.80)
        elif t <= 1.80:
            # Hurdle descent: y increases
            frac = (t - 1.00) / 0.80
            y.append(0.18 + 0.26 * frac)  # 0.18 → 0.44
            conf.append(0.80)
        elif t <= 2.50:
            # Board loading: stable
            y.append(0.44)
            conf.append(0.82)
        elif t <= 3.50:
            # Final takeoff + ascent: y decreases
            frac = (t - 2.50) / 1.00
            y.append(0.44 - 0.32 * frac)  # 0.44 → 0.12
            conf.append(0.78)
        elif t <= 4.50:
            # Descent: y increases
            frac = (t - 3.50) / 1.00
            y.append(0.12 + 0.43 * frac)  # 0.12 → 0.55
            conf.append(0.72)
        else:
            y.append(0.55)
            conf.append(0.30)
    return pts, y, conf


# ─── H3: Long-preparation + hurdle (cy_norm convention) ──────────────────────

def make_h3_long_prep_hurdle_trajectory(fps=60.0):
    """Long initial static preparation followed by hurdle springboard.

    Phases:
      0.0 – 2.0s  : Long static preparation at y=0.40
      2.0 – 2.5s  : Hurdle ascent: y DECREASES 0.40 → 0.18
      2.5 – 3.3s  : Hurdle descent: y INCREASES 0.18 → 0.44
      3.3 – 4.0s  : Board loading: y≈0.44
      4.0 – 5.0s  : Final takeoff ascent: y DECREASES 0.44 → 0.12
      5.0 – 6.0s  : Descent: y INCREASES 0.12 → 0.55

    Expected:
      takeoff_t ≈ 4.0s
      apex_t    ≈ 5.0s
      water_contact_t ≈ 5.7s
    """
    total = 6.5
    n = int(total * fps) + 1
    pts = [i / fps for i in range(n)]
    y = []
    conf = []
    for i, t in enumerate(pts):
        if t <= 2.00:
            y.append(0.40)
            conf.append(0.85)
        elif t <= 2.50:
            frac = (t - 2.00) / 0.50
            y.append(0.40 - 0.22 * frac)
            conf.append(0.80)
        elif t <= 3.30:
            frac = (t - 2.50) / 0.80
            y.append(0.18 + 0.26 * frac)
            conf.append(0.80)
        elif t <= 4.00:
            y.append(0.44)
            conf.append(0.82)
        elif t <= 5.00:
            frac = (t - 4.00) / 1.00
            y.append(0.44 - 0.32 * frac)
            conf.append(0.78)
        elif t <= 6.00:
            frac = (t - 5.00) / 1.00
            y.append(0.12 + 0.43 * frac)
            conf.append(0.72)
        else:
            y.append(0.55)
            conf.append(0.30)
    return pts, y, conf


# ─── Context classification (unchanged) ──────────────────────────────────────

def test_context_forward_group_1():
    assert classify_context("101B") == "HURDLE"
    assert classify_context("103C") == "HURDLE"

def test_context_backward_group_2():
    assert classify_context("202A") == "STANDING"

def test_context_reverse_group_3():
    assert classify_context("301A") == "STANDING"

def test_context_inward_group_4():
    assert classify_context("401C") == "STANDING"

def test_context_twisting_forward_51xx():
    assert classify_context("5111B") == "HURDLE"
    assert classify_context("5122D") == "HURDLE"

def test_context_twisting_backward_52xx():
    assert classify_context("5222A") == "STANDING"

def test_context_twisting_inward_54xx():
    assert classify_context("5411C") == "STANDING"

def test_context_freestyle_group_0():
    assert classify_context("010B") == "HURDLE"

def test_context_none_unknown():
    assert classify_context(None) == "UNKNOWN"
    assert classify_context("") == "UNKNOWN"

def test_context_platform_forward():
    assert classify_context("101B") == "HURDLE"


# ─── PTS-aware velocity (unchanged) ──────────────────────────────────────────

def test_pts_aware_velocity_uniform():
    pts = make_uniform_pts(10, fps=30.0)
    y = [0.5 + i * 0.01 for i in range(10)]
    vel = pts_aware_velocity(y, pts, max_gap_s=0.10)
    for i in range(1, 10):
        assert abs(vel[i] - 0.30) < 1e-6
    assert vel[0] is None

def test_pts_aware_velocity_vfr():
    pts = [0.0, 0.5, 0.6, 1.5]
    y =   [0.0, 0.5, 0.7, 0.0]
    vel = pts_aware_velocity(y, pts, max_gap_s=1.1)
    assert abs(vel[1] - 1.0) < 1e-9
    assert abs(vel[2] - 2.0) < 1e-9
    assert abs(vel[3] - (-0.7 / 0.9)) < 1e-6

def test_pts_aware_velocity_gap_too_large():
    pts = [0.0, 0.15, 0.25, 2.0]
    y =   [0.5, 0.6,  0.7,  0.8]
    vel = pts_aware_velocity(y, pts, max_gap_s=0.30)
    assert vel[3] is None
    assert vel[1] is not None
    assert vel[2] is not None

def test_pts_aware_velocity_none_obs():
    pts = make_uniform_pts(5)
    y = [0.5, None, 0.7, 0.8, 0.9]
    vel = pts_aware_velocity(y, pts, max_gap_s=0.20)
    assert vel[1] is None
    assert vel[2] is None


# ─── Smoothing (unchanged) ────────────────────────────────────────────────────

def test_pts_aware_smoothing_uses_window():
    n = 10
    pts = make_uniform_pts(n, fps=30.0)
    y = [0.50] * n
    y[5] = 0.80
    smoothed = pts_aware_smooth(y, pts, sigma_s=0.5)
    assert smoothed[5] < 0.80
    assert smoothed[5] > 0.50


# ─── Preparation plateau (convention-agnostic) ───────────────────────────────

def test_long_static_plateau_detected():
    n = 180
    pts = make_uniform_pts(n, fps=30.0)
    y = [None] * n
    for i in range(90):
        y[i] = 0.40 + (i % 3) * 0.0002
    for i in range(90, 180):
        y[i] = 0.40 - (i - 90) * 0.01  # cy_norm: rising = decreasing
    params = copy.deepcopy(PARAMS_E1)
    prep_end = _find_preparation_end(y, pts, params)
    assert prep_end is not None
    assert prep_end <= 90
    assert pts[prep_end] >= params["static_min_duration_s"]


def test_no_static_plateau_all_motion():
    n = 60
    pts = make_uniform_pts(n, fps=30.0)
    y = [0.40 - i * 0.005 for i in range(n)]  # always moving (vel ≈ 0.15/s)
    params = copy.deepcopy(PARAMS_E1)
    prep_end = _find_preparation_end(y, pts, params)
    assert prep_end is None


# ─── H1: Standing springboard integration ────────────────────────────────────

def test_h1_standing_integration():
    """H1 (standing): state machine must detect all three landmarks within tolerance."""
    pts, y, conf = make_h1_standing_trajectory(fps=60.0)
    params = copy.deepcopy(PARAMS_E1)
    result = propose_events(y, pts, conf, "201C", params)  # 201C = backward standing

    assert result["context"] == "STANDING"
    assert result["takeoff_t"] is not None, "H1: takeoff not detected"
    assert result["apex_t"] is not None, "H1: apex not detected"
    assert result["water_contact_t"] is not None, "H1: water_contact not detected"

    # Tolerances: takeoff ±0.50s, apex after takeoff, water_contact after apex
    assert abs(result["takeoff_t"] - 0.60) <= 0.50, \
        f"H1: takeoff error {result['takeoff_t'] - 0.60:+.3f}s > 0.50s"
    assert result["apex_t"] > result["takeoff_t"], "H1: apex before takeoff"
    assert result["water_contact_t"] > result["apex_t"], "H1: water_contact before apex"
    assert result["water_contact_t"] > 1.50, "H1: water_contact too early"


def test_h1_standing_no_hurdle_guard():
    """H1 (standing): takeoff detected without hurdle guard delay."""
    pts, y, conf = make_h1_standing_trajectory(fps=60.0)
    params = copy.deepcopy(PARAMS_E1)
    prep_end_idx = _find_preparation_end(
        pts_aware_smooth(y, pts, sigma_s=params["smooth_window_s"] / 3),
        pts, params
    )
    assert prep_end_idx is not None
    prep_end_t = pts[prep_end_idx]
    assert prep_end_t <= 0.55, f"H1: prep_end too late: {prep_end_t:.3f}s"


# ─── H2: Hurdle springboard integration ──────────────────────────────────────

def test_h2_hurdle_integration():
    """H2 (hurdle): state machine detects all three landmarks with correct timing."""
    pts, y, conf = make_h2_hurdle_trajectory(fps=60.0)
    params = copy.deepcopy(PARAMS_E1)
    result = propose_events(y, pts, conf, "5122D", params)

    assert result["context"] == "HURDLE"
    assert result["takeoff_t"] is not None, "H2: takeoff not detected"
    assert result["apex_t"] is not None, "H2: apex not detected"
    assert result["water_contact_t"] is not None, "H2: water_contact not detected"

    # takeoff should be after board loading (>2.0s) and before flight apex
    assert result["takeoff_t"] >= 2.0, \
        f"H2: takeoff too early: {result['takeoff_t']:.3f}s (expected >=2.0s, hurdle zone)"
    assert result["takeoff_t"] <= 3.2, \
        f"H2: takeoff too late: {result['takeoff_t']:.3f}s"
    assert result["apex_t"] > result["takeoff_t"], "H2: apex before takeoff"
    assert result["water_contact_t"] > result["apex_t"], "H2: water_contact before apex"


def test_h2_hurdle_not_takeoff_during_hurdle_ascent():
    """H2 (hurdle): takeoff is NOT detected during the hurdle ascent phase."""
    pts, y, conf = make_h2_hurdle_trajectory(fps=60.0)
    params = copy.deepcopy(PARAMS_E1)
    y_smooth = pts_aware_smooth(y, pts, sigma_s=params["smooth_window_s"] / 3)
    y_interp = interpolate_gaps_time(y_smooth, pts, max_gap_s=params["interp_max_gap_s"])
    vel_y = pts_aware_velocity(y_interp, pts, max_gap_s=params["vel_max_gap_s"])
    prep_end_idx = _find_preparation_end(y_interp, pts, params)

    takeoff_idx = _detect_takeoff(y_interp, vel_y, pts, prep_end_idx, "HURDLE", params)
    assert takeoff_idx is not None, "H2: takeoff not detected"
    # Must NOT be in hurdle ascent zone (0.5-1.0s)
    assert pts[takeoff_idx] >= 1.5, \
        f"H2: takeoff in hurdle zone at t={pts[takeoff_idx]:.3f}s"


def test_h2_hurdle_apex_after_final_takeoff():
    """H2: apex is detected AFTER the final takeoff, not at the hurdle apex."""
    pts, y, conf = make_h2_hurdle_trajectory(fps=60.0)
    params = copy.deepcopy(PARAMS_E1)
    result = propose_events(y, pts, conf, "5122D", params)

    assert result["takeoff_t"] is not None
    assert result["apex_t"] is not None
    # apex must be after the final takeoff AND before water contact
    assert result["apex_t"] > result["takeoff_t"] + 0.5, \
        f"H2: apex {result['apex_t']:.3f}s too close to takeoff {result['takeoff_t']:.3f}s"
    # apex must have minimum y (cy_norm) after takeoff — it's the highest physical point
    if result["water_contact_t"] is not None:
        assert result["apex_t"] < result["water_contact_t"], "H2: apex after water_contact"


# ─── H3: Long-preparation + hurdle integration ───────────────────────────────

def test_h3_long_prep_hurdle_integration():
    """H3 (long prep + hurdle): all three landmarks detected despite long plateau."""
    pts, y, conf = make_h3_long_prep_hurdle_trajectory(fps=60.0)
    params = copy.deepcopy(PARAMS_E1)
    result = propose_events(y, pts, conf, "101B", params)

    assert result["context"] == "HURDLE"
    assert result["takeoff_t"] is not None, "H3: takeoff not detected"
    assert result["apex_t"] is not None, "H3: apex not detected"
    assert result["water_contact_t"] is not None, "H3: water_contact not detected"

    # Long prep ends at ~2.0s, hurdle from 2.0-3.3s, board loading 3.3-4.0s
    assert result["takeoff_t"] >= 3.5, \
        f"H3: takeoff too early: {result['takeoff_t']:.3f}s (expected >=3.5s)"
    assert result["apex_t"] > result["takeoff_t"], "H3: apex before takeoff"
    assert result["water_contact_t"] > result["apex_t"], "H3: water_contact before apex"


def test_h3_long_prep_end_found():
    """H3: the long static plateau is correctly identified as preparation."""
    pts, y, conf = make_h3_long_prep_hurdle_trajectory(fps=60.0)
    params = copy.deepcopy(PARAMS_E1)
    y_smooth = pts_aware_smooth(y, pts, sigma_s=params["smooth_window_s"] / 3)
    prep_end = _find_preparation_end(y_smooth, pts, params)
    assert prep_end is not None
    # The 2.0s plateau should be found
    assert pts[prep_end] >= 1.5, f"H3: prep_end too early: {pts[prep_end]:.3f}s"
    assert pts[prep_end] <= 2.5, f"H3: prep_end too late: {pts[prep_end]:.3f}s"


# ─── Phase M REGRESSION — cy_norm-correct canary trajectory ──────────────────

def test_phase_m_regression_cy_norm_correct():
    """Phase M regression with CORRECT cy_norm trajectory (non-sinusoidal hurdle).

    This test WOULD HAVE FAILED for V2 due to the sinusoidal trajectory
    creating false board_recontact at t=0.444s.

    Ground truth from HIGHRES_CANARY_V2_EXACT_ANNOTATION.json:
      board_recontact = 2.668s
      takeoff = 3.120s
      apex = 3.570s
      water_contact = 4.220s
    """
    GT = {
        "board_recontact_t": 2.668,
        "takeoff_t": 3.120,
        "apex_t": 3.570,
        "water_contact_t": 4.220,
        "total_duration_s": 5.372,
        "dive_code": "5122D",
    }
    fps = 60.0
    n = int(GT["total_duration_s"] * fps) + 1
    pts = [i / fps for i in range(n)]
    y = []
    conf = []

    for t in pts:
        if t <= 0.50:
            # Static preparation
            y.append(0.40)
            conf.append(0.85)
        elif t <= GT["board_recontact_t"] * 0.60:
            # Hurdle ascent: y DECREASES (diver rises) - NON-SINUSOIDAL
            frac = (t - 0.50) / (GT["board_recontact_t"] * 0.60 - 0.50)
            y.append(0.40 - 0.22 * frac)  # 0.40 → 0.18
            conf.append(0.80)
        elif t <= GT["board_recontact_t"]:
            # Hurdle descent: y INCREASES (diver falls to board)
            frac = (t - GT["board_recontact_t"] * 0.60) / (GT["board_recontact_t"] * 0.40)
            y.append(0.18 + 0.26 * frac)  # 0.18 → 0.44
            conf.append(0.80)
        elif t <= GT["takeoff_t"]:
            # Board loading: stable (slight increase = board compresses)
            frac = (t - GT["board_recontact_t"]) / (GT["takeoff_t"] - GT["board_recontact_t"])
            y.append(0.44 + 0.01 * frac)  # 0.44 → 0.45
            conf.append(0.82)
        elif t <= GT["apex_t"]:
            # Final takeoff ascent: y DECREASES (diver rises)
            frac = (t - GT["takeoff_t"]) / (GT["apex_t"] - GT["takeoff_t"])
            y.append(0.45 - 0.33 * frac)  # 0.45 → 0.12
            conf.append(0.78)
        elif t <= GT["water_contact_t"]:
            # Descent: y INCREASES (diver falls)
            frac = (t - GT["apex_t"]) / (GT["water_contact_t"] - GT["apex_t"])
            y.append(0.12 + 0.42 * frac)  # 0.12 → 0.54
            conf.append(0.72)
        else:
            y.append(0.54 + 0.02 * (t - GT["water_contact_t"]))
            conf.append(0.30)

    params = copy.deepcopy(PARAMS_E1)
    result = propose_events(y, pts, conf, GT["dive_code"], params)

    assert result["context"] == "HURDLE"
    assert result["takeoff_t"] is not None, "Phase M regression: takeoff not detected"
    assert result["apex_t"] is not None, "Phase M regression: apex not detected"
    assert result["water_contact_t"] is not None, "Phase M regression: water_contact not detected"

    tko_err = result["takeoff_t"] - GT["takeoff_t"]
    apex_err = result["apex_t"] - GT["apex_t"]
    wc_err = result["water_contact_t"] - GT["water_contact_t"]

    assert abs(tko_err) <= 0.50, \
        f"Phase M regression: takeoff error {tko_err:+.3f}s exceeds 0.50s tolerance"
    assert result["apex_t"] > result["takeoff_t"], \
        "Phase M regression: apex before takeoff"
    assert abs(wc_err) <= 0.50, \
        f"Phase M regression: water_contact error {wc_err:+.3f}s exceeds 0.50s tolerance"


# ─── Hurdle not detected during hurdle ascent (cy_norm version) ──────────────

def test_hurdle_not_takeoff_during_hurdle_ascent_cy_norm():
    """In cy_norm, hurdle ascent has NEGATIVE velocity. Takeoff not detected there."""
    n = 300
    fps = 30.0
    pts = make_uniform_pts(n, fps=fps)
    y = [None] * n
    # Static plateau: 0-59 (2s)
    for i in range(60):
        y[i] = 0.40
    # Hurdle ascent: 60-89 (1s) — y DECREASES (rising in cy_norm)
    for i in range(60, 90):
        frac = (i - 60) / 30.0
        y[i] = 0.40 - 0.15 * math.sin(frac * math.pi)  # 0.40 → 0.25 → 0.40
    # Board loading: 90-109
    for i in range(90, 110):
        y[i] = 0.40
    # Final takeoff: 110+, y DECREASES strongly
    for i in range(110, n):
        y[i] = 0.40 - (i - 110) * 0.006

    vel = pts_aware_velocity(y, pts, max_gap_s=0.10)
    params = copy.deepcopy(PARAMS_E1)
    prep_end = _find_preparation_end(y, pts, params)
    takeoff = _detect_takeoff(y, vel, pts, prep_end, "HURDLE", params)

    if takeoff is not None:
        # Must NOT be in hurdle ascent zone (frames 60-89)
        assert pts[takeoff] >= pts[90], \
            f"Hurdle motion at t={pts[takeoff]:.2f}s should not be takeoff"


# ─── Standing takeoff detected (cy_norm version) ─────────────────────────────

def test_standing_takeoff_cy_norm():
    """Standing: takeoff detected when y DECREASES (diver rises in cy_norm)."""
    n = 120
    fps = 30.0
    pts = make_uniform_pts(n, fps=fps)
    y = [None] * n
    # Static plateau: 0-59
    for i in range(60):
        y[i] = 0.40
    # Takeoff: y DECREASES (rising)
    for i in range(60, 120):
        y[i] = 0.40 - (i - 60) * 0.007

    vel = pts_aware_velocity(y, pts, max_gap_s=0.10)
    params = copy.deepcopy(PARAMS_E1)
    prep_end = _find_preparation_end(y, pts, params)
    takeoff = _detect_takeoff(y, vel, pts, prep_end, "STANDING", params)

    assert takeoff is not None, "Standing takeoff should be detected"
    if takeoff is not None and prep_end is not None:
        assert pts[takeoff] < pts[prep_end] + 2.0, "Takeoff should occur soon after plateau"


# ─── Board loading does not prevent final takeoff (cy_norm) ──────────────────

def test_board_return_and_final_takeoff_cy_norm():
    """Board loading (stable y) after hurdle descent does not block final takeoff."""
    n = 300
    fps = 30.0
    pts = make_uniform_pts(n, fps=fps)
    y = [None] * n
    # Static: 0-59
    for i in range(60):
        y[i] = 0.40
    # Hurdle ascent: 60-79 — y DECREASES
    for i in range(60, 80):
        y[i] = 0.40 - (i - 60) * 0.008
    # Hurdle descent: 80-109 — y INCREASES
    for i in range(80, 110):
        y[i] = 0.24 + (i - 80) * 0.006
    # Board loading stable: 110-129
    for i in range(110, 130):
        y[i] = 0.42
    # Final takeoff: 130+, y DECREASES strongly
    for i in range(130, n):
        y[i] = 0.42 - (i - 130) * 0.007

    vel = pts_aware_velocity(y, pts, max_gap_s=0.10)
    params = copy.deepcopy(PARAMS_E1)
    prep_end = _find_preparation_end(y, pts, params)
    takeoff = _detect_takeoff(y, vel, pts, prep_end, "HURDLE", params)

    assert takeoff is not None, "Final takeoff after board loading should be detected"
    if takeoff is not None:
        assert pts[takeoff] >= pts[129], "Takeoff must be after board loading"


# ─── Apex search restricted after takeoff (cy_norm) ──────────────────────────

def test_apex_restricted_after_takeoff_cy_norm():
    """Apex search in cy_norm: minimum y AFTER takeoff frame."""
    n = 120
    fps = 30.0
    pts = make_uniform_pts(n, fps=fps)
    y = [None] * n
    # Some pre-takeoff minimum at frame 20 (y low = high position in cy_norm)
    for i in range(40):
        y[i] = 0.30 + abs(i - 20) * 0.005  # minimum at frame 20
    # Static: 40-59
    for i in range(40, 60):
        y[i] = 0.50
    # Flight arc after takeoff at frame 60: y decreases then increases
    for i in range(60, 100):
        # Arc: peaks (minimum y) at frame 80
        y[i] = 0.50 - (20 - abs(i - 80)) * 0.008
    for i in range(100, 120):
        y[i] = 0.34 + (i - 100) * 0.005

    vel = pts_aware_velocity(y, pts, max_gap_s=0.10)
    params = copy.deepcopy(PARAMS_E1)
    apex = _detect_apex(y, vel, pts, takeoff_idx=60, params=params)
    assert apex is not None
    assert apex > 60, "Apex must be after takeoff frame"


def test_preparation_extrema_not_apex_cy_norm():
    """Pre-takeoff minimum (high position in cy_norm) not returned as apex."""
    n = 180
    fps = 30.0
    pts = make_uniform_pts(n, fps=fps)
    y = [None] * n
    # Pre-takeoff minimum at frame 30 (very low cy_norm = high physical)
    for i in range(60):
        y[i] = 0.20 + abs(i - 30) * 0.003  # minimum at 30
    # After takeoff (frame 90): regular flight arc with min at frame 120
    for i in range(60, 180):
        y[i] = 0.50 - max(0, (30 - abs(i - 120))) * 0.005

    vel = pts_aware_velocity(y, pts, max_gap_s=0.10)
    params = copy.deepcopy(PARAMS_E1)
    apex = _detect_apex(y, vel, pts, takeoff_idx=90, params=params)
    assert apex is None or apex >= 90, "Apex must not be before takeoff"


# ─── PTS-aware derivative (unchanged) ────────────────────────────────────────

def test_pts_aware_derivative_not_hardcoded_fps():
    for fps in [24.0, 60.0]:
        n = int(fps * 1.0)
        pts = [i / fps for i in range(n)]
        # y DECREASING at 0.4/0.5 = 0.8 /s (rising in cy_norm)
        y = [0.7 - 0.4 * (i / fps) / 0.5 if i / fps <= 0.5 else 0.3 for i in range(n)]
        vel = pts_aware_velocity(y, pts, max_gap_s=1.0 / fps + 0.01)
        rising_vels = [vel[i] for i in range(1, int(0.45 * fps)) if vel[i] is not None]
        if rising_vels:
            mean_vel = sum(rising_vels) / len(rising_vels)
            # Velocity should be ≈ -0.8 (negative = rising in cy_norm)
            assert abs(mean_vel - (-0.8)) < 0.15, \
                f"fps={fps}: mean vel {mean_vel:.3f} should be ≈ -0.8"


# ─── Water contact (unchanged) ───────────────────────────────────────────────

def test_water_contact_not_last_frame():
    """Water contact detected before end of clip."""
    n = 200
    fps = 30.0
    pts = make_uniform_pts(n, fps=fps)
    y = [None] * n
    # Flight: descent phase — y starts low (apex min) then increases
    for i in range(50, 200):
        y[i] = 0.15 + (i - 50) * 0.003
    vel = pts_aware_velocity(y, pts, max_gap_s=0.10)
    conf = [0.8] * n
    params = copy.deepcopy(PARAMS_E1)
    params["water_line_cy_norm"] = 0.40  # water line
    water = _detect_water_contact(y, vel, conf, pts, apex_idx=50, params=params)
    assert water is not None
    assert water < n - 1


# ─── Standing vs hurdle path ──────────────────────────────────────────────────

def test_standing_takeoff_before_or_equal_hurdle_cy_norm():
    """Standing context finds takeoff earlier than hurdle (no guard applied)."""
    n = 180
    fps = 30.0
    pts = make_uniform_pts(n, fps=fps)
    # Static 0-59, then y DECREASES (takeoff in cy_norm)
    y = [0.40] * 60 + [0.40 - i * 0.006 for i in range(120)]
    vel = pts_aware_velocity(y, pts, max_gap_s=0.10)
    params = copy.deepcopy(PARAMS_E1)
    prep_end = _find_preparation_end(y, pts, params)
    takeoff_standing = _detect_takeoff(y, vel, pts, prep_end, "STANDING", params)
    takeoff_hurdle = _detect_takeoff(y, vel, pts, prep_end, "HURDLE", params)
    if takeoff_standing is not None and takeoff_hurdle is not None:
        assert pts[takeoff_standing] <= pts[takeoff_hurdle], \
            "Standing takeoff should not be later than hurdle takeoff"


# ─── Missing scene geometry fallback ─────────────────────────────────────────

def test_missing_scene_geometry_fallback():
    """E1 (no scene priors) does not crash without board/water geometry."""
    n = 60
    fps = 30.0
    pts = make_uniform_pts(n, fps=fps)
    # Simple descent trajectory
    y = [0.20] * 20 + [0.20 + i * 0.010 for i in range(20)] + \
        [0.40 + i * 0.010 for i in range(20)]
    vel = pts_aware_velocity(y, pts, max_gap_s=0.10)
    conf = [0.8] * n
    params = copy.deepcopy(PARAMS_E1)
    assert not params.get("use_scene_priors")
    water = _detect_water_contact(y, vel, conf, pts, apex_idx=20, params=params)
    # Result may be None or a frame — must not raise


# ─── E1/E2 parameter existence ───────────────────────────────────────────────

def test_params_e1_all_required_keys():
    required = [
        "variant", "detector", "smooth_window_s", "static_var_threshold",
        "static_min_duration_s", "takeoff_vel_threshold", "takeoff_sustained_s",
        "takeoff_min_after_prep_s", "hurdle_post_plateau_guard_s",
        "apex_search_start_s", "water_line_cy_norm", "min_coverage_for_confident",
    ]
    for k in required:
        assert k in PARAMS_E1, f"Missing required parameter: {k}"

def test_params_e2_extends_e1():
    assert PARAMS_E2["use_scene_priors"] is True
    assert PARAMS_E1["use_scene_priors"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
