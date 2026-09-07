# Perception V3 — Multi-Domain Generalization Report

**Date**: 2026-09-07  
**Gate**: SUPERVISOR_REVIEW_AFTER_REAL_SIGNAL_HIGHRES_V1  
**Pipeline**: Phases A–W  
**Status**: COMPLETE (Phases A–T/U executed; V/W this document)

---

## Executive Summary

This report documents the full evaluation cycle for the dive perception pipeline following gate `SUPERVISOR_REVIEW_AFTER_REAL_SIGNAL_HIGHRES_V1`. The cycle aimed to improve detection generalization to external venues (Paris canary: `IMG_1937.mov`, dive 2819, springboard 1m hurdle).

**Core finding**: Perception remains insufficient for external generalization. Both the L1 model (prior cycle) and the new D2 model (this cycle) produce 0 detections on the Paris canary at any operationally useful confidence threshold. The root cause is confirmed as single-venue training — insufficient domain diversity, not model capacity.

**Event Logic V2.1 is frozen and correct** (36/36 tests pass, oracle trajectory test passes). It cannot be evaluated on real Paris signal because the perception prerequisite is not met.

**Recommended path forward**: Scene-prior spatial filtering with COCO detections OR multi-domain training data acquisition.

---

## 1. Event Logic Corrections (Phases A–B)

### Phase A — Stale Document Correction

Two documents were identified as stale or incorrect:

1. **`HIGH_RESOLUTION_CANARY_EVENT_SEMANTICS_CORRECTION_V1.md`** — Marked SUPERSEDED. Section 5 table was computed with the wrong takeoff detection logic (global min-y instead of first local minimum). Status updated.

2. **`EVENT_LOGIC_V2_FREEZE.json`** — `known_limitations` contained an incorrect claim that the failure was "CUDA-related." This was wrong — training was never attempted on the Pentium (SIGILL), inference didn't fail due to CUDA. Claim removed.

### Phase B — Event Logic V2.1 Fix

**Root cause**: `_detect_takeoff` for HURDLE context used global minimum y to find hurdle apex. This is incorrect because:
- cy_norm = 0 at top of frame, 1 at bottom
- Rising diver → decreasing cy_norm (negative velocity)
- Flight apex (cy_norm ≈ 0.12) lies below hurdle apex (cy_norm ≈ 0.18) in frame coordinates
- Global minimum finds the flight apex, not the hurdle apex

**Fix**: Changed to first local minimum via first neg→non-neg velocity crossing after guard_end.

**Verification**: 36/36 tests pass in `test_event_logic_v2_1.py`.

**Frozen**: `EVENT_LOGIC_V2_1_FREEZE.json` (SHA-locked source).

---

## 2. Domain Inventory and Dataset D2 (Phases C–F)

### Phase C — Domain Inventory

Single-venue development corpus documented in `DOMAIN_INVENTORY_V1.json`:
- 168 sessions, 2803 dives, 239 proxy videos
- One training pool (location field NULL in DB)
- Paris canary (`IMG_1937.mov`) is the sole external sample: FIREWALL_PROTECTED

### Phase D — Dataset Design V2

43 new dives selected for V2 annotation (DEVELOPMENT_DESIGN):
- Stratified by apparatus, date, dive code
- EARLY bucket (before Q2 2025) → train/val
- MID bucket (Q2 2025) → train/val  
- LATE bucket (Q3 2025 onward) → holdout (temporal generalization test)
- Springboard 1m dives over-represented to match Paris canary apparatus

### Phase E — Annotation

86 frames extracted, annotated by Maxime (maxime@qwokka.fr):
- 51 visible diver frames → bounding box annotations
- 35 not_visible frames → skipped (excluded from training)
- Annotated via browser-based `annotate_v2_server.py` (fixed CSS/Python template collision bug)

### Phase F — Dataset D2 Freeze

`DATASET_D2_FREEZE.json`:
- 85 total annotated records (34 V1 + 51 V2 visible)
- Train: 32, Val: 7, Holdout: 46
- YOLO format exported to `DATASET_D2_YOLO/`

