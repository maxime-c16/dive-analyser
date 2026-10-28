BEGIN;
-- Contract phase of the shared-session calendar rollout. Apply ONLY after
-- the backend shipping the predicated fallback upsert
-- (ON CONFLICT (date) WHERE calendar_occurrence_id IS NULL) is deployed
-- and verified: the previous backend's plain ON CONFLICT (date) upsert has
-- no matching constraint past this point, so every dive upload touching an
-- existing day fails until the new backend serves.
-- Idempotent and re-runnable. Needs backend/migrations/add_session_calendar.sql.
-- Same-date calendar sessions (two trainings filmed one day) are possible
-- only after this file; nothing creates them while SHARED_SESSIONS_ENABLED
-- is off.
-- Legacy date identity for ordinary dive days/fallback recordings stays
-- unique through uq_sessions_day_fallback.
ALTER TABLE sessions DROP CONSTRAINT IF EXISTS sessions_date_key;
DROP INDEX IF EXISTS ix_sessions_date;
CREATE INDEX IF NOT EXISTS ix_sessions_date ON sessions(date);
COMMIT;
-- App rollback: keep this schema and all data; do NOT restore global date
-- uniqueness while distinct occurrences share a day (the old backend cannot
-- serve such days — use a forward fix). No responses or recordings deleted.
