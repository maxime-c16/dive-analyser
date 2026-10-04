"""Full-session scanning feature extraction for Core Detection V1.

Decodes a raw session ONCE into a disk-backed grayscale thumbnail stream
(ffmpeg, 2 fps, 480x270) and derives cheap per-timestamp visual features:

  diff_energy(t)      global frame-to-frame absolute difference energy
  water_diff(t)       frame-difference energy inside the water region
  board_diff(t)       frame-difference energy inside the board/launch region
  brightness(t)       mean luma (scene-change / exposure diagnostics)

No GT-derived search windows: the scan covers the whole session.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from protocol import SCAN_FPS, SCAN_WIDTH


@dataclass
class ScanFeatures:
    ts: np.ndarray          # seconds (PTS-based, from ffmpeg fps filter clock)
    diff_energy: np.ndarray
    water_diff: np.ndarray
    board_diff: np.ndarray
    brightness: np.ndarray
    n_frames: int
    width: int
    height: int
    fps: float


def probe_video(path: Path) -> dict:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ],
        capture_output=True, text=True, check=True,
    ).stdout
    info = json.loads(out)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    return {
        "duration": float(info["format"]["duration"]),
        "width": v["width"],
        "height": v["height"],
        "avg_frame_rate": v.get("avg_frame_rate"),
        "r_frame_rate": v.get("r_frame_rate"),
        "codec": v["codec_name"],
        "has_audio": a is not None,
        "audio_codec": a["codec_name"] if a else None,
        "size_bytes": info["format"].get("size"),
    }


def extract_thumbnail_stream(
    video: Path, out_gray: Path, width: int = SCAN_WIDTH,
    fps: float = SCAN_FPS,
) -> tuple[Path, int, int]:
    """Decode the full session into a raw grayscale thumbnail file (disk-backed).

    Rotation-safe: ffmpeg autorotates, then we scale the LONG side to `width`
    keeping aspect (scale=width:-2), so portrait sessions yield portrait
    thumbnails. Returns (path, actual_width, actual_height).
    """
    out_gray.parent.mkdir(parents=True, exist_ok=True)
    if out_gray.exists() and out_gray.stat().st_size > 0:
        # recover dims from file size is impossible; require sidecar
        side = out_gray.with_suffix(".dims.json")
        dims = json.loads(side.read_text())
        return out_gray, dims["w"], dims["h"]
    tmp = out_gray.with_suffix(".gray.part")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(video),
        "-vf", f"fps={fps},scale={width}:-2,format=gray",
        "-an", "-f", "rawvideo", "-pix_fmt", "gray", str(tmp),
    ]
    subprocess.run(cmd, check=True)
    size = tmp.stat().st_size
    # dims: probe the autorotated/scaled output via a 1-frame run
    probe = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
         "-vf", f"fps={fps},scale={width}:-2,format=gray", "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, check=True).stdout
    npx = len(probe)
    h = npx // width if npx else SCAN_HEIGHT
    w = width
    if npx == 0:
        raise RuntimeError("empty thumbnail probe")
    tmp.rename(out_gray)
    out_gray.with_suffix(".dims.json").write_text(
        json.dumps({"w": w, "h": h, "fps": fps}))
    return out_gray, w, h


def load_thumbnail_stream(gray_path: Path, width: int,
                          height: int) -> np.ndarray:
    n = gray_path.stat().st_size // (width * height)
    return np.fromfile(str(gray_path), dtype=np.uint8, count=n * width * height).reshape(
        n, height, width
    )


def compute_features(frames: np.ndarray, fps: float,
                     water_band: tuple[float, float],
                     board_band: tuple[float, float]) -> ScanFeatures:
    """frames: (N, H, W) uint8 grayscale thumbnails at `fps` thumbnails/s.

    water_band / board_band are (row_top_frac, row_bottom_frac) fractions of
    the frame height, frozen in the protocol after one-session inspection.

    Memory-lean: band energies slice rows first; the global diff energy is
    accumulated in time chunks so no full-session float array is materialized.
    """
    h = frames.shape[1]

    def band_energy(band: tuple[float, float]) -> np.ndarray:
        r0, r1 = int(band[0] * h), int(band[1] * h)
        f = frames[:, r0:r1, :].astype(np.float32)
        diff = np.abs(np.diff(f, axis=0))
        return (diff ** 2).mean(axis=(1, 2))

    # global diff energy in time chunks (identical values, bounded memory)
    chunk = 512
    de = np.empty(frames.shape[0] - 1, dtype=np.float64)
    for i in range(0, frames.shape[0] - 1, chunk):
        j = min(i + chunk + 1, frames.shape[0])
        d = np.abs(np.diff(frames[i:j].astype(np.float32), axis=0))
        de[i:i + d.shape[0]] = (d ** 2).mean(axis=(1, 2))

    ts = np.arange(frames.shape[0] - 1) / fps
    return ScanFeatures(
        ts=ts,
        diff_energy=de,
        water_diff=band_energy(water_band),
        board_diff=band_energy(board_band),
        brightness=frames.mean(axis=(1, 2), dtype=np.float64),
        n_frames=frames.shape[0],
        width=frames.shape[2],
        height=h,
        fps=fps,
    )
