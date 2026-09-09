#!/usr/bin/env python3
"""Robust content-alignment between two video representations.

Designed for cross-representation comparison (360p proxy vs edited HQ) where
resolution, color/HDR transform, and orientation metadata may differ. Uses
monotonicity-robust frame descriptors (rank-normalized downsampled luminance),
cross-correlation over candidate temporal offsets, and an optional linear
time-scale fit. Returns an explicit alignment result suitable for manifest
recording.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"
SAMPLE_FPS = 8.0
DESC_W = 48


def probe(path: str) -> dict:
    proc = subprocess.run(
        [
            FFPROBE, "-v", "error", "-select_streams", "v:0",
            "-show_entries",
            "stream=width,height,codec_name,avg_frame_rate,r_frame_rate,nb_frames,duration:stream_side_data=rotation:stream_disposition=rotated",
            "-of", "json", path,
        ],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    return json.loads(proc.stdout or "{}")


def pts_sequence(path: str, max_frames: int = 4000) -> dict:
    """Frame PTS (seconds) sequence via ffprobe frames."""
    proc = subprocess.run(
        [
            FFPROBE, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "frame=pts_time",
            "-of", "csv=p=0", path,
        ],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    vals = []
    for line in proc.stdout.splitlines():
        token = line.strip().split(",")[0]
        if not token or token == "N/A":
            continue
        try:
            vals.append(float(token))
        except ValueError:
            continue
    vals = vals[:max_frames]
    return {
        "n": len(vals),
        "first_pts": vals[0] if vals else None,
        "last_pts": vals[-1] if vals else None,
        "pts": vals,
    }


def load_descriptors(path: str, fps: float = SAMPLE_FPS, w: int = DESC_W, h: int = 24,
                     transpose: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Decode frames sampled at fps into fixed w x h grayscale descriptors.

    Autorotation is disabled; orientation is controlled explicitly via
    ``transpose`` (None = as coded, 1 = 90cw, 2 = 90ccw) so both sides of a
    comparison can be normalized identically regardless of rotation metadata.
    """
    pre = f"transpose={transpose}," if transpose is not None else ""
    cmd = [
        FFMPEG, "-noautorotate", "-v", "error", "-i", path,
        "-vf", f"{pre}fps={fps},scale={w}:{h}:flags=area,format=gray",
        "-frames:v", "100000",
        "-f", "rawvideo", "-pix_fmt", "gray", "-",
    ]
    raw = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False).stdout
    frame_bytes = w * h
    n = len(raw) // frame_bytes
    frames = np.frombuffer(raw[: n * frame_bytes], dtype=np.uint8).reshape(n, h, w)
    z_desc, r_desc = [], []
    for f in frames:
        z = f.astype(np.float64)
        z = (z - z.mean()) / (z.std() + 1e-9)
        flat = f.astype(np.float64).ravel()
        order = np.argsort(flat, kind="stable")
        ranks = np.empty_like(order, dtype=np.float64)
        ranks[order] = np.linspace(0.0, 1.0, flat.size)
        r_desc.append(ranks)
        z_desc.append(z.ravel())
    return np.asarray(z_desc), np.asarray(r_desc)


def similarity_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    an = a - a.mean(axis=1, keepdims=True)
    bn = b - b.mean(axis=1, keepdims=True)
    an = an / (np.linalg.norm(an, axis=1, keepdims=True) + 1e-12)
    bn = bn / (np.linalg.norm(bn, axis=1, keepdims=True) + 1e-12)
    return an @ bn.T


def best_offset(sim: np.ndarray, min_overlap_frac: float = 0.6) -> dict:
    """HQ frames are rows, proxy frames are columns. Find integer offset k such
    that HQ[i] best matches proxy[i + k] with sufficient overlap."""
    n_hq, n_pr = sim.shape
    best = None
    for k in range(-(n_pr - 1), n_hq):
        i0, j0 = max(0, -k), max(0, k)
        overlap = min(n_hq - i0, n_pr - j0)
        if overlap < min_overlap_frac * min(n_hq, n_pr):
            continue
        mean_sim = float(np.mean(np.diag(sim[i0: i0 + overlap, j0: j0 + overlap])))
        if best is None or mean_sim > best["mean_sim"]:
            best = {"offset_frames": k, "mean_sim": mean_sim, "overlap_frames": overlap}
    return best or {"offset_frames": None, "mean_sim": None, "overlap_frames": 0}


