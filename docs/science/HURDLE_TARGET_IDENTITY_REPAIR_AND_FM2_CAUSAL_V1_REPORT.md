# HURDLE Target Identity Repair and FM2 Causal Report — V1

Task packet: `HURDLE_TARGET_IDENTITY_REPAIR` (supervisor packet, 2026-09-09)
Thread: identity-repair worktree `~/.perso/diveanalyzer-hurdle-identity-repair`,
detached at Event Logic HEAD `a551319ac5e1ac90b3744072769fabc60f49e7f2`, with the
HQ-representation thread HEAD `4b192dc` fetched read-only. No HQ-thread artifact
was modified; media/manifest authority untouched. All detector runs used the
frozen `DIVER_DETECTOR_D5_A_V8N_best.pt`
(sha256 `82b420c4…dcf25`, conf floor 0.001, op 0.05, NMS 0.45, imgsz 640, MPS).
GT (human boxes + phase times) was used only to define eval intervals and GT
identity — never as inference input.

---

## 1. Question

FM2 (HURDLE final takeoff detection failure) has been attributed to "D5 target
instability at 360p" — target switching/oscillation corrupting board level and
departure detection. B1r repaired the *level* but not the scan validity; the
V3-E freeze gate returned `MORE_HURDLE_GT_REQUIRED`. This packet asked: is the
perception root cause a detector failure (target not in the raw proposals) or a
selection failure (target present but outranked)? And can a per-frame
appearance-aware global-path selector (R4) repair the identity without
retraining the frozen detector?

## 2. Instrument (Phase A)

- `experiments/landmark_pilot/phase_hurdle_raw_candidate_audit.py`: frozen D5-A
  at the diagnostic floor on the 7 HURDLE GT dives, eval interval
  `[max(0, takeoff−8s), wc+1s]`, ALL candidates (floor, cap 200) cached to
  `runs/hurdle_identity_v1/HURDLE_RAW_CANDIDATES_AUDIT_V1.json` (host artifact).
- `docs/science/HURDLE_TARGET_ANCHORS_V1.json`: 35 anchors — HUMAN_GT boxes at
  the 20 annotated frames (2169 takeoff fi377–392 + wc fi449–466, 2341 takeoff
  fi204–226, 2353 apex fi368–380, 2555 apex fi374–392) plus operator-verified
  VISUAL_EVALUATOR anchors (1040 prep/flight incl. three zoom-verified tail
  anchors; 2541; 2353 prep). Identity traps recorded (2341 next-diver-on-board;
  2353 persistent bystander at (0.13,0.45); 2555 screen recording, W=166).
  Annotation frame indices map to proxy PTS at fi/60 (validated on all four
  GT dives).
- `phase_hurdle_target_chain_v1.py`: per-frame GT chains — interpolation between
  anchors, candidate snapping under continuity constraints, GT-direct at
  annotated frames, AMBIGUOUS_GT where identity cannot be established, WATER
  post-wc. Validation: chain-vs-human-box IoU = 1.000 at every GT frame with an
  exact frame match (2169 8/8, 2341 4/4, 2555 4/4; 2353 3/4 with the fourth at
  IoU 0.38 / cdist 0.05).
- `phase_hurdle_identity_classify_v1.py`: A2/A3 classification, matching
  project-canonical (IoU ≥ 0.30 OR center-dist ≤ 0.05; 0.07 for chains seated
  purely on eyeball centers).

## 3. Phase A result — the failure is selection, not detection

| dive | n evaluable | avail@floor | avail@op | top-1 correct | longest wrong run | median target rank |
|---|---|---|---|---|---|---|
| 1040 | 161 | 1.000 | 0.217 | 0.106 | 122 | 31 |
| 2169 | 434 | 1.000 | 0.977 | 0.963 | 11 | 0 |
| 2341 | 273 | 1.000 | 0.476 | 0.022 | 260 | 11 |
| 2353 | 411 | 1.000 | 0.073 | 0.005 | 363 | 34 |
| 2541 | 262 | 1.000 | 0.221 | 0.149 | 173 | 24 |
| 2555 | 336 | 1.000 | 0.729 | 0.518 | 33 | 0 |
| 524 | 0 | — | — | UNRESOLVED | — | — |

