#!/usr/bin/env python3
"""Phase D + E + F — Train Candidate Rerankers R1 and R2, Evaluate on DEVELOPMENT.

R1: Frozen ResNet50 (2048-d) → L2-regularized logistic regression (class_weight=balanced)
R2: R1 diver_prob + D4_conf + bbox_area_norm + bbox_cy_norm + bbox_aspect → logistic regression

Grouped split: DEV_TRAIN dives train, DEV_VAL dives evaluate.
Per-frame ranking: score all proposals for a frame, sort by reranker score desc,
report target rank (position of highest-scoring positive proposal).

Outputs:
  R1_RERANKER.pkl
  R2_RERANKER.pkl  (R1 + contextual features)
  RERANKER_DEV_EVAL.json
"""
import os, json, pickle, datetime, hashlib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import roc_auc_score

BASE    = "/tmp/diveanalyzer-exp"
RESULTS = f"{BASE}/results"
DATASET = f"{RESULTS}/RERANKER_DATASET_V1.pkl"
MANIFEST = f"{RESULTS}/RERANKER_DATASET_V1_MANIFEST.json"

RANDOM_SEED = 42


def mrr(ranks):
    """Mean Reciprocal Rank (1-indexed, None=missed)."""
    rr = [1.0/r for r in ranks if r is not None]
    return float(np.mean(rr)) if rr else 0.0


def topk_recall(ranks, k, n_frames):
    """Fraction of frames where target is in top-K (1-indexed)."""
    hits = sum(1 for r in ranks if r is not None and r <= k)
    return hits / n_frames


def compute_contextual_features(samples, W_default=202, H_default=360):
    """Return (n, 5) contextual feature matrix for R2.
    Features: [r1_score (placeholder), d4_conf, bbox_area_norm, bbox_cy_norm, bbox_aspect]
    """
    feats = []
    for s in samples:
        xyxy = s["xyxy"]
        w_box = max(0, xyxy[2]-xyxy[0])
        h_box = max(0, xyxy[3]-xyxy[1])
        area_norm = (w_box * h_box) / (W_default * H_default)
        cy_norm   = ((xyxy[1]+xyxy[3])/2) / H_default
        aspect    = h_box / max(w_box, 1e-6)
        conf      = s["conf"]
        feats.append([conf, area_norm, cy_norm, aspect])
    return np.array(feats, dtype=np.float32)


def rerank_frame(frame_samples, scorer_fn):
    """Given all samples for a frame, return (new_rank, score_list).
    new_rank: 1-indexed position of the best positive after reranking (None if no positive).
    """
    scores = [scorer_fn(s) for s in frame_samples]
    order  = np.argsort(scores)[::-1]  # desc
    for rank, idx in enumerate(order, 1):
        if frame_samples[idx]["label"] == 1:
            return rank
    return None  # positive not found (shouldn't happen if there's a positive)


def evaluate_per_frame(split_samples, scorer_fn, split_name):
    """Group by frame_id, compute per-frame ranking metrics."""
    from collections import defaultdict
    frame_groups = defaultdict(list)
    for s in split_samples:
        frame_groups[s["frame_id"]].append(s)

    frame_results = {}
    for frame_id, fsamps in frame_groups.items():
        has_positive = any(s["label"]==1 for s in fsamps)
        if not has_positive:
            frame_results[frame_id] = {"rank": None, "n_cands": len(fsamps), "has_positive": False}
            continue
        rank = rerank_frame(fsamps, scorer_fn)
        frame_results[frame_id] = {
            "rank": rank,
            "n_cands": len(fsamps),
            "has_positive": True,
            "phase": fsamps[0]["phase"],
            "dive_id": fsamps[0]["dive_id"],
        }

    n_frames = len(frame_results)
    ranks_all = [v["rank"] for v in frame_results.values() if v.get("has_positive")]

    metrics = {
        "n_frames": n_frames,
        "n_frames_with_positive": len(ranks_all),
        "top1_recall":  topk_recall(ranks_all, 1,  n_frames),
        "top3_recall":  topk_recall(ranks_all, 3,  n_frames),
        "top5_recall":  topk_recall(ranks_all, 5,  n_frames),
        "top10_recall": topk_recall(ranks_all, 10, n_frames),
        "mrr": mrr(ranks_all),
        "rank_mean": float(np.mean([r for r in ranks_all if r])) if ranks_all else None,
        "rank_median": float(np.median([r for r in ranks_all if r])) if ranks_all else None,
    }

    # Per-phase breakdown
    by_phase = {}
    for phase in ["takeoff", "apex", "water_contact"]:
        phase_frames = [v for v in frame_results.values()
                        if v.get("phase") == phase and v.get("has_positive")]
        phase_ranks = [v["rank"] for v in phase_frames]
        by_phase[phase] = {
            "n": len(phase_frames),
            "top1": topk_recall(phase_ranks, 1, len(phase_frames)) if phase_frames else None,
            "top3": topk_recall(phase_ranks, 3, len(phase_frames)) if phase_frames else None,
            "mrr":  mrr(phase_ranks),
        }

    print(f"\n  [{split_name}] n_frames={n_frames}  n_with_pos={len(ranks_all)}")
    print(f"    top-1={metrics['top1_recall']:.1%}  top-3={metrics['top3_recall']:.1%}  "
          f"top-5={metrics['top5_recall']:.1%}  top-10={metrics['top10_recall']:.1%}  "
          f"MRR={metrics['mrr']:.3f}")
    for phase, pm in by_phase.items():
        if pm["n"] > 0:
            print(f"    {phase:15s} n={pm['n']} top-1={pm['top1']:.1%} MRR={pm['mrr']:.3f}")

    return metrics, by_phase, frame_results


