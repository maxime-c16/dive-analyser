-- DD values must be traceable to a rulebook edition, not an opaque lookup seed.
ALTER TABLE dives
  ADD COLUMN IF NOT EXISTS official_dd_source VARCHAR(120);

COMMENT ON COLUMN dives.official_dd_source IS
  'Versioned World Aquatics/FFN rulebook reference used to calculate official_dd.';

-- The prior migration limited DD lookups to 4.1 even though the official
-- formula includes valid values above that (for example 309B at 10m = 4.8).
ALTER TABLE dd_lookups DROP CONSTRAINT IF EXISTS check_dd_value_range;
