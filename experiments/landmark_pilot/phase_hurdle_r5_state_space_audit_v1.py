#!/usr/bin/env python3
"""Phase A (HURDLE_TARGET_IDENTITY_V2 packet) — R4 state-space failure audit.

Quantifies how often the true target diver was actually present in R4's
candidate graph. R4 (HURDLE_TARGET_IDENTITY packet) restricted its state space
to the top-12 floor candidates + NULL; this audit measures per-dive
candidate_graph_target_recall@K for K in {12, 24, 48, 96, 200(cap)} using the
committed per-frame target ranks from HURDLE_TARGET_IDENTITY_CLASSIFICATION_V1
(floor conf 0.001, NMS 0.45, imgsz 640, frozen D5-A; target rank 0 = top).

Also answers A1: what fraction of R4's per-frame failure is explained by
target exclusion from its top-12 graph (target_rank >= 12 on evaluable frames).

Evaluable frames = classes {TARGET_AVAILABLE_NOT_TOP1, TARGET_TOP1_CORRECT}
(WATER / AMBIGUOUS_GT frames have no established GT identity to audit).

No inference is performed; GT (anchors/chains) is used only to *evaluate*
candidate-graph coverage, never as inference input.

Artifact: runs/hurdle_identity_v1/R5_STATE_SPACE_AUDIT_V1.json (host cache)

Usage:
  python3 experiments/landmark_pilot/phase_hurdle_r5_state_space_audit_v1.py
"""

import json
import statistics
from collections import Counter
from pathlib import Path

BASE = Path(__file__).parents[2]
CLS_PATH = BASE / "docs/science/HURDLE_TARGET_IDENTITY_CLASSIFICATION_V1.json"
OUT_PATH = BASE / "runs/hurdle_identity_v1/R5_STATE_SPACE_AUDIT_V1.json"

KS = [12, 24, 48, 96, 200]
R4_K = 12  # R4's candidate graph state space: top-12 floor candidates + NULL

EVALUABLE = {"TARGET_AVAILABLE_NOT_TOP1", "TARGET_TOP1_CORRECT"}


def main():
    cls = json.loads(CLS_PATH.read_text())
    out = {
        "label": "R5_STATE_SPACE_AUDIT_V1",
        "packet": "HURDLE_TARGET_IDENTITY_V2",
        "source": "docs/science/HURDLE_TARGET_IDENTITY_CLASSIFICATION_V1.json",
        "rank_convention": "target_rank = 0-based index in conf-sorted floor candidate set (conf>=0.001, cap 200); inclusion@K = target_rank < K",
        "r4_state_space": {
            "graph": "frames x (top-12 floor candidates + NULL)",
            "K": R4_K,
        },
        "evaluable_classes": sorted(EVALUABLE),
        "dives": {},
    }

    for dive, info in cls["dives"].items():
        pf = info["per_frame"]
        ev = [f for f in pf if f["class"] in EVALUABLE]
        ranks = [f["target_rank"] for f in ev if f.get("target_rank") is not None]
        missing = [f for f in ev if f.get("target_rank") is None]
        rec = {
            "n_evaluable": len(ev),
            "n_target_rank_known": len(ranks),
            "n_target_rank_unknown": len(missing),
            "recall": {},
            "rank_stats": None,
            "a1": {},
        }
        if ranks:
            rec["rank_stats"] = {
                "min": min(ranks),
                "max": max(ranks),
                "median": statistics.median(ranks),
                "p75": int(statistics.quantiles(ranks, n=4)[2]),
                "p90": int(statistics.quantiles(ranks, n=10)[8]),
            }
            for k in KS:
                in_k = sum(1 for r in ranks if r < k)
                rec["recall"][f"K={k}"] = round(in_k / len(ranks), 4)
            excluded_by_r4 = sum(1 for r in ranks if r >= R4_K)
            rec["a1"] = {
                f"frames_with_target_excluded_from_top{R4_K}": excluded_by_r4,
                f"fraction_target_excluded_from_top{R4_K}": round(
                    excluded_by_r4 / len(ranks), 4
                ),
                "note": "On excluded frames R4's selector could never output the target regardless of appearance quality; appearance is only the residual failure mode on included frames.",
            }
        out["dives"][dive] = rec

    # A1 aggregate over the primary ordinary DEVELOPMENT identity set
    primary = ["1040", "2169", "2341", "2353", "2541"]
    tot_ev = tot_excl = 0
    per = {}
    for dive in primary:
        a1 = out["dives"][dive]["a1"]
        if a1:
            per[dive] = a1[f"fraction_target_excluded_from_top{R4_K}"]
            tot_ev += out["dives"][dive]["n_target_rank_known"]
            tot_excl += a1[f"frames_with_target_excluded_from_top{R4_K}"]
    out["a1_primary_aggregate"] = {
        "dives": primary,
        "n_evaluable_frames": tot_ev,
        f"n_frames_target_excluded_from_top{R4_K}": tot_excl,
        f"fraction_target_excluded_from_top{R4_K}": round(tot_excl / tot_ev, 4) if tot_ev else None,
        "per_dive": per,
        "causal_reading": None,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=1) + "\n")

    # Console summary
    print(f"{'dive':>6} {'n_eval':>7}", *[f"{'@'+str(k):>7}" for k in KS], f"{'excl@12':>9}")
    for dive in primary + ["2555"]:
        rec = out["dives"][dive]
        if not rec["rank_stats"]:
            print(f"{dive:>6} {rec['n_evaluable']:>7}  (no established GT identity)")
            continue
        vals = [f"{rec['recall'][f'K={k}']:.3f}" for k in KS]
        print(f"{dive:>6} {rec['n_evaluable']:>7}", *[f"{v:>7}" for v in vals], f"{rec['a1'][f'fraction_target_excluded_from_top{R4_K}']:>9.3f}")
    print("\nA1 aggregate (primary):", json.dumps(out["a1_primary_aggregate"]["causal_reading"] or "see artifact"))
    print(json.dumps(out["a1_primary_aggregate"], indent=1))


if __name__ == "__main__":
    main()
