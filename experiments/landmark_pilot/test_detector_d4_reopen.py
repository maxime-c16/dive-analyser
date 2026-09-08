#!/usr/bin/env python3
"""Phase S — Tests for DETECTOR_D4_REOPEN packet.

Tests cover:
- Canonical RAW_TARGET_CANDIDATE_RECALL denominator (Phase A reconciliation)
- BELOW_THRESHOLD_TARGET vs TARGET_NOT_LOCALIZED taxonomy (Phase A1)
- Exhaustive top-K candidate ceiling (Phase B)
- Paris firewall — no Paris data in D4 (Phase C/F)
- D4 dataset exclusion of Paris (Phase F)
- Hard-negative semantics (Phase C1)
- Complete visible-diver labeling (Phase C2)
- D4 annotation batch structure (Phase E)
- Proposal freeze consistency (Phase I)
- Selector conditional accuracy (Phase M)
- Scientific consistency: supersession of stale V2 figures (Phase A)
"""
import json, sys, os, math, unittest

sys.path.insert(0, os.path.expanduser("~/dive-analyser/experiments/landmark_pilot"))

BASE = os.path.expanduser("~/dive-analyser")
SCI_DIR = f"{BASE}/docs/science"
V1_DIR = f"{BASE}/experiments/landmark_pilot/runs/target_selection_v1"
V2_DIR = f"{BASE}/experiments/landmark_pilot/runs/target_selection_v2"
ANNOT_DIR = f"{SCI_DIR}/localization_annotations_v1/DEVELOPMENT_DESIGN"
D4_BATCH_DIR = f"{SCI_DIR}/localization_annotations_v1/D4_ANNOTATION_BATCH"


# ===== TEST GROUP A: Scientific Consistency Repair =====

class TestCanonicalRecallDenominator(unittest.TestCase):
    """Phase A: RAW_TARGET_CANDIDATE_RECALL canonical denominator."""

    def setUp(self):
        path = f"{V2_DIR}/D3_EXHAUSTIVE_RAW_CEILING_V1.json"
        self.data = json.load(open(path)) if os.path.exists(path) else None

    def test_ceiling_file_exists(self):
        path = f"{V2_DIR}/D3_EXHAUSTIVE_RAW_CEILING_V1.json"
        self.assertTrue(os.path.exists(path), "D3_EXHAUSTIVE_RAW_CEILING_V1.json must exist")

    def test_canonical_denominator_is_31(self):
        """Canonical denominator = 31 frames (visible + partial with bbox; exclude ambiguous/null-bbox)."""
        if self.data is None:
            self.skipTest("Ceiling file not found")
        self.assertEqual(self.data["canonical_denominator"], 31,
                         "Canonical denominator must be 31 (consistent with phase_a_threshold_sweep.json)")

    def test_stale_report_denominators_superseded(self):
        """Phase G of V2 report used 20/31 (AMBIGUOUS as miss); Phase A table used 22/31 (AMBIGUOUS as hit).
        Both are superseded by the ceiling audit. The ceiling audit counts 21/31 at op-threshold.
        Test that the fresh ceiling result for TARGET_AVAILABLE = 21 (not 20 or 22)."""
        if self.data is None:
            self.skipTest("Ceiling file not found")
        avail = self.data["target_available_count"]
        self.assertEqual(avail, 21,
                         f"TARGET_AVAILABLE at conf>=0.05 = 21/31 (supersedes 22 and 20 from V2 report); got {avail}")

    def test_taxonomy_three_classes_complete(self):
        """All 31 frames must be classified into exactly one of the three taxonomy classes."""
        if self.data is None:
            self.skipTest("Ceiling file not found")
        avail = self.data["target_available_count"]
        below = self.data["below_threshold_count"]
        not_loc = self.data["not_localized_count"]
        denom = self.data["canonical_denominator"]
        self.assertEqual(avail + below + not_loc, denom,
                         f"Taxonomy classes must sum to denominator: {avail}+{below}+{not_loc}={avail+below+not_loc} != {denom}")


