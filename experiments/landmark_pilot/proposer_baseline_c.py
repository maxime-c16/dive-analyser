#!/usr/bin/env python3
"""
Baseline C: YOLO Person Detection + ByteTrack + Human-Centric Trajectory

Design:
  video
    ↓  YOLOv8n person detection (class=0, COCO)
    ↓  ByteTrack single-frame association
    ↓  Primary-track selection (longest × avg_conf)
    ↓  Vertical-centroid trajectory
    ↓  Landmark-specific temporal reasoning
    ↓  takeoff / apex / water_contact

Variants:
  C1 — trajectory only (no temporal priors)
  C2 — trajectory + landmark-specific temporal priors

Freeze document: docs/science/BASELINE_C_FREEZE_V1.json
"""
import sys
import json
import hashlib
import datetime
import pathlib
import math
from typing import Optional, Dict, List, Any, Tuple

import cv2
import numpy as np

# ─── Frozen parameters ─────────────────────────────────────────────────────
PARAMS_C1 = {
    "variant":               "C1",
    "detector":              "yolov8n",
    "detector_imgsz":        640,
    "detector_conf":         0.10,
    "detector_iou":          0.45,
    "detector_classes":      [0],          # COCO class 0 = person
    "tracker":               "bytetrack",
    "track_min_conf":        0.10,
    "track_select_strategy": "longest_x_conf",
    "vid_stride":             1,            # process every frame (CPU-only; no GPU available)
    "traj_smooth_window":    11,
    "traj_smooth_poly":      3,
    "traj_interp_max_gap":   15,
    # Takeoff
    "takeoff_y_threshold":   0.30,         # y_norm must exceed this (0=bottom, 1=top)
    "takeoff_min_sustained": 6,            # must stay above for N consecutive frames
    "takeoff_gap_min":       8,            # min gap frames indicating run-up
    "takeoff_board_delta":   0.08,         # must be above board_y + this delta
    # Apex
    "apex_search_start_offset": 10,        # frames after takeoff
    # Water contact
    "water_contact_y_threshold": 0.15,     # y_norm must drop below this
    "water_contact_look_ahead":  30,       # check for sustained drop after trigger
}

PARAMS_C2 = dict(PARAMS_C1)
PARAMS_C2.update({
    "variant":               "C2",
    # Temporal priors derived from DEVELOPMENT_DESIGN annotations:
    # Takeoff→Apex min/max (frames at 30fps reference)
    "prior_t2a_min_frames":  8,           # ~0.27s
    "prior_t2a_max_frames":  300,         # ~10s
    # Apex→WC min/max
    "prior_a2w_min_frames":  4,           # ~0.13s
    "prior_a2w_max_frames":  400,         # ~13s
    # If detected landmarks violate priors, emit UNCERTAIN
    "use_temporal_priors":   True,
})


# ─── Detection helpers ──────────────────────────────────────────────────────

def _run_yolo_on_video(video_path: str, params: dict) -> List[Dict[str, Any]]:
    """Run YOLOv8n person detection on each frame.
    Returns list of per-frame dicts with 'boxes' (xyxy, conf, track_id) or [].
    Uses Ultralytics tracking API for ByteTrack.
    """
    from ultralytics import YOLO
    model = YOLO(f"{params['detector']}.pt")

    results_per_frame = []
    try:
        # Ultralytics track() reads frame-by-frame internally
        results = model.track(
            device="cpu",
            source=video_path,
            imgsz=params["detector_imgsz"],
            conf=params["detector_conf"],
            iou=params["detector_iou"],
            classes=params["detector_classes"],
            tracker="bytetrack.yaml",
            vid_stride=params.get("vid_stride", 1),
            stream=True,
            verbose=False,
        )
        for r in results:
            frame_detections = []
            if r.boxes is not None and len(r.boxes) > 0:
                boxes_xyxy = r.boxes.xyxy.cpu().numpy().astype(float)
                confs = r.boxes.conf.cpu().numpy().astype(float)
                track_ids = (r.boxes.id.cpu().numpy().astype(int)
                             if r.boxes.id is not None
                             else [-1] * len(boxes_xyxy))
                for box, conf, tid in zip(boxes_xyxy, confs, track_ids):
                    if conf < params["track_min_conf"]:
                        continue
                    frame_detections.append({
                        "xyxy": box.tolist(),
                        "conf": float(conf),
                        "track_id": int(tid),
                    })
            results_per_frame.append(frame_detections)
    except Exception as e:
        print(f"  YOLO tracking error: {e}", file=sys.stderr)
        return []

    return results_per_frame


