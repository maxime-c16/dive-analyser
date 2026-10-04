#!/usr/bin/env python3
"""S2_TRACK_QUALITY — lightweight ByteTrack-style track formation over the SAME
frozen D3.1 raw per-frame candidates, followed by a track-quality scoring pass that
picks ONE track for the whole clip (NULL elsewhere).

Track formation (ByteTrack-style two-stage IoU association via `lap` Hungarian
assignment — no ReID, no new tracker family, detector inference itself is untouched):
  1. High-confidence detections (conf >= CONF_HIGH) matched to existing tracks by IoU
     (Hungarian assignment via lap.lapjv on a 1-IoU cost matrix).
  2. Remaining unmatched tracks are given a second chance against low-confidence
     detections (conf < CONF_HIGH) — this is ByteTrack's defining idea: don't discard
     low-conf boxes outright, use them to keep a good track alive through a dip.
  3. Any high-confidence detection still unmatched spawns a new track.
  4. A track not matched for more than MAX_AGE frames is retired (kept as a completed
     track, no longer eligible to receive new detections).

Track-quality scoring (features asked for by the packet):
  - duration_frames, coverage = duration / n_video_frames
  - vertical displacement = max(cy) - min(cy) over the track's own detections
  - confidence distribution (mean conf)
  - fraction_of_track_static: fraction of the track's OWN lifetime with near-zero
    rolling vertical range (same STATIC_WINDOW/STATIC_RANGE_MIN idea as S1, applied to
    the track in isolation) -- again, a track that is static ONLY during an early
    preparation segment but shows real motion later is not penalized by this feature,
    because the rolling-range check finds the later window.
  - motion_arc_score: bonus if the track's cy trace has both a rise and fall segment
    (up-then-down, characteristic of a dive's flight arc) rather than monotonic drift.

score = 3.0*coverage + 20.0*vertical_range + 2.0*motion_arc_score
        - 15.0*fraction_of_track_static - 3.0*(1 - mean_conf_norm)
The winning track (max score) becomes the S2 trajectory; frames outside its lifetime
are NULL.
"""
import json, sys, math
import numpy as np
import lap

CONF_HIGH = 0.15
IOU_MATCH_THRESH = 0.20     # below this IoU, treat as no-match regardless of Hungarian cost
MAX_AGE = 10                 # frames a track may go unmatched before retirement
STATIC_WINDOW_S = 1.5
STATIC_RANGE_MIN = 0.03


