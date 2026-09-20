# SUBJECT_CONDITIONED_IDENTITY_PILOT_L0 — Frozen Protocol

Packet: `DIVE_ANALYZER_SUBJECT_CONDITIONED_IDENTITY_PILOT_L0`
Gate: `SUPERVISOR_REVIEW_AFTER_SUBJECT_CONDITIONED_IDENTITY_PILOT_L0`
Status: **FROZEN — no redesign after held-out results are examined.**
Canonical base: `76abc08116052e39419629fd01992c706d462d7a`
(`origin/uiux-overhaul-pro-app`, merge of Independent Subject GT Expansion V1)
Worktree: dedicated `diveanalyzer-subject-identity-l0` (fresh clone, clean).

This is a **learned identity-matching pilot only**. It is NOT end-to-end
subject resolution. The unresolved production problem —
**GT-free subject reference acquisition** — is explicitly OUTSIDE this pilot.

Interface under test:

```text
HUMAN-GT ORACLE SUBJECT REFERENCE + candidate person track
  -> learned identity matcher -> MATCH / NON_MATCH / AMBIGUOUS
```

A successful L0 means ONLY:

```text
identity-matching primitive validated (given a valid reference)
reference-acquisition still open
```

---

## 1. Cohort (15 dives, 13 sessions, 4 athletes, 2 families)

All scientifically valid primary subject-resolution dives. No silent removals.
Difficult / weak dives are KEPT and stratified (Phase 3), never dropped.

| dive | family | session | athlete (diver_id) | GT authority | candidate cache | appearance cache |
|------|--------|---------|--------------------|--------------|-----------------|------------------|
| 1040 | HURDLE_ORDINARY | 66 | Maxime (1) | frozen subject chains (target_chains_v1, GT/AMBIGUOUS/WATER per-frame) | R5_FULLCLIP_CANDIDATES_V1 (frozen D5, sha `3bed1aaf…`) | osnet_emb_cache_v1.npz (frozen OSNet) |
| 2169 | HURDLE_ORDINARY | 134 | Maxime (1) | chains | same | same |
| 2341 | HURDLE_ORDINARY | 148 | FANNY (7) | chains | same | same |
| 2353 | HURDLE_DRILL | 155 | Maxime (1) | chains | same | same |
| 2541 | HURDLE_ORDINARY | 144 | Maxime (1) | chains | same | same |
| 2526 | HURDLE_ORDINARY | 147 | MAT (14) | SUBJECT_GT_LEVEL_B_INDEPENDENT_V1 | R5_FULLCLIP_CANDIDATES_INDEP_V1 | osnet_emb_indep_v1.npz |
| 2839 | HURDLE_ORDINARY | 203 | Maxime (1) | LEVEL_B_INDEPENDENT_V1 | INDEP | INDEP |
| 133 | STANDING | 25 | Maxime (1) | SUBJECT_GT_LEVEL_A_STANDING_V1 | R5_FULLCLIP_CANDIDATES_COHORT_V1 (sha `b2f01e41…`) | osnet_emb_cohort_v1.npz |
| 311 | STANDING | 32 | Maxime (1) | LEVEL_A | COHORT | COHORT |
| 676 | STANDING | 46 | FANNY (7) | LEVEL_A | COHORT | COHORT |
| 2387 | STANDING | 144 | Maxime (1) | LEVEL_A | COHORT | COHORT |
| 1304 | STANDING_APPROACH | 81 | FANNY (7) | LEVEL_B | INDEP | INDEP |
| 2204 | STANDING_APPROACH | 137 | FANNY (7) | LEVEL_B | INDEP | INDEP |
| 2223 | STANDING | 137 | LOUIS (10) | LEVEL_B | INDEP | INDEP |
| 2583 | STANDING | 158 | Maxime (1) | LEVEL_B | INDEP | INDEP |

Notes:

- Session 144 = {2541, 2387}; session 137 = {2204, 2223}; all other
  sessions hold a single cohort dive. Session mapping for the 9 older dives
  verified against `PILOT_MANIFEST_V1` + expanded-dataset session list
  {25,32,46,66,81,134,137,144,147,148,155,158,203}.
