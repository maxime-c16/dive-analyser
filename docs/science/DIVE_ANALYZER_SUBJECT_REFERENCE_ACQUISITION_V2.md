# DIVE_ANALYZER_SUBJECT_REFERENCE_ACQUISITION_V2

**Packet:** `DIVE_ANALYZER_SUBJECT_REFERENCE_ACQUISITION_V2`
**Gate:** `SUPERVISOR_REVIEW_AFTER_SUBJECT_REFERENCE_ACQUISITION_V2`
**Date:** 2026-09-13
**Branch:** `subject-reference-acquisition-v2` (base = integrated canonical
`uiux-overhaul-pro-app` @ d4c3f29, i.e. V1 reconciled + diver-19 hardening)
**Companion JSON:** `docs/science/DIVE_ANALYZER_SUBJECT_REFERENCE_ACQUISITION_V2.json`

## 0. Executive answer

```text
V2 GT-FREE REFERENCE ACQUISITION = FAILED (both allowed formulations)
```

The edited clip DOES carry a consistent, family-stable temporal structure
(action inside the clip body, stable subject visible before the action, large
post-entry padding), but that structure does **not** separate the intended
subject's person hypotheses from the surrounding hypothesis ocean at
floor-conf 0.001. No GT-free acquisition rule — the two pre-registered V2
formulations (A0 clip-relative action ownership, A1 apparatus→water
consistency) plus a bounded stable-anchor→departure-continuation diagnostic —
produced a subject-correct reference at rank 1 on any of the 5 development
dives. Reference acquisition therefore REMAINS the bottleneck, exactly as V1
concluded; the V2 hypotheses did not rescue it.

## 1. Phase 0 — fresh authority + canonical reconciliation

- Starting canonical `uiux-overhaul-pro-app` was `defc6cf` (not the packet's
  assumed `c4c9cfc`): the concurrent UI-U0R audit thread had merged
  (`bc8ace5`, `165eadf`, `278b154`) plus an infra thread's DB-connection-leak
  work was uncommitted in the dirty main worktree. Fresh evidence wins.
- V1 commits verified: `3dafd8b` (parser/data repair) + `1a656c7` (Subject
  Resolution V1 science) on branch `subject-resolution-v1`.
- Integration: clean temporary worktree merge
  (`defc6cf` + `subject-resolution-v1` → merge `a0e09d2`), PROJECT_STATE
  conflict resolved UNION-style, both threads' sections preserved. Main
  worktree realigned file-by-file; the concurrent thread's staged science
  deletions and uncommitted backend/frontend work untouched.
- Production Mac-agent parser verified aligned (RIP reserved-token fix
  present at `/Users/Shared/services/data/diveanalyzer/code/mac-agent/src/metadata.py`,
  20/20 metadata tests).

## 2. Phase 0.2 — DIVER_ID_19 hardening

```text
PHANTOM_DIVER_HARDENING_GREEN
```

- Live DB: `UPDATE divers SET active=false WHERE id=19` — snapshot-proven
  zero collateral mutation (dive counts by diver_id identical before/after:
  {1: 2517, 19: 0}).
- `resolve_diver()` now requires `Diver.active IS TRUE` (generic; no
  RIP-specific branch) and refuses to create a duplicate identity when a
  retired diver owns the canonical name — historical RIP-style input can
  never silently reattach a Dive to diver 19 nor crash on the unique
  canonical_name constraint (caller leaves diver_id NULL).
- Backend container redeployed (mount-based) and verified live:
  `resolve_diver("RIP") -> None` (both create modes); TOM/PAUL/FANNY/SARA/MAT
  resolve to active rows; diver 19 remains directly queryable.
- Tests: `backend/tests/test_divers.py` 9/9; full backend suite failure set
  IDENTICAL to the pristine pre-change image (19 failed / 14 errors are
  pre-existing product test debt, untouched); resolver-touching suites
  (video_sync, mac_agent_sync, data_integrity) 44/44.
