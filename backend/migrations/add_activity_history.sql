-- Activity history: record when a like happened. Comments already carry
-- created_at; the four like tables predate the history feed and only store
-- identities. Additive and safe to re-run: existing rows keep NULL, which the
-- history endpoint treats as "unknown time" (sorted oldest).
BEGIN;
ALTER TABLE dive_likes ADD COLUMN IF NOT EXISTS created_at TIMESTAMP;
ALTER TABLE dive_guest_likes ADD COLUMN IF NOT EXISTS created_at TIMESTAMP;
ALTER TABLE dive_comment_likes ADD COLUMN IF NOT EXISTS created_at TIMESTAMP;
ALTER TABLE dive_guest_comment_likes ADD COLUMN IF NOT EXISTS created_at TIMESTAMP;
COMMIT;
-- Rollback (destroys like timestamps only):
--   ALTER TABLE dive_likes DROP COLUMN created_at;
--   ALTER TABLE dive_guest_likes DROP COLUMN created_at;
--   ALTER TABLE dive_comment_likes DROP COLUMN created_at;
--   ALTER TABLE dive_guest_comment_likes DROP COLUMN created_at;
