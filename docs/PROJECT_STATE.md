# PROJECT_STATE.md — Dive Analyser / DiveSensei

> Durable project handoff. Last verified: **2026-09-08** (Target Diver Selection V2 —
> proposal threshold sweep, S3 action-likelihood selector, motion auxiliary, Paris shadow eval.
> Gate A1 DETECTOR_REOPEN_REQUIRED (ceiling 77% < 80%). TRAJECTORY_INPUT_FAIL.
> S3 shows partial Paris static-lock break (water_contact MATCH); frozen selector remains S1.
> Latest audit: `docs/science/TARGET_DIVER_SELECTION_V2_LOW_CONFIDENCE_REPORT.md`
> Previous: `docs/science/TARGET_DIVER_SELECTION_V1_REPORT.md`
> Supervisor gate: **`SUPERVISOR_REVIEW_AFTER_TARGET_DIVER_SELECTION_V2`**

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
- **NEW** D3 proposal threshold frozen: `D3_PROPOSAL_V1_FREEZE.json`, conf=0.05
- **NEW** Target diver selector V2 frozen: `TARGET_DIVER_SELECTOR_V2_FREEZE.json` (S1_GLOBAL_PATH)
- Target diver selector V1 frozen: `TARGET_DIVER_SELECTOR_V1_FREEZE.json` (historical)
- Paris human spatial authority: 14 maintainer-boxed frames at native 1080×1920

### Critical findings (TARGET_DIVER_SELECTION_V2 cycle, 2026-09-08)

**Central finding:**
> Raw detector ceiling 77.4% < 80% at any practical proposal threshold.
> Gate A1: **DETECTOR_REOPEN_REQUIRED**.
> Perception architecture: **DETECTOR_REOPEN_REQUIRED**.

1. **Proposal-threshold sweep (Phase A)**: Evaluated conf=0.005/0.01/0.02/0.05 against
   31 DEVELOPMENT reference frames. Of 9 miss frames at conf=0.05: 7/9 are wrong-location
   (detector fires at wrong position — lower threshold adds more wrong candidates, no
   recovery); 2/9 are genuine zero-detection (dive 2541 frames 525/558, confirmed by
   conf=0.001 inference). Max achievable ceiling: 77.4% (24/31) at conf=0.005. Still
   below 80% gate.

2. **S3 action-likelihood selector (Phase E)**: Implemented spatial-persistence motion
   auxiliary: penalises candidates that appear at the same location in most frames
   (static FPs), favours transient candidates (true diver during flight).
   W_PERSIST=4.0 × max(0, persist_freq − 0.25). Also adds scale-plausibility term.
   DEVELOPMENT: S3=48.4% ALL vs S1=51.6% — 1-frame regression (dive 133 takeoff;
   dive 2625 safe-NULL from S1 → wrong-target from S3). HURDLE tied at 40%.

3. **S3 Paris shadow evaluation**: Persistence penalty partially breaks static-FP lock
   at Paris. water_contact MATCH (iou=0.511, dist=0.042, conf=0.121) — S1 was WRONG.
   Takeoff and apex still WRONG for both selectors. std_cy: S3=0.075 vs S1=0.016 —
   S3 shows 4.6× more trajectory variation (partial lock break confirmed).

4. **Selector freeze (Phase I)**: S1 remains better on DEVELOPMENT (per packet rule:
   choose using DEVELOPMENT only). Frozen as TARGET_DIVER_SELECTOR_V2 = S1_GLOBAL_PATH
   (algorithm unchanged from V1; same parameters). S3 recorded as directional finding.

5. **Paris trajectory gate**: TRAJECTORY_INPUT_FAIL for frozen S1 (0/3 GT anchors correct).
   Shadow S3: 1/3 correct (water_contact only). Both fail gate.

6. **Dive 311**: INDEPENDENT_EVENT_LOGIC_FAILURE confirmed. ~4s error in both V2.1 and
   V2.2 identically — not a V2.1-vs-V2.2 discriminator; state machine locks on late
   spurious motion at ~18s. Perception is clean (correct target identity verified).

7. **V2.2 status**: V2_2_SUPPORTED_BY_EXPANDED_REAL_DATA (n=2 HURDLE clean trajectories,
   1 clear win / 1 tie / 0 regressions) — unchanged from V1. Threshold not promoted.

8. **Paris event test**: not evaluable (TRAJECTORY_INPUT_FAIL). Both V2.1 and V2.2
   return no landmarks on Paris S1 trajectory — static-FP lock confounds the signal.

### Perception status
**`DETECTOR_REOPEN_REQUIRED`**

The selection mechanism (S3 motion auxiliary) is directionally correct but insufficient
to overcome the wrong-location detection gap (7/9 miss frames at wrong spatial position)
and static-FP confidence dominance at Paris (needs venue-specific training data).

### Detector reopen recommendation
1. Add Paris-venue training images with the static FP annotated as hard negative
2. Add wrong-location detections (2341, 2555, 2625, 2680, 676) as hard negatives
3. For 2541 zero-detection: reduce proposal_conf to 0.02 (recovers frame 525, conf=0.039)
4. Longer term: human-centric foreground representation (FineParser direction) to reduce
   background object influence in diving action analysis

### Event Logic status
- V2.1: **FROZEN** — historical reference
- V2.2: **FROZEN** experimental — `V2_2_EXPERIMENTAL_FROZEN_NOT_ADOPTED`. Pending larger HURDLE sample.
- Dive 311: open INDEPENDENT_EVENT_LOGIC_FAILURE (needs separate investigation)

### Next required work (priority order)
1. **Detector reopening**: wrong-location detection failures (7/9 miss frames) + static-FP
   confidence dominance at Paris. Exact recommendation above.
2. **Dive 311 Event Logic failure**: independent investigation needed once perception
   improves for more diverse clean trajectories.
3. **V2.2 HURDLE accumulation**: n=2 clean HURDLE trajectories is fragile; more needed
   before promoting threshold.
4. **S3 persistence auxiliary tuning**: directionally correct; once detector ceiling improves,
   S3 (or S3+) should be re-evaluated as primary selector.

## Test suite

28 new tests for V2 (all pass). Full suite:
- `test_target_diver_selection_v2.py` — **28 PASS**
- `test_target_diver_selection_v1.py` — 18 PASS
- `test_event_logic_v2_1.py` — 29 PASS (or 36, see file)
- `test_event_logic_v2_2.py` — 24 PASS (or 25)
- `test_d3_pipeline.py`, `test_d4_threshold_perception.py`, etc.
- Combined (`venv_c/bin/python3 -m pytest experiments/landmark_pilot -q`): **82+ PASS**

## AMP authority

`PINNED_STACK_MPS_AMP_INCOMPATIBILITY_OR_VERSION_SPECIFIC_BEHAVIOR`
All MPS retraining uses `amp=False`.

## Current supervisor gate

`SUPERVISOR_REVIEW_AFTER_TARGET_DIVER_SELECTION_V2`
