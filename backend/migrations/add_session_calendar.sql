BEGIN;
-- Keep all historical RSVP rows. Only declined still means absence.
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS calendar_occurrence_id integer REFERENCES event_occurrences(id) ON DELETE RESTRICT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS calendar_notified_at timestamp;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS calendar_notify_cursor integer NOT NULL DEFAULT 0;
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS session_id integer REFERENCES sessions(id) ON DELETE SET NULL;
-- Expand phase (online-safe): add the new partial identities WITHOUT dropping
-- the legacy global date uniqueness. The deployed backend's
-- ON CONFLICT (date) upsert keeps matching sessions_date_key, and the new
-- backend's predicated upsert already matches uq_sessions_day_fallback, so
-- both backends work with this schema. Same-date calendar sessions are NOT
-- possible yet (global uniqueness still enforced); nothing creates them
-- while SHARED_SESSIONS_ENABLED is off.
-- Contract phase: backend/migrations/add_session_calendar_drop_legacy.sql,
-- applied AFTER the new backend is verified (before any same-date filming).
CREATE INDEX IF NOT EXISTS ix_sessions_date ON sessions(date);
CREATE UNIQUE INDEX IF NOT EXISTS uq_sessions_calendar_occurrence_id ON sessions(calendar_occurrence_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_sessions_day_fallback ON sessions(date) WHERE calendar_occurrence_id IS NULL;
COMMIT;
-- App rollback: keep additive schema and all data. The legacy uniqueness was
-- never dropped here, so a rollback needs no schema change for uploads.
