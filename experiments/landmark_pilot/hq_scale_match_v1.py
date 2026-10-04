#!/usr/bin/env python3
"""Scale-search template matching between HQ frames and proxy frames.

For quarantined assets: determines whether HQ content is a zoomed/cropped
version of the proxy content, recovering (scale, x, y, temporal offset)
explicitly. Both sides are decoded with display orientation (autorotate) and
resampled to a COMMON search width so scale=1.0 means identical framing.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np

COMMON_W = 480
SCALES = [1.0, 1.1, 1.25, 1.4, 1.6, 1.8, 2.0, 2.3, 2.6, 3.0, 3.5, 4.0, 5.0, 6.0]
HQ_FRAMES = 16
PROXY_STRIDE = 4  # at 8 fps sampling -> 2 fps search grid
MIN_TEMPLATE = 60


def probe_dims(path: str) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
        text=True, stdout=subprocess.PIPE, check=False).stdout.strip()
    w, h = [int(x) for x in out.split(",")[:2]]
    return w, h


def sample_frames(path: str, max_frames: int, width: int, fps: float = 8.0,
                  autorotate: bool = True) -> np.ndarray:
    """Decode sampled at fps, common width; orientation per autorotate flag."""
    vf = f"fps={fps},scale={width}:-2:flags=area"
    rot = [] if autorotate else ["-noautorotate"]
    base = ["ffmpeg", *rot, "-v", "error", "-i", path, "-vf", vf]
    out_args = ["-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    head = subprocess.run(base + ["-frames:v", "1"] + out_args,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False).stdout
    if not head:
        return np.zeros((0, 0, 0, 3), np.uint8)
    hs = len(head) // (width * 3)
    fb = width * hs * 3
    raw = subprocess.run(base + out_args,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False).stdout
    cnt = len(raw) // fb
    fr = np.frombuffer(raw[: cnt * fb], dtype=np.uint8).reshape(cnt, hs, width, 3).copy()
    return fr[:max_frames]


def sample_even(path: str, n: int, width: int, fps: float = 8.0,
                autorotate: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """Sample n frames evenly from the fps stream; return (frames, times_s)."""
    fr = sample_frames(path, 100000, width, fps, autorotate)
    idx = np.linspace(0, len(fr) - 1, min(n, len(fr))).astype(int)
    return fr[idx], idx / fps


def prep(img: np.ndarray, transform: str = "identity") -> np.ndarray:
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    g = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(g)
    if transform == "hflip":
        g = g[:, ::-1]
    return np.ascontiguousarray(g)


def match_one(template: np.ndarray, search: np.ndarray, scale: float) -> tuple[float, tuple[int, int], tuple[int, int]]:
    """Template (HQ frame at common width) matched into search (proxy frame at
    common width) after downscaling the template by `scale` (zoom factor)."""
    ph, pw = search.shape
    tw = max(MIN_TEMPLATE, int(round(template.shape[1] / scale)))
    th = max(MIN_TEMPLATE, int(round(template.shape[0] / scale)))
    if th > ph or tw > pw:
        return -1.0, (-1, -1), (0, 0)
    t = cv2.resize(template, (tw, th), interpolation=cv2.INTER_AREA)
    res = cv2.matchTemplate(search, t, cv2.TM_CCOEFF_NORMED)
    _, maxv, _, maxloc = cv2.minMaxLoc(res)
    return float(maxv), maxloc, (tw, th)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--hq", required=True)
    p.add_argument("--proxy", required=True)
    p.add_argument("--label", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--score-threshold", type=float, default=0.65)
    p.add_argument("--hq-transform", default="identity", choices=["identity","hflip"])
    args = p.parse_args()

    per_frame = []
    orientation_modes = [(True, True), (False, False), (True, False), (False, True)]
    best_mode_scores = []
    for rot_hq, rot_proxy in orientation_modes:
        hq_frames, hq_times = sample_even(args.hq, HQ_FRAMES, COMMON_W, autorotate=rot_hq)
        proxy_frames, _ = sample_even(args.proxy, 100000, COMMON_W, autorotate=rot_proxy)
        if len(hq_frames) == 0 or len(proxy_frames) == 0:
            continue
        proxy_frames = proxy_frames[::PROXY_STRIDE]
        proxy_prep = [prep(f) for f in proxy_frames]
        proxy_times = np.arange(len(proxy_frames)) * PROXY_STRIDE / 8.0

        mode_scores = []
        for i, f in enumerate(hq_frames):
            template = prep(f, args.hq_transform)
            best = {"score": -1.0}
            for s in SCALES:
                for j, pf in enumerate(proxy_prep):
                    score, loc, tsize = match_one(template, pf, s)
                    if score > best["score"]:
                        best = {"score": score, "scale": s,
                                "proxy_frame_idx": j, "proxy_t_s": float(proxy_times[j]),
                                "loc": loc, "template_size": tsize,
                                "hq_sample_idx": i, "hq_t_s": float(hq_times[i])}
            mode_scores.append(best)
            print(f"[rot hq={rot_hq} px={rot_proxy}] frame {i:2d} t_hq={best['hq_t_s']:6.2f}s "
                  f"score={best['score']:.3f} scale={best.get('scale')} "
                  f"proxy_t={best.get('proxy_t_s', -1):7.2f}s loc={best.get('loc')}")
        best_mode_scores.append(((rot_hq, rot_proxy), mode_scores))

    if not best_mode_scores:
        raise SystemExit("no decodable orientation mode")
    res_rot, per_frame = max(
        best_mode_scores, key=lambda ms: float(np.mean([x["score"] for x in ms[1]]))
    )
    orientation_used = {"hq_autorotate": res_rot[0], "proxy_autorotate": res_rot[1]}

    good = [x for x in per_frame if x["score"] >= args.score_threshold]
    summary = {
        "label": args.label,
        "hq": args.hq,
        "proxy": args.proxy,
        "common_search_width": COMMON_W,
        "score_threshold": args.score_threshold,
        "orientation_used": orientation_used,
        "hq_transform": args.hq_transform,
        "n_frames": len(per_frame),
        "n_good_frames": len(good),
        "per_frame": per_frame,
        "verdict": ("SAME_CONTENT_WITH_SPATIAL_TRANSFORM"
                    if len(good) >= max(4, len(per_frame) // 2) else
                    "MATCH_NOT_ESTABLISHED"),
    }
    Path(args.out).write_text(json.dumps(summary, indent=2))
    print("verdict:", summary["verdict"], f"({len(good)}/{len(per_frame)} frames >= {args.score_threshold})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
