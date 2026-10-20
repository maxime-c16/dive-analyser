-- protect_browser_safe_cache_entries.sql — Lot A (P0, media-paths audit F1/F2)
--
-- Freeze the November expiry wave: every ready browser-safe preview/poster
-- row is a SOLE copy today (B2 holds camera originals only; no preview or
-- poster exists outside the deb-serv media-cache volume). Pinning exempts a
-- row from BOTH cleaner paths (TTL expiry AND quota trim); expires_at=NULL
-- alone would still allow quota eviction, so both columns are set together.
--
-- Scope is deliberately narrow:
-- - proxy_720p + poster only. proxy_360p belongs to Lot B (abandoned
--   rendition, still consumed by representatives/catalog): untouched.
-- - browser_source (raw upload bytes, roundtrip-verified into B2) stays a
--   disposable 1-day staging file: untouched.
-- - Mac local 'original' rows (0 in prod, 3-day staging): untouched.
-- - Non-ready rows (failed/verifying): untouched, the cleaner ignores them.
--
-- Properties:
-- - IDEMPOTENT: the WHERE clause only matches rows that still need
--   protection; re-running is a no-op.
-- - BACKWARD COMPATIBLE: no schema change, no row deleted, no media file
--   touched. The previous backend keeps working on the migrated schema: its
--   cleaner already excludes pinned rows from both passes, and NULL expiry
--   rows were never TTL-eligible. Safe to apply BEFORE the new backend
--   deploys (required order per docs/REPO_WORKFLOW.md: SQL first, then ship).
-- - ROLLBACK: no rollback SQL is needed. If the deploy is reverted, the
--   pinned rows simply stay protected (fail-safe direction). Unpinning, if
--   ever wanted, is an explicit per-row admin action, not a migration.
--
-- Apply by hand against Postgres (no migration runner). The babysitter runs
-- backend/scripts/protect_browser_safe_preflight.sql before AND after, and
-- only proceeds when the postflight shows zero residual expiring rows.
UPDATE media_cache_entries
SET pinned = TRUE,
    expires_at = NULL,
    updated_at = CURRENT_TIMESTAMP
WHERE status = 'ready'
  AND rendition IN ('proxy_720p', 'poster')
  AND (pinned IS NOT TRUE OR expires_at IS NOT NULL);
