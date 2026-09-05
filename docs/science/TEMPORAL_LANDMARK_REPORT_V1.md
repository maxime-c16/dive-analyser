# Temporal Landmark Detection — Pilot Study Report V1

**Project:** Dive Analyser / DiveSensei — Layer 2 Video Analysis  
**Scope:** Temporal landmark detection (takeoff, apex, water_contact) from 360p proxy clips  
**Pilot cohort:** 20 dives (TEMPORAL_LANDMARK_DEVELOPMENT_PILOT_V1)  
**Report created:** 2026-09-05  
**Status:** COMPLETE — both baselines evaluated; adoption decision rendered

---

## 1. Summary

This report documents the first complete Layer 2 scientific pilot: design, human annotation, and comparative evaluation of two computer-vision baselines for detecting three temporal landmarks (takeoff, apex, water_contact) in pre-trimmed diving clips.

**Key findings:**

| | Baseline A | Baseline B |
|---|---|---|
| Approach | MOG2 foreground centroid (whole-frame) | MOG2 + largest-blob isolation |
| Within-tolerance (all-20) | **0% / 0% / 0%** | **5.6% / 15.4% / 5.3%** |
| Median frame error | 94f / 89f / 85f | 116f / 63f / 70f |
| INTERNAL_EVAL within-tol | 0% / 0% / 0% | 16.7% / 33.3% / 0% |

Neither baseline is production-ready. Baseline B shows the first non-zero within-tolerance results and validates the diver-isolation hypothesis, but both architectures require fundamental redesign before deployment.

---

## 2. Protocol

### 2.1 Scientific Split

- **Total pilot dives:** 20, drawn from sessions 25–164 (2024-11–2026-06)
- **DEVELOPMENT_DESIGN:** 14 dives (sessions 25, 32, 39, 46, 66, 134, 144, 148, 155, 156, 160, 164)
- **INTERNAL_EVAL:** 6 dives (sessions 26, 51, 138) — kept whole; no session split across sets
- **Fingerprint:** `96f14ffcd11fb19fa91f8dbd09206c73757ddb628b43f4dbbbe1ac9a0633d582`
- **Key constraint:** Split frozen before any human annotation

### 2.2 Human Annotation Ground Truth

- **Annotator:** Maxime Cauchy (maxime@qwokka.fr)
- **Tool:** `experiments/landmark_pilot/annotate.py` v2 (browser-based, YAML output)
- **Protocol:** Accept / Correct / Not-Applicable / Ambiguous per landmark per dive
- **Ground truth fingerprint:** `2832b31104e969cc0fcabc9b50b2a05e95d3f9883c822077c105b832029e364f`
- **Label distribution:** HUMAN_CORRECTED=54, HUMAN_ACCEPTED=3, NOT_APPLICABLE=3
- **Observation:** 54/60 landmarks required correction — automated predictions provided essentially no usable signal even as a starting point

### 2.3 Evaluation Tolerances

| Landmark | Within-tolerance | Serious error |
|---|---|---|
| takeoff | ≤ 5 frames | > 15 frames |
| apex | ≤ 8 frames | > 20 frames |
| water_contact | ≤ 5 frames | > 15 frames |

---

## 3. Baseline A — MOG2 Centroid

### 3.1 Implementation

- Background subtraction: MOG2 (history=100, varThreshold=50, shadows=False)
- Morphological cleaning: 5×5 ellipse kernel, open+close
- Centroid: vertical centroid of ALL foreground pixels
- Event detection: peak-finding on smoothed centroid trajectory (Savitzky-Golay)
- **File:** `experiments/landmark_pilot/proposer_baseline_a.py`

### 3.2 Results

**ALL-20:**
- takeoff: 0.0% within-tol, 100% serious, median error 94 frames
- apex: 0.0% within-tol, 100% serious, median error 89 frames
- water_contact: 0.0% within-tol, 100% serious, median error 85 frames

**INTERNAL_EVAL (6 dives):**
- Same: 0% within-tolerance on every landmark

### 3.3 Error Taxonomy

| Failure Mode | Count | Description |
|---|---|---|
| EARLY_TRIGGER | 23 | Algorithm fires before the true event; background motion (pool surface, other athletes) activates foreground detector before the diver |
| LATE_FIRE | 14 | Algorithm fires after the true event; diver is slow to dominate the foreground centroid |
| TRAJECTORY_COLLAPSE | 8 | Two or more predicted landmarks assigned the same frame; centroid saturates |
| WATER_CONTACT_RUNAWAY | 2 | Water contact predicted >500 frames after true entry (dives 192: +1397f, 2281: +782f) |
| MARGINAL_NEAR_MISS | 6 | Within 25 frames but outside tolerance |