Three structural facts:

1. **The detector ceiling hypothesis is refuted.** The target is in the raw
   floor candidate set on 100% of evaluable frames on every classified dive —
   including 1040, whose earlier "raw candidates insufficient" hypothesis came
   from inspecting only the top-ranked proposals.
2. **D5 conf is anti-informative for the target.** The distractors are STATIC
   background objects that the detector fires on strongly: 2341's top-1 is a
   structure box at (0.64, 0.11) with conf 0.403, constant for the entire video,
   while the true diver sits at conf 0.003–0.05 during prep; 1040's stable top-1
   during prep is the structure box at (0.249, 0.221) (conf 0.13–0.14) and during
   flight the static pool object at (0.27, 0.60) takes over (conf up to 0.56 at
   water entry). This is not oscillation — it is continuous wrong-object
   dominance (wrong runs of 260–363 frames on 2341/2353).
3. **2169 is the counterexample** (top-1 correct 96.3%): where the target is a
   clear platform diver, conf-based selection already works, and the FM2
   takeoff failure there is a temporal/velocity artifact, not identity loss.

## 3. R4 appearance-aware global path (Phase B) — FAIL

`R4_APPEARANCE_AWARE_GLOBAL_PATH` was implemented per packet spec
(`phase_hurdle_r4_identity_repair_v1.py`, `phase_hurdle_r4_tracks_v2.py`):

- frozen ResNet50 (IMAGENET1K_V1) avgpool 2048-d features, L2-normalized, on
  1.3×-padded candidate crops;
- Viterbi global path over frames × (top-12 floor candidates + NULL state);
- E3 sequence prior: continuity cost on center displacement + appearance
  cosine + switch penalty, transitions bounded to STEP_MAX_PATH = 0.10
  (V3-E0 lesson honored: no unbounded scan);
- E4 static-prep protection: ×2 motion cost during prep + NULL hysteresis;
- track peeling (K=8 disjoint tracks) and dive-event track picking (peak
  smoothed-cy downward displacement over 0.4–1.5 s windows).

**Verdict: FAIL.** Two measured reasons:

- **The appearance features cannot discriminate.** Per-frame ResNet50 cosine:
  target-track self-similarity 0.70–1.00 vs target-vs-distractor cross 0.60–1.00
  (worst on 2353: cross 0.899–1.000 ≈ self 0.893–0.990). At proxy resolution the
  diver's crop is too small/blurry for ImageNet features to separate person from
  background structure; the selector cannot even *seed* on the target.
- **The conf prior pulls away from the target.** Because the distractors hold
  TOP conf (0.403 on 2341), any conf-weighted emission favors the wrong object;
  setting w_conf → 0 leaves appearance+motion continuity, which both the target
  and a static distractor satisfy equally well.

Best-of-192-configuration mean top-1 = **0.213** (1040 0.00, 2169 0.912, 2341
0.00, 2353 0.00, 2541 0.153) versus the D5 conf-only baseline mean **0.249**.
R4 preserves the dive that already works (2169) and repairs none. Full verdict
and diagnostics: `docs/science/HURDLE_R4_APPEARANCE_REPAIR_RESULT_V1.json`.

## 4. FM2 reclassification and V3-D0 replay (Phase K)

`docs/science/HURDLE_FM2_RECLASSIFICATION_V1.json`:

- **FM2 root cause corrected**: systematic per-frame SELECTION failure — the
  op-point top-1 continuously rides static background distractors that outrank
  the true diver — not target instability/oscillation, and not detector
  insufficiency (the target is always in the floor proposals).
