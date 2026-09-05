# PROJECT_STATE.md - Dive Analyser / DiveSensei

Last verified: **2026-09-05**, after Temporal Landmark Pilot V1 complete (Phases A–T).
Latest audit: `docs/audits/FOUNDATION_HARDENING_AND_LAYER2_READINESS_2026-09-05.md`.
Layer-2 architecture: `docs/design/ANALYSIS_LAYER_2_ARCHITECTURE_V1.md`.
Pilot report: `docs/science/TEMPORAL_LANDMARK_REPORT_V1.md`.
Supervisor gate: `SUPERVISOR_REVIEW_AFTER_TEMPORAL_LANDMARK_PILOT_V1_COMPLETE`.

## Canonical Repository

Canonical source is `mcauchy@192.168.1.57:~/dive-analyser` on host `deb-serv`, branch
`uiux-overhaul-pro-app`. History was rewritten on 2026-09-05 to remove historical live DB
credential material and tracked `.env`. Current HEAD: verify with `git rev-parse HEAD`.

The Mac local workspace `/Users/maximecauchy/.perso/diveanalyzer` is not a Git repository
and is not source authority.

## Backup Authority

A sanitized off-host bare mirror exists on the Mac at
`/Users/Shared/services/data/diveanalyzer-source-backups/dive-analyser-2026-09-05.git`.
It is source-only, outside the deployed Mac-agent tree, mode 0700, and must have HEAD equal
to the canonical repository after each final commit.

## Runtime Topology

Debian server `192.168.1.57` runs Docker Compose: PostgreSQL 16, FastAPI backend,
React/Vite frontend image, nginx, and Adminer. Mac `192.168.1.19` runs launchd
`com.diveanalyzer.agent` from `/Users/Shared/services/data/diveanalyzer/`.

nginx is the LAN entrypoint: `http://192.168.1.57:6090` and `https://192.168.1.57:6443`.
Direct service bindings are loopback-only: Postgres `127.0.0.1:5433`, backend `127.0.0.1:6002`,
frontend `127.0.0.1:6001`, Adminer `127.0.0.1:8080`.

## Runtime Configuration Authority

Server runtime secrets live in `/home/mcauchy/dive-analyser/.env` (ignored by Git).
Contains: rotated PostgreSQL credential, Mac machine API key, CORS origins,
`ANALYSIS_ARTIFACT_ROOT=/app/analysis-artifacts`.

Mac runtime config: `/Users/Shared/services/data/diveanalyzer/state/config.yaml` (0600).

## Source Authorities

- backend: Git `backend/`; runtime bind-mounted `/app`; PASS.
- frontend: Git `frontend/`; deployed image must be rebuilt for application source changes.
- infra: Git `docker-compose.yml`, `nginx/`; nginx config is bind-mounted; PASS.
- Mac agent: Git `mac-agent/` plus deployed Mac code; reconciled 2026-09-05 (byte-parity).
- Analysis schema: `backend/migrations/add_analysis_layer2.sql` applied to production DB.
- Experiment code: `experiments/landmark_pilot/` (NOT in backend container; standalone only).

## Security Status

- DB credential rotation: PASS (from 2026-09-05 hardening).
- Git sanitization: PASS; `git fsck --strict` passed.
- Machine API auth: PASS.
- TLS: PASS for Mac agent (local CA, explicit trust).
- Layer-2 security: proxy-only processing, no bulk recall, no production bulk-enqueue,
  no credentials in experiment code.

## Current Analysis Capabilities

### Layer 1 (Production)

User-authored metadata + deterministic/statistical/heuristic backend logic: caption parsing,
DD lookup/provenance, session aggregates, two-phase self ratings, Personal Dive Value V1,
Journey/fear/plateau heuristics, media readiness, representative-media workflows.

### Layer 2 (Experimental — Research Phase)

**Temporal landmark extraction** implemented and piloted:

- Schema: 9 new tables (`analysis_runs`, `analysis_jobs`, `analysis_landmarks`,
  `analysis_phases`, `analysis_metrics`, `analysis_artifacts`, `analysis_comparisons`,
  `analysis_comparison_artifacts`, `analysis_comparison_metrics`) applied to production DB.
