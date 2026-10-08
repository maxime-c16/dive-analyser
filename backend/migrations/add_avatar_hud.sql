-- Requires add_member_profiles.sql from PR #91. Apply before deployment.
BEGIN;
ALTER TABLE app_users ADD COLUMN IF NOT EXISTS avatar_hud VARCHAR(16) NOT NULL DEFAULT 'reticle';
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_app_users_avatar_hud'
                   AND conrelid = 'app_users'::regclass) THEN
        ALTER TABLE app_users ADD CONSTRAINT ck_app_users_avatar_hud
            CHECK (avatar_hud IN ('orbit', 'reticle', 'depth'));
    END IF;
END $$;
COMMIT;
