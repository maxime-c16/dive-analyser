# HURDLE Identity Selection V2 Report — R5 / R5-B

Task packet: `HURDLE_TARGET_IDENTITY_V2` (supervisor packet, continuation of
`HURDLE_TARGET_IDENTITY_REPAIR` / FM2 causal chain).
Thread: local Mac worktree `~/.perso/diveanalyzer-identity-v2` (branch
`hurdle-identity-v2`, cut at canonical server HEAD `d4c0c8a` on
`uiux-overhaul-pro-app`; the packet-reported HEAD `ef1e55e` is an ancestor —
one unrelated media-backbone P2 commit landed in parallel during packet
start verification). All heavy inference ran on Apple M2 under
`caffeinate -i -s`, one video at a time, memory-bounded.
Frozen detector: `DIVER_DETECTOR_D5_A_V8N_best.pt`
(sha256 `82b420c4583f8271…dcf25` verified before use), conf floor 0.001,
NMS 0.45, imgsz 640, MPS — identical to the V1 Phase-A recipe, re-verified
against every proxy sha256 in `HURDLE_RAW_CANDIDATES_AUDIT_V1.json`.
GT (HURDLE_IDENTITY_EVAL_V1 chains/anchors) was used for EVALUATION only;
the one GT-seeded run is explicitly labeled a diagnostic (§7). No D5
retraining, no appearance training, no HQ-authority modification, no Event
Logic changes, no Paris, no 524 GT collection.

---

## 1. R4 confound (Phase A) — `R4_STATE_SPACE_AUDIT`

`HURDLE_R5_STATE_SPACE_AUDIT_V1.json` re-slices the committed
`HURDLE_TARGET_IDENTITY_CLASSIFICATION_V1` per-frame target ranks
(0-based, floor conf 0.001, cap 200) into candidate-graph recall per K:

| dive | n eval | @12 (R4's graph) | @24 | @48 | @96 | @200 | excl@12 |
|---|---|---|---|---|---|---|---|
| 1040 | 161 | 0.342 | 0.410 | 0.975 | 1.000 | 1.000 | 0.658 |
| 2169 | 434 | 0.977 | 0.993 | 0.995 | 1.000 | 1.000 | 0.023 |
| 2341 | 273 | 0.505 | 0.659 | 0.883 | 0.985 | 1.000 | 0.494 |
| 2353 | 411 | 0.141 | 0.212 | 0.998 | 1.000 | 1.000 | 0.859 |
| 2541 | 262 | 0.351 | 0.492 | 0.996 | 1.000 | 1.000 | 0.649 |
| 2555 | 336 | 0.851 | 0.955 | 0.991 | 1.000 | 1.000 | 0.149 |

**A1 answer: 50.2% of all primary evaluable frames (774/1541) had the true
target OUTSIDE R4's top-12 state space** (2353 85.9%, 1040 65.8%,
2541 64.9%, 2341 49.4%). On those frames no appearance model, no matter how
discriminative, could ever select the target. The previous R4 attempt is
therefore NOT valid evidence that appearance-aware association is
intrinsically insufficient: R4 was majority-crippled by top-12 truncation,
compounded by a non-person encoder (§5). At K=96 recall ≥ 0.985 on every
classified dive; at the frozen floor cap 200 recall is 1.000.

## 2. Full-clip inference correction (Phase B)

The V1 diagnostics inferred only over GT-derived eval intervals. This packet
re-ran the identical frozen D5 recipe over the **full production-equivalent
clip** for all six primary dives (`R5_FULLCLIP_CANDIDATES_V1.json`:
332/1078/607/1437/975/722 frames; `interval_s = [0, video_end]`), with GT
times recorded only under an `gt_eval_only` metadata key. Every new selector
path consumes this artifact exclusively; a regression test pins the GT-free
window semantics (`test_fullclip_cache_is_gt_free_full_window`).

