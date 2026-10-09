"""Discussion is available to signed-in viewers of a visible dive.

Always resolve the dive first: private IDs return 404 for other members,
including mutations. A reaction never grants ownership or changes the dive.
"""
import logging
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.dive import Dive
from app.models.dive_social import DiveComment, DiveLike, DiveCommentLike, DiveGuestCommentLike
from app.models.user_auth import AppUser
from app.models.dive_share import DiveGuest, DiveGuestLike
from app.services import achievements
from app.services.write_guard import optional_session_user
from app.services.mentions import MentionInput, validate_mentions
from app.services.member_avatar import avatar_identity

router = APIRouter(prefix='/dives')

logger = logging.getLogger(__name__)


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
    mentions: list[MentionInput] = Field(default_factory=list, max_length=10)


def reaction_identity(user):
    if isinstance(user, DiveGuest):
        return DiveGuestCommentLike, dict(guest_id=user.id)
    return DiveCommentLike, dict(user_id=user.id)


def comment_payload(row, author, db, user, stats=None):
    reaction_model, identity = reaction_identity(user)
    avatar = {"avatar_url": None, "avatar_hud": "reticle"}
    # Shared-link guests cannot fetch session-protected member photos.
    if row.user_id and not isinstance(user, DiveGuest):
        if stats is not None:
            avatar = stats['avatars'].get(row.user_id, avatar)
        else:
            target = db.get(AppUser, row.user_id)
            if target:
                avatar = avatar_identity(target)
    return dict(id=row.id, body=row.body, mentions=row.mentions or [], author=author, user_id=row.user_id,
                **avatar,
                guest_id=row.guest_id, created_at=row.created_at.isoformat() + 'Z', parent_id=row.parent_id,
                liked=(row.id in stats['liked']) if stats is not None else db.query(reaction_model).filter_by(comment_id=row.id, **identity).first() is not None,
                like_count=stats['likes'].get(row.id, 0) if stats is not None else (db.query(func.count(DiveCommentLike.user_id)).filter_by(comment_id=row.id).scalar() + db.query(func.count(DiveGuestCommentLike.guest_id)).filter_by(comment_id=row.id).scalar()),
                reply_count=stats['replies'].get(row.id, 0) if stats is not None else db.query(func.count(DiveComment.id)).filter_by(parent_id=row.id).scalar())


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
    if payload.liked and not isinstance(user, DiveGuest):
        achievements.award(db, user.id, achievements.LIKE)
        achievements.award_dive_owners(db, dive_id, user.id, achievements.LIKE)
    return social(dive_id, user, db)


@router.get('/{dive_id}/comments')
def comments(dive_id: int, before: int | None = None, parent_id: int | None = None, user=Depends(visible_dive), db: Session = Depends(get_db)):
    query = db.query(DiveComment, func.coalesce(AppUser.display_name, DiveGuest.display_name)).outerjoin(AppUser, AppUser.id == DiveComment.user_id).outerjoin(DiveGuest, DiveGuest.id == DiveComment.guest_id).filter(DiveComment.dive_id == dive_id)
    if parent_id is not None:
        parent = db.query(DiveComment).filter_by(id=parent_id, dive_id=dive_id, parent_id=None).first()
        if parent is None:
            raise HTTPException(404, 'Thread not found')
    query = query.filter(DiveComment.parent_id == parent_id)
    if before is not None:
        query = query.filter(DiveComment.id < before)
    rows = query.order_by(DiveComment.id.desc()).limit(51).all()
    ids = [row.id for row, _ in rows[:50]]
    reaction_model, identity = reaction_identity(user)
    stats = dict(
        avatars={target.id: avatar_identity(target) for target in db.query(AppUser).filter(AppUser.id.in_({row.user_id for row, _ in rows[:50] if row.user_id})).all()} if not isinstance(user, DiveGuest) else {},
        liked={item[0] for item in db.query(reaction_model.comment_id).filter(reaction_model.comment_id.in_(ids)).filter_by(**identity).all()},
        likes=dict(db.query(DiveCommentLike.comment_id, func.count(DiveCommentLike.user_id)).filter(DiveCommentLike.comment_id.in_(ids)).group_by(DiveCommentLike.comment_id).all()),
        replies=dict(db.query(DiveComment.parent_id, func.count(DiveComment.id)).filter(DiveComment.parent_id.in_(ids)).group_by(DiveComment.parent_id).all()),
    )
    for comment_id, count in db.query(DiveGuestCommentLike.comment_id, func.count(DiveGuestCommentLike.guest_id)).filter(DiveGuestCommentLike.comment_id.in_(ids)).group_by(DiveGuestCommentLike.comment_id).all():
        stats['likes'][comment_id] = stats['likes'].get(comment_id, 0) + count
    return dict(items=[comment_payload(row, author, db, user, stats) for row, author in rows[:50]],
                next_before=rows[49][0].id if len(rows) > 50 else None)


