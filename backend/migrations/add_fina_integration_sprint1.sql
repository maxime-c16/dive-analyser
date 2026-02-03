-- Sprint 1: FINA Integration - Foundation Models and Official DD Support
-- February 2, 2026
--
-- This migration adds the foundational models for FINA diving rules integration:
-- 1. Adds official_dd field to dives table (NEW SIGNAL for journey analysis)
-- 2. Creates fina_dive_codes table (official FINA dive code metadata)
-- 3. Creates dd_lookups table (official Degree of Difficulty values by height)
-- 4. Creates fina_scoring_rules table (event requirements and compliance rules)

-- ============================================================================
-- 1. Add official_dd field to dives table
-- ============================================================================

ALTER TABLE dives
ADD COLUMN IF NOT EXISTS official_dd NUMERIC(3, 1) NULL;

COMMENT ON COLUMN dives.official_dd IS 'Official FINA Degree of Difficulty (1.2-4.1) - NEW SIGNAL for journey analysis, separate from execution-based performance';

-- Index for fast DD-based queries
CREATE INDEX IF NOT EXISTS idx_dives_official_dd ON dives(official_dd) WHERE official_dd IS NOT NULL;


-- ============================================================================
-- 2. Create fina_dive_codes table
-- ============================================================================

CREATE TABLE IF NOT EXISTS fina_dive_codes (
    -- Primary key: the full dive code (e.g., "101B", "5231D")
    dive_code VARCHAR(10) PRIMARY KEY,

    -- Parsed FINA components
    -- Group: 1=Forward, 2=Back, 3=Reverse, 4=Inward, 5=Twisting, 6=Armstand
    group INT NOT NULL,

    -- Direction (first digit for groups 1-4, direction for group 5)
    -- For group 5 (twisting): 1=Forward, 2=Back, 3=Reverse, 4=Inward
    direction INT NOT NULL,

    -- Flying action (0=no, 1=yes)
    has_flying INT DEFAULT 0,

    -- Number of half somersaults (1-8)
    rotations INT NOT NULL,

    -- Number of half twists (for group 5 only, else 0)
    twists INT DEFAULT 0,

    -- Position: A=Straight, B=Pike, C=Tuck, D=Free
    position VARCHAR(1) NOT NULL,

    -- Boolean flags
    is_twisting INT DEFAULT 0,
    is_flying INT DEFAULT 0,
    is_armstand INT DEFAULT 0,

    -- FINA official descriptions
    official_name VARCHAR(255),
    group_name VARCHAR(100),
    position_name VARCHAR(50),
    description TEXT,

    -- Statistics
    total_attempts INT DEFAULT 0,
    avg_performance NUMERIC(3, 2),
    success_rate NUMERIC(5, 2),
    last_attempted TIMESTAMP,

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Constraints
    CONSTRAINT check_group_range CHECK (group >= 1 AND group <= 6),
    CONSTRAINT check_direction_range CHECK (direction >= 1 AND direction <= 5),
    CONSTRAINT check_has_flying CHECK (has_flying IN (0, 1)),
    CONSTRAINT check_rotations_range CHECK (rotations >= 1 AND rotations <= 8),
    CONSTRAINT check_twists_range CHECK (twists >= 0 AND twists <= 8),
    CONSTRAINT check_position_valid CHECK (position IN ('A', 'B', 'C', 'D')),
    CONSTRAINT check_is_twisting CHECK (is_twisting IN (0, 1)),
    CONSTRAINT check_is_flying CHECK (is_flying IN (0, 1)),
    CONSTRAINT check_is_armstand CHECK (is_armstand IN (0, 1)),

    -- Group 5 (twisting) must have twists 1-8, not 0
    CONSTRAINT check_group5_twists_valid_range CHECK ((group = 5 AND twists >= 1 AND twists <= 8) OR (group != 5 AND twists = 0)),

    -- Group 5 (twisting) direction must be 1-4 (Forward, Back, Reverse, Inward)
    CONSTRAINT check_group5_direction_range CHECK ((group != 5) OR (direction >= 1 AND direction <= 4)),

    -- Flying dives only in groups 1-4
    CONSTRAINT check_flying_groups CHECK ((is_flying = 1 AND group <= 4) OR (is_flying = 0))
);

COMMENT ON TABLE fina_dive_codes IS 'Official FINA dive code reference with parsed components per FINA standards';
COMMENT ON COLUMN fina_dive_codes.group IS '1=Forward, 2=Back, 3=Reverse, 4=Inward, 5=Twisting, 6=Armstand';
COMMENT ON COLUMN fina_dive_codes.position IS 'A=Straight, B=Pike, C=Tuck, D=Free';

-- Indexes for fast lookup and filtering
CREATE INDEX IF NOT EXISTS idx_fina_dive_codes_group ON fina_dive_codes(group);
CREATE INDEX IF NOT EXISTS idx_fina_dive_codes_direction ON fina_dive_codes(direction);
CREATE INDEX IF NOT EXISTS idx_fina_dive_codes_position ON fina_dive_codes(position);
CREATE INDEX IF NOT EXISTS idx_fina_dive_codes_is_twisting ON fina_dive_codes(is_twisting);


-- ============================================================================
-- 3. Create dd_lookups table (Degree of Difficulty reference)
-- ============================================================================

