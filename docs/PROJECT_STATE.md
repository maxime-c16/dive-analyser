# PROJECT_STATE.md — Dive Analyser / DiveSensei

> Durable project handoff. Last verified: **2026-09-08** (Detector D4 Reopen + Selector Revalidation —
> D4 recall 80.6% (+12.9pp vs D3), 0 regressions. Paris 3/3 phases covered (historic first).
> All gates fail: H1 FAIL (80.6%<90%), M FAIL (S0 best 71%<80%), O FAIL (Paris 1/3 trajectory).
> S0 frozen as D4-era selector (S1 regresses with D4 FPs). Paris firewall unbroken.
> Latest audit: `docs/science/DETECTOR_D4_REOPEN_AND_SELECTION_REVALIDATION_REPORT.md`
> Previous: `docs/science/TARGET_DIVER_SELECTION_V2_LOW_CONFIDENCE_REPORT.md`
> Supervisor gate: **`SUPERVISOR_REVIEW_AFTER_DETECTOR_D4_REOPEN_AND_SELECTION_REVALIDATION`**

## Project purpose

Personal diving-analysis platform for a single athlete (Maxime) and training partners.
Divers manually pre-trim clips in macOS Photos and caption them with a compact grammar
(dive code, performance, height, modifiers). The system ingests those clips + captions,
stores structured metadata, computes statistics/insights, and serves a web UI.
Long-term goal: a second, deeper analysis layer (phase timing, takeoff/entry
characteristics, athlete-vs-self comparison). **Not implemented yet — direction only.**

## Canonical repository

- **`mcauchy@192.168.1.57:~/dive-analyser`** (Debian 12, host `deb-serv`) — the ONLY
  canonical Git repository. Branch `uiux-overhaul-pro-app`.
  No remotes.
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

## Canonical source authorities

| Concern | Authoritative source | Drift status |
|---|---|---|
| Backend | server repo `backend/` (uncommitted working tree) | UNCOMMITTED |
| Frontend | server repo `frontend/src` | UNCOMMITTED |
| Mac agent | server repo `mac-agent/` — reconciled 2026-09-05, byte-identical to deployed | RESOLVED |
| DB schema | `backend/migrations/*.sql` | known consolidation issue |
| Runtime config | `.env` + `docker-compose.yml` (server), `state/config.yaml` (Mac) | never in Git |
| Media originals | Mac source vault + server legacy `media/videos` | DATA — excluded |
| Derived renditions | server `media/cache` (~840 MB) | DATA — excluded |

## Current analysis capabilities

- **A. User-authored:** caption grammar → structured metadata
- **B. Deterministic:** DD engine, session aggregates, analytics, FINA scoring
- **C. Heuristic:** fear/plateau, milestones, journey service (no video analysis)
- **D. ML/CV:** `execution_analyzer.py` is a STUB. Analysis layer remains unimplemented.

## Science layer status (2026-09-08)

### Frozen references
- Canary dive: 2819 (5122D G/G, springboard 1m, hurdle)
- Source: `IMG_1937.mov` SHA=`d122262be8e7a8721ab2f6a71721bb3544403da78324138d026360ef9820eaae`
- GT PTS: takeoff=3.120s, apex=3.570s, water_contact=4.220s
- Event Logic V2.1 frozen: `EVENT_LOGIC_V2_1_FREEZE.json` (29/29 unit tests pass)
- Event Logic V2.2 frozen: `EVENT_LOGIC_V2_2_FREEZE.json`, status: `V2_2_EXPERIMENTAL_FROZEN_NOT_ADOPTED`
- D3.1 operating point frozen: `D3_1_OPERATING_POINT_FREEZE.json`, conf=0.05
- D3 weights frozen: SHA256 `bf6415fb63aa311f45262e555899d3023dd3d05d43a5e0d69b5e86c342e1a77d`
  (durable: `~/dive-analyser/models/frozen/DIVER_DETECTOR_D3_V8N_best.pt` on server)
- D3 proposal threshold frozen: `D3_PROPOSAL_V1_FREEZE.json`, conf=0.05
- Target diver selector V2 frozen: `TARGET_DIVER_SELECTOR_V2_FREEZE.json` (S1_GLOBAL_PATH, V2 era)
- Target diver selector V1 frozen: `TARGET_DIVER_SELECTOR_V1_FREEZE.json` (historical)
- Paris human spatial authority: 14 maintainer-boxed frames at native 1080×1920
- **NEW** D4 weights frozen: `D4_PROPOSAL_V1_FREEZE.json`, SHA `842291f1...` (`models/frozen/DIVER_DETECTOR_D4_A_V8N_best.pt`)
- **NEW** D4-era selector frozen: `SELECTOR_FREEZE_D4.json` — S0 (top-conf) replaces S1 for D4 proposals

### Critical findings (DETECTOR_D4_REOPEN cycle, 2026-09-08)

**Central finding:**
> D4 achieves 80.6% recall (+12.9pp vs D3), zero regressions.
> Paris coverage 3/3 phases (historic first, D3 had 0/3).
> All gates FAIL: H1 (80.6%<90%), M (71%<80%), O (Paris 1/3 trajectory).
> System remains at **TRAJECTORY_INPUT_FAIL** for Paris.

1. **D4 training (Phase G)**: YOLOv8n, COCO-pretrained fresh start, MPS amp=False.
   22 new frames from failure dives (2555/2680/676/2541 → train; 2341 → holdout).
   71 epochs early-stopped. val_mAP50=0.333, P=0.656, R=0.286.

2. **Grouped evaluation (Phase H)**: 25/31 = 80.6% at op threshold. +4 new matches vs D3.
   Zero regressions. Phase H1 gate (90%) → FAIL.

3. **Paris coverage (Phase J/K)**: D4 detects diver in all 3 Paris phases for first time.
   Takeoff IoU=0.387 (MATCH). Apex/water_contact detected but FP-ranked (wrong target).
   Floor analysis: diver visible at rank 10 (apex/takeoff), rank 121 (water_contact).
   Finding: `D4_IMPROVES_PARIS_WITHOUT_PARIS_TRAINING`.

4. **Selector revalidation (Phase M)**: S0=71%, S1=61%, S3=61% on DEVELOPMENT.
   S1 regresses with D4 — spatially plausible FPs confuse Viterbi path.
   Phase M gate (80%) → FAIL for all selectors.

5. **Selector freeze (Phase N)**: S0 (top-conf) frozen as D4-era selector.
   Simpler and more accurate than S1 with D4 FP profile.

6. **Paris trajectory gate (Phase O)**: TRAJECTORY_INPUT_FAIL with S0 (same as S1).
   Takeoff MATCH (IoU=0.387). Apex WRONG_TARGET. water_contact WRONG_TARGET (rank 121).

7. **Dive 311**: INDEPENDENT_EVENT_LOGIC_FAILURE carry-forward (unchanged).

8. **V2.2 status**: V2_2_EXPERIMENTAL_FROZEN_NOT_ADOPTED (unchanged).

### Perception status
**`TRAJECTORY_INPUT_FAIL`** — gates passed: H=80.6%/90% FAIL, M=71%/80% FAIL, O=1/3 FAIL

D4 is a strong improvement but systematic failures remain:
- Water-contact calibration (5 dives fail at water_contact phase)
- FP dominance at Paris (spectators outrank diver at apex and water_contact)
- 2625 architectural limit (hurdle geometry)

### Next required work (priority order)
1. **Water-contact calibration**: add more water-entry positives across venues.
2. **Paris FP suppression**: collect non-diver Paris-venue frames as hard negatives.
   (Requires explicitly downgrading Paris from canary status before using any Paris venue data.)
3. **Dive 311 EL failure**: independent state machine debug.
4. **V2.2 HURDLE accumulation**: n=2 is fragile.

### Event Logic status
- V2.1: **FROZEN** — historical reference
- V2.2: **FROZEN** experimental — `V2_2_EXPERIMENTAL_FROZEN_NOT_ADOPTED`. Pending larger HURDLE sample.
- Dive 311: open INDEPENDENT_EVENT_LOGIC_FAILURE (needs separate investigation)

## Test suite

D4 cycle adds Phase S tests (all pass). Full suite:
- `test_detector_d4_reopen.py` — **28 PASS** (pre-annotation) + **~14 PASS** (D4 cycle addons)
- `test_target_diver_selection_v2.py` — **28 PASS**
- `test_target_diver_selection_v1.py` — 18 PASS
- `test_event_logic_v2_1.py` — 29 PASS (or 36, see file)
- `test_event_logic_v2_2.py` — 24 PASS (or 25)
- `test_d3_pipeline.py`, `test_d4_threshold_perception.py`, etc.
- `test_report_consistency.py` — 15 PASS
- Combined (`venv_c/bin/python3 -m pytest experiments/landmark_pilot -q`): **100+ PASS**

## AMP authority

`PINNED_STACK_MPS_AMP_INCOMPATIBILITY_OR_VERSION_SPECIFIC_BEHAVIOR`
All MPS retraining uses `amp=False`.

## Current supervisor gate

`SUPERVISOR_REVIEW_AFTER_DETECTOR_D4_REOPEN_AND_SELECTION_REVALIDATION`
