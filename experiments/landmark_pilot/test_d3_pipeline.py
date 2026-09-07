#!/usr/bin/env python3
"""Phase U — D3 Training Pipeline Tests

Tests for:
- Dataset coordinate validity
- Multi-diver (synchronized diving) labeling policy
- Negative image handling
- Tiny-overfit training smoke
- Checkpoint identity
- Confidence-distribution sanity
- Grouped split leakage
- Target-diver recall evaluator
- Scene-prior precondition
- Paris firewall (metadata only)
- Trajectory gate
"""
import os
import json
import pytest
import hashlib
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRATCHPAD = Path("/private/tmp/claude-501/-Users-maximecauchy--perso-diveanalyzer/41096d47-755f-4843-9b56-3aecdee13d2e/scratchpad")
D3_WORK = SCRATCHPAD / "d3_work"
D3_YOLO = D3_WORK / "DIVER_LOCALIZATION_DATASET_D3"
SANITY_RESULT = D3_WORK / "DIVER_DETECTOR_SANITY_V1_REPAIRED_RESULT.json"
D3_TRAIN_RESULT = D3_WORK / "DIVER_DETECTOR_D3_V8N_TRAIN.json"
D3_FREEZE = D3_WORK / "DIVER_DETECTOR_D3_FREEZE.json"
PHASE_J = D3_WORK / "PHASE_J_GROUPED_EVAL_D3.json"
PHASE_M = D3_WORK / "PHASE_M_PARIS_CANARY_D3_FREEZE.json"
PHASE_N = D3_WORK / "PHASE_N_COCO_TARGET_DIVER_AUDIT.json"
PHASE_O = D3_WORK / "PHASE_O_SCENE_PRIOR_DECISION.json"
PHASE_P = D3_WORK / "PHASE_P_TRAJECTORY_GATE.json"
PHASE_S = D3_WORK / "PHASE_S_GENERALIZATION_DECISION.json"


# ===========================================================================
# 1. Dataset coordinate validity
# ===========================================================================

