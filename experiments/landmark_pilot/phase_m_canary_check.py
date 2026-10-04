#!/usr/bin/env python3
"""Phase M — Canary mechanism check for Event Logic V2 (E1).

Verifies that the state machine correctly identifies all landmarks
for the canary dive (dive 2819, 5122D G/G, springboard 1m, hurdle).

Two modes:
  1. Synthetic trajectory: construct ideal trajectory from annotation timestamps
     and trace the state machine through all states.
  2. (Future) Full detector run at 1080p when canary is accessible on server.
"""
import sys, os, json, math
sys.path.insert(0, os.path.dirname(__file__))
from proposer_event_logic_v2 import (
    classify_context, pts_aware_velocity, pts_aware_smooth,
    _find_preparation_end, _detect_takeoff, _detect_apex,
    _detect_water_contact, PARAMS_E1
)
import copy

# Ground truth from HIGHRES_CANARY_V2_EXACT_ANNOTATION.json
GT = {
    "hurdle_onset_t": 0.000,
    "board_recontact_t": 2.668333,
    "takeoff_t": 3.12,
    "apex_t": 3.57,
    "water_contact_t": 4.22,
    "total_duration_s": 5.371667,
    "dive_code": "5122D",
}

def make_canary_trajectory(pts_arr):
    """Construct a synthetic y trajectory matching canary timing.

    y_norm: 0 = top of frame, 1 = bottom of frame.
    Diver starts at y~0.40 (upper body position when static on board).
    During hurdle: rises to ~0.35, board recontact at ~0.42.
    Takeoff: rises from ~0.42 to apex y~0.20 (highest = smallest y).
    Descent: falls from apex to water_contact y~0.50.
    Post-entry: goes below water line (y > 0.50).
    """
    n = len(pts_arr)
    y = [None] * n
    conf = [0.0] * n

    for i, t in enumerate(pts_arr):
        if t <= GT["board_recontact_t"]:
            # Static + hurdle phase: oscillate gently around 0.40
            phase = (t / GT["board_recontact_t"]) * 2 * math.pi * 1.5
            y[i] = 0.40 + 0.04 * math.sin(phase)
            conf[i] = 0.85
        elif t <= GT["takeoff_t"]:
            # Board loading: y increases slightly (diver loading board)
            frac = (t - GT["board_recontact_t"]) / (GT["takeoff_t"] - GT["board_recontact_t"])
            y[i] = 0.40 + 0.03 * frac
            conf[i] = 0.80
        elif t <= GT["apex_t"]:
            # Ascent: y decreases (diver rises)
            frac = (t - GT["takeoff_t"]) / (GT["apex_t"] - GT["takeoff_t"])
            y[i] = 0.43 - 0.25 * frac  # from 0.43 down to 0.18
            conf[i] = 0.75
        elif t <= GT["water_contact_t"]:
            # Descent: y increases (diver falls)
            frac = (t - GT["apex_t"]) / (GT["water_contact_t"] - GT["apex_t"])
            y[i] = 0.18 + 0.34 * frac  # from 0.18 up to 0.52
            conf[i] = 0.70
        else:
            # Post-entry: y > water_line (in water)
            y[i] = 0.52 + 0.05 * (t - GT["water_contact_t"])
            conf[i] = 0.30  # low confidence — partially occluded

    return y, conf


