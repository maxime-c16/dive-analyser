# PROJECT_STATE.md — Dive Analyser / DiveSensei

> Durable project handoff. Last verified: **2026-09-09** (media-backbone P0/P1
> appended; iCloud high-resolution recovery frozen with per-asset temporal authority).
> Latest science: `docs/science/ICLOUD_HIGHRES_ANALYSIS_SOURCE_RECOVERY_V1_REPORT.md`
> Previous science: `docs/science/EVENT_LOGIC_V3_REAL_DATA_REPAIR_REPORT.md`
> Previous: `docs/science/PROCEDURAL_TRAJECTORY_READINESS_AND_EVENT_LOGIC_V3_REPORT.md`
> Supervisor gate: **`SUPERVISOR_REVIEW_AFTER_ICLOUD_HIGHRES_RECOVERY_V1_TCC_REPAIR`**

## Project purpose

Personal diving-analysis platform for a single athlete (Maxime) and training partners.
Divers manually pre-trim clips in macOS Photos and caption them with a compact grammar
(dive code, performance, height, modifiers). The system ingests those clips + captions,
stores structured metadata, computes statistics/insights, and serves a web UI.
Long-term goal: a second, deeper analysis layer (phase timing, takeoff/entry
characteristics, athlete-vs-self comparison). **Partially underway — Perception V1 frozen.**

## Canonical repository

- **`mcauchy@192.168.1.57:~/dive-analyser`** (Debian 12, host `deb-serv`) — the ONLY
  canonical Git repository. Branch `uiux-overhaul-pro-app`. HEAD: `e3c6cc4` → updated this cycle.
  No remotes.
- Mac bare mirror: `~/.perso/diveanalyzer-perception.git` (cloned from server).
- Mac working copy: `~/.perso/diveanalyzer-perception`. Remote `origin` → server. Remote `mac-mirror` → bare mirror.
- Local Mac working copy `~/.perso/diveanalyzer` is **NOT a git repo** — only a partial
  reference slice; never treat it as canonical.
