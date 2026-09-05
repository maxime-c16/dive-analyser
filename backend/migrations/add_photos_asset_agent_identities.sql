BEGIN;

ALTER TABLE photos_assets
    ADD COLUMN IF NOT EXISTS cloud_guid VARCHAR(100);

CREATE INDEX IF NOT EXISTS ix_photos_assets_cloud_guid
    ON photos_assets (cloud_guid)
    WHERE cloud_guid IS NOT NULL;

CREATE TABLE IF NOT EXISTS photos_asset_agent_identities (
    id SERIAL PRIMARY KEY,
    photos_asset_id INTEGER NOT NULL REFERENCES photos_assets(id) ON DELETE CASCADE,
    agent_id VARCHAR(100) NOT NULL REFERENCES media_agents(id) ON DELETE CASCADE,
    local_uuid VARCHAR(100) NOT NULL,
    cloud_guid VARCHAR(100),
    last_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_photos_asset_agent_identity_unique
    ON photos_asset_agent_identities (photos_asset_id, agent_id);
CREATE UNIQUE INDEX IF NOT EXISTS ix_photos_agent_local_uuid_unique
    ON photos_asset_agent_identities (agent_id, local_uuid);
CREATE INDEX IF NOT EXISTS ix_photos_agent_identity_cloud_guid
    ON photos_asset_agent_identities (cloud_guid);

COMMIT;
