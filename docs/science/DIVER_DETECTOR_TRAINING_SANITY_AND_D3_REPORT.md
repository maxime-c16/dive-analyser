# Diver Detector Training Sanity & D3 Report

**Date**: 2026-09-07  
**Gate**: SUPERVISOR_REVIEW_AFTER_REAL_SIGNAL_HIGHRES_V2  
**Pipeline**: Phases A–W  
**Status**: COMPLETE

---

## Executive Summary

This report answers the critical scientific question raised by the supervisor after gate
`SUPERVISOR_REVIEW_AFTER_REAL_SIGNAL_HIGHRES_V2`:

> Is the current custom-detector training pipeline scientifically capable of learning the `diver` class at all?

**Answer**: YES, with one bug fix. The D2 training collapsed due to MPS AMP
(`amp=True` default in Ultralytics on Apple MPS). With `amp=False`, the pipeline
memorizes clean data at mean_conf=0.91 and achieves 97% in-domain video detection.

**D3 generalizes to Paris only partially** (44.7% overall, 7.5% action window).
The primary remaining limitation is single-venue training — now a real generalization
question, not a pipeline defect.

---

## 1. D2 Diagnosis

### Supervisor Classification Correction (Phase A)
The prior cycle classified D2 failure primarily as `EXTERNAL_GENERALIZATION_FAILURE`.
This is **premature**.

**Revised primary classification**: `D2_TRAINING_COLLAPSE_OR_SEVERE_UNDERFIT`

Evidence:
- train precision ≈ 0.003
- train mAP50 ≈ 0.123
- best epoch = 1 (out of 21 total)
- max confidence on training images ≈ 0.013 (uniform across ALL scenes)
- zero useful detections at conf ≥ 0.05 even on training images

A model that cannot discriminate its own training examples has not reached
the stage where venue-generalization is the primary question.

**Phase A2**: No "ImageNet" claims found in any document. Base weight `yolov8n.pt`
is a COCO-pretrained detection model (MS-COCO 2017, 80 classes). Clarification recorded.

---

## 2. Label Semantic Audit (Phase C)

### Class Definition (Phase C — frozen)
```
class 0 = visible_diver
```
Every clearly visible diver that could legitimately be detected as a diver in the frame.
Target-athlete identity is NOT part of object detection.

### Synchronized Diving Audit (Phase C1)
Zero synchronized diving frames in corpus. All dive codes are individual-dive
codes (202C, 101C, 401C, etc.). No multi-diver annotation correction required.

---

## 3. Hard-Negative Correction (Phase C2 / B)

**Critical finding**: D2 excluded all 35 `not_visible` frames from YOLO export.
This left the model with 0 hard-negative examples — a contributing factor to training
collapse (the model never learned to suppress false positives).

**Correction**: All 35 `not_visible` frames included in D3 as empty-label
(background) images:
- EARLY+MID bucket: 17 → 14 train + 3 val
- LATE bucket: 18 → holdout

---

## 4. Dataset Integrity Audit (Phase B)

Programmatic audit of all 85 D2 positive images and labels:
- **1 error** found: `val/v2_d0287_f0.txt` — y1 = −0.001388 (bbox barely outside top edge). **Fixed** (clamped cy).
- **84 labels**: all valid coordinates, class=0, positive area, within frame.
- Image/label basename correspondence: 100% match.
- No synchronized diving frames.

---

## 5. Augmentation Visual Audit (Phase B1)

Verified during overfit sanity:
- Minimal augmentation (mosaic=0, mixup=0) used for sanity test.
- Standard augmentation (mosaic=0.5, fliplr=0.5) used for D3 training.
- Portrait geometry (202×360) preserved under 640-pixel resizing with letterboxing.
- No incorrect rotation or transposition observed in training batch inspection.

---

## 6. Training Pipeline Repairs

### Root Cause: MPS AMP Bug

**Diagnosis**: Ultralytics 8.x enables `amp=True` by default on MPS (Apple Silicon).
On MPS, AMP (float16 mixed-precision) **suppresses classification gradient flow** in the
YOLOv8 detection head. Box regression loss decreases normally; cls_loss stays high (≈4.0);
all prediction confidences remain at ≈0.013 (uniform).