- SSH access (passwordless from Maxime's MacBook Air only): key `~/.ssh/qwokka`
  installed in both hosts' `authorized_keys`; aliases in `~/.ssh/config`:
  `ssh diveanalyzer-server` (= `mcauchy@192.168.1.57`),
  `ssh diveanalyzer-mac` (= `divesensei@192.168.1.19`).

## Current deployment topology

Two machines on a LAN:

| Machine | Host | Role |
|---|---|---|
| Machine A | Debian 12 server `deb-serv` @ `192.168.1.57` (user `mcauchy`) | App host: Postgres 16, FastAPI backend, React frontend (nginx), reverse proxy (6090/6443), adminer. Canonical repo at `~/dive-analyser`. |
| Machine B | Intel MacBook, macOS 15.1.1, `mac-server.home` @ `192.168.1.19` (user `divesensei`) | Ingestion + media edge: watches the Photos library, parses captions, syncs metadata, exports/transcodes/uploads posters & proxies, manages a source vault for originals. |

## Science layer status (2026-09-09)

### High-Resolution Analysis Source Recovery — FROZEN_WITH_PER_ASSET_TEMPORAL_AUTHORITY

The Photos/iCloud recovery blocker was repaired through normal macOS Photos Full Access
for the actual PhotoKit client. Full-byte edited high-resolution renditions were recovered
for all 14 authorized TRAIN + DEVELOPMENT_EVAL media IDs, with media stored outside Git at
`/Users/Shared/services/data/media-node/highres_analysis_source_v1/`.

Temporal authority is per asset, now fully deterministic: 11 assets are
`PTS_EQUIVALENT` and 3 are `RECOVERED_DETERMINISTIC_MAPPING` (311 trim
`t_hq = t_proxy − 12.125s`; 524 PTS-equivalent with hflip+1.25-crop spatial
transform; 676 verified top-band crop map). **Zero quarantines remain** — the
311/524 quarantines were lifted by the quarantine forensics (evidence:
`docs/science/HIGHRES_QUARANTINE_FORENSICS_V1.json`), and 676's spatial map
was verified (the earlier map was direction-inverted).

Resolution decision (frozen):
`PRODUCTION_ANALYSIS_REPRESENTATION_REMAINS_PROXY_360P`
(`docs/science/HQ_REPRESENTATION_DECISION_V1.json`). HQ = archival master +
label forensics + future-retrain source, never fed to the frozen D5 detector;
720p canaries are derived tooling artifacts. Detector status remains
`NO_RETRAIN_AUTHORIZED`.

Primary artifacts:
- `docs/science/PHOTOS_TCC_CLIENT_V1.json`
- `docs/science/HIGHRES_ANALYSIS_SOURCE_MANIFEST_V1.json`
- `docs/science/ANALYSIS_SOURCE_HQ_V1_FREEZE.json`
- `docs/science/HIGHRES_QUALITY_AUDIT_D5_CANARY_V1.json`
- `docs/science/ICLOUD_HIGHRES_ANALYSIS_SOURCE_RECOVERY_V1_REPORT.md`
- `docs/science/HIGHRES_QUARANTINE_FORENSICS_V1.json`
- `docs/science/HQ_REPRESENTATION_DECISION_V1.json`
- `docs/science/HQ_REPRESENTATION_720P_AND_QUARANTINE_FORENSICS_V1_REPORT.md`
- `docs/science/HQ_PROXY_TEMPORAL_SPATIAL_INTEROP_V1.md`

### Frozen references
- Canary dive: 2819 (5122D G/G, springboard 1m, hurdle)
- Source: `IMG_1937.mov` SHA=`d122262be8e7a8721ab2f6a71721bb3544403da78324138d026360ef9820eaae`
- GT PTS: takeoff=3.120s, apex=3.570s, water_contact=4.220s
- Event Logic V2.1 frozen: `EVENT_LOGIC_V2_1_FREEZE.json`, 29/29 unit tests pass

### Perception V1 — FROZEN

**Architecture: `D5_FRAMEWISE_SUFFICIENT`**

| Component | SHA (first 16) | Status |
|---|---|---|
| D5-A detector (YOLOv8n) | `82b420c4583f8271...` | FROZEN |
| R1 reranker (ResNet50+LogReg) | N/A | NOT USED |
| Temporal continuity | N/A | NOT IMPLEMENTED |

**DEVELOPMENT metrics:**
- floor_recall: 97.1% (33/34 canonical frames)
- op_recall: 88.2%
- top-1 recall (D5-alone): 33.3%
- top-1 recall (D5+R1): 27.8%
- Δ top-1 (R1 contribution): -5.5%
- Architecture selection: R1 does not add material value (threshold: 5pp)

### Paris Canary (external evaluation — firewall intact)

**Flight trajectory gate: `TRAJECTORY_INPUT_PASS`** ✓

| Criterion | Result | IoU |
|---|---|---|
| C1: takeoff identity | ✓ PASS | 0.379 |
| C2: apex identity | ✓ PASS | 0.417 |
| C3: water_contact identity | ✓ PASS | 0.324 |
| C4: ≥80% flight coverage | ✓ PASS | 100.0% |
| C5: max gap | ✓ PASS | 0.0s |
| C6: wrong-target run | ✓ PASS | 0.0s |

**Procedural trajectory gate: `PARIS_PROCEDURAL_INPUT_PASS`** ✓  
C1_prep=100%, C2_pretakeoff=100%, Flight=100%. Full video (322/344 frames @ 1080p).

**Event Logic on Paris (V2.1 and V2.2) — FULL TRAJECTORY:**

| Version | Complete | to_err | ap_err | wc_err | Note |
|---|---|---|---|---|---|
| V2.1 | ✓ | 1.685s | 1.952s | 0.183s | HURDLE prep_end fails (FM2) |
| V2.2 | ✓ | 1.335s | 1.552s | 0.183s | HURDLE prep_end fails (FM2) |

Previous "BOTH_FAIL" EL result was incorrect — it ran on 3-point anchor trajectory, not full video.
Current failure: HURDLE prep_end detection (FM2 — first motion at 0.683s, actual takeoff 3.12s).

Artifact: `PARIS_PROC_EL_EVALUATION_V1.json`

### DEVELOPMENT Multi-Dive Evaluation

| Metric | Value |
|---|---|
| Dives evaluated | 10 |
| PERCEPTION_VALID (D5_FRAMEWISE) | 6 (60.0%) |
| PERCEPTION_INVALID | 4 |
| Valid dives | [133, 311, 676, 1040, 2169, 2387] |
| Invalid dives | [524, 2341, 2555, 2625] |

**PROCEDURAL gate (new):** All 6 VALID dives pass `PROCEDURAL_TRAJECTORY_INPUT`.  
Floor coverage = 100% for all. Op_conf coverage: 133=58.4%, 311=62.0%, 676=81.5%, 1040/2169=100%, 2387=89.2%.

**DEVELOPMENT EL evaluation (full continuous trajectories):**

| Dive | V2.1 complete | to_err | wc_err | Root cause |
|---|---|---|---|---|
| 133  | ✓ | 0.165s | 0.148s | OK |
| 311  | ✓ | 0.059s | **3.530s** | FM1: UNBOUNDED APEX FALLBACK |
| 676  | ✗ | — | — | FM3: 360p noise + interpolate_gaps crash |
| 1040 | ✓ | 1.995s | 2.511s | FM2: PREMATURE HURDLE PREP_END |
| 2169 | ✓ | 1.280s | 0.364s | FM2: late takeoff detection |
| 2387 | ✓ | 2.148s | 0.039s | FM2: PREMATURE PREP_END (brief off-board rest) |

**EL gate: `EVENT_LOGIC_FAILURE_CONFIRMED`** — 5/6 complete, documented failures.

### Event Logic V3 — DEVELOPMENT COMPLETE, NOT PROMOTED

**V3_DEVELOPMENT_COMPLETE_INSUFFICIENT**: V3-B best (3/6) < V2.1 (5/6). Not promoted.

**V3-A**: REJECTED (2/6) — STANDING "last qualifying plateau" picks post-wc pool-deck detections.  
**V3-B**: MARGINAL (3/6) — water_line_cy_norm boundary unreliable (diver disappears at wc).

**Confirmed future improvements:**
- A1 (bounded apex fallback): correct, validated by unit tests. Patch to V2.1 in next cycle.
- A2 (bounded wc search): correct. Patch to V2.1 in next cycle.

**Key finding (HURDLE prep_end):** HURDLE preparation structure is non-deterministic across divers (user-confirmed). No single rule generalizes. Requires future scene-level temporal segmentation.

V3 freeze: `EVENT_LOGIC_V3_FREEZE.json`

### Dive 311 diagnosis (CORRECTED)

| Field | Value |
|---|---|
| Classification | **EVENT_LOGIC_CAUSED_FAILURE** (corrected from PERCEPTION_GAP_CAUSED_FAILURE) |
| Procedural coverage | PASS (C2=89.7%, flight=100%) |
| V2.1 takeoff | 13.814s (error: **0.059s** — excellent) |
| V2.1 wc | 18.352s (error: **3.530s** — catastrophic) |
| Root cause | FM1: unbounded apex fallback picks pool-deck cy~0.11 as apex at 18.35s |
| Fix | A1 bounded apex (V3 confirmed): [takeoff, takeoff+1.5s] → wc_err ~0.15s |

### PTS Authority

**`PTS_AUTHORITATIVE_SEEK`** — always `cap.set(CAP_PROP_POS_FRAMES, fi)` before `cap.read()` for anchor frames.

Historical Paris failure documented: fi=235 sequential drift → fi=238 seek canonical (3-frame, 53ms at 56.5fps). Test suite: `test_pts_authority_v1.py` — 15/15 pass.

### Detector closure
`D5_A_FROZEN` — no new detector training authorized. Floor coverage 100% across all dives. No `RAW_DETECTOR_MISS` failures. No D6 warranted.

### Resolution diagnostic
`BLOCKED_TCC_PHOTOS_AUTHORIZATION` — iCloud catalog metadata is visible on the
Photos host, but full-byte edited high-resolution export is not proven. The
SSH-launched `osxphotos --download-missing --use-photokit` canary requested
Photos "Allow Access to All Photos" and failed authorization. Batch recovery was
not started; `ANALYSIS_SOURCE_HQ_V1` remains not frozen.

High-res recovery artifacts:
- `docs/science/ICLOUD_HIGHRES_ANALYSIS_SOURCE_RECOVERY_V1_REPORT.md`
- `docs/science/ANALYSIS_SOURCE_HQ_V1_FREEZE.json` (`NOT_FROZEN_CANARY_GATE_CLOSED`)
- `docs/science/HIGHRES_RECOVERY_BATCH_V1.json`

### Bug fix
`interpolate_gaps_time` in `proposer_event_logic_v2_1.py`: NoneType crash when left gap boundary is None. Fixed (None-guard). PARAMS_E1 unchanged.

## Current supervisor gate

`SUPERVISOR_REVIEW_AFTER_HURDLE_IDENTITY_REPAIR_V1`

## HURDLE target identity repair — COMPLETE (2026-09-09, identity-repair thread)

Packet `HURDLE_TARGET_IDENTITY_REPAIR` executed on top of `a551319` (Event Logic
HEAD) with the HQ-representation thread's `4b192dc` fetched read-only as the
canonical base. Read-only wrt the HQ thread's artifacts; no media/manifest
authority modified.

**Phase A — per-frame GT identity classification (new evidence):**
- Built `HURDLE_TARGET_ANCHORS_V1.json` (HUMAN_GT boxes at 20 annotated frames
  across 2169/2341/2353/2555 + operator-verified visual anchors; identity traps
  documented) and `HURDLE_TARGET_CHAINS_V1.json` (per-frame GT chains, GT-direct
  at annotated frames, AMBIGUOUS where identity is not establishable, WATER
  post-wc). Chains validated against every human box: IoU 0.30–1.00.
- `HURDLE_TARGET_IDENTITY_CLASSIFICATION_V1.json`: on ALL 5 classified HURDLE
  dives the target is present in the raw floor proposals **100% of evaluable
  frames**, while the D5 op-point top-1 is the target only **0.5–51.8%** (1040
  10.6%, 2169 96.3%, 2341 2.2%, 2353 0.5%, 2541 14.9%, 2555 51.8%); longest
  continuous wrong runs 33–363 frames. The failure is SELECTION, not detection.

**Phase B — R4 appearance-aware global path: FAIL.**
- `R4_APPEARANCE_AWARE_GLOBAL_PATH` implemented per packet spec (frozen ResNet50
  ImageNet features, NULL state, E3 sequence prior with bounded scan, E4 static
  prep protection, 192-config hyperparameter grid + dive-event track picking).
- Verdict: appearance features are non-discriminative at 360p (cross-cos ≈
  self-cos, 0.60–1.00) and D5 conf is anti-informative (the distractors are
  static background boxes with TOP conf — 2341: (0.64,0.11) conf 0.403 all
  video). Best R4 mean top-1 = 0.213 < D5 baseline 0.249. No configuration
  repairs any dive; 2169 is preserved (0.91–0.96).
- `HURDLE_R4_APPEARANCE_REPAIR_RESULT_V1.json` (verdict + diagnostics).

**FM2 reclassification + V3-D0 replay:**
- `HURDLE_FM2_RECLASSIFICATION_V1.json`: FM2 root cause corrected from "target
  instability/oscillation" to SYSTEMATIC per-frame selection failure (static
  distractors outrank the diver); detector-ceiling hypotheses refuted
  (avail_floor=1.000 on all classified dives incl. 1040).
