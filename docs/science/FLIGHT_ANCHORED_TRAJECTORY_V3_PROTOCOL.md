# Flight-Anchored Trajectory V3 — Protocol Freeze

Packet: `DIVE_ANALYZER_FLIGHT_ANCHORED_TRAJECTORY_V3`
Version: `FLIGHT_ANCHORED_TRAJECTORY_V3_F0F1_V1`
Status: **FROZEN — no post-evaluation tuning.**
Rule: this artifact was committed BEFORE any HUMAN subject-result
evaluation. All decoder constants, NULL cost, transition gates, motion
objective, beam/state limits, top-K policy, and extension policy below
are fixed. Any change requires a new protocol version, never an edit.

## 1. Architecture

```text
frame-level person proposals (frozen D5 floor, cache-only)
        ↓
GT-free flight-core decoding (F0: frame-level flight lattice)
        ↓
small set of plausible flight paths (ranked by flight-motion Q)
        ↓
extend backward through preparation (F1, generic continuity)
        ↓
extend forward through entry/post (F1, generic continuity)
        ↓
action-spanning DiveTracks (1–5 retained)
```

No identity. No appearance. No GT events in inference. No `diver_id`.
No per-dive/family tuning. No new labels, training, embeddings, media.

## 2. Inference inputs (GT-free)

- Frozen D5 floor candidate caches (MODEL_SHA `82b420c4…`, floor
  `(0.001, 0.45, 640, 200)`): per frame `(pts_s, fi, [{cx,cy,bw,bh,conf}])`.
- Recorded frame PTS authority (strictly increasing; one-based sequential
  frame cache enforced, else hard error).
- Nothing else. PersonTrack IDs are not read by inference.

## 3. Camera-flow estimation (GT-free, R5 analogue)

Per frame-step, the robust component-wise median velocity of the
top-FLOW_TOP confidence candidates' nearest-forward displacement.
Cumulative offsets give flow-compensated coordinates `(ccx, ccy)` in
which all dynamics (gates, speeds, Q) operate. Rationale: the diver is
the object that moves DIFFERENTLY from the world; absolute coordinates
confound diver motion with camera pan. Outputs always carry raw boxes.

## 4. Frame lattice

Per frame: top-FRAME_CAP candidates by `(conf desc, cx, cy, bw, bh)` plus
up to MOVER_KEEP extra candidates ranked by flow-relative forward motion
(nearest-candidate displacement into the next frame, per second).
Deterministic lattice order: confidence members first, then movers.
Full-floor counts are retained for the raw-union observation upper bound.

## 5. NULL / NO_OBSERVATION state

Explicit per-frame NULL successor with deterministic cost NULL_COST.
A path may remain unmatched while the time since its last observation
stays within NULL_MAX_S (reused frozen V3-C0 interpolation limit).
NULL_COST rationale (preregistered, never tuned against subject GT):
above a good match (residual ~0.02–0.05 plus small size/accel terms) so
any plausible continuation is preferred, below teleport/hijack jumps
(~0.2+) so bounded true disappearances stay representable without
forcing the path onto another human.

## 6. Local transitions (generic evidence only)

PTS delta, predicted-center continuity (constant-velocity EWMA,
VEL_ALPHA), bbox scale continuity (SIZE_TOL), velocity/direction
continuity (soft acceleration penalty, coherent-motion bonus),
support/confidence. Hard gates reuse frozen R5/V3 scales
(V_MAX_CY_S/CX_S, VEL_MAX, GATE_BASE + GATE_VEL·|v|·dt, SIZE_TOL).
No appearance (V2 proved local frozen-OSNet similarity geometry-redundant).

## 7. Flight-motion objective Q (core ranking)

For a candidate core window (observations + NULLs):

```text
Q = W_EXCURSION · excursion + W_DESCENT · descent + W_LATERAL · lateral
    − W_SMOOTH · smooth_pen − W_NULL · null_frac − W_STATIC · static_frac
    + W_CONF · mean_conf
```

- excursion: flow-compensated vertical range / RANGE_NORM.
- descent: max(0, cy_last − cy_first) / RANGE_NORM (descent progression;
  cy grows downward; camera-tracked dives contribute via excursion).
