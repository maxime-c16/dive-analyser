#!/usr/bin/env python3
"""Phase E (HURDLE_TARGET_IDENTITY_V2) — appearance separability benchmark.

Question: is a frozen person-ReID embedding actually discriminative on the
tiny 360p HURDLE divers, i.e. can it separate the target from the static
distractors that dominate D5 selection?

  E0: frozen ResNet50 ImageNet embedding (the historical R4 encoder)
  E1: frozen OSNet x1.0 person-ReID encoder (Market-1501-trained, official
      torchreid model zoo checkpoint; sha256 recorded in the artifact)

Pair construction uses the EVALUATION AUTHORITY ONLY (GT chains define the
target crop per frame; distractors are floor candidates that do NOT match
the target). This phase evaluates representation quality; GT never enters
inference later (R5-B consumes embeddings of CANDIDATE crops only).

Artifacts:
  runs/hurdle_identity_v1/E_APPEARANCE_BENCHMARK_V1.json

Usage:
  caffeinate -i -s .venv-reid/bin/python experiments/landmark_pilot/phase_hurdle_e_appearance_benchmark_v1.py
"""

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import cv2
import torch
import torch.nn as nn
import torchvision

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))

FULLCLIP = BASE / "runs/hurdle_identity_v1/R5_FULLCLIP_CANDIDATES_V1.json"
CHAINS = BASE / "runs/hurdle_identity_v1/target_chains_v1.json"
OUT = BASE / "runs/hurdle_identity_v1/E_APPEARANCE_BENCHMARK_V1.json"
OSNET_PATH = BASE / "models/reid/osnet_x1_0_market1501.pth"

STRIDE_S = 0.2        # sampled-frame stride within the eval interval
PAD = 1.3             # crop padding (R4 convention)
MAX_CROPS_PER_DIVE = 260

PRIMARY = ["1040", "2169", "2341", "2353", "2541"]
ALL_DIVES = PRIMARY + ["2555"]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


class OSNetWrap(nn.Module):
    def __init__(self, weights_path):
        super().__init__()
        import torchreid
        self.m = torchreid.models.build_model(
            name="osnet_x1_0", num_classes=1, pretrained=False, use_gpu=False)
        td = torch.load(weights_path, map_location="cpu", weights_only=False)
        if "state_dict" in td:
            td = td["state_dict"]
        # num_classes mismatch (751 vs 1): keep the backbone, drop classifier
        own = self.m.state_dict()
        td = {k: v for k, v in td.items() if k in own
              and own[k].shape == v.shape}
        self.m.load_state_dict(td, strict=False)
        self.m.eval()

    def forward(self, x):
        # torchreid osnet returns (feat, ...) when featuremaps not requested
        out = self.m(x)
        return out[0] if isinstance(out, tuple) else out


class ResNetWrap(nn.Module):
    def __init__(self):
        super().__init__()
        self.m = torchvision.models.resnet50(
            weights=torchvision.models.ResNet50_Weights.IMAGENET1K_V1)
        self.m.fc = nn.Identity()
        self.m.eval()

    def forward(self, x):
        return self.m(x)


NORM = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
STD = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)


def crop_tensor(frame_bgr, box, pad=PAD):
    H, W = frame_bgr.shape[:2]
    cx, cy, bw, bh = box
    w = max(2, int(bw * pad * W))
    h = max(2, int(bh * pad * H))
    x1 = int(max(0, (cx - (bw * pad) / 2) * W))
    y1 = int(max(0, (cy - (bh * pad) / 2) * H))
    crop = frame_bgr[y1:y1 + h, x1:x1 + w]
    if crop.size == 0:
        crop = frame_bgr[:8, :8]
    t = torch.from_numpy(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)).permute(2, 0, 1).float() / 255.0
    return t


def to_input(crops, size):
    batch = []
    for t in crops:
        t = torch.nn.functional.interpolate(
            t.unsqueeze(0), size=size, mode="bilinear", align_corners=False
        ).squeeze(0)
        batch.append((t - NORM) / STD)
    return torch.stack(batch)


@torch.no_grad()
def embed(model, crops, size):
    if not crops:
        return np.zeros((0, 0))
    feats = []
    for i in range(0, len(crops), 32):
        x = to_input(crops[i:i + 32], size).to(next(model.parameters()).device)
        f = model(x)
        f = torch.nn.functional.normalize(f, dim=1)
        feats.append(f.cpu().numpy())
    return np.concatenate(feats)


