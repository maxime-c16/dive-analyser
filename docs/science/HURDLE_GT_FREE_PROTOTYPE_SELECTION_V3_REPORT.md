# HURDLE GT-Free Prototype Selection V3 Report

Packet: `HURDLE_TARGET_IDENTITY_V3` (supervisor packet, continuation of
`HURDLE_TARGET_IDENTITY_V2` / the FM2 causal chain).
Thread: Apple M2, worktree `~/.perso/diveanalyzer-prototype-v3` (branch
`hurdle-prototype-v3`, cut at canonical server HEAD `636b0dc` on
`uiux-overhaul-pro-app`; the concurrently reported media-backbone storage
authority `59e9097573ef…` is an ancestor of the cut HEAD — integration
verified before start). Heavy steps ran under `caffeinate -i -s`, one
video at a time, memory-bounded. Report sections follow the Phase-U
required list.

**Headline verdict: `FREEZE GATE FAILED` — GT-free prototype selection is
NOT solved.** The correct prototype can be *found* by a bounded
appearance-guided hypothesis search on individual dives, but no single
GT-free scorer ranks it first across the corpus: aggregate path features
are systematically gameable by self-coherent static junk and
high-excursion movers. Nothing frozen; no repaired trajectories;
`FM2_STILL_IDENTITY_LIMITED`;
`PROTOTYPE_SELECTION_STILL_PRIMARY_BLOCKER`.

---

## 1. Previous V2 state

Per `docs/science/HURDLE_IDENTITY_SELECTION_V2_REPORT.md`:
`D5_DETECTOR_REMAINS_CLOSED` (recall@200 = 1.000), candidate-completeness
solvable, frozen OSNet x1.0 Market-1501 discriminative on all five
ordinary DEVELOPMENT dives (margin 0.203 / AUC 0.902; prep–prep cos
0.89–0.97, prep–flight 0.67–0.79 vs distractor ~0.65), GT-seeded
association functional (oracle 2169 0.883, 2341 0.472), and the single
blocker: **GT-free seed/prototype selection** (R5-A repaired 2353 only;
R5-B repaired none). `FM2_STILL_IDENTITY_LIMITED`; V3-D0 frozen
experimental baseline; 524 `AUTHORITY_CONFLICT_EXCLUDED`; 2555
`SCREEN_RECORDING_STRESS_CASE`.

## 2. Resource / cache reuse

`CACHE_READY` (`runs/hurdle_prototype_v3/CACHE_READINESS_V1.json`):

- D5 frames rerun: **0** — every selector path consumed the frozen
  `R5_FULLCLIP_CANDIDATES_V1.json` (model sha `82b420c4…` re-verified;
  full-clip 1..n coverage re-verified per dive; GT isolated under
  `gt_eval_only`).
- OSNet re-extraction: **one bounded sweep** — the V2 cycle never persisted
  embeddings (per-run in-memory only), so a one-time extraction of every
  plausible-tracklet crop set was required and was persisted as
  `runs/hurdle_prototype_v3/osnet_emb_cache_v1.npz` (25,524 crops, 512-d,
  weights sha `2809d322…` recorded and verified; sequential one-pass
  decode per dive). No candidate crop was re-embedded afterwards.
- No HQ derivatives regenerated; no hyperparameter grid; no new labels.
- Host caches referenced by sha256; nothing heavy committed to Git.

## 3. Oracle gap

`runs/hurdle_prototype_v3/ORACLE_GAP_V3.json` (GT used only to label which
tracklets are target-bearing):

| dive | pure target fragments | median frag life | pure-cov / GT frames | R5-B chosen ∩ target | R5-A ∩ target |
|---|---|---|---|---|---|
| 1040 | 43 | 0.30 s | 5.16× | 0 | 1 |
| 2169 | 23 | 0.20 s | 3.76× | 100 | 0 |
| 2341 | 47 | 0.30 s | 2.73× | 0 | 0 |
| 2353 | 29 | 0.53 s | 2.32× | 0 | 150 |
| 2541 | 48 | 0.20 s | 2.33× | 2 | 26 |

Failure taxonomy (Phase B): the GT-free component choices always lose to
*coherent junk* — 1040/2353/2541 `OTHER_PERSON_DOMINATES` (jump-mosaic
pseudo-components with peak raw velocities 5–33 cy/s from transitive
greedy merging), 2341 `NO_CLEAR_COMPONENT` + `TARGET_FRAGMENTED`. The
oracle gap is not an association gap: with the correct seed, association
works (V2 evidence); it is a **seed-preference gap**.

