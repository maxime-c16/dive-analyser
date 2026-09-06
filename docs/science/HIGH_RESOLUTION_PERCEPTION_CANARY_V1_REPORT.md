# HIGH_RESOLUTION_PERCEPTION_CANARY_V1 — Scientific Report

**Date**: 2026-09-06  
**Study**: Phases A–W — HIGH_RESOLUTION_PERCEPTION_CANARY_V1  
**Repository**: dive-analyser, branch `uiux-overhaul-pro-app`  
**Source**: `IMG_1937.mov` (iPhone 17, 2026-08-22, Paris indoor pool)  
**Label**: `HIGH_RESOLUTION_MECHANISM_CANARY`  
**Precondition**: Supervisor gate `SUPERVISOR_REVIEW_AFTER_TEMPORAL_LANDMARK_PERCEPTION_V2` CLEARED  
**Expected HEAD at start**: `d2aed54` ✓ (actual: `d2aed54dfdc5c112ff0112c91365e170028a1987`)

---

## 0. STARTING STATE

| Item | Value |
|---|---|
| Canonical HEAD | `d2aed54dfdc5c112ff0112c91365e170028a1987` |
| Mac working copy | NOT a git repo (partial reference slice — expected) |
| Mac bare mirror | **ABSENT** — `~/dive-analyser` does not exist on `diveanalyzer-mac`. Mirror sync required at end. |
| Source video | `/Users/maximecauchy/Downloads/IMG_1937.mov` — read-only ✓ |

---

## 1. UNIT CHECK (Phase 3 of packet)

### Finding: "55–389 s" is SAM2 wall-clock compute time, NOT video duration

The V2 report table (Section J1) reads:

```
| Dive | Outcome         | Zero-area frames | Window (s) |
|------|-----------------|------------------|-----------|
| 311  | IMMEDIATE_COLLAPSE | 31/48         | 55        |
| 2541 | IMMEDIATE_COLLAPSE | 48/49         | 61        |
| 2555 | IMMEDIATE_COLLAPSE | 332/333       | 389       |
```

The JSON source (`PHASE_J_ORACLE_TRACKING_V1.json`) reveals:
- `"seconds": 54.92` for dive 311 = **wall-clock seconds for SAM2 to process 48 frames**
- `"window": [412, 459]` = **frame indices** in the proxy video
- Dive 2555 "389 s" = SAM2 needed 389 seconds of compute to process 333 frames

**Actual proxy clip durations** sampled from server cache:
`5.2 s, 5.4 s, 7.5 s, 9.5 s, 11.8 s, 12.2 s, 13.7 s, 19.3 s, 19.8 s` (n=9 sample)

Range: approximately **5–20 seconds** — not 55–389 seconds.

**CORRECTION**: The V2 report's "Window (s)" column is ambiguous. It refers to SAM2 computation time in wall-clock seconds, NOT to clip duration. The historical dive range is **5–20 seconds** at 360p proxy.

**Consequence for this packet**: The 5.37-second high-resolution canary is **NOT abnormally short**. It sits at the low end of the normal clip distribution.

**Durable correction to V2 report**: Added clarifying note in updated V2 report section J1. Column relabeled "SAM2 compute (s)" in the JSON freeze.

---

## 2. SOURCE CHARACTERIZATION (Phase A)

### SHA256
```
d122262be8e7a8721ab2f6a71721bb3544403da78324138d026360ef9820eaae
```

### ffprobe Evidence

