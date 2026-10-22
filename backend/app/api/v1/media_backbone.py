"""Media backbone P4: authenticated commit endpoint.

POST /api/v1/media/backbone/commit — the production-safe replacement for the
P2/P3 operator-tunneled commit transport. The Mac production agent posts the
verified ingest document here with the existing X-API-Key machine credential;
the endpoint re-validates every invariant and delegates to
commit_verified_ingest (idempotent; repeated identical commits return the
same logical result with zero duplicate rows).

Security properties:
- existing agent API-key authentication (no public endpoint)
- environment/bucket firewall: DEV and PROD references never alias silently
- storage backend identity check
- object key must be the content-addressed key of the blob SHA
- unverified media, caption hash mismatch, malformed identifiers: 422
"""

import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.schemas.media_backbone import (
    MediaBackboneCommitRequest,
    MediaBackboneCommitResponse,
    MediaDomainInventoryItem,
    MediaMigrationInventoryItem,
)
from app.security import verify_api_key
from app.services.media_backbone import commit_verified_ingest
from app.models.media_backbone import MediaBlob, MediaBlobLocation, MediaRevision
from app.models.media_backbone import CaptionRevision
from app.models.user_auth import UserDiverAccess

router = APIRouter(prefix="/media/backbone", tags=["media-backbone"])

UUID_RE = re.compile(
    r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
)
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
SUPPORTED_ENVIRONMENTS = ("dev", "prod")
EXPECTED_STORAGE_BACKEND = "b2"
DEFAULT_OBJECT_PREFIX = "blobs/sha256"
KEY_EXT_RE = re.compile(r"^[a-z0-9]{1,8}$")


def _environment_bucket(environment: str) -> str:
    settings = get_settings()
    if environment == "prod":
        return (settings.media_backbone_prod_bucket or "").strip().lower()
    return (settings.media_backbone_dev_bucket or "").strip().lower()


def validate_commit_request(request: MediaBackboneCommitRequest) -> tuple[str, str, str | None]:
    """Fail-closed validation. Raises HTTPException 422 on any violation.

    Returns (environment, blob_sha256, caption_sha256) for the caller.
    caption_sha256 is None only in explicit media-only mode (P10).
    """
    payload = request.payload
    extra = request.extra
    if not UUID_RE.match(payload.video_uuid or ""):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="malformed video_uuid",
        )
    environment = str(extra.get("environment", "")).strip().lower()
    if environment not in SUPPORTED_ENVIRONMENTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unsupported or missing environment in extra: {environment!r}",
        )
    if not payload.remote_verified:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="refusing unverified ingest commit",
        )
    if not SHA_RE.match(payload.blob.sha256 or ""):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="malformed media sha256",
        )
    media_only = bool(extra.get("media_only", False))
    if media_only:
        reason = str(extra.get("media_only_reason", "")).strip()
        if not reason:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="media_only commit requires a non-empty media_only_reason",
            )
        if payload.caption is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="media_only commit must not carry caption data",
            )
        caption_sha = None
    else:
        if payload.caption is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="caption authority required unless media_only mode is declared",
            )
        if not SHA_RE.match(payload.caption.sha256 or ""):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="malformed caption sha256",
            )
        caption_sha = payload.caption.sha256
    if payload.blob.storage_backend != EXPECTED_STORAGE_BACKEND:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"unsupported storage backend {payload.blob.storage_backend!r}; "
                f"expected {EXPECTED_STORAGE_BACKEND!r}"
            ),
        )
    bucket = payload.blob.bucket.strip().lower()
    allowed_bucket = _environment_bucket(environment)
    if not allowed_bucket or bucket != allowed_bucket:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"bucket {payload.blob.bucket!r} is not the allowlisted "
                f"{environment} bucket"
            ),
        )
    prefix = (
        getattr(get_settings(), "media_backbone_object_prefix", DEFAULT_OBJECT_PREFIX)
        or DEFAULT_OBJECT_PREFIX
    ).strip("/")
    stem, _, ext = payload.blob.object_key.rpartition(".")
    candidate = stem if ext and KEY_EXT_RE.match(ext) else payload.blob.object_key
    expected = f"{prefix}/{payload.blob.sha256[:2]}/{payload.blob.sha256}"
    if candidate != expected:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="object key is not the content-addressed key of blob_sha256",
        )
    return environment, payload.blob.sha256, caption_sha


