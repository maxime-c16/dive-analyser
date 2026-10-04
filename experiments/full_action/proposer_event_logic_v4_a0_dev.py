"""Event Logic V4-A0 DEV PROTOTYPE — flight-anchored takeoff (NOT frozen).

Status: DEV investigation only. Frozen V3-C0 is untouched. No validation
claim is made here; a successor freezes only with its own protocol + fresh
event authority (with HUMAN apex) after the trajectory gate.

Hypothesis (from D3 attribution): V3-C0's takeoff = FIRST sustained rise
after the FIRST stillness. On full-prep tracks that fires on the earliest
prep motion (arm raise, hurdle jump, first step) — seconds before true
departure. The flight anchor already localizes departure: takeoff must
immediately precede the ballistic arc.

V4-A0 takeoff rule (flight-anchored, context-free):
  1. Let ft0 = flight-segment start (the selected DiveTrack's anchor).
  2. Search window W = [max(track_start, ft0 - SEARCH_BACK_S), ft0].
     Degenerate window (< 2 frames) -> abstain (None): the track starts at
     or after departure, so takeoff is unobservable (e.g. dive 980).
  3. On the smoothed y(t): find the LAST local maximum of cy (lowest
     physical point: crouch bottom for standing dives, board recontact
     after the hurdle for hurdle dives) inside W.
  4. Takeoff = first sustained rise (frozen PARAMS_E1 velocity thresholds)
     after that minimum. If no interior minimum exists, fall back to the
     first sustained rise in W (monotonic rise into flight).
  5. Apex / water-contact reuse the frozen V3-C0 bounded detectors
     downstream of the new takeoff (their windows are already relative).

This removes the dive-code context branch entirely: hurdle vs standing is
decided by the track shape before the anchor, not by FINA digits.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'landmark_pilot'))
from proposer_event_logic_v2_1 import (
    PARAMS_E1, classify_context, interpolate_gaps_time, pts_aware_smooth,
    pts_aware_velocity,
)
from proposer_event_logic_v3_c0 import (
    PARAMS_V3C0, _detect_apex_bounded, _detect_water_contact_bounded,
)

VERSION = 'EVENT_LOGIC_V4_A0_DEV'
SEARCH_BACK_S = 4.0  # DEV: how far before the flight anchor to look


def _sustained_rise_after(y_smooth, vel_y, pts_arr, t_start, params):
    vel_thresh = params['takeoff_vel_threshold']
    sustained_s = params['takeoff_sustained_s']
    n = len(y_smooth)
    for i in range(n):
        if pts_arr[i] < t_start:
            continue
        v = vel_y[i]
        if v is None or v >= -vel_thresh:
            continue
        t_end = pts_arr[i] + sustained_s
        ok = tot = 0
        for j in range(i + 1, n):
            if pts_arr[j] > t_end:
                break
            tot += 1
            if vel_y[j] is not None and vel_y[j] < -vel_thresh:
                ok += 1
        if tot > 0 and ok == tot:
            return i
    return None


def _last_local_cymax(y_smooth, pts_arr, w_lo, w_hi):
    """Last local maximum of cy (lowest physical point) in window indices."""
    best = None
    n = len(y_smooth)
    for i in range(w_lo, w_hi + 1):
        if y_smooth[i] is None:
            continue
        prev = y_smooth[i - 1] if i - 1 >= w_lo and y_smooth[i - 1] is not None else None
        nxt = y_smooth[i + 1] if i + 1 <= w_hi and y_smooth[i + 1] is not None else None
        if prev is None or nxt is None:
            continue
        if y_smooth[i] >= prev and y_smooth[i] >= nxt and (y_smooth[i] > prev or y_smooth[i] > nxt):
            best = i
    return best


def propose_events_v4a0(y_arr, pts_arr, conf_arr, ft0, params=None):
    """Flight-anchored takeoff + frozen bounded apex/wc. ft0 = anchor (seconds)."""
    if params is None:
        params = dict(PARAMS_V3C0)
    n = len(y_arr)
    y_smooth = pts_aware_smooth(y_arr, pts_arr, params['smooth_window_s'] / 3)
    y_smooth = interpolate_gaps_time(y_smooth, pts_arr, max_gap_s=params['interp_max_gap_s'])
    vel_y = pts_aware_velocity(y_smooth, pts_arr, max_gap_s=params['vel_max_gap_s'])

    w_lo = next((i for i in range(n) if pts_arr[i] >= ft0 - SEARCH_BACK_S), n - 1)
    w_hi = next((i for i in reversed(range(n)) if pts_arr[i] <= ft0), 0)
    takeoff_idx = None
    prep_end_idx = None
    if w_hi - w_lo >= 1:
        m = _last_local_cymax(y_smooth, pts_arr, w_lo, w_hi)
        if m is not None:
            prep_end_idx = m  # repurposed: last pre-flight low point
            takeoff_idx = _sustained_rise_after(y_smooth, vel_y, pts_arr, pts_arr[m], params)
        else:
            takeoff_idx = _sustained_rise_after(y_smooth, vel_y, pts_arr,
                                                pts_arr[w_lo], params)
    apex_idx = _detect_apex_bounded(y_smooth, vel_y, pts_arr, takeoff_idx, params) \
        if takeoff_idx is not None else None
    wc_idx = _detect_water_contact_bounded(y_smooth, vel_y, conf_arr, pts_arr, apex_idx, params) \
        if apex_idx is not None else None

    def _t(i):
        return pts_arr[i] if i is not None else None

    return {'takeoff_idx': takeoff_idx, 'takeoff_t': _t(takeoff_idx),
            'apex_idx': apex_idx, 'apex_t': _t(apex_idx),
            'water_contact_idx': wc_idx, 'water_contact_t': _t(wc_idx),
            'anchor_ft0': ft0, 'prep_low_idx': prep_end_idx,
            'prep_low_t': _t(prep_end_idx)}
