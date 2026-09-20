#!/usr/bin/env python3
"""DIVE_ANALYZER_INDEPENDENT_SUBJECT_GT_EXPANSION_V1 — Phases 15/17/18.

Post-human-read-only analysis on the 6 NEW independent dives:

- consistency: human-consistency diagnostics on the frozen Level-B authority
  (spatial jumps, NOT_VISIBLE runs, duplicate conflicts). FLAGS ONLY —
  never auto-corrects; genuine conflicts go back to the human.
- diagnostic: frozen-v2 tracklets + GT-free quality measures on the INDEP
  D5 cache, labeled ONLY by the frozen Level-B human anchors (STANDING
  subject rule reused unchanged: >=1 visible anchor with box and ALL
  consistent at center distance <= 0.06).
- negatives: identity-negative audit (subject / supported-mover /
  static / phantom classes from the diagnostic).
- replay: frozen V3 Q0 tiered rank read-only (frozen A0/A1 order within
  tier, frozen abstention semantics, graceful fallback).

No training, no tuning, no B2, no GT mutation. GT is labeling-only.

Usage:
  python3 experiments/subject_resolution/phase_indep_gt_expansion_analysis_v1.py consistency
  python3 experiments/subject_resolution/phase_indep_gt_expansion_analysis_v1.py diagnostic
  python3 experiments/subject_resolution/phase_indep_gt_expansion_analysis_v1.py negatives
  python3 experiments/subject_resolution/phase_indep_gt_expansion_analysis_v1.py replay
"""

import argparse
import json
import math
import sys
from pathlib import Path

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments/subject_resolution"))

import subject_reference_acquisition_v2 as v2  # noqa: E402
import phase_subject_candidate_quality_v3 as v3mod  # noqa: E402

LABEL = "DIVE_ANALYZER_INDEPENDENT_SUBJECT_GT_EXPANSION_V1"
INDEP_DIVES = ["1304", "2223", "2204", "2526", "2583", "2839"]
INDEP_CANDIDATES = BASE / "runs/subject_resolution/R5_FULLCLIP_CANDIDATES_INDEP_V1.json"
L1B_DIR = BASE / "docs/science/localization_annotations_v1/SUBJECT_GT_LEVEL_B_INDEPENDENT_V1"
WORK_DIR = BASE / "runs/subject_gt_level_b_v1"

FAMILY = {
    "1304": "STANDING_APPROACH",
    "2223": "STANDING",
    "2204": "STANDING_APPROACH",
    "2526": "HURDLE_ORDINARY",
    "2583": "STANDING",
    "2839": "HURDLE_ORDINARY",
}

# Consistency flag: normalized center jump per second between consecutive
# VISIBLE anchors exceeding this many mean-box-heights is flagged for human
# review (Level-A review observed max ~1.06 bh/0.5s; flag well above that).
JUMP_FLAG_PER_S = 4.0


def load_l1b():
    out = {}
    for p in sorted(L1B_DIR.glob("L1B_*.json")):
        a = json.loads(p.read_text())
        assert a["authority"] == "HUMAN_REVIEWED", p
        out.setdefault(str(a["dive_id"]), {})[int(a["frame_index"])] = a
    return out


def build_indep_dive(dive: str):
    raw = json.loads(INDEP_CANDIDATES.read_text())
    v = raw["dives"][dive]
    frames_raw = [{"fi": f["fi"], "pts_s": f["pts_s"], "c": f["c"]}
                  for f in v["frames"]]
    clip = v2.Clip(dive, frames_raw, fps=float(v["fps"]))
    return clip


