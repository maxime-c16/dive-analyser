# TARGET_DIVER_SELECTION_V1 — Report

**Date:** 2026-09-08
**Starting HEAD:** `b170b0faa49f7ba760ab7ead49fbbc7069b1cdf1` (verified before starting)
**Scope:** reopen PERCEPTION at target-diver identity selection only (raw D3.1 candidates → selection → temporal continuity). Detector training/weights/threshold, Event Logic thresholds, pose, SAM, and multi-domain data collection stayed frozen/untouched throughout.

---

## 1. Model artifact recovery

D3.1 weights (`DIVER_DETECTOR_D3_V8N_best.pt`, sha256 `bf6415f...1a77d`) were previously only reachable via an ephemeral scratchpad path. Established a durable, non-Git manifest: `docs/science/MODEL_ARTIFACT_MANIFEST.json`.

- **Primary**: `deb-serv:~/dive-analyser/models/frozen/DIVER_DETECTOR_D3_V8N_best.pt` (gitignored, canonical app/science server).
- **Independent backup**: `mac-server.home:~/.diveanalyzer/model_artifacts/DIVER_DETECTOR_D3_V8N_best.pt` — chosen because `~/.diveanalyzer/` is Machine B's pre-existing documented data root (holds `config.yaml`, `sync_state.json`, `manual_asset_exports/` per PROJECT_STATE.md), not an invented location.
- **Verified independently this cycle** (not just re-asserted): `sha256sum` on both hosts via SSH → identical (`bf6415fb63aa311f45262e555899d3023dd3d05d43a5e0d69b5e86c342e1a77d`), matching `D3_1_OPERATING_POINT_FREEZE.json`.
- **A1 recovery test**: performed live — located and hash-verified both copies using only the manifest's documented paths (no shell history, no scratchpad, no undocumented home path).
- **Status: `MODEL_ARTIFACT_AUTHORITY_GREEN`.**

## 2. D3.1 candidate recall (Phase C/F — DEVELOPMENT)

33 evaluable human spatial-reference frames across 12 dives (2 frames — `2169_apex`, `524_water_contact` — have no bbox on disk, `NOT_ANNOTATED`, excluded):

| Verdict | Count |
|---|---|
| TARGET_SELECTED_CORRECTLY (old N0 baseline) | 11 |
| TARGET_DETECTED_BUT_NOT_SELECTED | 9 |
| TARGET_NOT_DETECTED | 9 |
| AMBIGUOUS_REFERENCE | 2 |

**RAW_DETECTOR_CEILING ≈ 65%** (20/31 non-ambiguous frames have a usable candidate). **~29% (9/31) are genuine detection misses** no selector can repair — this is an honest, real ceiling on any selection-only fix, not glossed over. Per Phase F: candidates exist "sufficiently often" to justify continuing with selector development rather than an immediate `DETECTOR_REOPEN_REQUIRED`, but the ~29% miss rate should be read as a standing limitation, not solved by this packet.

## 3. 12-dive DEVELOPMENT corpus

All 12 target dives processed (the previous 8 — 133, 311, 524, 676, 1040, 2387, 2625, 2680 — plus the deferred 4 — 2169, 2341, 2541, 2555). Raw D3.1 candidates (conf=0.05) cached as lightweight JSON per dive; no raw video/frames persisted beyond what already existed.

## 4. Context distribution — CORRECTED

**Important correction made during this cycle:** a mid-cycle draft of `evaluate_selectors.py` hand-guessed only 2 of 12 dives as HURDLE (2625, 2680) and mislabeled 524, 1040, 2169, 2341, 2541, 2555 as STANDING. Cross-checking against the pre-existing, previously-committed `dev_analysis.py` dive-code table and running each real code through Event Logic's own frozen `classify_context()` gives the correct split:

| Context | n | Dives |
|---|---|---|
| STANDING | 4 | 133 (301B), 311 (401C), 676 (301A), 2387 (5411C) |
| HURDLE | 8 | 524 (103B), 1040 (102C), 2169 (101B), 2341 (101B), 2541 (5111B), 2555 (5132D), 2625 (103B), 2680 (010C) |

