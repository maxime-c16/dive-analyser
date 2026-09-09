# PROJECT_STATE.md — Dive Analyser / DiveSensei

> Durable project handoff. Last verified: **2026-09-09** (Event Logic V3-C0 frozen).
> Latest science: `docs/science/EVENT_LOGIC_V3_REAL_DATA_REPAIR_REPORT.md`
> Previous science: `docs/science/PROCEDURAL_TRAJECTORY_READINESS_AND_EVENT_LOGIC_V3_REPORT.md`
> Previous: `docs/science/ICLOUD_HIGHRES_ANALYSIS_SOURCE_RECOVERY_V1_REPORT.md`
> Supervisor gate: **`EVENT_LOGIC_V3_C0_FREEZE`**

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

`EVENT_LOGIC_V3_C0_FREEZE`

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