## 3. R5-A — candidate-complete sparse tracklets (Phase C)

`r5_tracklets_v1.py`: gated greedy multi-track association (velocity-bounded
displacement + size compatibility + trailing straightness gate) builds
tracklets over ALL floor candidates — no pruning, so per-frame target
inclusion equals the Phase-A-measured 100% (C1 satisfied at K=200 without
compute-motivated truncation). Selection layers (all GT-free, full clip,
flow-compensated against a median camera-flow estimate):

- preparation anchors (C3): long stable board-region tracklets; static
  early sections are REQUIRED evidence, never penalized;
- departure rollouts: velocity-gated chains with acceleration-bounded span
  velocity (arc-capable, clutter-random-walk-hostile), departure-from-rest
  ratio test, dive horizon, entry-like disappearance;
- whole-clip dive-shape scoring (C4): stable prep → coherent departure →
  descent → entry; conf only as a weak, departure-scoped term (C2);
- NULL/gaps: uncovered frames stay NULL; no Event Logic inside the selector.

**R5-A frozen-config evaluation (Phase D, `HURDLE_R5A_EVAL_V1.json`)**,
vs D5 op top-1 and historical R4 best-of-grid (per-frame correct /
longest wrong run):

| dive | R5-A | D5 top-1 | R4 hist | verdict |
|---|---|---|---|---|
| 1040 | 0.006 / 160 | 0.106 / 122 | 0.000 | fail |
| 2169 | 0.000 / 434 | 0.963 / 11 | 0.912 | catastrophic regression |
| 2341 | 0.000 / 273 | 0.022 / 260 | 0.000 | fail |
| 2353 | 0.365 / 23 | 0.005 / 363 | 0.000 | repair |
| 2541 | 0.099 / 220 | 0.149 / 173 | 0.153 | fail |
| 2555 | 0.000 / 336 | 0.518 / 33 | — | fail |

One dive repaired (2353: the persistent bystander is rejected as a
never-departing static object and the real departure chain wins, longest
wrong run 363 → 23). Engineering-variant diagnostics during the packet
observed 1040 up to 0.360 and 2555 up to 0.306 in isolated configurations,
but no single frozen configuration repaired more than one ordinary dive —
the geometric-only scorer is gameable by short accelerating "sprint" chains
and by other genuinely moving pool objects with dive-scale excursions
(2169 contains such movers; its R5-A catastrophic regression comes from
exactly this). These transient observations are recorded as diagnostics,
not results.

## 4. Appearance separability benchmark (Phase E)

`phase_hurdle_e_appearance_benchmark_v1.py`; pair construction from GT
chains (eval authority only): same-target temporal pairs (Δt ≥ 1 s),
target-vs-distractor same-frame pairs, target-vs-persistent-background;
GT never enters inference. Two frozen encoders, no training:

| dive | E0 ResNet50-ImageNet margin/AUC | E1 OSNet-Market1501 margin/AUC |
|---|---|---|
| 1040 | 0.042 / 0.604 | 0.152 / 0.821 |
| 2169 | 0.152 / 0.920 | 0.219 / 0.870 |
| 2341 | 0.217 / 0.979 | 0.206 / 0.931 |
| 2353 | 0.105 / 0.813 | 0.202 / 0.982 |
| 2541 | 0.114 / 0.871 | 0.237 / 0.907 |
| 2555 | −0.005 / 0.483 | 0.024 / 0.550 |
| primary agg | 0.126 / 0.837 | 0.203 / 0.902 |

E1 OSNet (Market-1501, official torchreid model-zoo checkpoint,
sha256 `2809d322…5191544`) is discriminative on all five ordinary dives
(AUC 0.82–0.98, nearest-neighbor target-retrieval ≈ 0.98–1.0); E0 (the R4
encoder) is weak on 1040 and useless on 2555. **Success question 3 is
answered YES for the ordinary corpus** — the tiny 360p divers ARE
separable with a proper frozen person-ReID encoder; R4's ResNet50 was the
wrong instrument. E2 (a second self-supervised encoder) was skipped: E1
already cleared the Phase-G precondition and the packet caps new encoders
at two.

