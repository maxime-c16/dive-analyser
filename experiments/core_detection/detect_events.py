"""Entry-spotting: eventness time series -> candidate dive events.

Baseline V0 (visual eventness): splash-like burst energy in the water region,
optionally gated/fused with board-region motion. No GT-derived windows: the
score is computed over the full session and candidates come from a
deterministic threshold rule + refractory period.

Baseline V1 (optional audio supplement): splash transient score from the
audio track; fused only when the audio track is usable.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from protocol import EVENTNESS_SMOOTH_S, EVENTNESS_Z_K, REFRACTORY_S
from scan_features import ScanFeatures


def robust_sigma(x: np.ndarray) -> tuple[float, float]:
    med = float(np.median(x))
    mad = float(np.median(np.abs(x - med)))
    return med, 1.4826 * mad


def smooth(x: np.ndarray, fps: float, half_window_s: float) -> np.ndarray:
    k = max(1, int(round(half_window_s * fps)))
    kernel = np.ones(2 * k + 1) / (2 * k + 1)
    return np.convolve(x, kernel, mode="same")


@dataclass
class EventCandidate:
    event_time: float
    score: float
    rough_start: float
    rough_end: float


def eventness(feat: ScanFeatures, water_weight: float = 0.7,
              board_weight: float = 0.3) -> np.ndarray:
    """Splash-burst eventness: water-region motion burst + board motion."""
    wd = smooth(feat.water_diff, feat.fps, EVENTNESS_SMOOTH_S)
    bd = smooth(feat.board_diff, feat.fps, EVENTNESS_SMOOTH_S)
    return water_weight * wd + board_weight * bd


def pick_candidates(score: np.ndarray, ts: np.ndarray,
                    pre_roll: float, post_roll: float,
                    z_k: float = EVENTNESS_Z_K,
                    refractory_s: float = REFRACTORY_S) -> list[EventCandidate]:
    med, sigma = robust_sigma(score)
    thr = med + z_k * max(sigma, 1e-9)
    above = score > thr
    cands: list[EventCandidate] = []
    last_t = -1e9
    for i in np.where(above)[0]:
        t = float(ts[i])
        if t - last_t < refractory_s:
            # keep the stronger event inside the refractory window
            if cands and score[i] > cands[-1].score and t - cands[-1].event_time < refractory_s:
                cands[-1] = EventCandidate(
                    event_time=t, score=float(score[i]),
                    rough_start=t - pre_roll, rough_end=t + post_roll,
                )
                last_t = t
            continue
        cands.append(EventCandidate(
            event_time=t, score=float(score[i]),
            rough_start=t - pre_roll, rough_end=t + post_roll,
        ))
        last_t = t
    return cands


def extract_audio(video: Path, out_wav: Path, rate: int = 16000) -> Path | None:
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    if out_wav.exists() and out_wav.stat().st_size > 0:
        return out_wav
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
         "-vn", "-ac", "1", "-ar", str(rate), "-f", "wav", str(out_wav)],
        capture_output=True,
    )
    if r.returncode != 0 or not out_wav.exists() or out_wav.stat().st_size < 44:
        return None
    return out_wav


def audio_transient_score(wav: Path, rate: int = 16000):
    """Broadband onset energy per 0.25 s hop. Returns (ts, score) or None."""
    import wave

    with wave.open(str(wav), "rb") as w:
        n = w.getnframes()
        if n < rate:
            return None
        data = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
    hop = rate // 4
    n_hops = n // hop
    if n_hops < 8:
        return None
    frames = data[: n_hops * hop].reshape(n_hops, hop)
    energy = (frames ** 2).mean(axis=1)
    log_e = np.log10(energy + 1e-10)
    onset = np.clip(np.diff(log_e, prepend=log_e[0]), 0, None)
    ts = np.arange(n_hops) * 0.25
    return ts, onset
