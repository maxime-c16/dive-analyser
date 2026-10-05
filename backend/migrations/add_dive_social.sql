-- Apply before deploying the immersive player. Additive, safe to re-run.
BEGIN;
CREATE TABLE IF NOT EXISTS dive_likes (
    dive_id INTEGER NOT NULL REFERENCES dives(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    PRIMARY KEY (dive_id, user_id)
);
CREATE TABLE IF NOT EXISTS dive_comments (
    id SERIAL PRIMARY KEY,
    dive_id INTEGER NOT NULL REFERENCES dives(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    body VARCHAR(2000) NOT NULL CONSTRAINT ck_dive_comment_length CHECK (length(body) BETWEEN 1 AND 2000),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_dive_comments_dive_id ON dive_comments(dive_id);
COMMIT;
-- Rollback (destroys reactions/discussion): DROP TABLE dive_comments, dive_likes;
