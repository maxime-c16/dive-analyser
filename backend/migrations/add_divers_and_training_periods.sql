-- Per-Dive Intelligence V2: normalized diver identities and training periods.
-- Additive and idempotent. Existing person_name values are preserved.

CREATE TABLE IF NOT EXISTS divers (
    id SERIAL PRIMARY KEY,
    display_name VARCHAR(100) NOT NULL,
    canonical_name VARCHAR(100) NOT NULL UNIQUE,
    is_primary_user BOOLEAN NOT NULL DEFAULT FALSE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_divers_canonical_name ON divers(canonical_name);
CREATE INDEX IF NOT EXISTS ix_divers_primary ON divers(is_primary_user);
CREATE INDEX IF NOT EXISTS ix_divers_active ON divers(active);
CREATE UNIQUE INDEX IF NOT EXISTS uq_divers_single_primary ON divers(is_primary_user) WHERE is_primary_user = TRUE;

CREATE TABLE IF NOT EXISTS diver_aliases (
    id SERIAL PRIMARY KEY,
    diver_id INTEGER NOT NULL REFERENCES divers(id) ON DELETE CASCADE,
    alias VARCHAR(100) NOT NULL,
    canonical_alias VARCHAR(100) NOT NULL UNIQUE,
    source VARCHAR(30) NOT NULL DEFAULT 'manual',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_diver_aliases_diver_id ON diver_aliases(diver_id);
CREATE UNIQUE INDEX IF NOT EXISTS ix_diver_aliases_canonical ON diver_aliases(canonical_alias);

ALTER TABLE dives ADD COLUMN IF NOT EXISTS diver_id INTEGER REFERENCES divers(id);
CREATE INDEX IF NOT EXISTS ix_dives_diver_id ON dives(diver_id);

CREATE TABLE IF NOT EXISTS training_periods (
    id SERIAL PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    period_type VARCHAR(40) NOT NULL DEFAULT 'custom',
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    description TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT check_training_period_dates CHECK (end_date >= start_date)
);

CREATE INDEX IF NOT EXISTS ix_training_periods_type ON training_periods(period_type);
CREATE INDEX IF NOT EXISTS ix_training_periods_range ON training_periods(start_date, end_date);
CREATE INDEX IF NOT EXISTS ix_training_periods_active ON training_periods(active);

INSERT INTO training_periods (name, period_type, start_date, end_date, description, active)
SELECT '2026 Season', 'season', DATE '2026-01-01', DATE '2026-12-31', 'Calendar-year season created for Per-Dive Intelligence V2.', TRUE
WHERE NOT EXISTS (
    SELECT 1 FROM training_periods
    WHERE name = '2026 Season' AND start_date = DATE '2026-01-01' AND end_date = DATE '2026-12-31'
);

-- Blank person_name means the primary athlete in the existing data model.
INSERT INTO divers (display_name, canonical_name, is_primary_user, active)
VALUES ('Maxime', 'maxime', TRUE, TRUE)
ON CONFLICT (canonical_name) DO UPDATE
SET is_primary_user = TRUE, active = TRUE, updated_at = CURRENT_TIMESTAMP;

INSERT INTO divers (display_name, canonical_name, is_primary_user, active)
SELECT DISTINCT ON (canonical_name)
    display_name,
    canonical_name,
    FALSE,
    TRUE
FROM (
    SELECT
        trim(regexp_replace(person_name, '[[:space:]]+', ' ', 'g')) AS display_name,
        lower(trim(regexp_replace(person_name, '[[:space:]]+', ' ', 'g'))) AS canonical_name,
        id
    FROM dives
    WHERE person_name IS NOT NULL AND trim(person_name) <> ''
) normalized
ORDER BY canonical_name, id
ON CONFLICT (canonical_name) DO NOTHING;

UPDATE dives d
SET diver_id = v.id
FROM divers v
WHERE d.diver_id IS NULL
  AND (
    (trim(COALESCE(d.person_name, '')) = '' AND v.is_primary_user = TRUE)
    OR lower(trim(regexp_replace(d.person_name, '[[:space:]]+', ' ', 'g'))) = v.canonical_name
  );
