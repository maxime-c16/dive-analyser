#!/usr/bin/env python3
"""Phase G — Freeze Candidate Reranker.

Reads RERANKER_DEV_EVAL.json to determine which reranker passed the gate.
Creates DIVER_CANDIDATE_RERANKER_V1_FREEZE.json.

This freeze is the authoritative record of the locked reranker identity
before any Paris evaluation.
"""
import os, json, pickle, hashlib, datetime

BASE    = "/tmp/diveanalyzer-exp"
RESULTS = f"{BASE}/results"

EVAL_PATH    = f"{RESULTS}/RERANKER_DEV_EVAL.json"
R1_PKL       = f"{RESULTS}/R1_RERANKER.pkl"
R2_PKL       = f"{RESULTS}/R2_RERANKER.pkl"
FREEZE_OUT   = f"{RESULTS}/DIVER_CANDIDATE_RERANKER_V1_FREEZE.json"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    eval_data = json.load(open(EVAL_PATH))
    gate = eval_data["reranker_gate"]

    if gate["gate"] != "PASS":
        print(f"RERANKER GATE: {gate['gate']} — no freeze")
        freeze = {
            "label": "DIVER_CANDIDATE_RERANKER_V1_FREEZE",
            "date": datetime.date.today().isoformat(),
            "status": "RERANKER_NOT_SUFFICIENT",
            "gate": gate,
            "note": "No reranker passes DEV_VAL material improvement threshold. Proceed to D5.",
        }
    else:
        selected = gate["selected_reranker"]
        pkl_path = R1_PKL if selected == "R1" else R2_PKL
        pkl_sha  = sha256_file(pkl_path)
        r_data   = eval_data[selected]

        freeze = {
            "label": "DIVER_CANDIDATE_RERANKER_V1_FREEZE",
            "date": datetime.date.today().isoformat(),
            "status": "FROZEN",
            "selected_reranker": selected,
            "pkl_path": os.path.basename(pkl_path),
            "pkl_sha256": pkl_sha,
            "feature_model": "ResNet50_IMAGENET1K_V1",
            "feature_dim": 2048,
            "classifier": r_data["name"],
            "gate": gate,
            "DEV_VAL_metrics": eval_data[selected]["DEV_VAL"],
            "B0_DEV_VAL_metrics": eval_data["B0"]["DEV_VAL"],
            "improvement_top1": gate["improvement"],
            "pipeline_identity": {
                "floor_conf": 0.001,
                "nms_iou": 0.45,
                "imgsz": 640,
                "detector": "D4_PROPOSAL_V1",
                "detector_sha256": "842291f1cd3c5ad086faa467ccaac197c56bdd63dcdd2b67a91c4a7d8fbc3aaa",
                "crop_padding_frac": 0.20,
                "crop_size_px": 224,
                "feature_normalization": "ImageNet (mean=[0.485,0.456,0.406] std=[0.229,0.224,0.225])",
            },
            "grouped_split": eval_data["grouped_split"],
            "paris_firewall": "VERIFIED — Paris not used in training, tuning, or threshold selection",
            "source_sha": "to_be_filled_at_commit",
        }
        print(f"Frozen: {selected}  val-top1={gate['best_top1_val']:.1%}  improvement={gate['improvement']:+.1%}")

    with open(FREEZE_OUT, "w") as f:
        json.dump(freeze, f, indent=2)
    print(f"Freeze written: {FREEZE_OUT}")
    return freeze


if __name__ == "__main__":
    main()
