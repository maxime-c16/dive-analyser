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
from io import BytesIO
from pathlib import Path
import re
import warnings
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool
from sqlalchemy import Integer, and_, cast, func, literal, or_, select, union_all
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user, _origin_allowed
from app.database import get_db
from app.models.dive import Dive
from app.models.diver import Diver
from app.models.media import MediaCacheEntry
from app.models.photos_asset import PhotosAsset
from app.models.dive_share import DiveGuest, DiveGuestLike
from app.models.dive_social import DiveComment, DiveCommentLike, DiveGuestCommentLike, DiveLike
from app.models.user_auth import AppUser, UserDiverAccess
from app.services.dive_access import owned_diver_ids, visible_dive_clause
from app.services import achievements
from app.services.member_avatar import avatar_identity

router = APIRouter(prefix="/users")


def _identity(target):
    return dict(user_id=target.id, display_name=target.display_name,
                handle=target.handle, bio=target.bio,
                **avatar_identity(target))


def _active_user(db, user_id):
    target = db.get(AppUser, user_id)
    if target is None or not target.is_active:
        raise HTTPException(404, "User not found")
    return target


def _profile_write(request):
    if not _origin_allowed(request):
        raise HTTPException(403, "Origin not allowed")


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=120)
    handle: str | None = Field(default=None, max_length=30)
    bio: str = Field(default="", max_length=500)

    @field_validator("display_name")
    @classmethod
    def valid_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Display name cannot be empty")
        return value

    @field_validator("handle")
    @classmethod
    def valid_handle(cls, value):
        if value is None or not value.strip():
            return None
        value = value.strip().lower().removeprefix("@")
        if not re.fullmatch(r"[a-z0-9_]{3,30}", value):
            raise ValueError("Handle must contain 3–30 letters, numbers or underscores")
        return value


