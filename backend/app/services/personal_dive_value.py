"""Deterministic, personal-only Dive Value V1 service.

This is an explainable review-priority signal. It intentionally does not
persist outputs, learn weights, or compare divers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import sqrt
from statistics import median
from threading import Lock
from time import monotonic

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.models.dive import Dive
from app.services.difficulty_adjustment import formula_dd
from app.services.dive_analysis_service import is_analytics_dive
from app.services.diver_identity import get_primary_diver
from app.services.performance_scoring import dive_score_10

VERSION = "v1"
REFERENCE_DD = 1.6
BETA = 0.30
WEIGHTS = {"technical": 0.35, "same_dive_relative": 0.25, "breakthrough": 0.15, "progression": 0.10, "consistency": 0.10, "novelty": 0.05}
MIN_SUPPORT = 5


@dataclass(frozen=True)
class HistoryEntry:
    """The small, precomputed representation needed by value calculations."""

    id: int
    dive_datetime: datetime
    dive_code: str
    height: str
    score: float
    dd: float | None


_recent_values_cache: dict[tuple, tuple[float, list[dict]]] = {}
_recent_values_cache_lock = Lock()


class PersonalDiveValueError(ValueError):
    pass


def _mad(values: list[float], center: float) -> float:
    return median(abs(value - center) for value in values) if values else 0.0


def _slope(values: list[float]) -> float:
    if len(values) < 3:
        return 0.0
    xs = range(len(values)); x_bar = (len(values) - 1) / 2; y_bar = sum(values) / len(values)
    denominator = sum((x - x_bar) ** 2 for x in xs)
    return sum((x - x_bar) * (y - y_bar) for x, y in enumerate(values)) / denominator if denominator else 0.0


def _eligible_primary(db: Session) -> list[Dive]:
    primary = get_primary_diver(db)
    dives = db.query(Dive).options(selectinload(Dive.modifiers)).filter(
        Dive.is_lineup.is_(False),
        or_(Dive.diver_id == primary.id, and_(Dive.diver_id.is_(None), Dive.person_name.is_(None))),
    ).order_by(Dive.dive_datetime, Dive.id).all()
    return [dive for dive in dives if is_analytics_dive(dive.dive_code)]


def _history(dives: list[Dive]) -> list[HistoryEntry]:
    """Precompute immutable calculation inputs once per bulk request."""
    return [
        HistoryEntry(
            id=dive.id,
            dive_datetime=dive.dive_datetime,
            dive_code=dive.dive_code,
            height=dive.height,
            score=dive_score_10(dive),
            dd=formula_dd(dive),
        )
        for dive in dives
    ]


def _before(left: Dive | HistoryEntry, right: Dive | HistoryEntry) -> bool:
    return (left.dive_datetime, left.id) < (right.dive_datetime, right.id)


def _confidence(support: int) -> dict:
    if support >= 10:
        return {"level": "high", "same_dive_support": support, "reasons": []}
    if support >= MIN_SUPPORT:
        return {"level": "medium", "same_dive_support": support, "reasons": ["Moderate same-dive history"]}
    return {"level": "low", "same_dive_support": support, "reasons": [f"Emerging pattern: {support} prior attempt{'s' if support != 1 else ''}"]}


def _modifiers(dive: Dive) -> set[str]:
    return {modifier.modifier_code for modifier in dive.modifiers}


def technical_component(score: float, dd: float) -> float:
    """Return the bounded V1 technical signal before contextual weighting."""
    return min(1.0, max(0.0, score * (dd / REFERENCE_DD) ** BETA / 10.0))


class PersonalDiveValueService:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def configuration() -> dict:
        return {"version": VERSION, "reference_dd": REFERENCE_DD, "beta": BETA, "weights": WEIGHTS, "execution_guard": {"floor": 0.20, "execution_weight": 0.80}, "minimum_same_dive_support": MIN_SUPPORT, "primary_diver_only": True}

    def _assert_primary_attempt(self, dive: Dive) -> None:
        primary = get_primary_diver(self.db)
        if dive.is_lineup or not (dive.diver_id == primary.id or (dive.diver_id is None and dive.person_name is None)):
            raise PersonalDiveValueError("Personal Dive Value is available only for the primary diver's non-lineup attempts")
        if not is_analytics_dive(dive.dive_code):
            raise PersonalDiveValueError("Straight jumps are excluded from Personal Dive Value")

    def calculate(self, dive: Dive, history: list[HistoryEntry] | None = None) -> dict:
        self._assert_primary_attempt(dive)
        if history is None:
            history = _history(_eligible_primary(self.db))
        target = next((item for item in history if item.id == dive.id), None)
        if target is None:
            target = _history([dive])[0]
        dd = target.dd
        now = datetime.utcnow()
        if dd is None:
            return {"version": VERSION, "value": None, "execution": {"score": round(target.score, 2), "scale": "0_10"}, "difficulty": {"official_dd": None, "reference_dd": REFERENCE_DD, "beta": BETA}, "components": {}, "primary_signal": None, "confidence": {"level": "undefined", "same_dive_support": 0, "reasons": ["Official DD is undefined"]}, "caveats": ["Personal Dive Value is unavailable because official DD is undefined."], "history_cutoff": dive.dive_datetime, "calculated_at": now}
        earlier = [item for item in history if _before(item, target) and item.dd is not None]
        same = [item for item in earlier if item.dive_code == target.dive_code]
        same_scores = [item.score for item in same]
        score = round(target.score, 2)
        support = len(same_scores)
        center = median(same_scores) if same_scores else None
        mad = _mad(same_scores, center) if center is not None else 0.0
        technical = technical_component(score, dd)
        percentile = sum(value <= score for value in same_scores) / support if support >= MIN_SUPPORT else None
        relative = 0.5 if support < MIN_SUPPORT else max(0.0, min(1.0, 0.5 + 0.18 * ((score - center) / max(1.0, mad * 1.4826))))
        previous = same_scores[-5:]
        personal_best = bool(same_scores) and score > max(same_scores)
        threshold = any(score >= value and all(item < value for item in same_scores) for value in (4.5, 7.0, 10.0))
        plateau = support >= MIN_SUPPORT and previous and score >= max(previous) + 0.5
        recovery = len(previous) >= 3 and score >= 4.5 and median(previous) <= 2.0
        breakthrough, reason = (1.0, "personal_best") if personal_best else (0.75, "first_threshold_crossing") if threshold else (0.65, "plateau_break") if plateau else (0.55, "recovery_after_regression") if recovery else (0.0, None)
        early = same_scores[:5]
        progression = max(0.0, min(1.0, 0.5 * max(0.0, (score - median(early)) / 4.0) + 0.5 * max(0.0, _slope(previous) / 2.0))) if early else 0.0
        contexts = [item for item in same if item.height == target.height]
        last = same[-1].dive_datetime if same else None
        absence = min(1.0, (dive.dive_datetime - last).days / 180.0) if last else 0.0
        novelty = min(1.0, 0.55 / sqrt(1 + support) + 0.30 / sqrt(1 + len(contexts)) + 0.15 * absence)
        consistency = 0.35 if support < MIN_SUPPORT else max(0.0, min(1.0, (sum(value >= 7.0 for value in previous) / len(previous)) * (1 - min(1.0, _mad(previous, median(previous)) / 3.0))))
        raw = {"technical": technical, "same_dive_relative": relative, "breakthrough": breakthrough, "progression": progression, "consistency": consistency, "novelty": novelty}
        contextual = sum(WEIGHTS[key] * raw[key] for key in WEIGHTS)
        guard = 0.20 + 0.80 * score / 10.0
        value = round(min(100.0, max(0.0, 100 * contextual * guard)), 1)
        primary = max({"Technical": technical, "Same-dive result": max(0.0, relative - 0.5) * 2, "Breakthrough": breakthrough, "Progression": progression, "Consistency": consistency, "Novelty": novelty}, key=lambda key: {"Technical": technical, "Same-dive result": max(0.0, relative - 0.5) * 2, "Breakthrough": breakthrough, "Progression": progression, "Consistency": consistency, "Novelty": novelty}[key])
        components = {key: {"raw_value": round(raw[key], 4), "normalized_value": round(raw[key], 4), "weight": WEIGHTS[key], "weighted_contribution": round(WEIGHTS[key] * raw[key] * guard * 100, 2)} for key in WEIGHTS}
        components["same_dive_relative"].update({"support": support, "percentile": round(percentile * 100, 1) if percentile is not None else None})
        components["breakthrough"].update({"reason": reason})
        components["progression"].update({"reason": "improvement_from_prior_history" if progression else None})
        caveats = ["Personal review-priority signal; not an official score."]
        if support < MIN_SUPPORT: caveats.append("Same-dive history is sparse; relative performance is neutral and percentile is omitted.")
        return {"version": VERSION, "value": value, "execution": {"score": score, "scale": "0_10"}, "difficulty": {"official_dd": dd, "reference_dd": REFERENCE_DD, "beta": BETA}, "components": components, "contextual_value": round(contextual, 4), "execution_guard": round(guard, 4), "primary_signal": primary, "confidence": _confidence(support), "caveats": caveats, "history_cutoff": dive.dive_datetime, "calculated_at": now}

    def values_for_dive_code(self, dive_code: str, limit: int) -> list[dict]:
        all_dives = _eligible_primary(self.db)
        history = _history(all_dives)
        dives = [dive for dive in all_dives if dive.dive_code == dive_code]
        return [self.calculate(dive, history) | {"attempt_id": dive.id} for dive in dives[-limit:]]

    def recent_values(self, limit: int) -> list[dict]:
        """Return a bounded series, cached until its source data changes or expires."""
        primary = get_primary_diver(self.db)
        # A timestamp alone misses deletion of any row except the newest.
        # Include row count and identity scope, and isolate separate databases.
        source_count, source_version = self.db.query(func.count(Dive.id), func.max(Dive.updated_at)).one()
        cache_key = (self.db.get_bind(), primary.id, limit, source_count, source_version)
        now = monotonic()
        ttl = get_settings().personal_dive_value_cache_ttl_seconds
        with _recent_values_cache_lock:
            cached = _recent_values_cache.get(cache_key)
            if cached and now - cached[0] < ttl:
                return cached[1]
            all_dives = _eligible_primary(self.db)
            history = _history(all_dives)
            dives = all_dives[-limit:]
            values = [self.calculate(dive, history) | {"attempt_id": dive.id, "dive_code": dive.dive_code, "dive_datetime": dive.dive_datetime} for dive in dives]
            _recent_values_cache.clear()
            _recent_values_cache[cache_key] = (now, values)
            return values

    def patterns(self, dive: Dive, limit: int = 3) -> list[dict]:
        self._assert_primary_attempt(dive)
        history = [item for item in _eligible_primary(self.db) if item.dive_code == dive.dive_code and _before(item, dive) and formula_dd(item) is not None]
        if len(history) < 3:
            return []
        target = [dive_score_10(dive)] + [dive_score_10(item) for item in history[-2:][::-1]]
        matches = []
        for index in range(2, len(history)):
            end = history[index]; window = [dive_score_10(history[index]), dive_score_10(history[index - 1]), dive_score_10(history[index - 2])]
            score_distance = sqrt(sum((left - right) ** 2 for left, right in zip(target, window)))
            penalty = (0 if end.height == dive.height else 1.0) + (0 if end.is_sync == dive.is_sync else 1.0) + (0 if _modifiers(end) == _modifiers(dive) else 0.5)
            matches.append({
                "attempt_id": end.id,
                "dive_code": end.dive_code,
                "session_id": end.session_id,
                "dive_datetime": end.dive_datetime,
                "height": end.height,
                "is_sync": end.is_sync,
                "modifiers": sorted(_modifiers(end)),
                "trailing_scores": [round(value, 2) for value in window],
                "current_trailing_scores": [round(value, 2) for value in target],
                "score_distance": round(score_distance, 3),
                "context_penalty": penalty,
                "similarity_distance": round(score_distance + penalty, 3),
                "evidence": "Historical similarity, not prediction.",
            })
        return sorted(matches, key=lambda item: item["similarity_distance"])[:limit]
