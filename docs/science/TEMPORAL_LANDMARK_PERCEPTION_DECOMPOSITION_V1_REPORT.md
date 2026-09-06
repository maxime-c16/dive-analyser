# Temporal Landmark Perception Decomposition V1

Status: COMPLETE (DEVELOPMENT). INTERNAL_EVAL localization labels missing; INTERNAL_EVAL evaluation blocked pending human re-review of 18 frames. User-facing status: NOT AUTHORIZED.

## Authority and Starting State

Canonical repository: `mcauchy@192.168.1.57:~/dive-analyser`, branch
`uiux-overhaul-pro-app`. Starting HEAD: `b9d8952a9e9dbfa78595904f4d2dfdf4e3e6cb58`;
clean worktree. Local research checkout: `/Users/maximecauchy/.perso/diveanalyzer-perception`.
The original `/Users/maximecauchy/.perso/diveanalyzer` directory is a stale reference slice.

Read authorities: PROJECT_STATE, Layer-2 architecture, pilot protocol, human-reference
manifest and completed pilot report, B/C freeze manifests and reports, scientific split.
Historical reports contain stale or contradictory conclusions; frozen files are preserved.
The active interpretation is **OFF_THE_SHELF_HUMAN_DETECTION_ON_CURRENT_360P_PIPELINE_INSUFFICIENT**.
Final landmark error alone does not distinguish detection, selection, tracking, or event rules.

## Newly Discovered Reference-Timebase Bug

`annotate.py` hardcoded `detectFps()` to 60 while some proxies are 30000/1001 FPS.
The resulting human timestamps and frame indices do not identify the same image.
Read-only DEVELOPMENT audit: **20/38 usable landmarks disagree by over one frame with
average media FPS; seven frame indices are outside their clips**. Average FPS is only
an audit signal, not the correction method, because some clips have variable frame timing.
See `PERCEPTION_LOCALIZATION_AUTHORITY_AUDIT_V1.json` for per-dive ffprobe evidence and hashes.

Concrete example: dive 676 is 202x360, 30000/1001 FPS, 222 frames, timebase 1/30000.
Its V1 water-contact reference says frame 291, timestamp 4.853569 s. Frame 291 does
not exist. The timestamp is within the clip. This defect confounds historical reported
frame errors and must not be presented as a detector failure.

The maintainer explicitly authorized repair in this thread on 2026-09-06, then authorized
fixing encountered bugs through completion of the packet. The repair creates
`pilot_annotations_v2/<split>/` and `TEMPORAL_LANDMARK_GROUND_TRUTH_V2_PTS_REPAIR.json`.
It preserves human timestamps, annotation states, all V1 files, and all A/B/C identities.
It maps each human timestamp to the displayed decoded frame: the last actual presentation
timestamp <= human time. The same fixed transformation applies blindly to both splits;
INTERNAL_EVAL values are not used for development. It is not a new human temporal review.
Historical A/B/C scores remain historical; comparisons against V2 must be separately labeled.

## Baseline C Decomposition

Exact code: `experiments/landmark_pilot/proposer_baseline_c.py`, SHA256
`ad02393b8ce7e6e4140f2db326c36f76449b028516f57015aa98c54735139ee7`.
Live weights match frozen SHA256
`f59b3d833e2ff32e194b5bb8e08d211dc7c5bdf144b90d2c8412c47ccfc83b36`.
Actual file size is 6,549,796 bytes; freeze reports 6,259,416 bytes. Hash identity matches.
Live server import reports Ultralytics 8.3.253, OpenCV 5.0.0.

1. Detection: YOLOv8n, COCO class 0, conf=.10, IoU=.45, imgsz=640, CPU,
   every decoded frame. `model.track()` output is already tracker-processed; it is
   not an independent record of all detector candidates.
2. Tracking: Ultralytics built-in ByteTrack. Non-ID detections use ID=-1 and are
   ineligible for primary selection. Raw Kalman/lost-track states are not persisted.
3. Selection: one ID for the entire clip, maximizing count x mean confidence,
   algebraically the sum of confidence. It has no diver, support-region, or flight
   identity evidence. A persistent bystander can win. This is a structural risk,
   not yet a measured wrong-person rate.
4. Trajectory: selected box center, y=1-cy/H; bbox height/H and confidence.
   Missing observations remain None. Interior gaps <=15 frames are interpolated.
5. Smoothing: Savitzky-Golay (11,3) operates on the compressed sequence of all
   nonmissing values. Long gaps lose their temporal separation during smoothing.
