-- Fediverse opt-in (Option 1: manual cross-post only). Apply with the usual
-- operator migration procedure. Re-runnable / idempotent.
-- No backfill: existing public dives stay unfederated until each owner
-- explicitly opts in globally AND per dive.
BEGIN;
CREATE TABLE IF NOT EXISTS user_fediverse_prefs (
    user_id INTEGER PRIMARY KEY REFERENCES app_users(id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE dives ADD COLUMN IF NOT EXISTS federate_enabled BOOLEAN;
UPDATE dives SET federate_enabled = FALSE WHERE federate_enabled IS NULL;
ALTER TABLE dives ALTER COLUMN federate_enabled SET DEFAULT FALSE;
ALTER TABLE dives ALTER COLUMN federate_enabled SET NOT NULL;
CREATE INDEX IF NOT EXISTS ix_dives_federate_enabled ON dives(federate_enabled);
COMMIT;
-- Rollback: deploy the previous code, then DROP TABLE user_fediverse_prefs
-- and DROP COLUMN dives.federate_enabled. Per-dive opt-ins are lost.