This is a materially better HURDLE representation than the prior packet's "zero real HURDLE trajectories" — see §8/§14.

## 5. S0 baseline

`S0_HIGHEST_CONFIDENCE`, framewise, no continuity. ALL correct-selection rate 48.4% (STANDING 72.7%, HURDLE 35.0%), mean coverage 90.2%, no near-zero-variance lock (S0 never refuses — it always confidently answers, right or wrong).

## 6. S1 global path selector

Deterministic Viterbi over {every raw candidate} ∪ {NULL} per frame. Observation = log-confidence; transition = bounded displacement + bbox-scale continuity cost; NULL is a first-class state (fixed re-acquire/hold costs). Post-hoc sequence-level rule: reject (→ all-NULL) a winning path that shows no meaningful vertical range in **any** 1.5s rolling window across the **whole** sequence — long static preparation followed by real motion is explicitly not penalized (regression-tested, §12).

**Bug found and fixed this cycle:** the static-track rejection was computed (`flagged_invalid_static_track`) but never actually applied to the returned path — dive 2625 (HURDLE) was still emitted as a confident wrong lock on static background despite being correctly flagged. Fixed to null the path when flagged; verified the other 11 dives are unaffected and the "long-prep-then-motion" case still passes.

Post-fix: ALL correct-selection 51.6% (STANDING 72.7%, HURDLE 40.0%), mean coverage 79.7% (drop vs. S0 driven entirely by dive 2625 now correctly returning NULL instead of a confident wrong answer).

## 7. S2 track-quality selector (ByteTrack-style)

Two-stage IoU/Hungarian association (`lap`) + a track-quality score (coverage, vertical range, motion arc, static-fraction penalty). Catastrophically fragments on this data: ALL correct-selection 25.8%, **mean coverage 13.3%** (STANDING 24.9%, HURDLE 7.6%) — far more short broken tracks than one usable trajectory. Disqualified on every axis, not a close call.

## 8. DEVELOPMENT selection result

| Selector | ALL correct | STANDING correct | HURDLE correct | Mean coverage | Near-zero-var lock rate |
|---|---|---|---|---|---|
| S0 | 48.4% | 72.7% | 35.0% | 90.2% | 0% |
| **S1** | **51.6%** | 72.7% | **40.0%** | 79.7% | 8.3% (1/12, dive 2625 — correctly fails safe, see §6) |
| S2 | 25.8% | 36.4% | 20.0% | 13.3% | 0% |

**4 DEVELOPMENT dives are "clean" under S1** (every available reference-frame verdict is MATCH, no material wrong-target lock anywhere checked): **133, 311 (STANDING), 524, 1040 (HURDLE)**. This is the first cycle with genuine clean HURDLE trajectories (previously: 3 clean, all STANDING, zero HURDLE).

## 9. Selector freeze

`docs/science/TARGET_DIVER_SELECTOR_V1_FREEZE.json` — **S1_GLOBAL_PATH** chosen: better correct-identity rate than S0 on ALL and HURDLE (ties on STANDING), and fails safe rather than confidently wrong on the one genuinely-static DEVELOPMENT track. S2 disqualified by coverage collapse. Freeze records detector identity (unchanged), full scoring-term parameters, NULL semantics, environment, DEVELOPMENT authority fingerprint, and an explicit Paris firewall clause. D3.1 weights/threshold and Event Logic thresholds were not touched anywhere in this process.

## 10. Paris human spatial authority

The prior Paris identity audit (`PHASE_B_PARIS_SPARSE_IDENTITY_AUDIT.json`) used Claude-vision inspection, explicitly flagged as not pixel-precise human authority. This cycle: extracted the same 14 sparse timestamps (0.2–5.0s, spanning preparation → hurdle → takeoff → apex → descent → water contact → post-dive) as PTS-exact native-resolution (1080×1920) frames from the **original** `IMG_1937.mov` (sha256 `d122262...`, verified byte-identical to the frozen canary reference), served through the existing localization-review UI (extended with a `PARIS` split) for maintainer boxing.

