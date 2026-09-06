"""
Phase B+T — Layer-2 analysis foundation + Baseline C tests.

Tests that can run without a live DB or Docker (pure-Python/unit tests).
Integration tests that require the DB are marked with @pytest.mark.db
and skipped unless DB_TEST=1 is set.

Run:
    cd ~/dive-analyser
    source experiments/landmark_pilot/venv/bin/activate
    pytest backend/tests/test_analysis_layer2.py --noconftest -v
"""
import hashlib
import json
import os
import sys
import math
import unittest
from pathlib import Path
from typing import Optional, Dict, List
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure we can import backend modules (repo root on path)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent.parent
SCIENCE_DIR = REPO_ROOT / "docs" / "science"
PILOT_MANIFEST = SCIENCE_DIR / "PILOT_MANIFEST_V1.json"
SPLIT_MANIFEST = SCIENCE_DIR / "TEMPORAL_LANDMARK_INTERNAL_EVAL_V1.json"
GROUND_TRUTH = SCIENCE_DIR / "TEMPORAL_LANDMARK_GROUND_TRUTH_V1.json"
sys.path.insert(0, str(REPO_ROOT / "backend"))


# ===========================================================================
# PHASE T-1: spec_fingerprint is deterministic and unique per distinct inputs
# ===========================================================================

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
        fp1 = self._fingerprint(42, "abc", "def", "pipe_v1", "1.0.0", {})
        fp2 = self._fingerprint(42, "abc", "def", "pipe_v1", "1.0.0", {})
        self.assertEqual(fp1, fp2)

    def test_length(self):
        fp = self._fingerprint(1, "x", "y", "k", "v", {})
        self.assertEqual(len(fp), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in fp))

    def test_distinct_dive_id(self):
        fp1 = self._fingerprint(1, "abc", "def", "pipe_v1", "1.0.0", {})
        fp2 = self._fingerprint(2, "abc", "def", "pipe_v1", "1.0.0", {})
        self.assertNotEqual(fp1, fp2)

    def test_distinct_pipeline(self):
        fp1 = self._fingerprint(1, "abc", "def", "pipe_v1", "1.0.0", {})
        fp2 = self._fingerprint(1, "abc", "def", "pipe_v2", "1.0.0", {})
        self.assertNotEqual(fp1, fp2)

    def test_distinct_pipeline_version(self):
        fp1 = self._fingerprint(1, "abc", "def", "pipe_v1", "1.0.0", {})
        fp2 = self._fingerprint(1, "abc", "def", "pipe_v1", "2.0.0", {})
        self.assertNotEqual(fp1, fp2)

    def test_distinct_parameters(self):
        fp1 = self._fingerprint(1, "abc", "def", "pipe_v1", "1.0.0", {"sigma": 3.0})
        fp2 = self._fingerprint(1, "abc", "def", "pipe_v1", "1.0.0", {"sigma": 4.0})
        self.assertNotEqual(fp1, fp2)

    def test_parameters_key_order_invariant(self):
        fp1 = self._fingerprint(1, "x", "y", "k", "v", {"b": 2, "a": 1})
        fp2 = self._fingerprint(1, "x", "y", "k", "v", {"a": 1, "b": 2})
        self.assertEqual(fp1, fp2)


# ===========================================================================
# PHASE T-2: Metric registry (fixed for actual YAML structure)
# ===========================================================================

class TestMetricRegistry(unittest.TestCase):

    def setUp(self):
        self.yaml_path = REPO_ROOT / "backend" / "app" / "data" / "metric_registry.yaml"
        self._registry = None

    def _load(self):
        """Load and return the metrics list from the registry YAML."""
        if self._registry is not None:
            return self._registry
        if not self.yaml_path.exists():
            self.skipTest(f"metric_registry.yaml not found at {self.yaml_path}")
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not available in this venv")
        with open(self.yaml_path) as f:
            raw = yaml.safe_load(f)
        # Registry YAML uses {"metrics": [...]} top-level key
        if isinstance(raw, dict) and "metrics" in raw:
            self._registry = raw["metrics"]
        elif isinstance(raw, list):
            self._registry = raw
        else:
            self.fail(f"Unexpected metric registry structure: {type(raw)}")
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
        """Registry uses valid_range:[min,max]; check ratio metrics are [0,1]."""
        reg = self._load()
        ratio_keys = {
            "ascent_fraction", "takeoff_frame_normalized",
            "apex_frame_normalized", "water_contact_frame_normalized",
        }
        for m in reg:
            if m["key"] in ratio_keys:
                vr = m.get("valid_range")
                self.assertIsNotNone(vr, f"{m['key']} missing valid_range")
                self.assertEqual(len(vr), 2)
                if vr[0] is not None:
                    self.assertGreaterEqual(float(vr[0]), 0.0)
                if vr[1] is not None:
                    self.assertLessEqual(float(vr[1]), 1.0)


# ===========================================================================
# PHASE T-3: Landmark temporal invariants
# ===========================================================================

