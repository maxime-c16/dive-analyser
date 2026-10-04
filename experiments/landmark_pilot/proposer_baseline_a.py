#!/usr/bin/env python3
"""Baseline A Temporal Landmark Proposer — Motion Energy + Vertical Centroid.

Algorithm:
    1. Subsample proxy video at every N-th frame (default: 4 for 30fps → ~8fps).
    2. Compute inter-frame difference mask to isolate moving region (foreground).
    3. Extract vertical centroid of largest moving blob per sampled frame.
    4. Apply Gaussian smoothing to centroid time series.
    5. Detect takeoff: largest upward velocity transition (centroid moving up fastest).
    6. Detect apex: maximum centroid height (minimum pixel Y-coordinate).
    7. Detect water_contact: maximum foreground area after apex in bottom region.

All outputs are AUTO-source landmark proposals.
This is EXPERIMENTAL and not scientifically validated.

Environment: use with experiments/landmark_pilot/venv
"""

import sys
import json
import hashlib
import logging
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.signal import argrelextrema

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("proposer_a")

ALGORITHM_KEY = "baseline_a_motion_centroid"
ALGORITHM_VERSION = "1.0.0"

# Subsample: analyze every N-th frame (4 → 7.5fps at 30fps)
FRAME_STEP = 4

# Gaussian smoothing sigma (in units of sampled frames)
SMOOTH_SIGMA = 3.0

# Bottom region fraction for water-contact detection
SPLASH_REGION_FRACTION = 0.30

# Minimum contour area to be considered "diver" (pixels at 360p)
MIN_CONTOUR_AREA = 500


@dataclass
class LandmarkProposal:
    """Proposed temporal landmark for one key."""
    landmark_key: str
    frame_index: Optional[int]      # 0-based frame in the clip
    timestamp_seconds: Optional[float]
    confidence: Optional[float]     # 0..1
    applicability: str              # APPLICABLE | NOT_APPLICABLE | UNCERTAIN
    source: str = "AUTO"
    algorithm_key: str = ALGORITHM_KEY
    algorithm_version: str = ALGORITHM_VERSION
    uncertainty_window_frames: Optional[int] = None


@dataclass
class ProposalResult:
    """Full result for one clip."""
    clip_path: str
    media_key: str
    dive_id: int
    fps: float
    total_frames: int
    duration_seconds: float
    input_checksum_sha256: Optional[str]
    landmarks: list   # list of LandmarkProposal
    diagnostics: dict  # internal debug data


