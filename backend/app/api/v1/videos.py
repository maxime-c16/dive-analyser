from fastapi import APIRouter, HTTPException, Query, Depends, BackgroundTasks, Request, status
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse, RedirectResponse
import httpx
import logging
import os
import mimetypes
import subprocess
import json
from pathlib import Path
import shutil
import threading
from datetime import datetime, date
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.dive import Dive
from app.models.dive_modifier import DiveModifier
from app.models.media import MediaCacheEntry
from app.models.photos_asset import PhotosAsset, PhotosAssetAgentIdentity
from app.models.video_label import VideoLabel
from app.models.session import Session as SessionModel
from app.schemas.video_sync import (
    VideoSyncRequest,
    VideoSyncResponse,
    VideoLabelRequest,
    VideoLabelResponse,
    BatchSyncRequest,
    BatchSyncResponse,
)
from app.services.phase_validator import PhaseValidator
from app.services.audit_log import get_audit_logger, PhaseInsightGenerator
from app.services.journey_service import JourneyService
from app.services.performance_scoring import ORDINAL_SCORE
from app.services.media_cache import playback_url
from app.services.media_jobs import create_or_reuse_media_job
from app.services.diver_identity import invalidate_analysis_cache, resolve_diver
from app.services.legacy_gate import require_legacy_media_user
from app.services.user_access import can_user_access_video
from app.security import verify_api_key

router = APIRouter(prefix="/videos", tags=["videos"])
audit_logger = get_audit_logger()
journey_service = JourneyService()

logger = logging.getLogger(__name__)

# How long to keep exported files/symlinks before cleanup (seconds)
CLEANUP_SECONDS = 7 * 24 * 60 * 60  # 7 days


def _queue_new_captioned_media(db: Session, dive: Dive) -> None:
    """Create a bounded poster/proxy pair only for a newly inserted dive."""
    if os.environ.get("NEW_VIDEO_AUTO_MEDIA_ENABLED", "false").lower() != "true":
        return
    if not dive.photos_asset_id:
        return
    asset = db.get(PhotosAsset, dive.photos_asset_id)
    if not asset:
        return
    for rendition in ("poster", "proxy_360p"):
        _, job, _ = create_or_reuse_media_job(db, asset, rendition, "new_captioned_ingestion")
        job.priority = 10
        job.max_attempts = min(job.max_attempts or 2, 2)
        db.add(job)


# ========== VIDEO SYNC ENDPOINTS (for mac-agent) ==========


def _modifier_type(modifier_code: str) -> str:
    """Classify known caption modifiers without mixing them with SYNC."""
    if modifier_code in {"DB", "SD", "HU"}:
        return "drill"
    if modifier_code == "BO":
        return "notation"
    return "training_context"


def _compute_composite_score(request: VideoSyncRequest) -> tuple[str, int]:
    """Infer the legacy composite score from single or two-phase input."""
    if request.phase1_performance and request.phase2_performance:
        composite_score = PhaseValidator.infer_legacy_score(
            request.phase1_performance,
            request.phase2_performance
        )
        return composite_score, ORDINAL_SCORE[composite_score]

    if request.performance:
        return request.performance, ORDINAL_SCORE[request.performance]

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Must provide either 'performance' (legacy) or both 'phase1_performance' and 'phase2_performance'"
    )


def _get_or_create_session(db: Session, dive_datetime: datetime) -> SessionModel:
    """Get or create the session for a synced dive date."""
    dive_date = dive_datetime.date() if isinstance(dive_datetime, datetime) else dive_datetime
    stmt = select(SessionModel).where(SessionModel.date == dive_date)
    session_record = db.execute(stmt).scalar_one_or_none()

    if session_record:
        return session_record

    session_record = SessionModel(
        date=dive_date,
        location=None,
        notes="Auto-created from video sync"
    )
    db.add(session_record)
    db.flush()
    return session_record


