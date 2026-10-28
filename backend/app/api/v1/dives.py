"""Dive CRUD endpoints"""

import logging
from typing import List, Optional
from pathlib import Path
from datetime import datetime, timedelta
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, File, Form, UploadFile
from sqlalchemy import or_, and_, func
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
    "batch_id", "accepted_at", "deposited_by_user_id",
    "dive_datetime", "created_at", "updated_at",
)
LIST_COLUMNS = tuple(getattr(Dive, _name) for _name in LIST_COLUMN_NAMES)


def _public_dive(dive: Dive, db: Session, federate_map: set[int] | None = None, evaluation_map: dict[int, dict] | None = None, owner_ids=None) -> dict:
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
    if context is None:
        # Legacy / machine-key reads keep the previous contract.
        payload["can_manage"] = True
    else:
        from types import SimpleNamespace

        from app.services.dive_access import can_manage_dive

        viewer = SimpleNamespace(
            id=context.get("user_id"),
            is_active=True,
            is_admin=bool(context.get("is_admin")),
        )
        payload["can_manage"] = can_manage_dive(db, viewer, dive, owner_ids=owner_ids)
    payload["pending_acceptance"] = dive.accepted_at is None and dive.batch_id is not None
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


def _filtered_dive_query(
    request: Request, db: Session, *, diver_scope: str, session_id: Optional[int] = None,
    dive_code: Optional[str] = None, height: Optional[str] = None, performance: Optional[str] = None,
    date_from: Optional[datetime] = None, date_to: Optional[datetime] = None,
    exclude_lineup: bool = False, exclude_personal: bool = False, code_prefix: str = "",
    search_text: str = "", position_filter: str = "", sync_filter: Optional[bool] = None,
    modifier_filter: str = "",
):
    """Access-scoped dive query with every Library filter applied (no order, no paging)."""
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
        query = query.filter(func.lower(func.replace(Dive.height, " ", "")) == height.lower().replace(" ", ""))

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

    from app.services.library_query import apply_library_filters
    return apply_library_filters(query, db, code_prefix, search_text, position_filter, sync_filter, modifier_filter)


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
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    code_prefix: str = "",
    search_text: str = "",
    position_filter: str = "",
    sync_filter: Optional[bool] = None,
    modifier_filter: str = "",
    cursor: Optional[str] = None,
):
    """
    List dives with optional filters
    """
    query = _filtered_dive_query(
        request, db, diver_scope=diver_scope, session_id=session_id, dive_code=dive_code,
        height=height, performance=performance, date_from=date_from, date_to=date_to,
        exclude_lineup=exclude_lineup, exclude_personal=exclude_personal, code_prefix=code_prefix,
        search_text=search_text, position_filter=position_filter, sync_filter=sync_filter,
        modifier_filter=modifier_filter,
    )
    from app.services.library_query import decode_cursor
    if cursor:
        before_date, before_id = decode_cursor(cursor)
        query = query.filter(or_(Dive.dive_datetime < before_date,
                                 and_(Dive.dive_datetime == before_date, Dive.id < before_id)))
    query = query.options(Load(Dive).load_only(*LIST_COLUMNS, raiseload=True))
    # Order by date and id descending. Many Photos videos can share the same
    # second-level timestamp, so id gives deterministic newest-first ties.
    dives = query.order_by(Dive.dive_datetime.desc(), Dive.id.desc()).offset(offset).limit(limit).all()
    from app.services.fediverse import optin_map
    from app.services.evaluation_access import request_map as evaluation_request_map

    federate_map = optin_map(db, [dive.id for dive in dives])
    evaluation_map = evaluation_request_map(db, [dive.id for dive in dives])
    context = db.info.get("member_access")
    owner_ids = frozenset(context["diver_ids"]) if context else None
    return [_public_dive(dive, db, federate_map, evaluation_map, owner_ids) for dive in dives]


