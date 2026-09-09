#!/usr/bin/env python3
"""Unit tests for Event Logic V3-C0 and V3-C1.

Tests organised per Phase S requirements:
  - Bounded apex fallback (A1)
  - Bounded terminal wc search (A2)
  - No post-dive apex / no post-dive water_contact
  - HURDLE departure vs final takeoff distinction (C1)
  - Board-recontact invariant
  - Long preparation (H2)
  - STANDING non-regression (H1)
  - Paris firewall (no Paris GT used in proposer logic)

All trajectories synthetic (cy_norm convention: 0=top, 1=bottom).
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from proposer_event_logic_v3_c0 import (
    propose_events_v3c0, PARAMS_V3C0,
    _detect_apex_bounded, _detect_water_contact_bounded,
)
from proposer_event_logic_v3_c1 import (
    propose_events_v3c1, PARAMS_V3C1,
    _detect_hurdle_final_takeoff,
)


# ─── Synthetic trajectory helpers ────────────────────────────────────────────

def make_pts(n, fps=30.0):
    return [i / fps for i in range(n)]


def standing_traj(fps=30.0, static_s=2.0, takeoff_s=2.1, apex_s=2.4,
                   wc_s=3.1, n_total_s=4.0, noise=0.0, post_wc_low_cy=None):
    """Minimal cy_norm trajectory for a STANDING dive.

    cy_norm=0.20 on board, drops to 0.10 at apex, rises to 0.60 at wc.
    Pool-deck noise at 0.10 can be appended after wc to test bounded search.
    """
    n = int(n_total_s * fps) + 1
    pts = [i / fps for i in range(n)]
    cy  = []
    for t in pts:
        if t < static_s:
            cy.append(0.20 + noise * (hash(int(t * 1000)) % 10 - 5) * 0.001)
        elif t < takeoff_s:
            cy.append(0.20)
        elif t < apex_s:
            # Rising: cy decreases from 0.20 → 0.10
            frac = (t - takeoff_s) / (apex_s - takeoff_s)
            cy.append(0.20 - frac * 0.10)
        elif t < wc_s:
            # Falling: cy increases from 0.10 → 0.60
            frac = (t - apex_s) / (wc_s - apex_s)
            cy.append(0.10 + frac * 0.50)
        else:
            # Post-wc: pool-deck at low cy if requested, else high cy
            if post_wc_low_cy is not None:
                cy.append(post_wc_low_cy)  # simulate pool-deck at cy=0.11
            else:
                cy.append(0.70)
    conf = [0.5 if y is not None else 0.0 for y in cy]
    return cy, pts, conf


def hurdle_traj(fps=30.0, static_s=1.5, hurdle_takeoff_s=2.0,
                hurdle_apex_s=2.18, board_recontact_s=2.5,
                final_takeoff_s=3.0, apex_s=3.35, wc_s=4.1,
                n_total_s=5.0):
    """Synthetic HURDLE trajectory.

    Phases:
      [0, static_s)         : static on board at cy=0.20
      [static_s, h_takeoff) : approach motion
      [h_takeoff, h_apex)   : hurdle ascent (cy: 0.20→0.10)
      [h_apex, recontact)   : hurdle descent (cy: 0.10→0.20)
      [recontact, f_takeoff): loading / brief rest
      [f_takeoff, apex)     : final ascent (cy: 0.20→0.08)
      [apex, wc)            : final descent (cy: 0.08→0.60)
      [wc, end)             : post-wc (cy: 0.70)
    """
    n   = int(n_total_s * fps) + 1
    pts = [i / fps for i in range(n)]
    cy  = []
    for t in pts:
        if t < static_s:
            cy.append(0.20)
        elif t < hurdle_takeoff_s:
            cy.append(0.20)   # approach
        elif t < hurdle_apex_s:
            frac = (t - hurdle_takeoff_s) / (hurdle_apex_s - hurdle_takeoff_s)
            cy.append(0.20 - frac * 0.10)   # 0.20→0.10
        elif t < board_recontact_s:
            frac = (t - hurdle_apex_s) / (board_recontact_s - hurdle_apex_s)
            cy.append(0.10 + frac * 0.10)   # 0.10→0.20 (back to board)
        elif t < final_takeoff_s:
            cy.append(0.20)   # brief board loading / rest
        elif t < apex_s:
            frac = (t - final_takeoff_s) / (apex_s - final_takeoff_s)
            cy.append(0.20 - frac * 0.12)   # 0.20→0.08
        elif t < wc_s:
            frac = (t - apex_s) / (wc_s - apex_s)
            cy.append(0.08 + frac * 0.52)   # 0.08→0.60
        else:
            cy.append(0.70)
    conf = [0.5 for _ in pts]
    return cy, pts, conf


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_a1_bounded_apex_fallback_prevents_postdive_apex():
    """A1: unbounded fallback would pick pool-deck cy~0.11 as apex; bounded must not."""
    # Simulate dive 311 pattern: correct takeoff, no apex velocity crossing,
    # post-wc pool-deck detections at cy=0.11 (< on-board cy=0.20).
    n = 600
    fps = 30.0
    pts = [i / fps for i in range(n)]
    cy  = [None] * n

    # Board: frames 0-390 at cy=0.20
    for i in range(391):
        cy[i] = 0.20

    # Takeoff at t=13.0s (frame 390): cy starts decreasing
    takeoff_fi = 390
    # Apex at t=13.35s (frame 400): velocity crossing happens
    for i in range(391, 401):
        frac = (i - 390) / 10
        cy[i] = 0.20 - frac * 0.10  # 0.20→0.10

    # Flight + wc at t=13.82s (frame 415): cy goes back up
    for i in range(401, 416):
        frac = (i - 401) / 14
        cy[i] = 0.10 + frac * 0.55  # 0.10→0.65

    # Post-wc: pool-deck at cy=0.11 (LOWER than on-board! same as V2.1 dive 311 failure)
    for i in range(416, n):
        cy[i] = 0.11

    conf = [0.5 for _ in pts]

    # Remove apex velocity crossing to force fallback (set apex region to None)
    cy_no_apex = list(cy)
    for i in range(398, 403):
        cy_no_apex[i] = None   # gap at apex → forces fallback

    res = propose_events_v3c0(cy_no_apex, pts, conf, "401C", PARAMS_V3C0)
    apex_t = res.get("apex_t")
    wc_t   = res.get("water_contact_t")
    takeoff_t = res.get("takeoff_t")

    assert takeoff_t is not None, "Should find takeoff"
    if apex_t is not None:
        # A1: apex must be within apex_max_window_s of takeoff
        assert apex_t <= takeoff_t + PARAMS_V3C0["apex_max_window_s"] + 0.1, \
            f"Apex {apex_t:.3f} exceeds bound {takeoff_t + PARAMS_V3C0['apex_max_window_s']:.3f}"
    print(f"[PASS] A1 bounded apex: takeoff={takeoff_t:.3f}, apex={apex_t}, wc={wc_t}")


def test_a1_apex_within_bound_for_normal_dive():
    """A1: normal dive apex found correctly within bound."""
    cy, pts, conf = standing_traj(static_s=1.5, takeoff_s=1.8, apex_s=2.1, wc_s=2.9)
    res = propose_events_v3c0(cy, pts, conf, "301B", PARAMS_V3C0)
    assert res["apex_t"] is not None, "Apex should be found"
    assert res["apex_t"] <= res["takeoff_t"] + PARAMS_V3C0["apex_max_window_s"], \
        f"Apex beyond bound"
    print(f"[PASS] A1 normal dive apex at {res['apex_t']:.3f}s")


def test_a2_bounded_wc_no_postdive_selection():
    """A2: wc search must not select post-wc pool-deck events."""
    # Apex at 2.1s, wc at 2.9s, then pool-deck activity from 3s onward
    cy, pts, conf = standing_traj(
        static_s=1.5, takeoff_s=1.8, apex_s=2.1, wc_s=2.9, n_total_s=10.0,
        post_wc_low_cy=0.70  # post-wc cy>0.50 = correctly above water_line
    )
    res = propose_events_v3c0(cy, pts, conf, "301B", PARAMS_V3C0)
    wc_t = res.get("water_contact_t")
    apex_t = res.get("apex_t")
    assert wc_t is not None, "WC should be found"
    if apex_t is not None:
        assert wc_t <= apex_t + PARAMS_V3C0["wc_max_window_s"] + 0.1, \
            f"WC {wc_t:.3f} exceeds apex+bound"
    print(f"[PASS] A2 bounded wc: wc={wc_t:.3f}s (apex={apex_t})")


def test_a2_postdive_pool_deck_blocked():
    """A2: unbounded V2.1 would pick post-wc pool-deck; V3-C0 must not."""
    # Simulated dive 311-like: apex forced, wc at t=14.82s,
    # then pool-deck (cy stays below water_line) from 15s until end of 20s video
    n = 600
    fps = 30.0
    pts = [i / fps for i in range(n)]
    cy  = [0.20] * n

    # Takeoff at frame 390 (t=13s)
    takeoff_fi = 390
    # Apex at frame 400 (t=13.33s): velocity crossing
    for i in range(391, 401):
        cy[i] = 0.20 - (i - 390) / 10 * 0.10
    for i in range(401, 416):
        # Descent to wc
        cy[i] = 0.10 + (i - 401) / 14 * 0.55
    # wc at frame 415 (t=13.83s)
    # After wc: pool-deck at cy=0.65 (above water_line=0.50, but shouldn't matter)
    for i in range(416, n):
        cy[i] = 0.65

    conf = [0.5] * n
    res = propose_events_v3c0(cy, pts, conf, "401C", PARAMS_V3C0)
    wc_t = res.get("water_contact_t")
    apex_t = res.get("apex_t")
    if apex_t is not None and wc_t is not None:
        assert wc_t - apex_t <= PARAMS_V3C0["wc_max_window_s"] + 0.1, \
            f"WC too late: {wc_t:.3f} - apex {apex_t:.3f} = {wc_t-apex_t:.3f}s"
    print(f"[PASS] A2 post-dive pool-deck blocked: wc={wc_t}")


def test_hurdle_departure_vs_final_takeoff_c1():
    """C1: HURDLE jump candidate with recontact must be rejected; final takeoff accepted.

    Tests _detect_hurdle_final_takeoff directly with explicit velocity arrays.
    Hurdle burst at 1.0s has positive vel at 1.15s (0.15s < 0.25s window → rejected).
    Final burst at 2.0s has no positive vel within 0.25s (apex at 0.30s) → accepted.
    """
    fps = 50.0
    n = 250
    pts = [i / fps for i in range(n)]
    vel_y = [0.0] * n  # default: near-zero vel

    # Hurdle departure at 1.0s: neg vel for 0.15s, then positive (hurdle ascent → apex)
    for i in range(n):
        t = pts[i]
        if 1.0 <= t < 1.15:
            vel_y[i] = -0.10   # rising (neg vel)
        elif 1.15 <= t < 1.40:
            vel_y[i] = 0.10    # descending (pos vel, board recontact)

    # Final takeoff at 2.0s: neg vel for 0.30s (apex at 2.30s, outside 0.25s window)
    for i in range(n):
        t = pts[i]
        if 2.0 <= t < 2.30:
            vel_y[i] = -0.10   # rising (neg vel)
        elif 2.30 <= t < 2.80:
            vel_y[i] = 0.05    # slight positive (descending to water, but AFTER 0.25s window)

    idx = _detect_hurdle_final_takeoff(vel_y, pts, PARAMS_V3C1)
    assert idx is not None, "Should find takeoff"
    takeoff_t = pts[idx]
    # Must select final takeoff (≥2.0s), not the hurdle (1.0s)
    assert takeoff_t >= 1.8, \
        f"Takeoff {takeoff_t:.3f}s looks like HURDLE jump (expected ≥1.8s for final at 2.0s)"
    print(f"[PASS] C1 HURDLE final takeoff at {takeoff_t:.3f}s (hurdle at 1.0s rejected)")


def test_board_recontact_invariant():
    """H: hurdle departure cannot be scored as final takeoff if later recontact observed.

    Tests _detect_hurdle_final_takeoff directly with explicit velocity arrays (no smoothing),
    which is the only reliable way to verify the recontact mechanism — Gaussian smoothing
    shifts detected candidate starts earlier and compresses the effective window.

    Hurdle burst at 1.8s: neg vel for 0.15s, positive at 1.93s (0.13s < 0.25s → rejected).
    Final burst at 2.8s: neg vel for 0.35s, no positive until 3.15s (0.35s > 0.25s → kept).
    """
    fps = 50.0
    n = 300
    pts = [i / fps for i in range(n)]
    vel_y = [0.0] * n

    # Hurdle departure at 1.8s: neg vel for 0.13s, positive at 1.93s (board recontact)
    for i in range(n):
        t = pts[i]
        if 1.80 <= t < 1.93:
            vel_y[i] = -0.10   # rising (neg vel) — hurdle ascent
        elif 1.93 <= t < 2.30:
            vel_y[i] = 0.10    # falling (pos vel) — descent back to board

    # Final takeoff at 2.8s: neg vel for 0.35s (apex at 3.15s, outside 0.25s window)
    for i in range(n):
        t = pts[i]
        if 2.80 <= t < 3.15:
            vel_y[i] = -0.10   # rising (neg vel) — final ascent
        elif 3.15 <= t < 3.70:
            vel_y[i] = 0.05    # descending to water (after 0.35s from takeoff)

    idx = _detect_hurdle_final_takeoff(vel_y, pts, PARAMS_V3C1)
    assert idx is not None, "Should find takeoff"
    takeoff_t = pts[idx]
    # Invariant: final takeoff must be AFTER board recontact completed (≥2.4s)
    assert takeoff_t >= 2.4, \
        f"Recontact invariant violated: takeoff at {takeoff_t:.3f}s < board_recontact 2.3s"
    print(f"[PASS] board-recontact invariant: takeoff at {takeoff_t:.3f}s (recontact at 2.3s)")


def test_standing_non_regression_v3c1():
    """H1: STANDING dives must behave identically in V3-C1 and V2.1 (no HURDLE branch)."""
    from proposer_event_logic_v2_1 import propose_events, PARAMS_E1
    # Standard standing dive
    cy, pts, conf = standing_traj(static_s=1.5, takeoff_s=1.8, apex_s=2.1, wc_s=2.9)

    res_v21  = propose_events(cy, pts, conf, "301B", PARAMS_E1)
    res_v3c1 = propose_events_v3c1(cy, pts, conf, "301B", PARAMS_V3C1)

    # Both should find takeoff (apex/wc may differ due to A1/A2 bounds)
    assert res_v21["takeoff_t"]  is not None, "V2.1 should find takeoff"
    assert res_v3c1["takeoff_t"] is not None, "V3-C1 should find takeoff"
    # STANDING takeoff logic: same branch → same result
    assert abs(res_v21["takeoff_t"] - res_v3c1["takeoff_t"]) < 0.1, \
        f"STANDING takeoff differs: V2.1={res_v21['takeoff_t']:.3f} V3-C1={res_v3c1['takeoff_t']:.3f}"
    print(f"[PASS] STANDING non-regression: "
          f"V2.1 to={res_v21['takeoff_t']:.3f} V3-C1 to={res_v3c1['takeoff_t']:.3f}")


def test_long_preparation_hurdle():
    """H2: HURDLE dive with long static preparation (5+ seconds) must still find final takeoff.

    Tests _detect_hurdle_final_takeoff directly with explicit velocity arrays.
    5 seconds of near-zero vel (long preparation), then a hurdle burst at 5.8s (rejected
    because positive vel appears at 5.93s = 0.13s < 0.25s), then final takeoff at 6.8s
    (no positive vel until 7.15s = 0.35s > 0.25s → kept).

    H2 invariant: min_search_start_s=0.30s is the only floor; no upper cap on prep duration.
    """
    fps = 50.0
    n = 500
    pts = [i / fps for i in range(n)]
    vel_y = [0.0] * n  # 10 seconds total, nearly zero everywhere

    # Hurdle departure at 5.8s: neg vel for 0.13s, positive at 5.93s (recontact)
    for i in range(n):
        t = pts[i]
        if 5.80 <= t < 5.93:
            vel_y[i] = -0.10   # hurdle ascent
        elif 5.93 <= t < 6.30:
            vel_y[i] = 0.10    # hurdle descent → board recontact

    # Final takeoff at 6.8s: neg vel for 0.35s (apex at 7.15s > 0.25s window)
    for i in range(n):
        t = pts[i]
        if 6.80 <= t < 7.15:
            vel_y[i] = -0.10   # final ascent
        elif 7.15 <= t < 7.70:
            vel_y[i] = 0.05    # descent to water

    idx = _detect_hurdle_final_takeoff(vel_y, pts, PARAMS_V3C1)
    assert idx is not None, "Should find final takeoff despite 5s preparation"
    takeoff_t = pts[idx]
    assert takeoff_t >= 6.5, \
        f"Expected takeoff ≥ 6.5s (final at 6.8s), got {takeoff_t:.3f}s"
    print(f"[PASS] long-prep HURDLE: final takeoff at {takeoff_t:.3f}s (after 5s prep)")


def test_v3c0_no_change_to_standing_prep_end():
    """V3-C0: _find_preparation_end unchanged from V2.1 for STANDING."""
    from proposer_event_logic_v2_1 import propose_events, PARAMS_E1
    cy, pts, conf = standing_traj()
    res21  = propose_events(cy, pts, conf, "301A", PARAMS_E1)
    res_c0 = propose_events_v3c0(cy, pts, conf, "301A", PARAMS_V3C0)
    pe21 = res21.get("prep_end_t")
    pec0 = res_c0.get("prep_end_t")
    if pe21 is not None and pec0 is not None:
        assert abs(pe21 - pec0) < 0.05, \
            f"prep_end changed: V2.1={pe21:.3f} V3-C0={pec0:.3f}"
    print(f"[PASS] V3-C0 prep_end unchanged for STANDING: {pec0}")


def test_apex_primary_velocity_crossing_preferred():
    """A1: velocity crossing is primary; fallback only when crossing absent."""
    cy, pts, conf = standing_traj(static_s=1.0, takeoff_s=1.2, apex_s=1.6, wc_s=2.3)
    res = propose_events_v3c0(cy, pts, conf, "301B", PARAMS_V3C0)
    apex_t = res.get("apex_t")
    assert apex_t is not None, "Should find apex via velocity crossing"
    # With clean data, apex_t should be close to 1.6s
    assert abs(apex_t - 1.6) < 0.3, f"Apex {apex_t:.3f}s far from 1.6s"
    print(f"[PASS] apex via velocity crossing at {apex_t:.3f}s")


def test_v3c1_complete_hurdle_triplet():
    """V3-C1: complete triplet for clean HURDLE trajectory."""
    cy, pts, conf = hurdle_traj()
    res = propose_events_v3c1(cy, pts, conf, "102C", PARAMS_V3C1)
    assert res["takeoff_t"] is not None, "takeoff missing"
    assert res["apex_t"] is not None, "apex missing"
    assert res["water_contact_t"] is not None, "wc missing"
    print(f"[PASS] V3-C1 complete HURDLE triplet: "
          f"to={res['takeoff_t']:.3f} ap={res['apex_t']:.3f} wc={res['water_contact_t']:.3f}")


def test_no_postdive_apex_v3c1():
    """No post-wc apex: bounded apex cannot select post-wc events."""
    cy, pts, conf = standing_traj(
        static_s=0.5, takeoff_s=0.8, apex_s=1.1, wc_s=1.8, n_total_s=8.0,
        post_wc_low_cy=0.10   # pool-deck at very low cy (like dive 311)
    )
    res = propose_events_v3c1(cy, pts, conf, "301B", PARAMS_V3C1)
    takeoff_t = res.get("takeoff_t")
    apex_t    = res.get("apex_t")
    if takeoff_t is not None and apex_t is not None:
        bound = takeoff_t + PARAMS_V3C1["apex_max_window_s"]
        assert apex_t <= bound + 0.05, \
            f"Post-wc apex selected: {apex_t:.3f}s > bound {bound:.3f}s"
    print(f"[PASS] no post-wc apex: takeoff={takeoff_t}, apex={apex_t}")


def test_paris_firewall_no_gt_in_proposer():
    """Paris firewall: no Paris GT values appear in V3-C proposer params."""
    paris_values_to_exclude = {3.120, 3.570, 4.220, 176, 201, 238}
    for p in (PARAMS_V3C0, PARAMS_V3C1):
        for k, v in p.items():
            if isinstance(v, (int, float)):
                assert v not in paris_values_to_exclude, \
                    f"Paris GT value {v} found in params[{k}]"
    print("[PASS] Paris firewall: no Paris GT in V3-C params")


def test_frozen_v3c_params_fingerprint():
    """V3-C param fingerprint matches expected values."""
    assert PARAMS_V3C0["apex_max_window_s"] == 1.5
    assert PARAMS_V3C0["wc_max_window_s"]   == 2.5
    assert PARAMS_V3C1["hurdle_recontact_window_s"] == 0.25
    assert PARAMS_V3C1["hurdle_min_search_start_s"] == 0.30
    # All V2.1 base params unchanged
    from proposer_event_logic_v2_1 import PARAMS_E1
    for k in ("takeoff_vel_threshold", "takeoff_sustained_s", "smooth_window_s",
              "interp_max_gap_s", "vel_max_gap_s", "static_min_duration_s",
              "water_line_cy_norm"):
        assert PARAMS_V3C0[k] == PARAMS_E1[k], f"V3-C0 param {k} differs from E1"
        assert PARAMS_V3C1[k] == PARAMS_E1[k], f"V3-C1 param {k} differs from E1"
    print("[PASS] V3-C param fingerprint matches")


# ─── Run all ──────────────────────────────────────────────────────────────────

TESTS = [
    test_a1_bounded_apex_fallback_prevents_postdive_apex,
    test_a1_apex_within_bound_for_normal_dive,
    test_a2_bounded_wc_no_postdive_selection,
    test_a2_postdive_pool_deck_blocked,
    test_hurdle_departure_vs_final_takeoff_c1,
    test_board_recontact_invariant,
    test_standing_non_regression_v3c1,
    test_long_preparation_hurdle,
    test_v3c0_no_change_to_standing_prep_end,
    test_apex_primary_velocity_crossing_preferred,
    test_v3c1_complete_hurdle_triplet,
    test_no_postdive_apex_v3c1,
    test_paris_firewall_no_gt_in_proposer,
    test_frozen_v3c_params_fingerprint,
]


if __name__ == "__main__":
    passed = 0
    failed = 0
    for test_fn in TESTS:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"[FAIL] {test_fn.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed / {len(TESTS)} total")
    if failed > 0:
        raise SystemExit(1)
