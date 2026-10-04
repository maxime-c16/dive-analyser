-- add_media_backbone_tables.sql — DIVE_ANALYZER_MEDIA_BACKBONE_V1 (P0.2/P1)
-- Additive-only schema for the object-storage media backbone.
-- Reversible: reverting this migration is exactly
--   DROP TABLE IF EXISTS ingest_object_state;
--   DROP TABLE IF EXISTS caption_revisions;
--   DROP TABLE IF EXISTS media_revisions;
--   DROP TABLE IF EXISTS media_blobs;
-- No legacy table is altered. No historical row is rewritten.
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS media_blobs (
    sha256 VARCHAR(64) PRIMARY KEY,
    byte_size BIGINT NOT NULL CHECK (byte_size > 0),
    codec VARCHAR(40),
    width INTEGER,
    height INTEGER,
    duration_seconds NUMERIC,
    rendition_semantics VARCHAR(60) NOT NULL DEFAULT 'photos_edited_rendition',
    storage_backend VARCHAR(40) NOT NULL DEFAULT 'b2',
    bucket VARCHAR(120),
    object_key VARCHAR(160),
    remote_object_id VARCHAR(120),
    ingest_impl_version VARCHAR(40) NOT NULL DEFAULT 'media_backbone_v1',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_media_blobs_object_key ON media_blobs (object_key);

CREATE TABLE IF NOT EXISTS media_revisions (
    id SERIAL PRIMARY KEY,
    video_uuid VARCHAR(100) NOT NULL,
    blob_sha256 VARCHAR(64) NOT NULL REFERENCES media_blobs (sha256),
    photos_edit_fingerprint VARCHAR(120),
    rendition_semantics VARCHAR(60) NOT NULL DEFAULT 'photos_edited_rendition',
    source_provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    observed_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_media_revisions_clip_blob_unique
    ON media_revisions (video_uuid, blob_sha256);
CREATE INDEX IF NOT EXISTS ix_media_revisions_video_uuid ON media_revisions (video_uuid);
CREATE INDEX IF NOT EXISTS ix_media_revisions_blob_sha256 ON media_revisions (blob_sha256);

CREATE TABLE IF NOT EXISTS caption_revisions (
    id SERIAL PRIMARY KEY,
    video_uuid VARCHAR(100) NOT NULL,
    caption_raw TEXT NOT NULL,
    caption_sha256 VARCHAR(64) NOT NULL,
    caption_provider VARCHAR(60) NOT NULL,
    parser_version VARCHAR(40),
    parsed_json JSONB,
    shadow_provider VARCHAR(60),
    shadow_raw TEXT,
    shadow_sha256 VARCHAR(64),
    shadow_available BOOLEAN,
    exact_equal BOOLEAN,
    observed_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_caption_revisions_clip_sha_unique
    ON caption_revisions (video_uuid, caption_sha256);
CREATE INDEX IF NOT EXISTS ix_caption_revisions_video_uuid ON caption_revisions (video_uuid);
CREATE INDEX IF NOT EXISTS ix_caption_revisions_caption_sha256 ON caption_revisions (caption_sha256);

CREATE TABLE IF NOT EXISTS ingest_object_state (
    id SERIAL PRIMARY KEY,
    video_uuid VARCHAR(100) NOT NULL,
    object_key VARCHAR(160) NOT NULL,
    state VARCHAR(40) NOT NULL DEFAULT 'DISCOVERED',
    attempts INTEGER NOT NULL DEFAULT 0,
    error_family VARCHAR(60),
    local_temp_path TEXT,
    blob_sha256 VARCHAR(64),
    caption_sha256 VARCHAR(64),
    verified BOOLEAN NOT NULL DEFAULT FALSE,
    db_committed_at TIMESTAMP,
    environment VARCHAR(20) NOT NULL DEFAULT 'dev',
    storage_backend VARCHAR(40) NOT NULL DEFAULT 'b2',
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_ingest_object_state_clip_key_unique
    ON ingest_object_state (video_uuid, object_key);
CREATE INDEX IF NOT EXISTS ix_ingest_object_state_video_uuid ON ingest_object_state (video_uuid);
CREATE INDEX IF NOT EXISTS ix_ingest_object_state_state ON ingest_object_state (state);
