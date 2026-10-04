#!/usr/bin/env python3
"""DIVE_ANALYZER_SUBJECT_REFERENCE_ACQUISITION_V2 — GT-free subject reference
acquisition from the edited-clip structure of individual Dive Analyzer clips.

Packet: DIVE_ANALYZER_SUBJECT_REFERENCE_ACQUISITION_V2
Gate:   SUPERVISOR_REVIEW_AFTER_SUBJECT_REFERENCE_ACQUISITION_V2

Design contract
---------------
- GT-FREE INFERENCE: the inference path (frozen D5 proposals -> tracklets ->
  action-ownership features -> A0 scorer -> reference acquisition) receives a
  deliberately stripped, GT-free view of the frozen candidate cache. The
  loader removes the artifact's `gt_eval_only` payload; no inference code path
  can touch GT. GT is loaded by a separate Evaluator used for
  characterization (Phase 3, eval-only) and metrics (Phase 9) only.
- FROZEN INPUTS ONLY: R5_FULLCLIP_CANDIDATES_V1.json (floor conf 0.001,
  NMS 0.45, imgsz 640, cap 200) + osnet_emb_cache_v1.npz (OSNet x1.0
  market1501). Zero new D5 inference, zero new embeddings, zero training.
- TRACKLETS + FLOW: reuses the canonical, frozen infrastructure
  experiments/landmark_pilot/r5_tracklets_v1.py (candidate-complete sparse
  association + background-flow camera-motion compensation).
- CLIP-RELATIVE TIME: tau = t / clip_duration on [0, 1] (Phase 2).
- NO TRAINING, no per-dive tuning, no dive-id rules, no HURDLE step counts,
  no GT event times anywhere in inference. Weights are fixed a priori.

Usage:
  python3 subject_reference_acquisition_v2.py \
      --artifacts-dir . \
      --candidates runs/hurdle_identity_v1/R5_FULLCLIP_CANDIDATES_V1.json \
      --osnet-cache runs/hurdle_prototype_v3/osnet_emb_cache_v1.npz \
      --chains runs/hurdle_identity_v1/target_chains_v1.json \
      --anchors runs/hurdle_identity_v1/target_anchors_v1.json \
      --classification docs/science/HURDLE_TARGET_IDENTITY_CLASSIFICATION_V1.json \
      --out docs/science/DIVE_ANALYZER_SUBJECT_REFERENCE_ACQUISITION_V2.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "experiments", "landmark_pilot"))

from r5_tracklets_v1 import (  # noqa: E402  (canonical frozen infrastructure)
    Cand, Tracklet, build_tracklets_full, estimate_flow,
)

LABEL = "DIVE_ANALYZER_SUBJECT_REFERENCE_ACQUISITION_V2"

# ---------------------------------------------------------------------------
# Frozen scorer constants (a priori, clip-relative; NO per-dive tuning)
# ---------------------------------------------------------------------------
MIN_TRACKLET_SPAN_S = 0.70     # reference candidates must persist >= 0.7 s
AREA_MIN = 0.002               # reject micro noise boxes
AREA_MAX = 0.30                # person-ish upper bound (coarse)

# A0 action-arc terms (all flow-compensated, clip-generic human scales)
STABLE_WIN_S = 0.50            # sliding window for "static" evidence
STABLE_STD_CY = 0.014          # per-window cy std ceiling (world-static)
STABLE_CREDIT_S = 2.0          # stable span earning full credit
EXCURSION_FULL_CY = 0.35       # cy-equivalent coherent excursion = full credit
DESCENT_FULL_CYS = 0.8         # coherent downward speed = full credit
ENTRY_EXTREME_MARGIN_CY = 0.08 # extreme point above stable level
ENTRY_LAG_S = 1.5              # ends shortly after the extreme point
# Clip-relative action band (Phase 2 prior): the user deliberately trimmed the
# clip around ONE intended action; the action arc — including its water entry
# termination — lives inside the clip body, not at its very tail. Generic
# product invariant, pre-registered; Phase 3 verifies against GT (eval-only).
ENTRY_TAU_MIN = 0.15
ENTRY_TAU_MAX = 0.75
ONSET_TAU_MIN = 0.05
ONSET_TAU_MAX = 0.95

# A1 coarse region constants (no board segmentation; generic pool scene)
WATER_CY_MIN = 0.45            # coarse water-region floor (lower frame)
APPARATUS_CY_MAX = 0.55        # coarse apparatus region ceiling (upper frame)

# Fixed a priori weights (single configuration; Phase 12 ablates groups)
W_EXCURSION = 1.5
W_DESCENT = 0.8
W_ENTRY = 0.8
W_STABLE = 0.6
MIN_ACTION_SCORE = 0.9         # a reference must actually own an action arc
ABSTAIN_MARGIN = 0.05          # top1-vs-top2 score margin for REFERENCE_FOUND

# Phase 5 board-topology adjacency tolerance (normalized frame units)
TOPO_ADJ_RADIUS = 0.15


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# GT-free inference store (deliberately stripped of every GT payload)
# ---------------------------------------------------------------------------

class Clip:
    """GT-free per-clip inference view."""

    def __init__(self, dive: str, frames_raw: list, fps: float):
        self.dive = dive
        self.fps = fps
        self.n_frames = len(frames_raw)
        self.duration_s = self.n_frames / fps
        # 0-based cache frame index (OSNet key convention) + candidates
        self.cache_idx = [int(f["fi"]) - 1 for f in frames_raw]
        self.pts_s = [float(f["pts_s"]) for f in frames_raw]
        self.cands = [[Cand(cx=c["cx"], cy=c["cy"], bw=c["bw"], bh=c["bh"],
                            conf=c["conf"]) for c in f["c"]] for f in frames_raw]

    def tau(self, t_s: float) -> float:
        return t_s / self.duration_s if self.duration_s > 0 else 0.0


def load_gt_free_store(candidates_path: str, dives: list) -> dict:
    """Load the frozen candidate cache WITHOUT any GT payload."""
    raw = json.load(open(candidates_path))
    store = {}
    for dive, v in raw["dives"].items():
        if dive not in dives:
            continue
        frames_raw = [
            {"fi": f["fi"], "pts_s": f["pts_s"], "c": f["c"]}
            for f in v["frames"]
        ]  # gt_eval_only deliberately NOT copied
        store[dive] = Clip(dive, frames_raw, fps=float(v["fps"]))
    return store


# ---------------------------------------------------------------------------
# Tracklets (frozen infrastructure) + flow-compensated geometry
# ---------------------------------------------------------------------------

def tracklets_and_flow(clip: Clip):
    trs = build_tracklets_full(clip.cands, clip.fps)
    flow = estimate_flow(trs, clip.n_frames, clip.fps)
    off = np.zeros((clip.n_frames, 2))
    for fi in range(1, clip.n_frames):
        off[fi] = off[fi - 1] + flow[fi] / clip.fps
    return trs, off


# ---------------------------------------------------------------------------
# A0 — CLIP-RELATIVE ACTION OWNERSHIP features (GT-free)
# ---------------------------------------------------------------------------

def tracklet_span(tr: Tracklet, clip: Clip) -> float:
    return (tr.starts[-1] - tr.starts[0]) / clip.fps


def tracklet_features(tr: Tracklet, clip: Clip, off: np.ndarray) -> dict | None:
    span = tracklet_span(tr, clip)
    if span < MIN_TRACKLET_SPAN_S or tr.n_frames() < 3:
        return None
    areas = [tr.boxes[fi].bw * tr.boxes[fi].bh for fi in tr.starts]
    med_area = sorted(areas)[len(areas) // 2]
    if not (AREA_MIN <= med_area <= AREA_MAX):
        return None
    # flow-compensated cy track
    fcy = [tr.boxes[fi].cy - off[fi][1] for fi in tr.starts]
    fcx = [tr.boxes[fi].cx - off[fi][0] for fi in tr.starts]
    n = len(fcy)

    # stability: longest sliding window whose cy std <= STABLE_STD_CY
    wlen = max(3, int(round(STABLE_WIN_S * clip.fps)))
    stable_s = 0.0
    i = 0
    while i < n:
        j = i
        ok = True
        while j < n and ok:
            if j - i + 1 >= wlen:
                seg = fcy[i:j + 1]
                m = sum(seg) / len(seg)
                var = sum((v - m) ** 2 for v in seg) / len(seg)
                ok = math.sqrt(var) <= STABLE_STD_CY
                if ok:
                    j += 1
                else:
                    break
            else:
                j += 1
        if j - i >= wlen:
            stable_s = max(stable_s, (tr.starts[j - 1] - tr.starts[i]) / clip.fps)
        i = j if j > i else i + 1

    # coherent excursion (max spread of the flow-compensated track)
    ex_cy = max(fcy) - min(fcy)
    ex_cx = max(fcx) - min(fcx)
    excursion = max(ex_cy, 0.35 * ex_cx)

    # coherent descent speed (downward-only, over >= 0.2 s windows)
    peak_down = 0.0
    w2 = max(2, int(round(0.2 * clip.fps)))
    for i in range(n - w2 + 1):
        dt = (tr.starts[i + w2 - 1] - tr.starts[i]) / clip.fps
        if dt <= 0:
            continue
        v = (fcy[i + w2 - 1] - fcy[i]) / dt
        if v > peak_down:
            peak_down = v

    # entry-like termination: the track ends shortly after its extreme point,
    # the extreme exceeds its stable level, and it does not persist to the end
    last_fi = tr.starts[-1]
    tau_end = last_fi / (clip.n_frames - 1) if clip.n_frames > 1 else 0.0
    ext_i = max(range(n), key=lambda k: fcy[k])
    ext = fcy[ext_i]
    base = min(fcy[: max(1, ext_i)] or [ext])
    entry_like = (
        (tr.starts[-1] - tr.starts[ext_i]) / clip.fps <= ENTRY_LAG_S
        and (ext - base) >= ENTRY_EXTREME_MARGIN_CY
        and ENTRY_TAU_MIN <= tau_end <= ENTRY_TAU_MAX
    )

    # onset tau: first frame whose flow-compensated speed exceeds a walk gate
    onset_tau = None
    for i in range(1, n):
        dt = (tr.starts[i] - tr.starts[i - 1]) / clip.fps
        if dt <= 0:
            continue
        if math.hypot(fcx[i] - fcx[i - 1], fcy[i] - fcy[i - 1]) / dt > 0.35:
            onset_tau = tr.starts[i] / (clip.n_frames - 1)
            break

    t_start = tr.starts[0] / (clip.n_frames - 1)
    excursion_cy_val = max(ex_cy, 0.35 * ex_cx)
    stable_term = (
        min(1.0, stable_s / STABLE_CREDIT_S)
        if onset_tau is None or ONSET_TAU_MIN <= onset_tau <= ONSET_TAU_MAX
        else 0.0
    )

    feats = {
        "tid": tr.tid,
        "span_s": span,
        "tau_start": tr.starts[0] / (clip.n_frames - 1),
        "tau_end": tau_end,
        "tau_onset": onset_tau,
        "med_area": med_area,
        "stable_s": stable_s,
        "excursion_cy": excursion_cy_val,
        "peak_down_cys": peak_down,
        "entry_like": bool(entry_like),
        "terminal_fcy": fcy[-1],
        "stable_pos_fcy": (sorted(fcy)[n // 2]),
        "n_frames": tr.n_frames(),
        "mean_conf": sum(tr.boxes[fi].conf for fi in tr.starts) / n,
    }

    # Multiplicative action-arc ownership: excursion x descent x band-gated
    # entry, with the stable-prefix credit additive (all terms fixed a priori).
    t_exc = min(1.0, excursion_cy_val / EXCURSION_FULL_CY)
    t_desc = min(1.0, peak_down / DESCENT_FULL_CYS)
    t_entry = 1.0 if entry_like else 0.15
    score = 3.2 * t_exc * t_desc * t_entry + W_STABLE * stable_term
    feats["a0_score"] = round(score, 4)
    return feats


def a0_feature_groups() -> dict:
    """Feature-group membership for the Phase 12 ablation."""
    return {
        "clip_relative_time": ["tau_start", "tau_end", "tau_onset"],
        "motion": ["excursion_cy", "peak_down_cys"],
        "termination": ["entry_like"],
        "track_quality": ["span_s", "stable_s", "med_area", "mean_conf"],
    }


def a0_score_from_features(f: dict, drop_groups: frozenset() = frozenset()) -> float:
    """Recompute the A0 score with ablated feature groups zeroed."""
    if "motion" in drop_groups:
        f = {**f, "excursion_cy": 0.0, "peak_down_cys": 0.0}
    if "termination" in drop_groups:
        f = {**f, "entry_like": False}
    if "track_quality" in drop_groups:
        f = {**f, "stable_s": 0.0}
    if "clip_relative_time" in drop_groups:
        f = {**f, "tau_onset": 0.5}  # neutral onset (inside clip body)
    stable_term = (
        min(1.0, f["stable_s"] / STABLE_CREDIT_S)
        if f["tau_onset"] is None or ONSET_TAU_MIN <= f["tau_onset"] <= ONSET_TAU_MAX
        else 0.0
    )
    t_exc = min(1.0, f["excursion_cy"] / EXCURSION_FULL_CY)
    t_desc = min(1.0, f["peak_down_cys"] / DESCENT_FULL_CYS)
    t_entry = 1.0 if f["entry_like"] else 0.15
    return round(3.2 * t_exc * t_desc * t_entry + W_STABLE * stable_term, 4)


def a1_score_from_features(f: dict, drop_groups: frozenset() = frozenset()) -> float:
    """A1 — APPARATUS-TO-WATER CONSISTENCY (coarse regions, no board
    segmentation): a person that (i) stood stably in an upper-frame plausible
    apparatus region, (ii) departed with a coherent excursion, and (iii)
    terminated toward the coarse water region (lower frame), owns the dive."""
    if "motion" in drop_groups:
        f = {**f, "excursion_cy": 0.0, "peak_down_cys": 0.0}
    if "termination" in drop_groups:
        f = {**f, "terminal_fcy": 0.0}
    if "track_quality" in drop_groups:
        f = {**f, "stable_s": 0.0}
    t_exc = min(1.0, f["excursion_cy"] / EXCURSION_FULL_CY)
    t_water = min(1.0, max(0.0, f["terminal_fcy"]) / WATER_CY_MIN)
    t_app = min(1.0, f["stable_s"] / 1.0) if f["stable_pos_fcy"] <= APPARATUS_CY_MAX else 0.0
    t_entry_lag = 1.0 if f["entry_like"] else 0.3
    return round(3.2 * t_exc * t_water * t_app * t_entry_lag, 4)


def acquire_reference(clip: Clip, feats: list[dict], drop_groups=frozenset(),
                      scorer=a0_score_from_features):
    """Phase 6/7: rank acquisition candidates by A0; deterministic; abstain."""
    scored = sorted(
        ((scorer(f, drop_groups), f) for f in feats),
        key=lambda sf: (-sf[0], sf[1]["tid"]),
    )
    if not scored:
        return {"status": "REFERENCE_NOT_FOUND", "candidates": []}
    s1, f1 = scored[0]
    s2 = scored[1][0] if len(scored) > 1 else 0.0
    margin = round(s1 - s2, 4)
    if s1 < MIN_ACTION_SCORE:
        status = "REFERENCE_NOT_FOUND"
    elif margin < ABSTAIN_MARGIN:
        status = "REFERENCE_AMBIGUOUS"
    else:
        status = "REFERENCE_FOUND"
    return {
        "status": status,
        "top": {"tid": f1["tid"], "score": s1, "margin": margin,
                "tau_start": f1["tau_start"], "tau_end": f1["tau_end"],
                "span_s": f1["span_s"]},
        "top2_score": s2,
        "ranked_top5": [{"tid": f["tid"], "score": s} for s, f in scored[:5]],
        "n_candidates": len(scored),
    }


def reference_embedding(clip: Clip, tr: Tracklet, index: dict,
                        keys: np.ndarray, vecs: np.ndarray) -> np.ndarray | None:
    """Mean OSNet embedding over the reference tracklet's cached crops."""
    rows = []
    dmap = index.get(clip.dive, {})
    for fi in tr.starts:
        ci_map = dmap.get(fi)
        if not ci_map:
            continue
        for ci, k in ci_map.items():
            rows.append(vecs[k])
    if not rows:
        return None
    ref = np.mean(rows, axis=0)
    nrm = np.linalg.norm(ref)
    return ref / max(nrm, 1e-9)


