# REAL_SIGNAL_EVENT_LOGIC_AND_HIGHRES_PIPELINE_V1_REPORT

**Date:** 2026-09-06  
**Author:** maxime@qwokka.fr  
**Supersedes gate:** SUPERVISOR_REVIEW_AFTER_EVENT_LOGIC_V2  
**Head at report:** baeb7378702bf6c69e6e2158c10b0c2e40ff4931  
**Canary source:** `IMG_1937.mov` SHA256=`d122262be8e7a8721ab2f6a71721bb3544403da78324138d026360ef9820eaae`

---

## 1. PHASE A — SYNTHETIC CANARY CHECK AUDIT (PHASE_M_CANARY_CHECK)

### Classification: `ORACLE_TRAJECTORY_TEST`

The PHASE_M_CANARY_CHECK (`phase_m_canary_check.py`) constructs a synthetic trajectory
whose **breakpoints use GT landmark times as input** (board_recontact=2.668s, takeoff=3.12s,
apex=3.57s, water_contact=4.22s). The state machine does NOT receive these times;
it must detect them from the trajectory shape.

### Actual committed-code output

| Landmark | Detected | GT | Error | Status |
|---|---|---|---|---|
| takeoff | 1.450s | 3.120s | -1.670s | MECHANISM FAILURE |
| apex | 2.217s | 3.570s | -1.353s | MECHANISM FAILURE |
| water_contact | 4.233s | 4.220s | +0.013s | GENUINE |

**Root cause:** The sinusoidal hurdle oscillation (`y = 0.40 + 0.04*sin(...)`) produces
periodic non-positive velocity transitions. The first such transition after the hurdle guard
(at t≈0.883s) is detected as "board_recontact." The subsequent oscillation peak is detected
as "takeoff" at t=1.45s — 1.67s before the true takeoff.

### Document vs actual discrepancy

`HIGH_RESOLUTION_CANARY_EVENT_SEMANTICS_CORRECTION_V1.md` records takeoff=−0.103s,
apex=+0.013s, water_contact=+0.030s. **These values were never produced by the committed code.**
The actual committed code produces −1.670s/−1.353s/+0.013s. The document is incorrect.

### Consequence

The 0.103/0.013/0.030s values are **NOT mechanism-validation evidence** for end-to-end accuracy.
They do not exist in code output. Only water_contact detection is genuine (+0.013s).

The 29 unit tests remain valid — they test individual functions in isolation, not the
end-to-end state-machine sequence on a realistic hurdle trajectory.

---

## 2. PHASE B — L1 INFERENCE PORTABILITY

**`L1_LOCAL_INFERENCE = PASS`** (technically) / **`L1_FUNCTIONAL_DETECTION = FAIL`**

### Model identity

- Weights: `L1_frozen_backbone_best.pt`  
- SHA256: `4944e62fade083872d425bc53ef5ff9f4f0bd0354610b405df144463d1c59ce9`  
- Architecture: YOLOv8n, frozen backbone (10 layers), COCO class 0 (person)  
- Trained on: 28 DEVELOPMENT frames (11 dives) at 360p  
- Val mAP50: 0.766 (8 val boxes, 3 dives)  

### B1: MPS (Apple M2)

- Status: **PASS** — torch 2.14.0, MPS available, model loads and runs  
- Speed: 220ms/frame (first inference), 221ms/frame (warm) at imgsz=640  
- CUDA is NOT required: inference runs on MPS

### B2: CPU fallback

- Status: **PASS** — 40ms/frame at imgsz=640 on Apple M2  
- MPS is ~5.5× faster than CPU for single-frame inference

### B3: Parity

- MPS and CPU: identical output (both 0 detections) — perfect parity

### B4: Functional failure

L1 at conf=0.10 produces **0 detections** on all 5 key frames (hurdle, board_load,
takeoff, apex, water_contact) at R1080 (imgsz=640 and imgsz=1920). At conf=0.01
with no class filter: 100–112 near-random boxes at conf=0.010–0.014 (noise floor).

**Root cause:** Domain distribution mismatch. The model was trained on 360p frames from
a specific pool/camera combination. The canary video (Paris pool, 1080p HEVC portrait,
different pool background, different lighting) is outside the training distribution.

**CUDA is NOT genuinely required.** The architecture runs locally; the performance gap
on this video is a generalization problem, not a hardware problem.

---

## 3. PHASE C — MEDIA SEMANTICS AUDIT