## 4. Component feature audit (B1)

`COMPONENT_FEATURES_V1.json` — GT-free descriptors for every plausible
component (anchors, movers ≥0.12 flow-relative excursion, tracklets
spanning ≥0.33 s; 518–1057 per dive): temporal coverage, longest run,
NULL/gap fraction, conf statistics, vertical/horizontal excursion,
peak/median velocity, abrupt jumps, path smoothness, start fraction,
appearance self-consistency. Key measured facts (GT used post-hoc only):

- **Confidence does NOT separate the target**: on 1040/2353 the target
  fragments sit at conf p50 ≈ 0.002–0.003, indistinguishable from the
  floor junk (p50 0.0033). Only 2169 (p50 0.05) is conf-separable.
- **Appearance does NOT separate target tracklets inside the plausible
  ocean**: pure-target–pure-target mean cos 0.82–0.93 vs
  pure-target–distractor 0.77–0.86 and distractor–distractor 0.79–0.85
  (2341/2353 distributions almost fully overlap). The Phase-E
  discriminability exists target-vs-top-distractor, NOT across the
  conf-floor candidate ocean.

## 5. P0 — appearance-consensus identity clusters

Union-find identity clustering over the plausible tracklet graph
(appearance floors re-used unchanged from R5-B: cos ≥ 0.85 static-static,
≥ 0.70 mover-involving; bounded spatial/temporal compatibility),
deterministic. Result: **the graph collapses into ONE mega-cluster per
dive** (transitive chaining at the 0.70 floor; distractor pairs at
0.65 ± 0.09 exceed the floor ~25% of the time). Targetness selection over
clusters therefore selects the mega-cluster, which tracks the target only
by accident (2169 0.836 — ordering luck; ≤ 0.006 everywhere else).
**P0 as a standalone selector: REJECTED.**

## 6. P1 — multi-hypothesis prototype search

Two generators, both bounded (≤ 150 candidates per dive):

- **Geometry enumeration** (frozen R5-A anchors + gated rollouts,
  top-30): the correct hypothesis IS in the set on 1040/2353/2169/2541
  (best-eval per-frame 0.373 / 0.324 / 0.770 / 0.469) but at path-quality
  ranks 7–17.
- **Appearance-guided rollouts** (R5-B appearance terms inside the R5-A
  chain machinery; prototype EWMA per `DEP_APP_EWMA`, abort at
  `DEP_APP_ABORT`): repaired 1040 — best path 0.609–0.658 at
  quality-rank 1–2 of 142 (D5 top-1 0.106, longest wrong 122 → 37).
  This is a real, reproducible engineering-variant repair (recorded as a
  diagnostic, NOT a frozen result).

But **no aggregate scorer is safe**: (a) excursion magnitude prefers
junk movers (2169 junk rollouts reach 0.46–0.54 cy while the true diver
reaches ~0.22); (b) appearance coherence REWARDS static objects
(self-similar crops) and PENALIZES true divers (prep↔flight pose gap
caps coherence ~0.79–0.87 while self-coherent junk reaches ~0.90–0.96);
(c) coverage/NULL terms are satisfied by junk rollouts that survive
through re-matching. Two frozen formula variants were evaluated
(`v6_path_quality` mechanistic term set; `hypothesis_path_quality`):
both are gameable — 1040 correct at rank 1 under one, rank >10 under the
other; 2169/2341/2353/2541 correct candidates lose under both. A
third generator (detector op-point top-confidence trajectory as a
hypothesis class) protects 2169 only when the scorer already prefers it
— i.e., it is the status quo, not a mechanism.

## 7. P2 — multi-phase consensus (executed, non-binding)

Dual-phase requirement (stable pre-action member AND high-motion member,
generic trajectory properties, no GT phase timestamps) was evaluated as a
per-hypothesis flag (`dual_phase`) and as a selection filter. Junk
hypotheses anchored at stable structures almost always satisfy BOTH
phases (a passer-by produces a "prep + excursion" shape), so the
consensus never binds. **P2: no additional discrimination on this
corpus.**

## 8. LOSO results

The selector has **no fitted parameters** — every constant is a frozen
literal derived from R5-A/R5-B frozen values or mechanistic physics
(departure-from-rest, continuity, coverage). Leave-one-dive-out is
therefore identity: the SAME configuration applies to every dive, so
there is no per-dive calibration to leak. Reported as
`LOSO_NO_FITTED_PARAMETERS` (identical pooled and LOSO config). The
honest caveat, recorded for the supervisor: the *choice* of scorer
formula was made by inspecting all five DEVELOPMENT dives (feature
diagnostics in §4/§6), which is a form of development-set exposure the
LOSO discipline cannot remove; the failure of BOTH variants to rank the
correct candidate first across dives is itself evidence the mechanism is
not robust at n=5.

