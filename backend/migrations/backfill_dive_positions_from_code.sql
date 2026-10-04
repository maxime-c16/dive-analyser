-- Backfill missing dive position from exact canonical dive codes.
--
-- The position is the final letter of the canonical dive code (A/B/C/D).
-- This migration is idempotent and only fills rows where position is missing;
-- it does not overwrite existing non-empty production values.

UPDATE dives
SET
    position = substring(upper(dive_code) from '[ABCD]$'),
    updated_at = now()
WHERE (position IS NULL OR position = '')
  AND upper(dive_code) ~ '^[0-9]{3,4}[ABCD]$';
