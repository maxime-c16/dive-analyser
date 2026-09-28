# Dive Analyzer diving-specific pose successor V1 — track-conditioned HQ crop successor, bounded fine-tune negative

**Cycle date:** 2026-09-28
**Canonical branch:** `uiux-overhaul-pro-app`
**Canonical base:** `ba594670ed43e35e212f243715657198063e542c`
**Gate:** `DIVING_SPECIFIC_POSE_SUCCESSOR_V1` (pose perception, not smoothing; no biomechanics, no scoring, no coaching).
**Prior authorities preserved unchanged:** `docs/science/DIVE_ANALYZER_CLEAN_TRACK_POSE_FEASIBILITY.md` (HEAD `76427df`) and `docs/science/DIVE_ANALYZER_POSE_HARDENING_V1.md` (HEAD `ba59467`) remain the feasibility/hardening baselines. True-merge continuity at `ca5bab9`, FAX7/FAX8 sealed HUMAN authorities, S3/FSR/FAT histories, identity/ReID, Event Logic, Media Backbone, B2, and protected authorities (Paris, INTERNAL_EVAL, FINAL_HOLDOUT, 524, 2555) were not mutated or used as DEVELOPMENT evidence. No B2 mutation. Event Logic not tuned. Pose never used to repair tracking or infer identity. No general overlay promotion.

## Data / track authority (DEVELOPMENT only, read-only)

Same six HUMAN-validated clean same-person dives as feasibility/hardening (FAX7 digest `b71b950e…`, FAX8 digest `a31d5bcf…`):

- Primary: 47/s15 201C 1m, 952/s58 201C 1m, 1257/s79 301C 1m (small-distant), 2120/s129 101C 1m.
- Supplemental rotation/scale probes: 1849/s107 403B 3m (large slow tuck), 2134/s130 103B 1m (inversion artifact; pose probe only).

HUMAN takeoff/apex/water_contact + `flight_fraction` (PREP, 0/8–8/8, POST) are context only for phase labels. Consumed clips for development only; no population claim. Input identity assumed solved; ambiguous intervals LOST/UNUSABLE, never forced.

Media: `fresh_prep_authority/proxies/*.mp4` (202×360) vs `fresh_prep_authority/raw/*.mov` (HQ portrait; e.g. 47 720×1280, 952/2120/1257 1080×1920, 1849 816×1450, 2134 774×1376; decoded H×W matches meta W×H). Proxy SHA verified (47 `059ab226…` matches queue manifest). HUMAN boxes are `proxy_pixels_native_360p` xyxy (`[x1,y1,x2,y2]`, not xywh — verified by overlay: xyxy gives tight diver boxes, xywh gives huge boxes); association uses normalized center distance in each resolution's own frame.

## Dataset / split authority (dive/session-disjoint, no neighboring-frame leakage)

Whole dives assigned to one role; sessions distinct; no random frame split:

- TRAIN: 47/s15, 952/s58 (easy upright + rotation pseudo-label source only).
- VAL (model selection): 2120/s129 (pike), 1849/s107 (tuck).
- FINAL fresh eval (never touched during train/val selection): 1257/s79 (small-distant), 2134/s130 (inversion).

Protected excluded: Paris (2819), INTERNAL_EVAL sessions (26,51,138), FINAL_HOLDOUT (none exists), 524, 2555. All sessions (15,58,129,107,79,130) distinct and DEVELOPMENT-only.

## HUMAN pose labels used: 0

No HUMAN pose annotation requested or used this cycle. Pseudo-labels sufficient for bootstrapping test (see below); true anatomical L/R ground truth remains absent, so L/R error is measured via temporal shoulder-order flips in VALID (stability proxy), not anatomical correctness. Minimal targeted HUMAN queue prepared but NOT requested (see §Minimal HUMAN queue).