def _upsert_photos_asset(db: Session, request: VideoSyncRequest) -> PhotosAsset:
    """Create or update a Photos asset without replacing its canonical UUID."""
    stmt = select(PhotosAsset).where(PhotosAsset.video_uuid == request.video_uuid)
    asset = db.execute(stmt).scalar_one_or_none()

    if not asset and request.cloud_guid:
        cloud_matches = list(db.execute(
            select(PhotosAsset).where(PhotosAsset.cloud_guid == request.cloud_guid)
        ).scalars().all())
        # Ambiguous fingerprints are deliberately not auto-linked.
        asset = cloud_matches[0] if len(cloud_matches) == 1 else None

    if not asset:
        asset = PhotosAsset(
            video_uuid=request.video_uuid,
            cloud_guid=request.cloud_guid,
        )
        db.add(asset)

    if request.cloud_guid and not asset.cloud_guid:
        asset.cloud_guid = request.cloud_guid

    asset.filename = request.filename
    asset.original_filename = request.filename
    asset.photos_path = request.photos_path
    asset.local_available = request.local_available
    asset.is_missing = (request.local_available is False) if request.local_available is not None else asset.is_missing
    asset.icloud_status = (
        "local" if request.local_available is True
        else "missing_local" if request.local_available is False
        else asset.icloud_status or "unknown"
    )
    asset.raw_caption = request.raw_caption
    asset.caption_hash = request.caption_hash
    asset.last_seen_on_mac_at = datetime.utcnow()
    asset.updated_at = datetime.utcnow()
    db.flush()

    if request.agent_id:
        identity = db.execute(
            select(PhotosAssetAgentIdentity).where(
                PhotosAssetAgentIdentity.photos_asset_id == asset.id,
                PhotosAssetAgentIdentity.agent_id == request.agent_id,
            )
        ).scalar_one_or_none()
        if not identity:
            identity = PhotosAssetAgentIdentity(
                photos_asset_id=asset.id,
                agent_id=request.agent_id,
                local_uuid=request.video_uuid,
            )
            db.add(identity)
        identity.local_uuid = request.video_uuid
        identity.cloud_guid = request.cloud_guid
        identity.last_seen_at = datetime.utcnow()
        identity.updated_at = datetime.utcnow()
        db.flush()
    return asset


def _replace_dive_modifiers(db: Session, dive: Dive, modifiers: list[str], raw_caption: str | None) -> None:
    """Replace caption-derived modifiers for a dive with the latest caption state."""
    existing = list(dive.modifiers or [])
    for modifier in existing:
        db.delete(modifier)
    db.flush()

    for code in modifiers:
        db.add(DiveModifier(
            dive_id=dive.id,
            modifier_code=code,
            modifier_type=_modifier_type(code),
            source="caption",
            raw_caption=raw_caption,
        ))


