"""Tests for HIGH_RESOLUTION_PERCEPTION_CANARY_V1 — synthetic fixtures only, no media required."""

import numpy as np
import pytest
from collections import defaultdict

# ---------------------------------------------------------------------------
# Pure functions extracted from the canary pipeline (no ultralytics / cv2)
# ---------------------------------------------------------------------------

def frame_to_pts(frame_idx: int, fps: float) -> float:
    return frame_idx / fps

def check_pts_aligned(pts_r0: list, pts_r1: list, tol: float = 1e-5) -> bool:
    if len(pts_r0) != len(pts_r1):
        return False
    return all(abs(a - b) <= tol for a, b in zip(pts_r0, pts_r1))

DIVER_CX_MIN = 0.55
DIVER_CX_MAX = 1.00
DIVER_CY_MIN = 0.20
DIVER_CY_MAX = 0.70
STATIC_THRESHOLD = 0.02
MIN_PX_HEIGHT = 30

def apply_scene_roi(candidates: list) -> list:
    return [
        c for c in candidates
        if DIVER_CX_MIN <= c["cx_norm"] <= DIVER_CX_MAX
        and DIVER_CY_MIN <= c["cy_norm"] <= DIVER_CY_MAX
        and c["px_h"] >= MIN_PX_HEIGHT
    ]

def build_static_cx_map(all_frames: list) -> set:
    cx_groups = defaultdict(list)
    for f in all_frames:
        for c in f["cands"]:
            bucket = round(c["cx_norm"] * 40) / 40
            cx_groups[bucket].append(c["cy_norm"])
    static = set()
    for bucket, cy_vals in cx_groups.items():
        if len(cy_vals) >= 10 and (max(cy_vals) - min(cy_vals)) < STATIC_THRESHOLD:
            static.add(bucket)
    return static

def select_diver_h0(candidates: list, static_buckets: set):
    roi = apply_scene_roi(candidates)
    non_static = [c for c in roi if round(c["cx_norm"] * 40) / 40 not in static_buckets]
    pool = non_static if non_static else roi
    if not pool:
        return None
    return max(pool, key=lambda c: (c["px_h"], c["conf"]))

def pts_aware_smooth(trajectory: list, window_s: float = 0.1) -> list:
    valid = [(i, t["pts_s"], t["cy_norm"]) for i, t in enumerate(trajectory)
             if t["cy_norm"] is not None]
    if not valid:
        return [{**t, "cy_smooth": None} for t in trajectory]
    pts_arr = np.array([v[1] for v in valid])
    cy_arr = np.array([v[2] for v in valid])
    smoothed = []
    for t_entry in trajectory:
        if t_entry["cy_norm"] is None:
            smoothed.append({**t_entry, "cy_smooth": None})
        else:
            mask = np.abs(pts_arr - t_entry["pts_s"]) <= window_s
            cy_s = float(np.mean(cy_arr[mask])) if mask.sum() > 0 else t_entry["cy_norm"]
            smoothed.append({**t_entry, "cy_smooth": round(cy_s, 4)})
    return smoothed

def detect_landmarks(trajectory: list):
    valid = [(t["pts_s"], t.get("cy_smooth") or t["cy_norm"])
             for t in trajectory
             if (t.get("cy_smooth") is not None or t.get("cy_norm") is not None)]
    if len(valid) < 3:
        return None, None, None
    times = np.array([v[0] for v in valid])
    cys = np.array([v[1] for v in valid])
    apex_idx = int(np.argmin(cys))
    apex_t = float(times[apex_idx])
    takeoff_t = float(times[0])
    post = cys[apex_idx:]
    wc_idx = int(np.argmax(post))
    water_t = float(times[apex_idx + wc_idx])
    return takeoff_t, apex_t, water_t

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_pts_representation_mapping():
    fps = 59.94
    assert abs(frame_to_pts(0, fps) - 0.0) < 1e-9
    assert abs(frame_to_pts(1, fps) - 1 / fps) < 1e-9
    assert abs(frame_to_pts(321, fps) - 321 / fps) < 1e-6

def test_source_360p_temporal_alignment():
    fps = 59.94
    n = 322
    pts_r0 = [frame_to_pts(i, fps) for i in range(n)]
    pts_r1 = [frame_to_pts(i, fps) for i in range(n)]
    assert check_pts_aligned(pts_r0, pts_r1)
    pts_bad = [frame_to_pts(i, fps) + 0.001 for i in range(n)]
    assert not check_pts_aligned(pts_r0, pts_bad)