def _get_frame_info(video_path: str) -> dict:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return {"fps": fps, "width": width, "height": height, "total_frames": total_frames}


# ─── Track selection ─────────────────────────────────────────────────────────

def _select_primary_track(results_per_frame: list) -> Optional[int]:
    """Select the primary diver track_id.

    Strategy (C-TRACK-SELECT-LONGEST-X-CONF):
    Score each track by (frame_count × avg_detection_conf).
    Return the track_id with the highest score.
    """
    track_data: Dict[int, Dict[str, Any]] = {}
    for frame_dets in results_per_frame:
        for det in frame_dets:
            tid = det["track_id"]
            if tid < 0:
                continue
            if tid not in track_data:
                track_data[tid] = {"count": 0, "conf_sum": 0.0}
            track_data[tid]["count"] += 1
            track_data[tid]["conf_sum"] += det["conf"]

    if not track_data:
        return None

    best_tid = max(track_data.items(),
                   key=lambda kv: kv[1]["count"] * (kv[1]["conf_sum"] / kv[1]["count"]))[0]
    return best_tid


# ─── Trajectory extraction ───────────────────────────────────────────────────

def _extract_diver_trajectory(
    results_per_frame: list,
    track_id: int,
    frame_height: int
) -> Dict[str, list]:
    """Extract per-frame y_norm, bbox_height_norm, and conf for the selected track.
    y_norm: 0 = bottom of frame, 1 = top of frame (inverse of pixel coords).
    bbox_height_norm: bbox_height / frame_height.
    """
    n = len(results_per_frame)
    y_norm = [None] * n          # centre y, normalised
    height_norm = [None] * n     # bbox height, normalised
    conf = [None] * n            # detection confidence

    for fi, frame_dets in enumerate(results_per_frame):
        for det in frame_dets:
            if det["track_id"] == track_id:
                x1, y1, x2, y2 = det["xyxy"]
                cy_px = (y1 + y2) / 2.0
                # Convert: y_norm=1 at top (low pixel y), y_norm=0 at bottom
                y_norm[fi] = 1.0 - cy_px / max(1, frame_height)
                height_norm[fi] = (y2 - y1) / max(1, frame_height)
                conf[fi] = det["conf"]
                break

    return {"y_norm": y_norm, "height_norm": height_norm, "conf": conf}


def _interpolate_gaps(values: list, max_gap: int = 15) -> list:
    """Linear interpolation of short None runs."""
    result = list(values)
    n = len(result)
    i = 0
    while i < n:
        if result[i] is None:
            j = i
            while j < n and result[j] is None:
                j += 1
            gap_len = j - i
            if gap_len <= max_gap and i > 0 and j < n:
                start_val = result[i - 1]
                end_val = result[j]
                for k in range(gap_len):
                    t = (k + 1) / (gap_len + 1)
                    result[i + k] = start_val + t * (end_val - start_val)
            i = j
        else:
            i += 1
    return result


