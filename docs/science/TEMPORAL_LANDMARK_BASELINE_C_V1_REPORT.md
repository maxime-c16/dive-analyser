# Temporal Landmark Detection — Baseline C V1 Report

> **Report label**: `TEMPORAL_LANDMARK_BASELINE_C_V1_REPORT`
> **Date**: 2026-09-06
> **Author**: autonomous science agent
> **Gate before this report**: `SUPERVISOR_REVIEW_AFTER_TEMPORAL_LANDMARK_PILOT_V1_COMPLETE`
> **Supersedes**: adds Baseline C to `TEMPORAL_LANDMARK_PILOT_V1_REPORT.md`

---

## 1. Executive Summary

Baseline C implements COCO-pretrained YOLOv8n person detection + ByteTrack single-diver
tracking for temporal landmark detection (takeoff / apex / water_contact).

**Result: R4 — HUMAN_DETECTION_ITSELF_INSUFFICIENT.**

On the 14-dive DEVELOPMENT_DESIGN set, Baseline C achieves **0% within-tolerance** on all
three landmarks (tolerances: takeoff ≤5f, apex ≤8f, water_contact ≤5f). Median frame errors
are 224f / 150f / 277f for takeoff / apex / water_contact — substantially worse than
Baselines A (94f / 89f / 85f) and B (157f / 63f / 70f). Five of 14 dives are UNCERTAIN
due to insufficient trajectory coverage or temporal prior violations.

On the 6-dive INTERNAL_EVAL set, results are even worse: 4/6 UNCERTAIN, 0/6 within-tolerance,
median errors 569f / 338.5f / 372f.

The single highest-confidence prediction (dive 2555 DESIGN, conf=0.53) is equally
catastrophically wrong as the lowest-confidence ones. Confidence does not separate reliable
from catastrophic predictions.

**Primary failure mode**: EARLY_TRIGGER — the diver is reliably detected on the board
(standing/walking = COCO-canonical person), but the gap+re-acquisition heuristic fails to
locate the diver when airborne (~30–50 px at 360p, athletic poses outside COCO distribution).

**Scientific outcome**: Generic pre-trained COCO person detection is insufficient for this
footage type and resolution. Immediate next direction is domain-specific detection or pose
estimation.

---

## 2. Scientific Integrity Controls

| Control | Status |
|---|---|
| Scientific split frozen before Baseline C code | ✅ fingerprint `96f14ffcd11fb19fa91f8dbd09206c73757ddb628b43f4dbbbe1ac9a0633d582` |
| INTERNAL_EVAL human labels NOT accessed until after freeze | ✅ firewall enforced in `run_baseline_c.py`, EVAL_DIVE_IDS={160,169,191,192,848,2281} |
| Baseline C frozen before INTERNAL_EVAL | ✅ `docs/science/BASELINE_C_FREEZE_V1.json` written first |
| Ground truth fingerprint | `2832b31104e969cc0fcabc9b50b2a05e95d3f9883c822077c105b832029e364f` |
| Proposer fingerprint | `b4afd8ae85878308ad0abb445f4da7fe708cd4a9b5987a57b120419176f2bd41` |
| INTERNAL_EVAL run exactly once | ✅ 2026-09-06T05:52:14Z |
| No iCloud originals downloaded | ✅ PROXY_VS_ORIGINAL_CANARY=DEFERRED_UNTIL_NEAR_NOISE_FLOOR |
| No production corpus analysis | ✅ |
| No user-facing autonomous result enabled | ✅ experimental only |

---

## 3. Algorithm

### 3.1 Pipeline

```
360p proxy video
  → YOLOv8n person detection (every frame, CPU, conf≥0.10, class 0)
  → ByteTrack multi-object tracking (bytetrack.yaml)
  → select primary track: argmax(frame_count × avg_conf)
  → extract y_norm trajectory: 1 − cy_px/frame_height
  → interpolate gaps ≤15 frames (linear)
  → Savitzky-Golay smooth (window=11, poly=3)
  → C-TAKEOFF-V2: gap+re-acquisition heuristic + velocity fallback
  → apex: max y_norm in [takeoff+10 : 0.92×total_frames]
  → water_contact: first y_norm < 0.15 after apex, or last confident detection
  → C2: temporal priors check (t2a: 8–300f@30fps, a2w: 4–400f@30fps) → UNCERTAIN if violated
```

