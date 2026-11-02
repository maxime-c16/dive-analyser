-- add_notifications_unread_index.sql — unread inbox probes (PR 181 UX fixes).
--
-- Additive-only: the unread_only pages and their has_more probe carry the
-- `read_at IS NULL` keyset over (user_id, created_at, id). Without a
-- matching index, Postgres filters a growing read history on every unread
-- page request regardless of LIMIT. This partial index bounds those scans
-- to the (un)read subset the queries actually address; the laid-out
-- "all" pages keep using ix_notifications_user_created.
--
-- Idempotent; safe to re-apply. CREATE INDEX CONCURRENTLY cannot run inside
-- a transaction block: apply this file as a single-statement psql call
-- (no BEGIN/COMMIT wrapper) BEFORE deploying the backend that serves
-- notifications. ci/ship.sh does not run SQL — see docs/REPO_WORKFLOW.md.
-- Rollback (safe: the queries keep working, slower): DROP INDEX IF EXISTS
-- ix_notifications_user_unread_recent;
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_notifications_user_unread_recent
    ON notifications (user_id, created_at, id)
    WHERE read_at IS NULL;
