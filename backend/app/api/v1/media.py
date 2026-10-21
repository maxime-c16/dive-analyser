"""Asynchronous media cache API.

This API is intentionally parallel to legacy /videos routes. A video_uuid means
"linked Photos asset"; only a ready media_cache_entry means "playable now".
"""

from pathlib import Path
from collections import OrderedDict, defaultdict
import asyncio
import threading
from time import monotonic
from urllib.parse import quote
from datetime import date, datetime, time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.write_guard import effective_diver_scope, require_owner_for_mutation
from app.models.media import MediaAgent, MediaCacheEntry, MediaJob, RecalledMediaSource
from app.models.photos_asset import PhotosAsset
from app.models.dive import Dive
from app.schemas.media import MediaRequest, MediaRequestResponse, MediaStatusResponse, MediaStatusBatchRequest
from app.schemas.media import (
    MediaJobFailRequest,
    MediaJobFinalizeRequest,
    MediaJobFinalizeResponse,
    MediaJobHeartbeatRequest,
    MediaJobLeaseRequest,
    MediaJobLeaseResponse,
    MediaJobUploadResponse,
    MediaCleanupResponse,
    MediaPinResponse,
    RepresentativePrepareRequest,
    RepresentativeReplaceRequest,
    RepresentativeReadyRemapRequest,
    MediaAgentHeartbeatRequest,
    RecalledSourceReportRequest,
    RecallBatchPlanRequest,
    CatalogRunStartRequest,
    CatalogRunLeaseRequest,
    CatalogChunkRequest,
    CatalogCompleteRequest,
    CatalogFailRequest,
    CatalogPopulationPlanRequest,
    CatalogPopulationStartRequest,
    CatalogPopulationRolloverRequest,
    ResolutionUpgradeStartRequest,
)
from app.security import verify_api_key
from app.services.legacy_gate import require_legacy_media_user
from app.services.user_access import can_user_access_cache_entry
from app.services.media_cache import (
    get_playable_entry,
    cache_tmp_path,
    cleanup_cache,
    drain_pending_retirement_unlinks,
    finalize_cache_entry,
    playback_url,
    ready_entries_for_asset,
    ready_entry_for_key,
    sha256_file,
    set_cache_entry_pinned,
    write_upload_chunk,
    to_cache_summary,
)
from app.services.media_jobs import (
    create_or_reuse_media_job,
    fail_media_job,
    heartbeat_media_job,
    latest_active_job_for_asset,
    latest_playback_failure_for_asset,
    lease_media_jobs,
    mark_job_ready,
    mark_job_uploaded,
    to_job_summary,
)
from app.services.media_keys import build_media_key
from app.services.media_agents import (
    authenticate_media_agent,
    public_agent_status,
    report_recalled_source,
    require_leasing_agent,
    update_agent_heartbeat,
)
from app.services.media_recall import build_recall_manifest, plan_recall_batch
from app.services.offload import run_to_completion
from app.models.media_catalog import CaptionedMediaCatalog, MediaCatalogPopulationRun, MediaCatalogRun, MediaResolutionUpgradeRun
from app.models.media_backbone import MediaBlobLocation, MediaRevision
from app.config import get_settings
from app.services.media_catalog import (
    catalog_population_plan,
    catalog_population_run_summary,
    catalog_summary,
    complete_catalog_run,
    fail_catalog_run,
    ingest_catalog_chunk,
    lease_catalog_run,
    start_catalog_run,
    start_catalog_population_run,
    resume_catalog_population_run,
    arm_catalog_population_rollover,
    advance_armed_catalog_population_rollovers,
)
from app.services.media_resolution_upgrade import (
    advance_resolution_upgrade_runs,
    resolution_upgrade_summary,
    schedule_resolution_upgrade,
)
from app.services.representative_media import (
    build_representative_media_manifest,
    replacement_candidates,
    replace_representative,
    plan_ready_representative_remap,
    remap_representatives_to_ready_media,
    representative_coverage,
    representative_gallery,
)
from app.services.representative_population import (
    dry_run_tier1_population,
    population_run_summary,
    start_tier1_population,
)

router = APIRouter(prefix="/media", tags=["media"], dependencies=[Depends(require_owner_for_mutation)])


RENDITION_PREFERENCE = {
    "original": 0,
    "proxy_720p": 1,
    "proxy_360p": 2,
    "poster": 3,
}


def _agent_auth(db: Session, agent_id: str, api_key: dict, leasing: bool = False):
    try:
        if leasing:
            return require_leasing_agent(db, agent_id, api_key["key"])
        return authenticate_media_agent(db, agent_id, api_key["key"])
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


def _asset_by_uuid(db: Session, video_uuid: str) -> PhotosAsset:
    stmt = select(PhotosAsset).where(PhotosAsset.video_uuid == video_uuid)
    asset = db.execute(stmt).scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Photos asset not found")
    return asset


def _preferred_entry(entries):
    # Never fall back to the poster: the Mac agent finishes it before the
    # proxy, and a JPEG playback_url makes the <video> element fail to decode.
    playable = [entry for entry in entries if entry.rendition != "poster"]
    if not playable:
        return None
    return sorted(playable, key=lambda entry: RENDITION_PREFERENCE.get(entry.rendition, 99))[0]


def _poster_entry(entries):
    for entry in entries:
        if entry.rendition == "poster":
            return entry
    return None


_UNSET_BACKBONE = object()


