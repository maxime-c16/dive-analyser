# Dive Analyzer — Action-Spanning Track Association V2

Packet: `DIVE_ANALYZER_ACTION_SPANNING_TRACK_ASSOCIATION_V2`
Gate: `SUPERVISOR_REVIEW_AFTER_ACTION_SPANNING_TRACK_ASSOCIATION_V2`
Status: **`ACTION_SPANNING_ASSOCIATION_V2_PARTIAL`**
Next: **`IMPROVE_ASSOCIATION_REPRESENTATION_NEXT`**
Companion metrics: `DIVE_ANALYZER_ACTION_SPANNING_TRACK_ASSOCIATION_V2.json`

## 1. Mission and outcome

V1 proved bounded endpoint stitching cannot reconstruct action-spanning
trajectories (`KNOWN_DIVE_TRACK_RECALL = 1/15`, strong coverage `0/15`).
V2 reformulated association as trajectory decoding over an overlap-aware
fragment lattice with top-K path preservation (no identity, no GT, no
connected-component collapse).

Outcome: representation genuinely improved, retention did not.

- `ACTION_SPANNING_SUBJECT_TRAJECTORY_RECALL = 0/15` (criterion: retained
  path is subject-corresponding with `>= 75%` subject-anchor coverage).
- Decoded-pool subject coverage materially exceeds V1 merged best on 10+
  clips (2169: `0.795` vs `0.194`; 2541: `0.584` vs `0.027`;
  1040: `0.547` vs `0.031`; 2583: `0.467` vs `0.000`;
  2387: `0.385` vs `0.231`; 676: `0.444` vs `0.333`).
- Lattice transition recall is `0.83–1.00` on 9 clips: the subject
  trajectory is pairwise representable, but beam search cannot chain it
  into the top 5, and identity-free ranking is Pareto-dominated by
  static/wanderer hypotheses.
- A1 (frozen OSNet local appearance) executed on 10/15 clips with a
  measured null result: handoff appearance does not separate
  subject–subject from other handoffs (mean delta `<= 0.03`).

## 2. Authorities (all frozen, all verified in preflight)

- Canonical base `8964f7d1258d5160c0f42e6db80521a12a148747`
  (branch `uiux-overhaul-pro-app`).
- V1 implementation + report byte-identical to canonical
  (`multi_track_action_v1.py`, `DIVE_ANALYZER_MULTI_TRACK_DIVE_ACTION_V1.json`).
- Frozen files: `phase_subject_candidate_quality_v3.py`
  (`9fc8dcbc…`), `proposer_event_logic_v3_c0.py` (`9c507719…`),
  `r5_tracklets_v1.py`, `proposer_event_logic_v2_1.py`,
  `subject_reference_acquisition_v2.py` (V1 `authorities()` green).
- Caches: hurdle `3bed1aaf…`, cohort `b2f01e41…`, indep `d945fc04…`;
  D5 `MODEL_SHA 82b420c4…` with floor `(0.001, 0.45, 640, 200)`;
  target chains `11d075be…`; L1A `63` anchors (`d805aacc…`);
  L1B `180` anchors (`dc958909…`).
- V1 baseline reproduced exactly before experimentation:
  V1 suite `14 passed`, recall `1/15`, strong `0/15`,
  totals `34,320` raw / `6,490` merged.

## 3. Fragmentation taxonomy (GT evaluation only)

Every clip exhibits overlapping alternatives and/or interleaved fragments;
union subject coverage is `>= 0.85` on 12/15 clips. The failure is
association, not perception — except where noted.