def _upsert_synced_dive(db: Session, request: VideoSyncRequest) -> tuple[Dive, bool, bool]:
    """Create or update a dive from mac-agent sync metadata.

    Returns:
        tuple of (dive, created, updated)
    """
    composite_score, composite_numeric = _compute_composite_score(request)
    phase_insight = None
    if request.phase1_performance and request.phase2_performance:
        phase_insight = PhaseInsightGenerator.generate_insight(
            request.phase1_performance,
            request.phase2_performance
        )

    asset = _upsert_photos_asset(db, request)
    session_record = _get_or_create_session(db, request.date)
    diver_record = resolve_diver(db, request.person_name)

    stmt = select(Dive).where(Dive.photos_asset_id == asset.id)
    dive = db.execute(stmt).scalar_one_or_none()
    if not dive:
        dive = db.execute(
            select(Dive).where(Dive.video_uuid == request.video_uuid)
        ).scalar_one_or_none()
    created = dive is None

    if created:
        dive = Dive(
            session_id=session_record.id,
            video_uuid=asset.video_uuid,
            dive_datetime=request.date,
        )
        db.add(dive)

    # Browser URLs, cache keys, and dive references keep the first canonical UUID.
    dive.video_uuid = asset.video_uuid

    tracked_before = None if created else {
        "session_id": dive.session_id,
        "dive_code": dive.dive_code,
        "position": dive.position,
        "performance": dive.performance,
        "performance_numeric": dive.performance_numeric,
        "height": dive.height,
        "is_sync": dive.is_sync,
        "is_smack": dive.is_smack,
        "person_name": dive.person_name,
        "diver_id": dive.diver_id,
        "raw_caption": dive.raw_caption,
        "video_filename": dive.video_filename,
        "video_path": dive.video_path,
        "photos_asset_id": dive.photos_asset_id,
        "phase1_performance": dive.phase1_performance,
        "phase1_numeric": dive.phase1_numeric,
        "phase2_performance": dive.phase2_performance,
        "phase2_numeric": dive.phase2_numeric,
        "phase_insight": dive.phase_insight,
        "dive_datetime": dive.dive_datetime,
    }

    canonical_code = request.dive_code.upper()
    dive.session_id = session_record.id
    dive.dive_code = canonical_code
    dive.position = canonical_code[-1]
    dive.performance = composite_score
    dive.performance_numeric = composite_numeric
    dive.height = request.height.lower()
    dive.is_sync = request.is_sync
    dive.is_smack = request.is_smack
    dive.person_name = request.person_name
    dive.diver_id = diver_record.id if diver_record else None
    dive.raw_caption = request.raw_caption
    dive.video_filename = request.filename
    # Keep Mac-local Photos paths on photos_assets. Do not make legacy
    # dive.video_path the source of truth for the new media architecture.
    dive.photos_asset_id = asset.id
    dive.dive_datetime = request.date
    dive.is_lineup = canonical_code.startswith("0")
    dive.phase1_performance = request.phase1_performance
    dive.phase1_numeric = ORDINAL_SCORE.get(request.phase1_performance) if request.phase1_performance else None
    dive.phase2_performance = request.phase2_performance
    dive.phase2_numeric = ORDINAL_SCORE.get(request.phase2_performance) if request.phase2_performance else None
    dive.phase_insight = phase_insight
    dive.synced_at = datetime.utcnow()
    dive.updated_at = datetime.utcnow()

    db.flush()
    _replace_dive_modifiers(db, dive, request.modifiers, request.raw_caption)

    tracked_after = {
        "session_id": dive.session_id,
        "dive_code": dive.dive_code,
        "position": dive.position,
        "performance": dive.performance,
        "performance_numeric": dive.performance_numeric,
        "height": dive.height,
        "is_sync": dive.is_sync,
        "is_smack": dive.is_smack,
        "person_name": dive.person_name,
        "diver_id": dive.diver_id,
        "raw_caption": dive.raw_caption,
        "video_filename": dive.video_filename,
        "video_path": dive.video_path,
        "photos_asset_id": dive.photos_asset_id,
        "phase1_performance": dive.phase1_performance,
        "phase1_numeric": dive.phase1_numeric,
        "phase2_performance": dive.phase2_performance,
        "phase2_numeric": dive.phase2_numeric,
        "phase_insight": dive.phase_insight,
        "dive_datetime": dive.dive_datetime,
    }
    updated = (not created) and tracked_before != tracked_after
    if created or updated:
        invalidate_analysis_cache(db)
    return dive, created, updated

@router.post("/label", status_code=status.HTTP_201_CREATED)
async def sync_video_label(
    request: VideoLabelRequest,
    db: Session = Depends(get_db),
    api_key: dict = Depends(verify_api_key),
) -> VideoLabelResponse:
    """
    Sync non-dive labels from mac-agent.

    This is separate from /videos/sync so person-only captions do not create
    fake dives or pollute analytics and Journey data.
    """
    try:
        stmt = select(VideoLabel).where(
            VideoLabel.video_uuid == request.video_uuid,
            VideoLabel.label_type == request.label_type,
            VideoLabel.source == request.source,
        )
        existing = db.execute(stmt).scalar_one_or_none()

        if existing:
            changed = (
                existing.label_value != request.label_value
                or existing.raw_caption != request.raw_caption
                or existing.video_filename != request.filename
                or existing.label_datetime != request.date
            )
            existing.label_value = request.label_value
            existing.raw_caption = request.raw_caption
            existing.video_filename = request.filename
            existing.label_datetime = request.date
            existing.updated_at = datetime.utcnow()
            db.add(existing)
            db.commit()
            db.refresh(existing)
            return VideoLabelResponse(
                label_id=existing.id,
                message="Video label updated" if changed else "Video label already synced",
                created=False,
            )

        label = VideoLabel(
            video_uuid=request.video_uuid,
            label_type=request.label_type,
            label_value=request.label_value,
            source=request.source,
            raw_caption=request.raw_caption,
            video_filename=request.filename,
            label_datetime=request.date,
        )
        db.add(label)
        db.commit()
        db.refresh(label)

        return VideoLabelResponse(
            label_id=label.id,
            message="Video label synced successfully",
            created=True,
        )

    except Exception as e:
        db.rollback()
        print(f"Error syncing video label: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error syncing video label"
        )


