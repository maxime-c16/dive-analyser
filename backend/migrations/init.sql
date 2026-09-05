-- Initial PostgreSQL Schema for Diving Analytics
-- This script creates all necessary tables, indexes, and views

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Sessions table (training days)
CREATE TABLE sessions (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL UNIQUE,
    location VARCHAR(255),
    notes TEXT,
    weather VARCHAR(50),
    total_dives INT DEFAULT 0,
    total_personal_dives INT DEFAULT 0,
    avg_performance DECIMAL(3,2),
    success_rate DECIMAL(5,2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_sessions_date ON sessions(date DESC);

-- Dives table (individual dives)
CREATE TABLE dives (
    id SERIAL PRIMARY KEY,
    session_id INT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,

    -- Core dive info
    dive_code VARCHAR(10) NOT NULL,
    dive_number VARCHAR(5),
    position CHAR(1),
    direction INT CHECK (direction >= 1 AND direction <= 5),

    -- Performance (legacy single score)
    performance CHAR(1) NOT NULL CHECK (performance IN ('F', 'B', 'M', 'G', 'P')),
    performance_numeric INT NOT NULL CHECK (performance_numeric >= 0 AND performance_numeric <= 4),

    -- Performance (new two-phase scoring as of Jan 2026)
    -- Phase 1: Hurdle + Flight (takeoff quality)
    -- Phase 2: Opening + Water Splash + Entry (landing quality)
    phase1_performance CHAR(1) CHECK (phase1_performance IN ('F', 'B', 'M', 'G', 'P')),
    phase1_numeric INT CHECK (phase1_numeric >= 0 AND phase1_numeric <= 4),
    phase2_performance CHAR(1) CHECK (phase2_performance IN ('F', 'B', 'M', 'G', 'P')),
    phase2_numeric INT CHECK (phase2_numeric >= 0 AND phase2_numeric <= 4),
    phase_insight TEXT,

    -- Conditions
    height VARCHAR(5) NOT NULL,
    platform_type VARCHAR(20) NOT NULL DEFAULT 'springboard',

    -- Flags
    is_lineup BOOLEAN DEFAULT FALSE,
    is_sync BOOLEAN DEFAULT FALSE,
    is_smack BOOLEAN DEFAULT FALSE,

    -- Metadata
    raw_caption TEXT,
    person_name VARCHAR(100),
    notes TEXT,
    video_uuid VARCHAR(100) UNIQUE,
    video_filename VARCHAR(255),
    video_path TEXT,

    -- Timestamps
    dive_datetime TIMESTAMP NOT NULL,
    synced_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_dives_session_date ON dives(session_id, dive_datetime DESC);
CREATE INDEX idx_dives_code ON dives(dive_code);
CREATE INDEX idx_dives_direction ON dives(direction);
CREATE INDEX idx_dives_height ON dives(height);
CREATE INDEX idx_dives_performance ON dives(performance_numeric DESC);
CREATE INDEX idx_dives_phase1_performance ON dives(phase1_numeric DESC) WHERE phase1_numeric IS NOT NULL;
CREATE INDEX idx_dives_synced_at ON dives(synced_at);
CREATE INDEX idx_dives_video_uuid ON dives(video_uuid);
CREATE INDEX idx_dives_person ON dives(person_name);
CREATE INDEX idx_dives_is_lineup ON dives(is_lineup);
CREATE INDEX idx_dives_phase2_performance ON dives(phase2_numeric DESC) WHERE phase2_numeric IS NOT NULL;
CREATE INDEX idx_dives_person ON dives(person_name);
CREATE INDEX idx_dives_lineup ON dives(is_lineup) WHERE is_lineup = FALSE;
CREATE INDEX idx_dives_personal ON dives(person_name) WHERE person_name IS NULL;

-- Full-text search on notes
CREATE INDEX idx_dives_notes_fts ON dives USING gin(to_tsvector('english', COALESCE(notes, '')));
CREATE INDEX idx_sessions_notes_fts ON sessions USING gin(to_tsvector('english', COALESCE(notes, '')));

-- Video labels table (non-dive Photos captions such as person-only labels)
CREATE TABLE IF NOT EXISTS video_labels (
    id SERIAL PRIMARY KEY,
    video_uuid VARCHAR(100) NOT NULL,
    label_type VARCHAR(50) NOT NULL,
    label_value VARCHAR(100) NOT NULL,
    source VARCHAR(50) NOT NULL DEFAULT 'photos_caption',
    raw_caption TEXT,
    video_filename VARCHAR(255),
    label_datetime TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_video_labels_uuid_type_source UNIQUE (video_uuid, label_type, source)
);

CREATE INDEX IF NOT EXISTS idx_video_labels_uuid ON video_labels(video_uuid);
CREATE INDEX IF NOT EXISTS idx_video_labels_type ON video_labels(label_type);
CREATE INDEX IF NOT EXISTS idx_video_labels_value ON video_labels(label_value);
CREATE INDEX IF NOT EXISTS idx_video_labels_source ON video_labels(source);
CREATE INDEX IF NOT EXISTS idx_video_labels_datetime ON video_labels(label_datetime);
CREATE INDEX IF NOT EXISTS idx_video_labels_type_value ON video_labels(label_type, label_value);

-- Analytics cache table
CREATE TABLE analytics_cache (
    id SERIAL PRIMARY KEY,
    cache_key VARCHAR(255) NOT NULL UNIQUE,
    cache_data JSONB NOT NULL,
    filters JSONB,
    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_analytics_cache_key ON analytics_cache(cache_key);
CREATE INDEX idx_analytics_cache_expires ON analytics_cache(expires_at);

-- Dive codes metadata (FINA codes reference)
CREATE TABLE dive_codes_metadata (
    dive_code VARCHAR(10) PRIMARY KEY,
    dive_number VARCHAR(5),
    position CHAR(1),
    direction INT,
    description TEXT,
    group_name VARCHAR(100),
    total_attempts INT DEFAULT 0,
    avg_performance DECIMAL(3,2),
    success_rate DECIMAL(5,2),
    last_attempted TIMESTAMP
);

-- Visualization presets
CREATE TABLE visualization_presets (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    viz_type VARCHAR(50) NOT NULL,
    filters JSONB,
    chart_config JSONB,
    is_favorite BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_viz_presets_favorite ON visualization_presets(is_favorite) WHERE is_favorite = TRUE;

-- Background jobs tracking
CREATE TABLE jobs (
    id SERIAL PRIMARY KEY,
    job_type VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    progress INT DEFAULT 0,
    result JSONB,
    error_message TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_jobs_created ON jobs(created_at DESC);

-- Audit log
CREATE TABLE audit_log (
    id SERIAL PRIMARY KEY,
    table_name VARCHAR(50),
    record_id INT,
    action VARCHAR(20),
    old_values JSONB,
    new_values JSONB,
    changed_by VARCHAR(100) DEFAULT 'system',
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_audit_log_table ON audit_log(table_name, record_id);

-- Materialized view for dashboard quick stats (disabled - will recreate after data load)
-- CREATE MATERIALIZED VIEW dashboard_stats AS
-- SELECT
--     COUNT(*) FILTER (WHERE is_lineup = FALSE AND person_name IS NULL) as total_dives,
--     COUNT(DISTINCT session_id) FILTER (WHERE is_lineup = FALSE AND person_name IS NULL) as total_sessions,
--     AVG(performance_numeric) FILTER (WHERE is_lineup = FALSE AND person_name IS NULL)::numeric as avg_performance,
--     (COUNT(*) FILTER (WHERE performance_numeric >= 2 AND is_lineup = FALSE AND person_name IS NULL)::FLOAT /
--      NULLIF(COUNT(*) FILTER (WHERE is_lineup = FALSE AND person_name IS NULL), 0) * 100) as success_rate,
--     MAX(dive_datetime) FILTER (WHERE is_lineup = FALSE AND person_name IS NULL) as last_dive_date,
--     MAX(s.date) FILTER (WHERE d.is_lineup = FALSE AND d.person_name IS NULL) as last_session_date
-- FROM dives d
-- LEFT JOIN sessions s ON d.session_id = s.id;

-- Performance by direction view
-- CREATE MATERIALIZED VIEW performance_by_direction AS (disabled - ROUND function compatibility)
-- SELECT
--     direction,
--     COUNT(*) as total_dives,
--     AVG(performance_numeric)::numeric as avg_performance,
--     (COUNT(*) FILTER (WHERE performance_numeric >= 2)::FLOAT /
--      NULLIF(COUNT(*), 0) * 100) as success_rate
-- FROM dives
-- WHERE is_lineup = FALSE AND person_name IS NULL AND direction IS NOT NULL
-- GROUP BY direction
-- ORDER BY direction;

-- Performance by height view
-- CREATE MATERIALIZED VIEW performance_by_height AS (disabled - ROUND function compatibility)
-- SELECT
--     height,
--     COUNT(*) as total_dives,
--     AVG(performance_numeric)::numeric as avg_performance,
--     (COUNT(*) FILTER (WHERE performance_numeric >= 2)::FLOAT /
--      NULLIF(COUNT(*), 0) * 100) as success_rate
-- FROM dives
-- WHERE is_lineup = FALSE AND person_name IS NULL
-- GROUP BY height;

-- Functions for common operations

-- Function to update session stats
CREATE OR REPLACE FUNCTION update_session_stats(p_session_id INT)
RETURNS void AS $$
BEGIN
    UPDATE sessions s
    SET
        total_dives = (SELECT COUNT(*) FROM dives WHERE session_id = p_session_id),
        total_personal_dives = (SELECT COUNT(*) FROM dives WHERE session_id = p_session_id AND person_name IS NULL),
        avg_performance = ROUND((SELECT AVG(performance_numeric)::numeric FROM dives WHERE session_id = p_session_id AND person_name IS NULL)::numeric, 2),
        success_rate = ROUND(((SELECT COUNT(*) FILTER (WHERE performance_numeric >= 2)::numeric / NULLIF(COUNT(*), 0) * 100 FROM dives WHERE session_id = p_session_id AND person_name IS NULL))::numeric, 1),
        updated_at = CURRENT_TIMESTAMP
    WHERE id = p_session_id;
END;
$$ LANGUAGE plpgsql;

-- Trigger to update session stats when dives change
CREATE OR REPLACE FUNCTION trigger_update_session_stats()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM update_session_stats(OLD.session_id);
    ELSE
        PERFORM update_session_stats(NEW.session_id);
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_dives_update_session_stats
AFTER INSERT OR UPDATE OR DELETE ON dives
FOR EACH ROW
EXECUTE FUNCTION trigger_update_session_stats();

-- Default visualization presets
INSERT INTO visualization_presets (name, description, viz_type, filters) VALUES
    ('Last 30 Days', 'All dives from past 30 days', 'custom_filter', '{"date_from": "-30d", "exclude_lineups": true}'::jsonb),
    ('Last 30 Days - 3m Only', 'Past month, 3m springboard only', 'custom_filter', '{"date_from": "-30d", "heights": ["3m"], "exclude_lineups": true}'::jsonb),
    ('Platform Only', 'All platform dives', 'custom_filter', '{"platform_type": "platform", "exclude_lineups": true}'::jsonb),
    ('Failed Dives', 'Only failed attempts (F rating)', 'custom_filter', '{"performance": ["F"], "exclude_lineups": true}'::jsonb),
    ('This Month', 'Current month only', 'custom_filter', '{"date_from": "this_month", "exclude_lineups": true}'::jsonb);

-- Sample dive codes (populate with real FINA codes as needed)
INSERT INTO dive_codes_metadata (dive_code, dive_number, position, direction, description, group_name) VALUES
    ('101B', '101', 'B', 1, 'Forward Somersault', 'Forward Dives'),
    ('101C', '101', 'C', 1, 'Forward Somersault', 'Forward Dives'),
    ('103B', '103', 'B', 1, 'Forward Dive with 1.5 Somersaults', 'Forward Dives'),
    ('103C', '103', 'C', 1, 'Forward Dive with 1.5 Somersaults', 'Forward Dives'),
    ('201B', '201', 'B', 2, 'Back Dive', 'Back Dives'),
    ('201C', '201', 'C', 2, 'Back Dive', 'Back Dives'),
    ('203C', '203', 'C', 2, 'Back Dive with 1.5 Somersaults', 'Back Dives'),
    ('301C', '301', 'C', 3, 'Reverse Dive', 'Reverse Dives'),
    ('401B', '401', 'B', 4, 'Inward Dive', 'Inward Dives'),
    ('401C', '401', 'C', 4, 'Inward Dive', 'Inward Dives'),
    ('5211A', '5211', 'A', 5, 'Back 1.5 Twists', 'Twist Dives'),
    ('5231D', '5231', 'D', 5, 'Back 1.5 Twists in Free Position', 'Twist Dives')
ON CONFLICT (dive_code) DO NOTHING;
