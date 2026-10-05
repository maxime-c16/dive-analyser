"""Video-only capabilities: guests never acquire a workspace/account session.

Link secrets live in URL fragments (not request/access logs). A visit exchanges
one for a cookie-backed grant to that share; every read/write/play revalidates
it. Issuing a share never changes the dive's library visibility.
"""
from datetime import datetime
from hashlib import sha256
from pathlib import Path
import secrets
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.dive import Dive
from app.models.dive_share import DiveShare, DiveGuest, DiveGuestLike, DiveGuestAccess
from app.models.dive_social import DiveComment, DiveLike
from app.models.user_auth import AppUser
from app.models.media_backbone import MediaRevision
from app.services.dive_access import can_manage_dive, require_dive_owner
from app.services.write_guard import optional_session_user
from app.services import legacy_media, b2_presign
from app.api.v1.auth import _origin_allowed
from app.api.v1.dive_social import LikeInput, CommentInput, comments, comment_payload
from app.api.v1.media import _serve_media_file
from app.api.v1.media_playback import _resolve_verified_prod_location, DENY_STORAGE_AMBIGUOUS

router = APIRouter()
COOKIE = 'dive_guest'
COOKIE_TTL = 365 * 24 * 60 * 60
# French names of characters appearing in the films; no account impersonation.
CHARACTERS = ('Harry Potter', 'Hermione Granger', 'Ron Weasley', 'Ginny Weasley',
              'Luna Lovegood', 'Neville Londubat', 'Drago Malefoy', 'Severus Rogue',
              'Albus Dumbledore', 'Minerva McGonagall', 'Rubeus Hagrid', 'Sirius Black',
              'Remus Lupin', 'Dobby', 'Fleur Delacour', 'Nymphadora Tonks')


