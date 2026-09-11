#!/usr/bin/env python3
"""Phase B + B1 (HURDLE_TARGET_IDENTITY_V3).

For every dive:
  1. build the candidate-complete tracklet graph (reused, unchanged);
  2. embed every plausible tracklet (one-time OSNet extraction, cached);
  3. GT-EVAL-ONLY: mark which tracklets are target-bearing;
  4. reproduce the R5-A / R5-B GT-free choices and compare against the
     oracle (union of target-bearing tracklets);
  5. classify WHY the correct component loses (distractor taxonomy);
  6. write the GT-free component feature table (top components by size,
     excursion, and ALL target-bearing ones, GT-labelled post-hoc).

Outputs (host caches):
  runs/hurdle_prototype_v3/ORACLE_GAP_V3.json
  runs/hurdle_prototype_v3/COMPONENT_FEATURES_V1.json

Usage:
  caffeinate -i -s .venv-reid/bin/python experiments/landmark_pilot/phase_v3_oracle_gap_v1.py
"""

import json
import sys
from pathlib import Path

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))

import r5_tracklets_v1 as R5  # noqa: E402
import r5b_association_v1 as R5B  # noqa: E402
import v6_prototype_v1 as V  # noqa: E402
from v6_prototype_v1 import (  # noqa: E402
    ALL_DIVES, EmbeddingCache, associate_all, cluster_features,
    component_box_map, embed_tracklets, gt_match, plausible_tracklets,
    tid_tracklet, tracklet_features,
)

OUT_GAP = BASE / "runs/hurdle_prototype_v3/ORACLE_GAP_V3.json"
OUT_FEAT = BASE / "runs/hurdle_prototype_v3/COMPONENT_FEATURES_V1.json"


def classify_dive(tstats, chosen_feat, chosen_target_frames):
    """Failure taxonomy (Phase B). GT only identifies WHICH component the
    selector should have chosen; the features used are GT-free."""
    frag = tstats["n_pure_fragments"] >= 5 and \
        tstats["pure_life_s_median"] < 0.8 * tstats["n_gt_frames"] / max(
            tstats["n_pure_fragments"], 1)
    out = []
    if chosen_feat is None:
        out.append("NO_CLEAR_COMPONENT")
        if frag:
            out.append("TARGET_FRAGMENTED")
        return out
    mv = chosen_feat.get("med_v_cy_s", 0.0) or chosen_feat.get("peak_v_cy_s", 0.0)
    if chosen_feat["static"] and (chosen_feat["life_frac"] > 0.6 or
                                  chosen_feat["life_s"] > 3.0):
        out.append("STATIC_DISTRACTOR_DOMINATES")
    elif chosen_feat["life_s"] < 2.5 and mv > 0.45:
        out.append("FAST_MOVER_DOMINATES")
    elif not chosen_feat["static"] and chosen_feat["life_s"] > 4.0 and \
            chosen_feat["exc_y"] >= R5B.MOVER_EXCURSION_MIN:
        out.append("OTHER_PERSON_DOMINATES")
    else:
        out.append("NO_CLEAR_COMPONENT")
    if chosen_target_frames == 0 and frag:
        out.append("TARGET_FRAGMENTED")
    elif 0 < chosen_target_frames < 0.5 * tstats["pure_cov_frac_of_gt"]:
        out.append("PROTOTYPE_DRIFT")
    return out


def tgt_frames_of(sel, gt, pts_by_pos):
    """sel: per-position dict or list of boxes (or None)."""
    n = 0
    items = sel.items() if isinstance(sel, dict) else enumerate(sel)
    for fi, box in items:
        if box is None:
            continue
        g = gt.get(pts_by_pos[fi])
        if g is None:
            continue
        if gt_match((box["cx"], box["cy"], box["bw"], box["bh"]), g):
            n += 1
    return n


