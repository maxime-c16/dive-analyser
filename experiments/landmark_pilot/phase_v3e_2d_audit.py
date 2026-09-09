#!/usr/bin/env python3
"""T4 — Phase D+E: 2D trajectory audit + approach-progress coordinate (GT-blind).

For each HURDLE dive (raw + light median filter over <= 0.3 s, NO Gaussian):
  - cx(t), cy(t), bbox-bottom by(t) stats
  - vx, vy, 2D speed (pts-aware central differences on the filtered signal)
  - direction changes (vx sign flips with hysteresis), curvature summary
  - robust approach-progress coordinate s(t):
      * bounds WITHOUT GT: start = end of initial static plateau (frozen
        _find_preparation_end semantics); end = last frame before the largest
        sustained |v| event of the whole clip (speed > SPEED_THR sustained >=
        SPEED_MIN_S), capped at 80% of the clip.
      * robust principal axis on [cx, cy] via iterative PCA with
        MAD-based perpendicular-residual rejection (RANSAC-like), 3 iters.
      * s(t) = projection onto the axis (oriented so s increases with time).
  - terminal-region detection (progression slowdown/reversal near the board),
    reported with signal-derived relative timing only.
  - Phase F classification: APPROACH_END_OBSERVABLE_FROM_2D_TRAJECTORY /
    APPROACH_END_NOT_RELIABLY_OBSERVABLE_FROM_2D_TRAJECTORY / MIXED_2D_OBSERVABILITY.

No GT event times are used anywhere.

Output: docs/science/TWOD_APPROACH_AUDIT_V1.json

Usage: .venv/bin/python experiments/landmark_pilot/phase_v3e_2d_audit.py
"""

import sys, json, hashlib, datetime
import numpy as np
from pathlib import Path

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))

from proposer_event_logic_v2_1 import _find_preparation_end, pts_aware_smooth, interpolate_gaps_time
from proposer_event_logic_v3_d0 import PARAMS_V3D0
import build_hurdle_traj_cache_v2 as T1

OUT_PATH = BASE / "docs/science/TWOD_APPROACH_AUDIT_V1.json"

MEDFILT_HALF_S   = 0.15   # median filter half-window (total <= 0.3 s)
VX_HYST          = 0.05   # vx hysteresis (norm units / s)
SPEED_THR        = 0.10   # sustained |v| event threshold (norm/s)
SPEED_MIN_S      = 0.30   # sustained |v| min duration (s)
END_CAP_FRAC     = 0.80   # approach end cap (fraction of clip)
PCA_ITERS        = 3
PROG_EPS         = 1e-4   # s-progress epsilon (norm units)
SLOWDOWN_FRAC    = 0.40   # terminal slowdown: window mean speed < 40% of approach mean
SLOWDOWN_WIN_S   = 0.40
LOOKBACK_S       = 2.0    # terminal-region search lookback before approach end
CLASS_THR        = {"inlier_observable": 0.75, "progression_observable": 0.75,
                    "inlier_unreliable": 0.50, "progression_unreliable": 0.50}
MIN_WINDOW_S     = 1.0    # approach window shorter than this cannot support a coordinate
SUSPICIOUS_FRAC  = 0.60   # window > 60% of clip => largest-event selection suspect


def median_filter_time(series, pts, half_s):
    out = []
    n = len(series)
    for i in range(n):
        vals = [series[j] for j in range(n)
                if abs(pts[j] - pts[i]) <= half_s and series[j] is not None]
        out.append(float(np.median(vals)) if vals else None)
    return out


def central_vel(series, pts, max_gap_s=0.20):
    n = len(series)
    vel = [None] * n
    for i in range(1, n - 1):
        a, b = series[i - 1], series[i + 1]
        if a is None or b is None:
            continue
        dt = pts[i + 1] - pts[i - 1]
        if dt <= 0 or dt > max_gap_s * 2:
            continue
        vel[i] = (b - a) / dt
    return vel


def direction_changes(vx, hyst):
    """Sign flips of vx with hysteresis; returns (count, events, state timeline len)."""
    state = 0  # -1 left, 0 undecided, +1 right
    flips = []
    for i, v in enumerate(vx):
        if v is None:
            continue
        if v > hyst and state != 1:
            if state == -1:
                flips.append(i)
            state = 1
        elif v < -hyst and state != -1:
            if state == 1:
                flips.append(i)
            state = -1
    return flips


