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
    # P10 media-only commit: caption is REQUIRED except when the caller
    # explicitly declares media-only mode in extra (media_only=true with a
    # non-empty media_only_reason). Media bytes and the MediaRevision are
    # committed; NO CaptionRevision is fabricated. The state is recorded as
    # MEDIA_VERIFIED_METADATA_PENDING in the ledger (metadata residuals stay
    # explicit, never hidden behind byte-storage success).
    caption: Optional[CommitCaption] = None
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
    caption_revision_id: Optional[int] = None
    caption_revision_existed: bool = False
    media_only: bool = False
    ingest_state_id: int
    ledger_state: str = "DB_COMMITTED"


class MediaDomainInventoryItem(BaseModel):
    """P10 domain-driven full-corpus inventory row (privacy-safe).

    Inventory authority is the Dive Analyzer DOMAIN graph:
    dives.video_uuid -> dives.video_filename (Photos asset UUID stem) ->
    dives.diver_id. media_revisions are referenced facts, never the
    inventory boundary. video_filename is included deliberately: its stem is
    the deterministic recorded Photos asset identity for the historical era
    (dives.video_uuid alone does not resolve for most historical rows —
    fresh-verified corpus finding); it is a UUID, not human text, and
    contains no captions, no names, no paths."""

    video_uuid: str
    video_filename: Optional[str] = None
    diver_id: Optional[int] = None
    dive_count: int = 1
    media_revision_id: Optional[int] = None
    blob_sha256: Optional[str] = None
    byte_size: int = 0
    rendition_semantics: Optional[str] = None
    verified_prod: bool = False
    verified_dev: bool = False
    prod_object_key: Optional[str] = None
    dev_object_key: Optional[str] = None
    caption_provider: Optional[str] = None
    caption_revision_count: int = 0
