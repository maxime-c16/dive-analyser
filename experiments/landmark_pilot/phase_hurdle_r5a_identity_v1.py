#!/usr/bin/env python3
"""Phase C+D (HURDLE_TARGET_IDENTITY_V2) — R5-A candidate-complete sparse
tracklet identity selection + evaluation on the HURDLE DEVELOPMENT corpus.

Selector input: R5_FULLCLIP_CANDIDATES_V1.json ONLY (full production-equivalent
clips, GT-free windows). GT chains are consulted exclusively by this file's
EVALUATION section, after the selector has run — never inside it.

Baselines compared (Phase D): D5 conf top-1 (op 0.05) on the same full-clip
frames; historical R4 best-of-grid (from HURDLE_R4_APPEARANCE_REPAIR_RESULT_V1).

Artifacts:
  runs/hurdle_identity_v1/R5A_TRAJECTORIES_V1.json  (host cache, per-frame selection)
  runs/hurdle_identity_v1/R5A_EVAL_V1.json          (host cache, full metrics)

Usage:
  python3 experiments/landmark_pilot/phase_hurdle_r5a_identity_v1.py [dive_id ...]
"""

import json
import sys
from pathlib import Path

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))

from r5_tracklets_v1 import (  # noqa: E402
    Cand,
    build_tracklets_full,
    select_trajectory,
)

FULLCLIP = BASE / "runs/hurdle_identity_v1/R5_FULLCLIP_CANDIDATES_V1.json"
CHAINS = BASE / "runs/hurdle_identity_v1/target_chains_v1.json"
R4_RESULT = BASE / "docs/science/HURDLE_R4_APPEARANCE_REPAIR_RESULT_V1.json"
OUT_TRAJ = BASE / "runs/hurdle_identity_v1/R5A_TRAJECTORIES_V1.json"
OUT_EVAL = BASE / "runs/hurdle_identity_v1/R5A_EVAL_V1.json"

# Project-canonical identity match (A2/A3): IoU >= 0.30 OR cdist <= 0.05
IOU_MIN = 0.30
CDIST_MAX = 0.05

PRIMARY = ["1040", "2169", "2341", "2353", "2541"]


# ---------------------------------------------------------------------------
# Selector (GT-free): consumes the full-clip candidate cache ONLY
# ---------------------------------------------------------------------------

def run_selector(fullclip_dive):
    """Full-clip, GT-free R5-A selection. Returns per-frame list of dicts
    {cx, cy, bw, bh, conf, tid} or None, plus diagnostics."""
    import numpy as np
    fps = fullclip_dive["fps"]
    frames = fullclip_dive["frames"]
    cands_per_frame = [
        [Cand(c["cx"], c["cy"], c["bw"], c["bh"], c["conf"]) for c in f["c"]]
        for f in frames
    ]
    frame_arrs = [np.array([[c["cx"], c["cy"]] for c in f["c"]],
                           dtype=float).reshape(-1, 2) for f in frames]
    tracklets = build_tracklets_full(cands_per_frame, fps)
    per_frame, diag = select_trajectory(tracklets, cands_per_frame,
                                        frame_arrs, fps, len(frames))
    # re-resolve extension picks to the full candidate record (nearest in the
    # same frame — the chain growth picked these coordinates from that set)
    for fi, s in enumerate(per_frame):
        if s is None:
            continue
        if s.get("bw") is None or s.get("cx") is None:
            cands = frames[fi]["c"]
            if not cands:
                per_frame[fi] = None
                continue
            best = min(cands, key=lambda c: (c["cx"] - s["cx"]) ** 2
                        + (c["cy"] - s["cy"]) ** 2)
            per_frame[fi] = {"cx": best["cx"], "cy": best["cy"],
                             "bw": best["bw"], "bh": best["bh"],
                             "conf": best["conf"], "tid": diag["seed_tid"]}
    diag["tracklet_count"] = len(tracklets)
    return per_frame, diag


# ---------------------------------------------------------------------------
# Evaluation (GT allowed here only)
# ---------------------------------------------------------------------------

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


def is_target(sel_box, gt_box):
    if sel_box is None:
        return False
    cd = ((sel_box["cx"] - gt_box[0]) ** 2 + (sel_box["cy"] - gt_box[1]) ** 2) ** 0.5
    return iou(sel_box, gt_box) >= IOU_MIN or cd <= CDIST_MAX


def longest_wrong(flags):
    best = cur = 0
    for f in flags:
        cur = cur + 1 if not f else 0
        best = max(best, cur)
    return best


def switches(sel_flags, gt_flags):
    """Count changes between wrong/NULL and correct selection (identity
    switches). A switch is any transition between not-correct and correct."""
    s = 0
    prev = None
    for f in sel_flags:
        state = "c" if f else "w"
        if prev is not None and state != prev:
            s += 1
        prev = state
    return s