def collect_crops(dive, fullclip_dive, chain_dive):
    """Sample eval-interval frames; target crop from GT chain, distractor
    crops from floor candidates not matching the target, plus the persistent
    background crop (median top-conf distractor box across sampled frames)."""
    fps = fullclip_dive["fps"]
    frames = fullclip_dive["frames"]
    gt = {}
    for c in chain_dive["chain"]:
        if c["status"] == "GT":
            gt[round(c["pts_s"], 4)] = (c["cx"], c["cy"], c["bw"], c["bh"])
    idx = [i for i, f in enumerate(frames)
           if round(f["pts_s"], 4) in gt]
    idx = idx[::max(1, int(round(STRIDE_S * fps)))]
    rows = []
    bg_pos = []
    for i in idx:
        g = gt[round(frames[i]["pts_s"], 4)]
        cands = frames[i]["c"]
        distractors = []
        for c in cands:
            cd = ((c["cx"] - g[0]) ** 2 + (c["cy"] - g[1]) ** 2) ** 0.5
            if cd > 0.08:
                distractors.append(c)
        if not distractors:
            continue
        distractors.sort(key=lambda c: -c["conf"])
        rows.append({"fi": i, "pts_s": frames[i]["pts_s"],
                     "target": g, "distractor": distractors[0],
                     "n_distractors": len(distractors)})
        bg_pos.append((distractors[0]["cx"], distractors[0]["cy"]))
    # persistent background = median position of the top distractor
    bg = (float(np.median([p[0] for p in bg_pos])),
          float(np.median([p[1] for p in bg_pos])))
    return rows, bg


def pair_metrics(emb_t, emb_d, rows, bg_emb, same_dt_min_s=1.0, fps=None):
    res = {}
    n = len(rows)
    same, cross = [], []
    for i in range(n):
        for j in range(i + 1, n):
            dt = abs(rows[i]["pts_s"] - rows[j]["pts_s"])
            same.append(float(emb_t[i] @ emb_t[j])) if dt >= same_dt_min_s else None
            cross.append(float(emb_t[i] @ emb_d[j]))
    same = np.array(same)
    cross = np.array(cross)
    # ROC-AUC for pair identity (same-target vs target-vs-distractor)
    lab = np.concatenate([np.ones(len(same)), np.zeros(len(cross))])
    sc = np.concatenate([same, cross])
    order = np.argsort(sc)
    ranks = np.empty(len(sc))
    ranks[order] = np.arange(1, len(sc) + 1)
    # average ranks for ties
    auc = (ranks[lab == 1].sum() - len(same) * (len(same) + 1) / 2) / \
        (len(same) * len(cross))
    # nearest-neighbor target retrieval: for each target crop, its NN among
    # all target crops (temporal, dt >= 1s) belongs to the target by
    # construction -> retrieval rate = fraction with NN similarity > best
    # same-frame distractor similarity
    nn_hits = 0
    nn_total = 0
    for i in range(n):
        cands_nn = [(float(emb_t[i] @ emb_t[j]), j)
                    for j in range(n)
                    if j != i and abs(rows[i]["pts_s"] - rows[j]["pts_s"]) >= same_dt_min_s]
        if not cands_nn:
            continue
        nn_total += 1
        nn_sim = max(c for c, _ in cands_nn)
        cross_sim = float(emb_t[i] @ emb_d[i])
        nn_hits += int(nn_sim > cross_sim)
    res.update({
        "n_same_pairs": int(len(same)),
        "n_cross_pairs": int(len(cross)),
        "cos_same_mean": round(float(same.mean()), 4) if len(same) else None,
        "cos_same_std": round(float(same.std()), 4) if len(same) else None,
        "cos_cross_mean": round(float(cross.mean()), 4) if len(cross) else None,
        "cos_cross_std": round(float(cross.std()), 4) if len(cross) else None,
        "separation_margin": round(float(same.mean() - cross.mean()), 4)
        if len(same) and len(cross) else None,
        "roc_auc": round(float(auc), 4),
        "nn_retrieval_rate": round(nn_hits / nn_total, 4) if nn_total else None,
        "n_nn_queries": nn_total,
        "bg_cross_cos_mean": round(float(np.mean(
            (emb_t * bg_emb[:len(emb_t)]).sum(axis=1))), 4)
        if len(emb_t) else None,
    })
    return res


