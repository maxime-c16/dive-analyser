"""Filtered, attempt-traceable analytics for one canonical dive code."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import re
from statistics import mean, median, pstdev
from typing import Iterable, Literal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.dive import Dive
from app.models.media import MediaCacheEntry, MediaJob
from app.models.training_period import TrainingPeriod
from app.services.media_cache import playback_url
from app.services.performance_scoring import ATHLETE_SCORE_10, dive_score_10
from app.services.diver_identity import get_primary_diver
from app.services.difficulty_adjustment import difficulty_summary, formula_dd

SUCCESS_ORDER = {"F": 0, "B": 1, "M": 2, "G": 3, "P": 4}
Weighting = Literal["attempts", "sessions"]
CANONICAL_DIVE_CODE_RE = re.compile(r"^\d{3,4}[ABCD]$")
OPEN_PIKE_DIVE_CODE_RE = re.compile(r"^(\d{3,4})BO$")


def canonical_dive_code(value: str) -> str:
    code = "".join(value.upper().split())
    open_pike = OPEN_PIKE_DIVE_CODE_RE.fullmatch(code)
    if open_pike:
        return f"{open_pike.group(1)}B"
    if not CANONICAL_DIVE_CODE_RE.fullmatch(code):
        raise ValueError("Dive code must be an exact canonical code such as 103B")
    return code


def is_analytics_dive(code: str) -> bool:
    return not code.startswith(("100", "200", "300", "400"))


def _quartiles(values: list[float]) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    lower = ordered[:midpoint]
    upper = ordered[midpoint + len(ordered) % 2:]
    return median(lower) if lower else ordered[0], median(upper) if upper else ordered[-1]


def sample_label(count: int) -> str:
    if count == 0:
        return "no_data"
    if count <= 2:
        return "insufficient"
    if count <= 5:
        return "exploratory"
    if count <= 11:
        return "moderate_sample"
    return "stronger_descriptive_sample"


def summarize_values(values: list[float]) -> dict:
    q1, q3 = _quartiles(values)
    return {
        "count": len(values),
        "average": round(mean(values), 2) if values else None,
        "median": round(median(values), 2) if values else None,
        "minimum": round(min(values), 2) if values else None,
        "maximum": round(max(values), 2) if values else None,
        "standard_deviation": round(pstdev(values), 2) if len(values) > 1 else 0.0 if values else None,
        "q1": round(q1, 2) if q1 is not None else None,
        "q3": round(q3, 2) if q3 is not None else None,
        "iqr": round(q3 - q1, 2) if q1 is not None and q3 is not None else None,
    }


def _weighted_scores(dives: list[Dive], weighting: Weighting) -> list[float]:
    scored = [dive for dive in dives if dive.performance]
    if weighting == "attempts":
        return [dive_score_10(dive) for dive in scored]
    by_session: dict[int, list[float]] = defaultdict(list)
    for dive in scored:
        by_session[dive.session_id].append(dive_score_10(dive))
    return [median(values) for values in by_session.values()]


def summarize(dives: Iterable[Dive], success_threshold: str = "G", weighting: Weighting = "attempts") -> dict:
    attempts = list(dives)
    values = _weighted_scores(attempts, weighting)
    value_summary = summarize_values(values)
    threshold_score = ATHLETE_SCORE_10[success_threshold]
    best = max(attempts, key=dive_score_10) if attempts else None
    worst = min(attempts, key=dive_score_10) if attempts else None
    return {
        "attempt_count": len(attempts),
        "session_count": len({dive.session_id for dive in attempts}),
        "scored_attempt_count": sum(bool(dive.performance) for dive in attempts),
        "unscored_attempt_count": sum(not bool(dive.performance) for dive in attempts),
        **{key: value for key, value in value_summary.items() if key != "count"},
        "success_rate": round(sum(value >= threshold_score for value in values) / len(values) * 100, 1) if values else None,
        "success_threshold": success_threshold,
        "weighting_mode": "session_weighted" if weighting == "sessions" else "attempt_weighted",
        "best_attempt_id": best.id if best else None,
        "worst_attempt_id": worst.id if worst else None,
        "first_attempt_at": min((d.dive_datetime for d in attempts), default=None),
        "last_attempt_at": max((d.dive_datetime for d in attempts), default=None),
        **difficulty_summary(attempts, weighting),
    }


def rolling_values(points: list[tuple[int, float | None]], window: int = 5) -> dict[int, float | None]:
    result = {}
    for index, (point_id, _) in enumerate(points):
        values = [value for _, value in points[max(0, index - window + 1):index + 1] if value is not None]
        result[point_id] = round(median(values), 2) if values else None
    return result


def rolling_median(dives: list[Dive], window: int = 5) -> dict[int, float | None]:
    ordered = sorted(dives, key=lambda dive: (dive.dive_datetime, dive.id))
    return rolling_values([(dive.id, dive_score_10(dive) if dive.performance else None) for dive in ordered], window)


def trend(dives: list[Dive]) -> dict:
    ordered = sorted((dive for dive in dives if dive.performance), key=lambda dive: (dive.dive_datetime, dive.id))
    if len(ordered) < 5:
        return {"direction": "insufficient_data", "slope_per_30_days": None, "confidence": "insufficient", "reason": "Fewer than 5 attempts"}
    span_days = (ordered[-1].dive_datetime - ordered[0].dive_datetime).total_seconds() / 86400
    if span_days < 14:
        return {"direction": "insufficient_data", "slope_per_30_days": None, "confidence": "insufficient", "reason": "Less than 14 days of observations"}
    origin = ordered[0].dive_datetime
    xs = [(item.dive_datetime - origin).total_seconds() / 86400 for item in ordered]
    ys = [dive_score_10(item) for item in ordered]
    x_mean, y_mean = mean(xs), mean(ys)
    denominator = sum((x - x_mean) ** 2 for x in xs)
    monthly = (sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denominator if denominator else 0) * 30
    threshold = max(0.2, pstdev(ys) * 0.15 if len(ys) > 1 else 0.2)
    direction = "improving" if monthly > threshold else "declining" if monthly < -threshold else "stable"
    return {"direction": direction, "slope_per_30_days": round(monthly, 2), "confidence": sample_label(len(ordered)), "reason": None}


def build_insights(current: dict, previous: dict | None, current_dives: list[Dive], previous_dives: list[Dive]) -> list[dict]:
    if not previous:
        return [{"type": "sample", "tone": "neutral", "confidence": "insufficient", "title": "Period comparison unavailable", "message": "Choose a bounded date range to compare it with the immediately preceding period.", "evidence": {"current_attempts": current["attempt_count"]}}]
    confidence = sample_label(min(current["attempt_count"], previous["attempt_count"]))
    evidence = {"current_attempts": current["attempt_count"], "previous_attempts": previous["attempt_count"]}
    if min(current["attempt_count"], previous["attempt_count"]) < 3:
        return [{"type": "sample", "tone": "neutral", "confidence": confidence, "title": "Not enough comparable attempts", "message": "At least 3 attempts are needed in both periods before describing a change.", "evidence": evidence}]
    insights = []
    if current["median"] is not None and previous["median"] is not None:
        change = round(current["median"] - previous["median"], 2)
        if abs(change) >= 0.25:
            insights.append({"type": "median_change", "tone": "positive" if change > 0 else "negative", "confidence": confidence, "title": f"Recent median {'increased' if change > 0 else 'decreased'}", "message": f"Observed median moved from {previous['median']:.1f} to {current['median']:.1f} ({change:+.1f}).", "evidence": evidence | {"change": change}})
    if current["iqr"] is not None and previous["iqr"] is not None:
        change = round(current["iqr"] - previous["iqr"], 2)
        if abs(change) >= 0.25:
            insights.append({"type": "consistency_change", "tone": "positive" if change < 0 else "caution", "confidence": confidence, "title": "Attempts became more consistent" if change < 0 else "Score spread increased", "message": f"Observed interquartile range moved from {previous['iqr']:.1f} to {current['iqr']:.1f}.", "evidence": evidence | {"change": change}})
    if current.get("average_dd") is not None and previous.get("average_dd") is not None:
        dd_change = round(current["average_dd"] - previous["average_dd"], 2)
        if abs(dd_change) >= 0.1:
            insights.append({"type": "difficulty_context_shift", "tone": "caution", "confidence": confidence, "title": "Difficulty context changed", "message": f"Average official DD moved from {previous['average_dd']:.2f} to {current['average_dd']:.2f}. Compare execution /10 alongside the changed difficulty context rather than treating them as one score.", "evidence": evidence | {"average_dd_change": dd_change, "current_dd_coverage_rate": current.get("dd_coverage_rate"), "previous_dd_coverage_rate": previous.get("dd_coverage_rate")}})
    if all(item.get("average") is not None and item.get("median") is not None for item in (current, previous)):
        if current["average"] - previous["average"] >= 0.4 and current["median"] - previous["median"] < 0.25:
            insights.append({"type": "outlier_sensitivity", "tone": "caution", "confidence": confidence, "title": "Average improvement is not reflected in the median", "message": "A small number of high attempts may be driving the average change.", "evidence": evidence})
    current_heights, previous_heights = Counter(d.height for d in current_dives), Counter(d.height for d in previous_dives)
    if current_heights and previous_heights and current_heights.most_common(1)[0][0] != previous_heights.most_common(1)[0][0]:
        insights.append({"type": "context_shift", "tone": "caution", "confidence": confidence, "title": "Height context changed", "message": f"Most attempts moved from {previous_heights.most_common(1)[0][0]} to {current_heights.most_common(1)[0][0]}; the periods are not directly equivalent.", "evidence": evidence})
    return insights or [{"type": "stable", "tone": "neutral", "confidence": confidence, "title": "No material period change detected", "message": "Median and score spread remain similar across the two periods.", "evidence": evidence}]


def phase_analysis(current: list[Dive], previous: list[Dive]) -> dict:
    result = {"total_attempts": len(current), "phases": {}}
    for key, attribute in (("phase1", "phase1_performance"), ("phase2", "phase2_performance")):
        raw = [(dive.id, ATHLETE_SCORE_10.get(getattr(dive, attribute)) if getattr(dive, attribute) else None) for dive in current]
        values = [value for _, value in raw if value is not None]
        previous_values = [ATHLETE_SCORE_10[getattr(dive, attribute)] for dive in previous if getattr(dive, attribute)]
        rolling = rolling_values(raw)
        result["phases"][key] = {
            "available_count": len(values), "missing_count": len(current) - len(values),
            "summary": summarize_values(values), "previous_summary": summarize_values(previous_values),
            "distribution": dict(Counter(getattr(dive, attribute) for dive in current if getattr(dive, attribute))),
            "points": [{"attempt_id": dive.id, "dive_datetime": dive.dive_datetime, "score": score, "rolling_median": rolling[dive.id]} for dive, (_, score) in zip(current, raw) if score is not None],
        }
    return result


class DiveAnalysisService:
    def __init__(self, db: Session):
        self.db = db

    def query_dives(self, dive_code: str, filters: dict, *, date_from: datetime | None = None, date_to: datetime | None = None) -> list[Dive]:
        stmt = select(Dive).options(selectinload(Dive.modifiers), selectinload(Dive.session), selectinload(Dive.diver)).where(Dive.dive_code == dive_code, Dive.is_lineup.is_(False))
        start = date_from if date_from is not None else filters.get("date_from")
        end = date_to if date_to is not None else filters.get("date_to")
        period_ids = filters.get("training_period_ids") or []
        if period_ids and date_from is None and date_to is None:
            periods = list(self.db.execute(select(TrainingPeriod).where(TrainingPeriod.id.in_(period_ids))).scalars())
            if periods:
                stmt = stmt.where(or_(*[Dive.dive_datetime.between(datetime.combine(period.start_date, datetime.min.time()), datetime.combine(period.end_date, datetime.max.time())) for period in periods]))
            else:
                return []
        if start:
            stmt = stmt.where(Dive.dive_datetime >= start)
        if end:
            stmt = stmt.where(Dive.dive_datetime <= end)
        for field in ("height", "platform_type", "position", "session_id"):
            if filters.get(field) not in (None, ""):
                stmt = stmt.where(getattr(Dive, field) == filters[field])
        if filters.get("is_sync") is not None:
            stmt = stmt.where(Dive.is_sync.is_(filters["is_sync"]))
        if filters.get("diver_ids"):
            stmt = stmt.where(Dive.diver_id.in_(filters["diver_ids"]))
        elif filters.get("diver"):
            stmt = stmt.where(Dive.person_name == filters["diver"])
        elif filters.get("diver_scope", "self") == "self":
            context = self.db.info.get("member_access")
            if context:
                stmt = stmt.where(Dive.diver_id.in_(context["diver_ids"]))
            else:
                primary = get_primary_diver(self.db)
                stmt = stmt.where(or_(Dive.diver_id == primary.id, (Dive.diver_id.is_(None) & Dive.person_name.is_(None))))
        if filters.get("performance"):
            stmt = stmt.where(Dive.performance.in_(filters["performance"]))
        dives = list(self.db.execute(stmt.order_by(Dive.dive_datetime.asc(), Dive.id.asc())).scalars().unique().all())
        selected, mode = set(filters.get("modifiers") or []), filters.get("modifier_mode", "any")
        if selected or mode == "none":
            def matches(dive: Dive) -> bool:
                codes = {modifier.modifier_code for modifier in dive.modifiers}
                return not codes if mode == "none" else selected.issubset(codes) if mode == "all" else bool(selected & codes)
            dives = [dive for dive in dives if matches(dive)]
        return dives

    def matching_periods(self, dives: list[Dive]) -> tuple[list[TrainingPeriod], dict[int, list[TrainingPeriod]]]:
        if not dives:
            return [], {}
        first, last = min(d.dive_datetime.date() for d in dives), max(d.dive_datetime.date() for d in dives)
        periods = list(self.db.execute(select(TrainingPeriod).where(TrainingPeriod.active.is_(True), TrainingPeriod.start_date <= last, TrainingPeriod.end_date >= first).order_by(TrainingPeriod.start_date)).scalars())
        mapping = {dive.id: [period for period in periods if period.start_date <= dive.dive_datetime.date() <= period.end_date] for dive in dives}
        return periods, mapping

    def media_maps(self, dives: list[Dive]):
        asset_ids = {d.photos_asset_id for d in dives if d.photos_asset_id}
        if not asset_ids:
            return {}, {}
        entries = self.db.execute(select(MediaCacheEntry).where(MediaCacheEntry.photos_asset_id.in_(asset_ids), MediaCacheEntry.status == "ready", MediaCacheEntry.rendition != "animated")).scalars().all()
        jobs = self.db.execute(select(MediaJob).where(MediaJob.photos_asset_id.in_(asset_ids)).order_by(MediaJob.updated_at.desc())).scalars().all()
        entry_map, job_map = defaultdict(list), {}
        for entry in entries:
            entry_map[entry.photos_asset_id].append(entry)
        for job in jobs:
            job_map.setdefault(job.photos_asset_id, job)
        return entry_map, job_map

    def serialize_attempts(
        self, dives: list[Dive], period_map: dict[int, list[TrainingPeriod]] | None = None
    ) -> list[dict]:
        rolling = rolling_median(dives)
        entries, jobs = self.media_maps(dives)
        # period_map can be shared from the caller that already computed it
        # for the cached analysis payload; recompute only when not given.
        if period_map is None:
            _, period_map = self.matching_periods(dives)
        result = []
        for dive in dives:
            cached = entries.get(dive.photos_asset_id, []) if dive.photos_asset_id else []
            # Lot B: prefer 720p, keep legacy 360p readable until replaced.
            proxy = next((item for item in cached if item.rendition == "proxy_720p"), None) or next(
                (item for item in cached if item.rendition == "proxy_360p"), None
            )
            poster = next((item for item in cached if item.rendition == "poster"), None)
            job = jobs.get(dive.photos_asset_id) if dive.photos_asset_id else None
            result.append({
                "id": dive.id, "dive_code": dive.dive_code, "dive_datetime": dive.dive_datetime,
                "performance": dive.performance, "performance_numeric": round(dive_score_10(dive), 2),
                "phase1_performance": dive.phase1_performance, "phase1_numeric": ATHLETE_SCORE_10.get(dive.phase1_performance) if dive.phase1_performance else None,
                "phase2_performance": dive.phase2_performance, "phase2_numeric": ATHLETE_SCORE_10.get(dive.phase2_performance) if dive.phase2_performance else None,
                "rolling_median": rolling[dive.id], "height": dive.height, "platform_type": dive.platform_type,
                "position": dive.position, "is_sync": dive.is_sync, "modifiers": sorted(modifier.modifier_code for modifier in dive.modifiers),
                "diver": {"id": dive.diver.id, "display_name": dive.diver.display_name, "is_primary_user": dive.diver.is_primary_user} if dive.diver else None,
                "legacy_person_name": dive.person_name, "session_id": dive.session_id, "session_date": dive.session.date if dive.session else None,
                "training_periods": [{"id": period.id, "name": period.name, "period_type": period.period_type} for period in period_map.get(dive.id, [])],
                # Formula DD is the live source of truth. Stored DD remains
                # available as a migration/audit record but must not make a
                # current attempt-detail display stale.
                "official_dd": formula_dd(dive),
                "dd_reference": "ffn_world_aquatics_diving_2022_2025_appendix_1_3",
                "raw_caption": dive.raw_caption if not self.db.info.get("member_access") or dive.diver_id in self.db.info["member_access"]["diver_ids"] else None, "notes": dive.notes if not self.db.info.get("member_access") or dive.diver_id in self.db.info["member_access"]["diver_ids"] else None, "video_uuid": dive.video_uuid,
                "media": {"status": "ready" if proxy else job.status if job else "missing", "poster_url": playback_url(poster) if poster else None, "playback_url": playback_url(proxy) if proxy else None, "can_request": bool(dive.video_uuid), "job_id": job.id if job else None, "job_error": job.last_error if job else None},
            })
        return result

    def breakdown(self, dives: list[Dive], dimension: str, success_threshold: str, weighting: Weighting, *, period_map: dict | None = None) -> list[dict]:
        groups: dict[tuple[str, int | None], list[Dive]] = defaultdict(list)
        if dimension == "training_period" and period_map is None:
            _, period_map = self.matching_periods(dives)
        for dive in dives:
            if dimension == "modifier": labels = [(m.modifier_code, None) for m in dive.modifiers] or [("No modifiers", None)]
            elif dimension == "sync": labels = [("SYNC" if dive.is_sync else "Individual", None)]
            elif dimension == "diver": labels = [((dive.diver.display_name if dive.diver else "Unassigned"), dive.diver_id)]
            elif dimension == "training_period": labels = [(period.name, period.id) for period in period_map.get(dive.id, [])] or [("No training period", None)]
            else: labels = [(str(getattr(dive, dimension) or "Unknown"), None)]
            for label in labels:
                groups[label].append(dive)
        return [{"context": label, "context_id": context_id, **summarize(group, success_threshold, weighting), "sample_label": sample_label(len(group))} for (label, context_id), group in sorted(groups.items(), key=lambda item: item[0][0])]
