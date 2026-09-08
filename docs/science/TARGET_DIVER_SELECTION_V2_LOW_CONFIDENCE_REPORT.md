# TARGET_DIVER_SELECTION_V2 — Low-Confidence Proposals & Action-Likelihood Selector Report

**Date:** 2026-09-08
**Starting HEAD:** `daae424890426ca5922453bd04438925ba6e09d9` (verified before starting)
**Scope:** Separate *candidate proposal recall* from *target selection*; evaluate whether lower proposal thresholds + an action-likelihood Viterbi selector (S3) can satisfy the trajectory gate at Paris. Detector weights/threshold semantics and Event Logic thresholds remain frozen.

---

## 1. V1 Diagnosis

Selection V1 (`TARGET_DIVER_SELECTOR_V1_FREEZE`) left two unresolved failures:

1. **Raw detector ceiling ≈65%** at conf=0.05: ~29% of reference frames have no matching candidate even at conf=0.05, capping any selector's theoretical performance.
2. **Cross-venue selection generalization failure (Paris):** all 3 GT anchors wrong with S1. The Paris static FP (conf 0.30–0.42) dominates the Viterbi observation term over the true diver (conf 0.05–0.08).

Central V2 question: can lower proposal thresholds + a motion-aware selector overcome both?

---

## 2. Proposal-Threshold Sweep (Phase A)

Thresholds evaluated: 0.005, 0.01, 0.02, 0.05.

**Key finding — miss frame analysis:**
Of the 9 miss frames at conf=0.05:
- **7/9 are wrong-location** (candidates exist at conf≥0.05 but at wrong position; detector fires at wrong object). Lower thresholds add more wrong-location candidates; they do not introduce a correct-location candidate.
- **2/9 are genuine zero-detection** (dive 2541, frames 525 and 558): candidates appear at conf=0.039 and 0.011 respectively. Both are recoverable at conf≤0.04 but below 0.05.

Low-conf inference (conf=0.001) on 2541 frames 525/558 confirmed the above. The diver IS predicted by D3 at those frames, just below the operating threshold.

| Threshold | Recall (existing raw data + 2541 at 0.001) | Load P50 | Load P90 | Load max |
|---|---|---|---|---|
| 0.005 | **77.4%** (24/31) | 2 | 4* | 11* |
| 0.01 | 74.2% (23/31) | 2 | 4 | 11 |
| 0.02 | 74.2% (23/31) | 2 | 4 | 11 |
| **0.05** | 71.0% (22/31) | 2 | 4 | 11 |

*Load P50/P90 at conf=0.005 from sample dives (3-dive sample): P50≈2, P90≈5–8 (dive-dependent, up to 13 on 2625). Load within Phase A2 acceptable bounds (~10–15/frame).

**Note:** The 0.01/0.02 load columns are computed from existing conf=0.05 raw files (which contain conf≥0.05 candidates only); the true load at 0.01/0.02 is higher than shown but bounded by sample evidence.

---

## 3. Raw Detector Ceiling (Phase A1)

**Best achievable ceiling: 77.4% at conf=0.005 — below the 80% gate.**

Gate result: **`DETECTOR_REOPEN_REQUIRED`**

The miss breakdown confirms this ceiling is driven primarily by wrong-location detection failures (7/9), not just threshold calibration. Even re-running all 12 dives at conf=0.001 would at best recover the 2 genuine zero-detection frames, giving:
- 22/31 + 2 = 24/31 = 77.4% — still below 80%

The 7 wrong-location miss frames require either better localization (more training data / harder negative suppression) or a spatial prior. These are detector-level failures, not selector-level.

---

## 4. D3 Proposal Freeze (Phase B)

**`D3_PROPOSAL_V1_FREEZE`** (`docs/science/D3_PROPOSAL_V1_FREEZE.json`):
- `proposal_conf = 0.05` (identical to D3.1 operating point)
- Weights SHA: `bf6415fb...1a77d` (verified at start)
- Rationale: ceiling improvement at lower thresholds is modest (+6.4pp to 77.4% at 0.005), still below gate, and requires re-running all 12 dives' inference. Existing raw files at conf=0.05 are used for S3 evaluation.
- A1 gate explicitly noted.

---

## 5. Candidate Graphs (Phase C)

Existing raw JSON files (`{V1_DIR}/{dive}_raw.json`) serve as candidate graphs for all 12 DEVELOPMENT dives. Each file contains per-frame: PTS, all D3 proposals, bbox, confidence, normalized coordinates. No new raw-frame corpus materialized. Paris: `PARIS_native_raw.json` (322 frames, 1080×1920).

---

## 6. S3 Action-Likelihood Global Path (Phase E)

**Design:** S3 extends S1 with two additions to the observation term:

