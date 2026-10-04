"""Shared public/private authorization for all video playback paths.

Public is signed-in only; private requires an explicit diver OWNER binding.
Unlinked media always denies. App administration does not imply ownership.
"""

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.models.dive import Dive
from app.models.media import MediaCacheEntry
from app.models.media_backbone import MediaRevision
from app.models.photos_asset import PhotosAsset
from app.models.user_auth import ROLE_FRIEND, AppUser, UserDiverAccess

ACCESS_KIND_OWNER = "OWNER"

# Denial reasons (privacy-safe, used in the grant ledger only).
DENY_UNKNOWN_REVISION = "unknown_revision"
DENY_NO_DIVER_CHAIN = "no_diver_chain"
DENY_NO_OWNER_ACCESS = "no_owner_access"


@dataclass(frozen=True)
class MediaAccessDecision:
    allowed: bool
    reason: str
    diver_id: Optional[int] = None


def resolve_media_diver_owner(
    db: Session, media_revision: MediaRevision
) -> Optional[int]:
    """Authoritative chain: media revision → dive → diver id.

    dives.video_uuid is UNIQUE, so the chain yields exactly one dive and
    therefore exactly one diver, or nothing. Returns None (fail closed)
    when the revision is None, no dive row exists, or the dive has no
    diver bound.
    """
    if media_revision is None:
        return None
    dive = (
        db.query(Dive).filter(Dive.video_uuid == media_revision.video_uuid).one_or_none()
    )
    if dive is None:
        return None
    if dive.diver_id is None:
        return None
    return dive.diver_id


def user_has_diver_access(
    db: Session, user_id: int, diver_id: int, access_kind: str = ACCESS_KIND_OWNER
) -> bool:
    """Explicit binding check only. Nothing implicit."""
    row = (
        db.query(UserDiverAccess)
        .filter_by(
            user_id=user_id,
            diver_id=diver_id,
            access_kind=access_kind,
        )
        .one_or_none()
    )
    return row is not None


def is_friend_user(user: Optional[AppUser]) -> bool:
    """Compatibility helper for the legacy role label; not an access policy."""
    return (
        user is not None
        and bool(user.is_active)
        and getattr(user, "role", None) == ROLE_FRIEND
    )


def _dive_access(db: Session, user: AppUser, dive: Optional[Dive]) -> MediaAccessDecision:
    if user is None or not user.is_active:
        return MediaAccessDecision(False, DENY_NO_OWNER_ACCESS)
    if dive is None:
        return MediaAccessDecision(False, DENY_NO_DIVER_CHAIN)
    if dive.diver_id is None:
        return MediaAccessDecision(bool(user.is_admin), "allowed" if user.is_admin else DENY_NO_DIVER_CHAIN)
    allowed = dive.visibility == "public" or user_has_diver_access(db, user.id, dive.diver_id)
    return MediaAccessDecision(allowed, "allowed" if allowed else DENY_NO_OWNER_ACCESS, dive.diver_id)


def can_user_access_media(db: Session, user: AppUser, media_revision: Optional[MediaRevision]) -> MediaAccessDecision:
    if media_revision is None:
        return MediaAccessDecision(False, DENY_UNKNOWN_REVISION)
    return can_user_access_video(db, user, media_revision.video_uuid)


def resolve_video_diver_owner(db: Session, video_uuid: str) -> Optional[int]:
    dive = db.query(Dive).filter(Dive.video_uuid == video_uuid).one_or_none()
    return dive.diver_id if dive else None


def can_user_access_video(db: Session, user: AppUser, video_uuid: str) -> MediaAccessDecision:
    dive = db.query(Dive).filter(Dive.video_uuid == video_uuid).one_or_none()
    return _dive_access(db, user, dive)


def resolve_cache_entry_diver_owner(db: Session, entry: Optional[MediaCacheEntry]) -> Optional[int]:
    asset = db.get(PhotosAsset, entry.photos_asset_id) if entry and entry.photos_asset_id else None
    return resolve_video_diver_owner(db, asset.video_uuid) if asset else None


def can_user_access_cache_entry(db: Session, user: AppUser, entry: Optional[MediaCacheEntry]) -> MediaAccessDecision:
    if entry is None:
        return MediaAccessDecision(False, DENY_UNKNOWN_REVISION)
    asset = db.query(PhotosAsset).filter(PhotosAsset.id == entry.photos_asset_id).one_or_none()
    if asset is None:
        return MediaAccessDecision(False, DENY_NO_DIVER_CHAIN)
    return can_user_access_video(db, user, asset.video_uuid)
