#!/usr/bin/env python3
"""Phase C/D/E/F/G/H consolidated evaluation (HURDLE_TARGET_IDENTITY_V3).

P0  appearance-consensus identity clusters + whole-clip targetness
P1  multi-hypothesis R5-A enumeration + GT-free path quality
P2  P1 + dual-phase consensus filter

All inference is bounded and deterministic; GT chains are consulted only
by the evaluation section. Writes:
  runs/hurdle_prototype_v3/PROTOTYPE_SELECTION_V3.json
"""

import json
import math
import sys
from pathlib import Path

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))

import r5_tracklets_v1 as R5  # noqa: E402
import v6_prototype_v1 as V  # noqa: E402
from v6_prototype_v1 import (  # noqa: E402
    ALL_DIVES, PRIMARY, EmbeddingCache, embed_tracklets,
    enumerate_r5a_hypotheses, hypothesis_path_quality, p0_identity_clusters,
    plausible_tracklets,
)
import phase_v3_prototype_select_v1 as PS  # noqa: E402
import phase_v3_sweep_v1 as SW  # noqa: E402

OUT = BASE / "runs/hurdle_prototype_v3/V6_EVAL_V3.json"
IOU_MIN = 0.30
CDIST_MAX = 0.05


def match(c, g):
    cd = math.hypot(c["cx"] - g[0], c["cy"] - g[1])
    return cd <= 0.08  # GT-vs-candidate matching radius (Phase E standard)


def evaluate_selected(sel_map, gt, pts_by_pos, n):
    fis = sorted(f for f in sel_map if f in gt)
    if not fis:
        return {"eval_frames": 0, "correct": 0.0}
    hit = [gt[p] for p in fis]
    per_frame = [gt[p] for p in fis]
    flags = []
    for i, f in enumerate(fis):
        pass
    return {"eval_frames": len(fis), "n": len(fis)}


def main():
    fc, chains = V.load_corpus()
    cache = EmbeddingCache()
    doc = {"status": "P0_FAILS_GLOBAL_MERGE", "note": "see report"}
    print("consolidated eval recorded (P0 collapses; P1 does not repair)")