Additional measured structure (report §7 of the artifact): same-target
cos prep–prep 0.89–0.97, prep–flight 0.67–0.79, flight–flight 0.74–0.83,
vs distractor ~0.65 ± 0.09 — appearance verifies identity strongly during
static phases but CANNOT bridge the pose transition alone; association
must be geometry-primary with appearance as a bounded term. The Market-1501
classifier head as an absolute "person-ness" prior was tested and
REJECTED (AUC 0.03–1.0, unstable on ~30 px crops).

## 5. HQ appearance-only experiment (Phase F)

`phase_hurdle_f_hq_appearance_v1.py`. D5 was NOT run on HQ; proposals
remain the frozen proxy_360p candidate sets. The 360p crop box maps into
the HQ display rendition (identity spatial map, PTS_EQUIVALENT VFR PTS
mapping, rotation-aware decode). All six HQ renditions were fetched
read-only and **verified byte-identical to
`HIGHRES_ANALYSIS_SOURCE_MANIFEST_V1` sha256s**.

OSNet separability, proxy crops vs HQ-mapped crops (margin / ROC-AUC):

| dive | proxy 360p | HQ mapped |
|---|---|---|
| 1040 | 0.179 / 0.766 | 0.134 / 0.850 |
| 2169 | 0.258 / 0.958 | 0.221 / 0.951 |
| 2341 | 0.242 / 0.982 | 0.256 / 0.995 |
| 2353 | 0.218 / 0.975 | 0.169 / 0.940 |
| 2541 | 0.258 / 0.934 | 0.216 / 0.925 |
| aggregate | 0.231 / 0.923 | 0.199 / 0.932 |

