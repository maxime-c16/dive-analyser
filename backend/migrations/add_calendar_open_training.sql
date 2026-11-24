-- Club open-training windows before competitions (e.g. advanced group
-- allowed to attend any club group session during the two calendar weeks
-- before a federal competition). Additive and idempotent: safe to re-run.
-- Apply MANUALLY after the calendar migrations and before the backend that
-- uses it. Without it, the opening routes answer 503 and the rest of the
-- calendar keeps working unchanged.
-- Rollback: keep the table (no reader once the backend is rolled back).
-- No down migration.
BEGIN;

CREATE TABLE IF NOT EXISTS club_training_openings (
 id SERIAL PRIMARY KEY,
 club_id INTEGER NOT NULL REFERENCES clubs(id) ON DELETE RESTRICT,
 eligible_group_id INTEGER NOT NULL,
 competition_event_id INTEGER REFERENCES calendar_events(id) ON DELETE SET NULL,
 label VARCHAR(200),
 starts_on DATE NOT NULL,
 ends_on DATE NOT NULL,
 window_start TIMESTAMP NOT NULL,
 window_end TIMESTAMP NOT NULL,
 created_by_user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
 created_at TIMESTAMP NOT NULL DEFAULT now(),
 CONSTRAINT fk_training_opening_group_club
  FOREIGN KEY (eligible_group_id, club_id) REFERENCES training_groups(id, club_id) ON DELETE RESTRICT,
 CONSTRAINT ck_training_opening_dates CHECK (ends_on >= starts_on),
 CONSTRAINT ck_training_opening_window CHECK (window_end > window_start)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_training_opening_comp_group
 ON club_training_openings (club_id, eligible_group_id, competition_event_id)
 WHERE competition_event_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_training_openings_club_window
 ON club_training_openings (club_id, window_start, window_end);

CREATE INDEX IF NOT EXISTS ix_training_openings_event
 ON club_training_openings (competition_event_id)
 WHERE competition_event_id IS NOT NULL;

COMMIT;
