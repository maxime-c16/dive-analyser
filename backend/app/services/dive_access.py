"""Account ownership and request-wide visibility for the member workspace.

All ORM reads in a browser request are scoped at the session boundary, including
column projections, joins and relationship loads. Machine-key and auth-disabled
flows keep their existing contract. Route handlers still authorize mutations.
"""
from contextlib import contextmanager
from typing import Optional

from fastapi import Depends, HTTPException, WebSocketException
from starlette.requests import HTTPConnection
from sqlalchemy import and_, event, or_, select
from sqlalchemy.orm import Session, with_loader_criteria

from app.config import get_settings
from app.database import Base, get_db
from app.models.dive import Dive
from app.models.diver import Diver
from app.models.photos_asset import PhotosAsset
from app.models.session import Session as TrainingSession
from app.models.user_auth import UserDiverAccess
from app.models.notification import Notification
from app.models.direct_message import DirectMessage
from app.services import sessions
from app.services.user_access import user_has_diver_access

CONTEXT_KEY = "member_access"


@contextmanager
def unscoped_reads(db: Session):
    """Temporarily drop the member read scope (admin triage only).

    Callers must still enforce their own authorization: queries inside the
    block see every row.
    """
    saved = db.info.pop(CONTEXT_KEY, None)
    try:
        yield
    finally:
        if saved is not None:
            db.info[CONTEXT_KEY] = saved


def owned_diver_ids(db: Session, user_id: int) -> tuple[int, ...]:
    return tuple(db.execute(select(UserDiverAccess.diver_id).where(
        UserDiverAccess.user_id == user_id, UserDiverAccess.access_kind == "OWNER"
    )).scalars())


def lock_diver_for_ownership_change(db: Session, diver_id: int) -> Optional[Diver]:
    """Row-lock one diver before reading or writing its OWNER bindings.

    "Is this diver already owned?" followed by "create a binding" is a
    check-then-act pair that appears in invite redemption and in the admin
    grant path. Without a shared lock those interleave and both succeed,
    handing a second OWNER to a diver whose clips already belong to an
    account. SELECT … FOR UPDATE on the diver row serializes them in
    Postgres; SQLite ignores the clause and serializes whole-database
    writes anyway. Returns the diver (None when it does not exist).
    """
    return db.query(Diver).filter(Diver.id == diver_id).with_for_update().first()


def visible_dive_clause(ids: tuple[int, ...], is_admin: bool = False, depositor_user_id=None):
    clauses = [Dive.diver_id.in_(ids),
               (Dive.visibility == "public") & Dive.diver_id.is_not(None),
               Dive.diver_id.is_(None) if is_admin else False]
    if depositor_user_id is not None:
        # A depositor keeps access to their own deposits while they are
        # still pending (private clips of other accounts). Acceptance ends
        # this grant: accepted private dives fall back to owner-only reads.
        clauses.append(
            (Dive.deposited_by_user_id == depositor_user_id)
            & Dive.accepted_at.is_(None)
            & Dive.batch_id.is_not(None)
        )
    return or_(*clauses)


def is_pending(dive: Dive) -> bool:
    """A deposit awaiting owner acceptance (accepted_at advisory only).

    Both flags are required: pre-migration rows have neither batch_id nor
    accepted_at and must keep their legacy contract.
    """
    return dive.accepted_at is None and dive.batch_id is not None


def can_manage_dive(db: Session, user, dive: Dive) -> bool:
    if not user or not user.is_active:
        return False
    if user.is_admin and dive.diver_id is None:
        return True
    if dive.diver_id is not None and user_has_diver_access(db, user.id, dive.diver_id):
        return True
    if is_pending(dive):
        # The depositor may tend their own pending deposits; admins may
        # triage any pending batch (orphans, mis-attributions).
        if dive.deposited_by_user_id is not None and dive.deposited_by_user_id == user.id:
            return True
        if user.is_admin:
            return True
    return False


def require_dive_owner(db: Session, user, dive: Dive) -> None:
    if not can_manage_dive(db, user, dive):
        raise HTTPException(403, "Only the dive owner can manage this dive")


def apply_self_scope(db: Session, query):
    """None means legacy scoping; an empty binding set means no own dives."""
    context = db.info.get(CONTEXT_KEY)
    return query.filter(Dive.diver_id.in_(context["diver_ids"])) if context else None


