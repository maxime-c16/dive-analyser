"""Member achievements API (session-only).

- GET  /users/me/achievements          Full catalogue with unlock state and
                                       progress; also backfills anything the
                                       member already earned before this
                                       feature existed.
- GET  /users/me/achievements/unseen   Cheap poll for the unlock toast.
- POST /users/me/achievements/seen     Mark unlocks as seen (toast closed).
- GET  /users/{id}/achievements        A member's unlocked achievements, shown
                                       on their profile (no progress/locked).
"""
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.v1.auth import _origin_allowed, get_current_user
from app.api.v1.users import _active_user
from app.database import get_db
from app.models.achievement import UserAchievement
from app.models.user_auth import AppUser
from app.services import achievements

router = APIRouter(prefix="/users")


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


def _unseen(db: Session, user_id: int) -> List[dict]:
    rows = (
        db.query(UserAchievement)
        .filter(UserAchievement.user_id == user_id, UserAchievement.seen_at.is_(None))
        .order_by(UserAchievement.unlocked_at, UserAchievement.key)
        .all()
    )
    return [dict(key=row.key, unlocked_at=row.unlocked_at.isoformat()) for row in rows
            if row.key in achievements.RULES_BY_KEY]


@router.get("/me/achievements")
def my_achievements(response: Response, user: AppUser = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    _no_store(response)
    achievements.award(db, user.id)
    items = achievements.catalog_for(db, user.id)
    return dict(items=items, unlocked=sum(item["unlocked"] for item in items), total=len(items))


@router.get("/me/achievements/unseen")
def my_unseen_achievements(response: Response, user: AppUser = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    _no_store(response)
    has_any = db.query(UserAchievement.key).filter_by(user_id=user.id).first() is not None
    if not has_any:
        # First visit since the feature shipped: credit what is already true.
        achievements.award(db, user.id)
    return dict(items=_unseen(db, user.id))


class SeenBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keys: List[str] = Field(default_factory=list, max_length=64)


@router.post("/me/achievements/seen", status_code=204)
def mark_seen(body: SeenBody, request: Request, user: AppUser = Depends(get_current_user),
              db: Session = Depends(get_db)):
    if not _origin_allowed(request):
        raise HTTPException(403, "Origin not allowed")
    query = db.query(UserAchievement).filter(
        UserAchievement.user_id == user.id, UserAchievement.seen_at.is_(None))
    if body.keys:
        query = query.filter(UserAchievement.key.in_(body.keys))
    query.update({UserAchievement.seen_at: datetime.utcnow()}, synchronize_session=False)
    db.commit()
    return Response(status_code=204)


@router.get("/{user_id}/achievements")
def member_achievements(user_id: int, response: Response,
                        user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    _no_store(response)
    target = _active_user(db, user_id)
    rows = (
        db.query(UserAchievement).filter_by(user_id=target.id)
        .order_by(UserAchievement.unlocked_at.desc(), UserAchievement.key).all()
    )
    items = [
        dict(key=row.key, category=achievements.RULES_BY_KEY[row.key].category,
             unlocked_at=row.unlocked_at.isoformat())
        for row in rows if row.key in achievements.RULES_BY_KEY
    ]
    return dict(items=items, unlocked=len(items), total=len(achievements.RULES))