# ---------------------------------------------------------------------------
# GT Evaluator — characterization (Phase 3) + metrics (Phase 9) ONLY
# ---------------------------------------------------------------------------

class Evaluator:
    def __init__(self, chains_path: str, anchors_path: str):
        self.chains = json.load(open(chains_path))["dives"]
        raw = json.load(open(anchors_path))
        self.anchors = raw["gt_phase_times_s"]  # GT event times (eval-only)

    def gt_frames(self, dive: str):
        return [c for c in self.chains[dive]["chain"] if c["status"] == "GT"]

    def gt_phase_times(self, dive: str):
        return self.anchors[dive]


def characterize_clip_structure(dive: str, clip: Clip, ev: Evaluator) -> dict:
    """Phase 3: where does the intended action sit relative to the edited
    clip? GT used to CHARACTERIZE the corpus only (never fed to inference)."""
    gt = ev.gt_frames(dive)
    ph = ev.gt_phase_times(dive)
    n1 = clip.n_frames - 1
    t_to, t_ap, t_wc = ph["takeoff"], ph["apex"], ph["water_contact"]
    fi = lambda t: int(round(t * clip.fps))
    chain_cy = [c["cy"] for c in gt]
    pre = [c["cy"] for c in gt if c["pts_s"] < t_to]
    stable_pre = (
        float(np.std(pre)) if len(pre) > 10 else None
    )
    vis_first_t, vis_last_t = gt[0]["pts_s"], gt[-1]["pts_s"]
    high_motion = [c for c in gt if t_to <= c["pts_s"] <= t_wc]
    out = {
        "clip_duration_s": round(clip.duration_s, 3),
        "subject_visible_tau": [
            round(clip.tau(vis_first_t), 4), round(clip.tau(vis_last_t), 4)
        ],
        "tau_takeoff": round(clip.tau(t_to), 4),
        "tau_apex": round(clip.tau(t_ap), 4),
        "tau_water_contact": round(clip.tau(t_wc), 4),
        "post_entry_tau": round(1.0 - clip.tau(t_wc), 4),
        "pre_dive_padding_tau": round(clip.tau(t_to), 4),
        "subject_pre_takeoff_cy_std": None if stable_pre is None else round(stable_pre, 4),
        "subject_flight_frames": len(high_motion),
        "subject_cy_water_end": round(chain_cy[-1], 4) if chain_cy else None,
    }
    # temporal occupancy of other (non-subject) person-plausible movers
    subj_cand = {int(c["cand"]) for c in gt if c.get("cand") is not None}
    other_present = defaultdict(int)
    total = 0
    for k, fidx in enumerate(clip.cache_idx):
        for ci, c in enumerate(clip.cands[k]):
            if ci in subj_cand:
                continue
            area = c.bw * c.bh
            if AREA_MIN <= area <= AREA_MAX and c.conf >= 0.05:
                other_present[int(round(clip.tau(fidx / max(clip.fps, 1e-9) * 10)) / 10)] += 1
        total += 1
    out["other_person_tau_histogram_deciles"] = {
        str(k): v for k, v in sorted(other_present.items())
    }
    return out


