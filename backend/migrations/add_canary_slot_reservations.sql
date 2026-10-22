-- Canary-only durable upload-attempt ledger (additive; manual apply BEFORE deploy).
--
-- New table `canary_slot_reservations`: one row per unique attempted B2
-- object (content-addressed by derivative SHA-256). Counts EVERY attempted
-- unique upload including safe orphans (verified B2 bytes never promoted
-- after a stale/fenced rejection, crash retry with different bytes).
-- Retry of the SAME bytes dedupes on the unique SHA (no double charge).
-- Monotonic: rows are never updated or deleted by the app.
--
-- Scope: CANARY ONLY. The 2 GiB bound is enforced only on canary paths
-- (web_package slot publish + canary ops tool). No other table is
-- altered; old code boots on the new schema (it never touches this table).
-- Rollback: dropping this table loses orphan accounting (fail closed:
-- the budget code refuses when the table is missing on PG; see runbook).
--
-- Idempotent: safe to re-run (`IF NOT EXISTS` + guarded index).

CREATE TABLE IF NOT EXISTS canary_slot_reservations (
    id SERIAL PRIMARY KEY,
    object_sha256 VARCHAR(64) NOT NULL UNIQUE,
    size_bytes BIGINT NOT NULL CONSTRAINT ck_canary_reservation_size CHECK (size_bytes > 0),
    job_id INTEGER NULL,
    slot VARCHAR(20) NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'reserved',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_canary_slot_reservation_sha
    ON canary_slot_reservations (object_sha256);
CREATE INDEX IF NOT EXISTS ix_canary_slot_reservations_created
    ON canary_slot_reservations (created_at);
