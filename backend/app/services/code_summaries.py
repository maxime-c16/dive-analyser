"""Per-code Library summaries and recent activity, computed over the full filtered scope.

The Library loads attempts page by page, so per-code numbers derived in the
browser only describe the loaded pages. This module aggregates the whole
filtered scope once so code cards and the progress view agree with the
per-code analysis.

Production path (`summarize_library_query`): a dive's score is a pure
function of (performance, phase1_performance, phase2_performance), so there
are only a handful of distinct score values. Every median is therefore
exactly computable from a score histogram, and histograms are plain
GROUP BY + COUNT queries that run identically on SQLite (gate suite) and
Postgres. Only bounded rows (recent attempts, spark windows, latest visuals)
reach Python as individual rows; memory is O(codes x distinct scores).
`summarize_codes` below is the row-based reference implementation kept for
unit tests; the gate-suite equivalence test pins both paths to the same
response.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from statistics import mean, median
from typing import Iterable

from sqlalchemy import and_, case, func

from app.models.dive import Dive
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


def _score_value(performance, phase1, phase2) -> float | None:
    if not performance:
        return None
    return attempt_score_10(performance, phase1, phase2)


def _median_from_hist(pairs) -> float | None:
    """Exact statistics.median over (score, count) pairs, without expanding rows."""
    items = sorted(pairs, key=lambda pair: pair[0])
    total = sum(count for _, count in items)
    if not total:
        return None
    if total % 2:
        target = total // 2 + 1
        seen = 0
        for score, count in items:
            seen += count
            if seen >= target:
                return score
    middle = total // 2
    lower = upper = None
    seen = 0
    for score, count in items:
        if lower is None and seen + count >= middle:
            lower = score
        if seen + count >= middle + 1:
            upper = score
            break
        seen += count
    return (lower + upper) / 2


def _hist_stats(pairs) -> dict:
    """Count/total/score-list summaries shared by every scored aggregate."""
    by_score: dict[float, int] = defaultdict(int)
    for score, count in pairs:
        by_score[score] += count
    items = sorted(by_score.items())
    total = sum(by_score.values())
    weighted = sum(score * count for score, count in items)
    return {
        "count": total,
        "average": _round(weighted / total) if total else None,
        "median": _round(_median_from_hist(items)),
        "best": _round(items[-1][0]) if items else None,
        "success_rate": round(sum(count for score, count in items if score >= SUCCESS_SCORE) / total * 100, 1) if total else None,
    }


def summarize_library_query(db, base_query, now: datetime) -> dict:
    """Full-scope summaries from SQL histograms plus bounded recent rows.

    `base_query` is the access-scoped, filtered Dive query (no order, no
    paging); this function selects it as a subquery so scope and filters are
    untouched. Only aggregate counts and at most 40 rows per code (recent,
    spark, latest candidates) are materialized.
    """
    cols = (
        Dive.id, Dive.dive_code, Dive.dive_datetime, Dive.performance,
        Dive.phase1_performance, Dive.phase2_performance, Dive.height,
        Dive.session_id, Dive.video_uuid,
    )
    sub = base_query.with_entities(*cols).statement.subquery()
    c = sub.c

    totals = db.query(
        c.dive_code, func.count().label("n"), func.count(func.distinct(c.session_id)).label("sessions"),
        func.min(c.dive_datetime).label("first"), func.max(c.dive_datetime).label("last"),
    ).select_from(sub).group_by(c.dive_code).all()
    ratings = db.query(
        c.dive_code, c.performance, func.count().label("n"),
    ).select_from(sub).group_by(c.dive_code, c.performance).all()
    heights = db.query(
        c.dive_code, c.height,
    ).select_from(sub).group_by(c.dive_code, c.height).all()
    hist = db.query(
        c.dive_code, c.performance, c.phase1_performance, c.phase2_performance, func.count().label("n"),
    ).select_from(sub).group_by(
        c.dive_code, c.performance, c.phase1_performance, c.phase2_performance,
    ).all()

    recent_start = now - timedelta(days=TREND_RECENT_DAYS)
    baseline_start = now - timedelta(days=TREND_BASELINE_DAYS)
    trend_bucket = case(
        (c.dive_datetime >= recent_start, "recent"),
        (c.dive_datetime >= baseline_start, "baseline"),
    )
    trend_rows = db.query(
        c.dive_code, trend_bucket.label("bucket"),
        c.performance, c.phase1_performance, c.phase2_performance, func.count().label("n"),
    ).select_from(sub).filter(c.dive_datetime >= baseline_start).group_by(
        c.dive_code, trend_bucket, c.performance, c.phase1_performance, c.phase2_performance,
    ).all()

    months = _month_keys(now)
    year, month = int(months[0][:4]), int(months[0][5:7])
    month_floor = datetime(year, month, 1)
    day_col = func.date(c.dive_datetime)
    month_rows = db.query(
        c.dive_code, day_col.label("day"),
        c.performance, c.phase1_performance, c.phase2_performance, func.count().label("n"),
    ).select_from(sub).filter(c.dive_datetime >= month_floor).group_by(
        c.dive_code, day_col, c.performance, c.phase1_performance, c.phase2_performance,
    ).all()

    prev_start = now - timedelta(days=60)
    cur_start = now - timedelta(days=30)
    horizon = now + timedelta(days=1)
    act_bucket = case((c.dive_datetime >= cur_start, "current"), else_="previous")
    act_counts = db.query(
        act_bucket.label("bucket"), func.count().label("n"),
        func.count(func.distinct(c.session_id)).label("sessions"),
        func.count(func.distinct(c.dive_code)).label("codes"),
    ).select_from(sub).filter(
        c.dive_datetime >= prev_start, c.dive_datetime < horizon,
    ).group_by(act_bucket).all()
    act_hist = db.query(
        c.dive_code, act_bucket.label("bucket"),
        c.performance, c.phase1_performance, c.phase2_performance, func.count().label("n"),
    ).select_from(sub).filter(
        c.dive_datetime >= prev_start, c.dive_datetime < horizon,
    ).group_by(
        c.dive_code, act_bucket, c.performance, c.phase1_performance, c.phase2_performance,
    ).all()

    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    first_monday = week_start - timedelta(weeks=WEEKS - 1)
    week_end = week_start + timedelta(weeks=1)
    week_day = func.date(c.dive_datetime)
    week_rows = db.query(
        week_day.label("day"), c.dive_code, func.count().label("n"),
    ).select_from(sub).filter(
        c.dive_datetime >= first_monday, c.dive_datetime < week_end,
    ).group_by(week_day, c.dive_code).order_by(
        week_day, func.min(c.dive_datetime), func.min(c.id),
    ).all()

    is_scored = and_(c.performance.isnot(None), c.performance != "")
    recent_inner = db.query(
        c.id, c.dive_code, c.dive_datetime, c.performance,
        c.phase1_performance, c.phase2_performance, c.height, c.video_uuid,
        func.row_number().over(
            partition_by=c.dive_code, order_by=(c.dive_datetime.desc(), c.id.desc()),
        ).label("rn"),
    ).select_from(sub).statement.subquery()
    recent_rows = db.query(recent_inner).filter(
        recent_inner.c.rn <= SPARK_ATTEMPTS,
    ).order_by(recent_inner.c.dive_code, recent_inner.c.dive_datetime, recent_inner.c.id).all()
    spark_inner = db.query(
        c.dive_code, c.dive_datetime, c.id,
        c.performance, c.phase1_performance, c.phase2_performance,
        func.row_number().over(
            partition_by=c.dive_code, order_by=(c.dive_datetime.desc(), c.id.desc()),
        ).label("rn"),
    ).select_from(sub).filter(is_scored).statement.subquery()
    spark_rows = db.query(spark_inner).filter(
        spark_inner.c.rn <= SPARK_ATTEMPTS,
    ).order_by(spark_inner.c.dive_code, spark_inner.c.dive_datetime, spark_inner.c.id).all()

    return _assemble_library_response(
        db, now, months, week_start, totals, ratings, heights, hist,
        trend_rows, month_rows, act_counts, act_hist, week_rows,
        recent_rows, spark_rows,
    )


def _assemble_library_response(
    db, now, months, week_start, totals, ratings, heights, hist,
    trend_rows, month_rows, act_counts, act_hist, week_rows,
    recent_rows, spark_rows,
) -> dict:
    codes: dict[str, dict] = {}
    for code, count, sessions, first, last in totals:
        codes[code] = {
            "attempt_count": count, "session_count": sessions,
            "first_at": first, "last_at": last, "heights": set(),
            "ratings": {}, "hist": [], "trend_hist": {"recent": [], "baseline": []},
            "months": defaultdict(list), "recent": [], "spark": [], "latest": None,
        }
    for code, performance, count in ratings:
        if code in codes and performance in ("P", "G", "M", "B", "F"):
            codes[code]["ratings"][performance] = count
    for code, height in heights:
        if code in codes and height:
            codes[code]["heights"].add(height)
    for code, performance, phase1, phase2, count in hist:
        if code not in codes:
            continue
        score = _score_value(performance, phase1, phase2)
        if score is None:
            continue
        codes[code]["hist"].append((score, count))
    for code, bucket, performance, phase1, phase2, count in trend_rows:
        if code not in codes or bucket is None:
            continue
        score = _score_value(performance, phase1, phase2)
        if score is None:
            continue
        codes[code]["trend_hist"][bucket].append((score, count))
    for code, day, performance, phase1, phase2, count in month_rows:
        if code not in codes:
            continue
        key = str(day)[:7]
        if key < months[0]:
            continue
        score = _score_value(performance, phase1, phase2)
        if score is None:
            continue
        codes[code]["months"][key].append((score, count))
    for row in recent_rows:
        acc = codes.get(row.dive_code)
        if acc is None:
            continue
        score = _score_value(row.performance, row.phase1_performance, row.phase2_performance)
        acc["recent"].append({
            "id": row.id, "performance": row.performance, "score": _round(score),
            "dive_datetime": row.dive_datetime, "height": row.height,
        })
        latest = acc["latest"]
        if latest is None or (row.dive_datetime, row.id) > (latest["dive_datetime"], latest["id"]):
            acc["latest"] = {"id": row.id, "dive_code": row.dive_code, "dive_datetime": row.dive_datetime, "video_uuid": row.video_uuid}
    for row in spark_rows:
        acc = codes.get(row.dive_code)
        if acc is None:
            continue
        score = _score_value(row.performance, row.phase1_performance, row.phase2_performance)
        if score is not None:
            acc["spark"].append(score)

    from app.api.v1.dives import _library_visuals
    visuals = _library_visuals(db, [
        acc["latest"]["video_uuid"] for acc in codes.values()
        if acc["latest"] and acc["latest"]["video_uuid"]
    ])

    out = []
    for code, acc in codes.items():
        analytics = is_analytics_dive(code)
        stats = _hist_stats(acc["hist"])
        trend = None
        if analytics:
            recent_pairs = acc["trend_hist"]["recent"]
            baseline_pairs = acc["trend_hist"]["baseline"]
            recent_n = sum(n for _, n in recent_pairs)
            baseline_n = sum(n for _, n in baseline_pairs)
            if recent_n >= TREND_MIN_ATTEMPTS and baseline_n >= TREND_MIN_ATTEMPTS:
                trend = {
                    "delta": round(_median_from_hist(recent_pairs) - _median_from_hist(baseline_pairs), 2),
                    "recent_count": recent_n, "baseline_count": baseline_n,
                }
        spark_values = acc["spark"][-SPARK_ATTEMPTS:]
        out.append({
            "dive_code": code,
            "analytics": analytics,
            "attempt_count": acc["attempt_count"],
            "scored_count": stats["count"],
            "session_count": acc["session_count"],
            "average": stats["average"],
            "median": stats["median"],
            "best": stats["best"],
            "success_rate": stats["success_rate"],
            "first_attempt_at": acc["first_at"],
            "last_attempt_at": acc["last_at"],
            "heights": sorted(acc["heights"]),
            "ratings": {rating: acc["ratings"][rating] for rating in ("P", "G", "M", "B", "F") if acc["ratings"].get(rating)},
            "trend": trend,
            "spark": _rolling_median(spark_values, SPARK_WINDOW) if analytics else [],
            "months": {key: {"count": sum(n for _, n in pairs), "median": _round(_median_from_hist(pairs))} for key, pairs in sorted(acc["months"].items())},
            "recent": list(reversed(acc["recent"][-RECENT_ATTEMPTS:])),
            "latest": {
                "id": acc["latest"]["id"], "dive_code": code, "dive_datetime": acc["latest"]["dive_datetime"],
                "video_uuid": acc["latest"]["video_uuid"], **visuals.get(acc["latest"]["video_uuid"] or "", {}),
            } if acc["latest"] else None,
        })
    out.sort(key=lambda item: (item["last_attempt_at"], item["dive_code"]), reverse=True)

    week = timedelta(weeks=1)
    slots = [{"count": 0, "per_code": {}} for _ in range(WEEKS)]
    for day, code, count in week_rows:
        index = (datetime.strptime(str(day)[:10], "%Y-%m-%d").date() - week_start.date()).days // 7 + (WEEKS - 1)
        if 0 <= index < WEEKS:
            slot = slots[index]
            slot["count"] += count
            slot["per_code"][code] = slot["per_code"].get(code, 0) + count
    weeks = []
    for offset in range(WEEKS - 1, -1, -1):
        start = week_start - offset * week
        slot = slots[(WEEKS - 1) - offset]
        weeks.append({
            "start": start.date(),
            "attempt_count": slot["count"],
            "codes": dict(sorted(slot["per_code"].items(), key=lambda item: -item[1])),
        })

    counts = {"current": (0, 0, 0), "previous": (0, 0, 0)}
    for bucket, count, sessions, code_count in act_counts:
        if bucket in counts:
            counts[bucket] = (count, sessions, code_count)
    medians: dict[str, list] = {"current": [], "previous": []}
    for code, bucket, performance, phase1, phase2, count in act_hist:
        if bucket not in medians or not is_analytics_dive(code):
            continue
        score = _score_value(performance, phase1, phase2)
        if score is None:
            continue
        medians[bucket].append((score, count))

    def _activity(bucket: str) -> dict:
        count, sessions, code_count = counts[bucket]
        return {
            "attempt_count": count, "session_count": sessions, "code_count": code_count,
            "median": _round(_median_from_hist(medians[bucket])),
        }

    return {
        "generated_at": now,
        "codes": out,
        "activity": {
            "current": _activity("current"),
            "previous": _activity("previous"),
            "months": months,
            "weeks": weeks,
        },
    }
