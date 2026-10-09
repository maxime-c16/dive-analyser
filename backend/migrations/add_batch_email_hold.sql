-- Batch-email admin confirmation: auto-ingested clips park their email as
-- 'held' until an admin releases it from Administration > Emails.
-- Apply BEFORE deploying the code that writes 'held'. Idempotent.
BEGIN;
ALTER TABLE batch_email_outbox DROP CONSTRAINT IF EXISTS ck_batch_email_status;
ALTER TABLE batch_email_outbox
    ADD CONSTRAINT ck_batch_email_status CHECK (status IN ('pending', 'held', 'sent', 'failed'));
COMMIT;
-- Rollback: UPDATE batch_email_outbox SET status='pending' WHERE status='held';
-- then re-add the original CHECK (status IN ('pending', 'sent', 'failed')).
