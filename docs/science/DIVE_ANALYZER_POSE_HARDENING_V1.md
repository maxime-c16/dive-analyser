# Dive Analyzer pose hardening V1 — temporal/anatomical stabilization on trusted clean tracks

**Cycle date:** 2026-09-28
**Canonical branch:** `uiux-overhaul-pro-app`
**Canonical base:** `76427df3141c76a6314fcdf717cbd25e1b0554b8`
**Gate:** `POSE_HARDENING_V1` (stabilization + phase gating; no biomechanics, no scoring, no coaching).
**Prior authority preserved:** `docs/science/DIVE_ANALYZER_CLEAN_TRACK_POSE_FEASIBILITY.md` (HEAD `76427df`) is untouched and remains the feasibility baseline. True-merge continuity at `ca5bab9`, FAX7/FAX8 sealed HUMAN authorities, S3/FSR/FAT histories, identity/ReID, Media Backbone, B2, Event Logic, and protected authorities (Paris, INTERNAL_EVAL, FINAL_HOLDOUT, 524, 2555) were not mutated or used as DEVELOPMENT evidence. No B2 mutation. Event Logic not tuned. Pose never used to repair tracking or infer identity.

## Data / track authority (DEVELOPMENT only, read-only)

Same six HUMAN-validated clean same-person dives as feasibility (FAX7 digest `b71b950e…`, FAX8 digest `a31d5bcf…`):

- Primary: 47/s15 201C 1m, 952/s58 201C 1m, 1257/s79 301C 1m (small-distant), 2120/s129 101C 1m.
- Supplemental rotation/scale probes: 1849/s107 403B 3m (large slow tuck), 2134/s130 103B 1m (inversion artifact that caused the FAX8 false mixed-edge flag; pose probe only).

HUMAN takeoff/apex/water_contact events + `flight_fraction` (PREP, 0/8–8/8, POST) are context only for phase labels. Consumed science clips for feasibility development only; no population claim. Input identity assumed solved; ambiguous intervals are LOST/UNUSABLE, never forced.

Media: `fresh_prep_authority/proxies/*.mp4` (202×360) vs `fresh_prep_authority/raw/*.mov` (HQ; 720p–1080p). Proxy SHA verified (e.g. 47 `059ab226…` matches FAX7 queue manifest). HUMAN boxes are `proxy_pixels_native_360p`; association uses normalized center distance in each resolution's own frame, so no aspect assumption. Raw mapping by PTS (`raw_idx = round(pts_s * fps_raw)`); equal-N dives map 1:1.

## Method (bounded, host-only dev)

Primary `yolov8n-pose.pt` (SHA `c6fa93dd…`), full-frame imgsz 640 conf 0.25 IoU 0.45. `yolov8m-pose.pt` (SHA `dbe539ea…`) only as bounded capacity spot check on sampled flight. No diving fine-tune.

1. **Track-conditioned selection (HUMAN-anchored).** Per dense frame (takeoff−0.3 s to water+0.4 s), reference = linearly interpolated HUMAN center at frame PTS (between sparse HUMAN boxes; edge-held outside). Select nearest pose box within 0.06 (sampled recall) / 0.15 (dense). This corrects a Stage-B chaining variant that latched onto a stable distractor on 2120 proxy (86% tracked, jitter 0.012) and restores the true 30% rate. Chaining without HUMAN anchoring is UNSAFE and is rejected.
2. **Whole-body L/R Viterbi.** Two states per tracked frame (as-is vs all 6 limb pairs + eyes/ears swapped). Pairwise cost = torso-normalized mean limb displacement over mutually valid (`conf>0.3`) keypoints; flip penalty λ=0.3 torso units; neutral cost 0.5 when <3 common valid points. Globally optimal path; reports swaps applied.
3. **Bone/topology gate → UNUSABLE, never smoothed.** Medians over stabilized tracked frames per dive/res. Reject if: <4 limb kpts valid; torso <0.3×median; shoulder/hip width <0.3×median; frame-to-frame limb jitter >1.0 torso. Second pass: shoulder image-order sign change between consecutive VALID frames with jitter >0.25 → later frame `FLIP_UNRESOLVED` UNUSABLE.
4. **Smoothing with uncertainty + short-gap interpolation only.** 3-frame median per limb keypoint on VALID runs only. Interpolation counted (not materialized for metrics) only for gaps ≤5 frames (≈0.08 s) with both endpoints VALID; longer gaps stay UNUSABLE. No smoothing across LOST/UNUSABLE or phase boundaries.
5. **Phase labels from HUMAN events only.** PREP (t<tk−0.15); TAKEOFF (|t−tk|≤0.15 or f<0.10); EARLY (0.10≤f<0.35); ROTATION/TUCK/PIKE (0.35≤f<0.75); EXTENSION (0.75≤f<0.95); ENTRY (0.95≤f≤1.05); POST (f>1.05), f=(t−tk)/(wc−tk).

