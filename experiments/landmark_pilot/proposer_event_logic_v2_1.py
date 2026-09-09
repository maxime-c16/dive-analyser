#!/usr/bin/env python3
"""Event Logic V2.1 — cy_norm-correct state-machine landmark proposer.

Coordinate convention (cy_norm, used throughout):
  y_arr[i] = normalised vertical centre of diver bounding box.
  0 = top of frame, 1 = bottom of frame.
  Rising diver  → y decreases → velocity NEGATIVE.
  Falling diver → y increases → velocity POSITIVE.
  Water contact → y > water_line_cy_norm (diver crosses into lower-frame region).

V2.1 fixes over V2:
  - _detect_takeoff: searches for sustained NEGATIVE velocity (rising = takeoff).
  - _detect_takeoff HURDLE: finds hurdle apex = FIRST local minimum via first
    neg→non-neg velocity crossing (NOT global min-y — flight apex is lower than
    hurdle apex in cy_norm so global min finds the wrong event). board_recontact
    is that crossing frame directly; then search sustained negative velocity.
  - _detect_apex: velocity crossing negative→positive = apex; fallback = min y.
  - All trajectory-based tests use cy_norm fixtures (not physical / inverted).
  - Water contact unchanged (y > thresh already correct for cy_norm).
  - known_limitations updated (CUDA claim removed).

SUPERSEDES: proposer_event_logic_v2.py (coordinate convention error in takeoff/apex).
"""

import math
from typing import List, Optional

# ─── Parameter dictionaries ───────────────────────────────────────────────────

PARAMS_E1 = {
    "variant": "E1",
    "detector": "yolov8n",
    "detector_imgsz": 640,
    "detector_conf": 0.10,
    "detector_iou": 0.45,
    "detector_classes": [0],
    "tracker": "bytetrack",
    "track_min_conf": 0.10,
    "track_select_strategy": "longest_x_conf",
    "smooth_window_s": 0.35,
    "interp_max_gap_s": 0.30,
    "vel_max_gap_s": 0.20,
    "static_var_threshold": 0.0015,
    "static_window_s": 0.40,
    "static_min_duration_s": 0.25,
    "takeoff_vel_threshold": 0.04,
    "takeoff_sustained_s": 0.15,
    "takeoff_min_after_prep_s": 0.10,
    "hurdle_post_plateau_guard_s": 0.40,
    "apex_search_start_s": 0.08,
    "water_line_cy_norm": 0.50,
    "water_contact_method": "cy_threshold_or_dropout",
    "water_contact_min_after_apex_s": 0.05,
    "min_coverage_for_confident": 0.15,
    "max_takeoff_error_for_confident": 0.50,
    "use_scene_priors": False,
    "board_cx_min": 0.50,
    "board_cx_max": 1.00,
    "water_line_auto": False,
}

PARAMS_E2 = dict(PARAMS_E1)
PARAMS_E2.update({
    "variant": "E2",
    "use_scene_priors": True,
    "water_line_cy_norm": 0.45,
    "water_line_auto": True,
})


# ─── Context classification (unchanged from V2) ───────────────────────────────

def classify_context(dive_code):
    """Return 'HURDLE', 'STANDING', or 'UNKNOWN' from FINA dive code."""
    if not dive_code:
        return "UNKNOWN"
    code = dive_code.strip()
    if not code:
        return "UNKNOWN"
    try:
        first = int(code[0])
    except (ValueError, IndexError):
        return "UNKNOWN"

    if first == 5:
        if len(code) < 2:
            return "UNKNOWN"
        try:
            approach = int(code[1])
        except ValueError:
            return "UNKNOWN"
        return "HURDLE" if approach in (0, 1) else "STANDING"

    if first in (0, 1):
        return "HURDLE"
    if first in (2, 3, 4):
        return "STANDING"
    return "UNKNOWN"


# ─── PTS-aware signal primitives (unchanged from V2) ─────────────────────────

def pts_aware_velocity(y_arr, pts_arr, max_gap_s=0.20):
    """Compute frame-by-frame velocity using actual PTS differences.

    In cy_norm convention: negative velocity = diver rising.
    """
    n = len(y_arr)
    vel = [None] * n
    for i in range(1, n):
        if y_arr[i] is None or y_arr[i - 1] is None:
            continue
        gap = pts_arr[i] - pts_arr[i - 1]
        if gap <= 0 or gap > max_gap_s:
            continue
        vel[i] = (y_arr[i] - y_arr[i - 1]) / gap
    return vel


def rolling_variance_time(y_arr, pts_arr, window_s):
    """Rolling variance using a centered time window."""
    n = len(y_arr)
    half = window_s / 2.0
    variances = [None] * n
    for i in range(n):
        tc = pts_arr[i]
        vals = [
            y_arr[j]
            for j in range(n)
            if abs(pts_arr[j] - tc) <= half and y_arr[j] is not None
        ]
        if len(vals) < 2:
            continue
        mean = sum(vals) / len(vals)
        variances[i] = sum((v - mean) ** 2 for v in vals) / len(vals)
    return variances


