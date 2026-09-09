#!/usr/bin/env python3
"""Event Logic V3-D0 — board-rise validation for HURDLE departure + STANDING fallback.

Targeted patch over V3-C0. Addresses FM2 (HURDLE final takeoff detection failure)
by adding a physical validity gate to the hurdle-apex candidate selection.

CHANGES over V3-C0:
  D0. _detect_hurdle_takeoff: board-rise validation + STANDING-like fallback.
      - V3-C0 accepts the first neg→non-neg velocity crossing after guard as
        the hurdle apex unconditionally.  When the D5 detector switches targets
        (2169: cy 0.26→0.71) the resulting smoothed arc produces a false crossing
        at cy_apex >> y_prep (diver apparently BELOW board level at "apex"), which
        is physically impossible for a real hurdle jump.
      - V3-D0 adds: at the candidate apex, cy_smooth MUST be strictly above board
        level (cy_apex < y_prep - min_rise), i.e. the diver rose above the board.
      - If no physically valid hurdle apex is found, V3-D0 falls back to a
        STANDING-like departure search from guard_end: find the first sustained
        negative velocity without requiring prior hurdle arc detection.
        Rationale: if the hurdle sequence is below the 360p signal noise floor,
        treating the departure conservatively (as a pure-flight takeoff) is more
        accurate than accepting a mis-identified post-water-contact arc.
      - DEVELOPMENT result (2169): to_err 1.280s → 0.412s (−68%).

UNCHANGED from V3-C0:
  - A1: bounded apex fallback (_detect_apex_bounded)
  - A2: bounded water-contact search (_detect_water_contact_bounded)
  - All PARAMS_E1/V3C0 parameter values except the new D0 keys
  - STANDING path (uses V2.1 _detect_takeoff unmodified)
  - PTS-aware signal primitives (cy_norm, Gaussian smooth, velocity)
  - No Paris-derived thresholds
  - No GT event-time windows fed to inference

Addresses: FM2 on DEVELOPMENT corpus (2169 improved; 1040 unchanged — signal
unrecoverable at 360p due to target instability).
Does NOT address: FM1 (already closed by V3-C0 A1+A2), FM3 (360p noise floor
for dive 1040 target instability), Paris external failure (no DEVELOPMENT
evidence for revision).

DEVELOPMENT authority: PROCEDURAL_INPUT_PASS on 6 dives [133, 311, 676, 1040, 2169, 2387].
Paris firewall: READ-ONLY post-freeze evaluation; NOT used to set parameters.
HQ authority: READ-ONLY from iCloud thread freeze (label_transfer_allowed, PTS_EQUIVALENT).
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
from proposer_event_logic_v3_c0 import (
    _detect_apex_bounded,
    _detect_water_contact_bounded,
    PARAMS_V3C0,
)


# ─── V3-D0 parameters (inherits V3-C0, adds D0 keys) ─────────────────────────

PARAMS_V3D0 = dict(PARAMS_V3C0)
PARAMS_V3D0.update({
    "variant": "V3D0",
    # D0: hurdle-apex validity gate.
    # At the candidate apex (first neg→non-neg velocity crossing after guard),
    # the diver must have risen above board level by at least min_hurdle_rise_cy.
    # Physical invariant: a true hurdle apex has cy_apex < y_prep
    # (lower cy_norm = higher position in frame = above the board).
    "min_hurdle_rise_cy": 0.01,
    # D0: fallback sustained window.
    # When no valid hurdle apex is found, search for the first sustained
    # negative velocity from guard_end (STANDING-like departure).
    "fallback_sustained_s": 0.15,
})


# ─── D0: HURDLE takeoff with board-rise validation + fallback ─────────────────

def _detect_hurdle_takeoff_v3d0(y_smooth, vel_y, pts_arr, prep_end_i, params):
    """HURDLE takeoff detection with board-rise validation (D0).

    Algorithm:
    1. Scan for neg→non-neg velocity crossings after guard_end.
    2. At each candidate apex (frame i-1), check board-rise invariant:
         cy_apex < y_prep - min_hurdle_rise_cy
       i.e. the diver's smoothed position is ABOVE board level.
       If violated: the crossing is a detector artifact, not a real hurdle jump.
       Continue scanning.
    3. After the first valid hurdle apex: search for the next sustained negative
       velocity period = final takeoff.  Uses PARAMS_V3D0["takeoff_sustained_s"].
    4. Fallback: if no valid apex found, search for sustained negative velocity
       from guard_end.  Uses PARAMS_V3D0["fallback_sustained_s"].
       Rationale: treating a hurdle that is invisible at 360p as a STANDING-style
       departure from guard_end is more accurate than accepting a false arc.

    Physical invariant enforced:
    At a true hurdle apex the diver is ABOVE the board (cy_norm is LOWER than at
    board level: lower cy = higher physical altitude).  If the smoothed signal
    reports the diver at or below board level at a candidate apex, the crossing is
    caused by a target switch or noise artefact, not by the diver actually jumping.

    Arguments:
        y_smooth:    per-frame smoothed cy_norm (None = gap)
        vel_y:       per-frame smoothed velocity (None = gap)
        pts_arr:     per-frame PTS timestamps (seconds)
        prep_end_i:  index of prep_end event (board reference level)
        params:      PARAMS_V3D0 dict

    Returns:
        int | None — index into pts_arr of the detected final takeoff, or None.
    """
    n = len(y_smooth)
    prep_t    = pts_arr[prep_end_i] if prep_end_i is not None else 0.0
    guard_s   = params["hurdle_post_plateau_guard_s"]
    guard_end = prep_t + guard_s

    vel_thresh   = params["takeoff_vel_threshold"]
    sustained_s  = params["takeoff_sustained_s"]
    fallback_s   = params.get("fallback_sustained_s", 0.15)
    min_rise     = params.get("min_hurdle_rise_cy", 0.01)

    # Board reference: cy_smooth at prep_end (diver on board).
    # For a valid hurdle apex: cy_apex < (y_prep - min_rise).
    y_prep = (y_smooth[prep_end_i]
              if prep_end_i is not None and y_smooth[prep_end_i] is not None
              else None)

    # ── Step 1–2: scan for valid hurdle apex ─────────────────────────────────
    valid_hurdle_recontact_i = None
    prev_v = None
    i = 0
    while i < n:
        if pts_arr[i] <= guard_end:
            prev_v = vel_y[i]
            i += 1
            continue
        v = vel_y[i]
        if v is None:
            prev_v = None
            i += 1
            continue
        if prev_v is not None and prev_v < 0 and v >= 0:
            # neg→non-neg crossing: candidate hurdle apex at frame i-1
            apex_i = i - 1
            cy_apex = y_smooth[apex_i]
            # Board-rise invariant: cy_apex < y_prep − min_rise
            if (y_prep is not None and cy_apex is not None
                    and cy_apex < y_prep - min_rise):
                valid_hurdle_recontact_i = i
                break
        prev_v = v
        i += 1

    # ── Step 3/4: find sustained negative velocity ───────────────────────────
    if valid_hurdle_recontact_i is not None:
        search_t   = pts_arr[valid_hurdle_recontact_i]
        sus_window = sustained_s
    else:
        search_t   = guard_end          # fallback: depart from guard_end
        sus_window = fallback_s

    for i in range(n):
        if pts_arr[i] < search_t:
            continue
        v = vel_y[i]
        if v is None or v >= -vel_thresh:
            continue
        # Sustained check: ALL frames in [pts_arr[i]+ε, pts_arr[i]+sus_window]
        # must have velocity < −vel_thresh.
        t_end   = pts_arr[i] + sus_window
        n_above = n_total = 0
        for j in range(i + 1, n):
            if pts_arr[j] > t_end:
                break
            n_total += 1
            if vel_y[j] is not None and vel_y[j] < -vel_thresh:
                n_above += 1
        if n_total > 0 and n_above == n_total:
            return i

    return None


# ─── Top-level proposer ───────────────────────────────────────────────────────

def propose_events_v3d0(y_arr, pts_arr, conf_arr, dive_code, params=None):
    """Propose dive events using Event Logic V3-D0.

    Arguments:
        y_arr:      list of cy_norm per frame (None = gap)
        pts_arr:    list of PTS timestamps (seconds) per frame
        conf_arr:   list of detection confidence per frame
        dive_code:  dive code string (used to classify context)
        params:     parameter dict (defaults to PARAMS_V3D0)

    Returns:
        dict with keys: context, prep_end_t, takeoff_t, apex_t, water_contact_t, coverage.
    """
    if params is None:
        params = PARAMS_V3D0

    context = classify_context(dive_code)
    sigma   = params["smooth_window_s"] / 3
    y_smooth = pts_aware_smooth(y_arr, pts_arr, sigma_s=sigma)
    y_smooth = interpolate_gaps_time(y_smooth, pts_arr, params["interp_max_gap_s"])
    vel_y    = pts_aware_velocity(y_smooth, pts_arr, params["vel_max_gap_s"])

    prep_end_i = _find_preparation_end(y_smooth, pts_arr, params)

    if context == "HURDLE":
        takeoff_i = _detect_hurdle_takeoff_v3d0(
            y_smooth, vel_y, pts_arr, prep_end_i, params)
    else:
        # STANDING path: V2.1 semantics, unchanged
        takeoff_i = _detect_takeoff(
            y_smooth, vel_y, pts_arr, prep_end_i, context, params)

    apex_i = (_detect_apex_bounded(y_smooth, vel_y, pts_arr, takeoff_i, params)
              if takeoff_i is not None else None)
    wc_i   = (_detect_water_contact_bounded(
                  y_smooth, vel_y, conf_arr, pts_arr, apex_i, params)
              if apex_i is not None else None)

    def _t(i): return pts_arr[i] if i is not None else None
    n_valid  = sum(1 for y in y_arr if y is not None)
    coverage = n_valid / len(y_arr) if y_arr else 0.0
    return {
        "context":         context,
        "prep_end_t":      _t(prep_end_i),
        "takeoff_t":       _t(takeoff_i),
        "apex_t":          _t(apex_i),
        "water_contact_t": _t(wc_i),
        "coverage":        round(coverage, 4),
    }