| dive | anchors | union | touching frags | overlap% | interleave | switch frags | classes |
|------|---------|-------|----------------|----------|------------|--------------|---------|
| 1040 | 161 | 1.000 | 44 | 0.45 | 0.24 | 27 | OVERLAPPING_ALTERNATIVES+ASSOCIATION_SWITCH+LOW_SUPPORT |
| 1304 | 10 | 0.900 | 16 | 0.34 | 1.00 | 0 | TEMPORAL_GAP+OVERLAPPING+INTERLEAVED+LOW_SUPPORT |
| 133 | 7 | 0.857 | 10 | 0.67 | 0.40 | 1 | TEMPORAL_GAP+OVERLAPPING+INTERLEAVED+SWITCH+LOW_SUPPORT |
| 2169 | 434 | 1.000 | 74 | 0.78 | 0.19 | 54 | OVERLAPPING_ALTERNATIVES+ASSOCIATION_SWITCH |
| 2204 | 13 | 0.615 | 14 | 0.33 | 0.86 | 0 | TEMPORAL_GAP+OVERLAPPING+INTERLEAVED+LOW_SUPPORT |
| 2223 | 20 | 0.500 | 14 | 0.54 | 1.00 | 0 | TEMPORAL_GAP+OVERLAPPING+INTERLEAVED+LOW_SUPPORT |
| 2341 | 273 | 1.000 | 119 | 0.49 | 0.75 | 89 | OVERLAPPING+INTERLEAVED+SWITCH+LOW_SUPPORT |
| 2353 | 411 | 1.000 | 58 | 0.82 | 0.28 | 50 | OVERLAPPING_ALTERNATIVES+ASSOCIATION_SWITCH+LOW_SUPPORT |
| 2387 | 13 | 1.000 | 18 | 0.65 | 0.33 | 6 | TEMPORAL_GAP+OVERLAPPING+INTERLEAVED+SWITCH |
| 2526 | 18 | 0.944 | 31 | 0.78 | 0.94 | 3 | OVERLAPPING+INTERLEAVED+SWITCH+LOW_SUPPORT |
| 2541 | 262 | 1.000 | 48 | 0.36 | 0.29 | 27 | OVERLAPPING_ALTERNATIVES+ASSOCIATION_SWITCH+LOW_SUPPORT |
| 2583 | 15 | 0.933 | 32 | 0.83 | 0.31 | 9 | TEMPORAL_GAP+OVERLAPPING+INTERLEAVED+SWITCH+LOW_SUPPORT |
| 2839 | 29 | 0.724 | 29 | 0.23 | 0.80 | 3 | TEMPORAL_GAP+INTERLEAVED+SWITCH+LOW_SUPPORT |
| 311 | 29 | 0.966 | 8 | 0.89 | 0.89 | 5 | TEMPORAL_GAP+OVERLAPPING+INTERLEAVED+SWITCH+LOW_SUPPORT |
| 676 | 9 | 0.889 | 17 | 0.73 | 0.43 | 2 | TEMPORAL_GAP+OVERLAPPING+INTERLEAVED+SWITCH |

`NO_OBSERVATION` never triggers (minimum union `0.500`).

## 4. Lattice (Phase 3–5)

Nodes: all frozen R5 raw PersonTrack fragments (nodes only carry
inference-available data: interval, boxes, motion, D5 support).
Three deterministic edge types, all gated by frozen constants
(`interp_max_gap_s = 0.30`, `SUPPORT_RADIUS = 0.06`,
`LOG_SIZE_MAX + JITTER_S`):

- **gap**: disjoint intervals, gap `<= 0.30 s`, frozen `_gate_ok` plus
  constant-velocity endpoint residual `<= 0.06` (V1 gates, mutual-best
  restriction dropped).
- **overlap**: interval overlap with a handoff frame where both carriers
  are observed and agree (`dist <= 0.06`, frozen size gate), plus
  forward-prediction motion-direction consistency (`<= 0.06`).
  Two simultaneously inconsistent boxes are never concatenated.
- **interleave** (the structural fix): overlapping intervals with NO
  common observed frame (strict frame alternation — V1 and naive overlap
  edges are both blind here). Handoff pair within frozen `MISS_MAX_S`
  (`0.08 s`), frozen `_gate_ok` under zero-order hold, `dist <= 0.06`.

Fan-out capped at 24 per type per node (documented implementation bound).
Edge inventory per clip is in the JSON (`gap_edges`, `overlap_edges`,
`interleave_edges`; interleave dominates: 5k–32k).

## 5. A0 continuity decoder (Phase 7)

Beam search (`BEAM_WIDTH = 512`, `MAX_FRAGMENTS_PER_PATH = 64`) over
segment-clipped carriers (each carrier contributes only its inter-handoff
segment, so post-switch boxes never leak into a path). Identity-free
score, all weights predetermined and dimensionless: completeness
(span + density) + `0.25` mean D5 confidence + vertical-range motion
(`RANGE_SCALE_CY = 0.5`) − mean edge cost, plus frozen V3-C0 motion
evidence (excursion / `0.5` + `0.25` complete sequence) after replay.
Top-`K = 5` diverse paths (near-duplicate suppression at `0.95`
box-agreement similarity only; simultaneous distinct people always kept).

## 6. A1 local appearance decoder — EXECUTED, null result

Continuity + frozen OSNet handoff compatibility (mean cosine over
cross-carrier box pairs within ±2 frames; no gallery, no learning, no GT),
weight `1.0`, applied in beam prefix scores and final ranking on the 10
clips with frozen embedding caches (hurdle group has no cache: A0
fallback, documented in per-dive `formulation`).