| Property | Value |
|---|---|
| Duration | 5.373333 s |
| Frame count (streams) | 344 (includes 22 Dolby Vision RPU frames) |
| Frame count (decoded video) | **322** |
| r_frame_rate | 60000/1001 ≈ 59.94 fps (nominal) |
| avg_frame_rate | 51600/913 ≈ 56.52 fps (container average) |
| Actual PTS intervals | 0.016666 s (≈60 fps) and 0.018333 s (rare) |
| PTS range | 0.000000 s – 5.355000 s |
| VFR/CFR | **VFR** — r_frame_rate ≠ avg_frame_rate; intervals are 1/60.0 or 1/54.5 |
| Encoded dimensions | 1920×1080 |
| Display dimensions | **1080×1920** (portrait) via Display Matrix rotation −90° |
| Pixel format | yuv420p10le (10-bit) |
| Color space | BT.2020 Non-Constant Luminance |
| Transfer | ARIB-STD-B67 (HLG / Hybrid Log-Gamma) |
| Color primaries | BT.2020 |
| Dolby Vision | Profile 8, Level 5 (HDR/HLG layer, no EL) |
| Codec | HEVC Main 10 (hvc1) |
| Audio | Apple Lossless (ALAC, 4-ch) + AAC stereo |
| Creation time | 2026-08-22T15:03:44+0200 (filmed) |
| Location | +48.8156+002.4943+034.089 (Paris indoor pool) |
| Device | iPhone 17 |
| Caption | "5122D G/G" |

**Rotation note**: ffmpeg auto-applies the Display Matrix when decoding. All representations in this study use ffmpeg's auto-rotation so frames are correctly upright (portrait 1080×1920 for R0, 202×360 for R1).

---

## 3. DIVE IDENTITY (Phase B)

**Result: MATCHED_DIVE_ID = 2819**

| Evidence | Value |
|---|---|
| DB match method | raw_caption="5122D G/G" in photos_assets |
| photos_asset_id | 2815 |
| dive_id | 2819 |
| session_id | 169 (session date 2026-08-29 = ingestion date) |
| Filming date | 2026-08-22 |
| Dive code | 5122D (Inward 2.5 Somersault Pike) |
| Performance | G (Good) |
| Confidence | HIGH — exact caption match + iPhone 17 device + Paris location |

**Note**: The DB records session_date=2026-08-29 (ingestion) while the video was filmed 2026-08-22. This is expected — the Photos agent ingests on the next sync pass. The duration_seconds field in photos_assets is NULL, confirming no media job has been completed for this asset yet.

---

## 4. HUMAN REFERENCE (Phase D)

**Status**: No existing localization or temporal annotations for dive 2819.

**Available evidence**: Visual frame inspection provides approximate landmark identification:
- Frame t≈0s: Tall person on right-side platform (diver standing before takeoff)
- Frame t≈1.5s: Diver visibly airborne (confirmed by frame image)
- Frame t≈3.5s: Platform empty (diver has entered water)

**Conservative visual estimate**:
- Takeoff: ~0.3–0.5 s
- Apex: ~1.3–1.7 s
- Water contact: ~2.0–2.5 s

**Annotation request**: See Section 14 — ONE concise task for Maxime.

---

## 5. REPRESENTATIONS (Phase C)

| Rep | File | Dimensions | Frames | fps | SHA256 (prefix) |
|---|---|---|---|---|---|
| R0 | R0_native_portrait.mp4 | 1080×1920 | 322 | 60000/1001 | 2f12a322... |
| R1 | R1_360p_norotate.mp4 | 202×360 | 322 | 60000/1001 | afe37a6f... |

**FFmpeg commands** (read-only — source NOT modified):
```bash
# R0: native portrait (auto-rotation via ffmpeg display matrix)
ffmpeg -i IMG_1937.mov -vf "scale=1080:-2" -c:v libx264 -preset fast -crf 18 -an R0_native_portrait.mp4

# R1: 360p portrait (same rotation, scaled to height=360)
ffmpeg -i IMG_1937.mov -vf "scale=-2:360" -c:v libx264 -preset fast -crf 23 -an R1_360p_norotate.mp4
```

**PTS alignment**: Verified IDENTICAL between R0 and R1 (ffprobe confirms same PTS sequence to 6 decimal places).

**No R2**: A 720p intermediate was considered. Given that COCO detects 100% recall at 1080p and 4.3% at 360p, a 720p point is scientifically useful (Phase N analysis). However, the primary causal finding is already clear at 2 points. R2 deferred to future targeted experiment.

---

## 6. DETECTOR IDENTITIES (Phase E)

