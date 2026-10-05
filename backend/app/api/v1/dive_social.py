"""Discussion is available to signed-in viewers of a visible dive.

Always resolve the dive first: private IDs return 404 for other members,
including mutations. A reaction never grants ownership or changes the dive.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.dive import Dive
from app.models.dive_social import DiveComment, DiveLike
from app.models.user_auth import AppUser
from app.models.dive_share import DiveGuest, DiveGuestLike
from app.services.write_guard import optional_session_user

router = APIRouter(prefix='/dives')


def visible_dive(dive_id: int, request: Request, db: Session = Depends(get_db)):
    user = optional_session_user(request, db)
    if user is None:
        raise HTTPException(401, 'Sign in to join the discussion')
    dive = db.query(Dive).filter(Dive.id == dive_id).first()
    if dive is None:
        raise HTTPException(404, 'Dive not found')
    return user


class LikeInput(BaseModel):
    liked: bool


class CommentInput(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


def comment_payload(row, author):
    return dict(id=row.id, body=row.body, author=author, user_id=row.user_id,
                guest_id=row.guest_id, created_at=row.created_at.isoformat() + 'Z')


@router.get('/{dive_id}/social')
def social(dive_id: int, user=Depends(visible_dive), db: Session = Depends(get_db)):
    return dict(
        liked=db.query(DiveLike).filter_by(dive_id=dive_id, user_id=user.id).first() is not None,
        like_count=db.query(func.count(DiveLike.user_id)).filter_by(dive_id=dive_id).scalar() + db.query(func.count(DiveGuestLike.guest_id)).filter_by(dive_id=dive_id).scalar(),
        comment_count=db.query(func.count(DiveComment.id)).filter_by(dive_id=dive_id).scalar(),
    )


@router.put('/{dive_id}/like')
def like(dive_id: int, payload: LikeInput, user=Depends(visible_dive), db: Session = Depends(get_db)):
    existing = db.query(DiveLike).filter_by(dive_id=dive_id, user_id=user.id).first()
    if payload.liked and existing is None:
        db.add(DiveLike(dive_id=dive_id, user_id=user.id))
    elif not payload.liked and existing is not None:
        db.delete(existing)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()  # Concurrent identical PUTs are still idempotent.
        if not db.query(DiveLike).filter_by(dive_id=dive_id, user_id=user.id).first():
            raise
    return social(dive_id, user, db)


@router.get('/{dive_id}/comments')
def comments(dive_id: int, before: int | None = None, user=Depends(visible_dive), db: Session = Depends(get_db)):
    query = db.query(DiveComment, func.coalesce(AppUser.display_name, DiveGuest.display_name)).outerjoin(AppUser, AppUser.id == DiveComment.user_id).outerjoin(DiveGuest, DiveGuest.id == DiveComment.guest_id).filter(DiveComment.dive_id == dive_id)
    if before is not None:
        query = query.filter(DiveComment.id < before)
    rows = query.order_by(DiveComment.id.desc()).limit(51).all()
    return dict(items=[comment_payload(row, author) for row, author in rows[:50]],
                next_before=rows[49][0].id if len(rows) > 50 else None)


@router.post('/{dive_id}/comments', status_code=201)
def comment(dive_id: int, payload: CommentInput, user=Depends(visible_dive), db: Session = Depends(get_db)):
    body = payload.body.strip()
    if not body:
        raise HTTPException(422, 'Comment cannot be blank')
    row = DiveComment(dive_id=dive_id, user_id=user.id, body=body)
    db.add(row)
    db.commit()
    db.refresh(row)
    return comment_payload(row, user.display_name)


@router.delete('/{dive_id}/comments/{comment_id}', status_code=204)
def delete_comment(dive_id: int, comment_id: int, user=Depends(visible_dive), db: Session = Depends(get_db)):
    row = db.query(DiveComment).filter_by(id=comment_id, dive_id=dive_id).first()
    if row is None:
        raise HTTPException(404, 'Comment not found')
    if row.user_id != user.id and not user.is_admin:
        raise HTTPException(403, 'Only the author can delete this comment')
    db.delete(row)
    db.commit()
