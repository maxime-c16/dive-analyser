-- protect_browser_safe_insert_guard.sql — Lot A transitional compat guard (P0).
--
-- Closes the migration→swap window the stock UPDATE alone cannot close:
-- the OLD finalizer (pre-Lot-A backend, still serving during the deploy)
-- inserts unpinned proxy_720p/poster rows AFTER the stock UPDATE, and the
-- OLD idle cleaner (upload_queue.process_one, every ~10 min at idle, plus
-- POST /cache/cleanup) can evict those sole copies BEFORE the post-deploy
-- reconciliation. Re-running the UPDATE after the deploy cannot resurrect
-- a deleted file.
--
-- This trigger pins sole-copy rows AT BIRTH, inside Postgres, atomically
-- with the old writer's own transaction: there is no instant where a new
-- sole-copy row exists unpinned, so neither cleaner pass (TTL expiry nor
-- quota trim, both of which only match pinned IS FALSE) can ever see it.
-- No pause, no API block, no restart of the old runtime, no new-code flag
-- (a flag in the new code cannot suspend the already-deployed old cleaner).
--
-- Scope mirrors finalize_cache_entry's SOLE_COPY_BROWSER_SAFE_RENDITIONS:
-- - proxy_720p + poster with status='ready': force pinned=TRUE,
--   expires_at=NULL. Covers both Mac finalizer inserts and browser
--   cache_upload poster inserts, old and new code alike (for new code the
--   trigger is a no-op: it already writes this state).
-- - proxy_360p: untouched (no new 360p production in this lot; shadowed
--   rows stay eligible for the planned upgrade retirement, sole-proxy
--   stock is covered by the stock UPDATE only).
-- - browser_source / original: untouched (1-day / conditional staging
--   stays evictable; browser originals are B2 roundtrip-verified and the
--   cleaner already spares them via its read predicate when remote
--   playback is not configured).
-- - Non-ready rows (verifying/failed): untouched, the cleaner ignores them.
-- - UPDATEs (incl. explicit admin pin/unpin): untouched. INSERT-only keeps
--   the admin unpin path and the verified-720p upgrade path unchanged.
--
-- Properties:
-- - IDEMPOTENT: CREATE OR REPLACE FUNCTION + DROP TRIGGER IF EXISTS before
--   CREATE TRIGGER; re-running is a no-op. Safe to apply BEFORE the stock
--   UPDATE and to re-apply at any point during the transition.
-- - BACKWARD COMPATIBLE: no column added/removed, no row deleted, no file
--   touched. The old backend keeps working: its INSERTs simply land pinned
--   (its cleaner already excludes pinned rows from both passes, and its
--   Python-side object is stale only until refresh, which no old code path
--   depends on). The new backend is unaffected (writes the same state).
-- - ROLLBACK: instant, see drop_protect_browser_safe_insert_guard.sql
--   (DROP TRIGGER IF EXISTS + DROP FUNCTION IF EXISTS). Dropping restores
--   pre-transition insert behavior; already-pinned rows stay pinned
--   (fail-safe direction, same as the stock UPDATE).
-- - ORDER: apply this guard BEFORE backend/migrations/
--   protect_browser_safe_cache_entries.sql, verify it, then apply the stock
--   UPDATE, then deploy, then reconcile, then DROP the guard (runbook
--   docs/runbooks/media-sole-copy-protection.md §3). Keeping it longer is
--   harmless (it enforces what the new finalizer already writes) but it is
--   dropped after verification to restore intentional unpinned-insert
--   flexibility for the future durable pipeline (outside Lots A/B).
--
-- Apply by hand against Postgres (no migration runner), same as the stock
-- UPDATE. Verifiable without writing prod data, inside a rolled-back
-- transaction (see runbook §3 step 2b).

CREATE OR REPLACE FUNCTION protect_browser_safe_cache_entries_fn()
RETURNS trigger
LANGUAGE plpgsql
AS $func$
BEGIN
  IF NEW.rendition IN ('proxy_720p', 'poster') AND NEW.status = 'ready' THEN
    NEW.pinned := TRUE;
    NEW.expires_at := NULL;
  END IF;
  RETURN NEW;
END;
$func$;

DROP TRIGGER IF EXISTS trg_protect_browser_safe_cache_entries ON media_cache_entries;

CREATE TRIGGER trg_protect_browser_safe_cache_entries
BEFORE INSERT ON media_cache_entries
FOR EACH ROW
EXECUTE FUNCTION protect_browser_safe_cache_entries_fn();
