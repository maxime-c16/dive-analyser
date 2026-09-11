#!/usr/bin/env python3
"""V4 Phases C + D — baseline-preservation gate + GT-free component ranking.

HURDLE_IDENTITY_COMPONENT_AND_TARGET_SELECTION_V4.

Phase C  BASELINE_STABILITY_GATE: GT-free decision KEEP_D5_TOP1 when the
         frozen D5 op-point top-1 path is already highly stable (long
         temporal continuity, low bbox-jump rate, low appearance
         discontinuity, low top-1 volatility, meaningful motion present,
         high usable coverage). No GT, no per-dive constants.

Phase D  V7 component ranking: identity components (Phase A mutual-kNN /
         bounded-degree graph), appearance-NN rollouts (Phase B repair)
         and R5-A hypotheses ranked by a NEW component-level GT-free
         scorer (v7_component_quality) built from the V3 causal findings
         (excursion saturation + departure-from-rest; appearance reward
         disabled for static components; prep->motion transition
         required). Not the V6 scorer.

Deterministic; full-clip; GT used only by evaluation.
"""

from __future__ import annotations

import math

import numpy as np

import r5_tracklets_v1 as R5
import r5b_association_v1 as R5B

# --- frozen constants ------------------------------------------------------
D5_OP_CONF = 0.05            # frozen D5 operating point (unchanged)

GATE = {                      # BASELINE_STABILITY_GATE (all generic)
    "min_coverage": 0.55,         # usable coverage of the D5 path
    "max_jump_rate": 0.03,        # bbox jumps per selected frame
    "min_consec_cos": 0.80,       # appearance continuity along the path
    "max_top1_volatility": 0.25,  # top-1 tracklet switches per selected frame
    "min_excursion": 0.10,        # meaningful motion present
    "min_longest_run_s": 2.0,     # long temporal continuity
}

V7Q = {                       # NEW v7 component-level scorer (frozen)
    "w_shape": 1.2,           # prep -> substantial-motion transition
    "shape_exc_sat": 0.20,
    "w_rest": 0.8,
    "rest_full": 0.85,
    "w_continuity": 0.5,
    "jumps_full": 8.0,
    "w_coverage": 0.4,
    "cov_full_frac": 0.25,
    "null_gate": 0.30,
    "w_null": 1.2,
    "w_ends_early": 0.4,
    "w_app": 0.5,             # appearance: ONLY for non-static components
    "static_penalty": 2.0,
    "static_exc_gate": 0.035,
    "short_mover_penalty": 1.5,
    "short_mover_life_s": 2.0,
    "post_action_penalty": 1.2,
    "post_action_start": 0.60,
    "keep_margin": 1.0,       # component must beat D5 by this much to
                              # override a KEEP_D5_TOP1 gate
    "override_min_coverage": 0.15,  # and be a usable trajectory itself
    "w_teleport": 1.0,        # velocity-plausibility penalty (see scorer)
    "human_v_max_cy_s": 1.5,  # frozen R5 human-velocity ceiling
    "teleport_cap": 3.0,
}


# ---------------------------------------------------------------------------
# Phase C — D5 op-top1 path + stability gate
# ---------------------------------------------------------------------------

def d5_optop1_path(trk):
    """Frozen D5 op-point top-1: per frame the max-confidence candidate
    with conf >= D5_OP_CONF (or None). Full-clip, GT-free."""
    out = {}
    for fi, cands in enumerate(trk["cands"]):
        op = [c for c in cands if c.conf >= D5_OP_CONF]
        if op:
            top = max(op, key=lambda c: c.conf)
            out[fi] = {"cx": top.cx, "cy": top.cy, "bw": top.bw,
                       "bh": top.bh, "conf": top.conf}
    return out


