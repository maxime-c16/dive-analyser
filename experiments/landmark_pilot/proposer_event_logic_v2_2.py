#!/usr/bin/env python3
"""Event Logic V2.2 — scale-aware / camera-robust takeoff detection.

Supersedes V2.1's fixed absolute velocity threshold (takeoff_vel_threshold =
0.04 cy_norm/s), which SUPERVISOR_TASK_PACKET (REAL_TRAJECTORY_EVENT_LOGIC_V2_2)
flags as CAMERA_SCALE_SENSITIVE: the same physical takeoff produces a smaller
cy_norm/s swing when the diver occupies fewer normalized pixels (e.g. wider
framing, further apparatus, higher resolution changing localization SNR but
not motion-per-second in normalized image coordinates).

Two scale-aware candidates are implemented (Phase F cap = 2 serious variants):

  S1_BODY_SCALE — velocity expressed in body-heights/second:
      v_body[i] = vel_y[i] / ref_bbox_h_norm
      ref_bbox_h_norm = robust (median) bbox height over the preparation
      window (a stable, non-flight posture), NOT instantaneous bbox height
      (instantaneous height is unstable during flight/rotation/tuck).
      Threshold becomes a fixed multiplier in body-heights/s, portable across
      framings because it is normalized by the diver's own apparent scale.

  S2_PREP_BASELINE — preparation-noise-relative change-point:
      During the preparation window compute robust statistics of the raw
      cy_norm/s velocity signal: median (should be ~0) and MAD (noise floor).
      Takeoff threshold = median_prep + k * max(MAD_prep, mad_floor), i.e. a
      per-dive-adaptive multiple of that dive's OWN preparation noise, rather
      than a universal constant. mad_floor guards near-zero-MAD degenerate
      cases (e.g. perfectly static preparation with a razor-thin MAD that
      would make the threshold pathologically tight).

Both candidates keep V2.1's state machine structure (PREPARATION -> HURDLE ->
BOARD_RECONTACT -> FINAL_FLIGHT, hurdle apex via first neg->non-neg velocity
crossing, apex via velocity crossing, water_contact via cy threshold) — only
the takeoff decision rule (and, for S1, the velocity signal itself) changes,
per packet Phase H (hurdle-state preservation is required, not renegotiable).
"""

import math
import statistics
from typing import List, Optional

from proposer_event_logic_v2_1 import (
    classify_context, pts_aware_velocity, pts_aware_smooth,
    interpolate_gaps_time, PARAMS_E1,
)

MIN_BBOX_H_NORM = 0.01  # zero/near-zero bbox-scale safeguard (Phase R)
MAD_FLOOR = 0.003        # cy_norm/s; guards degenerate near-zero-noise MAD


PARAMS_S1 = dict(PARAMS_E1)
PARAMS_S1.update({
    "variant": "V2.2_S1_BODY_SCALE",
    "takeoff_vel_threshold_bodylengths": 0.55,  # body-heights/s, calibrated on DEVELOPMENT
})

PARAMS_S2 = dict(PARAMS_E1)
PARAMS_S2.update({
    "variant": "V2.2_S2_PREP_BASELINE",
    "prep_mad_multiplier": 6.0,
})


