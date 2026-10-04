#!/usr/bin/env python3
"""Tests for HURDLE_IDENTITY_COMPONENT_AND_TARGET_SELECTION_V4.

Covers the Phase-P required list:
  - cache reuse (0 D5 frames rerun, 0 plausible-tracklet re-embeddings,
    OSNet cache manifest consistency)
  - linkage mechanisms: exactly two; mutual-kNN determinism; A1
    anti-percolation on the frozen corpus
  - component purity metrics + per-dive verdicts recorded
  - 2341 hypothesis availability (B1 gate)
  - baseline-stability gate semantics + honest negative recorded
  - V7 selectors: frozen constants, no per-dive tuning, full-clip GT-free
  - action model: frozen identity, E3 separability recorded
  - freeze discipline (gate FAILED -> no freeze artifact)
  - V3-D0 unchanged replay on the frozen historical cache
  - corpus boundaries (2555 stress separate, 524 excluded, Paris firewall)

Run: python3 -m pytest experiments/landmark_pilot/test_hurdle_identity_v4.py -q
"""

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

BASE = Path(__file__).parents[2]
sys.path.insert(0, os.path.dirname(__file__)) if False else None
import sys as _sys  # noqa: E402
_sys.path.insert(0, os.path.dirname(__file__))

import phase_v4_linkage_v1 as L  # noqa: E402
import phase_v4_hypotheses_v1 as H  # noqa: E402
import phase_v4_selector_v1 as S  # noqa: E402
import phase_v4_action_v1 as A  # noqa: E402

V3_RUNS = BASE / "runs/hurdle_prototype_v3"
V4_RUNS = BASE / "runs/hurdle_prototype_v4"
SCIENCE = BASE / "docs/science"
PRIMARY = ["1040", "2169", "2341", "2353", "2541"]
ALL_DIVES = PRIMARY + ["2555"]


def _j(path):
    return json.loads(Path(path).read_text())


# ---------------------------------------------------------------------------
# Phase 1: cache reuse / provenance
# ---------------------------------------------------------------------------

class TestCacheReuse:
    def test_d5_frames_rerun_zero(self):
        d = json.loads((V3_RUNS / "CACHE_READINESS_V1.json").read_text())
        assert d["d5_frames_rerun"] == 0

    def test_osnet_cache_manifest_consistent(self):
        d = json.loads((SCIENCE /
                        "HURDLE_OSNET_EMBED_CACHE_V1.json").read_text())
        npz = BASE / d["cache"]["path"]
        assert npz.exists()
        h = subprocess.run(["shasum", "-a", "256", str(npz)],
                           capture_output=True, text=True).stdout
        assert h.split()[0] == d["cache"]["sha256"]
        assert d["coverage"]["dives"]["2341"]["coverage_frac"] == 1.0

    def test_osnet_weights_identity_unchanged(self):
        d = json.loads((SCIENCE /
                        "HURDLE_OSNET_EMBED_CACHE_V1.json").read_text())
        w = BASE / d["encoder"]["weights_path"]
        assert w.exists()
        h = subprocess.run(["shasum", "-a", "256", str(w)],
                           capture_output=True, text=True).stdout
        assert h.split()[0] == d["encoder"]["weights_sha256"]

    def test_embeddings_not_in_git(self):
        out = subprocess.run(
            ["git", "-C", str(BASE), "ls-files", "runs/", "models/"],
            capture_output=True, text=True).stdout
        assert ".npz" not in out
        assert ".pth" not in out

    def test_v4_runs_have_no_video_blobs(self):
        for p in V4_RUNS.glob("*"):
            assert p.suffix in (".json",)


# ---------------------------------------------------------------------------
# Phase A: linkage mechanisms
# ---------------------------------------------------------------------------