Pseudo-label inventory (frozen `yolov8n-pose.pt` full-frame 640 conf 0.25 IoU 0.45, HQ, dist≤0.06, limb≥6, unique frames): TRAIN 45 (47 PREP 19 + 6 easy flight 0/8,1/8,2/8,3/8,6/8,7/8; 952 PREP 13 + 7 easy flight 0/8,1/8,2/8,5/8,6/8,7/8,8/8). Hard HQ misses (dist>0.06 or 0-det) clean-6 total 30 (1257 12 = 4 PREP + 8 flight 0/8–7/8 small-flight; 2134 10 = 1 PREP + 9 flight 0/8–8/8 inversion, all 0-det; 2120 3 flight 0/8,2/8,3/8 pike; 47 3 flight 4/8,5/8 rotation + 8/8 entry; 952 2 flight 3/8,4/8 rotation; 1849 0). Flight hard 25 (2134 9, 1257 8, 2120 3, 47 3, 952 2). Avoided oversampling easy PREP for design; training used only TRAIN pseudo (45), never VAL/FINAL.

## Successor design (bounded; one strong path + small justified alternative)

Primary successor (PROMOTED for recall, not geometry): **frozen `yolov8n-pose` + HQ + track-conditioned square crops + frozen Hardening V1 gates, no retraining.** Per dense frame, HUMAN-interpolated box (linear between sparse HUMAN boxes, edge-held) scaled to decoded HQ (sx=Wd/202, sy=Hd/360), expanded 30% + square×1.15, clamped; run frozen n-pose on crop imgsz 640 conf 0.25 IoU 0.45; map box+kpts back to full-frame; HUMAN-anchored nearest within 0.15; then identical Hardening V1 (Viterbi λ=0.3, bone/topology→UNUSABLE, 3f median on VALID runs, phase labels from HUMAN events only). This is diving-specific via track-conditioning + HQ-gating + phase-gating, not via new weights. Higher effective resolution + distractor removal; same 640 imgsz, so gain is cropping/resolution, not weights.

Small justified alternative (TESTED, NEGATIVE): fine-tune n-pose baseline on TRAIN pseudo (45 HQ full-frames or 45 crops) with rotation-heavy augmentation. Variants: (a) crop-trained, degrees 180, flipud 0.5, lr 0.001, 80ep; (b) full-trained, same; (c) mild repair, freeze backbone 10 layers, degrees 90, flipud 0, lr 0.0005, 50ep. All use identical hardening for eval. No broad zoo; no m-pose retrain (capacity already ruled out); no new architecture (no evidence YOLO pose structurally inadequate beyond scale/upright bias, which cropping addresses for recall).

## Frozen baseline reproduction (fresh evidence, fixed evaluation layer)

Reimplementation of Hardening V1 gates (`hardening_v1.py`) reproduces canonical within 1 frame for coverage; Viterbi tie broken toward detector output (dp0,1=0.3) to avoid arbitrary global flips from float noise; second-pass flip-unresolved (jitter>0.25) leaves residual flips in VALID on some HQ (unlike canonical 0) but identical code is used for baseline vs successor, so comparison is fair (answers detector improvement, not post-processing permissiveness).

Sampled visible unique-frame recall (HQ, dist≤0.06) reproduces feasibility exactly: 47 6/9, 952 7/9, 1257 1/9, 2120 6/9, 1849 9/9, 2134 0/9; PREP HQ 100% except 1257 7/11 (small) and 2134 2/3. Proxy flight 3/9,2/9,0/9,1/9,8/9,0/9. m-pose not rerun (prior capacity result preserved).

Dense anchored (takeoff−0.3 to water+0.4, 0.15 gate) HQ baseline (fixed code): 47 35/62→25/62 torsoCV 0.306 jit 0.296→0.203; 952 74/106→51/106 CV 0.356 jit 0.178→0.119; 2120 74/111→56/111 CV 0.278 jit 0.161→0.092; 1257 18/64→15/64 CV 0.279 jit 0.265→0.154; 1849 96/113→87/113 CV 0.125 jit 0.164→0.134; 2134 10/111→9/111 CV 0.065 jit 0.167→0.094. Matches hardening V1 within 1 VALID (47 25 vs 24, 1257 15 vs 14, 1849 87 vs 86, 2134 9 vs 10).

