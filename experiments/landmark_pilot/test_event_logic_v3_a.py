#!/usr/bin/env python3
"""Tests for Event Logic V3-A — validates fixes for V2.1 confirmed failure modes.

Coverage:
  A1: Bounded apex fallback (no unbounded post-wc scan)
  A2: Bounded water contact search (no unbounded post-wc scan)
  A3: Multi-plateau prep_end (STANDING: last plateau, HURDLE: first plateau)
  A4: Higher motion_vel_thresh_factor (0.70 vs 0.50)

Uses cy_norm convention (0=top, 1=bottom) throughout.
"""

import sys, os, math, pytest
sys.path.insert(0, os.path.dirname(__file__))

from proposer_event_logic_v3_a import (
    _find_preparation_end_v3,
    _detect_apex_v3,
    _detect_water_contact_v3,
    propose_events_v3a,
    PARAMS_V3A,
)
from proposer_event_logic_v2_1 import classify_context


def make_pts(n, fps=30.0):
    return [i / fps for i in range(n)]


# ─── A1 tests: bounded apex fallback ──────────────────────────────────────────

class TestBoundedApex:
    """V3-A fix A1: apex fallback must not exceed takeoff + apex_max_window_s."""

    def _vel(self, y_smooth, pts, max_gap=0.20):
        n = len(y_smooth)
        vel = [None] * n
        for i in range(1, n):
            if y_smooth[i] is None or y_smooth[i-1] is None:
                continue
            g = pts[i] - pts[i-1]
            if g <= 0 or g > max_gap:
                continue
            vel[i] = (y_smooth[i] - y_smooth[i-1]) / g
        return vel

    def test_bounded_fallback_not_past_window(self):
        """A1: If primary fails (noisy velocity), fallback stays within apex_max_window_s."""
        fps = 30.0
        # Diver in flight 0-1.5s, min_y at 0.5s (within window),
        # then post-wc detections at very low cy (0.02) from t=2s onward.
        n = 90
        pts = [i / fps for i in range(n)]
        y = [None] * n
        # Flight phase: 0-1.5s (45 frames), cy decreases then increases (parabola)
        for i in range(45):
            t = i / fps
            cy = 0.30 - 0.12 * math.sin(math.pi * t / 1.5)
            y[i] = cy
        # Post-wc: 1.5s onward, cy = 0.02 (pool deck level — very low cy_norm)
        for i in range(45, n):
            y[i] = 0.02  # Lowest possible cy — would be "best" in V2.1 unbounded fallback

        vel = self._vel(y, pts)
        takeoff_idx = 0
        params = dict(PARAMS_V3A)
        params["apex_max_window_s"] = 1.5
        params["apex_search_start_s"] = 0.08

        apex_idx = _detect_apex_v3(y, vel, pts, takeoff_idx, params)
        assert apex_idx is not None
        # Must be within bounded window
        assert pts[apex_idx] <= pts[takeoff_idx] + params["apex_max_window_s"] + 1e-6, (
            f"Apex at t={pts[apex_idx]:.3f}s exceeds window end "
            f"{pts[takeoff_idx] + params['apex_max_window_s']:.3f}s"
        )
        # Specifically must NOT be at t=2s+ where post-wc cy=0.02
        assert pts[apex_idx] < 1.6, (
            f"V3-A fallback leaked into post-wc region: apex at t={pts[apex_idx]:.3f}s"
        )

    def test_v21_would_fail_v3a_passes(self):
        """A1 regression: build a case where V2.1 unbounded fallback picks post-wc frame,
        V3-A bounded fallback picks correct in-flight apex."""
        from proposer_event_logic_v2_1 import _detect_apex as _apex_v21
        fps = 30.0
        n = 120
        pts = [i / fps for i in range(n)]
        y = [0.25] * n  # flat trajectory (primary velocity crossing won't fire)
        # Post-wc region: very low cy (pool deck) at t=2s+
        for i in range(60, n):
            y[i] = 0.05
        vel = self._vel(y, pts)
        takeoff_idx = 0
        p21 = {"apex_search_start_s": 0.08}
        p3a = dict(PARAMS_V3A)
        p3a["apex_max_window_s"] = 1.5

        v21_apex = _apex_v21(y, vel, pts, takeoff_idx, p21)
        v3a_apex = _detect_apex_v3(y, vel, pts, takeoff_idx, p3a)

        # V2.1: unbounded, picks the post-wc minimum at t=2s+ (frame 60+)
        assert v21_apex is not None and v21_apex >= 60, (
            f"Expected V2.1 to pick post-wc frame; got {v21_apex}"
        )
        # V3-A: bounded, picks within [0, 1.5s] window
        assert v3a_apex is None or pts[v3a_apex] <= 1.5 + 1e-6, (
            f"V3-A leaked past window: apex at t={pts[v3a_apex]:.3f}s"
        )

    def test_primary_velocity_crossing_unchanged(self):
        """A1: Primary detection (velocity crossing) is unchanged between V2.1 and V3-A."""
        fps = 30.0
        n = 60
        pts = [i / fps for i in range(n)]
        # Clean parabola: min at frame 15 (0.5s)
        y = [0.30 - 0.12 * math.sin(math.pi * i / 30) for i in range(n)]
        vel = self._vel(y, pts)
        takeoff_idx = 0
        params = dict(PARAMS_V3A)
        params["apex_search_start_s"] = 0.08

        apex_idx = _detect_apex_v3(y, vel, pts, takeoff_idx, params)
        # Should find apex near frame 15 (0.5s) via velocity crossing
        assert apex_idx is not None
        assert abs(pts[apex_idx] - 0.5) < 0.15, f"Primary apex too far from expected: {pts[apex_idx]:.3f}s"


