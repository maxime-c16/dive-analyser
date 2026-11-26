-- Session clip auto-detection runs, fast triage candidates, and Ground Truth.
-- Apply BEFORE deploying the backend that uses these tables. Additive and
-- idempotent; the previous backend ignores these tables.
-- Requires add_session_videos.sql (session_videos), divers, photos_assets, dives.
BEGIN;

CREATE TABLE IF NOT EXISTS session_clip_runs (
    id SERIAL PRIMARY KEY,
    session_video_id INTEGER NOT NULL REFERENCES session_videos(id) ON DELETE CASCADE,
    detector_name VARCHAR(80) NOT NULL,
    detector_version VARCHAR(80) NOT NULL,
    params_json JSONB,
    submitted_by_user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
    submitted_count INTEGER NOT NULL DEFAULT 0,
    created_count INTEGER NOT NULL DEFAULT 0,
    deduped_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_session_clip_runs_video
    ON session_clip_runs (session_video_id, created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS session_clip_candidates (
    id SERIAL PRIMARY KEY,
    session_video_id INTEGER NOT NULL REFERENCES session_videos(id) ON DELETE CASCADE,
    first_run_id INTEGER REFERENCES session_clip_runs(id) ON DELETE SET NULL,
    latest_run_id INTEGER REFERENCES session_clip_runs(id) ON DELETE SET NULL,
    start_s DOUBLE PRECISION NOT NULL,
    end_s DOUBLE PRECISION NOT NULL,
    trimmed_start_s DOUBLE PRECISION,
    trimmed_end_s DOUBLE PRECISION,
    confidence DOUBLE PRECISION,
    detector_label VARCHAR(80),
    detector_meta JSONB,

    triage_status VARCHAR(16) NOT NULL DEFAULT 'pending',
    reject_reason VARCHAR(32),
    triaged_by_user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
    triaged_at TIMESTAMP,
    skipped_at TIMESTAMP,

    diver_id INTEGER REFERENCES divers(id) ON DELETE SET NULL,
    dive_code VARCHAR(10),
    height VARCHAR(5),
    performance VARCHAR(1),
    phase1_performance VARCHAR(1),
    phase2_performance VARCHAR(1),
    notes TEXT,
    visibility VARCHAR(10) NOT NULL DEFAULT 'private',

    extraction_status VARCHAR(20) NOT NULL DEFAULT 'none',
    cut_revision INTEGER NOT NULL DEFAULT 1,
    lease_token VARCHAR(36),
    claimed_by VARCHAR(100),
    claimed_at TIMESTAMP,
    claimed_until TIMESTAMP,
    extraction_attempts INTEGER NOT NULL DEFAULT 0,
    extraction_error VARCHAR(240),
    clip_video_uuid VARCHAR(100) UNIQUE,
    photos_asset_id INTEGER REFERENCES photos_assets(id) ON DELETE SET NULL,
    dive_id INTEGER REFERENCES dives(id) ON DELETE SET NULL,
    publish_requested_at TIMESTAMP,
    publish_requested_by_user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
    published_at TIMESTAMP,
    source_etag VARCHAR(80),

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT ck_session_clip_bounds CHECK (start_s >= 0 AND end_s > start_s),
    CONSTRAINT ck_session_clip_trimmed_bounds CHECK (
        (trimmed_start_s IS NULL AND trimmed_end_s IS NULL)
        OR (trimmed_start_s IS NOT NULL AND trimmed_end_s IS NOT NULL AND trimmed_start_s >= 0 AND trimmed_end_s > trimmed_start_s)
    ),
    CONSTRAINT ck_session_clip_triage_status CHECK (triage_status IN ('pending', 'kept', 'rejected')),
    CONSTRAINT ck_session_clip_extraction_status CHECK (
        extraction_status IN ('none', 'queued', 'claimed', 'extracting', 'ready', 'published', 'failed')
    ),
    CONSTRAINT ck_session_clip_visibility CHECK (visibility IN ('private', 'public'))
);
CREATE INDEX IF NOT EXISTS ix_session_clip_candidates_queue
    ON session_clip_candidates (triage_status, skipped_at, id);
CREATE INDEX IF NOT EXISTS ix_session_clip_candidates_video
    ON session_clip_candidates (session_video_id, triage_status, start_s);
CREATE INDEX IF NOT EXISTS ix_session_clip_candidates_bounds
    ON session_clip_candidates (session_video_id, start_s, end_s);
CREATE INDEX IF NOT EXISTS ix_session_clip_candidates_trimmed
    ON session_clip_candidates (session_video_id, trimmed_start_s, trimmed_end_s)
    WHERE trimmed_start_s IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_session_clip_candidates_extract
    ON session_clip_candidates (extraction_status, claimed_until, id);

CREATE TABLE IF NOT EXISTS session_clip_run_matches (
    id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES session_clip_runs(id) ON DELETE CASCADE,
    candidate_id INTEGER NOT NULL REFERENCES session_clip_candidates(id) ON DELETE CASCADE,
    raw_start_s DOUBLE PRECISION NOT NULL,
    raw_end_s DOUBLE PRECISION NOT NULL,
    confidence DOUBLE PRECISION,
    was_new BOOLEAN NOT NULL DEFAULT FALSE,
    overlap_iou DOUBLE PRECISION,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_session_clip_run_match UNIQUE (run_id, candidate_id)
);
CREATE INDEX IF NOT EXISTS ix_session_clip_run_matches_run
    ON session_clip_run_matches (run_id);
CREATE INDEX IF NOT EXISTS ix_session_clip_run_matches_candidate
    ON session_clip_run_matches (candidate_id);

CREATE TABLE IF NOT EXISTS session_clip_orphan_objects (
    id SERIAL PRIMARY KEY,
    bucket VARCHAR(120) NOT NULL,
    object_key VARCHAR(200) NOT NULL,
    blob_sha256 VARCHAR(64) NOT NULL,
    byte_size BIGINT NOT NULL DEFAULT 0,
    candidate_id INTEGER REFERENCES session_clip_candidates(id) ON DELETE SET NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    eligible_after TIMESTAMP NOT NULL,
    reclaimed_at TIMESTAMP,
    last_error VARCHAR(240),
    CONSTRAINT uq_session_clip_orphan_key UNIQUE (bucket, object_key),
    CONSTRAINT ck_session_clip_orphan_status CHECK (status IN ('pending', 'deleting', 'reclaimed', 'retained'))
);
CREATE INDEX IF NOT EXISTS ix_session_clip_orphan_due
    ON session_clip_orphan_objects (status, eligible_after, id);

COMMIT;
-- Rollback (destroys clip detection runs and triage records; published dives stay):
-- DROP TABLE session_clip_orphan_objects, session_clip_run_matches, session_clip_candidates, session_clip_runs;