## 9. V6 association

`V6_GT_FREE_IDENTITY_ASSOCIATION` = candidate pool {appearance-guided
anchor rollouts (validated generator) ∪ P0 clusters ∪ D5-op-top1
trajectory} scored by the frozen `hypothesis_path_quality`
(appearance-coherence term included via the persisted embedding cache),
deterministic tie-breaks. Final frozen-configuration results
(`runs/hurdle_prototype_v3/V6_FINAL_V3.json`):

| dive | V6 per-frame correct | longest wrong | best-in-pool (eval) | D5 top-1 |
|---|---|---|---|---|
| 1040 | 0.0248 | 154 | 0.658 | 0.106 |
| 2169 | 0.0 | 434 | 0.770 (rollout) / 0.963 (D5 class) | 0.963 |
| 2341 | 0.0 | 273 | 0.077 | 0.022 |
| 2353 | 0.0 | 411 | 0.667 | 0.005 |
| 2541 | 0.0038 | 252 | 0.469 | 0.149 |
| 2555 | 0.0089 | 330 | — | 0.518 |

The pool CONTAINS a materially better path on 4/5 ordinary dives; the
scorer cannot PICK it robustly. V6 as configured is not better than D5
top-1 and regresses 2169.

## 10. Per-dive DEVELOPMENT results

Required-inspection families:

- **1040 (static structure family)**: repaired only in the P1
  appearance-guided engineering variant (0.609/0.658 vs D5 0.106; wrong
  run 122 → 37). Not rank-1-stable across scorers → not a result.
- **2341 (next-diver/post-action family)**: UNREPAIRED. No enumerated
  chain tracks the target (max 0.077 in 157 hypotheses); V2's
  appearance-NN oracle reached 0.472 — the correct path requires
  per-frame appearance tracking without the velocity gates that protect
  other scenes.
- **2353 (persistent bystander family)**: correct paths exist in the pool
  (0.667 anchor 109; rest-ratio 0.32 vs junk 0.84+) but the frozen scorer
  selects bystander/structure rollouts.
- **2541 (catastrophic wrong trajectory family)**: best-in-pool 0.469
  (anchor 895, departure-from-rest 0.02) — a potential repair — but
  ranked below junk under every frozen scorer tried.
- **2169 (control)**: preserved only by the frozen Event Logic on the
  historical trajectory (replay reproduces 0.4123/−0.2872 exactly).
  V6's own selection regresses it (junk rollout preferred).

## 11. Freeze decision

**`HURDLE_TARGET_IDENTITY_V3_FREEZE` NOT created — gate FAILED.**
Gate detail (recomputed in `V6_FINAL_V3.json`): materially-improved
failing dives 0/4 (required ≥3); 2169 not preserved by V6's own
selection. No identity freeze, no repaired trajectories, no new
trajectory cache (Phases K/L correctly skipped per packet order).

## 12. Repaired trajectories

Not generated (Phase K requires the freeze). The
`DEV_HURDLE_TRAJ_CACHE_V2` historical authority remains untouched.

## 13. V3-D0 replay

Replayed UNCHANGED on the frozen historical cache (Phase-K machinery
reused): the recorded V2 magnitudes reproduce exactly
(1040 −1.9947/−2.511; 2169 +0.4123/−0.2872; 2341 +1.0108/+3.4108;
2353 −1.8089/−2.2414; 2541 −15.0156/−14.9144; 2555 −2.6137/−7.4803).
Pinned by `test_historical_arm_replay_reproduces`.

## 14. FM2 causal result

**`FM2_STILL_IDENTITY_LIMITED`.** Identity repair was not achieved in any
frozen configuration; the V2 causal classification stands. FM2 is not an
Event Logic problem: V3-D0 was never given a correct target trajectory to
replay this cycle.

## 15. Trained-ReID-head decision

**`PROTOTYPE_SELECTION_STILL_PRIMARY_BLOCKER`.** Reasoning per the
packet's rule: (a) OSNet is confirmed discriminative (Phase E/F),
(b) candidate-complete association exists and functions, (c) reasonable
GT-free prototype selection was exercised (three causal ideas + two
scorer variants + a detector-confidence hypothesis class), and (d) the
remaining failure is NOT appearance separability — it is the preference
of junk by GT-free aggregate scorers plus chain-existence gaps (2341).
A trained head would sharpen appearance but cannot fix scorer gameability
or missing chains; prototype selection remains the binding constraint.

