# HUMAN-grounded pose V1 — anatomical authority and frozen baseline

**Date:** 2026-09-28  
**Base:** canonical `uiux-overhaul-pro-app` at `c3bd9643e092b00b2d668193978776d8663cb6aa`  
**Scope:** DEVELOPMENT-only pose. Tracking, identity/ReID, Event Logic, Media Backbone, B2, protected data, general overlay, and biomechanics unchanged. Prior feasibility, Hardening V1, and crop-successor results remain intact. Geometry gate unchanged.

## Frozen HUMAN authority

The accepted 16-frame queue was frozen in Git before annotation (`pose_human_v1_queue.json`, SHA-256 `89e2b9141da4840d4d2f2639a55425227231f2917ea267ca3787ee371ab823ac`). Frames are decoded raw/HQ, with no model skeleton overlay. Dive/session coverage: 2134/s130 inversion (4); 1257/s79 small flight (4); 2120/s129 compact pike (3); 47/s15 horizontal rotation and entry (3); 952/s58 horizontal rotation (2). Head/face excluded. The interface required an explicit state and anatomical side for left/right shoulder, elbow, wrist, hip, knee, and ankle. Maxime completed all 16: 113 visible points and 79 occluded, zero marked not visible. At Maxime's request, all six left/right joint pairs were swapped on the three 47 frames before freeze, preserving coordinates and states. Original draft backed up host-only. The single-annotator labels have no inter-rater uncertainty estimate.

Authority was sealed *before* model inference at commit `f5fc59c290d3f8b2eb59aa3adbc6e4b4947ffb52`; `pose_human_v1_authority.json` SHA-256 `96abeae0fb89a108b64c6f0e68434b580f5aed813cfd2d780cebea1325b55549`; authority manifest SHA-256 `090787ebe1aa0ec628179e67e40102a8519151d22f628dfebe680d256da42afd`. Source raw image and crop hashes are in the frozen queue. No pseudo-label was used as GT.

## Frozen crop-conditioned baseline

Frozen `yolov8n-pose.pt` SHA-256 `c6fa93dd1ee4a2c18c900a45c1d864a1c6f7aba75d84f91648a30b7fb641d212`; raw HQ input; same sealed HUMAN track box scaled from proxy to HQ, expanded 30%, square ×1.15; `imgsz=640`, conf 0.25, IoU 0.45; nearest pose box within normalized center distance 0.15. The 16-frame evaluation is sampled and **pre-Hardening** for direct anatomical localization; it does not alter Hardening V1 or its dense temporal results. A keypoint with YOLO confidence <0.5 counts as missing. Every normalized error divides by a HUMAN shoulder-to-hip torso length on the same frame (all 113 visible-joint rows have a HUMAN torso scale). PCK denominator includes missing visible joints. `opposite_side_closer` is a conservative side-error signal: the predicted counterpart is at least 0.1 torso lengths nearer to a HUMAN point than the predicted same-side point; it is not an exhaustive side-accuracy certificate.

| Condition | Frames | HUMAN visible joints | Predicted ≥0.5 | PCK@0.2 torso (all visible) | Opposite side closer (predicted) | Median error (predicted, torso) |
|---|---:|---:|---:|---:|---:|---:|
| Inversion, 2134 | 4 | 30 | 11 | 5/30 | 2/11 | 0.66 |
| Small flight, 1257 | 4 | 25 | 19 | 12/25 | 3/19 | 0.16 |
| Compact pike, 2120 | 3 | 20 | 20 | 14/20 | 4/20 | 0.12 |
| Horizontal rotation/entry, 47 | 3 | 25 | 4 | 1/25 | 0/4 | 0.46 |
| Horizontal rotation, 952 | 2 | 13 | 13 | 3/13 | 8/13 | 0.55 |
| **Total** | **16** | **113** | **67** | **35/113 (31%)** | **17/67 (25%)** | **0.182** |

Track-matched detection: 13/16 frames; zero detections/track matches on 2134 f247/f280 and 47 f324. Detection recall alone is misleading: 1257 f177 had a matched detection but 0/6 visible joints above 0.5. Overall 46/113 visible joints are missing, including 23 on the three unmatched frames. Among 67 predicted joints, 32 exceed 0.2 torso lengths, 20 exceed 0.5, and 8 exceed 1.0. Fifteen of the 32 inaccurate joints have an opposite-side-closer signal; 17 are inaccurate without that signal. PCK@0.5 over all visible is 47/113 (42%). Median error conditional on having a predicted joint hides the large missing-joint rate; p90 conditional error is 1.07 torso lengths.