- **Causal chain for FM2**: board level and departure detection consume the
  per-frame selection. On 4/6 classified dives (1040, 2341, 2353, 2541) that
  selection is predominantly the wrong object. The frozen
  `DEV_HURDLE_TRAJ_CACHE_V2` 1040 trajectory (cy = 0.221, conf 0.13) *is* the
  structure distractor — FM2's input trajectory is the wrong object. Repairing
  the *level* (B1r) or widening the *scan* cannot fix a trajectory whose
  identity is wrong at the majority of frames; this explains why V3-E0's
  unbounded scan turned 1040's repair into a late false-positive and why the
  V3-E freeze gate failed.
- **V3-D0 replay** (`runs/hurdle_identity_v1/v3d0_replay_v1.json`): replaying
  the frozen `proposer_event_logic_v3_d0.py` on the frozen cache reproduces
  1040 (|to_err| 1.9947 s, |wc_err| 2.511 s) and 2169 (0.4123 s / 0.2872 s)
  exactly (the freeze records absolute magnitudes; the replay computes
  detected − GT). The 5 remaining HURDLE dives (2341, 2353, 2541, 2555, 524)
  had no prior V3-D0 numbers and now do.

## 5. 524 and the HQ comparison

- 524 has no usable GT anchors (proxy strips ambiguous). The packet required
  self-validating the HQ thread's 524 hflip mapping
  (`runs/hq_rep_v1/scale_match_524_hflip.json`, claimed proxy = crop
  (93,8,384×683) of the 1.25×-scaled hflipped HQ) before using HQ 524 boxes.
  **Self-validation FAILED**: exhaustive template search over scale 0.4–2.0 ×
  hflip on/off × temporal offset ±1.0 s caps at NCC 0.32–0.46 (spec ~0.74), and
  the rendered mapping windows show content mismatch (roof band vs full proxy
  view). HQ 524 boxes were therefore NOT used. The HQ thread's media/manifest
  authority and representation decision (`proxy_360p`, 4b192dc) were left
  untouched.
- The HQ read-only comparison stands as fetched from 4b192dc: 720p/HQ does not
  auto-repair top-1 (1040 unstable at 720p, 2169 loses the anchored target
  24–27% in the takeoff window, 676 diver present at HQ IoU 0.63–0.72 but
  outranked) — consistent with this packet's finding that the failure lives in
  per-frame selection, not in the sensor representation.

## 6. What would actually repair FM2 (outside this packet's authority)

1. **Person-trained embedding** for candidate identity (retrain-class work —
   `NO_RETRAIN_AUTHORIZED` on D5; a separate small re-id head could be frozen
   alongside without touching D5 weights). ImageNet ResNet50 is measured
   insufficient (§3).
2. **Geometry-anchored selection**: the diver is the candidate ON the board
   during prep and the one that FALLS INTO the water; but the frozen board-level
   candidates are themselves contaminated by the same distractors (Phase A),
   so this needs the corrected board geometry first.
3. GT-anchored seeding is explicitly forbidden as inference input and was not
   used; it is listed only to bound the search space.

## 7. Commits and tests

- Worktree commits (this thread, on top of `a551319`):
  - `682b634` Phase A: raw-candidate audit + GT anchors/chains + A2/A3
    classification (8 files).
  - `438b7e0` R4 implementation + FAIL verdict + FM2 reclassification +
    V3-D0 replay (5 files).
- Server integration: both commits cherry-picked onto `4b192dc` (HQ-representation
  HEAD, fetched read-only) in the server-side worktree
  `~/dive-analyser-worktrees/hurdle-identity-repair`, then the report commit;
  pushed to `uiux-overhaul-pro-app` as the Git authority.
- `docs/PROJECT_STATE.md` updated with the packet section and the new gate.

## 8. Gate

`SUPERVISOR_REVIEW_AFTER_HURDLE_IDENTITY_REPAIR_V1`
