BEGIN;
-- Keep all historical RSVP rows. Only declined still means absence.
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS calendar_occurrence_id integer REFERENCES event_occurrences(id) ON DELETE RESTRICT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS calendar_notified_at timestamp;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS calendar_notify_cursor integer NOT NULL DEFAULT 0;
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS session_id integer REFERENCES sessions(id) ON DELETE SET NULL;
-- Legacy date identity remains unique for ordinary dive days/fallback recordings.
ALTER TABLE sessions DROP CONSTRAINT IF EXISTS sessions_date_key;
DROP INDEX IF EXISTS ix_sessions_date;
CREATE INDEX IF NOT EXISTS ix_sessions_date ON sessions(date);
CREATE UNIQUE INDEX IF NOT EXISTS uq_sessions_calendar_occurrence_id ON sessions(calendar_occurrence_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_sessions_day_fallback ON sessions(date) WHERE calendar_occurrence_id IS NULL;
COMMIT;
-- App rollback: keep additive schema and all data; do not restore date uniqueness
-- while distinct occurrences share a day. No responses or recordings are deleted.