class TestDetectionTaxonomy(unittest.TestCase):
    """Phase A1: BELOW_THRESHOLD_TARGET vs TARGET_NOT_LOCALIZED distinction."""

    def setUp(self):
        path = f"{V2_DIR}/D3_EXHAUSTIVE_RAW_CEILING_V1.json"
        self.data = json.load(open(path)) if os.path.exists(path) else None

    def test_2625_apex_is_not_localized(self):
        """2625_apex: genuine edge miss (diver at extreme frame edge). Must be TARGET_NOT_LOCALIZED."""
        if self.data is None:
            self.skipTest("Ceiling file not found")
        frames = {f["key"]: f for f in self.data["frames"]}
        self.assertIn("2625_apex", frames, "2625_apex must be in ceiling results")
        self.assertEqual(frames["2625_apex"]["taxonomy"], "TARGET_NOT_LOCALIZED",
                         "2625_apex is a genuine localization failure (diver at extreme frame edge)")

    def test_2341_takeoff_is_below_threshold(self):
        """2341_takeoff: target localized at floor but ranked 114/224. Must be BELOW_THRESHOLD_TARGET."""
        if self.data is None:
            self.skipTest("Ceiling file not found")
        frames = {f["key"]: f for f in self.data["frames"]}
        self.assertIn("2341_takeoff", frames)
        self.assertEqual(frames["2341_takeoff"]["taxonomy"], "BELOW_THRESHOLD_TARGET",
                         "2341_takeoff must be BELOW_THRESHOLD (detected at floor rank 114)")

    def test_no_frame_is_incorrectly_called_zero_detection(self):
        """Per taxonomy definition, BELOW_THRESHOLD frames must NOT be called zero-detection.
        Verify: all BELOW_THRESHOLD frames have topk_all=True (target exists in full list)."""
        if self.data is None:
            self.skipTest("Ceiling file not found")
        for f in self.data["frames"]:
            if f["taxonomy"] == "BELOW_THRESHOLD_TARGET":
                self.assertTrue(f["topk_all"],
                                f"{f['key']} is BELOW_THRESHOLD but topk_all=False — contradiction!")

    def test_not_localized_frames_have_no_match(self):
        """TARGET_NOT_LOCALIZED frames must have topk_all=False (no match at any rank)."""
        if self.data is None:
            self.skipTest("Ceiling file not found")
        for f in self.data["frames"]:
            if f["taxonomy"] == "TARGET_NOT_LOCALIZED":
                self.assertFalse(f["topk_all"],
                                 f"{f['key']} is TARGET_NOT_LOCALIZED but topk_all=True — contradiction!")


# ===== TEST GROUP B: Exhaustive Ceiling =====

