# HURDLE Identity Component & Target Selection V4 Report

Packet: `HURDLE_IDENTITY_COMPONENT_AND_TARGET_SELECTION_V4` (supervisor
packet; continuation of `HURDLE_TARGET_IDENTITY_V3` — the GT-free
prototype-selection negative result — and the FM2 causal chain).
Thread: Apple M2, worktree `~/.perso/diveanalyzer-prototype-v3`
(branch `hurdle-prototype-v3`; V4 cut at the V3 closure commit
`f116558`, whose parent `636b0dc` is the canonical science base; the
concurrent media-backbone B2 thread was not touched — production media
serving, playback authorization, storage migration all untouched).

**Headline verdict: `FREEZE GATE FAILED` again — but with two real
positive results: (1) transitive appearance-cluster percolation was
ELIMINATED by the A1 bounded-degree identity graph, and (2) the 2341
hypothesis-generation failure was REPAIRED (the pool now contains a
target trajectory at 0.337 per-frame vs 0.077 historical best). What
remains broken is exactly what V3 diagnosed: no GT-free aggregate
scorer — now including a frozen Kinetics action-semantic score — can
rank the correct component first. `FM2_STILL_IDENTITY_LIMITED`;
`IDENTITY_COMPONENT_CONSTRUCTION_STILL_PRIMARY_BLOCKER`.**

---

## 1. V3 closure (§0)

Recovered from `~/.perso/diveanalyzer-prototype-v3` (uncommitted): the
V3 report, six phase scripts, the test suite, the run artifacts
(`ORACLE_GAP_V3`, `COMPONENT_FEATURES_V1`, `PROTOTYPE_SELECTION_V3`,
`V6_EVAL_V3`, `V6_FINAL_V3`, the OSNet cache meta) and the PROJECT_STATE
handoff — all recovered and committed as `f116558`.

- Tests: closed at **34/34 zero failures** (the pending three: the
  historical-replay and report-consistency tests were already green;
  the gate-verdict recording was repaired — see §2).
- Commit: one dedicated closure commit (V3 negative result), separate
  from all V4 work.
