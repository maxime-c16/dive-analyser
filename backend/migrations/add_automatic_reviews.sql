-- Additive, safe to apply before deploying the application. No existing votes
-- or requests are changed. Daily keys use UTC; skips cool down for seven days.
BEGIN;
CREATE TABLE IF NOT EXISTS review_exclusions (
 dive_id INTEGER PRIMARY KEY REFERENCES dives(id) ON DELETE CASCADE,
 excluded BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE TABLE IF NOT EXISTS review_stacks (
 id SERIAL PRIMARY KEY,
 user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
 key VARCHAR(80) NOT NULL,
 created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
 CONSTRAINT uq_review_stack_key UNIQUE(user_id, key)
);
CREATE INDEX IF NOT EXISTS ix_review_stacks_user_id ON review_stacks(user_id);
CREATE TABLE IF NOT EXISTS review_stack_items (
 id SERIAL PRIMARY KEY,
 stack_id INTEGER NOT NULL REFERENCES review_stacks(id) ON DELETE CASCADE,
 dive_id INTEGER NOT NULL REFERENCES dives(id) ON DELETE CASCADE,
 position INTEGER NOT NULL,
 skipped_at TIMESTAMP,
 CONSTRAINT uq_review_stack_dive UNIQUE(stack_id, dive_id)
);
CREATE INDEX IF NOT EXISTS ix_review_stack_items_stack_id ON review_stack_items(stack_id);
CREATE INDEX IF NOT EXISTS ix_review_stack_items_dive_id ON review_stack_items(dive_id);
CREATE TABLE IF NOT EXISTS automatic_ratings (
 id SERIAL PRIMARY KEY,
 dive_id INTEGER NOT NULL REFERENCES dives(id) ON DELETE CASCADE,
 evaluator_user_id INTEGER NOT NULL REFERENCES app_users(id),
 score_half_steps INTEGER NOT NULL CHECK(score_half_steps BETWEEN 0 AND 20),
 comment VARCHAR(2000) CHECK(comment IS NULL OR length(comment) BETWEEN 1 AND 2000),
 dive_code VARCHAR(10) NOT NULL,
 height VARCHAR(5) NOT NULL,
 platform_type VARCHAR(20),
 dive_name VARCHAR(100) NOT NULL,
 video_uuid VARCHAR(100) NOT NULL,
 created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
 CONSTRAINT uq_automatic_rating_once UNIQUE(dive_id, evaluator_user_id)
);
CREATE INDEX IF NOT EXISTS ix_automatic_ratings_dive_id ON automatic_ratings(dive_id);
CREATE INDEX IF NOT EXISTS ix_automatic_ratings_evaluator_user_id ON automatic_ratings(evaluator_user_id);
COMMIT;