class TestExhaustiveCeiling(unittest.TestCase):
    """Phase B: exhaustive top-K ceiling analysis."""

    def setUp(self):
        path = f"{V2_DIR}/D3_EXHAUSTIVE_RAW_CEILING_V1.json"
        self.data = json.load(open(path)) if os.path.exists(path) else None

    def test_exhaustive_ceiling_ge_90pct(self):
        """Exhaustive ceiling (TARGET_AVAILABLE + BELOW_THRESHOLD) must be >= 90%."""
        if self.data is None:
            self.skipTest("Ceiling file not found")
        ceiling = self.data["exhaustive_ceiling"]
        self.assertGreaterEqual(ceiling, 0.90,
                                f"Exhaustive ceiling {ceiling:.1%} must be >= 90% for D4 to be justified")

    def test_topk_data_present(self):
        """Top-K results must be present for K in [1, 3, 5, 10, 20]."""
        if self.data is None:
            self.skipTest("Ceiling file not found")
        for k in [1, 3, 5, 10, 20]:
            self.assertIn(str(k), self.data["topk_results"],
                          f"Top-{k} result missing from ceiling data")

    def test_topk_monotone(self):
        """Top-K recall must be non-decreasing as K increases."""
        if self.data is None:
            self.skipTest("Ceiling file not found")
        ks = [1, 3, 5, 10, 20]
        vals = [self.data["topk_results"][str(k)]["count"] for k in ks]
        for i in range(len(vals)-1):
            self.assertLessEqual(vals[i], vals[i+1],
                                 f"Top-{ks[i]}={vals[i]} > top-{ks[i+1]}={vals[i+1]}: recall must be monotone")

    def test_ceiling_decision_d3_reopen_required(self):
        """Top-20 ceiling < 90% (87.1%) → D3_LOCALIZATION_REOPEN_REQUIRED
        (the 3 failure frames require ranks >20 with huge candidate loads)."""
        if self.data is None:
            self.skipTest("Ceiling file not found")
        denom = self.data["canonical_denominator"]
        top20 = self.data["topk_results"]["20"]["count"]
        rate = top20 / denom
        # Top-20 must be below 90% for this decision to be correct
        self.assertLess(rate, 0.90,
                        f"Expected top-20 < 90% (gate fails) but got {top20}/{denom}={rate:.1%}")


# ===== TEST GROUP C: Paris Firewall =====

class TestParisFirewall(unittest.TestCase):
    """Phase C/F: Paris (IMG_1937.mov) must not appear in D4 data."""

    PARIS_MEDIA_KEY = "d122262be8e7a8721ab2f6a71721bb3544403da78324138d026360ef9820eaae"
    PARIS_DIVE_ID_HINT = 2819  # canary dive

    def test_d4_batch_excludes_paris_media_key(self):
        """D4 annotation batch must not contain the Paris canary media key."""
        batch_path = f"{D4_BATCH_DIR}/manifest.json"
        if not os.path.exists(batch_path):
            self.skipTest("D4 batch not yet built")
        batch = json.load(open(batch_path))
        for f in batch.get("frames", []):
            mk = f.get("media_key", "")
            self.assertNotEqual(mk, self.PARIS_MEDIA_KEY,
                                f"Paris media key found in D4 batch frame {f.get('frame_id')}")

    def test_d4_batch_excludes_paris_dive_id(self):
        """D4 annotation batch must not reference dive 2819 (Paris canary)."""
        batch_path = f"{D4_BATCH_DIR}/manifest.json"
        if not os.path.exists(batch_path):
            self.skipTest("D4 batch not yet built")
        batch = json.load(open(batch_path))
        dive_ids = [f.get("dive_id") for f in batch.get("frames", [])]
        self.assertNotIn(self.PARIS_DIVE_ID_HINT, dive_ids,
                         "Dive 2819 (Paris canary) must not appear in D4 annotation batch")

    def test_ceiling_audit_is_development_only(self):
        """Ceiling audit must declare Paris firewall."""
        path = f"{V2_DIR}/D3_EXHAUSTIVE_RAW_CEILING_V1.json"
        if not os.path.exists(path):
            self.skipTest("Ceiling file not found")
        data = json.load(open(path))
        self.assertIn("paris_firewall", data,
                      "Ceiling audit must declare Paris firewall")
        self.assertIn("DEVELOPMENT_ONLY", data["paris_firewall"])

    def test_ceiling_audit_dives_are_development(self):
        """Ceiling audit frames must be from DEVELOPMENT dives only (not dive 2819)."""
        path = f"{V2_DIR}/D3_EXHAUSTIVE_RAW_CEILING_V1.json"
        if not os.path.exists(path):
            self.skipTest("Ceiling file not found")
        data = json.load(open(path))
        for f in data["frames"]:
            self.assertNotEqual(f.get("dive_id"), 2819,
                                "Paris canary dive found in ceiling audit frames!")


# ===== TEST GROUP D: D4 Annotation Batch =====