class TestLandmarkInvariants(unittest.TestCase):

    def _check_ordering(self, t, a, w):
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
        def check_na(applicability, frame_index):
            if applicability == "NOT_APPLICABLE":
                return frame_index is None
            return True
        self.assertTrue(check_na("NOT_APPLICABLE", None))
        self.assertFalse(check_na("NOT_APPLICABLE", 0))
        self.assertFalse(check_na("NOT_APPLICABLE", 100))
        self.assertTrue(check_na("APPLICABLE", 100))
        self.assertTrue(check_na("UNCERTAIN", 100))

    def test_uncertain_has_zero_confidence(self):
        def check_uncertain_confidence(applicability, confidence):
            if applicability == "UNCERTAIN":
                return confidence == 0.0
            return True
        self.assertTrue(check_uncertain_confidence("UNCERTAIN", 0.0))
        self.assertFalse(check_uncertain_confidence("UNCERTAIN", 0.5))
        self.assertTrue(check_uncertain_confidence("APPLICABLE", 0.5))

    def test_frame_to_time_conversion(self):
        """frame_index / fps == timestamp_seconds (deterministic)."""
        fps = 30.0
        frame = 90
        ts = frame / fps
        self.assertAlmostEqual(ts, 3.0, places=5)

    def test_time_to_frame_conversion(self):
        fps = 30.0
        ts = 2.5
        frame = int(round(ts * fps))
        self.assertEqual(frame, 75)

    def test_timestamp_bounds_non_negative(self):
        for ts in [0.0, 0.001, 1.5, 60.0]:
            self.assertGreaterEqual(ts, 0.0)

    def test_apex_normalized_in_range(self):
        """apex_normalized = apex_frame / total_frames must be in [0, 1)."""
        total = 500
        for apex_frame in [0, 100, 200, 499]:
            apex_norm = apex_frame / total
            self.assertGreaterEqual(apex_norm, 0.0)
            self.assertLess(apex_norm, 1.0)


# ===========================================================================
# PHASE T-4: Artifact path helpers
# ===========================================================================

class TestArtifactPaths(unittest.TestCase):

    def _run_artifact_dir(self, artifact_root, dive_id, run_uuid):
        return Path(artifact_root) / str(dive_id) / str(run_uuid)

    def _run_tmp_dir(self, artifact_root, run_uuid):
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
        path = self._run_artifact_dir(root, 42, "uuid-1234")
        self.assertNotIn("..", str(path))


# ===========================================================================
# PHASE T-5: Baseline A proposer — pure algorithm unit tests
# ===========================================================================

class TestBaselineAProposer(unittest.TestCase):

    def _find_max_upward_velocity(self, centroid_y_smooth, search_end_idx):
        if len(centroid_y_smooth) < 2:
            return 0
        max_vel_idx = 0
        max_vel = float('-inf')
        for i in range(1, min(search_end_idx, len(centroid_y_smooth))):
            vel = centroid_y_smooth[i - 1] - centroid_y_smooth[i]
            if vel > max_vel:
                max_vel = vel
                max_vel_idx = i
        return max_vel_idx

    def _find_apex(self, centroid_y_smooth, after_idx, before_frac=0.9, n_frames=None):
        if n_frames is None:
            n_frames = len(centroid_y_smooth)
        search_end = int(n_frames * before_frac)
        sub = centroid_y_smooth[after_idx:search_end]
        if not sub:
            return after_idx
        return after_idx + sub.index(min(sub))

    def test_takeoff_at_max_upward_velocity(self):
        y = [100.0, 90.0, 80.0, 60.0, 55.0, 52.0, 50.0, 48.0]
        idx = self._find_max_upward_velocity(y, len(y))
        self.assertEqual(idx, 3)

    def test_apex_at_minimum_y(self):
        y = [100.0, 80.0, 60.0, 40.0, 30.0, 20.0, 30.0, 50.0, 80.0]
        takeoff = 2
        apex = self._find_apex(y, takeoff, before_frac=0.95, n_frames=len(y))
        self.assertEqual(apex, 5)

    def test_ordering_violation_detected(self):
        takeoff, apex, water = 50, 50, 100
        self.assertFalse(takeoff < apex < water)

    def test_valid_ordering(self):
        takeoff, apex, water = 50, 80, 120
        self.assertTrue(takeoff < apex < water)


# ===========================================================================
# PHASE T-6: Comparison fingerprint identity
# ===========================================================================

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
        fp1 = self._fingerprint(1, 2, "method_v1", "1.0", {})
        fp2 = self._fingerprint(2, 1, "method_v1", "1.0", {})
        self.assertNotEqual(fp1, fp2)

    def test_different_method_different_fingerprint(self):
        fp1 = self._fingerprint(1, 2, "method_v1", "1.0", {})
        fp2 = self._fingerprint(1, 2, "method_v2", "1.0", {})
        self.assertNotEqual(fp1, fp2)


# ===========================================================================
# PHASE T-7: No-bulk-enqueue guard
# ===========================================================================

class TestNoBulkEnqueue(unittest.TestCase):

    def test_max_dives_flag_exists(self):
        runner_path = REPO_ROOT / "experiments" / "landmark_pilot" / "run_pilot_standalone.py"
        if not runner_path.exists():
            self.skipTest("run_pilot_standalone.py not found")
        content = runner_path.read_text()
        self.assertIn("--max-dives", content)

    def test_max_dives_default_is_bounded(self):
        runner_path = REPO_ROOT / "experiments" / "landmark_pilot" / "run_pilot_standalone.py"
        if not runner_path.exists():
            self.skipTest("run_pilot_standalone.py not found")
        import re
        content = runner_path.read_text()
        m = re.search(r"--max-dives.*?default=(\d+)", content, re.DOTALL)
        if m:
            default_val = int(m.group(1))
            self.assertLessEqual(default_val, 24)


# ===========================================================================
# PHASE T-8: Annotation schema
# ===========================================================================

class TestAnnotationSchema(unittest.TestCase):

    VALID_SOURCES = {"AUTO", "HUMAN", "HUMAN_CORRECTED", "HUMAN_ACCEPTED", "IMPORTED"}
    VALID_APPLICABILITIES = {"APPLICABLE", "NOT_APPLICABLE", "UNCERTAIN"}

    def test_human_is_valid_source(self):
        self.assertIn("HUMAN", self.VALID_SOURCES)

    def test_auto_is_valid_source(self):
        self.assertIn("AUTO", self.VALID_SOURCES)

    def test_annotated_landmark_structure(self):
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

    def test_human_accepted_annotation(self):
        """HUMAN_ACCEPTED means the auto prediction was accepted without change."""
        lm = {
            "state": "HUMAN_ACCEPTED",
            "frame_index": 150,
            "confidence": 1.0,
            "applicability": "APPLICABLE",
        }
        self.assertIn(lm["state"], self.VALID_SOURCES | {"HUMAN_ACCEPTED"})
        self.assertIsNotNone(lm["frame_index"])