- `dive_rows` family cell for 2839 reads "STANDING" in one JSON row but the
  frozen analysis `FAMILY` map, the 5124D inward code, and the frozen
  7-HURDLE / 8-STANDING counts all place 2839 in HURDLE. This protocol
  freezes 2839 = HURDLE_ORDINARY and records the row typo without
  reinterpreting any authority.
- 524 (`AUTHORITY_CONFLICT_EXCLUDED`), 2555 (`SCREEN_RECORDING_STRESS_CASE`),
  Paris (`EXTERNAL_ONLY`), `INTERNAL_EVAL`, `FINAL_HOLDOUT` are NEVER loaded.
- HURDLE chains, Level-A, Level-B authorities are READ-ONLY. No
  reinterpretation, no rewriting, no new labels.

Frozen identities (asserted at runtime):

- D5 model `models/frozen/DIVER_DETECTOR_D5_A_V8N_best.pt`
  sha256 `82b420c4583f8271b1eb3429b14dadf0a1e27477249de7b6a0b9d42a788dcf25`,
  floor_conf 0.001, NMS 0.45, imgsz 640, cap 200.
- OSNet weights (host-only `models/reid/osnet_x1_0_market1501.pth`, gitignored)
  sha256 `2809d3227f7d078f6045f7feb874a34d0684f0e0057b264b99adccf7d4519154`,
  recipe pad 1.3, resize 256x128 (h,w), ImageNet norm, L2-normalized 512-d.
- V2 module `subject_reference_acquisition_v2.py`
  sha256 `01a17dd77131076d323b4adbc0790ac1d284f36fe39ebfb98a0ef64ad7a1d73e`
  (tracklet construction + features + Q0 tier constants, imported unmodified).
- Level-A `SUBJECT_GT_LEVEL_A_STANDING_V1` sha `d805aac2…`,
  Level-B `SUBJECT_GT_LEVEL_B_INDEPENDENT_V1` sha `dc958909…`.
- Candidate Quality V3 = `CANDIDATE_QUALITY_V3_PARTIAL` (phantom top-1 9→0,
  top-1 0/18; indep replay 0/12, phantom 1→0, all wrong tops supported
  movers). V3 code/constants are CONSUMED read-only (Q0 tier), never altered.

Host caches (`runs/…`, gitignored) are READ-ONLY inputs resolved via
`L0_CACHE_DIRS` (sibling worktree paths). The L0 worktree writes only to
`runs/subject_identity_l0/` (gitignored) + durable `docs/science/` artifacts.
No D5 inference. No OSNet training. OSNet inference is limited to the bounded
GT-reference-crop extraction below (frozen weights/recipe only).

---

## 2. Candidate units (tracklets, frozen construction)

Candidate units are the frozen V2 tracklets: `v2.tracklets_and_flow(clip)`
over the frozen full-clip D5 candidate caches, with `v2.tracklet_features`
gating (features `None` → tracklet dropped before scoring, as in V3).
`tid` values are per-dive V2 identifiers, preserved verbatim.

For every dive the protocol records:

- family / session / athlete / GT authority / cache identity;
- n tracklets, n scored (features not-None), proposal reachability class;
- subject anchor coverage; number of viable subject candidates.

---

## 3. Proposal / association reachability (mandatory, GT eval-only)

Per dive, using GT ONLY for evaluation:

- `MATCHER_ELIGIBLE`: ≥1 MATCH candidate (label rule §6).
- `PARTIAL_PROPOSAL_REACHABILITY`: 0 MATCH but ≥1 AMBIGUOUS candidate with
  partial subject overlap (0 < purity < 1).
- `NO_POSITIVE_CANDIDATE`: no MATCH and no partial-overlap AMBIGUOUS.

Report per dive: subject candidate exists? best available subject purity,
subject anchor coverage, number of viable (MATCH) subject candidates, reason
if partial/not evaluable. PARTIAL and NO_POSITIVE dives STAY in the overall
report (Layer B). They are scored `MATCHER_NOT_EVALUABLE`, never
`MATCHER_WRONG`.

---

## 4. Two metric layers (never merged)