def _backbone_revision_ids_bulk(db: Session, video_uuids: list[str]) -> dict[str, "int | None"]:
    """Newest verified PROD revision id per uuid, resolved in ONE query.

    Mirrors _backbone_playback_url's decision (join verified PROD locations,
    newest revision per uuid) and populates the same bounded cache so the
    single-asset path sees warm entries afterwards. Called by the batch
    thumbnail route; the graph of cached (positive AND negative) entries
    keeps the no-row case from re-querying.
    """
    settings = get_settings()
    if not (settings.user_auth_enabled and settings.b2_playback_canary_enabled):
        return {}
    now = monotonic()
    ttl = settings.media_backbone_lookup_cache_ttl_seconds
    binder = db.get_bind()

    fresh: list[str] = []
    resolved: dict[str, "int | None"] = {}
    with _backbone_id_cache_lock:
        for video_uuid in video_uuids:
            cache_key = (binder, video_uuid)
            cached = _backbone_id_cache.get(cache_key)
            if ttl > 0 and cached and now < cached[0]:
                _backbone_id_cache.move_to_end(cache_key)
                resolved[video_uuid] = cached[1]
            else:
                _backbone_id_cache.pop(cache_key, None)
                fresh.append(video_uuid)

    if fresh:
        from app.services.matchmaking import verified_original_clause
        revision_ids = {}
        for row in db.execute(
            select(MediaRevision.video_uuid, func.max(MediaRevision.id))
            .join(
                MediaBlobLocation,
                (MediaBlobLocation.blob_sha256 == MediaRevision.blob_sha256)
                & (MediaBlobLocation.environment == "prod")
                & (MediaBlobLocation.verified == True),
            )
            .where(MediaRevision.video_uuid.in_(fresh), MediaRevision.rendition_semantics != "browser_original", verified_original_clause())
            .group_by(MediaRevision.video_uuid)
        ).all():
            revision_ids[row[0]] = row[1]
        for video_uuid in fresh:
            revision_id = revision_ids.get(video_uuid)
            resolved[video_uuid] = revision_id
            with _backbone_id_cache_lock:
                if ttl > 0:
                    _backbone_id_cache[(binder, video_uuid)] = (monotonic() + ttl, revision_id)
                    while len(_backbone_id_cache) > _BACKBONE_CACHE_MAX_ENTRIES:
                        _backbone_id_cache.popitem(last=False)
    return resolved


def _iter_file_range(path: Path, start: int, end: int, chunk_size: int = 1024 * 1024):
    with path.open("rb") as file_obj:
        file_obj.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = file_obj.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _media_headers(path: Path, content_type: str, content_length: int) -> dict[str, str]:
    return {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=3600",
        "Content-Disposition": f'inline; filename="{path.name}"',
        "Content-Length": str(content_length),
        "Content-Type": content_type,
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
    }


def _x_accel_uri_for(path: Path) -> str | None:
    """Return the nginx-internal URI when the file lives in the cache root.

    Byte serving then leaves Python entirely: nginx streams range requests
    straight from disk with sendfile, Last-Modified/ETag/304-rounds included.
    Any file outside the cache root (legacy revisions, guest shares rooted
    elsewhere) keeps the previous Python streaming path.
    """
    settings = get_settings()
    if not settings.media_xaccel_enabled:
        return None
    try:
        relative = path.resolve().relative_to(Path(settings.media_cache_root).resolve())
    except ValueError:
        return None
    return settings.media_xaccel_prefix + quote(str(relative), safe="/")


