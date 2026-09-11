#!/usr/bin/env python3
"""V4 Phase E — frozen action-semantic component score (conditional Phase E).

HURDLE_IDENTITY_COMPONENT_AND_TARGET_SELECTION_V4.

Executed because component construction improved (Phase A anti-percolation)
but GT-free component choice remains the blocker (Phase D ranking loss).

ONE frozen off-the-shelf representation, no training, no fine-tuning:
  torchvision r2plus1d_18, Kinetics-400 pre-trained (KINETICS400_V1),
  weights sha-verified against the torch-hub cache file.

Purpose (E2): a coarse per-candidate-path score
  action_score = sum of softmax probabilities over a frozen
  AIRBORNE/DIVING-adjacent class subset
  {springboard diving, diving cliff, jumping into pool, high jump,
   ski jumping, skydiving}
computed from a person-centered temporal tube (E1):
  - 360p candidate geometry (proxy authority), box crop pad 2.0,
  - 16 frames sampled around the path's excursion-peak frame (+-0.8 s
    geometry-only window; no GT event times, no dive-code timing, no
    human-selected identity).

E3 benchmark (GT for CLASS-LABELLING only): does the score separate
  target-bearing paths from persistent bystanders / static structures /
  fast unrelated movers / next-divers?

Deterministic; full-clip; GT used only in the benchmark labels.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))

import v6_prototype_v1 as V  # noqa: E402
import phase_v4_selector_v1 as S  # noqa: E402
import phase_v4_selector_v1_driver as D  # noqa: E402
from phase_v3_prototype_select_v1 import eval_sel  # noqa: E402

V4_RUNS = BASE / "runs/hurdle_prototype_v4"
OUT = V4_RUNS / "ACTION_SEMANTIC_V4.json"

# frozen constants -----------------------------------------------------------
TUBE_K = 16                # frames per tube (Kinetics 16-frame clips)
TUBE_WIN_S = 0.8           # +- window around the excursion peak
CROP_PAD_ACTION = 2.0      # person + action context
KINETICS_MEAN = (0.43216, 0.394666, 0.37645)
KINETICS_STD = (0.22803, 0.22145, 0.216989)
AIRBORNE_CLASSES = ["springboard diving", "diving cliff",
                    "jumping into pool", "high jump", "ski jumping",
                    "skydiving", "trampoline"]
W_ACTION = 2.0             # V7-B combination weight (frozen)

V7B_MARGIN_BONUS = None    # reserved


def tube_frames(box_map, feat, fps):
    """Deterministic 16-frame tube around the excursion peak."""
    fis = sorted(box_map)
    peak_fi = max(fis, key=lambda fi: abs(box_map[fi]["cy"] - feat["prep_level"]))
    near = [fi for fi in fis if abs(fi - peak_fi) <= TUBE_WIN_S * fps]
    if len(near) < 8:
        near = [fi for fi in fis
                if abs(fi - peak_fi) <= 2 * TUBE_WIN_S * fps]
    if len(near) < 4:
        near = fis
    idx = np.linspace(0, len(near) - 1, TUBE_K).round().astype(int)
    return [near[i] for i in idx]


def main():
    import torch
    import cv2
    from torchvision.models.video import r2plus1d_18, R2Plus1D_18_Weights

    V4_RUNS.mkdir(parents=True, exist_ok=True)
    weights_enum = R2Plus1D_18_Weights.KINETICS400_V1
    weights_path = Path(torch.hub.get_dir()) / "checkpoints/r2plus1d_18-91a641e6.pth"
    wsha = hashlib.sha256(weights_path.read_bytes()).hexdigest()
    categories = weights_enum.meta["categories"]
    air_idx = [categories.index(c) for c in AIRBORNE_CLASSES
               if c in categories]
    model = r2plus1d_18(weights=weights_enum).to("mps").eval()

    fc, chains = V.load_corpus()
    doc = {
        "label": "ACTION_SEMANTIC_V4",
        "packet": "HURDLE_IDENTITY_COMPONENT_AND_TARGET_SELECTION_V4",
        "model": "torchvision r2plus1d_18 KINETICS400_V1 (frozen, no training)",
        "weights_sha256": wsha,
        "airborne_classes": [categories[i] for i in air_idx],
        "gt_usage": "class-labelling in the benchmark ONLY; the score "
                    "consumes candidate geometry only",
        "dives": {},
    }
    args = [a for a in sys.argv[1:] if a in V.ALL_DIVES] or V.ALL_DIVES
    for did in args:
        t0 = time.time()
        print("==", did, flush=True)
        dive_doc = fc["dives"][did]
        trk = V.dive_arrays(dive_doc)
        plaus = V.plausible_tracklets(trk)
        embs = V.embed_tracklets(did, dive_doc, trk, cache=V.EmbeddingCache(),
                                 plaus=plaus)
        pts_by_pos = [round(f["pts_s"], 4) for f in trk["frames"]]
        tgt_tids, hits, gt = V.mark_target_tracklets(
            did, dive_doc, chains["dives"][did], trk)
        view = V.trk_view(trk, list(plaus.keys()))
        import phase_v4_linkage_v1 as L
        edges = L.compatible_edge_list(view, embs)
        pool = D.build_pool(trk, embs, V.EmbeddingCache(), did, dive_doc,
                            edges)
        fps = trk["fps"]

        # needed frames (unique, per candidate tube)
        tube_specs = []
        for c in pool:
            tfs = tube_frames(c["box_map"], c["feat"], fps)
            tube_specs.append((c, tfs))
        all_fis = sorted(set(fi for _c, tfs in tube_specs for fi in tfs))
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

        # tubes -> tensors
        tensors, metas = [], []
        for c, tfs in tube_specs:
            imgs = []
            for fi in tfs:
                fr = frames.get(fi)
                b = c["box_map"].get(fi)
                if fr is None or b is None:
                    continue
                H, W = fr.shape[:2]
                w = max(2, int(b["bw"] * CROP_PAD_ACTION * W))
                h = max(2, int(b["bh"] * CROP_PAD_ACTION * H))
                x1 = max(0, int((b["cx"] - b["bw"] * CROP_PAD_ACTION / 2) * W))
                y1 = max(0, int((b["cy"] - b["bh"] * CROP_PAD_ACTION / 2) * H))
                crop = fr[y1:y1 + h, x1:x1 + w]
                if crop.size == 0:
                    continue
                crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
                crop = cv2.resize(crop, (112, 112),
                                  interpolation=cv2.INTER_AREA)
                t = torch.from_numpy(crop).permute(2, 0, 1).float() / 255.0
                t = (t - torch.tensor(KINETICS_MEAN).view(3, 1, 1)) / \
                    torch.tensor(KINETICS_STD).view(3, 1, 1)
                imgs.append(t)
            if len(imgs) < 4:
                tensors.append(None)
                metas.append(c)
                continue
            while len(imgs) < TUBE_K:
                imgs.append(imgs[-1])
            clip = torch.stack(imgs[:TUBE_K])          # (T,3,112,112)
            tensors.append(clip.permute(1, 0, 2, 3))   # (3,T,112,112)
            metas.append(c)

        # batch forward
        probs = {}
        with torch.no_grad():
            batch = [(i, t) for i, t in enumerate(tensors) if t is not None]
            for s in range(0, len(batch), 8):
                ids = [i for i, _ in batch[s:s + 8]]
                x = torch.stack([t for _, t in batch[s:s + 8]]).to("mps")
                y = model(x)
                p = torch.softmax(y, dim=1).cpu()
                for j, i in enumerate(ids):
                    probs[i] = p[j]
        rows = []
        for i, c in enumerate(metas):
            ev = eval_sel(c["box_map"], gt, pts_by_pos)
            pf = ev.get("per_frame_correct", 0.0)
            if i in probs:
                p = probs[i]
                score = float(p[air_idx].sum())
                top_cls = categories[int(p.argmax())]
            else:
                score, top_cls = None, None
            rows.append({"cls": c["cls"], "label": c["label"],
                         "q": c["q"], "pf": pf, "action_score":
                         None if score is None else round(score, 4),
                         "top_class": top_cls,
                         "feat": {k: v for k, v in c["feat"].items()
                                  if k not in ("fis",)}})
        tgt = [r for r in rows if r["pf"] >= 0.3 and r["action_score"]
               is not None]
        oth = [r for r in rows if r["pf"] < 0.3 and r["action_score"]
               is not None]
        tgt_scores = [r["action_score"] for r in tgt]
        oth_scores = [r["action_score"] for r in oth]
        bench = {
            "n_target": len(tgt), "n_other": len(oth),
            "target_score_mean": round(float(np.mean(tgt_scores)), 4)
            if tgt_scores else None,
            "target_score_min": round(float(np.min(tgt_scores)), 4)
            if tgt_scores else None,
            "ocean_score_mean": round(float(np.mean(oth_scores)), 4)
            if oth_scores else None,
            "ocean_score_max": round(float(np.max(oth_scores)), 4)
            if oth_scores else None,
        }
        # simple AUC target vs ocean (rank statistic)
        if tgt_scores and oth_scores:
            allv = [(s, 1) for s in tgt_scores] + [(s, 0) for s in oth_scores]
            allv.sort()
            ranks = {}
            for i, (s, _) in enumerate(allv):
                ranks.setdefault(s, i + 1)
            # average ranks for ties
            from collections import defaultdict as dd
            groups = dd(list)
            for i, (s, _) in enumerate(allv):
                groups[s].append(i + 1)
            rsum_t = sum(np.mean(groups[s]) for s, _ in allv if _ == 1)
            n1, n0 = len(tgt_scores), len(oth_scores)
            bench["auc_target_vs_ocean"] = round(
                (rsum_t - n1 * (n1 + 1) / 2) / (n1 * n0), 4)
        # class-family means (GT-labelling for the E3 families)
        fam = {}
        for name, pred in (
            ("persistent_bystander", lambda r: r["pf"] < 0.3 and
             r["feat"]["life_frac"] > 0.6 and
             r["feat"]["exc_y"] < S.R5B.STATIC_EXC_MAX + 0.02 and
             r["action_score"] is not None),
            ("fast_mover", lambda r: r["pf"] < 0.3 and
             r["feat"]["life_s"] < 2.0 and
             r["feat"]["peak_v_cy_s"] > 0.45 and
             r["action_score"] is not None),
            ("next_diver", lambda r: r["pf"] < 0.3 and
             r["feat"]["start_frac"] > 0.6 and
             r["action_score"] is not None),
        ):
            sel = [r["action_score"] for r in rows if pred(r)]
            fam[name] = {
                "n": len(sel),
                "mean": round(float(np.mean(sel)), 4) if sel else None,
                "max": round(float(np.max(sel)), 4) if sel else None}
        doc["dives"][did] = {"benchmark": bench, "families": fam,
                             "candidates": rows,
                             "elapsed_s": round(time.time() - t0, 1)}
        print("  bench:", json.dumps(bench), json.dumps(fam), flush=True)

    OUT.write_text(json.dumps(doc, indent=1) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
