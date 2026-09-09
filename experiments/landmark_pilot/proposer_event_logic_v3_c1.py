#!/usr/bin/env python3
"""Event Logic V3-C1 — V3-C0 + explicit HURDLE final-departure semantics.

Extends V3-C0 with a redesigned HURDLE takeoff detection that explicitly distinguishes
the hurdle jump from the final board departure using a board-recontact check.

CHANGES over V3-C0 (which already has A1+A2):
  C1. HURDLE takeoff detection — new state machine:
      - Scan ALL sustained-negative-velocity start points in the full trajectory.
      - For each candidate: look forward `hurdle_recontact_window_s` seconds.
        If positive velocity found in that window → BOARD_RECONTACT → this was a
        hurdle jump, not the final takeoff. Skip.
        If no positive velocity found → FINAL_TAKEOFF. Return this candidate.
      - Does NOT depend on prep_end_idx for HURDLE context.
      - After tracking all candidates with recontact, return the first one
        AFTER the last recontact — the final departure.
      - Fallback: if all candidates have apparent recontact, return last candidate.

  Critical invariant (Phase H):
    "Hurdle departure must never be scored as final takeoff if a later board
     recontact is observed."

UNCHANGED from V3-C0 / V2.1:
  - STANDING takeoff: identical to V2.1 _detect_takeoff STANDING branch.
  - _find_preparation_end: unchanged (V2.1).
  - _detect_apex_bounded (A1).
  - _detect_water_contact_bounded (A2).
  - classify_context, PTS-aware primitives.
  - All PARAMS_E1 parameter values.
  - No GT event-time windows as inputs.
  - No Paris-derived thresholds.

Addresses: FM1 (dive 311), FM2 (HURDLE, dives 1040/2169/Paris).
Does NOT address: FM3 (360p noise, dive 676).

Long preparation (H2): min_search_start_s=0.5s is the only floor; no upper limit.
STANDING protection (H1): HURDLE branch only runs when context=='HURDLE'.
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from proposer_event_logic_v2_1 import (
    classify_context,
    pts_aware_velocity,
    pts_aware_smooth,
    interpolate_gaps_time,
    _find_preparation_end,
    _detect_takeoff,      # re-used for STANDING
    PARAMS_E1,
)
from proposer_event_logic_v3_c0 import (
    _detect_apex_bounded,
    _detect_water_contact_bounded,
)

# ─── V3-C1 parameters ─────────────────────────────────────────────────────────

PARAMS_V3C1 = dict(PARAMS_E1)
PARAMS_V3C1.update({
    "variant": "V3C1",
    # A1 (bounded apex)
    "apex_max_window_s": 1.5,
    # A2 (bounded wc)
    "wc_max_window_s": 2.5,
    # C1 (HURDLE board-recontact check)
    # Window = 0.25s < min GT takeoff-to-apex (0.284s from dive 133).
    # Final flight: positive vel appears at apex (≥0.284s away) → NOT within 0.25s → kept.
    # Hurdle jump: apex typically ≤0.20s from departure → positive vel within 0.25s → rejected.
    # Authority: DEVELOPMENT GT data only (Paris not used to set this bound).
    "hurdle_recontact_window_s":    0.25,   # SHORT window: < min takeoff-to-apex (0.284s)
    "hurdle_recontact_vel_thresh":  0.03,   # positive velocity threshold for board descent
    "hurdle_min_search_start_s":    0.30,   # skip first 0.3s (pre-action noise)
    "hurdle_min_sustained_s":       0.12,   # sustained neg-vel required to qualify
})


# ─── C1: HURDLE final-departure detection ─────────────────────────────────────

def _detect_hurdle_final_takeoff(vel_y, pts_arr, params):
    """Find the FINAL takeoff frame for HURDLE context.

    Scans all sustained-negative-velocity start points (candidate takeoffs).
    Rejects any candidate followed by positive velocity within recontact_window_s
    (= board recontact after a hurdle jump).
    Returns the first candidate NOT followed by recontact that comes after the
    last recontact-confirmed candidate (= the final departure from the board).

    Phase H invariant: if a later board recontact is observed, the candidate is
    classified as HURDLE_DEPARTURE and never returned as FINAL_TAKEOFF.

    Does not depend on prep_end_idx — scans the full trajectory.
    """
    vel_thresh          = params["takeoff_vel_threshold"]
    sustained_s         = params.get("hurdle_min_sustained_s", params["takeoff_sustained_s"])
    recontact_window_s  = params["hurdle_recontact_window_s"]
    recontact_thresh    = params["hurdle_recontact_vel_thresh"]
    min_start_s         = params["hurdle_min_search_start_s"]

    n = len(vel_y)

    # ── Step 1: find all sustained-neg-vel start points ────────────────────────
    candidates = []       # list of frame indices where sustained neg vel starts
    in_neg = False

    for i in range(n):
        if pts_arr[i] < min_start_s:
            in_neg = False
            continue

        v = vel_y[i]
        if v is None:
            in_neg = False
            continue

        if v < -vel_thresh:
            if not in_neg:
                # New upward-motion burst: check sustained
                t_end   = pts_arr[i] + sustained_s
                n_valid = 0
                n_above = 0
                for j in range(i + 1, n):
                    if pts_arr[j] > t_end:
                        break
                    if vel_y[j] is not None:
                        n_valid += 1
                        if vel_y[j] < -vel_thresh:
                            n_above += 1
                if n_valid > 0 and n_above == n_valid:
                    candidates.append(i)
                    in_neg = True
        else:
            in_neg = False

    if not candidates:
        return None

    # ── Step 2: for each candidate, check for board recontact ──────────────────
    has_recontact = []
    for ci in candidates:
        t_window_end = pts_arr[ci] + recontact_window_s
        found_recontact = False
        for j in range(ci + 1, n):
            if pts_arr[j] > t_window_end:
                break
            v = vel_y[j]
            if v is not None and v > recontact_thresh:
                found_recontact = True
                break
        has_recontact.append(found_recontact)

    # ── Step 3: return first candidate NOT followed by recontact, AFTER the    ──
    #            last candidate that DID have recontact (= after all hurdle jumps)
    last_recontact_idx = None
    for k, rc in enumerate(has_recontact):
        if rc:
            last_recontact_idx = k

    for k, ci in enumerate(candidates):
        if last_recontact_idx is not None and k <= last_recontact_idx:
            continue   # still before / at last hurdle jump
        if not has_recontact[k]:
            return ci  # FINAL TAKEOFF

    # ── Fallback: all candidates appear to have recontact → return last ─────────
    # (e.g. post-wc noise caused spurious positive vel in all windows)
    return candidates[-1]


# ─── Top-level proposer ───────────────────────────────────────────────────────

def propose_events_v3c1(y_arr, pts_arr, conf_arr, dive_code, params=None):
    """V3-C1: V3-C0 + explicit HURDLE final-departure detection.

    y_arr in cy_norm convention (0=top, 1=bottom of frame).
    Rising diver → negative velocity.
    """
    if params is None:
        params = PARAMS_V3C1

    context = classify_context(dive_code)

    y_smooth = pts_aware_smooth(y_arr, pts_arr, sigma_s=params["smooth_window_s"] / 3)
    y_smooth = interpolate_gaps_time(y_smooth, pts_arr, max_gap_s=params["interp_max_gap_s"])
    vel_y    = pts_aware_velocity(y_smooth, pts_arr, max_gap_s=params["vel_max_gap_s"])

    # prep_end still detected (needed for complete result dict; not used by HURDLE takeoff)
    prep_end_idx = _find_preparation_end(y_smooth, pts_arr, params)

    if context == "HURDLE":
        takeoff_idx = _detect_hurdle_final_takeoff(vel_y, pts_arr, params)
    else:
        # STANDING: unchanged V2.1 logic (H1 non-regression guarantee)
        takeoff_idx = _detect_takeoff(y_smooth, vel_y, pts_arr, prep_end_idx, context, params)

    apex_idx = _detect_apex_bounded(y_smooth, vel_y, pts_arr, takeoff_idx, params) \
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
