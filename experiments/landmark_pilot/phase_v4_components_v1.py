#!/usr/bin/env python3
"""V4 Phases A + B driver — component linkage + hypothesis-generation repair.

HURDLE_IDENTITY_COMPONENT_AND_TARGET_SELECTION_V4.

Per dive (ordinary HURDLE corpus + 2555 stress case, 524 excluded):
  1. candidate-complete tracklet graph (reused unchanged) + plausible set;
  2. OSNet embeddings from the provenanced host cache (0 re-extraction);
  3. GT-EVAL-ONLY: pure target fragments (>=50% GT-matched frames);
  4. Phase A: single-link BASELINE (P0 union-find), A0 mutual-kNN (k=3),
     A1 bounded-degree (deg=3, bridge margin 0.06) — component metrics;
  5. Phase B: pure-fragment adjacency audit (why fragments fail to
     assemble) + the ONE bounded repair (appearance-NN rollouts) evaluated
     as additional pool hypotheses (2341 pool-availability gate B1).

Outputs (host caches, JSON only):
  runs/hurdle_prototype_v4/COMPONENT_LINKAGE_V4.json
  runs/hurdle_prototype_v4/HYPOTHESIS_POOL_V4.json

Usage:
  python3 experiments/landmark_pilot/phase_v4_components_v1.py [dive ...]
"""

import json
import math
import sys
from pathlib import Path

import numpy as np

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))

import r5_tracklets_v1 as R5  # noqa: E402
import r5b_association_v1 as R5B  # noqa: E402
import v6_prototype_v1 as V  # noqa: E402
import phase_v4_linkage_v1 as L  # noqa: E402
import phase_v4_hypotheses_v1 as H  # noqa: E402
from v6_prototype_v1 import (  # noqa: E402
    ALL_DIVES, PRIMARY, EmbeddingCache, embed_tracklets, plausible_tracklets,
    tid_tracklet,
)
from phase_v3_prototype_select_v1 import eval_sel  # noqa: E402

V4_RUNS = BASE / "runs/hurdle_prototype_v4"
OUT_LINK = V4_RUNS / "COMPONENT_LINKAGE_V4.json"
OUT_POOL = V4_RUNS / "HYPOTHESIS_POOL_V4.json"

IOU_MIN = 0.30
CDIST_MAX = 0.05

MECHS = ("single_link_baseline", "mutual_knn_k3", "bounded_degree_d3")

# Phase A classification thresholds (frozen, generic; not per-dive tuned)
PURITY_PASS = 0.75       # target component purity to qualify as improved
MEGA_MAX = 0.60          # largest component fraction ceiling (anti-percolation)
IMPROVED_MIN_DIVES = 3   # aggregate: >=3 of 4 failing dives


def pure_target_marks(trk, hits, target_tids):
    """Pure target fragments: >=50% of the tracklet's frames GT-matched."""
    pure = [t for t in target_tids
            if hits[t] / max(1, tid_tracklet(trk, t).n_frames()) >= 0.5]
    return pure


def component_metrics(trk, comps, pure, tgt_any):
    """GT-EVAL-ONLY component quality metrics (Phase A2).

    pure: tracklets >=50% GT-matched (target fragments);
    tgt_any: all tracklets with any GT hit."""
    pure_set = set(pure)
    tgt_set = set(tgt_any)
    sizes = [sum(tid_tracklet(trk, t).n_frames() for t in m) for m in comps]
    total = sum(sizes)
    mega_frac = max(sizes) / total if total and sizes else 0.0
    tgt_comps = [m for m in comps if pure_set & set(m)]
    other = [m for m in comps if not (pure_set & set(m))]

    tgt_frames = sum(tid_tracklet(trk, t).n_frames()
                     for m in tgt_comps for t in m)
    pure_frames = sum(tid_tracklet(trk, t).n_frames()
                      for m in tgt_comps for t in m if t in pure_set)
    tgt_purity = pure_frames / tgt_frames if tgt_frames else None
    pure_all_frames = sum(tid_tracklet(trk, t).n_frames() for t in pure)
    frag_cov = pure_frames / pure_all_frames if pure_all_frames else None
    other_frames = sum(tid_tracklet(trk, t).n_frames()
                       for m in other for t in m)
    other_tgt_frames = sum(tid_tracklet(trk, t).n_frames()
                           for m in other for t in m if t in tgt_set)
    distr_purity = (other_frames - other_tgt_frames) / other_frames \
        if other_frames else None
    # largest contamination: distractor frames sharing a target component
    contam = max(
        (sum(tid_tracklet(trk, t).n_frames() for t in m if t not in pure_set)
         for m in tgt_comps), default=0)
    return {
        "n_components": len(comps),
        "n_target_components": len(tgt_comps),
        "largest_component_frac": round(mega_frac, 4),
        "target_component_purity": None if tgt_purity is None
        else round(tgt_purity, 4),
        "target_fragment_coverage": None if frag_cov is None
        else round(frag_cov, 4),
        "largest_distractor_contamination_frames": contam,
        "distractor_component_purity": None if distr_purity is None
        else round(distr_purity, 4),
        "target_components_contam_frac": round(
            contam / max(1, tgt_frames), 4) if tgt_frames else None,
    }


