#!/usr/bin/env python3
"""S0_HIGHEST_CONFIDENCE — baseline selector.

Reproduces the simplest possible current-behavior baseline: at every frame, pick the
raw D3.1 candidate with the highest confidence. No continuity, no NULL reasoning.
This is the explicit Phase G baseline the packet asks to freeze/reproduce exactly,
distinct from the historical N0 (framewise-highest-confidence + deterministic
continuity gate) already used for Paris/PHASE_MN — S0 removes the continuity term
entirely so its failure modes can be measured in isolation.
"""
import json, sys


def select_s0(raw):
    frames = raw["frames"]
    traj = []
    for fr in frames:
        cands = fr["all_candidates"]
        if not cands:
            traj.append(None)
            continue
        best = max(cands, key=lambda c: c["conf"])
        traj.append(best)
    return traj


def run(raw_path, out_path):
    raw = json.load(open(raw_path))
    traj = select_s0(raw)
    out = {
        "selector": "S0_HIGHEST_CONFIDENCE",
        "video": raw["video"],
        "n_frames": raw["n_frames"],
        "points": [
            {"frame_index": fr["frame_index"], "pts_s": fr["pts_s"],
             "selected": t}
            for fr, t in zip(raw["frames"], traj)
        ],
    }
    json.dump(out, open(out_path, "w"))
    n_null = sum(1 for t in traj if t is None)
    print(f"{raw_path}: {len(traj)} frames, {n_null} NULL")


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2])
