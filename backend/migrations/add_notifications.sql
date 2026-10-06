-- add_notifications.sql — backend notification foundation (PR1).
--
-- Additive, idempotent (IF NOT EXISTS everywhere). Apply manually before
-- deploying the backend that serves /api/v1/notifications.
--
-- Tables:
--   notifications      — per-user durable inbox (PR1 readers + prefs API).
--   push_subscriptions — WebPush endpoints (schema fixed in PR1; API in PR3).
--   notification_prefs — per-user per-type opt-outs (defaults applied in code).
--
-- Transaction: BEGIN/COMMIT below. Safe to re-run.
-- Rollback (destroys the inbox): DROP TABLE IF EXISTS notification_prefs;
--   DROP TABLE IF EXISTS push_subscriptions; DROP TABLE IF EXISTS notifications;
BEGIN;

CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    type VARCHAR(64) NOT NULL,
    title VARCHAR(200) NOT NULL,
    body VARCHAR(600),
    dive_id INTEGER REFERENCES dives(id) ON DELETE CASCADE,
    read_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_notifications_user_created
    ON notifications (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS push_subscriptions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    endpoint TEXT NOT NULL UNIQUE,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    device_label VARCHAR(100),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_push_subscriptions_user
    ON push_subscriptions (user_id);

CREATE TABLE IF NOT EXISTS notification_prefs (
    user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    notif_type VARCHAR(64) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (user_id, notif_type)
);

COMMIT;
-- Rollback (destroys the inbox): DROP TABLE IF EXISTS notification_prefs;
--   DROP TABLE IF EXISTS push_subscriptions; DROP TABLE IF EXISTS notifications;
