#!/usr/bin/env python3
"""Unit tests for Event Logic V4-B0 (frozen flight-anchored successor).

All trajectories synthetic (cy_norm convention: 0=top, 1=bottom).
Covers: frozen constants, flight-anchored takeoff on standing/hurdle
synthetics, bias calibration application, anchor clamp, abstention on
degenerate/flat windows, apex/wc delegation parity with V3-C0 detectors,
PARAMS_E1 threshold parity, DEV-calibration documentation.
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from proposer_event_logic_v2_1 import PARAMS_E1
from proposer_event_logic_v3_c0 import (
    PARAMS_V3C0, _detect_apex_bounded, _detect_water_contact_bounded,
)
from proposer_event_logic_v4_b0 import (
    propose_events_v4b0, PARAMS_V4B0, SEARCH_BACK_S, TAKEOFF_BIAS_S,
    VERSION,
)


# ─── Synthetic trajectory helpers ────────────────────────────────────────────

def make_pts(n, fps=30.0):
    return [i / fps for i in range(n)]


def standing_traj(fps=30.0, static_s=2.0, takeoff_s=2.1, apex_s=2.4,
                  wc_s=3.1, n_total_s=4.0, board_cy=0.20, apex_cy=0.10,
                  wc_cy=0.60):
    """cy on board, linear rise to apex, linear fall to wc, flat after."""
    n = int(n_total_s * fps) + 1
    pts = [i / fps for i in range(n)]
    cy = []
    for t in pts:
        if t < takeoff_s:
            cy.append(board_cy)
        elif t < apex_s:
            frac = (t - takeoff_s) / (apex_s - takeoff_s)
            cy.append(board_cy - frac * (board_cy - apex_cy))
        elif t < wc_s:
            frac = (t - apex_s) / (wc_s - apex_s)
            cy.append(apex_cy + frac * (wc_cy - apex_cy))
        else:
            cy.append(wc_cy)
    return cy, pts


def hurdle_traj(fps=30.0):
    """Board 0.20; hurdle jump dip (recontact low 0.24 at 1.0s); final rise
    at 2.1s; apex 2.4s; wc 3.1s. The takeoff must follow the LAST low."""
    n = int(4.0 * fps) + 1
    pts = [i / fps for i in range(n)]
    cy = []
    for t in pts:
        if t < 0.7:
            cy.append(0.20)
        elif t < 1.0:
            frac = (t - 0.7) / 0.3
            cy.append(0.20 - frac * 0.06)  # hurdle jump rise
        elif t < 1.3:
            frac = (t - 1.0) / 0.3
            cy.append(0.14 + frac * 0.10)  # fall to recontact low
        elif t < 2.1:
            cy.append(0.24)  # settle on board
        elif t < 2.4:
            frac = (t - 2.1) / 0.3
            cy.append(0.24 - frac * 0.14)  # final rise
        elif t < 3.1:
            frac = (t - 2.4) / 0.7
            cy.append(0.10 + frac * 0.50)
        else:
            cy.append(0.60)
    return cy, pts


def conf_full(n, v=0.9):
    return [v] * n


# ─── Tests ───────────────────────────────────────────────────────────────────

def test_frozen_constants():
    assert VERSION == 'EVENT_LOGIC_V4_B0'
    assert SEARCH_BACK_S == 4.0
    assert TAKEOFF_BIAS_S == 0.23
    assert PARAMS_V4B0['variant'] == 'V4B0'
    assert PARAMS_V4B0['search_back_s'] == 4.0
    assert PARAMS_V4B0['takeoff_bias_s'] == 0.23
    assert PARAMS_V4B0['apex_max_window_s'] == 1.5
    assert PARAMS_V4B0['wc_max_window_s'] == 2.5


def test_params_e1_parity():
    for k, v in PARAMS_E1.items():
        if k == 'variant':
            continue  # V4B0 carries its own variant tag
        assert PARAMS_V4B0[k] == v, k


def test_standing_takeoff_anchored_with_bias():
    cy, pts = standing_traj()
    conf = conf_full(len(cy))
    e = propose_events_v4b0(cy, pts, conf, ft0=2.6)
    # rise onset fires at/just before the synthetic corner (smoothing
    # anticipation is real and part of the calibrated bias); the test pins
    # the BIAS APPLICATION and the plausible window, not an exact frame.
    assert e['takeoff_t'] is not None
    assert e['rise_t'] is not None
    assert abs((e['takeoff_t'] - e['rise_t']) - 0.23) < 1 / 30 + 1e-9
    assert 2.0 <= e['takeoff_t'] <= 2.45, e['takeoff_t']
    assert e['takeoff_t'] <= 2.6
    assert e['clamped_to_anchor'] is False


def test_hurdle_takeoff_follows_last_low():
    cy, pts = hurdle_traj()
    conf = conf_full(len(cy))
    e = propose_events_v4b0(cy, pts, conf, ft0=2.6)
    # must ignore the 0.7s hurdle jump; prep low ~= recontact/settle region
    assert e['takeoff_t'] is not None
    assert e['takeoff_t'] > 1.5, e['takeoff_t']
    assert abs((e['takeoff_t'] - e['rise_t']) - 0.23) < 1 / 30 + 1e-9
    assert e['prep_low_t'] is not None and e['prep_low_t'] > 1.0


def test_anchor_clamp():
    cy, pts = standing_traj(takeoff_s=2.1)
    conf = conf_full(len(cy))
    # anchor before rise+bias (rise ~1.9 under smoothing + 0.23 = ~2.13
    # > ft0=2.05) -> clamp to the anchor
    e = propose_events_v4b0(cy, pts, conf, ft0=2.05)
    assert e['clamped_to_anchor'] is True
    # snapped to the nearest frame at/around the anchor
    assert abs(e['takeoff_t'] - 2.05) <= 1 / 60 + 1e-9, e['takeoff_t']


def test_degenerate_window_abstains():
    cy, pts = standing_traj()
    conf = conf_full(len(cy))
    # track starts at the anchor: takeoff unobservable
    e = propose_events_v4b0(cy[:0] + cy[64:], pts[64:], conf[64:], ft0=pts[64])
    assert e['takeoff_t'] is None
    assert e['apex_t'] is None and e['water_contact_t'] is None


def test_flat_track_abstains():
    n = 120
    pts = make_pts(n)
    cy = [0.5] * n
    e = propose_events_v4b0(cy, pts, conf_full(n), ft0=pts[-1])
    assert e['takeoff_t'] is None


def test_apex_wc_delegation_parity():
    cy, pts = standing_traj()
    conf = conf_full(len(cy))
    e = propose_events_v4b0(cy, pts, conf, ft0=2.15)
    from proposer_event_logic_v2_1 import (
        pts_aware_smooth, pts_aware_velocity, interpolate_gaps_time,
    )
    ys = pts_aware_smooth(cy, pts, PARAMS_V4B0['smooth_window_s'] / 3)
    ys = interpolate_gaps_time(ys, pts, max_gap_s=PARAMS_V4B0['interp_max_gap_s'])
    vel = pts_aware_velocity(ys, pts, max_gap_s=PARAMS_V4B0['vel_max_gap_s'])
    ti = e['takeoff_idx']
    ai = _detect_apex_bounded(ys, vel, pts, ti, PARAMS_V4B0)
    wi = _detect_water_contact_bounded(ys, vel, conf, pts, ai, PARAMS_V4B0)
    assert e['apex_idx'] == ai and e['water_contact_idx'] == wi


def test_complete_triplet_synthetic():
    cy, pts = standing_traj()
    e = propose_events_v4b0(cy, pts, conf_full(len(cy)), ft0=2.15)
    assert e['takeoff_t'] is not None
    assert e['apex_t'] is not None and e['takeoff_t'] < e['apex_t']
    assert e['water_contact_t'] is not None and e['apex_t'] < e['water_contact_t']
    assert abs(e['apex_t'] - 2.4) < 0.1 and abs(e['water_contact_t'] - 3.1) < 0.35


def test_no_dive_code_context():
    # context-free by construction: no dive_code parameter exists
    import inspect
    sig = inspect.signature(propose_events_v4b0)
    assert 'dive_code' not in sig.parameters
    assert list(sig.parameters) == ['y_arr', 'pts_arr', 'conf_arr', 'ft0', 'params']


TESTS = [
    test_frozen_constants,
    test_params_e1_parity,
    test_standing_takeoff_anchored_with_bias,
    test_hurdle_takeoff_follows_last_low,
    test_anchor_clamp,
    test_degenerate_window_abstains,
    test_flat_track_abstains,
    test_apex_wc_delegation_parity,
    test_complete_triplet_synthetic,
    test_no_dive_code_context,
]


if __name__ == "__main__":
    passed = 0
    failed = 0
    for test_fn in TESTS:
        try:
            test_fn()
            passed += 1
        except Exception as exc:
            print(f"[FAIL] {test_fn.__name__}: {exc}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed / {len(TESTS)} total")
    if failed > 0:
        raise SystemExit(1)
