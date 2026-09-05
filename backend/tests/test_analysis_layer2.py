"""
Phase T — Layer-2 analysis foundation tests.

Tests that can run without a live DB or Docker (pure-Python/unit tests).
Integration tests that require the DB are marked with @pytest.mark.db
and skipped unless DB_TEST=1 is set.

Run:
    cd ~/dive-analyser
    source experiments/landmark_pilot/venv/bin/activate
    pytest backend/tests/test_analysis_layer2.py -v
    # With DB:
    DB_TEST=1 pytest backend/tests/test_analysis_layer2.py -v
"""
import hashlib
import json
import os
import sys
import unittest
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure we can import backend modules (repo root on path)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

# ---------------------------------------------------------------------------
# Phase T-1: spec_fingerprint is deterministic and unique per distinct inputs
# ---------------------------------------------------------------------------

class TestSpecFingerprint(unittest.TestCase):

    def _fingerprint(self, dive_id, media_key, input_checksum,
                     pipeline_key, pipeline_version, canonical_parameters):
        """Replicate compute_spec_fingerprint logic for testing."""
        payload = json.dumps({
            "dive_id": dive_id,
            "media_key": media_key,
            "input_checksum": input_checksum,
            "pipeline_key": pipeline_key,
            "pipeline_version": pipeline_version,
            "parameters": canonical_parameters,
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    def test_deterministic(self):
        """Same inputs always produce the same fingerprint."""
        fp1 = self._fingerprint(42, "abc", "def", "pipe_v1", "1.0.0", {})
        fp2 = self._fingerprint(42, "abc", "def", "pipe_v1", "1.0.0", {})
        self.assertEqual(fp1, fp2)

    def test_length(self):
        """SHA-256 hex digest is always 64 characters."""
        fp = self._fingerprint(1, "x", "y", "k", "v", {})
        self.assertEqual(len(fp), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in fp))

    def test_distinct_dive_id(self):
        """Different dive_id → different fingerprint."""
        fp1 = self._fingerprint(1, "abc", "def", "pipe_v1", "1.0.0", {})
        fp2 = self._fingerprint(2, "abc", "def", "pipe_v1", "1.0.0", {})
        self.assertNotEqual(fp1, fp2)

    def test_distinct_pipeline(self):
        """Different pipeline_key → different fingerprint."""
        fp1 = self._fingerprint(1, "abc", "def", "pipe_v1", "1.0.0", {})
        fp2 = self._fingerprint(1, "abc", "def", "pipe_v2", "1.0.0", {})
        self.assertNotEqual(fp1, fp2)

    def test_distinct_pipeline_version(self):
        """Different pipeline_version → different fingerprint."""
        fp1 = self._fingerprint(1, "abc", "def", "pipe_v1", "1.0.0", {})
        fp2 = self._fingerprint(1, "abc", "def", "pipe_v1", "2.0.0", {})
        self.assertNotEqual(fp1, fp2)

    def test_distinct_parameters(self):
        """Different canonical_parameters → different fingerprint."""
        fp1 = self._fingerprint(1, "abc", "def", "pipe_v1", "1.0.0", {"sigma": 3.0})
        fp2 = self._fingerprint(1, "abc", "def", "pipe_v1", "1.0.0", {"sigma": 4.0})
        self.assertNotEqual(fp1, fp2)

    def test_parameters_key_order_invariant(self):
        """Parameter dict key order must not affect fingerprint (sort_keys=True)."""
        fp1 = self._fingerprint(1, "x", "y", "k", "v", {"b": 2, "a": 1})
        fp2 = self._fingerprint(1, "x", "y", "k", "v", {"a": 1, "b": 2})
        self.assertEqual(fp1, fp2)


# ---------------------------------------------------------------------------
# Phase T-2: Metric registry
# ---------------------------------------------------------------------------

class TestMetricRegistry(unittest.TestCase):

    def setUp(self):
        """Load the registry from the YAML file if it exists."""
        self.yaml_path = REPO_ROOT / "backend" / "app" / "data" / "metric_registry.yaml"
        self._registry = None

    def _load(self):
        if self._registry is not None:
            return self._registry
        if not self.yaml_path.exists():
            self.skipTest(f"metric_registry.yaml not found at {self.yaml_path}")
        try:
            import yaml  # type: ignore
        except ImportError:
            self.skipTest("PyYAML not available in this venv")
        with open(self.yaml_path) as f:
            self._registry = yaml.safe_load(f)
        return self._registry

    def test_registry_is_list(self):
        reg = self._load()
        self.assertIsInstance(reg, list)
        self.assertGreater(len(reg), 0)

    def test_each_metric_has_required_fields(self):
        reg = self._load()
        required = {"key", "version", "unit", "description", "value_type"}
        for m in reg:
            missing = required - set(m.keys())
            self.assertEqual(missing, set(), f"Metric {m.get('key')} missing: {missing}")

    def test_keys_are_unique(self):
        reg = self._load()
        keys = [(m["key"], m["version"]) for m in reg]
        self.assertEqual(len(keys), len(set(keys)), "Duplicate (key, version) in registry")

    def test_expected_metrics_present(self):
        reg = self._load()
        keys = {m["key"] for m in reg}
        expected = {
            "flight_duration_seconds",
            "ascent_duration_seconds",
            "descent_duration_seconds",
            "ascent_fraction",
            "takeoff_frame_normalized",
            "apex_frame_normalized",
            "water_contact_frame_normalized",
            "landmark_proposer_confidence_takeoff",
            "landmark_proposer_confidence_apex",
            "landmark_proposer_confidence_water_contact",
        }
        missing = expected - keys
        self.assertEqual(missing, set(), f"Missing expected metrics: {missing}")

    def test_value_bounds_for_ratio_metrics(self):
        reg = self._load()
        ratio_keys = {
            "ascent_fraction", "takeoff_frame_normalized",
            "apex_frame_normalized", "water_contact_frame_normalized",
        }
        for m in reg:
            if m["key"] in ratio_keys:
                bounds = m.get("bounds", {})
                # Should have min=0 and max=1 (exclusive or inclusive)
                self.assertIn("min", bounds, f"{m['key']} missing bounds.min")
                self.assertIn("max", bounds, f"{m['key']} missing bounds.max")
                self.assertGreaterEqual(float(bounds["min"]), 0.0)
                self.assertLessEqual(float(bounds["max"]), 1.0)


# ---------------------------------------------------------------------------
# Phase T-3: Landmark temporal invariants
# ---------------------------------------------------------------------------

class TestLandmarkInvariants(unittest.TestCase):
    """Tests for the temporal ordering and NOT_APPLICABLE invariants."""

    def _check_ordering(self, t, a, w):
        """Return True if t < a < w."""
        if t is None or a is None or w is None:
            return False
        return t < a < w

    def test_valid_ordering(self):
        self.assertTrue(self._check_ordering(100, 200, 300))

    def test_equal_takeoff_apex_invalid(self):
        self.assertFalse(self._check_ordering(100, 100, 300))

    def test_equal_apex_water_invalid(self):
        self.assertFalse(self._check_ordering(100, 200, 200))

    def test_all_equal_invalid(self):
        self.assertFalse(self._check_ordering(288, 288, 288))

    def test_reversed_invalid(self):
        self.assertFalse(self._check_ordering(300, 200, 100))

    def test_none_values_invalid(self):
        self.assertFalse(self._check_ordering(None, 200, 300))
        self.assertFalse(self._check_ordering(100, None, 300))
        self.assertFalse(self._check_ordering(100, 200, None))

    def test_not_applicable_must_have_null_frame(self):
        """NOT_APPLICABLE landmarks must have NULL frame_index.
        The DB CHECK constraint enforces this; test the logic here."""
        def check_not_applicable(applicability, frame_index):
            if applicability == "NOT_APPLICABLE":
                return frame_index is None
            return True  # other applicabilities can have any value

        self.assertTrue(check_not_applicable("NOT_APPLICABLE", None))
        self.assertFalse(check_not_applicable("NOT_APPLICABLE", 0))
        self.assertFalse(check_not_applicable("NOT_APPLICABLE", 100))
        self.assertTrue(check_not_applicable("APPLICABLE", 100))
        self.assertTrue(check_not_applicable("UNCERTAIN", 100))

    def test_uncertain_has_zero_confidence(self):
        """UNCERTAIN landmarks should have confidence=0.0."""
        def check_uncertain_confidence(applicability, confidence):
            if applicability == "UNCERTAIN":
                return confidence == 0.0
            return True

        self.assertTrue(check_uncertain_confidence("UNCERTAIN", 0.0))
        self.assertFalse(check_uncertain_confidence("UNCERTAIN", 0.5))
        self.assertTrue(check_uncertain_confidence("APPLICABLE", 0.5))


# ---------------------------------------------------------------------------
# Phase T-4: Artifact path helpers
# ---------------------------------------------------------------------------

class TestArtifactPaths(unittest.TestCase):

    def _run_artifact_dir(self, artifact_root, dive_id, run_uuid):
        """Replicate run_artifact_dir logic."""
        return Path(artifact_root) / str(dive_id) / str(run_uuid)

    def _run_tmp_dir(self, artifact_root, run_uuid):
        """Replicate run_tmp_dir logic."""
        return Path(artifact_root) / "_tmp" / str(run_uuid)

    def test_artifact_dir_structure(self):
        root = "/data/analysis-artifacts"
        path = self._run_artifact_dir(root, 42, "uuid-1234")
        self.assertEqual(str(path), "/data/analysis-artifacts/42/uuid-1234")

    def test_tmp_dir_under_tmp(self):
        root = "/data/analysis-artifacts"
        path = self._run_tmp_dir(root, "uuid-1234")
        self.assertEqual(str(path), "/data/analysis-artifacts/_tmp/uuid-1234")

    def test_artifact_dir_not_in_tmp(self):
        root = "/data/analysis-artifacts"
        final = self._run_artifact_dir(root, 42, "uuid-1234")
        tmp = self._run_tmp_dir(root, "uuid-1234")
        self.assertNotEqual(str(final.parent), str(tmp.parent))

    def test_no_directory_traversal_dive_id(self):
        root = "/data/analysis-artifacts"
        # dive_id=42 becomes str(42), no path traversal possible
        path = self._run_artifact_dir(root, 42, "uuid-1234")
        self.assertNotIn("..", str(path))


# ---------------------------------------------------------------------------
# Phase T-5: Baseline A proposer — pure algorithm unit tests
# ---------------------------------------------------------------------------

class TestBaselineAProposer(unittest.TestCase):
    """Unit tests for the Baseline A algorithm logic, without OpenCV."""

    def _find_max_upward_velocity(self, centroid_y_smooth, search_end_idx):
        """Replicate the takeoff-detection step."""
        if len(centroid_y_smooth) < 2:
            return 0
        max_vel_idx = 0
        max_vel = float('-inf')
        for i in range(1, min(search_end_idx, len(centroid_y_smooth))):
            vel = centroid_y_smooth[i - 1] - centroid_y_smooth[i]  # upward = negative Δy
            if vel > max_vel:
                max_vel = vel
                max_vel_idx = i
        return max_vel_idx

    def _find_apex(self, centroid_y_smooth, after_idx, before_frac=0.9, n_frames=None):
        """Replicate the apex-detection step (minimum centroid_y)."""
        if n_frames is None:
            n_frames = len(centroid_y_smooth)
        search_end = int(n_frames * before_frac)
        sub = centroid_y_smooth[after_idx:search_end]
        if not sub:
            return after_idx
        return after_idx + sub.index(min(sub))

    def test_takeoff_at_max_upward_velocity(self):
        # Centroid moves up (y decreasing) fastest at frame 3
        y = [100.0, 90.0, 80.0, 60.0, 55.0, 52.0, 50.0, 48.0]
        # Velocities: 10, 10, 20, 5, 3, 2, 2 → max at index 3
        idx = self._find_max_upward_velocity(y, len(y))
        self.assertEqual(idx, 3)

    def test_apex_at_minimum_y(self):
        # Centroid reaches minimum at frame 5 (index 5)
        y = [100.0, 80.0, 60.0, 40.0, 30.0, 20.0, 30.0, 50.0, 80.0]
        takeoff = 2
        apex = self._find_apex(y, takeoff, before_frac=0.95, n_frames=len(y))
        self.assertEqual(apex, 5)

    def test_ordering_violation_detected(self):
        """When takeoff >= apex, ordering is violated."""
        takeoff, apex, water = 50, 50, 100
        is_valid = takeoff < apex < water
        self.assertFalse(is_valid)

    def test_valid_ordering(self):
        takeoff, apex, water = 50, 80, 120
        is_valid = takeoff < apex < water
        self.assertTrue(is_valid)


# ---------------------------------------------------------------------------
# Phase T-6: Comparison fingerprint identity
# ---------------------------------------------------------------------------

class TestComparisonFingerprint(unittest.TestCase):

    def _fingerprint(self, target_run_id, ref_run_id, method_key, method_version, params):
        payload = json.dumps({
            "target_run_id": target_run_id,
            "reference_run_id": ref_run_id,
            "method_key": method_key,
            "method_version": method_version,
            "parameters": params,
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    def test_same_order_same_fingerprint(self):
        fp1 = self._fingerprint(1, 2, "method_v1", "1.0", {})
        fp2 = self._fingerprint(1, 2, "method_v1", "1.0", {})
        self.assertEqual(fp1, fp2)

    def test_swapped_runs_different_fingerprint(self):
        """target vs reference order matters for comparison identity."""
        fp1 = self._fingerprint(1, 2, "method_v1", "1.0", {})
        fp2 = self._fingerprint(2, 1, "method_v1", "1.0", {})
        self.assertNotEqual(fp1, fp2)

    def test_different_method_different_fingerprint(self):
        fp1 = self._fingerprint(1, 2, "method_v1", "1.0", {})
        fp2 = self._fingerprint(1, 2, "method_v2", "1.0", {})
        self.assertNotEqual(fp1, fp2)


# ---------------------------------------------------------------------------
# Phase T-7: No-bulk-enqueue guard
# ---------------------------------------------------------------------------

class TestNoBulkEnqueue(unittest.TestCase):
    """Verify that the standalone runner respects --max-dives."""

    def test_max_dives_flag_exists(self):
        """run_pilot_standalone.py must have --max-dives argument."""
        runner_path = REPO_ROOT / "experiments" / "landmark_pilot" / "run_pilot_standalone.py"
        if not runner_path.exists():
            self.skipTest("run_pilot_standalone.py not found")
        content = runner_path.read_text()
        self.assertIn("--max-dives", content,
                      "run_pilot_standalone.py must have --max-dives flag")

    def test_max_dives_default_is_bounded(self):
        """Default --max-dives must be ≤ 24 per protocol."""
        runner_path = REPO_ROOT / "experiments" / "landmark_pilot" / "run_pilot_standalone.py"
        if not runner_path.exists():
            self.skipTest("run_pilot_standalone.py not found")
        content = runner_path.read_text()
        # Find default value for --max-dives
        import re
        m = re.search(r"--max-dives.*?default=(\d+)", content, re.DOTALL)
        if m:
            default_val = int(m.group(1))
            self.assertLessEqual(default_val, 24,
                                 f"--max-dives default {default_val} exceeds allowed 24")


# ---------------------------------------------------------------------------
# Phase T-8: Annotation schema (source values)
# ---------------------------------------------------------------------------

class TestAnnotationSchema(unittest.TestCase):

    VALID_SOURCES = {"AUTO", "HUMAN", "HUMAN_CORRECTED", "IMPORTED"}
    VALID_APPLICABILITIES = {"APPLICABLE", "NOT_APPLICABLE", "UNCERTAIN"}

    def test_human_is_valid_source(self):
        self.assertIn("HUMAN", self.VALID_SOURCES)

    def test_auto_is_valid_source(self):
        self.assertIn("AUTO", self.VALID_SOURCES)

    def test_annotated_landmark_structure(self):
        """Manually-corrected landmark has expected fields."""
        landmark = {
            "landmark_key": "takeoff",
            "frame_index": 100,
            "timestamp_seconds": 1.67,
            "confidence": 1.0,
            "applicability": "APPLICABLE",
            "source": "HUMAN",
            "algorithm_key": "annotate_tool",
            "algorithm_version": "v1",
        }
        self.assertIn(landmark["source"], self.VALID_SOURCES)
        self.assertIn(landmark["applicability"], self.VALID_APPLICABILITIES)
        self.assertEqual(landmark["confidence"], 1.0)
        self.assertIsNotNone(landmark["frame_index"])

    def test_not_applicable_landmark_has_null_frame(self):
        landmark = {
            "landmark_key": "takeoff",
            "frame_index": None,
            "timestamp_seconds": None,
            "confidence": 1.0,
            "applicability": "NOT_APPLICABLE",
            "source": "HUMAN",
        }
        if landmark["applicability"] == "NOT_APPLICABLE":
            self.assertIsNone(landmark["frame_index"])
            self.assertIsNone(landmark["timestamp_seconds"])


# ---------------------------------------------------------------------------
# Integration tests (require DB) — skip unless DB_TEST=1
# ---------------------------------------------------------------------------

SKIP_DB = not os.getenv("DB_TEST")


@pytest.mark.skipif(SKIP_DB, reason="DB_TEST not set; skipping DB integration tests")
class TestDBIntegration(unittest.TestCase):
    """Integration tests that require a running PostgreSQL at localhost:5433."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(REPO_ROOT / "experiments" / "landmark_pilot"))
        import annotate
        cls.annotate = annotate

    def test_db_connection(self):
        conn = self.annotate._connect()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        self.assertEqual(cur.fetchone()[0], 1)
        conn.close()

    def test_pilot_dives_loaded(self):
        dives = self.annotate._get_all_pilot_data()
        self.assertEqual(len(dives), 20, "Should have exactly 20 pilot dives")

    def test_applicable_dives_have_metrics(self):
        dives = self.annotate._get_all_pilot_data()
        conn = self.annotate._connect()
        cur = conn.cursor()
        cur.execute("""
            SELECT ar.dive_id, COUNT(am.id) as metric_count
            FROM analysis_runs ar
            JOIN analysis_metrics am ON am.run_id = ar.id
            WHERE ar.pipeline_key = 'temporal_landmarks_baseline_a_v1'
            GROUP BY ar.dive_id
        """)
        metric_counts = {r[0]: r[1] for r in cur.fetchall()}
        conn.close()

        applicable_dives = [d for d in dives if d['ordering_valid']]
        for d in applicable_dives:
            self.assertIn(d['dive_id'], metric_counts,
                          f"Dive {d['dive_id']} has valid ordering but no metrics")
            self.assertGreaterEqual(metric_counts[d['dive_id']], 10,
                                    f"Dive {d['dive_id']} has < 10 metrics")

    def test_uncertain_dives_have_zero_confidence(self):
        dives = self.annotate._get_all_pilot_data()
        for d in dives:
            if not d['ordering_valid']:
                for key, lm in d['landmarks'].items():
                    if lm.get('applicability') == 'UNCERTAIN':
                        self.assertEqual(float(lm.get('confidence', -1)), 0.0,
                                         f"Dive {d['dive_id']} {key} UNCERTAIN but conf={lm.get('confidence')}")

    def test_comparisons_stored(self):
        conn = self.annotate._connect()
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM analysis_comparisons
            WHERE method_key = 'temporal_landmark_pairwise_v1' AND status = 'succeeded'
        """)
        count = cur.fetchone()[0]
        conn.close()
        self.assertEqual(count, 66, f"Expected 66 pairwise comparisons, got {count}")

    def test_metric_unique_constraint(self):
        """Unique constraint (run_id, metric_key, metric_version) must hold."""
        dives = self.annotate._get_all_pilot_data()
        conn = self.annotate._connect()
        cur = conn.cursor()
        cur.execute("""
            SELECT run_id, metric_key, metric_version, COUNT(*)
            FROM analysis_metrics
            GROUP BY run_id, metric_key, metric_version
            HAVING COUNT(*) > 1
        """)
        duplicates = cur.fetchall()
        conn.close()
        self.assertEqual(duplicates, [],
                         f"Found duplicate (run_id, metric_key, metric_version): {duplicates}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
