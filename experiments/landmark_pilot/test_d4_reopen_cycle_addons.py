#!/usr/bin/env python3
"""Additional Phase S tests for D4 reopen cycle — appended to test_detector_d4_reopen.py.

Covers: D4 proposal freeze, Paris D4 eval, selector revalidation (Phase M),
selector freeze D4 (Phase N), PARIS_FIREWALL integrity, grouped eval sanity.
"""
import json, sys, os, unittest

sys.path.insert(0, os.path.expanduser("~/dive-analyser/experiments/landmark_pilot"))

BASE = os.path.expanduser("~/dive-analyser")
SCI_DIR = f"{BASE}/docs/science"
SCRATCHPAD_LOCAL = "/private/tmp/claude-501/-Users-maximecauchy--perso-diveanalyzer/30aea248-b1dc-4e96-a516-7c1a3d5d757b/scratchpad"

PARIS_KEY = "d122262be8e7a8721ab2f6a71721bb3544403da78324138d026360ef9820eaae"


# ===== D4 PROPOSAL FREEZE =====

class TestD4ProposalFreeze(unittest.TestCase):
    """Phase H1/I — D4 proposal freeze integrity."""

    def _load(self):
        path = f"{SCI_DIR}/D4_PROPOSAL_V1_FREEZE.json"
        if not os.path.exists(path):
            self.skipTest("D4_PROPOSAL_V1_FREEZE.json not found")
        return json.load(open(path))

    def test_freeze_exists(self):
        self.assertTrue(os.path.exists(f"{SCI_DIR}/D4_PROPOSAL_V1_FREEZE.json"))

    def test_freeze_status_frozen(self):
        d = self._load()
        self.assertEqual(d["status"], "FROZEN")

    def test_d4_weights_sha_documented(self):
        d = self._load()
        sha = d.get("weights_sha256", "")
        self.assertEqual(len(sha), 64, "D4 weights SHA must be 64-char hex")
        self.assertEqual(sha, "842291f1cd3c5ad086faa467ccaac197c56bdd63dcdd2b67a91c4a7d8fbc3aaa",
                         "D4 weights SHA must match canonical value")

    def test_op_threshold_is_0_05(self):
        d = self._load()
        self.assertAlmostEqual(d["operating_threshold"], 0.05, places=3)

    def test_d4_recall_greater_than_d3(self):
        d = self._load()
        self.assertGreater(d["raw_target_candidate_recall_canonical"],
                           d["vs_d3"]["d3_recall"],
                           "D4 recall must exceed D3 recall")

    def test_zero_regressions_vs_d3(self):
        d = self._load()
        self.assertEqual(d["vs_d3"]["regressions"], 0,
                         "D4 must not regress any D3 hits")

    def test_phase_h1_gate_documented(self):
        d = self._load()
        self.assertIn("phase_h1_gate", d)
        self.assertEqual(d["phase_h1_gate"], "FAIL",
                         "Phase H1 gate must be FAIL (D4 80.6% < 90% threshold)")

    def test_paris_firewall_declared(self):
        d = self._load()
        self.assertIn("paris_firewall", d)
        fw = d["paris_firewall"].upper()
        self.assertTrue("PARIS" in fw or "EXCLUDED" in fw or "VERIFIED" in fw or "FIREWALL" in fw,
                        f"D4 freeze must declare paris_firewall; got: {d['paris_firewall']}")


# ===== D4 GROUPED EVAL =====

class TestD4GroupedEval(unittest.TestCase):
    """Phase H — grouped evaluation consistency."""

    def _load(self):
        path = f"{SCI_DIR}/D4_GROUPED_EVAL_V1.json"
        if not os.path.exists(path):
            self.skipTest("D4_GROUPED_EVAL_V1.json not found")
        return json.load(open(path))

    def test_eval_file_exists(self):
        self.assertTrue(os.path.exists(f"{SCI_DIR}/D4_GROUPED_EVAL_V1.json"))

    def test_canonical_denominator(self):
        d = self._load()
        self.assertEqual(d["canonical_denominator"], 31)

    def test_d4_recall_80_6_percent(self):
        d = self._load()
        recall = d["raw_target_candidate_recall"]
        self.assertAlmostEqual(recall, 0.806, places=2,
                               msg="D4 recall must be ~80.6% (25/31)")

    def test_no_regressions(self):
        d = self._load()
        self.assertEqual(len(d.get("regressions_vs_d3", [])), 0,
                         "D4 must have zero regressions vs D3")


# ===== PARIS D4 EVAL =====