- V3-D0 replayed on the frozen cache: 1040/2169 magnitudes reproduce the freeze
  exactly (sign convention differs); 5 HURDLE dives had no prior V3-D0 numbers.
  The frozen 1040 trajectory (cy=0.221) is literally the structure distractor —
  FM2 operates on the wrong object on 4/6 classified dives.

**524:** no usable GT anchors; the HQ hflip mapping self-validation FAILED
(exhaustive scale/flip/time search caps at NCC 0.32–0.46 vs spec ~0.74) — HQ 524
boxes NOT used; representation authority untouched.

### Tests / commits
- Worktree: `~/.perso/diveanalyzer-hurdle-identity-repair` (detached at `a551319`
  → `682b634` Phase A → `438b7e0` Phase B). Server integration lands on
  `4b192dc` via cherry-pick, then the report commit.
- Report: `docs/science/HURDLE_TARGET_IDENTITY_REPAIR_AND_FM2_CAUSAL_V1_REPORT.md`

## Event Logic V3-C — COMPLETE (2026-09-09)

**Decision: `V3_REAL_DATA_PROMOTION_JUSTIFIED`** — V3-C0 frozen.

### V3-C0 (A1+A2): FROZEN

Patches V2.1 with two bounded-search fixes only. All PARAMS_E1 values unchanged.

