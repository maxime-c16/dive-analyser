"""Dive CRUD endpoints"""

import logging
from typing import List, Optional
from pathlib import Path
from datetime import datetime, timedelta
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, File, Form, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session
from sqlalchemy.orm.strategy_options import Load

from app.database import get_db
from app.services.write_guard import effective_diver_scope, optional_session_user, require_owner_for_mutation
from app.services.workspace_access import require_workspace_user
from app.models.dive import Dive
from app.models.session import Session as SessionModel
from app.schemas.dive import DiveCreate, DiveUpdate
from app.services.dive_access import apply_self_scope, owned_diver_ids, require_dive_owner
from app.services.diver_identity import get_primary_diver, invalidate_analysis_cache, resolve_diver
from app.services.difficulty_adjustment import formula_dd
from app.services.world_aquatics_dd import REFERENCE_ID

router = APIRouter(dependencies=[Depends(require_workspace_user), Depends(require_owner_for_mutation)])

logger = logging.getLogger(__name__)

# Library/workflow payload surface: exactly the columns the UI reads
# (Library, session view, review viewer) plus divider/lineup scoping.
# Cuts multi-KB TEXT columns (phase_insight, video_path, captions-adjacent
# audit fields) out of the 5,000-row Library response.
LIST_COLUMN_NAMES = (
    "visibility", "id", "session_id", "dive_code", "dive_number", "position", "direction",
    "performance", "performance_numeric",
    "phase1_performance", "phase1_numeric", "phase2_performance", "phase2_numeric",
    "height", "platform_type",
    "is_lineup", "is_sync", "is_smack",
    "raw_caption", "notes", "person_name",
    "video_uuid", "photos_asset_id", "diver_id",
    "dive_datetime", "created_at", "updated_at",
)
LIST_COLUMNS = tuple(getattr(Dive, _name) for _name in LIST_COLUMN_NAMES)


def _public_dive(dive: Dive, db: Session, federate_map: set[int] | None = None, evaluation_map: dict[int, dict] | None = None) -> dict:
    """Serialize a dive with formula DD as the live display source of truth.

    ``dives.official_dd`` is retained as a migration/audit column and can be
    null for older imports. Returning it directly made the library disagree
    with analytics, which already uses the versioned rulebook calculation.

    Serialization is whitelisted to LIST_COLUMN_NAMES (the columns any UI
    flow reads); internal audit columns (phase_insight, video_path, DD
    migration/verification bookkeeping, emotion capture) are held back.

    ``federate_enabled`` comes from the separate ``dive_fediverse_optins``
    table (row presence = opt-in), never from the dives row, so list/detail
    serialization keeps working before ``add_fediverse_optin.sql`` is
    applied (missing tables read as OFF). List callers pass a batch map to
    avoid N+1 queries; single-dive callers fall back to one lookup.
    The flag is owner-only: community viewers of a public dive always read
    False, matching the owner-only per-dive fediverse endpoints.

    ``evaluation_request`` is the owner-only summary of the dive's evaluation
    request (null = none), from the separate ``evaluation_requests`` table.
    List callers pass a batch map; single-dive callers do one lookup. It is
    omitted entirely for non-managing viewers and whenever no verified member
    context exists: a deployment without user auth (or a machine-key call)
    proves nothing about which account the caller owns, so the jury prompt
    never degrades into an anonymous read (review-bot P1).
    """
    payload = {name: getattr(dive, name) for name in LIST_COLUMN_NAMES}
    context = db.info.get("member_access")
    payload["can_comment"] = True  # Capability for the next discussion phase.
    payload["can_manage"] = context is None or dive.diver_id in context["diver_ids"] or (context.get("is_admin") and dive.diver_id is None)
    if payload["can_manage"]:
        if federate_map is None:
            from app.services.fediverse import per_dive_enabled

            payload["federate_enabled"] = per_dive_enabled(db, dive.id)
        else:
            payload["federate_enabled"] = dive.id in federate_map
        # Only a VERIFIED member session may see evaluation summaries: with
        # auth disabled or a bare machine key there is no account to be owner
        # OF the request, so the summary key stays out of anonymous payloads.
        if evaluation_map is not None:
            if context is not None:
                payload["evaluation_request"] = evaluation_map.get(dive.id)
        elif context is not None:
            from app.services.evaluation_access import request_for_dive, summary as evaluation_summary

            payload["evaluation_request"] = evaluation_summary(request_for_dive(db, dive.id))
    else:
        payload["federate_enabled"] = False
    if context and not payload["can_manage"]:
        for key in ("notes", "raw_caption", "video_path", "video_filename", "pre_dive_emotion", "post_dive_emotion", "confidence_rating"):
            payload.pop(key, None)
    live_dd = formula_dd(dive)
    payload["official_dd"] = live_dd
    payload["official_dd_source"] = REFERENCE_ID if live_dd is not None else None
    return payload


