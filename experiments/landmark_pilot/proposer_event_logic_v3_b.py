#!/usr/bin/env python3
"""Event Logic V3-B — redesigned prep_end logic over V3-A.

V3-A REGRESSION DIAGNOSIS (from PROC_V3A_EVALUATION_V1.json):
  A3 STANDING "last qualifying plateau" picked post-wc pool-deck detections as
  prep_end. Pool-deck detections have cy~0.11 (low, same as on-board position) and
  form long static plateaus at the END of the video — after water contact.
  Examples: dive 311 → prep_end=19.22s (end of video), 133 → 5.91s (post-wc),
  2387 → 24.92s (post-wc). Takeoff=None for all three.

  A4 HURDLE merge: thresh_factor=0.70 classified slow approach walk (vel~0.022-0.028)
  as "static," merging the initial rest + approach walk + on-board static into one
  long plateau. HURDLE "first qualifying" fired at end of merged plateau (post-wc
  for 1040).

V3-B CHANGES over V3-A:
  B3a (STANDING): "Last qualifying plateau BEFORE first water_line_cy_norm crossing."
    - Find first time cy > 0.50 in the smoothed trajectory — this marks the
      water-contact boundary in the detection sequence.
    - Restrict "last qualifying plateau" search to frames BEFORE this crossing.
    - Post-wc pool-deck detections are excluded. Preparation plateau found correctly.
    - If no water_line crossing found (e.g., no detected contact): fall back to
      "last qualifying plateau in first 80% of video."
    - motion_vel_thresh_factor for STANDING: 0.70 (A4, helps with 360p noise).

  B3b (HURDLE): "First qualifying plateau, min_duration=0.50s, BOUNDED by water crossing."
    - Increases min_duration from 0.40s → 0.50s to skip brief initial off-board rests.
      (dive 1040: 0.43s initial rest < 0.50s → skipped → finds on-board static instead)
    - motion_vel_thresh_factor for HURDLE: 0.50 (V2.1 level) — preserves approach walk
      detection. Higher thresh in V3-A caused approach walk to merge into plateau.
    - Bounded by first water_line crossing.

UNCHANGED from V3-A (and V2.1):
  - A1: bounded apex fallback (apex_max_window_s=1.5s)
  - A2: bounded water contact search (wc_max_window_s=2.5s)
  - classify_context, pts_aware_velocity, pts_aware_smooth, interpolate_gaps_time,
    _detect_takeoff, _detect_apex_v3, _detect_water_contact_v3

Water-line boundary rationale:
  water_line_cy_norm=0.50 is the pre-existing V2.1 parameter (not Paris-derived).
  Using it as a prep_end search boundary does NOT violate the Paris firewall.
  The boundary is computed from the trajectory itself (not GT event times).
  cy > 0.50 reliably indicates diver is at or below mid-frame (water entry zone);
  cy~0.11 pool-deck detections (post-wc) appear BEFORE cy > 0.50 in the trajectory
  would NOT trigger the boundary — however, for the dives we've seen, the trajectory
  passes through cy > 0.50 at water contact, then returns to cy~0.11 post-contact.
  So the first crossing correctly captures the preparation → water contact boundary.

DEVELOPMENT ONLY — NOT evaluated on Paris in this file.
"""

import math
from typing import List, Optional

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
from proposer_event_logic_v3_a import (
    _detect_apex_v3,
    _detect_water_contact_v3,
)

# ─── V3-B parameters ──────────────────────────────────────────────────────────

PARAMS_V3B = {
    "variant": "V3B",
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
    # V3 A1/A2 (kept from V3-A):
    "apex_max_window_s": 1.5,           # bounded apex fallback
    "wc_max_window_s": 2.5,             # bounded wc search
    # V3-B new / changed:
    "motion_vel_thresh_factor_standing": 0.70,   # STANDING: tolerates 360p noise
    "motion_vel_thresh_factor_hurdle":   0.50,   # HURDLE: V2.1 level (preserves approach detection)
    "static_min_duration_standing_s":   0.40,   # STANDING: min plateau duration
    "static_min_duration_hurdle_s":     0.50,   # HURDLE: skip brief initial rests (0.43s < 0.50s → skip)
    "wc_boundary_fallback_frac": 0.80,           # fallback: search first 80% if no water_line crossing
}


# ─── B3: water-line bounded prep_end ──────────────────────────────────────────

def _find_water_line_crossing(y_smooth, pts_arr, water_line):
    """Find first frame index where y_smooth > water_line.

    Used as the prep_end search boundary: preparation must end BEFORE the diver
    crosses the water line in the detection sequence.

    Returns frame index or None if never crossed.
    """
    for i, y in enumerate(y_smooth):
        if y is not None and y > water_line:
            return i
    return None


