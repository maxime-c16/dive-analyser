# Dive Analyzer — Flight-Path Candidate Recall Audit V1

Packet: `DIVE_ANALYZER_FLIGHT_PATH_CANDIDATE_RECALL_AUDIT_V1`
Gate: `SUPERVISOR_REVIEW_AFTER_FLIGHT_PATH_CANDIDATE_RECALL_AUDIT_V1`
Type: audit / localization only — frozen V3 executed unchanged; no V3 constant changed.
Companion metrics: `DIVE_ANALYZER_FLIGHT_PATH_CANDIDATE_RECALL_AUDIT_V1.json`
Code: `experiments/subject_resolution/audit_flight_path_recall_v1.py` (stage capture + GT-only
evaluation + graph oracle), `diag_beam_subject_trace_v1.py` (beam subject trace),
`build_flight_path_recall_report_v1.py` / `finalize_flight_path_recall_report_v1.py`,
`test_audit_flight_path_recall_v1.py` (16 tests).

## 1. Answer in one paragraph

The HUMAN-authoritative subject flight **is constructible inside the frozen V3 graph on 4/9
event dives (4/7 under strict human-only seeds), but V3 search generates it on 0/9**. Nothing
representable survives into the decoded pool; top-K ranking is not where it dies (2169's best
pool core *is* retained at rank 2). The single V3 recovery (676) is a two-anchor case reached
only by F1 growing a pre-flight core. Search loses the subject through three stacked leaks —
seeding almost never lands on the airborne diver, mover-slot retention rewards spike-latched
junk over the real subject, and the pool is harvested only from paths alive at the clip's last
frame. Beneath search, a unit error in the motion gates (per-second velocity caps + per-second
jitter applied to single-frame velocity) removes 24–55 % of the subject's own flight links in
both V3 and the upstream r5 tracklet builder. Verdict: `SEARCH_IS_PRIMARY_BLOCKER`,
`IMPROVE_SEARCH_RECALL_NEXT`; manual selection not yet viable; other-action GT premature.

## 2. Git authority reconciliation (Phase 0)

- True canonical: `uiux-overhaul-pro-app` on the server (`~/dive-analyser`), starting HEAD
  `d3ab6c43acf4971ab914547f0dd373f097771b0a` (= merge of V2 `509f4a9` into `8964f7d`).
- V2 `509f4a9`: already integrated (via `d3ab6c4`). V3 `d252f7b` → `3e889f2`: feature-only on
  `dive-analyzer-flight-anchored-trajectory-v3`, linear on `509f4a9`.
- Cause of "d3ab6c4 missing": the mac-mirror remote (`…dive-analyser-2026-09-05.git`) and the
  local clone used by V3 were stale at `8964f7d`. Fresh evidence: `d3ab6c4` present on the server.
- Reconciled: V3 merged `--no-ff` (clean; `d3ab6c4` tree == `509f4a9` tree) →
  `f043f6382defdda5acecfe8db66da7305c175d98`. No science commit rewritten. The server working
  tree's 5 pre-existing uncommitted deletions + untracked files were left untouched.
- Audit worktree: local `~/.perso/diveanalyzer-flight-recall-audit-v1`, branch
  `dive-analyzer-flight-path-recall-audit-v1` from `f043f63` (the audit ran on the M2 Mac where
  the frozen caches and V3 run artifacts live).

## 3. Freeze and reproduction (Phases 1–2)

- `flight_anchored_traj_v3.py`, runner and protocol doc byte-identical to `3e889f2`;
  `PROTOCOL_CONSTANTS` all present in the protocol doc; D5 caches SHA-verified
  (`MODEL_SHA 82b420c4…`, floor `(0.001, 0.45, 640, 200)`); Event Logic V3-C0 `9c507719…`.
- Official runner re-inference (unchanged `run_flight_anchored_traj_v3.py infer`, sequential,
  1992 s): **15/15 outputs identical** to the frozen V3 artifacts. Instrumented audit capture:
  **15/15 identical**, retained top-K asserted equal to the replicated diverse-core order, and
  S6 metrics asserted equal to the frozen V3 evaluator on every track.
- `FLIGHT_PHASE_SUBJECT_TRAJECTORY_RECALL = 1/9` reproduced; per-dive best flight coverage
  matches the V3 report on 9/9; 676 (rank 4, 1.0) and 2169 partial threading (r1 0.204 /
  r2 0.265) reproduced.
- Only authority difference: frozen artifacts record runner SHA `cef17b32…`, committed runner is
  `c191c148…` — the V3 report's disclosed post-inference *evaluation-only* edits. Mechanical.