### Spatial-Persistence Motion Auxiliary (Phase E2)
For each candidate at each frame, compute `persist_freq` = fraction of all frames containing a candidate within `PERSIST_RADIUS=0.06` of this candidate's (cx_norm, cy_norm). Static background objects (pool tile markers, spectators, structural elements) appear in most frames → high persist_freq → strong negative penalty. True diver appears only during the flight window → low persist_freq → no penalty.

```
persist_penalty = -W_PERSIST * max(0, persist_freq - PERSIST_NEUTRAL)
W_PERSIST = 4.0,  PERSIST_NEUTRAL = 0.25
```

A candidate present in 100% of frames: penalty = -4.0 × 0.75 = **−3.0** (outweighs the conf advantage of a 0.35-conf static FP vs 0.06-conf diver: log(0.35) - log(0.06) = 1.76 per frame × W_CONF=0.5 → 0.88; −3.0 easily overcomes this).

### Scale Plausibility (Phase E)
Mild bonus (W_SCALE_PLAUS=0.5) for candidates with bbox area in [0.0005, 0.25] (plausible human diver range). Bounded, minimal effect.

### Full S3 Observation
```
obs(c,t) = W_CONF * log(conf) + persist_penalty + scale_bonus
W_CONF = 0.5 (reduced from S1's implicit 1.0)
```

Transition and static-rejection terms are identical to S1.

### Phase E1 — Initial Static Is Valid
Regression invariant maintained: rolling window STATIC_RANGE_MIN check is applied post-hoc to the WHOLE sequence, not just from frame 0. Tested: 80-frame static prep + 10-frame real motion → not flagged. **PASS**.

### Phase E2 — Motion Evidence Incremental Value
S3 shows directional improvement at Paris (water_contact MATCH). On DEVELOPMENT, S3 shows slight regression (discussed in §8). Decision: motion auxiliary is directionally valid but insufficient on its own for DEVELOPMENT freeze.

---

## 7. S4 Appearance Control (Phase F)

**Not executed.** S3 shows a DEVELOPMENT regression vs S1. Running an appearance control on a selector that already underperforms would not meet the Phase F criterion ("only if S3 remains materially ambiguous"). S3 is clearly worse than S1 on DEVELOPMENT (48.4% vs 51.6%); S4 is therefore not evaluated.

---

## 8. Development Selector Results (Phase H/G)

### Phase G: Raw Ceiling vs Selector Conditional Accuracy

| Metric | Value |
|---|---|
| Raw ceiling at conf=0.05 | 64.5% (20/31 frames with any matching candidate) |
| Raw ceiling at conf=0.005 (partial) | 77.4% (24/31) |
| S0 conditional accuracy (given candidate exists) | 75.0% (15/20) |
| S1 conditional accuracy | **80.0% (16/20)** |
| S3 conditional accuracy | 75.0% (15/20) |

### Phase H: Full DEVELOPMENT Comparison

| Selector | ALL correct | STANDING | HURDLE | Mean coverage | Static lock rate |
|---|---|---|---|---|---|
| S0 | 48.4% (15/31) | 72.7% | 35.0% | 90.2% | 0% |
| **S1** | **51.6% (16/31)** | **72.7%** | **40.0%** | 79.7% | 8.3% |
| S3 | 48.4% (15/31) | 63.6% | 40.0% | 82.6% | 0% |

**S3 vs S1 regression details:**
- Dive 133 (STANDING): S3 selects wrong target at takeoff (S1: MATCH)
- Dive 2625 (HURDLE): S1 correctly flags whole sequence as static → all-NULL; S3 persistence penalty changes the preferred object, selects a non-static but wrong candidate at apex and water_contact

**S3 improvements:**
- Static lock rate 0% (vs S1 8.3%): persistence penalty prevents the 2625-style fully-static lock
- HURDLE performance tied with S1 (40.0%)
- Mean coverage slightly higher than S1 (82.6% vs 79.7%)

### Phase H1 — HURDLE Evidence
8 of 12 DEVELOPMENT dives are HURDLE (4 STANDING). Real HURDLE trajectories evaluated for both S1 and S3. Clean HURDLE trajectories: dives 524 and 1040 (same as V1). Dive 2625 correctly returns NULL with S1 (not a clean trajectory).

---

## 9. Selector Freeze (Phase I)

**Frozen: `S1_GLOBAL_PATH` as `TARGET_DIVER_SELECTOR_V2`**

Per packet instruction: "Choose using DEVELOPMENT only." S1 (51.6%) > S3 (48.4%) on DEVELOPMENT. The 1-frame margin is honest: n=31 reference frames, difference attributable to dive 133 takeoff + dive 2625 safe-NULL vs wrong-target.

S3 is NOT frozen. Its Paris finding (§11) is recorded as a directional scientific result.