@router.post("/commit", response_model=MediaBackboneCommitResponse)
async def commit_backbone_ingest(
    request: MediaBackboneCommitRequest,
    db: Session = Depends(get_db),
    api_key: dict = Depends(verify_api_key),
) -> MediaBackboneCommitResponse:
    """Persist one verified object-store ingest (idempotent)."""
    del api_key  # authentication enforced by dependency
    environment, _media_sha, _caption_sha = validate_commit_request(request)
    payload = request.payload
    extra = request.extra
    media_only = bool(extra.get("media_only", False))
    try:
        result = commit_verified_ingest(
            db,
            video_uuid=payload.video_uuid,
            blob_sha256=payload.blob.sha256,
            byte_size=payload.blob.byte_size,
            object_key=payload.blob.object_key,
            storage_backend=payload.blob.storage_backend,
            bucket=payload.blob.bucket.strip().lower(),
            caption_raw=payload.caption.raw if payload.caption else None,
            caption_sha=payload.caption.sha256 if payload.caption else None,
            caption_provider=payload.caption.provider if payload.caption else None,
            verified=True,
            media_only=media_only,
            media_only_reason=str(extra.get("media_only_reason", "")) if media_only else None,
            rendition_semantics=payload.rendition_semantics,
            codec=extra.get("codec"),
            width=extra.get("width"),
            height=extra.get("height"),
            duration_seconds=extra.get("duration_seconds"),
            photos_edit_fingerprint=extra.get("photos_edit_fingerprint"),
            source_provenance=extra.get("source_provenance"),
            shadow_provider=extra.get("shadow_provider"),
            shadow_raw=extra.get("shadow_raw"),
            shadow_sha256=extra.get("shadow_sha256"),
            shadow_available=extra.get("shadow_available"),
            parser_version=extra.get("parser_version"),
            parsed_json=extra.get("parsed_json"),
            ingest_impl_version=payload.ingest_impl_version,
            environment=environment,
            commit=False,
        )
        from app.services.automatic_packages import queue_after_verified_original
        queue_after_verified_original(db, payload.video_uuid, result["media_revision_id"], environment)
        db.commit()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return MediaBackboneCommitResponse(**result)




@router.get(
    "/migration/inventory",
    response_model=list[MediaMigrationInventoryItem],
)
async def migration_inventory(
    db: Session = Depends(get_db),
    api_key: dict = Depends(verify_api_key),
) -> list[MediaMigrationInventoryItem]:
    """P7 historical migration inventory (agent-key gated, read-only).

    The DB/domain graph defines the migration queue: every MediaRevision whose
    deterministic chain MediaRevision.video_uuid -> dives (UNIQUE) -> diver
    resolves, annotated with verified storage locations and OWNER-binding
    facts. No captions, no filenames, no Photos crawl: agent-side source
    classification uses ONLY these storage facts. An unresolved chain is
    reported as has_diver_chain=False (agent-side QUARANTINE class E) — never
    guessed, never silently dropped.
    """
    del api_key  # authentication enforced by dependency

    from app.models.dive import Dive

    owner_diver_ids = {
        row[0]
        for row in db.execute(
            select(UserDiverAccess.diver_id).where(
                UserDiverAccess.access_kind == "OWNER"
            )
        ).all()
    }
    dives_by_video_uuid = dict(
        db.query(Dive.video_uuid, Dive.diver_id).all()
    )
    blobs = {b.sha256: b for b in db.query(MediaBlob).all()}
    locations = {
        (loc.blob_sha256, loc.environment): loc
        for loc in db.query(MediaBlobLocation).all()
    }
    latest_caption_provider = {
        cr.video_uuid: cr.caption_provider
        for cr in db.query(CaptionRevision).order_by(CaptionRevision.id).all()
    }

    items: list[MediaMigrationInventoryItem] = []
    revisions = db.query(MediaRevision).order_by(MediaRevision.id).all()
    for revision in revisions:
        blob = blobs.get(revision.blob_sha256)
        prod_loc = locations.get((revision.blob_sha256, "prod"))
        dev_loc = locations.get((revision.blob_sha256, "dev"))
        diver_id = dives_by_video_uuid.get(revision.video_uuid)
        items.append(
            MediaMigrationInventoryItem(
                media_revision_id=revision.id,
                video_uuid=revision.video_uuid,
                blob_sha256=revision.blob_sha256,
                byte_size=blob.byte_size if blob else 0,
                rendition_semantics=revision.rendition_semantics or "",
                verified_prod=bool(prod_loc is not None and prod_loc.verified),
                verified_dev=bool(dev_loc is not None and dev_loc.verified),
                prod_object_key=prod_loc.object_key if prod_loc else None,
                dev_object_key=dev_loc.object_key if dev_loc else None,
                owner_diver=(
                    diver_id in owner_diver_ids if diver_id is not None else False
                ),
                has_diver_chain=diver_id is not None,
                diver_id=diver_id,
                caption_provider=latest_caption_provider.get(revision.video_uuid),
                blob_created_at=(
                    blob.created_at.isoformat()
                    if blob is not None and blob.created_at
                    else None
                ),
            )
        )
    return items


