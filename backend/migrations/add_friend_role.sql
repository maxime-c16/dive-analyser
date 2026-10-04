-- add_friend_role.sql — FRIEND USER ACCESS (invite-gated, read-only).
--
-- Scope: the smallest additive change that opens the app to friends while
-- keeping the owner surface untouched:
--   app_users.role — 'owner' (default, existing behaviour) or 'friend'.
--                    Friends self-register with an invite code, see every
--                    diver's dives/media by default, and are read-only at the
--                    API boundary (no explicit user_diver_access rows needed).
--
-- Authorization recap (unchanged for owners):
--   owners keep the explicit user_diver_access OWNER bindings enforced by
--   the central policy in app/services/user_access.py. Friends bypass the
--   per-diver binding check (any existing media revision is viewable) but
--   are denied every state-changing browser route except viewing-support
--   calls (media request / viewed telemetry) — see
--   app/services/write_guard.py.
--
-- REVERSIBILITY: the column is standalone; pre-change state returns via
--   ALTER TABLE app_users DROP COLUMN role;
-- No legacy table is otherwise altered. NO data row is deleted/rewritten
-- (existing users backfill to 'owner').
--
-- IDEMPOTENT: safe to re-run (guarded DO blocks).

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'app_users' AND column_name = 'role'
    ) THEN
        ALTER TABLE app_users
            ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'owner';
    END IF;
END
$$;

-- Existing users predate roles: they are all owners.
UPDATE app_users SET role = 'owner' WHERE role IS NULL OR role NOT IN ('owner', 'friend');

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_app_users_role'
    ) THEN
        ALTER TABLE app_users
            ADD CONSTRAINT ck_app_users_role CHECK (role IN ('owner', 'friend'));
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS ix_app_users_role
    ON app_users (role);