def pts_aware_smooth(y_arr, pts_arr, sigma_s):
    """Gaussian-weighted smoothing in time domain using PTS."""
    n = len(y_arr)
    smoothed = [None] * n
    cutoff = 3.0 * sigma_s
    for i in range(n):
        tc = pts_arr[i]
        wsum = 0.0
        vsum = 0.0
        for j in range(n):
            dt = pts_arr[j] - tc
            if abs(dt) > cutoff:
                continue
            if y_arr[j] is None:
                continue
            w = math.exp(-0.5 * (dt / sigma_s) ** 2)
            wsum += w
            vsum += w * y_arr[j]
        if wsum > 0:
            smoothed[i] = vsum / wsum
    return smoothed


def interpolate_gaps_time(y_arr, pts_arr, max_gap_s):
    """Linear interpolation across gaps shorter than max_gap_s."""
    n = len(y_arr)
    result = list(y_arr)
    i = 0
    while i < n:
        if result[i] is not None:
            i += 1
            continue
        gap_start = i - 1
        if gap_start < 0:
            i += 1
            continue
        if result[gap_start] is None:
            # Left boundary has no value — skip (leading or adjacent-None gap).
            i += 1
            continue
        j = i
        while j < n and result[j] is None:
            j += 1
        if j >= n:
            break
        gap_end = j
        gap_dur = pts_arr[gap_end] - pts_arr[gap_start]
        if 0 < gap_dur <= max_gap_s:
            y0 = result[gap_start]
            y1 = result[gap_end]
            for k in range(gap_start + 1, gap_end):
                t = (pts_arr[k] - pts_arr[gap_start]) / gap_dur
                result[k] = y0 + t * (y1 - y0)
        i = j + 1
    return result


# ─── State machine internals ──────────────────────────────────────────────────

def _find_preparation_end(y_arr, pts_arr, params):
    """Return index of last frame of initial static plateau, or None.

    Uses absolute velocity: convention-agnostic (unchanged from V2).
    """
    min_dur_s = params["static_min_duration_s"]
    vel_max_gap_s = params.get("vel_max_gap_s", 0.20)
    motion_vel_thresh = params["takeoff_vel_threshold"] * 0.5
    n = len(y_arr)

    vel = pts_aware_velocity(y_arr, pts_arr, max_gap_s=vel_max_gap_s)

    prep_end = None
    for i in range(1, n):
        v = vel[i]
        if v is None:
            continue
        if abs(v) <= motion_vel_thresh:
            if pts_arr[i] >= min_dur_s:
                prep_end = i
        else:
            if prep_end is not None:
                return prep_end

    return None


def _detect_takeoff(y_smooth, vel_y, pts_arr, prep_end_idx, context, params):
    """Detect the final takeoff frame (cy_norm convention).

    Rising = NEGATIVE velocity (y_norm decreases as diver goes up).

    STANDING: search for first sustained negative velocity after
              prep_end + takeoff_min_after_prep_s.

    HURDLE:
      1. After guard, find hurdle apex = FIRST local minimum via first
         neg→non-neg velocity crossing (cy_norm convention: ascending = negative
         velocity, so the hurdle apex is where velocity first turns non-negative).
         NOTE: do NOT use global minimum y — the flight apex (reached after final
         takeoff) is lower in cy_norm than the hurdle apex, so global-min would
         find the wrong event.
      2. The crossing frame is already board_recontact. No separate Step 2 loop.
      3. After board_recontact, search for sustained negative velocity
         (the true final departure from the board).
    """
    n = len(y_smooth)
    prep_t = pts_arr[prep_end_idx] if prep_end_idx is not None else 0.0
    min_after_prep_s = params["takeoff_min_after_prep_s"]
    vel_thresh = params["takeoff_vel_threshold"]
    sustained_s = params["takeoff_sustained_s"]

    if context == "HURDLE":
        guard_s = params["hurdle_post_plateau_guard_s"]
        guard_end_t = prep_t + guard_s

        # Step 1+2 combined: hurdle apex = FIRST local minimum, found by the first
        # negative→non-negative velocity crossing after guard_end_t (cy_norm: rising
        # diver has negative velocity; first time velocity ≥ 0 marks the peak of the
        # hurdle jump and the start of descent back to the board = board_recontact).
        # This is correct even when the flight apex (later) has lower cy_norm.
        hurdle_apex_idx = None
        board_recontact_idx = None
        prev_v = None
        for i in range(n):
            if pts_arr[i] < guard_end_t:
                prev_v = vel_y[i]
                continue
            v = vel_y[i]
            if v is None:
                prev_v = None
                continue
            if prev_v is not None and prev_v < 0 and v >= 0:
                hurdle_apex_idx = i - 1   # last ascending frame
                board_recontact_idx = i   # first frame of descent back to board
                break
            prev_v = v

        if board_recontact_idx is not None:
            search_start_t = pts_arr[board_recontact_idx]
        else:
            search_start_t = guard_end_t + min_after_prep_s
    else:
        # STANDING: search immediately after plateau + minimum delay
        search_start_t = prep_t + min_after_prep_s

    # Find first sustained negative velocity (cy_norm: negative = rising = takeoff)
    for i in range(n):
        if pts_arr[i] < search_start_t:
            continue
        v = vel_y[i]
        if v is None or v >= -vel_thresh:
            continue
        # Check sustainability: ALL frames in next sustained_s must have v < -vel_thresh
        t_end = pts_arr[i] + sustained_s
        n_above = 0
        n_total = 0
        for j in range(i + 1, n):
            if pts_arr[j] > t_end:
                break
            n_total += 1
            if vel_y[j] is not None and vel_y[j] < -vel_thresh:
                n_above += 1
        if n_total > 0 and n_above == n_total:
            return i

    return None


