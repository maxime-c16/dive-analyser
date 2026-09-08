# PROJECT_STATE.md — Dive Analyser / DiveSensei

> Durable project handoff. Last verified: **2026-09-08** (Real-Trajectory Event Logic V2.2 —
> D3.1 target-identity audit found a pervasive wrong-target lock on Paris; V2.2 scale-aware
> Event Logic developed/frozen on DEVELOPMENT; Paris remains FAIL, now attributed to perception).
> Latest audit: `docs/science/REAL_TRAJECTORY_EVENT_LOGIC_V2_2_REPORT.md`
> Previous: `docs/science/PERCEPTION_V4_CROSS_VENUE_GENERALIZATION_REPORT.md`
> Supervisor gate: **`SUPERVISOR_REVIEW_AFTER_REAL_TRAJECTORY_EVENT_LOGIC_V2_2`**

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
- **2026-09-08 mirror repair**: server→Mac SSH auth was broken because the server's own
  agent key (`~/.ssh/divesensei_agent_key` on the server, comment
  `divesensei-agent@deb-serv`) was never added to the Mac's `~/.ssh/authorized_keys`
  (confirmed: the key existed on the server but had no matching entry on the Mac).
  Repaired by appending that existing public key to the Mac's `authorized_keys` (no new
  keypair, no security weakening). The Mac itself has **no outbound private key** to the
  server at all (`~/.ssh` on the Mac has no key files), so Mac-initiated `git fetch`/pull
  is still not possible — the durable sync method going forward is **server-initiated**:
  `git bundle create` on the server, `scp` (now working) to the Mac, `git fetch
  <bundle>`+`git update-ref HEAD` on the Mac's bare mirror repo at `~/dive-analyser`.
  This mirrors the mirror's own `remotes/bundle/head*` refs, which show this was the
  established method historically. A human should provision a Mac→server key if
  bidirectional (Mac-initiated) sync is ever required.

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
  (found only at `~/Downloads/IMG_1937.mov` on Maxime's local Mac in this cycle — NOT
  present on the canonical server or the Mac mirror. Reproducibility risk, see below.)
- GT PTS: takeoff=3.120s, apex=3.570s, water_contact=4.220s
- Event Logic V2.1 frozen: `EVENT_LOGIC_V2_1_FREEZE.json` (36/36 tests) — **superseded
  for new work** by Event Logic V2.2 (do not delete; still the historical reference)
- **Event Logic V2.2 frozen**: `EVENT_LOGIC_V2_2_FREEZE.json` — S1_BODY_SCALE selected,
  scale-aware takeoff threshold (0.55 body-heights/s), 24/24 unit tests pass
- D3.1 operating point frozen: `D3_1_OPERATING_POINT_FREEZE.json`, conf=0.05 (same weights as D3)
- D3 detector frozen: `DIVER_DETECTOR_D3_FREEZE.json`, weights SHA256: `bf6415fb63aa311f45262e555899d3023dd3d05d43a5e0d69b5e86c342e1a77d`
- **Reproducibility risk**: the D3/D3.1 weights file matching this SHA256 was found
  ONLY in an ephemeral local Claude-Code scratchpad directory from a previous session
  (`.../41096d47-.../scratchpad/runs/DIVER_DETECTOR_D3_V8N/weights/best.pt`), not in the
  canonical server repo or any durable server location. Copied in this cycle to
  `~/dive-analyser/models/frozen/DIVER_DETECTOR_D3_V8N_best.pt` on the server (gitignored,
  not committed — per "no model-weight duplication in git", but now at least durably
  present on the canonical host instead of only a disposable local scratchpad).
  **A human should confirm a permanent, backed-up home for frozen model weights** —
  the current situation was one cleaned scratchpad away from being unrecoverable.

### Critical findings (Real-Trajectory Event Logic V2.2 cycle, 2026-09-08)

1. **D3.1 target-identity audit (Phase B/C) — the headline finding**: the frozen N0
   (framewise-highest-confidence + continuity) trajectory used for ALL of Perception
   V4's Paris conclusions is a **wrong-target lock on static background structure**
   for nearly the entire action window (confirmed by direct visual comparison, at
   native 1080p, against the real source frames at every sampled phase: preparation
   correct at t=0.2s, then wrong from hurdle through entry). `PARIS_ACTION_WINDOW_
   CANDIDATE_COVERAGE=100%` was true but never meant "correctly identified the diver" —
   it meant "a candidate existed". N0 and N1 (ByteTrack) "agreeing" in PHASE_MN was
   both failing identically (same fixed-location lock / persisting track id), not
   evidence either is reliable.

