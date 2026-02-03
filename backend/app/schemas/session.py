"""Session request/response schemas"""

from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class SessionBase(BaseModel):
    """Base session schema"""

    date: date
    location: Optional[str] = None
    notes: Optional[str] = None
    weather: Optional[str] = None


class SessionCreate(SessionBase):
    """Session creation schema"""

    pass


class SessionUpdate(BaseModel):
    """Session update schema"""

    location: Optional[str] = None
    notes: Optional[str] = None
    weather: Optional[str] = None


class SessionResponse(SessionBase):
    """Session response schema"""

    id: int
    total_dives: int
    total_personal_dives: int
    avg_performance: Optional[float] = None
    success_rate: Optional[float] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SessionSummary(BaseModel):
    """Session summary (without dives list)"""

    id: int
    date: date
    location: Optional[str]
    total_dives: int
    total_personal_dives: int
    avg_performance: Optional[float]
    success_rate: Optional[float]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
