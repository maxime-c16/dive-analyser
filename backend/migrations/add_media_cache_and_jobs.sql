-- Add asynchronous media cache registry and media request jobs.

CREATE TABLE IF NOT EXISTS media_cache_entries (
    id SERIAL PRIMARY KEY,
    photos_asset_id INTEGER NOT NULL REFERENCES photos_assets(id) ON DELETE CASCADE,
    media_key CHAR(64) NOT NULL UNIQUE,
    rendition VARCHAR(40) NOT NULL,
    storage_backend VARCHAR(30) NOT NULL DEFAULT 'local_fs',
    storage_path TEXT NOT NULL,
    content_type VARCHAR(100),
    size_bytes BIGINT NOT NULL,
    checksum_sha256 CHAR(64),
    width INTEGER,
    height INTEGER,
    duration_seconds NUMERIC,
    status VARCHAR(30) NOT NULL DEFAULT 'ready',
    pinned BOOLEAN NOT NULL DEFAULT false,
    last_accessed_at TIMESTAMP,
    expires_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_media_cache_entries_asset ON media_cache_entries(photos_asset_id);
CREATE INDEX IF NOT EXISTS ix_media_cache_entries_rendition ON media_cache_entries(rendition);
CREATE INDEX IF NOT EXISTS ix_media_cache_entries_status ON media_cache_entries(status);
CREATE INDEX IF NOT EXISTS ix_media_cache_entries_expires ON media_cache_entries(expires_at);
CREATE INDEX IF NOT EXISTS ix_media_cache_entries_last_accessed ON media_cache_entries(last_accessed_at);

CREATE TABLE IF NOT EXISTS media_jobs (
    id SERIAL PRIMARY KEY,
    photos_asset_id INTEGER NOT NULL REFERENCES photos_assets(id) ON DELETE CASCADE,
    media_key CHAR(64) NOT NULL,
    rendition VARCHAR(40) NOT NULL,
    status VARCHAR(40) NOT NULL DEFAULT 'queued',
    priority INTEGER NOT NULL DEFAULT 100,
    request_reason VARCHAR(40),
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    claimed_by VARCHAR(100),
    claimed_at TIMESTAMP,
    claimed_until TIMESTAMP,
    progress INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    upload_tmp_path TEXT,
    output_checksum_sha256 CHAR(64),
    output_size_bytes BIGINT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_media_jobs_media_key ON media_jobs(media_key);
CREATE INDEX IF NOT EXISTS ix_media_jobs_status ON media_jobs(status);
CREATE INDEX IF NOT EXISTS ix_media_jobs_asset_rendition ON media_jobs(photos_asset_id, rendition);
CREATE INDEX IF NOT EXISTS ix_media_jobs_claimed_until ON media_jobs(claimed_until);

CREATE UNIQUE INDEX IF NOT EXISTS uq_active_media_job
ON media_jobs(media_key)
WHERE status IN (
    'queued',
    'waiting_for_mac',
    'claimed',
    'exporting',
    'transcoding',
    'uploading',
    'verifying'
);