## Sampled recall reproduction (117 visible HUMAN frames; matches feasibility exactly)

| Dive | PREP proxy/HQ | FLIGHT proxy/HQ | POST visible |
|---|---|---|---|
| 47 | 19/19, 19/19 | 3/9 0.33, 6/9 0.67 | 0/1, 0/1 |
| 952 | 11/13, 13/13 | 2/9 0.22, 7/9 0.78 | 0/1, 0/1 |
| 1257 | 0/11, 7/11 0.64 | 0/9, 1/9 0.11 | 0/1, 0/1 |
| 2120 | 5/6, 6/6 | 1/9 0.11, 6/9 0.67 | 0/1, 0/1 |
| 1849 | 4/4, 4/4 | 8/9 0.89, 9/9 1.00 | 0/1, 1/1 |
| 2134 | 2/4, 3/4 | 0/9, 0/9 | 0/1, 0/1 |

POST `not_visible` (splash) excluded from denominator; entry remains ~0.

## Dense anchored results (takeoff−0.3 s to water+0.4 s)

Tracked = HUMAN-anchored ≤0.15; VALID = tracked minus bone/flip/jitter UNUSABLE.

| Dive | Proxy tracked→VALID | HQ tracked→VALID | TorsoCV p/HQ | Comp p/HQ |
|---|---|---|---|---|
| 47 (61/62f) | 20/61 33% → 16/61 | 35/62 56% → 24/62 | 0.171 / 0.300 | 1.00 / 0.99 |
| 952 (107/106f) | 21/107 20% → 20/107 | 74/106 70% → 51/106 | 0.103 / 0.352 | 0.97 / 0.99 |
| 1257 (64/64f) | 0/64 0% → 0 | 18/64 28% → 14/64 | nan / 0.341 | 0.00 / 0.96 |
| 2120 (114/111f) | 34/114 30% → 29/114 | 74/111 67% → 56/111 | 0.203 / 0.278 | 1.00 / 1.00 |
| 1849 (112/113f) | 74/112 66% → 62/112 | 96/113 85% → 86/113 | 0.115 / 0.125 | 0.99 / 0.99 |
| 2134 (110/111f) | 5/110 5% → 4/110 | 10/111 9% → 10/111 | 0.026 / 0.110 | 1.00 / 0.98 |

HQ improves continuity everywhere except inversion (2134 stays 5→9%): +23 pts (47), +50 pts (952), +28 pts (1257 from zero), +37 pts (2120), +19 pts (1849). But HQ rescues harder poses: flips and torsoCV rise (see below). HQ helps recall/continuity, not geometry.

## Before/after L/R flip rate (shoulder image-order sign change, tracked pairs → VALID pairs)

| Dive | Proxy before → after (VALID) | HQ before → after (VALID) | Viterbi whole-body swaps applied |
|---|---|---|---|
| 47 | 2/16 → **0/9** | 10/30 → **0/13** | p 0, HQ 7 |
| 952 | 1/13 → **0/12** | 24/64 → **0/35** | 0, 0 |
| 1257 | — → — | 5/12 → **0/8** | 0 |
| 2120 | 4/25 → **0/18** | 29/69 → **0/40** | p 15, HQ 41 |
| 1849 | 11/60 → **0/39** | 16/95 → **0/78** | p 41, HQ 0 |
| 2134 | 3/4 → 0/2 | 1/8 → 0/8 | 0, 0 |

100% elimination of residual flips **within VALID** on all dives/resolutions, at the cost of marking flip-unresolved + collapse frames UNUSABLE (proxy 0–5, HQ 1–10 per window; e.g. 952 HQ: 4 shoulder-collapse, 6 flip-unresolved, 5 hip-collapse, 4 torso-collapse, 4 jitter-spike of 74 tracked). Whole-body Viterbi alone resolves almost nothing on 47/952/1257/2134 (0 swaps; costflip 0) — flips are **per-joint misassignments**, not global side swaps. 2120 HQ (41 swaps) and 1849 proxy (41) show whole-body ambiguity exists in pike/tuck but still leaves 29/16 raw flips requiring bone-gated rejection. Temporal hardening works as a **detector of wrong skeletons (→UNUSABLE)**, not as a fixer.

