-- Layer 2 Analysis Foundation
-- Adds analysis_runs, analysis_jobs, analysis_landmarks, analysis_phases,
-- analysis_metrics, analysis_artifacts, analysis_comparisons and their
-- associated output tables.
--
-- Design principles:
--   • AnalysisRun is the immutable scientific execution identity.
--   • AnalysisJob handles execution orchestration (retry/lease/heartbeat).
--   • A retry never destroys provenance — old run rows are preserved.
--   • spec_fingerprint enforces idempotence: same input+pipeline+params → same run.
--   • Landmarks, phases, metrics and artifacts all attach to a run.
--   • Comparisons are first-class outputs referencing two runs.

-- ---------------------------------------------------------------------------
-- analysis_runs
-- One record = one exact analysis specification applied to one exact media
-- input for one dive.  Captures full provenance for reproducibility.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analysis_runs (
    id                      SERIAL PRIMARY KEY,
    run_uuid                UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,

    -- Scientific subject
    dive_id                 INTEGER NOT NULL REFERENCES dives(id) ON DELETE RESTRICT,
    photos_asset_id         INTEGER REFERENCES photos_assets(id) ON DELETE RESTRICT,

    -- Exact media identity used
    media_key               CHAR(64),          -- FK-equivalent to media_cache_entries.media_key
    media_role              VARCHAR(30),        -- e.g. 'proxy_360p', 'proxy_720p', 'original'
    input_checksum_sha256   CHAR(64),           -- checksum of the actual bytes consumed

    -- Pipeline specification
    pipeline_key            VARCHAR(100) NOT NULL,
    pipeline_version        VARCHAR(40)  NOT NULL,
    canonical_parameters    JSONB        NOT NULL DEFAULT '{}',

    -- Idempotence key: hash(dive_id + media identity + pipeline_key + pipeline_version + canonical_parameters)
    -- Two byte-equivalent analysis requests share this key.
    spec_fingerprint        CHAR(64)     NOT NULL,

    -- Execution status
    status                  VARCHAR(30)  NOT NULL DEFAULT 'pending',
    -- pending | running | succeeded | failed | cancelled | superseded

    forced                  BOOLEAN      NOT NULL DEFAULT false,
    -- When true this run was explicitly forced despite a matching live run existing.

    -- Timestamps
    created_at              TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at              TIMESTAMP,
    completed_at            TIMESTAMP,

    -- Provenance
    implementation_version  VARCHAR(100),
    environment_meta        JSONB,
    -- e.g. {"python": "3.11.9", "opencv": "4.9.0", "host": "deb-serv", "commit": "abc123"}

    error_summary           TEXT
);

CREATE INDEX IF NOT EXISTS ix_analysis_runs_dive_id
    ON analysis_runs(dive_id);
CREATE INDEX IF NOT EXISTS ix_analysis_runs_status
    ON analysis_runs(status);
CREATE INDEX IF NOT EXISTS ix_analysis_runs_pipeline
    ON analysis_runs(pipeline_key, pipeline_version);
CREATE INDEX IF NOT EXISTS ix_analysis_runs_created
    ON analysis_runs(created_at);

-- Idempotence guard: at most one live (non-terminal) run per spec.
-- A 'pending' or 'running' run with a given fingerprint blocks duplicate enqueues.
-- Terminal runs (failed/cancelled/superseded) are excluded so retries are allowed.
CREATE UNIQUE INDEX IF NOT EXISTS uq_analysis_runs_active_fingerprint
    ON analysis_runs(spec_fingerprint)
    WHERE status NOT IN ('failed', 'cancelled', 'superseded');