def robust_median(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return statistics.median(vals)


def robust_mad(values, med=None):
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    if med is None:
        med = statistics.median(vals)
    devs = [abs(v - med) for v in vals]
    return statistics.median(devs)


def reference_bbox_height(bh_arr, pts_arr, prep_end_idx):
    """Robust (median) bbox height over the preparation window.

    Falls back to the median over the whole available signal if no
    preparation window was found (prep_end_idx is None), and to
    MIN_BBOX_H_NORM if even that degenerates to ~0 (zero/near-zero bbox-scale
    safeguard, Phase R).
    """
    if prep_end_idx is not None:
        window = bh_arr[: prep_end_idx + 1]
    else:
        window = bh_arr
    med = robust_median(window)
    if med is None or med < MIN_BBOX_H_NORM:
        med = robust_median(bh_arr)
    if med is None or med < MIN_BBOX_H_NORM:
        return MIN_BBOX_H_NORM
    return med


def _find_preparation_end_generic(vel_y, pts_arr, params, motion_vel_thresh):
    """Same structure as V2.1's _find_preparation_end but takes an explicit
    already-computed velocity array and threshold (so it can run on either
    raw cy_norm/s velocity or body-scale velocity)."""
    min_dur_s = params["static_min_duration_s"]
    n = len(vel_y)
    prep_end = None
    for i in range(1, n):
        v = vel_y[i]
        if v is None:
            continue
        if abs(v) <= motion_vel_thresh:
            if pts_arr[i] >= min_dur_s:
                prep_end = i
        else:
            if prep_end is not None:
                return prep_end
    return None


def _detect_takeoff_generic(vel_sig, pts_arr, prep_end_idx, context, params, vel_thresh_fn):
    """Structurally identical to V2.1's _detect_takeoff (hurdle-state
    preservation, Phase H) but the "is this sustained-rising" test is
    delegated to vel_thresh_fn(i) -> float (a per-frame or per-dive
    scale-aware threshold), instead of a single global constant.
    """
    n = len(vel_sig)
    prep_t = pts_arr[prep_end_idx] if prep_end_idx is not None else 0.0
    min_after_prep_s = params["takeoff_min_after_prep_s"]
    sustained_s = params["takeoff_sustained_s"]

    def rising(i):
        thr = vel_thresh_fn(i)
        v = vel_sig[i]
        return v is not None and v < -thr

    if context == "HURDLE":
        guard_s = params["hurdle_post_plateau_guard_s"]
        guard_end_t = prep_t + guard_s

        hurdle_apex_idx = None
        board_recontact_idx = None
        prev_v = None
        for i in range(n):
            if pts_arr[i] < guard_end_t:
                prev_v = vel_sig[i]
                continue
            v = vel_sig[i]
            if v is None:
                prev_v = None
                continue
            if prev_v is not None and prev_v < 0 and v >= 0:
                hurdle_apex_idx = i - 1
                board_recontact_idx = i
                break
            prev_v = v

        if board_recontact_idx is not None:
            search_start_t = pts_arr[board_recontact_idx]
        else:
            search_start_t = guard_end_t + min_after_prep_s
    else:
        search_start_t = prep_t + min_after_prep_s

    for i in range(n):
        if pts_arr[i] < search_start_t:
            continue
        if not rising(i):
            continue
        t_end = pts_arr[i] + sustained_s
        n_above = 0
        n_total = 0
        for j in range(i + 1, n):
            if pts_arr[j] > t_end:
                break
            n_total += 1
            if rising(j):
                n_above += 1
        if n_total > 0 and n_above == n_total:
            return i

    return None


def _detect_apex_generic(y_smooth, vel_y, pts_arr, takeoff_idx, params):
    """Unchanged from V2.1 (apex detection is not scale-sensitive: it is a
    zero-crossing test, not a magnitude threshold)."""
    n = len(y_smooth)
    search_start_t = pts_arr[takeoff_idx] + params["apex_search_start_s"]
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
            return i - 1
        prev_v = v
    best_idx, best_y = None, None
    for i in range(takeoff_idx + 1, n):
        if pts_arr[i] < search_start_t or y_smooth[i] is None:
            continue
        if best_y is None or y_smooth[i] < best_y:
            best_y, best_idx = y_smooth[i], i
    return best_idx


def _detect_water_contact_generic(y_smooth, vel_y, conf_arr, pts_arr, apex_idx, params):
    """Unchanged from V2.1."""
    n = len(y_smooth)
    min_after_apex_s = params["water_contact_min_after_apex_s"]
    water_thresh = params["water_line_cy_norm"]
    search_start_t = pts_arr[apex_idx] + min_after_apex_s
    for i in range(apex_idx + 1, n):
        if pts_arr[i] < search_start_t or y_smooth[i] is None:
            continue
        if y_smooth[i] > water_thresh:
            return i
    last_conf = None
    for i in range(apex_idx + 1, n):
        if pts_arr[i] < search_start_t:
            continue
        if conf_arr[i] > 0.3:
            last_conf = i
    return last_conf


def propose_events_s1_body_scale(y_arr, bh_arr, pts_arr, conf_arr, dive_code, params=PARAMS_S1):
    """S1: velocity expressed in body-heights/second."""
    context = classify_context(dive_code)
    y_smooth = pts_aware_smooth(y_arr, pts_arr, sigma_s=params["smooth_window_s"] / 3)
    y_smooth = interpolate_gaps_time(y_smooth, pts_arr, max_gap_s=params["interp_max_gap_s"])
    vel_y = pts_aware_velocity(y_smooth, pts_arr, max_gap_s=params["vel_max_gap_s"])

    # bootstrap: preparation end found on RAW cy_norm/s (scale-agnostic motion
    # detection is fine for "is it static", the scale issue is specifically
    # the takeoff magnitude threshold) — identical to V2.1 for this step.
    motion_vel_thresh_boot = 0.02
    prep_end_idx = _find_preparation_end_generic(vel_y, pts_arr, params, motion_vel_thresh_boot)

    ref_h = reference_bbox_height(bh_arr, pts_arr, prep_end_idx)
    v_body = [ (v / ref_h) if v is not None else None for v in vel_y ]

    thr_body = params["takeoff_vel_threshold_bodylengths"]
    takeoff_idx = _detect_takeoff_generic(
        v_body, pts_arr, prep_end_idx, context, params, vel_thresh_fn=lambda i: thr_body
    )
    apex_idx = _detect_apex_generic(y_smooth, vel_y, pts_arr, takeoff_idx, params) \
        if takeoff_idx is not None else None
    water_contact_idx = _detect_water_contact_generic(
        y_smooth, vel_y, conf_arr, pts_arr, apex_idx, params
    ) if apex_idx is not None else None

    def _t(idx):
        return pts_arr[idx] if idx is not None else None

    n_valid = sum(1 for y in y_arr if y is not None)
    coverage = n_valid / len(y_arr) if y_arr else 0.0
    return {
        "variant": params["variant"], "context": context,
        "ref_bbox_h_norm": ref_h,
        "prep_end_idx": prep_end_idx, "prep_end_t": _t(prep_end_idx),
        "takeoff_idx": takeoff_idx, "takeoff_t": _t(takeoff_idx),
        "apex_idx": apex_idx, "apex_t": _t(apex_idx),
        "water_contact_idx": water_contact_idx, "water_contact_t": _t(water_contact_idx),
        "confident": coverage >= params["min_coverage_for_confident"] and takeoff_idx is not None,
        "coverage": coverage,
    }


def propose_events_s2_prep_baseline(y_arr, bh_arr, pts_arr, conf_arr, dive_code, params=PARAMS_S2):
    """S2: threshold = this dive's own preparation-noise baseline + k*MAD."""
    context = classify_context(dive_code)
    y_smooth = pts_aware_smooth(y_arr, pts_arr, sigma_s=params["smooth_window_s"] / 3)
    y_smooth = interpolate_gaps_time(y_smooth, pts_arr, max_gap_s=params["interp_max_gap_s"])
    vel_y = pts_aware_velocity(y_smooth, pts_arr, max_gap_s=params["vel_max_gap_s"])

    motion_vel_thresh_boot = 0.02
    prep_end_idx = _find_preparation_end_generic(vel_y, pts_arr, params, motion_vel_thresh_boot)

    prep_window = vel_y[: prep_end_idx + 1] if prep_end_idx is not None else vel_y[: max(1, len(vel_y) // 4)]
    med = robust_median(prep_window) or 0.0
    mad = robust_mad(prep_window, med)
    if mad is None:
        mad = MAD_FLOOR
    mad = max(mad, MAD_FLOOR)
    thr = params["prep_mad_multiplier"] * mad

    takeoff_idx = _detect_takeoff_generic(
        vel_y, pts_arr, prep_end_idx, context, params, vel_thresh_fn=lambda i: thr
    )
    apex_idx = _detect_apex_generic(y_smooth, vel_y, pts_arr, takeoff_idx, params) \
        if takeoff_idx is not None else None
    water_contact_idx = _detect_water_contact_generic(
        y_smooth, vel_y, conf_arr, pts_arr, apex_idx, params
    ) if apex_idx is not None else None

    def _t(idx):
        return pts_arr[idx] if idx is not None else None

    n_valid = sum(1 for y in y_arr if y is not None)
    coverage = n_valid / len(y_arr) if y_arr else 0.0
    return {
        "variant": params["variant"], "context": context,
        "prep_median_vel": med, "prep_mad_vel": mad, "takeoff_threshold_used": thr,
        "prep_end_idx": prep_end_idx, "prep_end_t": _t(prep_end_idx),
        "takeoff_idx": takeoff_idx, "takeoff_t": _t(takeoff_idx),
        "apex_idx": apex_idx, "apex_t": _t(apex_idx),
        "water_contact_idx": water_contact_idx, "water_contact_t": _t(water_contact_idx),
        "confident": coverage >= params["min_coverage_for_confident"] and takeoff_idx is not None,
        "coverage": coverage,
    }