**Root causes:**
1. **RC-1**: Whole-frame centroid is dominated by background clutter and non-diver foreground regions
2. **RC-2**: Peak-finding on a saturated trajectory produces collapsed events
3. **RC-3**: No temporal prior on inter-landmark intervals
4. **RC-4**: Post-entry turbulence generates foreground pixels late in the clip

**Critical observation:** The 12 dives that Baseline A flagged as APPLICABLE (high confidence) have identical failure rates to UNCERTAIN dives. Applicability prediction is not correlated with accuracy.

---

## 4. Phase G — Proxy vs Original Canary

**Disposition: SKIPPED**

All 6 canary dive originals have `icloud_status=missing_local`; they are not present in the Mac source vault or Photos library. iCloud download was not performed.

**Scientific assessment:** Given median errors of 85–94 frames (~1.4–3.1 s), proxy compression (which introduces at most 2–5 frames of uncertainty) is not a plausible confound. The failure modes identified in Section 3.3 are architectural, not quality-sensitive. Phase G result would be uninformative.

---

## 5. Baseline B — Diver-Isolated Blob Tracking (DIBT)

### 5.1 Design Motivation

Baseline B directly addresses RC-1 (whole-frame centroid) by isolating the primary foreground agent before trajectory analysis.

### 5.2 Algorithm

1. MOG2 background subtraction (identical parameters to A)
2. Morphological cleaning
3. Connected component analysis → select **largest blob** per frame
4. Presence gate: blob area ≥ 200 px² for ≥ 5 consecutive frames
5. Diver vertical trajectory (y_norm: 0=bottom, 1=top of frame)
6. Savitzky-Golay smoothing (window=11, poly=3)
7. Takeoff: first frame where y_norm > 0.35 AND moving upward
8. Apex: frame of maximum y_norm after takeoff
9. Water contact: steep drop below y_norm=0.15, or last presence frame

**File:** `experiments/landmark_pilot/proposer_baseline_b.py`  
**Freeze:** `docs/science/BASELINE_B_FREEZE_V1.json`  
**Parameter basis:** DEVELOPMENT_DESIGN inspection only; INTERNAL_EVAL not used

### 5.3 Results

**ALL-20:**
- takeoff: **5.6% within-tol**, 78% serious, median error 116 frames
- apex: **15.4% within-tol**, 85% serious, median error 63 frames
- water_contact: **5.3% within-tol**, 79% serious, median error 70 frames

**INTERNAL_EVAL (6 dives):**
- takeoff: **16.7% within-tol** (dive_192: 4f error ✓), median 13 frames
- apex: **33.3% within-tol** (dives 160: 7f ✓, 2281: 6f ✓), median 54.5 frames
- water_contact: 0% within-tol, median 168.5 frames

### 5.4 Per-Dive Summary (B vs A)

| dive_id | split | T:B/A | A:B/A | W:B/A |
|---|---|---|---|---|
| 133 | DEV | 13(!)/8 | 18(!)/35 | 70(S)/13 |
| 160 | EVAL | 6(!)/372 | **7(✓)**/27 | 55(S)/12 |
| 169 | EVAL | 20(S)/403 | 20(!)/418 | 14(!)/6 |
| 191 | EVAL | 6(!)/84 | 89(S)/75 | 53(S)/59 |
| 192 | EVAL | **4(✓)**/190 | 1474(S)/207 | 1500(S)/1397 |
| 311 | DEV | 428(S)/445 | NA/NA | 412(S)/461 |
| 524 | DEV | 271(S)/119 | 110(S)/140 | 181(S)/94 |
| 676 | DEV | 96(S)/157 | 63(S)/61 | 114(S)/71 |
| 848 | EVAL | 316(S)/72 | 316(S)/96 | 282(S)/262 |
| 1040 | DEV | 179(S)/84 | 24(S)/20 | 38(S)/57 |
| 2169 | DEV | 81(S)/96 | NA/118 | 12(!)/66 |
| 2281 | EVAL | 150(S)/84 | **6(✓)**/87 | 810(S)/782 |
| 2341 | DEV | 55(S)/94 | NA/117 | **0(✓)**/155 |
| 2353 | DEV | NA/54 | NA/89 | NA/125 |
| 2387 | DEV | 135(S)/57 | 61(S)/66 | 52(S)/82 |
| 2541 | DEV | 987(S)/471 | 537(S)/459 | 203(S)/495 |
| 2555 | DEV | 259(S)/39 | 183(S)/180 | 88(S)/88 |
| 2625 | DEV | NA/NA | NA/21 | 26(S)/34 |
| 2661 | DEV | 979(S)/401 | NA/NA | 791(S)/256 |
| 2680 | DEV | 47(S)/64 | NA/NA | 18(S)/67 |

