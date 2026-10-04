"""Deterministic clip -> raw-session alignment (GT recovery), verifier v2.

Verifier v1 matched raw thumbnails directly. In this static indoor-pool scene
raw signatures are nearly undiscriminating (global median NCC ~0.99, peak
margins ~0.0003), producing bogus offsets and all-WEAK output. Verified
diagnosis: raw-NCC top peaks land in empty static pool segments (false
matches, confirmed by frame inspection), while temporal-derivative signatures
|sig[t+1] - sig[t]| separate true motion events from the static background.

Verifier v2 (registered before any event-level evaluation):
  1. Per clip derivative frame: NCC against ALL session derivative frames.
     A frame votes its offset iff the best peak has robust-z prominence
     >= ALIGN_DERIV_Z_MIN over the frame's own score background (excluding
     +-ALIGN_DERIV_EXCLUDE_IDX) and NCC >= ALIGN_DERIV_NCC_MIN.
  2. Votes are clustered by offset (tolerance ALIGN_CLUSTER_TOL_S). Each
     cluster gets a path score: mean derivative NCC over all energetic clip
     frames mapped at the cluster offset (energy >= 0.2 * max frame energy).
  3. Clusters with >= 2 votes are ranked by path score. The top cluster is
     ACCEPTED iff all of:
       - cluster size >= ALIGN_MIN_CLUSTER (4), or >= 3 for captioned clips
         (the caption guarantees exactly one real dive; alignment only
         locates it);
       - path score >= ALIGN_PATH_MIN;
       - path margin over the best other cluster (size >= 2) is
         >= ALIGN_PATH_MARGIN (ambiguity guard: similar dives elsewhere in
         the session attract splash frames; unresolved ties stay WEAK);
       - raw-signature block NCC (9 consecutive signatures, ALIGN_RAW_BLOCK
         samples) >= ALIGN_RAW_NCC_MIN at the consensus offset (sanity floor).
  4. Consensus offset = median of cluster vote offsets.

Acceptance -> DETERMINISTICALLY_RECOVERED_GT window (authority DIRECT for
captioned clips). Anything else is WEAK_LABEL (diagnostics only) or FAILED.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from protocol import (
    ALIGN_CLUSTER_TOL_S,
    ALIGN_DERIV_EXCLUDE_IDX,
    ALIGN_DERIV_NCC_MIN,
    ALIGN_DERIV_Z_MIN,
    ALIGN_MIN_CLUSTER,
    ALIGN_MIN_CLUSTER_CAPTIONED,
    ALIGN_PATH_MARGIN,
    ALIGN_PATH_MIN,
    ALIGN_RAW_BLOCK,
    ALIGN_RAW_NCC_MIN,
    SCAN_FPS,
    SIGNATURE_SIZE,
)


@dataclass
class AlignmentResult:
    clip: str
    status: str                     # RECOVERED / WEAK / FAILED
    offset_s: float | None = None   # clip t=0 inside the raw session
    clip_duration_s: float = 0.0
    window: tuple[float, float] | None = None  # (start, end) in session time
    votes: list = field(default_factory=list)
    ncc_best: float = 0.0           # path score of the accepted cluster
    ncc_margin: float = 0.0         # path margin over runner-up cluster
    refine_ncc: float = 0.0         # raw block NCC at the consensus offset


def _ffmpeg_thumbs(video: Path, fps: float, size: tuple[int, int],
                   ss: float | None = None, t: float | None = None) -> np.ndarray:
    w, h = size
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    if ss is not None:
        cmd += ["-ss", f"{ss:.3f}"]
    if t is not None:
        cmd += ["-t", f"{t:.3f}"]
    cmd += [
        "-i", str(video),
        "-vf", f"fps={fps},scale={w}:{h},format=gray",
        "-an", "-f", "rawvideo", "-pix_fmt", "gray", "-",
    ]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    n = len(raw) // (w * h)
    return np.frombuffer(raw, dtype=np.uint8, count=n * w * h).reshape(n, h, w)


def _ncc(a: np.ndarray, b: np.ndarray) -> float:
    a = a.astype(np.float64).ravel()
    b = b.astype(np.float64).ravel()
    a -= a.mean()
    b -= b.mean()
    da = np.linalg.norm(a)
    db = np.linalg.norm(b)
    if da < 1e-9 or db < 1e-9:
        return 0.0
    return float((a * b).sum() / (da * db))


def _deriv(sigs: np.ndarray) -> np.ndarray:
    """Temporal-derivative signatures |sig[t+1] - sig[t]| as float32 (N-1,D)."""
    d = np.abs(np.diff(sigs.astype(np.float32), axis=0))
    return d.reshape(d.shape[0], -1)


def _normalize_rows(m: np.ndarray) -> np.ndarray:
    """Zero-mean, unit-norm rows; rows with ~no energy become zeros."""
    m = m.astype(np.float64)
    m = m - m.mean(axis=1, keepdims=True)
    n = np.linalg.norm(m, axis=1, keepdims=True)
    out = np.zeros_like(m)
    np.divide(m, n, out=out, where=n > 1e-9)
    return out


def session_signatures(frames: np.ndarray,
                       size: tuple[int, int] = SIGNATURE_SIZE) -> np.ndarray:
    """Downsample scan thumbnails (N,H,W) to alignment signatures (N,h,w)."""
    import cv2

    w, h = size
    out = np.empty((frames.shape[0], h, w), dtype=np.uint8)
    for i in range(frames.shape[0]):
        out[i] = cv2.resize(frames[i], (w, h), interpolation=cv2.INTER_AREA)
    return out


def _clusters(votes: list, tol_s: float, step: float) -> list[dict]:
    """Greedy offset clusters within tol_s; returns [{offset, votes}] sorted
    by size desc."""
    offs = np.array([v[1] for v in votes])
    cands = []
    for a in range(len(offs)):
        members = [b for b in range(len(offs)) if abs(offs[b] - offs[a]) <= tol_s]
        cands.append((len(members), float(np.median(offs[members])), members))
    cands.sort(key=lambda x: -x[0])
    seen: set[float] = set()
    out = []
    for size, off, members in cands:
        key = round(off / step)
        if key in seen:
            continue
        seen.add(key)
        out.append({"offset": off, "votes": [votes[b] for b in members]})
    return out


def align_clip(clip: Path, session_sigs: np.ndarray, session_fps: float = SCAN_FPS,
               captioned: bool = False) -> AlignmentResult:
    """Align one clip against precomputed session signature thumbnails (v2)."""
    step = 1.0 / session_fps
    sigs = _ffmpeg_thumbs(clip, session_fps, SIGNATURE_SIZE)
    dur = sigs.shape[0] * step
    if sigs.shape[0] < 3 or session_sigs.shape[0] < 3:
        return AlignmentResult(clip=clip.name, status="FAILED",
                               clip_duration_s=dur)

    dclip = _deriv(sigs)
    dsess = _deriv(session_sigs)
    Dn = _normalize_rows(dsess)
    cn = _normalize_rows(dclip)
    energy = np.linalg.norm(dclip, axis=1)
    e_max = float(energy.max())

    votes = []                       # (clip_t, offset, ncc, z, sess_idx)
    for k in range(dclip.shape[0]):
        v = cn[k]
        if not np.any(v):
            continue
        scores = Dn @ v
        best = int(np.argmax(scores))
        lo = max(0, best - ALIGN_DERIV_EXCLUDE_IDX)
        hi = min(scores.shape[0], best + ALIGN_DERIV_EXCLUDE_IDX + 1)
        bg = np.concatenate([scores[:lo], scores[hi:]])
        med = float(np.median(bg))
        mad = float(np.median(np.abs(bg - med)))
        z = (float(scores[best]) - med) / max(1.4826 * mad, 1e-9)
        if z >= ALIGN_DERIV_Z_MIN and float(scores[best]) >= ALIGN_DERIV_NCC_MIN:
            votes.append((float(k + 1) * step,
                          float((k + 1) * step - best * step),
                          float(scores[best]), z, best))

    if len(votes) < 2:
        return AlignmentResult(clip=clip.name, status="WEAK", votes=votes,
                               clip_duration_s=dur)

    clusters = _clusters(votes, ALIGN_CLUSTER_TOL_S, step)
    scored = []
    for c in clusters:
        if len(c["votes"]) < 2:
            continue
        o_idx = -int(round(c["offset"] / step))
        pv = []
        for k in range(dclip.shape[0]):
            if e_max > 0 and energy[k] < 0.2 * e_max:
                continue  # uninformative (static) frame
            j = o_idx + (k + 1)
            if 0 <= j < Dn.shape[0]:
                pv.append(float(cn[k] @ Dn[j]))
        if pv:
            c["path"] = float(np.mean(pv))
            scored.append(c)
    if not scored:
        return AlignmentResult(clip=clip.name, status="WEAK", votes=votes,
                               clip_duration_s=dur)
    scored.sort(key=lambda c: -c["path"])
    top = scored[0]
    runner = next((c for c in scored[1:] if c is not top and len(c["votes"]) >= 2), None)

    min_size = ALIGN_MIN_CLUSTER_CAPTIONED if captioned else ALIGN_MIN_CLUSTER
    path_margin = top["path"] - runner["path"] if runner else 1.0
    # votes store (clip_t - session_t); the emitted offset is the session
    # time of clip t=0, i.e. the negated vote offset.
    offset = -float(np.round(np.median([v[1] for v in top["votes"]]), 3))

    # raw-signature block floor at the consensus offset
    o_idx = int(round(offset / step))
    block = 9
    bvals = []
    for pi in (1, 5, 10, 15, 20):
        j0 = o_idx + pi - block // 2
        if j0 < 0 or j0 + block > session_sigs.shape[0]:
            continue
        if pi - block // 2 < 0 or pi + block // 2 >= sigs.shape[0]:
            continue
        a = sigs[pi - block // 2: pi + block // 2 + 1].astype(np.float64).ravel()
        b = session_sigs[j0: j0 + block].astype(np.float64).ravel()
        bvals.append(_ncc(a, b))
    raw_block = float(np.mean(bvals)) if bvals else 0.0

    accepted = (
        len(top["votes"]) >= min_size
        and top["path"] >= ALIGN_PATH_MIN
        and path_margin >= ALIGN_PATH_MARGIN
        and raw_block >= ALIGN_RAW_NCC_MIN
    )
    status = "RECOVERED" if accepted else "WEAK"
    return AlignmentResult(
        clip=clip.name, status=status,
        offset_s=offset if accepted else None,
        clip_duration_s=dur,
        window=(offset, offset + dur) if accepted else None,
        votes=votes, ncc_best=top["path"],
        ncc_margin=path_margin, refine_ncc=raw_block,
    )