def cmd_consistency(_args):
    anchors = load_l1b()
    per_dive = {}
    all_flags = []
    for dive in INDEP_DIVES:
        anns = anchors.get(dive, {})
        items = sorted(anns.items())
        n_vis = sum(1 for _, a in items if a["visibility"] == "visible")
        n_nv = sum(1 for _, a in items if a["visibility"] != "visible")
        # consecutive visible-anchor jumps
        max_jump = 0.0
        max_jump_pair = None
        flags = []
        prev = None
        for fi, a in items:
            if a["visibility"] != "visible":
                prev = None
                continue
            x1, y1, x2, y2 = a["bbox"]
            cx, cy = ((x1 + x2) / 2) / a["width"], ((y1 + y2) / 2) / a["height"]
            bh = (y2 - y1) / a["height"]
            if prev is not None:
                pfi, pcx, pcy, pbh, ppts = prev
                dt = a["pts_s"] - ppts  # anchor PTS authority, fps-agnostic
                dist = math.hypot(cx - pcx, cy - pcy)
                mean_bh = (bh + pbh) / 2
                rate = (dist / mean_bh) / dt if dt > 0 and mean_bh > 0 else 0.0
                if rate > max_jump:
                    max_jump = rate
                    max_jump_pair = [pfi, fi]
                if rate > JUMP_FLAG_PER_S:
                    flags.append({"type": "LARGE_SPATIAL_JUMP",
                                  "frames": [pfi, fi],
                                  "per_s_bh": round(rate, 3)})
            prev = (fi, cx, cy, bh, a["pts_s"])
        # bounds check (mechanical)
        for fi, a in items:
            if a["visibility"] == "visible":
                ok, err = True, ""
                x1, y1, x2, y2 = a["bbox"]
                if not (0 <= x1 < x2 <= a["width"] and 0 <= y1 < y2 <= a["height"]):
                    ok, err = False, "bbox outside frame bounds"
                if not ok:
                    flags.append({"type": "BOUNDS", "frames": [fi], "detail": err})
        all_flags.extend({"dive_id": dive, **f} for f in flags)
        per_dive[dive] = {
            "n_anchors": len(items),
            "n_visible": n_vis,
            "n_not_visible": n_nv,
            "max_consecutive_visible_jump_per_s_bh": round(max_jump, 3),
            "max_jump_frames": max_jump_pair,
            "n_flags": len(flags),
        }
    report = {
        "label": "SUBJECT_GT_LEVEL_B_CONSISTENCY_V1",
        "packet": LABEL,
        "flag_rule": f"consecutive-visible jump > {JUMP_FLAG_PER_S} mean-bh/s",
        "note": "FLAGS ONLY — no auto-correction; genuine conflicts return to human",
        "per_dive": per_dive,
        "flags": all_flags,
        "verdict": "CLEAN" if not all_flags else "FLAGS_REQUIRE_HUMAN_REVIEW",
    }
    (WORK_DIR / "consistency_v1.json").write_text(json.dumps(report, indent=1, sort_keys=True))
    print(json.dumps(report, indent=1))


def cmd_diagnostic(_args):
    frozen = v3mod.check_frozen()
    anchors = load_l1b()
    out = {
        "label": "SUBJECT_GT_LEVEL_B_DIAGNOSTIC_V1",
        "packet": LABEL,
        "frozen": frozen,
        "constants": {
            "SUPPORT_CONF": v3mod.SUPPORT_CONF,
            "SUPPORT_RADIUS": v3mod.SUPPORT_RADIUS,
            "MOTION_EXCURSION_MIN": v3mod.MOTION_EXCURSION_MIN,
            "subject_rule": "STANDING rule reused unchanged: >=1 visible "
                            "Level-B anchor with tracklet box AND all such "
                            "anchors consistent (center dist <= 0.06)",
        },
        "dives": {},
    }
    for dive in INDEP_DIVES:
        clip = build_indep_dive(dive)
        trs, off = v2.tracklets_and_flow(clip)
        rows = []
        for tr in trs:
            f = v2.tracklet_features(tr, clip, off)
            if f is None:
                continue
            f["fi0"], f["fi1"] = tr.starts[0], tr.starts[-1]
            q = v3mod.quality_measures(tr, clip, f)
            ev = v3mod.standing_anchor_eval(dive, tr, anchors)
            purity = ev["purity"]
            subject = bool(ev["n_visible_anchors_with_box"]) and \
                ev["n_consistent"] == ev["n_visible_anchors_with_box"]
            q["gt_purity"] = purity
            q["n_visible_anchors_with_box"] = ev["n_visible_anchors_with_box"]
            q["family"] = FAMILY[dive]
            q["is_subject"] = subject
            mover_like = q["excursion_cy"] >= v3mod.MOTION_EXCURSION_MIN
            q["motion_class"] = "subject" if subject else (
                "nonsubject_mover" if mover_like else "nonsubject_static")
            rows.append(q)
        out["dives"][dive] = {
            "family": FAMILY[dive],
            "n_candidates": len(rows),
            "n_tracklets_total": len(trs),
            "n_features_none": len(trs) - len(rows),
            "candidates": rows,
        }
        print(f"{dive}: {len(rows)} candidates ({len(trs)} tracklets)")
    (WORK_DIR / "indep_diagnostic_v1.json").write_text(json.dumps(out))
    print("->", WORK_DIR / "indep_diagnostic_v1.json")


