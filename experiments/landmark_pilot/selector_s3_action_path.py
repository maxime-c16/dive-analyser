#!/usr/bin/env python3
"""S3_ACTION_GLOBAL_PATH — action-likelihood DP/Viterbi selector over D3 proposals.

Extends S1_GLOBAL_PATH with two key additions:

1. SPATIAL-PERSISTENCE MOTION AUXILIARY (Phase E2):
   For each candidate at each frame, compute a "persistence score" = how often a
   similar candidate appears at the same spatial location across the whole video.
   A persistently-present candidate (same location in most frames) is likely a static
   background object (pool tile marker, spectator, static structure). A candidate that
   appears only transiently is more likely the moving diver during flight.
   Score: motion_bonus = -W_PERSIST * max(0.0, persist_freq - PERSIST_NEUTRAL)
   where persist_freq is fraction of frames with a candidate within PERSIST_RADIUS of
   this candidate. Candidates present in most frames get a large negative bonus.
   This does NOT require video frames — computed from the raw candidate sequences only.

2. SCALE PLAUSIBILITY OBSERVATION TERM (Phase E):
   Diver bbox area (bw_norm*bh_norm) should be within a plausible range for a human
   diver in a pool video. Very tiny or very large boxes are unlikely to be the diver.
   This is a mild, bounded term.

Both additions maintain the core S1 invariants:
  - Static preparation prefix is NOT penalized (rolling window check is post-hoc)
  - NULL is a first-class state throughout
  - No human temporal landmarks used
  - No assumption about when action starts

SEQUENCE-LEVEL REJECTION (unchanged from S1):
  Post-hoc: if the winning path shows no coherent vertical motion ANYWHERE in the
  sequence (not just at the start), flag INVALID_STATIC_TRACK and emit all-NULL.
  A long static prep followed by real dive motion is explicitly NOT rejected.

MOTION AUXILIARY DESIGN NOTE (Phase E2):
  The spatial-persistence score addresses the specific Paris failure mode: a
  static background object that consistently produces conf=0.30-0.42 detections
  every frame dominates the Viterbi via observation score alone. By penalizing
  high-persistence candidates, the selector can prefer the true diver (which only
  appears during the flight window) over the persistent false positive.
"""
import json, sys, math, os

# === Core Viterbi parameters (same as S1) ===
W_DISP = 40.0
DISP_CAP = 0.04
W_SCALE = 8.0
SCALE_CAP = 1.0
C_REACQUIRE = 3.0
C_NULL_HOLD = 0.3
LOG_NULL_OBS = -3.5  # ~log(0.03); NULL competes with a very-low-conf candidate

# === S3 additions ===

# Motion/persistence auxiliary
PERSIST_RADIUS = 0.06       # normalized distance to consider "same location"
PERSIST_WINDOW = None       # None = use full sequence; or int for frame window
PERSIST_NEUTRAL = 0.25      # fraction of frames below which no penalty (diver in flight
                            # ~1-2s out of 5-10s clip = 10-40%; typical static FP = 80-100%)
W_PERSIST = 4.0             # weight of persistence penalty in observation score
                            # chosen so a 100%-present static object gets penalty
                            # = W_PERSIST * (1.0 - PERSIST_NEUTRAL) = 4.0 * 0.75 = -3.0,
                            # enough to overcome a 0.35-conf FP's log-conf advantage (~1.05)
                            # over a 0.06-conf diver (~2.81) across consecutive frames.

# Confidence weight (reduced from S1's implicit weight of 1.0 to make room for motion term)
W_CONF = 0.5                # downweight conf so motion cue has comparable influence
                            # (S1 used weight=1.0 implicitly)

# Scale plausibility
BBOX_AREA_MIN = 0.0005      # bbox_area = bw*bh; below this = too tiny
BBOX_AREA_MAX = 0.25        # above this = too large (nearly whole frame)
W_SCALE_PLAUS = 0.5         # mild bonus within plausible range

# Sequence-level static rejection (identical to S1)
STATIC_WINDOW_S = 1.5
STATIC_RANGE_MIN = 0.03


def precompute_persistence(frames):
    """For each frame/candidate, compute fraction of all frames that have a candidate
    within PERSIST_RADIUS of this candidate's (cx_norm, cy_norm).
    Returns a list of lists: persist[t][k] = float in [0,1] for candidate k at frame t.
    NULL (k=-1 / None) not included.
    """
    T = len(frames)
    # Build spatial index: per frame, list of (cx,cy) for each candidate
    positions = []
    for fr in frames:
        positions.append([(c["cx_norm"], c["cy_norm"]) for c in fr["all_candidates"]])

    # For each candidate at each frame, count overlapping candidates across all frames
    persist = []
    for t, fr in enumerate(frames):
        row = []
        cands = fr["all_candidates"]
        for c in cands:
            cx, cy = c["cx_norm"], c["cy_norm"]
            count = 0
            for t2 in range(T):
                found = False
                for (ox, oy) in positions[t2]:
                    if (ox-cx)**2 + (oy-cy)**2 <= PERSIST_RADIUS**2:
                        found = True
                        break
                if found:
                    count += 1
            row.append(count / T)
        persist.append(row)
    return persist