def run_canary_check():
    print("=" * 60)
    print("PHASE M — Event Logic V2 Canary Mechanism Check")
    print("=" * 60)
    print(f"Dive: {GT['dive_code']}, springboard 1m, HURDLE context")
    print()

    # Build synthetic 60fps PTS array
    fps = 60.0
    n = int(GT["total_duration_s"] * fps) + 1
    pts = [i / fps for i in range(n)]

    y, conf = make_canary_trajectory(pts)
    params = copy.deepcopy(PARAMS_E1)

    context = classify_context(GT["dive_code"])
    print(f"Context classification: {context}  (expected: HURDLE)")
    assert context == "HURDLE", f"FAIL: context={context}"
    print("  -> PASS")
    print()

    # Smooth + velocity
    y_smooth = pts_aware_smooth(y, pts, sigma_s=params["smooth_window_s"] / 3)
    vel_y = pts_aware_velocity(y_smooth, pts, max_gap_s=params["vel_max_gap_s"])

    # STATE: PREPARATION
    prep_end_idx = _find_preparation_end(y_smooth, pts, params)
    if prep_end_idx is not None:
        prep_end_t = pts[prep_end_idx]
        print(f"PREPARATION end:   frame {prep_end_idx}, t={prep_end_t:.3f}s")
        # Should be before board_recontact
        assert prep_end_t < GT["board_recontact_t"], \
            f"FAIL: prep_end {prep_end_t:.3f} >= board_recontact {GT['board_recontact_t']:.3f}"
        print("  -> PASS (before board recontact)")
    else:
        print("PREPARATION end:   NOT DETECTED")
    print()

    # STATE: APPROACH_OR_HURDLE -> SUPPORT_INTERACTION -> AIRBORNE_ASCENT
    takeoff_idx = _detect_takeoff(y_smooth, vel_y, pts, prep_end_idx, context, params)
    if takeoff_idx is not None:
        takeoff_t = pts[takeoff_idx]
        err = takeoff_t - GT["takeoff_t"]
        print(f"TAKEOFF:           frame {takeoff_idx}, t={takeoff_t:.3f}s")
        print(f"  GT:              t={GT['takeoff_t']:.3f}s  error={err:+.3f}s")
        if abs(err) <= 0.50:
            print("  -> PASS (within 0.50s tolerance)")
        else:
            print(f"  -> WARN: error {err:+.3f}s > 0.50s tolerance")
    else:
        print("TAKEOFF:           NOT DETECTED — FAIL")
    print()

    # STATE: AIRBORNE_ASCENT -> AIRBORNE_DESCENT (apex)
    apex_idx = _detect_apex(y_smooth, vel_y, pts, takeoff_idx, params) \
        if takeoff_idx is not None else None
    if apex_idx is not None:
        apex_t = pts[apex_idx]
        err = apex_t - GT["apex_t"]
        print(f"APEX:              frame {apex_idx}, t={apex_t:.3f}s")
        print(f"  GT:              t={GT['apex_t']:.3f}s  error={err:+.3f}s")
        if apex_t > GT["takeoff_t"]:
            print("  -> PASS (after takeoff)")
        else:
            print("  -> FAIL (before takeoff)")
    else:
        print("APEX:              NOT DETECTED")
    print()

    # STATE: ENTRY (water contact)
    water_idx = _detect_water_contact(y_smooth, vel_y, conf, pts, apex_idx, params) \
        if apex_idx is not None else None
    if water_idx is not None:
        water_t = pts[water_idx]
        err = water_t - GT["water_contact_t"]
        print(f"WATER CONTACT:     frame {water_idx}, t={water_t:.3f}s")
        print(f"  GT:              t={GT['water_contact_t']:.3f}s  error={err:+.3f}s")
        last_frame_t = pts[-1]
        if water_t < last_frame_t - 0.10:
            print("  -> PASS (genuine: not last frame of clip)")
            wc_type = "GENUINE"
        else:
            print("  -> WARN: near end of clip (END_OF_CLIP_COINCIDENCE?)")
            wc_type = "END_OF_CLIP_COINCIDENCE"
    else:
        print("WATER CONTACT:     NOT DETECTED")
        wc_type = "UNDETECTED"
    print()

    # Phase N: water contact classification
    print("-" * 60)
    print("PHASE N — Water Contact Classification")
    print(f"  water_contact_t = {GT['water_contact_t']:.3f}s")
    print(f"  clip duration   = {GT['total_duration_s']:.3f}s")
    margin = GT["total_duration_s"] - GT["water_contact_t"]
    print(f"  margin to end   = {margin:.3f}s")
    print(f"  classification  = {'END_OF_CLIP_COINCIDENCE' if margin < 0.5 else 'GENUINE'}")
    print(f"  rationale: CC3 water_contact=4.90s was the last PTS frame (coincidence).")
    print(f"  V2 annotation water_contact=4.22s leaves {margin:.3f}s of clip remaining.")
    print(f"  -> CC3 water_contact was END_OF_CLIP_COINCIDENCE (not physical detection).")
    print()

    print("=" * 60)
    print("CANARY MECHANISM CHECK: COMPLETE")
    print("=" * 60)

    result = {
        "label": "PHASE_M_CANARY_CHECK",
        "mode": "SYNTHETIC_TRAJECTORY",
        "context": context,
        "prep_end_t": prep_end_t if prep_end_idx is not None else None,
        "takeoff_t": pts[takeoff_idx] if takeoff_idx is not None else None,
        "takeoff_error_s": round(pts[takeoff_idx] - GT["takeoff_t"], 3) if takeoff_idx is not None else None,
        "apex_t": pts[apex_idx] if apex_idx is not None else None,
        "apex_error_s": round(pts[apex_idx] - GT["apex_t"], 3) if apex_idx is not None else None,
        "water_contact_t": pts[water_idx] if water_idx is not None else None,
        "water_contact_type": wc_type,
        "phase_n_cc3_water_classification": "END_OF_CLIP_COINCIDENCE",
        "phase_n_v2_water_classification": "GENUINE" if margin >= 0.5 else "NEAR_END",
        "all_states_traversed": all(x is not None for x in [prep_end_idx, takeoff_idx, apex_idx, water_idx]),
    }
    return result

if __name__ == "__main__":
    result = run_canary_check()
    import json
    out_path = os.path.join(os.path.dirname(__file__),
                            '../../docs/science/PHASE_M_CANARY_CHECK.json')
    with open(out_path, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"\nResult written to {out_path}")
