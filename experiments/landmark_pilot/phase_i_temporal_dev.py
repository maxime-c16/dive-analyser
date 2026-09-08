#!/usr/bin/env python3
"""Phase I — Temporal Selection After Reranking (DEVELOPMENT only).

Compare T0 (per-frame top R1) vs T1 (R1 + persistence path) on DEVELOPMENT dives.
Limited to anchor frames since we only have 3 GT annotations per dive,
so T1 persistence path cannot be fully evaluated without running full-video inference.

This script reports:
  - T0 results: what R1 gives frame-by-frame (from RERANKER_DEV_EVAL.json)
  - T1 reasoning: whether temporal continuity would plausibly help
  - Selector freeze: T0 (per-frame R1) is frozen as the Phase J selector,
    since T1 cannot be rigorously evaluated on 3-anchor data alone.

Output: TEMPORAL_SELECTION_V1.json
"""
import os, json, datetime

RESULTS = "/tmp/diveanalyzer-exp/results"

def main():
    eval_data = json.load(open(f"{RESULTS}/RERANKER_DEV_EVAL.json"))

    r1_train = eval_data["R1"]["DEV_TRAIN"]
    r1_val   = eval_data["R1"]["DEV_VAL"]
    b0_val   = eval_data["B0"]["DEV_VAL"]

    print("PHASE I — Temporal Selection Analysis")
    print("="*60)
    print(f"\nT0 (per-frame R1 top-1):")
    print(f"  DEV_TRAIN top-1: {r1_train['top1_recall']:.1%}")
    print(f"  DEV_VAL   top-1: {r1_val['top1_recall']:.1%}")
    print(f"  DEV_VAL   MRR:   {r1_val['mrr']:.3f}")
    print(f"\nB0 baseline:")
    print(f"  DEV_VAL   top-1: {b0_val['top1_recall']:.1%}")

    print(f"\nT1 (R1 + temporal continuity) assessment:")
    print("  T1 requires running R1 on all frames of each dive (not just 3 GT anchors).")
    print("  With only 3 anchor frames per dive, temporal path cannot be rigorously evaluated.")
    print("  Evidence from DEV_TRAIN: R1 achieves 100% top-1 → no inter-frame conflicts to resolve.")
    print("  DEV_VAL 1/2 water_contact fails: isolated frame failure (not systematic path error).")
    print("  FINDING: T1 would not help the 1 DEV_VAL failure (single frame, no neighboring anchors).")
    print("  DECISION: Freeze T0 (per-frame R1) as Phase J selector.")
    print("  RATIONALE: T1 spatial path (Viterbi) was shown to REGRESS with D4 FPs (D4 cycle).")
    print("             R1 already encodes appearance; adding Viterbi path risks propagating")
    print("             false-positive selections. T0 is simpler and safer.")

    decision = {
        "label": "TEMPORAL_SELECTION_V1",
        "date": datetime.date.today().isoformat(),
        "T0": {
            "description": "Per-frame top-1 R1 candidate",
            "DEV_TRAIN_top1": r1_train["top1_recall"],
            "DEV_VAL_top1":   r1_val["top1_recall"],
            "DEV_VAL_mrr":    r1_val["mrr"],
        },
        "T1": {
            "description": "R1 + temporal continuity bonus",
            "evaluation_status": "DEFERRED — requires full-video inference, not feasible with 3 anchor frames",
            "rationale": (
                "T1 cannot be rigorously evaluated on 3 anchor frames per dive. "
                "Viterbi spatial path was shown to regress with D4-era FPs. "
                "T0 achieves 100% DEV_TRAIN and 83.3% DEV_VAL, already a major improvement. "
                "T1 risk: propagating apex/water-contact FP errors across full trajectory."
            ),
        },
        "frozen_selector": "T0",
        "frozen_selector_description": "Per-frame top-1 R1 (ResNet50 visual reranker) score",
        "selector_gate": {
            "DEV_VAL_top1_T0": r1_val["top1_recall"],
            "DEV_VAL_top1_B0": b0_val["top1_recall"],
            "improvement": r1_val["top1_recall"] - b0_val["top1_recall"],
        },
        "paris_firewall": "Paris excluded from temporal analysis",
        "paris_trajectory_gate": "TRAJECTORY_INPUT_FAIL (apex rank=2 after R1)",
        "d5_required": True,
        "d5_rationale": (
            "Paris apex: D4_rank=10 → R1_rank=2. "
            "The apex target is visually distinct but not sufficiently so from spectators "
            "with the current DEVELOPMENT training distribution. "
            "D5 aims to add more apex/water-contact frames to improve R1 generalization "
            "and push the diver to rank 1 at Paris apex."
        ),
    }

    out = f"{RESULTS}/TEMPORAL_SELECTION_V1.json"
    with open(out, "w") as f:
        json.dump(decision, f, indent=2)
    print(f"\nTemporal selection analysis saved: {out}")
    return decision

if __name__ == "__main__":
    main()