def obs_s3(cand, persist_freq):
    """Observation score for a candidate under S3."""
    if cand is None:
        return LOG_NULL_OBS
    log_conf = W_CONF * math.log(max(cand["conf"], 1e-6))
    # Persistence penalty: subtracts W_PERSIST * (persist_freq - PERSIST_NEUTRAL)
    # for static objects; no penalty for transient candidates
    persist_penalty = -W_PERSIST * max(0.0, persist_freq - PERSIST_NEUTRAL)
    # Scale plausibility bonus
    area = cand["bw_norm"] * cand["bh_norm"]
    scale_bonus = W_SCALE_PLAUS if BBOX_AREA_MIN <= area <= BBOX_AREA_MAX else 0.0
    return log_conf + persist_penalty + scale_bonus


def transition_cost(prev, cur):
    """Same transition cost as S1."""
    dx = cur["cx_norm"] - prev["cx_norm"]
    dy = cur["cy_norm"] - prev["cy_norm"]
    disp2 = dx*dx + dy*dy
    cost = W_DISP * min(disp2, DISP_CAP)
    h_prev = max(prev["bh_norm"], 1e-4)
    h_cur = max(cur["bh_norm"], 1e-4)
    dlog_h = math.log(h_cur / h_prev)
    cost += W_SCALE * min(dlog_h*dlog_h, SCALE_CAP)
    return cost


def viterbi_s3(frames, persist):
    """Viterbi over {candidates_t} ∪ {NULL} with S3 observation scores."""
    T = len(frames)
    states = [fr["all_candidates"] + [None] for fr in frames]  # None = NULL

    dp = [None]*T; bp = [None]*T
    # Init
    dp[0] = []
    for k, st in enumerate(states[0]):
        if st is None:
            obs = LOG_NULL_OBS
        else:
            obs = obs_s3(st, persist[0][k] if k < len(persist[0]) else 0.0)
        dp[0].append(obs)
    bp[0] = [-1]*len(states[0])

    for t in range(1, T):
        st_prev = states[t-1]; st_cur = states[t]
        persist_cur = persist[t]
        dp[t] = []; bp[t] = []
        for j, cur in enumerate(st_cur):
            if cur is None:
                obs = LOG_NULL_OBS
            else:
                obs = obs_s3(cur, persist_cur[j] if j < len(persist_cur) else 0.0)
            best_score, best_i = -1e18, 0
            for i, prev in enumerate(st_prev):
                if prev is None and cur is None:
                    tc = -C_NULL_HOLD
                elif prev is None or cur is None:
                    tc = -C_REACQUIRE
                else:
                    tc = -transition_cost(prev, cur)
                score = dp[t-1][i] + tc
                if score > best_score:
                    best_score, best_i = score, i
            dp[t].append(best_score + obs)
            bp[t].append(best_i)

    # Backtrace
    last_idx = max(range(len(dp[T-1])), key=lambda k: dp[T-1][k])
    path_idx = [0]*T; path_idx[T-1] = last_idx
    for t in range(T-1, 0, -1):
        path_idx[t-1] = bp[t][path_idx[t]]
    path = [states[t][path_idx[t]] for t in range(T)]
    return path


def rolling_max_range(cy_series, pts_series, window_s):
    """Max cy_norm range within any sliding time-window (identical to S1)."""
    n = len(cy_series); best = 0.0; lo = 0
    for hi in range(n):
        if cy_series[hi] is None:
            continue
        while pts_series[hi] - pts_series[lo] > window_s:
            lo += 1
        vals = [cy_series[k] for k in range(lo, hi+1) if cy_series[k] is not None]
        if len(vals) >= 2:
            best = max(best, max(vals)-min(vals))
    return best


def select_s3(raw):
    frames = raw["frames"]
    print(f"  Precomputing persistence for {len(frames)} frames...", end="", flush=True)
    persist = precompute_persistence(frames)
    print(f" done. Running Viterbi...", end="", flush=True)
    path = viterbi_s3(frames, persist)
    print(" done.")
    cy = [p["cy_norm"] if p is not None else None for p in path]
    pts = [fr["pts_s"] if fr["pts_s"] is not None else i for i, fr in enumerate(frames)]
    max_range = rolling_max_range(cy, pts, STATIC_WINDOW_S)
    flagged_static = max_range < STATIC_RANGE_MIN
    if flagged_static:
        path = [None]*len(path)
    diag = {
        "max_rolling_cy_range": max_range,
        "flagged_invalid_static_track": flagged_static,
        "persist_w": W_PERSIST,
        "persist_neutral": PERSIST_NEUTRAL,
        "persist_radius": PERSIST_RADIUS,
        "w_conf": W_CONF,
    }
    return path, diag


def run(raw_path, out_path):
    raw = json.load(open(raw_path))
    print(f"Processing {raw_path} ({raw['n_frames']} frames)...")
    path, diag = select_s3(raw)
    out = {
        "selector": "S3_ACTION_GLOBAL_PATH",
        "video": raw["video"],
        "n_frames": raw["n_frames"],
        "width": raw.get("width"), "height": raw.get("height"),
        "diagnostics": diag,
        "points": [
            {"frame_index": fr["frame_index"], "pts_s": fr["pts_s"], "selected": t}
            for fr, t in zip(raw["frames"], path)
        ],
    }
    json.dump(out, open(out_path, "w"))
    n_null = sum(1 for t in path if t is None)
    print(f"  {out_path}: {len(path)} frames, {n_null} NULL ({n_null/max(1,len(path)):.1%}), diag={diag}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: selector_s3_action_path.py <raw.json> <out.json>")
        sys.exit(1)
    os.chdir(os.path.expanduser("~/dive-analyser"))
    run(sys.argv[1], sys.argv[2])
