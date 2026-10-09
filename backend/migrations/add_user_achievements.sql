-- add_user_achievements.sql — member achievements ledger.
--
-- Additive, idempotent. Apply manually on the server BEFORE deploying the
-- backend that serves /api/v1/users/me/achievements (ship.sh does not run it).
-- Rollback (loses unlock history): DROP TABLE IF EXISTS user_achievements;
BEGIN;

CREATE TABLE IF NOT EXISTS user_achievements (
    user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    key VARCHAR(64) NOT NULL,
    unlocked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    seen_at TIMESTAMP,
    PRIMARY KEY (user_id, key)
);
CREATE INDEX IF NOT EXISTS ix_user_achievements_user_unlocked
    ON user_achievements (user_id, unlocked_at);

COMMIT;
