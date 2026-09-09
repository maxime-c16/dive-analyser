#!/usr/bin/env python3
"""Event Logic V3-A — targeted fixes for V2.1 failure modes on real 360p trajectories.

CONFIRMED FAILURE MODES from PROC_EL_EVALUATION_V1.json:
  1. UNBOUNDED APEX FALLBACK: V2.1 _detect_apex fallback searches [takeoff, end-of-video].
     Post-wc detections at cy~0.11 (pool-deck level) become the "minimum y" fallback
     apex, pushing water-contact search far beyond actual wc (dive 311: 3.53s error).
  2. UNBOUNDED WC SEARCH: _detect_water_contact searches [apex, end-of-video].
     Compounds the unbounded apex issue for all dives.
  3. PREMATURE PREP_END (STANDING): V2.1 returns at first static→motion transition.
     Long-preparation videos (diver approaches board) misidentify the initial rest as
     prep_end (dives 2387: 2.15s early, 2169 hurdle: 1.28s late).
  4. HIGH VELOCITY NOISE AT 360p: motion_vel_thresh = 0.02 is too strict for 360p;
     detection noise at low resolution causes prep detection failure (dive 676: None).

V3-A CHANGES over V2.1:
  A1. _detect_apex: bounded fallback — search only [takeoff, takeoff + apex_max_window_s].
  A2. _detect_water_contact: bounded search — only [apex, apex + wc_max_window_s].
  A3. _find_preparation_end: multi-plateau.
      STANDING: return end of LAST qualifying plateau (handles long-prep videos).
      HURDLE: return end of FIRST qualifying plateau with extended min_duration.
  A4. motion_vel_thresh_factor: 0.70 (V2.1: 0.50) — more tolerant of 360p noise.
  A5. static_min_duration_v3_s: 0.40s (V2.1: 0.25s).

UNCHANGED from V2.1:
  - classify_context, pts_aware_velocity, rolling_variance_time, pts_aware_smooth,
    interpolate_gaps_time, _detect_takeoff.
  - All PARAMS_E1 parameters except motion_vel_thresh_factor.
  - Coordinate convention (cy_norm throughout).
  - No GT event-time windows, no Paris-derived thresholds.
  - No truncation at estimated water contact.

DEVELOPMENT ONLY — NOT evaluated on Paris.
"""

import math
from typing import List, Optional

# Re-use all unchanged primitives from V2.1
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from proposer_event_logic_v2_1 import (
    classify_context,
    pts_aware_velocity,
    rolling_variance_time,
    pts_aware_smooth,
    interpolate_gaps_time,
    _detect_takeoff,
)

# ─── V3-A parameters ──────────────────────────────────────────────────────────

PARAMS_V3A = {
    "variant": "V3A",
    # Unchanged from V2.1 E1:
    "smooth_window_s": 0.35,
    "interp_max_gap_s": 0.30,
    "vel_max_gap_s": 0.20,
    "static_var_threshold": 0.0015,
    "takeoff_vel_threshold": 0.04,
    "takeoff_sustained_s": 0.15,
    "takeoff_min_after_prep_s": 0.10,
    "hurdle_post_plateau_guard_s": 0.40,
    "apex_search_start_s": 0.08,
    "water_line_cy_norm": 0.50,
    "water_contact_method": "cy_threshold_or_dropout",
    "water_contact_min_after_apex_s": 0.05,
    "min_coverage_for_confident": 0.15,
    "use_scene_priors": False,
    "water_line_auto": False,
    # V3-A new / changed:
    "motion_vel_thresh_factor": 0.70,   # V2.1: 0.50
    "static_min_duration_v3_s": 0.40,   # V2.1: 0.25
    "apex_max_window_s": 1.5,           # NEW: bound apex fallback
    "wc_max_window_s": 2.5,             # NEW: bound wc search
}


# ─── A1: bounded apex detection ───────────────────────────────────────────────

def _detect_apex_v3(y_smooth, vel_y, pts_arr, takeoff_idx, params):
    """V3-A fix A1: bounded fallback for apex search.

    Primary unchanged: velocity zero-crossing neg→pos after takeoff+start_s.
    Fallback: minimum y in [takeoff, takeoff + apex_max_window_s] ONLY.
    V2.1 searched [takeoff, end-of-video], causing post-wc pool-deck detections
    to become the 'apex' when flight velocity is noisy (dive 311: 3.53s wc error).
    """
    n = len(y_smooth)
    search_start_t = pts_arr[takeoff_idx] + params["apex_search_start_s"]
    max_window_s = params.get("apex_max_window_s", 1.5)
    apex_search_end_t = pts_arr[takeoff_idx] + max_window_s

    # Primary: velocity zero-crossing negative → non-negative
    prev_v = None
    for i in range(takeoff_idx + 1, n):
        if pts_arr[i] > apex_search_end_t:
            break
        if pts_arr[i] < search_start_t:
            prev_v = vel_y[i]
            continue
        v = vel_y[i]
        if v is None:
            prev_v = None
            continue
        if prev_v is not None and prev_v < 0 and v >= 0:
            return i - 1
        prev_v = v

    # Fallback: min y in BOUNDED window [takeoff+start, takeoff+max_window]
    best_idx = None
    best_y = None
    for i in range(takeoff_idx + 1, n):
        if pts_arr[i] < search_start_t:
            continue
        if pts_arr[i] > apex_search_end_t:
            break
        if y_smooth[i] is None:
            continue
        if best_y is None or y_smooth[i] < best_y:
            best_y = y_smooth[i]
            best_idx = i

    return best_idx