- lateral: |cx_last − cx_first| / RANGE_NORM (down-weighted: coherent
  lateral drift alone must not outrank a vertical arc).
- smooth_pen: mean |acceleration| / ACC_NORM, clipped at 2 (bounded
  acceleration; arc-capable, teleport-killing).
- null_frac: missing-observation fraction (bounded gaps tolerated).
- static_frac: fraction of steps slower than STATIC_SPEED (long static
  occupancy is penalized by construction — preparation can never
  dominate flight ranking).
- mean_conf: detector support (small subordinate term).
- Windows are constrained to CORE_MIN_S ≤ duration ≤ CORE_MAX_S
  (generous domain envelope for an airborne phase; not clip-derived).

## 8. Search policy (F0)

Temporally stratified multi-start beam: starts every START_STRIDE frames
(~0.5–1.0 s; starts that cannot host a CORE_MIN_S core are skipped).
Each start seeds SEED_TOP confidence candidates plus SEED_MOVERS mover
candidates, then extends forward frame-by-frame with successor fan-out
capped at MAX_SUCC_PER_PATH plus NULL.

Dual-population retention per frame (the required anti-domination
property): STATIC_SLOTS slots rank all paths by accumulated cost;
DYNAMIC_SLOTS slots are reserved for latched movers
(EWMA speed ≥ SPEED_LATCH, or age ≤ LATCH_GRACE_FRAMES) ranked by cost
with a per-frame motion advantage W_DYN. Plausible fast-motion paths
cannot be eliminated solely because stationary tracks score well —
movers compete in a protected population. Total live hypotheses per
start never exceed SEARCH_BEAM_WIDTH.

Pool triage per start: top POOL_PER_START/2 latched movers plus the
cheapest static paths (POOL_PER_START total). Cross-start dedupe by full
observation skeleton (frame + candidate identity).

F0 core extraction: per pool path, the argmax-Q contiguous subsegment
(vectorized expanding-window scan); cores ranked by Q; greedy
near-duplicate suppression at DUP_AGREE box agreement (simultaneous
distinct people always kept); head kept for extension.

## 9. Top-K policy (F1)

FINAL_TOP_K = 5 retained product tracks (product shape 1–5, matching
V1/V2). SEARCH_BEAM_SIZE (64 per start, up to hundreds pooled) is
strictly distinguished from FINAL_ANALYSIS_TRACK_COUNT (5). K was not
tuned with subject GT.

## 10. F1 bidirectional extension

Each frozen F0 core is extended backward (prep recovery) and forward
(entry/post recovery) by greedy gated nearest-continuation with the
same frozen gates and NULL bound. Extension carries no score: final
order IS the F0 Q order (subordinate by construction). A weak flight
core can never be reranked into first place by its preparation.

## 11. Output contract

Each retained track reuses the frozen describe path
(`multi_track_action_v1.describe` over a frame-level observation set),
so trajectory/coverage/gap fields, frozen V3 support quality, and frozen
Event Logic V3-C0 replay are byte-identical machinery to V1/V2. Added
F3 fields: `path_id`, `path_rank`, `path_score` (Q),
`flight_objective_parts`, `flight_core_interval`, `handoff_provenance`
(frame/gap steps with NULL runs explicit), `handoff_count`,
`null_run_count`, `association_provenance`
(`F3_FRAME_LATTICE_FLIGHT_CORE`), `formulation` (F1). `person_track_refs`
is empty by design (decoding never uses PersonTrack membership);
`track_id` is a deterministic `f3-` hash of the ordered observation set.
`analysis_available` remains false. Manual-selection contract fields
(path_id, representative frame, time interval, box trajectory,
flight-core interval, analysis availability) are all present.

## 12. Evaluation rules (GT-only, post-freeze)

- Flight window for HUMAN-authority clips: HUMAN takeoff → HUMAN
  water-contact ± 0.05 s (existing frozen authority; never in inference).
  Clips without authority: inference identical; flight metrics
  `GT_UNAVAILABLE`; general subject-anchor coverage still reported.
