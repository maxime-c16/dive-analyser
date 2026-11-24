-- Official meet results on competition calendar events. Additive and
-- idempotent: safe to re-run. Apply MANUALLY after the calendar migrations
-- and before the backend that ships it. Without it, the results routes answer
-- 503 and the rest of the calendar is unaffected.
-- Rollback: keep the tables (no reader once the backend is rolled back).
-- No down migration.
BEGIN;

CREATE TABLE IF NOT EXISTS meet_results (
 id SERIAL PRIMARY KEY,
 calendar_event_id INTEGER NOT NULL UNIQUE REFERENCES calendar_events(id) ON DELETE CASCADE,
 source_name VARCHAR(200) NOT NULL,
 source_sha256 VARCHAR(64) NOT NULL,
 meet_date DATE,
 imported_by_user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
 imported_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS meet_result_events (
 id SERIAL PRIMARY KEY,
 result_id INTEGER NOT NULL REFERENCES meet_results(id) ON DELETE CASCADE,
 position INTEGER NOT NULL,
 title VARCHAR(200) NOT NULL,
 board VARCHAR(16) NOT NULL,
 CONSTRAINT uq_meet_result_event_position UNIQUE (result_id, position)
);

CREATE TABLE IF NOT EXISTS meet_result_entries (
 id SERIAL PRIMARY KEY,
 event_id INTEGER NOT NULL REFERENCES meet_result_events(id) ON DELETE CASCADE,
 position INTEGER NOT NULL,
 rank INTEGER,
 diver_name VARCHAR(120) NOT NULL,
 birth_year SMALLINT,
 club_name VARCHAR(120) NOT NULL,
 total NUMERIC(7, 2),
 status VARCHAR(16),
 guest BOOLEAN NOT NULL DEFAULT false,
 person_key VARCHAR(160),
 user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
 link_source VARCHAR(8),
 CONSTRAINT ck_meet_result_entry_link CHECK (link_source IS NULL OR link_source IN ('auto', 'admin')),
 CONSTRAINT uq_meet_result_entry_position UNIQUE (event_id, position),
 CONSTRAINT ck_meet_result_entry_status CHECK (status IS NULL OR status IN ('disqualified', 'withdrawn', 'knocked_out'))
);

CREATE INDEX IF NOT EXISTS ix_meet_result_entries_user ON meet_result_entries (user_id);
CREATE INDEX IF NOT EXISTS ix_meet_result_entries_person ON meet_result_entries (person_key);

-- Administrator link decisions, one per person across all meets. user_id
-- NULL = never link. Deleting the account deletes the decision.
CREATE TABLE IF NOT EXISTS meet_person_links (
 person_key VARCHAR(160) PRIMARY KEY,
 user_id INTEGER REFERENCES app_users(id) ON DELETE CASCADE,
 decided_by_user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
 decided_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_meet_person_links_user ON meet_person_links (user_id);

CREATE TABLE IF NOT EXISTS meet_result_dives (
 id SERIAL PRIMARY KEY,
 entry_id INTEGER NOT NULL REFERENCES meet_result_entries(id) ON DELETE CASCADE,
 position SMALLINT NOT NULL,
 dive_code VARCHAR(8) NOT NULL,
 height NUMERIC(3, 1) NOT NULL,
 dd NUMERIC(3, 1) NOT NULL,
 judge_half_steps JSON NOT NULL,
 cumul NUMERIC(5, 1) NOT NULL,
 points NUMERIC(6, 2) NOT NULL,
 running_total NUMERIC(7, 2) NOT NULL,
 penalty SMALLINT,
 CONSTRAINT uq_meet_result_dive_position UNIQUE (entry_id, position)
);

COMMIT;
