-- Additive. Apply before the server rollout; retain this table on rollback.
CREATE TABLE IF NOT EXISTS browser_upload_jobs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES app_users(id),
    upload_id VARCHAR(36) NOT NULL,
    payload JSON NOT NULL,
    filename VARCHAR(255) NOT NULL,
    storage_path TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'receiving',
    attempts INTEGER NOT NULL DEFAULT 0,
    result_id INTEGER,
    last_error VARCHAR(200),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_browser_upload_identity UNIQUE (user_id, upload_id)
);
CREATE INDEX IF NOT EXISTS ix_browser_upload_jobs_user_id ON browser_upload_jobs(user_id);
CREATE INDEX IF NOT EXISTS ix_browser_upload_jobs_status ON browser_upload_jobs(status);
