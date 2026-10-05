-- Apply after add_dive_social.sql, before deploying guest sharing. Re-runnable.
BEGIN;
CREATE TABLE IF NOT EXISTS dive_shares (
    id SERIAL PRIMARY KEY,
    dive_id INTEGER NOT NULL REFERENCES dives(id) ON DELETE CASCADE,
    created_by INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    video_uuid VARCHAR(255) NOT NULL,
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_dive_shares_dive_id ON dive_shares(dive_id);
CREATE TABLE IF NOT EXISTS dive_guests (
    id SERIAL PRIMARY KEY,
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    display_name VARCHAR(120) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS dive_guest_access (
    share_id INTEGER NOT NULL REFERENCES dive_shares(id) ON DELETE CASCADE,
    guest_id INTEGER NOT NULL REFERENCES dive_guests(id) ON DELETE CASCADE,
    PRIMARY KEY (share_id, guest_id)
);
CREATE TABLE IF NOT EXISTS dive_guest_likes (
    dive_id INTEGER NOT NULL REFERENCES dives(id) ON DELETE CASCADE,
    guest_id INTEGER NOT NULL REFERENCES dive_guests(id) ON DELETE CASCADE,
    PRIMARY KEY (dive_id, guest_id)
);
ALTER TABLE dive_comments ALTER COLUMN user_id DROP NOT NULL;
ALTER TABLE dive_comments ADD COLUMN IF NOT EXISTS guest_id INTEGER REFERENCES dive_guests(id) ON DELETE CASCADE;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_dive_comment_author' AND conrelid = 'dive_comments'::regclass) THEN
        ALTER TABLE dive_comments ADD CONSTRAINT ck_dive_comment_author CHECK ((user_id IS NULL) <> (guest_id IS NULL));
    END IF;
END $$;
COMMIT;
-- Rollback requires removing guest comments first, then restoring user_id NOT NULL
-- and dropping the guest_id column and the four new tables. This destroys guest data.
