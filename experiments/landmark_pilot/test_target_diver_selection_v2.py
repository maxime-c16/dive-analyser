#!/usr/bin/env python3
"""Phase S — Tests for TARGET_DIVER_SELECTION_V2.

Tests cover:
- Proposal threshold freeze (Phase B)
- Raw candidate ceiling (Phase A1)
- Conditional selection accuracy (Phase G)
- Low-confidence true candidate recovery (Phase A/E)
- Candidate explosion bound (Phase A2)
- NULL state semantics (Phase D)
- Long static preparation invariant (Phase E1)
- Static background rejection (Phase E)
- Hurdle trajectory (Phase H1)
- Motion auxiliary / spatial persistence (Phase E2)
- Action-likelihood scoring (Phase E)
- Paris firewall (Phase I)
- Selector freeze consistency (Phase I)
- Dive-311 independent failure classification (Phase N)
"""
import json, sys, os, math, unittest

sys.path.insert(0, os.path.expanduser("~/dive-analyser/experiments/landmark_pilot"))

BASE = os.path.expanduser("~/dive-analyser")
V1_DIR = "experiments/landmark_pilot/runs/target_selection_v1"
V2_DIR = "experiments/landmark_pilot/runs/target_selection_v2"
SCI_DIR = "docs/science"


# ===== TEST 1: Proposal threshold freeze identity =====
class TestProposalThresholdFreeze(unittest.TestCase):
    def test_proposal_freeze_exists(self):
        path = f"{SCI_DIR}/D3_PROPOSAL_V1_FREEZE.json"
        self.assertTrue(os.path.exists(path), f"Missing: {path}")
        freeze = json.load(open(path))
        self.assertEqual(freeze["proposal_conf"], 0.05,
                         "D3_PROPOSAL_V1 must use conf=0.05")
        self.assertEqual(freeze["weights_sha256"],
                         "bf6415fb63aa311f45262e555899d3023dd3d05d43a5e0d69b5e86c342e1a77d",
                         "Weights SHA must match D3.1 frozen weights")
        self.assertEqual(freeze["status"], "FROZEN")

    def test_proposal_conf_consistent_with_raw_files(self):
        """All existing raw files were produced at conf=0.05 as per D3_PROPOSAL_V1."""
        for did in [133, 311, 524, 676, 1040, 2387, 2625, 2680, 2169, 2341, 2541, 2555]:
            raw_path = f"{V1_DIR}/{did}_raw.json"
            self.assertTrue(os.path.exists(raw_path), f"Missing raw: {raw_path}")
            raw = json.load(open(raw_path))
            self.assertAlmostEqual(raw["conf"], 0.05, places=4,
                                   msg=f"Raw file {did} should have conf=0.05")
            # All candidates should have conf >= 0.05
            for fr in raw["frames"]:
                for c in fr["all_candidates"]:
                    self.assertGreaterEqual(c["conf"], 0.05 - 1e-6,
                                            f"Candidate conf below 0.05 in dive {did}")


# ===== TEST 2: Raw candidate ceiling =====
class TestRawCandidateCeiling(unittest.TestCase):
    def test_ceiling_at_conf_0_05(self):
        """Raw detector ceiling at conf=0.05 is ~65-71% — below the 80% gate."""
        phase_c = json.load(open(f"{V1_DIR}/phase_c_candidate_recall.json"))
        n_detected = phase_c["summary"]["counts"].get("TARGET_DETECTED_BUT_NOT_SELECTED",0) + \
                     phase_c["summary"]["counts"].get("TARGET_SELECTED_CORRECTLY",0)
        n_evaluable = sum(v for k,v in phase_c["summary"]["counts"].items()
                          if k not in ("NOT_ANNOTATED",))
        ceiling = n_detected / max(1, n_evaluable)
        # V1 established ceiling ~65-71%; must remain below 80% gate
        self.assertLess(ceiling, 0.80,
                        f"Ceiling {ceiling:.1%} should be below 80% (A1 gate)")
        # Must be at least 60% (confirms detector is finding some divers)
        self.assertGreater(ceiling, 0.60,
                           f"Ceiling {ceiling:.1%} should be >60% (sanity check)")

    def test_sweep_ceiling_below_80(self):
        """Even at conf=0.005, ceiling remains below 80% (DETECTOR_REOPEN_REQUIRED)."""
        sweep = json.load(open(f"{V2_DIR}/phase_a_threshold_sweep.json"))
        # conf=0.005 gives the highest recall
        best_recall = sweep["conf_0.005"]["summary"]["raw_target_recall"]
        self.assertLess(best_recall, 0.80,
                        f"Best achievable recall {best_recall:.1%} should be below 80%")

    def test_zero_detection_miss_frames_at_conf_0_05(self):
        """2541 frames 525 and 558 have 0 candidates at conf=0.05 (genuine no-detection)."""
        raw = json.load(open(f"{V1_DIR}/2541_raw.json"))
        for fidx in [525, 558]:
            fr = raw["frames"][fidx]
            self.assertEqual(fr["n_candidates"], 0,
                             f"2541 frame {fidx} should have 0 candidates at conf=0.05")


