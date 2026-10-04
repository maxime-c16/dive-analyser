#!/usr/bin/env python3
"""
Baseline B: Diver-Isolated Blob Tracking (DIBT)
Design: BASELINE_B_DESIGN_V1.json
Freeze: BASELINE_B_FREEZE_V1.json

Algorithm:
  1. MOG2 background subtraction (same params as Baseline A)
  2. Morphological cleaning
  3. Connected components → select largest blob per frame
  4. Presence gate (area > MIN_DIVER_AREA_PX for >= MIN_PRESENCE_FRAMES consecutive frames)
  5. Diver vertical trajectory (y_norm = normalized height from bottom of frame)
  6. Savitzky-Golay smoothing
  7. Takeoff: first frame in presence window where y_norm > TAKEOFF_THRESHOLD AND dy/dt > 0
  8. Apex: frame of max y_norm after takeoff
  9. Water contact: last diver-present frame (or steep drop below WATER_LEVEL_THRESHOLD after apex)
"""
import sys, json, math, pathlib, hashlib, datetime
from typing import Optional

import cv2
import numpy as np
from scipy.signal import savgol_filter

# ── Frozen parameters (BASELINE_B_FREEZE_V1) ───────────────────────────────
PARAMS = {
    "MIN_DIVER_AREA_PX":   200,
    "MIN_PRESENCE_FRAMES": 5,
    "TAKEOFF_THRESHOLD":   0.35,
    "WATER_LEVEL_THRESHOLD": 0.15,
    "SG_WINDOW":           11,
    "SG_POLY":             3,
    "MOG2_HISTORY":        100,
    "MOG2_VAR_THRESHOLD":  50,
    "MORPH_KERNEL_SIZE":   5,
}


