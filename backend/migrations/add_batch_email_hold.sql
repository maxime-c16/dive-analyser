-- Batch-email admin confirmation: auto-ingested clips park their email as
-- 'held' until an admin releases it from Administration > Emails.
-- Apply BEFORE deploying the code that writes 'held'. Idempotent.
--
-- The first application also parks any still-'pending' email of an
-- agent-day batch (`mac-<hash>-<yyyymmdd>`) as 'held': that id is reused all
-- day, so later machine-ingested clips could otherwise ride on a row queued
-- before this feature. Browser-upload and /videos/batch ids are per-request
-- UUIDs, never reused, so explicit admin deposits stay automatic. Later
-- re-applications leave statuses alone (an admin may have released rows).
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
        UPDATE batch_email_outbox SET status = 'held'
        WHERE status = 'pending' AND batch_id LIKE 'mac-%';
    END IF;
END
$$;
COMMIT;
-- Rollback (deploy the previous code first). Held emails were never approved:
-- park them as failed so cron can never send them, then restore the old CHECK.
--   UPDATE batch_email_outbox SET status='failed', error='rolled back while held' WHERE status='held';
--   ALTER TABLE batch_email_outbox DROP CONSTRAINT ck_batch_email_status;
--   ALTER TABLE batch_email_outbox ADD CONSTRAINT ck_batch_email_status CHECK (status IN ('pending','sent','failed'));
