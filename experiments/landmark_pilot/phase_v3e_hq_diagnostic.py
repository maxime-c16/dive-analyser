#!/usr/bin/env python3
"""T5 — Phase G: HQ read-only diagnostic for dives 1040 and 2169.

Runs the SAME frozen D5 framewise recipe on the two HQ renditions
(READ-ONLY authority — files are never modified; no HQ-derived parameter may
enter Event Logic). PTS are PTS_EQUIVALENT (offset 0, confirmed by the HQ
thread) — verified here report-only.

Per dive, on the SAME analysis primitives as the 360p signal:
  - target stability: cy level-switch count/locations (|cy - running_median|
    > 0.15 sustained > 0.2 s)
  - near-GT-window (GT_takeoff +/- 0.35 s) raw_neg_ratio / smooth_neg_ratio
    (sigma 0.1167 s) vs documented 360p values (1040: 0.381/0.0; 2169: 0.19/0.0)
  - B1-style robust support median + MAD (360p vs HQ)
  - V3-D0 hurdle path run GT-blind on the HQ cy signal: takeoff + error vs GT
    (report-only; does not feed back into params)
  - approach-progress coordinate quality (axis inlier fraction 360p vs HQ)

Verdict (exactly one per dive):
  HQ_REPAIRS_TARGET_IDENTITY_ONLY / HQ_REPAIRS_APPROACH_AND_TAKEOFF_KINEMATICS /
  HQ_IMPROVES_SNR_ONLY / HQ_NO_MATERIAL_GAIN

NOTE: cy_norm is relative to frame height, which differs between the portrait
360p proxies (202x360) and the HQ framings — shapes/relative dynamics are
compared, absolute cy levels are reported per rendition for context.

Output: docs/science/HQ_HURDLE_DIAGNOSTIC_V1.json
Sidecar cache: docs/science/HQ_HURDLE_TRAJ_CACHE_V2.json (idempotent)

Usage: caffeinate -i -s .venv/bin/python experiments/landmark_pilot/phase_v3e_hq_diagnostic.py
"""

import sys, json, hashlib, datetime
import numpy as np
from pathlib import Path

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))

from proposer_event_logic_v2_1 import (
    pts_aware_velocity, pts_aware_smooth, interpolate_gaps_time,
    _find_preparation_end,
)
from proposer_event_logic_v3_d0 import propose_events_v3d0, PARAMS_V3D0
import build_hurdle_traj_cache_v2 as T1
import phase_v3e_2d_audit as D2

OUT_PATH = BASE / "docs/science/HQ_HURDLE_DIAGNOSTIC_V1.json"
HQ_CACHE = BASE / "docs/science/HQ_HURDLE_TRAJ_CACHE_V2.json"

HQ_ASSETS = {
    "1040": {"path": BASE / "runs/highres_recovery_v1/batch_media/dive_1040/edited_highres_rendition/IMG_4301.mov",
             "expected": {"W": 1920, "H": 1080, "n_frames": 332}},
    "2169": {"path": BASE / "runs/highres_recovery_v1/batch_media/dive_2169/edited_highres_rendition/IMG_9474_edited.mov",
             "expected": {"W": 742, "H": 418, "n_frames": 1078}},
}

SWITCH_DIFF_THR = 0.15
SWITCH_MIN_S    = 0.2
RUNMED_WIN_S    = 1.0
GATE_WINDOW_S   = 0.35
SMOOTH_SIGMA_S  = 0.35 / 3.0     # 0.1167 s (documented)
DOC_360P_RATIOS = {"1040": {"raw_neg_ratio": 0.381, "smooth_neg_ratio": 0.0},
                   "2169": {"raw_neg_ratio": 0.19,   "smooth_neg_ratio": 0.0}}