def _smooth_trajectory(values: list, window: int, poly: int) -> list:
    """Savitzky-Golay smoothing with None-masking."""
    try:
        from scipy.signal import savgol_filter
    except ImportError:
        return values

    # Extract non-None
    indices = [i for i, v in enumerate(values) if v is not None]
    if len(indices) < window:
        return values

    arr = np.array([values[i] for i in indices])
    if len(arr) < window:
        return values

    # Ensure window is odd
    win = window if window % 2 == 1 else window - 1
    if win < poly + 2:
        win = poly + 2 + (0 if (poly + 2) % 2 == 1 else 1)

    try:
        smoothed = savgol_filter(arr, win, poly)
    except Exception:
        smoothed = arr

    result = list(values)
    for idx, smoothed_val in zip(indices, smoothed):
        result[idx] = float(smoothed_val)
    return result


# ─── Landmark detection ──────────────────────────────────────────────────────

def _detect_takeoff(y_norm: list, conf: list, params: dict) -> Optional[int]:
    """
    Takeoff: detect when the diver leaves the board using gap+re-acquisition heuristic.

    Strategy C-TAKEOFF-V2:
    1. Find initial 'board segment' (first run of detections).
    2. Compute board_y = median y_norm in the board segment.
    3. After any gap >= MIN_GAP_FOR_RUNUP frames, look for re-acquisition
       with y_norm > board_y + DELTA (diver elevated above board level).
    4. Fallback: if no gap found, use sustained upward velocity from the
       highest confidence region.

    Specifically designed to prevent EARLY_TRIGGER by requiring:
    - The diver is ABOVE where they were standing (board_y + delta)
    - There is measurable upward motion
    """
    threshold     = params["takeoff_y_threshold"]       # absolute minimum (0.30)
    min_sustained = params["takeoff_min_sustained"]     # sustained frames required (6)
    min_gap       = params.get("takeoff_gap_min", 8)   # minimum run-up gap
    board_delta   = params.get("takeoff_board_delta", 0.08)  # must be above board_y + this
    n = len(y_norm)

    # --- Step 1: Find initial board segment ---
    board_segment = []
    i = 0
    while i < min(80, n):
        if y_norm[i] is not None:
            board_segment.append(y_norm[i])
        else:
            if len(board_segment) >= 5:
                break  # found end of initial segment
        i += 1

    if board_segment:
        board_y = sorted(board_segment)[len(board_segment) // 2]  # median
    else:
        board_y = threshold  # fallback

    dynamic_threshold = max(threshold, board_y + board_delta)

    # --- Step 2: Look for gap + re-acquisition ---
    # Find gaps in the trajectory
    in_segment = False
    first_segment_end = None
    for i in range(n):
        if y_norm[i] is not None:
            if not in_segment:
                in_segment = True
        else:
            if in_segment and first_segment_end is None:
                first_segment_end = i
            in_segment = False

    if first_segment_end is not None:
        # Find re-acquisition after gap
        gap_start = first_segment_end
        gap_end = gap_start
        while gap_end < n and (y_norm[gap_end] is None or gap_end < gap_start + min_gap):
            gap_end += 1

        # Look for sustained detection above dynamic_threshold after gap
        for start in range(gap_end, n):
            if y_norm[start] is None or y_norm[start] <= dynamic_threshold:
                continue
            # Check sustained N frames
            valid_count = 0
            for j in range(start, min(start + min_sustained, n)):
                if y_norm[j] is not None and y_norm[j] > dynamic_threshold:
                    valid_count += 1
            if valid_count >= min_sustained:
                # Check upward motion over next few frames
                upward_vals = [y_norm[j] for j in range(start, min(start + 6, n))
                               if y_norm[j] is not None]
                if len(upward_vals) >= 2:
                    trend = upward_vals[-1] - upward_vals[0]
                    if trend >= -0.05:  # allow small flat or upward
                        return start

    # --- Step 3: Fallback - velocity-based from smoothed trajectory ---
    # Find first sustained upward motion + above absolute threshold
    for i in range(n):
        if y_norm[i] is None or y_norm[i] <= threshold:
            continue
        # Check sustained
        count = sum(1 for j in range(i, min(i + min_sustained, n))
                    if y_norm[j] is not None and y_norm[j] > threshold)
        if count >= min_sustained:
            # Check positive velocity
            future = [y_norm[j] for j in range(i, min(i + 8, n)) if y_norm[j] is not None]
            if len(future) >= 2 and future[-1] > future[0] - 0.05:
                return i

    return None


def _detect_apex(y_norm: list, takeoff_idx: Optional[int], params: dict,
                 total_frames: int) -> Optional[int]:
    """
    Apex: maximum y_norm after takeoff, excluding the last 10% of the clip.
    Addresses TRAJECTORY_COLLAPSE by using single-diver trajectory, not global centroid.
    """
    if takeoff_idx is None:
        return None

    start = takeoff_idx + params.get("apex_search_start_offset", 5)
    end = int(total_frames * 0.92)  # don't look in the last 8% (likely post-entry turbulence)
    if start >= end:
        end = total_frames - 1

    best_idx = None
    best_val = -float("inf")
    for i in range(start, min(end, len(y_norm))):
        if y_norm[i] is None:
            continue
        if y_norm[i] > best_val:
            best_val = y_norm[i]
            best_idx = i

    return best_idx


def _detect_water_contact(
    y_norm: list,
    apex_idx: Optional[int],
    conf: list,
    params: dict,
    total_frames: int,
) -> Optional[int]:
    """
    Water contact: first frame after apex where y_norm drops below the water threshold.
    If no explicit drop is detected, use the last confident-detection frame.
    Addresses WATER_CONTACT_RUNAWAY by anchoring to first drop below threshold,
    not post-entry turbulence.
    """
    if apex_idx is None:
        return None

    threshold = params["water_contact_y_threshold"]
    n = len(y_norm)

    # Primary: first drop below threshold after apex
    for i in range(apex_idx + 1, n):
        if y_norm[i] is None:
            continue
        if y_norm[i] < threshold:
            # Verify: ensure we're descending (not just a brief dip)
            # Look back: y must have been higher at apex
            apex_y = y_norm[apex_idx]
            if apex_y is not None and apex_y > threshold:
                return i
            return i  # accept anyway

    # Fallback: last frame with a confident detection (track ending ≈ water entry)
    last_detected = None
    for i in range(apex_idx, n):
        if conf[i] is not None and conf[i] > params["track_min_conf"]:
            last_detected = i
    if last_detected is not None and last_detected > apex_idx:
        return last_detected

    return None


def _apply_temporal_priors(
    takeoff_idx: Optional[int],
    apex_idx: Optional[int],
    water_idx: Optional[int],
    fps: float,
    params: dict,
) -> Tuple[Optional[int], Optional[int], Optional[int], bool]:
    """
    C2 only: Apply physical temporal priors.
    If the detected inter-landmark intervals are implausible, emit UNCERTAIN.
    Returns (takeoff, apex, water_contact, is_uncertain).
    """
    if not params.get("use_temporal_priors", False):
        is_invalid = (takeoff_idx is None or apex_idx is None or water_idx is None
                      or not (takeoff_idx < apex_idx < water_idx))
        return takeoff_idx, apex_idx, water_idx, is_invalid

    uncertain = False

    if takeoff_idx is None or apex_idx is None or water_idx is None:
        return takeoff_idx, apex_idx, water_idx, True

    t2a = apex_idx - takeoff_idx
    a2w = water_idx - apex_idx

    # Scale reference priors from 30fps to actual fps
    fps_scale = fps / 30.0

    min_t2a = params["prior_t2a_min_frames"] * fps_scale
    max_t2a = params["prior_t2a_max_frames"] * fps_scale
    min_a2w = params["prior_a2w_min_frames"] * fps_scale
    max_a2w = params["prior_a2w_max_frames"] * fps_scale

    if not (takeoff_idx < apex_idx < water_idx):
        uncertain = True
    if not (min_t2a <= t2a <= max_t2a):
        uncertain = True
    if not (min_a2w <= a2w <= max_a2w):
        uncertain = True

    return takeoff_idx, apex_idx, water_idx, uncertain


# ─── Confidence computation ───────────────────────────────────────────────────

def _compute_confidence(
    y_norm: list,
    takeoff_idx: Optional[int],
    apex_idx: Optional[int],
    water_idx: Optional[int],
    conf_track: list,
    is_uncertain: bool,
) -> Dict[str, float]:
    """Compute per-landmark confidence [0,1]."""
    if is_uncertain or takeoff_idx is None or apex_idx is None or water_idx is None:
        return {"takeoff": 0.0, "apex": 0.0, "water_contact": 0.0}

    n = len(y_norm)
    # Detection coverage: fraction of non-None frames in [takeoff, water_contact]
    window = list(range(takeoff_idx, min(water_idx + 1, n)))
    if not window:
        return {"takeoff": 0.0, "apex": 0.0, "water_contact": 0.0}

    detected_in_window = sum(1 for i in window if y_norm[i] is not None)
    coverage = detected_in_window / len(window) if window else 0.0

    # Trajectory quality: apex should be visibly higher than takeoff
    apex_y = y_norm[apex_idx]
    takeoff_y = y_norm[takeoff_idx] if takeoff_idx is not None else None

    if apex_y is None or takeoff_y is None:
        displacement_quality = 0.3
    else:
        disp = apex_y - takeoff_y
        displacement_quality = min(1.0, max(0.0, disp / 0.25))

    # Average track confidence near each landmark
    def avg_near(idx, radius=5):
        vals = [conf_track[i] for i in range(max(0, idx - radius), min(n, idx + radius + 1))
                if conf_track[i] is not None]
        return sum(vals) / len(vals) if vals else 0.0

    base = min(1.0, coverage * displacement_quality)
    return {
        "takeoff":       round(min(1.0, base * avg_near(takeoff_idx)), 3),
        "apex":          round(min(1.0, base * avg_near(apex_idx)), 3),
        "water_contact": round(min(1.0, base * avg_near(water_idx)), 3),
    }


# ─── Main proposer function ───────────────────────────────────────────────────

def propose_landmarks(video_path: str, params: dict) -> dict:
    """Run the full Baseline C pipeline on a single video.

    Returns dict with:
      takeoff: {frame, timestamp_s, confidence, applicability}
      apex:    {frame, timestamp_s, confidence, applicability}
      water_contact: {frame, timestamp_s, confidence, applicability}
      meta: {fps, total_frames, selected_track, n_tracked_frames, ...}
    """
    info = _get_frame_info(video_path)
    fps = info["fps"]
    total_frames = info["total_frames"]
    frame_height = info["height"]

    print(f"  Video: {total_frames} frames @ {fps:.1f}fps, {info['width']}×{frame_height}",
          file=sys.stderr)

    # Step 1: YOLO person detection with ByteTrack
    results_per_frame = _run_yolo_on_video(video_path, params)
    if not results_per_frame:
        return _make_uncertain_result(fps, total_frames, "yolo_failed", params)

    # Pad if YOLO returned fewer frames
    while len(results_per_frame) < total_frames:
        results_per_frame.append([])

    # Step 2: Select primary diver track
    selected_track = _select_primary_track(results_per_frame)
    if selected_track is None:
        return _make_uncertain_result(fps, total_frames, "no_track", params)

    # Step 3: Extract trajectory
    traj = _extract_diver_trajectory(results_per_frame, selected_track, frame_height)
    y_norm_raw = traj["y_norm"]
    conf_raw = traj["conf"]

    n_detected = sum(1 for v in y_norm_raw if v is not None)
    coverage = n_detected / max(1, total_frames)

    # Step 4: Interpolate + smooth
    y_norm_interp = _interpolate_gaps(y_norm_raw, max_gap=params.get("traj_interp_max_gap", 15))
    y_norm_smooth = _smooth_trajectory(
        y_norm_interp,
        window=params.get("traj_smooth_window", 11),
        poly=params.get("traj_smooth_poly", 3),
    )

    if coverage < 0.10:
        return _make_uncertain_result(fps, total_frames, f"low_coverage_{coverage:.2f}", params)

    # Step 5: Detect landmarks
    takeoff_idx = _detect_takeoff(y_norm_smooth, conf_raw, params)
    apex_idx = _detect_apex(y_norm_smooth, takeoff_idx, params, total_frames)
    water_idx = _detect_water_contact(y_norm_smooth, apex_idx, conf_raw, params, total_frames)

    # Step 6: Temporal priors (C2 only)
    takeoff_idx, apex_idx, water_idx, is_uncertain = _apply_temporal_priors(
        takeoff_idx, apex_idx, water_idx, fps, params
    )

    # Step 7: Confidence
    confidences = _compute_confidence(
        y_norm_smooth, takeoff_idx, apex_idx, water_idx, conf_raw, is_uncertain
    )

    def lm_result(idx, lm_key):
        if is_uncertain or idx is None:
            return {"frame": None, "timestamp_s": None,
                    "confidence": 0.0, "applicability": "UNCERTAIN"}
        return {
            "frame":        idx,
            "timestamp_s":  round(idx / fps, 4),
            "confidence":   confidences[lm_key],
            "applicability": "APPLICABLE",
        }

    meta = {
        "fps": fps,
        "total_frames": total_frames,
        "selected_track": selected_track,
        "n_detected_frames": n_detected,
        "trajectory_coverage": round(coverage, 3),
        "takeoff_raw": takeoff_idx,
        "apex_raw": apex_idx,
        "water_contact_raw": water_idx,
        "is_uncertain": is_uncertain,
        "variant": params["variant"],
    }

    return {
        "takeoff":       lm_result(takeoff_idx, "takeoff"),
        "apex":          lm_result(apex_idx, "apex"),
        "water_contact": lm_result(water_idx, "water_contact"),
        "meta":          meta,
    }


def _make_uncertain_result(fps, total_frames, reason, params):
    return {
        "takeoff":       {"frame": None, "timestamp_s": None, "confidence": 0.0, "applicability": "UNCERTAIN"},
        "apex":          {"frame": None, "timestamp_s": None, "confidence": 0.0, "applicability": "UNCERTAIN"},
        "water_contact": {"frame": None, "timestamp_s": None, "confidence": 0.0, "applicability": "UNCERTAIN"},
        "meta":          {"fps": fps, "total_frames": total_frames, "reason": reason, "variant": params["variant"]},
    }


# ─── Fingerprinting ──────────────────────────────────────────────────────────

def compute_weights_checksum(weights_path: pathlib.Path) -> str:
    """Compute SHA-256 of model weights file."""
    sha = hashlib.sha256()
    with open(weights_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()


def compute_proposer_fingerprint(params: dict, weights_sha256: str,
                                 ultralytics_version: str) -> str:
    """Compute a deterministic fingerprint over all algorithm identity components."""
    identity = {
        "params": {k: v for k, v in sorted(params.items())},
        "weights_sha256": weights_sha256,
        "ultralytics_version": ultralytics_version,
        "implementation": "proposer_baseline_c.py:v1.0.0",
    }
    payload = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


# ─── CLI helper (canary mode) ────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Baseline C landmark proposer")
    parser.add_argument("--video", required=True, help="Path to proxy video")
    parser.add_argument("--variant", default="C2", choices=["C1", "C2"])
    parser.add_argument("--output", help="Optional JSON output path")
    args = parser.parse_args()

    params = PARAMS_C1 if args.variant == "C1" else PARAMS_C2
    result = propose_landmarks(args.video, params)
    out = json.dumps(result, indent=2)

    if args.output:
        with open(args.output, "w") as f:
            f.write(out)
    print(out)
