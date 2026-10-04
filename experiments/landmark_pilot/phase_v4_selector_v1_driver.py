#!/usr/bin/env python3
"""V4 Phases F + G — V7-A and V7-B selector evaluation.

HURDLE_IDENTITY_COMPONENT_AND_TARGET_SELECTION_V4.

Candidate pool (all GT-free, full-clip, deterministic):
  A0 mutual-kNN identity components (K_MNN=3),
  A1 bounded-degree identity components (deg 3, bridge margin 0.06),
  Phase-B appearance-NN rollouts (anchor-seeded + component-seeded),
  R5-A enumerated (anchor, departure) hypotheses (unchanged machinery).

Gate (Phase C): KEEP_D5_TOP1 when the frozen D5 op-point top-1 path is
highly stable; a pool candidate may override only by keep_margin with
usable coverage.

Ranking:
  V7-A: NEW v7_component_quality (frozen constants, component level).
  V7-B: V7-A + frozen action-semantic component score
        q + W_ACTION * action_score, where action_score is the summed
        softmax mass of a frozen airborne/diving class subset of the
        frozen torchvision r2plus1d_18 KINETICS400_V1 encoder applied to
        a person-centered 16-frame tube around the path's excursion peak.

Writes runs/hurdle_prototype_v4/V7_EVAL_V4.json.

Usage:
  caffeinate -i -s python3 experiments/landmark_pilot/phase_v4_selector_v1_driver.py [dive ...]
"""

import hashlib
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))

import r5_tracklets_v1 as R5  # noqa: E402
import r5b_association_v1 as R5B  # noqa: E402
import v6_prototype_v1 as V  # noqa: E402
import phase_v4_linkage_v1 as L  # noqa: E402
import phase_v4_hypotheses_v1 as H  # noqa: E402
import phase_v4_selector_v1 as S  # noqa: E402
import phase_v4_action_v1 as A  # noqa: E402
from phase_v3_prototype_select_v1 import eval_sel  # noqa: E402

V4_RUNS = BASE / "runs/hurdle_prototype_v4"
OUT = V4_RUNS / "V7_EVAL_V4.json"


def component_box_map(trk, member_tids):
    bm = {}
    for t in member_tids:
        tr = V.tid_tracklet(trk, t)
        if tr is None:
            continue
        for fi in tr.starts:
            if fi not in bm:
                b = tr.boxes[fi]
                bm[fi] = {"cx": b.cx, "cy": b.cy, "bw": b.bw, "bh": b.bh,
                          "conf": b.conf}
    return bm


def comp_app_mean(embs, members):
    vs = [embs[t] for t in members if t in embs]
    if len(vs) < 2:
        return None
    sims = [float(np.dot(vs[i], vs[j]))
            for i in range(len(vs)) for j in range(i + 1, len(vs))]
    return float(np.mean(sims))


