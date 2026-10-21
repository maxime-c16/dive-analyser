"""P6 authenticated B2-default playback grant route.

GET /api/v1/media/revisions/{revision_id}/play

Flow (P6 default-playback architecture; authorization ALWAYS first):

    authenticated session
      → central authorization policy (can_user_access_media)
      → storage source decision (below)
      → either
          (a) B2: verified PROD location + healthy provider
              → presigned GET (short TTL) → HTTP 302 to presigned URL, or
          (b) authenticated legacy fallback: server-side resolution of the
              legacy source (cache rendition or legacy file) streamed from
              the backend with HTTP Range support — the browser NEVER
              receives a legacy URL.

Failure semantics (P6 §13, exact policy):

    AUTH_DENIED (flags off / unauthenticated / wrong owner / unknown
    revision / no diver chain)
        → 401/404. NEVER falls back to legacy. No media-existence
        disclosure.

    NO_PROD_B2_REPLICA (zero verified PROD locations)
        → authorized legacy fallback if a legacy source resolves, else
        uniform 404.

    B2_TEMPORARY_FAILURE (presign unavailable with a verified location)
        → authorized legacy fallback if a legacy source resolves, else
        explicit 503 B2_PROVIDER_FAILURE. Never a redirect.

    B2_INTEGRITY / AUTHORITY_AMBIGUITY (more than one verified PROD
    location, or the single one is not the PROD B2 bucket)
        → FAIL CLOSED 404. No legacy fallback, no signing of an ambiguous
        object.

Authorization denials NEVER reach source selection: wrong owner gets the
same 404 whether the media exists in B2, in legacy storage, or nowhere.

The presigned URL is returned ONLY as a redirect Location — never a JSON
body, never persisted, never logged. Grant ledger rows (privacy-safe:
ids/outcomes/TTL only) plus the in-process playback metrics feed the P6
cohort observation.
"""

import asyncio
import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.media_backbone import MediaBlobLocation, MediaRevision
from app.models.user_auth import AppUser, MediaPlaybackGrant
from app.api.v1.auth import get_current_user
from app.services import b2_presign, legacy_media, playback_metrics
from app.services.offload import run_to_completion
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
OUTCOME_LEGACY_FALLBACK = "LEGACY_FALLBACK"

DENY_STORAGE_NOT_FOUND = "storage_not_found"
DENY_STORAGE_AMBIGUOUS = "storage_ambiguous"
DENY_STORAGE_UNVERIFIED = "storage_unverified"

metrics = playback_metrics.get_playback_metrics()


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

    - zero verified PROD locations  → (None, storage_not_found)
    - more than one verified PROD location → (None, storage_ambiguous)
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
        # Bounded probe: 0 -> missing, 1 -> candidate, >= 2 -> ambiguous.
        # We only need to distinguish 0/1/many, never the full replica set.
        .limit(2)
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
    """Bounded listing: media revisions the current user may access.

    Privacy-safe: ids, source availability booleans and coarse ids only.
    ``b2_ready`` reports a single verified PROD B2 location (the P5 cohort
    rule); ``legacy_available`` reports whether an authorized legacy
    source resolves — used by the P6 default-playback cohort to record the
    per-revision source decision without exposing storage identities.
    """
    if not _flags_enabled():
        raise HTTPException(404, "Not found")
    revisions = db.query(MediaRevision).order_by(MediaRevision.id.desc()).all()
    out = []
    for revision in revisions:
        decision = can_user_access_media(db, user, revision)
        if not decision.allowed:
            continue
        location, _deny = _resolve_verified_prod_location(db, revision)
        legacy_source = legacy_media.resolve_legacy_media_source(db, revision)
        out.append(
            {
                "media_revision_id": revision.id,
                "video_uuid": revision.video_uuid,
                "storage_location_id": location.id if location else None,
                "b2_ready": location is not None,
                "legacy_available": legacy_source is not None,
            }
        )
    return {"revisions": out}


def _deny(db: Session, user_id: int, revision_id: int, reason: str):
    _record_grant(
        db,
        user_id=user_id,
        outcome=OUTCOME_DENIED,
        media_revision_id=revision_id,
        denial_reason=reason,
    )
    metrics.denied.inc()
    raise HTTPException(404, "Not found")


