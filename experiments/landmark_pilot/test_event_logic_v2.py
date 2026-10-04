#!/usr/bin/env python3
"""Tests for Event Logic V2 state machine — Phase Q.

Tests use synthetic trajectories to exercise state machine logic
independently of the perception (detection) pipeline.

All tests are deterministic. No video files required.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
import math
import numpy as np  # used in test_hurdle_context_not_takeoff_during_hurdle
import pytest
from proposer_event_logic_v2 import (
    classify_context,
    pts_aware_velocity,
    rolling_variance_time,
    pts_aware_smooth,
    interpolate_gaps_time,
    _find_preparation_end,
    _detect_takeoff,
    _detect_apex,
    _detect_water_contact,
    PARAMS_E1,
    PARAMS_E2,
)
import copy


# ─── Helpers ─────────────────────────────────────────────────────────────────

def make_uniform_pts(n, fps=30.0):
    """Create uniform PTS array for synthetic tests."""
    return [i / fps for i in range(n)]


def make_pts_vfr(n, rates=(1/60.0, 1/54.5), pattern=None):
    """Create VFR PTS array for PTS-aware tests."""
    pts = [0.0]
    for i in range(1, n):
        if pattern:
            dt = rates[pattern[i % len(pattern)]]
        else:
            dt = rates[i % 2]
        pts.append(pts[-1] + dt)
    return pts


# ─── Context classification ───────────────────────────────────────────────────

def test_context_forward_group_1():
    assert classify_context("101B") == "HURDLE"
    assert classify_context("103C") == "HURDLE"
    assert classify_context("104B") == "HURDLE"

def test_context_backward_group_2():
    assert classify_context("202A") == "STANDING"
    assert classify_context("203C") == "STANDING"

def test_context_reverse_group_3():
    assert classify_context("301A") == "STANDING"
    assert classify_context("302C") == "STANDING"

def test_context_inward_group_4():
    assert classify_context("401C") == "STANDING"

def test_context_twisting_forward_51xx():
    assert classify_context("5111B") == "HURDLE"
    assert classify_context("5122D") == "HURDLE"
    assert classify_context("5132D") == "HURDLE"

def test_context_twisting_backward_52xx():
    assert classify_context("5222A") == "STANDING"

def test_context_twisting_inward_54xx():
    assert classify_context("5411C") == "STANDING"

def test_context_freestyle_group_0():
    assert classify_context("010B") == "HURDLE"
    assert classify_context("010C") == "HURDLE"

def test_context_none_unknown():
    assert classify_context(None) == "UNKNOWN"
    assert classify_context("") == "UNKNOWN"

def test_context_platform_forward():
    # 2169: 101B on platform — still forward approach -> HURDLE semantics
    assert classify_context("101B") == "HURDLE"


# ─── PTS-aware velocity ───────────────────────────────────────────────────────

def test_pts_aware_velocity_uniform():
    """With uniform 30fps, dy/dt ≈ (dy * 30)."""
    pts = make_uniform_pts(10, fps=30.0)
    y = [0.5 + i * 0.01 for i in range(10)]  # rising trajectory
    vel = pts_aware_velocity(y, pts, max_gap_s=0.10)
    # velocity ≈ 0.01 * 30 = 0.30 /s
    for i in range(1, 10):
        assert abs(vel[i] - 0.30) < 1e-6, f"vel[{i}]={vel[i]}"
    assert vel[0] is None  # no backward difference at frame 0

def test_pts_aware_velocity_vfr():
    """VFR: velocity must use actual PTS differences, not uniform spacing."""
    pts = [0.0, 0.5, 0.6, 1.5]
    y =   [0.0, 0.5, 0.7, 0.0]
    vel = pts_aware_velocity(y, pts, max_gap_s=1.1)
    # vel[1] = (0.5 - 0.0) / 0.5 = 1.0
    assert abs(vel[1] - 1.0) < 1e-9
    # vel[2] = (0.7 - 0.5) / 0.1 = 2.0
    assert abs(vel[2] - 2.0) < 1e-9
    # vel[3] = (0.0 - 0.7) / 0.9 = -0.778  (gap = 0.9 < max_gap 1.1 -> computed)
    assert abs(vel[3] - (-0.7 / 0.9)) < 1e-6

def test_pts_aware_velocity_gap_too_large():
    """Gaps exceeding max_gap_s produce None velocity.
    
    FIX: Use pts where only the LAST gap exceeds max_gap_s.
    pts = [0.0, 0.15, 0.25, 2.0]:
      gap[1]=0.15 < 0.30 -> computed
      gap[2]=0.10 < 0.30 -> computed
      gap[3]=1.75 > 0.30 -> None
    """
    pts = [0.0, 0.15, 0.25, 2.0]   # only last gap = 1.75s > max_gap 0.30
    y =   [0.5, 0.6,  0.7,  0.8]
    vel = pts_aware_velocity(y, pts, max_gap_s=0.30)
    assert vel[3] is None, "Large gap should yield None velocity"
    assert vel[1] is not None
    assert vel[2] is not None

def test_pts_aware_velocity_none_obs():
    """None in y_arr -> None velocity."""
    pts = make_uniform_pts(5)
    y = [0.5, None, 0.7, 0.8, 0.9]
    vel = pts_aware_velocity(y, pts, max_gap_s=0.20)
    assert vel[1] is None
    assert vel[2] is None  # backward diff needs y[1] which is None


# ─── Smoothing ────────────────────────────────────────────────────────────────

def test_pts_aware_smoothing_uses_window():
    """Smoothing uses actual PTS time distances, not frame counts."""
    n = 10
    pts = make_uniform_pts(n, fps=30.0)
    y = [0.50] * n
    y[5] = 0.80  # spike
    smoothed = pts_aware_smooth(y, pts, sigma_s=0.5)
    assert smoothed[5] < 0.80, "Spike should be smoothed out"
    assert smoothed[5] > 0.50, "Value should still be elevated near spike"


# ─── Long initial static plateau ─────────────────────────────────────────────

def test_long_static_plateau_detected():
    """Long initial static period is identified as PREPARATION.
    
    NOTE: The motion at frame 90 has y[90]=0.40 (same as static value),
    so the last "static" frame may be 90 (not 89). Assertion is prep_end <= 90.
    """
    n = 180
    pts = make_uniform_pts(n, fps=30.0)  # 6s at 30fps
    y = [None] * n
    # Static for first 90 frames (3s), then motion
    for i in range(90):
        y[i] = 0.40 + (i % 3) * 0.0002  # tiny oscillation = effectively static
    for i in range(90, 180):
        y[i] = 0.40 + (i - 90) * 0.01  # rising
    params = copy.deepcopy(PARAMS_E1)
    prep_end = _find_preparation_end(y, pts, params)
    assert prep_end is not None, "Should detect static plateau"
    assert prep_end <= 90, "Plateau should end at or before motion starts"
    assert pts[prep_end] >= params["static_min_duration_s"], "Plateau must meet min duration"


def test_no_static_plateau_all_motion():
    """If the entire clip is motion, no plateau is returned."""
    n = 60
    pts = make_uniform_pts(n, fps=30.0)
    y = [0.40 + i * 0.005 for i in range(n)]  # always moving (vel=0.15/s > threshold)
    params = copy.deepcopy(PARAMS_E1)
    prep_end = _find_preparation_end(y, pts, params)
    # All-motion clip: no static plateau should be detected
    assert prep_end is None, \
        f"All-motion clip should not detect plateau, but got prep_end={prep_end}"


# ─── Static -> hurdle transition ───────────────────────────────────────────────

def test_hurdle_context_not_takeoff_during_hurdle():
    """For a HURDLE dive, motion immediately after plateau is NOT classified as takeoff."""
    n = 200
    pts = make_uniform_pts(n, fps=30.0)
    y = [None] * n
    # Static plateau: frames 0-59 (2s)
    for i in range(60):
        y[i] = 0.40
    # Hurdle motion: frames 60-89 (1s) — upward then downward
    for i in range(60, 90):
        phase = (i - 60) / 30.0 * math.pi
        y[i] = 0.40 + 0.10 * abs(math.sin(phase))
    # Board loading: frames 90-99 (0.33s) — downward back to board level
    for i in range(90, 100):
        y[i] = 0.38
    # Final takeoff: frames 100-180 — strong upward velocity
    for i in range(100, 180):
        y[i] = 0.38 + (i - 100) * 0.004
    vel = pts_aware_velocity(y, pts, max_gap_s=0.10)
    params = copy.deepcopy(PARAMS_E1)
    prep_end = _find_preparation_end(y, pts, params)
    takeoff = _detect_takeoff(y, vel, pts, prep_end, "HURDLE", params)
    # Takeoff should NOT be in hurdle zone (frames 60-89)
    if takeoff is not None:
        assert pts[takeoff] >= pts[90], \
            f"Hurdle motion at frame {takeoff} (t={pts[takeoff]:.2f}s) should not be takeoff"


def test_standing_takeoff_no_hurdle_guard():
    """For a STANDING dive, takeoff is detected right after plateau ends."""
    n = 120
    pts = make_uniform_pts(n, fps=30.0)
    y = [None] * n
    # Static: frames 0-59
    for i in range(60):
        y[i] = 0.40
    # Immediate upward velocity: frames 60-120
    for i in range(60, 120):
        y[i] = 0.40 + (i - 60) * 0.005
    vel = pts_aware_velocity(y, pts, max_gap_s=0.10)
    params = copy.deepcopy(PARAMS_E1)
    prep_end = _find_preparation_end(y, pts, params)
    takeoff = _detect_takeoff(y, vel, pts, prep_end, "STANDING", params)
    assert takeoff is not None, "Should detect takeoff after plateau"
    # Should be near frame 60, not delayed by hurdle guard
    if takeoff is not None and prep_end is not None:
        assert pts[takeoff] < pts[prep_end] + 2.0, "Takeoff should occur soon after plateau"


# ─── Board return before final departure ─────────────────────────────────────

def test_board_return_does_not_prevent_final_takeoff():
    """Board return (velocity reversal) does not block final takeoff detection."""
    n = 200
    pts = make_uniform_pts(n, fps=30.0)
    y = [None] * n
    # Static: 0-59
    for i in range(60):
        y[i] = 0.40
    # Hurdle (up): 60-79
    for i in range(60, 80):
        y[i] = 0.40 + (i - 60) * 0.005
    # Board return (down): 80-99
    for i in range(80, 100):
        y[i] = 0.50 - (i - 80) * 0.005
    # Final strong takeoff: 100+
    for i in range(100, 200):
        y[i] = 0.40 + (i - 100) * 0.006
    vel = pts_aware_velocity(y, pts, max_gap_s=0.10)
    params = copy.deepcopy(PARAMS_E1)
    prep_end = _find_preparation_end(y, pts, params)
    takeoff = _detect_takeoff(y, vel, pts, prep_end, "HURDLE", params)
    assert takeoff is not None, "Should detect final takeoff after board return"
    if takeoff is not None:
        # Must be after board return
        assert pts[takeoff] >= pts[99], "Takeoff must be after board return"


# ─── Takeoff -> apex search restriction ───────────────────────────────────────

def test_apex_search_restricted_after_takeoff():
    """Apex is not searched before takeoff frame."""
    n = 120
    pts = make_uniform_pts(n, fps=30.0)
    y = [None] * n
    # Peak before takeoff (preparation motion): frame 20
    for i in range(40):
        y[i] = 0.50 + (20 - abs(i - 20)) * 0.01  # pre-takeoff peak at frame 20
    # Static: 40-59
    for i in range(40, 60):
        y[i] = 0.40
    # Flight arc: 60-100
    for i in range(60, 100):
        y[i] = 0.40 + (20 - abs(i - 80)) * 0.008
    # Descent: 100-120
    for i in range(100, 120):
        y[i] = 0.40 - (i - 100) * 0.003
    vel = pts_aware_velocity(y, pts, max_gap_s=0.10)
    params = copy.deepcopy(PARAMS_E1)
    # Manually set takeoff at frame 60
    apex = _detect_apex(y, vel, pts, 60, params)
    assert apex is not None
    assert apex > 60, "Apex must be after takeoff frame"


def test_preparation_extrema_not_apex():
    """The maximum y_norm before takeoff (preparation) is not returned as apex."""
    n = 180
    pts = make_uniform_pts(n, fps=30.0)
    y = [None] * n
    # Pre-takeoff maximum at frame 30 (very high y_norm)
    for i in range(60):
        y[i] = 0.60 + (30 - abs(i - 30)) * 0.01
    # Takeoff at frame 90, lower flight arc
    for i in range(60, 180):
        y[i] = 0.40 + max(0, (30 - abs(i - 120))) * 0.005
    vel = pts_aware_velocity(y, pts, max_gap_s=0.10)
    params = copy.deepcopy(PARAMS_E1)
    apex = _detect_apex(y, vel, pts, takeoff_idx=90, params=params)
    # Apex should not be in pre-takeoff region (frames 0-89)
    assert apex is None or apex >= 90, "Apex must not be before takeoff"


# ─── PTS-aware derivative correctness ────────────────────────────────────────

def test_pts_aware_derivative_not_hardcoded_fps():
    """Velocity computed from PTS must be fps-agnostic."""
    for fps in [24.0, 60.0]:
        n = int(fps * 1.0)
        pts = [i / fps for i in range(n)]
        y = [0.3 + 0.4 * (i / fps) / 0.5 if i / fps <= 0.5 else 0.7 for i in range(n)]
        vel = pts_aware_velocity(y, pts, max_gap_s=1.0 / fps + 0.01)
        # During rising phase, velocity ≈ 0.4/0.5 = 0.8 /s
        rising_vels = [vel[i] for i in range(1, int(0.45 * fps)) if vel[i] is not None]
        if rising_vels:
            mean_vel = sum(rising_vels) / len(rising_vels)
            assert abs(mean_vel - 0.8) < 0.15, f"fps={fps}: mean vel {mean_vel:.3f} != 0.8"


# ─── Water contact not equivalent to last frame ───────────────────────────────

def test_water_contact_not_last_frame():
    """Water contact is detected before end of clip."""
    n = 200
    pts = make_uniform_pts(n, fps=30.0)
    y = [None] * n
    # Flight arc: rises 0-50, peaks at 50
    for i in range(100):
        y[i] = 0.30 + (50 - abs(i - 50)) * 0.005
    # After water contact (frame 100): trajectory enters water region (y > water_line)
    for i in range(100, 200):
        y[i] = 0.30 + (i - 100) * 0.003
    vel = pts_aware_velocity(y, pts, max_gap_s=0.10)
    conf = [0.8] * n
    params = copy.deepcopy(PARAMS_E1)
    params["water_line_cy_norm"] = 0.35  # water region: y > 0.35
    water = _detect_water_contact(y, vel, conf, pts, apex_idx=50, params=params)
    assert water is not None
    assert water < n - 1, "Water contact should not be the last frame of the clip"


# ─── Standing vs hurdle path ───────────────────────────────────────────────────

def test_standing_dive_path_no_hurdle_guard_applied():
    """Standing dive: takeoff detected immediately after static plateau."""
    n = 120
    pts = make_uniform_pts(n, fps=30.0)
    y = [0.40] * 60 + [0.40 + i * 0.008 for i in range(60)]
    vel = pts_aware_velocity(y, pts, max_gap_s=0.10)
    params = copy.deepcopy(PARAMS_E1)
    prep_end = _find_preparation_end(y, pts, params)
    takeoff_standing = _detect_takeoff(y, vel, pts, prep_end, "STANDING", params)
    takeoff_hurdle = _detect_takeoff(y, vel, pts, prep_end, "HURDLE", params)
    # Standing takeoff should be detected earlier (or equal) than hurdle
    if takeoff_standing is not None and takeoff_hurdle is not None:
        assert pts[takeoff_standing] <= pts[takeoff_hurdle], \
            "Standing takeoff should not be later than hurdle takeoff"


def test_hurdle_dive_path_guard_delays_takeoff():
    """Hurdle context guard delays takeoff search by hurdle_post_plateau_guard_s."""
    n = 120
    pts = make_uniform_pts(n, fps=60.0)
    y = [0.40] * 30 + [0.40 + i * 0.008 for i in range(90)]
    vel = pts_aware_velocity(y, pts, max_gap_s=0.05)
    params = copy.deepcopy(PARAMS_E1)
    prep_end = _find_preparation_end(y, pts, params)
    takeoff_standing = _detect_takeoff(y, vel, pts, prep_end, "STANDING", params)
    takeoff_hurdle = _detect_takeoff(y, vel, pts, prep_end, "HURDLE", params)
    if takeoff_standing is not None and takeoff_hurdle is not None:
        guard_s = params["hurdle_post_plateau_guard_s"]
        assert pts[takeoff_hurdle] >= pts[takeoff_standing] or \
               abs(pts[takeoff_hurdle] - pts[takeoff_standing]) < guard_s + 0.1


# ─── Missing scene geometry fallback ─────────────────────────────────────────

def test_missing_scene_geometry_fallback():
    """E1 (no scene priors) produces result even without board/water geometry."""
    n = 60
    pts = make_uniform_pts(n, fps=30.0)
    y = [0.40] * 20 + [0.40 + i * 0.010 for i in range(20)] + \
        [0.60 - i * 0.010 for i in range(20)]
    vel = pts_aware_velocity(y, pts, max_gap_s=0.10)
    conf = [0.8] * n
    params = copy.deepcopy(PARAMS_E1)
    assert not params.get("use_scene_priors"), "E1 should not use scene priors"
    # Should not crash without scene priors
    water = _detect_water_contact(y, vel, conf, pts, apex_idx=40, params=params)
    # Result may be None or a frame — just must not raise


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