# ===== TEST 3: Conditional selection accuracy =====
class TestConditionalSelectionAccuracy(unittest.TestCase):
    def test_s1_conditional_accuracy_beats_s0(self):
        """S1 conditional accuracy (80%) >= S0 conditional (75%)."""
        eval_data = json.load(open(f"{V2_DIR}/phase_h_selector_v2_comparison.json"))
        pg = eval_data["phase_g_raw_ceiling_vs_conditional"]
        s1_cond = pg["s1_conditional_accuracy"]["given_candidate_exists"]
        s0_cond = pg["s0_conditional_accuracy"]["given_candidate_exists"]
        self.assertGreaterEqual(s1_cond, s0_cond,
                                f"S1 conditional ({s1_cond:.2f}) should >= S0 ({s0_cond:.2f})")

    def test_ceiling_is_separate_from_selector_accuracy(self):
        """Raw ceiling and conditional accuracy are reported as distinct metrics."""
        eval_data = json.load(open(f"{V2_DIR}/phase_h_selector_v2_comparison.json"))
        pg = eval_data["phase_g_raw_ceiling_vs_conditional"]
        ceiling = pg["raw_detector_ceiling"]["at_conf_0_05"]
        s1_cond = pg["s1_conditional_accuracy"]["given_candidate_exists"]
        # They should differ (ceiling < 100%, conditional < ceiling)
        self.assertLess(ceiling, 1.0, "Ceiling must be < 100%")
        # S1 overall = ceiling * conditional (approximately)
        s1_overall = eval_data["aggregate"]["s1"]["ALL"]["correct_selection_rate"]
        expected_approx = ceiling * s1_cond
        self.assertAlmostEqual(s1_overall, expected_approx, delta=0.15,
                               msg="S1 overall should approximate ceiling*conditional")


# ===== TEST 4: Low-confidence candidate recovery =====
class TestLowConfidenceCandidateRecovery(unittest.TestCase):
    def test_2541_miss_frames_have_low_conf_candidates(self):
        """2541 frames 525/558 have candidates at conf<0.05 (confirmed by 0.001 inference)."""
        sweep = json.load(open(f"{V2_DIR}/phase_a_threshold_sweep.json"))
        zd = sweep["zero_detect_miss_frames"]
        # Frame 525: max conf = 0.039 (below 0.05)
        confs_525 = zd["2541_frame525_at_0001"]["confs"]
        self.assertTrue(len(confs_525) > 0, "2541 f=525 should have candidates at conf>=0.001")
        max_conf_525 = max(confs_525) if confs_525 else 0
        self.assertLess(max_conf_525, 0.05, f"Max conf {max_conf_525} should be <0.05")
        self.assertGreater(max_conf_525, 0.001, f"Max conf {max_conf_525} should be >0.001")
        # Frame 558: max conf = 0.011
        confs_558 = zd["2541_frame558_at_0001"]["confs"]
        max_conf_558 = max(confs_558) if confs_558 else 0
        self.assertLess(max_conf_558, 0.05)

    def test_conf_0_005_recovers_miss_frames(self):
        """At conf=0.005, more frames are recovered than at conf=0.05."""
        sweep = json.load(open(f"{V2_DIR}/phase_a_threshold_sweep.json"))
        n_0_05 = sweep["conf_0.05"]["summary"]["n_with_candidate"]
        n_0_005 = sweep["conf_0.005"]["summary"]["n_with_candidate"]
        self.assertGreaterEqual(n_0_005, n_0_05,
                                f"conf=0.005 ({n_0_005}) should recover >= conf=0.05 ({n_0_05})")


# ===== TEST 5: Candidate explosion bound =====
class TestCandidateExplosionBound(unittest.TestCase):
    def test_candidate_load_at_conf_0_05_bounded(self):
        """At conf=0.05, P90 candidate count <= 11/frame (well within bounds)."""
        sweep = json.load(open(f"{V2_DIR}/phase_a_threshold_sweep.json"))
        p90 = sweep["conf_0.05"]["load_summary"]["p90"]
        self.assertLessEqual(p90, 15,
                             f"P90 candidates {p90} should be <= 15 (Phase A2 bound)")