Measured separation (subject–subject vs other handoffs, per clip):

| dive | subj mean | other mean | | dive | subj mean | other mean |
|------|-----------|------------|-|------|-----------|------------|
| 133 | 0.647 | 0.641 | | 2387 | 0.639 | 0.658 |
| 311 | 0.646 | 0.665 | | 2526 | 0.935 | 0.969 |
| 1304 | 0.862 | 0.909 | | 2583 | 0.970 | 0.967 |
| 2204 | 0.933 | 0.931 | | 2839 | 0.919 | 0.933 |
| 2223 | 0.964 | 0.935 | | 676 | 0.617 | 0.626 |

No separation anywhere (delta `<= 0.03`, often other higher). Geometric
gating already enforces visual similarity (same location/size ⇒ similar
1.3-padded crop), so local appearance is geometry-redundant and cannot fix
crowded-scene ranking. No new embeddings were extracted; hurdle extraction
was not justified given the null on all 10 cached clips.

## 7. Association evaluation (HUMAN GT, paths frozen first)

| dive | union | V1 best | V2 pool best | V2 retained best | trans recall | limitation |
|------|-------|---------|--------------|------------------|--------------|------------|
| 1040 | 1.000 | 0.547 | 0.547 | 0.000 | 0.931 | ASSOCIATION_LIMITED |
| 1304 | 0.900 | 0.000 | 0.200 | 0.000 | 0.500 | ASSOCIATION_LIMITED |
| 133 | 0.857 | 0.429 | 0.429 | 0.000 | 0.800 | ASSOCIATION_LIMITED |
| 2169 | 1.000 | 0.788 | 0.795 | 0.000 | 0.995 | ASSOCIATION_LIMITED |
| 2204 | 0.615 | 0.154 | 0.154 | 0.000 | 0.286 | MIXED |
| 2223 | 0.500 | 0.000 | 0.000 | 0.000 | 0.222 | MIXED |
| 2341 | 1.000 | 0.037 | 0.201 | 0.000 | 0.915 | ASSOCIATION_LIMITED |
| 2353 | 1.000 | 0.037 | 0.036 | 0.000 | 0.932 | ASSOCIATION_LIMITED |
| 2387 | 1.000 | 0.231 | 0.385 | 0.000 | 0.833 | ASSOCIATION_LIMITED |
| 2526 | 0.944 | 0.111 | 0.111 | 0.000 | 0.500 | ASSOCIATION_LIMITED |
| 2541 | 1.000 | 0.531 | 0.584 | 0.000 | 0.935 | ASSOCIATION_LIMITED |
| 2583 | 0.933 | 0.400 | 0.467 | 0.000 | 0.923 | ASSOCIATION_LIMITED |
| 2839 | 0.724 | 0.138 | 0.172 | 0.000 | 0.300 | MIXED |
| 311 | 0.966 | 0.207 | 0.207 | 0.000 | 0.852 | ASSOCIATION_LIMITED |
| 676 | 0.889 | 0.333 | 0.444 | 0.000 | 1.000 | ASSOCIATION_LIMITED |

(V1 best = max raw/merged; V2 pool best = best subject-corresponding path
over the full decoded pool; retained best = best over top-5. Union
recomputed from raw caches, cross-checked against the V1 report.)

## 8. Flight-phase finding (the true bottleneck)

Where HUMAN takeoff/water-contact authority exists, flight-anchor union
coverage is ~100% (1040: 29/29; 2169: 49/49; 2341: 61/61; 2353: 72/72;
2541: 27/27; 2387: 3/3; 676: 2/2) — perception sees the diver in flight.
But flight anchors are shattered across dozens of single-anchor
micro-fragments (2169: 49 anchors / 54 fragments; 2341: 61 / 52;
2353: 72 / 34). Pairwise chaining is representable (transition recall
above) yet beam search cannot assemble 20–60-handoff flight chains into
the top 5. 2204/2223/2839 (no HUMAN flight authority, union 0.50–0.72,
multi-second anchor gaps) are MIXED/perception-limited.

## 9. Metric caveat (prep-dominated recovery criterion)

The preserved `>= 75%` all-anchor criterion is gameable on hurdle clips:
2169 preparation anchors alone are 79% of all anchors, so a static
prep-only fragment (V1 best raw `0.788`, `NON_DIVE`) nearly "recovers" by
letter while missing the flight entirely. V2's 2169 pool-best (`0.795`,
2 fragments, `AMBIGUOUS`) has the same property. Recovery must become
flight-phase-aware before it can gate analytics; retained as exploratory
criterion per packet, not weakened.

