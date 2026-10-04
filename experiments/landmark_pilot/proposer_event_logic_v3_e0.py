#!/usr/bin/env python3
"""Event Logic V3-E0 — V3-D0 + robust board reference (B1r).

DEVELOPMENT-only derivation. This variant is derived exclusively from the
DEVELOPMENT corpus (DEV_HURDLE_TRAJ_CACHE_V2.json + STANDING_TRAJ_CACHE_V2.json)
and the two audits BOARD_REFERENCE_AUDIT_V1.json / TWOD_APPROACH_AUDIT_V1.json.
  - NO Paris data and NO Paris-derived values are used anywhere in this module.
  - NO HQ-derived values are used anywhere in this module (HQ thread remains
    READ-ONLY diagnostics; see HQ_HURDLE_DIAGNOSTIC_V1.json).
  - NO approach-step inference (TWOD_APPROACH_AUDIT_V1.json verdict: no dive
    qualifies as APPROACH_END_OBSERVABLE_FROM_2D_TRAJECTORY; the 2D
    approach-progress coordinate s(t) is not reliably extractable at 360p.
    Consequence: V3-E0 does NOT add any 2D approach-progress gate.)

CHANGES over V3-D0 (single change):
  E0. Board reference for the HURDLE board-rise invariant.
      - V3-D0 uses y_prep = smoothed cy at prep_end (historical reference "B0").
        BOARD_REFERENCE_AUDIT_V1.json shows B0 inherits target-switch
        contamination on dive 1040 (B0=0.531 lands between the two apparent
        raw levels 0.221/0.599, matching neither; the true dominant diver level
        is 0.2208).
      - V3-E0 replaces it with "B1r" (the audit's chosen reference): the
        1.5xMAD-rejected median of RAW cy over the initial stable-support
        cluster (frames [0, prep_end], |vel_raw| <= 0.02, conf >= 0.10).
        GT-blind, computed from the RAW signal, bounded to the pre-hurdle
        static-plateau region via _find_preparation_end semantics.
      - If support is insufficient (cluster empty or n < board_ref_min_support_n),
        fall back to the historical V3-D0 y_prep and flag board_ref_mode =
        "HISTORICAL_FALLBACK" (2541-type non-diver low-conf plateaus degrade
        gracefully to exact V3-D0 behaviour instead of crashing).
      - Constant authority: cluster_constants of BOARD_REFERENCE_AUDIT_V1.json
        (vel_max 0.02, conf_min 0.10, mad_k 1.5) are audit-level constants,
        not tuned parameters. board_ref_min_support_n = 5 is justified by the
        audit: the smallest credible cluster on a scored dive is 1040 with
        n_samples = 5, and its B1r still matched the dominant raw level within
        0.0003 — so 5 is the minimum support at which the audit demonstrated
        a correct reference.

UNCHANGED from V3-D0:
  - HURDLE scan/gate semantics (_detect_hurdle_takeoff_v3d0 logic): only the
    reference value used by the board-rise invariant changes.
  - A1: bounded apex fallback (_detect_apex_bounded)
  - A2: bounded water-contact search (_detect_water_contact_bounded)
  - All PARAMS_V3D0 parameter values (min_hurdle_rise_cy stays 0.01,
    fallback_sustained_s stays 0.15)
  - STANDING path (uses V2.1 _detect_takeoff unmodified — byte-identical)
  - PTS-aware signal primitives (cy_norm, Gaussian smooth, velocity)
  - No Paris-derived thresholds
  - No GT event-time windows fed to inference

Addresses: B0 contamination of the board-rise invariant (1040-type two-level
raw signal). Does NOT address: 2541-type non-diver initial plateaus (no
credible support exists; degrade to V3-D0), approach-progress gating (Phase H
precondition not met), Paris external failure (no DEVELOPMENT evidence).

Paris firewall: READ-ONLY post-freeze evaluation; NOT used to set parameters.
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
from proposer_event_logic_v3_d0 import PARAMS_V3D0

import numpy as np


# ─── V3-E0 parameters (inherits V3-D0, adds E0 keys) ─────────────────────────

PARAMS_V3E0 = dict(PARAMS_V3D0)
PARAMS_V3E0.update({
    "variant": "V3E0",
    # E0: minimum stable-support cluster size for the B1r board reference.
    # Authority: BOARD_REFERENCE_AUDIT_V1.json — 1040 is the smallest credible
    # cluster on a scored dive (n_samples=5) and B1r matched the dominant raw
    # level within 0.0003 there. Below this support the reference is not
    # demonstrated and V3-E0 falls back to the historical V3-D0 y_prep.
    # NO other parameter changed vs V3-D0 (min_hurdle_rise_cy=0.01,
    # fallback_sustained_s=0.15 inherited unchanged).
    "board_ref_min_support_n": 5,
})

# Audit-level cluster constants (verbatim from BOARD_REFERENCE_AUDIT_V1.json
# "cluster_constants"). These are fixed recipe constants of the B1r reference,
# NOT Event Logic parameters and NOT tuned on any corpus.
BOARD_REF_VEL_MAX  = 0.02
BOARD_REF_CONF_MIN = 0.10
BOARD_REF_MAD_K    = 1.5


# ─── E0: robust board reference (B1r recipe, verbatim audit semantics) ───────

def _robust_median_mad(values):
    """1.5*MAD-rejected median (same helper as BOARD_REFERENCE_AUDIT_V1).

    Returns (median_rejected, mad_initial, n_total, n_rejected).
    """
    v = np.asarray([x for x in values if x is not None], dtype=float)
    if v.size == 0:
        return None, None, 0, 0
    med0 = float(np.median(v))
    mad0 = float(np.median(np.abs(v - med0)))
    if mad0 > 0:
        keep = np.abs(v - med0) <= BOARD_REF_MAD_K * mad0
    else:
        keep = np.ones(v.size, dtype=bool)
    v_kept = v[keep]
    med1 = float(np.median(v_kept)) if v_kept.size else med0
    return med1, mad0, int(v.size), int(v.size - v_kept.sum())


def _robust_board_reference(y_arr, pts_arr, conf_arr, prep_end_i, params):
    """B1r board reference from the RAW (unsmoothed) signal.

    Exact BOARD_REFERENCE_AUDIT_V1.json recipe:
      - stable-support cluster = frames [0, prep_end] (initial static-plateau
        region; prep_end_i comes from _find_preparation_end on the V3 smoothed
        signal — GT-blind) with valid raw cy, conf >= 0.10 and
        |vel_raw| <= 0.02 (raw-signal PTS-aware velocity);
      - B1r = 1.5*MAD-rejected median of the cluster's raw cy.

    Returns (b1r_value_or_None, n_cluster_samples, n_rejected).
    """
    n = len(y_arr)
    p_end = prep_end_i if prep_end_i is not None else n - 1
    vel_raw = pts_aware_velocity(y_arr, pts_arr, params["vel_max_gap_s"])
    cluster_idx = [i for i in range(0, p_end + 1)
                   if y_arr[i] is not None and conf_arr[i] >= BOARD_REF_CONF_MIN
                   and vel_raw[i] is not None
                   and abs(vel_raw[i]) <= BOARD_REF_VEL_MAX]
    med1, _mad0, n_samples, n_rej = _robust_median_mad(
        [y_arr[i] for i in cluster_idx])
    return med1, n_samples, n_rej


# ─── E0: HURDLE takeoff — V3-D0 semantics, B1r reference ─────────────────────

def _detect_hurdle_takeoff_v3e0(y_smooth, vel_y, pts_arr, prep_end_i,
                                board_ref, params, return_trace=False):
    """HURDLE takeoff with board-rise validation (D0 semantics, E0 reference).

    Identical to _detect_hurdle_takeoff_v3d0 except that the board level used
    by the board-rise invariant (cy_apex < ref - min_hurdle_rise_cy) is the
    resolved V3-E0 reference `board_ref` (B1r, or the historical y_prep when
    the caller resolved HISTORICAL_FALLBACK) instead of y_prep.

    Arguments:
        y_smooth:   per-frame smoothed cy_norm (None = gap)
        vel_y:      per-frame smoothed velocity (None = gap)
        pts_arr:    per-frame PTS timestamps (seconds)
        prep_end_i: index of prep_end event (only used for guard_end timing)
        board_ref:  resolved board reference value (cy_norm) or None
        params:     PARAMS_V3E0 dict
        return_trace: if True, also return a debug trace of every scanned
                    neg→non-neg crossing (t, cy_apex, board_ref, rise_cy,
                    passed gate or not, and the accepted crossing).

    Returns:
        int | None — index into pts_arr of the detected final takeoff, or None.
        (int | None, list) when return_trace is True.
    """
    n = len(y_smooth)
    prep_t    = pts_arr[prep_end_i] if prep_end_i is not None else 0.0
    guard_s   = params["hurdle_post_plateau_guard_s"]
    guard_end = prep_t + guard_s

    vel_thresh   = params["takeoff_vel_threshold"]
    sustained_s  = params["takeoff_sustained_s"]
    fallback_s   = params.get("fallback_sustained_s", 0.15)
    min_rise     = params.get("min_hurdle_rise_cy", 0.01)

    trace = []

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
            # Board-rise invariant: cy_apex < board_ref − min_rise
            if (board_ref is not None and cy_apex is not None
                    and cy_apex < board_ref - min_rise):
                valid_hurdle_recontact_i = i
                trace.append({
                    "t": pts_arr[apex_i], "cy_apex": cy_apex,
                    "board_ref": board_ref,
                    "rise_cy": round(board_ref - cy_apex, 5),
                    "gate_passed": True, "accepted": True,
                })
                break
            trace.append({
                "t": pts_arr[apex_i], "cy_apex": cy_apex,
                "board_ref": board_ref,
                "rise_cy": (round(board_ref - cy_apex, 5)
                            if board_ref is not None and cy_apex is not None
                            else None),
                "gate_passed": False, "accepted": False,
            })
        prev_v = v
        i += 1

    # ── Step 3/4: find sustained negative velocity ───────────────────────────
    if valid_hurdle_recontact_i is not None:
        search_t   = pts_arr[valid_hurdle_recontact_i]
        sus_window = sustained_s
    else:
        search_t   = guard_end          # fallback: depart from guard_end
        sus_window = fallback_s

    takeoff_i = None
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
            takeoff_i = i
            break

    if return_trace:
        return takeoff_i, trace
    return takeoff_i


# ─── Top-level proposer ───────────────────────────────────────────────────────

def propose_events_v3e0(y_arr, pts_arr, conf_arr, dive_code, params=None):
    """Propose dive events using Event Logic V3-E0.

    Arguments:
        y_arr:      list of cy_norm per frame (None = gap)
        pts_arr:    list of PTS timestamps (seconds) per frame
        conf_arr:   list of detection confidence per frame
        dive_code:  dive code string (used to classify context)
        params:     parameter dict (defaults to PARAMS_V3E0)

    Returns:
        dict with all V3-D0 keys (context, prep_end_t, takeoff_t, apex_t,
        water_contact_t, coverage) plus additive E0 keys:
          board_ref          — resolved reference value used by the gate
          board_ref_mode     — "B1R" | "HISTORICAL_FALLBACK" | "NOT_USED"
          board_ref_n_support— stable-support cluster size (None for STANDING)
          hurdle_trace       — per-crossing debug trace (HURDLE only)
    """
    if params is None:
        params = PARAMS_V3E0

    context = classify_context(dive_code)
    sigma   = params["smooth_window_s"] / 3
    y_smooth = pts_aware_smooth(y_arr, pts_arr, sigma_s=sigma)
    y_smooth = interpolate_gaps_time(y_smooth, pts_arr, params["interp_max_gap_s"])
    vel_y    = pts_aware_velocity(y_smooth, pts_arr, params["vel_max_gap_s"])

    prep_end_i = _find_preparation_end(y_smooth, pts_arr, params)

    board_ref = None
    board_ref_mode = "NOT_USED"
    board_ref_n = None
    trace = None

    if context == "HURDLE":
        # ── E0: resolve board reference ──────────────────────────────────────
        b1r, n_support, _n_rej = _robust_board_reference(
            y_arr, pts_arr, conf_arr, prep_end_i, params)
        y_prep = (y_smooth[prep_end_i]
                  if prep_end_i is not None and y_smooth[prep_end_i] is not None
                  else None)
        if b1r is None or n_support < params["board_ref_min_support_n"]:
            board_ref      = y_prep          # historical V3-D0 reference
            board_ref_mode = "HISTORICAL_FALLBACK"
        else:
            board_ref      = b1r
            board_ref_mode = "B1R"
        board_ref_n = n_support

        takeoff_i, trace = _detect_hurdle_takeoff_v3e0(
            y_smooth, vel_y, pts_arr, prep_end_i, board_ref, params,
            return_trace=True)
    else:
        # STANDING path: V2.1 semantics, unchanged (byte-identical to V3-D0)
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
        "context":           context,
        "prep_end_t":        _t(prep_end_i),
        "takeoff_t":         _t(takeoff_i),
        "apex_t":            _t(apex_i),
        "water_contact_t":   _t(wc_i),
        "coverage":          round(coverage, 4),
        "board_ref":         board_ref,
        "board_ref_mode":    board_ref_mode,
        "board_ref_n_support": board_ref_n,
        "hurdle_trace":      trace,
    }