@router.post('/{dive_id}/comments', status_code=201)
def comment(dive_id: int, payload: CommentInput, user=Depends(visible_dive), db: Session = Depends(get_db), background_tasks: BackgroundTasks = None):
    body = payload.body.strip()
    if not body:
        raise HTTPException(422, 'Comment cannot be blank')
    if isinstance(user, DiveGuest) and payload.mentions:
        raise HTTPException(403, 'Sign in to mention members')
    # Validate against the original body, then shift spans when trimming it.
    mentions = validate_mentions(db, payload.body, payload.mentions)
    trim = len(payload.body) - len(payload.body.lstrip())
    mentions = [dict(m, start=m['start'] - trim, end=m['end'] - trim) for m in mentions]
    parent = None
    if payload.parent_id is not None:
        parent = db.query(DiveComment).filter_by(id=payload.parent_id, dive_id=dive_id).first()
        if parent is None:
            raise HTTPException(404, 'Comment not found')
    author_identity = dict(guest_id=user.id) if isinstance(user, DiveGuest) else dict(user_id=user.id)
    row = DiveComment(dive_id=dive_id, **author_identity, body=body, mentions=mentions,
                      parent_id=(parent.parent_id or parent.id) if parent else None)
    db.add(row)
    db.commit()
    db.refresh(row)
    try:
        from app.services import notification_service
        dive_row = db.query(Dive).filter(Dive.id == dive_id).first()
        diver_id = dive_row.diver_id if dive_row is not None else None
        author_user_id = None if isinstance(user, DiveGuest) else user.id
        # Inbox synchronous; push deferred to BackgroundTasks (threadpool,
        # fresh SessionLocal, bounded) — never inline blocking sends here.
        pending = []
        if diver_id is not None:
            pending.extend(notification_service.notify_owners_for_diver(
                db, diver_id=diver_id, exclude_user_id=author_user_id,
                type='new_comment', title='New comment',
                body=body[:600], dive_id=dive_id, defer_push=True))
        if parent is not None:
            parent_author_id = parent.user_id
            if parent_author_id is not None and parent_author_id != author_user_id:
                created = notification_service.create(
                    db, user_id=parent_author_id, type='comment_reply',
                    title='New reply', body=body[:600], dive_id=dive_id,
                    defer_push=True)
                if created is not None:
                    pending.append(created)
        notification_service.schedule_push(background_tasks, pending)
    except Exception:
        logger.exception('comment notification failed for dive %s', dive_id)
        try:
            db.rollback()
        except Exception:
            pass
    if not isinstance(user, DiveGuest):
        achievements.award(db, user.id, achievements.COMMENT)
    achievements.award_dive_owners(db, dive_id, None if isinstance(user, DiveGuest) else user.id, achievements.COMMENT)
    return comment_payload(row, user.display_name, db, user)


@router.delete('/{dive_id}/comments/{comment_id}', status_code=204)
def delete_comment(dive_id: int, comment_id: int, user=Depends(visible_dive), db: Session = Depends(get_db)):
    row = db.query(DiveComment).filter_by(id=comment_id, dive_id=dive_id).first()
    if row is None:
        raise HTTPException(404, 'Comment not found')
    owns_comment = row.guest_id == user.id if isinstance(user, DiveGuest) else row.user_id == user.id
    if not owns_comment and not getattr(user, 'is_admin', False):
        raise HTTPException(403, 'Only the author can delete this comment')
    # Explicit deletion also works in SQLite tests without FK cascades enabled.
    ids = [row.id] + [item[0] for item in db.query(DiveComment.id).filter_by(parent_id=row.id).all()]
    db.query(DiveCommentLike).filter(DiveCommentLike.comment_id.in_(ids)).delete(synchronize_session=False)
    db.query(DiveGuestCommentLike).filter(DiveGuestCommentLike.comment_id.in_(ids)).delete(synchronize_session=False)
    db.query(DiveComment).filter(DiveComment.id.in_(ids)).delete(synchronize_session=False)
    db.commit()


@router.put('/{dive_id}/comments/{comment_id}/like')
def like_comment(dive_id: int, comment_id: int, payload: LikeInput, user=Depends(visible_dive), db: Session = Depends(get_db)):
    row = db.query(DiveComment).filter_by(id=comment_id, dive_id=dive_id).first()
    if row is None:
        raise HTTPException(404, 'Comment not found')
    reaction_model, identity = reaction_identity(user)
    existing = db.query(reaction_model).filter_by(comment_id=comment_id, **identity).first()
    if payload.liked and existing is None:
        db.add(reaction_model(comment_id=comment_id, **identity))
    elif not payload.liked and existing is not None:
        db.delete(existing)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if not db.query(reaction_model).filter_by(comment_id=comment_id, **identity).first():
            raise
    author_model = DiveGuest if row.guest_id is not None else AppUser
    author = db.query(author_model.display_name).filter_by(id=row.guest_id or row.user_id).scalar()
    return comment_payload(row, author, db, user)