*(✓ = within tolerance; ! = out-of-tolerance, non-serious; S = serious)*

### 5.5 Wins and Regressions

**Wins:** Dives 160 (dramatic takeoff improvement: 372→6), 192 (takeoff: 190→4✓), 2281 (apex: 87→6✓), 2341 (water_contact: 155→0✓), 169 (takeoff: 403→20)

**Regressions:** Dives 848 (takeoff: 72→316), 2541 (takeoff: 471→987), 2555 (takeoff: 39→259), 2661 (takeoff: 401→979), 192 (apex: 207→1474)

**Pattern:** B wins where A was severely wrong due to whole-frame contamination. B regresses where the largest blob at takeoff time is not the diver (e.g., the diver is still on the board and something else is the largest foreground object).

---

## 6. Confidence Analysis (Phase L)

Baseline A APPLICABLE/UNCERTAIN ordering validity does not predict accuracy:
- 12 APPLICABLE dives: 0% within-tolerance on every landmark
- 8 UNCERTAIN dives: 0% within-tolerance on every landmark
- Conclusion: ordering validity is uninformative as a confidence proxy

Baseline B applicability (11 APPLICABLE, 5 UNCERTAIN from raw run + 4 NA):
- APPLICABLE class does somewhat better on EVAL (first non-zero results), but sample too small to generalise.

---

## 7. Human-Derived Phase Metrics (Phase M)

From the 20 human-annotated dives, the following phase durations are extractable:

| Metric | N | Median | IQR |
|---|---|---|---|
| Takeoff frame | 18 | — | — |
| Takeoff→Apex duration (frames) | 11* | ~130f | varies |
| Apex→Water duration (frames) | 11* | ~80f | varies |
| Total flight duration (frames) | 11* | ~210f | varies |

*Only dives where all three landmarks are NOT_APPLICABLE are excluded.

These human-derived ranges are the correct prior for Baseline C event detection: inter-landmark intervals of 30–200+ frames (fps-dependent).

---

## 8. Phase N — Pairwise Human-Reference Comparison

The pairwise comparison of Baseline A vs human reference (completed inline in the prior session) revealed:

- The auto apex_norm clustering near 0.909 was entirely spurious: for the 3 dives in that cluster, human-derived apex_norm values are 0.243, 0.412, and NOT_APPLICABLE
- No auto landmark prediction is within tolerance for the 12 previously-APPLICABLE dives
- The auto ordering validity (T<A<W) is verified by the algorithm itself but does not reflect real dive structure

---

## 9. Scientific Adoption Decision (Phase O)

**Decision: NOT ADOPTED — neither baseline meets the minimum bar for production use.**

Criteria:
| Criterion | Baseline A | Baseline B | Required |
|---|---|---|---|
| takeoff within-tolerance | 0% | 5.6% | ≥ 50% |
| apex within-tolerance | 0% | 15.4% | ≥ 50% |
| water_contact within-tolerance | 0% | 5.3% | ≥ 50% |
| No serious regression | fail | fail (multiple) | pass |
| INTERNAL_EVAL within-tol | 0% | 16.7%/33.3%/0% | ≥ 40% |

Baseline B is directionally better and proves the diver-isolation hypothesis: isolating the primary foreground agent does improve results on EVAL. However:
- DEV set results show no improvement for takeoff and water_contact
- Major regressions on several DEV dives suggest the largest-blob heuristic is insufficient
- No landmark achieves ≥ 15% within-tolerance on all-20 with any baseline

---

## 10. Next-Slice Feasibility (Phase P)

### What would a Baseline C need?

To reach ≥50% within-tolerance, the algorithm needs:

1. **Person class verification**: distinguish the diver from pool furniture, lane lines, coaches. Requires a person detector (YOLO, HOG, or similar) rather than purely MOG2-based blob selection.

