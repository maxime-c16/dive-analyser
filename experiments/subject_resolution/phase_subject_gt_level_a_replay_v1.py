#!/usr/bin/env python3
"""DIVE_ANALYZER_SUBJECT_GT_LEVEL_A_ANNOTATION_V1 — frozen V2 replay + Level-A eval.

Phase 11: replay the FROZEN GT-free reference-acquisition methods (A0, A1) on
STANDING with zero changes (constants asserted against the V2 freeze artifact).
Phase 12: measure true Level-A reference correctness against the frozen human
Level-A anchors (SUBJECT_GT_LEVEL_A_STANDING_V1).

No tuning. No new inference. No embedding recomputation (OSNet not loaded).
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

import subject_reference_acquisition_v2 as v2  # frozen module, imported unmodified

LABEL = "DIVE_ANALYZER_SUBJECT_GT_LEVEL_A_ANNOTATION_V1"
STANDING_DIVES = ["133", "311", "676", "2387"]
D5_CACHE = REPO / "runs/subject_resolution/R5_FULLCLIP_CANDIDATES_COHORT_V1.json"
V2_FREEZE = REPO / "docs/science/DIVE_ANALYZER_SUBJECT_REFERENCE_ACQUISITION_V2.json"
OUT_DIR = REPO / "runs/subject_gt_level_a_v1"
ANCHOR_DIR = REPO / "docs/science/localization_annotations_v1/SUBJECT_GT_LEVEL_A_STANDING_V1"
CONSISTENCY_RADIUS = 0.06  # normalized center distance, reference_purity precedent


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


V2_MODULE_SHA = "01a17dd77131076d323b4adbc0790ac1d284f36fe39ebfb98a0ef64ad7a1d73e"


def check_frozen():
    """Pin the frozen scorers: module byte-identical to the V2 packet commit,
    A0 constants identical to the recorded V2 freeze artifact."""
    mod_sha = sha256_file(Path(v2.__file__))
    if mod_sha != V2_MODULE_SHA:
        raise SystemExit(f"V2 MODULE DRIFT {mod_sha} != {V2_MODULE_SHA} — refusing to replay")
    frozen = json.loads(V2_FREEZE.read_text())["phase6_scorers"]
    rec = frozen["A0_clip_relative_action_ownership"]["constants"]
    live = v2._frozen_constants()
    diffs = {k: (rec.get(k), live.get(k)) for k in set(rec) | set(live)
             if rec.get(k) != live.get(k)}
    if diffs:
        raise SystemExit(f"FROZEN CONSTANT DRIFT — refusing to replay: {diffs}")
    return {"module_sha256": mod_sha, **live}


def load_anchors():
    """Frozen Level-A human anchors keyed by (dive, frame_index)."""
    out = {}
    for p in sorted(ANCHOR_DIR.glob("L1A_*.json")):
        a = json.loads(p.read_text())
        assert a["authority"] == "HUMAN_REVIEWED", p
        out[(str(a["dive_id"]), int(a["frame_index"]))] = a
    return out


def cmd_replay(args):
    consts = check_frozen()
    raw = json.loads(D5_CACHE.read_text())
    assert raw["gt_payload"].startswith("NONE"), "cache must be GT-free"
    frames_raw = {
        d: [{"fi": f["fi"], "pts_s": f["pts_s"], "c": f["c"]} for f in raw["dives"][d]["frames"]]
        for d in STANDING_DIVES
    }
    clips = {d: v2.Clip(d, frames_raw[d], float(raw["dives"][d]["fps"])) for d in STANDING_DIVES}
    out = {"label": "SUBJECT_GT_LEVEL_A_REPLAY_V1", "packet": LABEL,
           "frozen_constants": consts, "consistency_radius": CONSISTENCY_RADIUS,
           "osnet_loaded": False, "dives": {}}
    for d in STANDING_DIVES:
        clip = clips[d]
        trs, off = v2.tracklets_and_flow(clip)
        feats = []
        for tr in trs:
            f = v2.tracklet_features(tr, clip, off)
            if f is not None:
                f["fi0"], f["fi1"] = tr.starts[0], tr.starts[-1]
                feats.append(f)
        anchors = sorted(k[1] for k in load_anchors() if k[0] == d) if ANCHOR_DIR.exists() else []
        tid_map = {t.tid: t for t in trs}
        per = {}
        for method, scorer in (("A0", v2.a0_score_from_features),
                               ("A1", v2.a1_score_from_features)):
            scored = sorted(((scorer(f), f) for f in feats),
                            key=lambda sf: (-sf[0], sf[1]["tid"]))
            ranked = []
            for rank, (s, f) in enumerate(scored, 1):
                ranked.append({
                    "rank": rank, "tid": f["tid"], "score": s,
                    "tau_start": f["tau_start"], "tau_end": f["tau_end"],
                    "span_s": f["span_s"], "fi0": f["fi0"], "fi1": f["fi1"],
                })
            # attach candidate boxes at anchor frames
            for r in ranked:
                tr = tid_map[r["tid"]]
                bxs = {}
                for fi in anchors:
                    if fi in tr.boxes:
                        b = tr.boxes[fi]
                        bxs[fi] = [round(b.cx, 6), round(b.cy, 6),
                                   round(b.bw, 6), round(b.bh, 6)]
                r["boxes_at_anchor_frames"] = bxs
            top = scored[0][1]
            per[method] = {
                "status": v2.acquire_reference(clip, feats, scorer=scorer)["status"],
                "n_candidates": len(scored),
                "top_tid": top["tid"],
                "top_score": scored[0][0],
                "top2_score": scored[1][0] if len(scored) > 1 else 0.0,
                "ranked": ranked,
            }
        out["dives"][d] = {
            "fps": clip.fps, "duration_s": round(clip.duration_s, 4),
            "n_frames": clip.n_frames, "n_tracklet_feats": len(feats),
            "anchor_frames": anchors,
            "candidate_features": {
                f["tid"]: {k: (list(v) if isinstance(v, tuple) else v)
                           for k, v in f.items()} for f in feats
            },
            "methods": per,
        }
        print(f"{d}: {len(feats)} candidates scored, anchors={len(anchors)}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "replay_rankings.json").write_text(json.dumps(out, indent=1, sort_keys=True))
    print(f"-> {OUT_DIR/'replay_rankings.json'}")


def _consistent(box, ann):
    """Anchor-consistency: normalized center distance <= radius (project
    precedent reference_purity). IoU recorded for transparency."""
    cx, cy = box[0], box[1]
    x1, y1, x2, y2 = ann["bbox"]
    pcx, pcy = ((x1 + x2) / 2) / 202, ((y1 + y2) / 2) / 360
    dist = math.hypot(cx - pcx, cy - pcy)
    bw, bh = box[2], box[3]
    ax1, ay1, ax2, ay2 = cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2
    bx1, by1, bx2, by2 = x1 / 202, y1 / 360, x2 / 202, y2 / 360
    iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    union = bw * bh + (bx2 - bx1) * (by2 - by1) - inter
    iou = inter / union if union > 0 else 0.0
    return dist <= CONSISTENCY_RADIUS, round(dist, 4), round(iou, 4)


def cmd_evaluate(args):
    replay = json.loads((OUT_DIR / "replay_rankings.json").read_text())
    anchors = load_anchors()
    out = {"label": "SUBJECT_GT_LEVEL_A_REFERENCE_EVAL_V1", "packet": LABEL,
           "consistency_rule": f"center distance <= {CONSISTENCY_RADIUS} (normalized)",
           "not_visible_policy": "excluded from consistency math, counted separately",
           "dives": {}}
    for d in STANDING_DIVES:
        rep = replay["dives"][d]
        fps, dur = rep["fps"], rep["duration_s"]
        a_items = {fi: anchors[(d, fi)] for fi in rep["anchor_frames"]}
        per = {}
        for method in ("A0", "A1"):
            m = rep["methods"][method]
            ranked = m["ranked"]
            # subject-consistency per candidate
            subj_ranks = []
            for r in ranked:
                hits = tot = 0
                details = []
                for fi, box in ((int(k), v) for k, v in
                                r["boxes_at_anchor_frames"].items()):
                    ann = a_items[fi]
                    if ann["visibility"] != "visible":
                        continue
                    tot += 1
                    ok, dist, iou = _consistent(box, ann)
                    details.append({"frame_index": fi, "dist": dist, "iou": iou,
                                    "consistent": ok})
                    if ok:
                        hits += 1
                r["anchor_eval"] = {
                    "n_visible_anchors_with_box": tot,
                    "n_consistent": hits,
                    "purity": round(hits / tot, 4) if tot else None,
                    "details": details,
                }
                if tot and hits == tot:
                    subj_ranks.append(r["rank"])
            top = ranked[0]
            span = [top["tau_start"] * dur, top["tau_end"] * dur]
            in_span = [fi for fi in a_items if span[0] <= fi / fps <= span[1]]
            vis_in_span = [fi for fi in in_span if a_items[fi]["visibility"] == "visible"]
            if not vis_in_span:
                verdict = "REFERENCE_GT_UNOBSERVED"
                purity = None
            else:
                hits = sum(1 for fi in vis_in_span
                           if any(dd["frame_index"] == fi and dd["consistent"]
                                  for dd in top["anchor_eval"]["details"]))
                purity = round(hits / len(vis_in_span), 4)
                verdict = "SUBJECT_CORRECT" if purity == 1.0 else "SUBJECT_WRONG"
            per[method] = {
                "selected_top_tid": top["tid"],
                "selected_span_s": [round(span[0], 4), round(span[1], 4)],
                "anchors_in_span": in_span,
                "visible_anchors_in_span": vis_in_span,
                "not_visible_anchors_in_span": [fi for fi in in_span
                                                if a_items[fi]["visibility"] != "visible"],
                "reference_verdict": verdict,
                "reference_purity_at_anchors": purity,
                "best_subject_rank": min(subj_ranks) if subj_ranks else None,
                "n_subject_consistent_candidates": len(subj_ranks),
                "top5_contains_subject": any(r <= 5 for r in subj_ranks),
                "top10_contains_subject": any(r <= 10 for r in subj_ranks),
                "top20_contains_subject": any(r <= 20 for r in subj_ranks),
                "ranked_with_anchor_eval": ranked,
            }
        out["dives"][d] = per
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "reference_eval_v1.json").write_text(json.dumps(out, indent=1, sort_keys=True))
    print(json.dumps(out["dives"], indent=1)[:2000])
    print(f"-> {OUT_DIR/'reference_eval_v1.json'}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("replay")
    sub.add_parser("evaluate")
    args = ap.parse_args()
    if args.cmd == "replay":
        cmd_replay(args)
    else:
        cmd_evaluate(args)


if __name__ == "__main__":
    main()