## Frozen baseline vs successor (identical hardening, HQ main representation)

Successor = frozen weights + track-crops (no retraining). HQ dense:

| Dive | Base tracked→VALID | Succ tracked→VALID | ΔVALID | TorsoCV b→s | Jit_a b→s | Flips_valid b→s | Phase VALID gains (succ−base) |
|---|---|---|---|---|---|---|---|
| 47 | 35/62→25/62 | 48/62→30/62 | +5 | 0.306→0.426 (worse) | 0.203→0.252 (worse) | 0/14→0/16 (0 preserved) | PREP 5→5, TAKEOFF 6→9, EARLY 4→5, ROTATION 4→8 (+4), EXT 6→2 (−4), ENTRY 0→1 (rescued) |
| 952 | 74/106→51/106 | 97/106→78/106 | +27 | 0.356→0.346 (similar) | 0.119→0.120 (similar) | 10/35→5/60 (28%→8% better) | PREP 9→9, TAKEOFF 15→15, EARLY 10→13, ROTATION 5→24 (+19!), EXT 3→11 (+8), ENTRY 5→4 |
| 2120 | 74/111→56/111 | 100/111→78/111 | +22 | 0.278→0.335 (worse) | 0.092→0.149 (worse) | 11/40→2/69 (27%→3% better) | PREP 8→10, TAKEOFF 12→15, EARLY 7→9, ROTATION 20→27 (+7, 27/28=96%!), EXT 7→13 (+6), ENTRY 2→3 |
| 1257 | 18/64→15/64 | 64/64→49/64 | +34 | 0.279→0.267 (similar) | 0.154→0.200 (worse) | 3/8→1/39 (37%→2.5% better) | PREP 6→6, TAKEOFF 2→7, EARLY 0→9 (from 0!), ROTATION 1→12 (+11), EXT 3→4, ENTRY 3→1, POST 0→10 (phase-gated out) |
| 1849 | 96/113→87/113 | 98/113→88/113 | +1 | 0.125→0.161 (worse) | 0.134→0.116 (better) | 7/80→8/81 (similar) | PREP 9→8 (−1), TAKEOFF 17→17, EARLY 14→15, ROTATION 23→25, EXT 14→14, ENTRY 7→5 |
| 2134 | 10/111→9/111 | 38/111→28/111 | +19 | 0.065→0.257 (worse, harder frames rescued) | 0.094→0.085 (better) | 1/7→2/10 | PREP 8→8, TAKEOFF 1→5, EARLY 0→3 (from 0!), ROTATION 0→12 (from 0! inversion rescued) |

Proxy shows same pattern (e.g. 1257 proxy 0/64→22/64→18 VALID from 0; 2134 proxy 5/110→36/110→20 VALID). PREP HQ preserved (47 5→5, 952 9→9, 2120 8→10, 1257 6→6, 1849 9→8, 2134 8→8); 952 proxy PREP 10→6 drop noted (tight crops cut extended arms standing; HQ unaffected, HQ is authority for small persons).

Fine-tuned alternative (VAL full-frame, identical hardening): crop-trained 2120 proxy 5→5 (vs base 34→29), raw 43→36 (vs 74→56); 1849 proxy 22→19 (vs 74→62), raw 59→53 (vs 96→87). Full-trained 2120 proxy 20→18, raw 60→50; 1849 proxy 34→30, raw 70→56. Mild (freeze-10, deg 90) 2120 proxy 21→18, raw 70→52; 1849 proxy 52→44, raw 88→78. All worse than frozen baseline on VAL, both full-frame and crop inference (crop-inferred successors also worse than frozen-crop: e.g. 2120 raw crop base 100→78 vs crop-succ 96→70). Conclusion: pseudo-only fine-tuning on 45 easy frames causes catastrophic forgetting/overfit; rotation augmentation (even mild, frozen backbone) does not rescue hard flight and hurts easy tuck/pike. Negative result accepted.

## Phase-specific VALID coverage (HQ, successor)

