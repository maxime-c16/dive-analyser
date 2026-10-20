-- drop_protect_browser_safe_insert_guard.sql — Lot A guard teardown (P0).
--
-- Drops the transitional INSERT guard installed by backend/migrations/
-- protect_browser_safe_insert_guard.sql. Run ONCE, AFTER the post-deploy
-- reconciliation shows zero residual (runbook
-- docs/runbooks/media-sole-copy-protection.md §3 step 7): at that point
-- every sole-copy row is pinned and the new finalizer writes pinned rows
-- itself, so the guard is a no-op and is removed to restore intentional
-- unpinned-insert flexibility for the future durable pipeline (outside
-- Lots A/B).
--
-- Properties: IDEMPOTENT (IF EXISTS on both statements), no row deleted,
-- no file touched, already-pinned rows stay pinned (fail-safe). Safe to
-- run whether or not the guard is installed. If the deploy is reverted,
-- dropping is still safe: the old backend works with or without the guard.

DROP TRIGGER IF EXISTS trg_protect_browser_safe_cache_entries ON media_cache_entries;

DROP FUNCTION IF EXISTS protect_browser_safe_cache_entries_fn();
