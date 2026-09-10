"""Media backbone P4 commit endpoint schema.

Accepts the canonical verified-ingest document shape used since P2:
{"payload": {video_uuid, caption{...}, blob{...}, ...}, "extra": {...}}.
Only verified, already-consistency-checked data is accepted; the router
re-validates every invariant before delegating to commit_verified_ingest.
"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class CommitCaption(BaseModel):
    raw: str
    sha256: str = Field(..., min_length=64, max_length=64)
    provider: str = Field(..., min_length=1, max_length=128)


class CommitBlob(BaseModel):
    sha256: str = Field(..., min_length=64, max_length=64)
    byte_size: int = Field(..., gt=0)
    object_key: str = Field(..., min_length=1, max_length=512)
    storage_backend: str = Field(..., min_length=1, max_length=32)
    bucket: str = Field(..., min_length=1, max_length=128)


class CommitPayload(BaseModel):
    video_uuid: str = Field(..., min_length=36, max_length=36)
    ingest_impl_version: str = Field(..., min_length=1, max_length=64)
    rendition_semantics: str = Field(..., min_length=1, max_length=128)
    caption: CommitCaption
    blob: CommitBlob
    remote_verified: bool


class MediaBackboneCommitRequest(BaseModel):
    """The staged verified-ingest document: payload + extra metadata."""

    payload: CommitPayload
    extra: dict[str, Any] = Field(default_factory=dict)


class MediaMigrationInventoryItem(BaseModel):
    """P7 historical-migration inventory row (privacy-safe).

    No captions, no filenames, no human-readable media text: identity +
    storage facts only. The DB/domain graph defines the migration queue."""

    media_revision_id: int
    video_uuid: str
    blob_sha256: str
    byte_size: int
    rendition_semantics: str
    verified_prod: bool
    verified_dev: bool
    prod_object_key: Optional[str] = None
    dev_object_key: Optional[str] = None
    owner_diver: bool
    has_diver_chain: bool
    diver_id: Optional[int] = None
    caption_provider: Optional[str] = None
    blob_created_at: Optional[str] = None


class MediaBackboneCommitResponse(BaseModel):
    video_uuid: str
    environment: str
    blob_sha256: str
    blob_existed: bool
    media_blob_location_id: int
    blob_location_existed: bool
    media_revision_id: int
    media_revision_existed: bool
    caption_revision_id: int
    caption_revision_existed: bool
    ingest_state_id: int
