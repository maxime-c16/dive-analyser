"""Official difficulty metadata summaries for DiveSensei analytics."""

from __future__ import annotations

from statistics import mean, median
from typing import Iterable, Literal

from app.models.dive import Dive
from app.services.world_aquatics_dd import OfficialDDUndefined, REFERENCE_ID, calculate_official_dd


def formula_dd(dive: Dive) -> float | None:
    """Return the live rulebook DD for an attempt, or None when undefined."""
    try:
        return float(calculate_official_dd(dive.dive_code, dive.height).dd)
    except OfficialDDUndefined:
        return None


def difficulty_summary(
    dives: Iterable[Dive],
    weighting: Literal["attempts", "sessions"] = "attempts",
) -> dict:
    """Summarize DD coverage without treating DD as an execution multiplier."""
    attempts = list(dives)
    scored = [dive for dive in attempts if dive.performance]
    pairs = [(dive, formula_dd(dive)) for dive in scored]
    dd_values = [dd for _, dd in pairs if dd is not None]
    return {
        "dd_defined_attempt_count": len(dd_values),
        "dd_coverage_rate": round((len(dd_values) / len(scored)) * 100, 1) if scored else None,
        "average_dd": round(mean(dd_values), 2) if dd_values else None,
        "median_dd": round(median(dd_values), 2) if dd_values else None,
        "max_dd": round(max(dd_values), 2) if dd_values else None,
        "dd_reference": REFERENCE_ID,
    }