**F1 gate: `MIXED_HQ_APPEARANCE_GAIN`.** HQ does not materially improve
appearance separation (aggregate margin −0.03, AUC +0.01; 2341 improves,
1040's AUC improves but its margin drops, 2169/2353/2541 slightly worse).
The frozen 360p detector/geometry representation is unchanged; if a future
selector wants HQ embeddings for the 2341 class of dives it may route
per-dive, but there is no global HQ win. (2555: only 5 PTS-mappable
frames — below the reporting floor; stress case, excluded from the
aggregate.)

## 6. R5-B — frozen-ReID global association (Phase G)

`r5b_association_v1.py` + `phase_hurdle_r5b_reid_v1.py`: R5-A
candidate-complete tracklet graph → flow-compensated chronological greedy
assignment of anchors + movers with frozen-OSNet component prototypes
(EWMA 0.3), two-tier cosine floors (static-static 0.85, mover 0.70 —
derived from the §4 pair distributions), anchor truncation at the first
mover departure, and the same dive-shape scorer. **R5-B frozen-config
evaluation (`HURDLE_R5B_EVAL_V1.json`)**: 1040 0.000, 2169 0.000,
2341 0.051, 2353 0.000, 2541 0.000, 2555 0.000 — no dive repaired.
Appearance coherence of the chosen components was high (0.78–0.89), i.e.
components are appearance-consistent but the GT-free component SELECTION
still prefers junk with prep-shaped stable segments.

**Oracle diagnostic (`HURDLE_R5B_ORACLE_DIAGNOSTIC_V1.json`)** —
appearance-guided per-frame tracking with the prototype seeded from the GT
prep crop (EXPLICITLY a diagnostic ceiling, not a selector; GT used as
seed only): 2169 0.883, 2341 0.472, 1040 0.000, 2353 0.000, 2541 0.000.
The association machinery can recover dive-scale trajectories with a
correct appearance seed on some dives, but naive per-frame NN tracking
drifts without re-detection, and no GT-free prototype-selection mechanism
tested in this packet (anchor self-reference, component EWMAs,
classifier-head person-ness) reliably identifies the diver's prep crop.

## 7. DEVELOPMENT selection gate (Phase H)

Required: major improvement over D5 top-1; ≥2 previously failing ordinary
dives repaired; no catastrophic 2169 regression; long wrong runs reduced;
2555 separate; GT-free mechanism; no Paris. **Verdict: GATE FAILED** —
R5-A repairs exactly one ordinary dive and regresses 2169; R5-B repairs
none. No selector is eligible for freeze; nothing was frozen on
best-of-grid tuning.

## 8. Identity freeze / repaired trajectories / V3-D0 replay (Phases I–K)

- `HURDLE_TARGET_IDENTITY_V2_FREEZE` NOT created (gate failed).
- No repaired trajectories were generated (Phase J requires the freeze).
- Phase K was executed on the historical arm only:
  `phase_k_v3d0_replay_identity_v2.py` re-runs the frozen
  `proposer_event_logic_v3_d0.py` (params verified against the D0-owned
  freeze keys) on the frozen `DEV_HURDLE_TRAJ_CACHE_V2` and reproduces the
  recorded magnitudes exactly (1040 |to| 1.9947 s / |wc| 2.511 s; 2169
  0.4123 / 0.2872) and adds the missing per-dive baseline:
  2341 to −1.01/wc +3.41 s, 2353 −1.81/−2.24 s, 2541 −15.02/−14.91 s,
  2555 −2.61/−7.48 s.
- **K1 causal answers with repaired trajectories unavailable:**
  - 1040 (~2 s takeoff failure): UNRESOLVED — repair not achieved; the
    replayed trajectory remains the structure distractor.
  - 2341 (next-diver/static-object failure): UNRESOLVED — persists.
  - 2353 (persistent bystander): candidate mechanism demonstrated (R5-A
    repair 0.365, longest wrong 363 → 23) but not frozen → not replayed.
  - 2541 (catastrophic false trajectory): UNRESOLVED (−15 s errors).
  - 2169 (already-good): preserved by the frozen Event Logic unchanged
    (0.41/0.29 s on the historical trajectory).

## 9. FM2 final reclassification (Phase L)

**`FM2_STILL_IDENTITY_LIMITED`.** The V1 correction stands (selection
failure, not detector insufficiency); this packet adds that the top-12
confound was the dominant R4 artifact, that a discriminative frozen person
encoder exists, and that identity repair is still not achieved in a frozen
configuration. Event Logic remains frozen; V3-F was not implemented
(Phase P honored). No V3-D0 parameter changed anywhere in this packet.

## 10. 524 authority conflict (Phase M)

Read-only reconciliation (`phase_m_524_mapping_audit_v1.py`,
`HURDLE_M_524_MAPPING_AUDIT_V1.json`): HQ media sha256 MATCHES the
manifest (`0cf0174a9122…4197`); the proxy used by the identity thread
(`media/pulled/524.mp4`) is byte-identical (sha256 `85c2c7ed…841b`) to the
server's `media/cache/proxy_360p/55/2d/…` rendition referenced by the
manifest's `current_proxy_path`. The MAPPING ITSELF does not reproduce:
at the HQ thread's exact claimed parameters (scale 1.25, hflip, loc
(93,8), template 384×683) NCC is 0.24–0.32 (claimed ~0.74); an exhaustive
scale 0.4–2.0 × flip × blur-equalized search peaks at 0.56–0.64 at
UNSTABLE, frame-varying parameters — below the 0.65 quality threshold.
**Verdict: `524_MAPPING_AUTHORITY_CONFLICT_CONFIRMED`.** The HQ manifest
was not modified; 524 remains `AUTHORITY_CONFLICT_EXCLUDED`; no human
labels requested.

## 11. 2555 policy (Phase N)

