BEGIN;
ALTER TABLE session_videos ADD COLUMN IF NOT EXISTS hidden boolean NOT NULL DEFAULT false;
ALTER TABLE session_videos ADD COLUMN IF NOT EXISTS deleted_at timestamp;
ALTER TABLE session_video_shares ADD COLUMN IF NOT EXISTS session_id integer REFERENCES sessions(id) ON DELETE CASCADE;
UPDATE session_video_shares sh SET session_id = v.session_id FROM session_videos v WHERE sh.session_video_id=v.id AND sh.session_id IS NULL;
CREATE INDEX IF NOT EXISTS ix_session_video_shares_session_id ON session_video_shares(session_id);
ALTER TABLE app_users DROP CONSTRAINT IF EXISTS ck_app_users_role;
ALTER TABLE app_users ADD CONSTRAINT ck_app_users_role CHECK (role IN ('owner','friend','diver'));
ALTER TABLE app_users ADD COLUMN IF NOT EXISTS session_email_enabled boolean NOT NULL DEFAULT true;
CREATE TABLE IF NOT EXISTS session_signup_reviews (
 id serial PRIMARY KEY, user_id integer NOT NULL UNIQUE REFERENCES app_users(id) ON DELETE CASCADE,
 candidate_diver_id integer NOT NULL REFERENCES divers(id), resolved_at timestamp
);
COMMIT;