# ─── A2 tests: bounded water contact ──────────────────────────────────────────

class TestBoundedWaterContact:
    """V3-A fix A2: water contact search must not exceed apex + wc_max_window_s."""

    def test_wc_bounded_not_past_window(self):
        """A2: cy>threshold found in post-dive region should be ignored if beyond window."""
        fps = 30.0
        n = 120
        pts = [i / fps for i in range(n)]
        # After apex (idx=0): cy stays below 0.50 until t=3.5s (past window)
        y = [0.30] * n
        for i in range(int(3.5 * fps), n):
            y[i] = 0.60  # cy > 0.50 — would trigger in V2.1 unbounded search
        # V3-A: search only [0, wc_max_window_s=2.5s] → won't find it
        conf = [0.5] * n
        params = dict(PARAMS_V3A)
        params["water_contact_min_after_apex_s"] = 0.05
        params["wc_max_window_s"] = 2.5
        params["water_line_cy_norm"] = 0.50

        apex_idx = 0
        wc_idx = _detect_water_contact_v3(y, [None]*n, conf, pts, apex_idx, params)
        assert wc_idx is None or pts[wc_idx] <= 2.5 + 1e-6, (
            f"V3-A wc leaked past window: wc at t={pts[wc_idx]:.3f}s"
        )

    def test_wc_found_within_window(self):
        """A2: Water contact found correctly when cy>threshold within window."""
        fps = 30.0
        n = 60
        pts = [i / fps for i in range(n)]
        y = [0.30] * n
        # cy exceeds 0.50 at t=1.0s
        for i in range(30, n):
            y[i] = 0.55
        conf = [0.5] * n
        params = dict(PARAMS_V3A)
        params["water_contact_min_after_apex_s"] = 0.05
        params["wc_max_window_s"] = 2.5
        params["water_line_cy_norm"] = 0.50

        apex_idx = 0
        wc_idx = _detect_water_contact_v3(y, [None]*n, conf, pts, apex_idx, params)
        assert wc_idx is not None
        assert abs(pts[wc_idx] - 1.0) < 0.1, f"Unexpected wc time: {pts[wc_idx]:.3f}s"