def _library_visuals(db: Session, uuids: list[str]) -> dict[str, dict]:
    """Latest ready poster thumbnail/thumbhash and animated preview per video, in one bounded join."""
    from app.models.media import MediaCacheEntry
    from app.models.photos_asset import PhotosAsset
    from app.services.media_cache import thumb_url, playback_url
    visuals: dict[str, dict] = {}
    if not uuids:
        return visuals
    # Reduce historical generations in SQL before materializing ORM rows:
    # at most one ready entry per asset/rendition (200 for a full page).
    latest_visual_ids = db.query(func.max(MediaCacheEntry.id).label("id")).join(
        PhotosAsset, MediaCacheEntry.photos_asset_id == PhotosAsset.id
    ).filter(
        PhotosAsset.video_uuid.in_(uuids),
        MediaCacheEntry.rendition.in_(("poster", "animated")),
        MediaCacheEntry.status == "ready",
    ).group_by(MediaCacheEntry.photos_asset_id, MediaCacheEntry.rendition).subquery()
    for uuid, poster in db.query(PhotosAsset.video_uuid, MediaCacheEntry).join(
        MediaCacheEntry, MediaCacheEntry.photos_asset_id == PhotosAsset.id
    ).join(latest_visual_ids, MediaCacheEntry.id == latest_visual_ids.c.id).all():
        visual = visuals.setdefault(uuid, {})
        if poster.rendition == "animated":
            visual["animated_url"] = playback_url(poster)
        else:
            visual.update({"thumbhash": poster.thumbhash, "thumb_url": thumb_url(poster)})
    return visuals


@router.get("/library")
def library_page(
    request: Request, db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=100), cursor: Optional[str] = None,
    diver_scope: str = Query("self", pattern="^(self|all)$"),
    height: str = "", performance: str = "", code_prefix: str = "",
    search_text: str = Query("", max_length=200), position_filter: str = "",
    sync_filter: Optional[bool] = None, modifier_filter: str = "",
):
    """A bounded, filtered Library page; cursor ties include id for stable order."""
    from app.services.library_query import encode_cursor
    rows = list_dives(request=request, db=db, session_id=None, dive_code=None,
        height=height, performance=performance, date_from=None, date_to=None,
        exclude_lineup=True, exclude_personal=False, diver_scope=diver_scope,
        limit=limit + 1, offset=0, code_prefix=code_prefix, search_text=search_text,
        position_filter=position_filter, sync_filter=sync_filter,
        modifier_filter=modifier_filter, cursor=cursor)
    more = len(rows) > limit
    rows = rows[:limit]
    # One bounded join after list_dives has applied the existing access scope.
    visuals = _library_visuals(db, [row["video_uuid"] for row in rows if row.get("video_uuid")])
    for row in rows:
        row.update(visuals.get(row.get("video_uuid"), {}))
    return {"items": rows, "next_cursor": encode_cursor(rows[-1]) if more else None}


@router.get("/library/codes")
def library_codes(
    request: Request, db: Session = Depends(get_db),
    diver_scope: str = Query("self", pattern="^(self|all)$"),
    height: str = "", performance: str = "", code_prefix: str = "",
    search_text: str = Query("", max_length=200), position_filter: str = "",
    sync_filter: Optional[bool] = None, modifier_filter: str = "",
):
    """Per-code summaries and recent activity over the whole filtered Library scope."""
    from app.services.code_summaries import summarize_library_query
    query = _filtered_dive_query(
        request, db, diver_scope=diver_scope, height=height, performance=performance,
        exclude_lineup=True, code_prefix=code_prefix, search_text=search_text,
        position_filter=position_filter, sync_filter=sync_filter, modifier_filter=modifier_filter,
    )
    return summarize_library_query(db, query, datetime.now())


@router.get("/library/codes/{dive_code}/community")
def library_code_community(
    dive_code: str, request: Request, db: Session = Depends(get_db),
    height: str = Query("", max_length=20),
):
    """Other divers' public attempts on one code: ranking stats, recent series, best dive."""
    from app.services.code_community import community_for_code
    from app.services.dive_access import CONTEXT_KEY
    code = dive_code.strip().upper()
    if not code or len(code) > 12:
        raise HTTPException(422, "Invalid dive code")
    context = db.info.get(CONTEXT_KEY)
    # Legacy single-diver deployments: "you" is the primary diver.
    own = tuple(context["diver_ids"]) if context else (get_primary_diver(db).id,)
    query = _filtered_dive_query(request, db, diver_scope="all", height=height, exclude_lineup=True)
    payload = community_for_code(db, query, code, own)
    best_ids = [member.pop("best_id") for member in payload["members"]]
    best = {dive.id: dive for dive in db.query(Dive).options(Load(Dive).load_only(*LIST_COLUMNS, raiseload=True)).filter(Dive.id.in_(best_ids)).all()} if best_ids else {}
    rows = {dive_id: _public_dive(dive, db) for dive_id, dive in best.items()}
    visuals = _library_visuals(db, [row["video_uuid"] for row in rows.values() if row.get("video_uuid")])
    for member, dive_id in zip(payload["members"], best_ids):
        row = rows.get(dive_id)
        if row:
            row.update(visuals.get(row.get("video_uuid"), {}))
        member["best"] = row
    return payload


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