- **LAYER A — MATCHER-CONDITIONAL**: only `MATCHER_ELIGIBLE` dives.
  Question: given the candidate set contains the subject, can the matcher
  select it? Primary metric lives here.
- **LAYER B — END-TO-END UPPER BOUND**: all 15 dives. Proposal misses and
  association fragmentation stay visible as stack failures, NEVER attributed
  to the matcher.

---

## 5. Oracle reference interface — `ORACLE_WITHIN_CLIP_REFERENCE_V1`

The reference comes ONLY from HUMAN-authoritative subject annotations on the
SAME clip (within-clip oracle). It exists solely to isolate matching. The
reference is NEVER selected by matcher performance.

Sources:

- HURDLE dives: `status == "GT"` boxes from the frozen `target_chains_v1`
  (dense per-frame subject boxes; AMBIGUOUS/WATER entries never used).
- STANDING (133/311/676/2387): `visibility == "visible"` boxes from
  `SUBJECT_GT_LEVEL_A_STANDING_V1`.
- INDEP (1304/2204/2223/2526/2583/2839): `visibility == "visible"` boxes from
  `SUBJECT_GT_LEVEL_B_INDEPENDENT_V1`.

Construction (deterministic):

1. Order the dive's HUMAN_REVIEWED visible subject boxes by frame index.
2. Embed each box with the FROZEN OSNet weights/recipe (pad 1.3, 256x128,
   L2). Bounded GT-crop extraction is authorized because GT-box embeddings
   do not already exist; this is NOT representation research (no training,
   no weight change, no recipe change, code path reuses the frozen
   `crop_tensor`/`to_input`/`OSNetWrap` recipe).
3. Aggregate the REFERENCE SUBSET (see §6) by L2-normalized mean:
   `proto = l2(mean(l2(vecs)))`. Single-vector dives use that vector.

---

## 6. Anti-leakage reference design (deterministic, pre-registered)

Split each dive's ordered HUMAN_REVIEWED visible boxes into two interleaved
temporal subsets by index parity:

- REFERENCE subset = even indices (0, 2, 4, …)
- EVALUATION subset = odd indices (1, 3, 5, …)

The oracle prototype uses ONLY the reference subset. Candidate appearance
statistics (§7) use ONLY candidate boxes whose frame index is NOT an exact
reference frame (reference-frame exclusion). Trivial same-frame /
identical-crop duplication therefore cannot dominate the score.

Fallback (documented per dive, never optimized on matcher results):

- If the dive has <4 HUMAN_REVIEWED visible boxes with successful embeddings,
  the two-way split is abandoned: prototype = all visible boxes, and the
  reference-frame exclusion is still applied where possible. The dive report
  marks `reference_split = FALLBACK_ALL_BOXES`.
- If a candidate has zero non-reference-frame embeddings, its appearance
  features are NULL → the candidate is UNSCORABLE (excluded from ranking,
  counted separately; a dive left with zero scorable MATCH candidates is
  reclassified per §3, not forced).
- The even/odd assignment is NEVER swapped or re-optimized on held-out
  results. (Where density permits, the swapped construction may be reported
  as a NON-HEADLINE diagnostic only if pre-declared here — it is NOT
  pre-declared, so no swap is run in L0.)

GT density note: HURDLE chains are dense (per-frame); STANDING/INDEP anchors
are sparse (~0.5 s grid + extras). The same parity rule applies to all; the
fallback above handles sparse dives deterministically.

---

## 7. Candidate labels (GT-only, three classes)

Labels derive EXCLUSIVELY from HUMAN-authoritative subject GT, evaluated on
the candidate's EVALUABLE support:

- HURDLE: GT-evaluable frames = tracklet frames overlapping a `GT`-status
  chain entry. Purity = fraction with normalized center distance ≤ 0.06
  (frozen `reference_purity` radius).
- STANDING/INDEP: evaluable anchors = visible Level-A/Level-B anchors whose
  frame has a tracklet box. Consistency = center distance ≤ 0.06 (frozen
  Level-A consistency rule). Purity = consistent / evaluable (None if zero
  evaluable).

Unified label rule (pre-registered, no per-dive tuning):