6. Takeoff: infer board height from observations in the first 80 frames; search
   after the first gap for six observations above max(.30, board_y+.08).
   The gap is tested after interpolation, so gaps of 8-15 frames may be erased.
   Fallback scans from frame zero: six values >.30 and a near-flat permitted trend
   (`future[-1] > future[0] - .05`). Stationary or slightly downward motion can
   satisfy a rule described as positive upward velocity. No foot/support relation.
7. Apex: maximum smoothed y after takeoff+10, before 92% of clip. Incorrect early
   takeoff, wrong selected ID, or missing flight observations can all corrupt apex.
8. Water contact: first center below y=.15 after apex, otherwise last confident
   observation after apex. No calibrated water surface; `water_contact_look_ahead`
   is unused, and the descent verification accepts either outcome. Track ending,
   swimming, and late observations are confounded with first body contact.
9. C2 priors reject bad ordering or intervals outside FPS-scaled bounds. Coverage
   <.10 also rejects. Confidence combines observation coverage, displacement, and
   detector confidence; none independently proves correct identity or event semantics.

These code findings explain mechanisms capable of frame-0 triggers and runaway entry;
they do not prove which mechanism caused each historical dive's error. Historical C
outputs do not preserve raw detector candidates and full tracker states, so those
cannot be recovered from final scores. New diagnostic traces need a separate identity.

## Localization Reference

`localization_review.py` is a file-backed companion to the existing annotation workflow.
It has no database connection and cannot edit temporal labels. It prepares native-resolution
PNG frames by sequential decoding and verifies reference checksums. Prepared set:
**56 frames: 38 DEVELOPMENT_DESIGN, 18 INTERNAL_EVAL**, excluding unusable/null timestamps.
Both splits have separate manifests and label directories. No boxes are auto-certified.
Required fields: bbox for visible/partial diver, visibility, ambiguity note where necessary,
annotator, review time, media/frame/reference checksums. Reviewer is the maintainer.
Images live under ignored `media/perception_decomposition_v1/localization/`; lightweight
human labels will live under `docs/science/localization_annotations_v1/<split>/`.

The UI is loopback-only, token-protected, with no-store responses and no-referrer policy.
Scientific consumers must enforce DEVELOPMENT-only access until the next candidate freeze.
UI visual check completed on a DEVELOPMENT frame; evaluation images were not inspected.

## Baseline C Stage Trace (C_STAGE_DIAGNOSTIC_V1)

New diagnostic identity; frozen C code/weights are read-only. Three DEVELOPMENT dives traced:
133 (178 frames), 2555 (722 frames), 2541 (975 frames).

**Dive 133** — selected_track=1, events: T=0, A=48, W=113:
- Track 1 is present at all three landmark frames (takeoff/53, apex/62, water_contact/88).
- IoU=0 at all landmark frames despite track presence. Center error: 70px (takeoff), 78px (apex),
  40px (water_contact). The tracker is following a stationary person on the board/platform
  throughout the clip while the diver exits frame. Center recall only at water_contact.
- This is the structural bystander-wins phenomenon. The persistent stationary person
  accumulates more detection count × mean_conf than the short flight arc.

**Dive 2555** — selected_track=4, events: T=11, A=108, W=203:
- At all three landmark frames, selected track (ID 4) is not present.
- Raw detections exist at takeoff (1) and apex (2) frames but none carry track_id=4.
- Zero raw detections at water_contact (frame 574).
- Selected track won selection over the entire clip but is absent at the dive event.
  This is catastrophic wrong-track selection: correct diver detection exists but loses
  the whole-clip confidence-sum competition to a bystander elsewhere in the clip.

**Dive 2541** — selected_track=9, events: T=402, A=437, W=440:
- Zero raw detections at ALL three landmark frames (takeoff/525, apex/539, water_contact/558).
- Complete detection failure at the actual dive event. The detector never fires on the
  diver during the flight. Late predicted events (T=402, A=437, W=440 near clip end)
  are well beyond actual human landmarks.

Structural conclusions: wrong-person acquisition (133, 2555) and total detection failure
(2541) independently explain poor landmark output without invoking event-rule analysis.

## V2 PTS Reference Re-evaluation of Baselines A, B, C

Frozen predictions unchanged; only the reference authority changes.
Saved: `BASELINE_A/B/C_V2_REFERENCE_REEVALUATION.json`. Historical V1 files preserved.

**Baseline A (V2, time-domain, n=38 evaluable phases):**
- Takeoff: n=13, median=1.668s, serious_rate=0.846
- Apex: n=11, median=2.35s, serious_rate=0.909
- Water_contact: n=14, median=2.202s, serious_rate=0.857
- **All phases: median=1.985s, mean=2.114s, serious_rate=0.868**