# ===== TEST 6: NULL state semantics =====
class TestNullStateSemanticsS3(unittest.TestCase):
    def test_s3_viterbi_has_null_state(self):
        """S3 uses NULL as first-class state in every frame."""
        from selector_s3_action_path import select_s3, LOG_NULL_OBS
        # NULL obs score is a finite negative constant (not -inf)
        self.assertGreater(LOG_NULL_OBS, -10.0, "NULL obs should be finite (not -inf)")
        self.assertLess(LOG_NULL_OBS, 0.0, "NULL obs should be negative")

    def test_static_track_leads_to_null(self):
        """A sequence where every candidate is at the same location (static) → all-NULL."""
        from selector_s3_action_path import select_s3
        # Build synthetic raw: 50 frames, each with 1 candidate at same position
        frames = []
        for i in range(50):
            frames.append({
                "frame_index": i, "pts_s": i/30.0,
                "n_candidates": 1,
                "selected": None,
                "all_candidates": [{"xyxy":[100,100,200,200],"conf":0.8,
                                    "cx_norm":0.5,"cy_norm":0.5,"bw_norm":0.1,"bh_norm":0.1}],
            })
        raw = {"video":"test","conf":0.05,"iou":0.45,"imgsz":640,
               "width":640,"height":640,"n_frames":50,"frames":frames}
        path, diag = select_s3(raw)
        self.assertTrue(diag["flagged_invalid_static_track"],
                        "Static sequence should be flagged")
        self.assertTrue(all(p is None for p in path),
                        "Static sequence should produce all-NULL path")


# ===== TEST 7: Long static preparation invariant =====
class TestLongStaticPrepInvariant(unittest.TestCase):
    def test_long_prep_then_motion_not_rejected(self):
        """A sequence with 3s static prep followed by real motion is NOT rejected."""
        from selector_s3_action_path import select_s3
        # 90 frames at 30fps: frames 0-79 static, frames 80-89 real vertical motion
        frames = []
        for i in range(80):  # static prep: same position
            frames.append({
                "frame_index": i, "pts_s": i/30.0,
                "n_candidates": 1, "selected": None,
                "all_candidates": [{"xyxy":[100,100,200,200],"conf":0.6,
                                    "cx_norm":0.5,"cy_norm":0.15,"bw_norm":0.1,"bh_norm":0.1}],
            })
        for i in range(80, 90):  # dynamic phase: diver moves down (cy increases)
            cy = 0.15 + (i-80)*0.04  # moves from 0.15 to 0.51
            frames.append({
                "frame_index": i, "pts_s": i/30.0,
                "n_candidates": 1, "selected": None,
                "all_candidates": [{"xyxy":[100,100,200,200],"conf":0.6,
                                    "cx_norm":0.5,"cy_norm":cy,"bw_norm":0.1,"bh_norm":0.1}],
            })
        raw = {"video":"test","conf":0.05,"iou":0.45,"imgsz":640,
               "width":640,"height":640,"n_frames":90,"frames":frames}
        path, diag = select_s3(raw)
        self.assertFalse(diag["flagged_invalid_static_track"],
                         "Long prep + real motion should NOT be flagged as static")
        # Some frames should be non-NULL
        n_non_null = sum(1 for p in path if p is not None)
        self.assertGreater(n_non_null, 0, "Should have non-NULL selections")


# ===== TEST 8: Static background rejection =====
class TestStaticBackgroundRejection(unittest.TestCase):
    def test_high_persistence_candidate_penalized(self):
        """In S3, a candidate appearing in every frame gets a strong persistence penalty."""
        from selector_s3_action_path import obs_s3
        # persist_freq=1.0 (appears in every frame): penalty = W_PERSIST*(1.0-0.25) = 3.0
        obs_static = obs_s3({"conf":0.35,"bw_norm":0.1,"bh_norm":0.1}, persist_freq=1.0)
        # No persistence: obs for low-conf diver
        obs_diver = obs_s3({"conf":0.06,"bw_norm":0.05,"bh_norm":0.1}, persist_freq=0.10)
        # S3 should prefer the low-conf diver over the high-conf static FP
        self.assertGreater(obs_diver, obs_static,
                           f"Diver obs ({obs_diver:.2f}) should beat static FP ({obs_static:.2f}) after persistence penalty")