- Sync: pushed to the canonical server (`diveanalyzer-server:dive-analyser`,
  branch `hurdle-prototype-v3` at `f116558`) and the Mac bare mirror
  (`~/.perso/diveanalyzer-perception.git`, same commit — the worktrees
  share the mirror's git dir).
- `HURDLE_PROTOTYPE_V3_NEGATIVE_RESULT_CLOSED`.

## 2. Historical freeze immutability (§0.2)

The V3 cycle had corrected the recorded interpolation-gap metadata
inside `docs/science/EVENT_LOGIC_V3_D0_FREEZE.json` in place. Per the
packet rule, historical freeze artifacts are immutable:

- the freeze artifact was **reverted to its original committed bytes**
  (sha256 `9702f7ee…`, verified against `HEAD` by test
  `test_historical_freeze_immutable`; the original 0.5/0.5 metadata is
  preserved uncorrected);
- a separate erratum artifact
  `docs/science/EVENT_LOGIC_V3_D0_FREEZE_ERRATUM_V1.json` records:
  - freeze metadata as recorded: `interp_max_gap_s = 0.5`,
    `vel_max_gap_s = 0.5`;
  - executable authority: `interp_max_gap_s = 0.30`,
    `vel_max_gap_s = 0.20` (chain `PARAMS_E1 → PARAMS_V3C0 →
    PARAMS_V3D0`);
  - the replay proof: the frozen executable reproduces the recorded V2
    magnitudes exactly on the frozen trajectory cache (2169 +0.4123/
    −0.2872; 1040 −1.9947/−2.511; …), impossible under 0.5/0.5 — the
    drift is documentation-only;
- NO executable behavior changed (Event Logic files byte-untouched,
  asserted by test).

## 3. Cache reuse (§1)

- **D5 frames rerun: 0.** Every V4 mechanism consumed the frozen
  `R5_FULLCLIP_CANDIDATES_V1.json` (sha re-verified via the manifest).
- **OSNet embeddings**: the V3 cache covered every plausible tracklet.
  Phase B's repair requires embeddings for short fragments OUTSIDE the
  plausible set (2341's target fragments were 60/239 embedded — the
  hypothesis gap extends to embedding coverage), so ONE bounded
  completion pass (`phase_v4_cache_complete_v1.py`, sequential decode
  per dive, MPS-batched) completed the cache to FULL candidate-ocean
  coverage (348,622 → 579,709 keys; every ordinary dive at 1.0
  coverage). No crop embedded twice; nothing re-extracted; the
  embeddings are NOT in Git (manifest-only, `HURDLE_OSNET_EMBED_CACHE_V1`,
  revision V1.1).
- No grid sweeps; every constant below is a frozen literal with a
  documented rationale.

## 4. Component-percolation diagnosis (§4 preserved)

Confirmed from scratch: the P0 single-link/union-find appearance graph
collapses into exactly ONE component per dive (fractions 1.0 on all six
dives; distractor pairs at cos 0.65 ± 0.09 clear the 0.70 mover floor
~25% of the time, and the compatible-edge floor set is dense enough
that even mutual nearest-neighbor chains percolate).

## 5. Phase A — linkage mechanisms (exactly two)

`phase_v4_linkage_v1.py`, both deterministic, both behind the unchanged
R5-B spatial/temporal compatibility gates and pair floors:

- **A0 MUTUAL_KNN (rejected)**: edge accepted only when each tracklet
  ranks the other among its top-k neighbours. Frozen k ∈ {1, 2, 3}:
  **ALL collapse** into one mega-component per dive. Reciprocal ranking
  does NOT bound percolation on this ocean — the compatible-edge set is
  dense and the cosine distributions overlap (target–target 0.82–0.93 vs
  distractor–distractor 0.79–0.85). A0: REJECTED as a standalone
  mechanism (recorded as the negative control it is).
- **A1 BOUNDED_DEGREE (deg cap 3 + bridge margin 0.06)**: per tracklet
  keep only its top-3 mutually-capped edges; reject edges materially
  weaker than BOTH endpoints' strongest edge (bridge rejection).
  Result: **136–278 components per dive, largest component fraction
  0.04–0.09** — percolation is eliminated by construction (the degree
  cap bounds component growth; no unrestricted connected-components
  logic survives).

## 6. Phase A2 component evaluation (GT for evaluation only)

Per dive (A1 mechanism): target fragment coverage 0.58–0.96, number of
target-bearing components 4–12 (was 1), largest distractor
contamination 0.27–0.65 (was 0.97–1.00), largest component fraction
0.04–0.09 (was 1.0), distractor component purity 1.0 by construction
(pure-target membership defines target components).

Best target-bearing component per dive (per-frame correct on GT frames,
EVAL-ONLY): 1040 **0.602**, 2169 0.834 (vs D5 0.963), 2341 **0.337**,
2353 **0.618**, 2541 **0.324**.

Classification (frozen thresholds purity ≥ 0.75, mega ≤ 0.60):
**`COMPONENT_IDENTITY_STILL_COLLAPSED` on all five** — purity is
0.10–0.42. The honest statement: percolation is fixed; purity is NOT
achieved. The target's own fragments still merge with distractor
frames under the association floors, and OSNet's ocean overlap
(V3 §4) bounds what the frozen encoder can separate.

## 7. Phase B — 2341 hypothesis-generation repair (ONE bounded repair)

Audit (recorded in `HYPOTHESIS_POOL_V4.json`, 2341): of 46 adjacent
pure-target fragment pairs, 43 fail the R5-A velocity gates (the
target moves at hurdle-sprint/flight speeds the tracklet gates reject),
43 also fail the pairwise appearance floor (pose transition), and 0
fail on gap length. The board-anchor departure paradigm itself
mismatches: 2341's target lives LOW in frame (cy 0.65–0.84) with no
board prep anchor — 160 prep anchors exist, all upper-frame.

**The one bounded repair: appearance-NN rollouts seeded from IDENTITY
COMPONENTS** (not just prep anchors). Seed = each bounded-degree
component's prototype (L2 mean of member embeddings); the walk extends
the component forward/backward frame-by-frame with best cosine-to-
prototype under a velocity-plausible per-second displacement ceiling
(the R5 human-velocity constants applied per gap), a 0.62 cosine
floor, 0.40 s NULL tolerance, and a frozen EWMA prototype adaptation.
Bounded: ≤ 40 component seeds per dive, deterministic, full-clip,
GT-free.

**B1 pool-availability gate: SATISFIED.** 2341's pool now contains a
trajectory with per-frame target identity 0.337 (component rollout)
vs 0.0 (V6 historical) and 0.077 (V3 best-in-pool) — a material
improvement. Rollouts also generate excellent chains on 1040 (0.851),
2169 (0.873), 2353 (0.876), 2541 (0.859).

## 8. Phase C — `BASELINE_STABILITY_GATE`

Implemented GT-free (frozen thresholds: coverage ≥ 0.9 … jump-rate ≤ 0.05,
continuity ≥ 2–5 s, meaningful motion ≥ 0.10, top-1 conf strength,
volatility) over the frozen D5 op-point (conf ≥ 0.05) top-1 path.

**Honest negative finding: D5-path stability is NOT
identity-informative.** 2341's WRONG D5 path is smoother (jump rate
0.0132) than 2169's correct one (0.0251), more confident (conf p50
0.363 vs 0.232), and continuous (coverage 1.0). A stable wrong
trajectory is indistinguishable from a stable right one without
action/identity semantics, so no stability evidence can preserve 2169
while excluding 2341/2541. The gate cannot be made to fire on exactly
the right clips without per-dive constants (forbidden). Recorded as a
negative result; the D5 path remains protected inside the ranking by
the keep-margin mechanism instead.