# ─── A3 tests: multi-plateau prep_end ─────────────────────────────────────────

class TestMultiPlateauPrepEnd:
    """V3-A fix A3: STANDING uses last qualifying plateau; HURDLE uses first."""

    def _params_for_vel_thresh(self, thresh_factor=0.70):
        p = dict(PARAMS_V3A)
        p["motion_vel_thresh_factor"] = thresh_factor
        return p

    def test_standing_last_plateau(self):
        """A3 STANDING: with two plateaus, last is returned (handles long approach)."""
        fps = 30.0
        # Scenario: initial rest (0-0.5s), approach motion (0.5-2s), on-board (2-4s), takeoff
        n = 150  # 5s
        pts = [i/fps for i in range(n)]
        # cy_norm trajectory
        y = [None] * n
        for i in range(n):
            t = i / fps
            if t < 0.5:
                y[i] = 0.50  # initial rest (off-board)
            elif t < 2.0:
                y[i] = 0.50 - 0.2 * (t - 0.5)  # approach: moving
            elif t < 4.0:
                y[i] = 0.10  # on-board static
            else:
                y[i] = 0.10 - 0.4 * (t - 4.0)  # takeoff motion

        params = self._params_for_vel_thresh()
        params["static_min_duration_v3_s"] = 0.40

        prep_end_idx = _find_preparation_end_v3(y, pts, params, context="STANDING")
        assert prep_end_idx is not None
        # Should find the LAST plateau end (on-board static ends at ~4.0s)
        assert pts[prep_end_idx] > 3.0, (
            f"STANDING should find last plateau end (near 4.0s); got {pts[prep_end_idx]:.3f}s"
        )

    def test_standing_last_plateau_ignores_brief_initial_rest(self):
        """A3 STANDING: initial brief rest (< 0.5s) should not be the final prep_end."""
        fps = 30.0
        n = 200  # ~6.7s
        pts = [i/fps for i in range(n)]
        y = [None] * n
        for i in range(n):
            t = i / fps
            if t < 0.40:
                y[i] = 0.50  # initial brief rest
            elif t < 2.0:
                y[i] = 0.50 + 0.1 * (t - 0.40)  # motion (approaching)
            elif t < 4.5:
                y[i] = 0.12  # on-board static (2.5s long >> min_dur)
            else:
                y[i] = 0.12 - 0.5 * (t - 4.5)  # takeoff

        params = self._params_for_vel_thresh()
        params["static_min_duration_v3_s"] = 0.40

        prep_end_idx = _find_preparation_end_v3(y, pts, params, context="STANDING")
        # V2.1 would return ~0.4s (first motion transition); V3-A should return ~4.5s
        assert prep_end_idx is not None
        assert pts[prep_end_idx] > 3.5, (
            f"STANDING should ignore initial brief rest; found prep_end at {pts[prep_end_idx]:.3f}s"
        )

    def test_hurdle_first_qualifying_plateau(self):
        """A3 HURDLE: first qualifying plateau (before hurdle jump) is returned."""
        fps = 30.0
        n = 150  # 5s
        pts = [i/fps for i in range(n)]
        y = [None] * n
        for i in range(n):
            t = i / fps
            if t < 0.30:
                y[i] = 0.50  # brief initial rest (< min_dur)
            elif t < 1.0:
                y[i] = 0.50 + 0.1 * t  # motion (walk to board)
            elif t < 2.5:
                y[i] = 0.12  # ON-BOARD STATIC (1.5s ≥ min_dur=0.40s)
            elif t < 3.5:
                y[i] = 0.12 - 0.3 * (t - 2.5)  # hurdle jump
            elif t < 4.0:
                y[i] = 0.42 + 0.1 * (t - 3.5)  # board recontact brief static
            else:
                y[i] = 0.12 - 0.8 * (t - 4.0)  # final takeoff

        params = self._params_for_vel_thresh()
        params["static_min_duration_v3_s"] = 0.40

        prep_end_idx = _find_preparation_end_v3(y, pts, params, context="HURDLE")
        assert prep_end_idx is not None
        # Should be the end of on-board static (~2.5s), NOT the board-recontact (~4.0s)
        assert 2.0 <= pts[prep_end_idx] <= 2.6, (
            f"HURDLE should find first qualifying plateau (~2.5s); got {pts[prep_end_idx]:.3f}s"
        )

    def test_hurdle_skips_short_initial_rest(self):
        """A3 HURDLE: brief initial rest < static_min_duration_v3_s is skipped."""
        fps = 30.0
        n = 120  # 4s
        pts = [i/fps for i in range(n)]
        y = [None] * n
        for i in range(n):
            t = i/fps
            if t < 0.25:
                y[i] = 0.5  # 0.25s static — shorter than min_dur=0.40
            elif t < 1.0:
                y[i] = 0.5 + 0.1*t  # motion
            elif t < 2.0:
                y[i] = 0.12  # on-board static 1s ≥ 0.40
            else:
                y[i] = 0.12 - 0.3*(t-2.0)  # hurdle

        params = self._params_for_vel_thresh()
        params["static_min_duration_v3_s"] = 0.40

        prep_end_idx = _find_preparation_end_v3(y, pts, params, context="HURDLE")
        assert prep_end_idx is not None
        # Should skip the 0.25s rest and find the 1s on-board plateau
        assert pts[prep_end_idx] >= 1.0, (
            f"HURDLE should skip short initial rest; got prep_end at {pts[prep_end_idx]:.3f}s"
        )

    def test_standing_single_plateau_unchanged(self):
        """A3 STANDING: with one plateau, behavior same as V2.1 (simple case)."""
        fps = 30.0
        n = 60
        pts = [i/fps for i in range(n)]
        y = [None] * n
        for i in range(n):
            t = i/fps
            if t < 1.5:
                y[i] = 0.15  # static
            else:
                y[i] = 0.15 - 0.3*(t-1.5)  # takeoff

        params = self._params_for_vel_thresh()
        params["static_min_duration_v3_s"] = 0.40

        prep_end_idx = _find_preparation_end_v3(y, pts, params, context="STANDING")
        assert prep_end_idx is not None
        # End of plateau ≈ 1.5s
        assert abs(pts[prep_end_idx] - 1.5) < 0.15, (
            f"Single plateau: expected prep_end near 1.5s; got {pts[prep_end_idx]:.3f}s"
        )


