#!/usr/bin/env python3
"""Unit tests for Event Logic V2.2 (scale-aware takeoff detection).

Covers packet Phase R requirements:
  - scale-normalized velocity (S1_BODY_SCALE)
  - zero/near-zero bbox-scale safeguard
  - preparation MAD/noise statistic (S2_PREP_BASELINE)
  - FPS invariance (time-based smoothing, already true of V2.1's PARAMS but
    re-verified here for the V2.2 code path)
  - hurdle vs final takeoff (state preservation, Phase H)
  - resolution invariance fixture: same synthetic trajectory rendered at
    360p/720p/1080p normalized scale must yield equivalent landmarks.
"""
import math
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from proposer_event_logic_v2_2 import (
    propose_events_s1_body_scale, propose_events_s2_prep_baseline,
    reference_bbox_height, robust_median, robust_mad,
    MIN_BBOX_H_NORM, PARAMS_S1, PARAMS_S2,
)


def make_hurdle_trajectory(fps=60.0, bbox_h=0.12):
    """H2_HURDLE-style trajectory in cy_norm, reusing the exact proven-good
    shape from test_event_logic_v2_1.make_h2_hurdle_trajectory (preparation
    0.0-0.5s, hurdle ascent/descent 0.5-1.8s, board loading 1.8-2.5s, final
    takeoff+ascent 2.5-3.5s [GT takeoff~2.5s], descent 3.5-4.5s, post-entry),
    with a matching bbox-height array added for the S1 body-scale candidate.
    """
    total = 5.5
    n = int(total * fps) + 1
    pts = [i / fps for i in range(n)]
    y = []
    conf = []
    for t in pts:
        if t <= 0.50:
            y.append(0.40); conf.append(0.85)
        elif t <= 1.00:
            frac = (t - 0.50) / 0.50
            y.append(0.40 - 0.22 * frac); conf.append(0.80)
        elif t <= 1.80:
            frac = (t - 1.00) / 0.80
            y.append(0.18 + 0.26 * frac); conf.append(0.80)
        elif t <= 2.50:
            y.append(0.44); conf.append(0.82)
        elif t <= 3.50:
            frac = (t - 2.50) / 1.00
            y.append(0.44 - 0.32 * frac); conf.append(0.78)
        elif t <= 4.50:
            frac = (t - 3.50) / 1.00
            y.append(0.12 + 0.43 * frac); conf.append(0.72)
        else:
            y.append(0.55); conf.append(0.30)
    bh = [bbox_h] * n
    return y, bh, pts, conf


def scale_trajectory(y, scale_factor, offset=0.0):
    """Rescale a cy_norm trajectory around its own mean, simulating a
    different (but still normalized 0..1) camera framing/crop. This models
    'same physical motion, different normalized-coordinate scale' — the
    exact scenario the packet says must NOT be conflated with resolution."""
    mean = sum(y) / len(y)
    return [mean + (v - mean) * scale_factor + offset for v in y]


class Result:
    def __init__(self):
        self.passed = 0
        self.failed = []

    def check(self, name, cond):
        if cond:
            self.passed += 1
        else:
            self.failed.append(name)