- Bounded test-env repair: `analysis.py` postgresql.UUID gets a
  sqlite-compatible variant (Postgres unchanged) so the in-memory sqlite
  harness can create the analysis tables (pre-existing breakage).
- Artifact: `docs/audits/DIVER_ID_19_HARDENING_V2.md`.

## 3. Phase 1 — authorized development cohort

| dive | family | subject authority | GT authority | cache | decision | reason |
|---|---|---|---|---|---|---|
| 1040 | HURDLE | diver 1 (Maxime) | chains+anchors eval-only | D5 fullclip + OSNet | INCLUDE | full authority set |
| 2169 | HURDLE | diver 1 (RIP fixed by V1 repair) | chains+anchors | D5 fullclip + OSNet | INCLUDE | full authority set |
| 2341 | HURDLE | diver 7 (FANNY) | chains+anchors eval-only | D5 fullclip + OSNet | INCLUDE | full authority set |
| 2353 | HURDLE | diver 1 | chains+anchors eval-only | D5 fullclip + OSNet | INCLUDE | full authority set |
| 2541 | HURDLE | diver 1 | chains+anchors eval-only | D5 fullclip + OSNet | INCLUDE | full authority set |
| 133/311/676/2387 | STANDING | product authority OK | temporal-landmark GT only, NO per-frame subject chains, NO multi-person frozen D5 cache | proxies + top-1 traj caches only | EXCLUDE | new D5 inference prohibited this packet; no subject-identity authority |
| 524 | — | AUTHORITY_CONFLICT | none | — | EXCLUDED | standing exclusion |
| 2555 | HURDLE(stress) | screen recording | anchors exist | D5 cache exists | STRESS-ONLY | not loaded, not evaluated |

The multi-person-hypothesis cohort is still exactly the 5 HURDLE dives: the
packet's Phase-1 goal (avoid deriving rules from 5 HURDLE clips) could NOT be
met with frozen caches — reported honestly as a cohort limitation.

## 4. Phase 2/3 — clip-relative time + edited-clip structure

τ = t / clip_duration. Measured (GT for characterization only):

| dive | dur s | τ takeoff | τ water | post-entry τ | subj pre-to cy std |
|---|---|---|---|---|---|
| 1040 | 11.08 | 0.403 | 0.489 | 0.511 | 0.0212 |
| 2169 | 17.98 | 0.359 | 0.428 | 0.572 | 0.0095 |
| 2341 | 10.12 | 0.353 | 0.454 | 0.546 | 0.0262 |
| 2353 | 23.97 | 0.238 | 0.287 | 0.713 | 0.0229 |
| 2541 | 32.53 | 0.539 | 0.573 | 0.427 | 0.0247 |