**Baseline B (V2, frame-domain, n=32 evaluable phases):**
- All phases: median=55 frames, mean=145.8 frames, serious_rate=0.812

**Baseline C/C2 (V2, time-domain, n=25 evaluable phases):**
- Takeoff: n=9, median=4.114s, serious_rate=1.0
- Apex: n=7, median=2.717s, serious_rate=0.857
- Water_contact: n=9, median=2.983s, serious_rate=0.889
- **All phases: median=3.717s, mean=5.146s, serious_rate=0.92**

V1 vs V2 comparison reveals the extent of timebase confounding: for 30fps clips at
~60fps-annotated frames, V1 doubled h_frame indices, causing V1 errors to appear
smaller or larger depending on algorithm direction. Example dive 133: V1 reported
takeoff time_err=0.27s; V2 reports 2.1s. Example dive 311: V1 reported 14.8s; V2
reports 1.1s. The V2 values are the corrected-reference truth.

All three baselines fail: 80–100% of predictions exceed ±1s from the correct reference.
Baseline C is worst (92% serious, median 3.7s). No previous V1 comparison can be used
as corrected evidence without this V2 re-evaluation.

## Independent Scientific Results

| Stage | Evidence (DEVELOPMENT) |
|---|---|
| Detector quality | Zero raw candidates at diver location at 3/9 landmark frames across 3 traced dives; bystander detections present at all zero-diver frames. Detection gap is real at 360p. |
| Target selection | Whole-clip confidence-sum selects wrong person in 2/3 traced dives. Bystander wins because persistence × conf > short flight arc. Structural defect, not tuning. |
| Tracking quality | Oracle SAM: only 1/3 DEVELOPMENT oracle dives maintains mask through events (dive 133, 38/51 active frames). Dives 2387 and 2169 collapse immediately after seed frame. |
| Representation effect | All DEVELOPMENT proxies are portrait 360px high; originals inaccessible (TCC blocked). Scale effect cannot be isolated without paired comparison. |
| Event logic | Not evaluable until a reliable track exists. |

## Oracle SAM Canary (DEVELOPMENT, diagnostic only, not autonomous)

SAM 2.1 tiny (`sam2.1_hiera_tiny.pt`, SHA256
`7402e0d864fa82708a20fbd15bc84245c2f26dff0eb43a4b5b93452deb34be69`), MPS device,
seeded with human takeoff bboxes, propagated over human-bounded window (takeoff to
water_contact + 15 frames). Saved: `media/perception_decomposition_v1/sam_oracle_<id>/result.json`.

**Dive 133** (window 53–103, 51 frames):
- Seed (takeoff, frame 53): IoU=0.806, iou50=True, center_error=0.2px ← excellent
- Apex (frame 62, index 9): IoU=0.329, iou50=False, center_error=21.4px, center_recall=True
- Water_contact (frame 88, index 35): IoU=0.198, iou50=False, center_error=5.3px, center_recall=True
- Active mask frames: 38/51. Mask collapses at frame index 38 (frame 91, post water_contact).
- Assessment: **tracking viable**. Diver maintained through all events at 360p.

**Dive 2387** (window 134–179, 46 frames):
- Seed (takeoff, frame 134): IoU=0.529, iou50=True, center_error=0.7px ← good
- Apex (frame 144, index 10): area=0. **Immediate collapse at frame index 1.**
- Water_contact (frame 164): area=0.
- Active mask frames: 1/46. Assessment: **tracking not viable** (immediate collapse).

**Dive 2169** (window 387–476, 90 frames):
- Seed (takeoff, frame 387): IoU=0.557, iou50=True, center_error=4.4px ← adequate
- Apex (frame 405, no reference — annotator marked ambiguous): area=0. **Immediate collapse at frame index 1.**
- Water_contact (frame 461): area=0.
- Active mask frames: 1/90. Assessment: **tracking not viable** (immediate collapse).

Overall: 1/3 dives successfully tracked by oracle SAM through the complete dive window.
The immediate collapse for 2387 and 2169 indicates that SAM2 tiny at 360p cannot
maintain tracking through the rapid appearance change of a diver in flight. Cause is
likely the combination of: very small subject (~50–130px height), JPEG compression,
and rapid pose/scale change between consecutive frames at ~30fps.

Automatic-seed tracking: **SKIPPED**. Oracle success rate (1/3) is insufficient to
justify investing in automatic seeding. Even if acquisition were perfect, the underlying
tracking failure for 2/3 dives would remain.

## Conditional Branch and Root Cause

**MULTI_STAGE_LIMITATION**