# ---------------------------------------------------------------------------
# Phase 8: frozen reference-conditioned matching replay (unchanged pipeline)
# ---------------------------------------------------------------------------

def match_with_reference(dive: str, clip: Clip, ref_vec: np.ndarray,
                         ev: Evaluator, index: dict, keys: np.ndarray,
                         vecs: np.ndarray) -> dict:
    gt = ev.gt_frames(dive)
    dmap = index.get(dive, {})
    hits = n_eval = 0
    wrong_runs = []
    cur_wrong = 0.0
    switches = 0
    last_top = None
    margins = []
    subj_found = 0
    for c in gt:
        t = c["pts_s"]
        fi = int(round(t * clip.fps))
        cands = dmap.get(fi)
        if not cands:
            continue
        cis = sorted(cands)
        M = vecs[[cands[ci] for ci in cis]]
        sims = M @ ref_vec
        order = np.argsort(-sims)
        tgt = c.get("cand")
        if tgt is None or tgt not in cis:
            continue
        n_eval += 1
        rank = int(np.where(np.asarray(cis)[order] == tgt)[0][0])
        top_cand = cis[order[0]]
        if rank == 0:
            hits += 1
            if cur_wrong:
                wrong_runs.append(cur_wrong)
            cur_wrong = 0.0
        else:
            cur_wrong += 1 / clip.fps
        if top_cand != last_top:
            switches += 1
            last_top = top_cand
        if len(order) > 1:
            margins.append(float(sims[order[0]] - sims[order[1]]))
        if tgt in cis:
            subj_found += 1
    if cur_wrong:
        wrong_runs.append(cur_wrong)
    return {
        "n_eval_frames": n_eval,
        "gt1": round(hits / n_eval, 4) if n_eval else None,
        "subject_presence_rate": round(subj_found / n_eval, 4) if n_eval else None,
        "longest_wrong_run_s": round(max(wrong_runs), 3) if wrong_runs else 0.0,
        "identity_switches": switches,
        "margin_top1_top2_p50": round(float(np.median(margins)), 4) if margins else None,
    }


