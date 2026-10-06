-- Community evaluation ratings and jury sessions (issue #67, ticket 2/3).
-- Votes are immutable (one per account/request), sessions are per account with
-- 24 h expiry, session proposals mark queue allocation. Everything cascades
-- from dives → requests → votes. Re-runnable / idempotent, additive only.
BEGIN;
CREATE TABLE IF NOT EXISTS evaluation_ratings (
    id SERIAL PRIMARY KEY,
    request_id INTEGER NOT NULL REFERENCES evaluation_requests(id) ON DELETE CASCADE,
    evaluator_user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    score_half_steps INTEGER NOT NULL,
    comment VARCHAR(2000),
    dive_code VARCHAR(10) NOT NULL,
    height VARCHAR(5) NOT NULL,
    platform_type VARCHAR(20) NOT NULL,
    dive_name VARCHAR(100) NOT NULL,
    prompt_snapshot VARCHAR(1000),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_evaluation_rating_once UNIQUE (request_id, evaluator_user_id),
    CONSTRAINT ck_evaluation_rating_score CHECK (score_half_steps >= 0 AND score_half_steps <= 20),
    CONSTRAINT ck_evaluation_rating_comment CHECK (comment IS NULL OR length(comment) BETWEEN 1 AND 2000)
);
CREATE INDEX IF NOT EXISTS idx_evaluation_ratings_request_votes ON evaluation_ratings(request_id, score_half_steps);
CREATE INDEX IF NOT EXISTS idx_evaluation_ratings_evaluator ON evaluation_ratings(evaluator_user_id, created_at);

CREATE TABLE IF NOT EXISTS evaluation_sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    client_session_id VARCHAR(64) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    revoked_at TIMESTAMP,
    CONSTRAINT uq_evaluation_session_client UNIQUE (client_session_id)
);
CREATE INDEX IF NOT EXISTS idx_evaluation_sessions_user ON evaluation_sessions(user_id, expires_at);

CREATE TABLE IF NOT EXISTS evaluation_session_requests (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES evaluation_sessions(id) ON DELETE CASCADE,
    request_id INTEGER NOT NULL REFERENCES evaluation_requests(id) ON DELETE CASCADE,
    batch_id VARCHAR(64) NOT NULL,
    state VARCHAR(16) NOT NULL DEFAULT 'proposed',
    proposed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_evaluation_session_request UNIQUE (session_id, request_id),
    CONSTRAINT ck_evaluation_session_request_state CHECK (state IN ('proposed', 'skipped'))
);
CREATE INDEX IF NOT EXISTS idx_evaluation_session_requests_batch ON evaluation_session_requests(session_id, batch_id);
COMMIT;
-- Rollback: deploy the previous code, then
-- DROP TABLE IF EXISTS evaluation_session_requests;
-- DROP TABLE IF EXISTS evaluation_sessions;
-- DROP TABLE IF EXISTS evaluation_ratings. Votes are lost (owner archives).