def level_switches(y_arr, pts_arr, diff_thr=SWITCH_DIFF_THR, min_s=SWITCH_MIN_S):
    """Count/locate sustained departures from a trailing running median."""
    n = len(y_arr)
    flags = [False] * n
    for i in range(n):
        if y_arr[i] is None:
            continue
        lo = max(0, i - int(RUNMED_WIN_S * 60))
        win = [y_arr[j] for j in range(lo, i) if y_arr[j] is not None]
        if len(win) < 5:
            continue
        rm = float(np.median(win))
        if abs(y_arr[i] - rm) > diff_thr:
            flags[i] = True
    # group consecutive flagged runs
    runs, i = [], 0
    while i < n:
        if flags[i]:
            j = i
            while j < n and flags[j]:
                j += 1
            if pts_arr[j - 1] - pts_arr[i] >= min_s:
                runs.append({"t_start": pts_arr[i], "t_end": pts_arr[j - 1],
                             "dur_s": round(pts_arr[j - 1] - pts_arr[i], 3),
                             "level_mean": round(float(np.mean(
                                 [y_arr[k] for k in range(i, j) if y_arr[k] is not None])), 4)})
            i = j
        else:
            i += 1
    return runs


def neg_ratios(y_arr, pts_arr, gt_takeoff, window_s=GATE_WINDOW_S):
    """Raw / smoothed (sigma 0.1167 s) negative-velocity ratios in the
    documented GT-takeoff window (diagnostic only — report-only GT usage)."""
    vel_raw = pts_aware_velocity(y_arr, pts_arr, 0.20)
    y_smooth = pts_aware_smooth(y_arr, pts_arr, sigma_s=SMOOTH_SIGMA_S)
    vel_smooth = pts_aware_velocity(y_smooth, pts_arr, 0.20)
    n_raw = n_sm = n_tot = 0
    for i, t in enumerate(pts_arr):
        if abs(t - gt_takeoff) > window_s:
            continue
        n_tot += 1
        if vel_raw[i] is not None and vel_raw[i] < 0:
            n_raw += 1
        if vel_smooth[i] is not None and vel_smooth[i] < 0:
            n_sm += 1
    return {"window_s": window_s, "n_frames": n_tot,
            "raw_neg_frames": n_raw, "raw_neg_ratio": round(n_raw / n_tot, 3) if n_tot else None,
            "smooth_neg_frames": n_sm, "smooth_neg_ratio": round(n_sm / n_tot, 3) if n_tot else None}


def b1_support_full(y_arr, pts_arr, conf_arr, params):
    vel_raw = pts_aware_velocity(y_arr, pts_arr, params["vel_max_gap_s"])
    y_smooth = interpolate_gaps_time(pts_aware_smooth(y_arr, pts_arr, params["smooth_window_s"] / 3),
                                     pts_arr, params["interp_max_gap_s"])
    prep_end_i = _find_preparation_end(y_smooth, pts_arr, params)
    p_end = prep_end_i if prep_end_i is not None else len(y_arr) - 1
    idx = [i for i in range(0, p_end + 1)
           if y_arr[i] is not None and conf_arr[i] >= 0.10
           and vel_raw[i] is not None and abs(vel_raw[i]) <= 0.02]
    if not idx:
        return {"prep_end_t": pts_arr[p_end], "n_cluster": 0,
                "median": None, "mad": None}
    v = np.asarray([y_arr[i] for i in idx])
    med = float(np.median(v))
    mad = float(np.median(np.abs(v - med)))
    keep = v[np.abs(v - med) <= 1.5 * mad] if mad > 0 else v
    return {"prep_end_t": pts_arr[p_end], "n_cluster": int(len(idx)),
            "median_plain": round(med, 5), "mad": round(mad, 5),
            "median_rejected": round(float(np.median(keep)), 5)}


