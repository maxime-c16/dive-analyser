-- D1 durable-derivative foundation (additive; manual apply BEFORE deploy).
--
-- New ledger table `media_derivatives` (one row per derivation) plus two
-- nullable columns on each of `media_cache_entries` and `media_jobs`.
-- D1 is publish- and read-inert: no job references the new table and no
-- route serves it, so the only valid post-deploy state is zero derivative
-- rows with all new columns NULL. Rolling back the code is always safe
-- (old code never touches these objects); never roll back this migration.
--
-- Idempotent: every statement tolerates re-runs (`IF NOT EXISTS` + guarded
-- constraint/index creation), exactly the way `psql -f` applies it.

CREATE TABLE IF NOT EXISTS media_derivatives (
    id SERIAL PRIMARY KEY,
    video_uuid VARCHAR(100) NOT NULL,
    source_blob_sha256 VARCHAR(64) NOT NULL,
    role VARCHAR(20) NOT NULL CONSTRAINT ck_media_derivative_role CHECK (role IN ('hq', 'light', 'poster')),
    transform_version VARCHAR(40) NOT NULL,
    derivative_blob_sha256 VARCHAR(64) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'verifying' CONSTRAINT ck_media_derivative_status CHECK (status IN ('verifying', 'ready', 'stale', 'superseded')),
    verified_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Ledger identity: one row per derivation. Unique INDEX (not a table
-- constraint) matches the SQLAlchemy model declaration, so `create_all`
-- and this file agree and re-runs are no-ops. The future publisher upserts
-- with ON CONFLICT (video_uuid, source_blob_sha256, role, transform_version)
-- (column list), never ON CONSTRAINT <name>.
CREATE UNIQUE INDEX IF NOT EXISTS uq_media_derivative_identity
    ON media_derivatives (video_uuid, source_blob_sha256, role, transform_version);

CREATE INDEX IF NOT EXISTS ix_media_derivative_clip_role
    ON media_derivatives (video_uuid, role, status);
CREATE INDEX IF NOT EXISTS ix_media_derivatives_video_uuid
    ON media_derivatives (video_uuid);
CREATE INDEX IF NOT EXISTS ix_media_derivatives_source_sha
    ON media_derivatives (source_blob_sha256);
CREATE INDEX IF NOT EXISTS ix_media_derivatives_derivative_sha
    ON media_derivatives (derivative_blob_sha256);

-- Nullable provenance on cache rows: legacy rows keep NULL (= pre-derivative
-- stock, served under the #134 sole-copy rules until replaced).
ALTER TABLE media_cache_entries ADD COLUMN IF NOT EXISTS source_blob_sha256 VARCHAR(64) NULL;
ALTER TABLE media_cache_entries ADD COLUMN IF NOT EXISTS transform_version VARCHAR(40) NULL;
CREATE INDEX IF NOT EXISTS ix_media_cache_entries_source_blob
    ON media_cache_entries (source_blob_sha256);

-- Nullable reservations for D2 fencing / D3 package finalization. D1 writes
-- nothing here; old code ignores both columns. finalized_slots ships
-- NULL-default (NULL = no slot finalized yet); D3 must treat NULL as empty.
ALTER TABLE media_jobs ADD COLUMN IF NOT EXISTS lease_token VARCHAR(36) NULL;
ALTER TABLE media_jobs ADD COLUMN IF NOT EXISTS finalized_slots JSON NULL;
