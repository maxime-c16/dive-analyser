-- Apply manually BEFORE backend deployment. Additive; safe to retain on rollback.
ALTER TABLE media_cache_entries ADD COLUMN IF NOT EXISTS thumbhash varchar(128);
ALTER TABLE media_cache_entries ADD COLUMN IF NOT EXISTS thumb_storage_path text;
ALTER TABLE media_cache_entries ADD COLUMN IF NOT EXISTS thumb_checksum_sha256 varchar(64);
ALTER TABLE media_cache_entries ADD COLUMN IF NOT EXISTS thumb_size_bytes bigint;