### D0 — Frozen generic COCO YOLOv8n
- **Architecture**: YOLOv8n, COCO 80-class
- **Weights**: yolov8n.pt (downloaded from ultralytics v8.4.0)
- **Class filter**: [0] (person)
- **Inference size**: imgsz=1920 (R0), imgsz=640 (R1)
- **Confidence**: 0.25 NMS: 0.45

### D1 — L1 frozen backbone (domain-adapted)
- **Architecture**: YOLOv8n, 1-class (diver), freeze=10 layers
- **Weights SHA256**: `4944e62fade083872d425bc53ef5ff9f4f0bd0354610b405df144463d1c59ce9`
- **Training**: 28 DEVELOPMENT_DESIGN frames (landscape 360p proxy)
- **Val mAP50** (V2 report): 0.766
- **Inference size**: imgsz=1920/640, conf=0.25

---

## 7. PAIRED RESOLUTION × DETECTOR EXPERIMENT (Phase F)

### 2×2 Primary Table

| Detector | Representation | Recall | Mean Conf | Mean px Height | Inference fps |
|---|---|---|---|---|---|
| D0 COCO | R0 native 1080p | **1.000** | **0.703** | **102.8 px** | 5.0 |
| D0 COCO | R1 360p | 0.043 | 0.358 | 31.2 px | 34.3 |
| D1 L1 | R0 native 1080p | **0.000** | 0.000 | 0.0 px | 5.2 |
| D1 L1 | R1 360p | **0.000** | 0.000 | 0.0 px | 38.7 |

*Recall = fraction of 322 frames with ≥1 detection above conf=0.25.*

### Resolution Effect (holding D0 constant)
- 1080p: recall=1.000 (322/322 frames detected)
- 360p: recall=0.043 (14/322 frames detected)
- **Resolution effect: 23× recall improvement at native vs 360p for generic COCO detector**
- Diver pixel height: 102.8 px at 1080p vs 31.2 px at 360p (3.3× larger at native)
- This is the **SCALE_FAILURE** root cause confirmed at new clip

### Domain Adaptation Effect (holding resolution constant)
- D0 at R0: 100% recall
- D1 at R0: 0% recall
- **Domain adaptation FAILURE**: L1 completely fails to generalize to this new clip at BOTH resolutions
- Diagnosis confirmed: max L1 confidence seen across all frames = 0.013 at conf=0.01 threshold — essentially noise-floor output
- Root cause: L1 trained on landscape 360p proxies from specific Paris pool sessions; new clip has different orientation (portrait), different visual context (10-bit HDR vs SDR proxy), completely OOD
- **Critical revision of V2 conclusion**: L1 mAP50=0.766 does NOT generalize. The domain adaptation is overfitted to training distribution. This is addressed in Phase P.

### Key Finding
**RESOLUTION_MAJOR** + **DOMAIN_ADAPTATION_OVERFITTING**:
- At native 1080p, even the generic COCO detector detects 100% of frames
- The L1 model has zero cross-clip generalization despite mAP50=0.766 in-distribution

---

## 8. FRAMEWISE DETECTION CONTINUITY (Phase G)

**Running D0 COCO on R0 native frame-by-frame (322 frames):**

- All 322 frames have ≥1 detection
- Mean candidates per frame: **5.6** (range: 2–11)
- Candidates include the diver AND spectators/poolside officials/other divers

**Scene content** (from frame image inspection):
- Indoor Paris diving pool, camera at pool deck level
- Pool occupies upper 55% of portrait frame
- Diving platform/tower on RIGHT side (cx_norm ≈ 0.80–0.95)
- Multiple spectators/coaches on LEFT and center (cx_norm < 0.45, always static)
- Water surface: approximately cy_norm ≈ 0.50–0.55

**Static spectator clusters identified** (cy_range < 0.02 across all 322 frames):
`cx_norm ∈ {0.075, 0.150, 0.175, 0.250, 0.275, 0.300, 0.525}`

**Diver candidate ROI**: cx_norm > 0.55, cy_norm ∈ [0.20, 0.70]