def _compute_diver_trajectory(video_path: str) -> dict:
    """Run the DIBT pipeline on a video file. Returns raw per-frame data."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    fgbg = cv2.createBackgroundSubtractorMOG2(
        history=PARAMS["MOG2_HISTORY"],
        varThreshold=PARAMS["MOG2_VAR_THRESHOLD"],
        detectShadows=False
    )
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (PARAMS["MORPH_KERNEL_SIZE"], PARAMS["MORPH_KERNEL_SIZE"])
    )

    frames_data = []   # list of {frame_idx, blob_area, blob_cy} or None if no blob

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        fg = fgbg.apply(gray)

        # morphological clean
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN,  kernel)
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, kernel)
        fg = (fg > 127).astype(np.uint8) * 255

        # connected components
        n_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(fg, connectivity=8)

        best_area = 0
        best_cy   = None
        best_cx   = None

        # label 0 = background; skip it
        for lbl in range(1, n_labels):
            area = int(stats[lbl, cv2.CC_STAT_AREA])
            if area > best_area:
                best_area = area
                best_cy = float(centroids[lbl][1])
                best_cx = float(centroids[lbl][0])

        frames_data.append({
            "frame_idx": frame_idx,
            "blob_area": best_area,
            "blob_cy":   best_cy,
            "blob_cx":   best_cx,
        })
        frame_idx += 1

    cap.release()
    return {
        "fps": fps, "width": width, "height": height,
        "total_frames": total_frames,
        "frames": frames_data
    }


def _presence_mask(frames_data: list, height: int) -> np.ndarray:
    """Build boolean presence array: True when diver is reliably in frame."""
    n = len(frames_data)
    raw = np.array([
        fd["blob_area"] >= PARAMS["MIN_DIVER_AREA_PX"]
        for fd in frames_data
    ], dtype=bool)

    # Apply MIN_PRESENCE_FRAMES gate: require at least N consecutive True frames
    min_run = PARAMS["MIN_PRESENCE_FRAMES"]
    presence = np.zeros(n, dtype=bool)
    run_start = None
    for i in range(n + 1):
        if i < n and raw[i]:
            if run_start is None:
                run_start = i
        else:
            if run_start is not None:
                run_len = i - run_start
                if run_len >= min_run:
                    presence[run_start:i] = True
            run_start = None

    return presence


def _detect_landmarks(frames_data: list, presence: np.ndarray, fps: float, height: int) -> dict:
    """Detect takeoff, apex, water_contact from diver trajectory."""
    n = len(frames_data)

    # y_norm: 0 = bottom of frame, 1 = top of frame
    y_norm = np.full(n, np.nan)
    for i, fd in enumerate(frames_data):
        if presence[i] and fd["blob_cy"] is not None:
            y_norm[i] = 1.0 - (fd["blob_cy"] / height)

    # Indices where diver is present
    pres_idx = np.where(presence)[0]
    if len(pres_idx) < PARAMS["MIN_PRESENCE_FRAMES"]:
        return {"takeoff": None, "apex": None, "water_contact": None,
                "applicability": "UNCERTAIN", "confidence": 0.0,
                "reason": "too few presence frames"}

    # Extract presence window
    p_start = int(pres_idx[0])
    p_end   = int(pres_idx[-1])
    pres_slice = y_norm[p_start:p_end+1]

    # Pre-interpolate NaN in pres_slice before SG filter
    valid = ~np.isnan(pres_slice)
    if valid.sum() < 3:
        return {"takeoff": None, "apex": None, "water_contact": None,
                "applicability": "UNCERTAIN", "confidence": 0.0,
                "reason": "insufficient valid frames in presence window"}
    x = np.arange(len(pres_slice))
    pres_interp = np.interp(x, x[valid], pres_slice[valid])

    # Smooth
    sg_w = min(PARAMS["SG_WINDOW"], len(pres_interp))
    sg_w = sg_w if sg_w % 2 == 1 else max(sg_w - 1, 1)
    if sg_w < 3:
        smooth_filled = pres_interp.copy()
    else:
        try:
            smooth_filled = savgol_filter(pres_interp, window_length=sg_w, polyorder=min(PARAMS["SG_POLY"], sg_w-1))
        except Exception:
            smooth_filled = pres_interp.copy()

    # Velocity
    dy = np.gradient(smooth_filled)

    # ── Takeoff: first frame where y_norm > TAKEOFF_THRESHOLD AND moving up ──
    takeoff_rel = None
    thresh = PARAMS["TAKEOFF_THRESHOLD"]
    for i in range(len(smooth_filled)):
        if smooth_filled[i] > thresh and dy[i] > 0:
            takeoff_rel = i
            break

    if takeoff_rel is None:
        # Fallback: first upward motion
        for i in range(len(dy)):
            if dy[i] > 0:
                takeoff_rel = i
                break

    if takeoff_rel is None:
        takeoff_rel = 0

    takeoff_frame = p_start + takeoff_rel

    # ── Apex: frame of maximum y_norm after takeoff ──
    if takeoff_rel < len(smooth_filled) - 1:
        apex_rel = takeoff_rel + int(np.argmax(smooth_filled[takeoff_rel:]))
    else:
        apex_rel = takeoff_rel

    apex_frame = p_start + apex_rel

    # Check apex validity: must be above TAKEOFF_THRESHOLD
    apex_y = smooth_filled[apex_rel]
    apex_applicable = apex_y > thresh

    # ── Water contact: last presence frame, or steep drop after apex ──
    # Find last presence frame after apex
    post_apex_pres = pres_idx[pres_idx >= apex_frame]
    if len(post_apex_pres) == 0:
        wc_frame = apex_frame
    else:
        # Look for steep downward movement below WATER_LEVEL_THRESHOLD
        wc_thresh = PARAMS["WATER_LEVEL_THRESHOLD"]
        wc_frame = int(post_apex_pres[-1])  # default: last presence frame
        for i in range(apex_rel, len(smooth_filled)):
            global_i = p_start + i
            if smooth_filled[i] < wc_thresh and dy[i] < 0:
                wc_frame = global_i
                break

    # ── Ordering validity ──
    if takeoff_frame < apex_frame < wc_frame:
        applicability = "APPLICABLE"
        confidence = round(float(apex_y), 4)
    else:
        applicability = "UNCERTAIN"
        confidence = round(float(apex_y) if apex_y else 0.0, 4)

    def _ts(frame, fps):
        return round(frame / fps, 6) if frame is not None else None

    return {
        "takeoff":      {"frame": int(takeoff_frame), "ts": _ts(takeoff_frame, fps)},
        "apex":         {"frame": int(apex_frame),    "ts": _ts(apex_frame, fps)} if apex_applicable else None,
        "water_contact":{"frame": int(wc_frame),      "ts": _ts(wc_frame, fps)},
        "applicability": applicability,
        "confidence": confidence,
        "p_start": int(p_start),
        "p_end":   int(p_end),
        "apex_y_norm": round(float(apex_y), 4) if apex_applicable else None,
    }


def run_baseline_b(video_path: str) -> dict:
    """Public API: run Baseline B on a video file, return result dict."""
    traj = _compute_diver_trajectory(video_path)
    presence = _presence_mask(traj["frames"], traj["height"])
    landmarks = _detect_landmarks(traj["frames"], presence, traj["fps"], traj["height"])
    return {
        "algorithm": "BASELINE_B_DIBT_V1",
        "params": PARAMS,
        "fps": traj["fps"],
        "total_frames": traj["total_frames"],
        "landmarks": landmarks,
    }


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Baseline B: Diver-Isolated Blob Tracking")
    p.add_argument("video", help="Path to video file")
    p.add_argument("--out", help="Output JSON path (default: stdout)")
    args = p.parse_args()

    result = run_baseline_b(args.video)
    out_str = json.dumps(result, indent=2)
    if args.out:
        with open(args.out, "w") as f:
            f.write(out_str)
        print(f"Written {args.out}")
    else:
        print(out_str)