def read_all_labels(split):
    """Return list of (stem, class_id, cx, cy, bw, bh) for all labels in split."""
    lbl_dir = D3_YOLO / "labels" / split
    results = []
    for lbl_path in sorted(lbl_dir.glob("*.txt")):
        content = lbl_path.read_text().strip()
        if not content:
            continue  # empty = background, valid
        for line in content.splitlines():
            parts = line.strip().split()
            assert len(parts) == 5, f"{lbl_path}: expected 5 fields, got {len(parts)}"
            cls, cx, cy, bw, bh = int(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
            results.append((lbl_path.stem, cls, cx, cy, bw, bh))
    return results


@pytest.mark.parametrize("split", ["train", "val", "holdout"])
def test_label_class_is_zero(split):
    """All labels must use class 0 (visible_diver)."""
    for stem, cls, cx, cy, bw, bh in read_all_labels(split):
        assert cls == 0, f"{split}/{stem}: class={cls}, expected 0 (visible_diver)"


@pytest.mark.parametrize("split", ["train", "val", "holdout"])
def test_label_coords_in_unit_range(split):
    """All normalized coordinates must be in [0, 1]."""
    for stem, cls, cx, cy, bw, bh in read_all_labels(split):
        for name, val in [("cx", cx), ("cy", cy), ("bw", bw), ("bh", bh)]:
            assert 0.0 <= val <= 1.0, f"{split}/{stem}: {name}={val:.6f} out of [0,1]"


@pytest.mark.parametrize("split", ["train", "val", "holdout"])
def test_label_bbox_positive_area(split):
    """Bounding boxes must have positive area."""
    for stem, cls, cx, cy, bw, bh in read_all_labels(split):
        assert bw > 0 and bh > 0, f"{split}/{stem}: non-positive bbox area bw={bw} bh={bh}"


@pytest.mark.parametrize("split", ["train", "val", "holdout"])
def test_label_bbox_within_image(split):
    """Bounding boxes must be within [0,1] bounds (with tiny tolerance for floating point)."""
    TOL = 1e-4
    for stem, cls, cx, cy, bw, bh in read_all_labels(split):
        x1, y1 = cx - bw / 2, cy - bh / 2
        x2, y2 = cx + bw / 2, cy + bh / 2
        assert x1 >= -TOL, f"{split}/{stem}: x1={x1:.6f} out of frame"
        assert y1 >= -TOL, f"{split}/{stem}: y1={y1:.6f} out of frame"
        assert x2 <= 1 + TOL, f"{split}/{stem}: x2={x2:.6f} out of frame"
        assert y2 <= 1 + TOL, f"{split}/{stem}: y2={y2:.6f} out of frame"


@pytest.mark.parametrize("split", ["train", "val", "holdout"])
def test_image_label_correspondence(split):
    """Every image must have a matching label and vice versa."""
    img_dir = D3_YOLO / "images" / split
    lbl_dir = D3_YOLO / "labels" / split
    img_stems = {p.stem for p in img_dir.glob("*.jpg")}
    lbl_stems = {p.stem for p in lbl_dir.glob("*.txt")}
    missing_labels = img_stems - lbl_stems
    missing_images = lbl_stems - img_stems
    assert not missing_labels, f"{split}: images without labels: {missing_labels}"
    assert not missing_images, f"{split}: labels without images: {missing_images}"


# ===========================================================================
# 2. Hard negative image handling
# ===========================================================================

def test_hard_negatives_exist_in_training():
    """D3 train split must include hard-negative (empty label) images."""
    lbl_dir = D3_YOLO / "labels" / "train"
    empty_labels = [p for p in lbl_dir.glob("*.txt") if not p.read_text().strip()]
    assert len(empty_labels) >= 10, (
        f"Expected at least 10 hard-negative training images, found {len(empty_labels)}. "
        "Hard negatives are required to prevent degenerate training collapse."
    )


def test_hard_negatives_are_neg_prefix():
    """Hard-negative images should be named with 'neg_' prefix for traceability."""
    for split in ["train", "val", "holdout"]:
        lbl_dir = D3_YOLO / "labels" / split
        for lbl in lbl_dir.glob("*.txt"):
            if not lbl.read_text().strip():
                assert lbl.stem.startswith("neg_"), (
                    f"{split}/{lbl.stem}: empty label (background) but missing 'neg_' prefix"
                )


def test_no_synchronized_diving_in_corpus():
    """Dive codes in corpus must not be synchronized (no 6xxx/8xxx codes).
    This test documents that synchronized diving was audited and not found."""
    manifest = json.loads((D3_WORK / "DEVELOPMENT_DESIGN_V2" / "manifest.json").read_text())
    frames = manifest["frames"]
    synchro_codes = [f for f in frames if f["dive_code"].startswith(("6", "8"))]
    assert len(synchro_codes) == 0, (
        f"Found {len(synchro_codes)} synchronized diving frames: "
        f"{[f['frame_id'] for f in synchro_codes[:5]]}"
    )


# ===========================================================================
# 3. Grouped split leakage (no dive-id in multiple splits)
# ===========================================================================

def get_dive_ids_for_split(split):
    """Extract dive IDs from filenames for a split."""
    img_dir = D3_YOLO / "images" / split
    dive_ids = set()
    for p in img_dir.glob("*.jpg"):
        stem = p.stem
        if stem.startswith("neg_"):
            continue
        # v1_1040_apex or v2_d0203_f0
        if stem.startswith("v1_"):
            parts = stem.split("_")
            if len(parts) >= 2:
                dive_ids.add(f"v1_{parts[1]}")
        elif stem.startswith("v2_d"):
            parts = stem.split("_")
            if len(parts) >= 2:
                dive_ids.add(f"v2_{parts[1]}")
    return dive_ids


def test_no_dive_id_leakage_train_holdout():
    """No dive should appear in both train and holdout splits."""
    train_ids = get_dive_ids_for_split("train")
    holdout_ids = get_dive_ids_for_split("holdout")
    overlap = train_ids & holdout_ids
    assert not overlap, f"Dive ID leakage between train and holdout: {overlap}"


def test_no_dive_id_leakage_val_holdout():
    """No dive should appear in both val and holdout splits."""
    val_ids = get_dive_ids_for_split("val")
    holdout_ids = get_dive_ids_for_split("holdout")
    overlap = val_ids & holdout_ids
    assert not overlap, f"Dive ID leakage between val and holdout: {overlap}"


# ===========================================================================
# 4. Tiny-overfit sanity result
# ===========================================================================

def test_sanity_pipeline_can_overfit():
    """Training pipeline must demonstrate overfit capability (PASS from sanity test)."""
    assert SANITY_RESULT.exists(), f"Sanity result not found: {SANITY_RESULT}"
    result = json.loads(SANITY_RESULT.read_text())
    verdict = result.get("verdict")
    assert verdict == "TRAINING_PIPELINE_CAN_OVERFIT", (
        f"Training pipeline failed sanity: {verdict}. "
        f"high_conf_positives={result.get('high_conf_positives')}/{result.get('train_n_positive')}. "
        "Check amp=False is set and model is correctly saved."
    )


def test_sanity_positive_confidence_above_threshold():
    """Mean positive confidence after overfit must be substantially above D2 degenerate level."""
    assert SANITY_RESULT.exists()
    result = json.loads(SANITY_RESULT.read_text())
    mean_pos = result.get("mean_pos_conf", 0.0)
    assert mean_pos > 0.5, (
        f"Mean positive confidence {mean_pos:.4f} is too low. "
        "D2 degenerate was 0.013. Sanity PASS requires >> 0.013."
    )


def test_sanity_negative_confidence_below_positives():
    """Negative images must have lower mean confidence than positive images."""
    assert SANITY_RESULT.exists()
    result = json.loads(SANITY_RESULT.read_text())
    mean_pos = result.get("mean_pos_conf", 0.0)
    mean_neg = result.get("mean_neg_conf", 1.0)
    assert mean_neg < mean_pos, (
        f"Negative conf ({mean_neg:.4f}) >= positive conf ({mean_pos:.4f}). "
        "Detector must discriminate positive from negative images."
    )


# ===========================================================================
# 5. Checkpoint identity
# ===========================================================================

def test_d3_checkpoint_sha256():
    """D3 best checkpoint SHA256 must match frozen identity."""
    assert D3_FREEZE.exists()
    freeze = json.loads(D3_FREEZE.read_text())
    expected_sha = freeze["best_weights_sha256"]
    best_pt = Path(freeze["best_weights_local"])
    assert best_pt.exists(), f"best.pt not found at {best_pt}"
    actual_sha = hashlib.sha256(best_pt.read_bytes()).hexdigest()
    assert actual_sha == expected_sha, (
        f"best.pt SHA256 mismatch: expected {expected_sha[:16]}, got {actual_sha[:16]}. "
        "Stale checkpoint or wrong weights loaded."
    )


# ===========================================================================
# 6. Confidence distribution sanity (D3 evaluation)
# ===========================================================================

def test_d3_val_map50_above_degenerate():
    """D3 val mAP50 must be substantially above D2's degenerate 0.073."""
    assert D3_TRAIN_RESULT.exists()
    result = json.loads(D3_TRAIN_RESULT.read_text())
    map50 = result.get("best_map50", 0.0)
    assert map50 > 0.30, (
        f"D3 val mAP50={map50:.4f} too low. D2 (broken) was 0.073. "
        "Expected > 0.30 with repaired pipeline."
    )


def test_d3_amp_disabled():
    """D3 training must have used amp=False (MPS AMP bug fix)."""
    assert D3_TRAIN_RESULT.exists()
    result = json.loads(D3_TRAIN_RESULT.read_text())
    amp = result.get("amp", True)
    assert amp is False, (
        f"D3 trained with amp={amp}. Must use amp=False for MPS to prevent classification collapse."
    )


def test_d3_holdout_recall_at_conf010():
    """D3 holdout recall at conf=0.10 must exceed D2's effective 0.0% at any useful threshold."""
    if not PHASE_J.exists():
        pytest.skip("Phase J evaluation not found")
    results = json.loads(PHASE_J.read_text())
    holdout_recall_010 = results["splits"]["holdout"]["0.1"]["diver_recall"]
    assert holdout_recall_010 > 0.30, (
        f"D3 holdout recall at conf=0.10: {holdout_recall_010:.3f}. "
        "D2 was 0.000. Expected > 0.30 with repaired pipeline."
    )


# ===========================================================================
# 7. Target-diver recall evaluator (Paris canary)
# ===========================================================================

def test_paris_no_spectator_false_positives():
    """D3 on Paris canary: all detections must be in diver region (cy<=0.7), not spectator region."""
    if not PHASE_M.exists():
        pytest.skip("Phase M Paris result not found")
    result = json.loads(PHASE_M.read_text())
    spectator_dets = result.get("spectator_region_detections", 0)
    assert spectator_dets == 0, (
        f"D3 has {spectator_dets} detections in spectator region (cy>0.7) on Paris canary. "
        "COCO's problem was detecting spectators. D3 must not replicate this."
    )


def test_paris_detection_rate_above_d2():
    """D3 overall Paris detection rate must exceed D2's 0.0%."""
    if not PHASE_M.exists():
        pytest.skip("Phase M Paris result not found")
    result = json.loads(PHASE_M.read_text())
    rate = result.get("detection_rate", 0.0)
    assert rate > 0.10, (
        f"D3 Paris detection rate = {rate:.3f}. D2 was 0.000. "
        "Expected substantial improvement with repaired pipeline."
    )


# ===========================================================================
# 8. Scene-prior precondition
# ===========================================================================

def test_scene_prior_decision_recorded():
    """Scene-prior decision must be documented."""
    assert PHASE_O.exists(), f"Phase O decision not found: {PHASE_O}"
    result = json.loads(PHASE_O.read_text())
    assert "decision" in result
    valid_decisions = {
        "SCENE_PRIOR_PLAUSIBLE",
        "SCENE_PRIOR_CANNOT_RECOVER_MISSING_DETECTION"
    }
    assert result["decision"] in valid_decisions, f"Unknown decision: {result['decision']}"


def test_coco_person_in_gt_frames():
    """Phase N must report whether COCO detects person in GT frames (correct outcome recorded)."""
    assert PHASE_N.exists()
    result = json.loads(PHASE_N.read_text())
    # Just check the result is recorded (value is scientific finding)
    assert "gt_diver_region_hits" in result
    assert "conclusion" in result


# ===========================================================================
# 9. Paris firewall (no tuning)
# ===========================================================================

def test_paris_firewall_not_violated():
    """Paris canary evaluation must be marked as read-only / no-tuning."""
    if not PHASE_M.exists():
        pytest.skip("Phase M Paris result not found")
    result = json.loads(PHASE_M.read_text())
    firewall = result.get("firewall", "")
    assert "NO_TUNING" in firewall or "no_tuning" in firewall.lower(), (
        f"Paris firewall metadata missing or incorrect: '{firewall}'"
    )


def test_d3_freeze_not_calibrated_on_paris():
    """D3 freeze record must be based on DEVELOPMENT evidence, not Paris results."""
    if not D3_FREEZE.exists():
        pytest.skip("D3 freeze not found")
    freeze = json.loads(D3_FREEZE.read_text())
    # The val_map50 should be from the D3 val set (not Paris)
    assert "val_map50" in freeze
    # Paris result is recorded separately — the freeze itself is based on val
    assert freeze.get("firewall") == "PARIS_CANARY_READ_ONLY_NO_TUNING"


# ===========================================================================
# 10. Trajectory gate
# ===========================================================================

def test_trajectory_gate_recorded():
    """Trajectory gate result must be documented."""
    assert PHASE_P.exists(), f"Phase P trajectory gate not found: {PHASE_P}"
    result = json.loads(PHASE_P.read_text())
    assert result.get("verdict") in {"TRAJECTORY_INPUT_PASS", "TRAJECTORY_INPUT_FAIL"}, (
        f"Trajectory gate verdict missing or invalid: {result.get('verdict')}"
    )


def test_trajectory_gate_requirements_documented():
    """Trajectory gate must document all 6 criteria."""
    assert PHASE_P.exists()
    result = json.loads(PHASE_P.read_text())
    criteria = result.get("criteria", {})
    assert len(criteria) >= 6, f"Expected 6 trajectory criteria, found {len(criteria)}"


# ===========================================================================
# 11. Generalization decision
# ===========================================================================

def test_generalization_decision_recorded():
    """Phase S generalization decision must be recorded."""
    assert PHASE_S.exists(), f"Phase S decision not found: {PHASE_S}"
    result = json.loads(PHASE_S.read_text())
    valid = {
        "TRAINING_PIPELINE_REPAIRED_AND_IN_DOMAIN_WORKS",
        "D3_GENERALIZES_TO_PARIS",
        "D3_IN_DOMAIN_ONLY",
        "MORE_DOMAIN_DIVERSITY_REQUIRED",
        "CUSTOM_DETECTOR_APPROACH_INSUFFICIENT",
    }
    assert result.get("verdict") in valid, f"Invalid verdict: {result.get('verdict')}"


if __name__ == "__main__":
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v"],
        cwd=str(Path(__file__).parent)
    )
    sys.exit(result.returncode)
