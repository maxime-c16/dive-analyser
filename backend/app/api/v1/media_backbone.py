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


def validate_commit_request(request: MediaBackboneCommitRequest) -> None:
    """Fail-closed validation. Raises HTTPException 422 on any violation."""
    if not UUID_RE.match(request.video_uuid or ""):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="malformed video_uuid",
        )
    if request.environment not in SUPPORTED_ENVIRONMENTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unsupported environment: {request.environment!r}",
        )
    if not request.remote_verified:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="refusing unverified ingest commit",
        )
    if not SHA_RE.match(request.blob_sha256 or ""):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="malformed media sha256",
        )
    if not SHA_RE.match(request.caption_sha256 or ""):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="malformed caption sha256",
        )
    if request.storage_backend != EXPECTED_STORAGE_BACKEND:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"unsupported storage backend {request.storage_backend!r}; "
                f"expected {EXPECTED_STORAGE_BACKEND!r}"
            ),
        )
    bucket = request.bucket.strip().lower()
    allowed_bucket = _environment_bucket(request.environment)
    if not allowed_bucket or bucket != allowed_bucket:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"bucket {request.bucket!r} is not the allowlisted "
                f"{request.environment} bucket"
            ),
        )
    prefix = (
        getattr(get_settings(), "media_backbone_object_prefix", DEFAULT_OBJECT_PREFIX)
        or DEFAULT_OBJECT_PREFIX
    ).strip("/")
    stem, _, ext = request.object_key.rpartition(".")
    candidate = stem if ext and KEY_EXT_RE.match(ext) else request.object_key
    expected = f"{prefix}/{request.blob_sha256[:2]}/{request.blob_sha256}"
    if candidate != expected:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="object key is not the content-addressed key of blob_sha256",
        )


@router.post("/commit", response_model=MediaBackboneCommitResponse)
async def commit_backbone_ingest(
    request: MediaBackboneCommitRequest,
    db: Session = Depends(get_db),
    api_key: dict = Depends(verify_api_key),
) -> MediaBackboneCommitResponse:
    """Persist one verified object-store ingest (idempotent)."""
    del api_key  # authentication enforced by dependency
    validate_commit_request(request)
    try:
        result = commit_verified_ingest(
            db,
            video_uuid=request.video_uuid,
            blob_sha256=request.blob_sha256,
            byte_size=request.byte_size,
            object_key=request.object_key,
            storage_backend=request.storage_backend,
            bucket=request.bucket.strip().lower(),
            caption_raw=request.caption_raw,
            caption_sha=request.caption_sha256,
            caption_provider=request.caption_provider,
            verified=True,
            rendition_semantics=request.rendition_semantics,
            codec=request.codec,
            width=request.width,
            height=request.height,
            duration_seconds=request.duration_seconds,
            photos_edit_fingerprint=request.photos_edit_fingerprint,
            source_provenance=request.source_provenance,
            shadow_provider=request.shadow_provider,
            shadow_raw=request.shadow_raw,
            shadow_sha256=request.shadow_sha256,
            shadow_available=request.shadow_available,
            parser_version=request.parser_version,
            parsed_json=request.parsed_json,
            ingest_impl_version=request.ingest_impl_version,
            environment=request.environment,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return MediaBackboneCommitResponse(environment=request.environment, **result)
