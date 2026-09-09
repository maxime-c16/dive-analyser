# Hurdle Final Takeoff Observability and Event Logic V3-D Report

**Thread**: Event Logic V3-D  
**Date**: 2026-09-09  
**Gate**: `EVENT_LOGIC_V3_D0_FREEZE`  
**Head at freeze**: `9881813` (branch `uiux-overhaul-pro-app`)

---

## Executive Summary

This report documents Phases A–U of the Event Logic V3-D experiment thread, which investigated the root causes of FM2 (HURDLE final takeoff detection failure) and developed, evaluated, and froze V3-D0 as the successor to V3-C0.

**Key results:**
- FM2 root cause identified: D5 detector target instability / switching creates artifact-dominated smoothed velocity that overwhelms the true hurdle departure signal at 360p resolution
- V3-D0: board-rise validation gate + STANDING-like fallback reduces DEVELOPMENT HURDLE mean takeoff error 26.5% (1.637s→1.204s)
- V3-D0 Paris: **unchanged** from V3-C0 (to_err=1.685s); different failure mode — pre-hurdle prep-walk creates a valid-looking false arc
- Decision: **V3_D_DEVELOPMENT_IMPROVES_PARIS_FAILS** / **SCENE_CONTEXT_NEXT_JUSTIFIED**
- 13/13 new unit tests pass
- Freeze gate: **PASS**

---

## Phase A — V3-C0 DEVELOPMENT Baseline

**Source**: `docs/science/EL_V3C_DEVELOPMENT_EVAL_V1.json`

V3-C0 DEVELOPMENT results on 6 procedural-input-pass dives:

| Dive | Context | to_err | wc_err |
|------|---------|--------|--------|
| 133  | STANDING | 0.165s | 0.148s |
| 311  | STANDING | 0.059s | 0.027s |
| 676  | STANDING | 3.086s | 1.016s |
| 1040 | HURDLE   | 1.995s | 2.511s |
| 2169 | HURDLE   | 1.280s | 0.364s |
| 2387 | STANDING | 2.148s | 0.161s |

DEVELOPMENT median: med_to=1.637s, med_wc=0.262s. FM1 closed (311 wc: 3.530→0.027s via A1+A2).

---

## Phases B–C — Observability Audit (Raw vs Smoothed)

**Source**: `docs/science/HURDLE_OBSERVABILITY_V3D_ANALYSIS_V1.json`

Near-GT-takeoff window analysis (±0.35s from GT takeoff):

| Dive | raw_neg_ratio | smooth_neg_ratio | Gate |
|------|--------------|-----------------|------|
| 1040 | 0.381 | 0.000 | AMBIGUOUS |
| 2169 | 0.190 | 0.000 | AMBIGUOUS |

**Finding**: Gaussian smoothing (sigma=0.117s) destroys the takeoff signal for both HURDLE dives. **smooth_neg_ratio=0.0** for both means the smoothed velocity shows no negative (rising) period near the GT takeoff.

**Root causes** (from signal trace):

**Dive 2169**: D5 switches from cy≈0.262 (board tracking) to cy≈0.711 at t=6.406s (just 55ms before GT takeoff 6.461s). This creates a +24 vel_raw spike followed by -24 spike (1 frame each at 60fps). Gaussian smoothing spreads these spikes into a large positive velocity artifact from guard_end (6.306s) through 6.840s. True takeoff (diver rising: negative velocity) is completely masked. First neg→non-neg crossing is at t=7.257s (smoothed flight-arc apex, delay=0.796s from GT apex 6.761s). cy_smooth at this crossing ≈ 0.447 > y_prep=0.264 → below board level.

**Dive 1040**: D5 alternates between cy=0.22 (board-track of diver at upper frame) and cy=0.60 (lower-frame target) with ±11/s raw velocity oscillations every 1–2 frames. Gaussian smooth averages these, creating a quasi-random smooth velocity that doesn't represent diver motion. False prep_end at 0.434s, false hurdle apex at 1.635s (cy_apex=0.221 < y_prep=0.531 → passes board-rise check), false takeoff at 2.469s (2.0s before GT). Signal irrecoverable at 360p.