Two operational issues were found and fixed before/during the human gate:
- **Manifest width/height were swapped** (1920×1080 recorded vs. actual 1080×1920 portrait files) — would have silently corrupted every box's normalization. Caught before most boxing happened; the one box saved under the bad dimensions was discarded and redone.
- **Served images were uncompressed PNG** (~9.5MB × 14 ≈ 129MB), causing severe UI slowness over the home-network path. Re-encoded to JPEG q=92 at the same native resolution (no downscale) — ~440KB each. Verified dimensions and file sizes after the fix.

All 14 frames reviewed by the maintainer: 12 `visible` (boxed), 2 `occluded` (correctly boxless — `entry`, `post_dive`, splash/underwater).

## 11. Paris raw detector recall (Phase N)

Fresh D3.1 inference (frozen weights/threshold, unchanged) on the native-resolution source, 322 frames, against the 12 boxed frames:

| Verdict | Count |
|---|---|
| TARGET_DETECTED_BUT_NOT_SELECTED | 8 |
| TARGET_NOT_DETECTED | 3 |
| AMBIGUOUS_REFERENCE | 1 |
| TARGET_SELECTED_CORRECTLY (old N0) | 0 |

**All three canonical GT anchors have the correct candidate present but unselected**: takeoff (rank 5 of 5 by confidence), apex (rank 3 of 3), water_contact (rank 2). **This is conclusively a selection failure at Paris, not a pure detection failure**, for the frames that matter most — confirming the mechanism already hypothesized in `PHASE_B_PARIS_SPARSE_IDENTITY_AUDIT.json` with real pixel-precise ground truth. Raw ceiling ≈ 67% (8/12), close to the DEVELOPMENT figure.

## 12. Paris frozen selector result (Phase O)

Ran the **frozen, unmodified** S1_GLOBAL_PATH selector on the Paris native raw candidates. Result: 2/12 correct (16.7%) — **all 3 GT anchors (takeoff/apex/water_contact) WRONG_TARGET**. S1's log-confidence observation term still strongly favors a persistently, falsely high-confidence static background object (conf 0.30–0.42) over the true diver's frequently-near-threshold confidence (0.05–0.08) — continuity smoothing alone does not overcome this at Paris.

**`TARGET_SELECTION_FAIL`.** Per the packet's own gating (Phase P/R "only if PASS"), no `VERIFIED_TARGET_DIVER_TRAJECTORY` was produced for Paris, and Phase R (Paris event test) does not get a clean run — see §15.

## 13. Real target trajectory

DEVELOPMENT: the 4 clean S1 trajectories (§8) constitute verified target-diver trajectories (bbox center/top/bottom/height, confidence, NULL state, selector provenance = `S1_GLOBAL_PATH` throughout, no switches).
Paris: **not produced** — gated off by §12's `TARGET_SELECTION_FAIL`.

## 14. V2.1/V2.2 expanded DEVELOPMENT comparison (Phase Q/Q1)

Run on the 4 clean S1 trajectories (frozen params, no tuning):

| Dive | Context | GT takeoff/apex/wc (s) | V2.1 err (s) | V2.2 (S1_BODY_SCALE) err (s) |
|---|---|---|---|---|
| 133 | STANDING | 1.800 / 2.084 / 2.950 | −0.165 / +0.119 / −0.114 | +0.168 / +0.119 / −0.114 |
| 311 | STANDING | 13.755 / n/a / 14.821 | **+4.297** / — / **+3.931** | **+4.364** / — / +3.931 |
| 524 | HURDLE | 5.810 / 6.327 / 7.094 | **−2.977** / **−3.227** / +0.473 | **−0.110** / **−0.110** / +0.473 |
| 1040 | HURDLE | 4.464 / 4.797 / 5.414 | −0.193 / +0.074 / −0.042 | −0.193 / +0.074 / −0.042 |

