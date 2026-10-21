-- drop_protect_browser_safe_insert_guard.sql — Lot A guard teardown (P0).
--
-- Drops the transitional INSERT guard installed by backend/migrations/
-- protect_browser_safe_insert_guard.sql. Run ONCE, AFTER the post-deploy
-- reconciliation shows zero residual AND the new finalizer is confirmed
-- live (runbook docs/runbooks/media-sole-copy-protection.md §3 step 8):
-- at that point every sole-copy row is pinned and the new finalizer writes
-- pinned rows itself, so the guard is a no-op and is removed to restore
-- intentional unpinned-insert flexibility for the future durable pipeline
-- (outside Lots A/B).
--
-- Do NOT drop while a pre-Lot-A writer may still run. A rollback to the
-- old backend reintroduces unpinned writers: dropping early re-opens the
-- migration→swap window the guard was installed to close. If a rollback
-- happens after the drop, re-apply the guard file first (single
-- transaction, idempotent), then reconcile again. Already-pinned rows stay
-- pinned either way (fail-safe direction, same additive-only direction as
-- the stock migration, which never unpins).
--
-- Properties: IDEMPOTENT (IF EXISTS on both statements), single
-- transaction with bounded lock timeouts (same pattern as the install:
-- DROP takes a brief table lock, aborted fast instead of queueing), no row
-- removed from the table, no file touched. Safe to run whether or not the
-- guard is installed.
--
-- Real reinstall/teardown proof runs in CI on a disposable database:
-- backend/tests/test_postgres_media_guard.py.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DROP TRIGGER IF EXISTS trg_protect_browser_safe_cache_entries ON media_cache_entries;

DROP FUNCTION IF EXISTS protect_browser_safe_cache_entries_fn();

COMMIT;
