"""Member-visible profiles and the personal activity history feed.

Session-only endpoints (no machine key, no guest identity):

- GET /users/{id}            Minimal member profile. No email, no admin data —
                             the same information a member already sees next to
                             any comment or like, plus diver bindings that
                             member-scope already makes visible.
- GET /users/me/activity     Merged personal history built from the live social
                             tables (dive_likes / dive_comments / comment likes
                             and their guest mirrors). Nothing is denormalized:
                             a deleted comment or an unliked reaction leaves the
                             feed immediately.
- GET /users/{id}/activity   A member's actions on dives visible to the
                             requester (profile page "recent activity").

Received items always involve a dive or comment the requester owns; sent items
always involve a dive that is still visible to the requester, so the deep link
(/dives?clip=…) can never point at hidden content.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import BigInteger, and_, cast, func, literal, or_, select, union_all
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.database import get_db
from app.models.dive import Dive
from app.models.diver import Diver
from app.models.dive_share import DiveGuest, DiveGuestLike
from app.models.dive_social import DiveComment, DiveCommentLike, DiveGuestCommentLike, DiveLike
from app.models.user_auth import AppUser, UserDiverAccess
from app.services.dive_access import owned_diver_ids, visible_dive_clause

router = APIRouter(prefix="/users")

# Likes recorded before the history feature have no timestamp; they sort as if
# they happened at this sentinel (oldest possible instant).
_EPOCH = datetime(1970, 1, 1)
_BODY_SNIPPET = 240
# Stable per-row tiebreak for like arms (no primary key): unique within an arm
# because (dive, actor) / (comment, actor) are the tables' composite keys.
_SPAN = 1_000_000


def _public_role(user: AppUser) -> str:
    return "administrator" if bool(user.is_admin) else "diver"


def _tb_dive_user(model):
    return cast(model.dive_id * _SPAN + model.user_id, BigInteger)


def _tb_dive_guest(model):
    return cast(model.dive_id * _SPAN + model.guest_id, BigInteger)


def _tb_comment_user(model):
    return cast(model.comment_id * _SPAN + model.user_id, BigInteger)


def _tb_comment_guest(model):
    return cast(model.comment_id * _SPAN + model.guest_id, BigInteger)


def _arm(arm_no, kind, direction, when, tiebreak, dive_id, actor_user, actor_guest, comment_id):
    """One UNION arm with the uniform column contract of the merged feed.

    arm_no is a fixed discriminator per arm: two rows from DIFFERENT arms can
    tie on (sort_key, tiebreak) — e.g. a member like and a guest like on the
    same dive recorded in the same second — so the (sort_key, tiebreak) pair
    alone cannot order the feed deterministically.
    """
    return select(
        literal(kind).label("kind"),
        literal(direction).label("direction"),
        func.coalesce(when, _EPOCH).label("sort_key"),
        tiebreak.label("tiebreak"),
        literal(arm_no).label("arm_no"),
        when.label("created_at"),
        dive_id.label("dive_id"),
        actor_user.label("actor_user_id"),
        actor_guest.label("actor_guest_id"),
        comment_id.label("comment_id"),
    )


def _parse_cursor(raw: str | None):
    if raw is None:
        return None
    try:
        stamp_text, arm_text, tiebreak_text = raw.split("|", 2)
        return datetime.fromisoformat(stamp_text), int(arm_text), int(tiebreak_text)
    except (ValueError, TypeError):
        raise HTTPException(422, "Invalid cursor")


def _activity(db: Session, user: AppUser, *, direction: str, before: str | None, limit: int, actor_id: int | None):
    me = user.id
    my_diver_ids = owned_diver_ids(db, me)
    is_admin = bool(user.is_admin)
    visible_ids = select(Dive.id).where(visible_dive_clause(my_diver_ids, is_admin))
    my_dives = select(Dive.id).where(Dive.diver_id.in_(my_diver_ids))
    actor = actor_id if actor_id is not None else me

    def dive_is_visible():
        return Dive.id.in_(visible_ids)

    arms = []
    # Sent: actions by the actor (me, or the profile-page member).
    if direction in ("all", "sent"):
        arms.append(
            _arm(0, "dive_like", "sent", DiveLike.created_at, _tb_dive_user(DiveLike),
                 DiveLike.dive_id, DiveLike.user_id, literal(None), literal(None))
            .select_from(DiveLike).join(Dive, Dive.id == DiveLike.dive_id)
            .where(DiveLike.user_id == actor, dive_is_visible())
        )
        arms.append(
            _arm(1, "comment", "sent", DiveComment.created_at, cast(DiveComment.id, BigInteger),
                 DiveComment.dive_id, DiveComment.user_id, literal(None), DiveComment.id)
            .select_from(DiveComment).join(Dive, Dive.id == DiveComment.dive_id)
            .where(DiveComment.user_id == actor, dive_is_visible())
        )
        arms.append(
            _arm(2, "comment_like", "sent", DiveCommentLike.created_at, _tb_comment_user(DiveCommentLike),
                 DiveComment.dive_id, DiveCommentLike.user_id, literal(None), DiveCommentLike.comment_id)
            .select_from(DiveCommentLike)
            .join(DiveComment, DiveComment.id == DiveCommentLike.comment_id)
            .join(Dive, Dive.id == DiveComment.dive_id)
            .where(DiveCommentLike.user_id == actor, dive_is_visible())
        )

    # Received: actions by others on my dives or my comments. Never emitted for
    # a third member's feed — their "received" side is not mine to see.
    if direction in ("all", "received") and actor_id is None:
        arms.append(
            _arm(3, "dive_like", "received", DiveLike.created_at, _tb_dive_user(DiveLike),
                 DiveLike.dive_id, DiveLike.user_id, literal(None), literal(None))
            .select_from(DiveLike).join(Dive, Dive.id == DiveLike.dive_id)
            .where(DiveLike.user_id != me, Dive.id.in_(my_dives))
        )
        arms.append(
            _arm(4, "dive_like", "received", DiveGuestLike.created_at, _tb_dive_guest(DiveGuestLike),
                 DiveGuestLike.dive_id, literal(None), DiveGuestLike.guest_id, literal(None))
            .select_from(DiveGuestLike).join(Dive, Dive.id == DiveGuestLike.dive_id)
            .where(Dive.id.in_(my_dives))
        )
        arms.append(
            _arm(5, "comment", "received", DiveComment.created_at, cast(DiveComment.id, BigInteger),
                 DiveComment.dive_id, DiveComment.user_id, literal(None), DiveComment.id)
            .select_from(DiveComment).join(Dive, Dive.id == DiveComment.dive_id)
            .where(DiveComment.user_id != me, DiveComment.guest_id.is_(None), Dive.id.in_(my_dives))
        )
        arms.append(
            _arm(6, "comment", "received", DiveComment.created_at, cast(DiveComment.id, BigInteger),
                 DiveComment.dive_id, literal(None), DiveComment.guest_id, DiveComment.id)
            .select_from(DiveComment).join(Dive, Dive.id == DiveComment.dive_id)
            .where(DiveComment.guest_id.is_not(None), Dive.id.in_(my_dives))
        )
        arms.append(
            _arm(7, "comment_like", "received", DiveCommentLike.created_at, _tb_comment_user(DiveCommentLike),
                 DiveComment.dive_id, DiveCommentLike.user_id, literal(None), DiveCommentLike.comment_id)
            .select_from(DiveCommentLike)
            .join(DiveComment, DiveComment.id == DiveCommentLike.comment_id)
            .join(Dive, Dive.id == DiveComment.dive_id)
            .where(DiveCommentLike.user_id != me, DiveComment.user_id == me, dive_is_visible())
        )
        arms.append(
            _arm(8, "comment_like", "received", DiveGuestCommentLike.created_at, _tb_comment_guest(DiveGuestCommentLike),
                 DiveComment.dive_id, literal(None), DiveGuestCommentLike.guest_id, DiveGuestCommentLike.comment_id)
            .select_from(DiveGuestCommentLike)
            .join(DiveComment, DiveComment.id == DiveGuestCommentLike.comment_id)
            .join(Dive, Dive.id == DiveComment.dive_id)
            .where(DiveComment.user_id == me, dive_is_visible())
        )

    cursor = _parse_cursor(before)
    stamp, cursor_arm, cursor_tiebreak = cursor if cursor is not None else (None, None, None)
    for index, arm in enumerate(arms):
        if stamp is not None:
            # Strictly-older-than-cursor, three keys deep: (time, arm, tiebreak).
            # Ties across arms reproduce the ORDER BY exactly, so no row is
            # skipped at a page boundary and none repeats.
            arms[index] = arm.where(or_(
                arm.selected_columns["sort_key"] < stamp,
                and_(arm.selected_columns["sort_key"] == stamp, or_(
                    arm.selected_columns["arm_no"] < cursor_arm,
                    and_(arm.selected_columns["arm_no"] == cursor_arm,
                         arm.selected_columns["tiebreak"] < cursor_tiebreak),
                )),
            ))
    if not arms:
        return dict(items=[], next_before=None)

    merged = union_all(*arms)
    # Execute on the raw connection: the session's request-wide ORM scoping
    # event (with_loader_criteria) compounds with this query's own identical
    # visibility filters and mangles UNION results across requests. Every arm
    # already filters dives explicitly, so nothing is exposed by bypassing it.
    rows = db.connection().execute(
        merged.order_by(merged.selected_columns["sort_key"].desc(),
                        merged.selected_columns["arm_no"].desc(),
                        merged.selected_columns["tiebreak"].desc()).limit(limit + 1)
    ).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    last = rows[-1] if rows else None
    next_before = (f"{last.sort_key.isoformat()}|{last.arm_no}|{last.tiebreak}"
                   if has_more and last is not None else None)
    return dict(items=_hydrate(db, rows), next_before=next_before)


def _hydrate(db: Session, rows):
    dive_ids = {row.dive_id for row in rows}
    user_ids = {row.actor_user_id for row in rows if row.actor_user_id is not None}
    guest_ids = {row.actor_guest_id for row in rows if row.actor_guest_id is not None}
    comment_ids = {row.comment_id for row in rows if row.comment_id is not None}

    dives = {}
    if dive_ids:
        for dive_id, dive_code, dive_number, height, dive_datetime, diver_name in (
            db.query(Dive.id, Dive.dive_code, Dive.dive_number, Dive.height, Dive.dive_datetime, Diver.display_name)
            .outerjoin(Diver, Diver.id == Dive.diver_id)
            .filter(Dive.id.in_(dive_ids))
            .all()
        ):
            dives[dive_id] = dict(
                id=dive_id, dive_code=dive_code, dive_number=dive_number, height=height,
                dive_datetime=dive_datetime.isoformat() + "Z" if dive_datetime else None,
                diver_name=diver_name,
            )
    users = dict(db.query(AppUser.id, AppUser.display_name).filter(AppUser.id.in_(user_ids)).all()) if user_ids else {}
    guests = dict(db.query(DiveGuest.id, DiveGuest.display_name).filter(DiveGuest.id.in_(guest_ids)).all()) if guest_ids else {}
    comments = {}
    if comment_ids:
        for comment_id, body in db.query(DiveComment.id, DiveComment.body).filter(DiveComment.id.in_(comment_ids)).all():
            comments[comment_id] = body[:_BODY_SNIPPET]

    items = []
    for row in rows:
        # u…/g… keeps member and guest ids in separate namespaces (both are
        # small integers that would otherwise collide).
        actor_ref = f"u{row.actor_user_id}" if row.actor_user_id is not None else f"g{row.actor_guest_id}"
        items.append(dict(
            key=f"{row.kind}:{row.dive_id}:{actor_ref}:{row.comment_id or 0}",
            kind=row.kind,
            direction=row.direction,
            created_at=row.created_at.isoformat() + "Z" if row.created_at else None,
            actor=dict(
                user_id=row.actor_user_id,
                guest_id=row.actor_guest_id,
                display_name=users.get(row.actor_user_id) or guests.get(row.actor_guest_id) or "?",
            ),
            dive=dives.get(row.dive_id),
            comment=dict(id=row.comment_id, body=comments.get(row.comment_id, "")) if row.comment_id else None,
        ))
    return items


@router.get("/me/activity")
def my_activity(
    direction: str = Query("all", pattern="^(all|sent|received)$"),
    before: str | None = Query(None, max_length=64),
    limit: int = Query(30, ge=1, le=100),
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _activity(db, user, direction=direction, before=before, limit=limit, actor_id=None)


@router.get("/{user_id}/activity")
def member_activity(
    user_id: int,
    before: str | None = Query(None, max_length=64),
    limit: int = Query(30, ge=1, le=100),
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """A member's actions on dives visible to the requester (profile page)."""
    target = db.get(AppUser, user_id)
    if target is None or not target.is_active:
        raise HTTPException(404, "User not found")
    return _activity(db, user, direction="sent", before=before, limit=limit, actor_id=user_id)


@router.get("/{user_id}")
def get_profile(
    user_id: int,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target = db.get(AppUser, user_id)
    if target is None or not target.is_active:
        raise HTTPException(404, "User not found")

    my_diver_ids = owned_diver_ids(db, user.id)
    visible_diver_ids = set(my_diver_ids) | set(
        db.execute(select(Dive.diver_id).where(visible_dive_clause(my_diver_ids, bool(user.is_admin)))).scalars()
    )
    bound = {
        diver_id
        for (diver_id,) in db.query(UserDiverAccess.diver_id).filter(UserDiverAccess.user_id == target.id).all()
    }
    divers = [
        dict(diver_id=diver_id, display_name=display_name)
        for diver_id, display_name in db.query(Diver.id, Diver.display_name)
        .filter(Diver.id.in_(bound & visible_diver_ids))
        .order_by(Diver.id.asc())
        .all()
    ]

    return dict(
        user_id=target.id,
        display_name=target.display_name,
        role=_public_role(target),
        is_admin=bool(target.is_admin),
        is_self=target.id == user.id,
        joined_at=target.created_at.isoformat() + "Z" if target.created_at else None,
        divers=divers,
    )