### Photos export semantics (from `media_materializer.py`)

`osxphotos export TARGET --uuid UUID --only-movies --download-missing --update`

**No `--skip-edited` flag.** osxphotos by default exports the **user-edited (trimmed)
version** of an asset when edits are present, or the original when there are none.
Since users manually pre-trim clips in Photos before ingestion, the exported file
IS the user-intended trimmed content.

### ANALYSIS_SOURCE definition

> `ANALYSIS_SOURCE` = the user-edited/trimmed Photos rendition exported by osxphotos
> without `--skip-edited`. This is the highest-quality representation that preserves
> the user's intended temporal boundaries and content.

This is NOT the raw camera master. Conflating them would introduce temporal misalignment.

### Existing proxy source

The existing 360p proxy is generated from the `ANALYSIS_SOURCE` (edited/trimmed Photos
rendition), NOT from the unedited camera master. PTS structure and clip boundaries
derive from the same user-trimmed content.

### `--skip-edited` disposition

Any recall using `--skip-edited` would export the **unedited camera master**, which
may contain content before/after the user's trim. This strategy is:

**`SCIENTIFICALLY_INVALID_FOR_DIRECT_PTS_COMPARISON`**

PTS timestamps from an untrimmed master cannot be directly compared to annotations
made on the trimmed rendition without a proven temporal transform.

### Canary video identity

`/Users/maximecauchy/Downloads/IMG_1937.mov` (SHA256 verified) is consistent with
the user-trimmed rendition: it begins at hurdle onset (frame 0 = hurdle start) and
ends ~1.15s after water contact, consistent with a manual trim around the dive event.

---

## 4. PHASE D — CONTROLLED REPRESENTATIONS

Three representations generated from identical source (`IMG_1937.mov`):

| Name | Dimensions | N frames | SHA256 |
|---|---|---|---|
| R1080 | 1080×1920 | 322 | `3eb1785e87d7d0a5263a636d8dcef56f29c2545ccc11a4dd72e3e7baeb56bd1a` |
| R720 | 720×1280 | 322 | `90d53ccd169055324cc03296204c078534ab7563c7f58ddfd7239e548546c88c` |
| R360 | 360×640 | 322 | `4d7ddb0379d8ffb191bdac64dfe1dddf7f0cc53c5e234fb3c4fb70705bb3a127` |

All share the same frame count (322) and PTS structure (60000/1001 fps ≈ 59.94Hz).
Rotation applied at encode time (source: HEVC 1920×1080 with -90° tag → H.264 portrait).
Landmark frame indices (187, 214, 253) preserved identically across all representations.

**PTS alignment note:** R1080 PTS at landmark frames (3.170, 3.554, 4.188s) differ by
0.033–0.050s from the source GT (3.120, 3.570, 4.220s) due to VFR→CFR re-encoding.
Frame indices remain canonical.

---

## 5. PHASE E/F — REAL L1 DETECTION AND RESOLUTION ABLATION

### L1 domain-adapted model

**0 detections at all resolutions (R1080/R720/R360) at conf=0.10.**  
Functional failure — complete generalization breakdown to canary video.

### COCO yolov8n (framewise, conf=0.10)

| Rep | Frames with detection | Recall | FPS (MPS) |
|---|---|---|---|
| R1080 | 322/322 | 100% | 52.1 |
| R720 | 322/322 | 100% | 70.2 |
| R360 | 300/322 | 93.2% | 74.7 |

**Critical: COCO detects spectators/bystanders, NOT the target diver during flight.**

At landmark frames (takeoff=187, apex=214, water_contact=253):
- The dominant detection (cy_norm≈0.503, cx_norm≈0.086) is a **stationary spectator**
  present in all frames at the pool deck level
- The target diver during flight (t=3.12s to 4.22s) is **NOT detected** at any resolution
- Upper-frame detections (cy_norm<0.40, potential diver) occur only in early frames
  (t<1.0s, hurdle approach) and are sparse

### Resolution effect on diver detection

| Resolution | Diver detected at takeoff | Diver detected at apex | Diver detected at WC |
|---|---|---|---|
| R1080 | NO | NO | NO |
| R720 | NO | NO | NO |
| R360 | NO | NO | NO |

**Resolution is NOT the primary limiting factor.** The diver is undetectable at flight
phase across all resolutions. This is a scene complexity + COCO generalization limitation.

**Phase F classification: `RESOLUTION_NOT_PRIMARY`**

