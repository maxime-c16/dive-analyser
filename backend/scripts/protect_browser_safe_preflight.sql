-- protect_browser_safe_preflight.sql — Lot A read-only pre/postflight.
--
-- Run BEFORE applying backend/migrations/protect_browser_safe_cache_entries.sql
-- (captures the affected scope + required capacity) and AFTER (must show zero
-- residual expiring/unpinned sole-copy rows). Read-only: only SELECTs.
-- All counts are aggregates (rendition-level counts/bytes); no per-clip,
-- per-user, or path data is returned.
--
-- Protected scope:
-- - proxy_720p + poster: every ready row (sole copies).
-- - proxy_360p: only ready rows with NO ready proxy_720p for the same
--   photos_asset_id (sole-proxy legacy stock still served by Lot B
--   consumers until a verified 720p replaces them). 360p rows shadowed by
--   a ready 720p stay on the normal upgrade-retirement path and are NOT
--   protected here.
--
-- 1. Rows the migration will protect, by rendition.
SELECT rendition,
       COUNT(*) AS rows_to_protect,
       COALESCE(SUM(size_bytes), 0) AS bytes_to_protect
FROM media_cache_entries
WHERE status = 'ready'
  AND (pinned IS NOT TRUE OR expires_at IS NOT NULL)
  AND (
    rendition IN ('proxy_720p', 'poster')
    OR (
      rendition = 'proxy_360p'
      AND NOT EXISTS (
        SELECT 1
        FROM media_cache_entries newer
        WHERE newer.photos_asset_id = media_cache_entries.photos_asset_id
          AND newer.rendition = 'proxy_720p'
          AND newer.status = 'ready'
      )
    )
  )
GROUP BY rendition
ORDER BY rendition;

-- 2. Capacity check: total bytes that must stay on disk after protection
-- (already-protected rows + rows the migration will protect). Compare with
-- `df` on the media-cache volume; no new bytes are written by the migration.
SELECT COUNT(*) AS protected_rows,
       COALESCE(SUM(size_bytes), 0) AS protected_bytes
FROM media_cache_entries
WHERE status = 'ready'
  AND (
    rendition IN ('proxy_720p', 'poster')
    OR (
      rendition = 'proxy_360p'
      AND NOT EXISTS (
        SELECT 1
        FROM media_cache_entries newer
        WHERE newer.photos_asset_id = media_cache_entries.photos_asset_id
          AND newer.rendition = 'proxy_720p'
          AND newer.status = 'ready'
      )
    )
  );

-- 3. Expiry wave the migration freezes (TTL pass would delete these next).
SELECT COUNT(*) AS expiring_rows,
       COALESCE(SUM(size_bytes), 0) AS expiring_bytes,
       MIN(expires_at) AS first_expiry,
       MAX(expires_at) AS last_expiry
FROM media_cache_entries
WHERE status = 'ready'
  AND expires_at IS NOT NULL
  AND (
    rendition IN ('proxy_720p', 'poster')
    OR (
      rendition = 'proxy_360p'
      AND NOT EXISTS (
        SELECT 1
        FROM media_cache_entries newer
        WHERE newer.photos_asset_id = media_cache_entries.photos_asset_id
          AND newer.rendition = 'proxy_720p'
          AND newer.status = 'ready'
      )
    )
  );

-- 4. Postflight expectation: this must return 0 rows after the migration.
SELECT COUNT(*) AS residual_unprotected_rows
FROM media_cache_entries
WHERE status = 'ready'
  AND (pinned IS NOT TRUE OR expires_at IS NOT NULL)
  AND (
    rendition IN ('proxy_720p', 'poster')
    OR (
      rendition = 'proxy_360p'
      AND NOT EXISTS (
        SELECT 1
        FROM media_cache_entries newer
        WHERE newer.photos_asset_id = media_cache_entries.photos_asset_id
          AND newer.rendition = 'proxy_720p'
          AND newer.status = 'ready'
      )
    )
  );

-- 5. Untouched renditions (informational: proves the migration scope did not
-- leak into disposable staging files, and that shadowed 360p rows stay on
-- the upgrade-retirement path).
-- 5a. Disposable staging files: never protected.
SELECT rendition,
       COUNT(*) AS rows_total,
       COUNT(*) FILTER (WHERE pinned IS TRUE) AS pinned_rows,
       COUNT(*) FILTER (WHERE expires_at IS NOT NULL) AS expiring_rows
FROM media_cache_entries
WHERE status = 'ready'
  AND rendition IN ('browser_source', 'original')
GROUP BY rendition
ORDER BY rendition;

-- 5b. Shadowed legacy 360p (a ready 720p exists for the same asset):
-- must stay unpinned by this migration so the verified-720p upgrade path
-- can still retire them. Small non-zero pinned counts here would only come
-- from explicit admin pins, never from this migration.
SELECT COUNT(*) AS shadowed_360p_rows,
       COUNT(*) FILTER (WHERE pinned IS TRUE) AS shadowed_360p_pinned,
       COALESCE(SUM(size_bytes), 0) AS shadowed_360p_bytes
FROM media_cache_entries shadowed
WHERE shadowed.status = 'ready'
  AND shadowed.rendition = 'proxy_360p'
  AND EXISTS (
    SELECT 1
    FROM media_cache_entries newer
    WHERE newer.photos_asset_id = shadowed.photos_asset_id
      AND newer.rendition = 'proxy_720p'
      AND newer.status = 'ready'
  );
