"""P5 authenticated B2 playback grant route.

GET /api/v1/media/revisions/{revision_id}/play

Flow (accelerated V1 architecture, verified rather than assumed):
    authenticated session
      → central authorization policy (can_user_access_media)
      → verified PROD storage-location resolution (P4.3 authority)
      → B2 presigned GET (short TTL)
      → HTTP 302, Location = presigned URL

The browser receives the presigned URL ONLY as the redirect target; it is
never returned in a JSON body, never persisted, never logged. The redirect
response carries Cache-Control: private, no-store and
Referrer-Policy: no-referrer.

Fail-closed policy (no legacy fallback inside this route):
- auth/feature flag off, unknown revision, unauthenticated, wrong owner,
  missing/DEV/unverified/ambiguous location → 401/404 (deny)
- authorization denial NEVER falls back to unauthenticated legacy playback
- B2/presign provider failure → 503 with explicit provider-failure body
  (B2_PROVIDER_FAILURE family), never a redirect to an arbitrary location

Grant ledger rows (privacy-safe: ids, outcomes, TTL only — never a URL)
feed the P5 cohort metrics.
"""

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.media_backbone import MediaBlobLocation, MediaRevision
from app.models.user_auth import AppUser, MediaPlaybackGrant
from app.api.v1.auth import get_current_user
from app.services import b2_presign
from app.services.user_access import (
    DENY_NO_DIVER_CHAIN,
    DENY_NO_OWNER_ACCESS,
    DENY_UNKNOWN_REVISION,
    can_user_access_media,
)

router = APIRouter(prefix="/media", tags=["media-playback"])

OUTCOME_ALLOWED = "ALLOWED"
OUTCOME_DENIED = "DENIED"
OUTCOME_PROVIDER_FAILURE = "PROVIDER_FAILURE"

DENY_STORAGE_NOT_FOUND = "storage_not_found"
DENY_STORAGE_AMBIGUOUS = "storage_ambiguous"
DENY_STORAGE_UNVERIFIED = "storage_unverified"


def _secure_headers(response) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"


def _flags_enabled() -> bool:
    settings = get_settings()
    return bool(
        settings.user_auth_enabled and settings.b2_playback_canary_enabled
    )


def _record_grant(
    db: Session,
    user_id: int,
    outcome: str,
    media_revision_id=None,
    storage_location_id=None,
    denial_reason=None,
    ttl_seconds=None,
) -> None:
    db.add(
        MediaPlaybackGrant(
            user_id=user_id,
            media_revision_id=media_revision_id,
            storage_location_id=storage_location_id,
            outcome=outcome,
            denial_reason=denial_reason,
            ttl_seconds=ttl_seconds,
        )
    )
    db.commit()


def _resolve_verified_prod_location(
    db: Session, revision: MediaRevision
):
    """P4.3 storage authority: exactly one verified PROD replica or deny.

    - zero verified PROD locations  → DENY (not found / unverified)
    - more than one verified PROD location → DENY (ambiguous)
    - the single location must be backend=b2 and bucket=diveanalyzer-prod-media
      (environment=prod by construction of the verified-PROD query)
    """
    settings = get_settings()
    locations = (
        db.query(MediaBlobLocation)
        .filter_by(
            blob_sha256=revision.blob_sha256,
            environment="prod",
            verified=True,
        )
        .all()
    )
    if len(locations) == 0:
        return None, DENY_STORAGE_NOT_FOUND
    if len(locations) > 1:
        return None, DENY_STORAGE_AMBIGUOUS
    location = locations[0]
    if (
        (location.storage_backend or "").lower() != "b2"
        or (location.bucket or "").strip().lower()
        != (settings.media_backbone_prod_bucket or "").strip().lower()
    ):
        return None, DENY_STORAGE_NOT_FOUND
    return location, None


@router.get("/playback/canary/revisions")
async def list_canary_revisions(
    db: Session = Depends(get_db),
    user: AppUser = Depends(get_current_user),
):
    """Bounded canary listing: media revisions the current user may access
    AND that resolve to exactly one verified PROD location (the P5 cohort).
    Privacy-safe: ids and coarse dive metadata only."""
    if not _flags_enabled():
        raise HTTPException(404, "Not found")
    revisions = db.query(MediaRevision).order_by(MediaRevision.id.desc()).all()
    out = []
    for revision in revisions:
        decision = can_user_access_media(db, user, revision)
        if not decision.allowed:
            continue
        location, _deny = _resolve_verified_prod_location(db, revision)
        if location is None:
            continue
        out.append(
            {
                "media_revision_id": revision.id,
                "video_uuid": revision.video_uuid,
                "storage_location_id": location.id,
            }
        )
    return {"revisions": out}


@router.get("/revisions/{revision_id}/play")
async def play_media_revision(
    revision_id: int,
    response: Response,
    db: Session = Depends(get_db),
    user: AppUser = Depends(get_current_user),
):
    if not _flags_enabled():
        # Feature flags OFF: fail closed, route invisible.
        raise HTTPException(404, "Not found")

    revision = db.get(MediaRevision, revision_id)
    decision = can_user_access_media(db, user, revision)
    if not decision.allowed:
        _record_grant(
            db,
            user_id=user.id,
            outcome=OUTCOME_DENIED,
            media_revision_id=revision_id,
            denial_reason=decision.reason,
        )
        if decision.reason == DENY_UNKNOWN_REVISION:
            # Uniform 404: no existence disclosure for unknown revisions.
            raise HTTPException(404, "Not found")
        if decision.reason == DENY_NO_DIVER_CHAIN:
            # Media exists but has no trusted owner chain: deny without
            # disclosing media identity.
            raise HTTPException(404, "Not found")
        # Wrong owner / no explicit access: uniform 404, no media-existence
        # disclosure beyond the shared generic body.
        raise HTTPException(404, "Not found")

    location, storage_deny = _resolve_verified_prod_location(db, revision)
    if location is None:
        _record_grant(
            db,
            user_id=user.id,
            outcome=OUTCOME_DENIED,
            media_revision_id=revision.id,
            denial_reason=storage_deny,
        )
        raise HTTPException(404, "Not found")

    try:
        presign = b2_presign.presign_get(
            bucket=location.bucket,
            object_key=location.object_key,
            storage_location_id=location.id,
        )
    except b2_presign.PresignUnavailable:
        _record_grant(
            db,
            user_id=user.id,
            outcome=OUTCOME_PROVIDER_FAILURE,
            media_revision_id=revision.id,
            storage_location_id=location.id,
            denial_reason="presign_unavailable",
        )
        # Explicit provider failure — never a redirect, never a legacy
        # fallback, never an arbitrary Location.
        raise HTTPException(503, "B2 provider unavailable")

    _record_grant(
        db,
        user_id=user.id,
        outcome=OUTCOME_ALLOWED,
        media_revision_id=revision.id,
        storage_location_id=location.id,
        ttl_seconds=presign.ttl_seconds,
    )
    redirect = RedirectResponse(url=presign.url, status_code=302)
    _secure_headers(redirect)
    return redirect