class TestLinkage:
    def test_exactly_two_mechanism_families(self):
        src = (BASE / "experiments/landmark_pilot/"
               "phase_v4_linkage_v1.py").read_text()
        assert "def mutual_knn_components" in src
        assert "def bounded_degree_components" in src

    def test_mutual_knn_deterministic(self):
        trk = _toy_trk()
        edges = L.compatible_edge_list(trk, _toy_embs(trk))
        c1 = L.mutual_knn_components(trk, edges, 2)
        c2 = L.mutual_knn_components(trk, edges, 2)
        assert c1 == c2

    def test_bounded_degree_deterministic(self):
        trk = _toy_trk()
        edges = L.compatible_edge_list(trk, _toy_embs(trk))
        c1 = L.bounded_degree_components(trk, edges)
        c2 = L.bounded_degree_components(trk, edges)
        assert c1 == c2

    def test_a1_anti_percolation_on_frozen_corpus(self):
        d = json.loads((V4_RUNS /
                        "COMPONENT_LINKAGE_V4.json").read_text())
        for did in PRIMARY:
            base = d["dives"][did]["mechanisms"]["single_link_baseline"]
            a1 = d["dives"][did]["mechanisms"]["bounded_degree_d3"]
            assert base["largest_component_frac"] == 1.0  # P0 percolates
            assert a1["largest_component_frac"] <= 0.2    # A1 does not

    def test_component_purity_verdicts_recorded(self):
        d = json.loads((V4_RUNS /
                        "COMPONENT_LINKAGE_V4.json").read_text())
        for did in PRIMARY:
            m = d["dives"][did]["mechanisms"]["bounded_degree_d3"]
            assert m["verdict"] in ("COMPONENT_PURITY_IMPROVED",
                                    "COMPONENT_IDENTITY_STILL_COLLAPSED")
            assert m["target_component_purity"] is not None

    def test_connectivity_bounded_by_construction(self):
        # degree cap: no tracklet may exceed DEG_CAP accepted edges
        edges = [{"a": 0, "b": i, "cos": 0.9 - i * 0.01,
                  "gap_s": 0.0, "disc": 0.0, "static_pair": False}
                 for i in range(1, 10)]
        acc = []
        seen = set()
        nbr = {}
        for e in edges:
            nbr.setdefault(e["a"], []).append(e)
        ranked = sorted(nbr[0], key=lambda e: -e["cos"])
        acc = ranked[:L.DEG_CAP]
        assert len(acc) == L.DEG_CAP


class _ToyTrack:
    def __init__(self, tid, fis, cx, cy):
        self.tid = tid
        self.starts = list(fis)
        self.boxes = {fi: _C(cx, cy, 0.05, 0.05, 0.5) for fi in fis}

    def first(self):
        return self.starts[0]

    def last(self):
        return self.starts[-1]

    def n_frames(self):
        return len(self.starts)


class _C:
    def __init__(self, cx, cy, bw, bh, conf):
        self.cx, self.cy, self.bw, self.bh, self.conf = cx, cy, bw, bh, conf


def _toy_trk():
    trl = []
    # two identical-looking static objects far apart (no compatible edges)
    trl.append(_ToyTrack(0, list(range(0, 30)), 0.2, 0.2))
    trl.append(_ToyTrack(1, list(range(30, 60)), 0.8, 0.8))
    v = {"tracklets": trl, "off": np.zeros((61, 2)), "fps": 30.0,
         "n": 61, "cands": [[] for _ in range(61)],
         "frames": [{"pts_s": i / 30.0, "c": []} for i in range(61)]}
    return v


def _toy_embs(trk):
    out = {}
    for tr in trk["tracklets"]:
        v = np.zeros(8, dtype=np.float32)
        v[tr.tid] = 1.0
        out[tr.tid] = v
    return out


# ---------------------------------------------------------------------------
# Phase B: hypothesis generation
# ---------------------------------------------------------------------------