-- ---------------------------------------------------------------------------
-- analysis_jobs
-- Execution orchestration separate from scientific identity.
-- A failed run may spawn a new job (retry) without destroying the run row.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analysis_jobs (
    id                  SERIAL PRIMARY KEY,
    run_id              INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,

    status              VARCHAR(40) NOT NULL DEFAULT 'pending',
    -- pending | leased | running | succeeded | failed | abandoned

    attempt             INTEGER NOT NULL DEFAULT 1,
    max_attempts        INTEGER NOT NULL DEFAULT 3,

    -- Lease fields (mirrors media_jobs pattern)
    claimed_by          VARCHAR(100),
    claimed_at          TIMESTAMP,
    claimed_until       TIMESTAMP,
    last_heartbeat_at   TIMESTAMP,

    last_error          TEXT,

    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_analysis_jobs_run_id
    ON analysis_jobs(run_id);
CREATE INDEX IF NOT EXISTS ix_analysis_jobs_status
    ON analysis_jobs(status);
CREATE INDEX IF NOT EXISTS ix_analysis_jobs_claimed_until
    ON analysis_jobs(claimed_until);

-- Prevent two active jobs for the same run simultaneously.
CREATE UNIQUE INDEX IF NOT EXISTS uq_analysis_jobs_active_run
    ON analysis_jobs(run_id)
    WHERE status IN ('pending', 'leased', 'running');

-- ---------------------------------------------------------------------------
-- analysis_landmarks
-- Temporal point events within a dive clip.
-- source distinguishes automatic proposals from human ground truth.
-- applicability handles landmarks that do not apply to a given dive type.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analysis_landmarks (
    id                      SERIAL PRIMARY KEY,
    run_id                  INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,

    landmark_key            VARCHAR(60) NOT NULL,
    -- e.g. 'takeoff', 'apex', 'water_contact', 'board_depression', 'hurdle'

    -- Temporal location (both stored; frame is canonical when fps is known)
    frame_index             INTEGER,
    timestamp_seconds       NUMERIC,

    confidence              NUMERIC CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    -- 0.0–1.0; NULL when not computed

    source                  VARCHAR(30) NOT NULL DEFAULT 'AUTO'
                            CHECK (source IN ('AUTO', 'HUMAN', 'HUMAN_CORRECTED', 'IMPORTED')),

    applicability           VARCHAR(30) NOT NULL DEFAULT 'APPLICABLE'
                            CHECK (applicability IN ('APPLICABLE', 'NOT_APPLICABLE', 'UNCERTAIN')),
    -- NOT_APPLICABLE: landmark is semantically undefined for this dive type.
    -- No frame/time is stored when NOT_APPLICABLE.

    algorithm_key           VARCHAR(100),
    algorithm_version       VARCHAR(40),

    uncertainty_window_frames INTEGER,
    -- ±N frames; NULL when not computed

    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (run_id, landmark_key)
);

CREATE INDEX IF NOT EXISTS ix_analysis_landmarks_run_id
    ON analysis_landmarks(run_id);
CREATE INDEX IF NOT EXISTS ix_analysis_landmarks_key
    ON analysis_landmarks(landmark_key);

-- ---------------------------------------------------------------------------
-- analysis_phases
-- Named intervals between temporal boundaries.
-- Start/end may reference landmark keys or explicit frame/time values.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analysis_phases (
    id                  SERIAL PRIMARY KEY,
    run_id              INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,

    phase_key           VARCHAR(60) NOT NULL,
    -- e.g. 'pre_takeoff', 'flight_ascent', 'flight_descent', 'entry'
    -- or coarser: 'takeoff', 'flight', 'entry'

    -- Boundary references (landmark-derived preferred)
    start_landmark_key  VARCHAR(60),
    end_landmark_key    VARCHAR(60),

    -- Explicit frame/time fallback when boundaries are not landmark-derived
    start_frame         INTEGER,
    end_frame           INTEGER,
    start_seconds       NUMERIC,
    end_seconds         NUMERIC,

    source              VARCHAR(30) NOT NULL DEFAULT 'AUTO',
    confidence          NUMERIC,

    algorithm_key       VARCHAR(100),
    algorithm_version   VARCHAR(40),

    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (run_id, phase_key)
);

CREATE INDEX IF NOT EXISTS ix_analysis_phases_run_id
    ON analysis_phases(run_id);

-- ---------------------------------------------------------------------------
-- analysis_metrics
-- Scalar or compact structured quantitative results.
-- Each row is one metric produced by one run.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analysis_metrics (
    id               SERIAL PRIMARY KEY,
    run_id           INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,

    metric_key       VARCHAR(100) NOT NULL,
    -- Stable key referencing the metric registry (e.g. 'flight_duration_s')
    metric_version   VARCHAR(20)  NOT NULL DEFAULT 'v1',

    -- Value slots — exactly one should be populated
    value_numeric    NUMERIC,
    value_text       TEXT,
    value_json       JSONB,

    unit             VARCHAR(40),
    confidence       NUMERIC,
    phase_key        VARCHAR(60),    -- phase this metric belongs to, if applicable

    producer_key     VARCHAR(100),
    producer_version VARCHAR(40),

    created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_analysis_metrics_run_id
    ON analysis_metrics(run_id);
CREATE INDEX IF NOT EXISTS ix_analysis_metrics_key
    ON analysis_metrics(metric_key);

-- ---------------------------------------------------------------------------
-- analysis_artifacts
-- Large / file-like outputs stored on the local filesystem.
-- DB row holds metadata only; actual bytes live under ANALYSIS_ARTIFACT_ROOT.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analysis_artifacts (
    id               SERIAL PRIMARY KEY,
    run_id           INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,

    artifact_key     VARCHAR(100) NOT NULL,
    -- e.g. 'frame_strip', 'timeline_svg', 'centroid_trajectory_json'

    artifact_type    VARCHAR(60)  NOT NULL,
    -- e.g. 'diagnostic_json', 'frame_strip', 'timeline_svg',
    --      'trajectory_series', 'overlay_video', 'alignment_map'

    -- Storage
    storage_path     TEXT         NOT NULL,   -- path relative to ANALYSIS_ARTIFACT_ROOT
    checksum_sha256  CHAR(64),
    size_bytes       BIGINT,
    format           VARCHAR(40),              -- e.g. 'png', 'svg', 'json', 'mp4'

    status           VARCHAR(30)  NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'writing', 'ready', 'failed')),
    -- Artifacts in 'pending'/'writing' must not be served.

    is_debug         BOOLEAN      NOT NULL DEFAULT false,
    -- Debug artifacts may be cleaned up aggressively; canonical results are false.

    producer_key     VARCHAR(100),
    producer_version VARCHAR(40),

    created_at       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (run_id, artifact_key)
);