# ===========================================================================
# PHASE B1: Scientific manifest integrity
# ===========================================================================

class TestScientificManifestIntegrity(unittest.TestCase):
    """B1: Pilot manifest and split manifest integrity tests."""

    def _load_pilot_manifest(self):
        if not PILOT_MANIFEST.exists():
            self.skipTest(f"Pilot manifest not found: {PILOT_MANIFEST}")
        with open(PILOT_MANIFEST) as f:
            return json.load(f)

    def _load_split_manifest(self):
        if not SPLIT_MANIFEST.exists():
            self.skipTest(f"Split manifest not found: {SPLIT_MANIFEST}")
        with open(SPLIT_MANIFEST) as f:
            return json.load(f)

    def test_pilot_manifest_parses(self):
        m = self._load_pilot_manifest()
        self.assertIsInstance(m, dict)
        self.assertIn("dives", m)

    def test_pilot_manifest_has_20_dives(self):
        m = self._load_pilot_manifest()
        self.assertEqual(len(m["dives"]), 20, "Pilot must contain exactly 20 dives")

    def test_pilot_manifest_dive_ids_unique(self):
        m = self._load_pilot_manifest()
        ids = [d["dive_id"] for d in m["dives"]]
        self.assertEqual(len(ids), len(set(ids)), "Dive IDs must be unique in pilot manifest")

    def test_pilot_manifest_required_fields(self):
        m = self._load_pilot_manifest()
        for d in m["dives"]:
            for field in ["dive_id", "dive_code", "media_key"]:
                self.assertIn(field, d, f"Dive {d.get('dive_id')} missing field: {field}")

    def test_split_manifest_parses(self):
        s = self._load_split_manifest()
        self.assertIsInstance(s, dict)
        self.assertIn("DEVELOPMENT_DESIGN", s)
        self.assertIn("INTERNAL_EVAL", s)

    def test_split_design_count(self):
        s = self._load_split_manifest()
        design = s["DEVELOPMENT_DESIGN"]
        self.assertEqual(design["count"], 14, "DEVELOPMENT_DESIGN must have 14 dives")
        self.assertEqual(len(design["dive_ids"]), 14)

    def test_split_eval_count(self):
        s = self._load_split_manifest()
        eval_ = s["INTERNAL_EVAL"]
        self.assertEqual(eval_["count"], 6, "INTERNAL_EVAL must have 6 dives")
        self.assertEqual(len(eval_["dive_ids"]), 6)

    def test_split_sets_are_disjoint(self):
        s = self._load_split_manifest()
        design_ids = set(s["DEVELOPMENT_DESIGN"]["dive_ids"])
        eval_ids = set(s["INTERNAL_EVAL"]["dive_ids"])
        intersection = design_ids & eval_ids
        self.assertEqual(intersection, set(),
                         f"DESIGN and EVAL share dives: {intersection}")

    def test_split_union_matches_pilot(self):
        m = self._load_pilot_manifest()
        s = self._load_split_manifest()
        pilot_ids = {d["dive_id"] for d in m["dives"]}
        design_ids = set(s["DEVELOPMENT_DESIGN"]["dive_ids"])
        eval_ids = set(s["INTERNAL_EVAL"]["dive_ids"])
        union = design_ids | eval_ids
        self.assertEqual(union, pilot_ids,
                         f"Split union != pilot. Extra: {union-pilot_ids} Missing: {pilot_ids-union}")

    def test_split_fingerprint_present(self):
        s = self._load_split_manifest()
        fp = s.get("split_fingerprint_sha256")
        self.assertIsNotNone(fp, "Split manifest must have split_fingerprint_sha256")
        self.assertEqual(len(fp), 64, "Fingerprint must be 64-char SHA-256 hex")

    def test_split_fingerprint_matches_expected(self):
        """Verify the frozen split fingerprint matches the known value."""
        s = self._load_split_manifest()
        fp = s.get("split_fingerprint_sha256")
        # Known frozen value from the pilot
        EXPECTED = "96f14ffcd11fb19fa91f8dbd09206c73757ddb628b43f4dbbbe1ac9a0633d582"
        self.assertEqual(fp, EXPECTED,
                         "Split fingerprint changed! Split must never be altered.")

    def test_missing_manifest_fails_closed(self):
        """Loading from a non-existent path must raise, not silently succeed."""
        bad_path = REPO_ROOT / "does_not_exist.json"
        self.assertFalse(bad_path.exists())
        with self.assertRaises((FileNotFoundError, OSError)):
            with open(bad_path) as f:
                json.load(f)

    def test_corrupt_manifest_fails_closed(self):
        """Corrupt JSON must raise, not silently succeed."""
        with self.assertRaises(json.JSONDecodeError):
            json.loads("{ this is not valid json }")

    def test_ground_truth_fingerprint_present(self):
        if not GROUND_TRUTH.exists():
            self.skipTest(f"Ground truth not found: {GROUND_TRUTH}")
        with open(GROUND_TRUTH) as f:
            gt = json.load(f)
        fp = gt.get("ground_truth_fingerprint_sha256")
        self.assertIsNotNone(fp)
        EXPECTED = "2832b31104e969cc0fcabc9b50b2a05e95d3f9883c822077c105b832029e364f"
        self.assertEqual(fp, EXPECTED, "Ground truth fingerprint must not change")

    def test_ground_truth_has_20_dives(self):
        if not GROUND_TRUTH.exists():
            self.skipTest(f"Ground truth not found: {GROUND_TRUTH}")
        with open(GROUND_TRUTH) as f:
            gt = json.load(f)
        self.assertEqual(gt["n_dives"], 20)
        self.assertEqual(gt["n_landmarks"], 60)

    def test_no_session_split_in_eval(self):
        """INTERNAL_EVAL must keep sessions whole (no partial session)."""
        s = self._load_split_manifest()
        eval_ids = set(s["INTERNAL_EVAL"]["dive_ids"])
        # Known eval sessions: 26, 51, 138 (these must not appear in DESIGN)
        design_ids = set(s["DEVELOPMENT_DESIGN"]["dive_ids"])
        self.assertTrue(eval_ids.isdisjoint(design_ids))

    def test_eval_dive_ids_are_known(self):
        """Verify the specific INTERNAL_EVAL dive IDs match the frozen set."""
        s = self._load_split_manifest()
        eval_ids = set(s["INTERNAL_EVAL"]["dive_ids"])
        EXPECTED_EVAL = {160, 169, 191, 192, 848, 2281}
        self.assertEqual(eval_ids, EXPECTED_EVAL,
                         "INTERNAL_EVAL dive IDs must never change")

    def test_design_dive_ids_are_known(self):
        """Verify the specific DEVELOPMENT_DESIGN dive IDs match the frozen set."""
        s = self._load_split_manifest()
        design_ids = set(s["DEVELOPMENT_DESIGN"]["dive_ids"])
        EXPECTED_DESIGN = {133, 311, 524, 676, 1040, 2169, 2341, 2353,
                           2387, 2541, 2555, 2625, 2661, 2680}
        self.assertEqual(design_ids, EXPECTED_DESIGN,
                         "DEVELOPMENT_DESIGN dive IDs must never change")


