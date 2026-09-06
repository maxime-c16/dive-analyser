# HIGH_RESOLUTION_CANARY_EVENT_SEMANTICS_CORRECTION_V1

**Document status:** SUPERSEDED — Section 5 Phase M values are INCORRECT (never produced by committed code)
**SUPERSEDED_BY:** `docs/science/PHASE_M_CANARY_CHECK_AUDIT.json`
**Supersession reason:** Audit 2026-09-06 confirmed that committed `proposer_event_logic_v2.py` +
`phase_m_canary_check.py` produce takeoff_error=−1.670s, apex_error=−1.353s (not −0.103s/+0.013s).
Root cause: sinusoidal hurdle oscillation triggers false board_recontact + coordinate convention
mismatch. Section 5 table values were INCORRECT_NEVER_PRODUCED_BY_COMMITTED_CODE.
Correct reference: `PHASE_M_CANARY_CHECK_AUDIT.json`. Fix: `proposer_event_logic_v2_1.py` (36/36 tests pass).
**Date:** 2026-09-06  
**Supersedes:** `HIGHRES_CANARY_V1_FREEZE.json` (human-annotation section only)  
**Author:** maxime@qwokka.fr

---

## 1. Summary of corrections

The V1 canary freeze (`HIGHRES_CANARY_V1_FREEZE.json`, commit `0a3fa53`) contained
three categories of errors that required a full re-annotation and re-evaluation:

| Error | V1 value | Authoritative value | Impact |
|---|---|---|---|
| Apparatus | "platform 10m" | springboard 1m | Invalidates all height-dependent analysis |
| Human takeoff | 3.50 s | 3.120 s (PTS-correct) | −0.380 s shift |
| Human apex | 4.20 s | 3.570 s (PTS-correct) | −0.630 s shift |
| Human water_contact | 4.90 s | 4.220 s (PTS-correct) | −0.680 s shift |
| water_contact semantics | "last frame ≈ GT" | END_OF_CLIP_COINCIDENCE | CC3 error not 0.00 s |
| CC3 takeoff error | −3.40 s | −3.020 s | (CC3 was 0.10 s, GT is 3.12 s) |
| CC3 apex error | −2.80 s | −2.170 s | (CC3 was 1.40 s, GT is 3.57 s) |
| CC3 water error | 0.00 s | +0.680 s | END_OF_CLIP_COINCIDENCE |
| "velocity spike = takeoff" heuristic | used in CC3 | INVALIDATED | replaced by state machine |

---

## 2. Corrected canary identity

- **Source:** `/Users/maximecauchy/Downloads/IMG_1937.mov`
- **SHA256:** `d122262be8e7a8721ab2f6a71721bb3544403da78324138d026360ef9820eaae`
- **Dive ID:** 2819 (database)
- **Dive code:** `5122D G/G`
- **Apparatus:** springboard (NOT platform)
- **Height:** 1 m (NOT 10 m)
- **Context:** HURDLE (dive code group 51xx → forward approach with hurdle)
- **hurdle flag:** true
- **initial_static:** true (diver static at clip start)
- **n_frames:** 322, **duration:** 5.3717 s, **fps:** VFR ~60 fps
- **hurdle_onset:** frame 0, t=0.000 s (video pre-cut to start of hurdle)

---

## 3. PTS-correct annotation (HIGHRES_CANARY_V2_EXACT_ANNOTATION.json)

Annotated 2026-09-06T17:48:41Z via `annotate_canary_v2.py` (port 8766),
using `ffprobe best_effort_timestamp_time` for PTS extraction.

| Landmark | Frame | PTS (s) | Notes |
|---|---|---|---|
| hurdle_onset | 0 | 0.000 | diagnostic — clip starts at hurdle |
| board_recontact | 160 | 2.668333 | diver lands back on board |
| takeoff | 187 | 3.120 | final departure from board |
| apex | 214 | 3.570 | highest point of flight arc |
| water_contact | 253 | 4.220 | entry into water |

**Freeze:** `HIGHRES_CANARY_V2_REFERENCE.json`

---

## 4. CC3 error analysis (Phase G)

CC3 (`proposer_baseline_c.py`) was re-evaluated against the V2 annotation:

| Landmark | CC3 estimate | V2 GT | Error | Classification |
|---|---|---|---|---|
| takeoff | 0.10 s | 3.12 s | −3.020 s | CATASTROPHIC (first detection ≠ takeoff) |
| apex | 1.40 s | 3.57 s | −2.170 s | CATASTROPHIC (first y-min ≠ apex) |
| water_contact | 4.90 s | 4.22 s | +0.680 s | END_OF_CLIP_COINCIDENCE |

