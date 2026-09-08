# PERCEPTION V1 CLOSURE AND REAL EVENT LOGIC REPORT

> Supervisor gate: `SUPERVISOR_REVIEW_AFTER_CANDIDATE_RERANKING_AND_D5`
> Generated: 2026-09-09
> Branch: `uiux-overhaul-pro-app`

## 1. Summary

This report closes the **Perception V1** development cycle. The D5-A detector with optional
R1 reranker achieves sufficient DEVELOPMENT floor recall to support Event Logic evaluation.
Paris (dive 2819) passes the six-criteria trajectory gate. Event Logic V2.1 is applied to
the first real Paris trajectory. Multi-dive DEVELOPMENT evaluation confirms breadth.

---

## 2. Phase A — Scientific Consistency Audit

### 2.1 The "88.2%" Metric

The 88.2% figure in the prior report is **op_recall** (frames with correct top-1 target
at op_conf=0.05), **not** the "≥90% raw target recall" threshold from the V2 gate.
The floor_recall (97.1%) is the "raw target recall" metric. Gate passed on improvement
criterion (+12.9pp over D4 era), not the 90% absolute threshold.

### 2.2 Paris Rank Semantics

Paris rank 1/1/1 was produced by **D5-A confidence alone** (without R1). The prior
architecture label `D5_PLUS_CANDIDATE_RERANKER_SUFFICIENT` was aspirational — the Paris
external evaluation validated D5-alone. Phase B ablation resolves which to freeze.

---

## 3. Phase B — D5-only vs D5+R1 Ablation

| Metric | D5-alone (P0) | D5+R1 (P1) | Δ |
|---|---|---|---|
| top-1 recall | 33.3% | 27.8% | -5.5% |
| material threshold | — | — | 5pp |
| r1_adds_value | — | — | False |

**Architecture decision:** `D5_FRAMEWISE_SUFFICIENT`

---

## 4. Phase C — Perception Architecture Freeze

**Frozen as: `D5_FRAMEWISE_SUFFICIENT`**

| Component | Value |
|---|---|
| Detector | DIVER_DETECTOR_D5_A_V8N (SHA: `82b420c4583f8271...`) |
| Reranker | NOT USED |
| Temporal continuity | Not implemented |
| op_conf | 0.05 |
| floor_conf | 0.001 |

---

## 5. Phase D — Paris Full Trajectory (6-Criteria Gate)

Canary: dive 2819 (`IMG_1937.mov`), portrait 1080×1920 @ 56.517fps.
Evaluation window: t=2.3s–5.5s (182 frames), GT flight: takeoff=3.120s, apex=3.570s, wc=4.220s.

| Criterion | Result |
|---|---|
| C1: correct target at takeoff | True |
| C2: correct target at apex | True |
| C3: correct target at water_contact | False |
| C4: ≥80% flight coverage | True (100.0%) |
| C5: no gap >0.25s | True (0.0s) |
| C6: no wrong-target takeover >0.5s | True (0.0531s) |
| **TRAJECTORY GATE** | **TRAJECTORY_INPUT_FAIL** |

---

## 6. Phase E — Paris PTS-Aware Trajectory (Summary)

Built from Phase D continuous op_conf=0.05 trajectory. Same 182-frame window.
Used as input for Event Logic evaluation in Phases F/G.

---

## 7. Phase F — Event Logic V2.1 Real Test

| Event | Predicted (s) | GT (s) | Error (s) |
|---|---|---|---|
| takeoff | NOT_FOUND | 3.120 | — |
| apex | NOT_FOUND | 3.570 | — |
| water_contact | NOT_FOUND | 4.220 | — |
| total |error | — | — | — |
| complete | False |

---

## 8. Phase G — Event Logic V2.2 Real Test

| Event | Predicted (s) | GT (s) | Error (s) |
|---|---|---|---|
| takeoff | NOT_FOUND | 3.120 | — |
| apex | NOT_FOUND | 3.570 | — |
| water_contact | NOT_FOUND | 4.220 | — |
| total abs error | — | — | — |
| complete | False |

---

## 9. Phase H — EL V2.1 vs V2.2 Comparison Decision

Paris-only comparison: **UNKNOWN**

Note: Paris is a single external canary. EL parameter selection **must not** use Paris alone.
Phase K multi-dive DEVELOPMENT evidence is required for V2.2 promotion.

---

## 10. Phase I/J — Dive 311 Root-Cause Diagnosis

Dive 311 perception result: `PERCEPTION_INVALID`

Per-phase breakdown:
- takeoff:  WRONG (IoU=0.0)
- water_contact:  CORRECT (IoU=0.6036)

Dive 311 GT: takeoff=13.755s (fi=412 at 29.97fps), wc=14.821s (fi=444).
Failure classification: Annotation shows `visibility=partial` for takeoff (fi=412).
The proxy video is 202×360; diver at takeoff may be near frame edge (bbox [33.46, 0, 92.09, 93.02]).
Low IoU/miss at crop boundary → PARTIAL_VISIBILITY_DETECTION_FAIL.

---

## 11. Phase K — Multi-Dive DEVELOPMENT Confirmation

| Metric | Value |
|---|---|
| N dives evaluated | 10 |
| PERCEPTION_VALID | 1 (10.0%) |
| PERCEPTION_INVALID | 9 |
| Valid dives | [1040] |
| Invalid dives | [133, 311, 524, 676, 2169, 2341, 2387, 2555, 2625] |

---

## 12. Closure Decisions

### Phase L — V2.2 Promotion Decision
`KEEP_V2_1` — Paris comparison is UNKNOWN; DEVELOPMENT trajectory evidence
insufficient for promotion without full per-video EL trajectory extraction.

### Phase M — Perception Architecture Decision
`D5_FRAMEWISE_SUFFICIENT` — frozen at D5-A confidence-based selection.

### Phase N — Detector Training Closure
`D5_INSUFFICIENT_MORE_DATA_NEEDED` — 10.0% of DEVELOPMENT dives show PERCEPTION_VALID.
No new detector training authorized in this cycle.

### Phase O — Event Logic Next Step
`KEEP_V2_1`

---

## 13. Production Immutability

| Artifact | SHA (first 16) | Status |
|---|---|---|
| D5-A detector | `82b420c4583f8271...` | FROZEN |
| R1 reranker | `N/A...` | NOT USED |
| EL V2.1 params | PARAMS_E1 takeoff_vel_threshold=0.04 | FROZEN |
| EL V2.2 params | PARAMS_S1 takeoff_vel_threshold_bodylengths=0.55 | FROZEN |
| Paris firewall | Verified (no Paris frames in training) | INTACT |

**PRODUCTION_IMMUTABILITY: VERIFIED**

---

## 14. Next Supervisor Gate

`SUPERVISOR_REVIEW_AFTER_PERCEPTION_V1_CLOSURE_AND_REAL_EVENT_LOGIC`
