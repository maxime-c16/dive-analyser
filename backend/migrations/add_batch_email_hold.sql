-- Batch-email admin confirmation: auto-ingested clips park their email as
-- 'held' until an admin releases it from Administration > Emails.
-- Apply BEFORE deploying the code that writes 'held'. Idempotent.
--
-- The first application also parks every email that is still 'pending' as
-- 'held', so nothing queued before this feature can be sent by cron without an
-- admin confirming it. Later re-applications leave statuses alone (an admin
-- may have released rows by then).
BEGIN;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_batch_email_status'
          AND conrelid = 'batch_email_outbox'::regclass
          AND pg_get_constraintdef(oid) LIKE '%held%'
    ) THEN
        ALTER TABLE batch_email_outbox DROP CONSTRAINT IF EXISTS ck_batch_email_status;
        ALTER TABLE batch_email_outbox
            ADD CONSTRAINT ck_batch_email_status CHECK (status IN ('pending', 'held', 'sent', 'failed'));
        UPDATE batch_email_outbox SET status = 'held' WHERE status = 'pending';
    END IF;
END
$$;
COMMIT;
-- Rollback: UPDATE batch_email_outbox SET status='pending' WHERE status='held';
-- then re-add the original CHECK (status IN ('pending', 'sent', 'failed')).
