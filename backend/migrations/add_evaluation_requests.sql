-- Community evaluation requests (issue #66, ticket 1/3).
-- One request per dive; votes (ticket 2) cascade from the request.
-- Re-runnable / idempotent. Additive only: the dives table is untouched, so
-- dive reads keep working before this migration is applied — the Library
-- summary reads as null and writes fail closed with 503 until tables exist.
BEGIN;
CREATE TABLE IF NOT EXISTS evaluation_requests (
    id SERIAL PRIMARY KEY,
    dive_id INTEGER NOT NULL UNIQUE REFERENCES dives(id) ON DELETE CASCADE,
    active BOOLEAN NOT NULL DEFAULT FALSE,
    prompt VARCHAR(1000),
    created_by_user_id INTEGER NOT NULL REFERENCES app_users(id),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_evaluation_request_prompt CHECK (prompt IS NULL OR length(prompt) <= 1000)
);
CREATE INDEX IF NOT EXISTS idx_evaluation_requests_active ON evaluation_requests(active);
COMMIT;
-- Rollback: deploy the previous code, then
-- DROP TABLE IF EXISTS evaluation_requests. Requests are lost; votes
-- (evaluation_ratings, ticket 2) do not exist yet at this stage.
