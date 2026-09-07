# PROJECT_STATE.md — Dive Analyser / DiveSensei

> Durable project handoff. Last verified: **2026-09-07** (D3 detector + training sanity).
> Latest audit: `docs/science/DIVER_DETECTOR_TRAINING_SANITY_AND_D3_REPORT.md`
> Previous: `docs/science/REAL_SIGNAL_EVENT_LOGIC_AND_HIGHRES_PIPELINE_V1_REPORT.md`
> Supervisor gate: **`SUPERVISOR_REVIEW_AFTER_D3_DETECTOR_SANITY`**

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
- GT PTS: takeoff=3.120s, apex=3.570s, water_contact=4.220s (frame 187, 214, 253)
- Event Logic V2.1 frozen: `EVENT_LOGIC_V2_1_FREEZE.json`, 36/36 unit tests pass (SHA: 63cfadebfc...)
- D3 detector frozen: `DIVER_DETECTOR_D3_FREEZE.json`, weights SHA256: `bf6415fb63aa311f45262e555899d3023dd3d05d43a5e0d69b5e86c342e1a77d`

### D2 taxonomy correction (Phase A, supervisor correction)
- D2 failure was previously classified as `EXTERNAL_GENERALIZATION_FAILURE` — **INCORRECT**
- **Correct classification**: `D2_TRAINING_COLLAPSE_OR_SEVERE_UNDERFIT`
- Root cause: MPS AMP bug (`amp=True` default on Apple Silicon suppresses classification gradient)
- Symptom: train precision ≈ 0.003, best_epoch=1, uniform conf ≈ 0.013 on ALL images
- Fix: `amp=False` for all MPS training

### Critical findings (D3_DETECTOR_SANITY cycle, 2026-09-07)

1. **MPS AMP bug root cause identified and repaired**: All future training uses `amp=False` on MPS.
   D2 training collapse was a pipeline bug, not a data/label problem.

2. **D2 missing hard negatives**: 35 `not_visible` frames were entirely excluded from D2 YOLO export.
   Fixed in D3: 14 hard negatives in train, 3 in val, 18 in holdout.

3. **D2 label audit**: 84/85 labels valid; 1 bbox y-clip fixed (v2_d0287_f0.txt).

4. **Overfit sanity PASS**: With `amp=False`, tiny 10+3 dataset achieves mean_pos_conf=0.912 (10/10 > 0.25).
   Verdict: `TRAINING_PIPELINE_CAN_OVERFIT`. Pipeline is scientifically sound.

5. **D3 training result**: best_epoch=68, best_mAP50=0.627, holdout recall=0.761 at conf=0.10.
   In-domain video coverage: **97.0%** (97/100 action frames at conf≥0.10).

6. **Paris external canary (frozen D3)**: overall 44.7%, action window **7.5%** (5/67 frames).
   Longest gap 1.034s. `TRAJECTORY_INPUT_FAIL` — domain gap remains.

7. **COCO person at R360**: 0 detections at conf≥0.10 in action window. Prior V1 spectator claim
   (300/322 at 1080p) is superseded; not applicable at R360 operating resolution.

8. **Scene-prior**: `SCENE_PRIOR_CANNOT_RECOVER_MISSING_DETECTION`.

9. **Trajectory gate**: FAIL (7.5% coverage, 1.034s gap). Event Logic V2.1 not yet evaluable on real signal.

10. **Generalization verdict**: `TRAINING_PIPELINE_REPAIRED_AND_IN_DOMAIN_WORKS`.
    Remaining issue: domain gap (single-venue training). Requires multi-domain data.

### Event Logic V2.1
- Status: **FROZEN, CORRECT, NOT_REAL_SIGNAL_VALIDATED**
- 36/36 unit tests pass (MECHANISM_TEST_PASS)
- Cannot be end-to-end evaluated until trajectory gate passes
- Do NOT modify Event Logic unless a real scientifically usable trajectory exists

### Perception architecture
**`TRAINING_PIPELINE_REPAIRED_AND_IN_DOMAIN_WORKS; MORE_DOMAIN_DIVERSITY_REQUIRED`**

### Next required work
1. **Multi-domain training data** (50–100 frames, 2–3 outdoor pool venues)
2. Evaluate D4 detector on Paris action window — target ≥ 50% coverage
3. When trajectory gate passes → evaluate Event Logic V2.1 end-to-end
4. Fix Phase M synthetic trajectory (sinusoidal hurdle bug → monotone board-loading)

## Test suite

- `experiments/landmark_pilot/test_d3_pipeline.py` — 36 tests, all pass
- Covers: D3 dataset integrity, hard-negative policy, overfit sanity, D3 training,
  Paris firewall, trajectory gate, scene-prior decision, generalization decision

## Current supervisor gate

`SUPERVISOR_REVIEW_AFTER_D3_DETECTOR_SANITY`
