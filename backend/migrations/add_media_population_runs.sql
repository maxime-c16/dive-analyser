-- Durable audit records for bounded representative media population runs.
-- Additive and safe to run on production before any population pass.

CREATE TABLE IF NOT EXISTS media_population_runs (
    id SERIAL PRIMARY KEY,
    population_type VARCHAR(60) NOT NULL DEFAULT 'representative_manifest',
    tier INTEGER NOT NULL DEFAULT 1,
    status VARCHAR(30) NOT NULL DEFAULT 'planned',
    requested_renditions JSON NOT NULL,
    manifest_snapshot JSON NOT NULL,
    total_items INTEGER NOT NULL DEFAULT 0,
    total_jobs INTEGER NOT NULL DEFAULT 0,
    ready_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    unavailable_count INTEGER NOT NULL DEFAULT 0,
    skipped_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    started_at TIMESTAMP NULL,
    completed_at TIMESTAMP NULL,
    last_error TEXT NULL
);

CREATE INDEX IF NOT EXISTS ix_media_population_runs_population_type
    ON media_population_runs (population_type);
CREATE INDEX IF NOT EXISTS ix_media_population_runs_tier
    ON media_population_runs (tier);
CREATE INDEX IF NOT EXISTS ix_media_population_runs_status
    ON media_population_runs (status);

CREATE TABLE IF NOT EXISTS media_population_run_items (
    id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES media_population_runs(id) ON DELETE CASCADE,
    dive_id INTEGER NOT NULL REFERENCES dives(id) ON DELETE CASCADE,
    video_uuid VARCHAR(100) NOT NULL,
    dive_code VARCHAR(10) NOT NULL,
    selection_band VARCHAR(20) NOT NULL,
    rendition VARCHAR(40) NOT NULL,
    media_key VARCHAR(64) NOT NULL,
    media_job_id INTEGER NULL REFERENCES media_jobs(id),
    status VARCHAR(30) NOT NULL DEFAULT 'planned',
    last_error TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_media_population_run_items_run_id
    ON media_population_run_items (run_id);
CREATE INDEX IF NOT EXISTS ix_media_population_run_items_dive_id
    ON media_population_run_items (dive_id);
CREATE INDEX IF NOT EXISTS ix_media_population_run_items_video_uuid
    ON media_population_run_items (video_uuid);
CREATE INDEX IF NOT EXISTS ix_media_population_run_items_dive_code
    ON media_population_run_items (dive_code);
CREATE INDEX IF NOT EXISTS ix_media_population_run_items_selection_band
    ON media_population_run_items (selection_band);
CREATE INDEX IF NOT EXISTS ix_media_population_run_items_rendition
    ON media_population_run_items (rendition);
CREATE INDEX IF NOT EXISTS ix_media_population_run_items_media_key
    ON media_population_run_items (media_key);
CREATE INDEX IF NOT EXISTS ix_media_population_run_items_media_job_id
    ON media_population_run_items (media_job_id);
CREATE INDEX IF NOT EXISTS ix_media_population_run_items_status
    ON media_population_run_items (status);
CREATE INDEX IF NOT EXISTS ix_media_population_items_run_media_key
    ON media_population_run_items (run_id, media_key);
CREATE INDEX IF NOT EXISTS ix_media_population_items_run_status
    ON media_population_run_items (run_id, status);
