#!/usr/bin/env python3
"""Phase C/D/E/G (HURDLE_TARGET_IDENTITY_V3) — prototype-selection eval.

Three GT-free methods, each a distinct causal idea (bounded, no grid):
  P0  appearance-consensus identity clusters (OSNet similarity graph over
      the plausible tracklet set) + whole-clip targetness selection;
  P1  multi-hypothesis search over the frozen R5-A (anchor, departure)
      machinery (<= 12 hypotheses) + GT-free whole-clip path quality;
  P2  dual-phase consensus variant of P1: an acceptable identity must be
      explainable from BOTH a stable pre-action segment and a high-motion
      segment (generic trajectory properties; no GT phase timestamps).

All methods operate on the full production-equivalent clip; GT chains are
consulted ONLY by the evaluation section. Deterministic.

Outputs:
  runs/hurdle_prototype_v3/V6_EVAL_V3.json

Usage:
  caffeinate -i -s .venv-reid/bin/python experiments/landmark_pilot/phase_v3_prototype_select_v1.py [dive ...]
"""

import json
import math
import sys
from pathlib import Path

import numpy as np

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))

import r5_tracklets_v1 as R5  # noqa: E402
import v6_prototype_v1 as V  # noqa: E402
from v6_prototype_v1 import (  # noqa: E402
    ALL_DIVES, PRIMARY, EmbeddingCache, cluster_features,
    embed_tracklets, enumerate_r5a_hypotheses, hypothesis_path_quality,
    p0_identity_clusters, plausible_tracklets, tid_tracklet, trk_view,
)

OUT = BASE / "runs/hurdle_prototype_v3/V6_EVAL_V3.json"
IOU_MIN = 0.30
CDIST_MAX = 0.05


def iou(a, b):
    ax1, ay1 = a[0] - a[2] / 2, a[1] - a[3] / 2
    ax2, ay2 = a[0] + a[2] / 2, a[1] + a[3] / 2
    bx1, by1 = b[0] - b[2] / 2, b[1] - b[3] / 2
    bx2, by2 = b[0] + b[2] / 2, b[1] + b[3] / 2
    ix = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    iy = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = ix * iy
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def match(c, g):
    cd = math.hypot(c[0] - g[0], c[1] - g[1])
    return iou(c, g) >= IOU_MIN or cd <= CDIST_MAX


def eval_sel(sel, gt, pts_by_pos):
    """sel: per-position dict/list of boxes or None. GT-EVAL-ONLY."""
    flags = []
    covered = 0
    for fi, p in enumerate(pts_by_pos):
        g = gt.get(p)
        if g is None:
            continue
        box = sel[fi] if isinstance(sel, list) else sel.get(fi)
        ok = False
        if box is not None:
            ok = match((box["cx"], box["cy"], box["bw"], box["bh"]), g)
            covered += ok
        flags.append(ok)
    n = len(flags)
    if n == 0:
        return {"n_eval_frames": 0}
    longest = cur = 0
    for f in flags:
        cur = cur + 1 if not f else 0
        longest = max(longest, cur)
    switches = sum(1 for a, b in zip(flags, flags[1:]) if a != b)
    return {
        "n_eval_frames": n,
        "per_frame_correct": round(sum(flags) / n, 4),
        "cond_correct": round(covered / n, 4),
        "target_coverage": round(sum(
            1 for fi, p in enumerate(pts_by_pos)
            if p in gt and (sel[fi] if isinstance(sel, list)
                            else sel.get(fi)) is not None) / n, 4),
        "longest_wrong_run": longest,
        "switch_count": switches,
        "null_frac": round(sum(
            1 for fi, p in enumerate(pts_by_pos)
            if p in gt and (sel[fi] if isinstance(sel, list)
                            else sel.get(fi)) is None) / n, 4),
    }