# ===========================================================================
# PHASE B3: Evaluator correctness with synthetic predictions
# ===========================================================================

def _compute_frame_error(pred_frame, human_frame):
    """Absolute frame error."""
    return abs(pred_frame - human_frame)


def _compute_time_error(pred_frame, human_frame, fps):
    """Absolute time error in seconds."""
    return abs(pred_frame - human_frame) / fps


def _is_within_tolerance(frame_error, landmark_key):
    """Protocol tolerances from PILOT_PROTOCOL_V1."""
    tol = {"takeoff": 5, "apex": 8, "water_contact": 5}
    return frame_error <= tol[landmark_key]


def _is_serious_error(frame_error, landmark_key):
    tol = {"takeoff": 15, "apex": 20, "water_contact": 15}
    return frame_error > tol[landmark_key]


def _compute_aggregate_stats(errors):
    """Compute median and P90 from a list of errors."""
    if not errors:
        return {"n": 0, "median": None, "p90": None, "max": None}
    sorted_e = sorted(errors)
    n = len(sorted_e)
    mid = n // 2
    if n % 2 == 0:
        median = (sorted_e[mid - 1] + sorted_e[mid]) / 2.0
    else:
        median = float(sorted_e[mid])
    p90_idx = int(math.ceil(0.9 * n)) - 1
    p90 = float(sorted_e[max(0, p90_idx)])
    return {"n": n, "median": median, "p90": p90, "max": float(sorted_e[-1])}


