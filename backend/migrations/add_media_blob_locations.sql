-- add_media_blob_locations.sql — DIVE_ANALYZER_MEDIA_BACKBONE_V1 (P4.3)
-- STORAGE AUTHORITY HARDENING: content identity vs physical storage replicas.
--
-- Problem being repaired: media_blobs carried physical-location fields
-- (storage_backend / bucket / object_key / remote_object_id) on the
-- content-identity row, so the same SHA ingested into both the DEV and PROD
-- buckets could not be represented without losing one location (exercised
-- live by the P4.2 dev-overlap cohort: 4 verified PROD uploads deduped onto
-- DEV content rows and were not durably represented).
--
-- This migration is ADDITIVE:
-- - creates media_blob_locations (authoritative per-replica storage records)
-- - backfills all currently-known blob locations from media_blobs
--   (idempotent, WHERE NOT EXISTS; no existing row is rewritten)
-- - replaces the ingest_object_state (video_uuid, object_key) uniqueness
--   with environment-scoped uniqueness (video_uuid, environment,
--   object_key); the pre-P4.3 index is dropped only AFTER the replacement
--   exists. No data row is deleted or rewritten.
--
-- REVERSIBILITY: dropping the backbone tables (add_media_backbone_tables.sql
-- revert procedure plus this table and the restored unique index) returns the
-- schema to the pre-P4.3 state:
--   CREATE UNIQUE INDEX ix_ingest_object_state_clip_key_unique
--       ON ingest_object_state (video_uuid, object_key);
--   DROP TABLE IF EXISTS media_blob_locations;
--   DROP INDEX IF EXISTS ix_ingest_object_state_clip_env_key_unique;
--
-- IDEMPOTENT: safe to re-run (all statements IF NOT EXISTS / NOT EXISTS).
--
-- NO legacy table is altered. NO media row is deleted. The media_blobs
-- location columns remain in place (transitional / non-authoritative;
-- documented in app/models/media_backbone.py) and are NOT removed here.

CREATE TABLE IF NOT EXISTS media_blob_locations (
    id SERIAL PRIMARY KEY,
    blob_sha256 VARCHAR(64) NOT NULL,
    environment VARCHAR(20) NOT NULL,
    storage_backend VARCHAR(40) NOT NULL DEFAULT 'b2',
    bucket VARCHAR(120) NOT NULL,
    object_key VARCHAR(160) NOT NULL,
    remote_object_id VARCHAR(120),
    verified BOOLEAN NOT NULL DEFAULT FALSE,
    verified_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_media_blob_locations_replica_unique
    ON media_blob_locations (storage_backend, bucket, object_key);
CREATE UNIQUE INDEX IF NOT EXISTS ix_media_blob_locations_blob_replica_unique
    ON media_blob_locations (blob_sha256, storage_backend, bucket, object_key);
CREATE INDEX IF NOT EXISTS ix_media_blob_locations_blob_sha256
    ON media_blob_locations (blob_sha256);
CREATE INDEX IF NOT EXISTS ix_media_blob_locations_blob_env
    ON media_blob_locations (blob_sha256, environment);
CREATE INDEX IF NOT EXISTS ix_media_blob_locations_env_verified
    ON media_blob_locations (environment, verified);

-- P4.3 ledger identity repair: environment-scoped uniqueness FIRST (the
-- replacement authority must exist before the conflated index is removed).
CREATE UNIQUE INDEX IF NOT EXISTS ix_ingest_object_state_clip_env_key_unique
    ON ingest_object_state (video_uuid, environment, object_key);
DROP INDEX IF EXISTS ix_ingest_object_state_clip_key_unique;

-- Backfill: one location row per currently-known media_blobs physical
-- location. environment is derived from the canonical environment buckets
-- (the same allowlist the commit API enforces); a blob row pointing at any
-- other bucket is NOT backfilled by this file (fail-closed: an unmapped
-- location must be reconciled explicitly, never invented). verified_at uses
-- the blob row's creation time: every media_blobs row in the backbone was
-- inserted only after full remote-GET SHA verification (P2 rule).
INSERT INTO media_blob_locations
    (blob_sha256, environment, storage_backend, bucket, object_key,
     remote_object_id, verified, verified_at, created_at)
SELECT
    b.sha256,
    CASE lower(b.bucket)
        WHEN 'diveanalyzer-dev-media' THEN 'dev'
        WHEN 'diveanalyzer-prod-media' THEN 'prod'
    END,
    b.storage_backend,
    b.bucket,
    b.object_key,
    b.remote_object_id,
    TRUE,
    b.created_at,
    NOW()
FROM media_blobs b
WHERE lower(b.bucket) IN ('diveanalyzer-dev-media', 'diveanalyzer-prod-media')
  AND b.object_key IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM media_blob_locations l
      WHERE l.storage_backend = b.storage_backend
        AND l.bucket = b.bucket
        AND l.object_key = b.object_key
  );