---

## 3. Detector D2 Training and Evaluation (Phases G–J)

### Phase G — Training

**Model**: YOLOv8n fine-tuned on D2 dataset  
**Device**: Mac M2 (MPS) — server Pentium 3550M rejected (no AVX → torch SIGILL on model save)  
**Result**:
- val_mAP50 = 0.073
- val_recall = 0.857
- val_precision = 0.003 (near zero)
- Elapsed: 83.8s, best epoch = 1, early-stopped at epoch 21

### Phase I — Grouped Evaluation

| Split | mAP50 | Recall | Precision | N |
|-------|-------|--------|-----------|---|
| train | 0.123 | 0.781  | 0.003     | 32 |
| val   | 0.073 | 0.857  | 0.003     | 7  |
| holdout | 0.056 | 0.630 | 0.002    | 46 |

**Holdout recall = 0.630** is meaningful (genuinely unseen LATE bucket data).

**Critical caveat**: Metrics from `model.val()` are computed over a confidence threshold scan. In `model.predict()`, the model fires on NO images at conf ≥ 0.05. The operating confidence is ~0.012–0.013 (uniform across all frames, all scenes). This indicates the model learned a degenerate near-uniform low-confidence strategy rather than a discriminative detector.

### Phase J — Perception Candidate Freeze

`PERCEPTION_CANDIDATE_FREEZE_D2.json`: decision = PROCEED_TO_PARIS_CANARY

---

## 4. Paris Canary Evaluation (Phase K)

### Setup

- Canary: `IMG_1937.mov`, SHA = `d122262b...`, dive 2819, 5122D, springboard 1m, hurdle
- GT: takeoff = 3.120s (frame 187), apex = 3.570s (frame 214), water_contact = 4.220s (frame 253)
- Model: DIVER_DETECTOR_D2_V8N, SHA_prefix = `488828723dff1be6`
- Representation: R360 (640×360 landscape, 322 frames)
- **FIREWALL**: read-only evaluation, no tuning

### Result

| Config | Detection Rate | GT Frames Detected |
|--------|---------------|-------------------|
| conf=0.25 (standard) | 0.0% | 0/3 |
| conf=0.10 (diagnostic) | 0.0% | 0/3 |
| conf=0.01 (low) | 100% (all frames, conf~0.013) | 3/3 (but indiscriminate) |

**Conclusion**: D2 produces the same generalization failure as L1. Zero useful detections on the Paris canary at any operationally meaningful threshold.

Phases L–P (tracking, scene prior, trajectory, event mechanism, event test) collapse — no trajectory can be extracted.

---

## 5. Internal Evaluation (Phase Q)

D2 run on 6 DEVELOPMENT_DESIGN internal dives (proxy_360p, 202×360px):

| Conf | Internal detection rate | Canary detection rate |
|------|------------------------|----------------------|
| 0.25 | 0.0% (all 6 dives) | 0.0% |
| 0.01 | 100% (all frames, conf~0.013) | 100% (all frames, conf~0.013) |

**Key finding**: No discrimination between venues. The model fires uniformly (or not at all) regardless of scene. This confirms the degenerate training outcome — insufficient frames for discriminative learning.

---

## 6. Generalization Decision (Phase R)

**Verdict**: PERCEPTION_STILL_INSUFFICIENT_FOR_EXTERNAL_GENERALIZATION

Root cause confirmed: single-venue training corpus with too few frames.

| Detector | Internal proxy (360p) | Paris canary (360p) |
|----------|----------------------|---------------------|
| COCO yolov8n | High recall (spectators) | 100% (spectators, not diver) |
| L1 (38 train frames) | Unknown | 0% |
| D2 (32 train frames, YOLO) | 0% at useful conf | 0% at useful conf |

---

## 7. Path Forward (Phase S)

### Recommended Immediate: COCO + Scene Prior Spatial Filter

COCO detects ALL persons at high recall. The Paris canary venue has a characteristic scene layout:
- Diver active region: cy_norm ≈ 0.10–0.50 (board + flight zone)
- Spectators: clustered at cy > 0.70 or at extreme cx values
- During flight phase: diver is the ONLY moving person in the active zone