Non-1849 HQ aggregate (47/952/1257/2120/2134): PREP 38/40 0.95 (preserved); TAKEOFF 53/71 0.75 (vs base 0.49); EARLY 40/61 0.66 (vs 0.34); ROTATION 83/113 0.73 (vs 0.26!); EXTENSION 43/55 0.78 (vs 0.35); ENTRY 12/29 0.41 (vs 0.34); POST 17/85 0.20 (phase-gated out, do-not-run). 1849 HQ: PREP 8/10, TAKEOFF 17/18, EARLY 15/15, ROTATION 25/27, EXTENSION 14/14, ENTRY 5/7, POST 4/22.

Do not hide failures: ENTRY still 0.41 non-1849 (47 1/4, 952 4/7, 2120 3/7, 1257 1/4, 2134 0/7 — 2134 entry still 0); POST is splash (do-not-run, crop rescues 10/11 on 1257 HQ but must stay UNUSABLE by phase gate); 2134 ENTRY 0/7 both; small-flight ENTRY 1/4; pike ENTRY 3/7. Catastrophic collapse rate (0-det frames in dense): base HQ 2134 101/111 LOST (91%), succ 73/111 LOST (66%) — improved but still majority LOST; 1257 base 46/64 LOST (72%), succ 0/64 LOST (0%! small-flight fully surfaced). Anatomical plausibility (bone-gated UNUSABLE): succ marks 13–23/dive HQ as collapse/flip/jitter UNUSABLE (e.g. 952 HQ 19 UNUSABLE of 97 tracked); L/R flip rate in VALID improves (see table) but per-joint misassignments remain (Viterbi swaps 0 everywhere in fixed code; flips are per-joint, not global, consistent with hardening).

## Geometry stability (gate: LR-stable + comp>0.95 + torsoCV<0.15 + valid/tracked>0.80 + VALID jitter<0.10)

Global HQ successor: 47 CV 0.426 fail, jit 0.252 fail; 952 CV 0.346 fail, jit 0.120 fail; 2120 CV 0.335 fail, jit 0.149 fail; 1257 CV 0.267 fail, jit 0.200 fail; 1849 CV 0.161 fail (just over 0.15), jit 0.116 fail (just over 0.10), valid/tracked 0.898 pass, comp 0.972 pass — closest but still fail; 2134 CV 0.257 fail, comp 0.849 fail. No flight phase passes strict gate. Phase-specific geometry not computed separately, but global already fails due to rescued hard frames (same HQ pattern as hardening: recall up, geometry down). Shoulder/hip width CV 0.46–0.67 on HQ flight (unchanged order). Head/face excluded (unchanged). No full-action body geometry can be derived; normalization by body scale remains unstable for derivatives. Sole conditional remains slow-tuck-hold sub-intervals on large persons (1849-like: CV 0.125–0.161, jit 0.116–0.134, 81–100% phase VALID) — still above derivative threshold on HQ, therefore NOT promoted; requires fine-tune + stricter sub-gating before any angle/velocity use. Do not derive torso/hip/shoulder angles or velocities.

## Resolution / crop / model attribution (Q4)

Gain is due to cropping/resolution (track-conditioned HQ crops, same frozen weights, same 640 imgsz), not model adaptation. Evidence: (a) frozen weights + crops improve VALID +19–34 pts on hard HQ (952 +27, 2120 +22, 1257 +34, 2134 +19) while preserving HQ PREP; (b) fine-tuned weights (all three variants) degrade VAL vs frozen baseline under identical hardening, both full-frame and crop inference (e.g. 2120 raw full base 74→56 vs mild 70→52 vs aggressive full 60→50 vs crop-trained 43→36); (c) higher input resolution not tested separately (640 kept constant), so gain is not imgsz; it is effective resolution via cropping (small diver upscaled, distractors removed) + HQ (necessary, proxy-only still non-viable: 1257 proxy crop 22→18 vs HQ 64→49). Model adaptation via 45 pseudo-labels is insufficient/harmful (catastrophic forgetting); true rotation/inversion/pike geometry needs more than rotation augmentation on easy pseudo.

