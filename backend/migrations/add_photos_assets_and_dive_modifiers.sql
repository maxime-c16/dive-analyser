-- Add Photos asset metadata and normalized dive modifiers.
-- This is Phase 1 foundation for the asynchronous media cache architecture.

CREATE TABLE IF NOT EXISTS photos_assets (
    id SERIAL PRIMARY KEY,
    video_uuid VARCHAR(100) NOT NULL UNIQUE,
    filename VARCHAR(255),
    original_filename VARCHAR(255),
    photos_path TEXT,
    local_available BOOLEAN,
    is_missing BOOLEAN,
    icloud_status VARCHAR(40) DEFAULT 'unknown',
    media_type VARCHAR(20) NOT NULL DEFAULT 'video',
    duration_seconds NUMERIC,
    width INTEGER,
    height INTEGER,
    file_size_bytes BIGINT,
    raw_caption TEXT,
    caption_hash VARCHAR(64),
    metadata_fingerprint VARCHAR(64),
    photos_created_at TIMESTAMP,
    photos_modified_at TIMESTAMP,
    last_seen_on_mac_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_photos_assets_video_uuid ON photos_assets(video_uuid);
CREATE INDEX IF NOT EXISTS ix_photos_assets_caption_hash ON photos_assets(caption_hash);
CREATE INDEX IF NOT EXISTS ix_photos_assets_last_seen ON photos_assets(last_seen_on_mac_at);

ALTER TABLE dives
ADD COLUMN IF NOT EXISTS photos_asset_id INTEGER REFERENCES photos_assets(id);

CREATE INDEX IF NOT EXISTS ix_dives_photos_asset_id ON dives(photos_asset_id);

CREATE TABLE IF NOT EXISTS dive_modifiers (
    id SERIAL PRIMARY KEY,
    dive_id INTEGER NOT NULL REFERENCES dives(id) ON DELETE CASCADE,
    modifier_code VARCHAR(20) NOT NULL,
    modifier_type VARCHAR(30) NOT NULL DEFAULT 'drill',
    source VARCHAR(30) NOT NULL DEFAULT 'caption',
    raw_caption TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_dive_modifier UNIQUE (dive_id, modifier_code)
);

CREATE INDEX IF NOT EXISTS ix_dive_modifiers_code ON dive_modifiers(modifier_code);
CREATE INDEX IF NOT EXISTS ix_dive_modifiers_type ON dive_modifiers(modifier_type);
CREATE INDEX IF NOT EXISTS ix_dive_modifiers_dive_id ON dive_modifiers(dive_id);