| Param | Value | Derivation |
|---|---|---|
| `apex_max_window_s` | 1.5s | 4.3× max dev takeoff→apex (0.35s, dive 2387) |
| `wc_max_window_s` | 2.5s | 2.6× max dev apex→wc (0.97s, dive 676) |

**DEVELOPMENT results:**

| Dive | V2.1 wc_err | V3-C0 wc_err | Note |
|---|---|---|---|
| 133  | 0.148s | 0.148s | unchanged |
| 311  | 3.530s | **0.027s** ✓ | FM1 FIXED |
| 676  | 0.752s | 1.016s | FM3 unresolved, minor regression |
| 1040 | 2.511s | 2.511s | FM2 unresolved |
| 2169 | 0.364s | 0.364s | FM2 unresolved |
| 2387 | 0.039s | 0.161s | minor regression |

| Metric | V2.1 | V3-C0 |
|---|---|---|
| Complete | 6/6 | 6/6 |
| med_to_err | 1.637s | 1.637s |
| med_wc_err | 0.558s | **0.262s** (+53%) |

**Paris V3-C0:** to_err=1.685s (FM2 unresolved), wc_err=0.133s (vs 0.183s V2.1).

### V3-C1 (A1+A2+HURDLE recontact): NOT PROMOTED

Scans all sustained-neg-vel starts; rejects any with positive vel in 0.25s window
(= board recontact after hurdle jump). Returns first candidate after last recontact.

Paris: to_err=0.183s, ap_err=0.033s (excellent). Development HURDLE catastrophic
regression (1040 to_err=6.214s, 2169 to_err=2.848s) due to 360p noise corrupting
the takeoff signal. DEVELOPMENT must justify before Paris can confirm.

### Open failures

- FM2 (HURDLE prep_end, dives 1040/2169): requires scene-level segmentation or higher-res proxies.
- FM3 (360p noise, dive 676): perception limitation.
- Paris HURDLE takeoff FM2: out of scope for V3-C0.

### Tests and artifacts

- `experiments/landmark_pilot/proposer_event_logic_v3_c0.py` — V3-C0 source
- `experiments/landmark_pilot/proposer_event_logic_v3_c1.py` — V3-C1 source (not promoted)
- `experiments/landmark_pilot/test_event_logic_v3_c.py` — 14 tests, 14/14 pass
- `docs/science/PARIS_MEDIA_IDENTITY_V1.json` — 322 vs 344 reconciliation
- `docs/science/EL_REAL_BASELINE_V1.json` — V2.1/V2.2 on full trajectories
- `docs/science/EL_V3C_DEVELOPMENT_EVAL_V1.json` — 4-variant DEVELOPMENT comparison
- `docs/science/EL_V3C_PARIS_EVAL_V1.json` — Paris external evaluation
- `docs/science/EVENT_LOGIC_V3_REAL_DATA_REPAIR_REPORT.md` — full report

**Regression:** 65/65 pass (V2.1 36 + PTS 15 + V3-C 14).

## Event Logic V3-D — FROZEN (2026-09-09)

**Decision: V3_D_DEVELOPMENT_IMPROVES_PARIS_FAILS / SCENE_CONTEXT_NEXT_JUSTIFIED**

### V3-D0: FROZEN (EVENT_LOGIC_V3_D0_FREEZE)

Board-rise validity gate for HURDLE apex detection + STANDING-like fallback.
Inherits V3-C0 (A1+A2) completely. Two new parameter keys only.

**Change summary:**
- D0: At each neg->non-neg velocity crossing after guard, check cy_apex < y_prep - min_rise.
  Physical invariant: at a real hurdle apex the diver must be above the board.
  If violated: crossing is a detector artifact -> continue scanning.
- Fallback: if no valid apex found, search for sustained negative velocity from guard_end.

**Parameters:** min_hurdle_rise_cy=0.01, fallback_sustained_s=0.15. All V3-C0/PARAMS_E1 values unchanged.

**DEVELOPMENT results:**

| Dive | Context | V3-C0 to_err | V3-D0 to_err | Delta |
|---|---|---|---|---|
| 133  | STANDING | 0.165s | 0.165s | UNCHANGED |
| 311  | STANDING | 0.059s | 0.059s | UNCHANGED (FM1 closed) |
| 676  | STANDING | 3.086s | 3.086s | UNCHANGED |
| 1040 | HURDLE   | 1.995s | 1.995s | UNCHANGED |
| 2169 | HURDLE   | 1.280s | **0.412s** | **-67.8%** (STANDING_FALLBACK) |
| 2387 | STANDING | 2.148s | 2.148s | UNCHANGED |