Findings: the intended dive consistently sits INSIDE the clip body
(τ_water ∈ [0.29, 0.57]; never at clip end); useful pre-dive padding
(0.24–0.54τ) and post-entry padding (0.43–0.71τ) exist in 5/5; the subject is
visible and stable (cy std ≤ 0.027) before takeoff in 5/5. The dive is NOT
centered (τ_takeoff varies 0.24–0.54) and other persons do NOT reliably
occupy different temporal regions (2353's bystander spans the whole clip;
2341's next-diver occupies the post-entry region).

```text
EDITED_CLIP_TEMPORAL_STRUCTURE_STRONG
```

(with the explicit caveat: the structure is real and corpus-consistent but
NOT discriminative between subject and distractor hypotheses — see §6.)

## 5. Phase 4/5 — action-ownership features + board topology

Features (all flow-compensated via the canonical `r5_tracklets_v1.estimate_flow`
background-flow estimator): tracklet span, τ interval, τ onset, stable-window
span, coherent excursion, coherent descent speed, entry-like termination,
terminal/stable flow-compensated cy, median area, mean conf.

Board topology: world-static long-span clusters are plentiful (74–151 per
dive) and every subject preparation position has one within 0.12 normalized
units — but so does nearly everything else; a specific apparatus region is
NOT separable from generic static clusters without hand-coded coordinates.
The coarse water region (terminal cy ≥ 0.45) is usable only as a weak prior.

```text
BOARD_TOPOLOGY_WEAK
```

## 6. Phase 6/7/9 — acquisition results

533–771 acquisition candidates (span ≥ 0.7 s, person-plausible area) per
dive; 1155–3109 raw tracklets. Top-1 by each scorer:

| dive | A0 status | A0 top1 purity | A1 top1 purity | best subject ref rank (A0 / A1) |
|---|---|---|---|---|
| 1040 | FOUND | 0.00 | 0.00 | 11 / 2 |
| 2169 | FOUND | 0.04 | AMBIG 0.04 | 6 / 14 |
| 2341 | FOUND | 0.00 | 0.00 | 5 / 178 |
| 2353 | FOUND | 0.00 | 0.46 | 9 / 2 |
| 2541 | FOUND | 0.00 | 0.00 | 71 / 35 |

`REFERENCE_SUBJECT_CORRECT` (top-1 purity ≥ 0.5): **0 / 5 dives** for both
scorers. Top-k analysis shows subject references DO exist in the candidate
space (best achievable purity within top-20: 0.65–1.0 on 4/5 dives under A0)
but the hand-crafted ranking does not surface them at rank 1. Bounded
continuation diagnostic (stable person-sized anchor + nearby later excursion
arc) also failed (top ranks all wrong-subject).

## 7. Phase 8 — frozen matcher replay (unchanged pipeline)

Downstream matching with the V2-acquired references (frozen OSNet
reference-conditioned replay, pipeline unchanged):

| dive | D5 top-1 | H1a | oracle stable ref | V2 A0 | V2 A1 |
|---|---|---|---|---|---|
| 1040 | 0.106 | 0.000 | 0.689 | 0.000 | 0.000 |
| 2169 | 0.963 | 0.880 | 0.873 | 0.000 | 0.000 |
| 2341 | 0.022 | 0.364 | 0.707 | 0.000 | 0.000 |
| 2353 | 0.005 | 0.730 | 0.788 | 0.000 | 0.000 |
| 2541 | 0.149 | 0.005 | 0.859 | 0.004 | 0.000 |

The oracle ceiling is unchanged (V1 values); V2 references are wrong
references, so downstream matching fails exactly as acquisition purity
predicts — acquisition failure is NOT hidden by the matcher.

## 9. Phase 11 — leakage audit

| feature | class |
|---|---|
| frozen D5 candidate cache (boxes/conf) | PRODUCT_AVAILABLE_AT_INFERENCE |
| OSNet x1.0 embeddings (frozen cache, matching stage) | PRODUCT_AVAILABLE_AT_INFERENCE |
| tracklets / association gates | GENERIC_VIDEO_DERIVED |
| background flow (camera-motion compensation) | GENERIC_VIDEO_DERIVED |
| stable windows / excursion / descent / entry-like / terminal cy / areas / conf | GENERIC_VIDEO_DERIVED |
| τ = t/clip_duration and clip-relative bands | GENERIC_VIDEO_DERIVED |
| GT chains, GT phase times | SCIENTIFIC_GT_DERIVED — EVALUATION ONLY |

Enforcement: the inference store strips `gt_eval_only` from the frozen
artifact; the inference functions never receive the Evaluator. Automated
tests: tamper-free determinism, source-level assertions that no inference
function references GT artifacts, and GT-free-store stripping.

## 10. Phase 12 — ablation (A0, feature groups)

Dropping ANY single group (clip_relative_time / motion / termination /
track_quality) leaves top-1 correct count at 0/5 — the baseline itself is
0/5, so ablation cannot localize a brittle shortcut: the failure is across
the whole feature space, not one term.

## 11. Phase 13 — abstention

```text
ABSTENTION_NOT_INFORMATIVE
```

Margin thresholds 0 / 0.02 / 0.05 / 0.1 keep coverage at 5/5 with subject
precision 0.0; at 0.2 coverage drops to 3/5 and precision is still 0.0.
Abstention removes nothing catastrophic because the top-1 errors are not
margin-thin ties — they are confident wrong picks over a noise-dominated
hypothesis ocean.

## 11. Phase 17/18 — subject trajectory + Event Logic replay

Subject trajectory status is UNCHANGED from V1 (subject reachable in
tracklets, coverage ≈ 1.0; resolution quality still capped by reference
acquisition). With no V2 trajectory improvement:

```text
EVENT_LOGIC_REPLAY_NOT_JUSTIFIED
```

## 12. Phase 14/15/16 — learning decision

- Good subject references exist in the tracklet space (best achievable
  purity 0.65–1.0 within top-20 on 4/5 dives) — the raw material for a
  learned acquisition scorer exists.
- Hand-crafted signals show real but INSUFFICIENT ranking signal
  (best-subject ranks 2–14 on 4/5 dives under A1; never rank 1).
- But the cohort is 5 dives × 1 family (HURDLE) × 2 athletes × 5 sessions;
  positives ≈ 5–10 reference candidates. Per Phase 16:

```text
LEARNING_DECISION = NO_TRAINING_YET
DATA_SUFFICIENCY  = DATA_TOO_SMALL_FOR_LEARNING
```

(Conservative per packet: five HURDLE dives alone cannot support a robust
universal learned scorer, and a learner trained on one family would not be
evaluable for generalization.)

## 13. Stress / exclusions

- 2555: `SCREEN_RECORDING_STRESS_CASE` — not loaded, not evaluated.
- 524: `AUTHORITY_CONFLICT_EXCLUDED` — untouched.
- Paris: `NOT_ACCESSED_FOR_DEVELOPMENT` — zero development frames.
- Protected holdout / internal eval: untouched.

## 14. Resource results

- New D5 inference: 0. New embeddings: 0. Model training: 0. New labels: 0.
- B2 reads: 0 (no media touched). B2 writes: 0.
- Peak RAM: OSNet npz (579,709 × 512 float32 ≈ 1.2 GB) dominated; single
  process, disk-backed caches only, no video decode required (pure cache
  science). Long compute: none > 10 min; no `caffeinate` needed beyond
  routine runs. Cleanup: none required (no temp media).

## 15. What exactly remains the blocker

> The intended subject's action arc is present and structurally consistent
> in every clip, but at floor-conf 0.001 the hypothesis ocean contains many
> decoy arcs (noise fragments, static-structure movers, bystanders) with
> indistinguishable local motion/region signatures. No GT-free ranking over
> single-tracklet (or stable-anchor→arc) features separates them. This now
> holds across 8 V1 rules + 2 V2 formulations + 1 continuation diagnostic.

## 16. Scientific recommendation

1. Widen the multi-person cohort FIRST (new frozen D5 fullclip candidate
   caches for the STANDING dives 133/311/676/2387 + any ARMSTAND dives —
   requires a NEW bounded D5-inference packet; this packet's 0-inference
   constraint forbade it).
2. Then a bounded LEARNED reference-acquisition scorer
   (TRAIN_REFERENCE_ACQUISITION_SCORER_NEXT) on tracklet units + clip-relative
   context + motion/topology features, labels from frozen GT chains, LOSO by
   dive, no random frame splits — only once the cohort spans ≥ 2 families.
3. Do NOT train a subject-conditioned matcher yet (downstream is not the
   dominant failure; acquisition is).

## 17. Tests

`experiments/subject_resolution/test_subject_reference_acquisition_v2.py`
— 11/11 pass (cohort determinism + firewalls, GT stripping + source-level
leakage guards, relative-time normalization, deterministic ranking,
abstention, soft junk preservation, A1 region-only check). Regression:
mac-agent metadata 20/20, V1 audit 13/13. Zero failures.

## 18. Authorities mutated

```text
SCIENTIFIC_AUTHORITIES_MUTATED = NO   (D5 frozen cache read-only; Event Logic untouched)
MEDIA_BACKBONE_MUTATED        = NO   (0 B2 reads/writes)
```
