-- Recurrent schedules and camps (Task04). Additive and idempotent: safe to re-run.
-- Apply MANUALLY after add_calendar_task03.sql and before CALENDAR_ENABLED.
-- With the flag on but this file missing, /calendar answers 503 (schema check).
-- Rollback: set CALENDAR_ENABLED=false; keep rows. No down migration.
BEGIN;

-- Weekly pattern of an app-created series. Occurrences are materialized in
-- full when the pattern is saved (bounded season, no background worker);
-- event_occurrences remain the source of truth for every date.
-- weekdays: ISO bitmask, bit 0 = Monday ... bit 6 = Sunday.
-- Local wall times in calendar_events.timezone; pattern_from is the first
-- date the current pattern applies to (earlier dates keep their history).
CREATE TABLE IF NOT EXISTS calendar_event_recurrences (
 event_id INTEGER PRIMARY KEY REFERENCES calendar_events(id) ON DELETE CASCADE,
 weekdays SMALLINT NOT NULL,
 start_time TIME NOT NULL,
 end_time TIME NOT NULL,
 first_date DATE NOT NULL,
 until_date DATE NOT NULL,
 pattern_from DATE NOT NULL,
 created_at TIMESTAMP NOT NULL DEFAULT now(),
 updated_at TIMESTAMP NOT NULL DEFAULT now(),
 CONSTRAINT ck_recurrence_weekdays CHECK (weekdays BETWEEN 1 AND 127),
 CONSTRAINT ck_recurrence_times CHECK (end_time > start_time),
 CONSTRAINT ck_recurrence_dates CHECK (until_date >= first_date AND until_date - first_date <= 400),
 CONSTRAINT ck_recurrence_pattern_from CHECK (pattern_from >= first_date AND pattern_from <= until_date)
);

-- Dates the pattern skips (holidays, pool closures). Durable: kept across
-- every later edit; never deleted by regeneration.
CREATE TABLE IF NOT EXISTS calendar_recurrence_exclusions (
 event_id INTEGER NOT NULL REFERENCES calendar_events(id) ON DELETE CASCADE,
 local_date DATE NOT NULL,
 created_by_user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
 created_at TIMESTAMP NOT NULL DEFAULT now(),
 PRIMARY KEY (event_id, local_date)
);

-- series_date: the pattern slot an occurrence fills (moves within a week
-- keep the row, its id and its responses). detached: edited "this session
-- only", so later pattern edits never overwrite it.
ALTER TABLE event_occurrences ADD COLUMN IF NOT EXISTS series_date DATE;
ALTER TABLE event_occurrences ADD COLUMN IF NOT EXISTS detached BOOLEAN NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS ix_occurrences_series ON event_occurrences (event_id, series_date);

-- Camp itinerary: informational blocks (day, local times, venue) inside one
-- whole-camp event. Not separately bookable: interest stays on the camp.
CREATE TABLE IF NOT EXISTS event_itinerary_items (
 id SERIAL PRIMARY KEY,
 event_id INTEGER NOT NULL REFERENCES calendar_events(id) ON DELETE CASCADE,
 position SMALLINT NOT NULL,
 local_date DATE NOT NULL,
 start_time TIME,
 end_time TIME,
 venue_name VARCHAR(200),
 label VARCHAR(200),
 CONSTRAINT uq_itinerary_position UNIQUE (event_id, position),
 CONSTRAINT ck_itinerary_times CHECK (start_time IS NULL OR end_time IS NULL OR end_time > start_time)
);

COMMIT;