**DIVER SELECTION PROBLEM**: Even at 100% detection recall, selecting the CORRECT person (the diver vs poolside officials and other athletes) requires scene geometry priors. Highest-confidence candidate is consistently a static poolside observer on the LEFT (cx_norm=0.086), not the diver.

---

## 9. TRACKING ABLATION (Phase H)

### H0 — Per-frame selection + scene ROI

- **Method**: Reject static cx buckets; select largest px_height candidate in ROI
- **Coverage**: 322/322 frames (100.0%) — always returns a selection
- **Problem**: cx_norm drifts from 0.929 to 0.648 across the clip — the algorithm is switching between different people in the ROI (not stable single-person tracking)
- **Trajectory noise**: High. The selection jumps between multiple people as the dive progresses.

### H1 — ByteTrack

- **Coverage**: 176/322 frames (54.7%) — loses track for 146 frames
- **Selected track**: Track ID=2 (cy_range=0.119, mean_cx=0.748, 176 frames)
- **Other ROI tracks**: Track 21 (cx=0.836, 132 frames), Track 4 (cx=0.649, 216 frames, static)
- **Gap analysis**: ByteTrack loses the diver during the fast-moving flight phase (ironic — the most interesting part of the dive has lowest coverage)
- **Identity switches**: Not fully quantifiable without ground truth, but the drifting cx_norm in H0 suggests ID switches

### Ablation Verdict

| Metric | H0 (frame selection) | H1 (ByteTrack) |
|---|---|---|
| Coverage | 100% (noisy) | 54.7% (clean but gapped) |
| Trajectory stability | LOW (cx drifts 0.3 units) | MEDIUM (one dominant track) |
| ID correctness | UNCERTAIN | UNCERTAIN |
| Gaps | None | 146/322 frames |

**Finding**: H1 (ByteTrack) covers only 54.7% of frames but produces a more stable single-person track. H0 has full coverage but tracks the wrong person in many frames. **Neither H0 nor H1 produces a reliable diver-only trajectory without scene geometry constraints**.

**Preferred path**: Neither H0 nor H1 alone suffices. The correct architecture requires:
1. Scene geometry initialization (platform position, water line)
2. Selection constrained to the dive corridor
3. ByteTrack for temporal continuity once correctly seeded

---

## 10. PTS-AWARE TRAJECTORY (Phase I)

**Best available trajectory**: H0 with ROI filtering (100% coverage, noisy)

Sampled trajectory (every ~0.33 s):

| t (s) | cy_norm | cx_norm | px_h | cy_smooth |
|---|---|---|---|---|
| 0.000 | 0.387 | 0.929 | 251 | 0.386 |
| 0.334 | 0.383 | 0.849 | 260 | 0.383 |
| 0.667 | 0.388 | 0.809 | 241 | 0.388 |
| 1.001 | 0.378 | 0.796 | 278 | 0.378 |
| 1.335 | 0.358 | 0.761 | 295 | 0.360 |
| 1.668 | 0.403 | 0.708 | 248 | 0.406 |
| 2.002 | 0.362 | 0.695 | 304 | 0.358 |
| 2.336 | 0.477 | 0.655 | 136 | 0.478 |
| 2.669 | 0.389 | 0.677 | 246 | 0.388 |
| 3.003 | 0.418 | 0.648 | 308 | 0.415 |
| 3.337 | 0.315 | 0.601 | 178 | 0.409 |
| 3.670 | 0.474 | 0.685 | 148 | 0.476 |
| 4.004–5.339 | ≈0.472 | ≈0.705 | ≈158 | ≈0.475 |

**Trajectory interpretation**:
- t=0–1.5s: cx drifts from 0.929 to 0.76, likely tracking diver from platform into early flight
- t=1.5–2.3s: cy reaches minimum ~0.358 (highest point in frame = apex region)
- t=2.3s: cy jumps to 0.477 — possible water entry, or selection switched to different person
- t=3.5–5.3s: trajectory stabilizes at cy≈0.47, cx≈0.70 — appears to be a poolside person, not diver

**Caveat**: Without human temporal landmarks, the trajectory boundary (dive arc vs spectator) is unclear. The jump at t=2.3s is the strongest candidate for water entry.