def _find_preparation_end_v3b(y_smooth, pts_arr, params, context="STANDING"):
    """V3-B fix B3: water-line bounded, context-sensitive prep_end.

    STANDING (B3a):
      motion_vel_thresh_factor=0.70 (tolerates 360p noise).
      min_duration=0.40s.
      Last qualifying plateau BEFORE first water_line_cy_norm crossing.
      Post-wc pool-deck detections (cy~0.11, post-water-entry) are excluded.
      Fallback if no crossing: last plateau in first 80% of video.

    HURDLE (B3b):
      motion_vel_thresh_factor=0.50 (V2.1 level — preserves approach detection).
      min_duration=0.50s (skips brief initial off-board rests < 0.50s).
      First qualifying plateau BEFORE first water_line_cy_norm crossing.
    """
    water_line = params.get("water_line_cy_norm", 0.50)
    vel_max_gap_s = params.get("vel_max_gap_s", 0.20)
    n = len(y_smooth)

    if context == "HURDLE":
        thresh_factor = params.get("motion_vel_thresh_factor_hurdle", 0.50)
        min_dur_s = params.get("static_min_duration_hurdle_s", 0.50)
    else:
        thresh_factor = params.get("motion_vel_thresh_factor_standing", 0.70)
        min_dur_s = params.get("static_min_duration_standing_s", 0.40)

    motion_vel_thresh = params["takeoff_vel_threshold"] * thresh_factor
    vel = pts_aware_velocity(y_smooth, pts_arr, max_gap_s=vel_max_gap_s)

    # Determine search boundary
    crossing_idx = _find_water_line_crossing(y_smooth, pts_arr, water_line)
    if crossing_idx is not None:
        search_end = crossing_idx
    else:
        # Fallback: first 80% of video
        fallback_frac = params.get("wc_boundary_fallback_frac", 0.80)
        search_end = int(n * fallback_frac)

    # Plateau tracking within [1, search_end)
    plateau_start_idx = None
    plateau_end_idx = None
    last_good_prep_end = None

    for i in range(1, search_end):
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
            # Motion: finalize current plateau
            if plateau_end_idx is not None and plateau_start_idx is not None:
                dur = pts_arr[plateau_end_idx] - pts_arr[plateau_start_idx]
                if dur >= min_dur_s:
                    if context == "HURDLE":
                        return plateau_end_idx   # first qualifying
                    else:
                        last_good_prep_end = plateau_end_idx  # track last
            plateau_start_idx = None
            plateau_end_idx = None

    # Finalize trailing plateau (if still within search window)
    if plateau_end_idx is not None and plateau_start_idx is not None:
        dur = pts_arr[plateau_end_idx] - pts_arr[plateau_start_idx]
        if dur >= min_dur_s:
            if context == "HURDLE":
                return plateau_end_idx
            else:
                last_good_prep_end = plateau_end_idx

    return last_good_prep_end


# ─── Top-level proposer ───────────────────────────────────────────────────────

def propose_events_v3b(y_arr, pts_arr, conf_arr, dive_code, params):
    """Run V3-B event state machine.

    Changes from V3-A:
      - _find_preparation_end_v3b (B3): water-line bounded, context-sensitive
    Kept from V3-A:
      - _detect_apex_v3 (A1): bounded fallback
      - _detect_water_contact_v3 (A2): bounded search
    """
    context = classify_context(dive_code)

    y_smooth = pts_aware_smooth(y_arr, pts_arr, sigma_s=params["smooth_window_s"] / 3)
    y_smooth = interpolate_gaps_time(y_smooth, pts_arr, max_gap_s=params["interp_max_gap_s"])
    vel_y = pts_aware_velocity(y_smooth, pts_arr, max_gap_s=params["vel_max_gap_s"])

    prep_end_idx = _find_preparation_end_v3b(y_smooth, pts_arr, params, context)
    takeoff_idx  = _detect_takeoff(y_smooth, vel_y, pts_arr, prep_end_idx, context, params) \
        if prep_end_idx is not None else None
    apex_idx     = _detect_apex_v3(y_smooth, vel_y, pts_arr, takeoff_idx, params) \
        if takeoff_idx is not None else None
    wc_idx       = _detect_water_contact_v3(
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
        "water_contact_idx": wc_idx,
        "water_contact_t": _t(wc_idx),
        "confident": confident,
        "coverage": coverage,
    }