@router.get("")
def list_dives(
    request: Request,
    db: Session = Depends(get_db),
    session_id: Optional[int] = Query(None, description="Filter by session ID"),
    dive_code: Optional[str] = Query(None, description="Filter by dive code"),
    height: Optional[str] = Query(None, description="Filter by height"),
    performance: Optional[str] = Query(None, description="Filter by performance"),
    date_from: Optional[datetime] = Query(None, description="Filter dives from date"),
    date_to: Optional[datetime] = Query(None, description="Filter dives until date"),
    exclude_lineup: bool = Query(False, description="Exclude lineup dives"),
    exclude_personal: bool = Query(False, description="Exclude personal dives (show lineup only)"),
    diver_scope: str = Query("self", pattern="^(self|all)$", description="Default to the primary diver; use all only intentionally"),
    limit: int = Query(100, ge=1, le=5000, description="Limit results"),
    offset: int = Query(0, description="Offset for pagination"),
):
    """
    List dives with optional filters
    """
    query = db.query(Dive)

    # My dives follows verified account ownership; Community follows visibility.
    effective_scope = effective_diver_scope(request, db, diver_scope)

    if effective_scope == "self":
        scoped = apply_self_scope(db, query)
        if scoped is not None:
            query = scoped
        else:
            primary = get_primary_diver(db)
            query = query.filter(or_(Dive.diver_id == primary.id, (Dive.diver_id.is_(None) & Dive.person_name.is_(None))))

    # Apply filters
    if session_id is not None:
        query = query.filter(Dive.session_id == session_id)

    if dive_code:
        query = query.filter(Dive.dive_code == dive_code)

    if height:
        query = query.filter(Dive.height == height)

    if performance:
        query = query.filter(Dive.performance == performance)

    if date_from:
        query = query.filter(Dive.dive_datetime >= date_from)

    if date_to:
        query = query.filter(Dive.dive_datetime <= date_to)

    if exclude_lineup:
        query = query.filter(Dive.is_lineup == False)

    if exclude_personal:
        query = query.filter(Dive.is_lineup == True)

    # Order by date and id descending. Many Photos videos can share the same
    # second-level timestamp, so id gives deterministic newest-first ties.
    dives = query.order_by(Dive.dive_datetime.desc(), Dive.id.desc()).offset(offset).limit(limit).all()
    from app.services.fediverse import optin_map
    from app.services.evaluation_access import request_map as evaluation_request_map

    federate_map = optin_map(db, [dive.id for dive in dives])
    evaluation_map = evaluation_request_map(db, [dive.id for dive in dives])
    return [_public_dive(dive, db, federate_map, evaluation_map) for dive in dives]


