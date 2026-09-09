"""Media backbone P4 commit endpoint schema.

Flattened, explicit request body for verified object-store ingest commits.
Only verified, already-consistency-checked data is accepted; the router
refuses anything that the commit service would reject.
"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class MediaBackboneCommitRequest(BaseModel):
    video_uuid: str = Field(..., min_length=36, max_length=36)
    ingest_impl_version: str = Field(..., min_length=1, max_length=64)
    rendition_semantics: str = Field(..., min_length=1, max_length=128)
    caption_raw: str
    caption_sha256: str = Field(..., min_length=64, max_length=64)
    caption_provider: str = Field(..., min_length=1, max_length=128)
    blob_sha256: str = Field(..., min_length=64, max_length=64)
    byte_size: int = Field(..., gt=0)
    object_key: str = Field(..., min_length=1, max_length=512)
    storage_backend: str = Field(..., min_length=1, max_length=32)
    bucket: str = Field(..., min_length=1, max_length=128)
    remote_verified: bool
    environment: str = Field(..., min_length=1, max_length=16)

    codec: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration_seconds: Optional[float] = None
    photos_edit_fingerprint: Optional[str] = None
    source_provenance: Optional[dict[str, Any]] = None

    shadow_provider: Optional[str] = None
    shadow_raw: Optional[str] = None
    shadow_sha256: Optional[str] = Field(None, min_length=64, max_length=64)
    shadow_available: Optional[bool] = None

    parser_version: Optional[str] = None
    parsed_json: Optional[dict[str, Any]] = None


class MediaBackboneCommitResponse(BaseModel):
    video_uuid: str
    environment: str
    blob_sha256: str
    blob_existed: bool
    media_revision_id: int
    media_revision_existed: bool
    caption_revision_id: int
    caption_revision_existed: bool
    ingest_state_id: int