@router.post("/sync", status_code=status.HTTP_201_CREATED)
async def sync_single_video(
    request: VideoSyncRequest,
    db: Session = Depends(get_db),
    api_key: dict = Depends(verify_api_key),
    background_tasks: BackgroundTasks = None,
) -> VideoSyncResponse:
    """
    Sync single video metadata from mac-agent.

    Receives dive metadata from the mac-agent, validates it, and stores in database.
    Automatically triggers Journey milestone detection in background.

    Args:
        request: VideoSyncRequest with dive metadata
        db: Database session
        background_tasks: Background task queue for Journey processing

    Returns:
        VideoSyncResponse with dive_id and status

    Raises:
        HTTPException(400): Invalid request data
        HTTPException(409): Duplicate video (same UUID)
        HTTPException(500): Database error
    """
    try:
        # Validate phase scores if two-phase format
        if request.phase1_performance or request.phase2_performance:
            valid, error = PhaseValidator.validate_combination(
                request.phase1_performance,
                request.phase2_performance
            )
            if not valid:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=error
                )

        from app.services import deposit_batches
        depositor = deposit_batches.resolve_depositor(db)
        day = request.date.date() if isinstance(request.date, datetime) else request.date
        batch_id = deposit_batches.agent_day_batch_id(request.agent_id, day)
        dive, created, updated = _upsert_synced_dive(db, request)
        pending_diver = deposit_batches.finalize_synced_dive(
            db, dive, batch_id=batch_id, created=created,
            depositor=depositor, raw_caption=request.raw_caption)
        if created:
            _queue_new_captioned_media(db, dive)
        db.commit()
        db.refresh(dive)
        if pending_diver is not None:
            try:
                deposit_batches.queue_batch_email(
                    db, batch_id=batch_id, diver_id=pending_diver,
                    exclude_user_id=depositor.id if depositor else None)
                db.commit()
            except Exception:
                logger.exception('batch email queue failed for dive %s', dive.id)
                try:
                    db.rollback()
                except Exception:
                    pass

        if created and dive.diver_id is not None:
            # Machine-key sync has no actor to exclude: every owner is told.
            # Inbox is synchronous; push is BackgroundTasks (threadpool,
            # fresh SessionLocal, bounded) — never inline pywebpush from
            # this async endpoint on the single uvicorn worker.
            try:
                from app.services import notification_service
                rows = notification_service.notify_owners_for_diver(
                    db, diver_id=dive.diver_id, exclude_user_id=None,
                    type='new_video', title='New video synced',
                    body=f'{dive.dive_code or "?"} · {dive.height or "?"}',
                    dive_id=dive.id, defer_push=True)
                notification_service.schedule_push(background_tasks, rows)
            except Exception:
                logger.exception('sync notification failed for dive %s', dive.id)
                try:
                    db.rollback()
                except Exception:
                    pass

        # Log successful sync
        audit_logger.log_sync_single(
            video_uuid=request.video_uuid,
            dive_code=request.dive_code,
            person_name=request.person_name,
            result="success" if created else "updated" if updated else "unchanged",
            dive_id=dive.id
        )

        # Log phase insight if generated
        if dive.phase_insight:
            audit_logger.log_phase_insight_generation(
                dive_id=dive.id,
                phase1_performance=request.phase1_performance,
                phase2_performance=request.phase2_performance,
                insight=dive.phase_insight
            )

        # Queue Journey milestone detection in background
        if background_tasks:
            try:
                background_tasks.add_task(
                    journey_service.process_new_dives,
                    [dive.id],
                    db
                )
            except Exception as e:
                print(f"Warning: Could not queue Journey processing: {e}")

        return VideoSyncResponse(
            dive_id=dive.id,
            message="Video synced successfully" if created else "Video metadata updated" if updated else "Video already up to date",
            created=created,
            updated=updated,
        )

    except HTTPException as e:
        # Log validation and auth errors
        if e.status_code == status.HTTP_400_BAD_REQUEST:
            audit_logger.log_validation_error(
                video_uuid=request.video_uuid,
                field="phase_scores" if "phase" in e.detail.lower() else "performance",
                error_message=e.detail
            )
        raise
    except Exception as e:
        db.rollback()
        print(f"Error syncing video: {str(e)}")
        # Log server error
        audit_logger.log_sync_single(
            video_uuid=request.video_uuid,
            dive_code=request.dive_code,
            person_name=request.person_name,
            result="server_error",
            error=str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error syncing video"
        )