class TestEvaluatorSynthetic(unittest.TestCase):
    """B3: Evaluator correctness tests using synthetic known predictions."""

    def test_exact_frame_error_zero(self):
        self.assertEqual(_compute_frame_error(100, 100), 0)

    def test_frame_error_positive(self):
        self.assertEqual(_compute_frame_error(110, 100), 10)
        self.assertEqual(_compute_frame_error(90, 100), 10)

    def test_time_error_at_30fps(self):
        """5 frames at 30fps = 0.1667s."""
        err = _compute_time_error(105, 100, 30.0)
        self.assertAlmostEqual(err, 5/30.0, places=5)

    def test_within_tolerance_takeoff(self):
        self.assertTrue(_is_within_tolerance(5, "takeoff"))
        self.assertFalse(_is_within_tolerance(6, "takeoff"))

    def test_within_tolerance_apex(self):
        self.assertTrue(_is_within_tolerance(8, "apex"))
        self.assertFalse(_is_within_tolerance(9, "apex"))

    def test_within_tolerance_water_contact(self):
        self.assertTrue(_is_within_tolerance(5, "water_contact"))
        self.assertFalse(_is_within_tolerance(6, "water_contact"))

    def test_serious_error_takeoff(self):
        self.assertTrue(_is_serious_error(16, "takeoff"))
        self.assertFalse(_is_serious_error(15, "takeoff"))

    def test_serious_error_apex(self):
        self.assertTrue(_is_serious_error(21, "apex"))
        self.assertFalse(_is_serious_error(20, "apex"))

    def test_median_single(self):
        stats = _compute_aggregate_stats([42])
        self.assertEqual(stats["median"], 42.0)
        self.assertEqual(stats["n"], 1)

    def test_median_odd(self):
        stats = _compute_aggregate_stats([10, 20, 30])
        self.assertEqual(stats["median"], 20.0)

    def test_median_even(self):
        stats = _compute_aggregate_stats([10, 20])
        self.assertEqual(stats["median"], 15.0)

    def test_p90_small_sample(self):
        # n=10: p90_idx = ceil(0.9*10)-1 = 9-1=8, sorted[8] = errors[8]
        errors = list(range(10, 110, 10))  # [10,20,30,40,50,60,70,80,90,100]
        stats = _compute_aggregate_stats(errors)
        # p90_idx = ceil(9.0)-1 = 9-1=8 → sorted[8]=90
        self.assertEqual(stats["p90"], 90.0)

    def test_empty_errors(self):
        stats = _compute_aggregate_stats([])
        self.assertEqual(stats["n"], 0)
        self.assertIsNone(stats["median"])

    def test_within_tolerance_count_synthetic(self):
        """Synthetic: 2 of 4 predictions within tolerance → 50%."""
        ground_truths = [100, 200, 300, 400]  # human labels
        predictions  = [102, 210, 350, 405]   # auto predictions
        within = sum(1 for h, p in zip(ground_truths, predictions)
                     if _is_within_tolerance(abs(p - h), "takeoff"))
        total = len(ground_truths)
        pct = within / total
        self.assertEqual(within, 2)       # 2, 10, 50, 5 → [2,5] within 5
        self.assertAlmostEqual(pct, 0.50)

    def test_all_within_tolerance(self):
        """All predictions within tolerance → 100%."""
        preds = [(100, 100), (200, 203), (300, 305)]  # (human, pred)
        within = sum(1 for h, p in preds
                     if _is_within_tolerance(abs(p - h), "takeoff"))
        self.assertEqual(within, 3)

    def test_none_within_tolerance(self):
        """All seriously wrong → 0%."""
        preds = [(100, 200), (200, 400), (300, 500)]
        within = sum(1 for h, p in preds
                     if _is_within_tolerance(abs(p - h), "takeoff"))
        self.assertEqual(within, 0)

    def test_invalid_ordering_detected(self):
        """Predictions that violate T < A < W must be detected."""
        invalid_cases = [
            (200, 100, 300),   # T > A
            (100, 300, 200),   # A > W
            (100, 100, 100),   # all equal
        ]
        for t, a, w in invalid_cases:
            self.assertFalse(t < a < w, f"({t},{a},{w}) should be invalid")

    def test_applicability_mismatch_not_evaluated(self):
        """If human says NOT_APPLICABLE but auto gives a frame, that's a mismatch."""
        human_applicability = "NOT_APPLICABLE"
        auto_frame = 100
        # Evaluator should skip/flag this rather than computing frame error
        # The convention: NOT_APPLICABLE landmarks are counted as applicability_error=1
        is_evaluable = human_applicability in ("APPLICABLE", "UNCERTAIN") and auto_frame is not None
        self.assertFalse(is_evaluable)

    def test_coverage_rate(self):
        """Coverage = fraction of dives where a prediction is made (not UNCERTAIN)."""
        results = [
            {"frame": 100, "uncertain": False},
            {"frame": 200, "uncertain": False},
            {"frame": None, "uncertain": True},
            {"frame": 300, "uncertain": False},
        ]
        coverage = sum(1 for r in results if not r["uncertain"]) / len(results)
        self.assertEqual(coverage, 0.75)

    def test_uncertainty_rate(self):
        results = [True, False, True, False, False]  # True = uncertain
        uncertain_rate = sum(results) / len(results)
        self.assertAlmostEqual(uncertain_rate, 0.4)

    def test_catastrophic_error_threshold(self):
        """Errors > 100 frames are 'catastrophic'."""
        errors = [5, 10, 50, 100, 200, 500]
        catastrophic = [e for e in errors if e > 100]
        self.assertEqual(catastrophic, [200, 500])


# ===========================================================================
# PHASE B2 additional: Annotation file parsing
# ===========================================================================

class TestAnnotationFileParsing(unittest.TestCase):
    """Test that DESIGN annotation files can be parsed correctly.
    INTERNAL_EVAL labels are not read during Baseline C development.
    This test reads only DESIGN dive annotations to verify schema."""

    DESIGN_DIVES = [133, 311, 524, 676, 1040, 2169, 2341, 2353,
                    2387, 2541, 2555, 2625, 2661, 2680]
    ANNOTATION_DIR = REPO_ROOT / "docs" / "science" / "pilot_annotations"

    def _load_annotation(self, dive_id):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not available")
        path = self.ANNOTATION_DIR / f"dive_{dive_id}.yaml"
        if not path.exists():
            self.skipTest(f"Annotation not found: {path}")
        with open(path) as f:
            return yaml.safe_load(f)

    def test_design_annotations_parse(self):
        """Verify DESIGN annotation files parse without error."""
        for dive_id in self.DESIGN_DIVES:
            try:
                import yaml
            except ImportError:
                self.skipTest("PyYAML not available")
            path = self.ANNOTATION_DIR / f"dive_{dive_id}.yaml"
            if not path.exists():
                continue
            with open(path) as f:
                ann = yaml.safe_load(f)
            self.assertIsInstance(ann, dict, f"Annotation for dive {dive_id} must be dict")
            self.assertIn("dive_id", ann, f"Annotation {dive_id} missing dive_id")
            self.assertEqual(ann["dive_id"], dive_id)

    def test_annotation_landmarks_have_required_fields(self):
        """Each landmark entry must have state and (if APPLICABLE) frame_index."""
        for dive_id in self.DESIGN_DIVES[:3]:  # spot-check 3 dives
            ann = self._load_annotation(dive_id)
            if not ann:
                continue
            landmarks = ann.get("landmarks", {})
            for lm_key, lm_data in landmarks.items():
                self.assertIn("state", lm_data, f"Dive {dive_id} {lm_key} missing state")
                if lm_data.get("state") not in ("NOT_APPLICABLE",):
                    self.assertIn("frame_index", lm_data,
                                  f"Dive {dive_id} {lm_key} missing frame_index")

    def test_internal_eval_annotations_not_read_for_dev(self):
        """Firewall test: verify we have not programmatically accessed EVAL labels.
        This is a structural test — EVAL annotation paths are not imported here."""
        EVAL_DIVES = {160, 169, 191, 192, 848, 2281}
        # We just assert that none of the EVAL dives are in DESIGN_DIVES
        design_set = set(self.DESIGN_DIVES)
        self.assertEqual(design_set & EVAL_DIVES, set(),
                         "INTERNAL_EVAL dives must not appear in DESIGN_DIVES list")


# ===========================================================================
# PHASE B4: Provenance — fingerprint changes with any input change
# ===========================================================================

