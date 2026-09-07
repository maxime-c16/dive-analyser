# PROJECT_STATE.md — Dive Analyser / DiveSensei

> Durable project handoff. Last verified: **2026-09-07** (Perception V4 — threshold calibration + Paris pass + EL diagnosis).
> Latest audit: `docs/science/PERCEPTION_V4_CROSS_VENUE_GENERALIZATION_REPORT.md`
> Previous: `docs/science/DIVER_DETECTOR_TRAINING_SANITY_AND_D3_REPORT.md`
> Supervisor gate: **`SUPERVISOR_REVIEW_AFTER_CROSS_VENUE_PERCEPTION_V4`**

## Project purpose

Personal diving-analysis platform for a single athlete (Maxime) and training partners.
Divers manually pre-trim clips in macOS Photos and caption them with a compact grammar
(dive code, performance, height, modifiers). The system ingests those clips + captions,
stores structured metadata, computes statistics/insights, and serves a web UI.
Long-term goal: a second, deeper analysis layer (phase timing, takeoff/entry
characteristics, athlete-vs-self comparison). **Not implemented yet — direction only.**

## Canonical repository

- **`mcauchy@192.168.1.57:~/dive-analyser`** (Debian 12, host `deb-serv`) — the ONLY
  canonical Git repository. Branch `uiux-overhaul-pro-app`. HEAD: *see commit below*.
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

## Science layer status (2026-09-07)

### Frozen references
- Canary dive: 2819 (5122D G/G, springboard 1m, hurdle)
- Source: `IMG_1937.mov` SHA=`d122262be8e7a8721ab2f6a71721bb3544403da78324138d026360ef9820eaae`
- GT PTS: takeoff=3.120s, apex=3.570s, water_contact=4.220s
- Event Logic V2.1 frozen: `EVENT_LOGIC_V2_1_FREEZE.json`, 36/36 unit tests pass (SHA: 63cfadebfc…)
- D3.1 operating point frozen: `D3_1_OPERATING_POINT_FREEZE.json`, conf=0.05 (same weights as D3)
- D3 detector frozen: `DIVER_DETECTOR_D3_FREEZE.json`, weights SHA256: `bf6415fb63aa311f45262e555899d3023dd3d05d43a5e0d69b5e86c342e1a77d`

### Critical findings (Perception V4 cycle, 2026-09-07)

1. **D3.1 threshold calibrated to conf=0.05**: Holdout recall 91.3% vs 76.1% at conf=0.10.
   Paris action-window coverage jumps from 7.5% → **100%** (64/64 frames).
   Val recall unchanged (no regression). Calibration used INTERNAL data only.

2. **Paris TRAJECTORY_INPUT_PASS achieved**: At conf=0.05, all GT landmarks detected,
   100% action-window coverage, max gap = 0s, zero spectator contamination.
   All 2178 detections in diver region (cy ≤ 0.70). Primary candidate in diver region: 64/64.

3. **Target selection (N0 vs N1 identical)**: Framewise (highest-conf + continuity)
   and ByteTrack both achieve 100% coverage with identical trajectory (no spectator hits).
   N0 preferred (simpler, equal performance).

4. **Event Logic V2.1 first real-signal evaluation**: `REAL_SIGNAL_CANARY_FAIL`
   - Predicted takeoff: 4.547s (GT: 3.120s, error **+1.427s**)
   - Predicted apex: 5.043s (GT: 3.570s, error **+1.473s**)
   - Predicted water_contact: 5.680s (GT: 4.220s, error **+1.460s**)
   - Systematic positive offset: algorithm finds events in post-dive portion of video

5. **Root cause: VELOCITY_RESOLUTION_INSUFFICIENT_AT_360P**
   - At GT takeoff (3.120s), smoothed velocity = **−0.011/s**
   - EL algorithm requires `takeoff_vel_threshold = 0.04/s` (sustained)
   - At 360p, the 1m springboard flight arc = ≈7px vertical → velocity too weak
   - Post-dive activity (t > 4.5s) generates 0.045–0.096/s signals → algorithm latches these
   - **Apex detection was correct**: t=3.556s vs GT 3.570s (Δ=14ms) — not a general failure

6. **Detector decision**: `D3_THRESHOLD_WAS_SUFFICIENT`
   No new training data required for detector coverage. Multi-venue D4 training is
   NOT yet required for detector generalization (deferred, not ruled out).

7. **Event Logic decision**: `REAL_SIGNAL_CANARY_FAIL` — velocity resolution is the blocker.

### Event Logic V2.1
- Status: **FROZEN, CORRECT, NOT_REAL_SIGNAL_VALIDATED**
- 36/36 unit tests pass (all H1/H2/H3 families)
- Real-signal evaluation: FAIL (velocity resolution at 360p insufficient)
- Do NOT modify Event Logic V2.1 — it correctly identifies events in the test; the problem is input signal quality

### Perception architecture decision
`D3_THRESHOLD_WAS_SUFFICIENT` (coverage); `REAL_SIGNAL_CANARY_FAIL` (EL velocity)

### Next required work (priority order)
1. **Process Paris canary at 1080p** — full resolution for ~3× velocity signal improvement.
   Verify v_takeoff ≥ 0.04/s sustained at 1080p. This is the fastest path to EL PASS.
2. **If 1080p still fails**: Create 360p-calibrated EL params variant with `takeoff_vel_threshold ≈ 0.008/s`,
   validate on synthetic trajectories, then apply to Paris.
3. **Post-dive isolation**: Truncate trajectory at water_contact + buffer before feeding EL,
   to eliminate post-dive noise. Does not require resolution change.
4. **If EL pass achieved**: Run Phase Q (bounded multi-dive validation, max 12 dives).
5. **Multi-domain D4** (Phases D–L): Deferred. Not yet required for coverage. Revisit if 1080p
   trajectory still fails Event Logic AND the failure is domain-related.

## Test suite

- `experiments/landmark_pilot/test_d3_pipeline.py` — 20 PASS, 16 SKIP (ephemeral Mac dataset files), 0 FAIL
- `experiments/landmark_pilot/test_d4_threshold_perception.py` — 35 PASS, 0 SKIP, 0 FAIL
- Combined: **55 PASS, 16 SKIP, 0 FAIL**
- Covers: D3.1 threshold freeze, Paris firewall, trajectory gate PASS (D3.1),
  spectator-region sanity, N0/N1 comparison, EL real-signal failure, EL identity,
  AMP=False authority, Phase R decisions.

## AMP authority

`PINNED_STACK_MPS_AMP_INCOMPATIBILITY_OR_VERSION_SPECIFIC_BEHAVIOR`

Observed on the exact historical Ultralytics/PyTorch environment used for D2/D3 training.
All MPS retraining uses `amp=False`. Do NOT document as "AMP broken on all Apple Silicon."

## Current supervisor gate

`SUPERVISOR_REVIEW_AFTER_CROSS_VENUE_PERCEPTION_V4`