def digest(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def secure_headers(response: Response):
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Content-Type-Options'] = 'nosniff'


def same_origin(request: Request):
    if request.method not in ('GET', 'HEAD') and not _origin_allowed(request):
        raise HTTPException(403, 'Origin not allowed')


def owner(dive_id: int, request: Request, db: Session):
    user = optional_session_user(request, db)
    if user is None:
        raise HTTPException(401, 'Sign in to share a dive')
    dive = db.get(Dive, dive_id)
    if dive is None:
        raise HTTPException(404, 'Dive not found')
    require_dive_owner(db, user, dive)
    return dive, user


@router.post('/dives/{dive_id}/shares', status_code=201, dependencies=[Depends(same_origin)])
def create_share(dive_id: int, request: Request, response: Response, db: Session = Depends(get_db)):
    dive, user = owner(dive_id, request, db)
    if not dive.video_uuid:
        raise HTTPException(422, 'This dive has no video to share')
    token = secrets.token_urlsafe(32)
    share = DiveShare(dive_id=dive.id, created_by=user.id, video_uuid=dive.video_uuid, token_hash=digest(token))
    db.add(share)
    db.commit()  # The capability becomes usable only after this transaction.
    db.refresh(share)
    secure_headers(response)
    return dict(path=f'/share/{share.id}#{token}')


@router.get('/dives/{dive_id}/shares')
def share_status(dive_id: int, request: Request, response: Response, db: Session = Depends(get_db)):
    owner(dive_id, request, db)
    secure_headers(response)
    return dict(active_count=db.query(func.count(DiveShare.id)).filter_by(dive_id=dive_id, revoked_at=None).scalar())


@router.delete('/dives/{dive_id}/shares', status_code=204, dependencies=[Depends(same_origin)])
def revoke_shares(dive_id: int, request: Request, db: Session = Depends(get_db)):
    owner(dive_id, request, db)
    db.query(DiveShare).filter_by(dive_id=dive_id, revoked_at=None).update({'revoked_at': datetime.utcnow()})
    db.commit()


def active_share(share_id: int, db: Session):
    share = db.get(DiveShare, share_id)
    dive = db.get(Dive, share.dive_id) if share and not share.revoked_at else None
    creator = db.get(AppUser, share.created_by) if dive else None
    if (dive is None or dive.video_uuid != share.video_uuid
            or not can_manage_dive(db, creator, dive)):
        raise HTTPException(404, 'Shared video unavailable')
    return share, dive


def existing_guest(request: Request, db: Session):
    token = request.cookies.get(COOKIE, '')
    return db.query(DiveGuest).filter_by(token_hash=digest(token)).first() if token else None


@router.post('/shared-dives/{share_id}/visit', dependencies=[Depends(same_origin)])
def visit(share_id: int, request: Request, response: Response,
          x_dive_share: str = Header(min_length=43, max_length=43), db: Session = Depends(get_db)):
    share, dive = active_share(share_id, db)
    if not secrets.compare_digest(share.token_hash, digest(x_dive_share)):
        raise HTTPException(404, 'Shared video unavailable')
    guest = existing_guest(request, db)
    token = None
    if guest is None:
        token = secrets.token_urlsafe(32)
        guest = DiveGuest(token_hash=digest(token), display_name=secrets.choice(CHARACTERS))
        db.add(guest)
        db.flush()
    if db.get(DiveGuestAccess, (share.id, guest.id)) is None:
        db.add(DiveGuestAccess(share_id=share.id, guest_id=guest.id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if token or db.get(DiveGuestAccess, (share.id, guest.id)) is None:
            raise
    if token:
        response.set_cookie(COOKIE, token, max_age=COOKIE_TTL, httponly=True,
                            secure=get_settings().auth_cookie_secure, samesite='lax', path='/api/v1/shared-dives')
    secure_headers(response)
    return dict(dive_id=dive.id, dive_code=dive.dive_code, height=dive.height,
                guest_id=guest.id, guest_name=guest.display_name,
                video_url=f'/api/v1/shared-dives/{share.id}/video')


def guest_access(share_id: int, request: Request, response: Response, db: Session = Depends(get_db)):
    same_origin(request)
    share, dive = active_share(share_id, db)
    guest = existing_guest(request, db)
    if guest is None or db.get(DiveGuestAccess, (share.id, guest.id)) is None:
        raise HTTPException(404, 'Shared video unavailable')
    secure_headers(response)
    return dive, guest


@router.get('/shared-dives/{share_id}/social')
def guest_social(access=Depends(guest_access), db: Session = Depends(get_db)):
    dive, guest = access
    return dict(liked=db.get(DiveGuestLike, (dive.id, guest.id)) is not None,
                like_count=db.query(func.count(DiveLike.user_id)).filter_by(dive_id=dive.id).scalar()
                + db.query(func.count(DiveGuestLike.guest_id)).filter_by(dive_id=dive.id).scalar(),
                comment_count=db.query(func.count(DiveComment.id)).filter_by(dive_id=dive.id).scalar())


@router.put('/shared-dives/{share_id}/like')
def guest_like(payload: LikeInput, access=Depends(guest_access), db: Session = Depends(get_db)):
    dive, guest = access
    row = db.get(DiveGuestLike, (dive.id, guest.id))
    if payload.liked and row is None:
        db.add(DiveGuestLike(dive_id=dive.id, guest_id=guest.id))
    elif not payload.liked and row is not None:
        db.delete(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if not db.get(DiveGuestLike, (dive.id, guest.id)):
            raise
    return guest_social(access, db)


@router.get('/shared-dives/{share_id}/comments')
def guest_comments(before: int | None = None, access=Depends(guest_access), db: Session = Depends(get_db)):
    dive, guest = access
    return comments(dive.id, before, guest, db)


@router.post('/shared-dives/{share_id}/comments', status_code=201)
def guest_comment(payload: CommentInput, access=Depends(guest_access), db: Session = Depends(get_db)):
    dive, guest = access
    body = payload.body.strip()
    if not body:
        raise HTTPException(422, 'Comment cannot be blank')
    row = DiveComment(dive_id=dive.id, guest_id=guest.id, body=body)
    db.add(row)
    db.commit()
    db.refresh(row)
    return comment_payload(row, guest.display_name)


@router.delete('/shared-dives/{share_id}/comments/{comment_id}', status_code=204)
def guest_delete_comment(comment_id: int, access=Depends(guest_access), db: Session = Depends(get_db)):
    dive, guest = access
    row = db.query(DiveComment).filter_by(id=comment_id, dive_id=dive.id).first()
    if row is None:
        raise HTTPException(404, 'Comment not found')
    if row.guest_id != guest.id:
        raise HTTPException(403, 'Only the author can delete this comment')
    db.delete(row)
    db.commit()


@router.get('/shared-dives/{share_id}/video')
def guest_video(request: Request, access=Depends(guest_access), db: Session = Depends(get_db)):
    dive, _ = access
    # Reuse production storage authority and path/Range safety, with a separate
    # capability boundary. Never expose workspace media preparation endpoints.
    revision = db.query(MediaRevision).filter_by(video_uuid=dive.video_uuid).order_by(MediaRevision.observed_at.desc(), MediaRevision.id.desc()).first()
    provider_failed = False
    if revision:
        location, reason = _resolve_verified_prod_location(db, revision)
        if reason == DENY_STORAGE_AMBIGUOUS:
            raise HTTPException(404, 'Shared video unavailable')
        if location:
            try:
                b2_presign.head_object(bucket=location.bucket, object_key=location.object_key)
                result = b2_presign.presign_get(bucket=location.bucket, object_key=location.object_key,
                                               storage_location_id=location.id)
                response = RedirectResponse(result.url, status_code=302)
                secure_headers(response)
                return response
            except b2_presign.PresignUnavailable:
                provider_failed = True
    source = legacy_media.resolve_legacy_media_source(db, SimpleNamespace(video_uuid=dive.video_uuid))
    if source is None:
        raise HTTPException(503 if provider_failed else 404, 'Shared video unavailable')
    path, content_type = source
    response = _serve_media_file(Path(path), content_type, request)
    secure_headers(response)
    return response