## 9. Phase D — GT-free component selection

New component-level scorer `v7_component_quality` (frozen constants;
NOT the V6 formula) built from the V3 causal diagnosis: shape term
REQUIRING the prep→substantial-motion transition, excursion saturation
at dive scale, departure-from-rest credit, appearance coherence counted
ONLY for non-static components, continuity/coverage/NULL/ending weak
evidence, plus a velocity-plausibility (teleport) penalty for
stitched multi-member components.

Result on the corpus: the scorer ranks coherent junk components first
on every ordinary dive (junk q ≈ 4.0–4.35, correct candidates 1.5–3.6):
correct 1040-ranked-156, 2341-ranked-56 under the intermediate config.
The additive form remains gameable: the diver's real path has detector
gaps (NULL penalty) while self-coherent walkers saturate every positive
term.

## 10. Phase E — frozen action-semantic score

ONE frozen off-the-shelf representation: torchvision `r2plus1d_18`,
KINETICS400_V1 (no training, no fine-tuning; weights sha
`91a641e6…`-named cache file, sha recorded in the artifact). Input:
person-centered 16-frame tube at 360p candidate geometry (box pad 2.0),
16 frames sampled around the path's excursion peak (±0.8 s,
geometry-only; no GT event times, no dive-code timing, no
human-selected identity). Score: summed softmax mass over the frozen
airborne/diving class subset {springboard diving, diving cliff,
jumping into pool, high jump, ski jumping, skydiving, trampoline}.

**E3 benchmark (separability): PARTIAL — target families separate
decisively from persistent bystanders and static structures
(target mean 0.71–0.96 vs bystander mean 0.01–0.24 on all four
family-bearing dives), but fast unrelated movers score 0.62–0.85 mean
and the ocean max is ≈ 1.0 everywhere (jump-mosaic pseudo-components
genuinely contain airborne motion). Raw action score alone is NOT
rank-1-safe → V7-B (q + 2.0 × action) was executed and still selects
junk. Per the packet rule the model is NOT forced into the selector as
a discriminator; it is recorded as a useful static-structure filter
but not decisive.**

## 11. Phase F/G — V7 comparison (final frozen config)

| dive | D5 top-1 | V7-A | V7-B | best-in-pool (EVAL) |
|---|---|---|---|---|
| 1040 | 0.106 | 0.0 | 0.019 | 0.851 |
| 2169 | **0.963** | 0.0 | 0.000 | 0.873 |
| 2341 | 0.022 | 0.0 | 0.0 | 0.337 |
| 2353 | 0.005 | 0.0 | 0.0 | 0.876 |
| 2541 | 0.149 | 0.012 | 0.012 | 0.817 |
| 2555 | 0.518 | 0.0 | 0.003 | 0.256 |

(An earlier intermediate config without velocity-plausible walks
repaired 1040 to 0.578 and 2353 to 0.667 but regressed the 2169
control; both configurations fail the freeze gate, and the final
frozen configuration is the physics-plausible one. Both runs are
recorded in `runs/hurdle_prototype_v4/`.)

