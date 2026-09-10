-- add_login_attempts_ip.sql — DIVE_ANALYZER_MEDIA_BACKBONE_V1 (P6)
-- LOGIN RATE-LIMIT REPAIR (P6 §7): add a client-source column to the
-- bounded brute-force ledger so the limiter can run TWO scopes:
--   per-identifier (credential-target, generous cap) and
--   per-client-IP (source/network cap, aggressive).
--
-- The IP is the nginx-seen direct peer (first X-Forwarded-For element) and
-- is used ONLY for rate-limit bucketing / ledger scoping — never for
-- authorization, never rendered to clients, never logged with session
-- material.
--
-- REVERSIBILITY: ALTER TABLE ... DROP COLUMN IF EXISTS client_ip;
-- No legacy table is created or dropped. NO data row is deleted.
--
-- IDEMPOTENT: safe to re-run (IF NOT EXISTS).

ALTER TABLE login_attempts
    ADD COLUMN IF NOT EXISTS client_ip VARCHAR(64) NULL;

CREATE INDEX IF NOT EXISTS ix_login_attempts_client_ip_time
    ON login_attempts (client_ip, created_at);