med_to: 1.637s -> 1.204s (-26.5%). med_wc: 0.262s -> 0.224s (improved).

**Freeze gate: PASS.** Hurdle improves, no STANDING catastrophe, FM1 closed, WC not regressed.

**Paris external test (read-only, post-freeze):**
- V3-D0 Paris to_err=1.685s -- identical to V3-C0
- Paris false hurdle at 1.117s: cy_apex=0.380 < y_prep=0.464, rise=+0.083 -> passes board-rise check
- Different failure mode from 2169 (approach-walk creates valid-looking brief rise above board)

**Scene context decision: SCENE_CONTEXT_NEXT_JUSTIFIED**
Paris approach-walk kinematics pass board-rise gate. Kinematic signals alone cannot distinguish
prep-walk rises from real hurdle at 360p.

**Observability findings (from V3-D analysis):**
- Both HURDLE dives: smooth_neg_ratio=0.0 at GT takeoff -> Gaussian smoothing destroys signal
- 2169 root cause: D5 switches from cy=0.262 to cy=0.711 at t=6.406s; artifact overwhelms rising motion
- 1040 root cause: D5 oscillates between cy=0.22 and cy=0.60; no filter/primitive recovers signal
- HQ (iCloud thread): 2169 HQ to_err=0.439s (improved); 1040 HQ sm_neg=0.714 (signal visible at HQ)

**V3-D1 evaluated:** identical results to V3-D0 (fallback_sustained_s=0.25s). Not promoted.

### Tests and artifacts

- experiments/landmark_pilot/proposer_event_logic_v3_d0.py -- V3-D0 source (frozen)
- experiments/landmark_pilot/test_event_logic_v3_d0.py -- 13 tests, 13/13 PASS
- docs/science/EVENT_LOGIC_V3_D0_FREEZE.json -- freeze artifact
- docs/science/EL_V3D_REVISED_DEVELOPMENT_EVAL_V1.json -- per-dive results
- docs/science/HURDLE_OBSERVABILITY_V3D_ANALYSIS_V1.json -- observability analysis
- docs/science/HURDLE_FINAL_TAKEOFF_OBSERVABILITY_AND_V3_D_REPORT.md -- full report

**Regression:** 27/27 pass (V3-C0 14 + V3-D0 13).

## V3-D0 status correction (2026-09-09, V3-E thread)

V3-D0 is `V3_D0_EXPERIMENTAL_FROZEN_DEVELOPMENT_BASELINE` — a frozen **development**
baseline, NOT production-promoted. Paris external failure (to_err 1.685s) stands.
FM1 CLOSED; FM2 OPEN/PARTIALLY_ADDRESSED; FM3 (360p target instability, 1040) open.
The V3-D0 test suite's Paris numeric assertion (`Paris to_err <= 2.0s`) was retired
as a selection criterion and replaced by Paris scientific-firewall integrity tests
(Paris absent from DEVELOPMENT inputs/params; freeze precedes Paris evaluation;
Paris artifact report-only). Suite now 16/16.

## HURDLE approach-end context and V3-E — COMPLETE (2026-09-09)

**Decision: `MORE_HURDLE_GT_REQUIRED` / `V3_D0_REMAINS_EXPERIMENTAL_BASELINE`.**
Full report: `docs/science/HURDLE_APPROACH_END_CONTEXT_AND_V3_E_REPORT.md`.

### Parallel-thread integration
Canonical HEAD `30267b1` verified on server + Mac; both reported thread HEADs
(`30267b1` Event Logic, `9881813` HQ/media) are ancestors (linear history, no
merge needed). HQ thread stable artifacts preserved; quarantined HQ (311, 524)
untouched. Audit: `docs/science/PARALLEL_THREAD_INTEGRATION_AUDIT.json`.

### HURDLE DEVELOPMENT corpus: 2 -> 7 dives (all with human V2 GT)
1040, 2169, 524 (HQ quarantined — 360p only), 2341, 2353 (drill), 2541, 2555.
2625 excluded (no takeoff GT); 2661/2680 excluded (armstand); INTERNAL_EVAL
(2281) untouched. No human-labeling gate needed; no step-count inference.

### Key findings
- **Robust board reference:** 1040's `y_prep` (0.531) is a corrupted mixture of
  two D5 levels; robust B1r cluster-median recovers the true level (0.2208) and
  fails loud (2541 non-diver plateau). Chosen: B1r.
- **2D audit:** no dive is APPROACH_END_OBSERVABLE_FROM_2D; the approach-progress
  coordinate s(t) is not reliably extractable at 360p. Vertical-only failure
  generalizes to 2D.
- **HQ (read-only, 1040/2169 only):** controlled comparison gives 1040 =
  HQ_IMPROVES_SNR_ONLY, 2169 = HQ_NO_MATERIAL_GAIN. Target instability persists
  at HQ; HQ does not repair detection.
- **V3-E0 (V3-D0 + B1r):** 2169 unchanged; **1040 regressed** (1.995s -> 5.746s):
  with a correct board level, the unbounded gate scan accepts a post-water-contact
  flicker crossing at 9.343s. STANDING byte-identical (4/4). FM1 intact.
