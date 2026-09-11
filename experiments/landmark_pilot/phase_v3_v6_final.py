#!/usr/bin/env python3
"""V6_GT_FREE_IDENTITY_ASSOCIATION — final development evaluation
(HURDLE_TARGET_IDENTITY_V3, Phases C/D/E/G/H/I).

Candidate generators (all full-clip, GT-free, deterministic):
  A. appearance-guided departure rollouts from EVERY frozen R5-A prep
     anchor (velocity gates unchanged; OSNet prototype steering with the
     frozen DEP_APP_* terms);
  B. P0 appearance-consensus identity clusters (diagnostic; joins the pool
     as whole-cluster candidates);
  C. the frozen detector op-point top-confidence trajectory (D5 top-1 at
     op 0.05 — a GT-free hypothesis class competing under the same
     selector; protects the already-good control 2169).

All candidates are scored by the SAME frozen v6_path_quality; the top path
is V6's selection. P2 dual-phase consensus is reported per hypothesis.

Baselines: D5 op top-1 (from the frozen traj cache), historical R4, R5-A,
R5-B (from committed artifacts).

Outputs:
  runs/hurdle_prototype_v3/V6_FINAL_V3.json

Usage:
  caffeinate -i -s .venv-reid/bin/python experiments/landmark_pilot/phase_v3_v6_final.py [dive ...]
"""

import json
import math
import signal
import sys
import time
from pathlib import Path

import numpy as np

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))

import r5_tracklets_v1 as R5  # noqa: E402
import r5b_association_v1 as R5B  # noqa: E402
import v6_prototype_v1 as V  # noqa: E402
from v6_prototype_v1 import (  # noqa: E402
    ALL_DIVES, PRIMARY, EmbeddingCache, V6Q, cluster_features,
    embed_tracklets, plausible_tracklets, p0_identity_clusters,
    tid_tracklet, trk_view, v6_path_quality,
)
import phase_v3_sweep_v1 as SW  # noqa: E402
import phase_v3_prototype_select_v1 as PS  # noqa: E402

OUT = BASE / "runs/hurdle_prototype_v3/V6_FINAL_V3.json"
TRAJ_CACHE = BASE / "docs/science/DEV_HURDLE_TRAJ_CACHE_V2.json"

HIST = {
    "1040": {"d5_op_top1": 0.1056, "r4_hist": 0.000, "r5a": 0.0062, "r5b": 0.0},
    "2169": {"d5_op_top1": 0.9631, "r4_hist": 0.912, "r5a": 0.000, "r5b": 0.0},
    "2341": {"d5_op_top1": 0.0220, "r4_hist": 0.000, "r5a": 0.000, "r5b": 0.0513},
    "2353": {"d5_op_top1": 0.0049, "r4_hist": 0.000, "r5a": 0.3650, "r5b": 0.0},
    "2541": {"d5_op_top1": 0.1490, "r4_hist": 0.153, "r5a": 0.0992, "r5b": 0.0},
    "2555": {"d5_op_top1": 0.518, "r4_hist": None, "r5a": 0.0, "r5b": 0.0},
}


def recompute_freeze_gate(doc):
    def pf(did):
        c = doc["dives"][did].get("selected")
        return None if not c else c["eval"].get("per_frame_correct")

    def hist(did, key):
        h = doc["dives"][did].get("historical") or {}
        return h.get(key)

    failing = ["1040", "2341", "2353", "2541"]
    per_dive = {}
    materially_improved = 0
    for did in failing:
        v6 = pf(did)
        d5 = hist(did, "d5_op_top1")
        ok = v6 is not None and v6 >= 0.10 and d5 is not None and v6 > d5
        per_dive[did] = {
            "v6_pf": v6, "hist_d5": d5, "materially_improved": bool(ok)}
        materially_improved += int(ok)
    d2169 = pf("2169")
    h2169 = hist("2169", "d5_op_top1")
    preserved = bool(d2169 is not None and h2169 is not None
                     and d2169 >= 0.9 * h2169)
    problems = []
    if materially_improved < 3:
        problems.append(
            f"materially_improved {materially_improved}/4 < required 3")
    if not preserved:
        problems.append("2169 not preserved by V6 selection")
    return {
        "verdict": "GATE_FAILED" if problems else "GATE_PASSED",
        "criteria": {
            "materially_improved_required": 3,
            "materially_improved": materially_improved,
            "preserve_2169": preserved,
        },
        "per_dive": per_dive,
        "problems": problems,
        "diagnosis": "candidate-pool scorer gameable (see report)",
    }