@router.post("/batch", status_code=status.HTTP_200_OK)
async def sync_batch_videos(
    request: BatchSyncRequest,
    db: Session = Depends(get_db),
    api_key: dict = Depends(verify_api_key),
    background_tasks: BackgroundTasks = None,
) -> BatchSyncResponse:
    """
    Sync multiple videos in a single batch request.

    Processes all videos and returns per-video status.
    Transactional: all succeed or all rollback.

    Args:
        request: BatchSyncRequest with list of videos
        api_key: Validated API key
        db: Database session
        background_tasks: Background task queue

    Returns:
        BatchSyncResponse with summary and per-video errors
    """
    try:
        succeeded = 0
        failed = 0
        errors = []
        new_dive_ids = []

        # Validate all before inserting any
        for video in request.videos:
            if video.phase1_performance or video.phase2_performance:
                valid, error = PhaseValidator.validate_combination(
                    video.phase1_performance,
                    video.phase2_performance
                )
                if not valid:
                    audit_logger.log_validation_error(
                        video_uuid=video.video_uuid,
                        field="phase_scores",
                        error_message=error
                    )
                    errors.append({
                        "video_uuid": video.video_uuid,
                        "error": error
                    })
                    failed += 1

        # If validation errors, fail fast
        if errors:
            return BatchSyncResponse(
                total=len(request.videos),
                succeeded=0,
                failed=len(errors),
                errors=errors
            )

        # Track UUIDs processed in this batch to detect intra-batch duplicates
        seen_uuids = set()

        from app.services import deposit_batches
        depositor = deposit_batches.resolve_depositor(db)
        batch_id = deposit_batches.new_batch_id()
        pending_divers: set = set()

        # Process each video
        for video in request.videos:
            try:
                # Repeated UUIDs in the same batch are idempotent; the last
                # payload wins, matching the single-video upsert endpoint.
                seen_uuids.add(video.video_uuid)

                dive, created, updated = _upsert_synced_dive(db, video)
                pending = deposit_batches.finalize_synced_dive(
                    db, dive, batch_id=batch_id, created=created,
                    depositor=depositor, raw_caption=video.raw_caption)
                if pending is not None:
                    pending_divers.add(pending)
                if created:
                    new_dive_ids.append(dive.id)
                    _queue_new_captioned_media(db, dive)
                succeeded += 1

            except Exception as e:
                errors.append({
                    "video_uuid": video.video_uuid,
                    "error": str(e)
                })
                failed += 1

        # Commit all at once (transactional)
        if succeeded > 0:
            db.commit()
            for diver_id in pending_divers:
                try:
                    deposit_batches.queue_batch_email(
                        db, batch_id=batch_id, diver_id=diver_id,
                        exclude_user_id=depositor.id if depositor else None)
                except Exception:
                    logger.exception('batch email queue failed for batch %s', batch_id)
                    try:
                        db.rollback()
                    except Exception:
                        pass
            try:
                db.commit()
            except Exception:
                db.rollback()

            if new_dive_ids:
                # One batched notification per diver per request (never N rows
                # for an N-clip batch to the same owner). Inbox synchronous;
                # push via BackgroundTasks (threadpool, fresh session, bounded).
                try:
                    from app.services import notification_service
                    rows = db.query(Dive.id, Dive.diver_id, Dive.dive_code).filter(
                        Dive.id.in_(new_dive_ids)).limit(500).all()
                    by_diver: dict = {}
                    for did, diver_id, code in rows:
                        if diver_id is None:
                            continue
                        by_diver.setdefault(diver_id, []).append((did, code))
                    all_notif_rows = []
                    for diver_id, items in by_diver.items():
                        count = len(items)
                        all_notif_rows.extend(
                            notification_service.notify_owners_for_diver(
                                db, diver_id=diver_id, exclude_user_id=None,
                                type='new_video',
                                title='New videos synced' if count > 1 else 'New video synced',
                                body=(f'{count} new clips synced' if count > 1
                                      else f'{items[0][1] or "?"} synced'),
                                dive_id=items[0][0] if count == 1 else None,
                                defer_push=True)
                        )
                    notification_service.schedule_push(background_tasks, all_notif_rows)
                except Exception:
                    logger.exception('batch sync notification failed')
                    try:
                        db.rollback()
                    except Exception:
                        pass

            # Queue Journey milestone detection in background
            if background_tasks:
                try:
                    background_tasks.add_task(
                        journey_service.process_new_dives,
                        new_dive_ids,
                        db
                    )
                except Exception as e:
                    print(f"Warning: Could not queue Journey processing: {e}")

        # Log batch sync operation
        import uuid as uuid_module
        audit_batch_id = str(uuid_module.uuid4())[:8]
        audit_logger.log_sync_batch(
            batch_id=audit_batch_id,
            video_count=len(request.videos),
            success_count=succeeded,
            error_count=failed,
            duplicate_count=sum(1 for e in errors if "Duplicate" in str(e.get("error", ""))),
            errors=errors if errors else None
        )

        return BatchSyncResponse(
            total=len(request.videos),
            succeeded=succeeded,
            failed=failed,
            errors=errors
        )

    except Exception as e:
        db.rollback()
        print(f"Error in batch sync: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error processing batch"
        )


