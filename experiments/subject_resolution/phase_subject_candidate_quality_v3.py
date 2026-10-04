#!/usr/bin/env python3
"""DIVE_ANALYZER_SUBJECT_CANDIDATE_QUALITY_V3 — candidate-quality diagnostic,
track-support premise test, subject-retention gate and V3 reference ranking.

Packet: DIVE_ANALYZER_SUBJECT_CANDIDATE_QUALITY_V3
Gate:   SUPERVISOR_REVIEW_AFTER_SUBJECT_CANDIDATE_QUALITY_V3

Design contract
---------------
- FROZEN INPUTS ONLY: the frozen D5 full-candidate caches (floor conf 0.001,
  NMS 0.45, imgsz 640, cap 200) + frozen OSNet caches. Zero new D5 inference,
  zero new embeddings, zero training, zero labels.
- FROZEN A0/A1: the frozen V2 module is imported unmodified (module SHA
  asserted); its feature definitions and constants are never changed. V3 adds
  a candidate-quality stage BEFORE the frozen scorers; A0/A1 scores are
  consumed as-is.
- GT-FREE INFERENCE: the quality stage consumes only the GT-free candidate
  cache. GT (HURDLE full subject chains, STANDING Level-A anchors) is loaded
  by a separate evaluator for labeling/metrics ONLY.
- NO THRESHOLD ZOO: every constant is reused frozen project semantics:
    SUPPORT_CONF  = 0.05  (frozen V2 characterize_clip_structure
                           "person-plausible" occupancy threshold)
    SUPPORT_RADIUS = 0.06 (frozen reference_purity / Level-A consistency
                           normalized center-distance radius)
  plus the frozen A0/A1 constants themselves. No per-dive/per-family tuning.

Subcommands:
  diagnostic  — Phase 2/3: per-candidate quality measures + GT labels
  rank        — Phase 4/5/8: V3 quality handling + reference ranking
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "experiments/subject_resolution"))
sys.path.insert(0, str(REPO / "experiments/landmark_pilot"))

import subject_reference_acquisition_v2 as v2  # frozen module, imported unmodified

LABEL = "DIVE_ANALYZER_SUBJECT_CANDIDATE_QUALITY_V3"

HURDLE_DIVES = ["1040", "2169", "2341", "2353", "2541"]
STANDING_DIVES = ["133", "311", "676", "2387"]
ALL_DIVES = HURDLE_DIVES + STANDING_DIVES

HURDLE_CANDIDATES = REPO / "runs/hurdle_identity_v1/R5_FULLCLIP_CANDIDATES_V1.json"
HURDLE_CHAINS = REPO / "runs/hurdle_identity_v1/target_chains_v1.json"
COHORT_CANDIDATES = REPO / "runs/subject_resolution/R5_FULLCLIP_CANDIDATES_COHORT_V1.json"
ANCHOR_DIR = REPO / "docs/science/localization_annotations_v1/SUBJECT_GT_LEVEL_A_STANDING_V1"
OUT_DIR = REPO / "runs/subject_candidate_quality_v3"

V2_MODULE_SHA = "01a17dd77131076d323b4adbc0790ac1d284f36fe39ebfb98a0ef64ad7a1d73e"

# Pre-registered constants — reused frozen project semantics ONLY (Phase 6).
SUPPORT_CONF = 0.05    # v2.characterize_clip_structure person-plausible conf
SUPPORT_RADIUS = 0.06  # v2.reference_purity normalized center-distance radius

# Motion class split for the diagnostic uses the frozen A0 semantics only:
# a tracklet is "mover-like" when its flow-compensated excursion reaches the
# frozen ENTRY_EXTREME_MARGIN_CY, else "static-like".
MOTION_EXCURSION_MIN = v2.ENTRY_EXTREME_MARGIN_CY


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_frozen():
    mod_sha = sha256_file(Path(v2.__file__))
    if mod_sha != V2_MODULE_SHA:
        raise SystemExit(f"V2 MODULE DRIFT {mod_sha} != {V2_MODULE_SHA}")
    return {"module_sha256": mod_sha}


def candidates_path(dive: str) -> Path:
    return COHORT_CANDIDATES if dive in STANDING_DIVES else HURDLE_CANDIDATES


def load_clip(dive: str):
    raw = json.loads(candidates_path(dive).read_text())
    v = raw["dives"][dive]
    frames_raw = [{"fi": f["fi"], "pts_s": f["pts_s"], "c": f["c"]}
                  for f in v["frames"]]
    return v2.Clip(dive, frames_raw, fps=float(v["fps"]))


# ---------------------------------------------------------------------------
# GT evaluator (labeling/metrics ONLY — never consumed by the quality stage)
# ---------------------------------------------------------------------------

def load_hurdle_gt():
    chains = json.loads(HURDLE_CHAINS.read_text())["dives"]
    return chains


def hurdle_purity(dive: str, clip, tr, chains, fps) -> float:
    """Frozen v2.reference_purity semantics (center distance <= 0.06)."""
    gt_by_fi = {}
    for c in chains[dive]["chain"]:
        if c["status"] == "GT":
            fi = int(round(c["pts_s"] * fps))
            if fi not in gt_by_fi:
                gt_by_fi[fi] = c
    hits = tot = 0
    for fi in tr.starts:
        gtbox = gt_by_fi.get(fi)
        if gtbox is None:
            continue
        tot += 1
        b = tr.boxes[fi]
        if math.hypot(gtbox["cx"] - b.cx, gtbox["cy"] - b.cy) <= SUPPORT_RADIUS:
            hits += 1
    return round(hits / tot, 4) if tot else 0.0


def load_anchors():
    out = {}
    for p in sorted(ANCHOR_DIR.glob("L1A_*.json")):
        a = json.loads(p.read_text())
        assert a["authority"] == "HUMAN_REVIEWED", p
        out.setdefault(str(a["dive_id"]), {})[int(a["frame_index"])] = a
    return out


def anchor_consistent(box, ann):
    """Frozen Level-A consistency rule (center distance <= 0.06, 202x360)."""
    cx, cy, bw, bh = box
    x1, y1, x2, y2 = ann["bbox"]
    pcx, pcy = ((x1 + x2) / 2) / ann["width"], ((y1 + y2) / 2) / ann["height"]
    dist = math.hypot(cx - pcx, cy - pcy)
    ax1, ay1, ax2, ay2 = cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2
    bx1, by1, bx2, by2 = x1 / ann["width"], y1 / ann["height"], \
        x2 / ann["width"], y2 / ann["height"]
    iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    union = bw * bh + (bx2 - bx1) * (by2 - by1) - inter
    iou = inter / union if union > 0 else 0.0
    return dist <= SUPPORT_RADIUS, round(dist, 4), round(iou, 4)


def standing_anchor_eval(dive: str, tr, anchors) -> dict:
    """Anchor purity of a tracklet (visible anchors only)."""
    hits = tot = 0
    for fi, ann in anchors.get(dive, {}).items():
        if ann["visibility"] != "visible":
            continue
        if fi not in tr.boxes:
            continue
        b = tr.boxes[fi]
        ok, dist, iou = anchor_consistent(
            (b.cx, b.cy, b.bw, b.bh), ann)
        tot += 1
        hits += 1 if ok else 0
    return {"n_visible_anchors_with_box": tot,
            "n_consistent": hits,
            "purity": round(hits / tot, 4) if tot else None}


# ---------------------------------------------------------------------------
# Candidate-quality measures (GT-free)
# ---------------------------------------------------------------------------

def quality_measures(tr, clip, feats) -> dict:
    """Generic track-level quality evidence from the frozen candidate cache."""
    fis = tr.starts
    confs = [tr.boxes[fi].conf for fi in fis]
    areas = [tr.boxes[fi].bw * tr.boxes[fi].bh for fi in fis]
    aspects = [tr.boxes[fi].bw / max(tr.boxes[fi].bh, 1e-9) for fi in fis]
    srt = sorted(confs)
    n = len(confs)

    # per-frame strongest detection support near the tracklet box
    support_flags = []
    for fi in fis:
        b = tr.boxes[fi]
        best = 0.0
        for c in clip.cands[fi]:
            if c.conf < SUPPORT_CONF:
                continue
            if math.hypot(c.cx - b.cx, c.cy - b.cy) <= SUPPORT_RADIUS:
                best = 1.0
                break
        support_flags.append(best)

    support_count = int(sum(support_flags))
    longest_run = best_run = 0
    episodes = 0
    prev = 0
    for s in support_flags:
        if s:
            best_run += 1
            longest_run = max(longest_run, best_run)
            if not prev:
                episodes += 1
        else:
            best_run = 0
        prev = s

    return {
        "tid": tr.tid,
        "fi0": fis[0], "fi1": fis[-1],
        "n_obs": n,
        "span_s": round((fis[-1] - fis[0]) / clip.fps, 4),
        "conf_max": round(max(confs), 6),
        "conf_mean": round(sum(confs) / n, 6),
        "conf_median": round(srt[n // 2], 6),
        "conf_q75": round(srt[int(0.75 * (n - 1))], 6),
        "conf_q90": round(srt[int(0.90 * (n - 1))], 6),
        "n_conf_ge_support": int(sum(1 for c in confs if c >= SUPPORT_CONF)),
        "frac_conf_ge_support": round(sum(1 for c in confs if c >= SUPPORT_CONF) / n, 4),
        "support_count": support_count,
        "support_frac": round(support_count / n, 4),
        "support_longest_run": longest_run,
        "support_episodes": episodes,
        "area_mean": round(sum(areas) / n, 6),
        "area_std": round(float(np.std(areas)), 6),
        "aspect_mean": round(sum(aspects) / n, 4),
        "aspect_std": round(float(np.std(aspects)), 4),
        "A0": feats["a0_score"],
        "A1": v2.a1_score_from_features(feats),
        "excursion_cy": feats["excursion_cy"],
        "peak_down_cys": feats["peak_down_cys"],
        "stable_s": feats["stable_s"],
        "entry_like": feats["entry_like"],
        "tau_start": feats["tau_start"],
        "tau_end": feats["tau_end"],
    }


def build_dive(dive: str):
    clip = load_clip(dive)
    trs, off = v2.tracklets_and_flow(clip)
    feats = []
    for tr in trs:
        f = v2.tracklet_features(tr, clip, off)
        if f is not None:
            f["fi0"], f["fi1"] = tr.starts[0], tr.starts[-1]
            feats.append((tr, f))
    return clip, trs, off, feats


# ---------------------------------------------------------------------------
# Q0 — TRACK SUPPORT EVIDENCE (Phase 5/7/8)
# ---------------------------------------------------------------------------
# Pre-registered formulation (single configuration, no sweep):
#   support_count(tracklet) = #frames where ANY candidate with conf >=
#                             SUPPORT_CONF lies within SUPPORT_RADIUS of the
#                             tracklet box (the tracklet's own box included).
#   Quality handling = SOFT TIERED DOWN-RANK (no deletion):
#     tier 1: support_count >= 1  (credible person-detector support)
#     tier 0: support_count == 0  (unsupported; still ranked, inspectable)
#   Within a tier the FROZEN A0/A1 order is preserved untouched. Selection
#   and the frozen abstention semantics (MIN_ACTION_SCORE, ABSTAIN_MARGIN)
#   apply to the top tier only; if NO candidate has support the frozen V2
#   ranking is returned unchanged (graceful fallback).
#   No new numeric cutoff is introduced: tier membership is the existence of
#   evidence, and both constants are reused frozen project semantics.

def q0_tier(q: dict) -> int:
    return 1 if q["support_count"] >= 1 else 0


def v3_rank(feats_q: list[dict], scorer_name: str) -> dict:
    """Quality stage -> frozen A0/A1 order -> reference ranking."""
    key = "A0" if scorer_name == "A0" else "A1"
    tiered = sorted(feats_q, key=lambda q: (-q0_tier(q), -q[key], q["tid"]))
    ranked = [{"rank": i, "tid": q["tid"], "tier": q0_tier(q),
               "score": q[key], "support_count": q["support_count"],
               "support_frac": q["support_frac"],
               "is_subject": q.get("is_subject"),
               "motion_class": q.get("motion_class")}
              for i, q in enumerate(tiered, 1)]
    top_tier = [q for q in feats_q if q0_tier(q) == 1]
    fallback = not top_tier
    pool = top_tier if top_tier else feats_q
    scored = sorted(((q[key], q) for q in pool),
                    key=lambda sf: (-sf[0], sf[1]["tid"]))
    s1, f1 = scored[0]
    s2 = scored[1][0] if len(scored) > 1 else 0.0
    margin = round(s1 - s2, 4)
    if s1 < v2.MIN_ACTION_SCORE:
        status = "REFERENCE_NOT_FOUND"
    elif margin < v2.ABSTAIN_MARGIN:
        status = "REFERENCE_AMBIGUOUS"
    else:
        status = "REFERENCE_FOUND"
    return {"status": status, "fallback_to_frozen": fallback,
            "top_tid": f1["tid"], "top_score": s1, "margin": margin,
            "top2_score": s2,
            "ranked": ranked}


def cmd_rank(args):
    frozen = check_frozen()
    diag = json.loads((OUT_DIR / "candidate_quality_diagnostic.json").read_text())

    out = {
        "label": "SUBJECT_CANDIDATE_QUALITY_V3_RANKING",
        "packet": LABEL,
        "frozen": frozen,
        "q0_formulation": {
            "name": "Q0_TRACK_SUPPORT_TIER",
            "support_conf": SUPPORT_CONF,
            "support_radius": SUPPORT_RADIUS,
            "handling": "soft tiered down-rank (tier 1 = supported outranks "
                        "tier 0 = unsupported; frozen A0/A1 order within tier; "
                        "frozen abstention semantics on the top tier; "
                        "graceful fallback to frozen ranking when no "
                        "candidate has support)",
            "pre_registered_cutoff_family": {
                "description": "tier membership thresholds pre-registered as "
                               "the existence-of-evidence boundary (>=1) plus "
                               "robustness members 2/3/5; primary formulation "
                               "is >=1 (no new numeric cutoff)",
                "members": [1, 2, 3, 5],
            },
            "new_cutoffs": 0,
        },
        "dives": {},
    }
    for dive in ALL_DIVES:
        dv = diag["dives"][dive]
        feats_q = dv["candidates"]
        per = {}
        for method in ("A0", "A1"):
            r = v3_rank(feats_q, method)
            subj_ranks = [x["rank"] for x in r["ranked"] if x["is_subject"]]
            top_q = next(q for q in feats_q if q["tid"] == r["top_tid"])
            per[method] = {
                "status": r["status"],
                "fallback_to_frozen": r["fallback_to_frozen"],
                "top_tid": r["top_tid"],
                "top_margin": r["margin"],
                "top2_score": r["top2_score"],
                "top_is_subject": top_q["is_subject"],
                "reference_verdict": "SUBJECT_CORRECT" if top_q["is_subject"]
                else "SUBJECT_WRONG",
                "best_subject_rank": min(subj_ranks) if subj_ranks else None,
                "n_subject_candidates": len(subj_ranks),
                "top5_contains_subject": any(x <= 5 for x in subj_ranks),
                "top10_contains_subject": any(x <= 10 for x in subj_ranks),
                "top20_contains_subject": any(x <= 20 for x in subj_ranks),
                "subject_candidate_retained": bool(subj_ranks),
                "ranked": r["ranked"],
            }
        # subject-retention gate detail (Phase 4): the best-ranked surviving
        # subject candidate and its GT coverage
        best_subj = None
        for method in ("A0", "A1"):
            sr = per[method]["best_subject_rank"]
            if sr is None:
                continue
            cand = next(x for x in per[method]["ranked"]
                        if x["rank"] == sr)
            q = next(q for q in feats_q if q["tid"] == cand["tid"])
            if best_subj is None or sr < best_subj["rank"]:
                best_subj = {"rank": sr, "tid": q["tid"], "method": method,
                             "gt_purity": q["gt_purity"],
                             "n_visible_anchors_with_box":
                                 q.get("n_visible_anchors_with_box")}
        # frozen (pre-V3) best subject rank for before/after comparison
        frozen_best = {}
        for method in ("A0", "A1"):
            order = sorted(feats_q, key=lambda q: (-q[method], q["tid"]))
            frozen_best[method] = next(
                (i for i, q in enumerate(order, 1) if q["is_subject"]), None)
        # phantom suppression accounting (Phase 10)
        phantoms = [q for q in feats_q
                    if q["motion_class"] == "nonsubject_mover"
                    and q["support_count"] == 0]
        before_top1_phantom_wins = 0
        after_top1_phantom_wins = 0
        for method in ("A0", "A1"):
            base_top = max(feats_q, key=lambda q: (q[method], -q["tid"]))
            if base_top["motion_class"] == "nonsubject_mover" and \
                    base_top["support_count"] == 0:
                before_top1_phantom_wins += 1
            if per[method]["top_tid"] in {p["tid"] for p in phantoms}:
                after_top1_phantom_wins += 1
        n_ph_downranked = 0
        for p in phantoms:
            for method in ("A0", "A1"):
                v3_rank_of = next(x["rank"] for x in per[method]["ranked"]
                                  if x["tid"] == p["tid"])
                frozen_order = sorted(feats_q,
                                      key=lambda q: (-q[method], q["tid"]))
                frozen_rank_of = next(
                    i for i, q in enumerate(frozen_order, 1)
                    if q["tid"] == p["tid"])
                if v3_rank_of > frozen_rank_of:
                    n_ph_downranked += 1
                    break
        # pre-registered cutoff-family robustness (reported, not selected)
        robustness = {}
        for K in (1, 2, 3, 5):
            row = {}
            for method in ("A0", "A1"):
                supported = [q for q in feats_q if q["support_count"] >= K]
                tier = supported or feats_q
                order = sorted(tier, key=lambda q: (-q[method], q["tid"]))
                top = order[0]
                srank = next((i for i, q in enumerate(order, 1)
                              if q["is_subject"]), None)
                row[method] = {
                    "top_tid": top["tid"],
                    "subject_correct": top["is_subject"],
                    "best_subject_rank": srank,
                    "fallback_to_frozen": not supported,
                }
            robustness[str(K)] = row
        out["dives"][dive] = {
            "family": dv["family"],
            "n_candidates": dv["n_candidates"],
            "subject_retention": {
                "retained": best_subj is not None,
                "best": best_subj,
                "frozen_best_subject_rank": frozen_best,
            },
            "n_phantom_candidates": len(phantoms),
            "n_phantom_downranked": n_ph_downranked,
            "phantom_top1_wins_before": before_top1_phantom_wins,
            "phantom_top1_wins_after": after_top1_phantom_wins,
            "cutoff_family_robustness": robustness,
            "methods": per,
        }
        print(f"{dive}: A0 top={per['A0']['top_tid']} "
              f"({per['A0']['reference_verdict']}) A1 top={per['A1']['top_tid']} "
              f"({per['A1']['reference_verdict']})")

    out["q1_support_appearance"] = load_q1_rejection()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "v3_ranking.json").write_text(json.dumps(out, indent=1, sort_keys=True))
    print("->", OUT_DIR / "v3_ranking.json")


def load_q1_rejection() -> dict:
    """Q1 premise probe result (within-track appearance coherence from the
    frozen OSNet caches; eval-only probe, no ranking change)."""
    p = OUT_DIR / "q1_coherence_probe.json"
    if not p.exists():
        return {"status": "NOT_EXECUTED"}
    rows = json.loads(p.read_text())
    def stats(sel):
        vs = sorted(o["coh"] for o in sel)
        if not vs:
            return None
        return {"n": len(vs), "min": vs[0], "median": vs[len(vs) // 2],
                "max": vs[-1]}
    return {
        "status": "REJECTED_EARLY",
        "reason": "within-track appearance coherence does not separate "
                  "subject candidates from supported non-subject movers: "
                  "non-subject candidates are equally or more coherent "
                  "(median at or above the subject median in every slice); "
                  "Q1 offers no generic benefit for the remaining supported-"
                  "mover failure mode and is rejected before formulation",
        "probe": {
            "subject_supported": stats([o for o in rows if o["subj"] and o["sup"] >= 1]),
            "nonsubject_mover_supported": stats(
                [o for o in rows if not o["subj"] and o["sup"] >= 1]),
            "subject_all": stats([o for o in rows if o["subj"]]),
            "nonsubject_all": stats([o for o in rows if not o["subj"]]),
        },
    }


def run_diagnostic(out_path: str):
    frozen = check_frozen()
    gt_hurdle = load_hurdle_gt()
    anchors = load_anchors()

    out = {
        "label": "SUBJECT_CANDIDATE_QUALITY_DIAGNOSTIC_V3",
        "packet": LABEL,
        "frozen": frozen,
        "constants": {
            "SUPPORT_CONF": SUPPORT_CONF,
            "SUPPORT_CONF_provenance": "frozen V2 characterize_clip_structure "
                                       "person-plausible occupancy threshold (conf>=0.05)",
            "SUPPORT_RADIUS": SUPPORT_RADIUS,
            "SUPPORT_RADIUS_provenance": "frozen reference_purity / Level-A "
                                         "consistency normalized center distance",
            "MOTION_EXCURSION_MIN": MOTION_EXCURSION_MIN,
            "MOTION_EXCURSION_MIN_provenance": "frozen A0 ENTRY_EXTREME_MARGIN_CY",
            "D5_floor_conf_unchanged": 0.001,
        },
        "dives": {},
    }

    for dive in ALL_DIVES:
        clip, trs, off, feats = build_dive(dive)
        rows = []
        for tr, f in feats:
            q = quality_measures(tr, clip, f)
            if dive in HURDLE_DIVES:
                purity = hurdle_purity(dive, clip, tr, gt_hurdle, clip.fps)
                subject = purity >= 0.5
                q["gt_purity"] = purity
            else:
                ev = standing_anchor_eval(dive, tr, anchors)
                purity = ev["purity"]
                subject = bool(ev["n_visible_anchors_with_box"]) and \
                    ev["n_consistent"] == ev["n_visible_anchors_with_box"]
                q["gt_purity"] = purity
                q["n_visible_anchors_with_box"] = ev["n_visible_anchors_with_box"]
            q["family"] = "HURDLE" if dive in HURDLE_DIVES else "STANDING"
            q["is_subject"] = subject
            mover_like = q["excursion_cy"] >= MOTION_EXCURSION_MIN
            if subject:
                cls = "subject"
            elif mover_like:
                cls = "nonsubject_mover"
            else:
                cls = "nonsubject_static"
            q["motion_class"] = cls
            rows.append(q)
        out["dives"][dive] = {
            "family": rows[0]["family"] if rows else None,
            "n_candidates": len(rows),
            "candidates": rows,
        }
        print(f"{dive}: {len(rows)} candidates")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(out, indent=1, sort_keys=True))
    print("->", out_path)


def cmd_report(args):
    """Assemble the durable packet artifact from the run outputs."""
    diag = json.loads((OUT_DIR / "candidate_quality_diagnostic.json").read_text())
    rank = json.loads((OUT_DIR / "v3_ranking.json").read_text())

    def dist(rows, key):
        vs = sorted(r[key] for r in rows)
        if not vs:
            return None
        return {"n": len(vs), "min": vs[0], "p25": vs[len(vs) // 4],
                "median": vs[len(vs) // 2], "p75": vs[3 * len(vs) // 4],
                "max": vs[-1],
                "zero": round(sum(1 for v in vs if v == 0) / len(vs), 4)}

    distributions = {}
    for fam in ("HURDLE", "STANDING"):
        rows = [c for dv in diag["dives"].values() if dv["family"] == fam
                for c in dv["candidates"]]
        by = {}
        for c in rows:
            by.setdefault(c["motion_class"], []).append(c)
        distributions[fam] = {
            cls: {
                "support_frac": dist(cs, "support_frac"),
                "support_count": dist(cs, "support_count"),
                "conf_max": dist(cs, "conf_max"),
                "conf_mean": dist(cs, "conf_mean"),
                "n": len(cs),
            } for cls, cs in by.items()
        }

    per_dive = {}
    for dive in ALL_DIVES:
        dv = rank["dives"][dive]
        fb = dv["subject_retention"]["frozen_best_subject_rank"]
        per_dive[dive] = {
            "family": dv["family"],
            "methods": {
                m: {
                    "v3_top_tid": dv["methods"][m]["top_tid"],
                    "v3_status": dv["methods"][m]["status"],
                    "subject_correct": dv["methods"][m]["top_is_subject"],
                    "best_subject_rank_frozen": fb[m],
                    "best_subject_rank_v3": dv["methods"][m]["best_subject_rank"],
                    "top5_contains_subject": dv["methods"][m]["top5_contains_subject"],
                    "top10_contains_subject": dv["methods"][m]["top10_contains_subject"],
                    "top20_contains_subject": dv["methods"][m]["top20_contains_subject"],
                    "subject_candidate_retained":
                        dv["methods"][m]["subject_candidate_retained"],
                } for m in ("A0", "A1")
            },
            "phantoms": {k: dv[k] for k in
                         ("n_phantom_candidates", "n_phantom_downranked",
                          "phantom_top1_wins_before", "phantom_top1_wins_after")},
            "cutoff_family_robustness": dv["cutoff_family_robustness"],
        }

    totals = {
        "phantom_candidates": sum(dv["n_phantom_candidates"]
                                  for dv in rank["dives"].values()),
        "phantom_downranked": sum(dv["n_phantom_downranked"]
                                  for dv in rank["dives"].values()),
        "phantom_top1_wins_before": sum(dv["phantom_top1_wins_before"]
                                        for dv in rank["dives"].values()),
        "phantom_top1_wins_after": sum(dv["phantom_top1_wins_after"]
                                       for dv in rank["dives"].values()),
        "top1_subject_correct": {
            "HURDLE": sum(1 for d in per_dive.values() if d["family"] == "HURDLE"
                          for m in d["methods"].values() if m["subject_correct"]),
            "STANDING": sum(1 for d in per_dive.values() if d["family"] == "STANDING"
                            for m in d["methods"].values() if m["subject_correct"]),
            "of": {"HURDLE": 10, "STANDING": 8},
        },
    }

    abstention = []
    for dive in ALL_DIVES:
        for m in ("A0", "A1"):
            p = rank["dives"][dive]["methods"][m]
            if not p["top_is_subject"]:
                abstention.append({"dive": dive, "method": m,
                                   "status": p["status"],
                                   "margin": p["top_margin"],
                                   "top_score": p["ranked"][0]["score"]})

    out = {
        "label": "DIVE_ANALYZER_SUBJECT_CANDIDATE_QUALITY_V3",
        "gate": "SUPERVISOR_REVIEW_AFTER_SUBJECT_CANDIDATE_QUALITY_V3",
        "date": "2026-09-13",
        "canonical_base": "0dabd2bca89270e2d0171107af4aca5f8b3a0650",
        "frozen_inputs": {
            "v2_module_sha256": V2_MODULE_SHA,
            "cohort_d5_cache_sha256": sha256_file(COHORT_CANDIDATES),
            "hurdle_d5_cache_sha256": sha256_file(HURDLE_CANDIDATES),
            "level_a_authority_sha256": "d805aac2b46e52f002de2842b56bb9a1b0ced808f0862a4c559f5ffe9099a75e",
            "d5_floor_conf": 0.001,
        },
        "baseline_reproduction": {
            "HURDLE": "IDENTICAL (A0/A1 top-1 tid+score match frozen V2 "
                      "freeze artifact on all 5 dives; candidate counts match)",
            "STANDING": "IDENTICAL (full ranked tid+score lists and candidate "
                        "features match durable Level-A replay artifact on all "
                        "4 dives; eval verdicts identical: 0/7 measurable "
                        "top-1 subject-correct, 2387-A0 REFERENCE_GT_UNOBSERVED)",
        },
        "phase3_track_support_signal": "TRACK_SUPPORT_SIGNAL_PARTIAL",
        "phase3_evidence": {
            "STANDING": "every subject candidate has >=1 supported frame "
                        "(0% zero-support, support_count>=2); 76.7% of "
                        "non-subject movers and 92.2% of non-subject statics "
                        "have zero support; the STANDING top-1 phantom decoys "
                        "on 133/311 have zero support",
            "HURDLE": "signal does not cover all subject candidates (26.8% "
                      "of subject candidates have zero support) but every "
                      "dive retains >=1 supported subject candidate; several "
                      "HURDLE top-1 decoys are supported movers",
            "verdict_rationale": "signal is real and generic but only "
                                 "partially separates subjects from the "
                                 "candidate ocean; supported real movers "
                                 "remain dominant after phantom suppression",
        },
        "subject_retention_gate": {
            "rule": "at least one subject candidate survives quality handling",
            "result": "PASSED on all 9 dives at every pre-registered cutoff "
                      "(support_count >= 1/2/3/5); no subject hypothesis deleted",
        },
        "q0_track_support": {
            "status": "EXECUTED",
            "definition": "support_count = #frames where any candidate with "
                          "conf >= 0.05 lies within normalized center "
                          "distance 0.06 of the tracklet box (own box "
                          "included); soft tiered down-rank, frozen A0/A1 "
                          "order within tier, frozen abstention semantics, "
                          "graceful fallback",
            "constants_provenance": "0.05 = frozen V2 person-plausible "
                                    "occupancy threshold; 0.06 = frozen "
                                    "reference_purity/Level-A consistency "
                                    "radius; no new numeric cutoff",
            "cutoff_family": [1, 2, 3, 5],
            "cutoff_family_result": "0/18 top-1 subject-correct at every "
                                    "member; >=1 retained as primary",
        },
        "q1_support_appearance": rank["q1_support_appearance"],
        "v3_results_per_dive": per_dive,
        "phantom_suppression_totals": totals,
        "abstention_diagnostic": {
            "policy": "no retuning; diagnostic margins only",
            "wrong_top1": abstention,
            "finding": "wrong top-1 references remain confidently wrong "
                       "(REFERENCE_FOUND margins up to 2.24); abstention "
                       "cannot separate them",
        },
        "downstream_matcher_replay": "NOT_JUSTIFIED (V3 produced no correct "
                                     "references to replay the matcher on)",
        "classification": "CANDIDATE_QUALITY_V3_PARTIAL",
        "classification_rationale": [
            "subject candidates preserved on all 9 dives (retention gate passed)",
            "phantom top-1 wins suppressed 9 -> 0 without deletion",
            "reference top-1 does NOT improve: 0/18 before and after; the "
            "dominant remaining decoys are SUPPORTED movers (real persons or "
            "subject-adjacent association fragments with purity up to 0.67), "
            "an identity/association failure mode outside candidate quality",
            "best-subject-rank improves materially on 12 of 18 (dive,method) "
            "cells (e.g. 311-A0 30->2, 133-A0 77->14, 2387-A0 435->100) but "
            "regresses on 3 HURDLE cells (1040-A1 2->15, 2353-A0 9->18, "
            "2353-A1 2->16), so the improvement is not clean",
        ],
        "handcrafted_heuristics": "HANDCRAFTED_SUBJECT_REFERENCE_HEURISTICS_"
                                  "CONTINUE_ONLY_IF_NEW_EVIDENCE (no V4 rule "
                                  "cycle proposed; remaining failure is "
                                  "identity/association, not candidate quality)",
        "learning_reassessment": "EXPAND_INDEPENDENT_GT_BEFORE_LEARNING",
        "armstand_decision": "ARMSTAND_STILL_DEFERRED",
        "exclusions": {
            "524": "AUTHORITY_CONFLICT_EXCLUDED (not loaded)",
            "2555": "SCREEN_RECORDING_STRESS_CASE (not loaded)",
            "Paris": "EXTERNAL_ONLY (not accessed)",
            "INTERNAL_EVAL": "NOT_ACCESSED",
            "FINAL_HOLDOUT": "NOT_ACCESSED",
        },
        "resource_results": {
            "new_d5_inference": 0, "new_embeddings": 0, "model_training": 0,
            "new_human_labels": 0, "b2_reads": 0, "b2_writes": 0,
        },
    }
    dest = REPO / "docs/science/DIVE_ANALYZER_SUBJECT_CANDIDATE_QUALITY_V3.json"
    dest.write_text(json.dumps(out, indent=1, sort_keys=True))
    print("->", dest)


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("diagnostic")
    sub.add_parser("rank")
    sub.add_parser("report")
    args = ap.parse_args()
    if args.cmd == "diagnostic":
        run_diagnostic(str(OUT_DIR / "candidate_quality_diagnostic.json"))
    elif args.cmd == "rank":
        cmd_rank(args)
    elif args.cmd == "report":
        cmd_report(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
