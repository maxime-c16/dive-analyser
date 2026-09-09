#!/usr/bin/env python3
"""Phase F (HURDLE_TARGET_IDENTITY_V2) — HQ appearance-only experiment.

Question: can HQ improve identity REPRESENTATION while 360p remains the
frozen detector/geometry representation?  D5 is NOT run on HQ: proposals
stay the frozen proxy_360p candidate sets; the 360p crop box is mapped into
the HQ rendition (identity spatial map, PTS_EQUIVALENT temporal map per
HQ_PROXY_TEMPORAL_SPATIAL_INTEROP_V1 + HIGHRES_ANALYSIS_SOURCE_MANIFEST_V1)
and ONLY the appearance embedding is extracted there.

E1 encoder (frozen OSNet Market-1501) is used for both arms:
  - proxy crops (the E benchmark protocol)
  - HQ-mapped crops (same protocol, VFR-aware PTS mapping, rotation-aware)

Pair construction uses the evaluation authority only (GT chains); no GT
enters inference later.

Artifact: runs/hurdle_identity_v1/F_HQ_APPEARANCE_V1.json

Usage:
  caffeinate -i -s .venv-reid/bin/python experiments/landmark_pilot/phase_hurdle_f_hq_appearance_v1.py
"""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import cv2
import torch

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))

from phase_hurdle_e_appearance_benchmark_v1 import (  # noqa: E402
    OSNetWrap, crop_tensor, to_input, FULLCLIP, CHAINS,
)

HQ_ROOT = BASE / "runs/hq_identity_v2/edited_highres_rendition"
OUT = BASE / "runs/hq_identity_v1" if False else BASE / "runs/hurdle_identity_v1/F_HQ_APPEARANCE_V1.json"
OSNET_PATH = BASE / "models/reid/osnet_x1_0_market1501.pth"
STRIDE_S = 0.25
PAD = 1.3

HQ_FILES = {
    "1040": "IMG_4301.mov",
    "2169": "IMG_9474_edited.mov",
    "2341": "IMG_0098.mov",
    "2353": "IMG_1334_edited.mov",
    "2541": "IMG_1090.mov",
    "2555": "ScreenRecording_07-05-2026 8-35-45\u202fPM_1.mp4",
}
PRIMARY = ["1040", "2169", "2341", "2353", "2541"]


def ffprobe_meta(path):
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", "-select_streams", "v:0", str(path)],
        capture_output=True, text=True).stdout
    j = json.loads(out)
    st = j["streams"][0]
    coded_w, coded_h = st["width"], st["height"]
    rot = 0
    for sd in st.get("side_data_list", []):
        if sd.get("rotation", None) is not None:
            r = int(sd["rotation"])
            rot = r if r in (-90, 90, -270, 270) else rot
    for tag in ("rotate",):
        if st.get("tag_key") == tag:
            pass
    # some containers store rotation as a tag
    if st.get("tags", {}).get("rotate"):
        r = int(st["tags"]["rotate"])
        if r in (90, 270):
            rot = r
    disp_w, disp_h = coded_w, coded_h
    if rot in (90, -90, 270, -270):
        disp_w, disp_h = coded_h, coded_w
    # frame PTS list (VFR-safe)
    pts = subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "v:0", "-show_frames",
         "-show_entries", "frame=pts_time", "-of",
         "csv=p=0", str(path)], capture_output=True, text=True).stdout
    pts_list = []
    for line in pts.splitlines():
        line = line.strip()
        if not line or line == "N/A" or "," not in line:
            continue
        tok = line.split(",")[0].strip()
        try:
            pts_list.append(float(tok))
        except ValueError:
            continue
    return {"coded": [coded_w, coded_h], "display": [disp_w, disp_h],
            "rotation": rot, "pts": pts_list}


@torch.no_grad()
def embed(model, device, frame, box, size):
    t = to_input([crop_tensor(frame, box)], size).to(device)
    f = model(t)
    return torch.nn.functional.normalize(f, dim=1)[0].cpu().numpy()