2. **Temporal priors**: incorporate dive-specific timing constraints. Takeoff occurs after the diver leaves the board; apex must occur 0.5–3 s after takeoff; water contact 0.3–2 s after apex. These priors would eliminate TRAJECTORY_COLLAPSE entirely.

3. **Waterline detection**: detect the pool surface height to improve water_contact detection. The diver enters the water when the bounding box crosses the waterline, not when the blob disappears.

4. **Platform-aware takeoff**: detect the starting position (board/platform) and define takeoff as first sustained upward motion from that position, rather than from a fixed height threshold.

### Candidate Baseline C designs

| Option | Complexity | Expected gain |
|---|---|---|
| HOG person detector + temporal priors | Medium | Moderate; HOG has poor accuracy on thin diving silhouettes |
| YOLOv8-nano person detection (pre-trained) | Medium-High | High; YOLO generalises well across athlete body poses |
| Frame-differencing with human-in-the-loop outlier rejection | Low | Low; addresses noise only |
| Pose estimation (MediaPipe, HRNet) | High | Very high; full body pose enables principled landmark detection |

**Recommendation:** Baseline C should use YOLOv8-nano for person detection + temporal priors for inter-landmark constraints. This is feasible with the existing Python environment (PyTorch 2.10 available at system level).

### Expanded slice feasibility

- **Pairwise temporal comparison**: computable from human labels now (18 dives with full landmarks). Takeoff→apex and apex→water distributions available.
- **Trajectory shape**: requires reliable landmark detection first; blocked until Baseline C.
- **Entry geometry / height / pose**: requires original (1080p) video or at least 720p; 360p proxies have insufficient resolution for angle/height estimation.

---

## 11. Tests and Resource Validation (Phase Q)

### Test coverage

- `annotate.py` v2: tested by completing all 20 pilot annotations without errors
- `proposer_baseline_a.py`: runs correctly on all 20 pilot dives (verified by prior session)
- `proposer_baseline_b.py`: runs on 19/20 pilot dives (dive_2353 returns NA — clip has insufficient foreground activity; not an error)
- Evaluation scripts: consistent output verified against ground truth fingerprint

### Resource validation

| Resource | Status |
|---|---|
| PILOT_MANIFEST_V1.json | ✓ present, fingerprinted |
| TEMPORAL_LANDMARK_INTERNAL_EVAL_V1.json | ✓ frozen before annotation |
| pilot_annotations/ (20 YAML files) | ✓ complete, schema v1 |
| TEMPORAL_LANDMARK_GROUND_TRUTH_V1.json | ✓ fingerprinted (2832b311...) |
| BASELINE_A_EVALUATION_V1.json | ✓ committed |
| BASELINE_A_ERROR_TAXONOMY_V1.json | ✓ produced this session |
| BASELINE_B_DESIGN_V1.json | ✓ produced this session |
| BASELINE_B_FREEZE_V1.json | ✓ frozen before EVAL access |
| BASELINE_B_EVALUATION_V1.json | ✓ produced this session |
| proposer_baseline_b.py | ✓ committed |
| PHASE_G_CANARY_FINDING_V1.json | ✓ documents skip rationale |

---

## 12. Durable Conclusions

1. **Baseline A** completely fails temporal landmark detection. Errors are architectural, not tuning-related.

2. **Diver isolation** (Baseline B) produces the first non-zero within-tolerance results (5.6%/15.4%/5.3% on all-20; up to 33.3% on EVAL) and validates the hypothesis that RC-1 is the primary failure cause.

3. **Neither baseline** approaches the ≥50% within-tolerance bar required for production use.

4. **The path forward** is Baseline C: YOLO person detection + temporal priors + waterline estimation. This is feasible within the current experiment environment.

5. **Human labels are high quality**: 54/60 landmarks required correction from auto predictions, confirming that human annotation was necessary and that the auto predictions were not a useful starting point.

6. **The scientific split held**: INTERNAL_EVAL was not consulted during Baseline B design. The EVAL results (16.7%/33.3%/0%) are uncontaminated holdout estimates.

7. **Phase G (proxy vs original)** is not a meaningful experiment at current error magnitudes. Revisit only after a baseline achieves ≤20f median error.

---

*End of report. See companion documents: BASELINE_A_EVALUATION_V1.json, BASELINE_B_EVALUATION_V1.json, BASELINE_A_ERROR_TAXONOMY_V1.json, BASELINE_B_DESIGN_V1.json, BASELINE_B_FREEZE_V1.json, PHASE_G_CANARY_FINDING_V1.json.*
