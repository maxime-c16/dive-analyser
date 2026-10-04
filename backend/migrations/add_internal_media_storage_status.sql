BEGIN;
ALTER TABLE media_agents ADD COLUMN IF NOT EXISTS last_query_timeout_at TIMESTAMP;
ALTER TABLE media_agents ADD COLUMN IF NOT EXISTS storage_status JSONB;
COMMIT;
