"""Dive code request/response schemas for FINA integration"""

from typing import Optional, List
from pydantic import BaseModel, Field, field_validator


class DiveCodeInput(BaseModel):
    """Input for dive code parsing/validation"""

    raw_input: str = Field(..., description="Raw caption or dive code (e.g., '101B M 3m' or '101B')")


class DiveCodeParsed(BaseModel):
    """Successfully parsed dive code data with support for both legacy and two-phase formats"""

    dive_code: str = Field(..., description="FINA dive code (e.g., '101B')")
    group: int = Field(..., description="FINA group (1-6)")
    direction: int = Field(..., description="Direction (1-5)")
    position: str = Field(..., description="Position (A/B/C/D)")
    # Legacy one-phase format (e.g., "101B M")
    performance: Optional[str] = Field(None, description="Performance rating (F/B/M/G/P)")
    performance_numeric: Optional[int] = Field(None, description="Performance numeric (0-4)")
    # New two-phase format (e.g., "101B G/P")
    phase1_performance: Optional[str] = Field(None, description="Phase 1 performance (F/B/M/G/P)")
    phase1_numeric: Optional[int] = Field(None, description="Phase 1 numeric (0-4)")
    phase2_performance: Optional[str] = Field(None, description="Phase 2 performance (F/B/M/G/P)")
    phase2_numeric: Optional[int] = Field(None, description="Phase 2 numeric (0-4)")
    # Height and platform information
    height: str = Field(default="1m", description="Height (1m, 3m, 5m, 7m/7.5m, 10m)")
    platform_type: str = Field(default="springboard", description="springboard or platform")
    # Special flags
    is_sync: bool = Field(default=False, description="Is synchronized dive")
    is_smack: bool = Field(default=False, description="Is smack/belly flop attempt")
    is_valid: bool = Field(default=True, description="Is valid dive code")


class ValidationError(BaseModel):
    """Single validation error"""

    field: str = Field(..., description="Field that failed validation")
    message: str = Field(..., description="Error message")
    severity: str = Field(default="error", description="error, warning, info")


class DiveCodeValidation(BaseModel):
    """Validation result for a dive code"""

    dive_code: str = Field(..., description="FINA dive code")
    is_valid: bool = Field(..., description="Overall validation result")
    errors: List[ValidationError] = Field(default_factory=list, description="List of validation errors")
    warnings: List[ValidationError] = Field(default_factory=list, description="List of warnings")
    suggestions: Optional[List[str]] = Field(None, description="Suggestions for correction")
    is_official_fina: bool = Field(..., description="Is this in official FINA codes")


class DiveCodeReference(BaseModel):
    """Reference data for a FINA dive code"""

    dive_code: str = Field(..., description="FINA dive code")
    group: int = Field(..., description="Group (1-6)")
    group_name: str = Field(..., description="Group name (Forward, Back, etc.)")
    direction: int = Field(..., description="Direction (1-5)")
    position: str = Field(..., description="Position (A/B/C/D)")
    position_name: str = Field(..., description="Position name (Straight, Pike, etc.)")
    rotations: int = Field(..., description="Number of half rotations")
    twists: int = Field(..., description="Number of half twists")
    official_name: Optional[str] = Field(None, description="Official FINA name")
    description: Optional[str] = Field(None, description="Description")
    is_twisting: bool = Field(..., description="Is a twisting dive")
    is_flying: bool = Field(..., description="Is a flying dive")
    is_armstand: bool = Field(..., description="Is an armstand dive")


class DiveCodeBatch(BaseModel):
    """Batch parsing request"""

    codes: List[str] = Field(..., description="List of raw dive codes to parse")


class DiveCodeBatchResponse(BaseModel):
    """Batch parsing response"""

    total: int = Field(..., description="Total codes submitted")
    successful: int = Field(..., description="Successfully parsed")
    failed: int = Field(..., description="Failed to parse")
    results: List[dict] = Field(..., description="Parse results (mixed success/failure)")