## Remaining failure modes (would corrupt biomechanics)

1. Per-joint limb misassignment during fast rotation (skeletons collapsed despite detection match; Viterbi whole-body swaps 0 — flips are per-joint, not global).
2. Inversion blindness reduced but not fixed (2134 HQ recall 9→28 VALID, but torsoCV 0.257, comp 0.849 fail; ENTRY 0/7).
3. Compact pike collapse reduced (2120 ROTATION 20→27/28) but torso foreshortening CV 0.335 invalidates scale normalization.
4. Small-person spectator hijack risk on proxy (1257 proxy crop rescues 22 tracked but POST 10 VALID likely splash/wrong-person; HUMAN-anchored prevents wrong-person links on VALID flight per FAX scoring radius, but POST must stay phase-gated out).
5. Entry/splash disappearance (ENTRY 0.41 non-1849, POST phase-gated out).
6. Head/face occlusion asymmetry (excluded).
7. Torso foreshortening (CV up to 0.426) invalidates scale normalization.
8. Temporal jitter 0.085–0.252 (still derivative-unsafe outside PREP).
9. Masks fail concurrently (prior result preserved, not rerun).
10. Tight crops can cut extended-arms PREP on proxy (952 proxy PREP 10→6); HQ unaffected.

## Geometry gate decision

**No new flight phases promoted to geometry-ready.** PREP/standing only remains geometry-ready (HQ PREP 0.95 VALID, flips 0, smoothing works). 1849-like slow-tuck-hold remains conditional, NOT promoted (HQ jitter 0.116–0.134 >0.10). If only some flight sub-phases qualified, we would promote only those — none qualify under strict gate. Stable body geometry cannot yet begin on any flight phases; do not produce biomechanics.

## Is more HUMAN pose annotation justified? (Q5)

**Yes, for next model-adaptation cycle only (not for cropping successor, which uses 0).** Pseudo-only fine-tuning on 45 easy frames fails (three variants, all degrade VAL), proving existing predictions/pseudo-labels insufficient for bootstrapping rotation/inversion/pike geometry and anatomical L/R. Next bounded step needs minimal HUMAN pose eval (and possibly train) to measure swap-vs-ambiguity and supply fine-tune eval. Prepared minimal targeted queue (16 frames, ≤20 budget, explicit anatomical L/R for shoulders/hips/elbows/wrists/knees/ankles), prioritizing true L/R ambiguity, inverted anatomy, pike/tuck ordering, rotation collapse — NOT requested now (0 used this cycle). Ask Maxime only once in next cycle if fine-tune proceeds.

Prepared queue (HQ raw, HUMAN box xyxy proxy, pts from GT; annotate anatomical left/right in image coordinates, even when inverted):

- 2134 inversion (4): fl_f00230 0/8 takeoff inversion (pts 3.837), fl_f00247 2/8 (4.120), fl_f00264 4/8 compact (4.404), fl_f00280 6/8 (4.671).
- 1257 small-flight (4): fl_f00157 0/8 (5.233), fl_f00167 2/8, fl_f00177 4/8, fl_f00188 6/8.
- 2120 pike (3): fl_f00270 0/8 (4.500), fl_f00288 2/8, fl_f00297 3/8 pike collapse (HQ d=0.288).
- 47 rotation (3): fl_f00304 4/8 horizontal (10.143), fl_f00309 5/8 (10.310), fl_f00324 8/8 entry (10.810).
- 952 rotation (2): fl_f00391 3/8, fl_f00399 4/8.

## Answers to definition-of-done

