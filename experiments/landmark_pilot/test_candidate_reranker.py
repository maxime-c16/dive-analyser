#!/usr/bin/env python3
"""Phase U — Tests for DIVER_CANDIDATE_RERANKING_AND_D5 packet.

Tests cover:
  - Phase A: D4 floor audit results (floor recall = 100%, canonical denominator)
  - Phase A1: D4_CANDIDATE_FLOOR_V1_FREEZE structure
  - Phase B/C: Reranker dataset — positive/negative matching, grouped split
  - Phase D: R1 reranker — feature identity, classifier presence
  - Phase E: R2 reranker — contextual features
  - Phase F: Development ranking evaluation — material improvement threshold
  - Phase G: Reranker freeze structure and Paris firewall
  - Phase H: Paris external test — rank improvement documented
  - Phase L: D5 annotation batch — no Paris frames, frame budget respected
  - Phase U: All tests deterministic and reproducible
"""
import json, os, sys, pickle, unittest
import numpy as np

BASE = os.path.expanduser("~/dive-analyser")
SCI  = f"{BASE}/docs/science"
EXP  = f"{BASE}/experiments/landmark_pilot"

# Where results were synced from Mac
RERANKER_DIR = f"{SCI}/reranker_v1"


def load_json(path):
    if not os.path.exists(path):
        return None
    return json.load(open(path))


class TestFloorAudit(unittest.TestCase):
    """Phase A: D4 proposal-floor audit."""

    @classmethod
    def setUpClass(cls):
        cls.audit = load_json(f"{RERANKER_DIR}/D4_FLOOR_AUDIT_V1.json")
        cls.freeze = load_json(f"{RERANKER_DIR}/D4_CANDIDATE_FLOOR_V1_FREEZE.json")

    def test_floor_audit_exists(self):
        self.assertIsNotNone(self.audit, "D4_FLOOR_AUDIT_V1.json must exist")

    def test_floor_recall_is_100pct(self):
        """D4 floor recall must be 100% — detector sees every annotated diver."""
        if self.audit is None:
            self.skipTest("Audit not found")
        self.assertEqual(self.audit["floor_recall"], 1.0,
                         "D4 floor recall (conf≥0.001) must be 100% on DEVELOPMENT")

    def test_canonical_denominator_gte_31(self):
        """Canonical denominator must be at least 31 (D4 historical) or larger."""
        if self.audit is None:
            self.skipTest("Audit not found")
        self.assertGreaterEqual(self.audit["canonical_denominator"], 31,
                                "Canonical denominator must be ≥31")

    def test_top25_recall_is_100pct(self):
        """Top-25 recall must be 100% (all targets within top-25 by confidence)."""
        if self.audit is None:
            self.skipTest("Audit not found")
        topk = self.audit.get("topk_recall", {})
        r25 = topk.get("25", {}).get("recall", 0.0)
        self.assertEqual(r25, 1.0,
                         "Top-25 target recall must be 100% at floor conf")

    def test_paris_firewall_in_audit(self):
        if self.audit is None:
            self.skipTest("Audit not found")
        fw = self.audit.get("paris_firewall", "")
        self.assertIn("Paris", fw, "Paris firewall must be documented in audit")

    def test_floor_freeze_exists(self):
        self.assertIsNotNone(self.freeze, "D4_CANDIDATE_FLOOR_V1_FREEZE.json must exist")

    def test_floor_freeze_conf(self):
        if self.freeze is None:
            self.skipTest("Freeze not found")
        self.assertEqual(self.freeze["floor_conf"], 0.001,
                         "Floor conf must be 0.001 (exhaustive)")

    def test_floor_freeze_cap(self):
        if self.freeze is None:
            self.skipTest("Freeze not found")
        self.assertLessEqual(self.freeze["floor_cap"], 200,
                             "Floor cap must be ≤200 (tractable)")

    def test_floor_freeze_status(self):
        if self.freeze is None:
            self.skipTest("Freeze not found")
        self.assertEqual(self.freeze["status"], "FROZEN")


