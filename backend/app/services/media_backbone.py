"""Media backbone commit service.

The single write path for verified object-store ingest: idempotent inserts of
content-addressed blobs, media revisions and caption revisions. Re-calling
with the same content returns the existing rows (no duplicates). No endpoint
is wired in this packet; the P2 canary will call this.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models.media_backbone import (
    CaptionRevision,
    IngestObjectState,
    MediaBlob,
    MediaRevision,
)

RENDITION_SEMANTICS_DEFAULT = "photos_edited_rendition"
CAPTION_HASH_ENCODING = "utf-8"


def caption_sha256(persisted_raw: str) -> str:
    """SHA-256 over the exact persisted caption representation (UTF-8 bytes).

    No normalization of any kind is applied before hashing.
    """
    import hashlib

    return hashlib.sha256(persisted_raw.encode(CAPTION_HASH_ENCODING)).hexdigest()


def _validate_sha(sha: str) -> str:
    if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise ValueError(f"malformed sha256: {sha!r}")
    return sha


def commit_verified_ingest(
    db: Session,
    *,
    video_uuid: str,
    blob_sha256: str,
    byte_size: int,
    object_key: str,
    storage_backend: str,
    bucket: str,
    caption_raw: str,
    caption_sha: str,
    caption_provider: str,
    verified: bool = True,
    rendition_semantics: str = RENDITION_SEMANTICS_DEFAULT,
    codec: str | None = None,
    width: int | None = None,
    height: int | None = None,
    duration_seconds: float | None = None,
    photos_edit_fingerprint: str | None = None,
    source_provenance: dict[str, Any] | None = None,
    shadow_provider: str | None = None,
    shadow_raw: str | None = None,
    shadow_sha256: str | None = None,
    shadow_available: bool | None = None,
    parser_version: str | None = None,
    parsed_json: dict[str, Any] | None = None,
    ingest_impl_version: str = "media_backbone_v1",
    environment: str = "dev",
) -> dict[str, Any]:
    if not verified:
        raise ValueError("refusing to commit unverified ingest (roundtrip verification required)")
    _validate_sha(blob_sha256)
    _validate_sha(caption_sha)
    if caption_sha != caption_sha256(caption_raw):
        raise ValueError(
            "caption_sha256 does not match the persisted caption_raw UTF-8 bytes"
        )
    if byte_size <= 0:
        raise ValueError(f"invalid byte_size: {byte_size}")

    blob = db.get(MediaBlob, blob_sha256)
    blob_existed = blob is not None
    if blob is None:
        blob = MediaBlob(
            sha256=blob_sha256,
            byte_size=byte_size,
            codec=codec,
            width=width,
            height=height,
            duration_seconds=(
                Decimal(str(duration_seconds)) if duration_seconds is not None else None
            ),
            rendition_semantics=rendition_semantics,
            storage_backend=storage_backend,
            bucket=bucket,
            object_key=object_key,
            ingest_impl_version=ingest_impl_version,
        )
        db.add(blob)

    media_revision = (
        db.query(MediaRevision)
        .filter_by(video_uuid=video_uuid, blob_sha256=blob_sha256)
        .one_or_none()
    )
    media_revision_existed = media_revision is not None
    if media_revision is None:
        media_revision = MediaRevision(
            video_uuid=video_uuid,
            blob_sha256=blob_sha256,
            photos_edit_fingerprint=photos_edit_fingerprint,
            rendition_semantics=rendition_semantics,
            source_provenance=dict(source_provenance or {}),
            observed_at=datetime.utcnow(),
        )
        db.add(media_revision)

    caption_revision = (
        db.query(CaptionRevision)
        .filter_by(video_uuid=video_uuid, caption_sha256=caption_sha)
        .one_or_none()
    )
    caption_revision_existed = caption_revision is not None
    if caption_revision is None:
        caption_revision = CaptionRevision(
            video_uuid=video_uuid,
            caption_raw=caption_raw,
            caption_sha256=caption_sha,
            caption_provider=caption_provider,
            parser_version=parser_version,
            parsed_json=dict(parsed_json) if parsed_json else None,
            shadow_provider=shadow_provider,
            shadow_raw=shadow_raw,
            shadow_sha256=shadow_sha256,
            shadow_available=shadow_available,
            exact_equal=(
                (shadow_sha256 == caption_sha)
                if (shadow_available and shadow_sha256)
                else None
            ),
            observed_at=datetime.utcnow(),
        )
        db.add(caption_revision)

    state = (
        db.query(IngestObjectState)
        .filter_by(video_uuid=video_uuid, object_key=object_key)
        .one_or_none()
    )
    if state is None:
        state = IngestObjectState(
            video_uuid=video_uuid,
            object_key=object_key,
            state="DB_COMMITTED",
            blob_sha256=blob_sha256,
            caption_sha256=caption_sha,
            verified=verified,
            db_committed_at=datetime.utcnow(),
            environment=environment,
            storage_backend=storage_backend,
        )
        db.add(state)

    db.commit()
    return {
        "video_uuid": video_uuid,
        "blob_sha256": blob.sha256,
        "blob_existed": blob_existed,
        "media_revision_id": media_revision.id,
        "media_revision_existed": media_revision_existed,
        "caption_revision_id": caption_revision.id,
        "caption_revision_existed": caption_revision_existed,
        "ingest_state_id": state.id,
    }