def approach_coord_quality(frames, params):
    """Same primitives as T4: bounds + robust PCA axis inlier fraction."""
    y_arr, pts_arr, conf_arr = T1.traj_arrays(frames)
    cx_arr = [f["cx"] for f in frames]
    n = len(frames)
    cx_f = D2.median_filter_time(cx_arr, pts_arr, D2.MEDFILT_HALF_S)
    cy_f = D2.median_filter_time(y_arr, pts_arr, D2.MEDFILT_HALF_S)
    vx = D2.central_vel(cx_f, pts_arr)
    vy = D2.central_vel(cy_f, pts_arr)
    speed = [None if (a is None or b is None) else float(np.hypot(a, b))
             for a, b in zip(vx, vy)]
    speed_f = D2.median_filter_time(speed, pts_arr, D2.MEDFILT_HALF_S)
    y_smooth = interpolate_gaps_time(pts_aware_smooth(y_arr, pts_arr, params["smooth_window_s"] / 3),
                                     pts_arr, params["interp_max_gap_s"])
    prep_end_i = _find_preparation_end(y_smooth, pts_arr, params)
    start_i = prep_end_i if prep_end_i is not None else 0
    events, i = [], 0
    while i < n:
        if speed_f[i] is not None and speed_f[i] > D2.SPEED_THR:
            j = i
            while j < n and speed_f[j] is not None and speed_f[j] > D2.SPEED_THR:
                j += 1
            if pts_arr[j - 1] - pts_arr[i] >= D2.SPEED_MIN_S:
                events.append((i, j, sum(s for s in speed_f[i:j] if s is not None)))
            i = j
        else:
            i += 1
    if events:
        big = max(events, key=lambda e: e[2])
        end_i = min(big[0] - 1, int(D2.END_CAP_FRAC * n) - 1)
    else:
        end_i = int(D2.END_CAP_FRAC * n) - 1
    end_i = max(end_i, start_i + 2)
    pts2d = [(cx_f[i], cy_f[i]) for i in range(start_i, end_i + 1)
             if cx_f[i] is not None and cy_f[i] is not None]
    if len(pts2d) < 10:
        return {"n_axis_samples": len(pts2d), "inlier_fraction": None,
                "note": "too few 2D samples in approach window"}
    axis, pmean, inlier_frac, *_ = D2.robust_pca_axis(pts2d)
    return {"start_t": pts_arr[start_i], "end_t": pts_arr[end_i],
            "n_axis_samples": len(pts2d),
            "axis_angle_deg": round(float(np.degrees(np.arctan2(axis[1], axis[0]))), 2),
            "inlier_fraction": round(inlier_frac, 4)}


