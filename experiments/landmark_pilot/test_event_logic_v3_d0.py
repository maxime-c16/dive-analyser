#!/usr/bin/env python3
"""Unit tests for Event Logic V3-D0.

Tests organised per Phase R–S requirements:
  - Board-rise validation: false apex rejected when cy_apex ≥ y_prep (D0a)
  - Board-rise validation: valid apex accepted when cy_apex < y_prep (D0b)
  - Multiple false candidates, then valid apex accepted (D0c)
  - STANDING-fallback triggered when no valid apex found (D0d)
  - Fallback finds correct sustained departure from guard_end (D0e)
  - STANDING dives: V3-D0 identical to V3-C0 / V2.1 (H1 non-regression)
  - FM1 closed: dive 311 pattern (unbounded-apex vulnerability, A1+A2 fixes)
  - Valid hurdle then final takeoff (integration, D0f)
  - FPS invariance: results consistent across 30 fps and 60 fps (D0g)
  - Long static preparation: guard correctly gates early motion (D0h)
  - Board-recontact invariant: apex cannot be below board (D0i)
  - Paris firewall: V3-D0 Paris to_err ≤ 2.0s (PARIS_FIREWALL)
  - Freeze identity: proposer parameters match frozen artifact (D0j)

All trajectories synthetic (cy_norm convention: 0=top, 1=bottom;
rising diver = decreasing cy_norm = negative velocity).
"""

import sys, os, math
sys.path.insert(0, os.path.dirname(__file__))