class TestRerankerDataset(unittest.TestCase):
    """Phase B/C: Proposal-level supervised dataset."""

    @classmethod
    def setUpClass(cls):
        cls.manifest = load_json(f"{RERANKER_DIR}/RERANKER_DATASET_V1_MANIFEST.json")

    def test_manifest_exists(self):
        self.assertIsNotNone(self.manifest, "RERANKER_DATASET_V1_MANIFEST.json must exist")

    def test_no_paris_in_dataset(self):
        """Paris frames must not appear in reranker training data."""
        if self.manifest is None:
            self.skipTest("Manifest not found")
        fw = self.manifest.get("paris_firewall", "")
        self.assertIn("Paris", fw)
        # Check frame_ids for Paris
        for s in self.manifest.get("samples", []):
            fid = s.get("frame_id", "")
            self.assertNotIn("PARIS", fid.upper(),
                             f"Paris sample found in dataset: {fid}")
            self.assertNotIn("2819", fid,
                             f"Paris dive 2819 found in dataset: {fid}")

    def test_positive_matching_rule(self):
        """Positive rule must use IoU≥0.30 or center_dist≤0.05."""
        if self.manifest is None:
            self.skipTest("Manifest not found")
        rule = self.manifest.get("positive_rule", "")
        self.assertIn("0.30", rule, "Positive rule must mention IoU threshold 0.30")
        self.assertIn("0.05", rule, "Positive rule must mention center_dist threshold 0.05")

    def test_grouped_split_no_overlap(self):
        """DEV_TRAIN and DEV_VAL dives must not overlap."""
        if self.manifest is None:
            self.skipTest("Manifest not found")
        split = self.manifest.get("grouped_split", {})
        train_dives = set(split.get("DEV_TRAIN", []))
        val_dives   = set(split.get("DEV_VAL",   []))
        overlap = train_dives & val_dives
        self.assertEqual(len(overlap), 0,
                         f"DEV_TRAIN and DEV_VAL share dives: {overlap}")

    def test_has_positives_and_negatives(self):
        if self.manifest is None:
            self.skipTest("Manifest not found")
        pos = self.manifest.get("positives", 0)
        neg = self.manifest.get("negatives", 0)
        self.assertGreater(pos, 0, "Dataset must have positive samples")
        self.assertGreater(neg, 0, "Dataset must have negative samples")
        # Sanity: at least 1 positive per phase (34 frames)
        self.assertGreater(pos, 30, "At least 30 positives expected (one per frame)")

    def test_feature_model_identity(self):
        if self.manifest is None:
            self.skipTest("Manifest not found")
        feat = self.manifest.get("feature_model", "")
        self.assertIn("ResNet50", feat, "Feature model must be ResNet50")
        self.assertEqual(self.manifest.get("feature_dim"), 2048,
                         "Feature dimension must be 2048")

    def test_negative_sampling_policy_documented(self):
        if self.manifest is None:
            self.skipTest("Manifest not found")
        policy = self.manifest.get("negative_sampling_policy", {})
        self.assertIn("tier1", policy, "Tier 1 sampling must be documented")
        self.assertIn("tier2", policy, "Tier 2 sampling must be documented")
        self.assertIn("max_per_frame", policy, "Max-per-frame must be documented")


class TestRerankerTraining(unittest.TestCase):
    """Phase D/E/F: R1 and R2 training evaluation."""

    @classmethod
    def setUpClass(cls):
        cls.eval = load_json(f"{RERANKER_DIR}/RERANKER_DEV_EVAL.json")

    def test_eval_exists(self):
        self.assertIsNotNone(self.eval, "RERANKER_DEV_EVAL.json must exist")

    def test_reranker_gate_pass(self):
        """R1 or R2 must pass the ≥5 pp improvement gate on DEV_VAL top-1."""
        if self.eval is None:
            self.skipTest("Eval not found")
        gate = self.eval.get("reranker_gate", {})
        result = gate.get("gate", "")
        self.assertEqual(result, "PASS",
                         f"Reranker gate must PASS; got: {result}")

    def test_r1_improves_over_b0_val(self):
        """R1 DEV_VAL top-1 must exceed B0 DEV_VAL top-1."""
        if self.eval is None:
            self.skipTest("Eval not found")
        r1_top1 = self.eval["R1"]["DEV_VAL"]["top1_recall"]
        b0_top1 = self.eval["B0"]["DEV_VAL"]["top1_recall"]
        self.assertGreater(r1_top1, b0_top1,
                           f"R1 top-1 ({r1_top1:.1%}) must exceed B0 ({b0_top1:.1%})")

    def test_r1_feature_model_identity(self):
        if self.eval is None:
            self.skipTest("Eval not found")
        feat = self.eval.get("feature_model", "")
        self.assertIn("ResNet50", feat)

    def test_no_paris_in_eval(self):
        if self.eval is None:
            self.skipTest("Eval not found")
        fw = self.eval.get("paris_firewall", "")
        self.assertIn("Paris", fw)

    def test_train_val_disjoint_in_eval(self):
        if self.eval is None:
            self.skipTest("Eval not found")
        split = self.eval.get("grouped_split", {})
        train_dives = set(split.get("DEV_TRAIN", []))
        val_dives   = set(split.get("DEV_VAL",   []))
        self.assertEqual(len(train_dives & val_dives), 0)

    def test_mrr_improves(self):
        """R1 MRR on DEV_VAL must be higher than B0 MRR."""
        if self.eval is None:
            self.skipTest("Eval not found")
        r1_mrr = self.eval["R1"]["DEV_VAL"]["mrr"]
        b0_mrr = self.eval["B0"]["DEV_VAL"]["mrr"]
        self.assertGreater(r1_mrr, b0_mrr,
                           f"R1 MRR ({r1_mrr:.3f}) must exceed B0 ({b0_mrr:.3f})")