def main():
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cache360 = T1.load_json(T1.CACHE_PATH)
    params = PARAMS_V3D0
    hq_cache = T1.load_json(HQ_CACHE) or {"label": "HQ_HURDLE_TRAJ_CACHE_V2",
                                          "pipeline": "D5_FRAMEWISE_ONLY",
                                          "model_sha256": cache360["model_sha256"],
                                          "per_dive": {}}

    model, device = T1.load_model()
    results = {}

    for did in ("1040", "2169"):
        spec = next(s for s in T1.DIVES if s["id"] == did)
        gt = spec["gt"]
        asset = HQ_ASSETS[did]
        if not asset["path"].exists():
            results[did] = {"status": "BLOCKED_HQ_ASSET_MISSING", "path": str(asset["path"])}
            continue

        # ── HQ inference (idempotent) ────────────────────────────────────────
        prev = hq_cache["per_dive"].get(did)
        if prev and prev.get("rendition_sha256") and prev.get("frames"):
            cur = T1.sha256_file(asset["path"])
            if cur == prev["rendition_sha256"]:
                frames, fps, W, H = prev["frames"], prev["fps"], *prev["video_size"]
                sha = cur
                print(f"[reuse] HQ {did}")
            else:
                frames = None
        else:
            frames = None
        if frames is None:
            print(f"[run] HQ {did} ({asset['path'].name})")
            sha = T1.sha256_file(asset["path"])
            frames, fps, W, H, _ = T1.run_inference_for_dive(model, device, asset["path"], f"HQ_{did}")
            hq_cache["per_dive"][did] = {
                "rendition": str(asset["path"].relative_to(BASE)),
                "rendition_sha256": sha, "fps": round(fps, 6),
                "video_size": [W, H], "n_frames": len(frames), "frames": frames,
                "updated": now,
            }
            with open(HQ_CACHE, "w") as f:
                json.dump(hq_cache, f)

        exp = asset["expected"]
        rendition_check = {"size_matches_expected": sorted([W, H]) == sorted([exp["W"], exp["H"]]),
                           "n_frames_matches_expected": len(frames) == exp["n_frames"],
                           "video_size": [W, H], "n_frames": len(frames),
                           "note": "size compared orientation-agnostic (cv2 WxH order)"}

        # ── 360p reference data ──────────────────────────────────────────────
        f360 = cache360["per_dive"][did]["frames"]
        y360, p360, c360 = T1.traj_arrays(f360)

        # ── PTS equivalence check (report-only) ──────────────────────────────
        yhq, phq, chq = T1.traj_arrays(frames)
        v360 = [t for t, y in zip(p360, y360) if y is not None]
        vhq = [t for t, y in zip(phq, yhq) if y is not None]
        n_cmp = min(len(v360), len(vhq))
        pts_check = {
            "360p_first": v360[0], "360p_last": v360[-1],
            "hq_first": vhq[0], "hq_last": vhq[-1],
            "first_offset_s": round(vhq[0] - v360[0], 6),
            "last_offset_s": round(vhq[-1] - v360[-1], 6),
            "per_frame_offset_median_s": (round(float(np.median(
                [b - a for a, b in zip(v360[:n_cmp], vhq[:n_cmp])])), 6)
                if n_cmp and len(v360) == len(vhq) else None),
            "same_frame_count": len(v360) == len(vhq),
            "verdict": ("PTS_EQUIVALENT_WITHIN_20MS"
                        if abs(vhq[0] - v360[0]) <= 0.02 and abs(vhq[-1] - v360[-1]) <= 0.02
                        else "SYSTEMATIC_OFFSET_REPORTED_NOT_MAPPED"),
        }

        # ── target stability ─────────────────────────────────────────────────
        sw360 = level_switches(y360, p360)
        sw_hq = level_switches(yhq, phq)

        # ── near-GT-window negative-velocity ratios ──────────────────────────
        nr360 = neg_ratios(y360, p360, gt["takeoff"])
        nr_hq = neg_ratios(yhq, phq, gt["takeoff"])

        # ── B1-style support ─────────────────────────────────────────────────
        b1_360 = b1_support_full(y360, p360, c360, params)
        b1_hq = b1_support_full(yhq, phq, chq, params)

        # ── V3-D0 on HQ signal (GT-blind run, report-only) ───────────────────
        pred_hq = propose_events_v3d0(yhq, phq, chq, spec["code"], params)
        hq_to_err = (round(abs(pred_hq["takeoff_t"] - gt["takeoff"]), 4)
                     if pred_hq.get("takeoff_t") is not None else None)
        pred_360 = propose_events_v3d0(y360, p360, c360, spec["code"], params)
        p360_to_err = (round(abs(pred_360["takeoff_t"] - gt["takeoff"]), 4)
                       if pred_360.get("takeoff_t") is not None else None)

        # ── approach coordinate quality ──────────────────────────────────────
        ac_hq = approach_coord_quality(frames, params)
        t4 = T1.load_json(D2.OUT_PATH)
        ac_360 = t4["per_dive"][did]["progress_coordinate"]["inlier_fraction"] if t4 else None

        # ── verdict (deterministic rule) ─────────────────────────────────────
        identity_repaired = (len(sw_hq) == 0 and len(sw_hq) < len(sw360)) or \
                            (len(sw360) > 0 and len(sw_hq) <= 0.5 * len(sw360))
        takeoff_repaired = (hq_to_err is not None and
                            (p360_to_err is None or
                             (hq_to_err <= 0.5 and hq_to_err < p360_to_err) or
                             hq_to_err <= 0.5 * p360_to_err))
        snr_improved = (b1_hq.get("mad") is not None and b1_360.get("mad") is not None
                        and b1_hq["mad"] <= b1_360["mad"]
                        and float(np.nanmedian(chq)) > float(np.nanmedian(c360)) + 0.05)
        if identity_repaired and takeoff_repaired:
            verdict = "HQ_REPAIRS_APPROACH_AND_TAKEOFF_KINEMATICS"
        elif identity_repaired:
            verdict = "HQ_REPAIRS_TARGET_IDENTITY_ONLY"
        elif snr_improved:
            verdict = "HQ_IMPROVES_SNR_ONLY"
        else:
            verdict = "HQ_NO_MATERIAL_GAIN"

        results[did] = {
            "code": spec["code"],
            "rendition": str(asset["path"].relative_to(BASE)),
            "rendition_sha256": sha,
            "rendition_check": rendition_check,
            "hq_read_only": True,
            "pts_check": pts_check,
            "absolute_cy_context": {
                "note": "cy_norm is frame-height-relative; framings differ (360p portrait "
                        "202x360 vs HQ). Compare relative dynamics, not absolute levels.",
                "cy_median_360p": round(float(np.nanmedian(y360)), 4),
                "cy_median_hq": round(float(np.nanmedian(yhq)), 4),
                "frame_size_360p": cache360["per_dive"][did]["video_size"],
                "frame_size_hq": [W, H],
            },
            "target_stability": {
                "360p_switches": {"count": len(sw360), "events": sw360},
                "hq_switches": {"count": len(sw_hq), "events": sw_hq},
            },
            "neg_velocity_ratios": {
                "360p": nr360, "documented_360p": DOC_360P_RATIOS[did],
                "360p_matches_documented": (
                    nr360["raw_neg_ratio"] == DOC_360P_RATIOS[did]["raw_neg_ratio"]
                    and nr360["smooth_neg_ratio"] == DOC_360P_RATIOS[did]["smooth_neg_ratio"]),
                "hq": nr_hq,
                "note": "The HQ-vs-360p comparison is computed on IDENTICAL primitives "
                        "(same recipe, same gate window) and is the controlled comparison. "
                        "The documented 360p ratios come from "
                        "HURDLE_OBSERVABILITY_V3D_ANALYSIS_V1 and do not exactly replicate "
                        "here (see 360p_matches_documented); the discrepancy is reported, "
                        "not reconciled, and no parameter is derived from either.",
            },
            "b1_support": {"360p": b1_360, "hq": b1_hq},
            "v3d0_on_hq": {
                "predicted": {k: pred_hq.get(k) for k in
                              ("prep_end_t", "takeoff_t", "apex_t", "water_contact_t")},
                "to_err_hq": hq_to_err, "to_err_360p": p360_to_err,
                "report_only": True,
            },
            "approach_coordinate": {"360p_inlier_fraction": ac_360, "hq": ac_hq},
            "verdict": verdict,
            "verdict_evidence": {
                "identity_repaired": identity_repaired,
                "takeoff_repaired": takeoff_repaired,
                "snr_improved": snr_improved,
            },
        }
        print(f"[{did}] switches 360p={len(sw360)} hq={len(sw_hq)} | "
              f"neg360={nr360['raw_neg_ratio']}/{nr360['smooth_neg_ratio']} "
              f"negHQ={nr_hq['raw_neg_ratio']}/{nr_hq['smooth_neg_ratio']} | "
              f"to_err 360p={p360_to_err} hq={hq_to_err} | VERDICT={verdict}")

    out = {
        "label": "HQ_HURDLE_DIAGNOSTIC_V1",
        "date": now,
        "hq_read_only": True,
        "assets_used": ["1040", "2169"],
        "pts_assumption": "PTS_EQUIVALENT (offset 0) per HQ thread; verified report-only",
        "model_sha256": cache360["model_sha256"],
        "script_sha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(),
        "gt_note": "GT used only for the documented neg-ratio diagnostic window and "
                   "post-hoc error reporting; no HQ-derived value feeds Event Logic params.",
        "results": results,
    }
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=1)
    print(f"[saved] {OUT_PATH}")


if __name__ == "__main__":
    main()
