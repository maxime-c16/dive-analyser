# PROJECT_STATE.md — Dive Analyser / DiveSensei

> Durable project handoff. Last verified: **2026-09-06** (real-signal pipeline V1).
> Latest audit: `docs/science/REAL_SIGNAL_EVENT_LOGIC_AND_HIGHRES_PIPELINE_V1_REPORT.md`
> Previous: `docs/audits/SOURCE_AUTHORITY_RECONCILIATION_2026-09-05.md`
> Supervisor gate: **`SUPERVISOR_REVIEW_AFTER_REAL_SIGNAL_HIGHRES_V1`**

## Project purpose

Personal diving-analysis platform for a single athlete (Maxime) and training partners.
Divers manually pre-trim clips in macOS Photos and caption them with a compact grammar
(dive code, performance, height, modifiers). The system ingests those clips + captions,
stores structured metadata, computes statistics/insights, and serves a web UI.
Long-term goal: a second, deeper analysis layer (phase timing, takeoff/entry
characteristics, athlete-vs-self comparison). **Not implemented yet — direction only.**

## Canonical repository

- **`mcauchy@192.168.1.57:~/dive-analyser`** (Debian 12, host `deb-serv`) — the ONLY
  canonical Git repository. Branch `uiux-overhaul-pro-app`. HEAD: `35a1b053`.
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

## Science layer status (2026-09-06)

### Frozen references
- Canary dive: 2819 (5122D G/G, springboard 1m, hurdle)
- Source: `IMG_1937.mov` SHA=`d122262be8e7a8721ab2f6a71721bb3544403da78324138d026360ef9820eaae`
- GT PTS: takeoff=3.120s, apex=3.570s, water_contact=4.220s (frame 187, 214, 253)
- Event Logic V2 frozen: `EVENT_LOGIC_V2_FREEZE.json`, 29/29 unit tests pass

### Critical findings (REAL_SIGNAL_HIGHRES_V1)
1. **Phase M synthetic check is broken:** takeoff error −1.670s, apex error −1.353s.
   The HIGH_RESOLUTION_CANARY_EVENT_SEMANTICS_CORRECTION_V1.md values (0.103/0.013/0.030s)
   were never produced by the committed code. Audit: `PHASE_M_CANARY_CHECK_AUDIT.json`.
2. **L1 domain-adapted model (mAP50=0.766 on DEVELOPMENT) produces 0 detections**
   on the canary video. CUDA is NOT required (MPS+CPU both work). Generalization failure.
3. **COCO model detects spectators, not the diver during flight** (t=3.12–4.22s).
   Both framewise and ByteTrack produce spectator trajectories.
4. **Event Logic V2 cannot be end-to-end evaluated** on any real video trajectory.
   Status: EVENT_LOGIC_NOT_YET_EVALUABLE_DUE_TO_PERCEPTION.
5. **ANALYSIS_SOURCE = user-edited/trimmed Photos rendition** (osxphotos default).
   `--skip-edited` is SCIENTIFICALLY_INVALID_FOR_DIRECT_PTS_COMPARISON.

### Perception architecture decision
**`PERCEPTION_STILL_INSUFFICIENT`**

### Next required work
1. Fix diver detection: pool-diverse training data OR spatial scene prior for COCO
2. Fix Phase M synthetic trajectory (monotone board-loading, not sinusoidal oscillation)
3. Add Event Logic V2 integration test on a realistic hurdle trajectory
4. Discriminative target selection (exclude spectator region)
5. Pool-specific corridor calibration as near-term fallback

## Current supervisor gate

`SUPERVISOR_REVIEW_AFTER_REAL_SIGNAL_HIGHRES_V1`