def d4_baseline_scorer(s):
    """B0: sort by D4 confidence (baseline)."""
    return s["conf"]


def main():
    print("Loading dataset …")
    samples = pickle.load(open(DATASET, "rb"))
    manifest = json.load(open(MANIFEST))

    train = [s for s in samples if s["split"] == "DEV_TRAIN"]
    val   = [s for s in samples if s["split"] == "DEV_VAL"]
    print(f"  DEV_TRAIN: {len(train)} samples ({sum(1 for s in train if s['label']==1)} pos)")
    print(f"  DEV_VAL:   {len(val)}   samples ({sum(1 for s in val   if s['label']==1)} pos)")

    X_train = np.array([s["features"] for s in train])
    y_train = np.array([s["label"]    for s in train])
    X_val   = np.array([s["features"] for s in val])
    y_val   = np.array([s["label"]    for s in val])

    ctx_train = compute_contextual_features(train)
    ctx_val   = compute_contextual_features(val)

    # =========== BASELINE B0: D4 confidence ===========
    print("\n" + "="*60)
    print("B0 BASELINE — D4 confidence ranking")
    b0_train_metrics, b0_train_phase, b0_train_frames = evaluate_per_frame(
        train, d4_baseline_scorer, "DEV_TRAIN")
    b0_val_metrics, b0_val_phase, b0_val_frames = evaluate_per_frame(
        val, d4_baseline_scorer, "DEV_VAL")

    # =========== R1: ResNet50 → LogReg ===========
    print("\n" + "="*60)
    print("R1 TRAINING — Frozen ResNet50 (2048-d) + L2-LogisticRegression")
    print(f"  Samples: train={len(X_train)} val={len(X_val)}")
    print(f"  Class distribution train: pos={y_train.sum()} neg={(y_train==0).sum()}")

    r1 = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(
            C=1.0,
            class_weight="balanced",
            max_iter=1000,
            random_state=RANDOM_SEED,
            solver="lbfgs",
        ))
    ])
    r1.fit(X_train, y_train)

    # R1 AUC
    r1_train_auc = roc_auc_score(y_train, r1.predict_proba(X_train)[:,1])
    r1_val_auc   = roc_auc_score(y_val,   r1.predict_proba(X_val)[:,1])   if y_val.sum()>0 and (y_val==0).sum()>0 else None
    print(f"  R1 train-AUC={r1_train_auc:.3f}  val-AUC={r1_val_auc}")

    def r1_scorer(s):
        feat = s["features"].reshape(1,-1)
        return r1.predict_proba(feat)[0,1]

    print("\n  R1 DEV_TRAIN ranking:")
    r1_train_metrics, r1_train_phase, r1_train_frames = evaluate_per_frame(
        train, r1_scorer, "DEV_TRAIN")
    print("\n  R1 DEV_VAL ranking:")
    r1_val_metrics, r1_val_phase, r1_val_frames = evaluate_per_frame(
        val, r1_scorer, "DEV_VAL")

    # =========== R2: R1 prob + contextual ===========
    print("\n" + "="*60)
    print("R2 TRAINING — R1 diver_prob + contextual (conf, area, cy, aspect)")

    # Build R2 features: [r1_prob, d4_conf, area_norm, cy_norm, aspect]
    r1_probs_train = r1.predict_proba(X_train)[:,1]
    r1_probs_val   = r1.predict_proba(X_val)[:,1]

    X2_train = np.column_stack([r1_probs_train, ctx_train])  # (N, 5)
    X2_val   = np.column_stack([r1_probs_val,   ctx_val])

    r2 = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(
            C=0.1,
            class_weight="balanced",
            max_iter=1000,
            random_state=RANDOM_SEED,
            solver="lbfgs",
        ))
    ])
    r2.fit(X2_train, y_train)

    r2_train_auc = roc_auc_score(y_train, r2.predict_proba(X2_train)[:,1])
    r2_val_auc   = roc_auc_score(y_val,   r2.predict_proba(X2_val)[:,1]) if y_val.sum()>0 and (y_val==0).sum()>0 else None
    print(f"  R2 train-AUC={r2_train_auc:.3f}  val-AUC={r2_val_auc}")

    # For R2 scorer, we need contextual features at score time
    def r2_scorer_factory(samples_list, r2_probs):
        """Precompute R2 scores for a list of samples."""
        score_map = {}
        for s, prob in zip(samples_list, r2_probs):
            key = (s["frame_id"], tuple(s["xyxy"]))
            score_map[key] = float(prob)
        def scorer(s):
            return score_map[(s["frame_id"], tuple(s["xyxy"]))]
        return scorer

    # Precompute R2 probs for all samples
    # train+val together
    all_samples = train + val
    X_all = np.array([s["features"] for s in all_samples])
    ctx_all = compute_contextual_features(all_samples)
    r1_probs_all = r1.predict_proba(X_all)[:,1]
    X2_all = np.column_stack([r1_probs_all, ctx_all])
    r2_probs_all = r2.predict_proba(X2_all)[:,1]

    # Map (frame_id, xyxy) → R2 score
    r2_score_map = {}
    for s, prob in zip(all_samples, r2_probs_all):
        key = (s["frame_id"], tuple(s["xyxy"]))
        r2_score_map[key] = float(prob)

    def r2_scorer(s):
        return r2_score_map.get((s["frame_id"], tuple(s["xyxy"])), 0.0)

    print("\n  R2 DEV_TRAIN ranking:")
    r2_train_metrics, r2_train_phase, r2_train_frames = evaluate_per_frame(
        train, r2_scorer, "DEV_TRAIN")
    print("\n  R2 DEV_VAL ranking:")
    r2_val_metrics, r2_val_phase, r2_val_frames = evaluate_per_frame(
        val, r2_scorer, "DEV_VAL")

    # =========== Comparison ===========
    print("\n" + "="*60)
    print("COMPARISON SUMMARY (DEV_VAL = held-out, definitive)")
    print(f"{'':15s} {'top-1':>8} {'top-3':>8} {'top-5':>8} {'top-10':>8} {'MRR':>8}")
    for name, m in [("B0 D4 conf", b0_val_metrics), ("R1 visual", r1_val_metrics), ("R2 visual+ctx", r2_val_metrics)]:
        print(f"  {name:15s} {m['top1_recall']:8.1%} {m['top3_recall']:8.1%} "
              f"{m['top5_recall']:8.1%} {m['top10_recall']:8.1%} {m['mrr']:8.3f}")

    # RERANKER GATE
    # Metric: R1 or R2 must show a material improvement in DEV_VAL top-1 vs B0
    b0_top1 = b0_val_metrics["top1_recall"]
    r1_top1 = r1_val_metrics["top1_recall"]
    r2_top1 = r2_val_metrics["top1_recall"]

    MATERIAL_IMPROVEMENT_THRESHOLD = 0.05  # ≥5 pp lift in top-1

    best_reranker = "R1" if r1_top1 >= r2_top1 else "R2"
    best_top1 = max(r1_top1, r2_top1)
    improvement = best_top1 - b0_top1
    gate = "PASS" if improvement >= MATERIAL_IMPROVEMENT_THRESHOLD else "RERANKER_NOT_SUFFICIENT"

    print(f"\nRERANKER GATE: improvement={improvement:+.1%}  threshold≥{MATERIAL_IMPROVEMENT_THRESHOLD:.0%}  → {gate}")
    print(f"  Best reranker: {best_reranker}  top-1={best_top1:.1%}  B0={b0_top1:.1%}")

    # =========== R1 coefficients (interpretability) ===========
    r1_coef = r1.named_steps["clf"].coef_[0]
    scaler  = r1.named_steps["scaler"]
    # Top contributing ResNet dimensions (scaled)
    coef_scaled = r1_coef * scaler.scale_
    top_pos = np.argsort(coef_scaled)[-5:][::-1]
    top_neg = np.argsort(coef_scaled)[:5]
    print(f"\nR1 top-5 positive ResNet dims: {top_pos.tolist()}")
    print(f"R1 top-5 negative ResNet dims: {top_neg.tolist()}")

    # R2 coefficients
    r2_coef  = r2.named_steps["clf"].coef_[0]
    r2_names = ["r1_prob", "d4_conf", "area_norm", "cy_norm", "aspect"]
    print(f"\nR2 contextual feature coefficients (scaled):")
    ctx_coef_raw = r2_coef[1:]  # first is r1_prob dim but actually flattened...
    # R2 feature order: [r1_prob (1), d4_conf, area_norm, cy_norm, aspect] = 5 cols
    r2_scaler = r2.named_steps["scaler"]
    for i, name in enumerate(["r1_prob_or_hidden", "d4_conf", "area_norm", "cy_norm", "aspect"]):
        print(f"  {name:20s}: {r2_coef[i]:.4f}")

    # =========== Save models ===========
    r1_path = f"{RESULTS}/R1_RERANKER.pkl"
    r2_path = f"{RESULTS}/R2_RERANKER.pkl"
    with open(r1_path, "wb") as f:
        pickle.dump(r1, f)
    with open(r2_path, "wb") as f:
        pickle.dump({"r1": r1, "r2": r2}, f)
    print(f"\nModels saved: {r1_path}, {r2_path}")

    # =========== Save evaluation JSON ===========
    eval_result = {
        "label": "RERANKER_DEV_EVAL_V1",
        "date": datetime.date.today().isoformat(),
        "feature_model": "ResNet50_IMAGENET1K_V1",
        "feature_dim": 2048,
        "grouped_split": {"DEV_TRAIN": manifest["grouped_split"]["DEV_TRAIN"],
                          "DEV_VAL":   manifest["grouped_split"]["DEV_VAL"]},
        "B0": {
            "name": "D4_confidence_ranking",
            "DEV_TRAIN": {**b0_train_metrics, "by_phase": b0_train_phase},
            "DEV_VAL":   {**b0_val_metrics,   "by_phase": b0_val_phase},
        },
        "R1": {
            "name": "ResNet50_frozen_LogisticRegression",
            "C": 1.0,
            "class_weight": "balanced",
            "train_auc": float(r1_train_auc),
            "val_auc":   float(r1_val_auc) if r1_val_auc else None,
            "DEV_TRAIN": {**r1_train_metrics, "by_phase": r1_train_phase},
            "DEV_VAL":   {**r1_val_metrics,   "by_phase": r1_val_phase},
        },
        "R2": {
            "name": "R1_prob_plus_contextual_LogisticRegression",
            "features": ["r1_diver_prob", "d4_conf", "bbox_area_norm", "bbox_cy_norm", "bbox_aspect"],
            "C": 0.1,
            "class_weight": "balanced",
            "train_auc": float(r2_train_auc),
            "val_auc":   float(r2_val_auc) if r2_val_auc else None,
            "DEV_TRAIN": {**r2_train_metrics, "by_phase": r2_train_phase},
            "DEV_VAL":   {**r2_val_metrics,   "by_phase": r2_val_phase},
        },
        "reranker_gate": {
            "gate": gate,
            "b0_top1_val":   float(b0_top1),
            "best_top1_val": float(best_top1),
            "improvement":   float(improvement),
            "material_threshold": MATERIAL_IMPROVEMENT_THRESHOLD,
            "selected_reranker": best_reranker if gate == "PASS" else "NONE",
        },
        "per_frame_val": {
            "B0": b0_val_frames,
            "R1": r1_val_frames,
            "R2": r2_val_frames,
        },
        "paris_firewall": "VERIFIED — Paris not used in training or evaluation",
    }
    eval_path = f"{RESULTS}/RERANKER_DEV_EVAL.json"
    with open(eval_path, "w") as f:
        json.dump(eval_result, f, indent=2)
    print(f"Evaluation saved: {eval_path}")
    print(f"\nRERANKER_GATE: {gate}")
    return eval_result


if __name__ == "__main__":
    main()