def main():
    fc, chains = V.load_corpus()
    cache = EmbeddingCache()
    gap_doc = {"label": "ORACLE_GAP_V3",
               "packet": "HURDLE_TARGET_IDENTITY_V3",
               "gt_usage": "marks the target component for diagnosis ONLY; "
                           "all descriptors and selections are GT-free",
               "dives": {}}
    feat_doc = {"label": "COMPONENT_FEATURES_V1",
                "packet": "HURDLE_TARGET_IDENTITY_V3",
                "descriptor_set": "GT-free; GT label only on gt_frames",
                "dives": {}}

    for did in ALL_DIVES:
        print("==", did, flush=True)
        trk = V.dive_arrays(fc["dives"][did])
        plaus = plausible_tracklets(trk)
        embs = embed_tracklets(did, fc["dives"][did], trk, cache, plaus)
        tgt_tids, hits, gt = V.mark_target_tracklets(
            did, fc["dives"][did], chains["dives"][did], trk)

        # ---- B1: GT-free tracklet feature table (bounded) ----
        rows = [tracklet_features(tr, trk["off"], trk["fps"])
                for tr in plaus.values()]
        for r in rows:
            r["gt_frames"] = hits[r["tid"]]  # EVAL-ONLY label
        keep = {r["tid"] for r in
                sorted(rows, key=lambda r: -r["n_frames"])[:200]}
        keep |= set(tgt_tids)
        keep |= {r["tid"] for r in
                 sorted(rows, key=lambda r: -r["exc_y"])[:50]}
        table = {str(r["tid"]): r for r in rows if r["tid"] in keep}
        feat_doc["dives"][did] = {
            "n_plausible": len(plaus),
            "n_kept": len(keep),
            "target_tids": tgt_tids,
            "tracklets": table,
        }

        # ---- oracle component ----
        best_cov = max((V.tid_tracklet(trk, t).n_frames()
                        for t in tgt_tids), default=0)
        # purity over ALL tracklets (not just plausible): a tracklet is a
        # target fragment if >=50% of its frames are GT-matched
        pure = [t for t in tgt_tids
                if hits[t] / max(1, V.tid_tracklet(trk, t).n_frames()) >= 0.5]
        pure_cov = sum(V.tid_tracklet(trk, t).n_frames() for t in pure)
        pure_med_life = sorted(
            (V.tid_tracklet(trk, t).last() - V.tid_tracklet(trk, t).first())
            / trk["fps"] for t in pure)
        tstats = {
            "n_gt_frames": len(gt),
            "n_target_tracklets": len(tgt_tids),
            "n_pure_fragments": len(pure),
            "pure_cov_frac_of_gt": round(pure_cov / max(1, len(gt)), 4),
            "pure_life_s_median": round(
                pure_med_life[len(pure_med_life) // 2], 3) if pure else 0.0,
            "pure_life_s_max": round(
                pure_med_life[-1], 3) if pure else 0.0,
            "max_target_tracklet_cov": round(
                best_cov / max(1, len(gt)), 4),
            "best_target_cov_frames": best_cov,
            "target_tracklet_life_s": [round(
                (V.tid_tracklet(trk, t).last() - V.tid_tracklet(trk, t).first())
                / trk["fps"], 2) for t in tgt_tids[:20]],
        }

        pts_by_pos = [round(f["pts_s"], 4) for f in trk["frames"]]

        # ---- reproduce R5-A choice ----
        r5a_per_frame, r5a_diag = R5.select_trajectory(
            trk["tracklets"], trk["cands"], trk["arrs"], trk["fps"], trk["n"])
        r5a_tid = r5a_diag.get("anchor_tid")
        r5a_feat = None
        if r5a_tid is not None:
            r5a_tr = V.tid_tracklet(trk, r5a_tid)
            if r5a_tr is not None:
                r5a_feat = tracklet_features(r5a_tr, trk["off"], trk["fps"])
        r5a_tgt = tgt_frames_of(r5a_per_frame, gt, pts_by_pos)

        # ---- reproduce R5-B choice (exact R5-B pool semantics) ----
        def r5b_pool_mask(tr, tid, is_anchor):
            rel = [(tr.boxes[fi].cx - trk["off"][fi][0],
                    tr.boxes[fi].cy - trk["off"][fi][1]) for fi in tr.starts]
            exc = max(max(y for _, y in rel) - min(y for _, y in rel),
                      max(x for x, _ in rel) - min(x for x, _ in rel))
            return exc >= R5B.MOVER_EXCURSION_MIN or is_anchor

        pool, comps = associate_all(trk, embs, pool_mask=r5b_pool_mask)
        best = None
        for comp in comps:
            if not comp["box_at"] or len(comp["box_at"]) < 3:
                continue
            box_map = component_box_map(trk, pool, comp)
            fis = sorted(box_map)
            cys = [comp["box_at"][fi][1] for fi in fis]   # flow-relative
            cis = [box_map[fi]["conf"] for fi in fis]
            score, feats = R5B.dive_shape_score(fis, cys, cis, trk["fps"],
                                                trk["n"])
            if comp["has_anchor"]:
                score += R5.W_PREP_DUR * 0.5
            if best is None or score > best[0]:
                best = (score, feats, comp)
        r5b_feat = None
        r5b_tgt = 0
        r5b_tids = []
        if best is not None:
            comp = best[2]
            r5b_tids = [pool[m]["tr"].tid for m in comp["members"]]
            r5b_feat = cluster_features(trk, r5b_tids, embs)
            r5b_tgt = tgt_frames_of(component_box_map(trk, pool, comp), gt, pts_by_pos)

        classes = classify_dive(tstats, r5b_feat or r5a_feat, r5b_tgt)
        gap_doc["dives"][did] = {
            "oracle": tstats,
            "r5a": {"anchor_tid": r5a_tid, "anchor_feat": r5a_feat,
                    "target_frames": r5a_tgt},
            "r5b": {"feat": r5b_feat, "member_tids_sample": r5b_tids[:12],
                    "target_frames": r5b_tgt, "n_components": len(comps)},
            "failure_classes": classes,
        }
        print(did, classes, "r5a_tgt", r5a_tgt, "r5b_tgt", r5b_tgt, flush=True)

    cache.save()
    ok, sha16 = cache.verify()
    gap_doc["embedding_cache"] = {
        "saved": True, "weights_sha16": sha16, "n_keys": cache.meta["n_keys"],
    }
    OUT_GAP.write_text(json.dumps(gap_doc, indent=1) + "\n")
    OUT_FEAT.write_text(json.dumps(feat_doc, indent=1) + "\n")
    print("wrote", OUT_GAP, OUT_FEAT)


if __name__ == "__main__":
    main()
