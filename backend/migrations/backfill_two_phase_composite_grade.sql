-- Two-phase dives: store the letter of the weighted 0-10 score.
--
-- The stored letter used to be min(phase1, phase2), so a G+P dive showed
-- "G" next to 8.65/10 and counted as G everywhere letters are counted.
-- New writes use performance_scoring.composite_grade (nearest band of
-- 0.45*phase1 + 0.55*phase2); this realigns existing rows. See docs/SCORING.md.
--
-- Idempotent: only rows whose letter differs are touched. Apply right after
-- the backend deploy (before it, old code still writes min() on new syncs;
-- re-running afterwards fixes those too). updated_at moves so caches keyed
-- on it (Personal Dive Value) refresh.
-- tests/test_scoring_contract.py pins this table to composite_grade.

BEGIN;

WITH grade(phase1, phase2, letter, ordinal) AS (
  VALUES
    ('F', 'F', 'F', 0),
    ('F', 'B', 'B', 1),
    ('F', 'M', 'B', 1),
    ('F', 'G', 'M', 2),
    ('F', 'P', 'M', 2),
    ('B', 'F', 'F', 0),
    ('B', 'B', 'B', 1),
    ('B', 'M', 'M', 2),
    ('B', 'G', 'M', 2),
    ('B', 'P', 'G', 3),
    ('M', 'F', 'B', 1),
    ('M', 'B', 'B', 1),
    ('M', 'M', 'M', 2),
    ('M', 'G', 'G', 3),
    ('M', 'P', 'G', 3),
    ('G', 'F', 'B', 1),
    ('G', 'B', 'M', 2),
    ('G', 'M', 'M', 2),
    ('G', 'G', 'G', 3),
    ('G', 'P', 'P', 4),
    ('P', 'F', 'M', 2),
    ('P', 'B', 'M', 2),
    ('P', 'M', 'G', 3),
    ('P', 'G', 'G', 3),
    ('P', 'P', 'P', 4)
)
UPDATE dives AS d
SET performance = g.letter,
    performance_numeric = g.ordinal,
    updated_at = now()
FROM grade AS g
WHERE d.phase1_performance = g.phase1
  AND d.phase2_performance = g.phase2
  AND (d.performance IS DISTINCT FROM g.letter OR d.performance_numeric IS DISTINCT FROM g.ordinal);

COMMIT;
