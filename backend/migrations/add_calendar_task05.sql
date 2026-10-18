-- Reliable calendar alerts (Task05). Additive and idempotent: safe to re-run.
-- Apply MANUALLY after add_calendar_task04.sql (and add_notifications.sql)
-- and before CALENDAR_ENABLED / the alerts worker.
-- With the flag on but this file missing, /calendar answers 503 (schema check).
-- Rollback: stop the worker, set CALENDAR_ENABLED=false; keep rows for
-- investigation. No down migration.
BEGIN;

-- Durable outbox: one row per event per writing transaction, inserted in the
-- SAME transaction as the event write and its calendar_change_log rows
-- (change_log.outbox_id points here). invitee_ids lists invitations created
-- or renewed in that transaction. The worker expands a row into
-- per-recipient deliveries; it never sends from this table directly.
CREATE TABLE IF NOT EXISTS calendar_alert_outbox (
 id SERIAL PRIMARY KEY,
 event_id INTEGER NOT NULL REFERENCES calendar_events(id) ON DELETE CASCADE,
 actor_user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
 from_import BOOLEAN NOT NULL DEFAULT false,
 invitee_ids JSON NOT NULL DEFAULT '[]',
 status VARCHAR(16) NOT NULL DEFAULT 'pending',
 attempts INTEGER NOT NULL DEFAULT 0,
 next_attempt_at TIMESTAMP NOT NULL DEFAULT now(),
 lease_owner VARCHAR(64),
 lease_until TIMESTAMP,
 last_error VARCHAR(200),
 created_at TIMESTAMP NOT NULL DEFAULT now(),
 processed_at TIMESTAMP,
 CONSTRAINT ck_calendar_alert_outbox_status CHECK (status IN ('pending', 'done', 'dead'))
);
CREATE INDEX IF NOT EXISTS ix_calendar_alert_outbox_due ON calendar_alert_outbox (status, next_attempt_at);

ALTER TABLE calendar_change_log ADD COLUMN IF NOT EXISTS outbox_id INTEGER
 REFERENCES calendar_alert_outbox(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS ix_calendar_change_log_outbox ON calendar_change_log (outbox_id);

-- One row per (recipient, alert): the delivery key is unique, so a retried
-- expansion or reminder planning never creates a second delivery, and the
-- inbox row is linked by notification_id (unique), so one delivery key can
-- never produce two inbox rows. details holds change kinds and old/new
-- times only (no free text); titles/venues are resolved at read time.
-- target_start/target_version pin a reminder to the occurrence as planned:
-- a move or cancellation makes it obsolete before dispatch.
CREATE TABLE IF NOT EXISTS calendar_alert_deliveries (
 id SERIAL PRIMARY KEY,
 delivery_key VARCHAR(160) NOT NULL,
 kind VARCHAR(16) NOT NULL,
 notif_type VARCHAR(64) NOT NULL,
 user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
 event_id INTEGER NOT NULL REFERENCES calendar_events(id) ON DELETE CASCADE,
 occurrence_id INTEGER REFERENCES event_occurrences(id) ON DELETE CASCADE,
 outbox_id INTEGER REFERENCES calendar_alert_outbox(id) ON DELETE SET NULL,
 target_version INTEGER,
 target_start TIMESTAMP,
 details JSON NOT NULL DEFAULT '{}',
 due_at TIMESTAMP NOT NULL,
 expires_at TIMESTAMP NOT NULL,
 status VARCHAR(16) NOT NULL DEFAULT 'pending',
 attempts INTEGER NOT NULL DEFAULT 0,
 next_attempt_at TIMESTAMP NOT NULL,
 lease_owner VARCHAR(64),
 lease_until TIMESTAMP,
 last_error VARCHAR(200),
 suppressed_reason VARCHAR(32),
 notification_id INTEGER REFERENCES notifications(id) ON DELETE SET NULL,
 push_state VARCHAR(16),
 created_at TIMESTAMP NOT NULL DEFAULT now(),
 delivered_at TIMESTAMP,
 CONSTRAINT uq_calendar_alert_delivery_key UNIQUE (delivery_key),
 CONSTRAINT uq_calendar_alert_delivery_notification UNIQUE (notification_id),
 CONSTRAINT ck_calendar_alert_delivery_kind
  CHECK (kind IN ('invitation', 'change', 'cancellation', 'reminder', 'new_event')),
 CONSTRAINT ck_calendar_alert_delivery_status CHECK (status IN ('pending', 'delivered', 'suppressed', 'dead')),
 CONSTRAINT ck_calendar_alert_delivery_push
  CHECK (push_state IS NULL OR push_state IN ('pending', 'sent', 'skipped', 'expired'))
);
CREATE INDEX IF NOT EXISTS ix_calendar_alert_deliveries_due ON calendar_alert_deliveries (status, next_attempt_at);
CREATE INDEX IF NOT EXISTS ix_calendar_alert_deliveries_target
 ON calendar_alert_deliveries (event_id, occurrence_id, user_id);

-- Worker heartbeat and overlapping-run exclusion (a leased singleton row).
CREATE TABLE IF NOT EXISTS calendar_worker_state (
 name VARCHAR(64) PRIMARY KEY,
 lease_owner VARCHAR(64),
 lease_until TIMESTAMP,
 last_started_at TIMESTAMP,
 last_success_at TIMESTAMP,
 last_error VARCHAR(200),
 last_error_at TIMESTAMP,
 runs INTEGER NOT NULL DEFAULT 0,
 failures INTEGER NOT NULL DEFAULT 0,
 last_stats JSON NOT NULL DEFAULT '{}'
);
INSERT INTO calendar_worker_state (name) VALUES ('calendar-alerts') ON CONFLICT (name) DO NOTHING;

COMMIT;