### 3.2 Frozen Parameters (C2 variant)

| Parameter | Value | Rationale |
|---|---|---|
| detector | yolov8n (COCO class 0) | smallest COCO model, person class |
| detector_imgsz | 640 | standard inference resolution |
| detector_conf | 0.10 | low threshold to maximise recall |
| detector_iou | 0.45 | ByteTrack default |
| track_min_conf | 0.10 | matches detector_conf |
| vid_stride | 1 | every frame (gap heuristic requires it) |
| track_select_strategy | longest_x_conf | score = count × avg_conf |
| traj_interp_max_gap | 15 frames | max linear interpolation gap |
| traj_smooth_window | 11 frames | Savitzky-Golay window |
| traj_smooth_poly | 3 | polynomial degree |
| takeoff_y_threshold | 0.30 | y_norm above which diver is airborne |
| takeoff_min_sustained | 6 frames | min frames above threshold for re-acquisition |
| takeoff_gap_min | 8 frames | min gap frames between board and flight |
| takeoff_board_delta | 0.08 | board_y + delta = dynamic_threshold |
| water_contact_y_threshold | 0.15 | y_norm below which water is reached |
| prior_t2a_min_frames | 8 | min takeoff→apex at 30fps reference |
| prior_t2a_max_frames | 300 | max takeoff→apex at 30fps reference |
| prior_a2w_min_frames | 4 | min apex→water at 30fps reference |
| prior_a2w_max_frames | 400 | max apex→water at 30fps reference |

### 3.3 C1 vs C2

- **C1**: trajectory-only (no temporal priors)
- **C2**: C1 + temporal priors (UNCERTAIN if ordering violated or t2a/a2w out of range)
- **DESIGN result**: C1 ≡ C2. All 9 APPLICABLE predictions satisfy T<A<W and valid intervals.
- **C2 selected** as frozen variant for its ordering-violation safety property.

### 3.4 Hardware / Runtime

| Item | Value |
|---|---|
| Server | deb-serv, Pentium 3550M @ 2.30GHz, 8 GB RAM |
| GPU | GTX 850M (sm_50) — incompatible with PyTorch 2.10 (requires sm_70+) |
| Inference device | CPU only |
| Ultralytics | 8.3.253, PyTorch 2.10.0+cu128 |
| Per-dive runtime | ~6–10 min at vid_stride=1 on 360p proxy |
| Total 14 DESIGN dives | ~90–130 min |
| Total 6 INTERNAL_EVAL dives | ~47 min (ended 2026-09-06T05:52Z) |

---

## 4. DEVELOPMENT_DESIGN Results

### 4.1 Per-Dive Predictions vs Human Labels

| Dive | T pred | T human | T err | A pred | A human | A err | W pred | W human | W err | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| 133 | 0 | 108 | 108 | 48 | 125 | 77 | 112 | 177 | 65 | serious×3 |
| 311 | 0 | 825 | 825 | 162 | N/A | — | 484 | 889 | 405 | serious×2 |
| 524 | 125 | 349 | 224 | 230 | 380 | 150 | 246 | 426 | 180 | serious×3 |
| 676 | 0 | 213 | 213 | 185 | 233 | 48 | 221 | 291 | 70 | serious×3 |
| 1040 | — | 268 | — | — | 288 | — | — | 325 | — | UNCERTAIN (cov 9%) |
| 2169 | — | 388 | — | — | 406 | — | — | 462 | — | UNCERTAIN (cov 14%) |
| 2341 | 7 | 214 | 207 | 74 | 237 | 163 | 111 | 275 | 164 | serious×3 |
| 2353 | — | 342 | — | — | 377 | — | — | 413 | — | UNCERTAIN (cov 81%, W→eof) |
| 2387 | 415 | 269 | 146 | 434 | 290 | 144 | 651 | 330 | 321 | serious×3 |
| 2541 | 237 | 1051 | 814 | 247 | 1079 | 832 | 441 | 1119 | 678 | serious×3 |
| 2555 | 11 | 259 | 248 | 109 | 384 | 275 | 299 | 576 | 277 | serious×3 |
| 2625 | N/A | N/A | — | — | 167 | — | — | 222 | — | UNCERTAIN (no_track) |
| 2661 | — | 1009 | — | N/A | N/A | — | — | 1056 | — | UNCERTAIN (cov 21%) |
| 2680 | 527 | 200 | 327 | N/A | N/A | — | 652 | 241 | 411 | serious×2 |