CREATE TABLE IF NOT EXISTS dd_lookups (
    id SERIAL PRIMARY KEY,

    -- Foreign key to fina_dive_codes
    dive_code VARCHAR(10) NOT NULL REFERENCES fina_dive_codes(dive_code) ON DELETE CASCADE,

    -- Height where this DD applies (1m, 3m, 5m, 7m/7.5m, 10m)
    -- Note: 7m is app-level alias for official FINA 7.5m
    height VARCHAR(10) NOT NULL,

    -- Platform type (springboard, platform)
    platform_type VARCHAR(20) NOT NULL DEFAULT 'springboard',

    -- The official DD value (1.2 to 4.1+ in 0.1 increments)
    dd_value NUMERIC(3, 1) NOT NULL,

    -- Notes about this DD
    notes VARCHAR(255),

    -- Effective date of this DD value
    effective_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Unique: each dive code + height + platform type has one DD value
    UNIQUE(dive_code, height, platform_type),

    -- Constraints
    -- Note: Both '7m' (app alias) and '7.5m' (official FINA) are accepted
    CONSTRAINT check_height_valid CHECK (height IN ('1m', '3m', '5m', '7m', '7.5m', '10m')),
    CONSTRAINT check_platform_type_valid CHECK (platform_type IN ('springboard', 'platform')),
    CONSTRAINT check_dd_value_range CHECK (dd_value >= 1.2 AND dd_value <= 4.1),

    -- 1m and 3m are springboard only; 5m, 7m, 7.5m, 10m are platform
    CONSTRAINT check_height_platform_match CHECK (
        ((height = '1m' OR height = '3m') AND platform_type = 'springboard') OR
        (height IN ('5m', '7m', '7.5m', '10m'))
    )
);

COMMENT ON TABLE dd_lookups IS 'Official FINA Degree of Difficulty (DD) values by dive code and height';
COMMENT ON COLUMN dd_lookups.dd_value IS 'Official FINA DD value (1.2-4.1+ in 0.1 increments)';

-- Indexes for fast lookup
CREATE INDEX IF NOT EXISTS idx_dd_lookups_dive_code_height ON dd_lookups(dive_code, height);
CREATE INDEX IF NOT EXISTS idx_dd_lookups_platform ON dd_lookups(platform_type);
CREATE INDEX IF NOT EXISTS idx_dd_lookups_dd_value ON dd_lookups(dd_value);


-- ============================================================================
-- 4. Create fina_scoring_rules table (Event requirements)
-- ============================================================================

CREATE TABLE IF NOT EXISTS fina_scoring_rules (
    id SERIAL PRIMARY KEY,

    -- Event type identifier (e.g., "springboard_1m_men", "platform_10m_women")
    event_type VARCHAR(100) NOT NULL UNIQUE,

    -- Descriptive name
    event_name VARCHAR(255) NOT NULL,

    -- Event category (springboard, platform, synchronized)
    event_category VARCHAR(50) NOT NULL,

    -- Height (1m, 3m, 5m, 7m/7.5m, 10m)
    -- Note: 7m is app-level alias for official FINA 7.5m
    height VARCHAR(10) NOT NULL,

    -- Gender (men, women, mixed)
    gender VARCHAR(20) NOT NULL,

    -- Platform type (springboard, platform)
    platform_type VARCHAR(20) NOT NULL,

    -- Number of mandatory dives
    mandatory_dive_count INT NOT NULL,

    -- DD limits for initial/final rounds
    dd_limit_initial VARCHAR(10),
    dd_limit_final VARCHAR(10),

    -- Required dive groups (JSON array: [1, 2, 3, 4, 5])
    mandatory_groups JSONB NOT NULL,

    -- Max mandatory groups (5 or 6)
    max_mandatory_groups INT DEFAULT 5,

    -- Whether armstand (group 6) is allowed
    allows_armstand INT DEFAULT 0,

    -- Judge counts
    judge_count_execution INT DEFAULT 7,
    judge_count_sync INT,

    -- Description and notes
    description TEXT,
    notes TEXT,

    -- Effective date
    effective_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Constraints
    CONSTRAINT check_event_category CHECK (event_category IN ('springboard', 'platform', 'synchronized')),
    CONSTRAINT check_event_height CHECK (height IN ('1m', '3m', '5m', '7m', '7.5m', '10m')),
    CONSTRAINT check_gender CHECK (gender IN ('men', 'women', 'mixed')),
    CONSTRAINT check_event_platform_type CHECK (platform_type IN ('springboard', 'platform')),
    CONSTRAINT check_mandatory_dive_count CHECK (mandatory_dive_count >= 3 AND mandatory_dive_count <= 7),
    CONSTRAINT check_judge_count CHECK (judge_count_execution >= 5 AND judge_count_execution <= 11),
    CONSTRAINT check_allows_armstand CHECK (allows_armstand IN (0, 1)),
    -- Armstand (group 6) only allowed for platform, not springboard
    CONSTRAINT check_armstand_platform_match CHECK (
        (platform_type = 'springboard' AND allows_armstand = 0) OR
        (platform_type = 'platform' AND allows_armstand = 1)
    ),
    -- DD limits for synchronized events must be valid numeric values
    CONSTRAINT check_dd_limit_initial_valid CHECK (
        (event_category != 'synchronized') OR
        (dd_limit_initial >= 1.2 AND dd_limit_initial <= 3.0)
    )
);

COMMENT ON TABLE fina_scoring_rules IS 'Official FINA event requirements and scoring rules per event type';
COMMENT ON COLUMN fina_scoring_rules.mandatory_groups IS 'JSON array of required dive groups (e.g., [1, 2, 3, 4, 5])';

-- Indexes for fast lookup
CREATE INDEX IF NOT EXISTS idx_fina_scoring_rules_event_type ON fina_scoring_rules(event_type);
CREATE INDEX IF NOT EXISTS idx_fina_scoring_rules_event_category ON fina_scoring_rules(event_category);
CREATE INDEX IF NOT EXISTS idx_fina_scoring_rules_height ON fina_scoring_rules(height);

-- ============================================================================
-- End of Sprint 1 FINA Integration Foundation Models
-- ============================================================================