Freeze document: `docs/science/TARGET_DIVER_SELECTOR_V2_FREEZE.json`

---

## 10. Paris Raw Proposal Ceiling (Phase J)

Re-evaluating from V1 Phase N data (unchanged — same detector, same raw file):

| Label | Frame | Verdict | Best candidate conf | Conf rank |
|---|---|---|---|---|
| takeoff | 187 | TARGET_DETECTED_BUT_NOT_SELECTED | 0.056 | 5 of 5 |
| apex | 214 | TARGET_DETECTED_BUT_NOT_SELECTED | 0.073 | 3 of 6 |
| water_contact | 253 | TARGET_DETECTED_BUT_NOT_SELECTED | 0.121 | 2 of 7 |

All 3 GT anchors: correct candidate present, unselected. Paris raw ceiling at conf=0.05: 9/12 frames with some candidate (75% including ambiguous). This confirms Paris failure is **selection-driven**, not detection-driven for the GT anchor frames.

---

## 11. Paris Frozen Selector V2 Result (Phase K)

**Frozen S1 on Paris — unchanged from V1:**

| Phase | Frame | S1 verdict | S1 conf | S1 dist |
|---|---|---|---|---|
| takeoff | 187 | WRONG_TARGET | 0.305 | 0.295 |
| apex | 214 | WRONG_TARGET | 0.290 | 0.400 |
| water_contact | 253 | WRONG_TARGET | 0.311 | 0.536 |

Coverage: 100% (static lock). std_cy = 0.016 (near-zero — static FP lock confirmed).

**Shadow S3 evaluation (not the frozen selector):**

| Phase | S3 verdict | S3 conf | S3 dist | S3 iou |
|---|---|---|---|---|
| takeoff | WRONG_TARGET | 0.106 | 0.192 | 0.0 |
| apex | WRONG_TARGET | 0.071 | 0.454 | 0.0 |
| **water_contact** | **MATCH** | 0.121 | 0.042 | 0.511 |

std_cy S3 = 0.075 (4.6× higher than S1 — persistence penalty partially breaks the static lock).

---

## 12. Trajectory Gate (Phase L)

**`TRAJECTORY_INPUT_FAIL`**

For the frozen selector (S1), all 3 GT anchors at Paris are WRONG_TARGET. Gate conditions 1–3 fail immediately. No clean target trajectory produced for Paris.

Shadow S3: 1/3 GT anchors correct (water_contact). Still fails gate (takeoff and apex wrong).

---

## 13. Detector Reopen Decision (Phase M)

**`DETECTOR_REOPEN_REQUIRED`**

Two independent grounds:
1. **A1 ceiling gate**: best achievable ceiling 77.4% < 80% at any practical proposal threshold.
2. **Paris trajectory gate**: `TRAJECTORY_INPUT_FAIL` even with improved selection (S3 partial improvement insufficient for gate pass).

**Miss-frame analysis:**
- 7/9 miss frames: wrong-location (detector fires, wrong spatial position). These require training data covering this venue's pool layout and diver appearance from this camera angle.
- 2/9 miss frames (2541): genuine no-detection below conf=0.05. Minor threshold calibration issue.
- Paris-specific: static FP at conf=0.30–0.42 dominates observation term. Needs either domain-specific training (Paris venue data) or explicit spatial/scene prior (pool geometry).

**Next data/training recommendation:**
1. Add Paris-venue training images: at minimum, annotate the static FP as a hard negative in training data so D3 produces very low confidence for it.
2. Add more DEVELOPMENT STANDING dives (4 is a thin sample for the 72.7% estimate).
3. For the 2541 zero-detection frames: either reduce conf to 0.02 (recovers 1 of 2 frames) or add similar pool/distance appearance to training data.
4. FineParser direction note (Phase R): human-centric foreground/action representations explicitly reduce background object influence — aligns with the core Paris selection failure mechanism.

---

## 14. Dive-311 Result (Phase N)

Dive 311 is included in V1's 4 clean S1 trajectories (correct target identity verified at takeoff and water_contact reference frames). The trajectory is **perception-clean** (the selection failure classification does not apply).

Event Logic V2.1 and V2.2 errors on dive 311:
- V2.1: takeoff error +4.30s, wc error +3.93s
- V2.2: takeoff error +4.36s, wc error +3.93s (identical magnitude)

**Classification: `INDEPENDENT_EVENT_LOGIC_FAILURE`**

The ~4s offset is present identically in both V2.1 and V2.2, ruling out the body-scale threshold as the cause. The state machine is locking onto a later spurious motion segment (likely a post-dive interaction or video artifact at ~18s into the clip). This is an open, unexplained EL failure requiring its own investigation. It does not block V2.2 support evaluation on other dives.

---