def _detect_apex(y_smooth, vel_y, pts_arr, takeoff_idx, params):
    """Detect the apex (minimum cy_norm = highest physical point) of the flight arc.

    Primary: velocity zero-crossing (negative → non-negative) after
             takeoff + apex_search_start_s. In cy_norm, the diver goes from
             ascending (negative velocity) to descending (positive velocity).
    Fallback: frame of minimum y_smooth in the search window.
    """
    n = len(y_smooth)
    search_start_t = pts_arr[takeoff_idx] + params["apex_search_start_s"]

    # Primary: velocity crossing from negative to non-negative
    prev_v = None
    for i in range(takeoff_idx + 1, n):
        if pts_arr[i] < search_start_t:
            prev_v = vel_y[i]
            continue
        v = vel_y[i]
        if v is None:
            prev_v = None
            continue
        if prev_v is not None and prev_v < 0 and v >= 0:
            return i - 1  # last ascending frame = apex
        prev_v = v

    # Fallback: minimum y in search window (= highest physical point in cy_norm)
    best_idx = None
    best_y = None
    for i in range(takeoff_idx + 1, n):
        if pts_arr[i] < search_start_t:
            continue
        if y_smooth[i] is None:
            continue
        if best_y is None or y_smooth[i] < best_y:
            best_y = y_smooth[i]
            best_idx = i

    return best_idx


def _detect_water_contact(y_smooth, vel_y, conf_arr, pts_arr, apex_idx, params):
    """Detect water contact frame (cy_norm convention, unchanged from V2).

    Primary: first frame after apex where y_smooth > water_line_cy_norm
             (larger cy_norm = lower in portrait frame = closer to water).
    Fallback: last frame with confident detection after apex.
    """
    n = len(y_smooth)
    min_after_apex_s = params["water_contact_min_after_apex_s"]
    water_thresh = params["water_line_cy_norm"]
    search_start_t = pts_arr[apex_idx] + min_after_apex_s

    for i in range(apex_idx + 1, n):
        if pts_arr[i] < search_start_t:
            continue
        if y_smooth[i] is None:
            continue
        if y_smooth[i] > water_thresh:
            return i

    # Fallback
    last_conf = None
    for i in range(apex_idx + 1, n):
        if pts_arr[i] < search_start_t:
            continue
        if conf_arr[i] > 0.3:
            last_conf = i

    return last_conf


# ─── Top-level proposer ───────────────────────────────────────────────────────

def propose_events(y_arr, pts_arr, conf_arr, dive_code, params):
    """Run the full event state machine and return landmark estimates.

    y_arr must be in cy_norm convention (0=top, 1=bottom of frame).
    Rising diver = decreasing y_arr = negative velocity.
    """
    context = classify_context(dive_code)

    y_smooth = pts_aware_smooth(y_arr, pts_arr, sigma_s=params["smooth_window_s"] / 3)
    y_smooth = interpolate_gaps_time(y_smooth, pts_arr, max_gap_s=params["interp_max_gap_s"])
    vel_y = pts_aware_velocity(y_smooth, pts_arr, max_gap_s=params["vel_max_gap_s"])

    prep_end_idx = _find_preparation_end(y_smooth, pts_arr, params)
    takeoff_idx = _detect_takeoff(y_smooth, vel_y, pts_arr, prep_end_idx, context, params)
    apex_idx = _detect_apex(y_smooth, vel_y, pts_arr, takeoff_idx, params) \
        if takeoff_idx is not None else None
    water_contact_idx = _detect_water_contact(
        y_smooth, vel_y, conf_arr, pts_arr, apex_idx, params
    ) if apex_idx is not None else None

    def _t(idx):
        return pts_arr[idx] if idx is not None else None

    n_valid = sum(1 for y in y_arr if y is not None)
    coverage = n_valid / len(y_arr) if y_arr else 0.0
    confident = coverage >= params["min_coverage_for_confident"] and takeoff_idx is not None

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
        "confident": confident,
        "coverage": coverage,
    }