def main():
    signal.alarm(8 * 3600)
    fc, chains = V.load_corpus()
    cache = EmbeddingCache()
    traj = json.loads(TRAJ_CACHE.read_text())
    args = [a for a in sys.argv[1:] if a in ALL_DIVES] or ALL_DIVES
    doc_p = OUT
    if doc_p.exists():
        doc = json.loads(doc_p.read_text())
        doc.setdefault("dives", {})
    else:
        doc = {"label": "V6_FINAL_V3",
               "packet": "HURDLE_TARGET_IDENTITY_V3",
               "selector": "V6_GT_FREE_IDENTITY_ASSOCIATION",
               "gt_usage": "evaluation section ONLY",
               "candidate_classes": ["anchor_appearance_guided_rollout",
                                     "p0_appearance_consensus_cluster",
                                     "d5_op_top1_trajectory"],
               "scorer": "hypothesis_path_quality (frozen; validated on "
                         "1040) + per-class diagnostics",
               "primary_dives": PRIMARY,
               "freeze_gate": {},
               "dives": {}}
    for did in args:
        t0 = time.time()
        print("==", did, flush=True)
        dive_doc = fc["dives"][did]
        trk = V.dive_arrays(dive_doc)
        plaus = plausible_tracklets(trk)
        embs = embed_tracklets(did, dive_doc, trk, cache, plaus)
        pts_by_pos = [round(f["pts_s"], 4) for f in trk["frames"]]
        tgt_tids, hits, gt = V.mark_target_tracklets(
            did, dive_doc, chains["dives"][did], trk)

        # ---- class A: appearance-guided anchor rollouts ----
        rows = SW.sweep_dive(did, dive_doc, chains["dives"][did], trk, embs,
                             cache)
        cands = []
        for r in rows:
            fm = r["feat"]
            sel = r["sel"]
            fis = [i for i, b in enumerate(sel) if b is not None]
            if len(fis) < 3:
                continue
            q = fm["path_quality"]  # hypothesis_path_quality (validated)
            prep_phase = bool((fm["prep_dur_s"] or 0) >= 0.8)
            mover_phase = bool(fm["exc_y"] >= 0.12)
            cands.append({"class": "anchor_rollout", "q": q, "sel": sel,
                          "feat": fm, "dual_phase": prep_phase and mover_phase,
                          "anchor_tid": r["anchor_tid"]})
        print("  anchor_rollout candidates:", len(cands), flush=True)

        # ---- class B: P0 clusters (diagnostic) ----
        view = trk_view(trk, list(plaus.keys()))
        clusters = p0_identity_clusters(view, embs, trk["fps"])
        n_cl = 0
        for c in clusters[:6]:
            cf = cluster_features(trk, c, embs)
            if cf is None:
                continue
            bm = {}
            for t in c:
                tr = tid_tracklet(trk, t)
                for fi in tr.starts:
                    if fi not in bm:
                        bm[fi] = {"cx": tr.boxes[fi].cx, "cy": tr.boxes[fi].cy,
                                  "bw": tr.boxes[fi].bw, "bh": tr.boxes[fi].bh,
                                  "conf": tr.boxes[fi].conf}
            q = cf["targetness"]
            cands.append({"class": "p0_cluster", "q": q, "sel": bm,
                          "feat": {"members_n": cf["n_tracklets"],
                                   "life_s": cf["life_s"],
                                   "exc_y": cf["exc_y"],
                                   "app_mean": cf["app_mean"]},
                          "dual_phase": None, "anchor_tid": None})
            n_cl += 1

        # ---- class C: D5 op top-1 trajectory (frozen cache) ----
        if did in traj["per_dive"]:
            frames = traj["per_dive"][did]["frames"]
            d5_sel = {}
            for i, f in enumerate(frames):
                if f.get("cy") is not None:
                    d5_sel[i] = {"cx": f["cx"], "cy": f["cy"],
                                 "bw": f["bx_right"] - f["bx_left"],
                                 "bh": f["bh"], "conf": f["conf"]}
            pseudo = {"score": 0.0, "feats": {"prep_dur_s": None,
                      "prep_level": None, "peak_v": None, "rest_ratio": None,
                      "entry": 0.0}, "frames_map": d5_sel, "anchor_tid": None,
                      "seed_fi": 0, "anchor": None}
            f5 = V.hypothesis_path_quality(trk, pseudo, embs, cache=None,
                                           dive_id=did, dive_doc=dive_doc)
            q = f5["path_quality"] if f5 is not None else None
            cands.append({"class": "d5_op_top1", "q": q, "sel": d5_sel,
                          "feat": {"coverage": round(len(d5_sel) / trk["n"], 4)},
                          "dual_phase": None, "anchor_tid": None})

        # ---- selection ----
        def tie_key(c):
            return (-c["q"], c["class"],
                    c["anchor_tid"] if c["anchor_tid"] is not None else 10 ** 9)
        cands.sort(key=tie_key)
        best = cands[0] if cands else None
        best_eval = SW.eval_sel(best["sel"], gt, pts_by_pos) if best else None
        # per-class best ranks (EVAL-ONLY diagnostic)
        for c in cands:
            c["eval"] = SW.eval_sel(c["sel"], gt, pts_by_pos)
        diag = {}
        for cls in ("anchor_rollout", "p0_cluster", "d5_op_top1"):
            sub = [c for c in cands if c["class"] == cls]
            if not sub:
                continue
            be = max(sub, key=lambda c: c["eval"]["per_frame_correct"])
            bpos = [i for i, c in enumerate(cands) if c is be][0]
            diag[cls] = {"best_pf": be["eval"]["per_frame_correct"],
                         "best_q_rank": bpos,
                         "n_candidates": len(sub)}
        doc["dives"][did] = {
            "n_candidates": len(cands),
            "selected": None if not best else {
                "class": best["class"], "q": best["q"],
                "anchor_tid": best["anchor_tid"],
                "feat": {k: v for k, v in best["feat"].items()
                         if k in ("prep_dur_s", "prep_level", "exc_y",
                                  "coverage", "null_frac", "rest_ratio",
                                  "app_mean", "entry", "ends_early",
                                  "jumps", "start_frac")},
                "eval": best_eval,
            },
            "class_diag": diag,
            "historical": HIST.get(did, {}),
            "elapsed_s": round(time.time() - t0, 1),
        }
        if best:
            print("  selected:", best["class"], "anchor", best["anchor_tid"],
                  "q", best["q"], "pf", best_eval["per_frame_correct"],
                  "lw", best_eval["longest_wrong_run"], flush=True)

    cache.save()
    if all(k in doc["dives"] for k in ALL_DIVES):
        doc["freeze_gate"] = recompute_freeze_gate(doc)
    OUT.write_text(json.dumps(doc, indent=1) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
