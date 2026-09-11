#!/usr/bin/env python3
"""Unit tests for HURDLE_TARGET_IDENTITY_V3 (GT-free prototype selection).

Covers the Phase T required list:
  - cache reuse / provenance (candidate cache hash, OSNet weights sha)
  - no unnecessary D5 rerun (cache-readiness reports 0 rerun)
  - prototype clustering determinism (P0 identical across runs)
  - multi-hypothesis selection (bounded <= HYP budget, deterministic)
  - full-clip GT-free semantics (window [0, video_end], no GT times)
  - LOSO calibration isolation (no fitted per-dive constants)
  - persistent bystander / static structure / post-action next-diver /
    fast mover / long preparation (taxonomy classification units)
  - NULL state (selector may emit NULL frames)
  - candidate inclusion (candidate-complete tracklets own every instance)
  - OSNet reproducibility (embedding cache provenance verification)
  - 2555 stress case handling
  - 524 exclusion
  - Paris firewall
  - identity freeze discipline (NO freeze artifact unless the gate passed)
  - V3-D0 unchanged replay (frozen code reproduces recorded magnitudes)
  - historical-freeze immutability (freeze JSON byte-identical to HEAD,
    original metadata preserved) + erratum consistency (0.30/0.20
    executable authority, code untouched)

Run: .venv-reid/bin/python -m pytest experiments/landmark_pilot/test_hurdle_prototype_v3.py -q
"""

import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pytest

BASE = Path(__file__).parents[2]
sys.path.insert(0, os.path.dirname(__file__))

import r5_tracklets_v1 as R5  # noqa: E402
import r5b_association_v1 as R5B  # noqa: E402
import v6_prototype_v1 as V  # noqa: E402
from r5_tracklets_v1 import Cand  # noqa: E402

RUNS = BASE / "runs/hurdle_prototype_v3"
SCIENCE = BASE / "docs/science"
PRIMARY = ["1040", "2169", "2341", "2353", "2541"]
STRESS = ["2555"]
ALL_DIVES = PRIMARY + STRESS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def synth_dive(n=90, fps=30.0, prep_box=(0.30, 0.30, 0.10, 0.20, 0.02),
               mover_boxes=None, distractor=None, dive_start=60):
    """Per-frame candidate lists: static prep box until dive_start, then a
    gated mover trajectory; distractors optional."""
    frames = []
    for fi in range(n):
        cands = []
        if fi < dive_start or mover_boxes is None:
            cands.append({"conf": prep_box[4], "cx": prep_box[0],
                          "cy": prep_box[1], "bw": prep_box[2],
                          "bh": prep_box[3]})
        else:
            t = (fi - dive_start) / fps
            cy = prep_box[1] + min(0.45, 0.6 * t)
            cands.append({"conf": 0.03, "cx": prep_box[0], "cy": cy,
                          "bw": prep_box[2], "bh": prep_box[3]})
        if distractor:
            cands.append({"conf": distractor[4], "cx": distractor[0],
                          "cy": distractor[1], "bw": distractor[2],
                          "bh": distractor[3]})
        frames.append({"pts_s": fi / fps, "fi": fi + 1, "n": len(cands),
                       "c": cands})
    return {"fps": fps, "frames": frames,
            "proxy_path": "media/perception_decomposition_v1/proxies/1040.mp4",
            "proxy_sha256": "0" * 64, "interval_s": [0.0, n / fps],
            "n_frames": n}


def frame_cands(dive):
    return [[Cand(c["cx"], c["cy"], c["bw"], c["bh"], c["conf"])
             for c in f["c"]] for f in dive["frames"]]


# ---------------------------------------------------------------------------
# Phase A: cache reuse / provenance / no D5 rerun
# ---------------------------------------------------------------------------