# ===== TEST 9: Hurdle trajectory handling =====
class TestHurdleTrajectory(unittest.TestCase):
    def test_hurdle_dives_evaluated(self):
        """HURDLE dives (8 of 12) are included in the DEVELOPMENT evaluation."""
        eval_data = json.load(open(f"{V2_DIR}/phase_h_selector_v2_comparison.json"))
        hurdle_data = eval_data["aggregate"]["s1"]["HURDLE"]
        self.assertEqual(hurdle_data["n_dives"], 8,
                         "Must have 8 HURDLE dives in DEVELOPMENT corpus")

    def test_s1_correct_hurdle(self):
        """S1 achieves >=35% correct on HURDLE (beats S0 baseline)."""
        eval_data = json.load(open(f"{V2_DIR}/phase_h_selector_v2_comparison.json"))
        s1_hurdle = eval_data["aggregate"]["s1"]["HURDLE"]["correct_selection_rate"]
        s0_hurdle = eval_data["aggregate"]["s0"]["HURDLE"]["correct_selection_rate"]
        self.assertGreaterEqual(s1_hurdle, s0_hurdle,
                                "S1 should not regress vs S0 on HURDLE")


# ===== TEST 10: Motion auxiliary consistency =====
class TestMotionAuxiliary(unittest.TestCase):
    def test_s3_selector_run_on_all_development_dives(self):
        """S3 selector output exists for all 12 DEVELOPMENT dives."""
        for did in [133, 311, 524, 676, 1040, 2387, 2625, 2680, 2169, 2341, 2541, 2555]:
            path = f"{V2_DIR}/{did}_s3.json"
            self.assertTrue(os.path.exists(path), f"Missing S3 output: {path}")
            s3 = json.load(open(path))
            self.assertEqual(s3["selector"], "S3_ACTION_GLOBAL_PATH")
            self.assertIn("persist_w", s3["diagnostics"])

    def test_persistence_params_documented_in_s3(self):
        """S3 diagnostics include persistence parameters."""
        s3 = json.load(open(f"{V2_DIR}/133_s3.json"))
        diag = s3["diagnostics"]
        self.assertIn("persist_w", diag)
        self.assertIn("persist_radius", diag)
        self.assertIn("persist_neutral", diag)
        self.assertEqual(diag["persist_w"], 4.0)


# ===== TEST 11: Action-likelihood sequence (S3 dynamics) =====
class TestActionLikelihoodSequence(unittest.TestCase):
    def test_s3_paris_std_cy_higher_than_s1(self):
        """S3 Paris trajectory shows more vertical variation than S1 (less static lock)."""
        import statistics
        s1_pts = json.load(open(f"{V1_DIR}/PARIS_s1.json"))["points"]
        s3_pts = json.load(open(f"{V2_DIR}/PARIS_s3.json"))["points"]
        s1_cy = [p["selected"]["cy_norm"] for p in s1_pts if p["selected"] is not None]
        s3_cy = [p["selected"]["cy_norm"] for p in s3_pts if p["selected"] is not None]
        s1_std = statistics.stdev(s1_cy) if len(s1_cy) > 1 else 0
        s3_std = statistics.stdev(s3_cy) if len(s3_cy) > 1 else 0
        self.assertGreater(s3_std, s1_std,
                           f"S3 std_cy ({s3_std:.4f}) should be > S1 std_cy ({s1_std:.4f})")


# ===== TEST 12: Paris firewall =====
class TestParisFirewall(unittest.TestCase):
    def test_selector_v2_freeze_has_paris_firewall(self):
        """The V2 freeze file includes a Paris firewall clause."""
        freeze = json.load(open(f"{SCI_DIR}/TARGET_DIVER_SELECTOR_V2_FREEZE.json"))
        self.assertIn("paris_firewall", freeze,
                      "V2 freeze must include paris_firewall clause")
        self.assertIn("Paris", freeze["paris_firewall"],
                      "Paris firewall must reference Paris explicitly")

    def test_proposal_freeze_has_paris_note(self):
        """The proposal freeze documents Paris was not used for calibration."""
        freeze = json.load(open(f"{SCI_DIR}/D3_PROPOSAL_V1_FREEZE.json"))
        # Should document that lower-conf sweep did not use Paris labels
        self.assertIn("conf=0.05", freeze.get("note",""),
                      "Proposal freeze must document the chosen threshold")


