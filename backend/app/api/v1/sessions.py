"""Session CRUD endpoints"""

from typing import Any, List, Optional
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.write_guard import effective_diver_scope, require_owner_for_mutation
from app.models.session import Session as SessionModel
from app.models.dive import Dive
from app.schemas.session import SessionCreate, SessionUpdate
from app.services.diver_identity import get_primary_diver
from app.services.performance_scoring import dive_score_10, is_success

router = APIRouter(dependencies=[Depends(require_owner_for_mutation)])


def _is_real_dive(dive: Dive) -> bool:
    return not (dive.dive_code or "").startswith(("100", "200", "300", "400"))


def _scope_filter(db: Session, diver_scope: str):
    if diver_scope == "all":
        return None
    primary = get_primary_diver(db)
    # Unattributed legacy attempts remain part of the primary user's history.
    return or_(Dive.diver_id == primary.id, (Dive.diver_id.is_(None) & Dive.person_name.is_(None)))


def _apply_live_stats(session: SessionModel, dives: list[Dive]) -> dict[str, Any]:
    """Return scoped, calibrated session stats without mutating legacy DB columns."""
    personal_dives = [d for d in dives if not d.is_lineup]
    analytics_dives = [d for d in personal_dives if _is_real_dive(d)]

    payload = {column.name: getattr(session, column.name) for column in SessionModel.__table__.columns}
    payload["total_dives"] = len(dives)
    payload["total_personal_dives"] = len(analytics_dives)
    if analytics_dives:
        payload["avg_performance"] = round(
            sum(dive_score_10(d) for d in analytics_dives) / len(analytics_dives),
            2,
        )
        payload["success_rate"] = round(
            sum(1 for d in analytics_dives if is_success(d.performance)) / len(analytics_dives) * 100,
            1,
        )
    else:
        payload["avg_performance"] = None
        payload["success_rate"] = None

    return payload


@router.get("")
async def list_sessions(
    request: Request,
    db: Session = Depends(get_db),
    date_from: Optional[date] = Query(None, description="Filter sessions from date"),
    date_to: Optional[date] = Query(None, description="Filter sessions until date"),
    limit: int = Query(100, description="Limit results"),
    offset: int = Query(0, description="Offset for pagination"),
    diver_scope: str = Query("self", pattern="^(self|all)$", description="Default to the primary diver; use all only intentionally"),
):
    """
    List all training sessions
    """
    diver_scope = effective_diver_scope(request, db, diver_scope)
    query = db.query(SessionModel)
    scope = _scope_filter(db, diver_scope)

    if date_from:
        query = query.filter(SessionModel.date >= date_from)

    if date_to:
        query = query.filter(SessionModel.date <= date_to)

    # A session is shown only when it contains at least one in-scope, non-lineup attempt.
    session_filter = [Dive.is_lineup.is_(False)]
    if scope is not None:
        session_filter.append(scope)
    query = query.join(Dive, Dive.session_id == SessionModel.id).filter(*session_filter).distinct()

    sessions = query.order_by(SessionModel.date.desc()).offset(offset).limit(limit).all()
    if not sessions:
        return []

    # One paged dive load for the whole session page instead of one query
    # per listed session (N+1). Stats stay computed by the same Python
    # scoring, only the loading is batched.
    dives_by_session: dict[int, list[Dive]] = {}
    for dive in (
        db.query(Dive)
        .filter(Dive.session_id.in_([session.id for session in sessions]))
        .filter(*session_filter)
        .all()
    ):
        dives_by_session.setdefault(dive.session_id, []).append(dive)

    return [
        _apply_live_stats(session, dives_by_session.get(session.id, []))
        for session in sessions
    ]


@router.post("", status_code=201)
async def create_session(
    session: SessionCreate,
    db: Session = Depends(get_db),
):
    """
    Create a new training session
    """
    # Check if session already exists for this date
    existing = db.query(SessionModel).filter(SessionModel.date == session.date).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Session for {session.date} already exists")

    db_session = SessionModel(
        date=session.date,
        location=session.location,
        notes=session.notes,
        weather=session.weather,
    )

    db.add(db_session)
    db.commit()
    db.refresh(db_session)
    return db_session


@router.get("/{session_id}")
async def get_session(
    session_id: int,
    request: Request,
    db: Session = Depends(get_db),
    diver_scope: str = Query("self", pattern="^(self|all)$"),
):
    """
    Get a specific session by ID with all its dives
    """
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    diver_scope = effective_diver_scope(request, db, diver_scope)
    scope = _scope_filter(db, diver_scope)
    filters = [Dive.session_id == session.id, Dive.is_lineup.is_(False)]
    if scope is not None:
        filters.append(scope)
    return _apply_live_stats(session, db.query(Dive).filter(*filters).all())


@router.put("/{session_id}")
async def update_session(
    session_id: int,
    session_update: SessionUpdate,
    db: Session = Depends(get_db),
):
    """
    Update a training session
    """
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    # Update only provided fields
    update_data = session_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(session, field, value)

    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: int,
    db: Session = Depends(get_db),
):
    """
    Delete a session and all its dives
    """
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    db.delete(session)
    db.commit()
    return None
