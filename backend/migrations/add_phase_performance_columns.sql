-- Migration: Add two-phase performance scoring columns
-- Date: January 31, 2026
--
-- This migration adds support for the new two-phase dive scoring system:
-- - Phase 1: Hurdle + Flight (takeoff quality)
-- - Phase 2: Opening + Water Splash + Entry (landing quality)
--
-- New caption format: "101B G/P 5m" instead of "101B P 5m"
-- This provides more detailed and unbiased scoring by separating takeoff quality from landing quality.

-- Add phase-specific performance columns to dives table
ALTER TABLE dives
    ADD COLUMN IF NOT EXISTS phase1_performance CHAR(1) CHECK (phase1_performance IN ('F', 'B', 'M', 'G', 'P')),
    ADD COLUMN IF NOT EXISTS phase1_numeric INT CHECK (phase1_numeric >= 0 AND phase1_numeric <= 4),
    ADD COLUMN IF NOT EXISTS phase2_performance CHAR(1) CHECK (phase2_performance IN ('F', 'B', 'M', 'G', 'P')),
    ADD COLUMN IF NOT EXISTS phase2_numeric INT CHECK (phase2_numeric >= 0 AND phase2_numeric <= 4);

-- Create indexes on new columns for performance queries
CREATE INDEX IF NOT EXISTS idx_dives_phase1_performance ON dives(phase1_numeric DESC) WHERE phase1_numeric IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_dives_phase2_performance ON dives(phase2_numeric DESC) WHERE phase2_numeric IS NOT NULL;

-- Add comment to dives table explaining the two-phase scoring
COMMENT ON COLUMN dives.phase1_performance IS 'Phase 1 performance: Hurdle + Flight (takeoff quality). New format from Jan 2026.';
COMMENT ON COLUMN dives.phase1_numeric IS 'Phase 1 numeric: 0-4 mapping for takeoff quality. New format from Jan 2026.';
COMMENT ON COLUMN dives.phase2_performance IS 'Phase 2 performance: Opening + Water Splash + Entry (landing quality). New format from Jan 2026.';
COMMENT ON COLUMN dives.phase2_numeric IS 'Phase 2 numeric: 0-4 mapping for landing quality. New format from Jan 2026.';

-- Note: The legacy 'performance' and 'performance_numeric' columns are kept for backwards compatibility.
-- When two-phase scores are provided, the overall performance is set to the minimum of phase1 and phase2.
-- This ensures analytics and journey features continue to work without modification.

COMMENT ON COLUMN dives.performance IS 'Overall performance score. For new two-phase format (Jan 2026+), this is set to min(phase1, phase2).';