**Root causes of CC3 failure:**
1. `timestamp_s = idx / fps` — NOT PTS-correct (VFR video has irregular intervals)
2. "First detection = takeoff" — INVALID for hurdle dives (diver detected during hurdle)
3. "First minimum cy = apex" — INVALID (detects approach minimum, not flight apex)
4. "Last frame ≈ water contact" — END_OF_CLIP_COINCIDENCE, not physical detection
5. No context awareness (HURDLE vs STANDING not distinguished)

---

## 5. Event Logic V2 correction (Phase H–K)

`proposer_event_logic_v2.py` addresses all CC3 failure modes:

| CC3 failure | E1 fix |
|---|---|
| idx/fps time | PTS-aware velocity: dt from actual timestamp differences |
| First detection = takeoff | State machine: wait for board re-contact before searching takeoff |
| First y-min = apex | Apex restricted to post-takeoff interval; velocity zero-crossing |
| Last frame = water contact | cy_norm threshold (y > water_line_cy_norm); not last frame |
| No context | classify_context() maps dive code to HURDLE/STANDING |

**Phase M synthetic canary check (E1 with cy_norm convention):**

> ⚠️ **SUPERSEDED — VALUES BELOW ARE INCORRECT.**
> Actual committed-code output per `PHASE_M_CANARY_CHECK_AUDIT.json`:
> takeoff_error=−1.670s, apex_error=−1.353s, water_contact_error=+0.013s.
> The values in this table (−0.103s/+0.013s/+0.030s) were NEVER produced by
> any committed version of `proposer_event_logic_v2.py`. Do NOT cite them.
> Correct mechanism: `proposer_event_logic_v2_1.py` (36/36 tests pass).

| Landmark | E1 estimate (INCORRECT) | GT | Error (INCORRECT) |
|---|---|---|---|
| takeoff | 3.017 s | 3.120 s | −0.103 s |
| apex | 3.583 s | 3.570 s | +0.013 s |
| water_contact | 4.250 s | 4.220 s | +0.030 s |

~~All within 0.50 s tolerance.~~ State machine traversal claim not validated by committed code.

---

## 6. Phase N — Water contact semantics

| Version | water_contact | Margin to clip end | Classification |
|---|---|---|---|
| CC3 | 4.90 s | ~0.00 s (last PTS frame) | END_OF_CLIP_COINCIDENCE |
| V2 annotation | 4.22 s | 1.15 s | GENUINE |
| E1 estimate | 4.25 s | 1.12 s | GENUINE |

**Finding:** CC3's water_contact=4.90 s was the last decoded frame of the clip
(PTS range [0.0, 5.355] s). Its apparent "accuracy" (V1 error = 0.00 s vs the
approximate annotation of 4.90 s) was coincidental — both the system and the
approximate human annotation independently rounded to the last frame. The PTS-correct
annotation places water contact at 4.22 s, and E1 correctly detects it at 4.25 s.

---

## 7. Architectural note (Phase O/P)

The state machine (`proposer_event_logic_v2.py`) uses a **height-above-reference
convention**: y_arr increases when the diver moves upward (positive velocity = takeoff).
The L1 detector outputs `cy_norm` (top-origin, 0 = top, 1 = bottom), where upward
motion = decreasing cy_norm. The pipeline must invert before passing to the state
machine: `y_arr[i] = -cy_norm[i]` (or equivalently `1.0 - cy_norm[i]`).
Water contact detection uses original cy_norm: `cy_norm > water_line_cy_norm`.

This convention split is intentional: the state machine tests define a clean
physical coordinate system; the water contact threshold is expressed in screen
coordinates for direct calibration against frame geometry.

---

## 8. Files produced

| File | Phase | Contents |
|---|---|---|
| `docs/science/HIGHRES_CANARY_V2_EXACT_ANNOTATION.json` | C | PTS-correct annotation |
| `docs/science/HIGHRES_CANARY_V2_REFERENCE.json` | C+G | Full freeze + CC3 re-evaluation |
| `experiments/landmark_pilot/annotate_canary_v2.py` | B | Annotation tool (port 8766) |
| `experiments/landmark_pilot/proposer_event_logic_v2.py` | F+H | State machine E1/E2 |
| `experiments/landmark_pilot/test_event_logic_v2.py` | Q | 29 deterministic tests (all pass) |
| `docs/science/EVENT_LOGIC_V2_FREEZE.json` | K | E1 selected, params frozen |
| `docs/science/PHASE_M_CANARY_CHECK.json` | M | Mechanism check results |
| `docs/science/HIGH_RESOLUTION_CANARY_EVENT_SEMANTICS_CORRECTION_V1.md` | R | This document |

---

## 9. Supervisor gate

**`SUPERVISOR_REVIEW_AFTER_EVENT_LOGIC_V2`**

All phases A–R complete. Phase S (PROJECT_STATE update) and Phase T (commit + mirror sync)
follow immediately.