---

## 6. PHASE G — FRAMEWISE VS BYTETRACK

### ByteTrack on R1080

- 10 unique track IDs across 322 frames  
- **Track 41** (n=142 frames): mean_cy=0.503, mean_cx=0.086 → THE STATIONARY SPECTATOR  
- **Track 17** (n=96 frames): mean_cy=0.477, mean_cx=0.650 → pool-side person/background  
- Other tracks: 3–16 frames, pool background  
- **No track corresponds to the target diver in flight**

### Comparison: Framewise vs ByteTrack

Both produce the same fundamental failure: the dominant tracked entity is a spectator,
not the diver. ByteTrack improves temporal consistency of the spectator track but does
not help locate the diver.

**ByteTrack does NOT add scientific value on this video.** It reinforces the wrong target.

Target selection (`longest_x_conf`) picks Track 41 (spectator) or Track 17
(background) — neither is scientifically useful.

---

## 7. PHASE H — TRAJECTORY CONTRACT

### Defined contract (formally)

```
Trajectory = {
    pts_arr: float[N]       # PTS seconds, from decoded video packets (not idx/fps)
    y_arr: float|None[N]    # -cy_norm (positive = UP; cy_norm=0 is top of frame)
    conf_arr: float[N]      # detection confidence; 0.0 if no detection
    cx_arr: float|None[N]   # cx_norm [0,1] left to right
    source_repr: str        # "R1080" | "R720" | "R360"
    detector: str           # "COCO_yolov8n" | "L1_frozen_backbone"
    selection_strategy: str # how target was selected per-frame
    missing_semantics: str  # "None = no detection; not imputed"
    interpolation: "bounded_linear, max_gap_s=0.30"
    velocity_units: "frame_norm_per_second (positive=up)"
}
```

Time-aware: all smoothing and velocity use PTS differences. No hard-coded FPS.

---

## 8. PHASE I — REAL SIGNAL EVENT LOGIC V2 CANARY

### Label: `REAL_SIGNAL_EVENT_LOGIC_V2_CANARY`

Input: COCO framewise max-confidence trajectory (selects spectator at cy_norm≈0.50)

| Rep | Takeoff | Apex | Water Contact |
|---|---|---|---|
| R1080 | NOT DETECTED | NOT DETECTED | NOT DETECTED |
| R720 | NOT DETECTED | NOT DETECTED | NOT DETECTED |
| R360 | NOT DETECTED | NOT DETECTED | NOT DETECTED |

**ALL LANDMARKS UNDETECTED AT ALL RESOLUTIONS.**

The state machine:
1. Detects preparation end (spectator has nearly constant position → triggers plateau)
2. Finds no upward velocity (spectator is stationary) → takeoff not triggered
3. Apex and water_contact never reached

This is a COMPLETE FAILURE of the end-to-end pipeline on real perception input.

---

## 9. PHASE J — CAUSAL ERROR ATTRIBUTION

Error origin for each undetected landmark:

| Landmark | Primary failure | Secondary |
|---|---|---|
| takeoff | **DETECTOR MISS** (diver not detected during flight) | Wrong person selected |
| apex | **DETECTOR MISS** | Wrong person selected |
| water_contact | **DETECTOR MISS** | Wrong person selected |

The failure is entirely in the **perception layer**, not in Event Logic V2 rules or
trajectory transforms. The state machine receives a flat trajectory (stationary spectator)
and correctly finds no velocity-based transitions.

Event Logic V2 is NOT the bottleneck — the input is wrong.

---

## 10. PHASE K — ANALYSIS RESOLUTION DECISION

**`RESOLUTION_NOT_PRIMARY`**

Resolution change does not fix the diver detection failure. The problem is:
1. L1 domain-adapted model: complete generalization failure
2. COCO: detects spectators/background instead of the diver

Higher resolution does not help COCO find the diver (the diver appears at all resolutions
but COCO still detects the more salient spectators in the foreground).

---

## 11. PHASE L — EVENT LOGIC V3

**NOT EXECUTED — NOT JUSTIFIED.**

Event Logic V3 is conditional on:
- Perception trajectory being demonstrably adequate (FAILED — no usable trajectory)
- Event Logic V2 being the limiting component (CONFIRMED NOT — perception is)

Executing Event Logic V3 would improve nothing while the perception layer is broken.

---

## 12. PHASE M — HIGH-RES MEDIA PIPELINE CANARY

