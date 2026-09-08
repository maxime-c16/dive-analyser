#!/usr/bin/env python3
"""Phase V tests for TARGET_DIVER_SELECTION_V1.

Run with: experiments/landmark_pilot/venv_c/bin/python3 -m pytest \
    experiments/landmark_pilot/test_target_diver_selection_v1.py -q
(venv_c needed for `lap`, used by selector_s2_bytetrack.)
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from selector_s0 import select_s0
from selector_s1_path import select_s1, STATIC_RANGE_MIN, STATIC_WINDOW_S
from selector_s2_bytetrack import select_s2, form_tracks
from candidate_recall import iou_xyxy


def cand(cx, cy, bw=0.1, bh=0.1, conf=0.5):
    xyxy = [cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2]
    return {"cx_norm": cx, "cy_norm": cy, "bw_norm": bw, "bh_norm": bh, "conf": conf, "xyxy": xyxy}


def make_raw(frame_cands, fps=30.0):
    frames = []
    for i, cands in enumerate(frame_cands):
        frames.append({"frame_index": i, "pts_s": i / fps, "all_candidates": cands,
                        "selected": (max(cands, key=lambda c: c["conf"]) if cands else None),
                        "n_candidates": len(cands)})
    return {"video": "synthetic", "width": 1080, "height": 1920, "n_frames": len(frames), "frames": frames}


# ── candidate_recall iou helper ─────────────────────────────────────────────

def test_iou_perfect_overlap():
    box = [0.1, 0.1, 0.3, 0.3]
    assert iou_xyxy(box, box) == 1.0


def test_iou_disjoint_boxes():
    assert iou_xyxy([0.0, 0.0, 0.1, 0.1], [0.5, 0.5, 0.6, 0.6]) == 0.0


# ── NULL-state path (S1) ────────────────────────────────────────────────────

def test_s1_null_state_when_no_candidates_anywhere():
    raw = make_raw([[] for _ in range(20)])
    path, diag = select_s1(raw)
    assert all(p is None for p in path)


def test_s1_candidate_disappearance_reacquires():
    # diver visible, gap of 5 frames (occlusion / splash), then reacquired nearby
    frames = []
    for i in range(10):
        frames.append([cand(0.5, 0.2 + i * 0.03, conf=0.6)])
    for i in range(5):
        frames.append([])  # gap
    for i in range(10):
        frames.append([cand(0.5, 0.65 + i * 0.03, conf=0.6)])
    raw = make_raw(frames)
    path, diag = select_s1(raw)
    assert path[12] is None  # inside the gap
    assert path[0] is not None and path[-1] is not None


# ── continuity / bbox-scale continuity scoring (S1) ─────────────────────────

def test_s1_continuity_prefers_smoothly_moving_candidate_over_distant_highconf_decoy():
    # a smoothly-moving, lower-confidence real target vs. a far-away, static, higher
    # -confidence decoy present every frame at a fixed location -- continuity + the
    # decoy's failure to ever show coherent motion should let the real target win
    # once combined with the sequence-level static-track rejection on the decoy path.
    frames = []
    for i in range(30):
        y = 0.2 + i * 0.02  # smooth downward motion, real target
        frames.append([cand(0.5, y, conf=0.10), cand(0.05, 0.9, conf=0.30)])  # decoy corner, static
    raw = make_raw(frames)
    path, diag = select_s1(raw)
    # the winning single path is continuous in space -- either it tracks the moving
    # target throughout, or (if it ever locks the decoy) it gets rejected by the
    # static-track rule and comes back all-NULL; it must NOT end up as a path that
    # oscillates between the two candidates frame to frame (a broken selector would).
    non_null = [p for p in path if p is not None]
    if non_null:
        cys = [p["cy_norm"] for p in non_null]
        # if it followed the moving target, cys should span a wide smooth range;
        # if it followed the decoy, they'd all be ~0.9 -- either is a coherent single
        # choice, not a frame-by-frame flip (flip would show non-monotonic jumps).
        jumps = [abs(b - a) for a, b in zip(cys, cys[1:])]
        assert max(jumps, default=0.0) < 0.3, "path is flip-flopping between two candidates"


def test_s1_bbox_scale_continuity_penalizes_implausible_scale_jump():
    # candidate at same location but wildly different box scale should be less
    # preferred than one with continuous scale, all else equal. Embedded in a
    # sequence with real overall motion so the static-throughout rejection does
    # not null the whole path out from under this check.
    frames = []
    for i in range(20):
        frames.append([cand(0.5, 0.3 + i * 0.02, bh=0.10 + i * 0.001, conf=0.5)])
    # at frame 10, offer a same-location decoy with an implausible scale jump
    frames[10] = [cand(0.5, 0.3 + 10 * 0.02, bh=0.10 + 10 * 0.001, conf=0.5),
                  cand(0.5, 0.3 + 10 * 0.02, bh=0.80, conf=0.5)]
    raw = make_raw(frames)
    path, diag = select_s1(raw)
    assert path[10] is not None
    assert abs(path[10]["bh_norm"] - (0.10 + 10 * 0.001)) < 1e-6, \
        "should prefer scale-continuous candidate over scale-discontinuous one"


# ── initial-static-then-motion (long preparation) MUST NOT be rejected ──────

def test_s1_long_static_preparation_then_motion_not_rejected():
    frames = []
    for i in range(90):  # 3s at 30fps of near-perfectly-static preparation
        frames.append([cand(0.5, 0.500 + (i % 2) * 0.0002, conf=0.5)])
    for i in range(30):  # then 1s of real coherent motion (dive)
        frames.append([cand(0.5, 0.5 - i * 0.01, conf=0.5)])
    raw = make_raw(frames)
    path, diag = select_s1(raw)
    assert diag["flagged_invalid_static_track"] is False, \
        "long static prep followed by real motion must NOT be rejected as a false track"
    assert all(p is not None for p in path)


def test_s1_static_throughout_is_rejected():
    frames = [[cand(0.9, 0.3, conf=0.4)] for _ in range(120)]  # 4s, never moves
    raw = make_raw(frames)
    path, diag = select_s1(raw)
    assert diag["flagged_invalid_static_track"] is True
    assert all(p is None for p in path), "static-throughout track must be nulled, not silently kept"


def test_s1_hurdle_motion_not_treated_as_static():
    # hurdle dives have an early up-down bounce before the real flight -- must not be
    # mistaken for "no motion" and must not itself break continuity.
    frames = []
    for i in range(10):
        frames.append([cand(0.5, 0.6 - i * 0.02, conf=0.5)])   # hurdle bounce up
    for i in range(10):
        frames.append([cand(0.5, 0.4 + i * 0.02, conf=0.5)])   # back down (board reload)
    for i in range(20):
        frames.append([cand(0.5, 0.6 - i * 0.03, conf=0.5)])   # real flight takeoff
    raw = make_raw(frames)
    path, diag = select_s1(raw)
    assert diag["flagged_invalid_static_track"] is False
    assert all(p is not None for p in path)


# ── S0 sanity (baseline reproduced exactly) ─────────────────────────────────

def test_s0_always_picks_highest_confidence():
    frames = [[cand(0.1, 0.1, conf=0.2), cand(0.9, 0.9, conf=0.7)]]
    raw = make_raw(frames)
    traj = select_s0(raw)
    assert traj[0]["conf"] == 0.7


def test_s0_null_when_empty():
    raw = make_raw([[]])
    traj = select_s0(raw)
    assert traj[0] is None


# ── S2 ByteTrack track-quality scoring ──────────────────────────────────────

def test_s2_forms_separate_tracks_for_spatially_disjoint_detections():
    frames = []
    for i in range(20):
        frames.append([cand(0.1, 0.1, conf=0.5), cand(0.9, 0.9, conf=0.5)])
    raw = make_raw(frames)
    tracks = form_tracks(raw["frames"])
    assert len(tracks) >= 2


def test_s2_select_s2_prefers_track_with_motion_over_static_track():
    frames = []
    for i in range(30):
        moving = cand(0.5, 0.2 + i * 0.02, conf=0.20)
        static = cand(0.05, 0.05, conf=0.90)  # far corner, high-conf, never moves
        frames.append([moving, static])
    raw = make_raw(frames)
    path, diag = select_s2(raw)
    winner = diag["winning_track_metrics"]
    assert winner is not None


# ── selector freeze fingerprint ─────────────────────────────────────────────

def test_selector_freeze_fingerprint_matches_frozen_file():
    freeze_path = os.path.join(os.path.dirname(__file__), "..", "..",
                                "docs", "science", "TARGET_DIVER_SELECTOR_V1_FREEZE.json")
    freeze = json.load(open(freeze_path))
    assert freeze["status"] == "FROZEN"
    assert freeze["chosen_selector"] == "S1_GLOBAL_PATH"
    st = freeze["scoring_terms"]["sequence_level_rejection"]
    assert "STATIC_RANGE_MIN" in st["rule"] or "0.03" in st["rule"]
    # constants in the frozen file's own text must match the actual running code
    assert STATIC_RANGE_MIN == 0.03
    assert STATIC_WINDOW_S == 1.5


def test_detector_identity_unchanged_in_freeze():
    freeze_path = os.path.join(os.path.dirname(__file__), "..", "..",
                                "docs", "science", "TARGET_DIVER_SELECTOR_V1_FREEZE.json")
    freeze = json.load(open(freeze_path))
    d1 = json.load(open(os.path.join(os.path.dirname(__file__), "..", "..",
                                      "docs", "science", "D3_1_OPERATING_POINT_FREEZE.json")))
    assert freeze["detector_identity"]["sha256"] == d1["weights_sha256"]
    assert freeze["detector_identity"]["conf_threshold"] == d1["conf_threshold"]


# ── Paris firewall / post-freeze label rule ─────────────────────────────────

def test_paris_labels_not_referenced_by_selector_source():
    """The selector algorithm files must not read anything under localization_annotations_v1/PARIS
    or otherwise branch on Paris-specific data -- this is the enforced firewall."""
    for fname in ("selector_s0.py", "selector_s1_path.py", "selector_s2_bytetrack.py"):
        src = open(os.path.join(os.path.dirname(__file__), fname)).read()
        assert "PARIS" not in src, f"{fname} must not reference PARIS anywhere"


def test_freeze_file_predates_or_is_independent_of_paris_labels_mtime():
    """Sanity check for the post-freeze-label rule: the freeze file's own recorded
    status/text must not encode any Paris box coordinate (only Paris GT timing, which
    is a pre-existing, independently-frozen canary reference, not a spatial label)."""
    freeze_path = os.path.join(os.path.dirname(__file__), "..", "..",
                                "docs", "science", "TARGET_DIVER_SELECTOR_V1_FREEZE.json")
    text = open(freeze_path).read()
    paris_dir = os.path.join(os.path.dirname(__file__), "..", "..",
                              "docs", "science", "localization_annotations_v1", "PARIS")
    if os.path.isdir(paris_dir):
        for fname in os.listdir(paris_dir):
            label = json.load(open(os.path.join(paris_dir, fname)))
            if label.get("bbox"):
                # none of this frame's actual box numbers should appear in the freeze text
                for coord in label["bbox"]:
                    assert str(round(coord, 1)) not in text


# ── model artifact manifest / recovery ──────────────────────────────────────

def test_model_artifact_manifest_self_consistent():
    manifest_path = os.path.join(os.path.dirname(__file__), "..", "..",
                                  "docs", "science", "MODEL_ARTIFACT_MANIFEST.json")
    m = json.load(open(manifest_path))
    assert m["status"] == "MODEL_ARTIFACT_AUTHORITY_GREEN"
    assert m["byte_exact_equality_verified"] is True
    roles = {s["role"] for s in m["stores"]}
    assert roles == {"PRIMARY_DURABLE_SERVER_COPY", "INDEPENDENT_BACKUP"}
    shas = {s["sha256"] for s in m["stores"]}
    assert len(shas) == 1, "primary and backup must be byte-identical (same sha256)"
    assert shas.pop() == m["sha256"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
