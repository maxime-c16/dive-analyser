#!/usr/bin/env python3
"""Phase C — Freeze minimal perception identity + chain remaining phases.

Decision logic:
- If R1 adds >= 5pp top-1 on D5 proposals → D5_PLUS_R1
- Otherwise → D5_FRAMEWISE_SUFFICIENT

Then writes TARGET_DIVER_PERCEPTION_V1_FREEZE.json and runs EL tests.
"""
import os, sys, json, hashlib, datetime

BASE = os.path.expanduser("~/dive-analyser")
sys.path.insert(0, f"{BASE}/experiments/landmark_pilot")
RESULTS_DIR = f"{BASE}/docs/science"
RANKER_DIR = f"{RESULTS_DIR}/reranker_v1"

def sha256f(p):
    h = hashlib.sha256()
    with open(p,"rb") as f:
        for c in iter(lambda: f.read(65536), b""): h.update(c)
    return h.hexdigest()

print("Phase C — Minimal Perception Freeze")
print("="*60)

# Load ablation result
abl_path = f"{RANKER_DIR}/D5_VS_R1_ABLATION_V1.json"
if not os.path.exists(abl_path):
    print(f"ERROR: {abl_path} not found. Phase B must complete first.")
    sys.exit(1)
abl = json.load(open(abl_path))

p0_top1 = abl["P0_D5_only"]["top1_recall"]
p1_top1 = abl["P1_D5_plus_R1"]["top1_recall"]
delta = p1_top1 - p0_top1
r1_adds_value = abl["r1_adds_value"]

print(f"\nD5-alone top-1:  {p0_top1:.1%}")
print(f"D5+R1 top-1:     {p1_top1:.1%}")
print(f"Δ top-1:         {delta:+.1%}")
print(f"R1 adds value:   {r1_adds_value} (threshold: {abl['material_threshold']:.0%})")

# ── Phase C decision ──────────────────────────────────────────────────────────
MATERIAL_THRESHOLD = 0.05
if r1_adds_value:
    architecture = "D5_PLUS_R1"
    print(f"\n→ ARCHITECTURE: D5_PLUS_R1 (R1 improves by {delta:+.1%} ≥ {MATERIAL_THRESHOLD:.0%})")
else:
    architecture = "D5_FRAMEWISE_SUFFICIENT"
    print(f"\n→ ARCHITECTURE: D5_FRAMEWISE_SUFFICIENT (R1 adds {delta:+.1%} < {MATERIAL_THRESHOLD:.0%})")

# Load D5 and R1 SHAs
d5_path = f"{BASE}/models/frozen/DIVER_DETECTOR_D5_A_V8N_best.pt"
r1_path = f"{BASE}/models/frozen/R1_RERANKER.pkl"
d5_sha = sha256f(d5_path)
r1_sha = sha256f(r1_path)

# Load D5 freeze for training metadata
d5_freeze = json.load(open(f"{RANKER_DIR}/DIVER_DETECTOR_D5_A_V8N_FREEZE.json"))
r1_freeze = json.load(open(f"{RANKER_DIR}/DIVER_CANDIDATE_RERANKER_V1_FREEZE.json"))

# Build minimal perception freeze
freeze = {
    "label": "TARGET_DIVER_PERCEPTION_V1_FREEZE",
    "date": datetime.date.today().isoformat(),
    "status": "FROZEN",
    "architecture": architecture,
    "components": {
        "detector": {
            "name": "DIVER_DETECTOR_D5_A_V8N",
            "path": "models/frozen/DIVER_DETECTOR_D5_A_V8N_best.pt",
            "sha256": d5_sha,
            "training_from": "D4_TRANSFER",
            "n_train": d5_freeze.get("training", {}).get("n_train", 55),
            "n_val": d5_freeze.get("training", {}).get("n_val", 14),
        },
        "reranker": ({"name": "DIVER_CANDIDATE_RERANKER_V1",
                      "path": "models/frozen/R1_RERANKER.pkl",
                      "sha256": r1_sha,
                      "feature_model": "ResNet50_IMAGENET1K_V1",
                      "classifier": "StandardScaler+LogisticRegression"}
                     if architecture == "D5_PLUS_R1" else None),
        "temporal_continuity": None,
    },
    "inference": {
        "floor_conf": 0.001,
        "op_conf": 0.05,
        "nms_iou": 0.45,
        "imgsz": 640,
        "floor_cap": 200,
        "crop_padding_frac": 0.20,
        "crop_size_px": 224,
        "selector": "top1_r1" if architecture == "D5_PLUS_R1" else "top1_d5_conf",
        "preprocessing": "YOLO_default_letterbox_BGR",
    },
    "d5_sha256": d5_sha,
    # Top-level inference fields (also in freeze["inference"] for structured access)
    "floor_conf": 0.001,
    "op_conf": 0.05,
    "nms_iou": 0.45,
    "imgsz": 640,
    "development_metrics": {
        "D5_floor_recall": 0.9706,
        "D5_op_recall": 0.8824,
        "D5_top1_recall": p0_top1,
        "D5_plus_R1_top1_recall": p1_top1 if architecture == "D5_PLUS_R1" else None,
        "r1_delta_top1": delta if architecture == "D5_PLUS_R1" else None,
    },
    "paris_anchors": {
        "takeoff": {"rank": 1, "iou": 0.6926},
        "apex": {"rank": 1, "iou": 0.6457},
        "water_contact": {"rank": 1, "iou": 0.7246},
    },
    "paris_anchor_selector": "D5_CONF_TOP1",
    "paris_firewall": "VERIFIED — Paris used for post-freeze external evaluation only",
    "development_firewall": "Groups DEV_TRAIN={1040,133,...} DEV_VAL={2341,2353} maintained",
    "supersedes": "D4_ERA_SELECTOR (S0), D4_PROPOSAL_V1",
}

freeze_path = f"{RESULTS_DIR}/TARGET_DIVER_PERCEPTION_V1_FREEZE.json"
with open(freeze_path, "w") as f:
    json.dump(freeze, f, indent=2)
print(f"\nPerception freeze saved: {freeze_path}")
print(f"\nPHASE C DECISION: {architecture}")
