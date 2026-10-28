-- Apply before deploying the dependent backend. No historical pair inference.
BEGIN;
CREATE TABLE IF NOT EXISTS dive_sync_pairs (
    dive_id INTEGER PRIMARY KEY REFERENCES dives(id) ON DELETE CASCADE,
    first_diver_id INTEGER REFERENCES divers(id),
    second_diver_id INTEGER REFERENCES divers(id),
    source VARCHAR(20) NOT NULL CHECK (source IN ('caption', 'reviewed')),
    complete BOOLEAN NOT NULL DEFAULT FALSE,
    conflict BOOLEAN NOT NULL DEFAULT FALSE,
    caption_sha256 VARCHAR(64) NOT NULL,
    latest_caption_sha256 VARCHAR(64) NOT NULL,
    evidence JSON NOT NULL DEFAULT '{}',
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (first_diver_id IS NULL OR second_diver_id IS NULL OR first_diver_id <> second_diver_id),
    CHECK (NOT complete OR (first_diver_id IS NOT NULL AND second_diver_id IS NOT NULL))
);
COMMIT;