---

## 11. SCENE GEOMETRY (Phase J)

**Platform**: On right side of frame, approximately cx_norm ∈ [0.82, 0.95]. Multiple levels visible.
**Water surface**: Horizontal band, approximately cy_norm ≈ 0.48–0.55 (upper pool edge visible in frame).
**Pool deck (camera level)**: cy_norm > 0.75 (foreground, no diving action).
**Dive corridor**: Right quarter of frame (cx_norm > 0.65), upper half (cy_norm < 0.55).

**Scene geometry representation**: `MANUALLY_INITIALIZED_GEOMETRY` — the platform position and water line can be estimated from first/last frames as fixed regions. A static background subtraction or ROI mask would substantially improve diver selection.

**Geometry-constrained detection rule** (proposed, not yet implemented):
1. Detect the diving platform in frame 0 (person standing = diver on board)
2. Set water line at cy_norm ≈ 0.50
3. Diver must be: cx_norm ∈ [platform_cx ± 0.15], cy_norm < water_line
4. At entry: diver disappears below water_line

---

## 12. CC3 CANARY RESULT (Phase L)

**Status**: PARTIAL — no human temporal reference for dive 2819.

**Algorithm-estimated landmarks** (from H0 trajectory, no validation possible):
- Takeoff: 0.000 s (algorithm artifact — first detection = takeoff)
- Apex: 2.119 s (minimum smoothed cy_norm)
- Water contact: 4.137 s (maximum cy after apex)

**Visual cross-check** (from frame image inspection):
- t≈0.0 s: Diver standing on platform — this IS the pre-takeoff position
- t≈1.5 s: Diver clearly airborne (visible in frame 4 image)
- t≈3.5 s: Platform empty (visible in frame 8 image) — diver has entered water

**Discrepancy with algorithm**: Algorithm estimates water contact at 4.137 s, but visual evidence shows platform empty by 3.5 s. The algorithm's post-apex trajectory tracks a DIFFERENT PERSON (poolside person at cy≈0.47, stable), inflating the water contact time.

**CC3 quality**: UNRELIABLE — the diver selection error propagates through the landmark estimates. CC3 is STILL INSUFFICIENT for this clip, for a different reason than in V2: not because of scale failure but because of multi-person disambiguation.

**Label**: `HIGH_RESOLUTION_MECHANISM_CANARY — CC3 INSUFFICIENT (DIVER_SELECTION_FAILURE)`

---

## 13. CAUSAL DECOMPOSITION (Phase M)

| Effect | Magnitude | Evidence |
|---|---|---|
| **Resolution** | MAJOR | D0 recall: 1.000 (1080p) vs 0.043 (360p); 23× improvement |
| **Domain adaptation** | OVERFITTING | L1 recall: 0.000 at both resolutions; complete OOD failure |
| **Diver selection** | NEW BOTTLENECK | Even at 100% detection recall, selecting correct person is unsolved |
| **ByteTrack** | MARGINAL | 54.7% coverage vs 100% (noisy) coverage from frame selection |

**Classification**: `RESOLUTION_MAJOR` — resolution is the dominant effect on raw detection recall.

However, resolution alone does not solve the problem: once multiple people are detected, selecting the diver requires scene priors that are not yet implemented. The **diver selection error** is now the limiting factor at 1080p.

**Root cause chain (revised)**:
```
At 360p: SCALE_FAILURE → detection missing
At 1080p + COCO: MULTI_PERSON_AMBIGUITY → wrong person selected → bad trajectory
At 1080p + L1: DISTRIBUTION_SHIFT → complete detector failure
```

---

## 14. ANALYSIS RENDITION RECOMMENDATION (Phase N)

Native 1080p produces dramatically better detection (100% vs 4.3% recall). A 720p intermediate was not tested this session. Based on the scale effect:

**Recommendation**: `ANALYSIS_PROXY_720P` is a reasonable hypothesis for a future targeted test.
- At 360p: diver is ~31 px tall (unreliable detection)
- At 1080p (1920 px tall frame): diver is ~103 px tall
- At 720p (estimate): diver would be ~69 px tall — likely above the detection threshold