def robust_pca_axis(points):
    """Iterative PCA with MAD residual rejection. Returns (axis, mean, inlier_frac, n_iter_used)."""
    P = np.asarray(points, dtype=float)
    idx = np.ones(len(P), dtype=bool)
    axis = mean = None
    for _ in range(PCA_ITERS):
        Q = P[idx]
        mean = Q.mean(axis=0)
        C = np.cov((Q - mean).T)
        w, V = np.linalg.eigh(C)
        axis = V[:, np.argmax(w)]
        d = (P - mean) @ axis
        perp = np.linalg.norm((P - mean) - np.outer(d, axis), axis=1)
        med = np.median(perp[idx])
        mad = np.median(np.abs(perp[idx] - med))
        tol = max(3 * 1.4826 * mad, 0.01)
        new_idx = perp <= tol
        if new_idx.sum() < 10:
            break
        if (new_idx == idx).all():
            idx = new_idx
            break
        idx = new_idx
    return axis, mean, float(idx.mean()), idx, perp, tol


def main():
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cache = T1.load_json(T1.CACHE_PATH)
    params = PARAMS_V3D0
    sigma = params["smooth_window_s"] / 3
    per_dive = {}

    for spec in T1.DIVES:
        did = spec["id"]
        frames = cache["per_dive"][did]["frames"]
        y_arr, pts_arr, conf_arr = T1.traj_arrays(frames)
        cx_arr = [f["cx"] for f in frames]
        by_arr = [f["by_bottom"] for f in frames]
        n = len(frames)

        cx_f = median_filter_time(cx_arr, pts_arr, MEDFILT_HALF_S)
        cy_f = median_filter_time(y_arr, pts_arr, MEDFILT_HALF_S)
        by_f = median_filter_time(by_arr, pts_arr, MEDFILT_HALF_S)

        vx = central_vel(cx_f, pts_arr)
        vy = central_vel(cy_f, pts_arr)
        speed = [None if (a is None or b is None) else float(np.hypot(a, b))
                 for a, b in zip(vx, vy)]

        vx_valid = [v for v in vx if v is not None]
        flips = direction_changes(vx, VX_HYST)
        turning = []
        for i in range(1, n):
            if vx[i] is not None and vx[i - 1] is not None:
                turning.append(abs(vx[i] - vx[i - 1]) / max(pts_arr[i] - pts_arr[i - 1], 1e-6))

        def stats(arr):
            v = [x for x in arr if x is not None]
            if not v:
                return None
            return {"mean": round(float(np.mean(v)), 5),
                    "std": round(float(np.std(v)), 5),
                    "min": round(float(np.min(v)), 5),
                    "max": round(float(np.max(v)), 5)}

        # ── approach bounds (GT-blind) ───────────────────────────────────────
        y_smooth = interpolate_gaps_time(pts_aware_smooth(y_arr, pts_arr, sigma),
                                         pts_arr, params["interp_max_gap_s"])
        prep_end_i = _find_preparation_end(y_smooth, pts_arr, params)
        start_i = prep_end_i if prep_end_i is not None else 0

        # largest sustained |v| event of the whole clip — computed on the
        # median-filtered speed (0.3 s) so detector level-switch flicker
        # (brief, very fast) does not masquerade as the dominant motion event.
        speed_f = median_filter_time(speed, pts_arr, MEDFILT_HALF_S)
        events = []
        i = 0
        while i < n:
            if speed_f[i] is not None and speed_f[i] > SPEED_THR:
                j = i
                while j < n and speed_f[j] is not None and speed_f[j] > SPEED_THR:
                    j += 1
                dur = pts_arr[j - 1] - pts_arr[i]
                if dur >= SPEED_MIN_S:
                    integral = sum(s for s in speed_f[i:j] if s is not None)
                    events.append((i, j, dur, integral))
                i = j
            else:
                i += 1
        if events:
            big = max(events, key=lambda e: e[3])
            end_i = min(big[0] - 1, int(END_CAP_FRAC * n) - 1)
            largest_event = {"t_start": pts_arr[big[0]], "t_end": pts_arr[big[1] - 1],
                             "dur_s": round(big[2], 3), "integral": round(big[3], 4)}
        else:
            end_i = int(END_CAP_FRAC * n) - 1
            largest_event = None
        end_i = max(end_i, start_i + 2)

        # ── robust principal axis over the approach ──────────────────────────
        pts2d = [(cx_f[i], cy_f[i]) for i in range(start_i, end_i + 1)
                 if cx_f[i] is not None and cy_f[i] is not None]
        if len(pts2d) >= 10:
            axis, pmean, inlier_frac, inlier_mask, perp, tol = robust_pca_axis(pts2d)
            s_vals = []
            k = 0
            idx_map = [i for i in range(start_i, end_i + 1)
                       if cx_f[i] is not None and cy_f[i] is not None]
            for i in idx_map:
                p = np.array([cx_f[i], cy_f[i]])
                s_vals.append((i, float((p - pmean) @ axis)))
            # orient: s should increase with time on average
            ts = np.array([pts_arr[i] for i, _ in s_vals])
            ss = np.array([s for _, s in s_vals])
            if np.corrcoef(ts, ss)[0, 1] < 0:
                axis = -axis
                ss = -ss
                s_vals = [(i, -v) for i, v in s_vals]
            ds = np.diff(ss)
            dts = np.diff(ts)
            fwd = ds[(np.abs(ds) > PROG_EPS)]
            prog_frac = float((fwd > 0).mean()) if fwd.size else None
            # terminal region: slowdown / reversal in the last LOOKBACK_S
            seg_speed = np.abs(ds / dts)
            mean_speed = seg_speed.mean() if seg_speed.size else None
            end_t = pts_arr[end_i]
            slowdown_t = None
            reversal_t = None
            if mean_speed and mean_speed > 0:
                for a in range(len(s_vals) - 1):
                    if pts_arr[s_vals[a][0]] < end_t - LOOKBACK_S:
                        continue
                    w = [b for b in range(a, len(s_vals) - 1)
                         if pts_arr[s_vals[b][0]] <= pts_arr[s_vals[a][0]] + SLOWDOWN_WIN_S]
                    if w and all(pts_arr[s_vals[b][0]] <= end_t + 0.5 for b in w):
                        ms = seg_speed[w].mean()
                        if ms < SLOWDOWN_FRAC * mean_speed and slowdown_t is None:
                            slowdown_t = pts_arr[s_vals[a][0]]
                    if ds[a] < -PROG_EPS:
                        b2 = [b for b in range(a, len(ds))
                              if pts_arr[s_vals[b + 1][0]] <= pts_arr[s_vals[a + 1][0]] + 0.2]
                        if b2 and all(ds[b] < 0 for b in b2) and reversal_t is None:
                            reversal_t = pts_arr[s_vals[a][0]]
            terminal = {"slowdown_detected": slowdown_t is not None,
                        "slowdown_t": slowdown_t,
                        "slowdown_rel_to_approach_end": (round(end_t - slowdown_t, 3)
                                                         if slowdown_t is not None else None),
                        "reversal_detected": reversal_t is not None,
                        "reversal_t": reversal_t}
            terminal["detected"] = terminal["slowdown_detected"] or terminal["reversal_detected"]

            axis_angle = float(np.degrees(np.arctan2(axis[1], axis[0])))
            s_range = float(ss.max() - ss.min())
            win_s = pts_arr[end_i] - pts_arr[start_i]
            suspicious = win_s > SUSPICIOUS_FRAC * (pts_arr[-1] - pts_arr[0])
            if win_s < MIN_WINDOW_S:
                cls = "APPROACH_END_NOT_RELIABLY_OBSERVABLE_FROM_2D_TRAJECTORY"
            elif (inlier_frac >= CLASS_THR["inlier_observable"]
                    and prog_frac is not None and prog_frac >= CLASS_THR["progression_observable"]
                    and terminal["detected"] and not suspicious):
                cls = "APPROACH_END_OBSERVABLE_FROM_2D_TRAJECTORY"
            elif (inlier_frac < CLASS_THR["inlier_unreliable"]
                  or prog_frac is None or prog_frac < CLASS_THR["progression_unreliable"]):
                cls = "APPROACH_END_NOT_RELIABLY_OBSERVABLE_FROM_2D_TRAJECTORY"
            else:
                cls = "MIXED_2D_OBSERVABILITY"
            just = (f"inlier_frac={inlier_frac:.3f} (thr {CLASS_THR['inlier_observable']}/"
                    f"{CLASS_THR['inlier_unreliable']}), sustained_progression={prog_frac}, "
                    f"terminal_detected={terminal['detected']} "
                    f"(slowdown={terminal['slowdown_detected']}, reversal={terminal['reversal_detected']}), "
                    f"window_s={win_s:.2f}"
                    + (f" — window < {MIN_WINDOW_S}s, too short to support a coordinate"
                       if win_s < MIN_WINDOW_S else "")
                    + (" — LARGEST-EVENT SELECTION SUSPECT: window > "
                       f"{SUSPICIOUS_FRAC:.0%} of clip (post-water-contact flicker likely "
                       "dominated the sustained-|v| integral)" if suspicious else ""))
        else:
            axis_angle = None; s_range = None; prog_frac = None
            inlier_frac = None; terminal = {"detected": False, "note": "too few 2D samples"}
            cls = "APPROACH_END_NOT_RELIABLY_OBSERVABLE_FROM_2D_TRAJECTORY"
            just = f"only {len(pts2d)} valid 2D samples in approach window"

        per_dive[did] = {
            "code": spec["code"],
            "series_stats": {"cx": stats(cx_arr), "cy": stats(y_arr), "by": stats(by_arr),
                             "vx": stats(vx), "vy": stats(vy), "speed": stats(speed)},
            "direction_changes": {"count": len(flips),
                                  "flip_times": [pts_arr[i] for i in flips][:50],
                                  "hysteresis": VX_HYST,
                                  "mean_abs_vx_rate": round(float(np.mean(turning)), 4) if turning else None},
            "approach_bounds": {"start_i": start_i, "start_t": pts_arr[start_i],
                                "end_i": end_i, "end_t": pts_arr[end_i],
                                "window_s": round(pts_arr[end_i] - pts_arr[start_i], 3),
                                "end_cap_frac": END_CAP_FRAC,
                                "largest_event_selection_suspicious":
                                    (pts_arr[end_i] - pts_arr[start_i]) > SUSPICIOUS_FRAC * (pts_arr[-1] - pts_arr[0]),
                                "largest_sustained_v_event": largest_event},
            "progress_coordinate": {
                "axis_angle_deg": round(axis_angle, 2) if axis_angle is not None else None,
                "inlier_fraction": round(inlier_frac, 4) if inlier_frac is not None else None,
                "s_range": round(s_range, 5) if s_range is not None else None,
                "sustained_progression_fraction": round(prog_frac, 4) if prog_frac is not None else None,
                "n_axis_samples": len(pts2d),
            },
            "terminal_region": terminal,
            "classification": cls,
            "justification": just,
        }
        print(f"[{did}] {cls.split('_FROM_')[0]} axis={axis_angle} inlier={inlier_frac} "
              f"prog={prog_frac} terminal={terminal['detected']} "
              f"flips={len(flips)} bounds=({pts_arr[start_i]:.2f},{pts_arr[end_i] if end_i < n else None})")

    out = {
        "label": "TWOD_APPROACH_AUDIT_V1",
        "date": now,
        "gt_used": False,
        "constants": {"median_filter_half_s": MEDFILT_HALF_S, "vx_hysteresis": VX_HYST,
                      "speed_thr": SPEED_THR, "speed_min_s": SPEED_MIN_S,
                      "end_cap_frac": END_CAP_FRAC, "pca_iters": PCA_ITERS,
                      "slowdown_frac": SLOWDOWN_FRAC, "lookback_s": LOOKBACK_S,
                      "class_thresholds": CLASS_THR},
        "script_sha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(),
        "traj_cache_sha256": hashlib.sha256(T1.CACHE_PATH.read_bytes()).hexdigest(),
        "per_dive": per_dive,
    }
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=1)
    print(f"[saved] {OUT_PATH}")


if __name__ == "__main__":
    main()