- **n=4 clean trajectories total (2 STANDING, 2 HURDLE)** — small, honestly reported as such; no P90 is meaningful at this n.
- **Dive 311 is a catastrophic outlier for both V2.1 and V2.2 alike** (~4s error on takeoff/wc) — same magnitude/direction for both variants, so it is not a V2.1-vs-V2.2 discriminator; flagged as an open failure (§16), likely the state machine locking onto a later spurious motion segment in a long clip.
- **Dive 524 is the one clear V2.1-vs-V2.2 discriminator**: V2.1's fixed velocity threshold catastrophically misidentifies the hurdle bounce as takeoff (−3.0/−3.2s); V2.2's body-scale-normalized threshold gets takeoff and apex right to within ~0.11s. Water-contact error is identical between variants (shared detection method, untouched by the S1_BODY_SCALE change).
- Dive 1040: V2.1 and V2.2 produce **identical** results (no regression, no improvement — the scale-normalized threshold made no difference here).

### Q1 — V2.2 status

**`SUPPORTED_BY_EXPANDED_REAL_DATA`** — weakly. This is the first cycle with any real HURDLE evidence at all (n=2, vs. n=0 previously), and on that n=2, V2.2 shows one clear, large win (524) and one exact tie (1040), no regression anywhere. This is real, non-trivial, but still just n=2 — **not promoted to the 0.55 body-heights/s threshold being adopted as scientific authority**, per the packet's explicit instruction. V2.1 remains the frozen simpler baseline; V2.2 stays `V2_2_EXPERIMENTAL_FROZEN_NOT_ADOPTED` pending a larger HURDLE sample.

## 15. External Paris Event Logic result

**Not meaningfully evaluable** — consequence of §12's `TARGET_SELECTION_FAIL`. Ran anyway for transparency (unchanged, frozen params, both variants): both V2.1 and V2.2 return **no landmarks at all** (`takeoff_idx=None` throughout) on the Paris S1 trajectory — the underlying signal has no real "rising diver" velocity because the selected trajectory is still substantially locked onto static structure. This is the same mechanism reported in `PHASE_B_PARIS_SPARSE_IDENTITY_AUDIT.json`, now confirmed with a real (not vision-audited) selector run. Labeled `CONFOUNDED_BY_UNRESOLVED_PERCEPTION`, not a clean Event-Logic verdict either way.

## 16. Remaining failure taxonomy

1. **Detector recall gap (~29-33% of reference frames, DEVELOPMENT and Paris alike)** — no candidate near the true diver at all. Selection cannot fix this; would require detector reopening (explicitly out of scope this packet).
2. **Cross-venue selection generalization failure (Paris)** — S1 wins in-domain but loses badly cross-venue because the false-positive's confidence profile at Paris (stable 0.30–0.42) dominates the true diver's (0.05–0.08) more decisively than in the DEVELOPMENT corpus. A pure confidence-weighted observation term is not enough; would need either a spatial prior, a discriminative appearance cue, or explicit per-venue confidence recalibration — none attempted here (would be new detector/perception work, out of this packet's scope).
3. **Dive 311's catastrophic ~4s Event-Logic error**, present identically in V2.1 and V2.2 — an open, unexplained failure on an otherwise perception-clean trajectory; needs its own investigation, not addressed here (Event Logic tuning was explicitly out of scope).
4. **n=2 HURDLE is still a very small sample** for the V2.2 support conclusion — real, but fragile.

---

## Phase S — Perception decision

**`SELECTION_IMPROVED_BUT_NOT_SUFFICIENT`**

Selection was demonstrably the dominant Paris failure mode (raw candidate present at all 3 GT anchors, just unselected) and the fix measurably helps in-domain (48.4%→51.6% ALL, first-ever clean HURDLE trajectories). It does not generalize to the actual named external test (Paris: `TARGET_SELECTION_FAIL`), and a genuine ~30% detector-recall ceiling remains regardless of selector quality. Not calling for more detector training here: raw candidate recall (§2, §11) shows the correct candidate present at the majority of failure frames — the demonstrated problem is selection/observation-term robustness, not primarily detector recall (detector reopening was explicitly out of this packet's scope in any case).

## Phase T — Tracking decision

**`FRAMEWISE_GLOBAL_PATH_PREFERRED`**

S1 beats S2 on every measured axis (correctness, coverage, robustness) — S2 is disqualified by fragmentation, not a close call. ByteTrack is not retained out of convention.

## Phase U — Model artifact status

**`MODEL_ARTIFACT_AUTHORITY_GREEN`** (§1).
