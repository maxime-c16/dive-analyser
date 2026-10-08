-- Apply BEFORE deploying profiles/discovery. Additive and re-runnable.
BEGIN;
ALTER TABLE app_users ADD COLUMN IF NOT EXISTS handle VARCHAR(30);
ALTER TABLE app_users ADD COLUMN IF NOT EXISTS bio VARCHAR(500) NOT NULL DEFAULT '';
ALTER TABLE app_users ADD COLUMN IF NOT EXISTS avatar BYTEA;
ALTER TABLE app_users ADD COLUMN IF NOT EXISTS avatar_updated_at TIMESTAMP;
CREATE UNIQUE INDEX IF NOT EXISTS uq_app_users_handle ON app_users(handle);
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_app_users_handle'
                   AND conrelid = 'app_users'::regclass) THEN
        ALTER TABLE app_users ADD CONSTRAINT ck_app_users_handle
            CHECK (handle IS NULL OR handle ~ '^[a-z0-9_]{3,30}$') NOT VALID;
    END IF;
END $$;
ALTER TABLE app_users VALIDATE CONSTRAINT ck_app_users_handle;
COMMIT;
