-- Diver invitation links ("send a friend a signup link with their dives").
-- Apply BEFORE deploying the diver-invite code. Idempotent.
--
-- Model: an administrator mints a single-use link for a diver name that has
-- clips but no account yet. The friend opens the link, creates their account
-- on the dedicated /invite page, and arrives already bound OWNER of that
-- diver (their pre-tied dives follow the existing UserDiverAccess contract).
--
-- This is the one deliberate exception to "registration never captures a real
-- diver name" (auth.py register mints a member-<id>-<hex> placeholder): the
-- administrator explicitly named the diver, which is the whole point.
--
-- Security contract (mirrors claim_tokens and user_sessions):
--   * the raw token is CSPRNG 256-bit, URL-safe, returned exactly once (it
--     travels in the email URL fragment so it never reaches server logs);
--   * the DB stores ONLY its SHA-256 hex;
--   * single-use (used_at) with a conditional UPDATE at redeem, so concurrent
--     redemptions serialize and exactly one wins;
--   * short expiry (DIVER_INVITE_TTL_SECONDS, default 7 days);
--   * revocable by the administrator at any time before use (revoked_at).
-- The link is a pure bearer credential: anyone holding it may complete the
-- signup. Keep TTLs short and revoke links you do not recognise.
--
-- Reversibility: DROP TABLE diver_invites; no other table is touched.

BEGIN;

CREATE TABLE IF NOT EXISTS diver_invites (
    id SERIAL PRIMARY KEY,
    diver_id INTEGER NOT NULL REFERENCES divers(id) ON DELETE CASCADE,
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    created_by_user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
    expires_at TIMESTAMP NOT NULL,
    used_at TIMESTAMP,
    revoked_at TIMESTAMP,
    user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- The admin panel lists outstanding invites per diver and scans the
-- unclaimed diver directory; both want the diver index.
CREATE INDEX IF NOT EXISTS ix_diver_invites_diver ON diver_invites(diver_id);
-- Listing "outstanding" (not used, not revoked, not expired) is the hot path.
CREATE INDEX IF NOT EXISTS ix_diver_invites_live ON diver_invites(diver_id, used_at, revoked_at);

COMMIT;