CREATE INDEX IF NOT EXISTS ix_analysis_artifacts_run_id
    ON analysis_artifacts(run_id);
CREATE INDEX IF NOT EXISTS ix_analysis_artifacts_status
    ON analysis_artifacts(status);

-- ---------------------------------------------------------------------------
-- analysis_comparisons
-- First-class pairwise comparison between a target and reference run.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analysis_comparisons (
    id                   SERIAL PRIMARY KEY,
    comparison_uuid      UUID        NOT NULL DEFAULT gen_random_uuid() UNIQUE,

    target_run_id        INTEGER     NOT NULL REFERENCES analysis_runs(id) ON DELETE RESTRICT,
    reference_run_id     INTEGER     NOT NULL REFERENCES analysis_runs(id) ON DELETE RESTRICT,

    method_key           VARCHAR(100) NOT NULL,
    method_version       VARCHAR(40)  NOT NULL,
    canonical_parameters JSONB        NOT NULL DEFAULT '{}',
    spec_fingerprint     CHAR(64)     NOT NULL,

    status               VARCHAR(30)  NOT NULL DEFAULT 'pending',
    -- pending | running | succeeded | failed

    created_at           TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at         TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_analysis_comparisons_target
    ON analysis_comparisons(target_run_id);
CREATE INDEX IF NOT EXISTS ix_analysis_comparisons_reference
    ON analysis_comparisons(reference_run_id);
CREATE INDEX IF NOT EXISTS ix_analysis_comparisons_status
    ON analysis_comparisons(status);

-- ---------------------------------------------------------------------------
-- analysis_comparison_artifacts
-- Artifacts produced as outputs of a comparison (e.g. alignment_map).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analysis_comparison_artifacts (
    id              SERIAL PRIMARY KEY,
    comparison_id   INTEGER     NOT NULL REFERENCES analysis_comparisons(id) ON DELETE CASCADE,

    artifact_key    VARCHAR(100) NOT NULL,
    artifact_type   VARCHAR(60)  NOT NULL,
    storage_path    TEXT         NOT NULL,
    checksum_sha256 CHAR(64),
    size_bytes      BIGINT,
    format          VARCHAR(40),
    status          VARCHAR(30)  NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'writing', 'ready', 'failed')),

    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (comparison_id, artifact_key)
);

CREATE INDEX IF NOT EXISTS ix_analysis_comparison_artifacts_cmp
    ON analysis_comparison_artifacts(comparison_id);

-- ---------------------------------------------------------------------------
-- analysis_comparison_metrics
-- Scalar difference metrics produced by a comparison.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analysis_comparison_metrics (
    id              SERIAL PRIMARY KEY,
    comparison_id   INTEGER     NOT NULL REFERENCES analysis_comparisons(id) ON DELETE CASCADE,

    metric_key      VARCHAR(100) NOT NULL,
    metric_version  VARCHAR(20)  NOT NULL DEFAULT 'v1',
    value_numeric   NUMERIC,
    value_text      TEXT,
    value_json      JSONB,
    unit            VARCHAR(40),
    phase_key       VARCHAR(60),

    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (comparison_id, metric_key)
);

CREATE INDEX IF NOT EXISTS ix_analysis_comparison_metrics_cmp
    ON analysis_comparison_metrics(comparison_id);

-- ---------------------------------------------------------------------------
-- Additional CHECK: NOT_APPLICABLE landmarks must not have a timestamp/frame.
-- Added as a separate ALTER to keep the landmark table definition readable.
-- ---------------------------------------------------------------------------
ALTER TABLE analysis_landmarks
    ADD CONSTRAINT IF NOT EXISTS chk_not_applicable_no_timestamp
    CHECK (
        applicability != 'NOT_APPLICABLE'
        OR (frame_index IS NULL AND timestamp_seconds IS NULL)
    );

-- ---------------------------------------------------------------------------
-- Comparison idempotence: one active comparison per spec fingerprint.
-- ---------------------------------------------------------------------------
CREATE UNIQUE INDEX IF NOT EXISTS uq_analysis_comparison_spec_active
    ON analysis_comparisons(spec_fingerprint)
    WHERE status IN ('pending', 'running', 'succeeded');

-- ---------------------------------------------------------------------------
-- Migration log entry
-- ---------------------------------------------------------------------------
INSERT INTO migration_logs (migration_name, applied_at)
SELECT 'add_analysis_layer2', CURRENT_TIMESTAMP
WHERE NOT EXISTS (
    SELECT 1 FROM migration_logs WHERE migration_name = 'add_analysis_layer2'
);