def main():
    fullclip = json.loads(FULLCLIP.read_text())
    chains = json.loads(CHAINS.read_text())["dives"]
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = OSNetWrap(OSNET_PATH).to(device)
    model.eval()
    doc = {"label": "F_HQ_APPEARANCE_V1",
           "packet": "HURDLE_TARGET_IDENTITY_V2",
           "semantics": "D5 proposals stay frozen proxy_360p; HQ used for "
                        "appearance embedding ONLY (no D5-on-HQ)",
           "spatial_map": "identity {0,1,0,1} per interop authority",
           "temporal_map": "PTS_EQUIVALENT (per-dive PTS list mapping)",
           "dives": {}}
    for did, hq_name in HQ_FILES.items():
        hq_path = HQ_ROOT / hq_name
        if not hq_path.exists():
            print(f"[skip] {did}: HQ file missing")
            continue
        meta = ffprobe_meta(hq_path)
        cap = cv2.VideoCapture(str(hq_path))
        if meta["rotation"] in (90, 270):
            cap.set(cv2.CAP_PROP_ORIENTATION_AUTO, 0)
            cap.set(cv2.CAP_PROP_ROTATION, meta["rotation"])
        dive = fullclip["dives"][did]
        frames = dive["frames"]
        gt = {}
        for c in chains[did]["chain"]:
            if c["status"] == "GT":
                gt[round(c["pts_s"], 4)] = (c["cx"], c["cy"], c["bw"], c["bh"])
        idx = [i for i, f in enumerate(frames) if round(f["pts_s"], 4) in gt]
        idx = idx[::max(1, int(round(STRIDE_S * dive["fps"])))]
        pts = meta["pts"]
        pairs_t, pairs_d, misses = [], [], 0
        crops_hq_t, crops_hq_d, crops_px_t, crops_px_d = [], [], [], []
        pxcap = VideoReaderProxy(dive)
        for i in idx:
            t = frames[i]["pts_s"]
            # nearest HQ frame by PTS
            j = int(np.argmin([abs(p - t) for p in pts])) if pts else None
            if j is None or abs(pts[j] - t) > 0.1:
                misses += 1
                continue
            cap.set(cv2.CAP_PROP_POS_FRAMES, j)
            ok, frame = cap.read()
            if not ok or frame is None:
                # decode forward once more
                ok, frame = cap.read()
                if not ok:
                    misses += 1
                    continue
            # OpenCV applies display auto-rotation (CAP_PROP sizes already
            # report display dims); no manual rotate is needed
            H, W = frame.shape[:2]
            if abs(W / H - (meta["display"][0] / meta["display"][1])) > 0.1:
                misses += 1
                continue
            g = gt[round(frames[i]["pts_s"], 4)]
            cands = frames[i]["c"]
            distractors = [c for c in cands
                           if ((c["cx"] - g[0]) ** 2
                               + (c["cy"] - g[1]) ** 2) ** 0.5 > 0.08]
            if not distractors:
                misses += 1
                continue
            distractors.sort(key=lambda c: -c["conf"])
            d = distractors[0]
            crops_hq_t.append((frame, g))
            crops_hq_d.append((frame, (d["cx"], d["cy"], d["bw"], d["bh"])))
            pxframe = pxcap.frame(i)
            crops_px_t.append((pxframe, g))
            crops_px_d.append((pxframe, (d["cx"], d["cy"], d["bw"], d["bh"])))
        n = len(crops_hq_t)
        if n < 6:
            doc["dives"][did] = {"error": "insufficient HQ-mapped frames",
                                 "misses": misses}
            print(f"[skip] {did}: only {n} mapped frames")
            continue
        t_hq = [embed(model, device, f, b, (256, 128)) for f, b in crops_hq_t]
        d_hq = [embed(model, device, f, b, (256, 128)) for f, b in crops_hq_d]
        t_px = [embed(model, device, f, b, (256, 128)) for f, b in crops_px_t]
        d_px = [embed(model, device, f, b, (256, 128)) for f, b in crops_px_d]
        res = {"n_samples": n, "hq_pts_misses": misses,
               "hq_display_size": meta["display"],
               "hq_rotation": meta["rotation"]}
        res["E1_proxy360"] = pair_metrics(t_px, d_px)
        res["E1_hq_mapped"] = pair_metrics(t_hq, d_hq)
        doc["dives"][did] = res
        print(did, "proxy margin/auc:",
              res["E1_proxy360"]["separation_margin"],
              res["E1_proxy360"]["roc_auc"],
              "| HQ margin/auc:", res["E1_hq_mapped"]["separation_margin"],
              res["E1_hq_mapped"]["roc_auc"])
    for key in ["E1_proxy360", "E1_hq_mapped"]:
        agg = {}
        for m in ["cos_same_mean", "cos_cross_mean", "separation_margin",
                  "roc_auc", "nn_retrieval_rate"]:
            vals = [doc["dives"][d][key][m] for d in PRIMARY
                    if d in doc["dives"] and m in doc["dives"][d].get(key, {})
                    and doc["dives"][d][key][m] is not None]
            agg[m] = round(float(np.mean(vals)), 4) if vals else None
        doc[key + "_primary_aggregate"] = agg
    OUT.write_text(json.dumps(doc, indent=1) + "\n")
    print("wrote", OUT)


def pair_metrics(emb_t, emb_d, same_dt_min_s=1.0):
    n = len(emb_t)
    same, cross = [], []
    rows = list(range(n))
    for i in range(n):
        for j in range(i + 1, n):
            same.append(float(np.dot(emb_t[i], emb_t[j])))
            cross.append(float(np.dot(emb_t[i], emb_d[j])))
    same, cross = np.array(same), np.array(cross)
    lab = np.concatenate([np.ones(len(same)), np.zeros(len(cross))])
    sc = np.concatenate([same, cross])
    order = np.argsort(sc)
    ranks = np.empty(len(sc))
    ranks[order] = np.arange(1, len(sc) + 1)
    auc = (ranks[lab == 1].sum() - len(same) * (len(same) + 1) / 2) / \
        (len(same) * len(cross))
    nn_hits = nn_total = 0
    for i in range(n):
        sims = [(float(np.dot(emb_t[i], emb_t[j])), j) for j in range(n)
                if j != i]
        nn_sim = max(c for c, _ in sims)
        nn_total += 1
        nn_hits += int(nn_sim > float(np.dot(emb_t[i], emb_d[i])))
    return {
        "n_same_pairs": int(len(same)),
        "cos_same_mean": round(float(same.mean()), 4),
        "cos_cross_mean": round(float(cross.mean()), 4),
        "separation_margin": round(float(same.mean() - cross.mean()), 4),
        "roc_auc": round(float(auc), 4),
        "nn_retrieval_rate": round(nn_hits / nn_total, 4) if nn_total else None,
    }


class VideoReaderProxy:
    def __init__(self, dive_doc):
        self.path = str(BASE / dive_doc["proxy_path"])
        self.cap = cv2.VideoCapture(self.path)

    def frame(self, fi):
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
        ok, fr = self.cap.read()
        if not ok:
            self.cap.release()
            self.cap = cv2.VideoCapture(self.path)
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
            ok, fr = self.cap.read()
        if not ok:
            raise RuntimeError(f"proxy seek failed at frame {fi}")
        return fr


if __name__ == "__main__":
    main()