- `MATCH`: n_evaluable ≥ 2 AND purity ≥ 0.75.
- `NON_MATCH`: n_evaluable ≥ 2 AND purity ≤ 0.25.
- `AMBIGUOUS`: everything else, including subject-adjacent mixed fragments,
  identity switches, partial purity (0.25 < purity < 0.75), and insufficient
  observation (n_evaluable < 2, purity None).

Training target: `MATCH vs NON_MATCH`. `AMBIGUOUS` is EXCLUDED from binary
fitting (weight 0) but RETAINED for ranking/evaluation/error analysis
(including its score distribution). No learned ambiguity classifier in L0.

Rationale for 0.75/0.25 (not 1.0/0.0): association fragments of the true
subject routinely carry 1–2 inconsistent frames; requiring literal 1.0 would
relabel genuine subject tracklets AMBIGUOUS and erase the positive class on
fragmented dives, while 0.5 would force mixed fragments into clean classes.
The strict-label sensitivity (1.0/0.0) is reported as a diagnostic column
only (counts, not a second training target).

---

## 8. Features (exact ordered vector, 11-D, continuous)

All features are GT-free at inference except the oracle-reference-conditioned
appearance block (which is the isolated interface under test). Forbidden
inputs (§9) are structurally excluded (asserted by tests).

For candidate tracklet T on dive D with oracle prototype P (from §5–6):

Appearance block (frozen OSNet cosine, eval-frames only after
reference-frame exclusion; UNSCORABLE if empty):

1. `cos_mean` — mean cosine(T_eval_embs, P)
2. `cos_median` — median cosine
3. `cos_max` — max cosine
4. `cos_q75` — 75th-percentile cosine
5. `cos_std` — population std of cosine (0.0 if single embedding)

Support / quality block (V2/V3 GT-free semantics, full tracklet):

6. `support_frac` — V3 support fraction (conf ≥ 0.05 within radius 0.06)
7. `conf_median` — median D5 confidence of tracklet boxes
8. `conf_q75` — 75th-percentile D5 confidence
9. `log_n_obs` — log1p(n_obs), n_obs = #tracklet boxes
10. `span_s` — (fi_last − fi_first) / fps

Coherence block (frozen within-track appearance, no a priori sign):

11. `track_coh_mean` — mean pairwise cosine among T_eval_embs
    (NULL → UNSCORABLE handling as above; single-embedding tracks define
    coherence = 1.0 deterministically)

Fixed order above is the model input order (tests assert it). No raw 512-D
embeddings enter L0. No concatenation of embedding vectors.

---

## 9. Forbidden features (structural exclusion)

Never included: `dive_id`, athlete integer, family label, session ID, GT
purity, GT event times, takeoff/apex/water-contact, A0/A1 correctness,
candidate GT rank, file/path-derived identity codes, any post-hoc
dive/session/family indicator. Tests assert absence by feature-name audit +
a source-column audit on the design matrix.

---

## 10. Frozen baselines (before learning)

- **B0 — FROZEN APPEARANCE SIMILARITY**: score = `cos_mean` (§8, feature 1).
  Oracle reference → candidate via frozen OSNet cosine. No training.
  Tie-break: higher `cos_max`, then lower `tid`.
- **B1 — FROZEN APPEARANCE + V3 SUPPORT ORDERING**: rank key =
  (`support_tier` desc, `cos_mean` desc, `cos_max` desc, `tid` asc) where
  `support_tier = 1 iff support_count ≥ 1` (reused Q0 existence-of-evidence
  boundary; frozen constants 0.05/0.06; graceful fallback = B0 order when a
  dive has zero supported candidates). No new constants.

Baselines use the SAME reference subsets, exclusion rule, and scorable set
as L0 (like-for-like). They establish whether learning adds value.

---

## 11. L0 model (exactly ONE family)

**L2 LOGISTIC REGRESSION** (`sklearn.linear_model.LogisticRegression`):

- solver `lbfgs`, C = 1.0, max_iter = 1000, tol = 1e-4,
  penalty `l2`, fit_intercept True, class_weight None (explicit sample
  weights instead), n_jobs 1, random_state 0 (lbfgs is deterministic;
  seed fixed for API stability).
