-- Working calendar (Task03). Additive and idempotent: safe to re-run.
-- Apply MANUALLY after add_calendar_domain.sql and before CALENDAR_ENABLED.
-- With the flag on but this file missing, /calendar answers 503 (schema
-- check), never a half-working feature.
-- Rollback: set CALENDAR_ENABLED=false; keep rows. No down migration.
BEGIN;

-- Following one event: a display preference that never grants access.
CREATE TABLE IF NOT EXISTS calendar_event_follows (
 event_id INTEGER NOT NULL REFERENCES calendar_events(id) ON DELETE CASCADE,
 user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
 created_at TIMESTAMP NOT NULL DEFAULT now(),
 PRIMARY KEY (event_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_calendar_event_follows_user ON calendar_event_follows (user_id);

-- Idempotent event creation: one key per actor; the request hash detects
-- reuse of a key for a different payload.
CREATE TABLE IF NOT EXISTS calendar_idempotency_keys (
 user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
 idempotency_key VARCHAR(80) NOT NULL,
 request_hash VARCHAR(64) NOT NULL,
 event_id INTEGER REFERENCES calendar_events(id) ON DELETE CASCADE,
 created_at TIMESTAMP NOT NULL DEFAULT now(),
 PRIMARY KEY (user_id, idempotency_key)
);

-- A member's explicit link between one of their own dives and an occurrence.
-- Private to the linking account; never changes dive/media visibility.
CREATE TABLE IF NOT EXISTS occurrence_dive_links (
 occurrence_id INTEGER NOT NULL REFERENCES event_occurrences(id) ON DELETE CASCADE,
 dive_id INTEGER NOT NULL REFERENCES dives(id) ON DELETE CASCADE,
 user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
 created_at TIMESTAMP NOT NULL DEFAULT now(),
 PRIMARY KEY (occurrence_id, dive_id)
);
CREATE INDEX IF NOT EXISTS ix_occurrence_dive_links_user ON occurrence_dive_links (user_id, occurrence_id);

-- Import review state: one source mapping can hold an unresolved item
-- (no target yet) with its review status.
ALTER TABLE calendar_source_mappings ADD COLUMN IF NOT EXISTS review_status VARCHAR(24);
DO $$ BEGIN
 ALTER TABLE calendar_source_mappings ADD CONSTRAINT ck_calendar_mapping_review
  CHECK (review_status IS NULL OR review_status IN ('needs_review', 'historical', 'conflict', 'missing_from_source', 'resolved'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- Indexed batch lookup: abandoned previews must not be loaded by apply.
ALTER TABLE calendar_import_runs ADD COLUMN IF NOT EXISTS batch_id VARCHAR(32);
UPDATE calendar_import_runs SET batch_id = summary->>'batch_id'
 WHERE batch_id IS NULL AND length(summary->>'batch_id') = 32;
CREATE INDEX IF NOT EXISTS ix_calendar_import_runs_batch_status
 ON calendar_import_runs (batch_id, status);

COMMIT;
