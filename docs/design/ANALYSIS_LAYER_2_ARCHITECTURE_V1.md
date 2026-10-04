# Analysis Layer 2 — Architecture V1

> Status: **EXPERIMENTAL** — analysis layer is in active research/pilot phase.
> All API endpoints return `"experimental": true`.
> Last updated: 2026-09-05

---

## 1. Purpose

Layer 2 adds temporal video analysis on top of Layer 1 (metadata ingestion + DD/scoring).
The goal is to automatically extract dive-phase timing from 360p proxy clips, enabling:
- Phase-duration metrics (flight time, ascent/descent split, apex position)
- Athlete-vs-self temporal comparison
- Future: kinematic analysis, execution fault detection

Layer 2 is explicitly **research-grade**. It is not connected to any production scoring or
athlete feedback pathway.

---

## 2. High-Level Design

```
         Proxy clip (360p, server-side)
                  │
                  ▼
         AnalysisRun  ←── immutable scientific identity (spec_fingerprint)
                  │
                  ▼
         AnalysisJob  ←── execution orchestration (lease / heartbeat / retry)
                  │
          ┌───────┼──────────┐
          ▼       ▼          ▼
     Landmarks  Phases   Metrics   Artifacts
    (takeoff,   (flight,  (duration, (diagnostic
     apex,       ascent,   norms,     JSON, future
     water_      descent)  confidence) visualisations)
     contact)
          │
          ▼
    Comparisons  ←── pairwise alignment
    + ComparisonMetrics
```

---

## 3. Core Data Model

### 3.1 AnalysisRun

The central immutable scientific identity. Created once per (dive, media, pipeline,
parameters) combination; never mutated once created.

```
analysis_runs
  id                    PK
  dive_id               FK → dives.id
  media_key             sha256 of the proxy/original file
  input_checksum        sha256 of actual input bytes
  pipeline_key          e.g. "temporal_landmarks_baseline_a_v1"
  pipeline_version      e.g. "1.0.0"
  canonical_parameters  JSONB (frozen algorithm parameters)
  spec_fingerprint      CHAR(64) — SHA-256 of all above; unique WHERE active
  status                pending | running | succeeded | failed | cancelled | superseded
  created_at / completed_at
```

**Idempotence:** if `spec_fingerprint` already exists as an active run, `enqueue_analysis_run()`
returns the existing run without creating a new one.

### 3.2 AnalysisJob

Execution orchestration decoupled from scientific identity. Retries create new jobs but
preserve the same AnalysisRun provenance.

```
analysis_jobs
  id                    PK
  run_id                FK → analysis_runs.id
  status                pending | leased | running | succeeded | failed | cancelled
  worker_id
  lease_expires_at
  heartbeat_at
  attempt_number        starts at 1; increments on retry
  max_attempts          default 3
  error_message
  created_at / completed_at
```

**Lease semantics:**
1. `lease_analysis_job()` — atomically sets status='leased', sets lease_expires_at=now+5min
2. Worker calls `heartbeat_analysis_job()` every 60s to extend lease
3. `reclaim_expired_jobs()` resets expired-lease jobs to 'pending'
4. On failure: `fail_analysis_job()` creates a new pending job if attempts < max_attempts

### 3.3 AnalysisLandmark

A temporal event in a video clip.

```
analysis_landmarks
  id / run_id / landmark_key / frame_index / timestamp_seconds
  confidence            [0,1]
  applicability         APPLICABLE | NOT_APPLICABLE | UNCERTAIN
  source                AUTO | HUMAN | HUMAN_CORRECTED | IMPORTED
  algorithm_key / algorithm_version
  uncertainty_window_frames
```

**Invariants:**
- NOT_APPLICABLE → frame_index and timestamp_seconds must be NULL
- UNCERTAIN → confidence must be 0.0 and does NOT produce derived metrics
- Source=HUMAN overrides AUTO for the same landmark_key (stored as a new row; previous AUTO
  row is deleted by the annotation tool)

### 3.4 AnalysisPhase

Contiguous time interval between landmarks.

```
analysis_phases
  run_id / phase_key / start_landmark_key / end_landmark_key
  start_frame / end_frame / duration_seconds / frame_count
```

Populated phases: `flight_ascent` (takeoff→apex), `flight_descent` (apex→water_contact),
`flight` (takeoff→water_contact).

### 3.5 AnalysisMetric

```
analysis_metrics
  run_id / metric_key / metric_version
  value_numeric / value_text / value_json
  unit / confidence
  phase_key / producer_key / producer_version
```

