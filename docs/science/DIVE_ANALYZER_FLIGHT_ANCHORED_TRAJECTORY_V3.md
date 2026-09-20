# Dive Analyzer — Flight-Anchored Trajectory V3

Packet: `DIVE_ANALYZER_FLIGHT_ANCHORED_TRAJECTORY_V3`
Gate: `SUPERVISOR_REVIEW_AFTER_FLIGHT_ANCHORED_TRAJECTORY_V3`
Status: **`FLIGHT_ANCHORED_TRAJECTORY_V3_PARTIAL`**
Next: **`IMPROVE_DIVE_ACTION_VALIDATION_NEXT`**
Protocol: `FLIGHT_ANCHORED_TRAJECTORY_V3_PROTOCOL.md` (frozen before GT evaluation)
Companion metrics: `DIVE_ANALYZER_FLIGHT_ANCHORED_TRAJECTORY_V3.json`

## 1. Mission and outcome

V2 proved fragment-level continuity ranking cannot surface subject flight
chains (`ACTION_SPANNING_SUBJECT_TRAJECTORY_RECALL = 0/15` retained; the
pool contains subject chains — 2169: 0.795 — that identity-free ranking
buries). V3 replaced prep-dominated fragment-path ranking with a
flight-anchored representation: frame-level proposal lattice → GT-free
flight-core decoding (F0) → bidirectional prep/entry extension (F1) →
action-spanning DiveTracks. No identity, no appearance, no GT in inference.

Outcome: the representation genuinely works — chaining now finds coherent
high-motion arcs — but subject *selection* among competing flights fails.

- `FLIGHT_PHASE_SUBJECT_TRAJECTORY_RECALL = 1/9` (criterion: retained path
  with `>= 75%` HUMAN subject-anchor coverage inside the authoritative
  takeoff→water-contact window). The single recovery (676) is thin:
  a 2-anchor window, rank 4, carried by F1 extension rather than its F0 core.
- `ACTION_SPANNING_SUBJECT_TRAJECTORY_RECALL = 1/15` (2169 rank-1,
  0.889 full-action coverage) — but its flight coverage is 0.294 core /
  0.204 extended with prep at 0.987: a prep-dominated recovery that the
  flight-aware metric correctly refuses to count as a DiveTrack (Phase-14
  hierarchy enforced, not notched as success).
- Observation is complete: full-floor flight-window inclusion is 1.0 on
  7/9 event dives; capped-lattice flight inclusion is ≥0.92 everywhere it
  matters. The misses are ranking/selection, not perception or chaining.
- Retained top cores on 7/9 event dives are temporally disjoint from the
  HUMAN flight window: the decoder finds *a* coherent flight, not *the*
  subject's flight. Crowded clips contain multiple flight-like arcs and
  identity-free Q cannot pick the subject's.

## 2. Authorities (all frozen, all verified in preflight)

- V3 base `509f4a9` (V2 head) on branch
  `dive-analyzer-flight-anchored-trajectory-v3`; dedicated worktree
  `diveanalyzer-flight-v3`; concurrent work preserved.
- Accepted V2 state reproduced exactly before representation work:
  union ≥0.85 on 12/15, `NO_OBSERVATION` never on primary cohort,
  retained recall 0/15 (no retained path even subject-corresponding),
  V2 pool coverages re-measured identical (2169 0.795 … 676 0.444),
  A1 null result standing (not re-run; appearance forbidden in V3).
  (Note: the packet's stated canonical `d3ab6c43…` exists in no local
  mirror; fresh repository evidence won per packet rule. V2 evaluate was
  re-run end-to-end; it overwrites the narrative V2 JSON with its raw
  subset, which was restored byte-identical afterwards.)
- Frozen files: `phase_subject_candidate_quality_v3.py` (`9fc8dcbc…`),
  `proposer_event_logic_v3_c0.py` (`9c507719…`), `r5_tracklets_v1.py`,
  D5 `MODEL_SHA 82b420c4…` floor `(0.001, 0.45, 640, 200)`;
  target chains `11d075be…`; L1A 63 (`d805aacc…`); L1B 180 (`dc958909…`).
- Protocol commit `d252f7b` precedes all subject-result evaluation.
  Post-freeze code changes: one NaN-guard repair in core smoothness
  (empty tail slice) and two evaluation-metric alignments with the frozen
  protocol (flight-window denominator; flight-union cutoff). No constant
  changed; `PROTOCOL_CONSTANTS` integrity test green.

