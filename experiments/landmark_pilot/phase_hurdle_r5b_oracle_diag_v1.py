#!/usr/bin/env python3
"""R5-B oracle diagnostic (HURDLE_TARGET_IDENTITY_V2, Phase G diagnostic).

DIAGNOSTIC ONLY — measures the appearance-association CEILING, not a
deployable selector: the appearance prototype is seeded from the GT chain's
preparation crop (EVALUATION AUTHORITY, explicitly NOT an inference input in
the frozen selector; this run exists to bound what a GT-free prototype
selection mechanism would have to achieve).

Per dive: per-frame candidate selection by appearance (max cosine to the
prep prototype among floor candidates), with prototype EWMA adaptation and
per-frame geometric continuity gating from the R5-A full-clip graph.

Artifact: runs/hurdle_identity_v1/R5B_ORACLE_DIAGNOSTIC_V1.json
"""

import json
import sys
from pathlib import Path

import numpy as np
import torch

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))

import r5_tracklets_v1 as R5  # noqa: E402
from r5_tracklets_v1 import Cand  # noqa: E402
from phase_hurdle_e_appearance_benchmark_v1 import (  # noqa: E402
    OSNetWrap, FULLCLIP, CHAINS, VideoReader, crop_tensor, to_input,
)

OUT = BASE / "runs/hurdle_identity_v1/R5B_ORACLE_DIAGNOSTIC_V1.json"
OSNET_PATH = BASE / "models/reid/osnet_x1_0_market1501.pth"
IOU_MIN = 0.30
CDIST_MAX = 0.05
PROTO_EWMA = 0.05
GATE_MAX = 0.25           # per-frame geometric continuity gate (rel, cents)
STRIDE = 3                # evaluate every STRIDE-th frame for speed


def iou(a, b):
    ax1, ay1 = a["cx"] - a["bw"] / 2, a["cy"] - a["bh"] / 2
    ax2, ay2 = a["cx"] + a["bw"] / 2, a["cy"] + a["bh"] / 2
    bx1, by1 = b[0] - b[2] / 2, b[1] - b[3] / 2
    bx2, by2 = b[0] + b[2] / 2, b[1] + b[3] / 2
    ix = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    iy = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = ix * iy
    union = a["bw"] * a["bh"] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def longest_wrong(flags):
    best = cur = 0
    for f in flags:
        cur = cur + 1 if not f else 0
        best = max(best, cur)
    return best


@torch.no_grad()
def main():
    ids = sys.argv[1:] or ["1040", "2169", "2341", "2353", "2541", "2555"]
    fullclip = json.loads(FULLCLIP.read_text())
    chains = json.loads(CHAINS.read_text())["dives"]
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = OSNetWrap(OSNET_PATH).to(device)
    model.eval()
    doc = {"label": "R5B_ORACLE_DIAGNOSTIC_V1",
           "packet": "HURDLE_TARGET_IDENTITY_V2",
           "gt_usage": "prototype seed ONLY (diagnostic ceiling, not inference)",
           "dives": {}}
    for did in ids:
        dive = fullclip["dives"][did]
        fps = dive["fps"]
        frames = dive["frames"]
        n = len(frames)
        gt = {}
        for c in chains[did]["chain"]:
            if c["status"] == "GT":
                gt[round(c["pts_s"], 4)] = (c["cx"], c["cy"], c["bw"], c["bh"])
        meta = dive["gt_eval_only"]["gt"]
        tk = meta["takeoff"]
        cap = VideoReader(dive)
        cache = {}

        @torch.no_grad()
        def embed(fi, k):
            if (fi, k) in cache:
                return cache[(fi, k)]
            c = frames[fi]["c"][k]
            try:
                fr = cap.frame(fi)
            except RuntimeError:
                cache[(fi, k)] = None
                return None
            t = to_input([crop_tensor(fr,
                                      (c["cx"], c["cy"], c["bw"], c["bh"]))],
                         (256, 128)).to(device)
            v = torch.nn.functional.normalize(model(t), dim=1)[0].cpu().numpy()
            cache[(fi, k)] = v
            return v

        # prototype: GT prep crop (0.5 s before takeoff)
        prep_i = max(0, int((tk - 0.5) * fps))
        gprep = gt.get(round(frames[prep_i]["pts_s"], 4))
        while prep_i < n and (round(frames[prep_i]["pts_s"], 4) not in gt
                              or not frames[prep_i]["c"]):
            prep_i += 1
        if prep_i >= n:
            print(f"[skip] {did}: no prep frame with candidates")
            continue
        g = gt[round(frames[prep_i]["pts_s"], 4)]
        ks = [k for k, c in enumerate(frames[prep_i]["c"])
              if ((c["cx"] - g[0]) ** 2 + (c["cy"] - g[1]) ** 2) ** 0.5 <= 0.05]
        proto = embed(prep_i, ks[0] if ks else 0)

        # appearance-guided per-frame selection over the full clip
        flow_hack = None  # geometry: continuity gate on RAW centers (cheap)
        sel = [None] * n
        last = None
        for fi in range(n):
            cands = frames[fi]["c"]
            if not cands:
                last = None
                continue
            scored = []
            for k, c in enumerate(cands):
                if last is not None and ((c["cx"] - last[0]) ** 2
                                         + (c["cy"] - last[1]) ** 2) ** 0.5 > GATE_MAX:
                    continue
                scored.append([0.0, k, c])
            # embed only the geometrically plausible few (nearest to last)
            if last is not None:
                scored.sort(key=lambda r: ((cands[r[1]]["cx"] - last[0]) ** 2
                                           + (cands[r[1] if False else r[1]]["cy"] - last[1]) ** 2))
            for r in scored[:6]:
                v = embed(fi, r[1])
                if v is None:
                    scored.remove(r)
                    continue
                r[0] = float(v @ proto)
            if not scored:
                last = None
                continue
            scored.sort(reverse=True)
            cosv, k, c = scored[0]
            sel[fi] = {"cx": c["cx"], "cy": c["cy"], "bw": c["bw"],
                       "bh": c["bh"], "conf": c["conf"], "cos": cosv}
            # prototype EWMA toward the selected crop
            v = embed(fi, k)
            np_ = (1 - PROTO_EWMA) * proto + PROTO_EWMA * (v if v is not None else proto)
            nn_ = np.linalg.norm(np_)
            proto = np_ / nn_ if nn_ > 0 else proto
            last = (c["cx"], c["cy"])
        # evaluate on GT frames (stride)
        idx = [i for i, f in enumerate(frames) if round(f["pts_s"], 4) in gt]
        idx = idx[::STRIDE]
        flags = []
        for i in idx:
            g = gt[round(frames[i]["pts_s"], 4)]
            s = sel[i]
            ok = False
            if s is not None:
                cd = ((s["cx"] - g[0]) ** 2 + (s["cy"] - g[1]) ** 2) ** 0.5
                ok = iou(s, g) >= IOU_MIN or cd <= CDIST_MAX
            flags.append(ok)
        res = {
            "n_eval_frames": len(idx),
            "per_frame_correct": round(sum(flags) / len(idx), 4),
            "longest_wrong_run": longest_wrong(flags),
            "null_coverage": round(sum(1 for i in idx if sel[i] is None) / len(idx), 4),
        }
        doc["dives"][did] = res
        print(f"{did}: ORACLE per-frame correct {res['per_frame_correct']:.3f} "
              f"(longest wrong {res['longest_wrong_run']})")
    OUT.write_text(json.dumps(doc, indent=1) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
