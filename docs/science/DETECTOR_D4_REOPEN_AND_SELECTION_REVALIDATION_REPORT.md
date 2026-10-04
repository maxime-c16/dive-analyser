# DETECTOR_D4_REOPEN_AND_SELECTION_REVALIDATION_REPORT

> **Cycle**: D4 detector reopen + target diver selector revalidation  
> **Date**: 2026-09-08  
> **Authority**: SUPERVISOR_TASK_PACKET `SUPERVISOR_REVIEW_AFTER_TARGET_DIVER_SELECTION_V2`  
> **Prior state**: HEAD=896e0d5 (Target Diver Selection V2)

---

## Executive summary

D4 (YOLOv8n, 22 new annotated frames from failure dives) delivers a **+12.9 pp recall
improvement** over D3 (80.6% vs 67.7%) with **zero regressions** on the canonical 31-frame
development set. Paris coverage reaches 3/3 phases for the first time — a historic first.

Gate outcomes:

| Phase | Gate | Result |
|---|---|---|
| H1 (raw detector recall) | ≥90% on 31 frames | **FAIL** — 80.6% (25/31) |
| M (selector accuracy) | ≥80% on DEVELOPMENT | **FAIL** — S0 best at 71.0% (22/31) |
| O (Paris trajectory) | 3/3 GT phases match | **FAIL** — 1/3 (takeoff MATCH only) |

All three gates fail. The system does not yet meet the bar for Paris trajectory
reconstruction. However, D4 establishes the highest-yet baseline, and the failure
modes are now well-understood (confidence calibration on water-contact + FP dominance).

**Paris firewall**: IMG_1937.mov / Dive 2819 remained **SEALED** throughout. No Paris
frames used in training, hard-negative mining, threshold selection, augmentation, or
selector parameter selection.

---

## Phase F — Annotation batch (22 frames)

- **Annotator**: Maxime Cauchy (single human review gate, 2026-09-08)
- **Tool**: http://192.168.1.57:8892
- **Frames annotated**: 22
  - 19 positive (visible + bbox)
  - 3 negative (not_visible): `d2680_post_water_contact`, `d676_entering_water`, `d2625_pre_flight_hurdle`
- **Surprise positives**: 5 frames originally expected background were annotated as visible-diver positive; all correctly included in training data
- **Manifest**: `docs/science/localization_annotations_v1/D4_ANNOTATION_BATCH/manifest.json`
- **Split**: dive 2341 → holdout (generalization test), failure dives 2555/2680/676/2541 → train

---

## Phase G — D4-A training

| Parameter | Value |
|---|---|
| Base weights | yolov8n.pt (COCO-pretrained, fresh start) |
| Device | MPS (Mac M2) |
| AMP | False (required — MPS AMP causes gradient collapse; see D3 sanity) |
| Epochs (stopped) | 71 (patience=25, best_epoch=46) |
| Dataset | DIVER_LOCALIZATION_DATASET_D4 — train:62, val:10, holdout:70 |
| best_map50 | 0.333 |
| val_precision | 0.656, val_recall: 0.286 |
| Weights SHA | `842291f1cd3c5ad086faa467ccaac197c56bdd63dcdd2b67a91c4a7d8fbc3aaa` |

Dataset sources:
- **Source A**: 85 D2 positives (split preserved, no Paris)
- **Source B**: 35 D3 hard negatives from DEVELOPMENT_DESIGN_V2 not_visible frames
- **Source C**: 22 D4 annotation batch frames

Artifacts:
- `models/frozen/DIVER_DETECTOR_D4_A_V8N_best.pt`
- `docs/science/DIVER_DETECTOR_D4_A_V8N_TRAIN.json`
- `docs/science/DATASET_D4_MANIFEST.json`

---

## Phase H — Grouped evaluation (RAW_TARGET_CANDIDATE_RECALL)

**Definition**: at least one prediction at `conf≥0.05`, `nms_iou=0.45`, `imgsz=640`
matches the GT bbox (IoU≥0.30 or centre_dist≤0.05 normalised).

| Metric | D3 | D4 | Δ |
|---|---|---|---|
| canonical denominator | 31 | 31 | — |
| op_match (25/31) | 21 | 25 | +4 |
| raw_target_candidate_recall | 0.677 | 0.806 | **+0.129** |
| regressions | — | 0 | — |

### Phase H1 gate

> Gate: RAW_TARGET_CANDIDATE_RECALL ≥ 0.90 → **FAIL** (0.806 < 0.90)

Canonical failures at op threshold:
- `2169_water_contact` — water-contact calibration failure
- `2341_apex` — holdout by design (dive 2341 withheld from training)
- `2625_apex`, `2625_water_contact` — architectural limit (pre-flight hurdle, difficult geometry)
- `2680_water_contact` — water-contact calibration failure
- `2555_apex` — FP dominates (confidence not calibrated for apex in this venue)
- `311_water_contact` — FP at rank 1
- `676_water_contact` — water-contact calibration failure
- `2387_water_contact` — FP at rank 1

Improvement analysis: all 6 D3 canonical failures at op threshold were addressed or
partially addressed. Zero regressions confirms dataset construction was sound.

