"""Per-code Library summaries and recent activity, computed over the full filtered scope.

The Library loads attempts page by page, so per-code numbers derived in the
browser only describe the loaded pages. This module aggregates the whole
filtered scope once so code cards and the progress view agree with the
per-code analysis.

Memory discipline (single worker): the endpoint streams its rows in SQL
order and folds them into compact per-code accumulators — counts, small
sets, score floats and bounded recent/latest trackers — instead of
materializing full ORM objects for the whole scope. Only bounded recent
attempts and visuals stay in memory alongside those accumulators.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
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
WINDOW_DAYS = 60

# Row layout for the streaming path: (id, dive_code, dive_datetime,
# performance, phase1, phase2, height, session_id, video_uuid).
_ROW_FIELDS = 9


def _round(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def _tuple_score(row: tuple) -> float | None:
    if not row[3]:
        return None
    return attempt_score_10(row[3], row[4], row[5])


def _rolling_median(values: list[float], window: int) -> list[float]:
    return [round(median(values[max(0, index - window + 1):index + 1]), 2) for index in range(len(values))]


def _month_keys(now: datetime) -> list[str]:
    keys, year, month = [], now.year, now.month
    for _ in range(MONTHS):
        keys.append(f"{year:04d}-{month:02d}")
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    return keys[::-1]


def _trend(scored: list[tuple[datetime, float]], now: datetime) -> dict | None:
    recent_start = now - timedelta(days=TREND_RECENT_DAYS)
    baseline_start = now - timedelta(days=TREND_BASELINE_DAYS)
    recent = [score for when, score in scored if when >= recent_start]
    baseline = [score for when, score in scored if baseline_start <= when < recent_start]
    if len(recent) < TREND_MIN_ATTEMPTS or len(baseline) < TREND_MIN_ATTEMPTS:
        return None
    return {"delta": round(median(recent) - median(baseline), 2), "recent_count": len(recent), "baseline_count": len(baseline)}


def _new_code_acc() -> dict:
    return {
        "count": 0,
        "sessions": set(),
        "heights": set(),
        "ratings": Counter(),
        "first_at": None,
        "scored": [],  # [(dive_datetime, score)], SQL order
        "recent": deque(maxlen=RECENT_ATTEMPTS),  # (id, performance, score, datetime, height)
        "latest": None,  # (id, dive_datetime, video_uuid)
    }


def accumulate_ordered(rows: Iterable[tuple], now: datetime) -> dict:
    """Fold (dive_datetime, id)-ordered rows into compact per-code accumulators.

    Retains score floats, datetimes and bounded recent/latest trackers — never
    full rows — so memory stays proportional to compact values, not the scope.
    """
    months = _month_keys(now)
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    window_cutoff = now - timedelta(days=WINDOW_DAYS)
    week = timedelta(weeks=1)
    state = {
        "now": now,
        "months": months,
        "week_start": week_start,
        "codes": {},
        "weeks": [{"count": 0, "per_code": {}} for _ in range(WEEKS)],
        "window_rows": [],  # (datetime, session_id, code, score|None, analytics) within 60 d
    }
    for row in rows:
        dive_id, code, when, performance, _, _, height, session_id, video_uuid = row[:_ROW_FIELDS]
        acc = state["codes"].get(code)
        if acc is None:
            acc = state["codes"][code] = _new_code_acc()
        acc["count"] += 1
        acc["sessions"].add(session_id)
        if height:
            acc["heights"].add(height)
        if performance in ("P", "G", "M", "B", "F"):
            acc["ratings"][performance] += 1
        if acc["first_at"] is None:
            acc["first_at"] = when
        analytics = is_analytics_dive(code)
        score = _tuple_score(row)
        if score is not None:
            acc["scored"].append((when, score))
        acc["recent"].append((dive_id, performance, score, when, height))
        acc["latest"] = (dive_id, when, video_uuid)
        bucket = (when - week_start) // week + (WEEKS - 1)
        if 0 <= bucket < WEEKS:
            slot = state["weeks"][bucket]
            slot["count"] += 1
            slot["per_code"][code] = slot["per_code"].get(code, 0) + 1
        if when >= window_cutoff:
            state["window_rows"].append((when, session_id, code, score if analytics else None, analytics))
    return state


def latest_uuids(state: dict) -> list[str]:
    """Latest ready-visual candidates, one per code, for the bounded visuals join."""
    return [acc["latest"][2] for acc in state["codes"].values() if acc["latest"] and acc["latest"][2]]


def _window_from(rows: list[tuple], start: datetime, end: datetime) -> dict:
    inside = [row for row in rows if start <= row[0] < end]
    scores = [row[3] for row in inside if row[4] and row[3] is not None]
    return {
        "attempt_count": len(inside),
        "session_count": len({row[1] for row in inside}),
        "code_count": len({row[2] for row in inside}),
        "median": _round(median(scores)) if scores else None,
    }


def render_summaries(state: dict, visuals: dict[str, dict]) -> dict:
    """Assemble the API response from accumulators plus bounded visuals."""
    now = state["now"]
    months = state["months"]
    codes = []
    for code, acc in state["codes"].items():
        analytics = is_analytics_dive(code)
        scored = acc["scored"]
        values = [score for _, score in scored]
        per_month: dict[str, list[float]] = defaultdict(list)
        for when, score in scored:
            key = when.strftime("%Y-%m")
            if key >= months[0]:
                per_month[key].append(score)
        latest_id, latest_at, latest_uuid = acc["latest"]
        codes.append({
            "dive_code": code,
            "analytics": analytics,
            "attempt_count": acc["count"],
            "scored_count": len(values),
            "session_count": len(acc["sessions"]),
            "average": _round(mean(values)) if values else None,
            "median": _round(median(values)) if values else None,
            "best": _round(max(values)) if values else None,
            "success_rate": round(sum(value >= SUCCESS_SCORE for value in values) / len(values) * 100, 1) if values else None,
            "first_attempt_at": acc["first_at"],
            "last_attempt_at": latest_at,
            "heights": sorted(acc["heights"]),
            "ratings": {rating: acc["ratings"][rating] for rating in ("P", "G", "M", "B", "F") if acc["ratings"][rating]},
            "trend": _trend(scored, now) if analytics else None,
            "spark": _rolling_median(values[-SPARK_ATTEMPTS:], SPARK_WINDOW) if analytics else [],
            "months": {key: {"count": len(scores), "median": _round(median(scores))} for key, scores in sorted(per_month.items())},
            "recent": [
                {"id": dive_id, "performance": performance, "score": _round(score), "dive_datetime": when, "height": height}
                for dive_id, performance, score, when, height in reversed(acc["recent"])
            ],
            "latest": {
                "id": latest_id, "dive_code": code, "dive_datetime": latest_at,
                "video_uuid": latest_uuid, **visuals.get(latest_uuid or "", {}),
            },
        })
    codes.sort(key=lambda item: (item["last_attempt_at"], item["dive_code"]), reverse=True)
    week_start = state["week_start"]
    week = timedelta(weeks=1)
    weeks = []
    for offset in range(WEEKS - 1, -1, -1):
        start = week_start - offset * week
        slot = state["weeks"][(WEEKS - 1) - offset]
        weeks.append({
            "start": start.date(),
            "attempt_count": slot["count"],
            "codes": dict(sorted(slot["per_code"].items(), key=lambda item: -item[1])),
        })
    return {
        "generated_at": now,
        "codes": codes,
        "activity": {
            "current": _window_from(state["window_rows"], now - timedelta(days=30), now + timedelta(days=1)),
            "previous": _window_from(state["window_rows"], now - timedelta(days=60), now - timedelta(days=30)),
            "months": months,
            "weeks": weeks,
        },
    }


def _as_tuple(dive) -> tuple:
    if isinstance(dive, tuple):
        return tuple(dive)[:_ROW_FIELDS]
    return (
        dive.id, dive.dive_code, dive.dive_datetime, dive.performance,
        dive.phase1_performance, dive.phase2_performance, dive.height,
        dive.session_id, dive.video_uuid,
    )


def summarize_stream(rows: Iterable[tuple], visuals: dict[str, dict], now: datetime) -> dict:
    """Aggregate (dive_datetime, id)-ordered rows without retaining full rows."""
    return render_summaries(accumulate_ordered(rows, now), visuals)


def summarize_codes(dives: Iterable, visuals: dict[str, dict], now: datetime) -> dict:
    """Aggregate attempts (any order) into per-code summaries and recent activity."""
    ordered = sorted((_as_tuple(dive) for dive in dives), key=lambda row: (row[2], row[0]))
    return render_summaries(accumulate_ordered(ordered, now), visuals)