def build_pool(trk, embs, cache, dive_id, dive_doc, edges):
    """All GT-free candidate paths."""
    n = trk["n"]
    pool = []
    rel_arrs = [trk["arrs"][fi] - trk["off"][fi] for fi in range(n)]

    def emb_fn(fi, k):
        return cache.get((dive_id, fi, k))

    for name, comps in (
        ("mnn_component",
         L.mutual_knn_components(V.trk_view(trk, list(embs)), edges, 3)),
        ("deg_component",
         L.bounded_degree_components(V.trk_view(trk, list(embs)), edges)),
    ):
        for members in comps:
            bm = component_box_map(trk, members)
            if len(bm) < 3:
                continue
            feat = S.path_features(trk, bm,
                                   app_mean=comp_app_mean(embs, members))
            if feat is None:
                continue
            pool.append({"cls": name, "label": str(members[:6]),
                         "box_map": bm, "feat": feat,
                         "q": S.v7_component_quality(feat, n)})

    # ---- Phase B rollouts ----
    anchors = R5.prep_anchors(trk["tracklets"], trk["off"], trk["fps"])
    for a in anchors:
        tr = a["tr"]
        pos_fi = tr.starts[a["i1"]]
        k0 = R5B._candidate_index(tr, pos_fi, trk["cands"])
        if k0 is None:
            continue
        cmap, diag = H.appearance_rollout(a, trk, rel_arrs, emb_fn, k0)
        if cmap is None or len(cmap) < 3:
            continue
        bm = {}
        for fi, k in cmap.items():
            c = trk["cands"][fi][k]
            bm[fi] = {"cx": c.cx, "cy": c.cy, "bw": c.bw, "bh": c.bh,
                      "conf": c.conf}
        feat = S.path_features(trk, bm, app_mean=None)
        if feat is None:
            continue
        pool.append({"cls": "app_rollout", "label": f"anchor{tr.tid}",
                     "box_map": bm, "feat": feat,
                     "q": S.v7_component_quality(feat, n)})

    comp_members = [m for m in
                    L.bounded_degree_components(
                        V.trk_view(trk, list(embs)), edges)
                    if len(m) >= H.COMP_ROLLOUT_MIN_MEMBERS]
    comp_members.sort(
        key=lambda m: (-sum(V.tid_tracklet(trk, t).n_frames() for t in m),
                       m[0]))
    for members in comp_members[:H.COMP_ROLLOUT_MAX_SEEDS]:
        cmap, diag = H.component_rollout(members, trk, rel_arrs, emb_fn)
        if cmap is None or len(cmap) < 3:
            continue
        bm = {}
        for fi, k in cmap.items():
            c = trk["cands"][fi][k]
            bm[fi] = {"cx": c.cx, "cy": c.cy, "bw": c.bw, "bh": c.bh,
                      "conf": c.conf}
        feat = S.path_features(trk, bm, app_mean=None)
        if feat is None:
            continue
        pool.append({"cls": "comp_rollout", "label": str(members[:6]),
                     "box_map": bm, "feat": feat,
                     "q": S.v7_component_quality(feat, n)})

    # R5-A enumerated hypotheses (unchanged machinery)
    hyps = V.enumerate_r5a_hypotheses(trk)
    for rank, h in enumerate(hyps):
        fis = sorted(h["frames_map"])
        if len(fis) < 3:
            continue
        feat = S.path_features(trk, dict(h["frames_map"]), app_mean=None)
        if feat is None:
            continue
        feat["prep_dur_s"] = h["feats"].get("prep_dur_s") or feat["prep_dur_s"]
        feat["rest_ratio"] = h["feats"].get("rest_ratio")
        feat["entry"] = h["feats"].get("entry")
        pool.append({"cls": "r5a_hypothesis",
                     "label": f"anchor{h['anchor_tid']}#rank{rank}",
                     "box_map": dict(h["frames_map"]), "feat": feat,
                     "q": S.v7_component_quality(feat, n)})
    return pool


def tubes_for(box_map, feat, fps):
    fis = sorted(box_map)
    peak_fi = max(fis, key=lambda fi: abs(box_map[fi]["cy"]
                                          - feat["prep_level"]))
    near = [fi for fi in fis if abs(fi - peak_fi) <= A.TUBE_WIN_S * fps]
    if len(near) < 8:
        near = [fi for fi in fis
                if abs(fi - peak_fi) <= 2 * A.TUBE_WIN_S * fps]
    if len(near) < 4:
        near = fis
    idx = np.linspace(0, len(near) - 1, 16).round().astype(int)
    return sorted(set(int(near[i]) for i in idx))


def crop_clip(frames, box_map, fis, pad, mean, std):
    import cv2
    import torch
    imgs = []
    for fi in fis:
        fr = frames.get(fi)
        b = box_map.get(fi)
        if fr is None or b is None:
            continue
        H, W = fr.shape[:2]
        w = max(2, int(b["bw"] * pad * W))
        h = max(2, int(b["bh"] * pad * H))
        x1 = max(0, int((b["cx"] - b["bw"] * pad / 2) * W))
        y1 = max(0, int((b["cy"] - b["bh"] * pad / 2) * H))
        crop = fr[y1:y1 + h, x1:x1 + w]
        if crop.size == 0:
            continue
        crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        crop = cv2.resize(crop, (112, 112), interpolation=cv2.INTER_AREA)
        t = torch.from_numpy(crop).permute(2, 0, 1).float() / 255.0
        t = (t - torch.tensor(mean).view(3, 1, 1)) / \
            torch.tensor(std).view(3, 1, 1)
        imgs.append(t)
    if len(imgs) < 4:
        return None
    while len(imgs) < 16:
        imgs.append(imgs[-1])
    return torch.stack(imgs[:16]).permute(1, 0, 2, 3)


