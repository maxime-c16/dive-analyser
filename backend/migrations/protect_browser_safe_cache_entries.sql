-- protect_browser_safe_cache_entries.sql — Lot A (P0, media-paths audit F1/F2)
--
-- Freeze the November expiry wave: every ready browser-safe preview/poster
-- row is a SOLE copy today (B2 holds camera originals only; no preview or
-- poster exists outside the deb-serv media-cache volume). Pinning exempts a
-- row from BOTH cleaner paths (TTL expiry AND quota trim); expires_at=NULL
-- alone would still allow quota eviction, so both columns are set together.
--
-- The same guarantee covers the legacy proxy_360p rows that are still the
-- ONLY ready proxy of their clip (no ready proxy_720p for the same
-- photos_asset_id). Lot B (#135) keeps serving those clips from 360p until
-- a verified 720p replaces them, so letting the last proxy expire before
-- the replacement would break guaranteed re-lecture. This migration pins
-- those 360-only rows as a transitional retention (not a durable replica).
-- 360p rows that already have a ready 720p for the same asset are NOT
-- pinned here: they stay unpinned and retained in this transition (the
-- generic cleaner excludes every 360p and the upgrade heartbeat retains
-- legacy files without retiring — a future explicit verified retirement
-- owns obsolete 360p once it serializes with replacement changes).
-- No new 360p is produced by this lot (no backfill, no finalizer change);
-- 360p is never a production requirement.
--
-- Scope is deliberately narrow:
-- - proxy_720p + poster: all ready rows (sole copies).
-- - proxy_360p: only ready rows with NO ready proxy_720p for the same
--   photos_asset_id (sole-proxy legacy stock). 360p rows shadowed by a
--   ready 720p are untouched.
-- - browser_source (raw upload bytes, roundtrip-verified into B2) stays a
--   disposable 1-day staging file: untouched.
-- - Mac local 'original' rows (0 in prod, 3-day staging): untouched.
-- - Non-ready rows (failed/verifying): untouched, the cleaner ignores them.
--
-- Properties:
-- - IDEMPOTENT: the WHERE clause only matches rows that still need
--   protection; re-running is a no-op. Re-run after the new finalizer is
--   live and whenever postflight shows a residual (concurrent finalizers
--   may insert unpinned rows between preflight and apply).
-- - BACKWARD COMPATIBLE: no schema change, no row deleted, no media file
--   touched. The previous backend keeps working on the migrated schema: its
--   cleaner already excludes pinned rows from both passes, and NULL expiry
--   rows were never TTL-eligible. Safe to apply BEFORE the new backend
--   deploys (required order per docs/REPO_WORKFLOW.md: SQL first, then ship).
--   The upgrade path is unaffected: legacy 360p rows are retained (never
--   retired in this transition) and the item is still marked upgraded, so
--   retention never blocks progression.
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