class TestParisD4Eval(unittest.TestCase):
    """Phase J/K — Paris external canary evaluation with D4."""

    def _load(self):
        path = f"{SCI_DIR}/PARIS_D4_EVAL.json"
        if not os.path.exists(path):
            self.skipTest("PARIS_D4_EVAL.json not found")
        return json.load(open(path))

    def test_paris_eval_exists(self):
        self.assertTrue(os.path.exists(f"{SCI_DIR}/PARIS_D4_EVAL.json"))

    def test_paris_3_of_3_phases_covered(self):
        d = self._load()
        self.assertEqual(d["phases_covered"], 3,
                         "D4 must cover all 3 Paris phases (historic first vs D3)")

    def test_paris_takeoff_match(self):
        d = self._load()
        takeoff = d["phase_results"]["takeoff"]
        iou = takeoff.get("iou_with_gt", 0)
        self.assertGreaterEqual(iou, 0.30, f"Paris takeoff IoU={iou:.3f} < 0.30")

    def test_paris_media_key_not_in_d4_training(self):
        """Paris media key must not appear in any D4 training annotation."""
        # Check D4 manifest
        manifest_path = f"{SCI_DIR}/DATASET_D4_MANIFEST.json"
        if os.path.exists(manifest_path):
            m = json.load(open(manifest_path))
            content = json.dumps(m)
            self.assertNotIn(PARIS_KEY, content,
                             "Paris media key found in D4 dataset manifest!")

    def test_paris_improves_without_paris_training(self):
        d = self._load()
        finding = d.get("finding", "")
        self.assertIn("IMPROVES", finding,
                      "Paris D4 eval must document the improvement finding")


# ===== SELECTOR REVALIDATION D4 (Phase M) =====

class TestSelectorRevalidationD4(unittest.TestCase):
    """Phase M — selector revalidation with D4 proposals."""

    def _load(self):
        path = f"{SCI_DIR}/SELECTOR_REVALIDATION_D4.json"
        if not os.path.exists(path):
            self.skipTest("SELECTOR_REVALIDATION_D4.json not found")
        return json.load(open(path))

    def test_reval_file_exists(self):
        self.assertTrue(os.path.exists(f"{SCI_DIR}/SELECTOR_REVALIDATION_D4.json"),
                        "SELECTOR_REVALIDATION_D4.json must exist after Phase M")

    def test_gate_result_documented(self):
        d = self._load()
        self.assertIn("selectors_passing_gate", d)

    def test_gate_threshold_is_0_80(self):
        d = self._load()
        self.assertAlmostEqual(d["gate_threshold"], 0.80, places=2)

    def test_s0_outperforms_s1_with_d4(self):
        d = self._load()
        s0 = d["results"]["S0"]["accuracy"]
        s1 = d["results"]["S1"]["accuracy"]
        self.assertGreater(s0, s1, "S0 must outperform S1 with D4 proposals")

    def test_s1_regression_documented(self):
        """S1 Viterbi was better in V2; must now show regression with D4."""
        d = self._load()
        s1_acc = d["results"]["S1"]["accuracy"]
        # S1 with D4 is ~61%, below its V2 value of 80%
        self.assertLess(s1_acc, 0.80,
                        "S1 with D4 must be below 0.80 (regression vs V2)")

    def test_s3_status_hypothesis_only(self):
        d = self._load()
        s3 = d["results"]["S3"]
        self.assertEqual(s3.get("status"), "HYPOTHESIS_ONLY")

    def test_development_dives_count(self):
        d = self._load()
        self.assertEqual(len(d["development_dives"]), 12,
                         "Must evaluate on all 12 DEVELOPMENT dives")

    def test_gate_fail_all_selectors(self):
        """Phase M gate (80%) fails — all selectors are below."""
        d = self._load()
        passing = d.get("selectors_passing_gate", [])
        self.assertEqual(len(passing), 0,
                         f"Gate must FAIL: no selector reaches 80%. Passing: {passing}")


# ===== SELECTOR FREEZE D4 (Phase N) =====

class TestSelectorFreezeD4(unittest.TestCase):
    """Phase N — D4-era selector freeze."""

    def _load(self):
        path = f"{SCI_DIR}/SELECTOR_FREEZE_D4.json"
        if not os.path.exists(path):
            self.skipTest("SELECTOR_FREEZE_D4.json not found")
        return json.load(open(path))

    def test_freeze_file_exists(self):
        self.assertTrue(os.path.exists(f"{SCI_DIR}/SELECTOR_FREEZE_D4.json"),
                        "SELECTOR_FREEZE_D4.json must exist after Phase N")

    def test_frozen_selector_is_s0(self):
        d = self._load()
        self.assertEqual(d["frozen_selector"], "S0",
                         "D4-era canonical selector must be S0 (top-conf)")

    def test_status_frozen(self):
        d = self._load()
        self.assertEqual(d["status"], "FROZEN")

    def test_paris_trajectory_still_fails(self):
        """Switching from S1 to S0 must not change the Paris trajectory result."""
        d = self._load()
        paris = d.get("phase_o_paris_with_s0", {})
        self.assertEqual(paris.get("paris_trajectory"), "TRAJECTORY_INPUT_FAIL",
                         "Paris must still be TRAJECTORY_INPUT_FAIL with S0")

    def test_s1_regression_root_cause_documented(self):
        d = self._load()
        finding = d.get("vs_v2_frozen_selector", {}).get("finding", "")
        self.assertIn("REGRESS", finding,
                      "Must document S1_REGRESSES_WITH_D4 finding")


if __name__ == "__main__":
    unittest.main(verbosity=2)