def run():
    r = Result()

    # 1. S1 body-scale detects takeoff/apex/water_contact on a standard fixture
    y, bh, pts, conf = make_hurdle_trajectory()
    res1 = propose_events_s1_body_scale(y, bh, pts, conf, "5111B")
    r.check("S1_hurdle_takeoff_detected", res1["takeoff_t"] is not None)
    r.check("S1_hurdle_apex_detected", res1["apex_t"] is not None)
    r.check("S1_hurdle_wc_detected", res1["water_contact_t"] is not None)
    r.check("S1_hurdle_takeoff_near_gt",
            res1["takeoff_t"] is not None and abs(res1["takeoff_t"] - 2.5) < 0.30)
    r.check("S1_context_is_hurdle", res1["context"] == "HURDLE")

    # 2. S2 prep-baseline detects the same fixture
    res2 = propose_events_s2_prep_baseline(y, bh, pts, conf, "5111B")
    r.check("S2_hurdle_takeoff_detected", res2["takeoff_t"] is not None)
    r.check("S2_hurdle_apex_detected", res2["apex_t"] is not None)
    r.check("S2_hurdle_wc_detected", res2["water_contact_t"] is not None)
    r.check("S2_hurdle_takeoff_near_gt",
            res2["takeoff_t"] is not None and abs(res2["takeoff_t"] - 2.5) < 0.30)

    # 3. Hurdle apex must not become final takeoff (state preservation, Phase H):
    #    the hurdle ascent/descent (t in [0.5,1.8]) has its own velocity
    #    zero-crossing; it must not be reported as takeoff_t (final takeoff is
    #    the SECOND rise, after board loading, at t>=2.0).
    r.check("S1_hurdle_peak_not_takeoff",
            res1["takeoff_t"] is not None and res1["takeoff_t"] >= 2.0)
    r.check("S2_hurdle_peak_not_takeoff",
            res2["takeoff_t"] is not None and res2["takeoff_t"] >= 2.0)

    # 4. Standing fixture (no hurdle) still works
    y_st = []
    pts_st = [i / 60.0 for i in range(int(3.5 * 60.0))]
    for t in pts_st:
        if t <= 1.0:
            v = 0.45
        elif t <= 1.5:
            frac = (t - 1.0) / 0.5
            v = 0.45 - 0.25 * frac
        elif t <= 2.2:
            frac = (t - 1.5) / 0.7
            v = 0.20 + 0.30 * frac
        else:
            v = 0.50 + 0.02 * (t - 2.2)
        y_st.append(v)
    bh_st = [0.12] * len(y_st)
    conf_st = [0.6] * len(y_st)
    res_st1 = propose_events_s1_body_scale(y_st, bh_st, pts_st, conf_st, "301B")
    r.check("S1_standing_context", res_st1["context"] == "STANDING")
    r.check("S1_standing_takeoff_detected", res_st1["takeoff_t"] is not None)
    res_st2 = propose_events_s2_prep_baseline(y_st, bh_st, pts_st, conf_st, "301B")
    r.check("S2_standing_takeoff_detected", res_st2["takeoff_t"] is not None)

    # 5. Zero/near-zero bbox-scale safeguard: degenerate bh array must not
    #    crash or produce a divide-by-zero; falls back to MIN_BBOX_H_NORM.
    bh_zero = [0.0] * len(y)
    ref_h = reference_bbox_height(bh_zero, pts, prep_end_idx=50)
    r.check("zero_bbox_safeguard_min", ref_h == MIN_BBOX_H_NORM)
    res_zero = propose_events_s1_body_scale(y, bh_zero, pts, conf, "5111B")
    r.check("zero_bbox_no_crash", res_zero is not None)

    # 6. Preparation MAD/noise statistic: degenerate perfectly-flat preparation
    #    (MAD=0) must not make the threshold pathologically tight (floor applies).
    y_flat_prep = [0.40] * 60 + y[60:]
    res_flat = propose_events_s2_prep_baseline(y_flat_prep[:len(y)], bh, pts, conf, "5111B")
    r.check("S2_flat_prep_no_crash", res_flat is not None)
    r.check("S2_flat_prep_mad_floored", res_flat["prep_mad_vel"] >= 0.003 - 1e-9)

    # 7. FPS invariance: same physical trajectory resampled at 30fps vs 60fps
    #    should yield equivalent PTS-timed landmarks (within ~1 frame at the
    #    lower fps).
    y60, bh60, pts60, conf60 = make_hurdle_trajectory(fps=60.0)
    y30, bh30, pts30, conf30 = make_hurdle_trajectory(fps=30.0)
    res60 = propose_events_s1_body_scale(y60, bh60, pts60, conf60, "5111B")
    res30 = propose_events_s1_body_scale(y30, bh30, pts30, conf30, "5111B")
    r.check("fps_invariance_takeoff",
            res60["takeoff_t"] is not None and res30["takeoff_t"] is not None and
            abs(res60["takeoff_t"] - res30["takeoff_t"]) < (2.0 / 30.0))
    r.check("fps_invariance_apex",
            res60["apex_t"] is not None and res30["apex_t"] is not None and
            abs(res60["apex_t"] - res30["apex_t"]) < (2.0 / 30.0))

    # 8. Resolution/scale-invariance fixture (packet Phase R explicit
    #    requirement): the SAME synthetic trajectory, rendered with amplitude
    #    scaled the way a different normalized framing/crop would (NOT the
    #    same as resolution — packet Phase O clarifies resolution alone does
    #    not multiply normalized displacement — but this stresses the S1
    #    body-scale normalization's robustness to varying cy_norm amplitude
    #    when bbox height scales proportionally too, which IS the resolution-
    #    invariant regime: both cy_norm swing AND bbox height shrink/grow
    #    together under a pure zoom).
    for scale, bbox_scale in [(1.0, 0.12), (0.5, 0.06), (2.0, 0.24)]:
        y_s = scale_trajectory(y, scale, offset=0.40 * (1 - scale))
        bh_s = [bbox_scale] * len(y)
        res_s = propose_events_s1_body_scale(y_s, bh_s, pts, conf, "5111B")
        ok = (res_s["takeoff_t"] is not None and
              abs(res_s["takeoff_t"] - res1["takeoff_t"]) < 0.20)
        r.check(f"scale_invariance_takeoff_x{scale}", ok)

    # 9. DEVELOPMENT/PARIS firewall: this test file must not import or
    #    reference any Paris-specific fixture/constant. (Marker strings are
    #    assembled at runtime so this check does not trivially match its own
    #    source text.)
    import inspect
    src = inspect.getsource(sys.modules[__name__])
    paris_marker = "IMG_" + "1937"
    canary_sha_marker = "d1222" + "62be8"
    r.check("no_paris_reference_in_tests",
            paris_marker not in src and canary_sha_marker not in src)

    print(f"PASS: {r.passed}  FAIL: {len(r.failed)}")
    for f in r.failed:
        print("  FAILED:", f)
    return len(r.failed) == 0


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