from app.schemas.dive import BrowserUploadReservation


@router.post("/uploads", status_code=202)
def queue_upload(body: BrowserUploadReservation, request: Request, db: Session = Depends(get_db)):
    from app.services.upload_queue import reserve
    user = getattr(request.state, "member_user", None)
    if not user:
        raise HTTPException(401, "Authentication required")
    payload = body.model_dump(mode='json', exclude={'filename'})
    return reserve(db, user, body.filename, payload)


@router.put("/uploads/{upload_id}/content", status_code=202)
async def upload_content(upload_id: str, request: Request, db: Session = Depends(get_db)):
    from app.services.upload_queue import receive
    user = getattr(request.state, "member_user", None)
    if not user:
        raise HTTPException(401, "Authentication required")
    return await receive(db, user, upload_id, request)


@router.get("/uploads/{upload_id}")
def upload_status(upload_id: str, request: Request, db: Session = Depends(get_db)):
    from app.models.browser_upload import BrowserUploadJob
    from app.services.upload_queue import summary
    user = getattr(request.state, "member_user", None)
    if not user:
        raise HTTPException(401, "Authentication required")
    job = db.query(BrowserUploadJob).filter_by(user_id=user.id, upload_id=upload_id).first()
    if job is None:
        raise HTTPException(404, "Upload not found")
    return summary(job)