## 12. Phase H — freeze decision

**`HURDLE_TARGET_IDENTITY_V4_FREEZE` NOT created — gate FAILED**
(0/4 materially improved vs required ≥ 3; 2169 not preserved; long
wrong runs remain). Gate record: `runs/hurdle_prototype_v4/
V4_FREEZE_GATE_VERDICT.json`.

## 13. Phase I/J — repaired trajectories + V3-D0 replay

Not generated (Phase K requires the freeze). The frozen historical
`DEV_HURDLE_TRAJ_CACHE_V2` remains untouched; the frozen V3-D0 Event
Logic replay reproduces the recorded magnitudes byte-exact (pinned by
test in both the V3 and V4 suites). No Event Logic parameter changed.

## 14. Phase K — FM2 classification

**`FM2_STILL_IDENTITY_LIMITED`.** No identity freeze was achieved; V2's
causal classification stands. FM2 is not an Event Logic problem: the
frozen Event Logic was never given a correct target trajectory.

## 15. Phase L — training decision

**`IDENTITY_COMPONENT_CONSTRUCTION_STILL_PRIMARY_BLOCKER`.** Per the
packet rule a trained selector becomes justified only when proposal
completeness (✓ recall@200 = 1.0 frozen D5), hypothesis generation
(✓ repaired this cycle) and component purity (✗ 0.10–0.42) are ALL no
longer binding. Component purity is still the binding constraint; the
action-semantic benchmark (partial separation) does not change this.

## 16. 2555

`SCREEN_RECORDING_STRESS_CASE` maintained; reported separately (V7-A/B
0.0/0.003; best-in-pool 0.256). It did not veto anything.

## 17. 524

`524_AUTHORITY_CONFLICT_EXCLUDED` — untouched, read-only, absent from
all V4 artifacts (asserted by test). No HQ authority mutation.

## 18. Answers to the packet's success questions

1. **V3 negative result cleanly closed and committed?** Yes —
   `f116558`, synced to canonical server and mirror.
2. **Can transitive appearance-cluster collapse be eliminated?** The
   percolation YES (A1 bounded-degree graph); full purity NO.
3. **Can 2341's target hypothesis actually be generated?** YES — the
   pool now contains a 0.337-pf target trajectory (was 0.077/0.0).
4. **Can 2169 be preserved automatically when baseline D5 is good?**
   Not by stability evidence alone (stable-wrong paths are
   indistinguishable GT-free); the keep-margin ranking also failed.
   Honest: NO automatic preservation mechanism found this cycle.
5. **Can clean identity components be ranked GT-free?** NO.
6. **Does a frozen action-semantic model identify the diver?**
   PARTIALLY — it separates divers from bystanders/structures
   decisively, but not from airborne-looking fast movers; not decisive
   for selection.
7. **Can at least three failing HURDLE dives be repaired?** Not by a
   frozen GT-free selector (best-in-pool exists everywhere; ranking
   loses). NO freeze.
8. **What happens to frozen V3-D0 once identity is repaired?**
   Still unanswered — no repaired trajectories exist.
9. **Is training finally justified?** Not yet by the packet's rule:
   component construction (purity) is still primary-blocker; a trained
   head would sharpen appearance discrimination — the exact blocker —
   but the packet order requires the component stage to stop binding
   first. Recorded explicitly for the supervisor.

## 19. Tests

`experiments/landmark_pilot/test_hurdle_identity_v4.py` — 31 tests,
zero failures: cache reuse + manifest consistency; no-heavy-blobs in
Git; exactly-two-mechanism discipline; mutual-kNN determinism (toy);
A1 anti-percolation on the frozen corpus (single-link 1.0 vs A1 ≤ 0.2);
purity verdicts recorded; rollout velocity plausibility; 2341 pool
availability + failure-mode record; gate constants generic + honest
negative recorded; V7 artifacts complete for all dives; frozen scorer
constants + teleport penalty unit; action-model identity frozen; E3
separability (bystander/static) recorded; action score is probability
mass; no V4 freeze artifact; gate verdict recorded; V3-D0 unchanged
replay; 524 absence; 2555 separation; Paris firewall.

## 20. Gate

`SUPERVISOR_REVIEW_AFTER_HURDLE_IDENTITY_V4`