**No bulk generation yet.** This requires a single controlled A/B (360p vs 720p on the same clip) before committing to a new proxy spec.

**Architecture consequence**: The current proxy_360p pipeline is **inadequate for perception research**. A dedicated analysis proxy at 720p+ is needed.

---

## 15. PILOT 360P DISPOSITION (Phase O)

`360P_ONLY_VALID_FOR_COARSE_TASKS`

Rationale:
- For **temporal landmark research** (Phase T): 360p is still valid for studying HUMAN timestamps vs algorithm timestamps. The human-authored timestamps do not depend on image quality.
- For **spatial localization** and **detection-based methods**: 360p is inadequate. Detection recall dropped from 100% to 4.3% on the same clip.
- For **trajectory and event logic**: 360p is inadequate because detection failures dominate.

Human timestamps remain valid regardless of resolution change. Do NOT retroactively invalidate V2 ground truth timestamps.

---

## 16. DOMAIN ADAPTATION AUDIT (Phase P)

| Audit Item | V2 Claim | Audit Finding |
|---|---|---|
| Training boxes | 28 | ✓ correct |
| Validation boxes | 8 | ✓ correct |
| Train unique dives | 11 | ✓ correct |
| Val unique dives | 3 | ✓ correct |
| Same-dive leakage | None (dive-level split) | ✓ correct |
| Near-duplicate leakage | Possible within val dives | LOW RISK (3 annotations per dive spread across landmark events) |
| Cross-session leakage | Train/val both from same pool (Paris) | MEDIUM RISK — val dives share pool with some train dives |

**Critical audit finding**: The val set mAP50=0.766 is **not a production generalization estimate**. L1 completely fails on `IMG_1937.mov` (same pool, different session, portrait format), with max confidence 0.013.

**Reclassification**: L1 mAP50=0.766 should be labeled `IN_DISTRIBUTION_FEASIBILITY_SIGNAL` not `PRODUCTION_ACCURACY_ESTIMATE`.

**Root causes of generalization failure**:
1. Training data was landscape 360p proxies; new clip is portrait 1080p native
2. Training data from specific sessions; model latched onto session-specific visual statistics
3. Training set too small (28 images) to learn robust diver appearance

**Recommendation**: Do NOT retrain L1 on current data. Instead:
1. Acquire more diverse training clips (different pools, different orientations, mixed resolution)
2. Explicitly include portrait-format and native-resolution frames in training
3. Include NEGATIVE examples (spectators labeled as "not diver") to teach discrimination

---

## 17. RESOURCE COST (Phase U)

| Configuration | Frames | Wall time | fps | Peak RAM | Device |
|---|---|---|---|---|---|
| D0 COCO R0 1080p (imgsz=1920) | 322 | 66.6 s | 4.84 | +340 MB (total 1.1 GB) | MPS (M-series) |
| D0 COCO R1 360p (imgsz=640) | 322 | 9.4 s | 34.3 | ~200 MB | MPS |
| D1 L1 R0 1080p | 322 | 62.0 s | 5.19 | ~1.1 GB | MPS |
| ByteTrack R0 1080p | 322 | 67.7 s | 4.76 | ~1.1 GB | MPS |
| Representation R0 encode | 322 frames | ~0.3 s | — | — | CPU |
| Representation R1 encode | 322 frames | ~0.1 s | — | — | CPU |

**Inference speed observation**: Native 1080p at imgsz=1920 runs at ~5 fps on M-series Mac. For a 5.37 s clip at 60 fps, total inference wall time = 66.6 s = 12.4× real-time. This is acceptable for offline analysis. Online/streaming is not a requirement.

**360p vs 1080p compute cost**: 7× faster at 360p (34.3 vs 4.84 fps). But 360p gives 4.3% recall vs 100%.

---

## 18. LIMITATIONS

