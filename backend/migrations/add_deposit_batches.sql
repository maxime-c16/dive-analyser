-- Deposit batches with owner acceptance ("Récupérer mes plongeons").
-- Apply BEFORE deploying the deposit-batch code. Idempotent.
--
-- Model: the mac-agent (or an admin on behalf) deposits clips. Dives whose
-- diver belongs to another account stay private + pending (accepted_at NULL)
-- until the owner accepts them one by one (or all at once) from the review
-- page. The depositor keeps access to their own deposits; admins see every
-- pending batch for triage. One batch email per diver goes out through
-- batch_email_outbox (sent by backend/scripts/send_batch_emails.py).
BEGIN;
ALTER TABLE dives ADD COLUMN IF NOT EXISTS batch_id VARCHAR(36);
ALTER TABLE dives ADD COLUMN IF NOT EXISTS accepted_at TIMESTAMP;
ALTER TABLE dives ADD COLUMN IF NOT EXISTS deposited_by_user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS ix_dives_batch_id ON dives(batch_id);
CREATE INDEX IF NOT EXISTS ix_dives_deposited_by ON dives(deposited_by_user_id);
CREATE INDEX IF NOT EXISTS ix_dives_pending_acceptance ON dives(diver_id, accepted_at);
-- Pre-existing dives predate acceptance: everything already in the library
-- counts as accepted (accepted_at stays advisory; visibility authoritative).
UPDATE dives SET accepted_at = COALESCE(synced_at, created_at, CURRENT_TIMESTAMP)
WHERE accepted_at IS NULL;

-- Maintainer note attached at deposit time. score_half_steps stays NULL for
-- a note-only evaluation (0-20 when the maintainer also scores); the eval
-- jury stack (PRs #72-#76) can adopt these rows as comment-first ratings.
CREATE TABLE IF NOT EXISTS evaluator_notes (
    id SERIAL PRIMARY KEY,
    dive_id INTEGER NOT NULL UNIQUE REFERENCES dives(id) ON DELETE CASCADE,
    author_user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    score_half_steps INTEGER,
    comment TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_evaluator_note_score CHECK (score_half_steps IS NULL OR (score_half_steps >= 0 AND score_half_steps <= 20)),
    CONSTRAINT ck_evaluator_note_content CHECK (comment IS NOT NULL OR score_half_steps IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS ix_evaluator_notes_dive ON evaluator_notes(dive_id);

-- Single-purpose magic-link tokens ("Récupérer mes plongeons" email button).
-- Redeeming mints a normal user session; the raw token is never stored.
CREATE TABLE IF NOT EXISTS claim_tokens (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    batch_id VARCHAR(36) NOT NULL,
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    created_by_user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
    expires_at TIMESTAMP NOT NULL,
    used_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_claim_tokens_batch ON claim_tokens(batch_id);

-- One email per (batch, recipient). Dive membership is derived at send time
-- (dives of the batch+diver still pending), so late-arriving clips join the
-- same email instead of spawning a new one.
CREATE TABLE IF NOT EXISTS batch_email_outbox (
    id SERIAL PRIMARY KEY,
    batch_id VARCHAR(36) NOT NULL,
    diver_id INTEGER NOT NULL REFERENCES divers(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    scheduled_for TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMP,
    error TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_batch_email_status CHECK (status IN ('pending', 'sent', 'failed')),
    CONSTRAINT uq_batch_email_recipient UNIQUE (batch_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_batch_email_due ON batch_email_outbox(status, scheduled_for);
COMMIT;
-- Rollback: deploy the previous code, then DROP TABLE batch_email_outbox,
-- claim_tokens, evaluator_notes and DROP COLUMN dives.batch_id/accepted_at/
-- deposited_by_user_id. Pending-acceptance state is lost; accepted dives stay
-- untouched (accepted_at is advisory, visibility is authoritative).