## 3. Flight evaluation authority (GT-only)

HUMAN takeoff→water-contact windows exist for 9 dives
(1040/2169/2341/2353/2541/133/311/676/2387); 6 dives
(1304/2204/2223/2526/2583/2839) are `GT_UNAVAILABLE` for flight metrics
(inference identical; general coverage still reported, all 0.0 retained).
Flight anchors: 1040: 29; 2169: 49; 2341: 61; 2353: 72; 2541: 27;
133: 2; 311: 1; 676: 2; 2387: 3.

## 4. F0 frame lattice (Phase 4–7)

Nodes: top-50/release per frame by confidence plus up to 10 flow-relative
movers (frozen D5 floor; no PersonTrack membership required).
Camera flow estimated GT-free per step (median of top-20); all dynamics
in compensated coordinates. Explicit NULL state (0.20/frame, runs bounded
by frozen 0.30 s interp limit). Transitions: PTS delta, predicted-center,
scale, velocity/direction continuity, confidence — no appearance.
Dual-population beam (32 static + 32 mover-protected slots with per-frame
motion advantage) over temporally stratified starts (stride 30 frames):
fast-motion hypotheses structurally cannot be eliminated by stationary
ones. Flight objective Q rewards excursion/descent/lateral coherence and
penalizes missing/static occupancy; long static prep scores ≈ −0.4 while
true arcs score > 0.

## 5. F1 extension

Greedy gated rollout backward (prep) and forward (entry/post) from each
frozen F0 core; final order IS the F0 Q order (subordinate by
construction). Retained set: 5 tracks on 14/15 clips (1040: 4 after
near-duplicate collapse), each with `path_id`, representative frame,
time interval, box trajectory, flight-core interval, analysis flags —
manual-selection contract satisfied without UI.

## 6. Flight retention results (paths frozen first)

| dive | flight anchors | floor/cap incl | best retained rank | flight cov | purity | longest missing gap | handoffs | limitation |
|------|---------------|----------------|--------------------|------------|--------|---------------------|----------|------------|
| 1040 | 29 | 1.00/1.00 | — | 0.000 | — | — | — | FLIGHT_ASSOCIATION_LIMITED |
| 2169 | 49 | 1.00/1.00 | — | 0.000 (r1 ext 0.204) | — | — | — | FLIGHT_ASSOCIATION_LIMITED |
| 2341 | 61 | 1.00/0.92 | — | 0.000 | — | — | — | FLIGHT_ASSOCIATION_LIMITED |
| 2353 | 72 | 1.00/0.99 | — | 0.000 | — | — | — | FLIGHT_ASSOCIATION_LIMITED |
| 2541 | 27 | 1.00/0.93 | — (r4 ext 0.333) | 0.000 | — | — | — | FLIGHT_ASSOCIATION_LIMITED |
| 133 | 2 | 0.50/0.50 | — | 0.000 | — | — | — | FLIGHT_ASSOCIATION_LIMITED |
| 311 | 1 | 0.00/0.00 | — | 0.000 | — | — | — | FLIGHT_OBSERVATION_LIMITED |
| 676 | 2 | 1.00/1.00 | 4 | 1.000 | 1.0 | 0.099 s | 128 core+ext | FULL_ACTION_EXTENSION_LIMITED |
| 2387 | 3 | 1.00/1.00 | — | 0.000 | — | — | — | FLIGHT_ASSOCIATION_LIMITED |

Stricter continuous-coverage distribution: 8/9 event dives at exactly
0.0; 676 at 1.0 on a 2-anchor window. No middle ground — selection is
binary-miss, not near-miss (except 2169 partial threading: r1 core 0.020
/ extended 0.204; r2 core 0.184 / extended 0.265).

## 7. Raw-union vs V2-pool vs V3-F0 vs V3-F1 (Phase 12)

- Raw union unchanged (frozen perception): ≥0.85 on 12/15.
- V2 decoded pool (full-action best): 2169 0.795, 2541 0.584, 1040 0.547,
  676 0.444, … (retained 0.0 everywhere).
- V3 F0 cores (flight-window): 0.0 on 8/9; 676 r2 core 0.500 (the only
  on-subject F0 core: [4.00, 6.94] overlapping the window, DIVE_LIKE).
