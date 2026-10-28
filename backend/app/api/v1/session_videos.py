"""Shared session videos: member pages, guest links and the B2 event hook.

Members (any signed-in account) watch; the owner or an admin manages guest
links. Guest links follow dive sharing (docs/guest-dive-sharing.md): secret in
the URL fragment, only SHA-256 hashes stored, revocable, and the same guest
cookie/identity under /api/v1/shared-dives. Playback and download are
short-lived presigned B2 GET redirects of the untouched original (B2 serves
Range requests). Everything 404s while SHARED_SESSIONS_ENABLED is off.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import logging
import secrets
from pathlib import PurePosixPath
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.api.v1.dive_sharing import (
    digest, existing_guest, guest_for_visit, same_origin, secure_headers, set_guest_cookie,
)
from app.config import get_settings
from app.database import get_db
from app.models.session_video import (
    SessionVideo, SessionVideoGuestAccess, SessionVideoPlaybackIssue, SessionVideoShare,
)
from app.models.user_auth import AppUser
from app.services import session_videos as service

logger = logging.getLogger(__name__)
router = APIRouter()
MAX_EVENT_BODY_BYTES = 256 * 1024
MAX_EVENTS_PER_DELIVERY = 100
LIST_LIMIT = 50
ISSUE_DEDUP_WINDOW = timedelta(hours=1)
UNAVAILABLE = 'Session video unavailable'


def require_enabled():
    if not get_settings().shared_sessions_enabled:
        raise HTTPException(404, 'Not found')


def serialize(video: SessionVideo, *, can_share: bool = False) -> dict:
    """Viewer-safe fields only: no bucket/key/etag, never location tags."""
    return dict(
        id=video.id, session_id=video.session_id, filename=PurePosixPath(video.object_key).name,
        recorded_at=(video.recorded_at.replace(tzinfo=timezone.utc).isoformat() if video.recorded_at else None),
        recorded_date=video.recorded_date.isoformat() if video.recorded_date else None,
        duration_seconds=video.duration_seconds, size_bytes=video.size_bytes,
        codec_string=video.codec_string, audio_codec_string=video.audio_codec_string,
        video_codec=video.video_codec, color_transfer=video.color_transfer,
        width=video.width, height=video.height, fps=video.fps, bit_rate=video.bit_rate,
        can_share=can_share,
    )


def can_manage(user: AppUser, video: SessionVideo) -> bool:
    return bool(user and user.is_active and (user.id == video.owner_user_id or user.is_admin))


def ready_video(db: Session, video_id: int) -> SessionVideo:
    video = db.get(SessionVideo, video_id)
    if video is None or video.status != 'ready':
        raise HTTPException(404, UNAVAILABLE)
    return video


def redirect_to(url: str) -> RedirectResponse:
    response = RedirectResponse(url, status_code=302)
    secure_headers(response)
    return response


def playback_redirect(video: SessionVideo) -> RedirectResponse:
    # The original is served as-is; video/mp4 lets every browser try the
    # QuickTime file (same ISO-BMFF structure) instead of refusing the MIME.
    try:
        url = service.presign_get(video.bucket, video.object_key, get_settings().sessions_playback_ttl_seconds,
                                  content_type='video/mp4')
    except service.SessionsStorageUnavailable:
        raise HTTPException(503, UNAVAILABLE) from None
    return redirect_to(url)


def download_redirect(video: SessionVideo) -> RedirectResponse:
    try:
        url = service.presign_get(video.bucket, video.object_key, get_settings().sessions_playback_ttl_seconds,
                                  download_name=PurePosixPath(video.object_key).name)
    except service.SessionsStorageUnavailable:
        raise HTTPException(503, UNAVAILABLE) from None
    return redirect_to(url)


class IssueInput(BaseModel):
    reason: Literal['unsupported', 'no_frames', 'error']


def record_issue(db: Session, video: SessionVideo, reason: str, request: Request,
                 *, user_id: int | None = None, guest_id: int | None = None) -> None:
    """Count devices that cannot show the original; one row per viewer/reason/hour."""
    since = datetime.utcnow() - ISSUE_DEDUP_WINDOW
    recent = db.query(SessionVideoPlaybackIssue.id).filter(
        SessionVideoPlaybackIssue.session_video_id == video.id,
        SessionVideoPlaybackIssue.reason == reason,
        SessionVideoPlaybackIssue.viewer_user_id.is_(None) if user_id is None
        else SessionVideoPlaybackIssue.viewer_user_id == user_id,
        SessionVideoPlaybackIssue.viewer_guest_id.is_(None) if guest_id is None
        else SessionVideoPlaybackIssue.viewer_guest_id == guest_id,
        SessionVideoPlaybackIssue.created_at >= since,
    ).first()
    if recent is None:
        db.add(SessionVideoPlaybackIssue(
            session_video_id=video.id, reason=reason, viewer_user_id=user_id, viewer_guest_id=guest_id,
            user_agent=(request.headers.get('user-agent') or '')[:200] or None))
        db.commit()
    logger.info('shared sessions: video %s not playable on a device (%s)', video.id, reason)


def issue_share(db: Session, video: SessionVideo, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    share = SessionVideoShare(session_video_id=video.id, created_by=user_id, token_hash=digest(token))
    db.add(share)
    db.commit()  # usable only once committed
    db.refresh(share)
    return f'/share/session/{share.id}#{token}'


# ----------------------------------------------------------------- members ---

@router.get('/session-videos', dependencies=[Depends(require_enabled)])
def list_videos(response: Response, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (db.query(SessionVideo).filter(SessionVideo.status == 'ready')
            .order_by(SessionVideo.recorded_at.desc().nullslast(), SessionVideo.id.desc())
            .limit(LIST_LIMIT + 1).all())
    secure_headers(response)
    return dict(items=[serialize(v, can_share=can_manage(user, v)) for v in rows[:LIST_LIMIT]],
                has_more=len(rows) > LIST_LIMIT)


@router.get('/session-videos/{video_id}', dependencies=[Depends(require_enabled)])
def get_video(video_id: int, response: Response, user: AppUser = Depends(get_current_user),
              db: Session = Depends(get_db)):
    video = ready_video(db, video_id)
    secure_headers(response)
    return serialize(video, can_share=can_manage(user, video))


@router.get('/session-videos/{video_id}/play', dependencies=[Depends(require_enabled)])
def play(video_id: int, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return playback_redirect(ready_video(db, video_id))


@router.get('/session-videos/{video_id}/download', dependencies=[Depends(require_enabled)])
def download(video_id: int, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return download_redirect(ready_video(db, video_id))


@router.post('/session-videos/{video_id}/playback-issues', status_code=204,
             dependencies=[Depends(require_enabled), Depends(same_origin)])
def member_issue(video_id: int, payload: IssueInput, request: Request,
                 user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    record_issue(db, ready_video(db, video_id), payload.reason, request, user_id=user.id)


def managed_video(video_id: int, user: AppUser, db: Session) -> SessionVideo:
    video = ready_video(db, video_id)
    if not can_manage(user, video):
        raise HTTPException(403, 'Only the session owner can share it')
    return video


@router.post('/session-videos/{video_id}/shares', status_code=201,
             dependencies=[Depends(require_enabled), Depends(same_origin)])
def create_share(video_id: int, response: Response, user: AppUser = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    video = managed_video(video_id, user, db)
    secure_headers(response)
    return dict(path=issue_share(db, video, user.id))


@router.get('/session-videos/{video_id}/shares', dependencies=[Depends(require_enabled)])
def share_status(video_id: int, response: Response, user: AppUser = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    managed_video(video_id, user, db)
    secure_headers(response)
    return dict(active_count=db.query(func.count(SessionVideoShare.id))
                .filter_by(session_video_id=video_id, revoked_at=None).scalar())


@router.delete('/session-videos/{video_id}/shares', status_code=204,
               dependencies=[Depends(require_enabled), Depends(same_origin)])
def revoke_shares(video_id: int, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    managed_video(video_id, user, db)
    (db.query(SessionVideoShare).filter_by(session_video_id=video_id, revoked_at=None)
     .update({'revoked_at': datetime.utcnow()}))
    db.commit()


# ------------------------------------------------------------- B2 events ---

def valid_signature(body: bytes, header: str | None) -> bool:
    secret = get_settings().sessions_b2_event_secret.strip()
    if not secret or not header or not header.startswith('v1='):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[3:].strip().lower())


@router.post('/session-videos/b2-events', dependencies=[Depends(require_enabled)])
async def b2_events(request: Request, background: BackgroundTasks,
                    x_bz_event_notification_signature: str | None = Header(default=None)):
    """Backblaze Event Notifications: HMAC-SHA256 of the raw body, `v1=<hex>`.

    Answer within B2's 3 s budget: verify, then ingest in the background.
    Delivery is at-least-once; ingestion is idempotent per object key.
    """
    declared = request.headers.get('content-length')
    if declared and declared.isdigit() and int(declared) > MAX_EVENT_BODY_BYTES:
        raise HTTPException(413, 'Too large')
    body = b''
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_EVENT_BODY_BYTES:
            raise HTTPException(413, 'Too large')
    if not valid_signature(body, x_bz_event_notification_signature):
        raise HTTPException(401, 'Invalid signature')
    try:
        events = json.loads(body).get('events')
        if not isinstance(events, list):
            raise ValueError
    except (ValueError, AttributeError):
        raise HTTPException(400, 'Invalid payload') from None
    settings = get_settings()
    accepted = 0
    for event in events[:MAX_EVENTS_PER_DELIVERY]:
        if not isinstance(event, dict):
            continue
        key = event.get('objectName')
        if (str(event.get('eventType', '')).startswith('b2:ObjectCreated:')
                and event.get('bucketName') == settings.sessions_b2_bucket
                and isinstance(key, str) and service.is_session_video_key(key)):
            stamp = event.get('eventTimestamp')
            when = (datetime.fromtimestamp(stamp / 1000, tz=timezone.utc)
                    if isinstance(stamp, (int, float)) else None)
            size = event.get('objectSize') if isinstance(event.get('objectSize'), int) else None
            background.add_task(service.ingest_in_background, key, size, when)
            accepted += 1
    return dict(accepted=accepted)


# ------------------------------------------------------------------ guests ---

def active_share(share_id: int, db: Session):
    share = db.get(SessionVideoShare, share_id)
    video = db.get(SessionVideo, share.session_video_id) if share and not share.revoked_at else None
    creator = db.get(AppUser, share.created_by) if video else None
    if video is None or video.status != 'ready' or not can_manage(creator, video):
        raise HTTPException(404, UNAVAILABLE)
    return share, video


@router.post('/shared-dives/sessions/{share_id}/visit', dependencies=[Depends(require_enabled), Depends(same_origin)])
def guest_visit(share_id: int, request: Request, response: Response,
                x_dive_share: str = Header(min_length=43, max_length=43), db: Session = Depends(get_db)):
    share, video = active_share(share_id, db)
    if not secrets.compare_digest(share.token_hash, digest(x_dive_share)):
        raise HTTPException(404, UNAVAILABLE)
    guest, token = guest_for_visit(request, db)
    if db.get(SessionVideoGuestAccess, (share.id, guest.id)) is None:
        db.add(SessionVideoGuestAccess(share_id=share.id, guest_id=guest.id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if token or db.get(SessionVideoGuestAccess, (share.id, guest.id)) is None:
            raise
    set_guest_cookie(response, token)
    secure_headers(response)
    base = f'/api/v1/shared-dives/sessions/{share.id}'
    return dict(**serialize(video), guest_id=guest.id, guest_name=guest.display_name,
                video_url=f'{base}/video', download_url=f'{base}/download')


def guest_access(share_id: int, request: Request, db: Session = Depends(get_db)):
    require_enabled()
    same_origin(request)
    share, video = active_share(share_id, db)
    guest = existing_guest(request, db)
    if guest is None or db.get(SessionVideoGuestAccess, (share.id, guest.id)) is None:
        raise HTTPException(404, UNAVAILABLE)
    return video, guest


@router.get('/shared-dives/sessions/{share_id}/video')
def guest_video(access=Depends(guest_access)):
    return playback_redirect(access[0])


@router.get('/shared-dives/sessions/{share_id}/download')
def guest_download(access=Depends(guest_access)):
    return download_redirect(access[0])


@router.post('/shared-dives/sessions/{share_id}/playback-issues', status_code=204)
def guest_issue(payload: IssueInput, request: Request, access=Depends(guest_access), db: Session = Depends(get_db)):
    video, guest = access
    record_issue(db, video, payload.reason, request, guest_id=guest.id)