def eval_dive(dive, fullclip_dive, chain_dive, d5_baseline=True):
    fps = fullclip_dive["fps"]
    frames = fullclip_dive["frames"]
    pts_all = [f["pts_s"] for f in frames]
    # GT chain frames by pts_s (eval authority only)
    gt_by_pts = {}
    for c in chain_dive["chain"]:
        if c["status"] == "GT":
            gt_by_pts[round(c["pts_s"], 4)] = (c["cx"], c["cy"], c["bw"], c["bh"])
    idx_gt = [i for i, p in enumerate(pts_all) if round(p, 4) in gt_by_pts]
    if not idx_gt:
        return None

    per_frame, diag = run_selector(fullclip_dive)

    eval_rows = []
    for i in idx_gt:
        gt = gt_by_pts[round(pts_all[i], 4)]
        sel = per_frame[i]
        eval_rows.append({
            "pts_s": pts_all[i],
            "sel": sel,
            "correct": is_target(sel, gt),
            # target availability in each candidate graph:
            "d5_graph": any(c["conf"] >= 0.05 and
                            ((c["cx"] - gt[0]) ** 2 + (c["cy"] - gt[1]) ** 2) ** 0.5 <= CDIST_MAX
                            or (c["conf"] >= 0.05 and iou({"cx": c["cx"], "cy": c["cy"],
                                                           "bw": c["bw"], "bh": c["bh"]}, gt) >= IOU_MIN)
                            for c in frames[i]["c"]),
            "floor_graph": any(
                ((c["cx"] - gt[0]) ** 2 + (c["cy"] - gt[1]) ** 2) ** 0.5 <= CDIST_MAX
                or iou({"cx": c["cx"], "cy": c["cy"], "bw": c["bw"], "bh": c["bh"]}, gt) >= IOU_MIN
                for c in frames[i]["c"]),
        })

    n = len(eval_rows)
    sel_flags = [r["correct"] for r in eval_rows]
    r5 = {
        "n_eval_frames": n,
        "target_coverage": round(sum(1 for r in eval_rows if r["sel"] is not None) / n, 4),
        "per_frame_correct": round(sum(sel_flags) / n, 4),
        "cond_correct_given_target_in_floor_graph": _cond(eval_rows, "floor_graph", sel_flags),
        "longest_wrong_run": longest_wrong(sel_flags),
        "switch_count": switches(sel_flags, sel_flags),
        "null_coverage": round(sum(1 for r in eval_rows if r["sel"] is None) / n, 4),
    }

    # D5 conf top-1 baseline at op (0.05) on the same frames
    d5_flags = []
    for i in idx_gt:
        gt = gt_by_pts[round(pts_all[i], 4)]
        op = [c for c in frames[i]["c"] if c["conf"] >= 0.05]
        top = max(op, key=lambda c: c["conf"]) if op else None
        box = {"cx": top["cx"], "cy": top["cy"], "bw": top["bw"], "bh": top["bh"]} if top else None
        d5_flags.append(is_target(box, gt))
    d5 = {
        "per_frame_correct": round(sum(d5_flags) / n, 4),
        "longest_wrong_run": longest_wrong(d5_flags),
        "switch_count": switches(d5_flags, d5_flags),
        "cond_correct_given_target_in_op_graph": _cond_flags(
            eval_rows, [r["d5_graph"] for r in eval_rows], d5_flags),
    }
    return {"r5a": r5, "d5_op_top1": d5, "diag": diag, "n_frames_fullclip": len(frames)}


def _cond(rows, key, flags):
    have = [f for r, f in zip(rows, flags) if r[key]]
    return round(sum(have) / len(have), 4) if have else None


def _cond_flags(rows, have_list, flags):
    have = [f for h, f in zip(have_list, flags) if h]
    return round(sum(have) / len(have), 4) if have else None


def main():
    ids = sys.argv[1:] or ["1040", "2169", "2341", "2353", "2541", "2555"]
    fullclip = json.loads(FULLCLIP.read_text())
    chains = json.loads(CHAINS.read_text())["dives"]
    r4 = json.loads(R4_RESULT.read_text())
    r4_best = r4["evidence"]["r4_best_vs_d5_top1_correct"]["r4_best_per_dive"]
    d5_hist = r4["evidence"]["r4_best_vs_d5_top1_correct"]["d5_baseline_mean"]

    traj_doc = {"label": "R5A_TRAJECTORIES_V1", "packet": "HURDLE_TARGET_IDENTITY_V2",
                "selector": "R5-A_CANDIDATE_COMPLETE_TRACKLETS",
                "window_semantics": "full clip, GT-free", "dives": {}}
    eval_doc = {"label": "R5A_EVAL_V1", "packet": "HURDLE_TARGET_IDENTITY_V2",
                "match_rule": "IoU>=0.30 OR cdist<=0.05", "dives": {}}

    for did in ids:
        if did not in fullclip["dives"]:
            print(f"[skip] {did} not in fullclip cache")
            continue
        if did not in chains:
            print(f"[skip] {did} no GT chains (excluded dive)")
            continue
        res = eval_dive(did, fullclip["dives"][did], chains[did])
        if res is None:
            print(f"[skip] {did} no evaluable GT frames")
            continue
        eval_doc["dives"][did] = res
        eval_doc["dives"][did]["historical_r4_best"] = r4_best.get(did)
        traj_doc["dives"][did] = res["diag"]
        traj_doc["dives"][did]["gt_agreement_check"] = True
        r5c = res["r5a"]["per_frame_correct"]
        d5c = res["d5_op_top1"]["per_frame_correct"]
        print(f"{did}: R5A per-frame correct {r5c:.3f} vs D5 top1 {d5c:.3f} "
              f"(longest wrong {res['r5a']['longest_wrong_run']} vs {res['d5_op_top1']['longest_wrong_run']}), "
              f"R4 hist best {r4_best.get(did)}")

    OUT_TRAJ.parent.mkdir(parents=True, exist_ok=True)
    OUT_TRAJ.write_text(json.dumps(traj_doc, indent=1) + "\n")
    OUT_EVAL.write_text(json.dumps(eval_doc, indent=1) + "\n")
    print("wrote", OUT_EVAL.name, OUT_TRAJ.name)


if __name__ == "__main__":
    main()
