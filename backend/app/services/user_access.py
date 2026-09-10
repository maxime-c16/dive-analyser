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
from app.models.media_backbone import MediaRevision
from app.models.user_auth import AppUser, UserDiverAccess

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


def can_user_access_media(
    db: Session, user: AppUser, media_revision: Optional[MediaRevision]
) -> MediaAccessDecision:
    """THE central P5 authorization policy. Every playback resolution goes
    through this function; no route may bypass it."""
    if media_revision is None:
        return MediaAccessDecision(False, DENY_UNKNOWN_REVISION)
    if user is None or not user.is_active:
        return MediaAccessDecision(False, DENY_NO_OWNER_ACCESS)
    diver_id = resolve_media_diver_owner(db, media_revision)
    if diver_id is None:
        return MediaAccessDecision(False, DENY_NO_DIVER_CHAIN)
    if not user_has_diver_access(db, user.id, diver_id):
        return MediaAccessDecision(False, DENY_NO_OWNER_ACCESS, diver_id)
    return MediaAccessDecision(True, "allowed", diver_id)