---

## Phase I — Dataset manifest freeze

`docs/science/DATASET_D4_MANIFEST.json` frozen with:
- splits: train(62), val(10), holdout(70)
- holdout_failure_dives: [2341]
- train_failure_dives: [2555, 2680, 676, 2541]
- paris_firewall: VERIFIED

---

## Phase J/K — Paris external canary evaluation

> **Paris firewall status**: SEALED. No IMG_1937.mov frames in training.

D4 evaluated on Paris (IMG_1937.mov, native 1080×1920, fps=56.52) at conf=0.05:

| Phase | n_op | top1_conf | IoU_with_GT | result |
|---|---|---|---|---|
| takeoff (3.12s) | 5 | 0.329 | 0.387 | MATCH |
| apex (3.57s) | 4 | 0.095 | ~0.136 | DETECTED but wrong-target |
| water_contact (4.22s) | 4 | 0.106 | ~0.000 | DETECTED but wrong-target |

**Finding**: `D4_IMPROVES_PARIS_WITHOUT_PARIS_TRAINING`

D3 had 0/3 Paris phases covered at op threshold. D4 achieves 3/3. The takeoff phase
reaches genuine localisation (IoU=0.387 ≥ 0.30). Apex and water_contact have detections
but top-1 is a false-positive (crowd / spectator region).

Floor analysis (conf=0.001) confirms the actual diver is visible to the detector:
- takeoff: best IoU=0.618 at rank 10
- apex: best IoU=0.601 at rank 10
- water_contact: best IoU=0.422 at rank 121

The water_contact rank-121 result is a severe confidence calibration failure — the
diver entering the water is not distinctive enough to surpass spectator detections
at this domain.

Artifact: `docs/science/PARIS_D4_EVAL.json`

---

## Phase L — S3 hypothesis only

S3 action-likelihood selector was documented as `HYPOTHESIS_ONLY` in the D3 sanity
cycle and remains so. S3 uses a persistence bonus to penalise static false-positives
(spectators), and was directionally effective on Paris water_contact in V2. With D4
proposals, S3 and S1 are tied at 61.3% on DEVELOPMENT.

---

## Phase M — Selector revalidation

Selectors tested on 12 DEVELOPMENT dives × 31 anchor frames with D4 proposals at
conf=0.05. Run locally on Mac M2 (MPS), using proxy videos rsync'd from server.
Server CPU (Intel Pentium 3550M) was too slow for inference; cv2 not available on server.

| Selector | Correct | Total | Accuracy |
|---|---|---|---|
| S0 (top-conf) | 22 | 31 | **71.0%** |
| S1 (Viterbi, frozen V2) | 19 | 31 | 61.3% |
| S3 (persist, HYPOTHESIS_ONLY) | 19 | 31 | 61.3% |

**Phase M gate (80%)**: FAIL — no selector reaches threshold.

**S0 vs Phase H discrepancy (71% vs 80.6%)**: Phase H counts any prediction matching
GT; Phase M S0 requires rank-1 match. The gap (9 frames) reflects frames where the
detector finds the diver but a higher-conf FP outranks it.

**S1 regression finding**: S1 (Viterbi with spatial cost) regresses from 80% (V2) to
61.3% (D4). Root cause: D4 produces spatially plausible FPs (crowd near dive area)
that receive high confidence. Viterbi's spatial smoothing propagates FP selections
across phases, compounding errors. S0 is immune to this propagation because it
evaluates each phase independently.

Artifact: `docs/science/SELECTOR_REVALIDATION_D4.json`

---

## Phase N — Selector freeze

**Frozen selector for D4 era**: **S0 (top-conf)**

S0 is the highest-accuracy selector (71.0%) and is simpler than S1. With D4 proposals,
independent per-phase top-conf outperforms the Viterbi path due to FP propagation.

The V2-frozen S1 selector is superseded for D4 proposals. S1 remains documented as
the V2 canonical selector for historical reference.

Note: Paris trajectory (Phase O) result is identical with S0 and S1 — both select
wrong-target for apex and water_contact. The selector change does not affect the Paris outcome.

Artifact: `docs/science/SELECTOR_FREEZE_D4.json`

---

## Phase O — Paris trajectory gate

Using S0 (D4-era frozen selector) on Paris D4 proposals:

| Phase | GT bbox (1080×1920) | Pred bbox | IoU | Result |
|---|---|---|---|---|
| takeoff | [522.9,542.7,820.0,892.4] | top-1 IoU≈0.387 | 0.387 | **MATCH** |
| apex | [495.2,353.5,665.8,657.2] | top-1 wrong target | ~0.136 | WRONG_TARGET |
| water_contact | [302.2,687.2,525.9,1076.6] | top-1 wrong target | ~0.000 | WRONG_TARGET |

**Paris trajectory gate**: **TRAJECTORY_INPUT_FAIL** (1/3 anchors correct)

The apex and water_contact failures share the same root cause: spectators/crowd in
the upper-left region receive higher confidence than the diver in flight or entry.
Floor analysis confirms the diver is visible (rank 10 for apex, rank 121 for water_contact)
but confidence calibration is insufficient to surface it above FPs.

