-- Canary exact-B2-key reservation identity (additive; manual apply BEFORE deploy).
--
-- Problem fixed: the ledger used to dedupe on content SHA-256 alone, but the
-- B2 key embeds <prefix>/derived/<source_sha[:2]>/<role>-<version>-<output_sha>
-- so identical bytes (e.g. the same poster) stored for different clips, roles
-- or versions are DISTINCT stored objects. SHA-only dedupe under-counted them.
--
-- New identity: one row per DISTINCT stored object (bucket + object_key),
-- validated against the actual hash/size/key at reservation time. Legacy rows
-- (NULL bucket/object_key) keep counting as orphans (monotonic, never
-- deleted, never updated).
--
-- Scope: CANARY ONLY. No other table is altered. Rollback: dropping the new
-- columns loses exact-key dedupe (fail closed: the code refuses new canary
-- publishes when the columns are missing on PG).
--
-- Idempotent: safe to re-run (IF NOT EXISTS + guarded index/constraint
-- drops). Never drops public tables; only touches canary_slot_reservations.

ALTER TABLE IF EXISTS canary_slot_reservations
    ADD COLUMN IF NOT EXISTS bucket VARCHAR(255) NULL;
ALTER TABLE IF EXISTS canary_slot_reservations
    ADD COLUMN IF NOT EXISTS object_key VARCHAR(1024) NULL;
ALTER TABLE IF EXISTS canary_slot_reservations
    ADD COLUMN IF NOT EXISTS environment VARCHAR(20) NULL;

-- The old SHA-only UNIQUE (from the first canary migration) must go: the
-- same content SHA stored under two different B2 keys needs two rows.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'canary_slot_reservations_object_sha256_key'
    ) THEN
        ALTER TABLE canary_slot_reservations
            DROP CONSTRAINT canary_slot_reservations_object_sha256_key;
    END IF;
END
$$;

DROP INDEX IF EXISTS uq_canary_slot_reservation_sha;
DROP INDEX IF EXISTS canary_slot_reservations_object_sha256_key;

CREATE UNIQUE INDEX IF NOT EXISTS uq_canary_slot_reservation_bucket_key
    ON canary_slot_reservations (bucket, object_key);
CREATE INDEX IF NOT EXISTS ix_canary_slot_reservations_sha
    ON canary_slot_reservations (object_sha256);
CREATE INDEX IF NOT EXISTS ix_canary_slot_reservations_created
    ON canary_slot_reservations (created_at);
