"""Performance scoring helpers.

Raw Photos captions use F/B/M/G/P tags. The database keeps the historical
0-4 ordinal for compatibility, while athlete-facing analytics use a calibrated
0-10 scale that better reflects the nonlinear jump from good to perfect.
"""

from app.models.dive import Dive


ORDINAL_SCORE = {
    "F": 0,
    "B": 1,
    "M": 2,
    "G": 3,
    "P": 4,
}

ATHLETE_SCORE_10 = {
    "F": 0.0,
    "B": 2.0,
    "M": 4.5,
    "G": 7.0,
    "P": 10.0,
}

PHASE1_WEIGHT = 0.45
PHASE2_WEIGHT = 0.55


def ordinal_score(performance: str | None) -> int | None:
    if performance is None:
        return None
    return ORDINAL_SCORE.get(performance.upper())


def athlete_score_10(performance: str | None) -> float:
    if performance is None:
        return 0.0
    return ATHLETE_SCORE_10.get(performance.upper(), 0.0)


def phase_score_10(
    phase1_performance: str | None,
    phase2_performance: str | None,
) -> float | None:
    """Weighted two-phase score on the athlete-facing 0-10 scale."""
    if not phase1_performance or not phase2_performance:
        return None

    phase1_score = athlete_score_10(phase1_performance)
    phase2_score = athlete_score_10(phase2_performance)
    return (phase1_score * PHASE1_WEIGHT) + (phase2_score * PHASE2_WEIGHT)


def dive_score_10(dive: Dive) -> float:
    two_phase_score = phase_score_10(dive.phase1_performance, dive.phase2_performance)
    if two_phase_score is not None:
        return two_phase_score

    return athlete_score_10(dive.performance)


def attempt_score_10(
    performance: str | None,
    phase1_performance: str | None = None,
    phase2_performance: str | None = None,
) -> float:
    two_phase_score = phase_score_10(phase1_performance, phase2_performance)
    if two_phase_score is not None:
        return two_phase_score

    return athlete_score_10(performance)


def is_success(performance: str | None) -> bool:
    return performance in {"M", "G", "P"}


def is_excellent(performance: str | None) -> bool:
    return performance in {"G", "P"}
