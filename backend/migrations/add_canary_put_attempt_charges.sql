-- Canary per-PUT attempt charges (additive; manual apply BEFORE deploy).
--
-- Problem fixed: the ledger deduped same-key retries (one row per
-- bucket+object_key), but a concurrent same-key race can PUT twice:
-- two publishers that both miss the pre-PUT full-GET reuse check each
-- stream a PUT, and a versioned bucket keeps BOTH versions. One charge
-- for two stored versions silently under-counts against the hard 2 GiB
-- cap, and the single package lease does NOT serialize duplicate
-- HTTP/stale in-flight B2 attempts.
--
-- New rule: EVERY actual PUT attempt inserts its own charge row BEFORE
-- any B2 byte streams, under the PG advisory xact lock with a
-- cumulative cap check, committed immediately (never refunded, never
-- deleted -- orphans and failed PUTs stay counted). A verified full-GET
-- reuse (same key already proves the same bytes) skips the PUT and
-- charges nothing new; but once the GET misses, the attempt MUST
-- charge, so two racers that both miss each charge. Idempotent replay
-- over-counts (safe direction) instead of under-counting.
--
-- Change: drop the UNIQUE (bucket, object_key) constraint to a plain
-- non-unique index. Same-key duplicate rows are concurrent/retry
-- attempts, each counted. No other table is altered.
--
-- Scope: CANARY ONLY. Rollback: dropping new rows loses orphan
-- accounting (fail closed: the budget code refuses when the table is
-- missing on PG).
--
-- Idempotent: safe to re-run (guarded drops + IF NOT EXISTS).

DROP INDEX IF EXISTS uq_canary_slot_reservation_bucket_key;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_canary_slot_reservation_bucket_key'
    ) THEN
        ALTER TABLE IF EXISTS canary_slot_reservations
            DROP CONSTRAINT uq_canary_slot_reservation_bucket_key;
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS ix_canary_slot_reservation_bucket_key
    ON canary_slot_reservations (bucket, object_key);
CREATE INDEX IF NOT EXISTS ix_canary_slot_reservations_sha
    ON canary_slot_reservations (object_sha256);
CREATE INDEX IF NOT EXISTS ix_canary_slot_reservations_created
    ON canary_slot_reservations (created_at);
