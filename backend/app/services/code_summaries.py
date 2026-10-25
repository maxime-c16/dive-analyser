"""Per-code Library summaries and recent activity, computed over the full filtered scope.

The Library loads attempts page by page, so per-code numbers derived in the
browser only describe the loaded pages. This module aggregates the whole
filtered scope once so code cards and the progress view agree with the
per-code analysis.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from statistics import mean, median
from typing import Iterable

from app.services.dive_analysis_service import is_analytics_dive
from app.services.performance_scoring import ATHLETE_SCORE_10, attempt_score_10

RECENT_ATTEMPTS = 16
SPARK_ATTEMPTS = 40
SPARK_WINDOW = 5
TREND_RECENT_DAYS = 42
TREND_BASELINE_DAYS = 182
TREND_MIN_ATTEMPTS = 4
MONTHS = 12
WEEKS = 26
SUCCESS_SCORE = ATHLETE_SCORE_10["G"]


def _round(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def _score(dive) -> float | None:
    if not dive.performance:
        return None
    return attempt_score_10(dive.performance, dive.phase1_performance, dive.phase2_performance)


def _rolling_median(values: list[float], window: int) -> list[float]:
    return [round(median(values[max(0, index - window + 1):index + 1]), 2) for index in range(len(values))]


def _month_keys(now: datetime) -> list[str]:
    keys, year, month = [], now.year, now.month
    for _ in range(MONTHS):
        keys.append(f"{year:04d}-{month:02d}")
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    return keys[::-1]


def _trend(scored: list[tuple[object, float]], now: datetime) -> dict | None:
    recent_start = now - timedelta(days=TREND_RECENT_DAYS)
    baseline_start = now - timedelta(days=TREND_BASELINE_DAYS)
    recent = [score for dive, score in scored if dive.dive_datetime >= recent_start]
    baseline = [score for dive, score in scored if baseline_start <= dive.dive_datetime < recent_start]
    if len(recent) < TREND_MIN_ATTEMPTS or len(baseline) < TREND_MIN_ATTEMPTS:
        return None
    return {"delta": round(median(recent) - median(baseline), 2), "recent_count": len(recent), "baseline_count": len(baseline)}


def _window(dives: list, start: datetime, end: datetime) -> dict:
    inside = [dive for dive in dives if start <= dive.dive_datetime < end]
    scores = [score for score in (_score(dive) for dive in inside if is_analytics_dive(dive.dive_code)) if score is not None]
    return {
        "attempt_count": len(inside),
        "session_count": len({dive.session_id for dive in inside}),
        "code_count": len({dive.dive_code for dive in inside}),
        "median": _round(median(scores)) if scores else None,
    }


def summarize_codes(dives: Iterable, visuals: dict[str, dict], now: datetime) -> dict:
    """Aggregate attempts (any order) into per-code summaries and recent activity."""
    ordered = sorted(dives, key=lambda dive: (dive.dive_datetime, dive.id))
    by_code: dict[str, list] = defaultdict(list)
    for dive in ordered:
        by_code[dive.dive_code].append(dive)
    months = _month_keys(now)
    codes = []
    for code, attempts in by_code.items():
        analytics = is_analytics_dive(code)
        scored = [(dive, score) for dive in attempts if (score := _score(dive)) is not None]
        values = [score for _, score in scored]
        per_month: dict[str, list[float]] = defaultdict(list)
        for dive, score in scored:
            key = dive.dive_datetime.strftime("%Y-%m")
            if key >= months[0]:
                per_month[key].append(score)
        latest = attempts[-1]
        codes.append({
            "dive_code": code,
            "analytics": analytics,
            "attempt_count": len(attempts),
            "scored_count": len(values),
            "session_count": len({dive.session_id for dive in attempts}),
            "average": _round(mean(values)) if values else None,
            "median": _round(median(values)) if values else None,
            "best": _round(max(values)) if values else None,
            "success_rate": round(sum(value >= SUCCESS_SCORE for value in values) / len(values) * 100, 1) if values else None,
            "first_attempt_at": attempts[0].dive_datetime,
            "last_attempt_at": latest.dive_datetime,
            "heights": sorted({dive.height for dive in attempts if dive.height}),
            "ratings": {rating: count for rating in ("P", "G", "M", "B", "F") if (count := sum(dive.performance == rating for dive in attempts))},
            "trend": _trend(scored, now) if analytics else None,
            "spark": _rolling_median(values[-SPARK_ATTEMPTS:], SPARK_WINDOW) if analytics else [],
            "months": {key: {"count": len(scores), "median": _round(median(scores))} for key, scores in sorted(per_month.items())},
            "recent": [
                {"id": dive.id, "performance": dive.performance, "score": _round(_score(dive)), "dive_datetime": dive.dive_datetime, "height": dive.height}
                for dive in reversed(attempts[-RECENT_ATTEMPTS:])
            ],
            "latest": {
                "id": latest.id, "dive_code": code, "dive_datetime": latest.dive_datetime,
                "video_uuid": latest.video_uuid, **visuals.get(latest.video_uuid or "", {}),
            },
        })
    codes.sort(key=lambda item: (item["last_attempt_at"], item["dive_code"]), reverse=True)
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    weeks = []
    for offset in range(WEEKS - 1, -1, -1):
        start = week_start - timedelta(weeks=offset)
        inside = [dive for dive in ordered if start <= dive.dive_datetime < start + timedelta(weeks=1)]
        per_code: dict[str, int] = defaultdict(int)
        for dive in inside:
            per_code[dive.dive_code] += 1
        weeks.append({"start": start.date(), "attempt_count": len(inside), "codes": dict(sorted(per_code.items(), key=lambda item: -item[1]))})
    return {
        "generated_at": now,
        "codes": codes,
        "activity": {
            "current": _window(ordered, now - timedelta(days=30), now + timedelta(days=1)),
            "previous": _window(ordered, now - timedelta(days=60), now - timedelta(days=30)),
            "months": months,
            "weeks": weeks,
        },
    }
