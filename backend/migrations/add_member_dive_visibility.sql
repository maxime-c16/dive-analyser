-- Apply BEFORE deploying member ownership/visibility code. Idempotent.
-- Existing attributed dives retain signed-in visibility; unowned dives are
-- quarantined. Administration is independent of diver ownership.
ALTER TABLE app_users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN;
UPDATE app_users SET is_admin = (role = 'owner') WHERE is_admin IS NULL;
ALTER TABLE app_users ALTER COLUMN is_admin SET DEFAULT false;
ALTER TABLE app_users ALTER COLUMN is_admin SET NOT NULL;

ALTER TABLE dives ADD COLUMN IF NOT EXISTS visibility VARCHAR(10);
UPDATE dives SET visibility = CASE WHEN diver_id IS NULL THEN 'private' ELSE 'public' END
WHERE visibility IS NULL;
ALTER TABLE dives ALTER COLUMN visibility SET DEFAULT 'public';
ALTER TABLE dives ALTER COLUMN visibility SET NOT NULL;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_dives_visibility') THEN
        ALTER TABLE dives ADD CONSTRAINT ck_dives_visibility
            CHECK (visibility IN ('public', 'private'));
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS ix_dives_visibility ON dives(visibility);
-- Rollback: deploy the previous code, then drop these two additive columns.
-- Visibility preferences are lost if the column is dropped; preserve a backup.
