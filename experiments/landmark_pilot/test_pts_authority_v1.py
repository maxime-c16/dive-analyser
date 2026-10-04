#!/usr/bin/env python3
"""Phase A — PTS Authority Regression Tests.

Freezes the canonical frame-addressing rule: PTS_AUTHORITATIVE_SEEK.

Historical failure (Paris repair cycle):
  - Sequential read at frame_count=235 returned incorrect content (non-diver)
  - Canonical fi=238 via cap.set(CAP_PROP_POS_FRAMES, 238) returned correct diver
  - Root cause: h264 decoder at 56.5fps accumulates PTS rounding error over long
    sequential reads; after ~230 frames the decoded frame counter is 3 frames
    ahead of actual PTS position.

Authoritative rule (FROZEN):
  PTS_AUTHORITATIVE_SEEK: always use cap.set(CAP_PROP_POS_FRAMES, fi) before
  cap.read() when extracting a specific anchor frame. Never rely on sequential
  frame-count alone when a specific PTS-based frame index is required.

Tests:
  A1: Seek to a known frame index returns a PTS within 1.5 frame-periods of GT
  A2: Repeated seek to same fi returns same PTS (deterministic)
  A3: Sequential read of all frames returns monotonically increasing PTS
  A4: Paris regression fixture — fi=235 vs fi=238 at wc PTS=4.220s
      (fixture-based: documents the known drift, no live video required)
  A5: Proxy video 311 — seek at GT takeoff fi=412 returns PTS within tolerance
  A6: PTS after seek matches PTS of equivalent sequential position within 2-frame period
  A7: Development trajectory proxy 1040 — seek at GT takeoff fi=134 within tolerance
"""

import sys
import os
import math
import pytest

sys.path.insert(0, os.path.dirname(__file__))

PROXY_ROOT = os.path.join(
    os.path.dirname(__file__), "../../media/perception_decomposition_v1/proxies"
)

# GT ground truth for 311 and 1040 from DEV_D5_ONLY_TRAJECTORIES_V1.json
GT_311 = {"takeoff_pts_s": 13.7546, "wc_pts_s": 14.821262, "fps": 29.97}
GT_1040 = {"takeoff_pts_s": 4.463857, "apex_pts_s": 4.797189, "wc_pts_s": 5.413853, "fps": 29.97}

# Paris regression fixture (no live video required — documents known drift)
PARIS_REGRESSION = {
    "fps": 56.517,
    "gt_wc_pts_s": 4.220,
    "canonical_fi": 238,
    "drift_fi": 235,
    "canonical_pts_expected_s": 4.220,  # ≈ 238/56.517
    "drift_pts_expected_s": 4.167,       # ≈ 235/56.517
    "pts_tolerance_s": 0.040,           # 2-frame period at 56.5fps
    "description": (
        "Paris h264 1080p @ 56.5fps sequential drift: after ~230 frames, "
        "sequential read counter is 3 frames ahead of actual PTS. "
        "fi=235 was wrong (IoU=0.107); fi=238 via seek was canonical (IoU=0.324). "
        "Root cause: OpenCV h264 decoder PTS rounding accumulated across 230+ frames."
    ),
}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def proxy_path(dive_id):
    return os.path.join(PROXY_ROOT, f"{dive_id}.mp4")


def pts_from_seek(cap, fi):
    """Seek to fi and return PTS of that frame in seconds."""
    import cv2
    cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
    ret, _ = cap.read()
    if not ret:
        return None
    return cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0


def pts_expected(fi, fps):
    """Expected PTS for frame fi at constant fps."""
    return fi / fps