@router.get(
    "/migration/domain_inventory",
    response_model=list[MediaDomainInventoryItem],
)
async def domain_migration_inventory(
    db: Session = Depends(get_db),
    api_key: dict = Depends(verify_api_key),
) -> list[MediaDomainInventoryItem]:
    """P10 FULL-CORPUS domain inventory (agent-key gated, read-only).

    Inventory authority is the Dive Analyzer DOMAIN graph — every dive row
    bearing a video_uuid, deduplicated to DISTINCT video_uuid identities —
    NOT the media_revisions table (which covered only 15 historical items).
    Each row reports: identity (video_uuid), the recorded Photos asset
    identity stem (video_filename), the diver set, and any existing
    backbone facts (MediaRevision/blob/locations/captions).

    video_filename is a recorded UUID string (the historical exporter named
    renditions after the Photos asset); it is the deterministic
    source-resolution key for the historical era and carries no human text,
    no captions and no PII. Ownership/access is NEVER granted by this
    endpoint: storage existence != authorization.
    """
    del api_key  # authentication enforced by dependency

    from app.models.dive import Dive
    from sqlalchemy import func

    blobs = {b.sha256: b for b in db.query(MediaBlob).all()}
    latest_loc = {}
    for loc in db.query(MediaBlobLocation).order_by(MediaBlobLocation.id).all():
        latest_loc[(loc.blob_sha256, loc.environment)] = loc
    caption_counts: dict[str, int] = {}
    caption_providers: dict[str, str] = {}
    for cr in db.query(CaptionRevision).order_by(CaptionRevision.id).all():
        caption_counts[cr.video_uuid] = caption_counts.get(cr.video_uuid, 0) + 1
        caption_providers[cr.video_uuid] = cr.caption_provider
    revisions_by_uuid = {
        r.video_uuid: r
        for r in db.query(MediaRevision).order_by(MediaRevision.id).all()
    }

    rows = (
        db.query(
            Dive.video_uuid,
            Dive.video_filename,
            Dive.diver_id,
            func.count(Dive.id),
        )
        .filter(Dive.video_uuid.isnot(None))
        .group_by(Dive.video_uuid, Dive.video_filename, Dive.diver_id)
        .all()
    )

    items: list[MediaDomainInventoryItem] = []
    for video_uuid, video_filename, diver_id, count in rows:
        revision = revisions_by_uuid.get(video_uuid)
        blob = blobs.get(revision.blob_sha256) if revision else None
        prod_loc = (
            latest_loc.get((revision.blob_sha256, "prod")) if revision else None
        )
        dev_loc = (
            latest_loc.get((revision.blob_sha256, "dev")) if revision else None
        )
        items.append(
            MediaDomainInventoryItem(
                video_uuid=video_uuid,
                video_filename=video_filename,
                diver_id=diver_id,
                dive_count=int(count),
                media_revision_id=revision.id if revision else None,
                blob_sha256=revision.blob_sha256 if revision else None,
                byte_size=blob.byte_size if blob else 0,
                rendition_semantics=(
                    revision.rendition_semantics if revision else None
                ),
                verified_prod=bool(
                    prod_loc is not None and prod_loc.verified
                ),
                verified_dev=bool(dev_loc is not None and dev_loc.verified),
                prod_object_key=prod_loc.object_key if prod_loc else None,
                dev_object_key=dev_loc.object_key if dev_loc else None,
                caption_provider=caption_providers.get(video_uuid),
                caption_revision_count=caption_counts.get(video_uuid, 0),
            )
        )
    return items


@router.get(
    "/migration/dive_caption/{video_uuid}",
)
async def dive_raw_caption(
    video_uuid: str,
    db: Session = Depends(get_db),
    api_key: dict = Depends(verify_api_key),
) -> dict:
    """P10 G-class tie-break helper (agent-key gated, read-only, per-item).

    Returns ONLY the dive's recorded raw_caption for ONE video_uuid (the
    exact provider string the historical extractor parsed). Used by the P10
    engine solely for the DETERMINISTIC caption-equality identity tie-break
    when dives.video_uuid and dives.video_filename resolve to two DIFFERENT
    Photos assets (same capture exported twice). Never used to manufacture
    caption data for a CaptionRevision (P10 §21: caption authority stays the
    fresh provider read). The generic domain inventory remains caption-free.
    """
    del api_key  # authentication enforced by dependency

    from app.models.dive import Dive

    row = (
        db.query(Dive.raw_caption)
        .filter(Dive.video_uuid == video_uuid)
        .first()
    )
    return {"video_uuid": video_uuid, "raw_caption": row[0] if row else None}