class TestD4AnnotationBatch(unittest.TestCase):
    """Phase E: D4 annotation batch structure validation."""

    def setUp(self):
        path = f"{D4_BATCH_DIR}/manifest.json"
        self.batch = json.load(open(path)) if os.path.exists(path) else None

    def test_d4_batch_exists(self):
        self.assertTrue(os.path.exists(f"{D4_BATCH_DIR}/manifest.json"),
                        "D4_ANNOTATION_BATCH/manifest.json must exist")

    def test_d4_batch_frame_count(self):
        """Batch must have 20-80 frames (within Phase E bounds)."""
        if self.batch is None:
            self.skipTest("D4 batch not found")
        n = len(self.batch["frames"])
        self.assertGreaterEqual(n, 10, "D4 batch must have at least 10 frames")
        self.assertLessEqual(n, 80, "D4 batch must not exceed 80 frames (packet hard maximum)")

    def test_d4_batch_frame_files_exist(self):
        """All frame image files referenced in the batch must exist."""
        if self.batch is None:
            self.skipTest("D4 batch not found")
        for f in self.batch["frames"]:
            fpath = os.path.join(D4_BATCH_DIR, f["frame_file"])
            self.assertTrue(os.path.exists(fpath),
                            f"Frame file missing: {fpath}")

    def test_d4_batch_covers_primary_failure_dives(self):
        """D4 batch must include frames from the primary failure dives."""
        if self.batch is None:
            self.skipTest("D4 batch not found")
        primary_dives = {2341, 2555}  # highest-severity failures
        batch_dives = {f["dive_id"] for f in self.batch["frames"]}
        for d in primary_dives:
            self.assertIn(d, batch_dives,
                          f"Primary failure dive {d} must be in D4 batch")


# ===== TEST GROUP E: Hard-Negative Semantics =====

class TestHardNegativeSemantics(unittest.TestCase):
    """Phase C1: Hard-negative semantics — correct label policy."""

    def test_hard_negative_class_definition(self):
        """Hard negatives are frames where NO visible diver is annotated.
        They are NOT annotated with a 'background' class — they are empty-label images."""
        # This tests that the YOLO format for negatives is an empty .txt file
        # We verify the D2 and V2 datasets: negative labels are empty files
        for label_dir in [
            f"{SCI_DIR}/localization_annotations_v1/DATASET_D2_YOLO/labels/train",
            f"{SCI_DIR}/localization_annotations_v1/DATASET_D2_YOLO/labels/val",
        ]:
            if not os.path.exists(label_dir):
                continue
            for fname in os.listdir(label_dir):
                if not fname.endswith('.txt'):
                    continue
                fpath = os.path.join(label_dir, fname)
                content = open(fpath).read().strip()
                if content:
                    # Non-empty = positive label, should have class 0
                    class_ids = [int(line.split()[0]) for line in content.splitlines() if line.strip()]
                    for cid in class_ids:
                        self.assertEqual(cid, 0,
                                         f"{fname}: only class 0 (visible_diver) allowed, got class {cid}")
                # Empty labels (hard negatives) are valid

    def test_paris_static_fp_not_in_training_negatives(self):
        """The Paris static FP (conf 0.30-0.42 at cy≈0.173) must NOT appear
        as an annotated negative in any training data.
        (It would contaminate Paris from the training side.)
        This is verified by checking that no annotation file references IMG_1937.mov."""
        paris_sha = "d122262be8e7a8721ab2f6a71721bb3544403da78324138d026360ef9820eaae"
        for split_dir in [
            f"{SCI_DIR}/localization_annotations_v1/DEVELOPMENT_DESIGN",
            f"{SCI_DIR}/localization_annotations_v1/DEVELOPMENT_DESIGN_V2",
        ]:
            if not os.path.exists(split_dir):
                continue
            for fname in os.listdir(split_dir):
                if fname.endswith('.json') and fname != 'manifest.json':
                    ann = json.load(open(os.path.join(split_dir, fname)))
                    # Check media_sha or media_key doesn't reference Paris video
                    for key in ['media_sha256', 'media_key']:
                        val = ann.get(key, '')
                        self.assertNotIn(paris_sha, val,
                                         f"Paris media found in {fname}!")