## 16. 2555

`SCREEN_RECORDING_STRESS_CASE` maintained. V6 final 0.0089 (best-in-pool
not meaningfully better); the 722-frame candidate cache's tail frames are
undecodable in the screen-recording rendition (graceful NULL handling
added and tested). 2555 did not veto anything (the gate failed on the
ordinary corpus alone) and is not reported as solved.

## 17. 524 exclusion

`524_AUTHORITY_CONFLICT_EXCLUDED` — untouched, read-only; the committed
`HURDLE_M_524_MAPPING_AUDIT_V1.json` conflict verdict re-verified by test.
No re-export, no labels.

## 18. V3-D0 freeze documentation drift

Read-only source-of-truth audit (Phase S): `EVENT_LOGIC_V3_D0_FREEZE.json`
recorded `interp_max_gap_s = 0.5 / vel_max_gap_s = 0.5`, while the
executable `PARAMS_V3D0` (inherited from `PARAMS_E1` via `PARAMS_V3C0`)
uses **0.30 / 0.20**. The executable is the scientific authority: the V2
replay re-ran the frozen code and reproduced the recorded magnitudes
exactly, which is impossible under 0.5/0.5.
**`EVENT_LOGIC_V3_D0_FREEZE_ERRATUM_V1`**: the drift is recorded in a
separate erratum artifact
(`docs/science/EVENT_LOGIC_V3_D0_FREEZE_ERRATUM_V1.json`) — freeze
metadata as recorded (0.5/0.5) vs executable authority (0.30/0.20) plus
the replay proof. The historical freeze artifact itself was NOT modified:
an interim in-place metadata correction performed during this cycle was
**reverted to the original committed bytes**
(sha256 `9702f7ee…`, verified against `HEAD` by test); historical freeze
artifacts are immutable from now on. NO executable behavior changed
(verified by `git diff` assertion in the test suite; Event Logic files
byte-untouched in this packet).

## 19. Answers to the packet's success questions

1. **Can the correct identity prototype be selected without GT?** No —
   correct prototypes exist in bounded candidate pools on 4/5 ordinary
   dives, but every frozen GT-free scorer is gameable by junk.
2. **Can the candidate-complete + OSNet machinery repair multiple
   dives?** Not in a frozen configuration; partial repairs demonstrated
   only as engineering variants (1040 0.61–0.66).
3. **Can it preserve 2169?** Only the historical frozen path (D5 op
   top-1 + frozen V3-D0) does; V6's own selection regresses it.
4. **Does a whole-clip targetness criterion reject the distractors?**
   Partially (static-forever / short-mover / post-action penalties are
   mechanistically sound) but not decisively — junk satisfies the
   positive criteria.
5. **Does the mechanism survive LOSO?** There are no fitted parameters
   (LOSO = identity), but the scorer formula itself was chosen with
   development-corpus exposure and fails across dives — the mechanism is
   NOT robust.
6. **Can repaired trajectories materially reduce FM2?** Unanswered this
   cycle (no freeze → no repaired trajectories).
7. **Do we need a trained ReID model?** Not indicated: the residual
   failure is selection preference, not appearance separability.
8. **Was the cycle mostly cache-based?** Yes — 0 D5 reruns, one bounded
   embedding extraction, everything else cached JSON/NPZ + graph work.

## 20. Tests

`experiments/landmark_pilot/test_hurdle_prototype_v3.py` — 33 tests,
zero failures: cache reuse/provenance; no-D5-rerun; P0 determinism;
bounded hypothesis enumeration; frozen scorer constants; NULL state;
full-clip GT-free windows; LOSO no-fitted-parameters; distractor taxonomy
units (static structure, persistent bystander, fast mover, post-action
next-diver, long preparation via targetness math); candidate inclusion;
OSNet reproducibility + embedding-cache provenance; 2555 stress +
graceful tail handling; 524 exclusion + audit verdict; Paris firewall;
freeze discipline (no freeze artifact exists; gate verdict recorded);
V3-D0 unchanged replay (recorded magnitudes + param identity);
historical-freeze immutability (freeze JSON byte-identical to HEAD,
original 0.5/0.5 metadata preserved) + erratum consistency
(`EVENT_LOGIC_V3_D0_FREEZE_ERRATUM_V1` ↔ executable, code untouched).

## 21. Gate

`SUPERVISOR_REVIEW_AFTER_HURDLE_PROTOTYPE_SELECTION_V3`