def main():
    import torch
    import cv2
    from torchvision.models.video import r2plus1d_18, R2Plus1D_18_Weights
    V4_RUNS.mkdir(parents=True, exist_ok=True)
    fc, chains = V.load_corpus()
    cache = V.EmbeddingCache()
    w_enum = R2Plus1D_18_Weights.KINETICS400_V1
    wpath = Path(torch.hub.get_dir()) / "checkpoints/r2plus1d_18-91a641e6.pth"
    wsha = hashlib.sha256(wpath.read_bytes()).hexdigest()
    cats = w_enum.meta["categories"]
    air_idx = [i for i, c in enumerate(cats) if c in A.AIRBORNE_CLASSES]
    model = r2plus1d_18(weights=w_enum).to("mps").eval()

    doc = {
        "label": "V7_EVAL_V4",
        "packet": "HURDLE_IDENTITY_COMPONENT_AND_TARGET_SELECTION_V4",
        "gt_usage": "evaluation section ONLY",
        "weights_sha256": wsha,
        "airborne_classes": [cats[i] for i in air_idx],
        "dives": {},
    }
    args = [a for a in sys.argv[1:] if a in V.ALL_DIVES] or V.ALL_DIVES
    for did in args:
        t0 = time.time()
        print("==", did, flush=True)
        dive_doc = fc["dives"][did]
        trk = V.dive_arrays(dive_doc)
        plaus = V.plausible_tracklets(trk)
        embs = V.embed_tracklets(did, dive_doc, trk, cache, plaus)
        pts_by_pos = [round(f["pts_s"], 4) for f in trk["frames"]]
        tgt_tids, hits, gt = V.mark_target_tracklets(
            did, dive_doc, chains["dives"][did], trk)
        view = V.trk_view(trk, list(plaus.keys()))
        edges = L.compatible_edge_list(view, embs)
        pool = build_pool(trk, embs, cache, did, dive_doc, edges)
        n = trk["n"]

        # ---- action scores ----
        tube_specs = [tubes_for(c["box_map"], c["feat"], trk["fps"])
                      for c in pool]
        all_fis = sorted(set(fi for tfs in tube_specs for fi in tfs))
        frames = {}
        cap = cv2.VideoCapture(str(BASE / dive_doc["proxy_path"]))
        pos = -1
        for fi in all_fis:
            if fi != pos + 1:
                cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
                ok, fr = cap.read()
                pos = fi
            else:
                ok, fr = cap.read()
                pos += 1
            if ok and fr is not None:
                frames[fi] = fr
        cap.release()
        with torch.no_grad():
            clips = []
            for c, tfs in zip(pool, tube_specs):
                clips.append(crop_clip(frames, c["box_map"], tfs, A.CROP_PAD_ACTION, A.KINETICS_MEAN, A.KINETICS_STD))
            probs = {}
            idxs = [i for i, t in enumerate(clips) if t is not None]
            for s in range(0, len(idxs), 8):
                grp = idxs[s:s + 8]
                x = torch.stack([clips[i] for i in grp]).to("mps")
                p = torch.softmax(model(x), dim=1).cpu()
                for j, i in enumerate(grp):
                    probs[i] = p[j]
        for i, c in enumerate(pool):
            c["action_score"] = None if i not in probs else round(
                float(probs[i][air_idx].sum()), 4)

        # ---- gate ----
        d5 = S.d5_optop1_path(trk)
        d5_k = {}
        for fi, b in d5.items():
            for k, c in enumerate(trk["cands"][fi]):
                if abs(c.cx - b["cx"]) < 1e-9 and abs(c.cy - b["cy"]) < 1e-9:
                    d5_k[fi] = k
                    break

        def cos_fn(a, b):
            ka, kb = d5_k.get(a), d5_k.get(b)
            if ka is None or kb is None:
                return None
            va, vb = cache.get((did, a, ka)), cache.get((did, b, kb))
            if va is None or vb is None:
                return None
            return float(np.dot(va, vb))

        keep, gate_ev = S.baseline_stability_gate(trk, d5, cos_fn)
        feat_d5 = S.path_features(trk, d5) if d5 else None
        q_d5 = S.v7_component_quality(feat_d5, n) if feat_d5 else None
        act_d5 = None
        if d5 and feat_d5:
            tfs = tubes_for(d5, feat_d5, trk["fps"])
            clip = crop_clip(frames, d5, tfs, A.CROP_PAD_ACTION, A.KINETICS_MEAN, A.KINETICS_STD)
            if clip is not None:
                with torch.no_grad():
                    p = torch.softmax(
                        model(clip.unsqueeze(0).to("mps")), dim=1).cpu()[0]
                act_d5 = round(float(p[air_idx].sum()), 4)
        q_d5_b = None if (q_d5 is None or act_d5 is None) else \
            round(q_d5 + A.W_ACTION * act_d5, 4)

        for c in pool:
            c["q_v7b"] = None if c["action_score"] is None else round(
                c["q"] + A.W_ACTION * c["action_score"], 4)

        def ranked_by(key):
            return sorted(pool, key=lambda c: (-c[key], c["cls"],
                                               c["label"]))

        res = {}
        for tag, qkey, qd5 in (("V7_A", "q", q_d5),
                               ("V7_B", "q_v7b", q_d5_b)):
            best = ranked_by(qkey)[0] if pool else None
            decision, chosen = "RANKED", best
            if keep and best is not None and qd5 is not None:
                cov = best["feat"]["coverage"]
                if best[qkey] < qd5 + S.V7Q["keep_margin"] or \
                        cov < S.V7Q["override_min_coverage"]:
                    decision, chosen = "KEEP_D5_TOP1", None
            if chosen is not None:
                ev = eval_sel(chosen["box_map"], gt, pts_by_pos)
                res[tag] = {"decision": decision,
                            "chosen_cls": chosen["cls"],
                            "chosen_q": chosen[qkey],
                            "eval": ev}
            else:
                ev = eval_sel(d5, gt, pts_by_pos)
                res[tag] = {"decision": decision, "chosen_cls": "d5_op_top1",
                            "chosen_q": qd5, "eval": ev}
        best_pf, best_cls = 0.0, None
        for c in pool:
            e = eval_sel(c["box_map"], gt, pts_by_pos)
            if e.get("per_frame_correct", 0) > best_pf:
                best_pf, best_cls = e["per_frame_correct"], c["cls"]
        doc["dives"][did] = {
            "gate": gate_ev,
            "V7_A": res["V7_A"], "V7_B": res["V7_B"],
            "d5_eval": eval_sel(d5, gt, pts_by_pos),
            "pool_top_a": pool_top(pool, "q", 6),
            "pool_top_b": pool_top(pool, "q_v7b", 6),
            "best_in_pool_pf": round(best_pf, 4),
            "best_in_pool_cls": best_cls,
            "n_pool": len(pool),
            "elapsed_s": round(time.time() - t0, 1),
        }
        print(f"  A pf {res['V7_A']['eval'].get('per_frame_correct')} "
              f"({res['V7_A']['chosen_cls']}, {res['V7_A']['decision']}) | "
              f"B pf {res['V7_B']['eval'].get('per_frame_correct')} "
              f"({res['V7_B']['chosen_cls']}, {res['V7_B']['decision']}) | "
              f"d5 pf {doc['dives'][did]['d5_eval'].get('per_frame_correct')}"
              f" | best-in-pool {best_pf:.3f} ({best_cls})", flush=True)

    OUT.write_text(json.dumps(doc, indent=1) + "\n")
    print("wrote", OUT)


def pool_top(pool, key, k):
    out = []
    for c in sorted(pool, key=lambda c: (-c[key], c["cls"], c["label"]))[:k]:
        out.append({"cls": c["cls"], "label": c["label"],
                    "q": c[key],
                    "action": c.get("action_score"),
                    "feat": {kk: v for kk, v in c["feat"].items()
                             if kk != "fis"}})
    return out


if __name__ == "__main__":
    main()