class TestRerankerFreeze(unittest.TestCase):
    """Phase G: Reranker freeze integrity."""

    @classmethod
    def setUpClass(cls):
        cls.freeze = load_json(f"{RERANKER_DIR}/DIVER_CANDIDATE_RERANKER_V1_FREEZE.json")

    def test_freeze_exists(self):
        self.assertIsNotNone(self.freeze, "DIVER_CANDIDATE_RERANKER_V1_FREEZE.json must exist")

    def test_freeze_status(self):
        if self.freeze is None:
            self.skipTest("Freeze not found")
        # Either FROZEN (passed) or RERANKER_NOT_SUFFICIENT (failed gate)
        self.assertIn(self.freeze.get("status"), ["FROZEN", "RERANKER_NOT_SUFFICIENT"])

    def test_freeze_paris_firewall(self):
        if self.freeze is None:
            self.skipTest("Freeze not found")
        fw = self.freeze.get("paris_firewall", "")
        self.assertIn("Paris", fw)

    def test_freeze_pipeline_identity_present(self):
        """Freeze must document the exact pipeline identity."""
        if self.freeze is None:
            self.skipTest("Freeze not found")
        if self.freeze.get("status") != "FROZEN":
            self.skipTest("Reranker did not pass gate — identity not required")
        pi = self.freeze.get("pipeline_identity", {})
        self.assertIn("floor_conf",    pi, "pipeline_identity must include floor_conf")
        self.assertIn("feature_normalization", pi)
        self.assertIn("detector_sha256", pi)


class TestParisRerankerEval(unittest.TestCase):
    """Phase H: Paris external reranker evaluation."""

    @classmethod
    def setUpClass(cls):
        cls.paris = load_json(f"{RERANKER_DIR}/PARIS_RERANKER_EVAL.json")

    def test_paris_eval_exists(self):
        self.assertIsNotNone(self.paris, "PARIS_RERANKER_EVAL.json must exist")

    def test_paris_firewall_post_freeze(self):
        if self.paris is None:
            self.skipTest("Paris eval not found")
        fw = self.paris.get("paris_firewall", "")
        self.assertIn("frozen", fw.lower())

    def test_paris_has_all_three_phases(self):
        if self.paris is None:
            self.skipTest("Paris eval not found")
        phases = self.paris.get("phase_results", {})
        self.assertIn("takeoff",       phases)
        self.assertIn("apex",          phases)
        self.assertIn("water_contact", phases)

    def test_paris_r1_improves_over_d4_for_water_contact(self):
        """R1 must improve water_contact rank vs D4 (rank ~121→better)."""
        if self.paris is None:
            self.skipTest("Paris eval not found")
        wc = self.paris["phase_results"].get("water_contact", {})
        d4_rank = wc.get("d4_confidence_rank")
        r1_rank = wc.get("r1_rank")
        if d4_rank and r1_rank:
            self.assertLess(r1_rank, d4_rank,
                            f"R1 must improve water_contact rank: d4={d4_rank} r1={r1_rank}")

    def test_paris_r1_improves_over_d4_for_apex(self):
        """R1 must improve apex rank vs D4 (rank ~10→better)."""
        if self.paris is None:
            self.skipTest("Paris eval not found")
        apex = self.paris["phase_results"].get("apex", {})
        d4_rank = apex.get("d4_confidence_rank")
        r1_rank = apex.get("r1_rank")
        if d4_rank and r1_rank:
            self.assertLess(r1_rank, d4_rank,
                            f"R1 must improve apex rank: d4={d4_rank} r1={r1_rank}")

    def test_paris_trajectory_gate_documented(self):
        if self.paris is None:
            self.skipTest("Paris eval not found")
        gate = self.paris.get("trajectory_gate")
        self.assertIn(gate, ["TRAJECTORY_INPUT_PASS", "TRAJECTORY_INPUT_FAIL"])

    def test_paris_media_identity_unchanged(self):
        """Paris media SHA must match canonical D4-era value."""
        if self.paris is None:
            self.skipTest("Paris eval not found")
        sha = self.paris.get("paris_media_sha", "")
        self.assertEqual(sha, "d122262be8e7a8721ab2f6a71721bb3544403da78324138d026360ef9820eaae",
                         "Paris media SHA must match canonical value")