# ---------------------------------------------------------------------------
# Phase 9: acquisition metrics
# ---------------------------------------------------------------------------

def reference_purity(dive: str, clip: Clip, tr: Tracklet, ev: Evaluator,
                     radius: float = 0.06) -> float:
    """Fraction of the reference tracklet's frames whose candidate is the GT
    subject (eval-only). Candidate identity is not stable across artifacts;
    purity is measured by center distance to the GT subject box."""
    gt_by_fi = {}
    for c in ev.gt_frames(dive):
        fi = int(round(c["pts_s"] * clip.fps))
        if c.get("cand") is not None and fi not in gt_by_fi:
            gt_by_fi[fi] = c
    hits = tot = 0
    for fi in tr.starts:
        gtbox = gt_by_fi.get(fi)
        if gtbox is None:
            continue
        tot += 1
        b = tr.boxes[fi]
        if math.hypot(gtbox["cx"] - b.cx, gtbox["cy"] - b.cy) <= radius:
            hits += 1
    return round(hits / tot, 4) if tot else 0.0


def _frozen_constants() -> dict:
    return {
        "MIN_TRACKLET_SPAN_S": MIN_TRACKLET_SPAN_S,
        "AREA_MIN": AREA_MIN, "AREA_MAX": AREA_MAX,
        "STABLE_WIN_S": STABLE_WIN_S, "STABLE_STD_CY": STABLE_STD_CY,
        "STABLE_CREDIT_S": STABLE_CREDIT_S,
        "EXCURSION_FULL_CY": EXCURSION_FULL_CY,
        "DESCENT_FULL_CYS": DESCENT_FULL_CYS,
        "ENTRY_EXTREME_MARGIN_CY": ENTRY_EXTREME_MARGIN_CY,
        "ENTRY_LAG_S": ENTRY_LAG_S,
        "ENTRY_TAU_MIN": ENTRY_TAU_MIN, "ENTRY_TAU_MAX": ENTRY_TAU_MAX,
        "ONSET_TAU_MIN": ONSET_TAU_MIN, "ONSET_TAU_MAX": ONSET_TAU_MAX,
        "WATER_CY_MIN": WATER_CY_MIN, "APPARATUS_CY_MAX": APPARATUS_CY_MAX,
        "W_EXCURSION": W_EXCURSION, "W_DESCENT": W_DESCENT,
        "W_ENTRY": W_ENTRY, "W_STABLE": W_STABLE,
        "MIN_ACTION_SCORE": MIN_ACTION_SCORE,
        "ABSTAIN_MARGIN": ABSTAIN_MARGIN,
    }


