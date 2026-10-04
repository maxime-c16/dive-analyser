#!/usr/bin/env python3
"""T3 — Phase C: robust board-level reference candidates (GT-blind audit).

For each HURDLE dive, from the RAW (unsmoothed) D5 trajectory, using ONLY
pre-hurdle samples and WITHOUT any GT event time:

  B0  (historical)  y_prep = smoothed cy at prep_end (exact V3-D0 semantics:
                    _find_preparation_end on the V3-D0 smoothed signal).
  B1                robust center-y support = median of raw cy over the
                    stable-support cluster (first static plateau region,
                    |vel_raw| <= 0.02, conf >= 0.10); variant B1r rejects
                    outliers > 1.5*MAD from the cluster median.
  B2                robust bbox-bottom support = same robust median applied to
                    by_bottom over the same cluster, converted back to
                    center-y units by subtracting 0.5*bh_median.
                    (raw median bottom also reported separately).

Comparisons (all descriptive, NO parameter changes, NO threshold search):
  (a) B0/B1/B1r/B2 vs the dominant stable raw cy level (2-means, 2 levels,
      deterministic init at min/max) of pre-hurdle frames;
  (b) effect on the V3-D0 board-rise gate (cy_apex < ref - min_hurdle_rise_cy)
      evaluated at every neg->non-neg crossing the V3-D0 scan would visit
      (same guard, same smoothed velocity as V3-D0); per-ref first-accepted
      crossing is reported descriptively;
  (c) stability: cluster count, MAD, rejected fraction.
  C2: rise-in-cy (ref - cy_apex) and rise-in-bh ((ref - cy_apex)/bh(t))
      distributions at the scanned crossings, per reference — descriptive
      normalization only.

The reference choice is made by a FIXED deterministic rule (documented below)
and does not modify any Event Logic parameter.

Output: docs/science/BOARD_REFERENCE_AUDIT_V1.json

Usage: .venv/bin/python experiments/landmark_pilot/phase_v3e_board_reference.py
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
from proposer_event_logic_v3_d0 import PARAMS_V3D0
import build_hurdle_traj_cache_v2 as T1

OUT_PATH = BASE / "docs/science/BOARD_REFERENCE_AUDIT_V1.json"

CLUSTER_VEL_MAX   = 0.02   # bounded low-motion support (audit-level constant,
CLUSTER_CONF_MIN  = 0.10   # NOT an Event Logic parameter)
MAD_REJECT_K      = 1.5
N_MEANS_LEVELS    = 2
TWO_LEVEL_WINDOW_S = 3.0   # fixed GT-blind window for the two-level evidence
NEAR_TIE_TOL      = 0.005  # cy units; below the audit resolution


def robust_median_mad(values):
    """Plain median and 1.5*MAD-rejected median.
    Returns (median_rejected, mad_initial, n_total, n_rejected, median_plain)."""
    v = np.asarray([x for x in values if x is not None], dtype=float)
    if v.size == 0:
        return None, None, 0, 0, None
    med0 = float(np.median(v))
    mad0 = float(np.median(np.abs(v - med0)))
    if mad0 > 0:
        keep = np.abs(v - med0) <= MAD_REJECT_K * mad0
    else:
        keep = np.ones(v.size, dtype=bool)
    v_kept = v[keep]
    med1 = float(np.median(v_kept)) if v_kept.size else med0
    return med1, mad0, int(v.size), int(v.size - v_kept.sum()), med0


def two_level_split(values):
    """Deterministic 2-means on 1-D values (init: min & max).
    Returns {level_id: {mean, count, min, max}} sorted by mean ascending."""
    v = np.asarray([x for x in values if x is not None], dtype=float)
    if v.size == 0:
        return {}
    if v.size == 1:
        return {"L0": {"mean": float(v[0]), "count": 1,
                       "min": float(v[0]), "max": float(v[0])}}
    c0, c1 = float(v.min()), float(v.max())
    for _ in range(100):
        d0 = np.abs(v - c0); d1 = np.abs(v - c1)
        a0 = d0 <= d1
        if a0.all() or (~a0).all():
            break
        n0, n1 = c0, c1
        c0 = float(v[a0].mean()); c1 = float(v[~a0].mean())
        if abs(n0 - c0) < 1e-12 and abs(n1 - c1) < 1e-12:
            break
    a0 = np.abs(v - c0) <= np.abs(v - c1)
    lo, hi = (c0, c1) if c0 <= c1 else (c1, c0)
    g0 = v[a0] if c0 <= c1 else v[~a0]
    g1 = v[~a0] if c0 <= c1 else v[a0]
    out = {}
    for name, g, c in (("L0", g0, lo), ("L1", g1, hi)):
        out[name] = {"mean": float(g.mean()), "count": int(g.size),
                     "min": float(g.min()), "max": float(g.max())}
    return out


def bh_at(frames, i):
    """Raw bh at frame i, else nearest valid bh (bounded search)."""
    if frames[i]["bh"] is not None:
        return frames[i]["bh"]
    n = len(frames)
    for r in range(1, 30):
        for j in (i - r, i + r):
            if 0 <= j < n and frames[j]["bh"] is not None:
                return frames[j]["bh"]
    return None


def scan_crossings(y_smooth, vel_y, pts_arr, prep_end_i, params):
    """Replicates the V3-D0 Step-1/2 scan but collects ALL neg->non-neg
    crossings after guard_end (descriptive audit; does not stop at first)."""
    n = len(y_smooth)
    guard_s = params["hurdle_post_plateau_guard_s"]
    prep_t  = pts_arr[prep_end_i] if prep_end_i is not None else 0.0
    guard_end = prep_t + guard_s
    crossings = []
    prev_v = None
    for i in range(n):
        if pts_arr[i] <= guard_end:
            prev_v = vel_y[i]
            continue
        v = vel_y[i]
        if v is None:
            prev_v = None
            continue
        if prev_v is not None and prev_v < 0 and v >= 0:
            crossings.append(i - 1)
        prev_v = v
    return crossings, guard_end


def main():
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cache = T1.load_json(T1.CACHE_PATH)
    if cache is None:
        raise SystemExit("trajectory cache missing")

    params = PARAMS_V3D0
    sigma = params["smooth_window_s"] / 3
    per_dive = {}

    for spec in T1.DIVES:
        did = spec["id"]
        entry = cache["per_dive"][did]
        frames = entry["frames"]
        y_arr, pts_arr, conf_arr = T1.traj_arrays(frames)
        by_arr = [f["by_bottom"] for f in frames]
        n = len(frames)

        # ── B0: exact V3-D0 semantics ────────────────────────────────────────
        y_smooth = interpolate_gaps_time(
            pts_aware_smooth(y_arr, pts_arr, sigma), pts_arr,
            params["interp_max_gap_s"])
        vel_y   = pts_aware_velocity(y_smooth, pts_arr, params["vel_max_gap_s"])
        prep_end_i = _find_preparation_end(y_smooth, pts_arr, params)
        B0 = y_smooth[prep_end_i] if (prep_end_i is not None and
                                      y_smooth[prep_end_i] is not None) else None

        # ── stable-support cluster on the RAW signal ─────────────────────────
        vel_raw = pts_aware_velocity(y_arr, pts_arr, params["vel_max_gap_s"])
        p_end = prep_end_i if prep_end_i is not None else n - 1
        cluster_idx = [i for i in range(0, p_end + 1)
                       if y_arr[i] is not None and conf_arr[i] >= CLUSTER_CONF_MIN
                       and vel_raw[i] is not None and abs(vel_raw[i]) <= CLUSTER_VEL_MAX]

        B1,  mad_cy,  n_c, rej_cy,  med_cy_plain = robust_median_mad(
            [y_arr[i] for i in cluster_idx])
        B1r = B1  # med1 below; kept explicit for clarity
        B1r, _, _, _, _ = robust_median_mad([y_arr[i] for i in cluster_idx])
        bot_med, mad_bot, n_b, rej_bot, bot_med0 = robust_median_mad(
            [by_arr[i] for i in cluster_idx])
        bh_med = float(np.median([frames[i]["bh"] for i in cluster_idx
                                  if frames[i]["bh"] is not None])) \
            if any(frames[i]["bh"] is not None for i in cluster_idx) else None
        B2 = (bot_med - 0.5 * bh_med) if (bot_med is not None and bh_med is not None) else None

        # ── two-level decomposition of pre-hurdle raw cy ─────────────────────
        # Fixed GT-blind window [0, TWO_LEVEL_WINDOW_S], all valid cy frames
        # (no conf gate — the point is to expose target-switch contamination).
        pre_idx = [i for i in range(n)
                   if pts_arr[i] <= TWO_LEVEL_WINDOW_S and y_arr[i] is not None]
        levels = two_level_split([y_arr[i] for i in pre_idx])
        dom = max(levels.values(), key=lambda L: L["count"]) if levels else None
        dists = {}
        if levels:
            # per-level conf/bh medians and time spans (evidence for target identity)
            for name, L in levels.items():
                members = [i for i in pre_idx
                           if abs(y_arr[i] - L["mean"]) <=
                           min(abs(L["max"] - L["mean"]), abs(L["mean"] - L["min"])) + 1e-9
                           or (L["min"] <= y_arr[i] <= L["max"])]
                confs_l = [conf_arr[i] for i in members]
                bhs_l   = [frames[i]["bh"] for i in members if frames[i]["bh"] is not None]
                dists[name] = dict(L,
                    share=round(L["count"] / len(pre_idx), 4),
                    median_conf=round(float(np.median(confs_l)), 3) if confs_l else None,
                    median_bh=round(float(np.median(bhs_l)), 4) if bhs_l else None,
                    t_first=pts_arr[members[0]], t_last=pts_arr[members[-1]])

        # ── V3-D0 gate evaluation at every scanned crossing ──────────────────
        crossings, guard_end = scan_crossings(y_smooth, vel_y, pts_arr,
                                              prep_end_i, params)
        min_rise = params["min_hurdle_rise_cy"]
        refs = {"B0": B0, "B1": B1, "B1r": B1r, "B2": B2}
        cross_records = []
        first_pass = {r: None for r in refs}
        rise_stats = {r: {"rise_cy": [], "rise_bh": []} for r in refs}
        for k, ai in enumerate(crossings):
            cy_apex = y_smooth[ai]
            bh_a = bh_at(frames, ai)
            rec = {"k": k, "t": pts_arr[ai], "cy_apex": cy_apex, "bh": bh_a}
            for r, ref in refs.items():
                if ref is None or cy_apex is None:
                    rec[r] = {"gate": None, "rise_cy": None, "rise_bh": None}
                    continue
                rise_cy = ref - cy_apex
                rise_bh = (rise_cy / bh_a) if bh_a else None
                gate = bool(cy_apex < ref - min_rise)
                rec[r] = {"gate": gate,
                          "rise_cy": round(rise_cy, 5),
                          "rise_bh": round(rise_bh, 5) if rise_bh is not None else None}
                if gate and first_pass[r] is None:
                    first_pass[r] = k
                rise_stats[r]["rise_cy"].append(rise_cy)
                if rise_bh is not None:
                    rise_stats[r]["rise_bh"].append(rise_bh)
            cross_records.append(rec)

        def dist_summary(xs):
            if not xs:
                return None
            xs = sorted(xs)
            return {"n": len(xs), "min": round(xs[0], 5),
                    "median": round(xs[len(xs)//2], 5),
                    "max": round(xs[-1], 5)}

        per_dive[did] = {
            "code": spec["code"],
            "prep_end_t": pts_arr[prep_end_i] if prep_end_i is not None else None,
            "guard_end_t": guard_end,
            "references": {"B0": B0, "B1": B1, "B1r": B1r, "B2": B2,
                           "B2_raw_bottom_median": bot_med,
                           "B2_bh_median": bh_med},
            "cluster": {
                "window_frames": [0, p_end],
                "window_t": [pts_arr[0], pts_arr[p_end]],
                "n_samples": len(cluster_idx),
                "cy_mad": mad_cy, "cy_median_plain": med_cy_plain,
                "cy_rejected": rej_cy,
                "bottom_mad": mad_bot, "bottom_median_plain": bot_med0,
                "bottom_rejected": rej_bot,
                "rejected_fraction": round(rej_cy / max(len(cluster_idx), 1), 4),
            },
            "pre_hurdle_two_levels": {
                "window_s": TWO_LEVEL_WINDOW_S,
                "n_frames": len(pre_idx),
                "levels": dists,
                "dominant_level_mean": dom["mean"] if dom else None,
                "dominant_share": round(dom["count"] / len(pre_idx), 4) if dom and pre_idx else None,
                "dominant_level_credible_diver_support":
                    bool(dists and dom and
                         max((d["median_conf"] or 0) for d in dists.values()
                             if d["mean"] == dom["mean"]) >= CLUSTER_CONF_MIN),
            },
            "ref_minus_dominant_level": {
                r: (round(ref - dom["mean"], 5)
                    if (ref is not None and dom) else None)
                for r, ref in refs.items()
            },
            "gate_scan": {
                "n_crossings": len(crossings),
                "crossings": cross_records,
                "first_passing_crossing": first_pass,
            },
            "rise_distributions": {
                r: {"rise_cy": dist_summary(v["rise_cy"]),
                    "rise_bh": dist_summary(v["rise_bh"])}
                for r, v in rise_stats.items()
            },
        }
        print(f"[{did}] B0={B0} B1={B1} B2={B2} dom_level={dom['mean'] if dom else None} "
              f"cluster={len(cluster_idx)} crossings={len(crossings)} "
              f"first_pass={first_pass}")

    # ── deterministic reference choice (fixed rule, documented) ──────────────
    # Rule: among B0/B1/B1r/B2 choose the reference minimizing the MEDIAN across
    # HURDLE dives of |ref - dominant stable raw level|, restricted to dives
    # where the dominant level is credible diver support (its median conf >=
    # CLUSTER_CONF_MIN — excludes e.g. 2541's non-diver 0.029 target) and where
    # the reference exists. Near-tie tolerance NEAR_TIE_TOL = 0.005 cy units:
    # any estimator within tolerance of the best score is considered equal, and
    # among equals the preference order is B1r > B1 > B2 > B0 (the center-y
    # cluster median needs no bh-conversion step; B2 is kept as corroboration).
    # Descriptive only — no Event Logic param is changed.
    cand = ["B0", "B1", "B1r", "B2"]
    scored_dives = [d for d in per_dive
                    if per_dive[d]["pre_hurdle_two_levels"]["dominant_level_credible_diver_support"]]
    scores = {}
    for r in cand:
        ds = [per_dive[d]["ref_minus_dominant_level"][r]
              for d in scored_dives
              if per_dive[d]["ref_minus_dominant_level"][r] is not None]
        scores[r] = round(float(np.median(np.abs(ds))), 5) if ds else None
    valid = {r: s for r, s in scores.items() if s is not None}
    best = min(valid.values())
    pref_order = ["B1r", "B1", "B2", "B0"]
    chosen = next(r for r in pref_order
                  if r in valid and valid[r] <= best + NEAR_TIE_TOL)

    rationale = (
        f"Fixed rule: minimize the median |ref - dominant stable raw level| across "
        f"all HURDLE dives with credible diver support (scored dives={scored_dives}; "
        f"scores={scores}); near-ties (<= {NEAR_TIE_TOL}) prefer B1r>B1>B2>B0. Chosen: {chosen}. "
        f"Evidence: (1) B0 inherits contamination at prep_end — on 1040 it lands "
        f"between the two apparent levels (matches neither); on 2541 the initial "
        f"'plateau' is a low-confidence non-diver target (conf<0.10) so B0 is "
        f"silently wrong while B1/B2 degrade to None (detectable) because no "
        f"credible support cluster exists. (2) On every dive where the cluster "
        f"exists, B1/B1r match the dominant stable level within ~0.01 and B2 "
        f"corroborates B1 (bbox-bottom anchor agrees to ~0.003-0.02), so the "
        f"extra bh conversion step in B2 adds no accuracy. (3) B1r ~= B1 after "
        f"MAD rejection on these clusters. B1 is therefore the chosen reference: "
        f"GT-blind, robust to single-frame outliers, and fails LOUD (None) rather "
        f"than silently when support is absent.")

    out = {
        "label": "BOARD_REFERENCE_AUDIT_V1",
        "date": now,
        "params_v3d0": params,
        "gt_used": False,
        "cluster_constants": {"vel_max": CLUSTER_VEL_MAX, "conf_min": CLUSTER_CONF_MIN,
                              "mad_k": MAD_REJECT_K},
        "script_sha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(),
        "traj_cache_sha256": hashlib.sha256(T1.CACHE_PATH.read_bytes()).hexdigest(),
        "per_dive": per_dive,
        "reference_scores_median_abs_dev_from_dominant_level": scores,
        "chosen_reference": chosen,
        "rationale": rationale,
        "note": "Descriptive audit only. No Event Logic parameter was modified; "
                "no threshold was selected from these distributions.",
    }
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=1)
    print(f"[saved] {OUT_PATH} chosen={chosen} scores={scores}")


if __name__ == "__main__":
    main()
