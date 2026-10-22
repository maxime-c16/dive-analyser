-- Apply before deploying the dependent backend. Calendar is optional.
BEGIN;
CREATE TABLE IF NOT EXISTS dive_series (
    id SERIAL PRIMARY KEY,
    owner_user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    title VARCHAR(160) NOT NULL,
    clip_policy VARCHAR(10) NOT NULL DEFAULT 'best' CHECK (clip_policy IN ('best','recent')),
    height VARCHAR(5) NOT NULL CHECK (height IN ('1m','3m','5m','7.5m','10m')),
    event_id INTEGER,
    slots JSON NOT NULL DEFAULT '[]',
    shared_with JSON NOT NULL DEFAULT '[]',
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_dive_series_owner_user_id ON dive_series(owner_user_id);
CREATE INDEX IF NOT EXISTS ix_dive_series_event_id ON dive_series(event_id);
COMMIT;
