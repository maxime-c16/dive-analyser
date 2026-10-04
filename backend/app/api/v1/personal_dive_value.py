"""Read-only Personal Dive Value V1 endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.services.workspace_access import require_workspace_user
from app.models.dive import Dive
from app.services.personal_dive_value import PersonalDiveValueError, PersonalDiveValueService, VERSION
from app.services.dive_analysis_service import is_analytics_dive

router = APIRouter(tags=["personal-dive-value"], dependencies=[Depends(require_workspace_user)])


def _enabled() -> None:
    if not get_settings().personal_dive_value_enabled:
        raise HTTPException(status_code=404, detail={"code": "personal_dive_value_disabled", "message": "Personal Dive Value is disabled."})


def _version(value: str) -> None:
    if value != VERSION:
        raise HTTPException(status_code=422, detail={"code": "unsupported_personal_dive_value_version", "message": f"Only {VERSION} is available."})


@router.get("/dives/{dive_id}/personal-value")
def personal_value(dive_id: int, version: str = Query(VERSION), db: Session = Depends(get_db)):
    _enabled(); _version(version)
    dive = db.query(Dive).filter(Dive.id == dive_id).first()
    if not dive: raise HTTPException(status_code=404, detail="Dive not found")
    try: return PersonalDiveValueService(db).calculate(dive) | {"attempt_id": dive.id}
    except PersonalDiveValueError as exc:
        code = "straight_jump_not_supported" if not is_analytics_dive(dive.dive_code) else "personal_dive_value_not_authorized"
        status = 422 if code == "straight_jump_not_supported" else 403
        raise HTTPException(status_code=status, detail={"code": code, "message": str(exc)}) from exc


@router.get("/dives/{dive_id}/personal-value/patterns")
def personal_value_patterns(dive_id: int, limit: int = Query(3, ge=1, le=3), version: str = Query(VERSION), db: Session = Depends(get_db)):
    _enabled(); _version(version)
    dive = db.query(Dive).filter(Dive.id == dive_id).first()
    if not dive:
        raise HTTPException(status_code=404, detail="Dive not found")
    try:
        return {"version": VERSION, "attempt_id": dive.id, "matches": PersonalDiveValueService(db).patterns(dive, limit)}
    except PersonalDiveValueError as exc:
        code = "straight_jump_not_supported" if not is_analytics_dive(dive.dive_code) else "personal_dive_value_not_authorized"
        status = 422 if code == "straight_jump_not_supported" else 403
        raise HTTPException(status_code=status, detail={"code": code, "message": str(exc)}) from exc


@router.get("/dive-analysis/{dive_code}/personal-values")
def personal_values(dive_code: str, limit: int = Query(100, ge=1, le=250), version: str = Query(VERSION), db: Session = Depends(get_db)):
    _enabled(); _version(version)
    if not is_analytics_dive(dive_code.upper()):
        raise HTTPException(status_code=422, detail={"code": "straight_jump_not_supported", "message": "Straight jumps are excluded from Personal Dive Value."})
    return {"version": VERSION, "dive_code": dive_code.upper(), "values": PersonalDiveValueService(db).values_for_dive_code(dive_code.upper(), limit)}


@router.get("/personal-dive-value/recent")
def recent_personal_values(limit: int = Query(60, ge=1, le=100), version: str = Query(VERSION), db: Session = Depends(get_db)):
    _enabled(); _version(version)
    return {"version": VERSION, "values": PersonalDiveValueService(db).recent_values(limit)}


@router.get("/personal-dive-value/configs/{version}")
def personal_value_config(version: str):
    _enabled(); _version(version)
    return PersonalDiveValueService.configuration()