### 4.2 DESIGN Aggregate

| Landmark | Eval | UNCERT | Within | Within% | Serious | Med err | P90 err |
|---|---|---|---|---|---|---|---|
| takeoff | 9/13 | 4 | 0 | **0%** | 9 | **224f** | 814f |
| apex | 7/11 | 4 | 0 | **0%** | 7 | **150f** | 275f |
| water_contact | 9/14 | 5 | 0 | **0%** | 9 | **277f** | 411f |

Tolerances: takeoff ≤5f serious >15f; apex ≤8f serious >20f; water_contact ≤5f serious >15f.

---

## 5. INTERNAL_EVAL Results

*Accessed once, after freeze. INTERNAL_EVAL human labels were not seen during any design decision.*

### 5.1 Per-Dive Predictions vs Human Labels

| Dive | T pred | T human | T err | A pred | A human | A err | W pred | W human | W err | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| 160 | — | 512 | — | — | 535 | — | — | 568 | — | UNCERTAIN (cov 86%, a2w prior violated) |
| 169 | 0 | 555 | 555 | 599 | 570 | 29 | 619 | 610 | 9 | serious×2 (T+A) |
| 191 | — | 128 | — | — | 153 | — | — | 197 | — | UNCERTAIN (cov 46%, t2a prior violated) |
| 192 | — | 938 | — | — | 965 | — | — | 999 | — | UNCERTAIN (cov 55%, a2w prior violated) |
| 848 | — | 180 | — | — | 204 | — | — | 246 | — | UNCERTAIN (cov 5%, low_coverage) |
| 2281 | 795 | 212 | 583 | 889 | 241 | 648 | 1017 | 282 | 735 | serious×3 |

Notes: dive 169 water_contact err=9f (not serious per >15f threshold, but not within 5f either).

### 5.2 INTERNAL_EVAL Aggregate

| Landmark | Eval | UNCERT | Within | Within% | Serious | Med err | P90 err |
|---|---|---|---|---|---|---|---|
| takeoff | 2/6 | 4 | 0 | **0%** | 2 | **569f** | 555f |
| apex | 2/6 | 4 | 0 | **0%** | 2 | **338.5f** | 29f |
| water_contact | 2/6 | 4 | 0 | **0%** | 1 | **372f** | 9f |

INTERNAL_EVAL confirms DESIGN findings. 67% UNCERTAIN rate (vs 36% on DESIGN).

---

## 6. A / B / C Comparison

### 6.1 DEVELOPMENT_DESIGN (n=14)

| Landmark | Metric | Baseline A | Baseline B | Baseline C |
|---|---|---|---|---|
| takeoff | within-tol | 0/13 (0%) | 0/12 (0%) | 0/9 (0%) |
| takeoff | serious | 12/13 | 11/12 | 9/9 (100%) |
| takeoff | median_err | **94f** | **157f** | **224f** |
| apex | within-tol | 0/11 (0%) | 0/7 (0%) | 0/7 (0%) |
| apex | serious | 10/11 | 6/7 | 7/7 (100%) |
| apex | median_err | **89f** | **63f** | **150f** |
| water_contact | within-tol | 0/14 (0%) | 1/13 (8%) | 0/9 (0%) |
| water_contact | serious | 13/14 | 11/13 | 9/9 (100%) |
| water_contact | median_err | **85f** | **70f** | **277f** |
| UNCERTAIN | any | 1/14 (7%) | 3/14 (21%) | 5/14 (36%) |

### 6.2 INTERNAL_EVAL (n=6)