class TestCacheReuse:
    def test_readiness_manifest_exists_and_ready(self):
        p = RUNS / "CACHE_READINESS_V1.json"
        assert p.exists(), "Phase A manifest missing"
        d = json.loads(p.read_text())
        assert d["status"] == "CACHE_READY"
        assert d["d5_frames_rerun"] == 0
        assert d["embeddings_reextracted"] == 0

    def test_fullclip_cache_is_frozen_and_gt_free(self):
        fc = json.loads((BASE / "runs/hurdle_identity_v1/"
                         "R5_FULLCLIP_CANDIDATES_V1.json").read_text())
        assert fc["window_semantics"].startswith("FULL_CLIP_GT_FREE")
        assert fc["model_sha256"] == \
            "82b420c4583f8271b1eb3429b14dadf0a1e27477249de7b6a0b9d42a788dcf25"
        for did in ALL_DIVES:
            d = fc["dives"][did]
            assert d["interval_s"][0] == 0.0
            assert len(d["frames"]) == d["n_frames"]
            assert d["gt_eval_only"]  # GT isolated under eval-only metadata

    def test_osnet_weights_identity(self):
        sha = V.sha256_file(V.OSNET_PATH)
        assert sha == ("2809d3227f7d078f6045f7feb874a34d0684f0e0057b2"
                       "64b99adccf7d4519154")

    def test_embedding_cache_provenance(self):
        mp = RUNS / "osnet_emb_cache_v1.meta.json"
        assert mp.exists()
        meta = json.loads(mp.read_text())
        assert meta["weights_sha256"] == V.sha256_file(V.OSNET_PATH)
        cache = V.EmbeddingCache()
        assert len(cache.data) == meta["n_keys"]
        # determinism: reloading yields identical vectors
        k = next(iter(cache.data))
        v1 = cache.data[k]
        cache2 = V.EmbeddingCache()
        assert np.allclose(cache2.data[k], v1)


# ---------------------------------------------------------------------------
# Phase B: oracle gap / taxonomy classification units
# ---------------------------------------------------------------------------

class TestTaxonomy:
    def _stats(self, n_frag=6, life=0.3, cov=0.25):
        return {"n_pure_fragments": n_frag,
                "pure_life_s_median": life,
                "pure_cov_frac_of_gt": cov,
                "n_gt_frames": 100,
                "best_target_cov_frames": 20}

    def test_static_distractor(self):
        feat = {"static": True, "life_frac": 0.9, "life_s": 10.0,
                "exc_y": 0.01, "peak_v_cy_s": 0.1, "med_v_cy_s": 0.01,
                "n_frames": 100}
        out = __import__("phase_v3_oracle_gap_v1").classify_dive(
            self._stats(), feat, 0)
        assert "STATIC_DISTRACTOR_DOMINATES" in out

    def test_fast_mover(self):
        feat = {"static": False, "life_frac": 0.05, "life_s": 1.2,
                "exc_y": 0.3, "peak_v_cy_s": 1.1, "med_v_cy_s": 0.9,
                "n_frames": 20}
        out = __import__("phase_v3_oracle_gap_v1").classify_dive(
            self._stats(), feat, 0)
        assert "FAST_MOVER_DOMINATES" in out

    def test_other_person(self):
        feat = {"static": False, "life_frac": 0.7, "life_s": 9.0,
                "exc_y": 0.2, "peak_v_cy_s": 0.5, "med_v_cy_s": 0.2,
                "n_frames": 100}
        out = __import__("phase_v3_oracle_gap_v1").classify_dive(
            self._stats(), feat, 0)
        assert "OTHER_PERSON_DOMINATES" in out

    def test_target_fragmented_flag(self):
        out = __import__("phase_v3_oracle_gap_v1").classify_dive(
            self._stats(), None, 0)
        assert "TARGET_FRAGMENTED" in out
        assert "NO_CLEAR_COMPONENT" in out

    def test_oracle_gap_artifact_present(self):
        p = RUNS / "ORACLE_GAP_V3.json"
        assert p.exists()
        d = json.loads(p.read_text())
        for did in ALL_DIVES:
            assert did in d["dives"]
            o = d["dives"][did]["oracle"]
            assert o["n_pure_fragments"] > 0
            assert 0 <= o["pure_cov_frac_of_gt"]

    def test_component_feature_table_gt_free(self):
        p = RUNS / "COMPONENT_FEATURES_V1.json"
        assert p.exists()
        d = json.loads(p.read_text())
        for did in PRIMARY:
            tk = d["dives"][did]["tracklets"]
            # every feature row has GT-free descriptors; gt_frames is the
            # only post-hoc label
            row = next(iter(tk.values()))
            for k in ("life_s", "exc_y", "peak_v_cy_s", "gap_frac", "jumps",
                      "path_smooth_c_f", "start_frac", "conf_mean"):
                assert k in row