# ========== VIDEO STREAM ENDPOINTS (existing) ==========

@router.get("/{video_uuid}")
async def stream_video(
    video_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = None,
):
    """
    Stream a video by UUID.

    Video files are stored in the macOS Photos library.
    We look up the dive record to get the video path, then stream the file.

    P6 legacy IDOR closure: while USER_AUTH_ENABLED the route requires a
    live session and central OWNER authorization BEFORE any bytes leave the
    server. With auth disabled the legacy behavior is preserved (rollback).
    """
    user = require_legacy_media_user(db, request)
    try:
        # Find the dive with this video UUID
        stmt = select(Dive).where(Dive.video_uuid == video_uuid)
        result = db.execute(stmt)
        dive = result.scalar_one_or_none()

        if not dive:
            raise HTTPException(status_code=404, detail="Video not found")

        if user is not None:
            decision = can_user_access_video(db, user, video_uuid)
            if not decision.allowed:
                # Uniform 404: no existence disclosure for unauthorized
                # identities, exactly like the P5 playback route.
                raise HTTPException(status_code=404, detail="Video not found")

        print(f"[videos] lookup: video_uuid={video_uuid}, video_path={getattr(dive,'video_path',None)}, video_filename={getattr(dive,'video_filename',None)}")

        # Get the video path
        video_path = dive.video_path

        if not video_path:
            cached_proxy = _ready_cached_media_for_uuid(db, video_uuid, "proxy_360p")
            if cached_proxy:
                return RedirectResponse(url=playback_url(cached_proxy.id), status_code=307)

            cached_poster = _ready_cached_media_for_uuid(db, video_uuid, "poster")
            if cached_poster:
                raise HTTPException(
                    status_code=202,
                    detail={
                        "message": "Video proxy not cached yet",
                        "source": "media_cache",
                        "poster_url": playback_url(cached_poster.id),
                        "can_request": True,
                    },
                )

            raise HTTPException(status_code=404, detail="Video path not available")

        # Skip streamer proxy for now - using local videos in /videos/
        # (If needed later, configure STREAMER_HOST and STREAMER_PORT env vars)

        # Try to find the video file in multiple locations
        # Priority order: test videos, photos library, direct path
        alternatives = [
            f"/videos/{video_uuid}.mp4",  # Mounted videos directory
            f"/videos/{os.path.basename(video_path)}" if video_path else None,  # Mounted videos directory
            video_path if os.path.isabs(video_path) else None,  # Absolute path
            f"/photos_library/Masters/{video_path}" if video_path else None,  # Photos library
            f"/photos_library/{video_path}" if video_path else None,  # Photos library alternative
            f"/tmp/dive_downloads/{video_uuid}/*",
        ]

        full_path = None
        for alt in filter(None, alternatives):
            if isinstance(alt, str) and alt.endswith('/*'):
                dirpath = Path(alt[:-2])
                if dirpath.exists():
                    # pick first file found
                    files = [p for p in dirpath.glob('**/*') if p.is_file()]
                    if files:
                        full_path = str(files[0])
                        break
                continue
            if os.path.exists(alt):
                full_path = alt
                break

        if not full_path:
            # Return 404 but don't expose file paths
            raise HTTPException(status_code=404, detail="Video file not accessible")

        # Verify the path is within allowed directories (security check)
        real_path = os.path.realpath(full_path)
        allowed_dirs = [
            os.path.realpath("/photos_library"),
            os.path.realpath("/videos"),
            os.path.realpath("/tmp/dive_downloads"),
        ]

        is_allowed = any(real_path.startswith(allowed_dir) for allowed_dir in allowed_dirs)
        if not is_allowed:
            raise HTTPException(status_code=403, detail="Access denied")

        # Determine MIME type
        mime_type, _ = mimetypes.guess_type(full_path)
        if mime_type is None:
            mime_type = "video/quicktime"  # Default for MOV files

        # Stream the video with proper headers for range requests (fast seeking)
        return FileResponse(
            full_path,
            media_type=mime_type,
            filename=os.path.basename(full_path),
            headers={
                "Accept-Ranges": "bytes",
                "Cache-Control": "public, max-age=3600",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error streaming video {video_uuid}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error serving video")


@router.get("/check/{video_uuid}")
async def check_video_availability(
    video_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Check if a video is available without streaming it.
    Useful for frontend to show icons only for available videos.

    P6 legacy IDOR closure: same session + central authorization gate as
    the streaming route (raised BEFORE the availability probe and outside
    its catch-all, so denial is a real 401/404 — never a spoofed
    {"available": false}).
    """
    user = require_legacy_media_user(db, request)
    if user is not None:
        decision = can_user_access_video(db, user, video_uuid)
        if not decision.allowed:
            raise HTTPException(status_code=404, detail="Video not found")
    try:
        cached_proxy = _ready_cached_media_for_uuid(db, video_uuid, "proxy_360p")
        if cached_proxy:
            return {
                "available": True,
                "source": "media_cache",
                "rendition": "proxy_360p",
                "playback_url": playback_url(cached_proxy.id),
                "size": cached_proxy.size_bytes,
                "status": "ready",
            }

        cached_poster = _ready_cached_media_for_uuid(db, video_uuid, "poster")
        if cached_poster:
            return {
                "available": False,
                "source": "media_cache",
                "status": "poster_ready",
                "can_request": True,
                "poster_url": playback_url(cached_poster.id),
            }

        stmt = select(Dive).where(Dive.video_uuid == video_uuid)
        result = db.execute(stmt)
        dive = result.scalar_one_or_none()

        if not dive or not dive.video_path:
            return {"available": False}

        # Check if file exists in multiple locations
        video_path = dive.video_path
        # First check for in-progress download status
        status_file = Path("/tmp/dive_downloads") / f"status_{video_uuid}.json"
        if status_file.exists():
            try:
                data = json.loads(status_file.read_text())
                status = data.get("status")
                if status == "completed":
                    files = data.get("files", [])
                    if files:
                        size = sum(Path(f).stat().st_size for f in files if Path(f).exists())
                        return {"available": True, "size": size, "status": "completed"}
                return {"available": False, "status": status}
            except Exception:
                return {"available": False}

        alternatives = [
            f"/videos/{video_uuid}.mp4",  # Mounted videos directory
            f"/videos/{os.path.basename(video_path)}" if video_path else None,  # Mounted videos directory
            video_path if os.path.isabs(video_path) else None,  # Absolute path
            f"/photos_library/Masters/{video_path}" if video_path else None,  # Photos library
            f"/photos_library/{video_path}" if video_path else None,  # Photos library alternative
        ]

        for alt in filter(None, alternatives):
            if os.path.exists(alt):
                return {"available": True, "size": os.path.getsize(alt)}

        return {"available": False}

    except Exception as e:
        print(f"Error checking video {video_uuid}: {str(e)}")
        return {"available": False}


def _ready_cached_media_for_uuid(db: Session, video_uuid: str, rendition: str) -> MediaCacheEntry | None:
    """Return a ready cached rendition for legacy video compatibility."""
    stmt = (
        select(MediaCacheEntry)
        .join(PhotosAsset, PhotosAsset.id == MediaCacheEntry.photos_asset_id)
        .where(
            PhotosAsset.video_uuid == video_uuid,
            MediaCacheEntry.rendition == rendition,
            MediaCacheEntry.status == "ready",
        )
        .order_by(MediaCacheEntry.created_at.desc())
    )
    return db.execute(stmt).scalars().first()
