"""Pydantic schemas for DD (Difficulty Degree) calculations"""

from pydantic import BaseModel, Field
from decimal import Decimal
from typing import Optional, List, Dict
from datetime import datetime


class DDLookupResponse(BaseModel):
    """Response for DD lookup query"""
    dive_code: str = Field(..., description="FINA dive code")
    height: str = Field(..., description="Training height")
    dd_value: float = Field(..., description="Official DD value")
    platform_type: Optional[str] = Field(None, description="springboard or platform")

    class Config:
        from_attributes = True


class DDCalculationInput(BaseModel):
    """Input for DD calculation request"""
    dive_code: str = Field(..., description="FINA dive code (e.g., 101B)")
    height: str = Field(..., description="Training height (1m, 3m, 5m, 7m, 7.5m, 10m)")
    performance: int = Field(..., ge=0, le=4, description="Execution performance (0=F, 1=B, 2=M, 3=G, 4=P)")
    conditions: Optional[Dict] = Field(None, description="Optional environmental conditions")


class DDCalculationResult(BaseModel):
    """Result of DD calculation"""
    dive_code: str = Field(..., description="FINA dive code")
    height: str = Field(..., description="Training height")
    base_dd: float = Field(..., description="Official FINA DD value")
    calculated_dd: float = Field(..., description="Final calculated DD with adjustments")
    performance: int = Field(..., description="Execution performance used")
    adjustments: List[str] = Field(..., description="List of adjustments applied")
    justification: str = Field(..., description="Explanation of calculation")


class DDMilestone(BaseModel):
    """DD milestone achievement"""
    type: str = Field(..., description="Milestone type (e.g., 'dd_2_0', 'dd_3_0')")
    achieved_date: datetime = Field(..., description="When milestone was achieved")
    dive_code: str = Field(..., description="Dive code that triggered milestone")
    height: str = Field(..., description="Height at which milestone was achieved")
    dd_value: float = Field(..., description="DD value of triggering dive")
    performance: Optional[int] = Field(None, description="Performance of triggering dive")


class DDJourneyProgress(BaseModel):
    """User's DD journey progress"""
    user_id: int = Field(..., description="User ID")
    highest_dd_achieved: Optional[float] = Field(None, description="Highest DD achieved")
    highest_dd_dive_code: Optional[str] = Field(None, description="Code of highest DD dive")
    total_dives_tracked: int = Field(..., description="Total dives in DD system")
    dives_with_dd_2_0_plus: int = Field(..., description="Count of dives with DD >= 2.0")
    dives_with_dd_3_0_plus: int = Field(..., description="Count of dives with DD >= 3.0")
    dives_with_dd_3_5_plus: int = Field(..., description="Count of dives with DD >= 3.5")
    milestones_achieved: List[DDMilestone] = Field(..., description="Achieved milestones")
    next_milestone: Optional[str] = Field(None, description="Next milestone to target")


class DDStatistics(BaseModel):
    """DD statistics for a height or group"""
    count: int = Field(..., description="Number of dives")
    min_dd: Optional[float] = Field(None, description="Minimum DD value")
    max_dd: Optional[float] = Field(None, description="Maximum DD value")
    average_dd: Optional[float] = Field(None, description="Average DD value")
    height: Optional[str] = Field(None, description="Height for these statistics")


class DDAutoAssignResult(BaseModel):
    """Result of auto-assignment operation"""
    dive_id: int = Field(..., description="Dive ID")
    dive_code: str = Field(..., description="Dive code")
    height: str = Field(..., description="Height")
    dd_value: float = Field(..., description="Assigned DD value")
    success: bool = Field(..., description="Whether assignment succeeded")
    error: Optional[str] = Field(None, description="Error message if failed")


class DDBatchAssignResult(BaseModel):
    """Result of batch assignment operation"""
    total: int = Field(..., description="Total dives processed")
    success: int = Field(..., description="Successfully assigned")
    failed: int = Field(..., description="Failed assignments")
    errors: List[str] = Field(..., description="Error messages")