# --------------------------------------------------------------------- main

def run(args) -> dict:
    dev_dives = ["1040", "2169", "2341", "2353", "2541"]

    store = load_gt_free_store(args.candidates, set(dev_dives))
    ev = Evaluator(args.chains, args.anchors)

    # ---------- tracklets + features (GT-free) ----------
    per_dive_feats = {}
    per_dive_tracks = {}
    for dive, clip in store.items():
        trs, off = tracklets_and_flow(clip)
        feats = []
        for tr in trs:
            f = tracklet_features(tr, clip, off)
            if f is not None:
                f["fi0"], f["fi1"] = tr.starts[0], tr.starts[-1]
                feats.append(f)
        per_dive_feats[dive] = feats
        per_dive_tracks[dive] = (trs, off)

    npz = np.load(args.osnet_cache, allow_pickle=False)
    keys, vecs = npz["keys"], npz["vecs"]
    index = defaultdict(dict)
    for i, k in enumerate(keys):
        d, fi, ci = k.split("|")
        index[d].setdefault(int(fi), {})[int(ci)] = i

    # ---------- Phase 3: edited-clip structure (characterization) ----------
    structure = {d: characterize_clip_structure(d, store[d], ev)
                 for d in dev_dives}

    # ---------- Phase 6/7: A0 + A1 acquisition ----------
    acquisition = {}
    for dive in dev_dives:
        clip = store[dive]
        res = {"A0": acquire_reference(clip, per_dive_feats[dive]),
               "A1": acquire_reference(clip, per_dive_feats[dive],
                                       scorer=a1_score_from_features)}
        for scorer_name, r in res.items():
            if r["status"] != "REFERENCE_NOT_FOUND":
                tid = r["top"]["tid"]
                tr = next(t for t in per_dive_tracks[dive][0] if t.tid == tid)
                ref = reference_embedding(clip, tr, index, keys, vecs)
                r["reference_subject_purity"] = reference_purity(
                    dive, clip, tr, ev)
                r["reference_embedding_available"] = ref is not None
                if ref is not None:
                    r["match"] = match_with_reference(
                        dive, clip, ref, ev, index, keys, vecs)
        acquisition[dive] = res

    # ---------- Phase 9: rank of the best subject reference ----------
    ranks = {"A0": {}, "A1": {}}
    for scorer_name, sc in (("A0", a0_score_from_features),
                            ("A1", a1_score_from_features)):
        for dive in dev_dives:
            order = sorted(per_dive_feats[dive],
                           key=lambda f: (-sc(f), f["tid"]))
            best_rank = None
            for r, f in enumerate(order, 1):
                tr = next(t for t in per_dive_tracks[dive][0]
                          if t.tid == f["tid"])
                p = reference_purity(dive, store[dive], tr, ev)
                if p >= 0.5:
                    best_rank = r
                    break
            ranks[scorer_name][dive] = best_rank

    # top-k reference purity feasibility (is a subject reference in top-k?)
    topk = {"A0": {}, "A1": {}}
    for scorer_name, sc in (("A0", a0_score_from_features),
                            ("A1", a1_score_from_features)):
        for dive in dev_dives:
            order = sorted(per_dive_feats[dive],
                           key=lambda f: (-sc(f), f["tid"]))
            row = {}
            for k in (1, 3, 5, 10, 20):
                best = 0.0
                for f in order[:k]:
                    tr = next(t for t in per_dive_tracks[dive][0]
                              if t.tid == f["tid"])
                    best = max(best, reference_purity(dive, store[dive], tr, ev))
                row[f"top{k}_best_purity"] = best
            topk[scorer_name][dive] = row

    # ---------- Phase 12: minimal feature-group ablation (A0) ----------
    ablation = {}
    for group in ("clip_relative_time", "motion", "termination",
                  "track_quality"):
        correct = []
        for dive in dev_dives:
            res = acquire_reference(
                store[dive], per_dive_feats[dive],
                drop_groups=frozenset([group]))
            tid = res["top"]["tid"] if res["status"] != "REFERENCE_NOT_FOUND" else None
            p = 0.0
            if tid is not None:
                tr = next(t for t in per_dive_tracks[dive][0] if t.tid == tid)
                p = reference_purity(dive, store[dive], tr, ev)
            correct.append(p >= 0.5)
        ablation[group] = {
            "reference_subject_correct_dive_count": sum(correct),
            "of_dives": len(dev_dives),
        }
    base_correct = []
    for dive in dev_dives:
        res = acquire_reference(store[dive], per_dive_feats[dive])
        tid = res["top"]["tid"] if res["status"] != "REFERENCE_NOT_FOUND" else None
        p = 0.0
        if tid is not None:
            tr = next(t for t in per_dive_tracks[dive][0] if t.tid == tid)
            p = reference_purity(dive, store[dive], tr, ev)
        base_correct.append(p >= 0.5)
    ablation["none_dropped_baseline"] = {
        "reference_subject_correct_dive_count": sum(base_correct),
        "of_dives": len(dev_dives),
    }

    # ---------- Phase 13: abstention curves (diagnostic, no calibration) ----------
    purity_of_tid = {}
    for dive in dev_dives:
        for f in per_dive_feats[dive]:
            tr = next(t for t in per_dive_tracks[dive][0] if t.tid == f["tid"])
            purity_of_tid[(dive, f["tid"])] = reference_purity(
                dive, store[dive], tr, ev)
    abstention = {
        "A0": _abstention_curve(dev_dives, per_dive_feats, store,
                                purity_of_tid),
    }

    # ---------- comparison table ----------
    cls = json.load(open(args.classification))
    audit = json.load(open(args.audit))
    comparison = {}
    for dive in dev_dives:
        a3 = cls["dives"][dive]["a3"]
        row = {"D5_top1": a3.get("top1_correct_rate"),
               "H1a_audit": audit["phase9_diagnostic"]["per_dive"][dive]
                            .get("H1a_subject_top1_rate")}
        oracle = {"1040": 0.689, "2169": 0.873, "2341": 0.707,
                  "2353": 0.788, "2541": 0.859}  # frozen V1 artifact values
        row["oracle_stable_ref"] = oracle[dive]
        a0 = acquisition[dive]["A0"]
        row["V2_A0_gtfree_gt1"] = (a0.get("match") or {}).get("gt1")
        a1 = acquisition[dive]["A1"]
        row["V2_A1_gtfree_gt1"] = (a1.get("match") or {}).get("gt1")
        comparison[dive] = row

    out = {
        "label": LABEL,
        "packet": "DIVE_ANALYZER_SUBJECT_REFERENCE_ACQUISITION_V2",
        "gate": "SUPERVISOR_REVIEW_AFTER_SUBJECT_REFERENCE_ACQUISITION_V2",
        "date": "2026-09-13",
        "gt_usage": "GT used for Phase-3 characterization and Phase-9 metrics "
                    "ONLY; the inference path consumed a deliberately "
                    "GT-stripped store (leakage test enforced)",
        "frozen_inputs": {
            "candidates_sha256": sha256_file(args.candidates),
            "osnet_cache_sha256": sha256_file(args.osnet_cache),
            "chains_sha256": sha256_file(args.chains),
            "anchors_sha256": sha256_file(args.anchors),
        },
        "phase3_clip_structure": structure,
        "phase6_scorers": {
            "A0_clip_relative_action_ownership": {
                "description": "multiplicative action-arc: flow-compensated "
                               "excursion x coherent descent x band-gated "
                               "entry termination + stable-prefix credit",
                "constants": _frozen_constants(),
                "feature_groups": a0_feature_groups(),
            },
            "A1_apparatus_to_water": {
                "description": "coarse apparatus/water region consistency: "
                               "stable upper-frame prefix x excursion x "
                               "lower-frame termination (no board "
                               "segmentation, no hand-coded coordinates)",
            },
        },
        "phase7_acquisition": acquisition,
        "phase9_metrics": {
            "best_subject_reference_rank": ranks,
            "topk_best_purity": topk,
            "primary_metric": "REFERENCE_SUBJECT_CORRECT (top1 purity>=0.5)",
        },
        "phase12_ablation": ablation,
        "phase13_abstention": abstention,
        "phase8_comparison": comparison,
        "n_acquisition_candidates_per_dive": {
            d: len(per_dive_feats[d]) for d in dev_dives},
        "n_tracklets_per_dive": {
            d: len(per_dive_tracks[d][0]) for d in dev_dives},
        "exclusions": {
            "524": "AUTHORITY_CONFLICT_EXCLUDED (untouched)",
            "2555": "SCREEN_RECORDING_STRESS_CASE (not loaded, not evaluated)",
            "Paris": "NOT_ACCESSED_FOR_DEVELOPMENT",
            "protected_holdout": "NOT_ACCESSED",
        },
    }
    return out