def main():
    fc, chains = V.load_corpus()
    cache = EmbeddingCache()
    args = [a for a in sys.argv[1:] if a in ALL_DIVES] or ALL_DIVES
    doc = {"label": "V6_EVAL_V3",
           "packet": "HURDLE_TARGET_IDENTITY_V3",
           "gt_usage": "evaluation section ONLY",
           "methods": {
               "P0": "appearance-consensus clusters + targetness",
               "P1": "multi-hypothesis R5-A enumeration + path quality",
               "P2": "P1 + dual-phase (prep AND mover) consensus"},
           "dives": {}}

    for did in args:
        print("==", did, flush=True)
        dive_doc = fc["dives"][did]
        trk = V.dive_arrays(dive_doc)
        plaus = plausible_tracklets(trk)
        embs = embed_tracklets(did, dive_doc, trk, cache, plaus)
        pts_by_pos = [round(f["pts_s"], 4) for f in trk["frames"]]
        tgt_tids, hits, gt = V.mark_target_tracklets(
            did, dive_doc, chains["dives"][did], trk)

        # ---- P0 ----
        view = trk_view(trk, list(plaus.keys()))
        clusters = p0_identity_clusters(view, embs, trk["fps"])
        cluster_info = []
        for members in clusters:
            feat = cluster_features(trk, members, embs)
            if feat is None:
                continue
            bm = {}
            for t in members:
                tr = tid_tracklet(trk, t)
                for fi in tr.starts:
                    if fi not in bm:
                        bm[fi] = {"cx": tr.boxes[fi].cx,
                                  "cy": tr.boxes[fi].cy,
                                  "bw": tr.boxes[fi].bw,
                                  "bh": tr.boxes[fi].bh,
                                  "conf": tr.boxes[fi].conf}
            feat["eval"] = eval_sel(bm, gt, pts_by_pos)
            cluster_info.append(feat)
        cluster_info.sort(key=lambda c: (-c["targetness"], c["members"][0]))
        p0 = cluster_info[0] if cluster_info else None
        # target rank of the correct cluster (EVAL-ONLY): how many
        # clusters rank above the cluster with best per-frame correct?
        p0_target_rank = None
        if cluster_info:
            best_ev = max(range(len(cluster_info)),
                          key=lambda i: cluster_info[i]["eval"]
                          .get("per_frame_correct", 0))
            p0_target_rank = best_ev

        # ---- P1/P2: enumerate R5-A hypotheses ----
        hyps = enumerate_r5a_hypotheses(trk)
        hyp_rows = []
        for rank, h in enumerate(hyps):
            feat = hypothesis_path_quality(
                trk, h, embs, cache=cache, dive_id=did, dive_doc=dive_doc)
            if feat is None:
                continue
            feat["hyp_rank"] = rank
            # GT-free dual-phase consensus (P2): prep AND mover evidence
            prep_phase = (feat["prep_dur_s"] or 0) >= 0.8
            mover_phase = feat["exc_y"] >= R5B_EXC_MIN
            feat["dual_phase"] = bool(prep_phase and mover_phase)
            sel = [None] * trk["n"]
            for fi, box in h["frames_map"].items():
                sel[fi] = box
            feat["eval"] = eval_sel(sel, gt, pts_by_pos)
            hyp_rows.append(feat)
        p1 = max(hyp_rows, key=lambda r: r["path_quality"]) \
            if hyp_rows else None
        # P2: restrict to dual-phase hypotheses (fall back to all if none)
        dual = [r for r in hyp_rows if r["dual_phase"]]
        p2 = max(dual, key=lambda r: r["path_quality"]) if dual else p1

        doc["dives"][did] = {
            "n_plausible": len(plaus), "n_clusters": len(cluster_info),
            "n_hypotheses": len(hyp_rows),
            "P0": None if not p0 else {
                "targetness": p0["targetness"],
                "app_mean": p0["app_mean"],
                "n_tracklets": p0["n_tracklets"],
                "eval": p0["eval"],
                "correct_cluster_target_rank": p0_target_rank},
            "P1": None if not p1 else {
                "feat": {k: v for k, v in p1.items() if k != "eval"},
                "eval": p1["eval"]},
            "P2": None if not p2 else {
                "feat": {k: v for k, v in p2.items() if k != "eval"},
                "eval": p2["eval"]},
            "hypotheses_top": [
                {k: v for k, v in r.items() if k != "eval"}
                for r in sorted(hyp_rows,
                                key=lambda r: -r["path_quality"])[:6]],
        }
        for name, r in (("P0", p0), ("P1", p1), ("P2", p2)):
            if r is None:
                print(f"  {name}: none")
                continue
            ev = r["eval"]
            print(f"  {name}: pf {ev.get('per_frame_correct')} "
                  f"lw {ev.get('longest_wrong_run')} "
                  f"cov {ev.get('target_coverage')} "
                  f"rank {r.get('hyp_rank', p0_target_rank)}", flush=True)

    cache.save()
    OUT.write_text(json.dumps(doc, indent=1) + "\n")
    print("wrote", OUT)


R5B_EXC_MIN = 0.12
R5B_EXC = R5B_EXC_MIN

if __name__ == "__main__":
    main()