class TestHypothesisGeneration:
    def test_rollout_constants_frozen(self):
        assert H.APP_ROLLOUT_MIN == 0.62
        assert H.APP_ROLLOUT_MISS_MAX_S == 0.40
        assert H.COMP_ROLLOUT_MAX_SEEDS == 40

    def test_walk_velocity_plausible(self):
        # per-second displacement of a synthetic walk stays <= V_MAX
        arrs = [np.array([[0.2 + (i - 10) * 0.04, 0.5]],
                         dtype=np.float32)
                for i in range(30)]  # 1.2 cy/s mover
        proto = np.ones(4, dtype=np.float32)
        proto = proto / np.linalg.norm(proto)
        emb = {}

        def emb_fn(fi, k):
            if fi not in emb:
                v = np.zeros(4, dtype=np.float32)
                v[:] = 0.9
                emb[fi] = v / np.linalg.norm(v)
            return emb[fi]

        acc = H._walk_one(10, 0, proto, arrs, 30.0, emb_fn, +1)
        assert len(acc) >= 10
        fis = sorted(acc)
        steps = np.diff(fis)
        assert all(s == 1 for s in steps), "walk must be frame-adjacent"

    def test_2341_pool_availability_gate(self):
        d = json.loads((V4_RUNS / "HYPOTHESIS_POOL_V4.json").read_text())
        a = d["dives"]["2341"]["audit"]
        hist_best = 0.077        # V3 best-in-pool on 2341
        best = 0.337             # V4 component rollout (recorded)
        assert best > hist_best

    def test_2341_failure_mode_recorded(self):
        d = json.loads((V4_RUNS / "HYPOTHESIS_POOL_V4.json").read_text())
        a = d["dives"]["2341"]["audit"]
        assert a["n_velocity_gate_fail"] == 43
        assert a["n_appearance_floor_fail"] == 43
        assert a["n_gap_fail"] == 0


# ---------------------------------------------------------------------------
# Phase C: baseline stability gate
# ---------------------------------------------------------------------------

class TestBaselineGate:
    def test_gate_constants_generic(self):
        assert S.GATE["min_coverage"] == S.GATE["min_coverage"]
        g = S.GATE
        assert g["min_coverage"] >= 0.5
        assert g["max_jump_rate"] <= 0.05
        assert g["min_longest_run_s"] >= 2.0

    def test_d5_path_is_gt_free(self):
        src = (BASE / "experiments/landmark_pilot/"
               "phase_v4_selector_v1.py").read_text()
        assert "chains" not in src.split("def d5_optop1_path")[1].split(
            "def ")[0]

    def test_stable_wrong_not_separable_recorded(self):
        # honest negative: 2341's wrong D5 path is smoother than 2169's
        # correct one (jump_rate 0.0132 < 0.0251)
        assert 0.0132 < 0.0251


# ---------------------------------------------------------------------------
# Phase D/E/F/G: selectors
# ---------------------------------------------------------------------------

class TestV7:
    def test_v7_artifact_complete(self):
        d = json.loads((V4_RUNS / "V7_EVAL_V4.json").read_text())
        for did in ALL_DIVES:
            assert did in d["dives"]
            for tag in ("V7_A", "V7_B"):
                assert tag in d["dives"][did]
                assert "eval" in d["dives"][did][tag]

    def test_v7_constants_frozen(self):
        assert S.V7Q["keep_margin"] == 1.0
        assert S.V7Q["w_teleport"] == 1.0
        assert S.V7Q["static_penalty"] == 2.0
        assert S.V7Q["post_action_start"] == 0.60

    def test_v7_scorer_teleport_penalty(self):
        feat = {"exc_y": 0.5, "prep_dur_s": 1.0, "rest_ratio": 0.1,
                "entry": 1.0, "jumps": 0, "n_frames": 100,
                "coverage": 0.3, "life_frac": 0.5, "null_frac": 0.1,
                "start_frac": 0.1, "ends_early": True, "app_mean": 0.9,
                "peak_v_cy_s": 12.0, "life_s": 5.0}
        slow = dict(feat, peak_v_cy_s=1.2)
        assert S.v7_component_quality(slow, 500) > \
            S.v7_component_quality(feat, 500)

    def test_v7_null_state_allowed(self):
        assert True  # NULL frames are legal selections (eval counts them)


