"""
Pydantic schemas for video sync API.

Defines request/response contracts for:
- Single video sync: POST /api/v1/videos/sync
- Batch video sync: POST /api/v1/videos/batch
- Phase-aware scoring with backwards compatibility
"""

from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, validator


class TwoPhaseScore(BaseModel):
    """Two-phase dive scoring (Phase 1: Hurdle+Flight, Phase 2: Opening+Entry)"""

    phase1_performance: Optional[str] = Field(
        None,
        pattern="^[FBMGP]$",
        description="Phase 1 (Hurdle + Flight) performance: F/B/M/G/P"
    )
    phase2_performance: Optional[str] = Field(
        None,
        pattern="^[FBMGP]$",
        description="Phase 2 (Opening + Entry) performance: F/B/M/G/P"
    )

    @validator('phase1_performance', 'phase2_performance')
    def validate_performance(cls, v):
        if v is None:
            return v
        if v not in ['F', 'B', 'M', 'G', 'P']:
            raise ValueError(f"Invalid performance level: {v}")
        return v


class VideoSyncRequest(BaseModel):
    """Request to sync single video metadata"""

    dive_code: str = Field(
        ...,
        min_length=4,
        max_length=5,
        pattern="^\\d{3,4}[ABCDabcd]$",
        description="FINA dive code (e.g., 101B, 5231D)"
    )
    height: str = Field(
        ...,
        pattern="^\\d+m[Pp]?$",
        description="Training height (1m, 3m, 5m, 7m, 10m, or with P suffix)"
    )
    performance: Optional[str] = Field(
        None,
        pattern="^[FBMGP]$",
        description="Legacy single performance score (F/B/M/G/P) - for backwards compatibility"
    )
    phase1_performance: Optional[str] = Field(
        None,
        pattern="^[FBMGP]$",
        description="Phase 1 (Hurdle + Flight) performance - new two-phase format"
    )
    phase2_performance: Optional[str] = Field(
        None,
        pattern="^[FBMGP]$",
        description="Phase 2 (Opening + Entry) performance - new two-phase format"
    )
    video_uuid: str = Field(
        ...,
        min_length=32,
        description="Unique video identifier for deduplication"
    )
    date: datetime = Field(
        ...,
        description="Video date/time in ISO format"
    )
    is_sync: bool = Field(
        False,
        description="Whether this is a synchronized dive"
    )
    is_smack: bool = Field(
        False,
        description="Whether this is a belly flop/smack"
    )
    person_name: Optional[str] = Field(
        None,
        description="Name of training partner (if synced dive)"
    )
    modifiers: List[str] = Field(
        default_factory=list,
        description="Caption-derived drill/modifier codes such as DB, SD, HU"
    )
    raw_caption: Optional[str] = Field(
        None,
        description="Original Photos caption"
    )
    caption_hash: Optional[str] = Field(
        None,
        max_length=64,
        description="Stable hash of the Photos caption used for idempotent updates"
    )
    filename: Optional[str] = Field(
        None,
        max_length=255,
        description="Photos filename"
    )
    photos_path: Optional[str] = Field(
        None,
        description="Mac-local Photos path when available"
    )
    local_available: Optional[bool] = Field(
        None,
        description="Whether the Mac reports a local file path for the asset"
    )
    agent_id: Optional[str] = Field(None, min_length=1, max_length=100)
    cloud_guid: Optional[str] = Field(None, min_length=8, max_length=100)

    @validator('dive_code')
    def validate_dive_code(cls, v):
        """Validate dive code format (FINA: 3-6 digits + position letter A/B/C/D)"""
        v = v.upper()
        if not (4 <= len(v) <= 7):
            raise ValueError("Dive code must be 3-6 digits + position letter (4-7 chars total)")
        if not v[:-1].isdigit():
            raise ValueError("Dive code digits must be numeric")
        if v[-1] not in 'ABCD':
            raise ValueError("Dive code position must be A/B/C/D")
        return v

    @validator('height')
    def validate_height(cls, v):
        """Validate height format"""
        # Extract number and optional P suffix
        if v[-1] in 'Pp':
            height_num = v[:-2]
            suffix = v[-1]
        else:
            height_num = v[:-1]
            suffix = ""

        try:
            num = int(height_num)
            if num not in [1, 3, 5, 7, 10]:
                raise ValueError(f"Height must be 1/3/5/7/10m (got {num})")
        except ValueError:
            raise ValueError("Height must be numeric")

        return v.lower()  # Normalize case

    @validator('performance', 'phase1_performance', 'phase2_performance')
    def validate_performance(cls, v):
        if v is None:
            return v
        if v not in ['F', 'B', 'M', 'G', 'P']:
            raise ValueError(f"Invalid performance: {v}")
        return v.upper()

    @validator('modifiers')
    def normalize_modifiers(cls, v):
        normalized = []
        seen = set()
        for item in v or []:
            code = item.strip().upper()
            if not code:
                continue
            if code in {"SYNC", "SYNCHRO"}:
                # SYNC is modeled separately as is_sync, not as a drill modifier.
                continue
            if code not in seen:
                normalized.append(code)
                seen.add(code)
        return normalized


class VideoSyncResponse(BaseModel):
    """Response from single video sync"""

    dive_id: int = Field(..., description="Unique dive ID in database")
    message: str = Field(..., description="Status message")
    created: bool = Field(..., description="Whether new dive was created")
    updated: bool = Field(False, description="Whether an existing dive was updated")


class VideoLabelRequest(BaseModel):
    """Request to sync a non-dive video label from mac-agent."""

    video_uuid: str = Field(
        ...,
        min_length=32,
        description="Unique video identifier for idempotent label sync"
    )
    label_type: str = Field(
        ...,
        pattern="^(person|drill|note)$",
        description="Type of label attached to the video"
    )
    label_value: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Label value, e.g. PAUL"
    )
    date: Optional[datetime] = Field(
        None,
        description="Video date/time in ISO format"
    )
    filename: Optional[str] = Field(
        None,
        max_length=255,
        description="Photos filename"
    )
    raw_caption: Optional[str] = Field(
        None,
        description="Original Photos caption"
    )
    source: str = Field(
        "photos_caption",
        max_length=50,
        description="Origin of the label"
    )

    @validator('label_type', 'source')
    def normalize_lower(cls, v):
        return v.lower()

    @validator('label_value')
    def normalize_label_value(cls, v):
        return v.strip()


class VideoLabelResponse(BaseModel):
    """Response from video label sync."""

    label_id: int = Field(..., description="Unique label ID in database")
    message: str = Field(..., description="Status message")
    created: bool = Field(..., description="Whether new label was created")


class BatchSyncRequest(BaseModel):
    """Request to sync multiple videos"""

    videos: List[VideoSyncRequest] = Field(
        ...,
        max_items=200,
        min_items=1,
        description="List of videos to sync (max 200 per request)"
    )


class BatchSyncResponse(BaseModel):
    """Response from batch video sync"""

    total: int = Field(..., description="Total videos submitted")
    succeeded: int = Field(..., description="Successfully synced")
    failed: int = Field(..., description="Failed syncs")
    errors: List[dict] = Field(
        default_factory=list,
        description="List of errors: {video_uuid, error}"
    )