- Primary: FLIGHT_PHASE_SUBJECT_TRAJECTORY_RECALL — retained path with
  ≥75% HUMAN subject-anchor coverage inside the flight window (purity
  reported separately, never hidden). Secondary: FULL_ACTION coverage.
- Perception vs representation (preregistered cutoffs mirroring V2):
  flight union < 0.50 → FLIGHT_OBSERVATION_LIMITED; flight recovered but
  full-action not → FULL_ACTION_EXTENSION_LIMITED; union ≥ 0.75 with no
  flight recovery → FLIGHT_ASSOCIATION_LIMITED; else MIXED.
- Raw-union upper bounds: full-floor union (V1 report) AND capped-lattice
  union (recomputed) per dive.
- Event Logic V3-C0 replayed unchanged on frozen full-action paths only;
  event accuracy reported signed + absolute where subject flight is
  recovered and HUMAN authority exists; no new thresholds.
- Overlay: strict continuity rule (recovered path, longest gap ≤ 0.30 s,
  purity 1.0) or TRACK_STABILITY_STILL_INSUFFICIENT.

## 13. Frozen constants

| constant | value | status |
|---|---|---|
| F3_VERSION | 'FLIGHT_ANCHORED_TRAJECTORY_V3_F0F1_V1' | preregistered F3 |
| FRAME_CAP | 50 | preregistered F3 |
| MOVER_KEEP | 10 | preregistered F3 |
| SEED_TOP | 12 | preregistered F3 |
| SEED_MOVERS | 6 | preregistered F3 |
| START_STRIDE | 30 | preregistered F3 |
| SEARCH_BEAM_WIDTH | 64 | preregistered F3 |
| STATIC_SLOTS | 32 | preregistered F3 |
| DYNAMIC_SLOTS | 32 | preregistered F3 |
| SPEED_LATCH | 0.15 | preregistered F3 |
| LATCH_GRACE_FRAMES | 3 | preregistered F3 |
| W_DYN | 1.0 | preregistered F3 |
| POOL_PER_START | 8 | preregistered F3 |
| MAX_SUCC_PER_PATH | 6 | preregistered F3 |
| NULL_COST | 0.2 | preregistered F3 |
| NULL_MAX_S | 0.3 | preregistered F3 |
| W_SIZE | 0.5 | preregistered F3 |
| W_ACC | 0.1 | preregistered F3 |
| W_CONF_CONT | 0.05 | preregistered F3 |
| W_MOVE | 0.05 | preregistered F3 |
| MOVE_NORM | 0.8 | preregistered F3 |
| FLOW_TOP | 20 | preregistered F3 |
| CORE_MIN_S | 0.3 | preregistered F3 |
| CORE_MAX_S | 3.0 | preregistered F3 |
| W_EXCURSION | 1.0 | preregistered F3 |
| W_DESCENT | 0.5 | preregistered F3 |
| W_LATERAL | 0.25 | preregistered F3 |
| W_SMOOTH | 0.25 | preregistered F3 |
| W_NULL | 1.0 | preregistered F3 |
| W_STATIC | 0.5 | preregistered F3 |
| W_CONF | 0.1 | preregistered F3 |
| STATIC_SPEED | 0.05 | preregistered F3 |
| FINAL_TOP_K | 5 | preregistered F3 |
| DUP_AGREE | 0.95 | preregistered F3 |
| RADIUS | 0.06 | reused frozen |
| V_MAX_CY_S | 1.5 | reused frozen |
| V_MAX_CX_S | 1.2 | reused frozen |
| SIZE_TOL | 0.7984573603642703 | reused frozen |
| VEL_ALPHA | 0.35 | reused frozen |
| GATE_BASE | 0.05 | reused frozen |
| GATE_VEL | 1.0 | reused frozen |
| VEL_MAX | 1.4 | reused frozen |
| ACC_NORM | 3.5 | reused frozen |
| RANGE_NORM | 0.5 | reused frozen |

## 14. Formulation status

- F0 (frame-level flight lattice): implemented, frozen, EXECUTED.
- F1 (flight-seed bidirectional extension): implemented, frozen, EXECUTED
  (extension is integral to every retained track; rank-subordinate).
