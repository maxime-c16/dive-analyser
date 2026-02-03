from fastapi import APIRouter, HTTPException, Query, Depends, BackgroundTasks, status
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
import httpx
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
from app.models.session import Session as SessionModel
from app.schemas.video_sync import (
    VideoSyncRequest,
    VideoSyncResponse,
    BatchSyncRequest,
    BatchSyncResponse,
)
from app.services.phase_validator import PhaseValidator
from app.services.audit_log import get_audit_logger, PhaseInsightGenerator
from app.services.journey_service import JourneyService
from app.security import verify_api_key

router = APIRouter(prefix="/videos", tags=["videos"])
audit_logger = get_audit_logger()
journey_service = JourneyService()

# How long to keep exported files/symlinks before cleanup (seconds)
CLEANUP_SECONDS = 7 * 24 * 60 * 60  # 7 days


# ========== VIDEO SYNC ENDPOINTS (for mac-agent) ==========

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

        # Check for duplicate by UUID
        stmt = select(Dive).where(Dive.video_uuid == request.video_uuid)
        result = db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            # Video already synced (idempotent return)
            audit_logger.log_deduplication_check(
                video_uuid=request.video_uuid,
                existing_dive_id=existing.id
            )
            return VideoSyncResponse(
                dive_id=existing.id,
                message="Video already synced (duplicate)",
                created=False
            )

        # Determine composite performance score
        if request.phase1_performance and request.phase2_performance:
            # Two-phase format: infer legacy score
            composite_score = PhaseValidator.infer_legacy_score(
                request.phase1_performance,
                request.phase2_performance
            )
            # Map to numeric
            score_map = {'F': 0, 'B': 1, 'M': 2, 'G': 3, 'P': 4}
            composite_numeric = score_map[composite_score]
        elif request.performance:
            # Legacy format
            composite_score = request.performance
            score_map = {'F': 0, 'B': 1, 'M': 2, 'G': 3, 'P': 4}
            composite_numeric = score_map[composite_score]
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Must provide either 'performance' (legacy) or both 'phase1_performance' and 'phase2_performance'"
            )

        # Generate phase insight if two-phase format
        phase_insight = None
        if request.phase1_performance and request.phase2_performance:
            phase_insight = PhaseInsightGenerator.generate_insight(
                request.phase1_performance,
                request.phase2_performance
            )

        # Get or create session for the dive date
        dive_date = request.date.date() if isinstance(request.date, datetime) else request.date
        stmt = select(SessionModel).where(SessionModel.date == dive_date)
        result = db.execute(stmt)
        session_record = result.scalar_one_or_none()

        if not session_record:
            # Create new session for this date
            session_record = SessionModel(
                date=dive_date,
                location=None,
                notes="Auto-created from video sync"
            )
            db.add(session_record)
            db.flush()  # Flush to get the session ID

        # Create new dive record
        dive = Dive(
            session_id=session_record.id,
            dive_code=request.dive_code.upper(),
            performance=composite_score,
            performance_numeric=composite_numeric,
            height=request.height.lower(),
            is_sync=request.is_sync,
            is_smack=request.is_smack,
            person_name=request.person_name,
            dive_datetime=request.date,
            video_uuid=request.video_uuid,
            is_lineup=request.dive_code.startswith("0"),
            phase1_performance=request.phase1_performance,
            phase1_numeric=({'F': 0, 'B': 1, 'M': 2, 'G': 3, 'P': 4}.get(request.phase1_performance)
                          if request.phase1_performance else None),
            phase2_performance=request.phase2_performance,
            phase2_numeric=({'F': 0, 'B': 1, 'M': 2, 'G': 3, 'P': 4}.get(request.phase2_performance)
                          if request.phase2_performance else None),
            phase_insight=phase_insight,
            synced_at=datetime.utcnow(),
        )

        db.add(dive)
        db.commit()
        db.refresh(dive)

        # Log successful sync
        audit_logger.log_sync_single(
            video_uuid=request.video_uuid,
            dive_code=request.dive_code,
            person_name=request.person_name,
            result="success",
            dive_id=dive.id
        )

        # Log phase insight if generated
        if phase_insight:
            audit_logger.log_phase_insight_generation(
                dive_id=dive.id,
                phase1_performance=request.phase1_performance,
                phase2_performance=request.phase2_performance,
                insight=phase_insight
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
            message="Video synced successfully",
            created=True
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

        # Process each video
        for video in request.videos:
            try:
                # Check for duplicate within this batch
                if video.video_uuid in seen_uuids:
                    errors.append({
                        "video_uuid": video.video_uuid,
                        "error": "Duplicate within batch"
                    })
                    failed += 1
                    continue

                seen_uuids.add(video.video_uuid)

                # Check for duplicate in database
                stmt = select(Dive).where(Dive.video_uuid == video.video_uuid)
                result = db.execute(stmt)
                existing = result.scalar_one_or_none()

                if existing:
                    # Duplicate
                    audit_logger.log_deduplication_check(
                        video_uuid=video.video_uuid,
                        existing_dive_id=existing.id
                    )
                    errors.append({
                        "video_uuid": video.video_uuid,
                        "error": "Duplicate video"
                    })
                    failed += 1
                    continue

                # Determine composite score
                if video.phase1_performance and video.phase2_performance:
                    composite_score = PhaseValidator.infer_legacy_score(
                        video.phase1_performance,
                        video.phase2_performance
                    )
                    score_map = {'F': 0, 'B': 1, 'M': 2, 'G': 3, 'P': 4}
                    composite_numeric = score_map[composite_score]
                elif video.performance:
                    composite_score = video.performance
                    score_map = {'F': 0, 'B': 1, 'M': 2, 'G': 3, 'P': 4}
                    composite_numeric = score_map[composite_score]
                else:
                    errors.append({
                        "video_uuid": video.video_uuid,
                        "error": "Must provide 'performance' or both 'phase1_performance' and 'phase2_performance'"
                    })
                    failed += 1
                    continue

                # Generate phase insight if two-phase format
                phase_insight = None
                if video.phase1_performance and video.phase2_performance:
                    phase_insight = PhaseInsightGenerator.generate_insight(
                        video.phase1_performance,
                        video.phase2_performance
                    )

                # Get or create session for the dive date
                dive_date = video.date.date() if isinstance(video.date, datetime) else video.date
                stmt_session = select(SessionModel).where(SessionModel.date == dive_date)
                result_session = db.execute(stmt_session)
                session_record = result_session.scalar_one_or_none()

                if not session_record:
                    # Create new session for this date
                    session_record = SessionModel(
                        date=dive_date,
                        location=None,
                        notes="Auto-created from video sync"
                    )
                    db.add(session_record)
                    db.flush()  # Flush to get the session ID

                # Create dive
                dive = Dive(
                    session_id=session_record.id,
                    dive_code=video.dive_code.upper(),
                    performance=composite_score,
                    performance_numeric=composite_numeric,
                    height=video.height.lower(),
                    is_sync=video.is_sync,
                    is_smack=video.is_smack,
                    person_name=video.person_name,
                    dive_datetime=video.date,
                    video_uuid=video.video_uuid,
                    is_lineup=video.dive_code.startswith("0"),
                    phase1_performance=video.phase1_performance,
                    phase1_numeric=({'F': 0, 'B': 1, 'M': 2, 'G': 3, 'P': 4}.get(video.phase1_performance)
                                  if video.phase1_performance else None),
                    phase2_performance=video.phase2_performance,
                    phase2_numeric=({'F': 0, 'B': 1, 'M': 2, 'G': 3, 'P': 4}.get(video.phase2_performance)
                                  if video.phase2_performance else None),
                    phase_insight=phase_insight,
                    synced_at=datetime.utcnow(),
                )

                db.add(dive)
                new_dive_ids.append(dive.id)
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
        batch_id = str(uuid_module.uuid4())[:8]
        audit_logger.log_sync_batch(
            batch_id=batch_id,
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
async def stream_video(video_uuid: str, db: Session = Depends(get_db), background_tasks: BackgroundTasks = None):
    """
    Stream a video by UUID.

    Video files are stored in the macOS Photos library.
    We look up the dive record to get the video path, then stream the file.
    """
    try:
        # Find the dive with this video UUID
        stmt = select(Dive).where(Dive.video_uuid == video_uuid)
        result = db.execute(stmt)
        dive = result.scalar_one_or_none()

        if not dive:
            raise HTTPException(status_code=404, detail="Video not found")

        print(f"[videos] lookup: video_uuid={video_uuid}, video_path={getattr(dive,'video_path',None)}, video_filename={getattr(dive,'video_filename',None)}")

        # Get the video path
        video_path = dive.video_path

        if not video_path:
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
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error streaming video {video_uuid}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error serving video")


@router.get("/check/{video_uuid}")
async def check_video_availability(video_uuid: str, db: Session = Depends(get_db)):
    """
    Check if a video is available without streaming it.
    Useful for frontend to show icons only for available videos.
    """
    try:
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