def center_crop(arr: np.ndarray, frac: float) -> np.ndarray:
    """Crop each descriptor's spatial grid (stored row-major) to its center frac."""
    n = arr.shape[0]
    h, w = 24, DESC_W
    ch, cw = max(2, int(round(h * frac)) // 2 * 2), max(2, int(round(w * frac)) // 2 * 2)
    r0, c0 = (h - ch) // 2, (w - cw) // 2
    frames = arr.reshape(n, h, w)
    return frames[:, r0: r0 + ch, c0: c0 + cw].reshape(n, ch * cw)


def motion_sequence(desc: np.ndarray) -> np.ndarray:
    """Frame-to-frame motion descriptors (z-normed diffs), same length as input
    by duplicating the first motion vector."""
    d = np.diff(desc, axis=0)
    d = (d - d.mean(axis=1, keepdims=True)) / (d.std(axis=1, keepdims=True) + 1e-12)
    return np.vstack([d[:1], d])


def shiftable_baseline(sim: np.ndarray) -> float:
    """Mean similarity of the best offset against a randomly-permuted control,
    to contextualize the peak (guards against trivially high self-similarity)."""
    n_hq, n_pr = sim.shape
    rng = np.random.default_rng(0)
    vals = []
    for _ in range(20):
        perm = rng.permutation(n_pr)
        vals.append(float(np.mean(np.diag(sim[:, perm][:, : min(n_hq, n_pr)]))))
    return float(np.mean(vals))


@dataclass
class AlignmentResult:
    label: str
    a_path: str
    b_path: str
    a_probe: dict = field(default_factory=dict)
    b_probe: dict = field(default_factory=dict)
    a_pts: dict = field(default_factory=dict)
    b_pts: dict = field(default_factory=dict)
    offset_frames: int | None = None
    mean_similarity: float | None = None
    baseline_similarity: float | None = None
    overlap_frames: int = 0
    offset_seconds: float | None = None
    orientation: dict = field(default_factory=dict)
    crop_frac: float = 1.0
    app_sim: float | None = None
    mot_sim: float | None = None
    crop_scan: list = field(default_factory=list)
    verdict: str = "UNRESOLVED"

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "a_path": self.a_path,
            "b_path": self.b_path,
            "a_media": {k: self.a_probe.get(k) for k in ("width", "height", "codec_name", "avg_frame_rate", "duration")},
            "b_media": {k: self.b_probe.get(k) for k in ("width", "height", "codec_name", "avg_frame_rate", "duration")},
            "a_pts_summary": {k: self.a_pts[k] for k in ("n", "first_pts", "last_pts")},
            "b_pts_summary": {k: self.b_pts[k] for k in ("n", "first_pts", "last_pts")},
            "offset_frames_hq_vs_proxy": self.offset_frames,
            "offset_seconds": self.offset_seconds,
            "orientation": self.orientation,
            "crop_frac": self.crop_frac,
            "appearance_similarity": self.app_sim,
            "motion_similarity": self.mot_sim,
            "crop_scan": self.crop_scan,
            "mean_similarity": self.mean_similarity,
            "baseline_permuted_similarity": self.baseline_similarity,
            "overlap_frames": self.overlap_frames,
            "verdict": self.verdict,
        }


def combined_score(da: np.ndarray, db: np.ndarray) -> dict:
    """Appearance + motion similarity at integer offsets."""
    sim_app = similarity_matrix(da, db)
    ma, mb = motion_sequence(da), motion_sequence(db)
    sim_mot = similarity_matrix(ma, mb)
    best = None
    for sim, weight in ((sim_app, 0.5), (sim_mot, 0.5)):
        cand = best_offset(sim)
        cand["kind"] = "appearance" if weight == 0.5 else "motion"
        if best is None or cand["mean_sim"] > best["mean_sim"]:
            best = cand
    # joint score at the best appearance offset
    def diag_mean(sim: np.ndarray, k: int) -> float:
        n_hq, n_pr = sim.shape
        i0, j0 = max(0, -k), max(0, k)
        overlap = min(n_hq - i0, n_pr - j0)
        if overlap <= 0:
            return float("nan")
        return float(np.mean(np.diag(sim[i0: i0 + overlap, j0: j0 + overlap])))
    k = best["offset_frames"] or 0
    return {
        "offset_frames": best["offset_frames"],
        "best_kind": best["kind"],
        "app_sim": diag_mean(sim_app, k),
        "mot_sim": diag_mean(sim_mot, k),
        "overlap_frames": best["overlap_frames"],
    }