1. **Single clip**: All conclusions from 1 dive (5.37 s, one session, one pool). No generalization claimed.
2. **No human temporal reference**: CC3 evaluation is approximate/qualitative only.
3. **No intermediate resolution tested**: 720p vs 1080p not yet measured.
4. **L1 complete failure**: Cannot evaluate domain adaptation effect at native resolution (it's zero by both measures).
5. **Diver selection unsolved**: Even with 100% recall, the right-person-selection problem is unresolved.
6. **VFR clip**: 322 decoded frames vs 344 in streams; PTS table accounts for this.
7. **HDR source**: 10-bit BT.2020 HLG decoded to 8-bit for inference; color truncation may affect some models.

---

## 19. NEXT DATA REQUIREMENT (Phase Q)

**Recommendation**: `6_HIGHRES_DIVES`

Rationale:
- We need ≥6 clips at native resolution (or ≥720p) to validate:
  1. Diver selection rule robustness across clips
  2. Resolution threshold (720p vs 1080p)
  3. Whether COCO or a retrained model is better at native resolution
- Do NOT request hundreds of clips yet — 6 clips would triple the current native-resolution evidence base
- Include at minimum: 2 different pools/venues, 2 different dive types, both portrait and landscape orientations

**Annotation priority**: Each clip needs only temporal landmarks (takeoff/apex/water) — not dense spatial annotation.

---

## 20. PERCEPTION ARCHITECTURE RECOMMENDATION (Phase R)

`DOMAIN_DETECTOR_PLUS_SCENE_PRIORS`

Reasoning:
1. At native 1080p, generic COCO detects all people (100% recall). A domain-adapted detector would improve precision but is not strictly necessary for recall.
2. The missing ingredient is **diver selection** — distinguishing the diver from 5–8 other detected people.
3. Scene priors (platform position, dive corridor, water line) would immediately resolve this.
4. ByteTrack alone is insufficient (54.7% coverage, loses the diver during fast flight).
5. Scene-seeded ByteTrack (initialize with known platform position) would likely maintain identity through the full dive arc.

**Concrete recommendation**:
1. Platform detector or manual initialization per clip (1-time setup)
2. D0 COCO or a retrained detector for per-frame people detection
3. Scene ROI + trajectory filtering to select the diver
4. ByteTrack seeded from the platform region for temporal continuity

---

## 21. POSE DECISION (Phase S)

`POSE_STILL_PREMATURE`

The diver selection problem is not yet solved. Pose estimation requires:
1. Reliable single-person bounding box (not yet achieved)
2. The detected person being the diver (not a spectator)

Both prerequisites remain unmet. Pose is not actionable until diver selection is solved.

---

## 22. ANNOTATION REQUEST (Phase D — Human Task)

**ONE TASK ONLY** for Maxime:

For video `IMG_1937.mov` (dive 2819, 5122D G/G), please watch the clip and record:

```
takeoff_seconds: <time in seconds when feet leave the platform>
apex_seconds: <time in seconds when diver is at highest point>
water_contact_seconds: <time in seconds when diver first touches water>
```

This is all that is needed. Open the file in QuickTime Player; use the scrubber to find each moment. No bounding boxes needed. This will complete the CC3 evaluation for Phase L.

---

## 23. SUMMARY OF SCIENTIFIC FINDINGS

| Question | Answer |
|---|---|
| Q1: Does 1080p improve localization vs 360p? | YES — dramatically. 100% vs 4.3% recall (generic COCO). |
| Q2: Does domain-adapted L1 outperform COCO at native resolution? | NO — L1 has 0% recall (complete OOD failure). |
| Q3: Is ByteTrack necessary for per-frame detections? | NOT YET DETERMINED — neither H0 nor H1 solves the diver selection problem. |
| Q4: Does ByteTrack improve continuity? | MARGINAL — 54.7% coverage vs 100% noisy coverage; no reliability advantage. |
| Q5: Can landmark detection work? | BLOCKED — diver selection must be solved first. |
| Q6: Which stage is now limiting? | DIVER SELECTION among multiple detected people. |

---

## 24. RECOMMENDED NEXT SUPERVISOR GATE

`SUPERVISOR_REVIEW_AFTER_HIGHRES_PERCEPTION_CANARY_V1`