- Standardization: zero-mean / unit-variance using TRAINING FOLD ONLY
  (per-feature mean/std stored per fold; held-out dive transformed with
  those statistics; zero-variance training features → std := 1.0
  deterministically, recorded per fold).
- No architecture search, no sweep, no held-out tuning of any kind.

Sample weighting (pre-registered exact formula): for a training fold with D
training dives, candidate i on dive d with clean class c ∈ {MATCH,
NON_MATCH} and per-dive class count n_{d,c} > 0:

```text
w_i = (1 / D) * (1 / (2 * n_{d,c}))
```

Each training dive contributes total weight 1/D; within a dive MATCH and
NON_MATCH each aggregate to 1/(2D). AMBIGUOUS weight = 0. Dives with zero
clean positives or zero clean negatives in the training fold contribute only
their present class (renormalized within-dive to total 1/D, documented per
fold — the 50/50 split applies where both classes exist). No per-fold tuning
on held-out performance.

Determinism: `OMP_NUM_THREADS=MKL_NUM_THREADS=OPENBLAS_NUM_THREADS=1`,
single-thread BLAS, fixed feature order (§8), fold order sorted by dive id
(LODO) / session id (LOSO), fixed logistic config, JSON serialization with
sorted keys + 6-decimal rounding. Repeated execution must reproduce rankings
and scores within 1e-9.

---

## 12. Grouped evaluation

- **Primary: LEAVE_ONE_DIVE_OUT (LODO)** — 15 folds. For held-out dive h:
  train on all other dives' clean (MATCH/NON_MATCH) candidates, standardize
  with training fold only, fit, score ALL scorable candidates of h
  (MATCH + NON_MATCH + AMBIGUOUS all ranked; training uses clean only).
- **Supplementary: LEAVE_ONE_SESSION_OUT (LOSO-session)** — sessions as in
  §1 (multi-dive sessions {137: 2204+2223} and {144: 2541+2387} held out
  together; all others coincide with LODO). Reported SEPARATELY, never
  merged with LODO.
- No held-out data may influence standardization, class balance, threshold,
  feature selection, or regularization (tests assert fold isolation).
- Athlete-aware reporting is descriptive only (per-athlete top-1 where sample
  count permits). Explicit statement is REQUIRED: this pilot does not
  demonstrate generalization to unseen athletes. No headline
  leave-one-athlete-out claim.

---

## 13. Metrics

Primary (Layer A, LODO):

- **HELD-OUT DIVE TOP-1 SUBJECT SELECTION**: fraction of matcher-eligible
  dives where the highest-scoring scorable candidate is MATCH.
  Report `correct / eligible` + exact per-dive table. No candidate-level
  AUROC as primary.

Secondary (per dive + pooled Layer A):

- subject rank distribution: mean reciprocal rank, median rank, top-3/5/10
  hit rates; best MATCH score, top NON_MATCH score, score margin
  (top_MATCH − top_NON_MATCH, signed); AMBIGUOUS score distribution
  (median, IQR, overlap with MATCH/NON_MATCH).
- Candidate-level ROC-AUC / AP are SUPPLEMENTARY ONLY, explicitly labeled
  correlated/non-independent (thousands of correlated candidates; the
  statistical unit stays dive/session).

Family reporting: HURDLE and STANDING ALWAYS separated alongside pooled.
Weak-D5/fragmentation dives: report proposal reachability + association
reachability + matcher-conditional result + end-to-end result; non-evaluable
dives are `MATCHER_NOT_EVALUABLE`, never `MATCHER_WRONG`.

No production threshold is chosen. No abstention calibration. Diagnostic
margins only.

---

## 14. Success classification (exactly one)

- `IDENTITY_MATCHER_L0_PROMISING`: clear held-out dive top-1 improvement of
  L0 over BOTH B0 and B1; not confined to one family; survives grouped
  (LODO + session) evaluation; not driven by a single dive/session; works
  where subject candidates are actually reachable.
- `IDENTITY_MATCHER_L0_WEAK`: some ranking improvement but inconsistent /
  too small to trust.
