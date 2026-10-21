-- protect_browser_safe_insert_guard.sql — Lot A transitional compat guard (P0).
--
-- Closes the migration→swap window the stock UPDATE alone cannot close:
-- the OLD finalizer (pre-Lot-A backend, still serving during the deploy)
-- inserts unpinned proxy_720p/poster rows AFTER the stock UPDATE, and the
-- OLD idle cleaner (upload_queue.process_one, every ~10 min at idle, plus
-- POST /cache/cleanup) can evict those sole copies BEFORE the post-deploy
-- reconciliation. Re-running the UPDATE cannot resurrect a file removed
-- from disk.
--
-- This trigger pins sole-copy rows AT BIRTH, inside Postgres, atomically
-- with the old writer's own transaction: once installed, there is no
-- instant where a new sole-copy row exists unpinned, so neither cleaner
-- pass (TTL expiry nor quota trim, both of which only match pinned IS
-- FALSE rows) can ever see it. No pause and no restart of the old runtime
-- is needed, and no new-code flag could replace this (a flag in the new
-- code cannot suspend the already-deployed old cleaner).
--
-- Scope mirrors finalize_cache_entry's SOLE_COPY_BROWSER_SAFE_RENDITIONS:
-- - proxy_720p + poster with status='ready': force pinned=TRUE,
--   expires_at=NULL. Covers both Mac finalizer inserts and browser
--   cache_upload poster inserts, old and new code alike (for new code the
--   trigger is a no-op: it already writes this state).
-- - proxy_360p: untouched, INCLUDING fresh 360p rows inserted by the old
--   runtime mid-transition. A new 360p row born during the transition
--   lands unpinned with its normal TTL and stays evictable, exactly as
--   today — the guard deliberately does not extend cover there, so the
--   planned upgrade-retirement path for shadowed 360p rows stays open
--   (retire_verified_proxy_entry refuses pinned rows). This is bounded,
--   not a hole in the sole-copy guarantee: 360p is never a production
--   requirement (a missing 360p is not an error), Lot B serves 720p
--   wherever a ready 720p exists, and the sole-proxy 360p STOCK is pinned
--   by the stock UPDATE plus the post-deploy reconciliation. Do not claim
--   transition-born 360p rows are protected; they are best-effort, as
--   before this lot.
-- - browser_source / original: untouched (1-day / conditional staging
--   stays evictable; browser originals are B2 roundtrip-verified and the
--   cleaner already spares them via its read predicate when remote
--   playback is not configured).
-- - Non-ready rows (verifying/failed): untouched, the cleaner ignores them.
-- - UPDATEs (incl. explicit admin pin/unpin): untouched. INSERT-only keeps
--   the admin unpin path and the verified-720p upgrade path unchanged.
--
-- Atomicity (single transaction, bounded locks):
-- - The whole install below is ONE transaction (explicit BEGIN/COMMIT):
--   DROP TRIGGER + CREATE TRIGGER never commit separately, so there is no
--   committed instant where the guard is absent. Re-running the file
--   re-enters the same single transaction (idempotent: CREATE OR REPLACE
--   + DROP IF EXISTS before CREATE).
-- - DDL takes a brief AccessExclusive lock on media_cache_entries. It is
--   bounded, not zero: SET LOCAL lock_timeout aborts the install fast
--   instead of queueing behind a long writer transaction, and
--   statement_timeout caps the build itself. A lock-timeout failure means
--   "a writer held the table" — wait for a quiet moment (between cleaner
--   passes) and run the file again; do NOT raise the timeouts to force it
--   through, and do NOT run it concurrently from two sessions.
-- - BACKWARD COMPATIBLE: no column added/removed, no row removed from the
--   table, no file touched. The old backend keeps working: its INSERTs
--   simply land pinned (its cleaner already excludes pinned rows from both
--   passes, and its Python-side object is stale only until refresh, which
--   no old code path depends on). The new backend is unaffected (writes
--   the same state).
-- - ORDER: apply this guard BEFORE backend/migrations/
--   protect_browser_safe_cache_entries.sql, verify it, then apply the stock
--   UPDATE, then deploy, then reconcile, then DROP the guard (runbook
--   docs/runbooks/media-sole-copy-protection.md §3). Keep the guard
--   installed while ANY pre-Lot-A writer may still run — including after a
--   rollback to the old backend. Remove it only after the new finalizer is
--   confirmed live AND the post-deploy reconciliation shows zero residual
--   (the DROP file documents the same rule).
--
-- Apply by hand against Postgres (no migration runner), same as the stock
-- UPDATE. Verifiable without writing prod data, inside a rolled-back
-- transaction (see runbook §3 step 2b). Real end-to-end proof (old-writer
-- row lands pinned, survives both cleaner passes, reinstall + teardown)
-- runs in CI on a disposable database:
-- backend/tests/test_postgres_media_guard.py.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

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

COMMIT;