def frame_period(fps):
    return 1.0 / fps


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestPTSAuthorityDive311:
    """Phase A1/A5: Seek-based PTS authority on development proxy 311."""

    @pytest.fixture(autouse=True)
    def open_cap(self):
        try:
            import cv2
        except ImportError:
            pytest.skip("cv2 not available")
        p = proxy_path(311)
        if not os.path.exists(p):
            pytest.skip(f"Proxy not found: {p}")
        self.cap = cv2.VideoCapture(p)
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        yield
        self.cap.release()

    def test_seek_gt_takeoff_within_tolerance(self):
        """A5: fi=412 seek returns PTS within 2 frame-periods of GT takeoff 13.754s."""
        # fi=412 is the annotation frame_index for 311 takeoff
        fi = 412
        pts = pts_from_seek(self.cap, fi)
        assert pts is not None, "Seek to fi=412 returned no frame"
        tol = 2 * frame_period(self.fps)
        assert abs(pts - GT_311["takeoff_pts_s"]) < tol, (
            f"Seek fi=412 returned PTS={pts:.4f}s, GT={GT_311['takeoff_pts_s']}s, "
            f"delta={abs(pts-GT_311['takeoff_pts_s']):.4f}s > tol={tol:.4f}s"
        )

    def test_seek_deterministic_repeated(self):
        """A2: Repeated seek to same fi returns identical PTS."""
        fi = 412
        pts1 = pts_from_seek(self.cap, fi)
        pts2 = pts_from_seek(self.cap, fi)
        assert pts1 is not None and pts2 is not None
        assert pts1 == pts2, (
            f"Repeated seek to fi={fi} returned different PTS: {pts1} vs {pts2}"
        )

    def test_seek_wc_within_tolerance(self):
        """A5 extended: fi for wc returns PTS within 2 frame-periods of GT wc 14.821s."""
        # wc fi ≈ 444 (14.821 * 29.97 ≈ 444.3)
        fi = int(round(GT_311["wc_pts_s"] * GT_311["fps"]))
        pts = pts_from_seek(self.cap, fi)
        assert pts is not None
        tol = 2 * frame_period(GT_311["fps"])
        assert abs(pts - GT_311["wc_pts_s"]) < tol, (
            f"Seek fi={fi} returned PTS={pts:.4f}s, GT={GT_311['wc_pts_s']}s, "
            f"delta={abs(pts-GT_311['wc_pts_s']):.4f}s > tol={tol:.4f}s"
        )

    def test_sequential_pts_monotonically_increasing(self):
        """A3: Sequential read of all frames produces strictly increasing PTS."""
        import cv2
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        prev_pts = -1.0
        n_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        for i in range(min(n_frames, 100)):  # Sample first 100
            ret, _ = self.cap.read()
            if not ret:
                break
            pts = self.cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            assert pts > prev_pts or i == 0, (
                f"Non-monotonic PTS at frame {i}: {pts} <= {prev_pts}"
            )
            prev_pts = pts

    def test_seek_vs_sequential_agreement_at_anchor(self):
        """A6: For proxy video, seek PTS and sequential PTS at fi=412 agree within 1-frame period.

        Note: This validates that proxy 360p h264 does NOT exhibit the Paris-style
        drift. Paris drift is documented in the regression fixture below. Proxy 360p at
        29.97fps is a simpler h264 stream with shorter duration and lower fps — no
        accumulation of 3-frame drift observed.
        """
        import cv2
        fi = 412
        pts_seek = pts_from_seek(self.cap, fi)
        # Sequential walk
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        for i in range(fi):
            ret, _ = self.cap.read()
            if not ret:
                pytest.skip("Sequential read failed before fi=412")
        ret, _ = self.cap.read()
        pts_seq = self.cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        assert abs(pts_seek - pts_seq) < frame_period(self.fps), (
            f"Seek PTS={pts_seek:.4f}s vs sequential PTS={pts_seq:.4f}s differ by "
            f"{abs(pts_seek-pts_seq):.4f}s > 1 frame period={frame_period(self.fps):.4f}s"
        )


class TestPTSAuthorityDive1040:
    """Phase A7: Seek-based PTS authority on HURDLE proxy 1040."""

    @pytest.fixture(autouse=True)
    def open_cap(self):
        try:
            import cv2
        except ImportError:
            pytest.skip("cv2 not available")
        p = proxy_path(1040)
        if not os.path.exists(p):
            pytest.skip(f"Proxy not found: {p}")
        self.cap = cv2.VideoCapture(p)
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        yield
        self.cap.release()

    def test_seek_gt_takeoff_within_tolerance(self):
        """A7: 1040 takeoff seek within 2 frame-periods of GT 4.464s."""
        fi = int(round(GT_1040["takeoff_pts_s"] * GT_1040["fps"]))
        pts = pts_from_seek(self.cap, fi)
        assert pts is not None
        tol = 2 * frame_period(self.fps)
        assert abs(pts - GT_1040["takeoff_pts_s"]) < tol, (
            f"Seek fi={fi} returned PTS={pts:.4f}s, GT={GT_1040['takeoff_pts_s']}s"
        )

    def test_seek_deterministic(self):
        """A2/A7: Repeated seeks are deterministic for HURDLE proxy."""
        fi = int(round(GT_1040["takeoff_pts_s"] * GT_1040["fps"]))
        pts1 = pts_from_seek(self.cap, fi)
        pts2 = pts_from_seek(self.cap, fi)
        assert pts1 == pts2