@event.listens_for(Session, "do_orm_execute")
def scope_member_reads(state):
    context = state.session.info.get(CONTEXT_KEY)
    if not context or not state.is_select:
        return
    ids = context["diver_ids"]
    is_admin = context.get("is_admin", False)
    depositor_user_id = context.get("user_id")
    clause = visible_dive_clause(ids, is_admin, depositor_user_id)
    visible_ids = select(Dive.id).where(visible_dive_clause(ids, is_admin, depositor_user_id))
    visible_videos = select(Dive.video_uuid).where(visible_dive_clause(ids, is_admin, depositor_user_id))
    visible_assets = select(PhotosAsset.id).where(PhotosAsset.video_uuid.in_(visible_videos))
    criteria = [(Dive, clause),
                (PhotosAsset, PhotosAsset.video_uuid.in_(visible_videos)),
                (TrainingSession, TrainingSession.id.in_(
                    select(Dive.session_id).where(visible_dive_clause(ids, is_admin, depositor_user_id)))),
                (Diver, or_(Diver.id.in_(ids), Diver.id.in_(
                    select(Dive.diver_id).where(visible_dive_clause(ids, is_admin, depositor_user_id)))))]
    # Scope derived dive records and media identities too. The mapper registry
    # covers every imported model; no route can accidentally omit a filter.
    # DirectMessage is excluded: every messaging endpoint explicitly checks
    # conversation membership, and inaccessible dive cards are redacted per viewer.
    # Filtering here would hide text-only messages and skip receipt checks.
    # Notifications are excluded: the inbox is explicitly user-scoped in
    # notification_service (never client-supplied), and the generic dive
    # filter would wrongly hide rows with a NULL dive_id.
    for mapper in Base.registry.mappers:
        model = mapper.class_
        if model in (Dive, PhotosAsset, TrainingSession, Diver, Notification, DirectMessage):
            continue
        dive_links = [column for column in mapper.columns if any(fk.target_fullname == "dives.id" for fk in column.foreign_keys)]
        if dive_links:
            criteria.append((model, and_(*[getattr(model, column.key).in_(visible_ids) for column in dive_links])))
        elif "video_uuid" in mapper.columns:
            criteria.append((model, model.video_uuid.in_(visible_videos)))
        elif "photos_asset_id" in mapper.columns:
            criteria.append((model, model.photos_asset_id.in_(visible_assets)))
    state.statement = state.statement.options(*[
        with_loader_criteria(model, clause, include_aliases=True)
        for model, clause in criteria
    ])


@event.listens_for(Session, "before_flush")
def protect_dive_ownership(db, flush_context, instances):
    context = db.info.get(CONTEXT_KEY)
    if not context or context.get("system_mutation"):
        return
    for row in db.new.union(db.dirty).union(db.deleted):
        if isinstance(row, Dive):
            if row.diver_id not in context["diver_ids"] and not (context.get("is_admin") and row.diver_id is None):
                # Own pending deposits stay editable by their depositor and
                # triageable by admins; ownership transfer stays guarded below.
                pending = row.accepted_at is None and row.batch_id is not None
                depositor = (
                    row.deposited_by_user_id is not None
                    and row.deposited_by_user_id == context.get("user_id")
                )
                if not (pending and (depositor or context.get("is_admin"))):
                    raise HTTPException(403, "Only the dive owner can manage this dive")
            from sqlalchemy import inspect
            previous = inspect(row).attrs.diver_id.history.deleted
            if previous and previous[0] not in context["diver_ids"]:
                raise HTTPException(403, "Dive ownership cannot be transferred")


async def member_access_context(request: HTTPConnection, db: Session = Depends(get_db)):
    """Install a fresh access context for one request, always removed on exit."""
    from app.services.write_guard import _valid_machine_api_key
    path = request.url.path
    if (not get_settings().user_auth_enabled or path.startswith("/api/v1/auth/")
            or path.startswith("/api/v1/shared-dives/")
            or path.startswith("/api/v1/deposits/claim/")
            or path.startswith("/api/v1/health") or _valid_machine_api_key(request)):
        yield
        return
    resolved = sessions.resolve_session(db, request.cookies.get(get_settings().auth_cookie_name))
    if resolved is None:
        if request.scope["type"] == "websocket":
            raise WebSocketException(1008, "Authentication required")
        raise HTTPException(401, "Authentication required")
    user = resolved[1]
    # Operational/raw analysis endpoints have no member resource contract.
    operational = ("/api/v1/media/catalog", "/api/v1/media/recall", "/api/v1/media/agents",
                   "/api/v1/media/mac", "/api/v1/media/resolution-upgrades",
                   "/api/v1/media/representative-manifest/runs", "/api/v1/analysis",
                   "/api/v1/ws/", "/api/v1/psychology")
    if path.startswith(operational) and not user.is_admin:
        if request.scope["type"] == "websocket":
            raise WebSocketException(1008, "Administrative access required")
        raise HTTPException(403, "Administrative access required")
    request.state.member_user = user
    context = {"user_id": user.id, "diver_ids": owned_diver_ids(db, user.id), "is_admin": bool(user.is_admin)}
    db.info[CONTEXT_KEY] = context
    try:
        yield
    finally:
        db.info.pop(CONTEXT_KEY, None)
