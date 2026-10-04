"""Central user→media authorization policy (P5).

MEDIA→DIVER LINK (fresh P5 audit classification):
MEDIA_DIVER_LINK_ALREADY_DETERMINISTIC — the existing domain already holds a
deterministic ownership chain:

    MediaRevision.video_uuid  →  dives.video_uuid (UNIQUE)  →  dives.diver_id

Every MediaRevision in the production database resolves to exactly one dive
row, and dive.video_uuid is UNIQUE, so (media revision → diver) is a
function, not a heuristic. Filename, caption text, UUID secrecy, Photos
albums, and divers.is_primary_user are NEVER consulted for authorization.
No additive media ownership table is introduced in P5 V1.

CENTRAL POLICY (V1 rule, single implementation used by every route):

    ALLOW  iff
      authenticated user
      AND media revision resolves to exactly one trusted diver owner
          through the chain above
      AND the user holds an explicit OWNER UserDiverAccess row for that diver

    otherwise DENY.

There is no fallback: not to the primary user, not to LAN locality, not to
UUID/revision-id secrecy, not to any legacy unauthenticated playback path.
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
    """True for an active friend-role user (FRIEND ACCESS V1).

    Friends see every diver's dives/media by default with no explicit
    bindings; read-only enforcement lives in app/services/write_guard.py.
    """
    return (
        user is not None
        and bool(user.is_active)
        and getattr(user, "role", None) == ROLE_FRIEND
    )


def can_user_access_media(
    db: Session, user: AppUser, media_revision: Optional[MediaRevision]
) -> MediaAccessDecision:
    """THE central P5 authorization policy. Every playback resolution goes
    through this function; no route may bypass it.

    FRIEND ACCESS V1: an active friend-role user is allowed for any
    EXISTING revision (unknown revisions still deny — no existence oracle
    change). Owner behaviour is unchanged (explicit OWNER binding)."""
    if media_revision is None:
        return MediaAccessDecision(False, DENY_UNKNOWN_REVISION)
    if user is None or not user.is_active:
        return MediaAccessDecision(False, DENY_NO_OWNER_ACCESS)
    if is_friend_user(user):
        diver_id = resolve_media_diver_owner(db, media_revision)
        return MediaAccessDecision(True, "allowed", diver_id)
    diver_id = resolve_media_diver_owner(db, media_revision)
    if diver_id is None:
        return MediaAccessDecision(False, DENY_NO_DIVER_CHAIN)
    if not user_has_diver_access(db, user.id, diver_id):
        return MediaAccessDecision(False, DENY_NO_OWNER_ACCESS, diver_id)
    return MediaAccessDecision(True, "allowed", diver_id)


def resolve_video_diver_owner(db: Session, video_uuid: str) -> Optional[int]:
    """Authoritative chain for a legacy video identity:

        dives.video_uuid (UNIQUE)  ->  dives.diver_id

    Same deterministic function the media-revision chain bottoms out in.
    Returns None (fail closed) for unknown/unlinked UUIDs.
    """
    if not video_uuid:
        return None
    dive = db.query(Dive).filter(Dive.video_uuid == video_uuid).one_or_none()
    if dive is None or dive.diver_id is None:
        return None
    return dive.diver_id


def can_user_access_video(
    db: Session, user: AppUser, video_uuid: str
) -> MediaAccessDecision:
    """Central policy for legacy video-identity playback (P6 legacy gating).

    ALLOW iff the same rule as can_user_access_media, entered through the
    dive chain directly. No legacy fallbacks: no primary-user shortcut, no
    LAN locality, no UUID secrecy.

    FRIEND ACCESS V1: friends are allowed for any KNOWN video UUID."""
    if user is None or not user.is_active:
        return MediaAccessDecision(False, DENY_NO_OWNER_ACCESS)
    diver_id = resolve_video_diver_owner(db, video_uuid)
    if diver_id is None:
        if is_friend_user(user):
            # The UUID still has to resolve to a real dive row (unknown
            # UUIDs deny); the diver binding is what friends skip.
            dive = db.query(Dive).filter(Dive.video_uuid == video_uuid).one_or_none()
            if dive is not None:
                return MediaAccessDecision(True, "allowed", None)
        return MediaAccessDecision(False, DENY_NO_DIVER_CHAIN)
    if is_friend_user(user):
        return MediaAccessDecision(True, "allowed", diver_id)
    if not user_has_diver_access(db, user.id, diver_id):
        return MediaAccessDecision(False, DENY_NO_OWNER_ACCESS, diver_id)
    return MediaAccessDecision(True, "allowed", diver_id)


def resolve_cache_entry_diver_owner(
    db: Session, entry: Optional[MediaCacheEntry]
) -> Optional[int]:
    """Authoritative chain for a media-cache rendition:

        MediaCacheEntry.photos_asset_id -> PhotosAsset.video_uuid
          -> dives.video_uuid (UNIQUE)  ->  dives.diver_id

    Cache entries are derived renditions of a Photos asset; the asset's
    video_uuid joins the unique dive chain, so (cache entry -> diver) is a
    function or nothing. Returns None (fail closed) otherwise.
    """
    if entry is None or entry.photos_asset_id is None:
        return None
    asset = db.get(PhotosAsset, entry.photos_asset_id)
    if asset is None or not asset.video_uuid:
        return None
    return resolve_video_diver_owner(db, asset.video_uuid)


def can_user_access_cache_entry(
    db: Session, user: AppUser, entry: Optional[MediaCacheEntry]
) -> MediaAccessDecision:
    """Central policy for media-cache (poster/proxy) playback (P6).

    FRIEND ACCESS V1: friends are allowed for any resolvable entry."""
    if entry is None:
        return MediaAccessDecision(False, DENY_UNKNOWN_REVISION)
    if user is None or not user.is_active:
        return MediaAccessDecision(False, DENY_NO_OWNER_ACCESS)
    if is_friend_user(user):
        diver_id = resolve_cache_entry_diver_owner(db, entry)
        if diver_id is None:
            # Entry must still resolve to a real asset (unknown entries
            # deny); only the diver binding is skipped for friends.
            asset = db.get(PhotosAsset, entry.photos_asset_id) if entry.photos_asset_id else None
            if asset is None or not asset.video_uuid:
                return MediaAccessDecision(False, DENY_NO_DIVER_CHAIN)
            dive = db.query(Dive).filter(Dive.video_uuid == asset.video_uuid).one_or_none()
            if dive is None:
                return MediaAccessDecision(False, DENY_NO_DIVER_CHAIN)
            return MediaAccessDecision(True, "allowed", None)
        return MediaAccessDecision(True, "allowed", diver_id)
    diver_id = resolve_cache_entry_diver_owner(db, entry)
    if diver_id is None:
        return MediaAccessDecision(False, DENY_NO_DIVER_CHAIN)
    if not user_has_diver_access(db, user.id, diver_id):
        return MediaAccessDecision(False, DENY_NO_OWNER_ACCESS, diver_id)
    return MediaAccessDecision(True, "allowed", diver_id)