1. Does diving-specific successor materially improve hard-flight pose? Yes for recall/VALID via track-conditioned HQ crops with frozen weights (ROTATION non-1849 0.26→0.73, 1257 small 15→49 VALID, 2134 inversion 9→28 VALID, 2120 pike ROTATION 20→27/28); No for model adaptation via pseudo fine-tuning (three variants all degrade VAL — negative result).
2. Which phases become newly geometry-ready? None. PREP only stands; 1849-like tuck-hold conditional, not promoted.
3. Which phases remain unusable? All flight for geometry (rotation, inversion, compact pike, small-flight, entry, POST phase-gated out); 2134 ENTRY 0/7, POST excluded.
4. Gain due to model adaptation, resolution/cropping, or both? Cropping/resolution (track-crops + HQ), not model adaptation (fine-tune hurts). Imgsz held at 640, so effective resolution via cropping + distractor removal.
5. Is more HUMAN pose annotation justified? Yes for next model-adaptation cycle (16-frame queue prepared, 0 used now); pseudo insufficient proven.
6. Can stable body geometry now begin on any flight phases? No. PREP-only.

## Artifact identities

| Artifact | Identity |
|---|---|
| Canonical branch/base | `uiux-overhaul-pro-app` / `ba59467` (this commit identifies HEAD) |
| Prior feasibility (preserved) | `docs/science/DIVE_ANALYZER_CLEAN_TRACK_POSE_FEASIBILITY.md` at `76427df` |
| Prior hardening (preserved) | `docs/science/DIVE_ANALYZER_POSE_HARDENING_V1.md` at `ba59467` |
| FAX7 HUMAN | `docs/science/localization_annotations_v1/FULL_ACTION_GT_HUMAN_FAX7_FRESH/MANIFEST.json` digest `b71b950e…` (182 records) |
| FAX8 HUMAN | `docs/science/localization_annotations_v1/FULL_ACTION_GT_HUMAN_FAX8_FRESH/MANIFEST.json` digest `a31d5bcf…` (174 records) |
| Pose weights (frozen) | `yolov8n-pose.pt` `c6fa93dd1ee4a2c18c900a45c1d864a1c6f7aba75d84f91648a30b7fb641d212`; `yolov8m-pose.pt` `dbe539ea268db2534390942cfdf206e521f376f19e5415967a57f6a2ddfa3c90` (verified locally) |
| Successor weights (negative, not promoted) | crop-trained `best.pt` `a446ec0a1434c0bb4cf07c349ea54ada6112831355c27784677753df37f0b485`; full-trained `best.pt` `886b5bfe2b29f3240f1ee6d740078d6f8b9c9e3786f539210d2844fbfb0e5fab`; mild-freeze10 `best.pt` `93e2edad49de0885ee55b436abd4971064b7fc0c9fbc48b90f58181afe31b467` (6.5–6.8 MB n-pose, host-only) |
| Split authority (this cycle) | TRAIN 47/s15,952/s58; VAL 2120/s129,1849/s107; FINAL 1257/s79,2134/s130 (whole dives, session-disjoint, protected excluded) |
| HUMAN pose labels used | 0 (16-frame queue prepared, not requested) |
| Hardening evaluation layer (host-only, frozen for this comparison) | `hardening_v1.py` `a54dd942d12175e7d296357f605a613548a1f947fd91416f2c6fe5129272d002`; `dense_baseline.py` `759c33b34ec06136f097eb7be3ca2d2fa12447db1b89871fdb8864f4a10d68e5`; `dense_crop_eval.py` `92ad957b69d815a5515ae735c13dc61c311fac0275943ce2d187e5f1a7f53893` |
| Pseudo train (host-only) | 45 HQ crops/full-frames from TRAIN (47 19+6, 952 13+7), `pseudo_train_47_952_HQ.json`; hard inventory 30 clean-6 (25 flight hard) |
| Media | local `fresh_prep_authority/proxies/*.mp4` + `raw/*.mov` (47 proxy SHA `059ab226…` matches queue manifest) |
| Results (host-only) | `dense_baseline_fixed.json` (full baseline), `dense_crop_baseline_{train,val,final}.json` (crop successor), `dense_*_val.json` (fine-tune negatives), `sampled_baseline.json` (117-frame repro), `pseudo_train/*.json` |

SUPERVISOR_REVIEW_AFTER_DIVING_SPECIFIC_POSE_SUCCESSOR
