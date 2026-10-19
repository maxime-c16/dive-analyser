BEGIN;
CREATE TABLE IF NOT EXISTS calendar_launch_control (
    id INTEGER PRIMARY KEY CONSTRAINT ck_calendar_launch_singleton CHECK (id = 1),
    enabled BOOLEAN,
    changed_by_user_id INTEGER REFERENCES app_users(id),
    changed_at TIMESTAMP WITHOUT TIME ZONE,
    accepted_checks JSON NOT NULL DEFAULT '{}',
    probe_count INTEGER NOT NULL DEFAULT 0,
    last_probe_at TIMESTAMP WITHOUT TIME ZONE
);
-- NULL preserves existing installations' environment setting until the first
-- explicit administrator launch/pause. Never enable a calendar by migrating.
INSERT INTO calendar_launch_control (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
COMMIT;