- **V3-E1:** NOT_JUSTIFIED_BY_DEVELOPMENT_EVIDENCE (no validated end-of-board cue).
- **Freeze gate: FAILED** -> no V3-E freeze; `MORE_HURDLE_GT_REQUIRED`.
- **Paris (report-only, post-decision):** full-clip authority unchanged
  (to_err 1.685s); frozen 182-frame window trajectory: V3-D0 = V3-E0 = to_err
  1.3919s (window excludes the 1.117s pre-window feature). No tuning afterward.
- **Scene-context decision: `MORE_HURDLE_GT_REQUIRED`** — scene segmentation is
  NOT yet justified (target trajectory itself is incorrect; HQ no material gain).

### Tests
V3-E 13/13, V3-D0 16/16 (incl. Paris firewall 1-4), V3-C 14/14, highres 16/16,
PTS 15/15. Zero failures.

### Artifacts
- `experiments/landmark_pilot/proposer_event_logic_v3_e0.py` (candidate, not frozen)
- `experiments/landmark_pilot/test_event_logic_v3_e.py`
- `docs/science/DEV_HURDLE_TRAJ_CACHE_V2.json`, `STANDING_TRAJ_CACHE_V2.json`
- `docs/science/V3D0_HURDLE_CORPUS_BASELINE_V1.json`, `BOARD_REFERENCE_AUDIT_V1.json`
- `docs/science/TWOD_APPROACH_AUDIT_V1.json`, `HQ_HURDLE_DIAGNOSTIC_V1.json`
- `docs/science/V3E_DEVELOPMENT_COMPARISON_V1.json`, `V3E_FREEZE_GATE_FAILED_V1.json`
- `docs/science/PARIS_EXTERNAL_V3E_EVAL_V1.json`
- `docs/science/HURDLE_APPROACH_END_CONTEXT_AND_V3_E_REPORT.md`


## HQ representation audit + quarantine forensics — COMPLETE (2026-09-09)

**Decision: `PRODUCTION_ANALYSIS_REPRESENTATION_REMAINS_PROXY_360P`; manifest
`RECOVERED_ALL_DETERMINISTIC` (zero quarantines).**
Full report: `docs/science/HQ_REPRESENTATION_720P_AND_QUARANTINE_FORENSICS_V1_REPORT.md`.

### Quarantine forensics (Phases B/C/D)
- **311 lifted:** HQ = deterministic trim, `t_hq = t_proxy − 12.125s` (10/10
  stride-1 samples NCC 0.977–0.995, scale 1.0, no spatial transform). Both
  annotated events (takeoff 13.747s, water_contact 14.815s proxy) inside the
  HQ-covered window [12.125, 19.2433].
- **524 lifted:** PTS-equivalent (offset 0) with spatial transform
  hflip + zoom 1.25 (16/16 frames, scores 0.701–0.778; identity scan failed ->
  hflip required). HQ-arm box math for 524 unexercised (no audit run).
- **676 map verified:** HQ display 1080x1136 == proxy top band (rows
  [0, ~213/360]) upscaled x5.347, full horizontal FOV, no hflip; blur-equalized
  NCC 0.998 at loc (0,1); GT boxes for takeoff/apex/water_contact mapped into
  HQ land on the diver (`runs/hq_rep_v1/sheets/676_gt_overlay_HQ.png`). Prior
  map `{y_off 0.002, y_span 0.5917}` was direction-inverted and is superseded.
- Phase A unchanged: `ORIGINAL_MASTER_NOT_INDEPENDENTLY_PROVEN` (library fully
  iCloud-optimized; "original" exports byte-identical to edited renditions).

### Representation audit (frozen D5, 360p vs 720p vs HQ)
- 1040: 720p top-1 target switching (anchored cy SNR 0.22 vs 2.81 at 360p).
- 2169: anchored missingness 0.24–0.27 in takeoff window at 720p/HQ (0.0 at
  360p); anchored peak departure velocity ~2x at 720p.
- 676: top-1 switches away from the diver at takeoff/apex in 720p/HQ arms
  (diver present in candidates at IoU 0.63–0.72 but outranked) — genuine
  resolution-dependent ranking effect, not a mapping failure.
- 133 (control): stable across arms. Higher resolution gives 3–4x diver pixel
  height and better 2169 water-contact IoU, but only matters after a retrain.
- Tooling fixes: 676 map direction corrected and `event_identity` proxy-arm
  identity bug fixed in `hq_representation_audit_v1.py`; authoritative numbers
  from `hq_audit_recompute_v2.py` (V2 recomputed JSON + trajectory sheets).

### Decision + policy (frozen)
- Detector inference: proxy_360p only (frozen D5). HQ = archival master,
  label transfer allowed for all 14 dives through explicit deterministic
  transforms. 720p canaries = derived tooling artifacts (not durable; 1040
  720p drops 7/339 frames, VFR).
- Retrain at ≥480p: NOT authorized; requires a new detector freeze + fresh audit.
- `ANALYSIS_SOURCE_HQ_V1_FREEZE.json` amended (`resolution_decision`,
  `batch_summary`: 11 aligned + 3 deterministic mapping + 0 quarantined;
  amendment log).

### Tests
`experiments/landmark_pilot/test_hq_quarantine_forensics_v1.py` — 10/10
(manifest invariants, recovery_history preservation, 676 map direction math,
311 window coverage, forensics↔manifest↔decision↔freeze consistency,
audit-script map parity). Existing suites untouched.

