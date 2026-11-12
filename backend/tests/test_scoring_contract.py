"""Pins the personal-note contract in docs/SCORING.md across Python, SQL and TypeScript.

A two-phase dive's stored letter is the band of its weighted 0-10 score, so the
letter, the number, the colour and the success flag can never disagree.
"""
import re
from pathlib import Path

import pytest

from app.services.performance_scoring import (
    ATHLETE_SCORE_10,
    GRADE_FLOORS,
    ORDINAL_SCORE,
    PHASE1_WEIGHT,
    PHASE2_WEIGHT,
    composite_grade,
    grade_for_score,
    is_excellent,
    is_success,
    phase_score_10,
)
from app.services.phase_validator import PhaseValidator

ROOT = Path(__file__).resolve().parents[2]
LETTERS = "FBMGP"


def test_each_letter_is_its_own_band():
    assert {letter: grade_for_score(score) for letter, score in ATHLETE_SCORE_10.items()} == {
        letter: letter for letter in ATHLETE_SCORE_10
    }


@pytest.mark.parametrize("phase1", LETTERS)
@pytest.mark.parametrize("phase2", LETTERS)
def test_two_phase_letter_matches_its_score(phase1, phase2):
    letter = PhaseValidator.infer_legacy_score(phase1, phase2)
    score = phase_score_10(phase1, phase2)
    assert letter == composite_grade(phase1, phase2) == grade_for_score(score)
    assert score >= GRADE_FLOORS[letter]
    assert is_success(letter) == (score >= GRADE_FLOORS["M"])
    assert is_excellent(letter) == (score >= GRADE_FLOORS["G"])


def test_reported_examples():
    # The letter used to be min(phase1, phase2): "G" next to 8.65/10.
    assert PhaseValidator.infer_legacy_score("G", "P") == "P"
    assert PhaseValidator.infer_legacy_score("P", "M") == "G"
    assert PhaseValidator.infer_legacy_score("P", "G") == "G"


def test_backfill_migration_matches_composite_grade():
    sql = (ROOT / "backend/migrations/backfill_two_phase_composite_grade.sql").read_text()
    rows = re.findall(r"\('([FBMGP])', '([FBMGP])', '([FBMGP])', (\d)\)", sql)
    assert len(rows) == 25
    for phase1, phase2, letter, ordinal in rows:
        assert letter == composite_grade(phase1, phase2), (phase1, phase2)
        assert int(ordinal) == ORDINAL_SCORE[letter]


def _ts_object(source: str, name: str) -> dict[str, float]:
    body = re.search(rf"export const {name}[^=]*=\s*\{{(.*?)\}}", source, re.S).group(1)
    return {key: float(value) for key, value in re.findall(r"([A-Z]):\s*([\d.]+)", body)}


def test_frontend_constants_match_backend():
    source = (ROOT / "frontend/src/utils/performanceScoring.ts").read_text()
    assert _ts_object(source, "ATHLETE_SCORE_10") == ATHLETE_SCORE_10
    assert _ts_object(source, "GRADE_FLOORS") == GRADE_FLOORS
    assert float(re.search(r"PHASE1_WEIGHT = ([\d.]+)", source).group(1)) == PHASE1_WEIGHT
    assert float(re.search(r"PHASE2_WEIGHT = ([\d.]+)", source).group(1)) == PHASE2_WEIGHT
