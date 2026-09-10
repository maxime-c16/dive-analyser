-- add_user_auth_tables.sql — DIVE_ANALYZER_MEDIA_BACKBONE_V1 (P5)
-- USER AUTHENTICATION + OWNERSHIP LAYER.
--
-- Scope (P5 V1): the smallest production-grade USER authentication layer
-- required for secure B2 playback:
--   app_users            — browser users (no public signup; provisioned by
--                          the operator bootstrap CLI only)
--   user_credentials     — Argon2id password verifiers (never plaintext,
--                          never reversible; one credential row per user)
--   user_sessions        — SERVER-SIDE OPAQUE sessions: the browser cookie
--                          carries only a cryptographically random raw
--                          token; the DB stores only its SHA-256 hash
--   user_diver_access    — durable user→diver authorization binding
--                          (P5 V1: access_kind='OWNER' only)
--   login_attempts       — bounded brute-force protection ledger
--   media_playback_grants— privacy-safe playback grant ledger (no URLs,
--                          no signatures; ids + outcomes only, for the
--                          P5 cohort metrics)
--
-- Authorization is EXPLICIT: is_primary_user on divers is descriptive and
-- must never authenticate a browser user. Media→diver ownership uses the
-- existing deterministic chain media_revisions.video_uuid → dives.video_uuid
-- (unique) → dives.diver_id; NO additive media ownership table is needed
-- while that chain holds (verified fresh on the P5-PRE audit).
--
-- REVERSIBILITY: each table is standalone; the full pre-P5 state returns via
--   DROP TABLE IF EXISTS media_playback_grants;
--   DROP TABLE IF EXISTS login_attempts;
--   DROP TABLE IF EXISTS user_diver_access;
--   DROP TABLE IF EXISTS user_sessions;
--   DROP TABLE IF EXISTS user_credentials;
--   DROP TABLE IF EXISTS app_users;
-- No legacy table is altered. NO data row is deleted or rewritten.
--
-- IDEMPOTENT: safe to re-run (IF NOT EXISTS everywhere).

CREATE TABLE IF NOT EXISTS app_users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    display_name VARCHAR(120) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_app_users_email
    ON app_users (lower(email));
CREATE INDEX IF NOT EXISTS ix_app_users_active
    ON app_users (is_active);

CREATE TABLE IF NOT EXISTS user_credentials (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES app_users(id) ON DELETE CASCADE,
    password_hash TEXT NOT NULL,
    password_algo VARCHAR(40) NOT NULL DEFAULT 'argon2id',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_user_credentials_user
    ON user_credentials (user_id);

CREATE TABLE IF NOT EXISTS user_sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    token_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL,
    revoked_at TIMESTAMP,
    last_used_at TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_user_sessions_token_hash
    ON user_sessions (token_hash);
CREATE INDEX IF NOT EXISTS ix_user_sessions_user
    ON user_sessions (user_id);
CREATE INDEX IF NOT EXISTS ix_user_sessions_expires
    ON user_sessions (expires_at);

CREATE TABLE IF NOT EXISTS user_diver_access (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    diver_id INTEGER NOT NULL REFERENCES divers(id) ON DELETE CASCADE,
    access_kind VARCHAR(20) NOT NULL DEFAULT 'OWNER',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_user_diver_access_unique
    ON user_diver_access (user_id, diver_id, access_kind);
CREATE INDEX IF NOT EXISTS ix_user_diver_access_diver
    ON user_diver_access (diver_id);

CREATE TABLE IF NOT EXISTS login_attempts (
    id SERIAL PRIMARY KEY,
    identifier VARCHAR(255) NOT NULL,
    success BOOLEAN NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_login_attempts_identifier_time
    ON login_attempts (identifier, created_at);

CREATE TABLE IF NOT EXISTS media_playback_grants (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    media_revision_id INTEGER,
    storage_location_id INTEGER,
    outcome VARCHAR(20) NOT NULL,
    denial_reason VARCHAR(40),
    ttl_seconds INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_media_playback_grants_user_time
    ON media_playback_grants (user_id, created_at);
CREATE INDEX IF NOT EXISTS ix_media_playback_grants_revision
    ON media_playback_grants (media_revision_id);
