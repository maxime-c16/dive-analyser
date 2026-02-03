-- Sprint 6 Migration: Add official DD columns and Phase 5 emotional state columns to dives table
-- This migration adds support for FINA official difficulty degrees and psychological tracking

BEGIN;

-- Add official DD columns for Sprint 6
ALTER TABLE dives
ADD COLUMN IF NOT EXISTS official_dd NUMERIC(3, 1),
ADD COLUMN IF NOT EXISTS official_dd_assigned_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS official_dd_migration_id INTEGER,
ADD COLUMN IF NOT EXISTS official_dd_verification_status VARCHAR(20);

-- Add Phase 5 psychological tracking columns
ALTER TABLE dives
ADD COLUMN IF NOT EXISTS pre_dive_emotion VARCHAR(20),
ADD COLUMN IF NOT EXISTS post_dive_emotion VARCHAR(20),
ADD COLUMN IF NOT EXISTS confidence_rating INTEGER;

-- Add indexes for DD lookup and migration tracking
CREATE INDEX IF NOT EXISTS idx_dives_official_dd ON dives(official_dd);
CREATE INDEX IF NOT EXISTS idx_dives_dd_migration ON dives(official_dd_migration_id);
CREATE INDEX IF NOT EXISTS idx_dives_dd_verification ON dives(official_dd_verification_status);
CREATE INDEX IF NOT EXISTS idx_dives_pre_emotion ON dives(pre_dive_emotion);
CREATE INDEX IF NOT EXISTS idx_dives_post_emotion ON dives(post_dive_emotion);

COMMIT;
