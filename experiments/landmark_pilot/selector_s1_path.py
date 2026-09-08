#!/usr/bin/env python3
"""S1_GLOBAL_PATH — deterministic Viterbi-style sequence selector over frozen D3.1
raw per-frame candidates, plus an explicit NULL state.

States per frame t: every raw candidate at t, plus NULL.

Observation score (per state):
  candidate: log(conf)               -- prefers confident detections
  NULL:      LOG_NULL_OBS            -- fixed small negative constant (mild penalty,
             so NULL is only chosen over a low-conf candidate when continuity/scale
             evidence does not support that candidate either)

Transition score (state at t-1 -> state at t):
  candidate_i -> candidate_j : -W_DISP * min(disp**2, DISP_CAP)
                                -W_SCALE * min(dlog_h**2, SCALE_CAP)
    where disp = center displacement (normalized), dlog_h = log(h_j/h_i) (bbox-scale
    continuity). Bounded motion is expected between adjacent frames; large jumps are
    discouraged but never impossible (capped, not a hard gate) so a real fast take-off
    frame is never structurally excluded.
  candidate -> NULL / NULL -> candidate: -C_REACQUIRE (fixed small cost: track loss and
    track re-acquisition both cost something, but neither is free or forbidden)
  NULL -> NULL: -C_NULL_HOLD (very small; long true gaps, e.g. splash occlusion at
    water contact, must be affordable)

No human temporal landmarks are used as inputs anywhere in this scoring. No
assumption about when action starts: transition scores only ever look at adjacent
frames' geometry, never absolute time.

Sequence-level rejection (post-hoc, applied to the winning path AFTER Viterbi decoding,
never as a per-step penalty): a path is flagged INVALID_STATIC_TRACK only if it shows
no meaningful vertical range ANYWHERE across the whole selected sequence (i.e. also
static during whatever portion would have been the dive itself). A long static
PREPARATION prefix followed by real coherent motion must NOT be rejected — the
per-window rolling-range check below specifically looks for at least one window of
sustained variation anywhere in the sequence, not for variation from frame 0.
"""
import json, sys, math

W_DISP = 40.0
DISP_CAP = 0.04       # beyond this squared-distance, transition cost saturates
W_SCALE = 8.0
SCALE_CAP = 1.0
C_REACQUIRE = 3.0
C_NULL_HOLD = 0.3
LOG_NULL_OBS = -3.5   # roughly log(0.03): NULL competes with a very-low-conf candidate

# Sequence-level static-track rejection (post-hoc)
STATIC_WINDOW_S = 1.5     # rolling window length used to look for coherent motion
STATIC_RANGE_MIN = 0.03   # min cy_norm range within some window to call it "moving"


def transition_cost(prev, cur):
    dx = cur["cx_norm"] - prev["cx_norm"]
    dy = cur["cy_norm"] - prev["cy_norm"]
    disp2 = dx * dx + dy * dy
    cost = W_DISP * min(disp2, DISP_CAP)
    h_prev = max(prev["bh_norm"], 1e-4)
    h_cur = max(cur["bh_norm"], 1e-4)
    dlog_h = math.log(h_cur / h_prev)
    cost += W_SCALE * min(dlog_h * dlog_h, SCALE_CAP)
    return cost


def viterbi(frames):
    """Returns list of chosen state per frame: either a candidate dict or None (NULL)."""
    T = len(frames)
    # dp[t] = list of (score, backpointer_index) aligned with states_t = candidates + [NULL]
    states = []  # states[t] = list of candidate dicts, NULL represented as None appended
    for fr in frames:
        states.append(fr["all_candidates"] + [None])

    dp = [None] * T
    bp = [None] * T
    # init
    s0 = states[0]
    dp[0] = []
    for st in s0:
        obs = math.log(max(st["conf"], 1e-6)) if st is not None else LOG_NULL_OBS
        dp[0].append(obs)
    bp[0] = [-1] * len(s0)

    for t in range(1, T):
        st_prev = states[t - 1]
        st_cur = states[t]
        dp[t] = []
        bp[t] = []
        for j, cur in enumerate(st_cur):
            obs = math.log(max(cur["conf"], 1e-6)) if cur is not None else LOG_NULL_OBS
            best_score, best_i = -1e18, 0
            for i, prev in enumerate(st_prev):
                if prev is None and cur is None:
                    tcost = -C_NULL_HOLD
                elif prev is None or cur is None:
                    tcost = -C_REACQUIRE
                else:
                    tcost = -transition_cost(prev, cur)
                score = dp[t - 1][i] + tcost
                if score > best_score:
                    best_score, best_i = score, i
            dp[t].append(best_score + obs)
            bp[t].append(best_i)

    # backtrace
    last_idx = max(range(len(dp[T - 1])), key=lambda k: dp[T - 1][k])
    path_idx = [0] * T
    path_idx[T - 1] = last_idx
    for t in range(T - 1, 0, -1):
        path_idx[t - 1] = bp[t][path_idx[t]]

    path = [states[t][path_idx[t]] for t in range(T)]
    return path


def rolling_max_range(cy_series, pts_series, window_s):
    """Max cy_norm range within any sliding time-window; None entries (NULL/gap) skipped."""
    n = len(cy_series)
    best = 0.0
    lo = 0
    for hi in range(n):
        if cy_series[hi] is None:
            continue
        while pts_series[hi] - pts_series[lo] > window_s:
            lo += 1
        window_vals = [cy_series[k] for k in range(lo, hi + 1) if cy_series[k] is not None]
        if len(window_vals) >= 2:
            rng = max(window_vals) - min(window_vals)
            best = max(best, rng)
    return best


def select_s1(raw):
    frames = raw["frames"]
    path = viterbi(frames)
    cy = [p["cy_norm"] if p is not None else None for p in path]
    pts = [fr["pts_s"] if fr["pts_s"] is not None else i for i, fr in enumerate(frames)]
    max_range = rolling_max_range(cy, pts, STATIC_WINDOW_S)
    flagged_static = max_range < STATIC_RANGE_MIN
    if flagged_static:
        # Enforce the rejection: a path with no meaningful vertical range ANYWHERE in
        # the whole sequence (not merely a static preparation prefix) is not a valid
        # target-diver trajectory -- output NULL throughout rather than a false lock.
        path = [None] * len(path)
    return path, {"max_rolling_cy_range": max_range, "flagged_invalid_static_track": flagged_static}


def run(raw_path, out_path):
    raw = json.load(open(raw_path))
    path, diag = select_s1(raw)
    out = {
        "selector": "S1_GLOBAL_PATH",
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
    print(f"{raw_path}: {len(path)} frames, {n_null} NULL, diag={diag}")


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2])