def _is_derivative_revision(revision: MediaRevision | None) -> bool:
    """Whether this revision carries durable-derivative bytes (D5).

    Derived revisions are served ONLY from their verified PROD B2
    replica. Falling back to a legacy cache file would hand the browser
    mislabeled bytes (e.g. a 720p proxy at an HQ URL), so the legacy
    fallback never applies to them: missing storage is a uniform 404,
    a presign failure an explicit 503.
    """
    from app.services.media_backbone import is_derived_rendition_semantics

    return revision is not None and is_derived_rendition_semantics(
        getattr(revision, "rendition_semantics", None)
    )


def _has_current_derivative_proof(db: Session, revision: MediaRevision) -> bool:
    """Authoritative current-source/version/ready PROD proof (D5).

    A derived revision is servable ONLY when the shared resolver reports
    the SAME revision id as ready for the clip's CURRENT canonical
    camera-original source SHA + current transform version with exactly
    one verified PROD location. A direct request for a known revision
    whose source has since drifted, whose transform version is stale, or
    whose ledger row left ``ready`` (verifying/stale/superseded) fails
    here even though the revision row itself still carries bytes and may
    still have a verified location: the status contract would no longer
    advertise this URL, so the play route must not honor it either.

    Runs AFTER authorization but BEFORE any location signing or ALLOWED
    grant: denials are uniform 404 with zero presign calls. Posters and
    the small-source HQ alias are covered the same way (the alias shares
    the light revision id, so it passes exactly when light is provable).
    A pre-D1 database (no ledger table) yields no proof and fails closed.
    """
    from app.services.derivative_read import safe_resolve_clip_derivatives
    from app.services.derivative_publisher import MissingSourceError

    try:
        clip = safe_resolve_clip_derivatives(db, revision.video_uuid)
    except (MissingSourceError, ValueError):
        return False
    if clip is None:
        return False
    return any(
        decision.state == "ready" and decision.revision_id == revision.id
        for decision in clip.roles.values()
    )


async def _serve_legacy_fallback(
    db: Session,
    request: Request,
    revision: MediaRevision,
    user_id: int,
    reason: str,
):
    """Authorized legacy playback, streamed server-side with Range."""
    # Resolution probes the filesystem (os.path.exists/stat per candidate)
    # against the request session; keep it off the loop and let it finish
    # even when the awaiting handler is cancelled mid-way.
    source = await run_to_completion(asyncio.to_thread(
        legacy_media.resolve_legacy_media_source, db, revision
    ))
    if source is None:
        metrics.legacy_fallback_failures.inc()
        if reason == "presign_unavailable":
            # B2 temporary failure with no legacy copy: explicit provider
            # failure, never a redirect, never an unauthenticated URL.
            _record_grant(
                db,
                user_id=user_id,
                outcome=OUTCOME_PROVIDER_FAILURE,
                media_revision_id=revision.id,
                denial_reason=reason,
            )
            raise HTTPException(503, "B2 provider unavailable")
        # No authorized source at all (e.g. DEV-only replica, no legacy
        # copy): uniform deny, recorded in the ledger for the cohort view.
        _record_grant(
            db,
            user_id=user_id,
            outcome=OUTCOME_DENIED,
            media_revision_id=revision.id,
            denial_reason=reason,
        )
        raise HTTPException(404, "Not found")

    _record_grant(
        db,
        user_id=user_id,
        outcome=OUTCOME_LEGACY_FALLBACK,
        media_revision_id=revision.id,
        denial_reason=reason,
    )
    metrics.legacy_fallback_selected.inc()
    path, content_type = source
    from app.api.v1.media import _serve_media_file

    response = _serve_media_file(Path(path), content_type, request)
    _secure_headers(response)
    if request.headers.get("range"):
        metrics.range_successes.inc()
    return response


