-- protect_browser_safe_preflight.sql — Lot A read-only pre/postflight.
--
-- Run BEFORE applying backend/migrations/protect_browser_safe_cache_entries.sql
-- (captures the affected scope + required capacity) and AFTER (must show zero
-- residual expiring/unpinned sole-copy rows). Read-only: only SELECTs.
--
-- 1. Rows the migration will protect, by rendition.
SELECT rendition,
       COUNT(*) AS rows_to_protect,
       COALESCE(SUM(size_bytes), 0) AS bytes_to_protect
FROM media_cache_entries
WHERE status = 'ready'
  AND rendition IN ('proxy_720p', 'poster')
  AND (pinned IS NOT TRUE OR expires_at IS NOT NULL)
GROUP BY rendition
ORDER BY rendition;

-- 2. Capacity check: total bytes that must stay on disk after protection
-- (already-protected rows + rows the migration will protect). Compare with
-- `df` on the media-cache volume; no new bytes are written by the migration.
SELECT COUNT(*) AS protected_rows,
       COALESCE(SUM(size_bytes), 0) AS protected_bytes
FROM media_cache_entries
WHERE status = 'ready'
  AND rendition IN ('proxy_720p', 'poster');

-- 3. Expiry wave the migration freezes (TTL pass would delete these next).
SELECT COUNT(*) AS expiring_rows,
       COALESCE(SUM(size_bytes), 0) AS expiring_bytes,
       MIN(expires_at) AS first_expiry,
       MAX(expires_at) AS last_expiry
FROM media_cache_entries
WHERE status = 'ready'
  AND rendition IN ('proxy_720p', 'poster')
  AND expires_at IS NOT NULL;

-- 4. Postflight expectation: this must return 0 rows after the migration.
SELECT COUNT(*) AS residual_unprotected_rows
FROM media_cache_entries
WHERE status = 'ready'
  AND rendition IN ('proxy_720p', 'poster')
  AND (pinned IS NOT TRUE OR expires_at IS NOT NULL);

-- 5. Untouched renditions (informational: proves the migration scope did not
-- leak into Lot B territory or disposable staging files).
SELECT rendition,
       COUNT(*) AS rows_total,
       COUNT(*) FILTER (WHERE pinned IS TRUE) AS pinned_rows,
       COUNT(*) FILTER (WHERE expires_at IS NOT NULL) AS expiring_rows
FROM media_cache_entries
WHERE status = 'ready'
  AND rendition IN ('proxy_360p', 'browser_source', 'original')
GROUP BY rendition
ORDER BY rendition;
