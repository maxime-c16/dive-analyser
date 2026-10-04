"""Dive CRUD endpoints"""

from typing import List, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.workspace_access import require_workspace_user
from app.models.dive import Dive
from app.models.session import Session as SessionModel
from app.schemas.dive import DiveCreate, DiveUpdate
from app.services.diver_identity import get_primary_diver, invalidate_analysis_cache, resolve_diver
from app.services.difficulty_adjustment import formula_dd
from app.services.world_aquatics_dd import REFERENCE_ID

router = APIRouter(dependencies=[Depends(require_workspace_user)])


def _public_dive(dive: Dive) -> dict:
    """Serialize a dive with formula DD as the live display source of truth.

    ``dives.official_dd`` is retained as a migration/audit column and can be
    null for older imports. Returning it directly made the library disagree
    with analytics, which already uses the versioned rulebook calculation.
    """
    payload = {column.key: getattr(dive, column.key) for column in Dive.__table__.columns}
    live_dd = formula_dd(dive)
    payload["official_dd"] = live_dd
    payload["official_dd_source"] = REFERENCE_ID if live_dd is not None else None
    return payload


@router.get("")
def list_dives(
    db: Session = Depends(get_db),
    session_id: Optional[int] = Query(None, description="Filter by session ID"),
    dive_code: Optional[str] = Query(None, description="Filter by dive code"),
    height: Optional[str] = Query(None, description="Filter by height"),
    performance: Optional[str] = Query(None, description="Filter by performance"),
    date_from: Optional[datetime] = Query(None, description="Filter dives from date"),
    date_to: Optional[datetime] = Query(None, description="Filter dives until date"),
    exclude_lineup: bool = Query(False, description="Exclude lineup dives"),
    exclude_personal: bool = Query(False, description="Exclude personal dives (show lineup only)"),
    diver_scope: str = Query("self", pattern="^(self|all)$", description="Default to the primary diver; use all only intentionally"),
    limit: int = Query(100, description="Limit results"),
    offset: int = Query(0, description="Offset for pagination"),
):
    """
    List dives with optional filters
    """
    query = db.query(Dive)

    if diver_scope == "self":
        primary = get_primary_diver(db)
        query = query.filter(or_(Dive.diver_id == primary.id, (Dive.diver_id.is_(None) & Dive.person_name.is_(None))))

    # Apply filters
    if session_id is not None:
        query = query.filter(Dive.session_id == session_id)

    if dive_code:
        query = query.filter(Dive.dive_code == dive_code)

    if height:
        query = query.filter(Dive.height == height)

    if performance:
        query = query.filter(Dive.performance == performance)

    if date_from:
        query = query.filter(Dive.dive_datetime >= date_from)

    if date_to:
        query = query.filter(Dive.dive_datetime <= date_to)

    if exclude_lineup:
        query = query.filter(Dive.is_lineup == False)

    if exclude_personal:
        query = query.filter(Dive.is_lineup == True)

    # Order by date and id descending. Many Photos videos can share the same
    # second-level timestamp, so id gives deterministic newest-first ties.
    dives = query.order_by(Dive.dive_datetime.desc(), Dive.id.desc()).offset(offset).limit(limit).all()
    return [_public_dive(dive) for dive in dives]


@router.post("", status_code=201)
def create_dive(
    dive: DiveCreate,
    db: Session = Depends(get_db),
):
    """
    Create a new dive record
    """
    # Verify session exists
    session = db.query(SessionModel).filter(SessionModel.id == dive.session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {dive.session_id} not found")

    # Create dive
    diver_record = resolve_diver(db, dive.person_name)
    db_dive = Dive(
        session_id=dive.session_id,
        dive_code=dive.dive_code,
        dive_number=dive.dive_number,
        position=dive.position,
        direction=dive.direction,
        performance=dive.performance,
        performance_numeric=dive.performance_numeric,
        height=dive.height,
        platform_type=dive.platform_type,
        is_lineup=dive.is_lineup,
        is_sync=dive.is_sync,
        is_smack=dive.is_smack,
        raw_caption=dive.raw_caption,
        person_name=dive.person_name,
        diver_id=diver_record.id if diver_record else None,
        notes=dive.notes,
        video_uuid=dive.video_uuid,
        video_filename=dive.video_filename,
        video_path=dive.video_path,
        dive_datetime=dive.dive_datetime,
    )

    db.add(db_dive)
    invalidate_analysis_cache(db)
    db.commit()
    db.refresh(db_dive)
    return _public_dive(db_dive)


@router.get("/{dive_id}")
def get_dive(
    dive_id: int,
    db: Session = Depends(get_db),
):
    """
    Get a specific dive by ID
    """
    dive = db.query(Dive).filter(Dive.id == dive_id).first()
    if not dive:
        raise HTTPException(status_code=404, detail=f"Dive {dive_id} not found")
    return _public_dive(dive)


@router.put("/{dive_id}")
def update_dive(
    dive_id: int,
    dive_update: DiveUpdate,
    db: Session = Depends(get_db),
):
    """
    Update a dive record
    """
    dive = db.query(Dive).filter(Dive.id == dive_id).first()
    if not dive:
        raise HTTPException(status_code=404, detail=f"Dive {dive_id} not found")

    # Update only provided fields
    update_data = dive_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(dive, field, value)
    if "person_name" in update_data:
        diver_record = resolve_diver(db, dive.person_name)
        dive.diver_id = diver_record.id if diver_record else None

    db.add(dive)
    invalidate_analysis_cache(db)
    db.commit()
    db.refresh(dive)
    return _public_dive(dive)


@router.delete("/{dive_id}", status_code=204)
def delete_dive(
    dive_id: int,
    db: Session = Depends(get_db),
):
    """
    Delete a dive record
    """
    dive = db.query(Dive).filter(Dive.id == dive_id).first()
    if not dive:
        raise HTTPException(status_code=404, detail=f"Dive {dive_id} not found")

    db.delete(dive)
    invalidate_analysis_cache(db)
    db.commit()
    return None
