# PROJECT_STATE.md — Dive Analyser / DiveSensei

> Durable project handoff. Last verified: **2026-09-09** (Perception V1 closure REPAIR).
> Latest science: `docs/science/PERCEPTION_V1_CLOSURE_REPAIR_AND_REAL_EVENT_LOGIC_REPORT.md`
> Previous: `docs/science/PERCEPTION_V1_CLOSURE_AND_REAL_EVENT_LOGIC_REPORT.md`
> Supervisor gate: **`SUPERVISOR_REVIEW_AFTER_PERCEPTION_V1_FINAL_CLOSURE`**

## Project purpose

Personal diving-analysis platform for a single athlete (Maxime) and training partners.
Divers manually pre-trim clips in macOS Photos and caption them with a compact grammar
(dive code, performance, height, modifiers). The system ingests those clips + captions,
stores structured metadata, computes statistics/insights, and serves a web UI.
Long-term goal: a second, deeper analysis layer (phase timing, takeoff/entry
characteristics, athlete-vs-self comparison). **Partially underway — Perception V1 frozen.**

## Canonical repository

- **`mcauchy@192.168.1.57:~/dive-analyser`** (Debian 12, host `deb-serv`) — the ONLY
  canonical Git repository. Branch `uiux-overhaul-pro-app`. HEAD: `f50a132`.
  No remotes.
- Mac bare mirror: `~/.perso/diveanalyzer-perception.git` (cloned from server). HEAD: `f50a132`.
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

**Trajectory gate: `TRAJECTORY_INPUT_PASS`** ✓ (repair cycle corrected two execution bugs)

| Criterion | Result | IoU |
|---|---|---|
| C1: takeoff identity | ✓ PASS | 0.379 |
| C2: apex identity | ✓ PASS | 0.417 |
| C3: water_contact identity | ✓ PASS | 0.324 |
| C4: ≥80% flight coverage | ✓ PASS | 100.0% |
| C5: max gap | ✓ PASS | 0.0s |
| C6: wrong-target run | ✓ PASS | 0.0s |

**Repair notes:** Previous V1 C3 failure caused by (1) FLOOR_CONF=0.01 instead of frozen 0.001,
and (2) sequential-read frame drift (3-frame offset from canonical fi=238). Corrected with
seek-based anchor extraction at FLOOR_CONF=0.001.

Artifact: `PARIS_REAL_TARGET_TRAJECTORY_V1.json` (FROZEN)

**Event Logic on Paris (V2.1 and V2.2):** `BOTH_FAIL` — all events NOT_FOUND.
Root cause: EL calibration scope mismatch (not a perception failure).

### DEVELOPMENT Multi-Dive Evaluation (D5-only, repair cycle)

| Metric | Value |
|---|---|
| Dives evaluated | 10 |
| PERCEPTION_VALID (D5_FRAMEWISE) | 6 (60.0%) |
| PERCEPTION_INVALID | 4 |
| Valid dives | [133, 311, 676, 1040, 2169, 2387] |
| Invalid dives | [524, 2341, 2555, 2625] |

Previous result (1/10) was R1-contaminated. Re-derived from d5_only_correct fields.
Gate: `DEVELOPMENT_PERCEPTION_USABLE`

**DEVELOPMENT EL evaluation (D5_FRAMEWISE trajectories):** V2.1 0/6, V2.2 0/6.
Root cause: proxy video (202×360) creates coverage gaps during flight phase — not EL bug.

### Dive 311 diagnosis
{
  "perception": "PERCEPTION_INVALID",
  "phases": {
    "takeoff": {
      "correct": false,
      "iou": 0.0,
      "d5_only_correct": true,
      "d5_only_iou": 0.4543,
      "sel_cy_norm": 0.95,
      "sel_bbox_h_norm": 0.1001
    },
    "water_contact": {
      "correct": true,
      "iou": 0.6036,
      "d5_only_correct": true,
      "d5_only_iou": 0.6036,
      "sel_cy_norm": 0.5114,
      "sel_bbox_h_norm": 0.2289
    }
  },
  "n_correct": 1,
  "n_total": 2,
  "gt_timing": {
    "dive_id": 311,
    "takeoff_pts_s": 13.7546,
    "apex_pts_s": null,
    "water_contact_pts_s": 14.821262
  }
}

### Perception architecture decision
**`D5_FRAMEWISE_SUFFICIENT`** (see `docs/science/TARGET_DIVER_PERCEPTION_V1_FREEZE.json`)

### Event Logic decision
- V2.1: retained and frozen (PARAMS_E1 takeoff_vel_threshold=0.04)
- V2.2: NOT promoted — Paris trajectory gate failed, no EL comparison possible
- Next step: Fix C3 (water_contact detection) then re-run Paris EL evaluation

### Detector closure
`D5_A_FROZEN` — no new detector training authorized in this cycle.
Water contact detection requires FLOOR_CONF<0.01 (noted for next cycle).

## Current supervisor gate

`SUPERVISOR_REVIEW_AFTER_PERCEPTION_V1_CLOSURE_AND_REAL_EVENT_LOGIC`