def baseline_stability_gate(trk, d5_sel, cos_fn):
    """cos_fn(fi, k) -> embedding cosine between the path's candidate at fi
    and the previous frame's matched candidate (cache-backed; None when
    either crop has no embedding). Returns (KEEP_D5_TOP1, evidence)."""
    fis = sorted(d5_sel)
    n_sel = len(fis)
    if n_sel < 2:
        return False, {"reason": "empty path"}
    n = trk["n"]
    off, fps = trk["off"], trk["fps"]
    rel = [(d5_sel[fi]["cx"] - off[fi][0], d5_sel[fi]["cy"] - off[fi][1])
           for fi in fis]
    exc_y = max(y for _, y in rel) - min(y for _, y in rel)
    steps = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(rel, rel[1:])]
    jumps = sum(1 for s in steps if s > R5.JUMP_CY)
    jump_rate = jumps / max(1, n_sel)
    coverage = n_sel / n
    # longest contiguous selected run
    runs, cur = [], 0
    prev = None
    for fi in range(n):
        if fi in d5_sel:
            cur = cur + 1 if prev == fi - 1 else 1
            prev = fi
            runs.append(cur)
        else:
            runs.append(0)
    longest_run_s = (max(runs) if runs else 0) / fps
    # top-1 volatility: how often the top-1 candidate changes identity
    # between consecutive selected frames (matched to tracklet membership)
    vol = _top1_volatility(trk, fis)
    # appearance continuity (consecutive cosine along the path)
    coss = [c for c in (cos_fn(a, b) for a, b in zip(fis, fis[1:]))
            if c is not None]
    consec = float(np.mean(coss)) if coss else None
    ev = {
        "coverage": round(coverage, 4),
        "jump_rate": round(jump_rate, 4),
        "exc_y": round(exc_y, 4),
        "longest_run_s": round(longest_run_s, 2),
        "top1_volatility": None if vol is None else round(vol, 4),
        "consec_cos": None if consec is None else round(consec, 4),
        "n_cos_pairs": len(coss),
    }
    keep = (coverage >= GATE["min_coverage"] and
            jump_rate <= GATE["max_jump_rate"] and
            exc_y >= GATE["min_excursion"] and
            longest_run_s >= GATE["min_longest_run_s"] and
            vol is not None and vol <= GATE["max_top1_volatility"] and
            consec is not None and consec >= GATE["min_consec_cos"])
    ev["keep_d5_top1"] = bool(keep)
    return bool(keep), ev


def _top1_volatility(trk, fis):
    """Fraction of consecutive selected-frame pairs where the top-1 box
    belongs to a different R5 tracklet (a real identity change), rather
    than continuing in the same tracklet."""
    by_fi = {}
    for tr in trk["tracklets"]:
        for fi in tr.starts:
            by_fi.setdefault(fi, []).append(tr.tid)
    switches = 0
    pairs = 0
    prev_tid = None
    for fi in fis:
        cands = trk["cands"][fi]
        b = d5_box(trk, fi)
        if b is None:
            continue
        # nearest candidate to the D5 top-1 box -> tracklet membership
        best, bestk = None, None
        for tr in trk["tracklets"]:
            if fi not in tr.boxes:
                continue
            bb = tr.boxes[fi]
            d = abs(bb.cx - b["cx"]) + abs(bb.cy - b["cy"])
            if best is None or d < best:
                best, bestk = d, tr.tid
        if bestk is None:
            continue
        if prev_tid is not None:
            pairs += 1
            if bestk != prev_tid:
                switches += 1
        prev_tid = bestk
    return switches / pairs if pairs else None


def d5_box(trk, fi):
    op = [c for c in trk["cands"][fi] if c.conf >= D5_OP_CONF]
    if not op:
        return None
    top = max(op, key=lambda c: c.conf)
    return {"cx": top.cx, "cy": top.cy, "bw": top.bw, "bh": top.bh}


# ---------------------------------------------------------------------------
# Phase D — v7 component-level GT-free scoring
# ---------------------------------------------------------------------------