# ─── A4 tests: higher motion_vel_thresh for 360p noise ────────────────────────

class TestHigherMotionVelThresh:
    """V3-A fix A4: motion_vel_thresh_factor=0.70 handles 360p detection noise."""

    def test_noisy_static_detected_as_prep(self):
        """A4: Trajectory with 360p-level noise (vel ~0.015 cy/s) detected as static by V3-A.

        360p detection noise: bbox jitter ≈ 0.0005 cy per frame at 30fps.
        vel ≈ 0.0005 * 30 = 0.015 cy/s.
        V3-A thresh = 0.04 * 0.70 = 0.028 > 0.015 → detected as static.
        V2.1 thresh = 0.04 * 0.50 = 0.020 > 0.015 → also ok at this level.
        The fix targets jitter ≈ 0.0007 cy/frame → vel~0.021 cy/s: above V2.1 (0.020)
        but below V3-A (0.028).
        """
        fps = 30.0
        n = 60
        pts = [i/fps for i in range(n)]
        # 360p detection noise at the borderline level: vel ~0.021 cy/s
        # (jitter=0.0007 cy per frame, marginally above V2.1 thresh=0.020)
        import random
        random.seed(42)
        y = [0.15 + random.gauss(0, 0.0007) for _ in range(n)]
        y[-15:] = [0.15 - 0.1 * i / 15 for i in range(15)]  # takeoff at end

        params_v3a = dict(PARAMS_V3A)
        params_v3a["static_min_duration_v3_s"] = 0.40
        params_v3a["motion_vel_thresh_factor"] = 0.70  # V3-A: thresh=0.028

        prep_end_v3a = _find_preparation_end_v3(y, pts, params_v3a, context="STANDING")
        # V3-A with 0.70 factor (thresh=0.028 > vel~0.021) should detect static
        assert prep_end_v3a is not None, (
            "V3-A thresh_factor=0.70 (thresh=0.028) should detect marginal 360p noise (vel~0.021)"
        )
        # V3-A should find the static period before the last 15 frames of motion
        assert pts[prep_end_v3a] < pts[-16] + 0.1, (
            f"V3-A prep_end should be before takeoff: {pts[prep_end_v3a]:.3f}s"
        )