- V3 F1 extended (flight-window): 2169 r2 0.265, 2541 r4 0.333,
  676 r4 1.000 — extension *adds* flight anchors by growing into subject
  prep/post, but never assembles a subject flight core except 676-r2.
- V3 retained full-action: 2169 r1 0.889 (prep 0.987 / flight 0.294 /
  post — / full 0.889); all other clips 0.0.

The 2169 hierarchy is the packet's Phase-14 case in numbers: good prep +
bad flight is NOT a recovered DiveTrack. V2's metric caveat (prep alone
≈ 79% ≈ recovery by letter) is now empirically closed: the flight-aware
metric refuses it.

## 8. Why selection fails (perception vs representation)

- 311: `FLIGHT_OBSERVATION_LIMITED` — its single flight anchor has no
  floor candidate within radius (in-window perception gap). Stop here.
- 133 (2-anchor window, floor 0.5): thin-authority; association-limited
  by rule, low weight as evidence either way.
- 1040/2169/2341/2353/2541/2387: observation complete incl. lattice, yet
  top cores sit outside the HUMAN window (1040 r1 [8.64, 9.81] vs
  [4.46, 5.41]; 2341 r1 [5.80, 8.78] vs [3.57, 4.59]; 2353 r1
  [23.02, 23.96] vs [5.70, 6.88]; 2541 r1 [10.11, 13.08] vs
  [17.52, 18.65]; 311 r1 [8.01, 10.98] vs [13.75, 14.82]).
  The decoder chains *a* flight per clip — usually with COMPLETE
  Event-Logic sequences — but crowded scenes hold several flight-like
  arcs (other divers, repeated actions across long clips) and Q has no
  subject evidence to choose with. 2169 r1 is the purest exhibit: a
  mixed stitch (subject prep 0.987 + another flight), i.e. F1 extension
  growing a wrong flight core into dense static subject prep.
- 676: `FULL_ACTION_EXTENSION_LIMITED` — flight core r2 is genuinely
  on-subject (DIVE_LIKE, COMPLETE), but no retained path spans the full
  action on-subject.
- 6 non-event dives: `GT_UNAVAILABLE` (all retained 0.0 general coverage).

## 9. Multi-path preservation (Phase 16)

5 retained paths per clip (1040: 4), temporally overlapping with disjoint
boxes on every clip → `SYNCHRO_REPRESENTABLE`. Synthetic two-arc fixture:
two simultaneous flight-like trajectories → two independently retained
paths (Q +0.74 / −0.44, disjoint boxes). No collapse toward one track.
Plausible non-subject arcs are preserved, not suppressed.

## 10. Frozen Event Logic replay (Phase 17–19)