def classify(metrics):
    ok_purity = (metrics["target_component_purity"] is not None and
                 metrics["target_component_purity"] >= PURITY_PASS)
    ok_mega = metrics["largest_component_frac"] <= MEGA_MAX
    if ok_purity and ok_mega:
        return "COMPONENT_PURITY_IMPROVED"
    return "COMPONENT_IDENTITY_STILL_COLLAPSED"


def adjacency_audit(trk, pure, embs, off, fps):
    """Phase B audit: why adjacent pure target fragments fail to assemble.
    GT identifies WHICH fragments are the target; every feature recorded
    is GT-free machinery evidence (gates, gaps, appearance)."""
    frs = sorted(pure, key=lambda t: tid_tracklet(trk, t).first())
    rows = []
    for a_t, b_t in zip(frs, frs[1:]):
        a, b = tid_tracklet(trk, a_t), tid_tracklet(trk, b_t)
        g = L._compat_pair_gate(a, b, off, fps)
        gap_s = max(0.0, (b.first() - a.last()) / fps,
                    (a.first() - b.last()) / fps)
        disc = None if g is None else g["disc"]
        cos = None
        if a_t in embs and b_t in embs:
            cos = round(float(np.dot(embs[a_t], embs[b_t])), 4)
        static_pair = None if g is None else g["static_pair"]
        thr = None if static_pair is None else \
            (R5B.APP_STATIC_MERGE if static_pair else R5B.APP_MERGE_MIN)
        rows.append({
            "a": a_t, "b": b_t,
            "gap_s": round(gap_s, 3),
            "disc": None if disc is None else round(disc, 4),
            "cos": cos,
            "spatial_temporal_ok": g is not None,
            "appearance_floor_ok": None if thr is None
            else (cos is not None and cos >= thr),
            "would_link_r5b": g is not None and thr is not None and
            cos is not None and cos >= thr,
            "velocity_gate_ok": _velocity_gate_ok(a, b, off, fps),
        })
    return rows


def _velocity_gate_ok(a, b, off, fps):
    """Would the pair survive the R5-A tracklet-formation velocity gates?
    (Displacement across the gap must fit the human-velocity ceiling.)"""
    gap_fi = max(1, b.first() - a.last())
    dt = gap_fi / fps
    ba = a.boxes[a.last()]
    bb = b.boxes[b.first()]
    dcy = abs(bb.cy - ba.cy)
    dcx = abs(bb.cx - ba.cx)
    return bool(dcy / dt <= R5.V_MAX_CY_S + R5.JITTER_C and
                dcx / dt <= R5.V_MAX_CX_S + R5.JITTER_C)


def appearance_rollouts(trk, embs, cache, dive_id, dive_doc):
    """ONE bounded repair: appearance-NN rollouts from every prep anchor."""
    n = trk["n"]
    rel_arrs = [trk["arrs"][fi] - trk["off"][fi] for fi in range(n)]
    anchors = R5.prep_anchors(trk["tracklets"], trk["off"], trk["fps"])
    cands = trk["cands"]
    plaus = plausible_tracklets(trk)

    def emb_fn(fi, k):
        vec = cache.get((dive_id, fi, k))
        return vec

    out = []
    for a in anchors:
        tr = a["tr"]
        pos_fi = tr.starts[a["i1"]]
        k0 = R5B._candidate_index(tr, pos_fi, cands)
        if k0 is None or (dive_id, pos_fi, k0) not in cache.data:
            continue
        cmap, diag = H.appearance_rollout(a, trk, rel_arrs, emb_fn, k0)
        if cmap is None:
            out.append({"anchor_tid": tr.tid, "ok": False, "diag": diag})
            continue
        sel = [None] * n
        for fi, k in cmap.items():
            c = cands[fi][k]
            sel[fi] = {"cx": c.cx, "cy": c.cy, "bw": c.bw, "bh": c.bh,
                       "conf": c.conf}
        out.append({"anchor_tid": tr.tid, "ok": True, "diag": diag,
                    "sel": sel, "n_frames": len(cmap)})
    return out


