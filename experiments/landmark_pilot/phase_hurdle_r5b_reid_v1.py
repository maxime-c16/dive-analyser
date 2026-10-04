#!/usr/bin/env python3
"""Phase G (HURDLE_TARGET_IDENTITY_V2) — R5-B_REID_GLOBAL_ASSOCIATION driver.

Conditional frozen-ReID association on the R5-A candidate-complete graph:
  - appearance: frozen OSNet x1.0 (Market-1501), Phase E passed
    (ROC-AUC 0.82-0.98 on the ordinary DEVELOPMENT dives);
  - association: appearance+motion-consistent tracklet merging
    (r5b_association_v1) — no top-12 truncation, no encoder training,
    D5 proposals remain the frozen 360p detector representation;
  - full-clip, GT-free windows; GT consulted by the evaluation only.

Artifacts:
  runs/hurdle_identity_v1/R5B_TRAJECTORIES_V1.json (host cache, per-frame selection)
  runs/hurdle_identity_v1/R5B_EVAL_V1.json         (host cache, metrics)

Usage:
  caffeinate -i -s .venv-reid/bin/python experiments/landmark_pilot/phase_hurdle_r5b_reid_v1.py [dive_id ...]
"""

import json
import sys
from pathlib import Path

import numpy as np
import torch

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))

import r5_tracklets_v1 as R5  # noqa: E402
import r5b_association_v1 as R5B  # noqa: E402
from r5_tracklets_v1 import Cand  # noqa: E402
from phase_hurdle_e_appearance_benchmark_v1 import (  # noqa: E402
    OSNetWrap, crop_tensor, to_input, FULLCLIP, CHAINS, VideoReader,
)

R4_RESULT = BASE / "docs/science/HURDLE_R4_APPEARANCE_REPAIR_RESULT_V1.json"
OUT_TRAJ = BASE / "runs/hurdle_identity_v1/R5B_TRAJECTORIES_V1.json"
OUT_EVAL_R5B = BASE / "runs/hurdle_identity_v1/R5B_EVAL_V1.json"
OSNET_PATH = BASE / "models/reid/osnet_x1_0_market1501.pth"
IOU_MIN = 0.30
CDIST_MAX = 0.05
W_APP_SCORE = 0.5


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


def run_dive(dive, chains_dive, model, device):
    fps = dive["fps"]
    frames = dive["frames"]
    n = len(frames)
    cands_per_frame = [
        [Cand(c["cx"], c["cy"], c["bw"], c["bh"], c["conf"]) for c in f["c"]]
        for f in frames
    ]
    cap = VideoReader(dive)
    cache = {}

    @torch.no_grad()
    def embed_fn(fi, k):
        key = (fi, k)
        if key in cache:
            return cache[key]
        c = frames[fi]["c"][k]
        t = to_input([crop_tensor(cap.frame(fi),
                                  (c["cx"], c["cy"], c["bw"], c["bh"]))],
                     (256, 128)).to(device)
        v = torch.nn.functional.normalize(model(t), dim=1)[0].cpu().numpy()
        cache[key] = v
        return v

    tracklets = R5.build_tracklets_full(cands_per_frame, fps)
    per_frame, diag = R5B.select_component(
        tracklets, cands_per_frame, None, fps, n, embed_fn,
        w_app=W_APP_SCORE)

    # evaluation (GT consulted only here)
    gt = {}
    for c in chains_dive["chain"]:
        if c["status"] == "GT":
            gt[round(c["pts_s"], 4)] = (c["cx"], c["cy"], c["bw"], c["bh"])
    idx = [i for i, f in enumerate(frames) if round(f["pts_s"], 4) in gt]
    sel_flags = []
    for i in idx:
        g = gt[round(frames[i]["pts_s"], 4)]
        s = per_frame[i]
        ok = False
        if s is not None:
            cd = ((s["cx"] - g[0]) ** 2 + (s["cy"] - g[1]) ** 2) ** 0.5
            ok = iou(s, g) >= IOU_MIN or cd <= CDIST_MAX
        sel_flags.append(ok)
    ngt = len(idx)
    res = {
        "n_eval_frames": ngt,
        "per_frame_correct": round(sum(sel_flags) / ngt, 4),
        "longest_wrong_run": longest_wrong(sel_flags),
        "null_coverage": round(sum(1 for i in idx if per_frame[i] is None) / ngt, 4),
        "diag": diag,
    }
    return per_frame, res


@torch.no_grad()
def main():
    ids = sys.argv[1:] or ["1040", "2169", "2341", "2353", "2541", "2555"]
    fullclip = json.loads(FULLCLIP.read_text())
    chains = json.loads(CHAINS.read_text())["dives"]
    r4 = json.loads(R4_RESULT.read_text())
    r4_best = r4["evidence"]["r4_best_vs_d5_top1_correct"]["r4_best_per_dive"]

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = OSNetWrap(OSNET_PATH).to(device)
    model.eval()

    traj_doc = {"label": "R5B_TRAJECTORIES_V1",
                "packet": "HURDLE_TARGET_IDENTITY_V2",
                "selector": "R5-B_REID_GLOBAL_ASSOCIATION",
                "appearance": "frozen OSNet x1.0 Market-1501 (no training)",
                "window_semantics": "full clip, GT-free", "dives": {}}
    eval_doc = {"label": "R5B_EVAL_V1", "packet": "HURDLE_TARGET_IDENTITY_V2",
                "match_rule": "IoU>=0.30 OR cdist<=0.05", "dives": {}}
    for did in ids:
        if did not in fullclip["dives"] or did not in chains:
            continue
        per_frame, res = run_dive(fullclip["dives"][did], chains[did],
                                  model, device)
        res["historical_r4_best"] = r4_best.get(did)
        eval_doc["dives"][did] = res
        traj_doc["dives"][did] = res["diag"]
        print(f"{did}: R5-B per-frame correct {res['per_frame_correct']:.3f} "
              f"(longest wrong {res['longest_wrong_run']}) "
              f"members={res['diag'].get('n_members')} app={res['diag'].get('app_mean')}")
    OUT_TRAJ.parent.mkdir(parents=True, exist_ok=True)
    OUT_TRAJ.write_text(json.dumps(traj_doc, indent=1) + "\n")
    OUT_EVAL_R5B.write_text(json.dumps(eval_doc, indent=1) + "\n")
    print("wrote", OUT_TRAJ.name, OUT_EVAL_R5B.name)


if __name__ == "__main__":
    main()