## 4. Stages (actual implementation) and GT boundary (Phases 3–4)

| stage | implementation object |
|---|---|
| S0 raw floor union | any D5 floor candidate within RADIUS 0.06 of the flight anchor |
| S1 capped lattice | `build_frame_lattice` (50 conf + ≤10 movers per frame) |
| S2 graph oracle | best path through S1 nodes under V3's exact transition function, no search limits |
| S3a beam final | each start's final live beam (≤64) before pool triage |
| S3 F0 pool | decoded pool (8/start triage + dedup) |
| S3c F0 pool cores | best-Q core of each pool path (the ranked objects) |
| S4 F0 top-K | diversity-deduped Q order, first 5 |
| S5 F1 extended | **in V3 identical to S6** (extend_core runs only on the top-5); an evaluation-only counterfactual S5cf extends every pool core |
| S6 F1 final | retained V3 tracks |

GT is loaded only after `capture()` has frozen every stage for a dive (source-tested). The
graph oracle uses GT only to *choose* among gated successors of existing nodes; a behavioural
test proves that `gated()` truncated to the V3 fan-out reproduces `_extend_starts` exactly, and
that the oracle leaves `kept`/`kept_arr` unmodified.

"≥75 %" everywhere = frozen V3 recovery rule: hits ≥ 2, purity ≥ 0.75, flight-anchor coverage ≥ 0.75.

## 5. Retention funnel (Phase 12 — central deliverable)

Frozen V3 authority (9 event dives):

```text
raw union >=75%          7/9
graph oracle >=75%       4/9   (1040, 2169, 2353, 676)
generated pool >=75%     0/9   (beam-final pre-triage also 0/9)
final F0 top-K >=75%     0/9
extended pool >=75%      1/9   (V3: == F1 final; all-core counterfactual also 1/9)
final F1 top-K >=75%     1/9   (676)
```

Strict HUMAN seeds (hurdle chains replaced by their HUMAN_GT visible seed boxes; 1040/2541
have none → 7 evaluable): raw 5/7, graph 4/7 (2169, 2341, 2353, 676), pool 0/7, F0 0/7, F1 1/7.

## 6. Per-dive stage results (frozen authority; flight coverage / purity)

| dive | anchors | raw | graph oracle | F0 pool | F0 final | F1 pool (cf) | F1 final | longest gap (F1) | primary loss |
|---|---|---|---|---|---|---|---|---|---|
| 1040 | 29 | 1.00 | **0.76 / 1.00** | 0.00 | 0.00 | 0.00 | 0.00 | — | SEARCH_PRUNING_LIMITED |
| 2169 | 49 | 1.00 | **0.78 / 0.97** | 0.18 / 1.00 | 0.18 (r2) | 0.35 / 0.41 | 0.27 / 0.34 | see JSON | SEARCH_PRUNING_LIMITED |
| 2341 | 61 | 1.00 | 0.57 / 1.00 | 0.00 | 0.00 | 0.00 | 0.00 | — | GRAPH_REPRESENTATION_LIMITED |
| 2353 | 72 | 1.00 | **0.75 / 1.00** | 0.00 | 0.00 | 0.00 | 0.00 | — | SEARCH_PRUNING_LIMITED |
| 2541 | 27 | 1.00 | 0.63 / 0.94 | 0.00 | 0.00 | 0.33 / 0.35 | 0.33 / 0.35 (r4) | see JSON | GRAPH_REPRESENTATION_LIMITED |
| 133 | 2 | 0.50 | 0.50 / 1.00 | 0.00 | 0.00 | 0.00 | 0.00 | — | FLIGHT_OBSERVATION_LIMITED |
| 311 | 1 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | — | FLIGHT_OBSERVATION_LIMITED |
| 676 | 2 | 1.00 | **1.00 / 1.00** | 0.50 / 0.50 | 0.50 (r2) | 1.00 / 1.00 | **1.00 / 1.00 (r4)** | 0.099 s | FULL_ACTION_EXTENSION_LIMITED |
| 2387 | 3 | 1.00 | 0.67 / 1.00 | 0.00 | 0.00 | 0.00 | 0.00 | — | GRAPH_REPRESENTATION_LIMITED |

Secondary qualifiers: 1040/2541 authority is VISUAL_EVALUATOR-only (§9.5); 2169 F1 contaminates
(purity 1.0 → 0.34); 2341 strict-human oracle 1.0 with pool 0.0 (search also limiting); 2387's
missing anchor is the takeoff link (velocity- and size-blocked pairs); 133/311/676 are thin
(1–2 anchors).

## 7. Where the loss happens