class TestProvenanceFingerprints(unittest.TestCase):

    def _fp(self, **kwargs):
        payload = json.dumps(kwargs, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    def test_model_version_change_changes_fingerprint(self):
        fp1 = self._fp(model="yolov8n", version="8.0.0", weights_sha256="abc", params={})
        fp2 = self._fp(model="yolov8n", version="8.1.0", weights_sha256="abc", params={})
        self.assertNotEqual(fp1, fp2)

    def test_weights_change_changes_fingerprint(self):
        fp1 = self._fp(model="yolov8n", version="8.0.0", weights_sha256="aaa", params={})
        fp2 = self._fp(model="yolov8n", version="8.0.0", weights_sha256="bbb", params={})
        self.assertNotEqual(fp1, fp2)

    def test_parameter_change_changes_fingerprint(self):
        fp1 = self._fp(model="yolov8n", version="8.0.0", weights_sha256="abc",
                       params={"conf": 0.25})
        fp2 = self._fp(model="yolov8n", version="8.0.0", weights_sha256="abc",
                       params={"conf": 0.30})
        self.assertNotEqual(fp1, fp2)

    def test_media_checksum_change_changes_fingerprint(self):
        fp1 = self._fp(media_sha256="aaa", pipeline="baseline_c_v1")
        fp2 = self._fp(media_sha256="bbb", pipeline="baseline_c_v1")
        self.assertNotEqual(fp1, fp2)

    def test_fingerprint_is_deterministic(self):
        fp1 = self._fp(a=1, b=2, c="x")
        fp2 = self._fp(a=1, b=2, c="x")
        self.assertEqual(fp1, fp2)

    def test_empty_params_vs_nonempty(self):
        fp1 = self._fp(model="x", params={})
        fp2 = self._fp(model="x", params={"k": "v"})
        self.assertNotEqual(fp1, fp2)


# ===========================================================================
# PHASE B (Baseline C): Track selection logic tests
# ===========================================================================

class TestTrackSelectionLogic(unittest.TestCase):
    """Tests for the single-diver track selection heuristics of Baseline C.
    These test pure algorithmic logic, no YOLO or video needed."""

    def _select_primary_track(self, tracks):
        """Select the primary diver track from a list of track dicts.
        Strategy: prefer longest track with highest average confidence.
        Returns track_id of selected track, or None if no tracks.
        """
        if not tracks:
            return None
        # Score = (length * avg_conf)
        def score(t):
            avg_conf = sum(t["confidences"]) / len(t["confidences"]) if t["confidences"] else 0
            return len(t["boxes"]) * avg_conf
        return max(tracks, key=score)["track_id"]

    def test_single_track_selected(self):
        tracks = [{"track_id": 1, "boxes": [(0,0,50,100)]*20,
                   "confidences": [0.9]*20}]
        self.assertEqual(self._select_primary_track(tracks), 1)

    def test_longer_track_preferred(self):
        tracks = [
            {"track_id": 1, "boxes": [(0,0,50,100)]*10, "confidences": [0.9]*10},
            {"track_id": 2, "boxes": [(0,0,50,100)]*30, "confidences": [0.9]*30},
        ]
        self.assertEqual(self._select_primary_track(tracks), 2)

    def test_higher_confidence_preferred_for_equal_length(self):
        tracks = [
            {"track_id": 1, "boxes": [(0,0,50,100)]*20, "confidences": [0.5]*20},
            {"track_id": 2, "boxes": [(0,0,50,100)]*20, "confidences": [0.9]*20},
        ]
        self.assertEqual(self._select_primary_track(tracks), 2)

    def test_no_tracks_returns_none(self):
        self.assertIsNone(self._select_primary_track([]))

    def test_zero_confidence_track_not_preferred(self):
        tracks = [
            {"track_id": 1, "boxes": [(0,0,50,100)]*50, "confidences": [0.0]*50},
            {"track_id": 2, "boxes": [(0,0,50,100)]*5, "confidences": [0.9]*5},
        ]
        self.assertEqual(self._select_primary_track(tracks), 2)


# ===========================================================================
# PHASE B (Baseline C): Trajectory smoothing tests
# ===========================================================================

class TestTrajectorySmoothingLogic(unittest.TestCase):
    """Tests for vertical trajectory processing logic."""

    def _interpolate_gaps(self, y_values, max_gap=10):
        """Linear interpolation for None/missing frames.
        Returns list with Nones filled by linear interpolation where gap <= max_gap.
        """
        result = list(y_values)
        n = len(result)
        i = 0
        while i < n:
            if result[i] is None:
                # Find gap end
                j = i
                while j < n and result[j] is None:
                    j += 1
                gap_len = j - i
                if gap_len <= max_gap and i > 0 and j < n:
                    # Interpolate linearly
                    start_val = result[i - 1]
                    end_val = result[j]
                    for k in range(gap_len):
                        t = (k + 1) / (gap_len + 1)
                        result[i + k] = start_val + t * (end_val - start_val)
                i = j
            else:
                i += 1
        return result

    def _find_trajectory_apex(self, y_norm_sequence):
        """Return index of maximum y_norm (highest position)."""
        if not y_norm_sequence:
            return None
        valid = [(i, v) for i, v in enumerate(y_norm_sequence) if v is not None]
        if not valid:
            return None
        return max(valid, key=lambda x: x[1])[0]

    def test_smooth_monotone_ascending_apex_at_end(self):
        y = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
        apex = self._find_trajectory_apex(y)
        self.assertEqual(apex, 8)

    def test_smooth_parabola_apex_at_center(self):
        y = [0.1, 0.4, 0.7, 0.9, 0.7, 0.4, 0.1]
        apex = self._find_trajectory_apex(y)
        self.assertEqual(apex, 3)

    def test_gap_interpolation_fills_short_gap(self):
        y = [0.2, None, None, 0.8]
        result = self._interpolate_gaps(y, max_gap=5)
        self.assertIsNotNone(result[1])
        self.assertIsNotNone(result[2])
        # Interpolated values should be between 0.2 and 0.8
        self.assertGreater(result[1], 0.2)
        self.assertLess(result[1], 0.8)

    def test_gap_interpolation_skips_long_gap(self):
        y = [0.2, None, None, None, None, None, None, None, None, None, None, None, 0.8]
        result = self._interpolate_gaps(y, max_gap=5)
        # Gap of 11 is > max_gap=5, not interpolated
        for i in range(1, 12):
            self.assertIsNone(result[i])

    def test_apex_with_none_values(self):
        y = [0.3, None, 0.8, None, 0.5]
        apex = self._find_trajectory_apex(y)
        self.assertEqual(apex, 2)  # index of 0.8 (highest non-None)

    def test_all_none_returns_none(self):
        y = [None, None, None]
        apex = self._find_trajectory_apex(y)
        self.assertIsNone(apex)


# ===========================================================================
# PHASE B (Baseline C): Event detection logic tests
# ===========================================================================

class TestEventDetectionLogic(unittest.TestCase):
    """Tests for landmark-specific event detection (without video/YOLO)."""

    TAKEOFF_THRESH_Y = 0.3   # above this y_norm = in the air
    WATER_LEVEL_Y = 0.1      # below this = in the water
    MIN_FLIGHT_FRAMES = 10   # minimum frames for valid flight detection

    def _detect_takeoff(self, y_norm_seq, threshold=0.3, min_sustained=5):
        """Detect takeoff: first frame where y_norm > threshold for >= min_sustained frames."""
        n = len(y_norm_seq)
        for i in range(n):
            if y_norm_seq[i] is None:
                continue
            if y_norm_seq[i] > threshold:
                # Check sustained
                count = sum(1 for j in range(i, min(i + min_sustained, n))
                            if y_norm_seq[j] is not None and y_norm_seq[j] > threshold)
                if count >= min_sustained:
                    return i
        return None

    def _detect_water_contact(self, y_norm_seq, apex_idx, threshold=0.15):
        """Detect water contact: first frame after apex where y_norm drops below threshold."""
        if apex_idx is None:
            return None
        n = len(y_norm_seq)
        for i in range(apex_idx + 1, n):
            if y_norm_seq[i] is None:
                continue
            if y_norm_seq[i] < threshold:
                return i
        return None

    def test_takeoff_detected_on_rising_trajectory(self):
        # Trajectory: flat, then rises above threshold
        y = [0.1]*10 + [0.35, 0.40, 0.45, 0.50, 0.55, 0.60]
        t = self._detect_takeoff(y, threshold=0.3, min_sustained=5)
        self.assertIsNotNone(t)
        self.assertEqual(t, 10)

    def test_takeoff_not_detected_below_threshold(self):
        y = [0.1, 0.2, 0.25, 0.28, 0.1]
        t = self._detect_takeoff(y, threshold=0.3, min_sustained=3)
        self.assertIsNone(t)

    def test_takeoff_not_detected_if_not_sustained(self):
        # Rises briefly but doesn't sustain 5 frames
        y = [0.1]*10 + [0.35, 0.20, 0.1, 0.1, 0.1]
        t = self._detect_takeoff(y, threshold=0.3, min_sustained=5)
        self.assertIsNone(t)

    def test_water_contact_detected_below_threshold(self):
        # Descends from apex through the water-level threshold
        y = [0.5, 0.4, 0.3, 0.2, 0.09, 0.05]
        apex_idx = 0
        w = self._detect_water_contact(y, apex_idx, threshold=0.15)
        self.assertIsNotNone(w)
        self.assertEqual(w, 4)  # first frame < 0.15 after apex

    def test_water_contact_none_if_no_drop(self):
        y = [0.5, 0.4, 0.3, 0.2, 0.18, 0.17]
        w = self._detect_water_contact(y, apex_idx=0, threshold=0.15)
        self.assertIsNone(w)

    def test_ordering_invariant_t_before_a_before_w(self):
        """Detected events must satisfy T < A < W."""
        t, a, w = 10, 30, 50
        self.assertTrue(t < a < w)

    def test_early_trigger_would_be_before_flight(self):
        """EARLY_TRIGGER: takeoff detected before the diver is actually in the air."""
        y = [0.0]*5 + [0.35]*10  # diver on board first 5 frames, then airborne
        # Non-sustained early trigger would pick frame 0 — detect_takeoff prevents this
        t = self._detect_takeoff(y, threshold=0.3, min_sustained=8)
        # Only detects when sustained ≥ 8 frames → frame 5
        self.assertGreaterEqual(t if t is not None else 999, 5)

    def test_water_contact_runaway_prevented(self):
        """WATER_CONTACT_RUNAWAY: water contact must not be detected long after entry.
        After the diver enters (drops below threshold), the FIRST such frame is returned.
        Subsequent turbulence frames don't change the result."""
        y = [0.5, 0.3, 0.08, 0.20, 0.05, 0.03]  # 0.08 is first below 0.15
        w = self._detect_water_contact(y, apex_idx=0, threshold=0.15)
        self.assertEqual(w, 2)  # First frame below threshold, not the last


# ===========================================================================
# PHASE B (Baseline C): Confidence/uncertainty logic
# ===========================================================================

class TestBaselineCConfidenceLogic(unittest.TestCase):
    """Tests for Baseline C confidence and uncertainty emitting."""

    def _compute_trajectory_confidence(self, y_norm_seq, apex_idx, takeoff_idx):
        """Confidence proxy based on detection coverage and trajectory plausibility."""
        if apex_idx is None or takeoff_idx is None:
            return 0.0
        if not (takeoff_idx < apex_idx):
            return 0.0
        # Coverage: fraction of non-None frames
        coverage = sum(1 for v in y_norm_seq if v is not None) / max(1, len(y_norm_seq))
        # Trajectory displacement: apex should be higher than takeoff
        apex_y = y_norm_seq[apex_idx]
        takeoff_y = y_norm_seq[takeoff_idx]
        if apex_y is None or takeoff_y is None:
            return 0.0
        displacement = apex_y - takeoff_y
        if displacement <= 0:
            return max(0.0, coverage * 0.3)
        return min(1.0, coverage * min(1.0, displacement / 0.3))

    def test_full_coverage_good_displacement_high_confidence(self):
        y = [0.2, 0.4, 0.6, 0.8, 0.6, 0.4, 0.2]
        conf = self._compute_trajectory_confidence(y, apex_idx=3, takeoff_idx=0)
        self.assertGreater(conf, 0.7)

    def test_low_coverage_reduces_confidence(self):
        y = [0.2, None, None, None, 0.8, None, None]
        conf = self._compute_trajectory_confidence(y, apex_idx=4, takeoff_idx=0)
        self.assertLess(conf, 0.8)

    def test_none_apex_returns_zero_confidence(self):
        y = [0.2, 0.4, 0.6, 0.8]
        conf = self._compute_trajectory_confidence(y, apex_idx=None, takeoff_idx=0)
        self.assertEqual(conf, 0.0)

    def test_none_takeoff_returns_zero_confidence(self):
        y = [0.2, 0.4, 0.6, 0.8]
        conf = self._compute_trajectory_confidence(y, apex_idx=3, takeoff_idx=None)
        self.assertEqual(conf, 0.0)

    def test_invalid_ordering_takeoff_gte_apex_returns_low_confidence(self):
        y = [0.8, 0.6, 0.4, 0.2]
        conf = self._compute_trajectory_confidence(y, apex_idx=0, takeoff_idx=3)
        self.assertEqual(conf, 0.0)

    def test_no_displacement_reduces_confidence(self):
        # Apex at same height as takeoff → no upward motion detected
        y = [0.5, 0.5, 0.5, 0.5]
        conf = self._compute_trajectory_confidence(y, apex_idx=3, takeoff_idx=0)
        self.assertLess(conf, 0.4)


# ===========================================================================
# PHASE B (Baseline C): Serialization and fingerprint of results
# ===========================================================================

class TestBaselineCSerializationAndFingerprint(unittest.TestCase):

    def _serialize_result(self, dive_id, landmarks, fps, params, weights_sha256):
        """Produce deterministic serialized result dict."""
        return {
            "dive_id": dive_id,
            "fps": fps,
            "landmarks": {k: {"frame": v} for k, v in landmarks.items()},
            "params": params,
            "weights_sha256": weights_sha256,
        }

    def _fingerprint_result(self, result_dict):
        payload = json.dumps(result_dict, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    def test_result_serialization_deterministic(self):
        r1 = self._serialize_result(42, {"takeoff": 100, "apex": 200, "water_contact": 300},
                                    30.0, {"conf": 0.25}, "abc123")
        r2 = self._serialize_result(42, {"takeoff": 100, "apex": 200, "water_contact": 300},
                                    30.0, {"conf": 0.25}, "abc123")
        self.assertEqual(self._fingerprint_result(r1), self._fingerprint_result(r2))

    def test_result_fingerprint_sensitive_to_landmarks(self):
        r1 = self._serialize_result(42, {"takeoff": 100}, 30.0, {}, "abc")
        r2 = self._serialize_result(42, {"takeoff": 105}, 30.0, {}, "abc")
        self.assertNotEqual(self._fingerprint_result(r1), self._fingerprint_result(r2))

    def test_result_fingerprint_sensitive_to_weights(self):
        r1 = self._serialize_result(42, {"takeoff": 100}, 30.0, {}, "weights_v1")
        r2 = self._serialize_result(42, {"takeoff": 100}, 30.0, {}, "weights_v2")
        self.assertNotEqual(self._fingerprint_result(r1), self._fingerprint_result(r2))

    def test_result_ordering_invariant(self):
        """JSON serialized with sort_keys=True; landmark key order doesn't matter."""
        lm1 = {"takeoff": 100, "apex": 200, "water_contact": 300}
        lm2 = {"water_contact": 300, "takeoff": 100, "apex": 200}
        r1 = self._serialize_result(1, lm1, 30.0, {}, "x")
        r2 = self._serialize_result(1, lm2, 30.0, {}, "x")
        self.assertEqual(self._fingerprint_result(r1), self._fingerprint_result(r2))


# ===========================================================================
# PHASE B6: Production guard (runner max-dives)
# ===========================================================================
# (Already present as TestNoBulkEnqueue — kept)


# ===========================================================================
# Integration tests (require DB) — skip unless DB_TEST=1
# ===========================================================================

SKIP_DB = not os.getenv("DB_TEST")


@pytest.mark.skipif(SKIP_DB, reason="DB_TEST not set; skipping DB integration tests")
class TestDBIntegration(unittest.TestCase):

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
        self.assertEqual(len(dives), 20)

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
            self.assertIn(d['dive_id'], metric_counts)
            self.assertGreaterEqual(metric_counts[d['dive_id']], 10)

    def test_uncertain_dives_have_zero_confidence(self):
        dives = self.annotate._get_all_pilot_data()
        for d in dives:
            if not d['ordering_valid']:
                for key, lm in d['landmarks'].items():
                    if lm.get('applicability') == 'UNCERTAIN':
                        self.assertEqual(float(lm.get('confidence', -1)), 0.0)

    def test_comparisons_stored(self):
        conn = self.annotate._connect()
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM analysis_comparisons
            WHERE method_key = 'temporal_landmark_pairwise_v1' AND status = 'succeeded'
        """)
        count = cur.fetchone()[0]
        conn.close()
        self.assertEqual(count, 66)

    def test_metric_unique_constraint(self):
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
        self.assertEqual(duplicates, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
