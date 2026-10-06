-- Fediverse opt-in (Option 1: manual cross-post only). Apply with the usual
-- operator migration procedure. Re-runnable / idempotent.
-- Additive only: the dives table is untouched, so dive reads keep working
-- before this migration is applied (endpoints report federated OFF until
-- the tables exist). No backfill: existing public dives stay unfederated
-- until each owner explicitly opts in globally AND per dive.
BEGIN;
CREATE TABLE IF NOT EXISTS user_fediverse_prefs (
    user_id INTEGER PRIMARY KEY REFERENCES app_users(id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS dive_fediverse_optins (
    dive_id INTEGER PRIMARY KEY REFERENCES dives(id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
COMMIT;
-- Rollback: deploy the previous code, then DROP TABLE dive_fediverse_optins
-- and DROP TABLE user_fediverse_prefs. Per-dive opt-ins are lost.