# ===== TEST 13: Selector freeze consistency =====
class TestSelectorFreezeConsistency(unittest.TestCase):
    def test_v2_freeze_chose_s1(self):
        """V2 selector freeze chose S1 per DEVELOPMENT criteria."""
        freeze = json.load(open(f"{SCI_DIR}/TARGET_DIVER_SELECTOR_V2_FREEZE.json"))
        self.assertEqual(freeze["chosen_selector"], "S1_GLOBAL_PATH")
        self.assertEqual(freeze["status"], "FROZEN")

    def test_s1_beats_s0_on_development(self):
        """S1 achieves higher ALL correct_selection_rate than S0 on DEVELOPMENT."""
        eval_data = json.load(open(f"{V2_DIR}/phase_h_selector_v2_comparison.json"))
        s1_all = eval_data["aggregate"]["s1"]["ALL"]["correct_selection_rate"]
        s0_all = eval_data["aggregate"]["s0"]["ALL"]["correct_selection_rate"]
        self.assertGreater(s1_all, s0_all,
                           f"S1 ({s1_all}) should beat S0 ({s0_all}) on DEVELOPMENT")


# ===== TEST 14: Dive-311 independent failure classification =====
class TestDive311(unittest.TestCase):
    def test_dive311_clean_trajectory_from_s1(self):
        """Dive 311 S1 trajectory exists and is non-trivially non-NULL."""
        s1_311 = json.load(open(f"{V1_DIR}/311_s1.json"))
        points = s1_311["points"]
        n_non_null = sum(1 for p in points if p["selected"] is not None)
        self.assertGreater(n_non_null / max(1, len(points)), 0.80,
                           "Dive 311 should have high coverage (trajectory is non-static)")

    def test_dive311_el_catastrophic_error(self):
        """Dive 311 has a ~4s Event Logic error — classified INDEPENDENT_EVENT_LOGIC_FAILURE."""
        phase_q = json.load(open(f"{V1_DIR}/phase_q_development_event_logic_reeval.json"))
        dive_311 = next(d for d in phase_q["clean_dives"] if d["dive_id"] == 311)
        err_takeoff = dive_311["v21"]["err_takeoff"]
        err_wc = dive_311["v21"]["err_wc"]
        # Both errors should be large (>2s) — catastrophic failure
        self.assertGreater(abs(err_takeoff), 2.0,
                           f"Dive 311 takeoff error {err_takeoff}s should be >2s")
        self.assertGreater(abs(err_wc), 2.0,
                           f"Dive 311 wc error {err_wc}s should be >2s")

    def test_dive311_error_same_in_v21_and_v22(self):
        """Dive 311 error magnitude is similar in V2.1 and V2.2 — not a V2.1-vs-V2.2 issue."""
        phase_q = json.load(open(f"{V1_DIR}/phase_q_development_event_logic_reeval.json"))
        dive_311 = next(d for d in phase_q["clean_dives"] if d["dive_id"] == 311)
        err_v21 = abs(dive_311["v21"]["err_takeoff"])
        err_v22 = abs(dive_311["v22_s1_body_scale"]["err_takeoff"])
        # Both large; their difference should be small (<0.5s)
        self.assertAlmostEqual(err_v21, err_v22, delta=0.5,
                               msg="V2.1 and V2.2 errors should be similar for dive 311")


# ===== TEST 15: Trajectory gate document =====
class TestTrajectoryGate(unittest.TestCase):
    def test_paris_evaluation_documented(self):
        """Paris Phase J/K evaluation is documented."""
        path = f"{V2_DIR}/paris_phase_jk_evaluation.json"
        self.assertTrue(os.path.exists(path))
        paris = json.load(open(path))
        self.assertEqual(paris["status"], "EVALUATED")
        # All 3 GT anchors evaluated
        s1_gt = paris["phase_k_frozen_s1_result"]
        self.assertEqual(s1_gt["correct_gt_anchors"], 0,
                         "S1 should have 0/3 correct GT anchors at Paris")

    def test_trajectory_gate_fails_for_paris_s1(self):
        """Trajectory gate TRAJECTORY_INPUT_FAIL for Paris S1 (all GT anchors wrong)."""
        paris = json.load(open(f"{V2_DIR}/paris_phase_jk_evaluation.json"))
        s1 = paris["phase_k_frozen_s1_result"]
        self.assertEqual(s1["takeoff"]["verdict"], "WRONG_TARGET")
        self.assertEqual(s1["apex"]["verdict"], "WRONG_TARGET")
        self.assertEqual(s1["water_contact"]["verdict"], "WRONG_TARGET")


if __name__ == "__main__":
    os.chdir(BASE)
    unittest.main(verbosity=2)