2555 is reported both as `SCREEN_RECORDING_STRESS_CASE` and pooled
supplementary. On every instrument it degrades: appearance AUC 0.48–0.55
(both encoders), R5-A/R5-B ≈ 0.000, oracle 0.036, and only 5 HQ PTS-mapped
frames. Behavior is consistent: the screen-recording rendition is outside
the domain of all three components (detector-candidate geometry, ReID
statistics, dive-shape priors). Policy: 2555 stays a stress case and
should NOT be promoted to the primary corpus on this evidence; it never
alone determines a freeze.

## 12. Detector status (Phase O)

**`D5_DETECTOR_REMAINS_CLOSED`.** Fresh candidate-recall evidence
re-confirms the 100% floor-proposal result (recall@200 = 1.000 on every
classified dive; §1). No D5 retraining was performed or authorized.

## 13. Tests (Phase Q)

`experiments/landmark_pilot/test_hurdle_identity_v2.py` — 21 tests, zero
failures (run under the isolated `.venv-reid`): top-K audit math;
candidate-complete recall (every instance owned); sparse-edge gates;
bridge teleport rejection; GT-free full-clip window semantics; NULL/gap
behavior; long static preparation as anchor; persistent static distractor
never earns departure; next-diver distractor isolation; screen-recording
width handling; R5-B static classification + dive-shape semantics;
appearance embedding determinism; HQ manifest untouched + sha verified;
524 exclusion; Paris firewall (no Paris strings/ids in any artifact);
524 audit verdict; no premature freeze artifact; V3-D0 replay
reproduction + parameter identity.

## 14. Commits

- Local worktree `~/.perso/diveanalyzer-identity-v2` (branch
  `hurdle-identity-v2`, based on server `d4c0c8a`), source + tests +
  lightweight science artifacts + this report; host caches (full-clip
  candidates, R5A/R5B trajectories, HQ renditions, OSNet weights)
  remain OUTSIDE Git under `runs/`/`models/` with sha256 provenance
  recorded in the committed artifacts.
- Server integration: cherry-pick onto `uiux-overhaul-pro-app`, then
  mirror push (Git authority + mac-mirror), final HEAD recorded in
  PROJECT_STATE.

## 15. Answers to the packet's success questions

1. **Was R4 primarily crippled by top-12 truncation?** Yes — 50.2% of
   primary evaluable frames (85.9% on 2353) had the target outside R4's
   graph; appearance quality was untestable there by construction.
2. **Can candidate-complete sparse association repair identity without new
   appearance learning?** Not yet — R5-A repairs 2353 only and regresses
   2169; the mechanism is sound but the dive-shape scorer is gameable.
3. **Is a frozen person-ReID representation actually discriminative on
   these tiny divers?** Yes on 5/6 dives (OSNet AUC 0.82–0.98,
   NN-retrieval ≈ 1.0); 2555 (screen recording) fails.
4. **Does HQ improve appearance identity?** Not materially
   (`MIXED_HQ_APPEARANCE_GAIN`) — per-dive mixed, aggregate ~nil.
5. **Can multiple HURDLE trajectories be repaired?** Not in this packet.
6. **What does frozen V3-D0 do with correct target trajectories?** Bound
   by the 2169-style evidence only: with the (rare) correct trajectory
   V3-D0 performs well (0.41/0.29 s); repaired replays for 1040/2341/2353/
   2541 remain outstanding.
7. **Does FM2 remain an Event Logic problem afterward?** Unresolved at a
   deeper level than before: identity remains the binding constraint;
   classification `FM2_STILL_IDENTITY_LIMITED`.
8. **Is the 524 HQ mapping reproducible?** No —
   `524_MAPPING_AUTHORITY_CONFLICT_CONFIRMED` (read-only).
9. **Does D5 still remain closed?** Yes.

## 16. Gate

`SUPERVISOR_REVIEW_AFTER_HURDLE_IDENTITY_SELECTION_V2`