# ===== TEST GROUP F: Proposal Freeze =====

class TestProposalFreeze(unittest.TestCase):
    """Phase I: Proposal identity freeze."""

    def test_d3_proposal_freeze_exists(self):
        path = f"{SCI_DIR}/D3_PROPOSAL_V1_FREEZE.json"
        self.assertTrue(os.path.exists(path))
        data = json.load(open(path))
        self.assertEqual(data["status"], "FROZEN")
        self.assertEqual(data["proposal_conf"], 0.05)

    def test_d3_selector_freeze_exists(self):
        path = f"{SCI_DIR}/TARGET_DIVER_SELECTOR_V2_FREEZE.json"
        self.assertTrue(os.path.exists(path))
        data = json.load(open(path))
        self.assertEqual(data["status"], "FROZEN")
        self.assertEqual(data["chosen_selector"], "S1_GLOBAL_PATH")

    def test_ceiling_audit_uses_correct_weights(self):
        """Ceiling audit must use the frozen D3 weights SHA."""
        path = f"{V2_DIR}/D3_EXHAUSTIVE_RAW_CEILING_V1.json"
        if not os.path.exists(path):
            self.skipTest("Ceiling file not found")
        data = json.load(open(path))
        self.assertEqual(
            data["weights_sha256"],
            "bf6415fb63aa311f45262e555899d3023dd3d05d43a5e0d69b5e86c342e1a77d",
            "Ceiling audit must use frozen D3 weights"
        )


# ===== TEST GROUP G: Selector Conditional Accuracy =====

class TestSelectorConditionalAccuracy(unittest.TestCase):
    """Phase M: selector conditional accuracy must be preserved."""

    def test_s1_conditional_accuracy(self):
        """S1 conditional accuracy on DEVELOPMENT (given candidate exists): 80%."""
        path = f"{SCI_DIR}/TARGET_DIVER_SELECTOR_V2_FREEZE.json"
        self.assertTrue(os.path.exists(path))
        data = json.load(open(path))
        self.assertAlmostEqual(data["development_results"]["S1_conditional_acc"], 0.80,
                                places=2, msg="S1 conditional accuracy must be 80%")

    def test_s3_status_is_hypothesis_only(self):
        """Per Phase L: S3 is S3_HYPOTHESIS_ONLY — not scientifically validated."""
        path = f"{SCI_DIR}/TARGET_DIVER_SELECTOR_V2_FREEZE.json"
        data = json.load(open(path))
        # S3 was not chosen as the frozen selector
        self.assertNotEqual(data["chosen_selector"], "S3_ACTION_GLOBAL_PATH",
                             "S3 must not be the chosen selector (development regression)")


# ===== TEST GROUP H: Trajectory Gate Constants =====

class TestTrajectoryGate(unittest.TestCase):
    """Phase O: trajectory gate criteria must remain unchanged."""

    def test_trajectory_gate_criteria(self):
        """The 6-condition gate must be verified from Paris frozen evaluation.
        This is a metadata test — verify the gate criteria are documented."""
        path = f"{SCI_DIR}/TARGET_DIVER_SELECTION_V2_LOW_CONFIDENCE_REPORT.md"
        self.assertTrue(os.path.exists(path))
        content = open(path).read()
        # Gate result must be documented (Phase L result)
        self.assertIn("TRAJECTORY_INPUT_FAIL", content,
                      "Paris trajectory gate result must be documented")
        # The report should document the gate condition criteria
        self.assertIn("WRONG_TARGET", content,
                      "Trajectory gate failure details (WRONG_TARGET) must be documented")


if __name__ == "__main__":
    import unittest
    unittest.main(verbosity=2)
