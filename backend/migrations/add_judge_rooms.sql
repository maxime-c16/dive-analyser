-- Apply manually before backend deployment. Additive; no startup migration.
CREATE TABLE IF NOT EXISTS judge_room_results (
 id VARCHAR(32) PRIMARY KEY, code VARCHAR(4) NOT NULL, mode VARCHAR(16) NOT NULL,
 result TEXT, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS judge_room_ratings (
 id SERIAL PRIMARY KEY, room_id VARCHAR(32) NOT NULL REFERENCES judge_room_results(id),
 dive_id INTEGER NOT NULL REFERENCES dives(id) ON DELETE CASCADE,
 player_id VARCHAR(64) NOT NULL, user_id INTEGER REFERENCES app_users(id), nickname VARCHAR(40) NOT NULL,
 score_half_steps INTEGER NOT NULL CHECK(score_half_steps BETWEEN 0 AND 20),
 dive_code VARCHAR(10) NOT NULL, height VARCHAR(5) NOT NULL,
 UNIQUE(room_id, dive_id, player_id)
);
CREATE TABLE IF NOT EXISTS judge_shadow_preferences (
 user_id INTEGER PRIMARY KEY REFERENCES app_users(id) ON DELETE CASCADE,
 enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0, 1))
);
INSERT INTO judge_shadow_preferences (user_id, enabled)
SELECT id, 1 FROM app_users WHERE id = 1 ON CONFLICT (user_id) DO NOTHING;