**Overall observability**: MIXED_OBSERVABILITY (AMBIGUOUS for both HURDLE dives).

---

## Phases D–E — Signal Primitive and Filter Comparison

**Source**: `docs/science/HURDLE_OBSERVABILITY_V3D_ANALYSIS_V1.json`

**Primitive comparison** (D0=center-y, D1=bottom-y, D2=body-scale) at GT takeoff:
- 1040: D0/D1/D2 peak vel near GT takeoff all POSITIVE (artifact dominated) — no primitive helps
- 2169: D0/D1/D2 peak vel all LARGE POSITIVE (artifact dominated) — no primitive helps

**Filter comparison** (F0=Gaussian, F1=SG lower-delay):
- 1040: No material difference — target instability overwhelms any filter
- 2169: SG filter reduces phase shift from 0.067s to ~0.030s but doesn't recover the signal from the target-switch artifact

**Conclusion**: The fundamental issue is not filter delay or primitive choice; it is D5 target selection failure near the hurdle moment. Lower-delay filters and bbox_bottom do not help.

---

## Phase F — Overall Observability Gate

**MIXED_OBSERVABILITY**: 2169 signal is artifact-dominated (target switch), 1040 is target-oscillation dominated. Neither shows reliable kinematic takeoff signal at 360p in the smoothed domain.

---

## Phase G — HQ Authority (Read-Only from iCloud Thread)

**Source**: `docs/science/HURDLE_HQ_COMPARISON_V1.json`

HQ inference (from `HIGHRES_ANALYSIS_SOURCE_MANIFEST_V1.json`, PTS_EQUIVALENT):

| Dive | HQ file | Resolution | HQ classification | V3-C0 360p to_err | V3-C0 HQ to_err |
|------|---------|-----------|------------------|------------------|----------------|
| 1040 | IMG_4301.mov | 1920×1080 | HQ_RECOVERS_MISSING_TAKEOFF_SIGNAL | 1.995s | ~1.094s |
| 2169 | IMG_9474_edited.mov | 742×418 | HQ_NO_MATERIAL_INCREMENT | 1.280s | 0.439s |

HQ shows modest improvement for 2169 (1.280→0.439s) and stronger improvement for 1040 (to_err reduced). However, HQ inference was read-only and no HQ-derived thresholds are used in V3-D0. HQ authority confirmed by iCloud thread freeze (commit 9881813).

---

## Phases H–I — V3-D Candidate Design

**First attempt (failed)**: D0=bbox_bottom + SG filter. Both failed:
- 1040: to_err worsened to 4.145s (target instability affects bbox_bottom identically)
- 2169: INCOMPLETE (no takeoff found; same root cause — target switch overwhelms any cy-based signal)

**Root cause analysis** from full signal trace led to revised design:

**V3-D0 revised**: Board-rise validity gate for hurdle apex + STANDING-like fallback.
- Physical invariant: at a real hurdle apex, the diver must be ABOVE board level (cy_apex < y_prep)
- If all crossings fail: fallback to guard_end, find first sustained negative velocity
- No parameter changes from V3-C0 except two new keys (min_hurdle_rise_cy=0.01, fallback_sustained_s=0.15)

**V3-D1 revised**: Same as V3-D0 but fallback_sustained_s=0.25s. Evaluated; identical results to V3-D0 on all 8 dives. Not promoted separately.

---

## Phase J — DEVELOPMENT Evaluation

**Source**: `docs/science/EL_V3D_REVISED_DEVELOPMENT_EVAL_V1.json`