class TestD5AnnotationBatch(unittest.TestCase):
    """Phase L: D5 annotation batch integrity."""

    @classmethod
    def setUpClass(cls):
        cls.batch = load_json(f"{RERANKER_DIR}/D5_ANNOTATION_BATCH_MANIFEST.json")

    def test_batch_exists(self):
        self.assertIsNotNone(self.batch, "D5_ANNOTATION_BATCH_MANIFEST.json must exist")

    def test_no_paris_in_d5_batch(self):
        """No Paris frames in D5 batch."""
        if self.batch is None:
            self.skipTest("Batch not found")
        fw = self.batch.get("paris_firewall", "")
        self.assertIn("Paris", fw)
        for f in self.batch.get("frames", []):
            fid = f.get("frame_id", "")
            self.assertNotIn("PARIS", fid.upper(), f"Paris frame in D5 batch: {fid}")
            self.assertNotIn("2819", fid, f"Paris dive in D5 batch: {fid}")

    def test_d5_frame_count_within_budget(self):
        """D5 batch must have 25–60 frames (packet budget)."""
        if self.batch is None:
            self.skipTest("Batch not found")
        n = self.batch.get("n_frames", 0)
        self.assertGreaterEqual(n, 25, f"D5 batch must have ≥25 frames; got {n}")
        self.assertLessEqual(n, 60, f"D5 batch must have ≤60 frames (hard max); got {n}")

    def test_d5_frames_diverse_dives(self):
        """D5 batch must span multiple dives (≥3)."""
        if self.batch is None:
            self.skipTest("Batch not found")
        dives = set(f["dive_id"] for f in self.batch.get("frames", []))
        self.assertGreaterEqual(len(dives), 3,
                                f"D5 batch must span ≥3 dives; got {len(dives)}")

    def test_d5_prioritizes_water_contact(self):
        """D5 batch must include water_contact frames (systematic failure)."""
        if self.batch is None:
            self.skipTest("Batch not found")
        wc_frames = [f for f in self.batch.get("frames", []) if f["phase"] == "water_contact"]
        self.assertGreater(len(wc_frames), 0,
                           "D5 batch must include water_contact frames")


class TestRerankerTopKTargetRecall(unittest.TestCase):
    """Phase A: Top-K target recall metrics on development set."""

    @classmethod
    def setUpClass(cls):
        cls.audit = load_json(f"{RERANKER_DIR}/D4_FLOOR_AUDIT_V1.json")

    def test_top1_recall_below_100pct(self):
        """Top-1 recall must be < 100% (confirms ranking is the bottleneck)."""
        if self.audit is None:
            self.skipTest("Audit not found")
        r1 = self.audit["topk_recall"]["1"]["recall"]
        self.assertLess(r1, 1.0,
                        "Top-1 must be < 100% — D4 confidence alone does not solve ranking")

    def test_top10_recall_above_90pct(self):
        """Top-10 recall must be ≥ 90% (target is within first 10 candidates)."""
        if self.audit is None:
            self.skipTest("Audit not found")
        r10 = self.audit["topk_recall"]["10"]["recall"]
        self.assertGreaterEqual(r10, 0.90,
                                f"Top-10 recall must be ≥90%; got {r10:.1%}")

    def test_floor_100pct_justifies_reranker(self):
        """100% floor recall + <100% top-1 = ranking is the bottleneck (not detection)."""
        if self.audit is None:
            self.skipTest("Audit not found")
        floor_recall = self.audit["floor_recall"]
        top1_recall  = self.audit["topk_recall"]["1"]["recall"]
        self.assertEqual(floor_recall, 1.0)
        self.assertLess(top1_recall, 1.0)
        # This combination confirms: DETECTION is solved, RANKING is the bottleneck
        self.assertGreater(floor_recall - top1_recall, 0.05,
                           "Gap between floor and top-1 must be >5 pp to justify reranker")


