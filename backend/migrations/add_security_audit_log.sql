-- P8 security audit trail (MEDIA_BACKBONE_P8_ACCELERATED_PRODUCTIONIZATION_V1 §26).
-- Additive + idempotent (IF NOT EXISTS only). Reversible: DROP TABLE security_audit_log;
-- No legacy table is altered; no credential material is ever stored here.
CREATE TABLE IF NOT EXISTS security_audit_log (
    id              SERIAL PRIMARY KEY,
    event_type      VARCHAR(40)  NOT NULL,
    actor_context   VARCHAR(40)  NOT NULL DEFAULT 'system',
    actor_note      VARCHAR(120),
    target_user_id  INTEGER,
    target_diver_id INTEGER,
    metadata_json   TEXT,
    created_at      TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_security_audit_event_time
    ON security_audit_log (event_type, created_at);
CREATE INDEX IF NOT EXISTS ix_security_audit_target_user_time
    ON security_audit_log (target_user_id, created_at);
CREATE INDEX IF NOT EXISTS ix_security_audit_log_id_idx
    ON security_audit_log (id);
CREATE INDEX IF NOT EXISTS ix_security_audit_log_created_at_idx
    ON security_audit_log (created_at);
