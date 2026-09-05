BEGIN;

CREATE TABLE IF NOT EXISTS media_resolution_upgrade_runs (
    id SERIAL PRIMARY KEY,
    target_rendition VARCHAR(40) NOT NULL DEFAULT 'proxy_720p',
    scope VARCHAR(20) NOT NULL DEFAULT 'self',
    status VARCHAR(30) NOT NULL DEFAULT 'scheduled',
    starts_after_population_run_id INTEGER REFERENCES media_catalog_population_runs(id),
    total_items INTEGER NOT NULL DEFAULT 0,
    completed_items INTEGER NOT NULL DEFAULT 0,
    upgraded_items INTEGER NOT NULL DEFAULT 0,
    failed_items INTEGER NOT NULL DEFAULT 0,
    skipped_pinned_items INTEGER NOT NULL DEFAULT 0,
    current_item_id INTEGER,
    plan_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    paused_at TIMESTAMP,
    pause_reason VARCHAR(100),
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_resolution_upgrade_runs_status ON media_resolution_upgrade_runs(status);

CREATE TABLE IF NOT EXISTS media_resolution_upgrade_items (
    id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES media_resolution_upgrade_runs(id) ON DELETE CASCADE,
    catalog_item_id INTEGER NOT NULL REFERENCES captioned_media_catalog(id) ON DELETE CASCADE,
    old_cache_entry_id INTEGER NOT NULL REFERENCES media_cache_entries(id),
    upgrade_job_id INTEGER REFERENCES media_jobs(id),
    status VARCHAR(40) NOT NULL DEFAULT 'planned',
    last_error TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    completed_at TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_resolution_upgrade_item_unique
    ON media_resolution_upgrade_items(run_id, catalog_item_id);
CREATE INDEX IF NOT EXISTS ix_resolution_upgrade_item_status
    ON media_resolution_upgrade_items(run_id, status, id);

COMMIT;
