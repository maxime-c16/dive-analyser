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
from app.models.dive_social import DiveComment, DiveLike, DiveCommentLike
from app.models.user_auth import AppUser
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
    parent_id: int | None = Field(default=None, gt=0)


def comment_payload(row, author, db, user, stats=None):
    return dict(id=row.id, body=row.body, author=author, user_id=row.user_id,
                created_at=row.created_at.isoformat() + 'Z', parent_id=row.parent_id,
                liked=(row.id in stats['liked']) if stats is not None else db.query(DiveCommentLike).filter_by(comment_id=row.id, user_id=user.id).first() is not None,
                like_count=stats['likes'].get(row.id, 0) if stats is not None else db.query(func.count(DiveCommentLike.user_id)).filter_by(comment_id=row.id).scalar(),
                reply_count=stats['replies'].get(row.id, 0) if stats is not None else db.query(func.count(DiveComment.id)).filter_by(parent_id=row.id).scalar())


@router.get('/{dive_id}/social')
def social(dive_id: int, user=Depends(visible_dive), db: Session = Depends(get_db)):
    return dict(
        liked=db.query(DiveLike).filter_by(dive_id=dive_id, user_id=user.id).first() is not None,
        like_count=db.query(func.count(DiveLike.user_id)).filter_by(dive_id=dive_id).scalar(),
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
def comments(dive_id: int, before: int | None = None, parent_id: int | None = None, user=Depends(visible_dive), db: Session = Depends(get_db)):
    query = db.query(DiveComment, AppUser.display_name).join(AppUser, AppUser.id == DiveComment.user_id).filter(DiveComment.dive_id == dive_id)
    if parent_id is not None:
        parent = db.query(DiveComment).filter_by(id=parent_id, dive_id=dive_id, parent_id=None).first()
        if parent is None:
            raise HTTPException(404, 'Thread not found')
    query = query.filter(DiveComment.parent_id == parent_id)
    if before is not None:
        query = query.filter(DiveComment.id < before)
    rows = query.order_by(DiveComment.id.desc()).limit(51).all()
    ids = [row.id for row, _ in rows[:50]]
    stats = dict(
        liked={item[0] for item in db.query(DiveCommentLike.comment_id).filter(DiveCommentLike.comment_id.in_(ids), DiveCommentLike.user_id == user.id).all()},
        likes=dict(db.query(DiveCommentLike.comment_id, func.count(DiveCommentLike.user_id)).filter(DiveCommentLike.comment_id.in_(ids)).group_by(DiveCommentLike.comment_id).all()),
        replies=dict(db.query(DiveComment.parent_id, func.count(DiveComment.id)).filter(DiveComment.parent_id.in_(ids)).group_by(DiveComment.parent_id).all()),
    )
    return dict(items=[comment_payload(row, author, db, user, stats) for row, author in rows[:50]],
                next_before=rows[49][0].id if len(rows) > 50 else None)


@router.post('/{dive_id}/comments', status_code=201)
def comment(dive_id: int, payload: CommentInput, user=Depends(visible_dive), db: Session = Depends(get_db)):
    body = payload.body.strip()
    if not body:
        raise HTTPException(422, 'Comment cannot be blank')
    parent = None
    if payload.parent_id is not None:
        parent = db.query(DiveComment).filter_by(id=payload.parent_id, dive_id=dive_id).first()
        if parent is None:
            raise HTTPException(404, 'Comment not found')
    row = DiveComment(dive_id=dive_id, user_id=user.id, body=body,
                      parent_id=(parent.parent_id or parent.id) if parent else None)
    db.add(row)
    db.commit()
    db.refresh(row)
    return comment_payload(row, user.display_name, db, user)


@router.delete('/{dive_id}/comments/{comment_id}', status_code=204)
def delete_comment(dive_id: int, comment_id: int, user=Depends(visible_dive), db: Session = Depends(get_db)):
    row = db.query(DiveComment).filter_by(id=comment_id, dive_id=dive_id).first()
    if row is None:
        raise HTTPException(404, 'Comment not found')
    if row.user_id != user.id and not user.is_admin:
        raise HTTPException(403, 'Only the author can delete this comment')
    # Explicit deletion also works in SQLite tests without FK cascades enabled.
    ids = [row.id] + [item[0] for item in db.query(DiveComment.id).filter_by(parent_id=row.id).all()]
    db.query(DiveCommentLike).filter(DiveCommentLike.comment_id.in_(ids)).delete(synchronize_session=False)
    db.query(DiveComment).filter(DiveComment.id.in_(ids)).delete(synchronize_session=False)
    db.commit()


@router.put('/{dive_id}/comments/{comment_id}/like')
def like_comment(dive_id: int, comment_id: int, payload: LikeInput, user=Depends(visible_dive), db: Session = Depends(get_db)):
    row = db.query(DiveComment).filter_by(id=comment_id, dive_id=dive_id).first()
    if row is None:
        raise HTTPException(404, 'Comment not found')
    existing = db.query(DiveCommentLike).filter_by(comment_id=comment_id, user_id=user.id).first()
    if payload.liked and existing is None:
        db.add(DiveCommentLike(comment_id=comment_id, user_id=user.id))
    elif not payload.liked and existing is not None:
        db.delete(existing)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if not db.query(DiveCommentLike).filter_by(comment_id=comment_id, user_id=user.id).first():
            raise
    author = db.query(AppUser.display_name).filter_by(id=row.user_id).scalar()
    return comment_payload(row, author, db, user)