def test_scene_roi_filter_rejects_left_side():
    candidates = [
        {"cx_norm": 0.10, "cy_norm": 0.40, "px_h": 80, "conf": 0.9},
        {"cx_norm": 0.30, "cy_norm": 0.40, "px_h": 80, "conf": 0.85},
        {"cx_norm": 0.70, "cy_norm": 0.40, "px_h": 80, "conf": 0.75},
    ]
    result = apply_scene_roi(candidates)
    assert len(result) == 1
    assert result[0]["cx_norm"] == 0.70

def test_scene_roi_filter_rejects_small_bbox():
    candidates = [
        {"cx_norm": 0.70, "cy_norm": 0.40, "px_h": 10, "conf": 0.8},
        {"cx_norm": 0.70, "cy_norm": 0.40, "px_h": 100, "conf": 0.8},
    ]
    result = apply_scene_roi(candidates)
    assert len(result) == 1
    assert result[0]["px_h"] == 100

def test_static_spectator_rejection():
    cand_static = {"cx_norm": 0.10, "cy_norm": 0.50, "px_h": 80, "conf": 0.9}
    frames = []
    for i in range(12):
        cy_move = 0.30 + i * 0.03
        frames.append({"cands": [
            cand_static,
            {"cx_norm": 0.70, "cy_norm": cy_move, "px_h": 80, "conf": 0.8},
        ]})
    static = build_static_cx_map(frames)
    assert round(0.10 * 40) / 40 in static
    assert round(0.70 * 40) / 40 not in static

def test_diver_selection_prefers_largest_height():
    static_buckets: set = set()
    candidates = [
        {"cx_norm": 0.70, "cy_norm": 0.40, "px_h": 100, "conf": 0.6},
        {"cx_norm": 0.80, "cy_norm": 0.40, "px_h": 250, "conf": 0.5},
        {"cx_norm": 0.65, "cy_norm": 0.40, "px_h": 80, "conf": 0.9},
    ]
    selected = select_diver_h0(candidates, static_buckets)
    assert selected is not None
    assert selected["px_h"] == 250

def test_pts_aware_smoothing_uses_window():
    trajectory = [
        {"frame_idx": 0, "pts_s": 0.0, "cy_norm": 0.4},
        {"frame_idx": 1, "pts_s": 0.1, "cy_norm": 0.5},
        {"frame_idx": 2, "pts_s": 0.2, "cy_norm": 0.3},
    ]
    smoothed = pts_aware_smooth(trajectory, window_s=0.05)
    assert abs(smoothed[0]["cy_smooth"] - 0.4) < 1e-4
    assert abs(smoothed[1]["cy_smooth"] - 0.45) < 1e-4

def test_missing_gap_preservation():
    trajectory = [
        {"frame_idx": 0, "pts_s": 0.0, "cy_norm": 0.4},
        {"frame_idx": 1, "pts_s": 0.1, "cy_norm": None},
        {"frame_idx": 2, "pts_s": 0.2, "cy_norm": 0.3},
    ]
    smoothed = pts_aware_smooth(trajectory, window_s=0.05)
    assert smoothed[1]["cy_smooth"] is None
    assert smoothed[0]["cy_smooth"] is not None
    assert smoothed[2]["cy_smooth"] is not None

def test_cc3_apex_detection():
    trajectory = [
        {"pts_s": 0.0, "cy_norm": 0.45, "cy_smooth": 0.45},
        {"pts_s": 0.5, "cy_norm": 0.30, "cy_smooth": 0.30},
        {"pts_s": 1.0, "cy_norm": 0.50, "cy_smooth": 0.50},
        {"pts_s": 1.5, "cy_norm": 0.65, "cy_smooth": 0.65},
    ]
    _, apex_t, _ = detect_landmarks(trajectory)
    assert abs(apex_t - 0.5) < 1e-6

def test_cc3_takeoff_and_water_contact():
    trajectory = [
        {"pts_s": 0.2, "cy_norm": 0.44, "cy_smooth": 0.44},
        {"pts_s": 0.8, "cy_norm": 0.28, "cy_smooth": 0.28},
        {"pts_s": 1.4, "cy_norm": 0.55, "cy_smooth": 0.55},
        {"pts_s": 2.0, "cy_norm": 0.70, "cy_smooth": 0.70},
    ]
    takeoff_t, apex_t, water_t = detect_landmarks(trajectory)
    assert abs(takeoff_t - 0.2) < 1e-6
    assert abs(apex_t - 0.8) < 1e-6
    assert abs(water_t - 2.0) < 1e-6
