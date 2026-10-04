#!/usr/bin/env python3
"""Event Logic V3-C0 — bounded apex + bounded water-contact only.

Minimal targeted patch over V2.1. Isolates FM1 (unbounded apex fallback) and
terminal water-contact behaviour from HURDLE redesign.

CHANGES over V2.1 (PARAMS_E1):
  A1. _detect_apex: fallback bounded to [takeoff, takeoff + apex_max_window_s].
      - V2.1 fallback searched entire remaining video → post-wc pool-deck cy~0.11
        became false apex (dive 311: wc_err=3.53s).
      - Bound = 1.5s derived from DEVELOPMENT data: max observed takeoff→apex = 0.35s;
        1.5s is 4× that, conservative enough for springboard dives of varying height/code.
      - Authority: DEVELOPMENT corpus only. Paris NOT used to set this bound.
  A2. _detect_water_contact: search bounded to [apex, apex + wc_max_window_s].
      - V2.1 searched [apex, end-of-video] → compounds unbounded apex error.
      - Bound = 2.5s derived from DEVELOPMENT data: max observed apex→wc = 0.97s (dive 676);
        2.5s is ~2.6× that, conservative.
      - Authority: DEVELOPMENT corpus only.

UNCHANGED from V2.1:
  - _find_preparation_end (V2.1 semantics)
  - _detect_takeoff (V2.1 semantics, STANDING + HURDLE)
  - All PARAMS_E1 parameter values
  - PTS-aware signal primitives
  - Coordinate convention (cy_norm: 0=top, 1=bottom; rising = negative velocity)
  - No Paris-derived thresholds
  - No GT event-time windows used as inputs

Addresses: FM1 (dive 311). Does NOT address: FM2 (HURDLE prep_end), FM3 (360p noise).
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from proposer_event_logic_v2_1 import (
    classify_context,
    pts_aware_velocity,
    pts_aware_smooth,
    interpolate_gaps_time,
    _find_preparation_end,
    _detect_takeoff,
    PARAMS_E1,
)

# ─── V3-C0 parameters (inherits PARAMS_E1, adds bounded-search keys) ─────────

PARAMS_V3C0 = dict(PARAMS_E1)
PARAMS_V3C0.update({
    "variant": "V3C0",
    "apex_max_window_s": 1.5,   # A1: bound apex fallback [takeoff, takeoff+1.5s]
    "wc_max_window_s":   2.5,   # A2: bound wc search    [apex,    apex+2.5s]
})


# ─── A1: bounded apex detection ──────────────────────────────────────────────

def _detect_apex_bounded(y_smooth, vel_y, pts_arr, takeoff_idx, params):
    """Apex detection with bounded fallback (A1).

    Primary: velocity zero-crossing neg→non-neg after takeoff+apex_search_start_s.
    Fallback: min y in [takeoff+apex_search_start_s, takeoff+apex_max_window_s].
    (V2.1 fallback was [takeoff+apex_search_start_s, end-of-video].)
    """
    n = len(y_smooth)
    apex_max_window_s = params.get("apex_max_window_s", 1.5)
    search_start_t = pts_arr[takeoff_idx] + params["apex_search_start_s"]
    search_end_t   = pts_arr[takeoff_idx] + apex_max_window_s

    # Primary: velocity crossing negative → non-negative (diver peaks and starts descent)
    prev_v = None
    for i in range(takeoff_idx + 1, n):
        if pts_arr[i] < search_start_t:
            prev_v = vel_y[i]
            continue
        if pts_arr[i] > search_end_t:
            break
        v = vel_y[i]
        if v is None:
            prev_v = None
            continue
        if prev_v is not None and prev_v < 0 and v >= 0:
            return i - 1  # last ascending frame = apex
        prev_v = v

    # Fallback: min y (highest physical point) within BOUNDED window (A1 fix)
    best_idx = None
    best_y   = None
    for i in range(takeoff_idx + 1, n):
        if pts_arr[i] < search_start_t:
            continue
        if pts_arr[i] > search_end_t:
            break
        if y_smooth[i] is None:
            continue
        if best_y is None or y_smooth[i] < best_y:
            best_y   = y_smooth[i]
            best_idx = i

    return best_idx


# ─── A2: bounded water-contact detection ─────────────────────────────────────

def _detect_water_contact_bounded(y_smooth, vel_y, conf_arr, pts_arr, apex_idx, params):
    """Water contact with bounded search window (A2).

    Primary: first frame after apex where y_smooth > water_line_cy_norm.
    Fallback: last confident detection in [apex, apex+wc_max_window_s].
    (V2.1 searched [apex, end-of-video] — this compounds unbounded apex errors.)
    """
    n = len(y_smooth)
    wc_max_window_s     = params.get("wc_max_window_s", 2.5)
    min_after_apex_s    = params["water_contact_min_after_apex_s"]
    water_thresh        = params["water_line_cy_norm"]
    search_start_t      = pts_arr[apex_idx] + min_after_apex_s
    search_end_t        = pts_arr[apex_idx] + wc_max_window_s

    # Primary: threshold crossing
    for i in range(apex_idx + 1, n):
        if pts_arr[i] < search_start_t:
            continue
        if pts_arr[i] > search_end_t:
            break
        if y_smooth[i] is None:
            continue
        if y_smooth[i] > water_thresh:
            return i

    # Fallback: last confident detection in bounded window (A2 fix)
    last_conf = None
    for i in range(apex_idx + 1, n):
        if pts_arr[i] < search_start_t:
            continue
        if pts_arr[i] > search_end_t:
            break
        if conf_arr[i] > 0.3:
            last_conf = i

    return last_conf


# ─── Top-level proposer ───────────────────────────────────────────────────────

def propose_events_v3c0(y_arr, pts_arr, conf_arr, dive_code, params=None):
    """V3-C0: V2.1 with bounded apex (A1) and bounded wc (A2).

    y_arr in cy_norm convention (0=top, 1=bottom).
    """
    if params is None:
        params = PARAMS_V3C0

    context = classify_context(dive_code)

    y_smooth = pts_aware_smooth(y_arr, pts_arr, sigma_s=params["smooth_window_s"] / 3)
    y_smooth = interpolate_gaps_time(y_smooth, pts_arr, max_gap_s=params["interp_max_gap_s"])
    vel_y    = pts_aware_velocity(y_smooth, pts_arr, max_gap_s=params["vel_max_gap_s"])

    prep_end_idx    = _find_preparation_end(y_smooth, pts_arr, params)
    takeoff_idx     = _detect_takeoff(y_smooth, vel_y, pts_arr, prep_end_idx, context, params)
    apex_idx        = _detect_apex_bounded(y_smooth, vel_y, pts_arr, takeoff_idx, params) \
                        if takeoff_idx is not None else None
    water_contact_idx = _detect_water_contact_bounded(
                            y_smooth, vel_y, conf_arr, pts_arr, apex_idx, params
                        ) if apex_idx is not None else None

    def _t(idx):
        return pts_arr[idx] if idx is not None else None

    n_valid  = sum(1 for y in y_arr if y is not None)
    coverage = n_valid / len(y_arr) if y_arr else 0.0

    return {
        "context": context,
        "prep_end_idx": prep_end_idx,
        "prep_end_t": _t(prep_end_idx),
        "takeoff_idx": takeoff_idx,
        "takeoff_t": _t(takeoff_idx),
        "apex_idx": apex_idx,
        "apex_t": _t(apex_idx),
        "water_contact_idx": water_contact_idx,
        "water_contact_t": _t(water_contact_idx),
        "confident": coverage >= params["min_coverage_for_confident"] and takeoff_idx is not None,
        "coverage": coverage,
    }


# ─── Alias for direct import consistency ─────────────────────────────────────

from proposer_event_logic_v2_1 import pts_aware_velocity   # noqa: re-export for tests