**DEFERRED — not applicable yet.**

Phase K determined RESOLUTION_NOT_PRIMARY. A 720p/1080p analysis proxy would not
help until the fundamental detection problem is solved.

`analysis_proxy_v1` design:
- Derived from ANALYSIS_SOURCE (user-trimmed Photos rendition)  
- PTS preserved from source  
- Checksum/version documented  
- No bulk corpus generation  
- Deferred until perception is viable

---

## 13. PHASE N/O — HIGH-RES PILOT SOURCE RECOVERY AND ALIGNMENT

**DEFERRED — not yet scientifically justified.**

Cannot compare source/proxy alignment until the perception pipeline can extract
meaningful trajectories. Performing alignment work now would validate a pipeline
that produces no useful output.

---

## 14. PHASE P — BOUNDED MULTI-DIVE EVALUATION

**DEFERRED.**

Perception is still insufficient. Running 6 dives through a broken pipeline produces
no new scientific information.

---

## 15. PHASE Q — INTERNAL LOCALIZATION LABEL STATUS

From previous study: DEVELOPMENT 38/38, INTERNAL_EVAL 0/18.

**Not required for current scientific decisions.** The DEVELOPMENT corpus would not
fix the generalization failure on the canary video. Deferred.

---

## 16. PHASE R — L1 DOMAIN ADAPTATION AUDIT

### Dataset summary

| Split | Dives | Boxes |
|---|---|---|
| Train | 11 | 28 |
| Val | 3 | 8 |

Split strategy: dive-level (no same-dive leakage).

### Leakage classification: `CLEAN_GROUPED_SIGNAL`

No adjacent-frame or same-dive leakage detected. The dive-level split prevents the
most common form of leakage.

**However:** Val mAP50=0.766 is based on only 8 validation boxes. High variance.
All dives are from the DEVELOPMENT corpus (same athlete, likely same or similar pools).
The model appears to have learned pool-specific and athlete-specific features that
do not generalize to the canary video (Paris pool, different visual environment).

**Qualified as:** `CLEAN_GROUPED_SIGNAL` but **optimistic generalization claim**
due to distribution narrowness and tiny validation set.

---

## 17. PHASE S — ARCHITECTURE DECISION

**`PERCEPTION_STILL_INSUFFICIENT`**

Rationale:
- L1 domain-adapted model: 0 detections on canary video
- COCO model: detects spectators, not diver during flight
- Neither model provides a usable trajectory for Event Logic V2

Neither framewise detection nor ByteTrack recovers the diver track.

SAM2 and pose estimation remain deferred — insufficient evidence to justify either.

---

## 18. PHASE T — EVENT LOGIC STATUS

**`EVENT_LOGIC_NOT_YET_EVALUABLE_DUE_TO_PERCEPTION`**

Event Logic V2 cannot be evaluated end-to-end because no valid perception input
has been established. The 29 unit tests validate individual mechanism functions only.
The synthetic canary check has a trajectory-construction flaw that makes its good
water_contact result (also +0.013s) unreliable as accuracy evidence.

---

## 19. RESOURCE CHARACTERIZATION (Phase V)

| Setup | Speed | Notes |
|---|---|---|
| L1 MPS (M2) imgsz=640 | 220ms/frame | First inference warm-up included |
| L1 CPU imgsz=640 | 40ms/frame | |
| COCO MPS R1080 (1080×1920) imgsz=640 | 52.1fps | Full 322-frame clip |
| COCO MPS R720 (720×1280) imgsz=640 | 70.2fps | |
| COCO MPS R360 (360×640) imgsz=640 | 74.7fps | |
| ByteTrack R1080 MPS | 48.7fps | |

COCO at 1080p/MPS runs at ~52fps (real-time). L1 is slower due to model overhead but
still technically viable for non-real-time analysis.

---

## 20. REMAINING SCIENTIFIC LIMITATIONS

1. **L1 domain adaptation does not generalize** to novel pool/camera environments.
   The model trained on 28 DEVELOPMENT frames (one pool/athlete) fails on a Paris pool video.

2. **COCO YOLOv8n detects salient background persons**, not the diver, when both
   are present. Target selection without spatial/motion priors is fundamentally unsafe.

3. **The Phase M synthetic canary check mechanism is broken** (takeoff/apex detection).
   The state machine needs testing on a trajectory with realistic hurdle dynamics
   (monotone board-loading, not sinusoidal oscillation).