def main():
    fullclip = json.loads(FULLCLIP.read_text())
    chains = json.loads(CHAINS.read_text())["dives"]
    osnet_sha = sha256_file(OSNET_PATH)
    resnet_sha = sha256_file(Path(torch.hub.get_dir()) /
                             "checkpoints/resnet50-0676ba61.pth")

    e0 = ResNetWrap()
    e1 = OSNetWrap(OSNET_PATH)
    doc = {
        "label": "E_APPEARANCE_BENCHMARK_V1",
        "packet": "HURDLE_TARGET_IDENTITY_V2",
        "encoders": {
            "E0_resnet50_imagenet": {
                "class": "torchvision resnet50 IMAGENET1K_V1 (historical R4 encoder)",
                "weights_sha256": resnet_sha, "input": "224x224 avgpool 2048-d"},
            "E1_osnet_market1501": {
                "class": "OSNet x1.0 person-ReID, Market-1501-trained (frozen)",
                "weights_path": str(OSNET_PATH.relative_to(BASE)),
                "weights_sha256": osnet_sha,
                "source": "torchreid MODEL_ZOO (KaiyangZhou/deep-person-reid)",
                "input": "256x128 512-d"},
        },
        "pair_construction": "GT chains define target crops (eval authority only); distractors = floor candidates with center-dist > 0.08 from target; persistent background = median top-distractor position",
        "dives": {},
    }
    for did in ALL_DIVES:
        rows, bg = collect_crops(did, fullclip["dives"][did], chains[did])
        if not rows:
            continue
        cap = VideoReader(fullclip["dives"][did])
        t_crops, d_crops, bg_crops = [], [], []
        for r in rows:
            frame = cap.frame(r["fi"])
            t_crops.append(crop_tensor(frame, r["target"]))
            d_crops.append(crop_tensor(frame, (r["distractor"]["cx"],
                                               r["distractor"]["cy"],
                                               r["distractor"]["bw"],
                                               r["distractor"]["bh"])))
            bg_crops.append(crop_tensor(frame, (bg[0], bg[1],
                                                r["distractor"]["bw"],
                                                r["distractor"]["bh"])))
        t_e0 = embed(e0, t_crops, (224, 224))
        d_e0 = embed(e0, d_crops, (224, 224))
        b_e0 = embed(e0, bg_crops, (224, 224))
        t_e1 = embed(e1, t_crops, (256, 128))
        d_e1 = embed(e1, d_crops, (256, 128))
        b_e1 = embed(e1, bg_crops, (256, 128))
        res = {"n_samples": len(rows)}
        res["E0_resnet50_imagenet"] = pair_metrics(t_e0, d_e0, rows, b_e0)
        res["E1_osnet_market1501"] = pair_metrics(t_e1, d_e1, rows, b_e1)
        doc["dives"][did] = res
        print(did, "E0 margin/auc/nn:", res["E0_resnet50_imagenet"]["separation_margin"],
              res["E0_resnet50_imagenet"]["roc_auc"],
              res["E0_resnet50_imagenet"]["nn_retrieval_rate"],
              "| E1:", res["E1_osnet_market1501"]["separation_margin"],
              res["E1_osnet_market1501"]["roc_auc"],
              res["E1_osnet_market1501"]["nn_retrieval_rate"])
    # aggregate over primary
    for key in ["E0_resnet50_imagenet", "E1_osnet_market1501"]:
        agg = {}
        for m in ["cos_same_mean", "cos_cross_mean", "separation_margin",
                  "roc_auc", "nn_retrieval_rate", "bg_cross_cos_mean"]:
            vals = [doc["dives"][d][key][m] for d in PRIMARY
                    if d in doc["dives"] and doc["dives"][d][key][m] is not None]
            agg[m] = round(float(np.mean(vals)), 4) if vals else None
        doc[key + "_primary_aggregate"] = agg
    OUT.write_text(json.dumps(doc, indent=1) + "\n")
    print("wrote", OUT)


class VideoReader:
    """PTS_AUTHORITATIVE_SEEK reader (cap.set POS_FRAMES before read)."""

    def __init__(self, dive_doc):
        import os
        self.path = str(BASE / dive_doc["proxy_path"])
        self.cap = cv2.VideoCapture(self.path)

    def frame(self, fi):
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
        ok, fr = self.cap.read()
        if not ok:
            self.cap.release()
            self.cap = cv2.VideoCapture(str(self.path))
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
            ok, fr = self.cap.read()
        if not ok:
            raise RuntimeError(f"seek failed at frame {fi}")
        return fr

    def __del__(self):
        self.cap.release()


if __name__ == "__main__":
    main()