**Evidence from controlled experiment**:

| Setting | Best mAP50 | Train max_conf | Classification |
|---------|-----------|----------------|----------------|
| `amp=True` (D2 default) | 0.142 (threshold scan artifact) | 0.013–0.018 | NOT LEARNED |
| `amp=False` (fix) | 0.595 | up to 0.99 | LEARNED |

**Fix**: All training must use `amp=False` on MPS.

### Additional Repair
- Hard negatives added to training (see §3).
- One bbox coordinate clamped (see §4).

---

## 7. Overfit Sanity Result (Phase E/F)

**Dataset**: DIVER_DETECTOR_SANITY_V1 — 10 positive + 3 hard-negative train, 2 val.  
**Recipe**: amp=False, epochs=100, batch=4, mosaic=0.

| Metric | Value |
|--------|-------|
| Best mAP50 | 0.4475 |
| Mean positive conf (training images) | 0.912 |
| Min positive conf | 0.709 |
| Max positive conf | 0.999 |
| Mean negative conf | 0.116 |
| Positives with conf > 0.25 | 10/10 |

**Verdict**: `TRAINING_PIPELINE_CAN_OVERFIT` ✅

---

## 8. Dataset D3 (Phase H)

**Label**: `DIVER_LOCALIZATION_DATASET_D3`

### Split Design

| Split | Positive | Negative | Total | Temporal bucket |
|-------|----------|----------|-------|-----------------|
| Train | 32 | 14 | 46 | EARLY + MID |
| Val | 7 | 3 | 10 | EARLY + MID |
| Holdout | 46 | 18 | 64 | LATE (≥Q3 2025) |

Temporal separation maintained. Grouped by dive_id (no adjacent-frame leakage).
Hard negatives distributed proportionally.

---

## 9. D3 Training (Phase I)

**Model**: `DIVER_DETECTOR_D3_V8N`  
**Base**: `yolov8n.pt` (COCO-pretrained detection model)  
**Device**: Apple M2 MPS (`amp=False`)

| Parameter | Value |
|-----------|-------|
| epochs | 150 (early-stopped at 118) |
| best_epoch | 68 |
| batch | 8 |
| imgsz | 640 |
| optimizer | SGD |
| lr0 | 0.01 |
| mosaic | 0.5 |
| amp | **False** |

| Metric | Value |
|--------|-------|
| Best val mAP50 | **0.627** |
| Best val precision | 1.000 |
| Best val recall | 0.523 |
| SHA256 (best.pt) | `bf6415fb63aa311f...` |

---

## 10. D3 Grouped Results (Phase J)

| Split | conf | Recall | Precision | F1 | FP-rate | mAP50 |
|-------|------|--------|-----------|-----|---------|-------|
| train | 0.10 | 0.938 | 0.882 | 0.909 | 0.286 | 0.926 |
| train | 0.25 | 0.844 | 0.964 | 0.900 | 0.071 | — |
| val | 0.10 | 0.714 | 0.833 | 0.769 | 0.333 | 0.637 |
| val | 0.25 | 0.429 | 0.750 | 0.545 | 0.333 | — |
| holdout | 0.10 | **0.761** | 0.778 | 0.769 | 0.556 | 0.101 |
| holdout | 0.25 | 0.522 | 0.774 | 0.623 | 0.389 | — |

Key insight: holdout mAP50=0.101 is low but holdout recall=0.761 at conf=0.10 is
meaningful. The model is genuinely discriminative (not degenerate).

---

## 11. In-Domain Video Canary (Phase K)

| Metric | Value |
|--------|-------|
| Video | dive 192 (203C, proxy_360p) |
| Frames evaluated | 100 (action window 800–1300, step 5) |
| Detection rate at conf=0.10 | **97.0%** |
| Takeoff frame detected | Yes (conf=0.373) |
| Mean action-window conf | 0.379 |

**D3 is a functioning, discriminative in-domain detector.**

---

