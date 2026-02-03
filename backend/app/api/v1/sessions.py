"""Session CRUD endpoints"""

from typing import List, Optional
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.session import Session as SessionModel
from app.schemas.session import SessionCreate, SessionUpdate

router = APIRouter()


@router.get("")
async def list_sessions(
    db: Session = Depends(get_db),
    date_from: Optional[date] = Query(None, description="Filter sessions from date"),
    date_to: Optional[date] = Query(None, description="Filter sessions until date"),
    limit: int = Query(100, description="Limit results"),
    offset: int = Query(0, description="Offset for pagination"),
):
    """
    List all training sessions
    """
    query = db.query(SessionModel)

    if date_from:
        query = query.filter(SessionModel.date >= date_from)

    if date_to:
        query = query.filter(SessionModel.date <= date_to)

    sessions = query.order_by(SessionModel.date.desc()).offset(offset).limit(limit).all()
    return sessions


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
    db: Session = Depends(get_db),
):
    """
    Get a specific session by ID with all its dives
    """
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return session


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