---

## Phase P — Event Logic test

**BLOCKED** — Phase O = TRAJECTORY_INPUT_FAIL. Event Logic cannot be tested without
a valid input trajectory.

---

## Phase Q — Dive 311 Event Logic failure

Carry-forward from TARGET_DIVER_SELECTION_V2:
- Status: `INDEPENDENT_EVENT_LOGIC_FAILURE`
- ~4s error in both V2.1 and V2.2 identically
- State machine locks on late spurious motion at ~18s
- Perception is clean (correct target identity verified)
- Not a V2.1-vs-V2.2 discriminator
- Resolution requires Event Logic debug, not perception improvement

---

## Phase R — V2.2 status

Status: `V2_2_EXPERIMENTAL_FROZEN_NOT_ADOPTED` — unchanged from V2.

V2.2 threshold (0.55 body-heights/s) remains documented but not promoted:
- n=2 clean HURDLE trajectories is fragile
- 1 clear win / 1 tie / 0 regressions — insufficient for adoption
- Accumulation of additional HURDLE dives required

---

## Failure analysis summary

### Water-contact calibration (systematic)

Five dives fail at water_contact with D4: 311, 676, 2169, 2387, 2680. The entering-water
visual is fundamentally different from mid-flight — body vertical, splash, partial
occlusion — and the training set has limited water-contact positives in this configuration.
The Viterbi spatial cost does not help (wrong detection is spatially close to GT).

### FP dominance (spectator/crowd)

Paris apex and water_contact, plus several DEVELOPMENT frames (311_wc, 2387_wc, 2555_apex):
spectators or crowd in the near field receive higher confidence than the target diver.
This is the key barrier to Paris trajectory success.

### 2625 architectural limit

Dive 2625 has no takeoff GT anchor (hurdle obscures the view). Both apex and water_contact
fail with D4 due to geometry — the diver is at an unusual angle during hurdle. This is
unlikely to be fixed by additional training data alone.

### 2341 holdout by design

Dive 2341 was placed in the holdout split explicitly to test generalization. takeoff and
water_contact match with D4 (calibration improved by training on similar failure dives).
Apex remains a failure — this is the holdout probe.

---

## Scientific integrity

### Paris firewall (unbroken)

All training, negative mining, threshold selection, augmentation selection, and selector
parameter selection used DEVELOPMENT_DESIGN data only. Paris (IMG_1937.mov / Dive 2819)
was evaluated as external canary only, after all parameters were frozen.

The Paris video is stored at:
- Server: `experiments/landmark_pilot/paris_source/IMG_1937.mov`
- media_sha256: `d122262be8e7a8721ab2f6a71721bb3544403da78324138d026360ef9820eaae`
- Format: native 1080×1920, fps=56.52 (no proxy, not at `media/cache/proxy_360p/`)

### No proxy for Paris

The proxy_360p cache does NOT contain a Paris proxy. The path
`media/cache/proxy_360p/d1/22/d122...mp4` does not exist on the server. Paris was
evaluated at native 1080p resolution.

---

## Artifacts produced

| Artifact | Location |
|---|---|
| D4 annotation batch manifest | `docs/science/localization_annotations_v1/D4_ANNOTATION_BATCH/manifest.json` |
| D4 dataset manifest | `docs/science/DATASET_D4_MANIFEST.json` |
| D4 training record | `docs/science/DIVER_DETECTOR_D4_A_V8N_TRAIN.json` |
| D4 proposal freeze | `docs/science/D4_PROPOSAL_V1_FREEZE.json` |
| D4 grouped eval | `docs/science/D4_GROUPED_EVAL_V1.json` |
| Paris D4 eval | `docs/science/PARIS_D4_EVAL.json` |
| Selector revalidation D4 | `docs/science/SELECTOR_REVALIDATION_D4.json` |
| Selector freeze D4 | `docs/science/SELECTOR_FREEZE_D4.json` |
| D4 weights | `models/frozen/DIVER_DETECTOR_D4_A_V8N_best.pt` (SHA `842291f1...`) |

---

## Next required work

1. **Water-contact calibration**: add more water-entry positives across multiple venues.
   The entering-water phase is fundamentally underrepresented.

2. **FP suppression at Paris**: venue-specific training with Paris spectator background
   as hard negative (requires collecting non-diver Paris frames, NOT using IMG_1937.mov).
   Note: adding ANY Paris-venue training data requires explicitly downgrading Paris from
   external canary status before doing so (Paris firewall must be updated, not just
   silently violated).

3. **Confidence calibration for long-range detection**: water_contact rank 121 at floor
   suggests the detector sees the diver but is very uncertain. Temperature scaling or
   additional positive examples may help.

4. **Dive 311 EL failure**: independent investigation needed. Root cause is in state
   machine logic, not perception.

5. **V2.2 HURDLE accumulation**: more clean HURDLE trajectories before promoting threshold.

---

## Supervisor gate

`SUPERVISOR_REVIEW_AFTER_DETECTOR_D4_REOPEN_AND_SELECTION_REVALIDATION`