2. **Root cause reframed**: Perception V4 attributed the Paris `REAL_SIGNAL_CANARY_FAIL`
   to `VELOCITY_RESOLUTION_INSUFFICIENT_AT_360P`. This cycle shows the larger effect is
   that the fed-in trajectory was frequently not the diver at all — a selection failure
   (framewise-highest-confidence prefers a stable false positive at conf 0.30-0.42 over
   the true diver's near-threshold conf 0.05-0.08), not (only) a magnitude/resolution
   problem. The resolution hypothesis is also now directly falsified: controlled
   360p/720p/native-1080p re-inference shows normalized trajectory span stays in the
   same 0.06-0.08 order of magnitude across a 6x linear-resolution range — no ~3x
   velocity-signal improvement exists at 1080p, confirming Supervisor Correction 3.

3. **Same failure mode confirmed on DEVELOPMENT, not just Paris**: of 8 DEVELOPMENT
   dives run through the identical frozen D3.1/N0 pipeline, 3 (both HURDLE dives in the
   sample, plus one STANDING dive) were excluded by a static-lock variance check
   (cy_norm std 0.0002-0.0004, matching Paris's 0.0016 signature) and 2 more failed a
   sparse-frame identity check — leaving only **3 of 8 usable** (all STANDING) for
   Event Logic scoring.

4. **Event Logic V2.2 developed and frozen** (scale-aware takeoff detection,
   `EVENT_LOGIC_V2_2_FREEZE.json`, S1_BODY_SCALE selected): on the 3 usable DEVELOPMENT
   dives, V2.2-S1/S2 and frozen V2.1 are statistically indistinguishable (n too small
   to show improvement either way; no >1s or catastrophic errors). Selected on
   scale-robustness/simplicity grounds per Phase K, not a proven accuracy win.

5. **Paris external test**: still `REAL_SIGNAL_CANARY_FAIL` for every variant/resolution,
   via a *different* error pattern than before (early or absent, not the prior systematic
   +1.4s late) — expected and explicitly non-diagnostic of Event Logic, since perception
   identity there is unresolved (see finding 1).

6. **Smoothing audit (Phase G)**: all Event Logic temporal windows are already
   PTS/seconds-based (not frame-count), so there was nothing to convert. FPS-invariance
   verified by a new test fixture.

7. **Water-contact terminality (Phase I)**: audited and confirmed already non-circular
   (fixed geometric cy-threshold / confidence-dropout, no dependency on any prior
   water_contact estimate). No new refinement needed or added.

### Event Logic status
- V2.1: **FROZEN** (historical reference, do not modify)
- **V2.2: FROZEN** (`EVENT_LOGIC_V2_2_FREEZE.json`), 24/24 unit tests pass,
  `V2_2_NO_DEVELOPMENT_IMPROVEMENT` (accuracy) but selected for scale-robustness per
  packet Phase K instructions. Paris remains FAIL, attributed to perception (below).

### Perception status
`PERCEPTION_REOPEN_REQUIRED` for the current N0 (framewise-highest-confidence +
continuity) selection architecture at D3.1's conf=0.05 operating point — it is not safe
whenever true-target confidence is near threshold. Detector weights/threshold
themselves are NOT reopened (per packet scope); only the SELECTION step needs revision
(e.g. a static-object/no-motion plausibility filter, or ByteTrack with a track-quality
filter on displacement variance).

### Next required work (priority order)
1. **Perception selection repair**: add a plausibility gate that rejects candidates with
   near-zero motion variance over their lifetime (directly targets the demonstrated
   failure mode), or re-evaluate ByteTrack with such a filter (previously not tested).
2. **Re-run DEVELOPMENT Event Logic evaluation** with a materially larger surviving-dive
   count once (1) is done, including real HURDLE examples (zero survived this cycle).
3. **Re-test Paris** once (1) is done — the canary itself remains valid; its perception
   identity was the blocker, not Event Logic.
4. **Model-weight durability**: give D3/D3.1 weights a permanent, backed-up home (see
   Frozen references above) — currently one accidental scratchpad cleanup from being lost.
5. **Multi-domain D4**: still deferred (packet Phase P); DEVELOPMENT trajectory coverage
   issues found this cycle are a SELECTION problem, not primarily a data/domain problem,
   so D4 is not automatically indicated by these findings.

## Test suite

- `experiments/landmark_pilot/test_d3_pipeline.py` — 20 PASS, 16 SKIP (ephemeral Mac dataset files), 0 FAIL
- `experiments/landmark_pilot/test_d4_threshold_perception.py` — 35 PASS, 0 SKIP, 0 FAIL
- `experiments/landmark_pilot/test_event_logic_v2_1.py` — 36 PASS, 0 FAIL
- `experiments/landmark_pilot/test_event_logic_v2_2.py` — 24 PASS, 0 FAIL (new: scale-normalized
  velocity, zero/near-zero bbox-scale safeguard, preparation MAD/noise statistic,
  FPS invariance, hurdle-vs-final-takeoff, resolution/scale-invariance fixture,
  DEVELOPMENT/PARIS firewall)
- Combined: **115 PASS, 16 SKIP, 0 FAIL**

## AMP authority

`PINNED_STACK_MPS_AMP_INCOMPATIBILITY_OR_VERSION_SPECIFIC_BEHAVIOR`

Observed on the exact historical Ultralytics/PyTorch environment used for D2/D3 training.
All MPS retraining uses `amp=False`. Do NOT document as "AMP broken on all Apple Silicon."

## Current supervisor gate

`SUPERVISOR_REVIEW_AFTER_REAL_TRAJECTORY_EVENT_LOGIC_V2_2`