# ─── Full state machine integration test ──────────────────────────────────────

class TestV3AFullPipeline:
    """Full V3-A pipeline: test against known failure cases from development evaluation."""

    def test_bounded_apex_prevents_post_wc_confusion(self):
        """Full pipeline: bounded apex fallback prevents V2.1's post-wc confusion.

        Dive 311 failure pattern: V2.1 fallback apex picked pool-deck detections
        (cy~0.11) at t=18s because they have minimum cy in the entire video.
        V3-A: fallback is bounded to [takeoff, takeoff + 1.5s].
        Test: with known takeoff at t=1.0s, apex fallback must not reach t=3.0s.
        """
        from proposer_event_logic_v2_1 import _detect_apex as _apex_v21
        fps = 30.0
        n = int(5 * fps)  # 5s clip
        pts = [i/fps for i in range(n)]
        # Flat trajectory in flight (noisy, no clear velocity crossing)
        y = [0.20] * n
        # Post-wc: very low cy starting at t=2.0s (pool deck, cy=0.05)
        for i in range(int(2.0*fps), n):
            y[i] = 0.05
        vel = [None] + [(y[i]-y[i-1])*fps for i in range(1, n)]
        takeoff_idx = int(1.0 * fps)  # t=1.0s
        params_v3a = dict(PARAMS_V3A)
        params_v3a["apex_max_window_s"] = 1.5

        # V2.1 unbounded: picks the post-wc minimum (t=2.0s, idx=60)
        v21_apex = _apex_v21(y, vel, pts, takeoff_idx, {"apex_search_start_s": 0.08})
        assert v21_apex is not None and v21_apex >= int(2.0*fps), (
            f"V2.1 should pick post-wc frame; got idx={v21_apex} t={pts[v21_apex]:.3f}s"
        )

        # V3-A bounded: must stay within [1.0, 1.0+1.5] = [1.0, 2.5]
        v3a_apex = _detect_apex_v3(y, vel, pts, takeoff_idx, params_v3a)
        assert v3a_apex is None or pts[v3a_apex] <= 1.0 + 1.5 + 1e-6, (
            f"V3-A bounded apex leaked past window: t={pts[v3a_apex]:.3f}s > 2.5s"
        )

    def test_standing_long_prep_finds_correct_takeoff(self):
        """Full pipeline: STANDING dive with motion-rich post-wc region.
        Preparation is the dominant long plateau; takeoff identified correctly.
        The V3-A 'last plateau' behavior correctly finds the on-board static
        (not a brief initial or post-wc rest) as prep_end.
        """
        fps = 30.0
        # t=0-0.5s: brief off-board rest
        # t=0.5-3.0s: motion (walking to board)
        # t=3.0-4.8s: on-board static (longest plateau)
        # t=4.8-5.5s: takeoff and flight
        # t=5.5+: post-wc motion (oscillatory, not static → not a qualifying plateau)
        n = int(8 * fps)
        pts = [i/fps for i in range(n)]
        y = []
        for i in range(n):
            t = i/fps
            if t < 0.5:
                y.append(0.50)  # brief off-board rest
            elif t < 3.0:
                y.append(0.50 - 0.15*(t-0.5))  # walking to board
            elif t < 4.8:
                y.append(0.12)  # on-board static
            elif t < 5.0:
                y.append(0.12 - 0.3*(t-4.8))  # takeoff
            elif t < 5.5:
                y.append(0.06 + 0.5*(t-5.0))  # ascent + descent
            else:
                # Post-wc: oscillatory motion (not a static plateau)
                y.append(0.50 + 0.06 * math.sin(3.0 * (t - 5.5)))

        conf = [0.5] * n
        result = propose_events_v3a(y, pts, conf, "301B", dict(PARAMS_V3A))

        # Takeoff should be near 4.8-5.2s
        to_t = result.get("takeoff_t")
        assert to_t is not None, "V3-A should find takeoff in long-prep dive"
        assert 4.5 <= to_t <= 5.5, f"Unexpected takeoff time: {to_t:.3f}s"

    def test_prep_end_found_late_in_long_prep_video(self):
        """Full pipeline: long-prep STANDING video where diver approaches board at 3s.
        V3-A should find prep_end near 4.5s (not at 0.5s like V2.1).
        """
        fps = 30.0
        n = int(7 * fps)  # 7s video, takeoff at 5s
        pts = [i/fps for i in range(n)]
        y = []
        for i in range(n):
            t = i/fps
            if t < 0.5:
                y.append(0.50)  # initial brief rest (off-board)
            elif t < 3.0:
                y.append(0.50 - 0.1*(t-0.5))  # motion: walking to board
            elif t < 4.8:
                y.append(0.12)  # on-board static (1.8s)
            elif t < 5.5:
                y.append(0.12 - 0.5*(t-4.8))  # takeoff
            else:
                y.append(0.08)  # flight/post

        conf = [0.5] * n
        result = propose_events_v3a(y, pts, conf, "301B", dict(PARAMS_V3A))

        prep_t = result.get("prep_end_t")
        assert prep_t is not None, "V3-A should find prep_end"
        # V2.1 would find 0.5s; V3-A should find ~4.8s
        assert prep_t > 3.5, f"V3-A should find late prep_end; got {prep_t:.3f}s"

    def test_hurdle_first_plateau_used(self):
        """Full pipeline: HURDLE dive with prep on board then hurdle jump.
        V3-A should find prep_end before the hurdle, not at board-recontact.
        """
        fps = 30.0
        n = int(6 * fps)  # 6s, takeoff at 4.5s
        pts = [i/fps for i in range(n)]
        y = []
        for i in range(n):
            t = i/fps
            if t < 0.20:
                y.append(0.50)  # initial brief rest
            elif t < 1.0:
                y.append(0.50 - 0.2*(t-0.2))  # walk to board
            elif t < 2.5:
                y.append(0.12)  # on-board PREPARATION (1.5s)
            elif t < 3.2:
                y.append(0.12 - 0.3*(t-2.5))  # HURDLE ascent
            elif t < 3.7:
                y.append(0.12 + 0.1*(t-3.2))  # descent/board recontact
            elif t < 4.0:
                y.append(0.17)  # brief board-recontact static
            elif t < 5.0:
                y.append(0.17 - 0.6*(t-4.0))  # final takeoff
            else:
                y.append(0.10)  # flight

        conf = [0.5] * n
        result = propose_events_v3a(y, pts, conf, "102C", dict(PARAMS_V3A))

        prep_t = result.get("prep_end_t")
        assert prep_t is not None, "V3-A should find prep_end for HURDLE"
        # Should be the on-board prep plateau end (~2.5s), not board-recontact (~4.0s)
        assert prep_t < 3.0, (
            f"HURDLE prep_end should be before hurdle jump (~2.5s); got {prep_t:.3f}s"
        )