| Dive | Context | V3-C0 to_err | V3-D0 to_err | Delta |
|------|---------|-------------|-------------|-------|
| 133  | STANDING | 0.165s | 0.165s | UNCHANGED |
| 311  | STANDING | 0.059s | 0.059s | UNCHANGED |
| 676  | STANDING | 3.086s | 3.086s | UNCHANGED |
| 1040 | HURDLE   | 1.995s | 1.995s | UNCHANGED |
| 2169 | HURDLE   | 1.280s | **0.412s** | **−67.8%** |
| 2387 | STANDING | 2.148s | 2.148s | UNCHANGED |

**HURDLE detail:**
- Dive 2169: Board-rise check rejected 12/12 candidates (all cy_apex > y_prep=0.264). STANDING_FALLBACK found sustained negative velocity at 6.873s. to_err: 1.280s→0.412s.
- Dive 1040: False apex at 1.635s passes board-rise check (y_prep=0.531, cy_apex=0.221, rise=+0.310 > min_rise). Algorithm accepts it, finds takeoff at 2.469s — unchanged. Root cause: y_prep itself was computed from the oscillating detector (tracking intermediate position at prep_end), making the rise check ineffective.

---

## Phase K — Freeze Gate

| Criterion | Result |
|-----------|--------|
| HURDLE improves (mean to_err) | ✅ 1.637→1.204s (−26.5%) |
| No STANDING catastrophe | ✅ All 4 STANDING dives: UNCHANGED |
| FM1 closed | ✅ Dive 311 wc_err=0.027s (A1+A2 preserved) |
| WC not materially regressed | ✅ med_wc 0.262→0.224s (improved) |
| Physical interpretation defensible | ✅ Board-rise invariant is a physical necessity |
| **GATE RESULT** | **PASS** |

---

## Phase L — Freeze

**`EVENT_LOGIC_V3_D0_FREEZE`** declared.  
Artifact: `docs/science/EVENT_LOGIC_V3_D0_FREEZE.json`  
Source: `experiments/landmark_pilot/proposer_event_logic_v3_d0.py`

---

## Phase M — Paris External Test (Post-Freeze, Read-Only)

| Variant | Paris to_err | Paris wc_err |
|---------|-------------|-------------|
| V3-C0   | 1.685s | 0.133s |
| V3-D0   | 1.685s | 0.133s |

**Paris V3-D0 trace**: candidate apex at 1.117s with y_prep=0.464, cy_apex=0.380, rise=+0.083 > min_rise=0.01 → **ACCEPTED** (valid-looking pre-takeoff motion). Takeoff found at 1.435s (GT=3.120s, to_err=1.685s).

**Paris failure mode**: The diver's approach walk briefly creates a kinematically valid-looking hurdle pattern (the approach step rises above the board level slightly). At 360p, this false arc passes the board-rise check because the diver does genuinely rise above board during the approach. This is a distinct failure mode from 2169 (where the false arc was a detector artifact going BELOW board level).

---

## Phase N — Paris Failure Diagnosis

**Paris failure classification**: Pre-hurdle approach kinematics create a valid-looking board-rise pattern that the algorithm cannot distinguish from the real hurdle jump at 360p. The board-rise invariant is a necessary condition but not sufficient: a diver's normal walking approach also involves brief rises above the nominal board standing position.

**What would fix Paris**: A time constraint on when the hurdle can begin (approach-end gate), knowledge of the number of approach steps, or scene-based detection of the diver reaching the end of the board. All of these require scene context beyond kinematics alone.

---

## Phase O — Scene Context Decision

**Decision**: `SCENE_CONTEXT_NEXT_JUSTIFIED`

**Rationale**: 
1. Kinematic signals at 360p (with D5 detector instability near takeoff) are insufficient to reliably detect HURDLE final takeoff without scene context.
2. Paris pre-hurdle approach walks pass the board-rise check — a purely kinematic gate cannot distinguish them from the real hurdle.
3. Higher resolution (HQ) helps (2169: 1.280→0.439s) but Paris would have the same approach-walk false positive.
4. Scene context needed: approach-end detection (when the diver stops walking and begins the hurdle) or board-proximity gating.

