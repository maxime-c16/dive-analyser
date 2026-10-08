-- Apply before deploying the mentions backend. Safe to run more than once.
ALTER TABLE dive_comments ADD COLUMN IF NOT EXISTS mentions JSON NOT NULL DEFAULT '[]';
