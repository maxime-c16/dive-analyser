BEGIN;

CREATE TABLE IF NOT EXISTS media_agents (
    id VARCHAR(100) PRIMARY KEY,
    hostname VARCHAR(255) NOT NULL,
    api_key_sha256 VARCHAR(64) NOT NULL UNIQUE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    leasing_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    capabilities JSON NOT NULL DEFAULT '[]'::json,
    photos_access_status VARCHAR(40) NOT NULL DEFAULT 'unknown',
    last_successful_photos_query_at TIMESTAMP,
    last_permission_error_at TIMESTAMP,
    last_successful_export_at TIMESTAMP,
    last_materialization_success_at TIMESTAMP,
    internal_free_bytes BIGINT,
    vault_volume_uuid VARCHAR(64),
    vault_free_bytes BIGINT,
    vault_mounted BOOLEAN NOT NULL DEFAULT FALSE,
    last_seen_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_media_agents_api_key_sha256 ON media_agents(api_key_sha256);
CREATE INDEX IF NOT EXISTS ix_media_agents_active ON media_agents(active);
CREATE INDEX IF NOT EXISTS ix_media_agents_leasing_enabled ON media_agents(leasing_enabled);
CREATE INDEX IF NOT EXISTS ix_media_agents_last_seen_at ON media_agents(last_seen_at);

CREATE TABLE IF NOT EXISTS recalled_media_sources (
    id SERIAL PRIMARY KEY,
    video_uuid VARCHAR(100) NOT NULL,
    dive_id INTEGER REFERENCES dives(id) ON DELETE CASCADE,
    agent_id VARCHAR(100) NOT NULL REFERENCES media_agents(id) ON DELETE CASCADE,
    source_kind VARCHAR(50) NOT NULL,
    source_path TEXT NOT NULL,
    volume_uuid VARCHAR(64) NOT NULL,
    size_bytes BIGINT NOT NULL CHECK (size_bytes > 0),
    checksum_sha256 VARCHAR(64) NOT NULL,
    retention_class VARCHAR(40) NOT NULL DEFAULT 'temporary',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    validated_at TIMESTAMP NOT NULL,
    last_seen_at TIMESTAMP NOT NULL,
    expires_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_recalled_media_sources_video_uuid ON recalled_media_sources(video_uuid);
CREATE INDEX IF NOT EXISTS ix_recalled_media_sources_dive_id ON recalled_media_sources(dive_id);
CREATE INDEX IF NOT EXISTS ix_recalled_media_sources_agent_id ON recalled_media_sources(agent_id);
CREATE INDEX IF NOT EXISTS ix_recalled_media_sources_active ON recalled_media_sources(active);
CREATE INDEX IF NOT EXISTS ix_recalled_source_uuid_agent_active ON recalled_media_sources(video_uuid, agent_id, active);
CREATE INDEX IF NOT EXISTS ix_recalled_source_retention_expiry ON recalled_media_sources(retention_class, expires_at);

COMMIT;
