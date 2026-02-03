-- Migration: Add sync tracking and coaching insight columns
-- Date: January 31, 2026
--
-- This migration adds support for tracking video sync operations and storing
-- phase-based coaching recommendations:
-- - synced_at: Timestamp when video was synced from mac-agent
-- - phase_insight: Coaching recommendation based on two-phase performance scores
--
-- These fields enable:
-- 1. Incremental sync tracking (know which videos have been synced)
-- 2. Audit logging of sync operations
-- 3. Smart coaching recommendations based on phase performance

-- Add sync tracking columns to dives table
ALTER TABLE dives
    ADD COLUMN IF NOT EXISTS synced_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS phase_insight TEXT;

-- Create index on synced_at for efficient querying of synced videos
CREATE INDEX IF NOT EXISTS idx_dives_synced_at ON dives(synced_at DESC) WHERE synced_at IS NOT NULL;

-- Add comments explaining the new columns
COMMENT ON COLUMN dives.synced_at IS 'Timestamp when video was successfully synced from mac-agent. Used for incremental sync tracking and audit logging.';
COMMENT ON COLUMN dives.phase_insight IS 'Coaching recommendation based on two-phase performance scores. Generated automatically during sync. E.g., "Focus on hurdle height" or "Improve entry angle".';
