-- Apply before deploying comment threads and reactions. Additive, re-runnable.
BEGIN;
ALTER TABLE dive_comments ADD COLUMN IF NOT EXISTS parent_id INTEGER REFERENCES dive_comments(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS ix_dive_comments_parent_id ON dive_comments(parent_id);
CREATE TABLE IF NOT EXISTS dive_comment_likes (
    comment_id INTEGER NOT NULL REFERENCES dive_comments(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    PRIMARY KEY (comment_id, user_id)
);
CREATE TABLE IF NOT EXISTS dive_guest_comment_likes (
    comment_id INTEGER NOT NULL REFERENCES dive_comments(id) ON DELETE CASCADE,
    guest_id INTEGER NOT NULL REFERENCES dive_guests(id) ON DELETE CASCADE,
    PRIMARY KEY (comment_id, guest_id)
);
COMMIT;