Unique constraint: `(run_id, metric_key, metric_version)`.

### 3.6 AnalysisArtifact

File-backed artifact (JSON, video clip, visualization).

```
analysis_artifacts
  run_id / artifact_key / artifact_type
  file_path (relative to ANALYSIS_ARTIFACT_ROOT)
  file_size_bytes / checksum_sha256 / format
```

**Storage layout:**
```
media/analysis-artifacts/
  <dive_id>/
    <run_uuid>/
      <artifact_key>.<ext>
      manifest.json
  _tmp/
    <run_uuid>/    ← write here first, then atomically move
```

### 3.7 AnalysisComparison + ComparisonMetrics

Pairwise comparison between two runs.

```
analysis_comparisons
  comparison_uuid / target_run_id / reference_run_id
  method_key / method_version / canonical_parameters
  spec_fingerprint (unique WHERE status IN pending/running/succeeded)
  status / completed_at

analysis_comparison_metrics
  comparison_id / metric_key / value_numeric / metric_version
```

---

## 4. Pipeline Architecture

### 4.1 Fixture Pipeline

`pipeline_key = "fixture_deterministic_v1"`

Deterministic test pipeline. Reads clip duration, emits one test metric, writes
`diagnostic.json`. For integration testing only; not scientific.

### 4.2 Baseline A Pipeline

`pipeline_key = "temporal_landmarks_baseline_a_v1"`

Temporal landmark extraction via motion energy analysis.

**Algorithm (`baseline_a_motion_centroid` v1.0.0):**
1. Open proxy clip with OpenCV VideoCapture
2. MOG2 background subtractor (detectShadows=False, history=120)
3. For each frame (FRAME_STEP=4): compute foreground mask → centroid_y, foreground_area
4. Gaussian smooth centroid trajectory (sigma=3.0)
5. Takeoff: frame of maximum upward velocity (max negative Δcentroid_y in first 70% of clip)
6. Apex: frame of minimum centroid_y (topmost position, after takeoff, before 90%)
7. Water contact: first frame of foreground area > median_area × 1.5, after apex
8. If ordering violated (T≥A or A≥W): all landmarks marked UNCERTAIN, confidence=0.0

**Execution environment:**
- Runs outside Docker container (container lacks cv2)
- Uses `experiments/landmark_pilot/venv/` (Python 3.11)
- Connects directly to PostgreSQL at localhost:5433 via psycopg2
- Invoked via `run_pilot_standalone.py` (not the backend API job queue for now)

**Why outside Docker:**
The backend container does not include OpenCV. The experiment venv is intentionally isolated
to keep heavy CV dependencies out of the production backend image. In a future productionized
state, a dedicated analysis container (or sidecar) would host the CV dependencies.

### 4.3 Baseline B (Planned)

Will address Baseline A failure modes:
- Longer background subtractor warmup
- Dual-signal water entry (area jump + centroid low-threshold)
- Adaptive frame step for short clips

---

## 5. API Surface

All routes are under `/api/v1/analysis/` and return `"experimental": true`.

| Method | Route | Description |
|--------|-------|-------------|
| POST | `/analysis/runs/enqueue` | Create or retrieve an AnalysisRun + AnalysisJob |
| GET  | `/analysis/runs/{run_uuid}` | Get run status, landmarks, metrics |
| POST | `/analysis/runs/lease` | Lease the next pending job |
| POST | `/analysis/jobs/{job_id}/heartbeat` | Extend lease |
| POST | `/analysis/jobs/{job_id}/succeed` | Mark job succeeded |
| POST | `/analysis/jobs/{job_id}/fail` | Mark job failed (triggers retry if attempts remain) |
| GET  | `/analysis/metrics/registry` | List metric registry definitions |
| POST | `/analysis/comparisons` | Create a pairwise comparison |
| GET  | `/analysis/comparisons/{comparison_uuid}` | Get comparison results |

---

## 6. Metric Registry

Defined in `backend/app/data/metric_registry.yaml`. Loaded by
`backend/app/services/metric_registry.py` (LRU-cached, Git-versioned).

11 metrics defined (10 per-run, 1 comparison):
- `flight_duration_seconds`, `ascent_duration_seconds`, `descent_duration_seconds`
- `takeoff_frame_normalized`, `apex_frame_normalized`, `water_contact_frame_normalized`
- `landmark_proposer_confidence_takeoff/apex/water_contact`
- `ascent_fraction`
- `flight_duration_delta_seconds` (comparison metric)