def _serve_media_file(path: Path, content_type: str, request: Request, head_only: bool = False):
    file_size = path.stat().st_size
    headers = _media_headers(path, content_type, file_size)
    redirect_uri = None if head_only else _x_accel_uri_for(path)

    if redirect_uri is not None:
        # The body is replaced by the file nginx serves, so this response
        # must NOT carry Content-Length (its real body is empty): a declared
        # length made uvicorn/h11 abort every accelerated response with
        # "Response content shorter than Content-Length" in production, even
        # with the default 0. A streamed body sets no length; nginx sets
        # length and ranges itself from the file; identity headers stay.
        headers.pop("Content-Length", None)
        headers["X-Accel-Redirect"] = redirect_uri
        return StreamingResponse(iter(()), status_code=status.HTTP_200_OK, headers=headers)

    range_header = request.headers.get("range")

    if not range_header:
        if head_only:
            return Response(status_code=status.HTTP_200_OK, headers=headers)
        return StreamingResponse(
            _iter_file_range(path, 0, file_size - 1),
            status_code=status.HTTP_200_OK,
            media_type=content_type,
            headers=headers,
        )

    if not range_header.startswith("bytes="):
        raise HTTPException(status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE)

    start_text, _, end_text = range_header.removeprefix("bytes=").partition("-")
    try:
        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else file_size - 1
        else:
            suffix_length = int(end_text)
            start = max(file_size - suffix_length, 0)
            end = file_size - 1
    except ValueError:
        raise HTTPException(status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE)

    if start < 0 or end < start or start >= file_size:
        raise HTTPException(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    end = min(end, file_size - 1)
    range_length = end - start + 1
    headers.update(
        {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(range_length),
        }
    )
    if head_only:
        return Response(status_code=status.HTTP_206_PARTIAL_CONTENT, headers=headers)
    return StreamingResponse(
        _iter_file_range(path, start, end),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=content_type,
        headers=headers,
    )


# Bound both positive and negative lookups so new verified revisions become
# visible across workers without a restart. Database sessions are closed by
# get_db; this cache only saves repeated lookup queries.
# Library thumbnail status batches cap how many assets one
# POST /media/status/batch may resolve (see get_media_status_batch).
MAX_STATUS_BATCH = 100

_BACKBONE_CACHE_MAX_ENTRIES = 1024
_backbone_id_cache: OrderedDict = OrderedDict()
_backbone_id_cache_lock = threading.Lock()


def _backbone_playback_url(db: Session, video_uuid: str) -> "str | None":
    """Return the B2 playback URL for the most-recent verified PROD backbone
    revision of *video_uuid*, or None if no such revision exists.

    Both missing and available revisions are cached for a bounded interval.
    Playback still enforces current authorization and verified storage state.
    """
    settings = get_settings()
    if not (settings.user_auth_enabled and settings.b2_playback_canary_enabled):
        return None

    cache_key = (db.get_bind(), video_uuid)
    now = monotonic()
    ttl = settings.media_backbone_lookup_cache_ttl_seconds
    # Including database identity prevents results leaking between databases.
    with _backbone_id_cache_lock:
        cached = _backbone_id_cache.get(cache_key)
        if ttl > 0 and cached and now < cached[0]:
            _backbone_id_cache.move_to_end(cache_key)
            revision_id = cached[1]
            return f"/api/v1/media/revisions/{revision_id}/play" if revision_id is not None else None
        _backbone_id_cache.pop(cache_key, None)

    # Slow path: query the DB once, then cache the result
    from app.services.matchmaking import verified_original_clause
    row = db.execute(
        select(MediaRevision.id)
        .join(
            MediaBlobLocation,
            (MediaBlobLocation.blob_sha256 == MediaRevision.blob_sha256)
            & (MediaBlobLocation.environment == "prod")
            & (MediaBlobLocation.verified == True),
        )
        .where(MediaRevision.video_uuid == video_uuid, MediaRevision.rendition_semantics != "browser_original", verified_original_clause())
        .order_by(MediaRevision.id.desc())
        .limit(1)
    ).scalar_one_or_none()

    with _backbone_id_cache_lock:
        if ttl > 0:
            _backbone_id_cache[cache_key] = (monotonic() + ttl, row)
            _backbone_id_cache.move_to_end(cache_key)
            while len(_backbone_id_cache) > _BACKBONE_CACHE_MAX_ENTRIES:
                _backbone_id_cache.popitem(last=False)

    return f"/api/v1/media/revisions/{row}/play" if row is not None else None


def _status_for_asset(db: Session, asset: PhotosAsset) -> MediaStatusResponse:
    entries = ready_entries_for_asset(db, asset.id)
    preferred = _preferred_entry(entries)
    poster = _poster_entry(entries)
    job = latest_active_job_for_asset(db, asset.id)

    # Original discovery is independent of preview existence.
    backbone_url = _backbone_playback_url(db, asset.video_uuid)
    local_original = next((entry for entry in entries if entry.rendition == "original"), None)
    full_quality = playback_url(local_original.id) if local_original else backbone_url
    preview = next((entry for rendition in ("proxy_720p", "proxy_360p")
                    for entry in entries if entry.rendition == rendition), None)
    backbone_url = full_quality
    if not backbone_url and not preferred and not job:
        job = latest_playback_failure_for_asset(db, asset.id)
    if backbone_url:
        status_value = "ready"
        final_playback_url = backbone_url
    elif preferred:
        status_value = "ready"
        final_playback_url = playback_url(preferred.id)
    elif job:
        status_value = job.status
        final_playback_url = None
    else:
        status_value = "missing"
        final_playback_url = None

    return MediaStatusResponse(
        video_uuid=asset.video_uuid,
        status=status_value,
        can_request=True,
        preferred_rendition="original" if backbone_url else preferred.rendition if preferred else None,
        available_renditions=sorted({entry.rendition for entry in entries} | ({"original"} if full_quality else set())),
        playback_url=final_playback_url,
        poster_url=playback_url(poster.id) if poster else None,
        full_quality_url=full_quality,
        preview_url=playback_url(preview.id) if preview else None,
        cache_entries=[to_cache_summary(entry) for entry in entries],
        job=to_job_summary(job),
        last_mac_seen_at=asset.last_seen_on_mac_at,
    )


def _media_error_code(error: str | None) -> str | None:
    if not error:
        return None
    if "permission_required" in error:
        return "permission_required"
    if "photos_access_denied" in error:
        return "photos_access_denied"
    if "osxphotos_export_timeout" in error:
        return "osxphotos_export_timeout"
    if "materialization_only_placeholders" in error or "materialized_video_not_found" in error:
        return "materialization_only_placeholders"
    if "osxphotos_export_failed" in error:
        return "osxphotos_export_failed"
    return "media_unavailable"


def _photos_access_status_from_jobs(db: Session) -> dict:
    latest_error_job = db.execute(
        select(MediaJob)
        .where(MediaJob.last_error.isnot(None))
        .order_by(MediaJob.updated_at.desc(), MediaJob.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    latest_ready_job = db.execute(
        select(MediaJob)
        .where(MediaJob.status == "ready")
        .order_by(MediaJob.updated_at.desc(), MediaJob.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    error_code = _media_error_code(latest_error_job.last_error if latest_error_job else None)
    if error_code == "permission_required":
        access_status = "permission_required"
    elif error_code == "photos_access_denied":
        access_status = "denied"
    elif latest_ready_job:
        access_status = "ok"
    else:
        access_status = "unknown"

    return {
        "photos_access_status": access_status,
        "last_successful_media_job_at": latest_ready_job.updated_at if latest_ready_job else None,
        "last_permission_error_at": latest_error_job.updated_at if error_code in {"permission_required", "photos_access_denied"} and latest_error_job else None,
        "last_materialization_success_at": latest_ready_job.updated_at if latest_ready_job else None,
        "last_error_code": error_code,
        "last_error_at": latest_error_job.updated_at if latest_error_job else None,
        "generated_at": datetime.utcnow(),
        "source": "media_job_history",
    }


@router.get("/representative-manifest")
async def representative_media_manifest(
    request: Request,
    limit_codes: int | None = Query(None, ge=1, le=500),
    include_sync_codes: bool = False,
    diver_scope: str = Query("self", pattern="^(self|all)$"),
    diver_id: int | None = None,
    db: Session = Depends(get_db),
):
    """Build a reviewed Tier 1 media-readiness manifest without creating jobs."""
    diver_scope = effective_diver_scope(request, db, diver_scope)
    return build_representative_media_manifest(
        db,
        limit_codes=limit_codes,
        include_sync_codes=include_sync_codes,
        diver_scope="selected" if diver_id else diver_scope,
        diver_id=diver_id,
    )


@router.get("/representatives")
async def representatives_gallery(
    request: Request,
    dive_code: str | None = None,
    readiness: str | None = None,
    selection_band: str | None = None,
    height: str | None = None,
    diver_scope: str = Query("self", pattern="^(self|all)$"),
    diver_id: int | None = None,
    is_sync: bool | None = None,
    has_proxy: bool | None = None,
    has_poster: bool | None = None,
    db: Session = Depends(get_db),
):
    """Return read-only representative media gallery state."""
    diver_scope = effective_diver_scope(request, db, diver_scope)
    return representative_gallery(
        db,
        dive_code=dive_code,
        readiness=readiness,
        selection_band=selection_band,
        height=height,
        diver_scope="selected" if diver_id else diver_scope,
        diver_id=diver_id,
        is_sync=is_sync,
        has_proxy=has_proxy,
        has_poster=has_poster,
    )


@router.get("/representatives/coverage")
async def representatives_coverage(
    request: Request,
    diver_scope: str = Query("self", pattern="^(self|all)$"),
    diver_id: int | None = None,
    db: Session = Depends(get_db),
):
    """Return read-only representative coverage and zero-ready audit state."""
    diver_scope = effective_diver_scope(request, db, diver_scope)
    return representative_coverage(db, diver_scope="selected" if diver_id else diver_scope, diver_id=diver_id)


@router.get("/mac/status")
async def mac_media_status(
    db: Session = Depends(get_db),
):
    """Return inferred Mac Photos/media operational status without creating jobs."""
    return _photos_access_status_from_jobs(db)


@router.get("/representatives/{dive_code}/{role}/replacement-candidates")
async def get_representative_replacement_candidates(
    dive_code: str,
    role: str,
    request: Request,
    diver_scope: str = Query("self", pattern="^(self|all)$"),
    diver_id: int | None = None,
    db: Session = Depends(get_db),
):
    """Return at most five bounded replacement candidates without creating jobs."""
    diver_scope = effective_diver_scope(request, db, diver_scope)
    return {
        "dive_code": dive_code.upper(),
        "role": "median" if role == "typical" else role,
        "candidates": replacement_candidates(db, dive_code, role, limit=5, diver_scope="selected" if diver_id else diver_scope, diver_id=diver_id),
    }


@router.post("/representatives/{dive_code}/{role}/replace")
async def replace_representative_attempt(
    dive_code: str,
    role: str,
    request: RepresentativeReplaceRequest,
    db: Session = Depends(get_db),
):
    """Replace one representative role with an explicit bounded candidate."""
    try:
        result = replace_representative(
            db,
            dive_code=dive_code,
            role=role,
            replacement_dive_id=request.replacement_dive_id,
            prepare=request.prepare,
            renditions=request.renditions,
            diver_scope="selected" if request.diver_id else request.diver_scope,
            diver_id=request.diver_id,
        )
        db.commit()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/representatives/remap-ready")
async def remap_representatives_ready_media(
    request: RepresentativeReadyRemapRequest,
    db: Session = Depends(get_db),
):
    """Plan or apply a bounded, cache-only representative remap.

    No media jobs are requested here: candidates must already have both
    requested durable renditions ready.
    """
    scope = "selected" if request.diver_id else request.diver_scope
    kwargs = {
        "max_changes": request.max_changes,
        "diver_scope": scope,
        "diver_id": request.diver_id,
    }
    if request.dry_run:
        return {
            "dry_run": True,
            "proposals": plan_ready_representative_remap(db, **kwargs),
            "jobs_created": 0,
        }
    result = remap_representatives_to_ready_media(db, **kwargs)
    db.commit()
    return {"dry_run": False, **result}


@router.post("/representative-manifest/prepare")
async def prepare_representative_media(
    request: RepresentativePrepareRequest,
    db: Session = Depends(get_db),
    api_key: dict = Depends(verify_api_key),
):
    """Dry-run or start a bounded Tier 1 representative media population run."""
    try:
        if request.dry_run:
            return dry_run_tier1_population(db, tier=request.tier, renditions=request.renditions)
        run = start_tier1_population(db, tier=request.tier, renditions=request.renditions)
        db.commit()
        return population_run_summary(db, run.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/representative-manifest/runs/{run_id}")
async def get_representative_population_run(
    run_id: int,
    db: Session = Depends(get_db),
):
    """Return current status for a representative media population run."""
    try:
        summary = population_run_summary(db, run_id)
        db.commit()
        return summary
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Population run not found") from exc


@router.get("/agents")
async def list_media_agents(db: Session = Depends(get_db)):
    """Return public operational state for allow-listed media agents."""
    agents = db.execute(select(MediaAgent).order_by(MediaAgent.id)).scalars().all()
    return {"agents": [public_agent_status(agent) for agent in agents], "read_only": True}


def _advance_background_media_work(db: Session) -> None:
    """Advance agent-side asynchronous media workflows (catalog rollovers,
    resolution upgrades). The upgrade path verifies 720p artifacts with a
    full-file SHA-256, so the work runs on a worker thread instead of the
    event loop, and the caller commits inside the same cancellation-safe
    unit. Legacy 360p files are retained in this transition (no retirement:
    the item is marked upgraded, row and file kept); the retirement-queue
    drain stays wired but queues nothing, so a rolled-back transaction
    trivially keeps rows and files together."""
    advance_armed_catalog_population_rollovers(db)
    advance_resolution_upgrade_runs(db)
    db.commit()
    drain_pending_retirement_unlinks(db)


@router.post("/agents/heartbeat")
async def media_agent_heartbeat(
    request: MediaAgentHeartbeatRequest,
    db: Session = Depends(get_db),
    api_key: dict = Depends(verify_api_key),
):
    # Heartbeat bookkeeping, background advancement and the commit form one
    # cancellation-safe unit: cancelling the response mid-advancement must
    # not strand a half-run or an uncommitted row behind session teardown.
    def _apply_and_advance():
        agent = update_agent_heartbeat(db, request, api_key["key"])
        _advance_background_media_work(db)
        # Attribute access lazily reloads the expired row inside this worker.
        return public_agent_status(agent)

    try:
        status_payload = await run_to_completion(asyncio.to_thread(_apply_and_advance))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return status_payload


@router.post("/agents/sources/report")
async def report_media_source(
    request: RecalledSourceReportRequest,
    db: Session = Depends(get_db),
    api_key: dict = Depends(verify_api_key),
):
    try:
        source = report_recalled_source(db, request, api_key["key"])
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    db.commit()
    return {
        "source_id": source.id,
        "video_uuid": source.video_uuid,
        "agent_id": source.agent_id,
        "retention_class": source.retention_class,
        "active": source.active,
    }


@router.get("/agents/sources/{video_uuid}")
async def recalled_source_status(video_uuid: str, db: Session = Depends(get_db)):
    """Return source readiness without disclosing Mac filesystem paths."""
    sources = db.execute(
        select(RecalledMediaSource).where(
            RecalledMediaSource.video_uuid == video_uuid,
            RecalledMediaSource.active.is_(True),
        ).order_by(RecalledMediaSource.validated_at.desc())
    ).scalars().all()
    return {
        "video_uuid": video_uuid,
        "available": bool(sources),
        "sources": [
            {
                "id": source.id,
                "agent_id": source.agent_id,
                "source_kind": source.source_kind,
                "size_bytes": source.size_bytes,
                "checksum_sha256": source.checksum_sha256,
                "retention_class": source.retention_class,
                "validated_at": source.validated_at,
                "last_seen_at": source.last_seen_at,
            }
            for source in sources
        ],
        "read_only": True,
    }


@router.get("/recall-manifest")
async def recall_manifest(
    limit: int = Query(25, ge=1, le=100),
    priority_class: str | None = None,
    dive_code: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    representative_role: str | None = Query(None, pattern="^(low|median|high)$"),
    db: Session = Depends(get_db),
):
    """Return a bounded recall plan; never creates jobs or downloads."""
    return build_recall_manifest(
        db,
        limit=limit,
        priority_class=priority_class,
        dive_code=dive_code,
        date_from=datetime.combine(date_from, time.min) if date_from else None,
        date_to=datetime.combine(date_to, time.max) if date_to else None,
        representative_role=representative_role,
    )


@router.post("/recall-batches/plan")
async def recall_batch_plan(request: RecallBatchPlanRequest, db: Session = Depends(get_db)):
    """Calculate a bounded internal-storage plan without creating work."""
    if not request.dry_run:
        raise HTTPException(status_code=422, detail="recall_batch_execution_not_enabled")
    return plan_recall_batch(db, priority=request.priority, limit=request.limit)


def _catalog_run_public(run: MediaCatalogRun) -> dict:
    return {
        "id": run.id,
        "agent_id": run.agent_id,
        "status": run.status,
        "catalog_revision": run.catalog_revision,
        "checkpoint": run.checkpoint,
        "observed_count": run.observed_count,
        "eligible_count": run.eligible_count,
        "excluded_count": run.excluded_count,
        "error_count": run.error_count,
        "photos_library_bytes_start": run.photos_library_bytes_start,
        "photos_library_bytes_end": run.photos_library_bytes_end,
        "free_bytes_start": run.free_bytes_start,
        "free_bytes_end": run.free_bytes_end,
        "pause_reason": run.pause_reason,
        "last_error": run.last_error,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "created_at": run.created_at,
    }


@router.post("/catalog/runs")
async def create_catalog_run(request: CatalogRunStartRequest, db: Session = Depends(get_db)):
    """Request one full read-only catalog pass; creates no media jobs."""
    try:
        run = start_catalog_run(db, request.agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    db.refresh(run)
    return _catalog_run_public(run)


@router.get("/catalog/runs/latest")
async def latest_catalog_run(db: Session = Depends(get_db)):
    run = db.execute(select(MediaCatalogRun).order_by(MediaCatalogRun.id.desc())).scalars().first()
    return _catalog_run_public(run) if run else None


@router.get("/catalog/runs/{run_id}")
async def catalog_run_status(run_id: int, db: Session = Depends(get_db)):
    run = db.get(MediaCatalogRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="catalog_run_not_found")
    return _catalog_run_public(run)


@router.post("/catalog/runs/lease")
async def catalog_run_lease(request: CatalogRunLeaseRequest, api_key: dict = Depends(verify_api_key), db: Session = Depends(get_db)):
    _agent_auth(db, request.agent_id, api_key)
    run = lease_catalog_run(db, request.agent_id)
    db.commit()
    return {"run": _catalog_run_public(run) if run else None}


@router.post("/catalog/runs/{run_id}/chunks")
async def catalog_run_chunk(run_id: int, request: CatalogChunkRequest, api_key: dict = Depends(verify_api_key), db: Session = Depends(get_db)):
    _agent_auth(db, request.agent_id, api_key)
    run = db.get(MediaCatalogRun, run_id)
    if not run or run.agent_id != request.agent_id:
        raise HTTPException(status_code=404, detail="catalog_run_not_found")
    try:
        result = ingest_catalog_chunk(db, run, [record.model_dump() for record in request.records], request.checkpoint)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return result


@router.post("/catalog/runs/{run_id}/complete")
async def catalog_run_complete(run_id: int, request: CatalogCompleteRequest, api_key: dict = Depends(verify_api_key), db: Session = Depends(get_db)):
    _agent_auth(db, request.agent_id, api_key)
    run = db.get(MediaCatalogRun, run_id)
    if not run or run.agent_id != request.agent_id:
        raise HTTPException(status_code=404, detail="catalog_run_not_found")
    try:
        complete_catalog_run(db, run, request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    db.refresh(run)
    return _catalog_run_public(run)


@router.post("/catalog/runs/{run_id}/fail")
async def catalog_run_fail(run_id: int, request: CatalogFailRequest, api_key: dict = Depends(verify_api_key), db: Session = Depends(get_db)):
    _agent_auth(db, request.agent_id, api_key)
    run = db.get(MediaCatalogRun, run_id)
    if not run or run.agent_id != request.agent_id:
        raise HTTPException(status_code=404, detail="catalog_run_not_found")
    fail_catalog_run(db, run, request.error, paused=request.paused)
    db.commit()
    return _catalog_run_public(run)


@router.get("/catalog/summary")
async def get_catalog_summary(revision: int | None = None, db: Session = Depends(get_db)):
    return catalog_summary(db, revision)


@router.get("/catalog/items")
async def get_catalog_items(
    eligibility: str | None = None,
    exclusion_code: str | None = None,
    limit: int = Query(100, ge=1, le=250),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    revision = db.execute(select(func.max(CaptionedMediaCatalog.catalog_revision))).scalar_one_or_none()
    stmt = select(CaptionedMediaCatalog).where(CaptionedMediaCatalog.catalog_revision == revision)
    if eligibility:
        stmt = stmt.where(CaptionedMediaCatalog.eligibility == eligibility)
    if exclusion_code:
        stmt = stmt.where(CaptionedMediaCatalog.exclusion_code == exclusion_code)
    rows = db.execute(stmt.order_by(CaptionedMediaCatalog.captured_at.desc(), CaptionedMediaCatalog.id).offset(offset).limit(limit)).scalars().all()
    return {"read_only": True, "revision": revision, "offset": offset, "count": len(rows), "items": [
        {"id": row.id, "canonical_video_uuid": row.canonical_video_uuid, "agent_local_uuid": row.agent_local_uuid,
         "caption": row.raw_caption, "dive_code": row.canonical_dive_code, "captured_at": row.captured_at,
         "eligibility": row.eligibility, "exclusion_code": row.exclusion_code, "media_state": row.media_state,
         "poster_state": row.poster_state, "proxy_state": row.proxy_state, "photos_local_state": row.photos_local_state,
         "representative_role": row.representative_role, "last_error_code": row.last_error_code}
        for row in rows]}


@router.post("/catalog/population-plan")
async def population_plan(request: CatalogPopulationPlanRequest, db: Session = Depends(get_db)):
    if not request.dry_run:
        raise HTTPException(status_code=422, detail="catalog_population_execution_requires_staged_run")
    try:
        return catalog_population_plan(db, scope=request.scope)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/catalog/population-runs")
async def start_population_run(request: CatalogPopulationStartRequest, db: Session = Depends(get_db)):
    try:
        run = start_catalog_population_run(
            db, limit=request.limit, stage=request.stage,
            catalog_item_ids=request.catalog_item_ids or None,
        )
        result = catalog_population_run_summary(db, run)
        db.commit()
        return result
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/catalog/population-runs/{run_id}")
async def get_population_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(MediaCatalogPopulationRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="catalog_population_run_not_found")
    result = catalog_population_run_summary(db, run)
    db.commit()
    return result


@router.post("/catalog/population-runs/{run_id}/resume")
async def resume_population_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(MediaCatalogPopulationRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="catalog_population_run_not_found")
    try:
        resume_catalog_population_run(db, run)
        result = catalog_population_run_summary(db, run)
        db.commit()
        return result
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/catalog/population-runs/{run_id}/arm-rolling-successor")
async def arm_population_rolling_successor(
    run_id: int,
    request: CatalogPopulationRolloverRequest,
    db: Session = Depends(get_db),
):
    """Arm a bounded, checkpointed successor chain after the current run completes."""
    run = db.get(MediaCatalogPopulationRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="catalog_population_run_not_found")
    try:
        arm_catalog_population_rollover(db, run, batch_limit=request.batch_limit)
        db.commit()
        return catalog_population_run_summary(db, run)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/resolution-upgrades")
async def schedule_proxy_resolution_upgrade(
    request: ResolutionUpgradeStartRequest,
    db: Session = Depends(get_db),
):
    """Schedule a sequential 360p-to-720p replacement run."""
    try:
        run = schedule_resolution_upgrade(
            db,
            starts_after_population_run_id=request.starts_after_population_run_id,
            scope=request.scope,
        )
        db.commit()
        return resolution_upgrade_summary(db, run)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/resolution-upgrades/{run_id}")
async def get_proxy_resolution_upgrade(run_id: int, db: Session = Depends(get_db)):
    run = db.get(MediaResolutionUpgradeRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="resolution_upgrade_run_not_found")
    await run_to_completion(asyncio.to_thread(_advance_background_media_work, db))
    return resolution_upgrade_summary(db, run)


@router.get("/{video_uuid}/status")
async def get_media_status(
    video_uuid: str,
    db: Session = Depends(get_db),
) -> MediaStatusResponse:
    """Return cache/job status for a Photos asset UUID."""
    asset = _asset_by_uuid(db, video_uuid)
    return _status_for_asset(db, asset)


def _web_preview_entry(entries):
    """First browser-compatible cached preview, 720p before legacy 360p.

    The Library grid may only ever render these cheap local entries: never
    the camera original and never a B2 revision URL (which would mint a
    grant, a B2 HEAD, a presigned 302 and HEVC range traffic per tile, and
    render black on browsers without HEVC). No media conversion happens
    here; this is a selection over already-ready entries.
    """
    for rendition in ("proxy_720p", "proxy_360p"):
        for entry in entries:
            if entry.rendition == rendition:
                return entry
    return None


def _thumbnail_status_for_entries(
    db: Session, video_uuid: str, entries: list, backbone_url: "str | None | object" = _UNSET_BACKBONE,
) -> dict:
    """Compact per-asset thumbnail payload for the Library grid.

    Poster first, then the ready web preview, else nothing: the grid shows
    a placeholder rather than loading the camera original. ``backbone_url``
    is accepted for call compatibility but deliberately ignored — the grid
    must never expose a B2 revision URL, so no per-tile grant can occur.
    The full player status (``_status_for_asset``) keeps the explicit
    original fallback; only the tile payload is bounded here.
    """
    poster = _poster_entry(entries)
    preview = _web_preview_entry(entries)
    playback = playback_url(preview.id) if preview else None
    status_value = "ready" if (poster or preview) else "missing"

    return {
        "video_uuid": video_uuid,
        "status": status_value,
        "poster_url": playback_url(poster.id) if poster else None,
        "playback_url": playback,
    }


@router.post("/status/batch")
async def get_media_status_batch(
    request: MediaStatusBatchRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Status summary for many library thumbnails in one request.

    Tile payload: poster plus the ready web preview only — never the
    camera original and never a B2 revision URL, so a grid scroll mints
    no playback grants and downloads no original bytes. The full player
    status (GET /{video_uuid}/status) keeps the explicit original
    fallback. Bounded to
    MAX_STATUS_BATCH uuids so one grid cannot fan a request out into a
    corpus scan; larger libraries page naturally through the Intersection
    Observer visibility gate.
    """
    seen: list[str] = []
    for video_uuid in request.video_uuids:
        if video_uuid and video_uuid not in seen:
            seen.append(video_uuid)
    seen = seen[:MAX_STATUS_BATCH]
    if db.info.get("member_access"):
        # Filter before consulting the process-wide backbone cache: a revision
        # cached by its owner must never identify a private clip to a member.
        allowed = set(db.execute(select(Dive.video_uuid).where(Dive.video_uuid.in_(seen))).scalars())
        seen = [video_uuid for video_uuid in seen if video_uuid in allowed]

    entries_by_asset: dict[int, list] = defaultdict(list)
    uuid_by_asset: dict[int, str] = {}
    if seen:
        assets = db.execute(
            select(PhotosAsset).where(PhotosAsset.video_uuid.in_(seen))
        ).scalars().all()
        asset_ids = [asset.id for asset in assets]
        uuid_by_asset = {asset.id: asset.video_uuid for asset in assets}
        if asset_ids:
            rows = db.execute(
                select(MediaCacheEntry).where(
                    MediaCacheEntry.photos_asset_id.in_(asset_ids),
                    MediaCacheEntry.status == "ready",
                ).order_by(MediaCacheEntry.created_at.desc())
            ).scalars().all()
            for row in rows:
                entries_by_asset[row.photos_asset_id].append(row)

    # No B2 revision lookup on the tile path: thumbnails never expose an
    # original URL, so no grant, HEAD, 302 or Range traffic can originate
    # from a grid scroll. Unknown uuids still answer (missing), never 404.
    result: dict[str, dict] = {}
    for video_uuid in seen:
        asset_id = next((aid for aid, uid in uuid_by_asset.items() if uid == video_uuid), None)
        entries = entries_by_asset.get(asset_id, []) if asset_id else []
        result[video_uuid] = _thumbnail_status_for_entries(db, video_uuid, entries, None)
    return result


@router.post("/{video_uuid}/request")
async def request_media(
    video_uuid: str,
    request: MediaRequest,
    db: Session = Depends(get_db),
) -> MediaRequestResponse:
    """Create or reuse a media job for a specific rendition."""
    asset = _asset_by_uuid(db, video_uuid)
    media_key = build_media_key(asset.video_uuid, request.rendition)
    entry = ready_entry_for_key(db, media_key)
    if entry:
        status_response = _status_for_asset(db, asset)
        return MediaRequestResponse(
            **status_response.model_dump(),
            media_key=media_key,
            created_job=False,
            reused_job=False,
            cache_hit=True,
        )

    media_key, job, created = create_or_reuse_media_job(
        db=db,
        asset=asset,
        rendition=request.rendition,
        reason=request.reason,
    )
    db.commit()
    db.refresh(job)

    status_response = _status_for_asset(db, asset)
    return MediaRequestResponse(
        **status_response.model_dump(),
        media_key=media_key,
        created_job=created,
        reused_job=not created,
        cache_hit=False,
    )


@router.api_route("/cache/{entry_id}/play", methods=["GET", "HEAD"])
async def play_cached_media(
    entry_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Serve a verified cached media artifact.

    P6 legacy IDOR closure: while USER_AUTH_ENABLED the route requires a
    live session and central OWNER authorization (via the deterministic
    cache-entry → Photos asset → dive → diver chain) BEFORE any bytes are
    served. With auth disabled the legacy behavior is preserved (rollback).
    """
    entry = get_playable_entry(db, entry_id)
    user = require_legacy_media_user(db, request)
    if user is not None:
        decision = can_user_access_cache_entry(db, user, entry)
        if not decision.allowed:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    media_path = Path(entry.storage_path)
    return _serve_media_file(
        media_path,
        entry.content_type or "application/octet-stream",
        request,
        head_only=request.method == "HEAD",
    )


@router.post("/events/viewed")
async def mark_media_viewed(
    request: Request,
    entry_id: int,
    db: Session = Depends(get_db),
):
    """Track a cache entry access without streaming the file."""
    entry = get_playable_entry(db, entry_id)
    user = require_legacy_media_user(db, request)
    if user is not None:
        decision = can_user_access_cache_entry(db, user, entry)
        if not decision.allowed:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return {
        "entry_id": entry.id,
        "last_accessed_at": entry.last_accessed_at,
    }


@router.post("/jobs/lease")
async def lease_jobs(
    request: MediaJobLeaseRequest,
    db: Session = Depends(get_db),
    api_key: dict = Depends(verify_api_key),
) -> MediaJobLeaseResponse:
    """Lease queued media jobs for a Mac agent."""
    agent = _agent_auth(db, request.agent_id, api_key, leasing=True)
    # Two concurrent assets are allowed only for the Mac canary. The agent and
    # service both keep poster/proxy work for a single source serialized.
    if request.max_jobs > 2:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="media_max_jobs_must_not_exceed_two")
    if not set(request.capabilities).issubset(set(agent.capabilities or [])):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="media_agent_capability_mismatch")
    jobs = lease_media_jobs(db, request)
    db.commit()
    return MediaJobLeaseResponse(jobs=jobs)


@router.post("/jobs/{job_id}/heartbeat")
async def heartbeat_job(
    job_id: int,
    request: MediaJobHeartbeatRequest,
    db: Session = Depends(get_db),
    api_key: dict = Depends(verify_api_key),
):
    """Update progress for a leased media job."""
    try:
        _agent_auth(db, request.agent_id, api_key)
        job = heartbeat_media_job(db, job_id, request.agent_id, request.status, request.progress)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media job not found")
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    db.commit()
    return {"job_id": job.id, "status": job.status, "progress": job.progress}


@router.post("/jobs/{job_id}/fail")
async def fail_job(
    job_id: int,
    request: MediaJobFailRequest,
    db: Session = Depends(get_db),
    api_key: dict = Depends(verify_api_key),
):
    """Mark a leased media job failed or unavailable."""
    try:
        _agent_auth(db, request.agent_id, api_key)
        job = fail_media_job(db, job_id, request.agent_id, request.error, request.status)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media job not found")
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    db.commit()
    return {"job_id": job.id, "status": job.status, "last_error": job.last_error}


@router.post("/jobs/{job_id}/upload")
async def upload_job_artifact(
    job_id: int,
    agent_id: str = Form(...),
    checksum_sha256: str = Form(...),
    size_bytes: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    api_key: dict = Depends(verify_api_key),
) -> MediaJobUploadResponse:
    """Upload a completed artifact for a leased media job."""
    _agent_auth(db, agent_id, api_key)
    job = db.get(MediaJob, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media job not found")
    if job.status not in {"claimed", "exporting", "transcoding", "uploading", "verifying"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Job cannot upload from status {job.status}")
    if job.claimed_by != agent_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="media_job_lease_owner_mismatch")

    tmp_path = cache_tmp_path(job)
    tmp_path.unlink(missing_ok=True)
    actual_size = 0
    try:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            actual_size += len(chunk)
            write_upload_chunk(tmp_path, chunk)
    finally:
        await file.close()

    if actual_size != size_bytes:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded size mismatch")

    # Full-artifact reads belong on a worker thread: hashing gigabyte-scale
    # proxies on the loop stalls every concurrent request. Verify + accept
    # (hash, mark uploaded, commit) is one cancellation-safe unit so a
    # cancelled upload never leaves an unverified-accepted artifact or a
    # half transaction behind the session teardown.
    def _verify_and_accept():
        actual_checksum = sha256_file(tmp_path)
        if actual_checksum != checksum_sha256:
            tmp_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded checksum mismatch",
            )
        accepted = mark_job_uploaded(db, job_id, agent_id, str(tmp_path), checksum_sha256, size_bytes)
        db.commit()
        return accepted

    job = await run_to_completion(asyncio.to_thread(_verify_and_accept))
    return MediaJobUploadResponse(
        job_id=job.id,
        status=job.status,
        upload_tmp_path=job.upload_tmp_path,
        size_bytes=size_bytes,
        checksum_sha256=checksum_sha256,
    )


@router.post("/jobs/{job_id}/finalize")
async def finalize_job_artifact(
    job_id: int,
    request: MediaJobFinalizeRequest,
    db: Session = Depends(get_db),
    api_key: dict = Depends(verify_api_key),
) -> MediaJobFinalizeResponse:
    """Verify and promote an uploaded job artifact into the media cache."""
    _agent_auth(db, request.agent_id, api_key)
    job = db.get(MediaJob, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media job not found")
    if job.status != "verifying":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Job cannot finalize from status {job.status}")
    if job.claimed_by != request.agent_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="media_job_lease_owner_mismatch")

    # Verify + promote touches the filesystem (full-file hash, move, chmod).
    # The whole semantic unit - verify, promote, mark ready, commit - runs
    # to completion on a worker even when this handler is cancelled mid-
    # way: an abandoned finalize must never leave the job in `verifying`
    # with its temp file already moved, nor half a transaction behind the
    # session teardown.
    def _finalize_and_commit():
        entry = finalize_cache_entry(
            db=db,
            job=job,
            checksum_sha256=request.checksum_sha256,
            size_bytes=request.size_bytes,
            content_type=request.content_type,
        )
        mark_job_ready(db, job)
        db.commit()
        return entry

    entry = await run_to_completion(asyncio.to_thread(_finalize_and_commit))
    db.refresh(entry)
    return MediaJobFinalizeResponse(
        job_id=job.id,
        status=job.status,
        cache_entry_id=entry.id,
        playback_url=playback_url(entry.id),
    )


@router.post("/cache/{entry_id}/pin")
async def pin_cache_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    api_key: dict = Depends(verify_api_key),
) -> MediaPinResponse:
    """Prevent a cache entry from eviction."""
    entry = set_cache_entry_pinned(db, entry_id, True)
    db.commit()
    return MediaPinResponse(entry_id=entry.id, pinned=entry.pinned)


@router.post("/cache/{entry_id}/unpin")
async def unpin_cache_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    api_key: dict = Depends(verify_api_key),
) -> MediaPinResponse:
    """Allow a cache entry to be evicted."""
    entry = set_cache_entry_pinned(db, entry_id, False)
    db.commit()
    return MediaPinResponse(entry_id=entry.id, pinned=entry.pinned)


@router.post("/cache/cleanup")
async def cleanup_media_cache(
    max_bytes: int | None = None,
    db: Session = Depends(get_db),
    api_key: dict = Depends(verify_api_key),
) -> MediaCleanupResponse:
    """Remove expired/unpinned media and optionally trim to max bytes."""
    removed_entries, removed_bytes, remaining_bytes = cleanup_cache(db, max_bytes)
    db.commit()
    return MediaCleanupResponse(
        removed_entries=removed_entries,
        removed_bytes=removed_bytes,
        remaining_bytes=remaining_bytes,
    )