| Landmark | Metric | Baseline A | Baseline B | Baseline C |
|---|---|---|---|---|
| takeoff | within-tol | 0/6 (0%) | 1/6 (17%) | 0/2 (0%) |
| takeoff | serious | 6/6 | 3/6 | 2/2 (100%) |
| takeoff | median_err | **137f** | **13f** | **569f** |
| apex | within-tol | 0/6 (0%) | 2/6 (33%) | 0/2 (0%) |
| apex | serious | 6/6 | 3/6 | 2/2 (100%) |
| apex | median_err | **91.5f** | **54.5f** | **338.5f** |
| water_contact | within-tol | 0/6 (0%) | 0/6 (0%) | 0/2 (0%) |
| water_contact | serious | 4/6 | 5/6 | 1/2 |
| water_contact | median_err | **160.5f** | **168.5f** | **372f** |
| UNCERTAIN | any | 0/6 | 0/6 | 4/6 (67%) |

**Trend**: C is strictly worse than A and B on all metrics. The UNCERTAIN rate increases
monotonically A→B→C. On DESIGN, C has 100% serious rate (among evaluable dives).
Baseline B is the best performer to date on INTERNAL_EVAL median errors.

---

## 7. Failure Mode Analysis

### 7.1 Primary: EARLY_TRIGGER (7/9 DESIGN predictions, 1/2 EVAL predictions)

Predicted takeoff at frame 0–11 when true takeoff is frame 108–1051.

**Root cause**: The diver is reliably detected on the board (walking/standing = COCO-canonical
person pose). After the diver takes off, YOLO fails to detect them in flight (athletic dive
pose, ~30–50px tall at 360p, motion blur during rotation). The gap+re-acquisition heuristic
finds the gap correctly but finds no sustained re-acquisition after the gap → falls back to
the velocity method which triggers too early.

### 7.2 Secondary: HIGH_COVERAGE_PRIOR_VIOLATION (3/4 INTERNAL_EVAL UNCERTAINs)

Dives 160, 191, 192 have 46–86% trajectory coverage but are UNCERTAIN because temporal priors
fire:
- Dive 160: raw a2w = 3 frames at 59.9fps → ~1.5f at 30fps reference → < prior_a2w_min=4f
- Dive 191: raw t2a = 12 frames at 59.9fps → ~6f at 30fps reference → < prior_t2a_min=8f
- Dive 192: raw a2w = 1108 frames at 59.9fps → ~554f at 30fps reference → > prior_a2w_max=400f

These are correct signals: the algorithm detected physically implausible intervals because
the detection track does not correspond to the actual dive flight (it tracks the diver through
warm-up/walking periods). The prior correctly rejects these nonsense predictions.

### 7.3 Tertiary: LOW_COVERAGE (2/14 DESIGN UNCERTAINs, 1/6 EVAL UNCERTAIN)

Dives 1040, 2169 (DESIGN) and 848 (EVAL): diver barely appears in the 360p proxy → YOLO
detects them in <10% of frames → no reliable track.

---

## 8. Confidence Audit

| Dive | Confidence | T err | A err | W err |
|---|---|---|---|---|
| 2555 | **0.532** (highest) | 248f | 275f | 277f |
| 676 | 0.021 | 213f | 48f | 70f |
| 169 (EVAL) | 0.006 | 555f | 29f | 9f |
| 133 | 0.006 | 108f | 77f | 65f |
| 2341 | 0.005 | 207f | 163f | 164f |
| 311 | 0.003 | 825f | N/A | 405f |
| 2281 (EVAL) | 0.019 | 583f | 648f | 735f |

**Finding**: No correlation between track confidence and frame error. The highest-confidence
prediction (2555, conf=0.53) has errors of 248–277 frames. There is no confidence threshold
that would separate usable from unusable predictions. Confidence reflects detection quality,
not event-detection accuracy.

---

## 9. Scientific Classification (Phase R)

**Classification: R4 — HUMAN_DETECTION_ITSELF_INSUFFICIENT**

Generic COCO-pretrained person detection (YOLOv8n, class 0) is unreliable for detecting
divers in this footage:

| Factor | Detail |
|---|---|
| Resolution | 360p proxy → diver ~30–50px tall during flight |
| Pose distribution | Athletic dive poses (tuck, pike, layout) outside COCO training distribution |
| Motion blur | Fast rotation during flight; blur reduces detector confidence |
| Camera angle | Top-down or side angle shows diver as elongated shape, not upright person |
| Track coverage | Median 19–36% (vs 100% on ideal conditions) |

**Key insight**: Adding a COCO neural detector made results *strictly worse* than
feature-based baselines A and B. This confirms that the domain gap between COCO persons and
diving footage is fundamental, not a parameter-tuning issue.