@router.post("/upload")
def retired_upload():
    # No body parameters: old clients cannot trigger multipart spooling or
    # bypass queue reservations. The worker invokes publication internally.
    raise HTTPException(410, "Reload the app to use the new upload flow")


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
    # Admins may deposit on behalf of another account: the clip stays
    # private + pending until the owner accepts it (deposit-batch flow).
    deposit_for_other = diver_id not in owned_diver_ids(db, user.id)
    if deposit_for_other and not user.is_admin:
        raise HTTPException(403, "Choose a diver you own")
    if deposit_for_other:
        context = db.info.get("member_access")
        if context is not None:
            context["system_mutation"] = True
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
    if diver is None and deposit_for_other and user.is_admin:
        # The target diver has no visible dive yet, so the member read scope
        # hides them; re-read unscoped (admin deposit path only).
        from app.services.dive_access import unscoped_reads

        with unscoped_reads(db):
            diver = db.get(Diver, diver_id)
    if diver is None:
        raise HTTPException(404, "Diver not found")
    # End the authorization read transaction before CPU/network work. Never
    # publish a clip until original storage has been roundtrip verified.
    user_id = user.id
    db.rollback()
    folder, size = prepare_video(file)
    try:
        manifest = persist_original(None, video_uuid, folder, register=False)
        playback_manifest = persist_original(None, video_uuid, folder, register=False, source_name='original.mp4')
        if manifest and playback_manifest and manifest['blob_sha256'] == playback_manifest['blob_sha256']:
            # Exact content identity is deduplicated. Identical source/output
            # bytes are already proven to be the browser-compatible MP4.
            manifest = playback_manifest
        lease = getattr(request.state, 'upload_job', None)
        if lease is not None:
            from app.models.browser_upload import BrowserUploadJob
            job_id, attempt = lease
            job = db.query(BrowserUploadJob).filter_by(id=job_id).with_for_update().populate_existing().one()
            if job.status != 'processing' or job.attempts != attempt:
                raise HTTPException(409, 'Upload processing lease changed; please retry')
        # Re-check ownership/account state after preparation; permissions may
        # have changed while this large file was being processed.
        from app.models.user_auth import AppUser
        db.expire_all()
        user = db.get(AppUser, user_id)
        if not user or not user.is_active:
            raise HTTPException(403, "Upload account is no longer active")
        deposit_for_other = diver_id not in owned_diver_ids(db, user.id)
        if deposit_for_other and not user.is_admin:
            raise HTTPException(403, "Choose a diver you own")
        context = db.info.get("member_access")
        if context is not None:
            context.update(diver_ids=owned_diver_ids(db, user.id), is_admin=bool(user.is_admin), system_mutation=deposit_for_other)
        from app.services.dive_access import unscoped_reads
        with unscoped_reads(db):
            diver = db.get(Diver, diver_id)
        if diver is None:
            raise HTTPException(404, "Diver not found")
        # Sessions are shared calendar days. Use a Core lookup so a day with
        # only another member's private clips is reused without exposing them.
        day = dive_datetime.date()
        session_id = db.execute(select(SessionModel.__table__.c.id).where((SessionModel.__table__.c.date == day) & SessionModel.__table__.c.calendar_occurrence_id.is_(None))).scalar_one_or_none()
        if session_id is None:
            # Two members can upload on the same day concurrently.
            if db.get_bind().dialect.name in ("postgresql", "sqlite"):
                if db.get_bind().dialect.name == "postgresql":
                    from sqlalchemy.dialects.postgresql import insert
                else:
                    from sqlalchemy.dialects.sqlite import insert
                db.execute(insert(SessionModel.__table__).values(date=day).on_conflict_do_nothing(index_elements=["date"], index_where=SessionModel.__table__.c.calendar_occurrence_id.is_(None)))
                session_id = db.execute(select(SessionModel.__table__.c.id).where((SessionModel.__table__.c.date == day) & SessionModel.__table__.c.calendar_occurrence_id.is_(None))).scalar_one()
            else:
                session = SessionModel(date=day)
                db.add(session)
                db.flush()
                session_id = session.id
        from app.services import deposit_batches
        asset = PhotosAsset(video_uuid=video_uuid, original_filename=Path(file.filename or 'video').name[:255], media_type='video', file_size_bytes=size, photos_created_at=dive_datetime)
        db.add(asset)
        db.flush()
        batch_id = deposit_batches.new_batch_id()
        if deposit_for_other:
            # Maintainer note becomes an evaluator note; the owner's personal
            # notes field stays theirs to fill in.
            owner_notes = None
            pending_at = None
            forced_visibility = "private"
        else:
            owner_notes = notes
            pending_at = datetime.utcnow()
            forced_visibility = visibility
        record = Dive(
            session_id=session_id, diver_id=diver_id, person_name=diver.display_name,
            visibility=forced_visibility, dive_code=parsed.dive_code,
            dive_number=parsed.dive_code[:-1], position=parsed.position,
            # The parser reports 0 for an unspecified armstand direction;
            # the existing nullable DB field only stores directions 1–5.
            direction=parsed.direction or None,
            performance=parsed.performance, performance_numeric=parsed.performance_numeric,
            height=parsed.height, platform_type=parsed.platform_type,
            notes=owner_notes, dive_datetime=dive_datetime,
            video_uuid=video_uuid, photos_asset_id=asset.id,
            batch_id=batch_id, accepted_at=pending_at,
            deposited_by_user_id=user.id,
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
        if deposit_for_other:
            if (notes or "").strip():
                from app.models.deposit_batch import EvaluatorNote
                db.add(EvaluatorNote(
                    dive_id=record.id, author_user_id=user.id,
                    comment=notes.strip()[:deposit_batches.NOTE_COMMENT_MAX]))
                db.flush()
            # Every pending deposit emails its owner; the caption is optional.
            try:
                deposit_batches.queue_batch_email(
                    db, batch_id=batch_id, diver_id=diver_id,
                    exclude_user_id=user.id)
            except Exception:
                logger.exception('batch email queue failed for upload %s', record.id)
        posters = cache_upload(db, asset, folder)
        db.flush()
        poster_ids = [entry.id for entry in (posters or [])]
        if manifest is not None:
            from app.services.media_backbone import commit_verified_ingest
            commit_verified_ingest(db, **manifest, commit=False)
            if playback_manifest is not None:
                commit_verified_ingest(db, **playback_manifest, commit=False)
        invalidate_analysis_cache(db)
        db.commit()
    except BaseException:
        db.rollback()
        cleanup_upload(folder)
        raise
    # Called by the synchronous upload worker, after the publication commit.
    from app.services.poster_visuals import enrich_committed_poster
    for poster_id in poster_ids:
        enrich_committed_poster(poster_id, bind=db.get_bind())
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
    if (
        update_data.get("visibility") == "public"
        and dive.batch_id is not None
        and dive.accepted_at is None
    ):
        # A pending deposit stays private until its owner accepts it; the
        # depositor can manage it but must never expose it early.
        raise HTTPException(409, "Accept this deposit before making it public")
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
