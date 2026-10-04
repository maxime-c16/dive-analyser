"""Account ownership and request-wide visibility for the member workspace.

All ORM reads in a browser request are scoped at the session boundary, including
column projections, joins and relationship loads. Machine-key and auth-disabled
flows keep their existing contract. Route handlers still authorize mutations.
"""
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
from app.services import sessions

CONTEXT_KEY = "member_access"


def owned_diver_ids(db: Session, user_id: int) -> tuple[int, ...]:
    return tuple(db.execute(select(UserDiverAccess.diver_id).where(
        UserDiverAccess.user_id == user_id, UserDiverAccess.access_kind == "OWNER"
    )).scalars())


def visible_dive_clause(ids: tuple[int, ...], is_admin: bool = False):
    return or_(Dive.diver_id.in_(ids),
               (Dive.visibility == "public") & Dive.diver_id.is_not(None),
               Dive.diver_id.is_(None) if is_admin else False)


def can_manage_dive(db: Session, user, dive: Dive) -> bool:
    return bool(user and user.is_active and (
        dive.diver_id in owned_diver_ids(db, user.id)
        or (user.is_admin and dive.diver_id is None)
    ))


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
    visible_ids = select(Dive.id).where(visible_dive_clause(ids, is_admin))
    visible_videos = select(Dive.video_uuid).where(visible_dive_clause(ids, is_admin))
    visible_assets = select(PhotosAsset.id).where(PhotosAsset.video_uuid.in_(visible_videos))
    criteria = [(Dive, visible_dive_clause(ids, is_admin)),
                (PhotosAsset, PhotosAsset.video_uuid.in_(visible_videos)),
                (TrainingSession, TrainingSession.id.in_(
                    select(Dive.session_id).where(visible_dive_clause(ids, is_admin)))),
                (Diver, or_(Diver.id.in_(ids), Diver.id.in_(
                    select(Dive.diver_id).where(visible_dive_clause(ids, is_admin)))))]
    # Scope derived dive records and media identities too. The mapper registry
    # covers every imported model; no route can accidentally omit a filter.
    for mapper in Base.registry.mappers:
        model = mapper.class_
        if model in (Dive, PhotosAsset, TrainingSession, Diver):
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