def cmd_negatives(_args):
    diag = json.loads((WORK_DIR / "indep_diagnostic_v1.json").read_text())
    per_dive = {}
    agg = {"subject": 0, "supported_mover": 0, "phantom_mover": 0,
           "static": 0, "subject_adjacent_fragment": 0}
    for dive in INDEP_DIVES:
        rows = diag["dives"][dive]["candidates"]
        subj = [q for q in rows if q["is_subject"]]
        movers = [q for q in rows if q["motion_class"] == "nonsubject_mover"]
        statics = [q for q in rows if q["motion_class"] == "nonsubject_static"]
        sup_movers = [q for q in movers if q["support_count"] >= 1]
        phantoms = [q for q in movers if q["support_count"] == 0]
        # subject-adjacent fragments: non-subject tracklets with partial
        # anchor consistency (0 < purity < 1) — association-fragment suspects
        adj = [q for q in rows if not q["is_subject"]
               and q["gt_purity"] is not None and 0 < q["gt_purity"] < 1]
        # other-diver evidence: supported movers with zero anchor consistency
        # (a distinct person never overlapping the subject anchors)
        other_diver_like = [q for q in sup_movers
                            if (q["gt_purity"] or 0) == 0]
        per_dive[dive] = {
            "n_candidates": len(rows),
            "subject_tracklets": len(subj),
            "subject_anchor_coverage": {
                "n_visible_anchors": sum(
                    1 for q in subj for _ in [0]),
                "best_purity": max([q["gt_purity"] or 0 for q in subj] or [0]),
            },
            "supported_nonsubject_movers": len(sup_movers),
            "phantom_movers": len(phantoms),
            "static_candidates": len(statics),
            "subject_adjacent_fragments": len(adj),
            "other_diver_like_supported": len(other_diver_like),
            "subject_zero_support": sum(1 for q in subj if q["support_count"] == 0),
            "movers_zero_support_frac": round(
                sum(1 for q in movers if q["support_count"] == 0) / len(movers), 4) if movers else None,
        }
        agg["subject"] += len(subj)
        agg["supported_mover"] += len(sup_movers)
        agg["phantom_mover"] += len(phantoms)
        agg["static"] += len(statics)
        agg["subject_adjacent_fragment"] += len(adj)
    report = {"label": "IDENTITY_NEGATIVE_AUDIT_V1", "packet": LABEL,
              "per_dive": per_dive, "aggregate": agg}
    (WORK_DIR / "identity_negative_audit_v1.json").write_text(
        json.dumps(report, indent=1, sort_keys=True))
    print(json.dumps(report, indent=1))


def cmd_replay(_args):
    frozen = v3mod.check_frozen()
    diag = json.loads((WORK_DIR / "indep_diagnostic_v1.json").read_text())
    out = {"label": "FROZEN_V3_REPLAY_INDEP_V1", "packet": LABEL,
           "frozen": frozen,
           "q0": "Q0_TRACK_SUPPORT_TIER reused unchanged (>=1, soft tiered "
                 "down-rank, frozen A0/A1 within tier, frozen abstention, "
                 "graceful fallback)",
           "dives": {}}
    for dive in INDEP_DIVES:
        feats_q = diag["dives"][dive]["candidates"]
        per = {}
        for method in ("A0", "A1"):
            r = v3mod.v3_rank(feats_q, method)
            subj_ranks = [x["rank"] for x in r["ranked"] if x["is_subject"]]
            top_q = next(q for q in feats_q if q["tid"] == r["top_tid"])
            order = sorted(feats_q, key=lambda q: (-q[method], q["tid"]))
            frozen_best = next(
                (i for i, q in enumerate(order, 1) if q["is_subject"]), None)
            base_top = max(feats_q, key=lambda q: (q[method], -q["tid"]))
            per[method] = {
                "status": r["status"],
                "fallback_to_frozen": r["fallback_to_frozen"],
                "top_tid": r["top_tid"],
                "top_margin": r["margin"],
                "top_is_subject": top_q["is_subject"],
                "top_motion_class": top_q["motion_class"],
                "top_support_count": top_q["support_count"],
                "reference_verdict": "SUBJECT_CORRECT" if top_q["is_subject"] else "SUBJECT_WRONG",
                "best_subject_rank": min(subj_ranks) if subj_ranks else None,
                "frozen_best_subject_rank": frozen_best,
                "n_subject_candidates": len(subj_ranks),
                "subject_retained": bool(subj_ranks),
                "frozen_top1_was_unsupported_phantom": (
                    base_top["motion_class"] == "nonsubject_mover"
                    and base_top["support_count"] == 0),
                "top1_is_unsupported_phantom_after": (
                    top_q["motion_class"] == "nonsubject_mover"
                    and top_q["support_count"] == 0),
            }
        phantoms = [q for q in feats_q
                    if q["motion_class"] == "nonsubject_mover"
                    and q["support_count"] == 0]
        out["dives"][dive] = {
            "family": FAMILY[dive],
            "n_candidates": len(feats_q),
            "n_phantom_candidates": len(phantoms),
            "methods": per,
        }
        print(f"{dive}: A0 top={per['A0']['top_tid']} "
              f"({per['A0']['reference_verdict']}, {per['A0']['status']}) "
              f"A1 top={per['A1']['top_tid']} "
              f"({per['A1']['reference_verdict']}, {per['A1']['status']})")
    (WORK_DIR / "frozen_v3_replay_indep_v1.json").write_text(
        json.dumps(out, indent=1, sort_keys=True))
    print("->", WORK_DIR / "frozen_v3_replay_indep_v1.json")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("consistency", "diagnostic", "negatives", "replay"):
        sub.add_parser(name)
    args = ap.parse_args()
    {"consistency": cmd_consistency, "diagnostic": cmd_diagnostic,
     "negatives": cmd_negatives, "replay": cmd_replay}[args.cmd](args)


if __name__ == "__main__":
    main()