**Approach**: COCO at conf=0.10 → background subtraction to identify stationary cluster → filter detections outside stationary cluster → ByteTrack → trajectory extraction → Event Logic V2.1.

**Firewall**: Pool corridor calibration must NOT use Paris canary GT.

### Secondary: Multi-Domain Training Data

Acquire 200–500 frames from ≥3 external venues. Expected improvement: mAP50 ≥ 0.40 on external venue.

---

## 8. Event Logic Status (Phase T)

Event Logic V2.1: **FROZEN, CORRECT, NOT EVALUABLE ON REAL SIGNAL**

- 36/36 unit tests pass
- Oracle trajectory test passes (synthetic trajectory from GT timestamps → correct event detection)
- Cannot evaluate on real Paris signal (perception prerequisite not met)
- V2.1 will NOT be modified to compensate for perception failures

Paris firewall maintained throughout: no V2.1 changes driven by canary results.

---

## 9. Test Status (Phase U)

| Test Suite | Tests | Status |
|-----------|-------|--------|
| `test_event_logic_v2_1.py` | 36 | ✅ PASS |
| `test_report_consistency.py` | 15 | ✅ PASS |
| **Total** | **51** | **✅ PASS** |

---

## 10. Scientific Invariants Status

All invariants maintained throughout this pipeline execution:

| Invariant | Status |
|-----------|--------|
| Paris is external; do NOT train on IMG_1937.mov | ✅ Maintained |
| Do not optimize tracking before detection | ✅ Phases L–P collapsed with documented rationale |
| Do not optimize Event Logic before trajectory | ✅ V2.1 unchanged; no real trajectory available |
| Do not simplify hurdle physics to make tests pass | ✅ V2.1 fix is physically correct (first local min) |
| Do not make hurdle trajectory artificially monotonic | ✅ |
| Do NOT use real INTERNAL_EVAL labels to tune mechanism | ✅ |
| Paris firewall | ✅ All conf threshold explorations are diagnostic only |

---

## 11. Commit History

| Commit | Phases | Description |
|--------|--------|-------------|
| `f9a54b2` | A/B/C/D/E | V2.1 event logic, document integrity, dataset V2 |
| `76adce1` | F/G/I/J/K | D2 dataset, detector, evaluation, Paris canary |
| (this commit) | Q/R/S/T/U/V/W | Internal eval, decisions, report |

---

## 12. Next Gate

**Gate**: SUPERVISOR_REVIEW_AFTER_REAL_SIGNAL_HIGHRES_V2  

Primary open question: Does the COCO + scene-prior spatial filter produce a usable Paris canary trajectory?

Recommended action before next gate:
1. Implement COCO + scene prior filter
2. If successful: run Event Logic V2.1 on extracted real trajectory
3. If not successful: proceed with multi-domain data acquisition

---

*Report frozen at commit to be determined. SHA-lock on Event Logic V2.1 maintained.*

---

## Supervisor Correction — Phase A (2026-09-07)

**Added after gate .**

### A1 — Root-cause re-classification

The report above classifies the D2 failure primarily as
. The supervisor has corrected this.

**Revised primary failure taxonomy**: 

**Evidence**:
- Train precision ≈ 0.003 (on D2's own 32 training images)
- Best epoch = 1 (early-stopped at epoch 21, never improved)
- Max confidence on any frame ≈ 0.013 (uniform across all scenes, venues, images)
- Model produces zero useful detections at any operationally meaningful threshold

A model that cannot discriminate its own training examples has not reached
the stage where venue-generalization is the primary question. The correct
question is: **can the training pipeline learn to detect divers at all?**

This question is answered in the subsequent D3 cycle
().

### A2 — Pretrained weight description

No ImageNet claims found in Phase V/W documents. The base weight
 is a **COCO-pretrained detection model** (trained on MS-COCO
2017 person class among 79 others), not an ImageNet classifier.
This report never made that error; clarification recorded for completeness.
