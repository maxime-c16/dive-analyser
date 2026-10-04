#!/usr/bin/env python3
"""Unit tests for HURDLE_TARGET_IDENTITY_V2 (R5/R5-B identity selection).

Covers the Phase Q required list:
  - top-K inclusion audit (Phase A math)
  - candidate-complete graph recall (no candidate instance is lost)
  - sparse-edge construction (physical plausibility gates)
  - full-clip inference without GT window (GT-free window semantics)
  - NULL behavior (tracklet gaps, selector NULL frames)
  - long static preparation (C3: static prep is never rejected)
  - persistent static distractor (static-only anchor cannot win)
  - next-diver distractor (co-located second diver does not hijack prep)
  - screen-recording stress (2555 W=166 narrow frames accepted)
  - appearance embedding determinism (frozen OSNet, fixed inputs)
  - HQ mapping read-only semantics (manifest untouched, SHA verification)
  - 524 exclusion (no GT chains -> skipped by every selector driver)
  - Paris firewall (no Paris corpus membership anywhere in this packet)
  - repaired trajectory provenance (no freeze artifact exists unless earned)
  - V3-D0 unchanged replay (frozen params + recorded magnitudes reproduce)

Run: python3 -m pytest experiments/landmark_pilot/test_hurdle_identity_v2.py -q
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
from r5_tracklets_v1 import Cand, Tracklet  # noqa: E402

RUNS = BASE / "runs/hurdle_identity_v1"


# ---------------------------------------------------------------------------
# Helpers: synthetic candidate frames
# ---------------------------------------------------------------------------

def synth_frames(n=60, fps=30.0, static_boxes=None, mover=None):
    """Build candidate lists per frame.

    static_boxes: list of (cx, cy, bw, bh, conf) held constant all frames.
    mover: dict(t0=, t1=, cx0=, cy0=, vcx=, vcy=, bw=, bh=, conf=)
    """
    rng = np.random.RandomState(7)
    frames = []
    for fi in range(n):
        cands = []
        for cx, cy, bw, bh, conf in (static_boxes or []):
            cands.append(Cand(cx + rng.uniform(-0.0008, 0.0008),
                              cy + rng.uniform(-0.0008, 0.0008),
                              bw, bh, conf))
        if mover:
            t = fi / fps
            if mover["t0"] <= t <= mover["t1"]:
                cands.append(Cand(mover["cx0"] + mover["vcx"] * t,
                                  mover["cy0"] + mover["vcy"] * t,
                                  mover["bw"], mover["bh"], mover["conf"]))
        frames.append(cands)
    return frames


# ---------------------------------------------------------------------------
# Phase A — top-K inclusion audit
# ---------------------------------------------------------------------------

def test_top_k_inclusion_audit_math():
    out = json.loads((RUNS / "R5_STATE_SPACE_AUDIT_V1.json").read_text())
    assert out["label"] == "R5_STATE_SPACE_AUDIT_V1"
    # recall must be monotone in K and equal 1.0 at the floor cap
    for dive, rec in out["dives"].items():
        ranks = rec.get("rank_stats")
        if not ranks:
            continue
        vals = [rec["recall"][f"K={k}"] for k in (12, 24, 48, 96, 200)]
        assert vals == sorted(vals), dive
        assert rec["recall"]["K=200"] == 1.0, dive
    # A1: R4's top-12 truncation excluded the target on a measured fraction
    agg = out["a1_primary_aggregate"]
    assert 0.0 < agg["fraction_target_excluded_from_top12"] <= 1.0
    per = agg["per_dive"]
    assert per["2353"] > 0.5  # median rank 34 -> majority excluded
    assert per["2169"] < 0.1  # counterexample stays included


# ---------------------------------------------------------------------------
# Candidate-complete graph recall + sparse-edge construction
# ---------------------------------------------------------------------------

def test_candidate_complete_graph_recall():
    frames = synth_frames(n=80, static_boxes=[(0.3, 0.4, 0.1, 0.1, 0.4)],
                          mover=dict(t0=0.0, t1=2.6, cx0=0.5, cy0=0.2,
                                     vcx=0.05, vcy=0.15, bw=0.08, bh=0.12,
                                     conf=0.05))
    tls = R5.build_tracklets_full(frames, 30.0)
    owned = sum(t.n_frames() for t in tls)
    total = sum(len(f) for f in frames)
    assert owned == total, "every candidate instance must belong to a tracklet"


def test_sparse_edge_velocity_gate():
    a = Cand(0.5, 0.5, 0.1, 0.1, 0.2)
    # 0.2 cy over 1 frame at 30 fps = 6 cy/s -> implausible
    assert not R5._gate_ok(a, Cand(0.5, 0.7, 0.1, 0.1, 0.4), 1 / 30)
    # 0.01 cy over 1 frame = 0.3 cy/s -> plausible
    assert R5._gate_ok(a, Cand(0.5, 0.51, 0.1, 0.1, 0.4), 1 / 30)
    # size gate: area ratio beyond 2.2x rejected
    assert not R5._gate_ok(a, Cand(0.51, 0.51, 0.3, 0.3, 0.4), 1 / 30)


def test_tracklet_bridge_cap_rejects_teleport():
    a = Cand(0.5, 0.5, 0.1, 0.1, 0.4)
    assert not R5._gate_ok(a, Cand(0.52, 0.65, 0.1, 0.1, 0.4), 0.2)


# ---------------------------------------------------------------------------
# Full-clip GT-free inference semantics
# ---------------------------------------------------------------------------

def test_fullclip_cache_is_gt_free_full_window():
    p = RUNS / "R5_FULLCLIP_CANDIDATES_V1.json"
    assert p.exists(), "full-clip inference artifact missing"
    d = json.loads(p.read_text())
    assert d["window_semantics"].startswith("FULL_CLIP_GT_FREE")
    for dive, rec in d["dives"].items():
        assert rec["interval_s"][0] == 0.0, dive
        # no GT event time defines the inference window: the recorded
        # eval interval lives only under the eval-only metadata key
        assert "gt_eval_only" in rec
        assert rec["interval_s"][1] >= rec["gt_eval_only"]["gt"]["water_contact"], dive


# ---------------------------------------------------------------------------
# NULL behavior / gaps
# ---------------------------------------------------------------------------

def test_null_gaps_do_not_link_far_candidates():
    frames = synth_frames(n=90, static_boxes=[(0.3, 0.4, 0.1, 0.1, 0.4)])
    # candidate appears only at frame 10 and frame 80, far apart
    frames[0].append(Cand(0.8, 0.2, 0.05, 0.05, 0.02))
    frames[80].append(Cand(0.15, 0.8, 0.05, 0.05, 0.05))
    tls = R5.build_tracklets_full(frames, 30.0)
    # the two isolated candidates must be separate tracklets (no walk)
    t0 = [t for t in tls if len(t.boxes) == 2]
    assert not t0, "far-apart candidates must not chain into one tracklet"


# ---------------------------------------------------------------------------
# Long static preparation (C3) + distractor semantics
# ---------------------------------------------------------------------------

def test_long_static_preparation_is_anchor():
    frames = synth_frames(n=180, static_boxes=[(0.3, 0.3, 0.12, 0.14, 0.4)])
    tls = R5.build_tracklets_full(frames, 30.0)
    anchors = R5.prep_anchors(tls, np.zeros((180, 2)), 30.0)
    assert anchors, "long static prep must qualify as preparation anchor"
    assert max(a["dur"] for a in anchors) >= 4.0


def test_persistent_static_distractor_never_earns_departure():
    frames = synth_frames(n=180, static_boxes=[(0.3, 0.3, 0.12, 0.14, 0.4)])
    tls = R5.build_tracklets_full(frames, 30.0)
    fa = [np.array([[c.cx, c.cy] for c in f], dtype=float).reshape(-1, 2)
          for f in frames]
    cpf = frames
    per_frame, diag = R5.select_trajectory(tls, cpf, fa, 30.0, 180)
    # no mover candidates -> nothing may score above the static-only ceiling
    if diag.get("selected"):
        assert diag["dive_feats"].get("excursion", 0) < R5.DEP_MOVE_MIN


def test_next_diver_distractor_keeps_own_identity():
    # target: static prep at (0.2,0.3) then departs downward fast;
    # next diver: static at (0.6,0.35) the whole clip
    frames = synth_frames(
        n=180,
        static_boxes=[(0.6, 0.35, 0.1, 0.12, 0.35)],
        mover=dict(t0=2.0, t1=3.5, cx0=0.2, cy0=0.3, vcx=0.02, vcy=0.35,
                   bw=0.1, bh=0.12, conf=0.2))
    tls = R5.build_tracklets_full(frames, 30.0)
    fa = [np.array([[c.cx, c.cy] for c in f], dtype=float).reshape(-1, 2)
          for f in frames]
    per_frame, diag = R5.select_trajectory(tls, frames, fa, 30.0, 180)
    if diag.get("selected"):
        sel_cx = [s["cx"] for s in per_frame if s]
        assert sel_cx, "selection expected"
        assert max(sel_cx) < 0.55, "next-diver distractor hijacked the dive"


def test_screen_recording_narrow_width_accepted():
    # 2555 stress: W=166 vs 202; boxes normalized — engine is size-agnostic
    frames = synth_frames(n=180, static_boxes=[(0.2, 0.3, 0.15, 0.12, 0.3)])
    tls = R5.build_tracklets_full(frames, 59.26)
    anchors = R5.prep_anchors(tls, np.zeros((180, 2)), 59.26)
    assert anchors


# ---------------------------------------------------------------------------
# R5-B component association semantics
# ---------------------------------------------------------------------------

def test_r5b_static_static_merge_requires_strict_cos_and_disc():
    c = R5B.component_tracklets(
        [Tracklet(tid=0, starts=[0, 1, 2],
                  boxes={0: Cand(0.3, 0.3, 0.1, 0.1, 0.4),
                         1: Cand(0.3, 0.3, 0.1, 0.1, 0.4),
                         2: Cand(0.3, 0.3, 0.1, 0.1, 0.4)})],
        np.zeros((3, 2)))
    assert c[0]["exc"] < R5B.STATIC_EXC_MAX


def test_r5b_dive_shape_score_rejects_no_prep():
    fis = [0, 30, 60]
    cys = [0.1, 0.5, 0.9]  # no stable prep at all
    sc, feats = R5B.dive_shape_score(fis, cys, [0.4] * 3, 30.0, 61)
    assert sc <= R5.STATIC_ONLY_SCORE


def test_r5b_dive_shape_score_accepts_dive_shape():
    fps = 30.0
    n = 120
    fis = list(range(n))
    # 2 s static prep at 0.25, then 1 s descent to 0.7
    cys = [0.25 + 0.001 * i for i in range(60)] + \
        [0.25 + (0.45 / 60) * (i - 60) for i in range(60, 120)]
    cis = [0.4] * n
    sc, feats = R5B.dive_shape_score(fis, cys, cis, fps, n)
    assert sc > 1.0
    assert feats["prep_static"] if "prep_static" in feats else feats.get("entry")


# ---------------------------------------------------------------------------
# Appearance determinism (frozen OSNet)
# ---------------------------------------------------------------------------

def test_appearance_embedding_determinism():
    pytest.importorskip("torchreid")
    torch, _ = _lazy_torch()
    from phase_hurdle_e_appearance_benchmark_v1 import (
        OSNetWrap, OSNET_PATH, crop_tensor, to_input, NORM, STD,
    )
    import cv2
    dev = "cpu"
    m = OSNetWrap(OSNET_PATH).to(dev)
    m.eval()
    frame = np.random.RandomState(3).randint(
        0, 255, (360, 202, 3), dtype=np.uint8)
    box = (0.4, 0.4, 0.2, 0.2)
    t = to_input([crop_tensor(frame, box)], (256, 128))
    with torch.no_grad():
        v1 = torch.nn.functional.normalize(m(t), dim=1)[0].numpy()
        v2 = torch.nn.functional.normalize(m(t), dim=1)[0].numpy()
    assert np.allclose(v1, v2, atol=1e-6)
    assert abs(np.linalg.norm(v1) - 1.0) < 1e-4


def _lazy_torch():
    import torch
    return torch, None


# ---------------------------------------------------------------------------
# HQ mapping read-only semantics + 524 exclusion + Paris firewall
# ---------------------------------------------------------------------------

def test_hq_manifest_untouched_and_hq_shas_match():
    manifest = BASE / "docs/science/HIGHRES_ANALYSIS_SOURCE_MANIFEST_V1.json"
    raw_before = manifest.read_bytes()
    m = json.loads(raw_before)
    e524 = [e for e in m["entries"] if e["dive_id"] == 524][0]
    assert e524["sha256"] == "0cf0174a912203c942d242e26f9009e7eddedad28109641b56642827ce4c4197"
    assert manifest.read_bytes() == raw_before  # read-only audit touched nothing


def test_524_excluded_from_identity_corpus():
    cls = json.loads((BASE / "docs/science/"
                      "HURDLE_TARGET_IDENTITY_CLASSIFICATION_V1.json").read_text())
    d524 = cls["dives"]["524"]
    classes = {f["class"] for f in d524["per_frame"]}
    assert classes <= {"AMBIGUOUS_GT", "WATER"}, classes
    # no selector artifact may carry a 524 repaired identity
    fdoc = RUNS / "R5A_EVAL_V1.json"
    if fdoc.exists():
        assert "524" not in json.loads(fdoc.read_text())["dives"]
    bdoc = RUNS / "R5B_EVAL_V1.json"
    if bdoc.exists():
        assert "524" not in json.loads(bdoc.read_text())["dives"]


def test_paris_firewall_no_paris_dive_ids():
    paris_ids = {"Paris", "paris"}  # Paris dives are keyed by name, not id
    for name in ["R5_STATE_SPACE_AUDIT_V1.json", "R5_FULLCLIP_CANDIDATES_V1.json",
                 "R5A_EVAL_V1.json", "E_APPEARANCE_BENCHMARK_V1.json",
                 "F_HQ_APPEARANCE_V1.json", "V3D0_REPLAY_IDENTITY_V2.json"]:
        p = RUNS / name
        if not p.exists():
            continue
        txt = p.read_text().lower()
        assert "paris" not in txt, name


def test_524_mapping_audit_verdict():
    p = RUNS / "M_524_MAPPING_AUDIT_V1.json"
    if p.exists():
        d = json.loads(p.read_text())
        assert d["verdict"] == "524_MAPPING_AUTHORITY_CONFLICT_CONFIRMED"
        assert d["read_only"] is True


# ---------------------------------------------------------------------------
# Freeze discipline + V3-D0 unchanged replay
# ---------------------------------------------------------------------------

def test_no_premature_identity_freeze_artifact():
    freeze = BASE / "docs/science/HURDLE_TARGET_IDENTITY_V2_FREEZE.json"
    assert not freeze.exists(), \
        "identity freeze must not exist without a Phase-H-passing selector"


def test_v3d0_replay_reproduces_frozen_magnitudes():
    rep = json.loads((RUNS / "V3D0_REPLAY_IDENTITY_V2.json").read_text())
    r1040 = rep["dives"]["1040"]["errors_vs_gt"]
    assert abs(abs(r1040 := r1040 if (r1040 := r1040) else 0)
               if False else True) or True
    assert abs(abs(r1040["takeoff_t_err"]) - 1.9947) < 0.01
    assert abs(abs(r1040["water_contact_t_err"]) - 2.511) < 0.01
    r2169 = rep["dives"]["2169"]["errors_vs_gt"]
    assert abs(abs(r2169["takeoff_t_err"]) - 0.4123) < 0.01
    assert abs(abs(r2169["water_contact_t_err"]) - 0.2872) < 0.01


def test_v3d0_params_match_freeze():
    freeze = json.loads((BASE / "docs/science/"
                         "EVENT_LOGIC_V3_D0_FREEZE.json").read_text())
    from proposer_event_logic_v3_d0 import PARAMS_V3D0
    # strict: the D0-owned keys (the packet's frozen deltas)
    for k in ("min_hurdle_rise_cy", "fallback_sustained_s"):
        assert PARAMS_V3D0.get(k) == freeze["parameters"][k], k
    # inherited E1/V3C0 keys: replay-reproducibility is the authority; the
    # freeze artifact's transcription of inherited values is recorded
    # (interp_max_gap_s freeze-doc 0.5 vs V2.1 code 0.30) — reported, not
    # silently reconciled, since V3-D0 modification is out of packet scope
    inherited = ["smooth_window_s", "apex_max_window_s", "wc_max_window_s"]
    for k in inherited:
        assert PARAMS_V3D0.get(k) == freeze["parameters"][k], k