def main():
    V4_RUNS.mkdir(parents=True, exist_ok=True)
    fc, chains = V.load_corpus()
    cache = EmbeddingCache()
    link_doc = {
        "label": "COMPONENT_LINKAGE_V4",
        "packet": "HURDLE_IDENTITY_COMPONENT_AND_TARGET_SELECTION_V4",
        "gt_usage": "pure-target marking + evaluation ONLY",
        "mechanisms": {
            "single_link_baseline": "unchanged P0 union-find (negative control)",
            "mutual_knn_k3": "A0 reciprocal top-3 linkage (K_MNN=3)",
            "bounded_degree_d3": "A1 degree cap 3 + bridge margin 0.06",
        },
        "dives": {},
    }
    pool_doc = {
        "label": "HYPOTHESIS_POOL_V4",
        "packet": "HURDLE_IDENTITY_COMPONENT_AND_TARGET_SELECTION_V4",
        "gt_usage": "evaluation section ONLY",
        "repair": "appearance-NN rollout (ONE bounded hypothesis generator)",
        "dives": {},
    }

    args = [a for a in sys.argv[1:] if a in ALL_DIVES] or ALL_DIVES
    for did in args:
        print("==", did, flush=True)
        dive_doc = fc["dives"][did]
        trk = V.dive_arrays(dive_doc)
        plaus = plausible_tracklets(trk)
        embs = embed_tracklets(did, dive_doc, trk, cache, plaus)
        tgt_tids, hits, gt = V.mark_target_tracklets(
            did, dive_doc, chains["dives"][did], trk)
        pure = pure_target_marks(trk, hits, tgt_tids)
        pts_by_pos = [round(f["pts_s"], 4) for f in trk["frames"]]

        view = V.trk_view(trk, list(plaus.keys()))
        edges = L.compatible_edge_list(view, embs)
        mechs = {}
        for name, fn in (
            ("single_link_baseline", L.single_link_components),
            ("mutual_knn_k3", lambda t, e: L.mutual_knn_components(t, e, 3)),
            ("bounded_degree_d3", L.bounded_degree_components),
        ):
            comps = fn(view, edges)
            met = component_metrics(trk, comps, pure, tgt_tids)
            met["n_edges"] = len(edges)
            # eval the target-bearing component union (GT-EVAL-ONLY)
            pure_set = set(pure)
            tgt_comp = next((m for m in comps if pure_set & set(m)), None)
            if tgt_comp is not None:
                bm = {}
                for t in tgt_comp:
                    tr = tid_tracklet(trk, t)
                    for fi in tr.starts:
                        b = tr.boxes[fi]
                        if fi not in bm:
                            bm[fi] = {"cx": b.cx, "cy": b.cy, "bw": b.bw,
                                      "bh": b.bh, "conf": b.conf}
                met["target_component_eval"] = eval_sel(bm, gt, pts_by_pos)
            met["verdict"] = classify(met)
            mechs[name] = met
            print(f"  {name}: comps {met['n_components']} "
                  f"mega {met['largest_component_frac']} "
                  f"purity {met['target_component_purity']} "
                  f"-> {met['verdict']}", flush=True)
        link_doc["dives"][did] = {
            "n_plausible": len(plaus), "n_pure_target_fragments": len(pure),
            "n_gt_frames": len(gt), "mechanisms": mechs,
        }

        # ---- Phase B: adjacency audit + rollouts ----
        audit = adjacency_audit(trk, pure, embs, trk["off"], trk["fps"])
        n_link_r5b = sum(1 for r in audit if r["would_link_r5b"])
        n_vel_fail = sum(1 for r in audit if not r["velocity_gate_ok"])
        n_app_fail = sum(1 for r in audit
                         if r["appearance_floor_ok"] is False)
        n_gap_fail = sum(1 for r in audit if r["gap_s"] > R5B.MERGE_GAP_MAX_S)
        rollouts = appearance_rollouts(trk, embs, cache, did, dive_doc)
        ro_rows = []
        for r in rollouts:
            if not r["ok"]:
                ro_rows.append({"anchor_tid": r["anchor_tid"], "ok": False,
                                "diag": r["diag"]})
                continue
            ev = eval_sel(r["sel"], gt, pts_by_pos)
            ro_rows.append({"anchor_tid": r["anchor_tid"], "ok": True,
                            "n_frames": r["n_frames"], "eval": ev})
        best_ro = max((x["eval"].get("per_frame_correct", 0.0)
                       for x in ro_rows if x.get("ok")), default=0.0)
        pool_doc["dives"][did] = {
            "audit": {
                "n_adjacent_pairs": len(audit),
                "pairs": audit if did == "2341" else audit[:12],
                "n_would_link_r5b": n_link_r5b,
                "n_velocity_gate_fail": n_vel_fail,
                "n_appearance_floor_fail": n_app_fail,
                "n_gap_fail": n_gap_fail,
            },
            "rollouts": [
                {k: v for k, v in r.items() if k != "sel"} for r in ro_rows],
            "best_rollout_pf": round(best_ro, 4),
        }
        print(f"  audit: link {n_link_r5b}/{len(audit)} "
              f"vel_fail {n_vel_fail} app_fail {n_app_fail} "
              f"gap_fail {n_gap_fail}; best rollout pf {best_ro}", flush=True)

    cache.save()
    OUT_LINK.write_text(json.dumps(link_doc, indent=1) + "\n")
    OUT_POOL.write_text(json.dumps(pool_doc, indent=1) + "\n")
    print("wrote", OUT_LINK, OUT_POOL)


if __name__ == "__main__":
    main()