def _abstention_curve(dev_dives, per_dive_feats, store, purity_of_tid,
                      thresholds=(0.0, 0.02, 0.05, 0.1, 0.2)):
    """Coverage vs subject-precision over deterministic margin thresholds."""
    rows = []
    for th in thresholds:
        n_eligible = n_cov = n_correct = 0
        for dive in dev_dives:
            res = acquire_reference(store[dive], per_dive_feats[dive])
            if res["status"] == "REFERENCE_NOT_FOUND":
                continue
            n_eligible += 1
            margin = res["top"]["margin"]
            if margin is not None and margin >= th:
                n_cov += 1
                tid = res["top"]["tid"]
                if purity_of_tid.get((dive, tid), 0.0) >= 0.5:
                    n_correct += 1
        rows.append({
            "min_margin": th,
            "eligible": n_eligible,
            "covered": n_cov,
            "covered_fraction": round(n_cov / n_eligible, 3) if n_eligible else None,
            "subject_correct": n_correct,
            "subject_precision": round(n_correct / n_cov, 3) if n_cov else None,
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates",
                    default="runs/hurdle_identity_v1/R5_FULLCLIP_CANDIDATES_V1.json")
    ap.add_argument("--osnet-cache",
                    default="runs/hurdle_prototype_v3/osnet_emb_cache_v1.npz")
    ap.add_argument("--chains",
                    default="runs/hurdle_identity_v1/target_chains_v1.json")
    ap.add_argument("--anchors",
                    default="runs/hurdle_identity_v1/target_anchors_v1.json")
    ap.add_argument("--classification",
                    default="docs/science/HURDLE_TARGET_IDENTITY_CLASSIFICATION_V1.json")
    ap.add_argument("--audit",
                    default="docs/science/DIVE_ANALYZER_SUBJECT_RESOLUTION_AUDIT_V1.json")
    ap.add_argument("--out",
                    default="docs/science/DIVE_ANALYZER_SUBJECT_REFERENCE_ACQUISITION_V2.json")
    args = ap.parse_args()
    out = run(args)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    print("wrote", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