## 12. Paris External Result (Phase M)

**Frozen D3 evaluated on `IMG_1937.mov` (Paris, R360, 322 frames).**
**Firewall: read-only, no tuning from Paris results.**

| Metric | Value |
|--------|-------|
| Overall detection rate (conf=0.10) | 44.7% (144/322) |
| GT takeoff detected | ✅ conf=0.274 |
| GT apex detected | ❌ |
| GT water_contact detected | ✅ conf=0.104 |
| Action window coverage (frames 187–253) | **7.5%** (5/67 frames) |
| Longest gap in action window | 62 frames = **1.034s** |
| Spectator-region false positives | **0** (all in cy ≤ 0.70) |

---

## 13. COCO Target-Diver Audit (Phase N)

COCO-pretrained `yolov8n.pt` on Paris canary R360 (640×360):

| Conf threshold | Persons detected (action window) |
|----------------|----------------------------------|
| 0.10 | **0/67 frames** |
| 0.001 | ~10 persons/frame at max_conf=0.022 |

**Prior cycle correction**: Phase S reported "COCO achieves 100% recall at conf=0.10
(spectators)". This was from the 1080p representation. At R360 (360p), spectators
are too few pixels for COCO to detect at any useful confidence. **Superseded**.

---

## 14. Scene-Prior Decision (Phase O)

**Decision**: `SCENE_PRIOR_CANNOT_RECOVER_MISSING_DETECTION`

Rationale: COCO has 0 person detections at conf ≥ 0.10 in the Paris R360 video.
A spatial filter requires a high-recall input detector. With no detections, no filter
can recover missing targets.

Note: At 1080p processing, COCO may detect spectators. A future investigation
could test scene-prior at 1080p, but requires framework changes for 1080p training.

---

## 15. Trajectory Usability Gate (Phase P)

**Verdict**: `TRAJECTORY_INPUT_FAIL`

| Criterion | Required | Actual |
|-----------|----------|--------|
| Target present at takeoff | ✓ | ✅ |
| Target present at apex | ✓ | ❌ |
| Target present at water_contact | ✓ | ✅ |
| Action window coverage | ≥ 80% | **7.5%** |
| Max missing gap | ≤ 0.25s | **1.034s** |
| No persistent wrong-person | ✓ | ✅ |

Event Logic V2.1 cannot yet be evaluated on real Paris signal.

---

## 16. Real Event Logic V2.1 Test

Not executed (trajectory gate failed). Event Logic V2.1 remains `FROZEN, CORRECT,
NOT_REAL_SIGNAL_VALIDATED`.

---

## 17. Data Recommendation (Phase T)

**Preconditions met for multi-domain training**:
1. ✅ Tiny overfit sanity passes
2. ✅ D3 works in-domain (97% video coverage)
3. ✅ D3 still fails Paris action window (7.5%)

**Recommended first multi-domain batch** (bounded, not jumping to 500 images):
- Target: 50–100 frames from 2–3 venues with outdoor pools (Paris-style)
- Sources: FINA/World Aquatics public competition footage, YouTube CC diving pools
- Expected outcome: improved holdout mAP50 and Paris action window coverage
- Annotation effort: ~2–3 hours
- Decision point: if Paris action window ≥ 50% → proceed to Event Logic evaluation

---

## 18. Generalization Decision (Phase S)

**Verdict**: `TRAINING_PIPELINE_REPAIRED_AND_IN_DOMAIN_WORKS`

Secondary finding: `MORE_DOMAIN_DIVERSITY_REQUIRED` (for Paris generalization).

The pipeline is scientifically sound. The remaining gap is domain coverage.

---

## Test Results (Phase U)

```
test_d3_pipeline.py — 36 tests: 36 PASS, 0 FAIL
```

All tests pass. Covers: coordinate validity, hard-negative handling, synchronized-
diver policy, grouped-split leakage, overfit sanity, checkpoint identity, confidence
distribution, target-diver recall, scene-prior precondition, Paris firewall,
trajectory gate.

---

*Report frozen at final commit. SHA-lock on D3 weights maintained.*
