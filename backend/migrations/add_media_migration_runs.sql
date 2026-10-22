-- Historical web-package migration ledger (additive; manual apply BEFORE deploy).
--
-- One durable run per historical migration and one item per clip
-- (dives.video_uuid). The server tick (ops/systemd/dive-media-migration.*)
-- reads/writes only these two tables plus normal media_jobs rows created
-- through create_or_reuse_media_job. Nothing else is altered.
--
-- Old code ignores both tables. Rollback: stop the timer; the tables may
-- stay (never drop: they are the migration history).
--
-- Idempotent: safe to re-run (IF NOT EXISTS everywhere).

CREATE TABLE IF NOT EXISTS media_migration_runs (
    id SERIAL PRIMARY KEY,
    kind VARCHAR(40) NOT NULL DEFAULT 'web_package_backfill',
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'paused', 'cancelled')),
    pause_reason TEXT NULL,
    transform_version VARCHAR(40) NOT NULL,
    priority INTEGER NOT NULL DEFAULT 70 CHECK (priority >= 60),
    max_attempts INTEGER NOT NULL DEFAULT 2 CHECK (max_attempts BETWEEN 1 AND 2),
    queue_depth INTEGER NOT NULL DEFAULT 2 CHECK (queue_depth BETWEEN 1 AND 5),
    budget_bytes BIGINT NOT NULL CHECK (budget_bytes > 0),
    admission_cap INTEGER NULL CHECK (admission_cap IS NULL OR admission_cap >= 0),
    admitted_jobs INTEGER NOT NULL DEFAULT 0,
    sweep_cursor INTEGER NOT NULL DEFAULT 0,
    last_tick_at TIMESTAMP NULL,
    last_tick JSON NULL,
    created_by VARCHAR(80) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- At most one non-cancelled run at a time.
CREATE UNIQUE INDEX IF NOT EXISTS uq_media_migration_one_open_run
    ON media_migration_runs ((1)) WHERE status IN ('active', 'paused');

CREATE TABLE IF NOT EXISTS media_migration_items (
    id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES media_migration_runs(id) ON DELETE CASCADE,
    video_uuid VARCHAR(100) NOT NULL,
    photos_asset_id INTEGER NULL REFERENCES photos_assets(id) ON DELETE SET NULL,
    sort_key TIMESTAMP NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'queued', 'complete', 'skipped_complete', 'blocked', 'failed')),
    reason VARCHAR(80) NULL,
    source_sha256 VARCHAR(64) NULL,
    source_revision_id INTEGER NULL,
    media_job_id INTEGER NULL REFERENCES media_jobs(id) ON DELETE SET NULL,
    job_owned BOOLEAN NOT NULL DEFAULT FALSE,
    estimated_bytes BIGINT NULL,
    published_bytes BIGINT NULL,
    published_objects INTEGER NULL,
    settled_bytes BIGINT NOT NULL DEFAULT 0,
    hq_aliased_to VARCHAR(10) NULL,
    source_changes INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NULL,
    admitted_at TIMESTAMP NULL,
    completed_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_media_migration_item_run_uuid
    ON media_migration_items (run_id, video_uuid);
CREATE INDEX IF NOT EXISTS ix_media_migration_items_run_status
    ON media_migration_items (run_id, status);
CREATE INDEX IF NOT EXISTS ix_media_migration_items_job
    ON media_migration_items (media_job_id);