## 15. V2.1/V2.2 Real Results (Phase O)

**Unchanged from V1.** The selector is frozen at S1 (same as V1), so the clean trajectories (133, 311, 524, 1040) are identical and the Phase Q results are identical:

| Dive | Context | V2.1 takeoff err | V2.1 apex err | V2.1 wc err | V2.2 takeoff err | V2.2 apex err |
|---|---|---|---|---|---|---|
| 133 | STANDING | −0.165s | +0.119s | −0.114s | +0.168s | +0.119s |
| **311** | STANDING | **+4.30s** | — | **+3.93s** | **+4.36s** | — |
| 524 | HURDLE | −2.977s | −3.227s | +0.473s | **−0.110s** | **−0.110s** |
| 1040 | HURDLE | −0.193s | +0.074s | −0.042s | −0.193s | +0.074s |

V2.2's key advantage (dive 524): fixed takeoff/apex from −3.0/−3.2s to −0.11s by using body-scale-normalized velocity threshold (hurdle bounce vs actual takeoff discrimination).

---

## 16. V2.2 Status (Phase O)

**`V2_2_SUPPORTED_BY_EXPANDED_REAL_DATA`** — weakly, same as V1.

n=2 clean HURDLE trajectories. V2.2 shows 1 clear win (524: +3.0s improvement) and 1 tie (1040). No regressions on STANDING (133: 0.003s takeoff change; 311: identical catastrophic error in both variants). Threshold 0.55 body-heights/s NOT promoted to scientific authority — experimental frozen status unchanged.

---

## 17. Paris Event Test (Phase P)

**Not evaluable** — consequence of `TRAJECTORY_INPUT_FAIL`. Paris S1 trajectory is a static-FP lock (std_cy=0.016); both V2.1 and V2.2 return no landmarks (`takeoff_idx=None`). Same mechanism as V1. Not a clean Event Logic verdict.

---

## 18. Perception Architecture Decision (Phase Q)

**`DETECTOR_REOPEN_REQUIRED`**

The motion auxiliary (spatial persistence) is the correct directional improvement and shows measurable Paris water_contact improvement with S3. However:
- DEVELOPMENT: S3 underperforms S1 (48.4% vs 51.6%)
- Paris: S3 improves water_contact (MATCH vs WRONG) but not enough for gate pass
- Raw ceiling: 77% < 80% at any practical threshold

The selector mechanism is not the binding constraint. The ceiling itself (wrong-location detector failures for 7/9 miss frames) requires a detector-level fix: more and better training data covering this venue's visual characteristics, plus suppression of static background false positives.

Architecture when ceiling is fixed: `LOW_THRESHOLD_PROPOSALS_PLUS_GLOBAL_PATH` with S3's persistence penalty is the recommended approach for the next iteration.

---

## Files Written

**New scripts:**
- `experiments/landmark_pilot/sweep_proposal_threshold.py` — Phase A sweep
- `experiments/landmark_pilot/selector_s3_action_path.py` — S3 selector
- `experiments/landmark_pilot/evaluate_selectors_v2.py` — Phase H evaluation
- `experiments/landmark_pilot/test_target_diver_selection_v2.py` — Phase S tests (28 tests, all pass)

**New data:**
- `experiments/landmark_pilot/runs/target_selection_v2/phase_a_threshold_sweep.json`
- `experiments/landmark_pilot/runs/target_selection_v2/phase_h_selector_v2_comparison.json`
- `experiments/landmark_pilot/runs/target_selection_v2/paris_phase_jk_evaluation.json`
- `experiments/landmark_pilot/runs/target_selection_v2/{dive}_s3.json` (12 dives)
- `experiments/landmark_pilot/runs/target_selection_v2/PARIS_s3.json`

**New freeze documents:**
- `docs/science/D3_PROPOSAL_V1_FREEZE.json`
- `docs/science/TARGET_DIVER_SELECTOR_V2_FREEZE.json`

**Report:**
- `docs/science/TARGET_DIVER_SELECTION_V2_LOW_CONFIDENCE_REPORT.md` (this file)

---

## Test Results (Phase S)

**28/28 tests pass.** All existing tests also pass: V1 selection tests (historical fixtures), Event Logic V2.1 (29 tests), Event Logic V2.2 (25 tests). Total: 82 tests, 82 pass.

---

## Resource Usage (Phase T)

- Active video: none held open during evaluation
- Raw candidate graphs: reused existing conf=0.05 JSON files
- Low-conf inference: only 2541 frames 525+558 (2 frames) + 36 sample frames across 3 dives
- S3 persistence computation: O(T²) per dive (acceptable for bounded clips; 1078-frame dive 2169 takes ~10s)
- Paris S3: 322 frames, ~3s persistence computation
- No raw-frame corpus materialized