def align_pair(label: str, hq_path: str, proxy_path: str, threshold: float = 0.5) -> AlignmentResult:
    res = AlignmentResult(label=label, a_path=hq_path, b_path=proxy_path)
    res.a_probe = (probe(hq_path).get("streams") or [{}])[0]
    res.b_probe = (probe(proxy_path).get("streams") or [{}])[0]
    res.a_pts = pts_sequence(hq_path)
    res.b_pts = pts_sequence(proxy_path)

    # orientation scan on appearance+motion
    best_overall, best_ta, best_tb = None, None, None
    for ta in (None, 1, 2):
        _, da = load_descriptors(hq_path, transpose=ta)
        for tb in (None, 1, 2):
            _, db = load_descriptors(proxy_path, transpose=tb)
            cand = combined_score(da, db)
            score = (cand["app_sim"] or -1) + (cand["mot_sim"] or -1)
            if best_overall is None or score > best_overall:
                best_overall, best_ta, best_tb = score, ta, tb
    res.orientation = {"hq_transpose": best_ta, "proxy_transpose": best_tb}

    _, da = load_descriptors(hq_path, transpose=best_ta)
    _, db = load_descriptors(proxy_path, transpose=best_tb)

    full = combined_score(da, db)
    res.offset_frames = full["offset_frames"]
    res.overlap_frames = full["overlap_frames"]
    res.crop_frac = 1.0
    res.app_sim = full["app_sim"]
    res.mot_sim = full["mot_sim"]

    # crop scan (center crops applied in descriptor space)
    crop_results = []
    for frac in (1.0, 0.85, 0.7, 0.6, 0.5, 0.4):
        cand = combined_score(center_crop(da, frac), center_crop(db, frac))
        cand["crop_frac"] = frac
        crop_results.append(cand)
        cand_score = (cand["app_sim"] or -1) + (cand["mot_sim"] or -1)
        if cand_score > (full["app_sim"] or -1) + (full["mot_sim"] or -1):
            full = cand
            res.offset_frames = cand["offset_frames"]
            res.overlap_frames = cand["overlap_frames"]
            res.crop_frac = frac
            res.app_sim = cand["app_sim"]
            res.mot_sim = cand["mot_sim"]

    res.baseline_similarity = shiftable_baseline(
        similarity_matrix(center_crop(da, res.crop_frac), center_crop(db, res.crop_frac)))
    fps_a = 1.0 / np.mean(np.diff(res.a_pts["pts"])) if res.a_pts["n"] > 2 else None
    if res.offset_frames is not None and fps_a:
        res.offset_seconds = res.offset_frames / fps_a
    res.crop_scan = crop_results
    strength = max(res.app_sim or -1, res.mot_sim or -1)
    if strength >= threshold and strength > (res.baseline_similarity or 0) + 0.2:
        res.verdict = "ALIGNED_SAME_OFFSET"
    elif strength >= threshold:
        res.verdict = "ALIGNED_WEAK_SEPARATION"
    else:
        res.verdict = "NO_ALIGNMENT_AT_INTEGER_OFFSET"
    return res


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--pairs-json", required=True,
                   help='[{"label":..., "hq":..., "proxy":...}, ...]')
    p.add_argument("--out", required=True)
    args = p.parse_args()
    pairs = json.loads(Path(args.pairs_json).read_text())
    results = [align_pair(x["label"], x["hq"], x["proxy"]).to_dict() for x in pairs]
    Path(args.out).write_text(json.dumps({"results": results}, indent=2))
    for r in results:
        print(f"{r['label']}: {r['verdict']} app={r['appearance_similarity']} "
              f"mot={r['motion_similarity']} offset={r['offset_frames_hq_vs_proxy']} "
              f"({r['offset_seconds']}s) crop={r['crop_frac']} baseline={r['baseline_permuted_similarity']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