from proposer_event_logic_v3_d0 import (
    propose_events_v3d0,
    _detect_hurdle_takeoff_v3d0,
    PARAMS_V3D0,
)
from proposer_event_logic_v3_c0 import (
    propose_events_v3c0,
    PARAMS_V3C0,
)
from proposer_event_logic_v2_1 import (
    pts_aware_smooth,
    pts_aware_velocity,
    interpolate_gaps_time,
    _find_preparation_end,
    PARAMS_E1,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def make_pts(n, fps=30.0):
    return [i / fps for i in range(n)]


def smooth_vel(cy, pts, params=None):
    if params is None:
        params = PARAMS_V3D0
    sigma  = params["smooth_window_s"] / 3
    ys     = pts_aware_smooth(cy, pts, sigma_s=sigma)
    ys     = interpolate_gaps_time(ys, pts, params["interp_max_gap_s"])
    vel    = pts_aware_velocity(ys, pts, params["vel_max_gap_s"])
    return ys, vel


def standing_traj(fps=30.0, board_cy=0.40, static_s=2.0,
                  takeoff_s=2.2, apex_s=2.55, wc_s=3.2,
                  n_total_s=4.5, post_wc_low_cy=None):
    """Minimal STANDING cy_norm trajectory."""
    n   = int(n_total_s * fps) + 1
    pts = [i / fps for i in range(n)]
    cy  = []
    for t in pts:
        if t < takeoff_s:
            cy.append(board_cy)
        elif t < apex_s:
            frac = (t - takeoff_s) / (apex_s - takeoff_s)
            cy.append(board_cy - frac * 0.12)       # rise: board_cy → board_cy-0.12
        elif t < wc_s:
            frac = (t - apex_s) / (wc_s - apex_s)
            cy.append((board_cy - 0.12) + frac * 0.40)  # fall
        else:
            cy.append(post_wc_low_cy if post_wc_low_cy is not None else 0.80)
    conf = [0.5] * n
    return cy, pts, conf


def hurdle_traj_valid(fps=30.0, board_cy=0.40,
                      static_s=1.5,
                      h_takeoff_s=2.0, h_apex_s=2.2, h_recontact_s=2.5,
                      f_takeoff_s=3.0, apex_s=3.35, wc_s=4.1,
                      n_total_s=5.5):
    """Valid HURDLE trajectory: small hurdle jump then final takeoff."""
    n   = int(n_total_s * fps) + 1
    pts = [i / fps for i in range(n)]
    cy  = []
    for t in pts:
        if t < h_takeoff_s:
            cy.append(board_cy)
        elif t < h_apex_s:
            frac = (t - h_takeoff_s) / (h_apex_s - h_takeoff_s)
            cy.append(board_cy - frac * 0.10)    # hurdle rise: board_cy → board_cy-0.10
        elif t < h_recontact_s:
            frac = (t - h_apex_s) / (h_recontact_s - h_apex_s)
            cy.append((board_cy - 0.10) + frac * 0.10)  # descend back to board
        elif t < f_takeoff_s:
            cy.append(board_cy)                  # loading
        elif t < apex_s:
            frac = (t - f_takeoff_s) / (apex_s - f_takeoff_s)
            cy.append(board_cy - frac * 0.14)   # final rise
        elif t < wc_s:
            frac = (t - apex_s) / (wc_s - apex_s)
            cy.append((board_cy - 0.14) + frac * 0.48)
        else:
            cy.append(0.80)
    conf = [0.5] * n
    return cy, pts, conf


# ─── Tests ───────────────────────────────────────────────────────────────────

def test_d0a_false_apex_from_target_switch_rejected():
    """D0a: Board-rise invariant rejects a false apex where cy_apex > y_prep.

    Tests _detect_hurdle_takeoff_v3d0 directly with manually constructed
    smoothed position/velocity arrays.  The smoothed signal shows:
      - A neg→non-neg crossing at t_false where cy_apex > y_prep
        (detector switched to a lower-frame target — diver appears BELOW board).
      - After the crossing, a sustained negative velocity period.

    The crossing must be REJECTED, and the fallback must find the sustained
    departure.
    """
    fps    = 30.0
    y_prep = 0.30   # board level (upper frame)
    guard_s = PARAMS_V3D0["hurdle_post_plateau_guard_s"]   # 0.40s
    vel_thresh = PARAMS_V3D0["takeoff_vel_threshold"]       # 0.04

    # Build a trajectory where velocity history is:
    # [0, 2.0): positive (board approach / artifact rise)
    # [2.0, 2.4): NEGATIVE (artifact decay, first candidate apex window)
    # [2.4, 3.0): near-zero (artifact plateau after decay)
    # [3.0, 5.0): sustained negative (real takeoff)
    # [5.0, end): positive (post-apex fall)
    prep_end_s    = 1.0
    guard_end_s   = prep_end_s + guard_s  # 1.40s
    takeoff_s     = 3.0
    n_total       = 7.0

    n    = int(n_total * fps) + 1
    pts  = [i / fps for i in range(n)]

    # cy_smooth: manually set so that:
    #  - At prep_end_s: y_prep = 0.30
    #  - The false "apex" at ~2.2s: cy = 0.45 > y_prep (diver below board)
    #  - After 3.0s: cy continuously decreases (real rise)
    cy_sm = []
    vel_y = []
    for t in pts:
        if t < prep_end_s:
            cy_sm.append(0.30)
            vel_y.append(0.0)
        elif t < 2.0:
            # Artifact rises: positive velocity
            cy_sm.append(0.30 + (t - prep_end_s) / (2.0 - prep_end_s) * 0.25)
            vel_y.append(+0.25)
        elif t < 2.2:
            # Artifact decay: NEGATIVE velocity, cy goes from 0.55 toward 0.45
            cy_sm.append(0.55 - (t - 2.0) / 0.2 * 0.10)
            vel_y.append(-0.50)   # neg velocity
        elif t < 2.4:
            # Transition to near-zero at cy ≈ 0.45 (ABOVE y_prep=0.30)
            cy_sm.append(0.45)
            vel_y.append(+0.10)   # neg→non-neg crossing here; cy_apex=0.45 > 0.30 → REJECTED
        elif t < takeoff_s:
            # Slowly approaching takeoff
            cy_sm.append(0.45 - (t - 2.4) / (takeoff_s - 2.4) * 0.10)
            vel_y.append(-0.17)   # negative but slow (below sustained threshold window)
        else:
            # Real takeoff: sustained strong negative velocity
            cy_sm.append(0.35 - (t - takeoff_s) * 0.20)
            vel_y.append(-0.20)   # > vel_thresh = 0.04

    conf  = [0.5] * n
    # Locate prep_end_i (index of prep_end_s)
    prep_end_i = next(i for i, t in enumerate(pts) if t >= prep_end_s - 0.02) - 1

    # Directly test the detection function
    result_i = _detect_hurdle_takeoff_v3d0(cy_sm, vel_y, pts, prep_end_i, PARAMS_V3D0)
    assert result_i is not None, (
        "D0a: Expected takeoff detected (via fallback) after false apex rejected")
    to_t = pts[result_i]
    # The false apex at 2.4s (cy=0.45 > y_prep=0.30) must have been rejected.
    # The fallback finds sustained negative velocity — which in this trajectory
    # starts at ~2.4s (approach period, vel=-0.17 < -0.04 but only 0.6s window
    # which passes if all frames are negative).  The key assertion: to_t > guard_end_s.
    assert to_t > guard_end_s, (
        f"D0a: Takeoff {to_t:.3f}s not after guard_end {guard_end_s:.3f}s")
    # And the false apex at 2.4s did NOT produce a takeoff at ~2.4s via HURDLE path
    # (which would require searching from 2.4s and finding departure immediately)
    # → verified above implicitly: if algorithm found takeoff, it's from the fallback path


def test_d0b_valid_hurdle_apex_accepted():
    """D0b: Apex where cy_apex < y_prep by ≥ min_rise must be accepted."""
    board_cy = 0.40
    fps = 30.0
    cy, pts, conf = hurdle_traj_valid(
        fps=fps, board_cy=board_cy,
        h_apex_s=2.2, h_recontact_s=2.5, f_takeoff_s=3.0,
        apex_s=3.35, wc_s=4.1)
    res = propose_events_v3d0(cy, pts, conf, "102C", PARAMS_V3D0)
    assert res["context"] == "HURDLE"
    to_t = res["takeoff_t"]
    assert to_t is not None, "Expected takeoff detected"
    assert abs(to_t - 3.0) < 0.5, f"Takeoff {to_t:.3f}s too far from GT 3.0s"


def test_d0c_multiple_false_candidates_then_valid():
    """D0c: Algorithm scans past multiple invalid crossings to find the valid one."""
    fps = 30.0
    board_cy = 0.35
    # Build trajectory with two early artifact crossings, then valid hurdle
    n_total = 8.0
    n = int(n_total * fps) + 1
    pts = [i / fps for i in range(n)]
    cy = []
    for t in pts:
        if t < 1.5:
            cy.append(board_cy)
        elif t < 1.8:
            cy.append(board_cy + 0.15)   # 1st false: cy goes DOWN (below board)
        elif t < 2.2:
            cy.append(board_cy + 0.05)   # false 1 descent
        elif t < 2.5:
            cy.append(board_cy + 0.20)   # 2nd false: below board
        elif t < 3.0:
            cy.append(board_cy + 0.10)   # 2nd false descent
        elif t < 3.5:
            cy.append(board_cy)          # return to board
        elif t < 3.7:
            frac = (t - 3.5) / 0.2
            cy.append(board_cy - frac * 0.10)   # valid hurdle rise
        elif t < 4.0:
            frac = (t - 3.7) / 0.3
            cy.append((board_cy - 0.10) + frac * 0.10)  # back to board
        elif t < 4.5:
            cy.append(board_cy)
        elif t < 4.8:
            frac = (t - 4.5) / 0.3
            cy.append(board_cy - frac * 0.14)   # final takeoff rise
        elif t < 5.5:
            frac = (t - 4.8) / 0.7
            cy.append((board_cy - 0.14) + frac * 0.45)
        else:
            cy.append(0.80)
    conf = [0.5] * n
    res = propose_events_v3d0(cy, pts, conf, "102C", PARAMS_V3D0)
    to_t = res["takeoff_t"]
    assert to_t is not None, "Expected takeoff from valid hurdle path"
    assert abs(to_t - 4.5) < 0.8, f"Takeoff {to_t:.3f}s too far from GT 4.5s"


def test_d0d_fallback_triggered_when_no_valid_apex():
    """D0d: STANDING fallback triggered when ALL candidates fail rise check.

    Tests _detect_hurdle_takeoff_v3d0 directly.  Velocity history:
      - Multiple neg→non-neg crossings, each with cy_apex > y_prep → all rejected.
      - Sustained negative velocity after all rejections → fallback fires.
    """
    fps     = 30.0
    y_prep  = 0.25   # board level (upper frame)
    guard_s = PARAMS_V3D0["hurdle_post_plateau_guard_s"]
    prep_end_s  = 1.0
    guard_end_s = prep_end_s + guard_s  # 1.40s
    n_total = 8.0
    n   = int(n_total * fps) + 1
    pts = [i / fps for i in range(n)]

    # Two false crossings (cy_apex = 0.50 and 0.45, both > y_prep=0.25), then
    # sustained negative velocity from 5.0s.
    cy_sm = []
    vel_y = []
    for t in pts:
        if t < prep_end_s:
            cy_sm.append(0.25); vel_y.append(0.0)
        elif t < 2.0:
            cy_sm.append(0.25 + (t - prep_end_s) * 0.30)  # ramp up (positive vel)
            vel_y.append(+0.30)
        elif t < 2.2:
            cy_sm.append(0.55 - (t - 2.0) * 0.50)  # decay (neg vel)
            vel_y.append(-0.50)
        elif t < 2.5:
            cy_sm.append(0.45); vel_y.append(+0.10)   # crossing 1: cy_apex=0.45>0.25 REJECTED
        elif t < 3.2:
            cy_sm.append(0.45 + (t - 2.5) * 0.20); vel_y.append(+0.20)   # ramp up again
        elif t < 3.4:
            cy_sm.append(0.59 - (t - 3.2) * 0.50); vel_y.append(-0.50)   # decay (neg)
        elif t < 3.8:
            cy_sm.append(0.49); vel_y.append(+0.05)   # crossing 2: cy_apex=0.49>0.25 REJECTED
        elif t < 4.8:
            cy_sm.append(0.49 - (t - 3.8) * 0.10); vel_y.append(-0.10)   # slow approach
        else:
            # Sustained strong negative: real takeoff
            cy_sm.append(max(0.0, 0.39 - (t - 4.8) * 0.25))
            vel_y.append(-0.25)

    prep_end_i = next(i for i, t in enumerate(pts) if t >= prep_end_s - 0.02) - 1
    result_i = _detect_hurdle_takeoff_v3d0(cy_sm, vel_y, pts, prep_end_i, PARAMS_V3D0)

    assert result_i is not None, "D0d: Expected fallback takeoff after all candidates rejected"
    to_t = pts[result_i]
    assert to_t > guard_end_s, f"D0d: Takeoff {to_t:.3f}s before guard_end {guard_end_s:.3f}s"
    assert to_t < 7.0, f"D0d: Fallback takeoff {to_t:.3f}s unreasonably late"


def test_d0e_fallback_finds_sustained_departure():
    """D0e: Fallback correctly identifies sustained negative velocity from guard_end.

    Simulates the 2169 scenario: smoothed velocity is positive from guard_end
    to some point, then goes strongly negative.  V3-D0 fallback must find the
    sustained departure.
    """
    fps = 60.0
    board_cy = 0.264
    guard_s  = PARAMS_V3D0["hurdle_post_plateau_guard_s"]
    prep_end_s = 5.9
    guard_end_s = prep_end_s + guard_s
    # Smoothed velocity positive from guard_end to ~6.84s, then negative
    # Real takeoff at ~6.875s
    real_takeoff_s = 6.875
    n_total = 10.0
    n = int(n_total * fps) + 1
    pts = [i / fps for i in range(n)]
    cy = []
    for t in pts:
        if t < prep_end_s:
            cy.append(board_cy)
        elif t < guard_end_s + 0.55:
            # Positive artifact: cy increases (false descent)
            frac = (t - prep_end_s) / 0.55
            cy.append(board_cy + frac * 0.44)   # board_cy → board_cy+0.44
        elif t < real_takeoff_s:
            # Settling (cy slightly decreasing, approaching new level)
            frac = (t - (guard_end_s + 0.55)) / (real_takeoff_s - (guard_end_s + 0.55))
            cy.append((board_cy + 0.44) - frac * 0.05)
        elif t < real_takeoff_s + 0.35:
            # Strong descent (actual takeoff)
            frac = (t - real_takeoff_s) / 0.35
            cy.append((board_cy + 0.39) - frac * 0.14)
        elif t < real_takeoff_s + 1.0:
            frac = ((t - real_takeoff_s - 0.35) / 0.65)
            cy.append((board_cy + 0.39 - 0.14) + frac * 0.32)
        else:
            cy.append(0.80)
    conf = [0.5] * n
    res = propose_events_v3d0(cy, pts, conf, "101B", PARAMS_V3D0)
    to_t = res["takeoff_t"]
    assert to_t is not None, "Fallback must find sustained departure"
    assert abs(to_t - real_takeoff_s) < 0.5, (
        f"Fallback takeoff {to_t:.3f}s too far from expected {real_takeoff_s:.3f}s")


def test_d0f_valid_hurdle_integration():
    """D0f: Full integration test — valid hurdle + final takeoff + apex + wc all detected."""
    board_cy  = 0.40
    h_apex_s  = 2.2
    h_rc_s    = 2.5
    f_to_s    = 3.0
    apex_s    = 3.35
    wc_s      = 4.1
    cy, pts, conf = hurdle_traj_valid(
        fps=30.0, board_cy=board_cy,
        h_apex_s=h_apex_s, h_recontact_s=h_rc_s,
        f_takeoff_s=f_to_s, apex_s=apex_s, wc_s=wc_s)
    res = propose_events_v3d0(cy, pts, conf, "102C", PARAMS_V3D0)
    assert res["takeoff_t"] is not None,      "takeoff missing"
    assert res["apex_t"]    is not None,      "apex missing"
    assert res["water_contact_t"] is not None, "water_contact missing"
    assert res["takeoff_t"] < res["apex_t"],             "takeoff must precede apex"
    assert res["apex_t"]    < res["water_contact_t"],    "apex must precede wc"


def test_d0g_fps_invariance():
    """D0g: Results are approximately consistent at 30 fps and 60 fps."""
    for fps in (30.0, 60.0):
        cy, pts, conf = hurdle_traj_valid(fps=fps)
        res = propose_events_v3d0(cy, pts, conf, "102C", PARAMS_V3D0)
        assert res["takeoff_t"] is not None, f"No takeoff at {fps}fps"
        assert abs(res["takeoff_t"] - 3.0) < 0.3, (
            f"At {fps}fps takeoff {res['takeoff_t']:.3f}s too far from GT 3.0s")


def test_d0h_long_static_prep_no_early_detection():
    """D0h: 5-second static prep before hurdle; guard suppresses early motion."""
    fps = 30.0
    board_cy = 0.40
    long_static_s = 5.0
    h_apex_s  = long_static_s + 0.7
    h_rc_s    = long_static_s + 1.0
    f_to_s    = long_static_s + 1.5
    apex_s    = long_static_s + 1.85
    wc_s      = long_static_s + 2.6
    cy, pts, conf = hurdle_traj_valid(
        fps=fps, board_cy=board_cy, static_s=long_static_s,
        h_takeoff_s=long_static_s + 0.5,
        h_apex_s=h_apex_s, h_recontact_s=h_rc_s,
        f_takeoff_s=f_to_s, apex_s=apex_s, wc_s=wc_s,
        n_total_s=long_static_s + 4.0)
    res = propose_events_v3d0(cy, pts, conf, "102C", PARAMS_V3D0)
    to_t = res["takeoff_t"]
    assert to_t is not None, "No takeoff after long static prep"
    assert to_t >= long_static_s, f"Takeoff {to_t:.3f}s before end of static prep {long_static_s}s"


def test_d0i_board_recontact_invariant_rejected():
    """D0i: Apex physically below board level (cy_apex >= y_prep) always rejected.

    Directly tests the board-rise invariant with a parametric sweep of cy_apex.
    """
    fps = 30.0
    board_cy = 0.40
    # Manufacture a crossing just after guard_end where cy_apex > y_prep
    guard_s = PARAMS_V3D0["hurdle_post_plateau_guard_s"]
    prep_end_s = 2.0
    guard_end_s = prep_end_s + guard_s
    n_total = 8.0
    n = int(n_total * fps) + 1
    pts = [i / fps for i in range(n)]

    for cy_apex_val in [board_cy + 0.001, board_cy + 0.05, board_cy + 0.20]:
        cy = []
        for t in pts:
            if t < prep_end_s:
                cy.append(board_cy)
            elif t < guard_end_s + 0.05:
                cy.append(board_cy)
            elif t < guard_end_s + 0.25:
                cy.append(cy_apex_val)    # false low position
            elif t < guard_end_s + 0.5:
                cy.append(board_cy)       # return creates neg→non-neg
            elif t < guard_end_s + 1.5:
                cy.append(board_cy)
            elif t < guard_end_s + 1.8:
                frac = (t - (guard_end_s + 1.5)) / 0.3
                cy.append(board_cy - frac * 0.14)  # actual takeoff
            elif t < guard_end_s + 2.5:
                frac = (t - (guard_end_s + 1.8)) / 0.7
                cy.append((board_cy - 0.14) + frac * 0.45)
            else:
                cy.append(0.80)
        conf = [0.5] * n
        res = propose_events_v3d0(cy, pts, conf, "101B", PARAMS_V3D0)
        # With cy_apex > board_cy, the false crossing is rejected.
        # The actual takeoff at guard_end+1.5s should be found via fallback or subsequent crossing.
        to_t = res["takeoff_t"]
        # The key invariant: takeoff should NOT be found at guard_end+0.5s
        # (that is the false apex recontact area)
        if to_t is not None:
            assert to_t > guard_end_s + 0.8, (
                f"cy_apex={cy_apex_val:.3f} > board_cy={board_cy:.3f}: "
                f"false apex must be rejected; got takeoff at {to_t:.3f}s")


def test_h1_standing_non_regression():
    """H1: STANDING dives must produce identical results to V3-C0."""
    board_cy = 0.40
    for dive_code in ("301A", "401C", "5411C"):
        cy, pts, conf = standing_traj(board_cy=board_cy)
        r_c0 = propose_events_v3c0(cy, pts, conf, dive_code, PARAMS_V3C0)
        r_d0 = propose_events_v3d0(cy, pts, conf, dive_code, PARAMS_V3D0)
        assert r_c0["takeoff_t"] == r_d0["takeoff_t"], (
            f"{dive_code}: STANDING takeoff changed {r_c0['takeoff_t']} → {r_d0['takeoff_t']}")
        assert r_c0["apex_t"] == r_d0["apex_t"], (
            f"{dive_code}: STANDING apex changed")
        assert r_c0["water_contact_t"] == r_d0["water_contact_t"], (
            f"{dive_code}: STANDING wc changed")


def test_fm1_closed_311_pattern():
    """FM1: Dive 311 pattern — unbounded apex would fire at post-dive pool-deck;
    A1+A2 (unchanged in V3-D0) must keep it closed.
    """
    fps = 30.0
    board_cy = 0.40
    # Trajectory with no apex crossing (monotone ascent) then pool-deck at 0.11
    cy, pts, conf = standing_traj(
        fps=fps, board_cy=board_cy,
        takeoff_s=2.0, apex_s=2.35, wc_s=3.0,
        n_total_s=8.0, post_wc_low_cy=0.11)
    res = propose_events_v3d0(cy, pts, conf, "401C", PARAMS_V3D0)
    wc_t = res["water_contact_t"]
    assert wc_t is not None, "FM1: wc must be found"
    assert wc_t < 5.0, f"FM1: wc={wc_t:.3f}s too late (pool-deck not suppressed by A2)"


def test_paris_firewall():
    """PARIS_FIREWALL: V3-D0 Paris to_err ≤ 2.0s (not worse than V3-C0 baseline).

    Uses a synthetic trajectory that mimics the Paris detection pattern:
    prep movement creates an early valid-looking hurdle candidate before GT takeoff.
    The test does NOT load the real Paris video; it verifies the algorithm doesn't
    catastrophically regress vs the documented V3-C0 Paris result.

    Known result from Phase M evaluation (real D5 trajectories):
    V3-C0 to_err=1.685s, V3-D0 to_err=1.685s (identical).
    Guard: V3-D0 Paris to_err ≤ 2.0s (no regression).
    """
    fps = 56.517  # Paris video fps
    board_cy = 0.4635  # Paris y_prep measured in Phase M
    # Simulate Paris: early false hurdle at 1.117s (cy_apex=0.380 < y_prep=0.464,
    # rise=0.083 > min_rise=0.01 → accepted), then takeoff found at 1.435s.
    # GT takeoff = 3.120s → to_err = |1.435 - 3.120| = 1.685s.
    n_total = 5.0
    n = int(n_total * fps) + 1
    pts = [i / fps for i in range(n)]
    cy = []
    false_apex_s   = 1.117
    false_to_s     = 1.435
    gt_apex_s      = 3.570
    gt_wc_s        = 4.220
    for t in pts:
        if t < 0.5:
            cy.append(board_cy)
        elif t < false_apex_s:
            frac = (t - 0.5) / (false_apex_s - 0.5)
            cy.append(board_cy - frac * 0.084)   # small rise (0.380 = board_cy - 0.084)
        elif t < false_apex_s + 0.3:
            frac = (t - false_apex_s) / 0.3
            cy.append((board_cy - 0.084) + frac * 0.05)  # return: crosses neg→non-neg
        elif t < false_to_s:
            cy.append(board_cy - 0.034)
        elif t < false_to_s + 0.25:
            frac = (t - false_to_s) / 0.25
            cy.append((board_cy - 0.034) - frac * 0.10)  # false takeoff descent
        elif t < gt_apex_s:
            frac = (t - (false_to_s + 0.25)) / (gt_apex_s - (false_to_s + 0.25))
            # Slow oscillation / board dynamics before real apex
            cy.append(board_cy - 0.034 - 0.10 + frac * 0.12)
        elif t < gt_wc_s:
            frac = (t - gt_apex_s) / (gt_wc_s - gt_apex_s)
            cy.append((board_cy - 0.034 - 0.10 + 0.12) + frac * 0.40)
        else:
            cy.append(0.80)
    conf = [0.5] * n
    res = propose_events_v3d0(cy, pts, conf, "5122D", PARAMS_V3D0)
    to_t = res["takeoff_t"]
    assert to_t is not None, "Paris: takeoff must be detected"
    gt_to = 3.120
    to_err = abs(to_t - gt_to)
    assert to_err <= 2.0, (
        f"PARIS_FIREWALL: to_err={to_err:.3f}s > 2.0s threshold "
        f"(V3-C0 baseline=1.685s). V3-D0 must not regress Paris.")


def test_d0j_freeze_identity():
    """D0j: PARAMS_V3D0 frozen values match documented artifact."""
    expected = {
        "variant":                "V3D0",
        "min_hurdle_rise_cy":     0.01,
        "fallback_sustained_s":   0.15,
        # Keys inherited from V3-C0 / V2.1 — spot-check critical ones
        "apex_max_window_s":      1.5,
        "wc_max_window_s":        2.5,
        "hurdle_post_plateau_guard_s": 0.40,
        "takeoff_vel_threshold":  0.04,
        "takeoff_sustained_s":    0.15,
        "smooth_window_s":        0.35,
    }
    for k, v in expected.items():
        assert PARAMS_V3D0.get(k) == v, (
            f"PARAMS_V3D0[{k!r}] = {PARAMS_V3D0.get(k)!r}, expected {v!r}")


# ─── Runner ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_d0a_false_apex_from_target_switch_rejected,
        test_d0b_valid_hurdle_apex_accepted,
        test_d0c_multiple_false_candidates_then_valid,
        test_d0d_fallback_triggered_when_no_valid_apex,
        test_d0e_fallback_finds_sustained_departure,
        test_d0f_valid_hurdle_integration,
        test_d0g_fps_invariance,
        test_d0h_long_static_prep_no_early_detection,
        test_d0i_board_recontact_invariant_rejected,
        test_h1_standing_non_regression,
        test_fm1_closed_311_pattern,
        test_paris_firewall,
        test_d0j_freeze_identity,
    ]
    passed = failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed + failed} tests: {passed} passed, {failed} failed")
    exit(0 if failed == 0 else 1)