def iou_xyxy(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    aarea = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    barea = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = aarea + barea - inter
    return inter / union if union > 0 else 0.0


class Track:
    __slots__ = ("id", "hist", "last_frame", "active")

    def __init__(self, tid, frame_idx, pts_s, cand):
        self.id = tid
        self.hist = [(frame_idx, pts_s, cand)]
        self.last_frame = frame_idx
        self.active = True

    def last_bbox(self):
        return self.hist[-1][2]["xyxy"]


def hungarian_match(tracks, dets, iou_thresh):
    """Match tracks to dets by IoU using lap.lapjv on a 1-IoU cost matrix.
    Returns (matches[(track_idx, det_idx)], unmatched_track_idx, unmatched_det_idx)."""
    if not tracks or not dets:
        return [], list(range(len(tracks))), list(range(len(dets)))
    cost = np.ones((len(tracks), len(dets)), dtype=np.float64)
    for i, tr in enumerate(tracks):
        tb = tr.last_bbox()
        for j, d in enumerate(dets):
            iou = iou_xyxy(tb, d["xyxy"])
            cost[i, j] = 1.0 - iou if iou >= iou_thresh else 1.0 + (1.0 - iou)  # discourage below-thresh
    cost_, x, y = lap.lapjv(cost, extend_cost=True)
    matches, um_t, um_d = [], [], []
    for i in range(len(tracks)):
        j = x[i]
        if j >= 0 and iou_xyxy(tracks[i].last_bbox(), dets[j]["xyxy"]) >= iou_thresh:
            matches.append((i, j))
        else:
            um_t.append(i)
    matched_d = {j for _, j in matches}
    um_d = [j for j in range(len(dets)) if j not in matched_d]
    return matches, um_t, um_d


def form_tracks(frames):
    active = []
    completed = []
    next_id = 0
    for fr in frames:
        cands = fr["all_candidates"]
        high = [c for c in cands if c["conf"] >= CONF_HIGH]
        low = [c for c in cands if c["conf"] < CONF_HIGH]

        # stage 1: active tracks vs high-conf dets
        m1, um_t1, um_d1 = hungarian_match(active, high, IOU_MATCH_THRESH)
        matched_track_idx = set()
        for ti, di in m1:
            active[ti].hist.append((fr["frame_index"], fr["pts_s"], high[di]))
            active[ti].last_frame = fr["frame_index"]
            matched_track_idx.add(ti)

        # stage 2: still-unmatched tracks vs low-conf dets (ByteTrack 2nd stage)
        still_unmatched_tracks = [active[i] for i in um_t1]
        m2, um_t2, um_d2 = hungarian_match(still_unmatched_tracks, low, IOU_MATCH_THRESH)
        for ti, di in m2:
            tr = still_unmatched_tracks[ti]
            tr.hist.append((fr["frame_index"], fr["pts_s"], low[di]))
            tr.last_frame = fr["frame_index"]
            matched_track_idx.add(active.index(tr))

        # retire stale tracks
        still_active = []
        for i, tr in enumerate(active):
            if i in matched_track_idx:
                still_active.append(tr)
            elif fr["frame_index"] - tr.last_frame <= MAX_AGE:
                still_active.append(tr)
            else:
                completed.append(tr)
        active = still_active

        # new tracks from unmatched high-conf dets
        for di in um_d1:
            active.append(Track(next_id, fr["frame_index"], fr["pts_s"], high[di]))
            next_id += 1

    completed.extend(active)
    return completed


def rolling_max_range(points):
    """points: list of (pts_s, cy_norm) for one track, in order."""
    n = len(points)
    best = 0.0
    lo = 0
    for hi in range(n):
        while points[hi][0] - points[lo][0] > STATIC_WINDOW_S:
            lo += 1
        vals = [points[k][1] for k in range(lo, hi + 1)]
        if len(vals) >= 2:
            best = max(best, max(vals) - min(vals))
    return best


def motion_arc_score(cy_series):
    if len(cy_series) < 3:
        return 0.0
    d = np.diff(cy_series)
    sign_changes = np.sum(np.diff(np.sign(d)) != 0)
    return min(sign_changes / 3.0, 1.0)


def score_track(track, n_video_frames):
    hist = track.hist
    duration = hist[-1][0] - hist[0][0] + 1
    coverage = duration / max(1, n_video_frames)
    cy_series = [h[2]["cy_norm"] for h in hist]
    pts_points = [(h[1] if h[1] is not None else h[0], h[2]["cy_norm"]) for h in hist]
    vrange = max(cy_series) - min(cy_series) if len(cy_series) > 1 else 0.0
    max_roll_range = rolling_max_range(pts_points)
    fraction_static = 1.0 if max_roll_range < STATIC_RANGE_MIN else 0.0
    mean_conf = float(np.mean([h[2]["conf"] for h in hist]))
    arc = motion_arc_score(cy_series)
    score = (3.0 * coverage + 20.0 * max_roll_range + 2.0 * arc
             - 15.0 * fraction_static - 3.0 * (1.0 - min(mean_conf, 1.0)))
    return {
        "score": score, "duration_frames": duration, "coverage": coverage,
        "vertical_range": vrange, "max_rolling_range": max_roll_range,
        "fraction_static": fraction_static, "mean_conf": mean_conf,
        "motion_arc_score": arc, "n_hits": len(hist),
    }


def select_s2(raw):
    frames = raw["frames"]
    tracks = form_tracks(frames)
    scored = [(t, score_track(t, raw["n_frames"])) for t in tracks]
    scored.sort(key=lambda ts: -ts[1]["score"])
    best_track, best_metrics = scored[0] if scored else (None, None)

    by_frame = {}
    if best_track is not None:
        for fidx, pts_s, cand in best_track.hist:
            by_frame[fidx] = cand
    path = [by_frame.get(fr["frame_index"]) for fr in frames]

    diag = {
        "n_tracks_formed": len(tracks),
        "winning_track_id": best_track.id if best_track else None,
        "winning_track_metrics": best_metrics,
        "all_track_scores": [{"id": t.id, **m} for t, m in scored],
    }
    return path, diag


def run(raw_path, out_path):
    raw = json.load(open(raw_path))
    path, diag = select_s2(raw)
    out = {
        "selector": "S2_TRACK_QUALITY",
        "video": raw["video"],
        "n_frames": raw["n_frames"],
        "diagnostics": diag,
        "points": [
            {"frame_index": fr["frame_index"], "pts_s": fr["pts_s"], "selected": t}
            for fr, t in zip(raw["frames"], path)
        ],
    }
    json.dump(out, open(out_path, "w"))
    n_null = sum(1 for t in path if t is None)
    print(f"{raw_path}: {len(path)} frames, {n_null} NULL, tracks={diag['n_tracks_formed']}, "
          f"winner={diag['winning_track_id']}")


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2])