### Artifacts
- `docs/science/HIGHRES_QUARANTINE_FORENSICS_V1.json`
- `docs/science/HQ_REPRESENTATION_DECISION_V1.json`
- `docs/science/HQ_PROXY_TEMPORAL_SPATIAL_INTEROP_V1.md`
- `docs/science/HQ_REPRESENTATION_720P_AND_QUARANTINE_FORENSICS_V1_REPORT.md`
- `runs/hq_rep_v1/`: `HQ_REPRESENTATION_AUDIT_V2_RECOMPUTED.json`,
  `scale_match_676_v2_blur.json`, `offset_verify_311_stride1.json`,
  `720p_canaries/`, `sheets/` (untracked; videos not committed)

## Media backbone P0/P1 — COMPLETE (2026-09-09, media-backbone thread)

**Status: `INTAKE_GATE_1_READY`** — implementation branch `media-backbone-p0-p1-v1`
(worktree `~/.perso/diveanalyzer-media-backbone`, base HEAD `4b192dc0`).
Task packet `MEDIA_BACKBONE_P0_P1_V1`. No cloud resources created. Production
upload/serving untouched; science authorities untouched.

### What exists now (all additive, feature-flagged OFF)

- **Agent-side backbone** `mac-agent/src/ingest/`:
  `content_addr` (sha256 + `blobs/sha256/<2>/<sha>` keys),
  `objectstore/` (`FakeObjectStore` test backend with fault injection,
  `BackblazeB2Store` S3-compatible adapter — lazy boto3, private-bucket,
  DEV/PROD bucket cross-wiring rejected, no bucket creation, guarded delete),
  `state_store` (JSON atomic-persist resumable state),
  `coordinator` (`ObjectStoreIngestCoordinator`, states
  DISCOVERED→…→CACHE_CLEANED + QUARANTINED, verified-ingest roundtrip rule:
  full GET SHA == local SHA, min_free_disk_bytes guard, stale-temp
  reconciliation, idempotent re-drive),
  `caption` (`CurrentStableCaptionProvider` authority — R1: returns the EXACT
  provider string, no app-level strip; `PhotosDbCaptionProviderShadow`
  SHADOW provider — R2: truthful name, direct Photos-DB SQLite is NOT
  PhotoKit, `PHOTOKIT_CAPTION_SHADOW_STATUS =
  NOT_IMPLEMENTED_CURRENT_RUNTIME`; redacted provider-identity parity
  harness).
  Config: `object_store:` block in mac-agent config, `enabled: false` default;
  disabled mode never constructs object-store components (tested).
- **Server-side additive schema** `backend/app/models/media_backbone.py`
  (`media_blobs`, `media_revisions`, `caption_revisions`,
  `ingest_object_state`) + idempotent commit service
  `backend/app/services/media_backbone.py::commit_verified_ingest`
  (refuses unverified commit; caption SHA must equal sha256 of the exact
  persisted caption_raw UTF-8 bytes) + additive migration
  `backend/migrations/add_media_backbone_tables.sql` (IF NOT EXISTS only,
  reversible by dropping the 4 new tables; static guard test).
- **Caption doctrine implemented (post-R1)**: `caption_raw` = EXACT provider
  output BEFORE any application-level whitespace normalization; the legacy
  `.strip()` lives ONLY in the legacy payload path
  (`legacy_caption_transform`) and is byte-unchanged; append-only revisions;
  shadow comparison fields; parser never mutates raw.
- **State-machine crash tests A–G all green** (before materialization /
  before hash / before upload / mid-upload / before verify / before commit /
  before cleanup) + no-duplicate replay + corrupt-state-file recovery.

### Test results (2026-09-09, Python 3.12, post-repair R1)

- `mac-agent`: `test_ingest_backbone.py` **68/68 pass**; full mac-agent suite
  with the repo-required deps installed (incl. pytest-asyncio): **127/127 pass
  on branch, 59/59 on base HEAD** — zero new failures.
- `backend`: `test_media_backbone.py` **23/23 pass**; full backend suite in an
  identical venv: base `9 failed / 279 passed / 11 skipped / 273 errors` vs
  branch `9 failed / 302 passed / 11 skipped / 273 errors` with **byte-identical
  failure/error signatures (282 lines)** — all pre-existing (sqlite vs
  postgres-UUID analysis models + 8 e2e async-plugin + 1 DD-metric test).
  `NEW_FAILURES_INTRODUCED_BY_BRANCH = 0` (branch adds +23 passing tests).

### B2 research (see `docs/architecture/MEDIA_BACKBONE_SECURITY_V1.md`)

Region choice is ACCOUNT-LEVEL at creation, immutable, one region per account;
EU Central = Amsterdam (`s3.eu-central-003.backblazeb2.com`); EU residency does
NOT remove US (CLOUD Act) jurisdiction over the provider — legal/policy
decision explicitly left to the human. PRIMARY-SOURCE pricing (Pay-As-You-Go):
$6.95/TB-month, first 10 GB free, free egress up to 3× average monthly
storage, $0.01/GB above; S3 API requires an Application Key (master key
unusable). Resource plan presents Option A (one account, two buckets) vs
Option B (separate accounts) neutrally; the human decides. P1 private-bucket
claims are CONFIGURATION REQUIREMENTS only — anonymous-access denial must be
verified against the real DEV bucket at P2.

