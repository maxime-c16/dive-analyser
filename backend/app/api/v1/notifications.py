"""Authenticated notification inbox (PR1, backend only).

Session pattern mirrors dive_social.py/updates.py: the session cookie is
the only identity source (get_current_user → 401 when signed out) and no
user_id is ever taken from the client. A row that does not belong to the
caller reads as missing (404), never as forbidden.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.database import get_db
from app.services import notification_service

router = APIRouter()


def _payload(row) -> dict:
    return {
        "id": row.id,
        "type": row.type,
        "title": row.title,
        "body": row.body,
        "dive_id": row.dive_id,
        "read_at": row.read_at.isoformat() + "Z" if row.read_at else None,
        "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
    }


class PrefInput(BaseModel):
    type: str = Field(min_length=1, max_length=64)
    enabled: bool


@router.get("/notifications")
def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=100),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items = notification_service.list_for_user(
        db, user.id, limit=limit, unread_only=unread_only
    )
    return {
        "items": [_payload(row) for row in items],
        "unread_count": notification_service.count_unread(db, user.id),
    }


@router.post("/notifications/{notif_id}/read")
def read_notification(
    notif_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)
):
    row = notification_service.mark_read(db, user.id, notif_id)
    if row is None:
        raise HTTPException(404, "Notification not found")
    return _payload(row)


@router.post("/notifications/read-all")
def read_all_notifications(
    user=Depends(get_current_user), db: Session = Depends(get_db)
):
    return {"marked": notification_service.mark_all_read(db, user.id)}


@router.get("/notification-prefs")
def get_prefs(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return {"prefs": notification_service.get_prefs(db, user.id)}


@router.put("/notification-prefs")
def put_pref(
    payload: PrefInput, user=Depends(get_current_user), db: Session = Depends(get_db)
):
    try:
        row = notification_service.set_pref(
            db, user.id, payload.type, payload.enabled
        )
    except ValueError:
        raise HTTPException(422, "Unknown notification type")
    return {"type": row.notif_type, "enabled": bool(row.enabled)}