**Dominant failure:** missing usable joints (46/113), followed by localization and anatomical side errors of similar size among emitted joints (17 and 15 above 0.2 torso, respectively). Failure depends on phase: 47 rotation/entry is primarily joint disappearance, 952 horizontal rotation is primarily left/right assignment (8/13 opposite-side-closer), 2134 inversion mixes missed frames and localization, while 2120 pike has better coverage but 4/20 side errors. Eight >1-torso errors are catastrophic geometry. The sparse, occluded frames do not separate foreshortening ambiguity cleanly from detector topology errors; no causal claim is made there.

## Successor decision and geometry gate

**Bounded successor selected: HUMAN calibration/evaluation authority first; supervised weight adaptation deferred.** The sealed set is 16 deliberately difficult frames from five sessions, with only 5 frames on the prior TRAIN sessions (47/s15 and 952/s58). A train/validation/final split would leave fewer than a dozen train examples, no independent hard-phase coverage, and too little session-disjoint evidence to distinguish learned improvement from memorization. Training YOLO on these 16 or tuning a side-correction rule against their final labels would contaminate the only genuine anatomical test. The prior three pseudo-label fine-tunes degraded VAL and remain negative evidence. Therefore **whether small supervised adaptation materially improves anatomy is unresolved, not a positive result**; no model weights are promoted, no baseline-vs-supervised score is invented.

Minimum justified next labeling tranche: approximately **60–80 additional HUMAN frames**, sampled as contiguous short temporal groups over at least three TRAIN sessions and one VAL session, with upright/easy anchors and hard inversion, rotation, pike/tuck, small flight, and entry. Keep 1257/s79 and 2134/s130 sealed as final evaluation; do not train or tune on them. Obtain further clean DEVELOPMENT dives/sessions as needed for training diversity. Freeze the queue and labels before inference, use the same raw/HQ joint interface and explicit occlusion states, then run one conservative YOLO supervised adaptation with rotation augmentation and frozen crop/Hardening V1 comparisons. A >10 percentage-point absolute PCK@0.2 gain on session-disjoint VAL with no detection or phase VALID regression is a practical go/no-go threshold, followed by sealed final evaluation; anatomical side, catastrophic errors, jitter, and scale must improve separately. This count is an engineering minimum for a pilot, not a sample-size guarantee of production reliability.

**Geometry readiness: no flight phase.** On HUMAN points, overall PCK@0.2 is 31%, side errors and catastrophic errors persist, and entry/inversion coverage is poor. Existing unchanged dense Hardening V1 measurements show HQ crop jitter 0.085–0.252 torso/frame and torso CV 0.161–0.426 (plus 2134 CV 0.257), with no flight phase passing the strict prior gate (LR-stable, completeness >0.95, torso CV <0.15, valid/tracked >0.80, VALID jitter <0.10). Those dense jitter/CV numbers are prior model-only stability measures, not newly HUMAN-grounded temporal estimates; the 16 separated hard frames cannot establish temporal jitter. PREP/standing remains the prior conditional geometry scope; this study has no PREP HUMAN joints and does not extend that claim. No biomechanics begins.

## Artifacts and limits

- Frozen queue: `docs/science/pose_human_v1_queue.json`, SHA-256 above.
- Frozen HUMAN labels and manifest: `docs/science/pose_human_v1_authority.json`, `docs/science/pose_human_v1_authority_manifest.json`, SHAs above.
- Reproducible baseline evaluator: `experiments/pose_human_v1/evaluate.py`; frozen results: `docs/science/pose_human_v1_baseline_eval.json`, SHA-256 `68779d570f9110b9c5872747add429589509d3e810c42efe11d59d5d39ccfc4d`.
- All five dives are development-only and session-disjoint. This is a selected hard-frame audit, not a population accuracy estimate. Single annotator, no repeatability study. Crop uses sealed HUMAN track boxes, so the result measures pose conditional on trusted identity, not autonomous tracking. Model-side no-retrain verdict applies only to this frozen baseline and cannot exclude a later supervised successor.

SUPERVISOR_REVIEW_AFTER_HUMAN_GROUNDED_POSE_V1