def path_features(trk, box_map, prep_stats=None, app_mean=None):
    """Generic GT-free whole-path features from a box map."""
    off, n = trk["off"], trk["n"]
    fis = sorted(box_map)
    if len(fis) < 3:
        return None
    rel = [(box_map[fi]["cx"] - off[fi][0], box_map[fi]["cy"] - off[fi][1])
           for fi in fis]
    xs = [p[0] for p in rel]
    ys = [p[1] for p in rel]
    steps = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(rel, rel[1:])]
    jumps = sum(1 for s in steps if s > R5.JUMP_CY)
    vels = [s * trk["fps"] for s in steps]
    peak_v = max(vels) if vels else 0.0
    exc_y = max(ys) - min(ys)
    # prep->motion transition: longest low-motion prefix (flow-relative),
    # then the velocity peak must occur well after it
    win = max(3, int(round(0.5 * trk["fps"])))
    prep_end = None
    for i in range(0, max(1, len(ys) - win)):
        seg = ys[i:i + win]
        m = sum(seg) / len(seg)
        var = sum((v - m) ** 2 for v in seg) / len(seg)
        if var ** 0.5 <= R5.PREP_STD_CY:
            prep_end = i + win
        elif prep_end is not None:
            break
    if prep_end is not None:
        prep_end = min(prep_end, len(ys)) - 1
        prep_dur_s = (fis[prep_end] - fis[0]) / trk["fps"]
        prep_level = ys[prep_end]
    else:
        prep_dur_s = 0.0
        prep_level = ys[0] if ys else 0.0
    # rest_ratio: velocity shortly after the prep segment vs peak
    if prep_end and prep_end < len(vels):
        post = vels[prep_end:prep_end + int(round(0.15 * trk["fps"]))]
        rest_v = max(post) if post else 0.0
    elif vels:
        rest_v = vels[0]
    else:
        rest_v = 0.0
    rest_ratio = rest_v / max(peak_v, 1e-6)
    peak_fi = fis[int(np.argmax([
        math.hypot(x - xs[0], y - prep_level) for x, y in rel]))]
    end_lag = (fis[-1] - peak_fi) / trk["fps"]
    post = [v for v, f in zip(vels, fis) if f > peak_fi
            and (f - peak_fi) / trk["fps"] <= 1.5]
    entry = 1.0 if (exc_y >= R5.ENTRY_EXCURSION and
                    (end_lag <= R5.ENTRY_LAG_S or
                     (post and min(post) <= 0.2))) else 0.0
    null_frac = 1.0 - len(fis) / max(fis[-1] - fis[0] + 1, 1)
    return {
        "fis": fis,
        "n_frames": len(fis),
        "life_s": round((fis[-1] - fis[0]) / trk["fps"], 2),
        "exc_y": round(exc_y, 4),
        "peak_v_cy_s": round(peak_v, 3),
        "prep_dur_s": round(prep_dur_s, 2),
        "prep_level": round(prep_level, 4),
        "rest_ratio": round(rest_ratio, 3),
        "entry": entry,
        "jumps": jumps,
        "coverage": round(len(fis) / n, 4),
        "life_frac": round((fis[-1] - fis[0]) / n, 4),
        "null_frac": round(null_frac, 4),
        "start_frac": round(fis[0] / max(n - 1, 1), 3),
        "ends_early": bool(fis[-1] < 0.92 * n),
        "app_mean": None if app_mean is None else round(app_mean, 4),
    }


def v7_component_quality(feat, clip_n):
    """NEW GT-free component-level scorer (frozen constants; built from the
    V3 causal diagnosis, NOT the V6 formula):
      - shape term REQUIRES the prep->substantial-motion transition;
      - excursion saturates at dive scale (junk movers stop earning);
      - departure-from-rest credit (a diver leaves from standing);
      - appearance coherence counts ONLY for non-static components
        (self-coherent static junk no longer earns);
      - continuity, coverage, NULL and ending terms as weak evidence."""
    t = V7Q
    exc = feat["exc_y"]
    q = 0.0
    # shape: stable prep followed by substantial motion
    if feat["prep_dur_s"] >= 0.5 and exc >= t["shape_exc_sat"]:
        q += t["w_shape"]
    elif exc >= t["shape_exc_sat"]:
        q += 0.4 * t["w_shape"]
    if feat["rest_ratio"] is not None:
        q += t["w_rest"] * (1.0 - min(feat["rest_ratio"], t["rest_full"])
                            / t["rest_full"])
    q += t["w_continuity"] * max(0.0, 1.0 - feat["jumps"] / t["jumps_full"])
    q += t["w_coverage"] * min(1.0, feat["n_frames"] /
                               max(1, t["cov_full_frac"] * clip_n))
    q -= t["w_null"] * max(0.0, feat["null_frac"] - t["null_gate"]) / \
        max(1e-6, 1.0 - t["null_gate"])
    if feat["ends_early"]:
        q += t["w_ends_early"]
    if feat["entry"]:
        q += 0.6
    if feat["app_mean"] is not None and exc >= t["static_exc_gate"]:
        q += t["w_app"] * feat["app_mean"]
    if exc < t["static_exc_gate"] and feat["null_frac"] < 0.25 and \
            feat["life_frac"] > 0.85:
        q -= t["static_penalty"]
    if feat.get("life_s", 10 ** 9) < t["short_mover_life_s"] and \
            feat["peak_v_cy_s"] > 0.45:
        q -= t["short_mover_penalty"]
    if feat["start_frac"] > t["post_action_start"] and \
            exc < R5B.MOVER_EXCURSION_MIN:
        q -= t["post_action_penalty"]
    # velocity plausibility: a human track cannot teleport. Stitched
    # multi-member components show step velocities far beyond the frozen
    # R5 human-velocity ceiling; discount them physically.
    if feat["peak_v_cy_s"] > t["human_v_max_cy_s"]:
        pen = min(t["teleport_cap"],
                  math.log2(feat["peak_v_cy_s"] / t["human_v_max_cy_s"]))
        q -= t["w_teleport"] * max(0.0, pen)
    return round(q, 4)