def _checksum(path: str) -> Optional[str]:
    """SHA-256 of a file (reads in chunks)."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _extract_centroid_series(clip_path: str, frame_step: int = FRAME_STEP):
    """Extract per-frame foreground centroid and area.

    Returns:
        frame_indices: np.array of shape (N,)
        centroids_y: np.array of shape (N,) — pixel Y of centroid (lower = higher in image)
        fg_areas: np.array of shape (N,) — foreground pixel count
        fps: float
        total_frames: int
    """
    cap = cv2.VideoCapture(clip_path)
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {clip_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # Use MOG2 background subtractor
    bg_sub = cv2.createBackgroundSubtractorMOG2(
        history=30, varThreshold=25, detectShadows=False
    )

    frame_indices = []
    centroids_y = []
    fg_areas = []

    f_idx = 0
    sampled = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if f_idx % frame_step == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            fg_mask = bg_sub.apply(gray)

            # Morphological cleanup
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
            fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)

            # Find contours
            contours, _ = cv2.findContours(
                fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )

            # Filter small contours and find largest
            valid = [c for c in contours if cv2.contourArea(c) > MIN_CONTOUR_AREA]
            fg_area = sum(cv2.contourArea(c) for c in valid)

            if valid:
                largest = max(valid, key=cv2.contourArea)
                M = cv2.moments(largest)
                if M["m00"] > 0:
                    cy = M["m01"] / M["m00"]   # vertical centroid pixel
                else:
                    cy = float(h) / 2
            else:
                cy = float(h) / 2

            frame_indices.append(f_idx)
            centroids_y.append(cy)
            fg_areas.append(fg_area)
            sampled += 1

        f_idx += 1

    cap.release()

    return (
        np.array(frame_indices, dtype=int),
        np.array(centroids_y, dtype=float),
        np.array(fg_areas, dtype=float),
        fps,
        total_frames,
    )


def propose_landmarks(
    clip_path: str,
    media_key: str,
    dive_id: int,
    frame_step: int = FRAME_STEP,
    compute_checksum: bool = True,
) -> ProposalResult:
    """Propose takeoff, apex, and water_contact landmarks for a clip.

    Args:
        clip_path: Absolute path to proxy video file.
        media_key: Cache entry media key (for DB registration).
        dive_id: Dive ID (for DB registration).
    Returns:
        ProposalResult with three LandmarkProposal entries.
    """
    log.info("Processing dive %d from %s", dive_id, clip_path)

    checksum = _checksum(clip_path) if compute_checksum else None

    try:
        frame_idxs, centroids_y, fg_areas, fps, total_frames = \
            _extract_centroid_series(clip_path, frame_step)
    except Exception as e:
        log.error("Failed to extract centroid series: %s", e)
        # Return NOT_APPLICABLE for all
        not_applic = [
            LandmarkProposal("takeoff", None, None, None, "NOT_APPLICABLE"),
            LandmarkProposal("apex", None, None, None, "NOT_APPLICABLE"),
            LandmarkProposal("water_contact", None, None, None, "NOT_APPLICABLE"),
        ]
        return ProposalResult(
            clip_path=clip_path, media_key=media_key, dive_id=dive_id,
            fps=0, total_frames=0, duration_seconds=0,
            input_checksum_sha256=checksum,
            landmarks=not_applic, diagnostics={"error": str(e)},
        )

    duration_seconds = total_frames / fps
    n = len(frame_idxs)
    if n < 10:
        log.warning("Too few sampled frames (%d) for dive %d", n, dive_id)
        return ProposalResult(
            clip_path=clip_path, media_key=media_key, dive_id=dive_id,
            fps=fps, total_frames=total_frames, duration_seconds=duration_seconds,
            input_checksum_sha256=checksum,
            landmarks=[
                LandmarkProposal("takeoff", None, None, 0.0, "UNCERTAIN"),
                LandmarkProposal("apex", None, None, 0.0, "UNCERTAIN"),
                LandmarkProposal("water_contact", None, None, 0.0, "UNCERTAIN"),
            ],
            diagnostics={"reason": "too_few_frames", "n": n},
        )

    # Skip first 20% of frames (background subtractor warmup period)
    warmup_idx = max(5, n // 5)

    # Smooth centroid trajectory
    smooth_y = gaussian_filter1d(centroids_y, sigma=SMOOTH_SIGMA)
    smooth_area = gaussian_filter1d(fg_areas, sigma=SMOOTH_SIGMA)

    # Velocity: dy/dt where negative = moving UP (lower pixel Y)
    velocity_y = np.gradient(smooth_y)

    # ----------------------------------------------------------------
    # TAKEOFF: frame with maximum upward velocity (most negative dy/dt)
    # after warmup. The diver accelerates upward most strongly at takeoff.
    # ----------------------------------------------------------------
    search_start = warmup_idx
    search_end = n * 2 // 3   # takeoff must be in first 2/3 of clip
    if search_end <= search_start:
        search_end = n - 1

    takeoff_rel = np.argmin(velocity_y[search_start:search_end]) + search_start
    takeoff_frame = int(frame_idxs[takeoff_rel])
    takeoff_time = takeoff_frame / fps

    # Confidence: how pronounced is the upward velocity at takeoff vs mean
    vel_range = np.ptp(velocity_y[search_start:search_end])
    takeoff_vel = abs(velocity_y[takeoff_rel])
    takeoff_conf = float(np.clip(takeoff_vel / (vel_range + 1e-6), 0, 1))

    # ----------------------------------------------------------------
    # APEX: frame with minimum centroid Y (highest point) after takeoff
    # ----------------------------------------------------------------
    apex_start = takeoff_rel
    apex_end = min(n, takeoff_rel + (n - takeoff_rel) * 3 // 4)
    if apex_end <= apex_start:
        apex_end = min(n - 1, apex_start + 5)

    apex_rel = np.argmin(smooth_y[apex_start:apex_end]) + apex_start
    apex_frame = int(frame_idxs[apex_rel])
    apex_time = apex_frame / fps

    # Confidence: drop from takeoff-height to apex vs total range
    height_drop = smooth_y[takeoff_rel] - smooth_y[apex_rel]
    total_range = np.ptp(smooth_y)
    apex_conf = float(np.clip(height_drop / (total_range + 1e-6), 0, 1))

    # ----------------------------------------------------------------
    # WATER_CONTACT: largest sudden foreground expansion after apex,
    # concentrated in bottom third of frame.
    # ----------------------------------------------------------------
    wc_start = apex_rel
    # Compute area change (sudden increase = splash)
    area_diff = np.gradient(smooth_area)
    wc_search = area_diff[wc_start:]
    if len(wc_search) > 0:
        wc_rel = np.argmax(wc_search) + wc_start
    else:
        wc_rel = n - 1
    water_frame = int(frame_idxs[wc_rel])
    water_time = water_frame / fps

    # Confidence: area jump magnitude
    area_jump = area_diff[wc_rel] if wc_rel < len(area_diff) else 0
    area_jump_norm = float(np.clip(area_jump / (np.std(area_diff) * 3 + 1e-6), 0, 1))

    # ----------------------------------------------------------------
    # Ordering check: if ordering is violated, mark affected as UNCERTAIN
    # ----------------------------------------------------------------
    ordering_valid = (takeoff_frame < apex_frame < water_frame)
    if not ordering_valid:
        log.warning("Dive %d: landmark ordering violated T=%d A=%d W=%d — marking UNCERTAIN",
                    dive_id, takeoff_frame, apex_frame, water_frame)
        applicability_all = "UNCERTAIN"
        takeoff_conf = 0.0
        apex_conf = 0.0
        area_jump_norm = 0.0
    else:
        applicability_all = "APPLICABLE"

    landmarks = [
        LandmarkProposal(
            landmark_key="takeoff",
            frame_index=takeoff_frame,
            timestamp_seconds=round(takeoff_time, 4),
            confidence=round(takeoff_conf, 4),
            applicability=applicability_all,
            uncertainty_window_frames=frame_step * 2,
        ),
        LandmarkProposal(
            landmark_key="apex",
            frame_index=apex_frame,
            timestamp_seconds=round(apex_time, 4),
            confidence=round(apex_conf, 4),
            applicability=applicability_all,
            uncertainty_window_frames=frame_step * 2,
        ),
        LandmarkProposal(
            landmark_key="water_contact",
            frame_index=water_frame,
            timestamp_seconds=round(water_time, 4),
            confidence=round(area_jump_norm, 4),
            applicability=applicability_all,
            uncertainty_window_frames=frame_step * 2,
        ),
    ]

    diagnostics = {
        "n_sampled": n,
        "frame_step": frame_step,
        "smooth_sigma": SMOOTH_SIGMA,
        "warmup_frames": warmup_idx,
        "ordering_valid": ordering_valid,
        "centroid_range_px": round(float(total_range), 2),
        "takeoff_velocity": round(float(velocity_y[takeoff_rel]), 4),
        "apex_height_drop_px": round(float(height_drop), 2),
        "water_area_jump": round(float(area_jump), 1),
    }

    return ProposalResult(
        clip_path=clip_path, media_key=media_key, dive_id=dive_id,
        fps=fps, total_frames=total_frames, duration_seconds=round(duration_seconds, 4),
        input_checksum_sha256=checksum,
        landmarks=landmarks, diagnostics=diagnostics,
    )


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: proposer_baseline_a.py <clip_path> <dive_id> [media_key]")
        sys.exit(1)
    clip = sys.argv[1]
    dive = int(sys.argv[2])
    key = sys.argv[3] if len(sys.argv) > 3 else "unknown"
    result = propose_landmarks(clip, key, dive)
    print(json.dumps({
        "dive_id": result.dive_id,
        "fps": result.fps,
        "total_frames": result.total_frames,
        "duration_seconds": result.duration_seconds,
        "landmarks": [asdict(lm) for lm in result.landmarks],
        "diagnostics": result.diagnostics,
    }, indent=2))