# ─── A2: bounded water contact detection ──────────────────────────────────────

def _detect_water_contact_v3(y_smooth, vel_y, conf_arr, pts_arr, apex_idx, params):
    """V3-A fix A2: bounded water contact search window.

    Primary: first frame in [apex+min, apex+max_window] where y_smooth > water_line.
    Fallback: last frame with conf>0.3 in the SAME bounded window.
    V2.1 searched [apex, end-of-video]; post-wc activity caused wc found 3.5s late.
    """
    n = len(y_smooth)
    min_after_apex_s = params["water_contact_min_after_apex_s"]
    water_thresh = params["water_line_cy_norm"]
    max_window_s = params.get("wc_max_window_s", 2.5)
    search_start_t = pts_arr[apex_idx] + min_after_apex_s
    search_end_t = pts_arr[apex_idx] + max_window_s

    for i in range(apex_idx + 1, n):
        if pts_arr[i] > search_end_t:
            break
        if pts_arr[i] < search_start_t:
            continue
        if y_smooth[i] is None:
            continue
        if y_smooth[i] > water_thresh:
            return i

    # Fallback: last confident frame in bounded window
    last_conf = None
    for i in range(apex_idx + 1, n):
        if pts_arr[i] > search_end_t:
            break
        if pts_arr[i] < search_start_t:
            continue
        if conf_arr[i] > 0.3:
            last_conf = i

    return last_conf


# ─── A3+A4: multi-plateau, context-aware preparation detection ─────────────────

def _find_preparation_end_v3(y_arr, pts_arr, params, context="STANDING"):
    """V3-A fix A3+A4: multi-plateau, context-aware prep_end detection.

    A4 fix: motion_vel_thresh_factor=0.70 (V2.1: 0.50) handles 360p detection noise.
    A3 fix (STANDING): return end of LAST qualifying plateau.
      - Handles long-prep videos: (initial motion) → (on-board static) → (takeoff)
      - V2.1 returned at first static→motion transition (too early).
    A3 fix (HURDLE): return end of FIRST qualifying plateau, min_duration extended.
      - min_duration_v3_s=0.40s (V2.1: 0.25s) skips brief early rests.
      - Detects on-board static before hurdle jump (not board-recontact after it).
    """
    min_dur_s = params.get("static_min_duration_v3_s", 0.40)
    vel_max_gap_s = params.get("vel_max_gap_s", 0.20)
    thresh_factor = params.get("motion_vel_thresh_factor", 0.70)
    motion_vel_thresh = params["takeoff_vel_threshold"] * thresh_factor
    n = len(y_arr)

    vel = pts_aware_velocity(y_arr, pts_arr, max_gap_s=vel_max_gap_s)

    # Track plateau
    plateau_start_idx = None   # index where current plateau started
    plateau_end_idx = None     # index of last static frame in current plateau
    last_good_prep_end = None  # last qualifying plateau end (STANDING: updated throughout)

    for i in range(1, n):
        v = vel[i]
        if v is None:
            # Unknown velocity (gap): don't break plateau
            continue

        if abs(v) <= motion_vel_thresh:
            # Static frame
            if plateau_start_idx is None:
                plateau_start_idx = i
            plateau_end_idx = i
        else:
            # Motion frame: finalize current plateau
            if plateau_end_idx is not None and plateau_start_idx is not None:
                dur = pts_arr[plateau_end_idx] - pts_arr[plateau_start_idx]
                if dur >= min_dur_s:
                    if context == "HURDLE":
                        # First qualifying plateau: return immediately
                        return plateau_end_idx
                    else:
                        # STANDING: record and continue (find last)
                        last_good_prep_end = plateau_end_idx
            # Reset
            plateau_start_idx = None
            plateau_end_idx = None

    # Finalize trailing plateau (motion never interrupted)
    if plateau_end_idx is not None and plateau_start_idx is not None:
        dur = pts_arr[plateau_end_idx] - pts_arr[plateau_start_idx]
        if dur >= min_dur_s:
            last_good_prep_end = plateau_end_idx

    return last_good_prep_end


# ─── Top-level proposer ───────────────────────────────────────────────────────

def propose_events_v3a(y_arr, pts_arr, conf_arr, dive_code, params):
    """Run V3-A event state machine.

    Changes from V2.1:
      - _find_preparation_end_v3 (A3+A4): multi-plateau, context-aware
      - _detect_apex_v3 (A1): bounded fallback
      - _detect_water_contact_v3 (A2): bounded search
    """
    context = classify_context(dive_code)

    y_smooth = pts_aware_smooth(y_arr, pts_arr, sigma_s=params["smooth_window_s"] / 3)
    y_smooth = interpolate_gaps_time(y_smooth, pts_arr, max_gap_s=params["interp_max_gap_s"])
    vel_y = pts_aware_velocity(y_smooth, pts_arr, max_gap_s=params["vel_max_gap_s"])

    prep_end_idx = _find_preparation_end_v3(y_smooth, pts_arr, params, context)
    takeoff_idx = _detect_takeoff(y_smooth, vel_y, pts_arr, prep_end_idx, context, params)
    apex_idx = _detect_apex_v3(y_smooth, vel_y, pts_arr, takeoff_idx, params) \
        if takeoff_idx is not None else None
    water_contact_idx = _detect_water_contact_v3(
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