## 10. Downstream gates

- Frozen Event Logic V3-C0 replayed unchanged on all retained paths (no
  tuning). Retained DIVE_LIKE counts per clip: 1040: 1; 1304: 5; 133: 0;
  2169: 3; 2204: 1; 2223: 4; 2341: 0; 2353: 2; 2387: 5; 2526: 0; 2541: 0;
  2583: 2; 2839: 3; 311: 0; 676: 5. Complete sequences on unattributed
  arcs remain diagnostics, not correctness labels (V1 lesson stands).
- Subject event accuracy: `NO_RETAINED_SUBJECT_PATHTRACK` on all clips
  with HUMAN authority (nothing recovered to score).
- Analytics readiness: `TRAJECTORY_NOT_READY = 15`,
  `RECOVERED_EVENT_UNVERIFIED = 0`, `AND_EVENTS_PLAUSIBLE = 0`. No frozen
  event-accuracy acceptance threshold exists; none invented.
- Overlay: `TRACK_STABILITY_STILL_INSUFFICIENT` (strict rule: needs a
  recovered path with longest gap `<= 0.30 s` and purity `1.0`).
- Multi-path: 5 retained paths per clip, temporally overlapping with
  disjoint boxes everywhere → `SYNCHRO_REPRESENTABLE`. Plausible
  non-subject arcs are preserved, not collapsed.
- Other-action GT: `OTHER_ACTION_GT_STILL_PREMATURE` — labels cannot fix
  a search/representation failure. Minimal future plan (post
  representation-next): HUMAN flight windows (takeoff/water_contact,
  existing grammar) for top retained arcs of 3–4 crowded clips to measure
  multi-path precision.
- Identity/reference lines: `FROZEN_DEFERRED` / `DEFERRED`. No identity
  science in this packet.

## 11. Resources and compliance

Cache-only. `D5 inference = 0`, `training = 0`, `new embeddings = 0`,
`new labels = 0`, `B2 reads/writes = 0`, `media decodes = 0`.
Runtime `691 s`, peak RAM `1.7 GB` (Apple M2 class, sequential,
disk-backed). Frozen D5/Event Logic/GT authorities untouched; B2
unmutated; 524/2555/Paris/internal-eval/holdout untouched. Tests: V2
suite 16 passed; V1 suite 14 passed; zero packet-owned failures.

## 12. Success questions (answers)

1. Fragmentation causes: overlapping alternatives + interleaved fragments
   on every clip; association switches inside R5 fragments; flight
   shattered into single-anchor micro-fragments; low D5 support
   throughout (mean subject-box conf often `< 0.05`).
2. Can overlaps/interleaves be decoded into coherent paths? Pairwise yes
   (transition recall `0.83–1.00` on 9 clips; interleave edges unlock
   stitching V1 could not represent); full action-spanning chains no —
   beam search cannot assemble 20–60-handoff flight chains.
3. Does top-K preserve the subject? No (`0/15` retained; best subject
   ranks 35–600+): subject chains are Pareto-dominated on every
   identity-free signal; alternatives are not collapsed (5 diverse,
   synchro-representable paths per clip).
4. Decoded-vs-union headroom: §7 table. Pool-best reaches union only on
   1040 (0.547/1.000 no — nowhere fully); largest absolute gains on 2169,
   2541, 1040, 2583.
5. Perception-limited: 2204/2223/2839 (MIXED); all others
   ASSOCIATION_LIMITED by the union rule, with flight-phase shattering as
   the mechanism.
6. Event Logic accuracy after recovery: untestable — nothing recovered.
7. Box overlays: not viable (`TRACK_STABILITY_STILL_INSUFFICIENT`).
8. Per-track analysis: not ready (15/15 `TRAJECTORY_NOT_READY`).
9. Other-dive labels: still premature (plan in §10).
10. Next true bottleneck: **flight-phase chaining** — representable
    pairwise, unsearchable by continuity beam, unrankable identity-free;
    needs flight-anchored or frame-level decoding representation plus
    flight-phase validation.

## 13. Verdicts

- `ACTION_SPANNING_ASSOCIATION_V2_PARTIAL`
- `IMPROVE_ASSOCIATION_REPRESENTATION_NEXT`
- `IDENTITY_LINE = FROZEN_DEFERRED`, `REFERENCE_ACQUISITION = DEFERRED`
- `SUPERVISOR_REVIEW_AFTER_ACTION_SPANNING_TRACK_ASSOCIATION_V2`