**Directions implied by R4**:
1. Fine-tune YOLOv8n on diving imagery (requires labeled diving data)
2. Pose estimation (ViTPose / HRNet → joint skeleton → event rules)
3. Strengthen signal-based approach (build on B's optical flow baseline)
4. Multi-modal (audio splash + optical flow for water_contact)

---

## 10. Phase S — Proxy vs Original Decision

**Decision: KEEP_DEFERRED** (`PROXY_VS_ORIGINAL_CANARY = DEFERRED_UNTIL_NEAR_NOISE_FLOOR`)

Median errors are 150–569 frames. Proxy vs original would matter at ±5–10 frames.
Not relevant until an algorithm is within striking distance of tolerance thresholds.

---

## 11. Pairwise Impact (Phase Q)

All C predictions are either UNCERTAIN or seriously wrong. There is no close call stratum
for pairwise analysis. Deferred until ≥10% within-tolerance is achieved on any landmark.

---

## 12. Resource Characterization

- CPU: Pentium 3550M @ 2.30GHz (no GPU viable on this server)
- Per-dive: ~6–10 min at vid_stride=1 on 360p proxy (resolution-dependent)
- Estimated GPU speedup: ~10–20× on RTX 3080 → ~30–60s/dive
- RAM peak: ~900 MB (PyTorch + YOLO + OpenCV frame buffer)
- Model: yolov8n.pt, 6.26 MB, weights SHA256 `f59b3d8...`

---

## 13. Tests

Covered by `backend/tests/test_analysis_layer2.py` (119 tests, all passing,
run with `pytest backend/tests/test_analysis_layer2.py --noconftest -v`):

| Class | Coverage |
|---|---|
| TestTrackSelectionLogic | _select_primary_track logic |
| TestTrajectorySmoothingLogic | interpolation, smoothing, gap limits |
| TestEventDetectionLogic | takeoff/apex/water_contact detection |
| TestBaselineCConfidenceLogic | confidence scoring |
| TestBaselineCSerializationAndFingerprint | proposer fingerprint stability |
| TestAnnotationFileParsing | DESIGN-only access; INTERNAL_EVAL firewall |
| TestScientificManifestIntegrity | split fingerprints, disjointness (B1) |
| TestEvaluatorSynthetic | frame_err, within_tol metrics (B3) |
| TestProvenanceFingerprints | model/param fingerprint changes (B4) |

---

## 14. Files

| File | Purpose |
|---|---|
| `experiments/landmark_pilot/proposer_baseline_c.py` | Algorithm implementation |
| `experiments/landmark_pilot/run_baseline_c.py` | Evaluation harness |
| `experiments/landmark_pilot/requirements_c.txt` | Pinned dependencies |
| `docs/science/BASELINE_C_FREEZE_V1.json` | Frozen parameter manifest |
| `docs/science/BASELINE_CC2_CANARY_RESULTS_V1.json` | 4-dive canary results |
| `docs/science/BASELINE_CC2_DESIGN_RESULTS_V1.json` | 14-dive DESIGN results |
| `docs/science/BASELINE_CC2_EVAL_RESULTS_V1.json` | 6-dive INTERNAL_EVAL results |
| `docs/science/TEMPORAL_LANDMARK_BASELINE_C_V1_REPORT.md` | This report |
| `backend/tests/test_analysis_layer2.py` | 119 tests (expanded from 37) |

---

## 15. Next Direction Recommendation

Supervisor review of R4 classification is required before committing to the next baseline.
Three candidates, in order of estimated implementation cost:

| Option | Description | Estimated difficulty |
|---|---|---|
| D3-OPT | Improve Baseline B (optical flow + stronger motion segmentation) | Low (no new data needed) |
| D1-FT | Fine-tune YOLOv8n on diving images (50–200 labeled frames) | Medium (requires data labeling) |
| D2-POSE | ViTPose / HRNet pose estimation on proxy frames | Medium-high (larger model, no label cost) |

**Recommended first step**: D2-POSE (pose estimation). Body joint positions provide direct
discriminating signal for takeoff (feet leave board), apex (body at maximum height), and
water_contact (hands enter water) without requiring diving-specific training data.

---

*End of Baseline C V1 Report*