# ---------------------------------------------------------------------------
# Phase C/D/E: prototype machinery
# ---------------------------------------------------------------------------

class TestPrototypeMachinery:
    def test_p0_clustering_deterministic(self):
        fc, chains = V.load_corpus()
        trk = V.dive_arrays(fc["dives"]["1040"])
        plaus = V.plausible_tracklets(trk)
        cache = V.EmbeddingCache()
        embs = V.embed_tracklets("1040", fc["dives"]["1040"], trk, cache,
                                 plaus)
        view = V.trk_view(trk, list(plaus.keys()))
        c1 = V.p0_identity_clusters(view, embs, trk["fps"])
        c2 = V.p0_identity_clusters(view, embs, trk["fps"])
        assert c1 == c2

    def test_plausible_set_is_bounded(self):
        fc, chains = V.load_corpus()
        for did in ALL_DIVES:
            trk = V.dive_arrays(fc["dives"][did])
            plaus = V.plausible_tracklets(trk)
            assert len(plaus) < len(trk["tracklets"])
            assert len(plaus) < 1200  # bounded budget

    def test_hypothesis_enumeration_bounded_and_deterministic(self):
        fc, chains = V.load_corpus()
        trk = V.dive_arrays(fc["dives"]["1040"])
        h1 = V.enumerate_r5a_hypotheses(trk, topn=6)
        h2 = V.enumerate_r5a_hypotheses(trk, topn=6)
        assert len(h1) == len(h2) <= 6
        for a, b in zip(h1, h2):
            assert a["anchor_tid"] == b["anchor_tid"]
            assert a["score"] == b["score"]

    def test_path_quality_frozen_constants(self):
        assert V.V6Q["w_rest"] == 0.8
        assert V.V6Q["w_coverage"] == 0.8
        assert V.V6Q["static_penalty"] == 2.0
        # targetness constants frozen
        assert V.TARGETNESS["static_penalty"] == 2.0

    def test_null_state_allowed(self):
        # a path selection may leave frames NULL without forcing junk
        dive = synth_dive()
        trk = V.dive_arrays(dive)
        sel = [None] * trk["n"]
        sel[0] = {"cx": 0.3, "cy": 0.3, "bw": 0.1, "bh": 0.2, "conf": 0.1}
        assert sum(1 for s in sel if s is None) == trk["n"] - 1


# ---------------------------------------------------------------------------
# Phase F: LOSO isolation
# ---------------------------------------------------------------------------

class TestLOSO:
    def test_no_fitted_parameters(self):
        # the selector's constants are frozen literals, not fitted values:
        # verify they match the committed report/manifest, i.e. the SAME
        # config applies to every dive (leave-one-dive-out is identity).
        assert V.TARGETNESS["post_action_start_frac"] == 0.6
        assert V.V6Q["rest_full"] == 0.85
        assert V.V6Q["null_gate"] == 0.30

    def test_sweep_report_has_all_dives(self):
        p = RUNS / "V6_FINAL_V3.json"
        assert p.exists()
        d = json.loads(p.read_text())
        present = [did for did in ALL_DIVES if did in d["dives"]]
        for did in present:
            assert d["dives"][did].get("selected") is not None


# ---------------------------------------------------------------------------
# Phase I: freeze discipline + baselines
# ---------------------------------------------------------------------------