@router.post("", status_code=201)
def create_dive(
    dive: DiveCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Create a new dive record
    """
    # Verify session exists
    session = db.query(SessionModel).filter(SessionModel.id == dive.session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {dive.session_id} not found")

    # Create dive
    user = getattr(request.state, "member_user", None)
    if user:
        from app.models.diver import Diver
        ids = owned_diver_ids(db, user.id)
        diver_id = dive.diver_id if dive.diver_id is not None else (ids[0] if len(ids) == 1 else None)
        if diver_id not in ids:
            raise HTTPException(403, "Choose a diver you own")
        diver_record = db.get(Diver, diver_id)
        if dive.video_uuid or dive.video_path or dive.video_filename:
            raise HTTPException(403, "Media must be attached through trusted ingestion")
    else:
        diver_record = resolve_diver(db, dive.person_name)
    db_dive = Dive(
        session_id=dive.session_id,
        visibility=dive.visibility,
        dive_code=dive.dive_code,
        dive_number=dive.dive_number,
        position=dive.position,
        direction=dive.direction,
        performance=dive.performance,
        performance_numeric=dive.performance_numeric,
        height=dive.height,
        platform_type=dive.platform_type,
        is_lineup=dive.is_lineup,
        is_sync=dive.is_sync,
        is_smack=dive.is_smack,
        raw_caption=dive.raw_caption,
        person_name=diver_record.display_name if user else dive.person_name,
        diver_id=diver_record.id if diver_record else None,
        notes=dive.notes,
        video_uuid=dive.video_uuid,
        video_filename=dive.video_filename,
        video_path=dive.video_path,
        dive_datetime=dive.dive_datetime,
    )

    db.add(db_dive)
    invalidate_analysis_cache(db)
    db.commit()
    db.refresh(db_dive)
    return _public_dive(db_dive, db)


@router.post("/upload", status_code=201)
def upload_dive(
    request: Request,
    file: UploadFile = File(...),
    dive_code: str = Form(..., pattern=r"^(?:[1-5][0-9]{2,3}|6[0-9]{2})[ABCD]$"),
    height: str = Form(..., pattern=r"^(1|3|5|7\.5|10)m$"),
    performance: str = Form(..., pattern=r"^[FBMGP]$"),
    dive_datetime: datetime = Form(...),
    visibility: str = Form("private", pattern=r"^(public|private)$"),
    notes: str = Form("", max_length=2000),
    evaluation_requested: bool = Form(False),
    evaluation_prompt: str = Form("", max_length=1000),
    diver_id: int = Form(...),
    upload_id: str = Form(..., pattern=r"^[a-f0-9-]{36}$"),
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = None,
):
    from uuid import UUID, uuid5, NAMESPACE_URL
    from sqlalchemy import select
    from app.models.diver import Diver
    from app.models.photos_asset import PhotosAsset
    from app.services.browser_upload import prepare_video, cache_upload, cleanup_upload, persist_original
    user = getattr(request.state, "member_user", None)
    if not user:
        raise HTTPException(401, "Authentication required")
    if diver_id not in owned_diver_ids(db, user.id):
        raise HTTPException(403, "Choose a diver you own")
    try:
        UUID(upload_id)
    except ValueError:
        raise HTTPException(422, "Invalid upload identity")
    video_uuid = str(uuid5(NAMESPACE_URL, f"browser:{user.id}:{upload_id}"))
    existing = db.query(Dive).filter(Dive.video_uuid == video_uuid).first()
    if existing:
        return _public_dive(existing, db)
    from app.services.dive_code_parser import DiveCodeParser
    parsed = DiveCodeParser.parse(f"{dive_code} {performance} {height}")
    if not parsed.is_valid:
        raise HTTPException(422, parsed.error or "Invalid dive code")
    diver = db.get(Diver, diver_id)
    folder, size = prepare_video(file)
    try:
        # Sessions are shared calendar days. Use a Core lookup so a day with
        # only another member's private clips is reused without exposing them.
        day = dive_datetime.date()
        session_id = db.execute(select(SessionModel.__table__.c.id).where(SessionModel.__table__.c.date == day)).scalar_one_or_none()
        if session_id is None:
            # Two members can upload on the same day concurrently.
            if db.get_bind().dialect.name in ("postgresql", "sqlite"):
                if db.get_bind().dialect.name == "postgresql":
                    from sqlalchemy.dialects.postgresql import insert
                else:
                    from sqlalchemy.dialects.sqlite import insert
                db.execute(insert(SessionModel.__table__).values(date=day).on_conflict_do_nothing(index_elements=["date"]))
                session_id = db.execute(select(SessionModel.__table__.c.id).where(SessionModel.__table__.c.date == day)).scalar_one()
            else:
                session = SessionModel(date=day)
                db.add(session)
                db.flush()
                session_id = session.id
        asset = PhotosAsset(video_uuid=video_uuid, original_filename=Path(file.filename or 'video').name[:255], media_type='video', file_size_bytes=size, photos_created_at=dive_datetime)
        db.add(asset)
        db.flush()
        record = Dive(
            session_id=session_id, diver_id=diver_id, person_name=diver.display_name,
            visibility=visibility, dive_code=parsed.dive_code,
            dive_number=parsed.dive_code[:-1], position=parsed.position,
            # The parser reports 0 for an unspecified armstand direction;
            # the existing nullable DB field only stores directions 1–5.
            direction=parsed.direction or None,
            performance=parsed.performance, performance_numeric=parsed.performance_numeric,
            height=parsed.height, platform_type=parsed.platform_type,
            notes=notes, dive_datetime=dive_datetime,
            video_uuid=video_uuid, photos_asset_id=asset.id,
        )
        db.add(record)
        db.flush()
        if evaluation_requested:
            # Same transaction as the dive publication: an upload failure
            # never publishes a request, and a retry with the same upload_id
            # returns the existing dive below without duplicating it.
            from app.services import evaluation_access

            evaluation_access.set_request(
                db, dive=record, user_id=user.id, active=True,
                prompt=evaluation_prompt or None, prompt_set=True,
            )
        cache_upload(db, asset, folder)
        db.flush()
        persist_original(db, video_uuid, folder)
        invalidate_analysis_cache(db)
        db.commit()
    except BaseException:
        db.rollback()
        cleanup_upload(folder)
        raise
    # Once committed, a response failure must never remove durable media.
    db.refresh(record)
    try:
        from app.services import notification_service
        # Inbox stays synchronous; push fans out in the background
        # (Starlette threadpool, fresh SessionLocal, bounded sends) so
        # blocking pywebpush never runs on the request path.
        rows = notification_service.notify_owners_for_diver(
            db, diver_id=diver_id, exclude_user_id=user.id,
            type='new_video', title=f'New video from {diver.display_name}',
            body=f'{parsed.dive_code} · {parsed.height}', dive_id=record.id,
            defer_push=True)
        notification_service.schedule_push(background_tasks, rows)
    except Exception:
        logger.exception('upload notification failed for dive %s', record.id)
        try:
            db.rollback()
        except Exception:
            pass
    return _public_dive(record, db)


@router.get("/{dive_id}")
def get_dive(
    dive_id: int,
    db: Session = Depends(get_db),
):
    """
    Get a specific dive by ID
    """
    dive = db.query(Dive).filter(Dive.id == dive_id).first()
    if not dive:
        raise HTTPException(status_code=404, detail=f"Dive {dive_id} not found")
    return _public_dive(dive, db)


@router.put("/{dive_id}")
def update_dive(
    dive_id: int,
    dive_update: DiveUpdate,
    db: Session = Depends(get_db),
):
    """
    Update a dive record
    """
    dive = db.query(Dive).filter(Dive.id == dive_id).first()
    if not dive:
        raise HTTPException(status_code=404, detail=f"Dive {dive_id} not found")

    # Update only provided fields
    update_data = dive_update.model_dump(exclude_unset=True)
    if db.info.get("member_access") and "person_name" in update_data:
        raise HTTPException(403, "Diver reassignment requires an operator")
    if update_data.get("visibility", "public") is None:
        raise HTTPException(422, "Visibility cannot be null")
    for field, value in update_data.items():
        setattr(dive, field, value)
    if "person_name" in update_data:
        diver_record = resolve_diver(db, dive.person_name)
        dive.diver_id = diver_record.id if diver_record else None

    db.add(dive)
    invalidate_analysis_cache(db)
    db.commit()
    db.refresh(dive)
    return _public_dive(dive, db)


@router.delete("/{dive_id}", status_code=204)
def delete_dive(
    dive_id: int,
    db: Session = Depends(get_db),
):
    """
    Delete a dive record
    """
    dive = db.query(Dive).filter(Dive.id == dive_id).first()
    if not dive:
        raise HTTPException(status_code=404, detail=f"Dive {dive_id} not found")

    db.delete(dive)
    invalidate_analysis_cache(db)
    db.commit()
    return None
