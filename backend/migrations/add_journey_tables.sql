-- Migration: Create Journey and JourneyMilestone tables
-- Date: January 31, 2026
--
-- Enables tracking of diver progression milestones and journey narratives.
-- Populated automatically when new dives are synced.

-- Create journeys table
CREATE TABLE IF NOT EXISTS journeys (
    id SERIAL PRIMARY KEY,
    journey_code VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_milestone_date TIMESTAMP,
    total_dives INTEGER DEFAULT 0,
    milestones_count INTEGER DEFAULT 0,
    success_rate INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1
);

-- Create journey_milestones table
CREATE TABLE IF NOT EXISTS journey_milestones (
    id SERIAL PRIMARY KEY,
    journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
    type VARCHAR(50) NOT NULL,
    dive_code VARCHAR(10),
    height VARCHAR(5),
    title VARCHAR(255) NOT NULL,
    narrative TEXT NOT NULL,
    attempts_before INTEGER DEFAULT 0,
    failures_before INTEGER DEFAULT 0,
    days_since_last INTEGER DEFAULT 0,
    streak_length INTEGER DEFAULT 0,
    emoji VARCHAR(10) DEFAULT '🏊',
    significance INTEGER DEFAULT 1,
    dive_uuid VARCHAR(100),
    phase1_performance CHAR(1),
    phase2_performance CHAR(1),
    phase_insight TEXT,
    detected_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    occurrence_date TIMESTAMP NOT NULL,
    CHECK (significance >= 1 AND significance <= 5)
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_journeys_created ON journeys(created_at);
CREATE INDEX IF NOT EXISTS idx_journeys_last_milestone ON journeys(last_milestone_date);
CREATE INDEX IF NOT EXISTS idx_journeys_is_active ON journeys(is_active);
CREATE INDEX IF NOT EXISTS idx_journeys_code ON journeys(journey_code);

CREATE INDEX IF NOT EXISTS idx_milestones_journey_date ON journey_milestones(journey_id, occurrence_date);
CREATE INDEX IF NOT EXISTS idx_milestones_type ON journey_milestones(type);
CREATE INDEX IF NOT EXISTS idx_milestones_dive_code ON journey_milestones(dive_code);
CREATE INDEX IF NOT EXISTS idx_milestones_dive_uuid ON journey_milestones(dive_uuid);
CREATE INDEX IF NOT EXISTS idx_milestones_detected ON journey_milestones(detected_date);
CREATE INDEX IF NOT EXISTS idx_milestones_occurrence ON journey_milestones(occurrence_date);

-- Add comments explaining the schema
COMMENT ON TABLE journeys IS 'Represents a diver''s progression journey with automatic milestone detection.';
COMMENT ON TABLE journey_milestones IS 'Meaningful moments detected in a diver''s journey, populated automatically after video sync.';
COMMENT ON COLUMN journeys.last_milestone_date IS 'Most recent milestone detected, used for incremental processing.';
COMMENT ON COLUMN journey_milestones.phase_insight IS 'Coaching recommendation based on two-phase performance (Jan 2026+).';
COMMENT ON COLUMN journey_milestones.detected_date IS 'When the milestone was detected (usually after sync).';
COMMENT ON COLUMN journey_milestones.occurrence_date IS 'When the actual milestone event occurred (dive date).';