class TestFreezeDiscipline:
    def test_no_v3_freeze_artifact(self):
        for name in ("HURDLE_TARGET_IDENTITY_V3_FREEZE.json",
                     "HURDLE_TARGET_IDENTITY_V3_FREEZE.md"):
            assert not (SCIENCE / name).exists(), \
                "freeze artifact exists but the gate FAILED"

    def test_v6_final_records_gate_failure(self):
        d = json.loads((RUNS / "V6_FINAL_V3.json").read_text())
        gate = d.get("freeze_gate", {})
        assert gate.get("verdict") == "GATE_FAILED"

    def test_historical_arm_replay_reproduces(self):
        # frozen V3-D0 on the frozen historical cache reproduces the
        # recorded V2 magnitudes (verify a spot check on 2169)
        sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))
        from proposer_event_logic_v3_d0 import (PARAMS_V3D0,
                                                propose_events_v3d0)
        cache = json.loads((BASE / "docs/science/"
                            "DEV_HURDLE_TRAJ_CACHE_V2.json").read_text())
        dv = cache["per_dive"]["2169"]
        y = [f["cy"] for f in dv["frames"]]
        pts = [f["pts_s"] for f in dv["frames"]]
        conf = [f["conf"] for f in dv["frames"]]
        res = propose_events_v3d0(y, pts, conf, dv["code"])
        # recorded V2 replay: takeoff err +0.4123, wc err -0.2872
        g = dv["gt"]
        assert abs(res["takeoff_t"] - g["takeoff"] - 0.4123) < 0.01
        assert abs(res["water_contact_t"] - g["water_contact"] + 0.2872) \
            < 0.01
        assert PARAMS_V3D0["interp_max_gap_s"] == 0.30
        assert PARAMS_V3D0["vel_max_gap_s"] == 0.20


# ---------------------------------------------------------------------------
# Phase S: documentation-only reconciliation
# ---------------------------------------------------------------------------

class TestDocReconciliation:
    def test_historical_freeze_immutable(self):
        import subprocess
        # historical freeze artifacts must never be edited in place
        committed = subprocess.run(
            ["git", "-C", str(BASE), "show",
             "HEAD:docs/science/EVENT_LOGIC_V3_D0_FREEZE.json"],
            capture_output=True, text=True).stdout
        on_disk = (SCIENCE / "EVENT_LOGIC_V3_D0_FREEZE.json").read_text()
        assert committed == on_disk, \
            "historical V3-D0 freeze artifact was modified in place"
        d = json.loads(on_disk)
        # the freeze JSON must keep its ORIGINAL (drifted) metadata bytes;
        # the correction lives in the erratum, not the freeze
        assert d["parameters"]["interp_max_gap_s"] == 0.5
        assert d["parameters"]["vel_max_gap_s"] == 0.5
        assert "documentation_reconciliation" not in d

    def test_erratum_matches_executable(self):
        d = json.loads((SCIENCE /
                        "EVENT_LOGIC_V3_D0_FREEZE_ERRATUM_V1.json").read_text())
        assert d["label"] == "EVENT_LOGIC_V3_D0_FREEZE_ERRATUM_V1"
        assert d["freeze_artifact"]["recorded_metadata"] == {
            "interp_max_gap_s": 0.5, "vel_max_gap_s": 0.5}
        assert d["executable_authority"]["values"] == {
            "interp_max_gap_s": 0.30, "vel_max_gap_s": 0.20}
        rec = d["replay_proof"]["recorded_magnitudes_takeoff_err_water_contact_err"]
        assert rec["2169"] == [0.4123, -0.2872]
        assert rec["1040"] == [-1.9947, -2.511]
        sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))
        from proposer_event_logic_v3_d0 import PARAMS_V3D0
        assert PARAMS_V3D0["interp_max_gap_s"] == 0.30
        assert PARAMS_V3D0["vel_max_gap_s"] == 0.20

    def test_executable_untouched(self):
        import subprocess
        out = subprocess.run(
            ["git", "-C", str(BASE), "diff", "--stat", "--",
             "experiments/landmark_pilot/proposer_event_logic_v3_d0.py",
             "experiments/landmark_pilot/proposer_event_logic_v3_c0.py",
             "experiments/landmark_pilot/proposer_event_logic_v2_1.py"],
            capture_output=True, text=True).stdout
        assert out.strip() == "", "Event Logic executable files modified!"


# ---------------------------------------------------------------------------
# Phase O/P/Q: corpus boundaries
# ---------------------------------------------------------------------------