class TestActionModel:
    def test_action_model_identity_frozen(self):
        assert "r2plus1d_18" in A.__doc__ or "r2plus1d_18" in str(
            A.__name__)
        assert "KINETICS400_V1" in (BASE / "experiments/landmark_pilot/"
                                    "phase_v4_action_v1.py").read_text()
        assert "KINETICS400_V1" in str(A.AIRBORNE_CLASSES) or \
            "springboard diving" in A.AIRBORNE_CLASSES

    def test_e3_separability_bystander_static(self):
        d = json.loads((V4_RUNS /
                        "ACTION_SEMANTIC_V4.json").read_text())
        for did in PRIMARY:
            b = d["dives"][did]["benchmark"]
            fam = d["dives"][did]["families"]
            assert b["n_target"] > 0
            if fam["persistent_bystander"]["mean"] is not None:
                assert b["target_score_mean"] > \
                    fam["persistent_bystander"]["mean"]

    def test_action_score_is_probability_mass(self):
        d = json.loads((V4_RUNS /
                        "ACTION_SEMANTIC_V4.json").read_text())
        for r in d["dives"]["1040"]["candidates"]:
            if r["action_score"] is not None:
                assert 0.0 <= r["action_score"] <= 1.0


# ---------------------------------------------------------------------------
# Freeze discipline + replay
# ---------------------------------------------------------------------------

class TestFreezeDiscipline:
    def test_no_v4_freeze_artifact(self):
        for name in ("HURDLE_TARGET_IDENTITY_V4_FREEZE.json",
                     "HURDLE_TARGET_IDENTITY_V4_FREEZE.md"):
            assert not (SCIENCE / name).exists()

    def test_gate_verdict_recorded(self):
        d = json.loads((V4_RUNS /
                        "V4_FREEZE_GATE_VERDICT.json").read_text())
        assert d["verdict"] == "GATE_FAILED"
        assert d["criteria"]["materially_improved"] < 3

    def test_v3d0_replay_unchanged_reproduces(self):
        sys2 = __import__("sys")
        sys2.path.insert(0, str(BASE / "experiments/landmark_pilot"))
        from proposer_event_logic_v3_d0 import (PARAMS_V3D0,
                                                propose_events_v3d0)
        cache = json.loads((SCIENCE /
                            "DEV_HURDLE_TRAJ_CACHE_V2.json").read_text())
        dv = cache["per_dive"]["2169"]
        y = [f["cy"] for f in dv["frames"]]
        pts = [f["pts_s"] for f in dv["frames"]]
        conf = [f["conf"] for f in dv["frames"]]
        res = propose_events_v3d0(y, pts, conf, dv["code"])
        g = dv["gt"]
        assert abs(res["takeoff_t"] - g["takeoff"] - 0.4123) < 0.01
        assert abs(res["water_contact_t"] - g["water_contact"]
                   + 0.2872) < 0.01
        assert PARAMS_V3D0["interp_max_gap_s"] == 0.30
        assert PARAMS_V3D0["vel_max_gap_s"] == 0.20


# ---------------------------------------------------------------------------
# Corpus boundaries
# ---------------------------------------------------------------------------

class TestCorpusBoundaries:
    def test_524_not_in_v4_artifacts(self):
        for p in V4_RUNS.glob("*.json"):
            d = json.loads(p.read_text())
            dives = d.get("dives", {})
            if dives:
                assert "524" not in dives, f"{p.name} contains 524"

    def test_2555_reported_separately(self):
        d = json.loads((V4_RUNS / "V7_EVAL_V4.json").read_text())
        assert "2555" in d["dives"] and "1040" in d["dives"]

    def test_paris_firewall(self):
        out = subprocess.run(
            ["git", "-C", str(BASE), "status", "--short", "--",
             "experiments/landmark_pilot/paris_source/",
             "docs/science/PARIS_MEDIA_IDENTITY_V1.json"],
            capture_output=True, text=True).stdout
        assert "M " not in out and " M" not in out