---

## 7. Experiment Isolation

```
experiments/landmark_pilot/
  venv/                         ← Python 3.11 + cv2, numpy, scipy, sqlalchemy, psycopg2
  proposer_baseline_a.py        ← Landmark proposal algorithm
  run_pilot_standalone.py       ← Standalone pilot runner (no Docker dependency)
  compare_pilot.py              ← Pairwise comparison prototype
  annotate.py                   ← Web annotation tool (port 8765)
```

**Key invariants:**
- Experiment code never imports from `backend/app/`
- Backend pipeline module (`analysis_pipeline_landmark_a.py`) loads proposer via importlib
  by resolving `experiments/landmark_pilot/proposer_baseline_a.py` at runtime — no package dependency
- All experiment outputs (venv, data artefacts) excluded from Git via `.gitignore`

---

## 8. Security Constraints

| Constraint | Implementation |
|---|---|
| No bulk recall of originals | Proxy-only processing enforced; originals excluded from pipeline |
| Canary ≤ 6 dives | `proxy_canary_dives` list in PILOT_MANIFEST_V1.json; manual invocation only |
| No processing > 24 dives | `--max-dives` flag enforced in run_pilot_standalone.py |
| No production bulk-enqueue | No scheduled job; standalone runner only |
| No media in Git | `.gitignore` covers `media/`, `analysis-artifacts/`, `experiments/*/venv` |
| No credentials in Git | DB password in `.env` only; all code reads from env or `.env` file |
| No experiment megablobs | Only diagnostic.json per run stored; raw frame arrays never persisted |
| No repurposing holdout data | Holdout subset not in PILOT_MANIFEST_V1.json |
| Off-host backup after commit | Phase V: bare mirror at Mac `/Users/Shared/services/data/diveanalyzer-source-backups/` |

---

## 9. Known Limitations

1. **Baseline A failure rate 40%** on this pilot corpus. Unsuitable for production use.
   Requires Baseline B or human annotation before any statistical conclusions.
2. **Proxy only**: landmark positions on 360p proxy may drift vs original-resolution.
   Proxy canary (Phase P) will quantify this drift; results pending.
3. **No backend execution path**: Landmark A pipeline runs standalone (not via backend
   `/analysis/runs/lease` API) because the backend container lacks cv2. This is a temporary
   research architecture; productionization requires a dedicated CV container.
4. **No scoring gate**: UNCERTAIN landmarks are stored but silently excluded from metric
   computation. A failed dive has 0 metrics, not an error metric. Downstream must handle NULL.
5. **Single-threaded annotation tool**: `annotate.py` uses `http.server.HTTPServer` (single-
   threaded). Fine for single-user research; not suitable for concurrent use.

---

## 10. File Index

| File | Role |
|------|------|
| `backend/migrations/add_analysis_layer2.sql` | Schema (analysis_runs, analysis_jobs, landmarks, phases, metrics, artifacts, comparisons) |
| `backend/app/models/analysis.py` | SQLAlchemy ORM models |
| `backend/app/services/analysis_jobs.py` | Lease/heartbeat/retry service |
| `backend/app/services/analysis_artifacts.py` | Artifact storage service |
| `backend/app/services/metric_registry.py` | Metric registry loader |
| `backend/app/services/analysis_pipeline_fixture.py` | Deterministic test pipeline |
| `backend/app/services/analysis_pipeline_landmark_a.py` | Baseline A backend shim |
| `backend/app/api/v1/analysis.py` | REST API routes |
| `backend/app/data/metric_registry.yaml` | Git-versioned metric definitions |
| `experiments/landmark_pilot/proposer_baseline_a.py` | Baseline A algorithm |
| `experiments/landmark_pilot/run_pilot_standalone.py` | Standalone pilot runner |
| `experiments/landmark_pilot/compare_pilot.py` | Pairwise comparison prototype |
| `experiments/landmark_pilot/annotate.py` | Web annotation tool |
| `docs/science/TEMPORAL_LANDMARK_PILOT_PROTOCOL_V1.md` | Scientific protocol |
| `docs/science/PILOT_MANIFEST_V1.json` | 20-dive pilot corpus definition |
| `docs/science/PILOT_LANDMARK_PROPOSALS.json` | Pilot run output report |
| `docs/science/TEMPORAL_LANDMARK_PILOT_V1_REPORT.md` | This pilot results report |
| `media/analysis-artifacts/` | Artifact storage root (excluded from Git) |