- `IDENTITY_MATCHER_L0_FAILS`: no reliable grouped improvement over frozen
  baselines.

Interpretation gate: at most *"subject-conditioned identity learning is
scientifically promising when a valid reference is supplied"*. NEVER
*"Dive Analyzer can now automatically find the user"*. The oracle reference
is non-production by construction.

Next-research decision (exactly one):

- `IMPROVE_REFERENCE_ACQUISITION_NEXT` (L0 strong with oracle),
- `SCALE_IDENTITY_MATCHER_DATA_NEXT` (signal exists, data size limits
  confidence),
- `TEST_RICHER_IDENTITY_REPRESENTATION_NEXT` (representation separability
  demonstrated as bottleneck),
- `RETURN_TO_ASSOCIATION_ROBUSTNESS_NEXT` (positives frequently missing /
  fragmented),
- `STOP_IDENTITY_LEARNING_LINE`.

No L1 / neural matcher / OSNet fine-tune is authorized regardless of outcome
without supervisor review of L0 first.

---

## 15. Scope firewalls (binding)

ARMSTAND deferred. No Event Logic execution/tuning. Media Backbone closed
(expected B2 writes = 0, media revisions = 0; read-only proxy decode for GT
crop embedding extraction is the sole media access). Protected data never
accessed: 524, 2555, Paris, INTERNAL_EVAL, FINAL_HOLDOUT. No D5 training /
modification / floor-confidence / NMS / imgsz change. No OSNet/ReID training.
No new representation family. No HQ branch. No Candidate Quality V3 change.
No A0/A1 reopen. No new reference-acquisition heuristic. No random frame or
candidate splits. No per-dive / per-family tuning. No human labels beyond the
frozen authorities.

Resource envelope: D5 inference 0; new human labels 0; OSNet training 0;
bounded frozen-OSNet GT-crop inference only; matcher training = small CPU
logistic task (no multi-hour MPS job).

---

## 16. Required tests (packet-owned, zero failures)

cohort identity (15 dives + mapping) · GT authority SHA identity (L1A/L1B/D5/
OSNet/V2) · reference construction determinism · reference/candidate
anti-leakage (reference frames excluded from candidate stats; no identical
crop domination) · feature-order determinism · no forbidden features ·
fold isolation (no held-out influence on scaler/weights/config) ·
training-fold-only standardization · dive-equal weighting + within-dive class
balance · LODO split (15 folds) · session grouped split (137/144 grouped) ·
weak-D5 stratification columns present · B0/B1 identity (frozen definitions) ·
L0 deterministic fit (repeat fit bit-identical within 1e-9) ·
protected-data firewall (524/2555/Paris/INTERNAL_EVAL/holdout never loaded) ·
no D5 mutation · no OSNet training · no new labels · no B2 mutation.

---

## 17. Durable artifacts

- `docs/science/SUBJECT_CONDITIONED_IDENTITY_PILOT_L0_PROTOCOL.md` (this file)
- `docs/science/DIVE_ANALYZER_SUBJECT_CONDITIONED_IDENTITY_PILOT_L0.md`
- `docs/science/DIVE_ANALYZER_SUBJECT_CONDITIONED_IDENTITY_PILOT_L0.json`
- Code: `experiments/subject_resolution/subject_conditioned_identity_l0.py`
  (+ `test_subject_conditioned_identity_l0.py`); run outputs gitignored under
  `runs/subject_identity_l0/`. Retained model artifacts (if any) marked
  `EXPERIMENTAL / NOT_PRODUCTION / ORACLE_REFERENCE_DEPENDENT`.
- `docs/PROJECT_STATE.md` updated union-style (append science record, keep
  concurrent UI/infra history).

Protocol freeze record: commit hash + file SHA recorded in the result JSON
before any learned test-fold result is examined (§18).

---

## 18. Freeze attestation

This protocol was committed BEFORE fitting any model or examining any learned
held-out result. Baselines B0/B1 were defined here (formulae above) and may
be executed after freezing; the LEARNED model (L0) is fitted only after the
freeze commit. Any post-freeze correction requires a new protocol version and
supervisor review — silent redesign on held-out results is prohibited.