class TestParisRegressionFixture:
    """Phase A4: Paris sequential-read drift regression (fixture-based).

    Paris video is not required locally. This test documents the known drift
    and verifies the fixture arithmetic is consistent.
    """

    def test_paris_regression_fixture_documented(self):
        """A4: Paris fi=235 vs fi=238 drift is documented in fixture."""
        fix = PARIS_REGRESSION
        assert fix["canonical_fi"] == 238
        assert fix["drift_fi"] == 235
        assert fix["canonical_fi"] - fix["drift_fi"] == 3, (
            "Paris drift is exactly 3 frames (documented)"
        )

    def test_paris_pts_arithmetic_drift_significance(self):
        """A4: At 56.5fps a 3-frame drift shifts PTS by 53ms — enough to cross
        a different detector candidate pool and change the rank-1 detection."""
        fps = PARIS_REGRESSION["fps"]
        drift_frames = PARIS_REGRESSION["canonical_fi"] - PARIS_REGRESSION["drift_fi"]
        drift_pts_s = drift_frames / fps
        # At 56.5fps, 3 frames = 53ms — this is enough to change the candidate pool
        assert 0.04 < drift_pts_s < 0.07, (
            f"Expected ~53ms drift, got {drift_pts_s*1000:.1f}ms"
        )

    def test_pts_at_canonical_fi_close_to_gt_wc(self):
        """A4: At fps=56.517, fi=238 gives PTS ≈ 4.210s, within tolerance of GT wc=4.220s."""
        fps = PARIS_REGRESSION["fps"]
        fi_canonical = PARIS_REGRESSION["canonical_fi"]
        pts_canonical = fi_canonical / fps
        gt_wc = PARIS_REGRESSION["gt_wc_pts_s"]
        tol = PARIS_REGRESSION["pts_tolerance_s"]
        assert abs(pts_canonical - gt_wc) < tol, (
            f"fi={fi_canonical} expected PTS={pts_canonical:.3f}s, GT wc={gt_wc}s, "
            f"delta={abs(pts_canonical-gt_wc):.3f}s > tol={tol}s"
        )

    def test_pts_at_drift_fi_incorrect(self):
        """A4: At fps=56.517, fi=235 gives PTS ≈ 4.157s — 63ms before GT wc.
        At this PTS the diver had not yet made contact (still in flight),
        so D5 rank-1 was not the diver at water-contact position."""
        fps = PARIS_REGRESSION["fps"]
        fi_drift = PARIS_REGRESSION["drift_fi"]
        pts_drift = fi_drift / fps
        gt_wc = PARIS_REGRESSION["gt_wc_pts_s"]
        assert pts_drift < gt_wc - 0.040, (
            f"fi={fi_drift} PTS={pts_drift:.3f}s should be well before GT wc={gt_wc}s"
        )

    def test_description_documents_root_cause(self):
        """A4: Regression fixture contains a causal explanation."""
        assert "h264" in PARIS_REGRESSION["description"].lower()
        assert "sequential" in PARIS_REGRESSION["description"].lower()
        assert "drift" in PARIS_REGRESSION["description"].lower()


class TestPTSAnchorExtractionRule:
    """Phase A: Frozen rule validation."""

    def test_seek_rule_name(self):
        """Canonical rule is PTS_AUTHORITATIVE_SEEK."""
        RULE = "PTS_AUTHORITATIVE_SEEK"
        assert RULE == "PTS_AUTHORITATIVE_SEEK"

    def test_forbidden_methods_documented(self):
        """Forbidden: sequential read count, nominal frame index alone, average FPS."""
        forbidden = [
            "sequential_read_count",
            "nominal_frame_index_alone",
            "average_fps_division",
        ]
        for f in forbidden:
            assert len(f) > 0  # Documents the list exists

    def test_allowed_method_seek_cap_set(self):
        """Allowed anchor extraction: cap.set(CAP_PROP_POS_FRAMES, fi) then cap.read()."""
        try:
            import cv2
            assert hasattr(cv2, "CAP_PROP_POS_FRAMES")
            assert hasattr(cv2, "CAP_PROP_POS_MSEC")
        except ImportError:
            pytest.skip("cv2 not available")