@router.get("")
def search_members(q: str = Query("", max_length=120), after: int = Query(0, ge=0),
                   limit: int = Query(24, ge=1, le=50),
                   user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(AppUser).filter(AppUser.is_active.is_(True), AppUser.id > after)
    term = q.strip().removeprefix("@")
    if term:
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        # Accounts can use a nickname (e.g. Fouiny) while their linked diver
        # is named Fanny. Match those names only where the binding is visible
        # to this requester, just as on the profile header.
        own = owned_diver_ids(db, user.id)
        visible_divers = select(Dive.diver_id).where(visible_dive_clause(own, bool(user.is_admin)))
        linked_accounts = select(UserDiverAccess.user_id).join(
            Diver, Diver.id == UserDiverAccess.diver_id).where(
            UserDiverAccess.access_kind == "OWNER",
            Diver.display_name.ilike(f"%{escaped}%", escape="\\"),
            or_(Diver.id.in_(own), Diver.id.in_(visible_divers)))
        query = query.filter(or_(AppUser.display_name.ilike(f"%{escaped}%", escape="\\"),
                                 AppUser.handle.contains(term.lower(), autoescape=True),
                                 AppUser.id.in_(linked_accounts)))
    rows = query.order_by(AppUser.id).limit(limit + 1).all()
    # One aggregate for this page, using exactly the profile grid visibility.
    stats = {uid: (count, latest) for uid, count, latest in db.query(
        UserDiverAccess.user_id, func.count(Dive.id),
        func.max(func.coalesce(Dive.dive_datetime, Dive.created_at)),
    ).join(Dive, Dive.diver_id == UserDiverAccess.diver_id).filter(
        UserDiverAccess.user_id.in_([row.id for row in rows[:limit]]),
        UserDiverAccess.access_kind == "OWNER",
        visible_dive_clause(owned_diver_ids(db, user.id), bool(user.is_admin)),
    ).group_by(UserDiverAccess.user_id).all()}
    items = []
    for row in rows[:limit]:
        count, latest = stats.get(row.id, (0, None))
        items.append(dict(**_identity(row), accessible_dive_count=count,
                          latest_dive_at=latest.isoformat() + "Z" if latest else None))
    return dict(items=items,
                next_after=rows[limit - 1].id if len(rows) > limit else None)


@router.put("/me/profile")
def update_profile(body: ProfileUpdate, request: Request,
                   user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    _profile_write(request)
    user.display_name, user.handle, user.bio = body.display_name, body.handle, body.bio.strip()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Handle is already taken")
    achievements.award(db, user.id, achievements.PROFILE)
    return _identity(user)


_AVATAR_MAX_BYTES = 2 * 1024 * 1024


class AvatarStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    avatar_hud: Literal["orbit", "reticle", "depth"]


@router.put("/me/avatar-style")
def update_avatar_style(body: AvatarStyle, request: Request,
                        user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    _profile_write(request)
    user.avatar_hud = body.avatar_hud
    db.commit()
    return _identity(user)


@router.put("/me/avatar")
async def upload_avatar(request: Request,
                        user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    _profile_write(request)
    # Read raw image bytes: no multipart parser/spooling runs before this
    # limit. Also bound chunked requests and forged Content-Length headers.
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > _AVATAR_MAX_BYTES:
            raise HTTPException(413, "Avatar must be at most 2 MB")
        chunks.append(chunk)
    return await run_in_threadpool(_save_avatar, b"".join(chunks), user, db)


def _save_avatar(raw, user, db):
    # Decode and persist off the event loop after the bounded body read.
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw), formats=["JPEG", "PNG", "WEBP"]) as image:
                if image.width * image.height > 16_000_000:
                    raise ValueError("Image too large")
                image = ImageOps.exif_transpose(image)
                image = ImageOps.fit(image.convert("RGB"), (256, 256))
                output = BytesIO()
                image.save(output, format="JPEG", quality=85)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(422, "Use a valid JPEG, PNG or WebP image up to 16 megapixels")
    user.avatar = output.getvalue()
    user.avatar_updated_at = datetime.utcnow()
    db.commit()
    achievements.award(db, user.id, achievements.PROFILE)
    return _identity(user)


@router.delete("/me/avatar", status_code=204)
def remove_avatar(request: Request, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    _profile_write(request)
    user.avatar = None
    user.avatar_updated_at = None
    db.commit()
    return Response(status_code=204)


@router.get("/{user_id}/avatar")
def get_avatar(user_id: int, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    avatar = _active_user(db, user_id).avatar
    if not avatar:
        raise HTTPException(404, "Avatar not found")
    return Response(avatar, media_type="image/jpeg", headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/{user_id}/dives")
def profile_dives(user_id: int, before: str | None = None,
                  limit: int = Query(30, ge=1, le=60),
                  user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    _active_user(db, user_id)
    stamp = func.coalesce(Dive.dive_datetime, Dive.created_at)
    query = db.query(Dive).filter(Dive.diver_id.in_(owned_diver_ids(db, user_id)),
                                 visible_dive_clause(owned_diver_ids(db, user.id), bool(user.is_admin)))
    if before:
        try:
            when, dive_id = before.split("|", 1)
            when, dive_id = datetime.fromisoformat(when), int(dive_id)
        except (ValueError, TypeError):
            raise HTTPException(422, "Invalid cursor")
        query = query.filter(or_(stamp < when, and_(stamp == when, Dive.id < dive_id)))
    rows = query.order_by(stamp.desc(), Dive.id.desc()).limit(limit + 1).all()
    page = rows[:limit]
    # Profiles follow the same bounded tile rule as the Library grid: poster
    # plus the ready local web preview only — never the camera original and
    # never a B2 revision URL, so profile tiles mint no playback grants.
    from app.api.v1.media import _thumbnail_status_for_entries
    uuids = [row.video_uuid for row in page if row.video_uuid]
    entries = {}
    for video_uuid, entry in db.query(PhotosAsset.video_uuid, MediaCacheEntry).join(
        MediaCacheEntry, MediaCacheEntry.photos_asset_id == PhotosAsset.id).filter(
        PhotosAsset.video_uuid.in_(uuids), MediaCacheEntry.status == "ready"
    ).order_by(MediaCacheEntry.id.desc()).all():
        if Path(entry.storage_path).is_file():
            entries.setdefault(video_uuid, []).append(entry)
    previews = {uuid: _thumbnail_status_for_entries(
        db, uuid, entries.get(uuid, []), None,
    ) for uuid in uuids}
    return dict(items=[dict(id=row.id, dive_code=row.dive_code, height=row.height,
                            dive_datetime=(row.dive_datetime or row.created_at).isoformat() + "Z",
                            visibility=row.visibility,
                            poster_url=previews.get(row.video_uuid, {}).get("poster_url"),
                            playback_url=previews.get(row.video_uuid, {}).get("playback_url"))
                       for row in page],
                next_before=f"{(page[-1].dive_datetime or page[-1].created_at).isoformat()}|{page[-1].id}" if len(rows) > limit else None)

# Likes recorded before the history feature have no timestamp; they sort as if
# they happened at this sentinel (oldest possible instant).
_EPOCH = datetime(1970, 1, 1)
_BODY_SNIPPET = 240


def _public_role(user: AppUser) -> str:
    return "administrator" if bool(user.is_admin) else "diver"


def _arm(arm_no, kind, direction, when, row_key, actor_key, dive_id, actor_user, actor_guest, comment_id):
    """One UNION arm with the uniform column contract of the merged feed.

    Ordering uses separate scalar columns — (sort_key, arm_no, row_key,
    actor_key) — never an arithmetic encoding: packed `id * span + actor`
    expressions are computed in INT4 in Postgres and overflow for large ids,
    and can collide when actor ids reach the span. row_key is the like or
    comment row identity; actor_key pins the actor so two rows that share a
    row (a member like and a guest like on the same dive in the same second)
    still order deterministically.
    """
    return select(
        literal(kind).label("kind"),
        literal(direction).label("direction"),
        func.coalesce(when, _EPOCH).label("sort_key"),
        literal(arm_no).label("arm_no"),
        row_key.label("row_key"),
        actor_key.label("actor_key"),
        when.label("created_at"),
        dive_id.label("dive_id"),
        # PostgreSQL resolves an initial run of untyped NULLs to TEXT in a
        # UNION. Cast nullable IDs so later guest/comment arms stay INTEGER.
        cast(actor_user, Integer).label("actor_user_id"),
        cast(actor_guest, Integer).label("actor_guest_id"),
        cast(comment_id, Integer).label("comment_id"),
    )


def _parse_cursor(raw: str | None):
    if raw is None:
        return None
    try:
        stamp_text, arm_text, row_text, actor_text = raw.split("|", 3)
        return datetime.fromisoformat(stamp_text), int(arm_text), int(row_text), int(actor_text)
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
            _arm(0, "dive_like", "sent", DiveLike.created_at, DiveLike.dive_id, DiveLike.user_id,
                 DiveLike.dive_id, DiveLike.user_id, literal(None), literal(None))
            .select_from(DiveLike).join(Dive, Dive.id == DiveLike.dive_id)
            .where(DiveLike.user_id == actor, dive_is_visible())
        )
        arms.append(
            _arm(1, "comment", "sent", DiveComment.created_at, DiveComment.id, DiveComment.user_id,
                 DiveComment.dive_id, DiveComment.user_id, literal(None), DiveComment.id)
            .select_from(DiveComment).join(Dive, Dive.id == DiveComment.dive_id)
            .where(DiveComment.user_id == actor, dive_is_visible())
        )
        arms.append(
            _arm(2, "comment_like", "sent", DiveCommentLike.created_at, DiveCommentLike.comment_id, DiveCommentLike.user_id,
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
            _arm(3, "dive_like", "received", DiveLike.created_at, DiveLike.dive_id, DiveLike.user_id,
                 DiveLike.dive_id, DiveLike.user_id, literal(None), literal(None))
            .select_from(DiveLike).join(Dive, Dive.id == DiveLike.dive_id)
            .where(DiveLike.user_id != me, Dive.id.in_(my_dives))
        )
        arms.append(
            _arm(4, "dive_like", "received", DiveGuestLike.created_at, DiveGuestLike.dive_id, DiveGuestLike.guest_id,
                 DiveGuestLike.dive_id, literal(None), DiveGuestLike.guest_id, literal(None))
            .select_from(DiveGuestLike).join(Dive, Dive.id == DiveGuestLike.dive_id)
            .where(Dive.id.in_(my_dives))
        )
        arms.append(
            _arm(5, "comment", "received", DiveComment.created_at, DiveComment.id, DiveComment.user_id,
                 DiveComment.dive_id, DiveComment.user_id, literal(None), DiveComment.id)
            .select_from(DiveComment).join(Dive, Dive.id == DiveComment.dive_id)
            .where(DiveComment.user_id != me, DiveComment.guest_id.is_(None), Dive.id.in_(my_dives))
        )
        arms.append(
            _arm(6, "comment", "received", DiveComment.created_at, DiveComment.id, func.coalesce(DiveComment.guest_id, 0),
                 DiveComment.dive_id, literal(None), DiveComment.guest_id, DiveComment.id)
            .select_from(DiveComment).join(Dive, Dive.id == DiveComment.dive_id)
            .where(DiveComment.guest_id.is_not(None), Dive.id.in_(my_dives))
        )
        arms.append(
            _arm(7, "comment_like", "received", DiveCommentLike.created_at, DiveCommentLike.comment_id, DiveCommentLike.user_id,
                 DiveComment.dive_id, DiveCommentLike.user_id, literal(None), DiveCommentLike.comment_id)
            .select_from(DiveCommentLike)
            .join(DiveComment, DiveComment.id == DiveCommentLike.comment_id)
            .join(Dive, Dive.id == DiveComment.dive_id)
            .where(DiveCommentLike.user_id != me, DiveComment.user_id == me, dive_is_visible())
        )
        arms.append(
            _arm(8, "comment_like", "received", DiveGuestCommentLike.created_at, DiveGuestCommentLike.comment_id, DiveGuestCommentLike.guest_id,
                 DiveComment.dive_id, literal(None), DiveGuestCommentLike.guest_id, DiveGuestCommentLike.comment_id)
            .select_from(DiveGuestCommentLike)
            .join(DiveComment, DiveComment.id == DiveGuestCommentLike.comment_id)
            .join(Dive, Dive.id == DiveComment.dive_id)
            .where(DiveComment.user_id == me, dive_is_visible())
        )

    cursor = _parse_cursor(before)
    stamp, cursor_arm, cursor_row, cursor_actor = cursor if cursor is not None else (None, None, None, None)
    for index, arm in enumerate(arms):
        if stamp is not None:
            # Strictly-older-than-cursor, four keys deep: (time, arm, row,
            # actor). Ties across arms reproduce the ORDER BY exactly, so no
            # row is skipped at a page boundary and none repeats.
            arms[index] = arm.where(or_(
                arm.selected_columns["sort_key"] < stamp,
                and_(arm.selected_columns["sort_key"] == stamp, or_(
                    arm.selected_columns["arm_no"] < cursor_arm,
                    and_(arm.selected_columns["arm_no"] == cursor_arm, or_(
                        arm.selected_columns["row_key"] < cursor_row,
                        and_(arm.selected_columns["row_key"] == cursor_row,
                             arm.selected_columns["actor_key"] < cursor_actor),
                    )),
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
                        merged.selected_columns["row_key"].desc(),
                        merged.selected_columns["actor_key"].desc()).limit(limit + 1)
    ).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    last = rows[-1] if rows else None
    next_before = (f"{last.sort_key.isoformat()}|{last.arm_no}|{last.row_key}|{last.actor_key}"
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
    users = {row.id: row for row in db.query(AppUser).filter(AppUser.id.in_(user_ids)).all()} if user_ids else {}
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
                display_name=users[row.actor_user_id].display_name if row.actor_user_id in users else guests.get(row.actor_guest_id) or "?",
                **(avatar_identity(users[row.actor_user_id]) if row.actor_user_id in users else {"avatar_url": None, "avatar_hud": "reticle"}),
            ),
            dive=dives.get(row.dive_id),
            comment=dict(id=row.comment_id, body=comments.get(row.comment_id, "")) if row.comment_id else None,
        ))
    return items


@router.get("/me/diver-score")
def my_diver_score(
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Account-aggregate 0-100 diver score (performance + judging + community)."""
    from app.services import diver_score
    return diver_score.compute(db, user)


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
        **_identity(target),
        role=_public_role(target),
        is_admin=bool(target.is_admin),
        is_self=target.id == user.id,
        joined_at=target.created_at.isoformat() + "Z" if target.created_at else None,
        divers=divers,
    )