## Before/after jitter/stability (torso-normalized mean limb displacement per frame)

VALID-only contiguous pairs, before → after 3-frame median (UNUSABLE excluded, not smoothed):

- 47: p 0.266→0.135 (−49%), HQ 0.287→0.220 (−23%)
- 952: p 0.141→0.086 (−39%), HQ 0.178→0.116 (−35%)
- 1257: HQ 0.265→0.153 (−42%); proxy undefined (0 tracked)
- 2120: p 0.136→0.075 (−45%), HQ 0.162→0.092 (−43%)
- 1849: p 0.167→0.078 (−53%), HQ 0.162→0.134 (−17%)
- 2134: p 0.133→0.000 (2 pairs), HQ 0.168→0.098 (−42%)

Smoothing cuts VALID jitter 17–53% but absolute remains 0.075–0.220 torso/frame; max spikes 0.38–3.73 are excluded as UNUSABLE, not smoothed. Dense torsoCV stays 0.10–0.35 (HQ worse on 47/952/1257 where hard frames are rescued). Shoulder/hip width CV 0.46–0.67 on HQ flight. No resolution yields derivative-safe stability outside gated subsets.

## Phase-specific pose validity (HQ VALID/total; non-1849 aggregate + 1849 exception)

Non-1849 HQ (47/952/1257/2120/2134): PREP 37/40 **0.93**; TAKEOFF 35/71 0.49; EARLY 21/61 0.34; ROTATION 29/113 0.26; EXTENSION 19/55 0.35; ENTRY 10/29 0.34; POST 4/85 **0.05**.
1849 HQ slow-tuck exception: PREP 9/10, TAKEOFF 17/18, EARLY 14/15, ROTATION 22/27, EXTENSION 14/14, ENTRY 7/7, POST 3/22.

Per-dive HQ phase VALID shows the same pattern: ROTATION valid only on 2120 (20/28 pike but jitter-gated) and 1849 (22/27); 2134 flight 0/94 across all flight phases both resolutions; 1257 EARLY+ROTATION 0/26 HQ; 47 ENTRY 0/4 HQ; POST ~0 everywhere except splash-hit 1849 1/1 sampled. **Phase gate: PREP/standing = VALID-candidate; upright TAKEOFF = conditional; EARLY/ROTATION/EXTENSION/ENTRY = default UNUSABLE except 1849-like slow-tuck-hold; POST = do not run pose.**

## HQ findings (quantified, not assumed)

HQ materially improves recall and continuity (sampled flight +11–67 pts ex. 2134; dense +19–50 pts ex. 2134) and is **required** for small-distant PREP (1257 0→64%) and flight continuity (952 20→70%, 2120 30→67%). But HQ **degrades geometry metrics** because rescued frames are harder: torsoCV 47 0.17→0.30, 952 0.10→0.35, 1257 nan→0.34; flips 47 2→10, 952 1→24, 2120 4→29; jitter 47 0.27→0.29, 952 0.14→0.18. **HQ is necessary but not sufficient; proxy-only flight pose remains non-viable; any future pose layer is HQ-gated for small persons and phase-gated for flight.**

## Capacity + rotation probes (bounded, sampled flight HQ, 9 frames/dive)

- m-pose vs n-pose: 47 4/9 vs 6/9 (m worse); 952 7/9 vs 7/9; 1257 6/9 vs 1/9 (m helps tiny); 2120 9/9 vs 6/9 (m helps pike recall); 1849 9/9 vs 9/9; 2134 1/9 vs 0/9 (both ~blind). Capacity shifts recall ±, never fixes inversion/geometry. Confirms feasibility: larger COCO model is not the blocker.
- Test-time rotation augmentation (90/180/270, loose 0.20 back-projected gate, upper-bound probe): rescues 47 2/3 misses, 1257 3/8, 2120 2/3, 952 0/2, 1849 n/a, **2134 0/9**. Supports COCO upright bias as a contributor but rotation alone does not rescue inversion/compact-fold. Justifies a rotation-robust/diving-specific model rather than test-time rotation.

## Geometry readiness (gate: LR-stable + comp>0.95 + torsoCV<0.15 + valid/tracked>0.80 + VALID jitter<0.10)