4. **Event Logic V2 has not been tested end-to-end on any real video.**
   Only the water_contact unit test (via phase_m_canary_check) produces a valid result.

5. **VFR→CFR re-encoding introduces small PTS drift** (up to 50ms) that may affect
   precise landmark comparison. Original source PTS should be used when possible.

---

## SUMMARY TABLE (LOCAL_AGENT_REPORT fields)

| Field | Value |
|---|---|
| PHASE_M_AUDIT | `ORACLE_TRAJECTORY_TEST` — mechanism failure, document contains fabricated values |
| L1_MPS | PASS (runs) / 0 detections (fails functionally) |
| L1_CPU | PASS (runs) / 0 detections (fails functionally) |
| L1_CUDA_REQUIRED | FALSE — MPS and CPU both work |
| ANALYSIS_SOURCE | User-edited/trimmed Photos rendition (osxphotos default export) |
| skip_edited_disposition | SCIENTIFICALLY_INVALID_FOR_DIRECT_PTS_COMPARISON |
| R1080_sha | 3eb1785e... (1080×1920, 322 frames) |
| R720_sha | 90d53ccd... (720×1280, 322 frames) |
| R360_sha | 4d7ddb03... (360×640, 322 frames) |
| REAL_L1_DETECTION | 0% all resolutions — COMPLETE FAILURE |
| TRACKING_ABLATION | ByteTrack tracks spectators, not diver. No advantage over framewise on this video |
| TRAJECTORY_CONTRACT | Defined: pts_arr, y_arr (-cy_norm), conf_arr, cx_arr, source, detector, missing_semantics |
| REAL_SIGNAL_EL_V2_TAKEOFF | NOT DETECTED (all reps) |
| REAL_SIGNAL_EL_V2_APEX | NOT DETECTED (all reps) |
| REAL_SIGNAL_EL_V2_WC | NOT DETECTED (all reps) |
| ERROR_ATTRIBUTION | DETECTOR MISS → wrong person selected → trajectory flat |
| ANALYSIS_RESOLUTION_DECISION | `RESOLUTION_NOT_PRIMARY` |
| EVENT_LOGIC_V3 | NOT JUSTIFIED — perception is the bottleneck |
| ANALYSIS_PROXY | DEFERRED |
| HIGHRES_PILOT_RECOVERY | DEFERRED |
| SOURCE_ALIGNMENT | DEFERRED |
| MULTI_DIVE_RESULT | DEFERRED |
| INTERNAL_LOCALIZATION | 0/18 (unchanged; not needed now) |
| DOMAIN_ADAPTATION_AUDIT | `CLEAN_GROUPED_SIGNAL` but optimistic due to tiny narrow-distribution dataset |
| PERCEPTION_ARCHITECTURE | `PERCEPTION_STILL_INSUFFICIENT` |
| EVENT_LOGIC_STATUS | `EVENT_LOGIC_NOT_YET_EVALUABLE_DUE_TO_PERCEPTION` |
| POSE_DECISION | DEFERRED — insufficient evidence to justify |
| TEST_RESULTS | 29/29 EL V2 unit tests pass (mechanism functions); new integration tests needed |

---

## RECOMMENDED NEXT STEPS (maximum 5)

1. **Fix the perception system for this use case.** Either:
   - Collect pool-diverse training data and re-train L1 domain adapter
   - Or use a spatial prior (person near the pool center/top frame area) to filter COCO detections
   - Required before any meaningful Event Logic V2 evaluation

2. **Fix the phase_m_canary_check synthetic trajectory** to correctly model the
   monotone board-loading phase (not sinusoidal hurdle oscillation). Correct the
   HIGH_RESOLUTION_CANARY_EVENT_SEMANTICS_CORRECTION_V1.md values.

3. **Add integration test for Event Logic V2** on a trajectory that correctly models
   the board-loading phase dynamics (not the unit-function-level tests that currently exist).

4. **Design discriminative target selection.** The current max-conf and ByteTrack strategies
   select background persons. A scene corridor prior (top-center of portrait frame,
   excluding pool edge area) would immediately exclude the spectator at cx_norm=0.086.

5. **Pool-specific calibration.** The Paris pool canary has specific background
   clutter. Establishing one pool-specific detection profile (water region, spectator
   region, corridor) could rescue COCO-based detection without retraining.

---

**SUPERVISOR_REVIEW_AFTER_REAL_SIGNAL_HIGHRES_V1**