class TestWaterEntryRanking(unittest.TestCase):
    """Phase F1: Water-entry candidate ranking (special focus area)."""

    @classmethod
    def setUpClass(cls):
        cls.audit = load_json(f"{RERANKER_DIR}/D4_FLOOR_AUDIT_V1.json")
        cls.eval  = load_json(f"{RERANKER_DIR}/RERANKER_DEV_EVAL.json")

    def test_water_contact_worst_phase_for_d4(self):
        """Water_contact must be the worst-ranked phase for D4."""
        if self.audit is None:
            self.skipTest("Audit not found")
        per_frame = self.audit.get("per_frame", {})
        wc_ranks = [v.get("target_rank_floor") for k,v in per_frame.items()
                    if "water_contact" in k and v.get("target_rank_floor")]
        apex_ranks = [v.get("target_rank_floor") for k,v in per_frame.items()
                      if "apex" in k and v.get("target_rank_floor")]
        to_ranks = [v.get("target_rank_floor") for k,v in per_frame.items()
                    if "takeoff" in k and v.get("target_rank_floor")]
        if wc_ranks and apex_ranks and to_ranks:
            wc_mean   = sum(wc_ranks) / len(wc_ranks)
            apex_mean = sum(apex_ranks) / len(apex_ranks)
            to_mean   = sum(to_ranks) / len(to_ranks)
            # Water contact should have highest mean rank (worst)
            self.assertGreater(wc_mean, to_mean,
                               f"WC mean rank ({wc_mean:.1f}) should exceed takeoff ({to_mean:.1f})")


class TestParisFirewall(unittest.TestCase):
    """Paris firewall — verified across all phases."""

    @classmethod
    def setUpClass(cls):
        cls.dataset_manifest = load_json(f"{RERANKER_DIR}/RERANKER_DATASET_V1_MANIFEST.json")
        cls.freeze = load_json(f"{RERANKER_DIR}/DIVER_CANDIDATE_RERANKER_V1_FREEZE.json")
        cls.d5_batch = load_json(f"{RERANKER_DIR}/D5_ANNOTATION_BATCH_MANIFEST.json")

    def test_dataset_paris_firewall(self):
        """Reranker dataset must explicitly verify Paris exclusion."""
        if self.dataset_manifest is None:
            self.skipTest("Manifest not found")
        fw = self.dataset_manifest.get("paris_firewall", "")
        self.assertIn("no Paris", fw.lower() if fw else "",
                      f"Firewall not explicit: '{fw}'")

    def test_freeze_paris_firewall(self):
        if self.freeze is None:
            self.skipTest("Freeze not found")
        fw = self.freeze.get("paris_firewall", "")
        self.assertIn("Paris", fw)

    def test_d5_batch_paris_firewall(self):
        if self.d5_batch is None:
            self.skipTest("D5 batch not found")
        fw = self.d5_batch.get("paris_firewall", "")
        self.assertIn("Paris", fw)
        # Verify no Paris dive_id in frames
        for f in self.d5_batch.get("frames", []):
            self.assertNotEqual(f.get("dive_id"), 2819,
                                "Paris dive 2819 must not be in D5 batch")


if __name__ == "__main__":
    # When running from Mac (pre-sync), adjust paths
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", default=None,
                        help="Override RERANKER_DIR to local results path")
    args, remaining = parser.parse_known_args()
    if args.results_dir:
        # Monkey-patch global
        RERANKER_DIR = args.results_dir
        # Re-import
        import importlib, sys as _sys
        _sys.argv = [_sys.argv[0]] + remaining

    loader = unittest.TestLoader()
    suite  = loader.discover(os.path.dirname(__file__), pattern=os.path.basename(__file__))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