@router.get("/revisions/{revision_id}/play")
async def play_media_revision(
    revision_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: AppUser = Depends(get_current_user),
):
    if not _flags_enabled():
        # Feature flags OFF: fail closed, route invisible.
        raise HTTPException(404, "Not found")

    metrics.requests_total.inc()
    revision = db.get(MediaRevision, revision_id)
    decision = can_user_access_media(db, user, revision)
    if not decision.allowed:
        # AUTH_DENIED: uniform 404 for every denial family. Fallback can
        # never be reached from here (wrong owner + B2 copy, wrong owner +
        # legacy copy, unknown revision → DENY alike).
        _deny(db, user.id, revision_id, decision.reason)

    derived_only = _is_derivative_revision(revision)
    if derived_only and not _has_current_derivative_proof(db, revision):
        # The revision is no longer (or never was) the current PROD proof
        # for its clip: stale source, wrong transform version, non-ready
        # ledger, or missing/ambiguous/DEV-only storage. Uniform 404 with
        # zero presign calls and no legacy fallback (derived bytes must
        # never be substituted with cache bytes at a stable revision URL).
        _deny(db, user.id, revision.id, "derivative_not_current")

    lookup_started = playback_metrics.now_ms()
    location, storage_deny = _resolve_verified_prod_location(db, revision)
    metrics.storage_lookup_latency.observe(playback_metrics.now_ms() - lookup_started)

    if location is None:
        if storage_deny == DENY_STORAGE_AMBIGUOUS or derived_only:
            # B2_INTEGRITY/AMBIGUITY: fail closed. Never sign an ambiguous
            # object; never fall back from an integrity fault. Derived
            # revisions additionally never fall back to legacy cache bytes
            # (they would be mislabeled renditions at a stable URL).
            _deny(db, user.id, revision.id, storage_deny)
        # NO_PROD_B2_REPLICA: authorized legacy fallback.
        return await _serve_legacy_fallback(
            db, request, revision, user.id, reason=storage_deny
        )

    try:
        # P6 §13/§29: verify the playback credential is actually usable at
        # grant time. boto3 presigning is a LOCAL operation and would happily
        # sign with an invalid/revoked credential; the provider-side HEAD
        # turns that into B2_TEMPORARY_FAILURE (→ authorized legacy
        # fallback) instead of handing the browser a dead URL.
        # The HEAD is a real network round-trip to the provider; run it off
        # the event loop so a provider hiccup cannot stall every other
        # request handled by this worker.
        head_started = playback_metrics.now_ms()
        await run_to_completion(asyncio.to_thread(
            b2_presign.head_object,
            bucket=location.bucket,
            object_key=location.object_key,
        ))
        metrics.presign_latency.observe(playback_metrics.now_ms() - head_started)
        presign_started = playback_metrics.now_ms()
        presign = b2_presign.presign_get(
            bucket=location.bucket,
            object_key=location.object_key,
            storage_location_id=location.id,
        )
        metrics.presign_latency.observe(playback_metrics.now_ms() - presign_started)
    except b2_presign.PresignUnavailable:
        # B2_TEMPORARY_FAILURE: authorized legacy fallback when available,
        # else explicit provider failure. Derived revisions never take the
        # legacy path (mislabeled bytes): explicit 503 instead.
        metrics.provider_failures.inc()
        if derived_only:
            _record_grant(
                db,
                user_id=user.id,
                outcome=OUTCOME_PROVIDER_FAILURE,
                media_revision_id=revision.id,
                denial_reason="presign_unavailable",
            )
            raise HTTPException(503, "B2 provider unavailable")
        return await _serve_legacy_fallback(
            db, request, revision, user.id, reason="presign_unavailable"
        )

    if (
        db.query(MediaPlaybackGrant)
        .filter_by(
            user_id=user.id,
            media_revision_id=revision.id,
            outcome=OUTCOME_ALLOWED,
        )
        .first()
        is not None
    ):
        metrics.grant_refreshes.inc()

    _record_grant(
        db,
        user_id=user.id,
        outcome=OUTCOME_ALLOWED,
        media_revision_id=revision.id,
        storage_location_id=location.id,
        ttl_seconds=presign.ttl_seconds,
    )
    metrics.authorized.inc()
    metrics.b2_selected.inc()
    redirect = RedirectResponse(url=presign.url, status_code=302)
    _secure_headers(redirect)
    return redirect


@router.get("/playback/metrics")
async def playback_metrics_endpoint(
    db: Session = Depends(get_db),
    user: AppUser = Depends(get_current_user),
):
    """Privacy-safe playback counters (authenticated users only)."""
    if not _flags_enabled():
        raise HTTPException(404, "Not found")
    snapshot = metrics.snapshot()
    # P9 §41: durable aggregation from the grant ledger (survives restart).
    from app.services.ops_metrics import durable_ops_snapshot

    snapshot["durable"] = durable_ops_snapshot(db)
    return snapshot