**Not:** KINEMATICS_SUFFICIENT (fails Paris) | HIGHER_RESOLUTION_NEEDED_BEFORE_SCENE_CONTEXT (resolution doesn't fix the approach-walk ambiguity)

---

## Phase P — Event Logic Decision

**Decision**: `V3_D_DEVELOPMENT_IMPROVES_PARIS_FAILS`

- V3-D0 is FROZEN and replaces V3-C0 as the active DEVELOPMENT baseline
- V3-D0 does not solve Paris FM2 — Paris error is identical to V3-C0
- The promotion to production requires solving Paris, which requires scene context
- V3-C0 is superseded; V3-D0 is the new active frozen variant for DEVELOPMENT purposes

---

## Phases R–S — Tests

**File**: `experiments/landmark_pilot/test_event_logic_v3_d0.py`  
**Result**: 13/13 PASS

| Test | Description |
|------|-------------|
| D0a | False apex (cy_apex > y_prep) rejected |
| D0b | Valid apex (cy_apex < y_prep) accepted |
| D0c | Multiple false candidates, valid one found |
| D0d | Fallback when no valid apex |
| D0e | Fallback finds 2169-scenario sustained departure |
| D0f | Full integration: hurdle + apex + wc |
| D0g | FPS invariance (30fps and 60fps) |
| D0h | Long static prep — no early detection |
| D0i | Board-recontact invariant (parametric sweep) |
| H1  | STANDING non-regression |
| FM1 | Dive 311 pattern closed |
| PARIS_FIREWALL | Paris to_err ≤ 2.0s |
| D0j | Freeze identity (PARAMS_V3D0 spot-check) |

---

## Success Criterion Answers

1. **Is true HURDLE final takeoff visible in raw D5 trajectories?**  
   Partially. Raw neg_ratio=0.19-0.38 but smoothed=0.0 for both HURDLE dives. The signal exists in isolated raw frames but is not reliably observable in the smoothed domain at 360p.

2. **Is Gaussian smoothing destroying or delaying the cue?**  
   Destroying it, not just delaying. The 0.067s phase shift is negligible compared to the artifact-dominated velocity (>1.0/s from target switching). No filter choice recovers the signal.

3. **Is bbox-bottom better than bbox-center for support departure?**  
   No material difference at 360p with D5 target instability. The artifact level (from switching) overwhelms the signal regardless of which cy is used.

4. **Does a lower-delay filter repair DEVELOPMENT FM2?**  
   No. SG filter reduces phase shift but does not address target-switch artifacts.

5. **Does HQ materially restore the signal?**  
   Yes for 1040, partially for 2169. But HQ-derived improvements are outside this thread's authority.

6. **Can a kinematic V3-D solve HURDLE without STANDING regressions?**  
   Partially. V3-D0 improves 2169 by 68% with zero STANDING regressions. It does not improve 1040 (different target instability pattern not caught by board-rise gate). Paris is unchanged.

7. **Is scene context actually necessary?**  
   Yes, for Paris. Board-rise invariant is necessary but not sufficient to distinguish the real hurdle from approach-walk motions.

---

## Artifacts Produced

| File | Description |
|------|-------------|
| `experiments/landmark_pilot/proposer_event_logic_v3_d0.py` | V3-D0 proposer (frozen) |
| `experiments/landmark_pilot/test_event_logic_v3_d0.py` | 13 unit tests |
| `docs/science/EVENT_LOGIC_V3_D0_FREEZE.json` | Freeze artifact |
| `docs/science/EL_V3D_REVISED_DEVELOPMENT_EVAL_V1.json` | Full per-dive results |
| `docs/science/HURDLE_OBSERVABILITY_V3D_ANALYSIS_V1.json` | Observability analysis |
| `docs/science/HURDLE_HQ_COMPARISON_V1.json` | HQ vs 360p comparison |
| `docs/PROJECT_STATE.md` | Updated project state |