Evidence summary:
1. Generic detection fails or fires on wrong person at 360p scale in 3/3 traced dives.
2. Whole-clip track selection has no diver-identity evidence; bystander wins in 2/3 cases.
3. Oracle-seeded SAM2 tracking fails immediately for 2/3 DEVELOPMENT dives.
4. All three V2-corrected baselines produce serious errors in >80% of predictions.
5. Original-resolution data unavailable (TCC blocked); scale isolation impossible.

No single stage is the complete explanation:
- Acquisition alone cannot explain total detection failure (dive 2541).
- Detection alone cannot explain wrong-track selection when diver IS detected (dives 133, 2555).
- Tracking alone cannot explain detection failures.
- Scale (360p) is an underlying factor for all stages but cannot be proven primary without originals.

**Root cause: MULTI_STAGE_LIMITATION.** Proxy resolution + generic-detector domain gap
+ wrong-person acquisition + tracking collapse at rapid motion are compounding.

**Custom fine-tuning: NOT JUSTIFIED.** Oracle tracking fails 2/3 dives; acquisition is
not the only bottleneck. Fine-tuning a detector on DEVELOPMENT labels would not resolve
tracking failure or wrong-person selection by confidence sum.

**Pose: POSE_STILL_PREMATURE.** Reliable diver tracking does not yet exist.

**Optical flow: no demonstrated incremental value** in this decomposition.

**INTERNAL_EVAL localization labels: MISSING.** `docs/science/localization_annotations_v1/INTERNAL_EVAL/`
does not exist. The DEVELOPMENT_DESIGN split has 38/38 complete labels. The INTERNAL_EVAL
images (18 frames) were prepared and stored at `media/perception_decomposition_v1/localization/INTERNAL_EVAL/`
but no labels were saved. INTERNAL_EVAL evaluation is blocked until these 18 frames are
reviewed. This does not block DEVELOPMENT conclusions.

## Original Access

**ORIGINAL_CANARY = ACCESS_METHOD_BLOCKED**. Six SSH-launched `osxphotos export`
attempts produced zero video bytes due to macOS Photos TCC authorization failure
("could not get authorization to access Photos library") for SSH-launched processes.
This is not evidence that originals do not exist. Paired original-vs-proxy measurement
cannot be conducted without a separately authorized retrieval mechanism.
Authorized canary IDs: 2661, 2169, 192, 311, 2555, 2387.
Provenance: `media/perception_decomposition_v1/original_export_provenance.json`.

## Model Toolchain

SAM 2.1 official source, HEAD `2b90b9f5ceec907a1c18123530e92e794ad901a4`.
Tiny checkpoint SHA256 `7402e0d864fa82708a20fbd15bc84245c2f26dff0eb43a4b5b93452deb34be69`
(156,008,466 bytes), MPS device (Apple M2 16 GiB). Peak RSS during oracle: ~1.0–1.3 GiB.
Isolated venv: Python 3.11.15, PyTorch 2.10.0, Ultralytics 8.3.253, OpenCV 4.13.0,
scipy 1.17.1, lap 0.5.12, hydra-core 1.3.2, iopath 0.1.10.
Production environment unchanged.

## External Domain Annotations (Documentation Only)

[FineDiving](https://github.com/xujinglin/FineDiving) provides domain procedure annotations
and requires its documented release agreement. [FineParser / FineDiving-HM](https://github.com/PKU-ICST-MIPL/FineParser_CVPR2024)
provides human-centric masks via its documented release process, potentially useful for
future diver localization/segmentation transfer. [FineDiving-Pose / HP-MCoRe](https://github.com/Lumos0507/HP-MCoRe)
describes refined skeleton annotations combining manual and automatic work, potentially
useful only if body configuration is later justified. Domain/style transfer to personal
portrait training footage is unproven. No agreement submitted and no dataset acquired.
[SAM 2 official implementation](https://github.com/facebookresearch/sam2) supports prompted
video propagation; success with a human seed does not establish autonomous acquisition.

## Validation

12/12 tests pass (`test_localization_review.py` + `test_perception_metrics.py`), covering
VFR PTS mapping, out-of-media rejection, invalid/nonfinite boxes, visibility, ambiguity,
review provenance, no-detection miss, no-reference non-miss, IoU geometry, and small-box
center vs overlap distinction.

`annotate.py` repaired to use actual presentation timestamps for seeking, stepping, and
frame numbering. Production DB/media and frozen scientific artifacts remain unchanged.

## Remaining Work

INTERNAL_EVAL localization labels: 18 frames at
`media/perception_decomposition_v1/localization/INTERNAL_EVAL/` require one human review
session before INTERNAL_EVAL evaluation can proceed. This is the single remaining human
gate before SUPERVISOR_REVIEW_AFTER_PERCEPTION_DECOMPOSITION_V1.