### STATE AUTHORITY (post-R3)

Single coherent model: the mac-agent per-clip JSON execution journal is the
ONLY pre-commit/restart orchestration authority; the server DB
(blob/revision/caption-revision rows) is the ONLY durable committed-result
authority; `ingest_object_state` is a server-side durable commit ledger
written once per verified commit, never read by agent orchestration.
Reconciliation matrix (4 cases, one deterministic outcome each) tested in
`TestStateAuthority` + `TestStateAuthorityArchitecture`.

### Next gate

`INTAKE_GATE_1`: human/provider decisions required — (1) B2 account/region
(EU Central Amsterdam recommended, legal sign-off human), (2) authorize DEV
bucket + bucket-scoped app key creation, (3) provision credentials. Then P2
packet: one real canary clip (album `DiveAnalyzer Ready`, caption
`107B | 7.5 | H:3 | drill:no-arms | note:à revoir`) through
`ObjectStoreIngestCoordinator` with `object_store.enabled: true` on DEV.

### Key documents

- `docs/architecture/MEDIA_BACKBONE_CURRENT_STATE_V1.md` (P0 audit)
- `docs/architecture/MEDIA_BACKBONE_TARGET_V1.md` (interfaces/seams)
- `docs/architecture/MEDIA_INGEST_STATE_MACHINE_V1.md` (states, crash contract)
- `docs/architecture/MEDIA_BACKBONE_SECURITY_V1.md` (security + B2 EU research)
- `docs/architecture/MEDIA_BACKBONE_MIGRATION_PLAN_V1.md` (P0–P8 phases; DB-driven historical migration, NOT a Photos-library crawl)

## HURDLE identity selection V2 — GATE FAILED, confound closed (2026-09-10, identity-v2 thread)

Packet `HURDLE_TARGET_IDENTITY_V2` executed on Apple M2 (worktree
`~/.perso/diveanalyzer-identity-v2`, branch `hurdle-identity-v2`, base
`d4c0c8a`). Report:
`docs/science/HURDLE_IDENTITY_SELECTION_V2_REPORT.md`.

**A1 — the R4 confound is quantified and confirmed.** The true target was
OUTSIDE R4's top-12 candidate graph on 50.2% of primary evaluable frames
(2353 85.9%, 1040 65.8%, 2541 64.9%); recall@48 ≥ 0.88, @96 ≥ 0.985, @200
= 1.000 on every classified dive (`HURDLE_R5_STATE_SPACE_AUDIT_V1.json`).
R4 was therefore NOT valid evidence that appearance-aware association is
intrinsically insufficient.

**Full-clip GT-free inference (Phase B).** The frozen D5 recipe re-ran over
FULL production clips for all six primary dives; selector paths consume
only `R5_FULLCLIP_CANDIDATES_V1.json` (interval [0, video_end]); GT times
appear only under `gt_eval_only` metadata. Regression-tested.

**R5-A (candidate-complete sparse tracklets) — repairs one dive.** 2353
0.365 vs D5 top-1 0.005 (longest wrong 363 → 23); 2169 regresses
catastrophically (movers with dive-scale excursions exist in that clip);
no stable multi-dive configuration. **R5-B (frozen OSNet Market-1501
association) — repairs none.** Selection gate **FAILED**; no
`HURDLE_TARGET_IDENTITY_V2_FREEZE`; no repaired trajectories; V3-D0
replayed UNCHANGED on the frozen cache and reproduces the recorded
magnitudes exactly (adds per-dive baselines for 2341/2353/2541/2555).

**Appearance is vindicated as a direction (Phase E).** Frozen OSNet
(Market-1501) is discriminative on the tiny 360p divers: separation
margin 0.203 / ROC-AUC 0.902 aggregate vs ResNet50-ImageNet 0.126 / 0.837
(AUC 0.82–0.98 on all five ordinary dives, NN-retrieval ≈ 1.0). The R4
"appearance is insufficient" verdict is REFUTED at the representation
level. Measured pose-transition structure: prep–prep cos 0.89–0.97,
prep–flight 0.67–0.79 vs distractor ~0.65 — appearance verifies static
identity but cannot bridge prep→flight alone.

**HQ appearance-only (Phase F): `MIXED_HQ_APPEARANCE_GAIN`** (aggregate
margin 0.199/AUC 0.932 vs proxy 0.231/0.923; per-dive mixed; 2341
improves). All six HQ renditions sha-verified against the manifest.

**FM2: `FM2_STILL_IDENTITY_LIMITED`.** Detector remains closed
(`D5_DETECTOR_REMAINS_CLOSED`; recall@200 = 1.000 re-confirmed). **524:
`524_MAPPING_AUTHORITY_CONFLICT_CONFIRMED`** (read-only re-audit: at the
HQ thread's own claimed parameters NCC 0.24–0.32, exhaustive search caps
0.64 at unstable parameters) — 524 stays excluded. **2555** stays
`SCREEN_RECORDING_STRESS_CASE` (all instruments degrade; not promoted).

Tests: `experiments/landmark_pilot/test_hurdle_identity_v2.py` — 21/21
pass (zero failures). Host caches/weights stay outside Git with sha256
provenance committed.

### Next gate

`SUPERVISOR_REVIEW_AFTER_HURDLE_IDENTITY_SELECTION_V2`
