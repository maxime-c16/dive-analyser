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
from pydantic import BaseModel, Field
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
        can_share=can_share, hidden=video.hidden,
        poster_url=f"/api/v1/session-videos/{video.id}/images/poster",
        animated_url=f"/api/v1/session-videos/{video.id}/images/animated",
    )


def can_manage(user: AppUser, video: SessionVideo) -> bool:
    return bool(user and user.is_active and (user.id == video.owner_user_id or user.is_admin))


def ready_video(db: Session, video_id: int, user: AppUser | None = None) -> SessionVideo:
    video = db.get(SessionVideo, video_id)
    if video is None or video.status != 'ready' or (video.hidden and not can_manage(user, video)) or video.deleted_at is not None:
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
    share = SessionVideoShare(session_video_id=video.id, session_id=video.session_id, created_by=user_id, token_hash=digest(token))
    db.add(share)
    db.commit()  # usable only once committed
    db.refresh(share)
    return f'/share/session/{share.id}#{token}'


# ----------------------------------------------------------------- members ---

@router.get('/session-videos', dependencies=[Depends(require_enabled)])
def list_videos(response: Response, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (db.query(SessionVideo).filter(SessionVideo.status == 'ready', SessionVideo.hidden.is_(False), SessionVideo.deleted_at.is_(None))
            .order_by(SessionVideo.recorded_at.desc().nullslast(), SessionVideo.id.desc())
            .limit(LIST_LIMIT + 1).all())
    secure_headers(response)
    return dict(items=[serialize(v, can_share=can_manage(user, v)) for v in rows[:LIST_LIMIT]],
                has_more=len(rows) > LIST_LIMIT)


@router.get('/session-videos/{video_id}', dependencies=[Depends(require_enabled)])
def get_video(video_id: int, response: Response, user: AppUser = Depends(get_current_user),
              db: Session = Depends(get_db)):
    video = ready_video(db, video_id, user)
    secure_headers(response)
    return serialize(video, can_share=can_manage(user, video))


@router.get('/session-videos/{video_id}/play', dependencies=[Depends(require_enabled)])
def play(video_id: int, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return playback_redirect(ready_video(db, video_id, user))


@router.get('/session-videos/{video_id}/download', dependencies=[Depends(require_enabled)])
def download(video_id: int, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return download_redirect(ready_video(db, video_id, user))


@router.post('/session-videos/{video_id}/playback-issues', status_code=204,
             dependencies=[Depends(require_enabled), Depends(same_origin)])
def member_issue(video_id: int, payload: IssueInput, request: Request,
                 user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    record_issue(db, ready_video(db, video_id, user), payload.reason, request, user_id=user.id)


def managed_video(video_id: int, user: AppUser, db: Session) -> SessionVideo:
    video = ready_video(db, video_id, user)
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
                .filter_by(session_id=ready_video(db, video_id, user).session_id, revoked_at=None).scalar())


@router.delete('/session-videos/{video_id}/shares', status_code=204,
               dependencies=[Depends(require_enabled), Depends(same_origin)])
def revoke_shares(video_id: int, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    managed_video(video_id, user, db)
    db.query(SessionVideoShare).filter_by(session_id=ready_video(db, video_id, user).session_id).with_for_update().all()
    (db.query(SessionVideoShare).filter_by(session_id=ready_video(db, video_id, user).session_id, revoked_at=None)
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
    if video is None or not can_manage(creator, video):
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
    return serialize(video) | session_payload(db, share.session_id or video.session_id, guest_base=base) | dict(guest_id=guest.id, guest_name=guest.display_name,
                video_url=f'{base}/video', download_url='')


def guest_access(share_id: int, request: Request, db: Session = Depends(get_db)):
    require_enabled()
    same_origin(request)
    share, video = active_share(share_id, db)
    guest = existing_guest(request, db)
    if guest is None or db.get(SessionVideoGuestAccess, (share.id, guest.id)) is None:
        raise HTTPException(404, UNAVAILABLE)
    return video, guest


@router.get('/shared-dives/sessions/{share_id}/video')
def guest_video(share_id: int, request: Request, db: Session = Depends(get_db), access=Depends(guest_access)):
    return playback_redirect(guest_selected(share_id, access[0].id, request, db))


@router.get('/shared-dives/sessions/{share_id}/download')
def guest_download(access=Depends(guest_access)):
    raise HTTPException(401, "Account required")


@router.post('/shared-dives/sessions/{share_id}/playback-issues', status_code=204)
def guest_issue(payload: IssueInput, request: Request, access=Depends(guest_access), db: Session = Depends(get_db)):
    video, guest = access
    record_issue(db, video, payload.reason, request, guest_id=guest.id)

# Session identity is stable when later recordings arrive or a video is moved.
def session_payload(db, session_id, *, user=None, guest_base=None, after=0):
    result = session_payloads(db, [session_id], user=user, guest_base=guest_base, after=after)
    if not result:
        raise HTTPException(404, UNAVAILABLE)
    return result[0]


def session_payloads(db, ids, *, user=None, guest_base=None, after=0):
    from app.models.session import Session as TrainingSession
    from sqlalchemy import or_
    from sqlalchemy.orm import aliased
    visible = [SessionVideo.status == 'ready', SessionVideo.deleted_at.is_(None), SessionVideo.session_id.in_(ids)]
    if not user or not user.is_admin:
        visible.append(or_(SessionVideo.hidden.is_(False), SessionVideo.owner_user_id == user.id) if user else SessionVideo.hidden.is_(False))
    ranked = db.query(SessionVideo.id, func.row_number().over(partition_by=SessionVideo.session_id,
        order_by=SessionVideo.id).label('rank')).filter(*visible, SessionVideo.id > after).subquery()
    rows = db.query(SessionVideo).join(ranked, ranked.c.id == SessionVideo.id).filter(ranked.c.rank <= 101).order_by(
        SessionVideo.id).all()
    totals = {r[0]: r[1:] for r in db.query(SessionVideo.session_id, func.count(SessionVideo.id),
        func.sum(SessionVideo.duration_seconds), func.sum(SessionVideo.size_bytes)).filter(*visible,
            SessionVideo.hidden.is_(False)).group_by(SessionVideo.session_id).all()}
    # Day identity is shared independently of dive visibility. Read only the
    # day columns through Core; ORM TrainingSession is intentionally dive-scoped.
    from sqlalchemy import select
    table = TrainingSession.__table__
    days = {d.id: d for d in db.execute(select(table.c.id, table.c.date).where(table.c.id.in_(ids))).all()}
    owned = set() if not user else {r[0] for r in db.query(SessionVideo.session_id).filter(SessionVideo.session_id.in_(ids), SessionVideo.owner_user_id == user.id).distinct()}
    grouped = {id: [] for id in ids}
    for v in rows:
        item = serialize(v, can_share=can_manage(user, v))
        if guest_base:
            item.update(video_url=f'{guest_base}/videos/{v.id}/play', download_url='',
                        poster_url=f'{guest_base}/videos/{v.id}/images/poster',
                        animated_url=f'{guest_base}/videos/{v.id}/images/animated')
        grouped[v.session_id].append(item)
    return [dict(session_id=id, date=days[id].date.isoformat(), videos=grouped[id][:100], can_manage=bool(user and (user.is_admin or id in owned)),
        video_count=totals.get(id,(0,0,0))[0], total_duration=totals.get(id,(0,0,0))[1] or 0,
        total_bytes=totals.get(id,(0,0,0))[2] or 0, has_more=len(grouped[id])>100,
        next_video_id=grouped[id][99]['id'] if len(grouped[id])>100 else None) for id in ids if id in days]


@router.get('/shared-sessions', dependencies=[Depends(require_enabled)])
def session_feed(response: Response, before: int | None = None, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.models.session import Session as TrainingSession
    from sqlalchemy import select
    day_table = TrainingSession.__table__
    query = db.query(SessionVideo.session_id, day_table.c.date).join(day_table, day_table.c.id == SessionVideo.session_id).filter(SessionVideo.status == 'ready', SessionVideo.hidden.is_(False),
        SessionVideo.deleted_at.is_(None), SessionVideo.session_id.isnot(None))
    if before is not None:
        query = query.filter(day_table.c.date < select(day_table.c.date).where(day_table.c.id == before).scalar_subquery())
    ids = query.distinct().order_by(day_table.c.date.desc(), SessionVideo.session_id.desc()).limit(21).all()
    secure_headers(response)
    return dict(items=session_payloads(db, [row[0] for row in ids[:20]], user=user),
                next_cursor=ids[19][0] if len(ids)>20 else None)


@router.get('/shared-sessions/{session_id}', dependencies=[Depends(require_enabled)])
def session_detail(session_id: int, response: Response, after: int = 0, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    secure_headers(response)
    return session_payload(db, session_id, user=user, after=after)


class VideoSettings(BaseModel):
    hidden: bool | None = None
    delete: bool = False
    date: str | None = None


@router.patch('/session-videos/{video_id}', dependencies=[Depends(require_enabled), Depends(same_origin)])
def edit_video(video_id: int, payload: VideoSettings, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.models.session import Session as TrainingSession
    from datetime import date
    video = db.query(SessionVideo).filter_by(id=video_id).with_for_update().first()
    if video is None or not can_manage(user, video):
        raise HTTPException(403, 'Owner required')
    if payload.date:
        try:
            day = date.fromisoformat(payload.date)
        except ValueError:
            raise HTTPException(422, 'Invalid date') from None
        from sqlalchemy import select
        if db.bind.dialect.name == 'postgresql':
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        table = TrainingSession.__table__
        db.execute(insert(table).values(date=day).on_conflict_do_nothing(index_elements=['date']))
        video.session_id = db.execute(select(table.c.id).where(table.c.date == day)).scalar_one()
    if payload.hidden is not None:
        video.hidden = payload.hidden
    if payload.delete:
        video.deleted_at = datetime.utcnow()  # B2 is never mutated.
    db.commit()
    return serialize(video, can_share=True)


def guest_selected(share_id, video_id, request, db):
    anchor, guest = guest_access(share_id, request, db)
    video = ready_video(db, video_id)
    share = db.get(SessionVideoShare, share_id)
    if video.session_id != (share.session_id or anchor.session_id):
        raise HTTPException(404, UNAVAILABLE)
    return video


@router.get('/shared-dives/sessions/{share_id}/videos/{video_id}/play')
def guest_selected_play(share_id: int, video_id: int, request: Request, db: Session = Depends(get_db)):
    return playback_redirect(guest_selected(share_id, video_id, request, db))


def image_response(video, kind):
    from fastapi.responses import FileResponse
    from app.services.session_images import image_path
    if kind not in ('poster', 'animated'):
        raise HTTPException(404)
    path = image_path(video.id, kind)
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type='image/webp', headers={'Cache-Control': 'private, max-age=300'})


@router.get('/session-videos/{video_id}/images/{kind}', dependencies=[Depends(require_enabled)])
def member_image(video_id: int, kind: str, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return image_response(ready_video(db, video_id, user), kind)


@router.get('/shared-dives/sessions/{share_id}/videos/{video_id}/images/{kind}')
def guest_image(share_id: int, video_id: int, kind: str, request: Request, db: Session = Depends(get_db)):
    return image_response(guest_selected(share_id, video_id, request, db), kind)


@router.get('/shared-dives/sessions/{share_id}/groups', dependencies=[Depends(require_enabled)])
def signup_groups(share_id: int, request: Request, db: Session = Depends(get_db)):
    from app.models.calendar import Club, TrainingGroup
    guest_access(share_id, request, db)
    return [dict(id=g.id, name=g.name, club_id=c.id, club=c.name) for g,c in
        db.query(TrainingGroup, Club).join(Club, Club.id == TrainingGroup.club_id).filter(
            Club.archived_at.is_(None), Club.self_join_enabled.is_(True), TrainingGroup.archived_at.is_(None))
        .order_by(Club.name, TrainingGroup.name).limit(200).all()]


class SessionSignup(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=255, pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    password: str = Field(min_length=10, max_length=1024)
    group_id: int
    email_enabled: bool = True


@router.post('/shared-dives/sessions/{share_id}/signup', status_code=201,
             dependencies=[Depends(require_enabled), Depends(same_origin)])
def signup(share_id: int, payload: SessionSignup, request: Request, response: Response,
           background: BackgroundTasks, db: Session = Depends(get_db)):
    from app.api.v1 import auth
    from app.models.calendar import Club, ClubMembership, TrainingGroup, TrainingGroupMembership
    from app.models.diver import Diver
    from app.models.user_auth import UserCredential, UserDiverAccess
    from app.models.session_video import SessionSignupReview
    from app.services.passwords import hash_password
    from app.services import sessions, notification_service, telegram
    from datetime import date
    from uuid import uuid4
    if not get_settings().user_auth_enabled:
        raise HTTPException(404, 'Not found')
    if auth._register_rate_limited(db, auth._client_ip(request)):
        raise HTTPException(429, 'Too many attempts')
    auth._record_attempt(db, auth._REGISTER_IDENTIFIER, success=False, client_ip=auth._client_ip(request))
    # Same row lock as revocation: no signup can race past a committed revoke.
    db.query(SessionVideoShare).filter_by(id=share_id).populate_existing().with_for_update().first()
    video, _ = guest_access(share_id, request, db)
    group = db.get(TrainingGroup, payload.group_id)
    club = db.get(Club, group.club_id) if group else None
    if not group or group.archived_at or not club or club.archived_at or not club.self_join_enabled:
        raise HTTPException(422, 'Invalid group')
    email = payload.email.strip().lower()
    if db.query(AppUser.id).filter_by(email=email).first():
        raise HTTPException(409, 'An account with this email already exists')
    name = payload.display_name.strip()
    if not name:
        raise HTTPException(422, 'Name required')
    if db.bind.dialect.name == 'postgresql':
        from sqlalchemy import text
        db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': int.from_bytes(hashlib.sha256(name.casefold().encode()).digest()[:8], 'big', signed=True)})
    candidate = db.query(Diver).filter(func.lower(Diver.display_name) == name.lower(),
        ~Diver.id.in_(db.query(UserDiverAccess.diver_id))).order_by(Diver.id).first()
    user = AppUser(email=email, display_name=name, role='diver', session_email_enabled=payload.email_enabled)
    db.add(user); db.flush()
    db.add(UserCredential(user_id=user.id, password_hash=hash_password(payload.password)))
    if candidate:
        db.add(SessionSignupReview(user_id=user.id, candidate_diver_id=candidate.id))
    else:
        diver = Diver(display_name=name, canonical_name=f'member-{user.id}-{uuid4().hex}')
        db.add(diver); db.flush()
        db.add(UserDiverAccess(user_id=user.id, diver_id=diver.id, access_kind='OWNER'))
    membership = ClubMembership(club_id=club.id, user_id=user.id, source='signup')
    db.add(membership); db.flush()
    db.add(TrainingGroupMembership(club_id=club.id, group_id=group.id, user_id=user.id,
        club_membership_id=membership.id, effective_from=date.today()))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Account already exists') from None
    notification_service.create(db, user_id=video.owner_user_id, type='session_video',
        title='Inscription par lien séance', body=f'{name} · {email}' + (' · Profil à rattacher' if candidate else ''), defer_push=True)
    if telegram.configured():
        background.add_task(telegram.send, f'Inscription séance : {name} · {email}' + (' · Profil à rattacher' if candidate else ''))
    token, _ = sessions.create_session(db, user_id=user.id, ttl_seconds=get_settings().auth_session_ttl_seconds)
    auth._set_session_cookie(response, token)
    secure_headers(response)
    share = db.get(SessionVideoShare, share_id)
    return dict(path=f'/sessions/shared/{share.session_id or video.session_id}', profile_pending=bool(candidate))


@router.get('/session-preferences', dependencies=[Depends(require_enabled)])
def email_preference(user: AppUser = Depends(get_current_user)):
    return dict(enabled=user.session_email_enabled)


class EmailPreference(BaseModel):
    enabled: bool


@router.put('/session-preferences', dependencies=[Depends(require_enabled), Depends(same_origin)])
def set_email_preference(payload: EmailPreference, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    user.session_email_enabled = payload.enabled
    db.commit()
    return dict(enabled=user.session_email_enabled)


@router.get('/session-signup-reviews', dependencies=[Depends(require_enabled)])
def signup_reviews(user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.models.session_video import SessionSignupReview
    if not user.is_admin:
        raise HTTPException(403)
    from app.models.diver import Diver
    rows = db.query(SessionSignupReview, AppUser.display_name, AppUser.email, Diver.__table__.c.display_name).join(
        AppUser, AppUser.id == SessionSignupReview.user_id).join(Diver.__table__, Diver.__table__.c.id == SessionSignupReview.candidate_diver_id).filter(
        SessionSignupReview.resolved_at.is_(None)).order_by(SessionSignupReview.id).limit(100).all()
    return [dict(id=r.id, user_id=r.user_id, candidate_diver_id=r.candidate_diver_id, name=name, email=email, candidate_name=candidate) for r,name,email,candidate in rows]


@router.post('/session-signup-reviews/{review_id}/accept', dependencies=[Depends(require_enabled), Depends(same_origin)])
def accept_signup_review(review_id: int, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.models.session_video import SessionSignupReview
    from app.models.user_auth import UserDiverAccess
    if not user.is_admin:
        raise HTTPException(403)
    review = db.query(SessionSignupReview).filter_by(id=review_id).with_for_update().first()
    if not review or review.resolved_at:
        raise HTTPException(404)
    from app.models.diver import Diver
    from sqlalchemy import select
    db.execute(select(Diver.__table__.c.id).where(Diver.__table__.c.id == review.candidate_diver_id).with_for_update()).first()
    if db.query(UserDiverAccess.id).filter_by(diver_id=review.candidate_diver_id).first():
        raise HTTPException(409, 'Profile already linked')
    db.add(UserDiverAccess(user_id=review.user_id, diver_id=review.candidate_diver_id, access_kind='OWNER'))
    review.resolved_at = datetime.utcnow()
    db.commit()
    return dict(ok=True)


def session_owner_video(session_id, user, db):
    query = db.query(SessionVideo).filter_by(session_id=session_id)
    if not user.is_admin:
        query = query.filter_by(owner_user_id=user.id)
    video = query.order_by(SessionVideo.id).first()
    if video is None:
        raise HTTPException(403, 'Owner required')
    return video


@router.get('/shared-sessions/{session_id}/shares', dependencies=[Depends(require_enabled)])
def session_shares(session_id: int, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    session_owner_video(session_id, user, db)
    return dict(active_count=db.query(func.count(SessionVideoShare.id)).filter_by(session_id=session_id, revoked_at=None).scalar())


@router.post('/shared-sessions/{session_id}/shares', status_code=201, dependencies=[Depends(require_enabled), Depends(same_origin)])
def new_session_share(session_id: int, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return dict(path=issue_share(db, session_owner_video(session_id, user, db), user.id))


@router.delete('/shared-sessions/{session_id}/shares', status_code=204, dependencies=[Depends(require_enabled), Depends(same_origin)])
def revoke_session_shares(session_id: int, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    session_owner_video(session_id, user, db)
    # UPDATE locks each capability and serializes against signup's row lock.
    db.query(SessionVideoShare).filter_by(session_id=session_id, revoked_at=None).update({'revoked_at':datetime.utcnow()})
    db.commit()


@router.get('/shared-dives/sessions/{share_id}/recordings')
def guest_recordings(share_id: int, request: Request, after: int = 0, db: Session = Depends(get_db)):
    anchor, _ = guest_access(share_id, request, db)
    share = db.get(SessionVideoShare, share_id)
    return session_payload(db, share.session_id or anchor.session_id,
        guest_base=f'/api/v1/shared-dives/sessions/{share_id}', after=after)


@router.post('/shared-dives/sessions/{share_id}/videos/{video_id}/playback-issues', status_code=204)
def guest_selected_issue(share_id: int, video_id: int, payload: IssueInput, request: Request, db: Session = Depends(get_db)):
    video = guest_selected(share_id, video_id, request, db)
    guest = existing_guest(request, db)
    record_issue(db, video, payload.reason, request, guest_id=guest.id)
