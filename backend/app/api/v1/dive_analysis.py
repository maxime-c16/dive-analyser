"""Per-dive longitudinal analysis API V2."""

from datetime import datetime, time, timedelta
from time import perf_counter
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.workspace_access import require_workspace_user
from app.services.write_guard import effective_diver_scope
from app.services.dive_analysis_cache import ANALYTICS_VERSION, analysis_cache_key, get_cached_analysis, set_cached_analysis
from app.services.dive_analysis_service import DiveAnalysisService, build_insights, canonical_dive_code, is_analytics_dive, phase_analysis, summarize, trend

router = APIRouter(prefix="/dive-analysis", tags=["dive-analysis"], dependencies=[Depends(require_workspace_user)])


def _parse_date_bound(value: str | None, *, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_date", "message": f"Invalid date value: {value}"}) from exc
    return datetime.combine(parsed.date(), time.max) if end_of_day and "T" not in value and " " not in value else parsed


def analysis_filters(
    request: Request,
    db: Session = Depends(get_db),
    date_from: str | None = None,
    date_to: str | None = None,
    height: str | None = None,
    platform_type: str | None = None,
    position: str | None = None,
    modifiers: list[str] = Query(default=[]),
    modifier_mode: Literal["any", "all", "none"] = "any",
    is_sync: bool | None = None,
    diver_scope: Literal["self", "all", "selected"] = "self",
    diver_ids: list[int] = Query(default=[]),
    diver: str | None = Query(None, deprecated=True),
    performance: list[str] = Query(default=[]),
    session_id: int | None = None,
    training_period_ids: list[int] = Query(default=[]),
    success_threshold: Literal["M", "G", "P"] = "G",
    weighting: Literal["attempts", "sessions"] = "attempts",
) -> dict:
    parsed_from, parsed_to = _parse_date_bound(date_from), _parse_date_bound(date_to, end_of_day=True)
    if parsed_from and parsed_to and parsed_from > parsed_to:
        raise HTTPException(status_code=422, detail={"code": "invalid_date_range", "message": "date_from must be before date_to"})
    if not diver_ids:
        # Friends see everyone's dives by default (no diver bindings held).
        diver_scope = effective_diver_scope(request, db, diver_scope)
    return {
        "date_from": parsed_from, "date_to": parsed_to, "height": height, "platform_type": platform_type,
        "position": position, "modifiers": sorted({item.upper() for item in modifiers}), "modifier_mode": modifier_mode,
        "is_sync": is_sync, "diver_scope": "selected" if diver_ids else diver_scope, "diver_ids": sorted(set(diver_ids)), "diver": diver,
        "viewer_access": db.info.get("member_access"),
        "performance": sorted({item.upper() for item in performance}), "session_id": session_id,
        "training_period_ids": sorted(set(training_period_ids)), "success_threshold": success_threshold, "weighting": weighting,
    }


def _validate_code(value: str) -> str:
    try:
        code = canonical_dive_code(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_dive_code", "message": str(exc)}) from exc
    if not is_analytics_dive(code):
        raise HTTPException(status_code=422, detail={"code": "straight_jump_not_supported", "message": "Straight jumps are excluded from performance analytics."})
    return code


def _build_analysis(db: Session, dive_code: str, filters: dict, *, include_attempts: bool = True) -> dict:
    started = perf_counter()
    code = _validate_code(dive_code)
    service = DiveAnalysisService(db)
    weighting, threshold = filters["weighting"], filters["success_threshold"]
    key = analysis_cache_key(code, filters, weighting)
    core = get_cached_analysis(db, key)
    cache_hit = core is not None
    query_started = perf_counter()
    dives = service.query_dives(code, filters) if core is None or include_attempts else []
    query_ms = (perf_counter() - query_started) * 1000
    calculation_started = perf_counter()
    period_map = None
    if core is None:
        current_summary = summarize(dives, threshold, weighting)
        previous_dives, previous_summary, previous_range = [], None, None
        if filters.get("date_from") and filters.get("date_to"):
            duration = filters["date_to"] - filters["date_from"]
            previous_to = filters["date_from"] - timedelta(microseconds=1)
            previous_from = previous_to - duration
            previous_dives = service.query_dives(code, filters, date_from=previous_from, date_to=previous_to)
            previous_summary = summarize(previous_dives, threshold, weighting)
            previous_range = {"date_from": previous_from, "date_to": previous_to}
        periods, period_map = service.matching_periods(dives)
        core = {
            "summary": current_summary, "trend": trend(dives),
            "comparison": {"current": current_summary, "previous": previous_summary, "previous_range": previous_range},
            "breakdowns": {dimension: service.breakdown(dives, dimension, threshold, weighting, period_map=period_map) for dimension in ("modifier", "height", "position", "sync", "diver", "training_period")},
            "phases": phase_analysis(dives, previous_dives),
            "insights": build_insights(current_summary, previous_summary, dives, previous_dives),
            "training_periods": [{"id": period.id, "name": period.name, "period_type": period.period_type, "start_date": period.start_date, "end_date": period.end_date} for period in periods],
        }
        set_cached_analysis(db, key, filters, core)
    calculation_ms = (perf_counter() - calculation_started) * 1000
    attempts = (
        service.serialize_attempts(dives, period_map=period_map)
        if include_attempts else []
    )
    # Serialize before commit expires the eagerly loaded attempts/relationships.
    if not cache_hit:
        db.commit()
    total_ms = (perf_counter() - started) * 1000
    return {
        "generated_at": datetime.utcnow(), "analytics_version": ANALYTICS_VERSION, "dive_code": code,
        "filters": filters, "weighting_mode": "session_weighted" if weighting == "sessions" else "attempt_weighted",
        "sample": {key: core["summary"][key] for key in ("attempt_count", "session_count", "scored_attempt_count", "unscored_attempt_count", "first_attempt_at", "last_attempt_at")},
        **core, "attempts": attempts,
        "observability": {"cache": "hit" if cache_hit else "miss", "query_ms": round(query_ms, 2), "calculation_ms": round(calculation_ms, 2), "total_ms": round(total_ms, 2), "result_attempts": core["summary"]["attempt_count"]},
    }


@router.get("/{dive_code}")
def analyze_dive(dive_code: str, filters: dict = Depends(analysis_filters), db: Session = Depends(get_db)):
    return _build_analysis(db, dive_code, filters)


@router.get("/{dive_code}/attempts")
def analysis_attempts(dive_code: str, filters: dict = Depends(analysis_filters), db: Session = Depends(get_db)):
    result = _build_analysis(db, dive_code, filters)
    return {key: result[key] for key in ("generated_at", "analytics_version", "dive_code", "filters", "weighting_mode", "sample", "attempts", "observability")}


@router.get("/{dive_code}/phases")
def analysis_phases(dive_code: str, filters: dict = Depends(analysis_filters), db: Session = Depends(get_db)):
    result = _build_analysis(db, dive_code, filters, include_attempts=False)
    return {key: result[key] for key in ("generated_at", "analytics_version", "dive_code", "filters", "weighting_mode", "sample", "phases", "observability")}


@router.get("/{dive_code}/insights")
def analysis_insights(dive_code: str, filters: dict = Depends(analysis_filters), db: Session = Depends(get_db)):
    result = _build_analysis(db, dive_code, filters, include_attempts=False)
    return {key: result[key] for key in ("generated_at", "analytics_version", "dive_code", "filters", "weighting_mode", "sample", "insights", "observability")}


@router.get("/{dive_code}/breakdown")
def analysis_breakdown(dive_code: str, dimension: Literal["modifier", "height", "position", "sync", "diver", "training_period"], filters: dict = Depends(analysis_filters), db: Session = Depends(get_db)):
    result = _build_analysis(db, dive_code, filters, include_attempts=False)
    return {"generated_at": result["generated_at"], "analytics_version": ANALYTICS_VERSION, "dive_code": result["dive_code"], "filters": result["filters"], "weighting_mode": result["weighting_mode"], "dimension": dimension, "groups": result["breakdowns"][dimension], "observability": result["observability"]}


@router.get("/{dive_code}/compare")
def analysis_compare(dive_code: str, dimension: Literal["modifier", "height", "position", "sync", "diver", "training_period", "date_period"], equivalent_only: bool = False, filters: dict = Depends(analysis_filters), db: Session = Depends(get_db)):
    result = _build_analysis(db, dive_code, filters, include_attempts=False)
    if dimension == "date_period":
        groups = [{"context": "Selected period", **result["comparison"]["current"]}, {"context": "Previous equal period", **result["comparison"]["previous"]}] if result["comparison"]["previous"] else []
    else:
        groups = result["breakdowns"][dimension]
    constraints = {key: filters[key] for key in ("height", "position", "platform_type", "is_sync", "modifiers") if filters.get(key)} if equivalent_only else {}
    return {"generated_at": result["generated_at"], "analytics_version": ANALYTICS_VERSION, "dive_code": result["dive_code"], "dimension": dimension, "equivalent_only": equivalent_only, "equivalent_constraints": constraints, "groups": groups, "observability": result["observability"]}
