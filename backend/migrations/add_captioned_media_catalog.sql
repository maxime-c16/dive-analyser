BEGIN;

CREATE TABLE IF NOT EXISTS media_catalog_runs (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(100) NOT NULL REFERENCES media_agents(id) ON DELETE CASCADE,
    status VARCHAR(30) NOT NULL DEFAULT 'requested',
    catalog_revision INTEGER NOT NULL,
    checkpoint INTEGER NOT NULL DEFAULT 0,
    observed_count INTEGER NOT NULL DEFAULT 0,
    eligible_count INTEGER NOT NULL DEFAULT 0,
    excluded_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    photos_library_bytes_start BIGINT,
    photos_library_bytes_end BIGINT,
    free_bytes_start BIGINT,
    free_bytes_end BIGINT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    paused_at TIMESTAMP,
    pause_reason VARCHAR(100),
    last_error TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_media_catalog_runs_status ON media_catalog_runs(status);
CREATE INDEX IF NOT EXISTS ix_media_catalog_runs_revision ON media_catalog_runs(catalog_revision);

CREATE TABLE IF NOT EXISTS captioned_media_catalog (
    id SERIAL PRIMARY KEY,
    canonical_video_uuid VARCHAR(100),
    agent_id VARCHAR(100) NOT NULL REFERENCES media_agents(id) ON DELETE CASCADE,
    agent_local_uuid VARCHAR(100) NOT NULL,
    cloud_fingerprint VARCHAR(100),
    photos_asset_id INTEGER REFERENCES photos_assets(id) ON DELETE SET NULL,
    dive_id INTEGER REFERENCES dives(id) ON DELETE SET NULL,
    raw_caption TEXT NOT NULL,
    canonical_dive_code VARCHAR(10),
    captured_at TIMESTAMP,
    duration_seconds NUMERIC,
    width INTEGER,
    height INTEGER,
    estimated_source_bytes BIGINT,
    photos_local_state VARCHAR(40) NOT NULL DEFAULT 'unknown',
    media_state VARCHAR(40) NOT NULL DEFAULT 'missing',
    poster_state VARCHAR(40) NOT NULL DEFAULT 'missing',
    proxy_state VARCHAR(40) NOT NULL DEFAULT 'missing',
    source_state VARCHAR(40) NOT NULL DEFAULT 'missing',
    representative_role VARCHAR(20),
    eligibility VARCHAR(30) NOT NULL DEFAULT 'excluded',
    exclusion_code VARCHAR(60),
    last_cataloged_at TIMESTAMP NOT NULL DEFAULT now(),
    last_media_attempt_at TIMESTAMP,
    last_media_success_at TIMESTAMP,
    last_error_code VARCHAR(100),
    catalog_revision INTEGER NOT NULL DEFAULT 1,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_captioned_catalog_agent_local_unique ON captioned_media_catalog(agent_id, agent_local_uuid);
CREATE INDEX IF NOT EXISTS ix_captioned_catalog_cloud ON captioned_media_catalog(cloud_fingerprint);
CREATE INDEX IF NOT EXISTS ix_captioned_catalog_asset ON captioned_media_catalog(photos_asset_id);
CREATE INDEX IF NOT EXISTS ix_captioned_catalog_dive ON captioned_media_catalog(dive_id);
CREATE INDEX IF NOT EXISTS ix_captioned_catalog_revision_eligibility ON captioned_media_catalog(catalog_revision, eligibility);
CREATE INDEX IF NOT EXISTS ix_captioned_catalog_exclusion ON captioned_media_catalog(exclusion_code);

CREATE TABLE IF NOT EXISTS media_catalog_population_runs (
    id SERIAL PRIMARY KEY,
    catalog_revision INTEGER NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'planned',
    scope VARCHAR(60) NOT NULL DEFAULT 'all_eligible_captioned',
    stage INTEGER NOT NULL DEFAULT 1,
    total_items INTEGER NOT NULL DEFAULT 0,
    completed_items INTEGER NOT NULL DEFAULT 0,
    ready_items INTEGER NOT NULL DEFAULT 0,
    partial_items INTEGER NOT NULL DEFAULT 0,
    unavailable_items INTEGER NOT NULL DEFAULT 0,
    skipped_items INTEGER NOT NULL DEFAULT 0,
    current_item_id INTEGER,
    plan_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMP,
    paused_at TIMESTAMP,
    completed_at TIMESTAMP,
    pause_reason VARCHAR(100),
    last_error TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_catalog_population_runs_status ON media_catalog_population_runs(status);

CREATE TABLE IF NOT EXISTS media_catalog_population_items (
    id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES media_catalog_population_runs(id) ON DELETE CASCADE,
    catalog_item_id INTEGER NOT NULL REFERENCES captioned_media_catalog(id) ON DELETE CASCADE,
    priority INTEGER NOT NULL,
    priority_class VARCHAR(10) NOT NULL,
    status VARCHAR(40) NOT NULL DEFAULT 'planned',
    poster_status VARCHAR(30) NOT NULL DEFAULT 'missing',
    proxy_status VARCHAR(30) NOT NULL DEFAULT 'missing',
    source_status VARCHAR(30) NOT NULL DEFAULT 'missing',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    poster_job_id INTEGER REFERENCES media_jobs(id),
    proxy_job_id INTEGER REFERENCES media_jobs(id),
    last_error_code VARCHAR(100),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_catalog_population_run_item_unique ON media_catalog_population_items(run_id, catalog_item_id);
CREATE INDEX IF NOT EXISTS ix_catalog_population_run_priority ON media_catalog_population_items(run_id, priority, id);

COMMIT;