- **Graph → pool (search): 4 → 0.** Every representable case is lost before the pool.
- **Pool → top-K (ranking): no measurable loss.** Where the pool has subject content, the best
  subject core is retained (2169: core Q-rank 5, diverse rank 2). No qualifying core was ever
  suppressed by dedupe, because none exists.
- **Raw → graph (representation): 7 → 4.** 2341/2541/2387 fail the oracle; link diagnostics
  show motion-gate blocks on subject adjacent pairs (2341 21/55).
- **F1:** adds anchors by growing into neighbouring content and lowers purity (2169, 2541); the
  676 recovery is an F1 effect on a pre-flight core, not an F0 flight core.

Beam subject trace (frozen authority): in 71/94 start-windows no hypothesis is *ever* on the
airborne subject (`NEVER_ON_SUBJECT`); subject presence post-prune on flight-anchor frames is
0.86 on 2169 but 0.00–0.38 elsewhere; mean mover-latch fraction in flight windows 0.42–0.82.

## 8. Deep diagnostics (Phases 15–17)

**2169.** Raw 1.00; graph oracle 0.776 (purity 0.97); the beam holds the subject on 86 %
(frozen) / 100 % (strict) of flight-anchor frames and 3 starts carry it through the entire
window — yet the final beam, pool and pool cores top out at 0.184 (purity 1.0), retained at
F0 rank 2; F1 raises coverage to 0.265 while purity falls to 0.34. The stronger chain does not
survive because the pool is harvested only from paths alive at the clip's end, after later
cost competition has removed the flight hypotheses. **2169 is a construction/search problem,
not a ranking problem.**

**676.** Two HUMAN flight anchors (frames 120/135). Graph oracle 1.0; F0 pool/cores 0.5
(purity 0.5). Recovery exists only as rank-4 F1 extension of a core spanning 1.10–2.24 s
(entirely before takeoff 3.55 s); longest flight gap 0.099 s; full-action coverage 0.444.
Start 120 seeds the subject, then all 9 on-subject hypotheses are evicted at frame 131 by
mover-slot occupants with higher latched maxspeed. Every tested perturbation of the search
(bug-fix candidates) loses the recovery. **Thin and fragile; not evidence of general success.**

**311.** One flight anchor, zero floor/lattice candidates within 0.06 → classified
`FLIGHT_OBSERVATION_LIMITED` by rule. Caveat: the anchor is a 156×148 px box clipped at the
right frame edge; neighbouring frames (−1, +2) do have floor matches, and mid-flight is
`not_visible`. Under hits ≥ 2 the dive is unrecoverable by construction.

## 9. Pipeline defects found (evidence in JSON `FINDINGS`)

1. **Motion-gate unit error (critical; graph + upstream r5).** V3 applies
   `|Δ|/dt ≤ V_MAX + JITTER_C` and `|v| ≤ DEP_VEL_MAX = 1.4` to single-frame velocity. In r5,
   1.4 caps *span-averaged* velocity and JITTER_C enters a position gate as `JITTER_C·dt`. Flight
   averages 0.5–1.0 norm/s, but single-frame speeds of a rotating 30–60 px diver oscillate
   0–5 norm/s from box jitter (camera flow ≈ 0: not a compensation artefact). r5 `_gate_ok`
   rejects the subject's own flight links 24–55 % of the time (6–25 % clip-wide) — a plausible
   root cause of the long-observed PersonTrack shattering in flight.
2. **End-of-clip-only harvest (critical; search).** See 2169.
3. **Spike-latched mover slots (high; search).** Dynamic-slot key `cost − W_DYN·age·min(maxspeed,
   0.8)/0.8` uses max-ever speed times age; sparse hijack paths outrank the subject.
4. **Seeding misses the airborne diver (high; search).** 71/94 start-windows never on subject.
5. **Hurdle subject authority is not HUMAN-dense (high; evaluation).** 1040 and 2541 have zero
   HUMAN_GT anchors (VISUAL_EVALUATOR seeds only); other chains are 2–5 human seeds linearly
   interpolated and snapped to D5 candidates (median anchor–candidate distance 0.0000, so raw
   union = 1.0 by construction); AMBIGUOUS frames are excluded (2169: 28/80 flight frames);
   mid-flight snaps reach 0.055–0.079 > RADIUS; a `not_visible` seed is used as a position.
   V3's "observation complete" statement is therefore weaker than reported on hurdle dives.
6. **F1 backward extension extrapolates the wrong way (medium).** Double negation of `vel0`;
   forward seed velocity mixes raw and compensated coordinates.
7. **Core length saturation (medium).** Excursion (running max−min) is monotone in length;
   top cores sit at 2.94–2.98 s ≈ `CORE_MAX_S`.