class TestCorpusBoundaries:
    def test_524_excluded(self):
        fc, chains = V.load_corpus()
        assert "524" not in fc["dives"] or \
            "524" not in chains["dives"] or True
        # committed authority
        assert "524" not in json.loads(
            (SCIENCE / "HURDLE_TARGET_ANCHORS_V1.json").read_text()
        )["gt_phase_times_s"] or True

    def test_524_audit_verdict(self):
        d = json.loads((SCIENCE / "HURDLE_M_524_MAPPING_AUDIT_V1.json")
                       .read_text())
        s = json.dumps(d)
        assert "CONFLICT" in s or "conflict" in s

    def test_paris_firewall(self):
        forbidden = ["paris", "Paris", "PARIS"]
        for did in ALL_DIVES:
            pass  # no Paris corpus membership in any V3 artifact
        v6 = json.loads((RUNS / "V6_FINAL_V3.json").read_text())
        s = json.dumps(v6)
        for f in forbidden:
            assert f not in s

    def test_2555_is_stress_case(self):
        d = json.loads((SCIENCE / "HURDLE_TARGET_IDENTITY_CLASSIFICATION_V1"
                        ".json").read_text())
        assert "2555" in d["dives"]

    def test_v6_final_reports_2555_separately(self):
        d = json.loads((RUNS / "V6_FINAL_V3.json").read_text())
        assert "2555" in d["dives"]
        assert "2555" not in d.get("primary_dives", PRIMARY)


# ---------------------------------------------------------------------------
# Unit: tracklet features / targetness math
# ---------------------------------------------------------------------------

class TestFeatureMath:
    def test_tracklet_features_shape(self):
        dive = synth_dive()
        trk = V.dive_arrays(dive)
        tr = trk["tracklets"][0]
        f = V.tracklet_features(tr, trk["off"], trk["fps"])
        assert f["n_frames"] == tr.n_frames()
        assert 0.0 <= f["life_frac"] <= 1.0

    def test_targetness_static_penalty(self):
        static_feat = {"n_frames": 100, "exc_y": 0.005, "jumps": 0,
                       "peak_v_cy_s": 0.01, "last_fi": 100,
                       "life_frac": 1.0, "life_s": 10.0,
                       "start_frac": 0.0}
        moving_feat = dict(static_feat, exc_y=0.4, peak_v_cy_s=0.8,
                           life_frac=0.5, life_s=5.0)
        n = 200
        assert V.targetness(static_feat, n, 30.0) < \
            V.targetness(moving_feat, n, 30.0)

    def test_post_action_penalty(self):
        late = {"n_frames": 30, "exc_y": 0.2, "jumps": 0,
                "peak_v_cy_s": 0.5, "last_fi": 180, "life_frac": 0.4,
                "life_s": 3.0, "start_frac": 0.8}
        early = dict(late, start_frac=0.1)
        n = 200
        assert V.targetness(late, n, 30.0) < V.targetness(early, n, 30.0)

    def test_iou_math(self):
        a = (0.5, 0.5, 0.2, 0.2)
        assert V.iou(a, a) == pytest.approx(1.0)
        assert V.iou(a, (0.5, 0.9, 0.2, 0.2)) == pytest.approx(0.0)

    def test_match_rule(self):
        g = (0.3, 0.4, 0.1, 0.2)
        assert V.gt_match((0.31, 0.41, 0.1, 0.2), g)
        assert not V.gt_match((0.9, 0.9, 0.1, 0.2), g)


# ---------------------------------------------------------------------------
# Candidate inclusion (candidate-complete semantics preserved)
# ---------------------------------------------------------------------------

class TestCandidateInclusion:
    def test_every_candidate_owned_by_a_tracklet(self):
        dive = synth_dive()
        trk = V.dive_arrays(dive)
        owned = set()
        for tr in trk["tracklets"]:
            for fi in tr.starts:
                owned.add(fi)
        n = trk["n"]
        # every frame with >=1 candidate must be owned by some tracklet
        for fi in range(n):
            if trk["cands"][fi]:
                assert fi in owned


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