- API: `/api/v1/analysis/` routes (all return `experimental: true`).
- Metric registry: 11 metrics in `backend/app/data/metric_registry.yaml`.
- Artifact storage: `media/analysis-artifacts/<dive_id>/<run_uuid>/` (bind-mounted in Docker).
- Baseline A pipeline: MOG2 + vertical centroid → takeoff/apex/water_contact landmarks.
- Pilot corpus: 20 dives run; 12/20 APPLICABLE (60%), 8/20 UNCERTAIN (40%).
- Pairwise comparison: 66 pairs computed and stored.
- Annotation tool: `experiments/landmark_pilot/annotate.py` (web UI, port 8765).

**Temporal Landmark Pilot V1 COMPLETE.**

**Baseline A:** 0% within-tolerance on all 3 landmarks (all 20 dives). Architectural failure.
See docs/science/BASELINE_A_EVALUATION_V1.json + BASELINE_A_ERROR_TAXONOMY_V1.json.

**Baseline B (DIBT):** 5.6%/15.4%/5.3% within-tol (takeoff/apex/water_contact, all-20).
INTERNAL_EVAL: 16.7%/33.3%/0%. NOT ADOPTED — does not meet ≥50% production bar.
See docs/science/BASELINE_B_EVALUATION_V1.json + BASELINE_B_FREEZE_V1.json.

**Full pilot report:** `docs/science/TEMPORAL_LANDMARK_REPORT_V1.md`.

## Production Data Authority

PostgreSQL Docker volume is the production metadata authority.
Server `media/videos` holds legacy originals/stubs; `media/cache` holds derived renditions.
Mac Photos and `/Users/Shared/services/data/media-node/` remain authority for new originals.
`media/analysis-artifacts/` holds Layer-2 analysis outputs (excluded from Git).

## Layer-2 DB State (2026-09-05)

```
analysis_runs          20  (pilot; pipeline=temporal_landmarks_baseline_a_v1)
analysis_jobs          20  (all succeeded)
analysis_landmarks     60  (3 per run: 36 APPLICABLE, 24 UNCERTAIN)
analysis_phases        36  (3 per APPLICABLE run: flight_ascent, flight_descent, flight)
analysis_metrics      120  (10 per APPLICABLE run)
analysis_artifacts     20  (diagnostic.json per run)
analysis_comparisons   66  (pairwise, method=temporal_landmark_pairwise_v1)
analysis_comparison_metrics 264  (4 per comparison)
```

## Tests And Validation

- Pre-Layer-2 backend security/sync/media tests: 21 passed.
- Layer-2 schema invariants: verified manually (temporal ordering, UNCERTAIN → conf=0,
  NOT_APPLICABLE → NULL timestamps, unique metric constraint).
- Layer-2 unit/integration tests (Phase T): not yet written. TODO.

## Remaining Engineering Debt

1. Layer-2 test suite not yet written.
2. Baseline C not yet implemented (Baseline A+B both fail production bar).
3. Proxy-vs-original canary deferred (originals are iCloud-only; Phase G scientifically low priority at current error magnitudes).
4. Migration-system consolidation remains deferred.
5. DB role privileges remain broad; rotation preserved current architecture.
6. Browser/system trust for the local CA is not installed.
7. Frontend image should be rebuilt on next user-facing frontend source change.
8. Layer-2 temporal landmark results not yet surfaced in the web UI.

## Current Gate

`SUPERVISOR_REVIEW_AFTER_TEMPORAL_LANDMARK_PILOT_V1_COMPLETE`

**What the supervisor should review:**
1. Commission Baseline C: YOLO person detection + temporal priors (PyTorch 2.10 on server)
2. Write Layer-2 test suite (0 automated tests for Layer-2 logic currently)
3. Phase G: decide whether to recall iCloud originals for proxy-vs-original canary
4. Off-host backup: refresh Mac mirror after this commit
5. UI layer: decide when to surface temporal landmark results in the frontend