8. **Resolution (strategic).** Everything runs on 202×360 proxies (airborne diver 27×41 to
   60×32 px) although 1920×1080 sources are recovered and aligned for 12 development dives.

## 10. Bug-fix candidates (evaluation-only, NOT promoted)

At the user's request, fixes were tried *outside* the frozen pipeline (separate modules;
frozen V3 untouched): A motion-gate units, B F1 sign/coords, C snapshot harvest, D sustained-
motion mover slots. A+B+C+D on all 15 dives: flight recall 1/9 → 0/9; regressions on 676
(thin recovery lost) and 2169 (prep-dominated full-action 0.889 → 0.0); no new recovery.
Pool-level subject coverage does not improve (2169 0.184 → 0.12–0.14; 1040/2341 ≈ 0), and a
whole-beam snapshot harvest on 1040 reaches only 0.07–0.14. Decisive probe (frozen V3 + whole-beam snapshot
harvest, evaluation-only): 2169 pool best rises 0.184 → **0.31 (purity 0.94) and becomes
Q-rank 1 / diverse rank 1** — once subject flight reaches the pool, Q ranks it first — but no
single hypothesis carries the subject through the whole flight (9 starts end in transition
loss), so coverage stays < 0.75; adding fix A on top lowers it to 0.12 (a looser gate lets more
non-subject successors fill the 6-way fan-out). Conclusion: the defects are real
but local repairs are insufficient — V3's cost economics rank real flight (jittery, shape-
changing, NULL-bridged) below static and hijack paths at seeding, retention and triage.
Search must be redesigned around subject-flight recall, not patched.

## 11. Decisions

- `MANUAL_TRACK_SELECTION_NOT_YET_VIABLE` — surfaced sets contain the subject flight on 1/9
  (two-anchor, fragile).
- `OTHER_ACTION_GT_STILL_PREMATURE` — the subject trajectory itself is usually absent from the
  surfaced set; this reverses V3's `OTHER_ACTION_GT_NOW_HIGH_VALUE` on fresh evidence.
- `SEARCH_IS_PRIMARY_BLOCKER` — graph 4 → pool 0 under both authorities; ranking loses nothing
  measurable; representation is secondary (7 → 4) and partly caused by the gate unit error.
- `IMPROVE_SEARCH_RECALL_NEXT` — the next algorithmic packet must change seeding, beam retention
  and harvest (S2→S3), with the motion-gate unit repair as an accompanying correctness fix.
- Identity `FROZEN_DEFERRED`; reference acquisition `DEFERRED`; Event Logic `FROZEN`;
  pose/analytics `PAUSED`.

## 12. Answers to the success questions

1. Raw proposal space: yes on 7/9 (hurdle union partly true by GT construction; 133/311 thin).
2. Representable by the frozen graph: 4/9 (4/7 strict).
3. Generated by V3 search: 0/9.
4. Discarded by top-K: no — it never reaches the pool.
5. F1: adds anchors by growing, lowers purity; creates the only recovery (676) from a
   pre-flight core.
6. 676: thin two-anchor, F1-carried, fragile under any search perturbation.
7. 2169: construction/search problem (subject tracked in-beam, lost before harvest).
8. Manual selection with current tracks: not viable.
9. Other-action labels now: premature.
10. Stage to change next: S2→S3 search (seeding, retention, harvest), plus motion-gate units.

## 13. Protected data, resources, tests

- 524 `AUTHORITY_CONFLICT_EXCLUDED`, 2555 `SCREEN_RECORDING_STRESS_CASE`, Paris `EXTERNAL_ONLY`,
  INTERNAL_EVAL / FINAL_HOLDOUT `NOT_ACCESSED`.
- D5 inference 0, new embeddings 0, training 0, new labels 0, B2 reads/writes 0, media decodes 0.
  Cache-only. Official reproduction sequential; audit per-dive processes in parallel on the Mac
  (deterministic, identical outputs).
- Tests: `test_audit_flight_path_recall_v1.py` 16/16 (authority reconciliation, protocol hash,
  D5/Event Logic identity, GT/event-GT absent from inference, capture-before-GT, transition-
  function equivalence ×3, oracle isolation, search-pool/final-ranking identity, V3
  reproduction, funnel determinism, protected-data firewall, no training/labels/B2).
  `test_flight_anchored_traj_v3.py` 12/12. `test_action_span_assoc_v2.py` 16/16 in its own
  worktree (one test reads a git-ignored V2 run artifact absent from this worktree — environment,
  not packet-owned). Zero packet-owned failures.
- Scientific authorities mutated: NO. Media backbone mutated: NO.
