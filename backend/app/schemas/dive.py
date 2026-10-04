"""Dive request/response schemas"""

from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field, ConfigDict


class DiveBase(BaseModel):
    """Base dive schema"""

    dive_code: str = Field(..., description="FINA dive code (e.g., 101B)")
    dive_number: Optional[str] = Field(None, description="Dive number")
    position: Optional[str] = Field(None, description="Position (B, C, etc.)")
    direction: Optional[int] = Field(None, description="Direction (1-5)")
    performance: str = Field(..., description="Performance rating (F, B, M, G, P)")
    performance_numeric: int = Field(..., description="Performance numeric (0-4)")
    height: str = Field(..., description="Height (1m, 3m, 5m, etc.)")
    platform_type: str = Field(default="springboard", description="springboard or platform")
    is_lineup: bool = Field(default=False, description="Is lineup dive")
    is_sync: bool = Field(default=False, description="Is synchronized dive")
    is_smack: bool = Field(default=False, description="Is smack attempt")
    raw_caption: Optional[str] = Field(None, description="Raw caption from video")
    person_name: Optional[str] = Field(None, description="Person name (for lineup dives)")
    notes: Optional[str] = Field(None, description="Additional notes")
    video_uuid: Optional[str] = Field(None, description="Video UUID")
    video_filename: Optional[str] = Field(None, description="Video filename")
    video_path: Optional[str] = Field(None, description="Video file path")
    dive_datetime: datetime = Field(..., description="When the dive occurred")


class DiveCreate(DiveBase):
    """Dive creation schema"""

    diver_id: Optional[int] = None
    visibility: Literal["public", "private"] = "public"
    session_id: int = Field(..., description="Session ID")


class DiveUpdate(BaseModel):
    """Dive update schema (all fields optional)"""

    visibility: Optional[Literal["public", "private"]] = None
    performance: Optional[str] = None
    performance_numeric: Optional[int] = None
    notes: Optional[str] = None
    is_lineup: Optional[bool] = None
    person_name: Optional[str] = None


class DiveResponse(DiveBase):
    """Dive response schema"""

    id: int
    session_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
