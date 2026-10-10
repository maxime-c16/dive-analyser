"""Authenticated video downloads reuse existing storage; no archives or jobs."""
import asyncio
import mimetypes
from pathlib import Path
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from starlette.background import BackgroundTask
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.api.v1.media import _serve_media_file
from app.api.v1.media_playback import _resolve_verified_prod_location, DENY_STORAGE_AMBIGUOUS, _secure_headers
from app.config import get_settings
from app.database import get_db
from app.models.dive import Dive
from app.models.media_backbone import MediaRevision
from app.services import b2_presign, legacy_media
from app.services.offload import run_to_completion
from app.services.user_access import can_user_access_video

router = APIRouter()
MAX_SHARE_BYTES = 128 * 1024 * 1024


async def _share_file(bucket: str, object_key: str, filename: str) -> StreamingResponse:
    """Bounded same-origin SDK stream; no signed URL enters HTTP client logs."""
    body = None
    opening = asyncio.create_task(asyncio.to_thread(b2_presign.open_get_stream, bucket, object_key))
    try:
        body, size = await run_to_completion(opening)
        if not 0 < size <= MAX_SHARE_BYTES:
            raise HTTPException(413, 'Use the normal download for this video')
    except BaseException:
        # Offloading drains before propagating cancellation. Close the result
        # even when cancellation arrived while the provider was opening it.
        if body is None and opening.done() and not opening.cancelled() and opening.exception() is None:
            body = opening.result()[0]
        if body is not None:
            body.close()
        raise

    async def content():
        received = 0
        try:
            while True:
                chunk = await run_to_completion(asyncio.to_thread(body.read, 64 * 1024))
                if not chunk:
                    break
                received += len(chunk)
                if received > MAX_SHARE_BYTES:
                    raise RuntimeError('Video exceeds sharing limit')
                yield chunk
        finally:
            body.close()

    response = StreamingResponse(content(), media_type=mimetypes.guess_type(filename)[0] or 'video/mp4', headers={
        'Content-Length': str(size), 'Content-Disposition': f'attachment; filename="{filename}"',
    }, background=BackgroundTask(body.close))
    _secure_headers(response)
    return response


def download_filename(dive: Dive, suffix: str = '.mp4') -> str:
    # Keep names safe for HTTP headers and recognizable across batch downloads.
    suffix = suffix.lower() if suffix.lower() in {'.mp4', '.mov', '.m4v', '.webm'} else '.mp4'
    date = dive.dive_datetime.strftime('%Y-%m-%d') if dive.dive_datetime else 'clip'
    return f'dive-{date}-{dive.id}{suffix}'


@router.get('/dives/{dive_id}/download')
async def download_clip(dive_id: int, request: Request, for_share: bool = Query(default=False), db: Session = Depends(get_db), user=Depends(get_current_user)):
    dive = db.query(Dive).filter(Dive.id == dive_id).first()
    if not dive or not dive.video_uuid or not can_user_access_video(db, user, dive.video_uuid).allowed:
        raise HTTPException(404, 'Video unavailable')
    revision = db.query(MediaRevision).filter_by(video_uuid=dive.video_uuid).order_by(MediaRevision.observed_at.desc(), MediaRevision.id.desc()).first()
    source = None
    provider_failed = False
    if revision and get_settings().b2_playback_canary_enabled:
        location, reason = _resolve_verified_prod_location(db, revision)
        if reason == DENY_STORAGE_AMBIGUOUS:
            raise HTTPException(404, 'Video unavailable')
        # Browser uploads store raw sources under extensionless keys. Their
        # pinned, prepared MP4 is already available and needs no conversion.
        if revision.rendition_semantics == 'browser_original':
            source = legacy_media.resolve_legacy_media_source(db, SimpleNamespace(video_uuid=dive.video_uuid))
        if location and source is None:
            try:
                await run_to_completion(asyncio.to_thread(b2_presign.head_object, bucket=location.bucket, object_key=location.object_key))
                if for_share:
                    return await _share_file(location.bucket, location.object_key, download_filename(dive, Path(location.object_key).suffix))
                signed = b2_presign.presign_get(
                    bucket=location.bucket, object_key=location.object_key,
                    storage_location_id=location.id,
                    download_filename=download_filename(dive, Path(location.object_key).suffix),
                )
                response = RedirectResponse(signed.url, status_code=302)
                _secure_headers(response)
                return response
            except b2_presign.PresignUnavailable:
                provider_failed = True
    if source is None:
        source = legacy_media.resolve_legacy_media_source(db, SimpleNamespace(video_uuid=dive.video_uuid))
    if not source:
        raise HTTPException(503 if provider_failed else 404, 'Video unavailable')
    path, content_type = source
    if for_share and Path(path).stat().st_size > MAX_SHARE_BYTES:
        raise HTTPException(413, 'Use the normal download for this video')
    response = _serve_media_file(Path(path), content_type, request)
    response.headers['Content-Disposition'] = f'attachment; filename="{download_filename(dive, Path(path).suffix)}"'
    _secure_headers(response)
    return response