Global gate passes only on survivor subsets (952 proxy 20/107 valid; 2134 HQ 10/111 all PREP) or the tuck exception (1849 proxy 62/112 all-pass; 1849 HQ fails jitter 0.134). Combined with phase VALID fractions (ROTATION 0.26 non-1849) and jitter 0.075–0.220, **no full-action body geometry can be derived. Gate geometry to PREP/standing only. The sole conditional candidate is slow-tuck-hold sub-intervals on large persons (1849-like: torsoCV 0.115–0.125, comp 0.99, flips 0 in VALID, 81–100% phase VALID) — still above the derivative threshold on HQ (0.134) and therefore NOT promoted; requires fine-tune + stricter sub-gating before any angle/velocity use.** Head/face excluded (prior 10–86% asymmetric occlusion, unchanged). Do not derive torso/hip/shoulder angles or velocities yet.

## Is fine-tuning now justified?

**Yes — bounded diving-specific pose fine-tune (or rotation-robust pose replacement) is now the justified next model step**, because: (a) generic COCO is systematically blind in rotation/inversion/compact-pike/small-flight/entry across 6 session-disjoint dives and both resolutions (2134 0/9 both res; 1257 flight 0.00 proxy/0.11 HQ; ENTRY/POST ~0); (b) capacity (m) does not fix it; (c) temporal hardening already extracts the maximum defensible signal (flips 0 in VALID, jitter −17–53%) and the residual is a perception gap (LOST 30–95% of flight outside 1849), not a smoothing gap; (d) rotation augmentation partially rescues but leaves inversion at 0. Scope: HQ flight frames of rotation/inversion/pike/small-person cases only; freeze tracking/identity/Event Logic; phase/HQ gates stay; LOST stays LOST.

## Minimal HUMAN ask (only if fine-tune proceeds; not requested now)

≤20 hard flight frames across 47/2120/2134 with explicit anatomical L/R labels (shoulders/hips/elbows/wrists/knees/ankles), targeting the ambiguity hardening cannot resolve: whole-body swap vs per-joint misassignment in rotation/inversion. No broad pose labeling. Purpose is to measure swap-vs-ambiguity and to supply fine-tune eval only, after gates are frozen.

## Actual remaining blocker

**Perception blindness in rotation/inversion/compact-fold/small-flight/entry (COCO upright + scale bias), not temporal consistency.** Hardening converts wrong skeletons to UNUSABLE and stabilizes PREP/tuck-hold, but cannot create detections where the detector is blind (2134 flight 91–95% LOST both res; 1257 proxy 100% LOST). The next step is a bounded diving-specific pose model/fine-tune under frozen phase/HQ gates, not more smoothing, not Event Logic, not tracking repair.

## Artifact identities

| Artifact | Identity |
|---|---|
| Canonical branch/base | `uiux-overhaul-pro-app` / `76427df3141c76a6314fcdf717cbd25e1b0554b8` (this commit identifies HEAD) |
| Prior feasibility (preserved) | `docs/science/DIVE_ANALYZER_CLEAN_TRACK_POSE_FEASIBILITY.md` at `76427df` |
| FAX7 HUMAN | `docs/science/localization_annotations_v1/FULL_ACTION_GT_HUMAN_FAX7_FRESH/MANIFEST.json` digest `b71b950e…` |
| FAX8 HUMAN | `docs/science/localization_annotations_v1/FULL_ACTION_GT_HUMAN_FAX8_FRESH/MANIFEST.json` digest `a31d5bcf…` |
| Pose weights | `yolov8n-pose.pt` `c6fa93dd…`; `yolov8m-pose.pt` `dbe539ea…` (verified locally) |
| Hardening code (host-only dev) | `run_hardening_v1.py` `2a489802…`; `stageA_recall.py` `2525f55f…`; `stageB_dense.py` `81cf61ec…`; `stageC_anchored.py` `23568fad…`; `stageD_rot_m.py` `577b8211…` |
| Results (host-only) | `stageA_recall.json` `5f816c79…`; `stageC_summary.json` `07e4f96a…`; `stageD_rot_m.json` `2533740e…` |
| Media | local `fresh_prep_authority/proxies/*.mp4` + `raw/*.mov` (47 proxy SHA `059ab226…` matches queue manifest) |

SUPERVISOR_REVIEW_AFTER_POSE_HARDENING_V1
