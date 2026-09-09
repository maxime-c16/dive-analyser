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
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.schemas.media_backbone import (
    MediaBackboneCommitRequest,
    MediaBackboneCommitResponse,
)
from app.security import verify_api_key
from app.services.media_backbone import commit_verified_ingest

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


def validate_commit_request(request: MediaBackboneCommitRequest) -> tuple[str, str, str]:
    """Fail-closed validation. Raises HTTPException 422 on any violation.

    Returns (environment, blob_sha256, caption_sha256) for the caller.
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
    if not SHA_RE.match(payload.caption.sha256 or ""):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="malformed caption sha256",
        )
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
    return environment, payload.blob.sha256, payload.caption.sha256


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
    try:
        result = commit_verified_ingest(
            db,
            video_uuid=payload.video_uuid,
            blob_sha256=payload.blob.sha256,
            byte_size=payload.blob.byte_size,
            object_key=payload.blob.object_key,
            storage_backend=payload.blob.storage_backend,
            bucket=payload.blob.bucket.strip().lower(),
            caption_raw=payload.caption.raw,
            caption_sha=payload.caption.sha256,
            caption_provider=payload.caption.provider,
            verified=True,
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
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return MediaBackboneCommitResponse(**result)