Replayed unchanged on all frozen full-action paths (never used in
selection). Retained DIVE_LIKE counts: 676: 2 (r2, r4); 311: 1 (r5);
2583: 1 (r4); all other clips 0. Statuses are otherwise AMBIGUOUS with
scattered NON_DIVE — unattributed arcs remain diagnostics, not labels
(V1 lesson stands).
Subject event accuracy: `NO_RETAINED_SUBJECT_PATHTRACK` on every clip
with HUMAN authority (no full-action subject path retained anywhere;
676's flight-only recovery does not qualify). Continuous errors are
therefore unscored — trajectory is still the blocker, so the
`TRAJECTORY_RECOVERED_EVENT_LOGIC_NOW_BLOCKER` outcome does NOT trigger:
Event Logic remains *untested* on subject paths, neither blocker nor
validated. No thresholds invented.

## 11. Readiness (Phase 20–23)

- Analytics: `TRAJECTORY_NOT_READY = 14`,
  `FLIGHT_TRAJECTORY_RECOVERED_ONLY = 1` (676),
  `ACTION_TRAJECTORY_RECOVERED_EVENT_UNVERIFIED = 0`,
  `TRAJECTORY_AND_EVENTS_PLAUSIBLE = 0`. (2169's 0.889 is prep-dominated
  and excluded by the Phase-14 hierarchy — documented, not hidden.)
- Overlay: `TRACK_STABILITY_STILL_INSUFFICIENT`. (676 r4 meets the letter
  of the continuity rule on a 2-anchor extension-luck recovery; no
  retained *subject action-trajectory* has stable continuity. No
  masks/silhouettes/pose.)
- Manual-selection contract: satisfied at artifact level (path_id,
  representative frame, interval, box trajectory, flight-core interval,
  analysis_available=false). Product fallback (user picks among valid
  DiveTracks) remains viable once precision is measurable.
- Other-action labels: `OTHER_ACTION_GT_NOW_HIGH_VALUE` — V3 retains
  plausible action-spanning trajectories on every clip (COMPLETE
  sequences throughout the retained sets) and subject selection among
  them is now the measurable blocker: false-DiveTrack precision (real
  other dives vs mixed stitches, cf. 2169 r1) is the next quantity to
  measure. Minimal future plan (design only, no collection): HUMAN
  takeoff/water-contact marks for top retained arcs on 3–4 crowded clips
  to score multi-path precision.
- Identity: `IDENTITY_LINE = FROZEN_DEFERRED`. Reference acquisition:
  `DEFERRED`. D5/perception frozen (no retune, incl. the three
  weaker-observation clips). B2 writes 0; new media tier 0.

## 12. Resources and tests

- D5 inference 0; new embeddings 0; training 0; new labels 0; B2 reads 0;
  B2 writes 0; media decodes 0. Inference 1115 s sequential, peak RAM
  447 MB (far below the 20 GB threshold). Cache-only.
- Required tests (12 in `test_flight_anchored_traj_v3.py`, all green):
  V2 baseline reproduction, candidate cache identity, PTS authority,
  protected-data firewall, GT/event-GT/diver_id absent from inference,
  no appearance dependency, no Event Logic in core selection,
  NULL-state determinism + bounded-gap bridging, frame transition +
  decoder determinism, protocol freeze integrity, top-K preservation,
  simultaneous-path representation, resource budget, Event Logic frozen
  identity, no D5 mutation/training/labels/B2. Zero packet-owned failures.
- Scientific authorities mutated: NO. Media backbone mutated: NO.

## 13. Answers to the packet's success questions

1. Reconstruct subject fast-motion flight from frame proposals despite
   shattered PersonTracks? — Mechanically yes (arcs chain; NULL bridges;
   676 r2 is an on-subject flight core), reliably no (1/9).
2. Does flight-first search surface paths V2 buried? — Partially: 2169
   subject content is retained rank-1 (0.889) vs V2 retained 0.0; but its
   flight core is another arc — surfacing improved, subject selection did
   not.
3. Retained flight coverage vs raw-union bound? — 0.0 on 8/9 despite
   union ≈ 1.0: the gap is pure selection.
4. Prep/post attached without dominating ranking? — Yes by construction
   (F0 order frozen; F1 subordinate). 2169 proves the hierarchy matters:
   extension recovered prep (0.987) around a wrong core.
5. Genuinely perception-limited? — 311 in-window (single anchor, zero
   floor candidates). Nowhere else in flight.
6. Multiple simultaneous flights preserved? — Yes (synthetic + all-clip
   synchro).
7. Does continuity make frozen Event Logic accurate? — Untestable: no
   subject full-action path to score. Non-subject COMPLETE sequences
   fire throughout (diagnostics only).
8. Stable box overlays viable? — No.
9. Per-track analysis resumes? — No.
10. Next true bottleneck? — `SUBJECT_FLIGHT_SELECTION_AMONG_COMPLETE_ALTERNATIVES`:
    with observation complete and chaining solved, choosing the subject's
    arc among several plausible flights needs subject evidence the packet
    forbids (identity) — hence validation-first: other-action labels +
    manual-selection fallback to make precision measurable.

## 14. Classification

`FLIGHT_ANCHORED_TRAJECTORY_V3_PARTIAL`: flight retention improves
materially over V2 in the retained set (676 flight recovery; 2169
subject content rank-1 vs V2's all-zero retained; coherent arcs with
COMPLETE sequences on every clip; NULL bridging; synchro preserved) but
remains insufficient for reliable downstream analysis (1/9 thin flight
recall; 0/9 substantive). Not PROMISING (no multi-clip flight recovery).
Not FAILS (representation demonstrably improved retained trajectories
and isolated the true next blocker with observation ruled out).

`IMPROVE_DIVE_ACTION_VALIDATION_NEXT`: the decoder produces multiple
plausible DiveTracks per clip; the science now needs precision
machinery — which retained arcs are real dives, whose are they, and
(through the manual-selection contract) letting the user pick. Do not
return to identity unless validation specifically requires it.
