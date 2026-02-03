"""Dive code parser service - parses captions and dive codes to DiveCodeData"""

import re
from typing import Optional, Dict, Tuple
from dataclasses import dataclass


@dataclass
class DiveCodeData:
    """Parsed dive code data with support for both legacy one-phase and new two-phase formats"""

    dive_code: str
    group: int
    direction: int
    position: str
    performance: Optional[str] = None  # Legacy: single performance (F/B/M/G/P)
    performance_numeric: Optional[int] = None  # Legacy: numeric value (0-4)
    phase1_performance: Optional[str] = None  # Two-phase: phase 1 performance (F/B/M/G/P)
    phase1_numeric: Optional[int] = None  # Two-phase: phase 1 numeric (0-4)
    phase2_performance: Optional[str] = None  # Two-phase: phase 2 performance (F/B/M/G/P)
    phase2_numeric: Optional[int] = None  # Two-phase: phase 2 numeric (0-4)
    height: str = "1m"
    platform_type: str = "springboard"
    is_sync: bool = False
    is_smack: bool = False
    is_valid: bool = True
    error: Optional[str] = None


class DiveCodeParser:
    """Parser for dive codes in app caption format and FINA format"""

    # Performance scale: letter → numeric value
    PERFORMANCE_MAP = {
        "F": 0,  # Failed
        "B": 1,  # Bad
        "M": 2,  # Medium
        "G": 3,  # Good
        "P": 4,  # Perfect
    }

    # Reverse mapping
    PERFORMANCE_REVERSE = {v: k for k, v in PERFORMANCE_MAP.items()}

    # Valid heights
    VALID_HEIGHTS = ["1m", "3m", "5m", "7m", "7.5m", "10m"]

    # Height to platform type mapping
    HEIGHT_PLATFORM_MAPPING = {
        "1m": "springboard",
        "3m": "springboard",
        "5m": "platform",
        "7m": "platform",  # App alias for 7.5m
        "7.5m": "platform",
        "10m": "platform",
    }

    # Height normalization: convert 7m → 7.5m for official FINA standard
    HEIGHT_NORMALIZATION = {
        "7m": "7.5m",
    }

    @classmethod
    def parse(cls, raw_input: str) -> DiveCodeData:
        """
        Parse a dive code from app caption format or FINA format.

        App format: DIVECODE PERF [HEIGHT] [FLAGS]
        Example: "101B M 3m SYNC"
        Example: "5231D G 10m"
        Example: "101B" (minimal)

        FINA format: pure dive code (3-4 digits + position)
        Example: "101B"
        Example: "5231D"

        Returns: DiveCodeData with parsed components
        """
        if not raw_input or not isinstance(raw_input, str):
            return DiveCodeData(
                dive_code="",
                group=0,
                direction=0,
                position="",
                is_valid=False,
                error="Invalid input: must be non-empty string",
            )

        raw_input = raw_input.strip().upper()

        # Parse components: DIVECODE PERF [HEIGHT] [FLAGS]
        parts = raw_input.split()

        if not parts:
            return DiveCodeData(
                dive_code="",
                group=0,
                direction=0,
                position="",
                is_valid=False,
                error="Input is empty",
            )

        # Extract dive code (first part)
        dive_code = parts[0]
        dive_code_result = cls._parse_dive_code(dive_code)
        if not dive_code_result[2]:  # Not valid
            return DiveCodeData(
                dive_code=dive_code,
                group=0,
                direction=0,
                position="",
                is_valid=False,
                error=dive_code_result[3],
            )

        group, direction, position = dive_code_result[:3]

        # Default values
        performance = None
        performance_numeric = None
        phase1_performance = None
        phase1_numeric = None
        phase2_performance = None
        phase2_numeric = None
        height = "1m"
        platform_type = "springboard"
        is_sync = False
        is_smack = False

        # Parse remaining parts (performance/phases, height, flags)
        for part in parts[1:]:
            part_upper = part.upper()

            # Check if it's a two-phase format (e.g., "G/P")
            if "/" in part_upper:
                phases = part_upper.split("/")
                if len(phases) == 2:
                    phase1, phase2 = phases
                    if len(phase1) == 1 and phase1 in cls.PERFORMANCE_MAP:
                        if len(phase2) == 1 and phase2 in cls.PERFORMANCE_MAP:
                            phase1_performance = phase1
                            phase1_numeric = cls.PERFORMANCE_MAP[phase1]
                            phase2_performance = phase2
                            phase2_numeric = cls.PERFORMANCE_MAP[phase2]
                            # Two-phase format overrides legacy single-phase
                            performance = None
                            performance_numeric = None
                            continue

            # Check if it's a legacy single performance rating
            if len(part_upper) == 1 and part_upper in cls.PERFORMANCE_MAP:
                # Only set legacy performance if not already parsed as two-phase
                if phase1_performance is None:
                    performance = part_upper
                    performance_numeric = cls.PERFORMANCE_MAP[part_upper]
                continue

            # Check if it's a height
            if cls._is_height(part_upper):
                height = cls._normalize_height(part_upper)
                platform_type = cls.HEIGHT_PLATFORM_MAPPING.get(height, "springboard")
                continue

            # Check flags
            if part_upper == "SYNC":
                is_sync = True
                continue
            if part_upper == "SMACK":
                is_smack = True
                continue

        return DiveCodeData(
            dive_code=dive_code,
            group=group,
            direction=direction,
            position=position,
            performance=performance,
            performance_numeric=performance_numeric,
            phase1_performance=phase1_performance,
            phase1_numeric=phase1_numeric,
            phase2_performance=phase2_performance,
            phase2_numeric=phase2_numeric,
            height=height,
            platform_type=platform_type,
            is_sync=is_sync,
            is_smack=is_smack,
            is_valid=True,
            error=None,
        )

    @classmethod
    def _parse_dive_code(cls, dive_code: str) -> Tuple[int, int, str, Optional[str]]:
        """
        Parse FINA dive code structure.

        Returns: (group, direction, position, error_message)

        FINA dive code format:
        - Groups 1-4: [GROUP][FLYING][ROTATIONS][POSITION] (4 chars)
          Example: 101B = group=1, flying=0, rotations=1, position=B
        - Group 5: [5][DIRECTION][ROTATIONS][TWISTS][POSITION] (5 chars)
          Example: 5231D = group=5, direction=2, rotations=3, twists=1, position=D
        - Group 6: [6][DIRECTION][ROTATIONS][POSITION] (4 chars)
          Example: 6031B = group=6, direction=0, rotations=3, position=B
        """
        if not dive_code or not isinstance(dive_code, str):
            return 0, 0, "", "Invalid dive code: empty or not a string"

        dive_code = dive_code.strip().upper()

        # Must be 4-5 characters
        if len(dive_code) < 4 or len(dive_code) > 5:
            return (
                0,
                0,
                "",
                f"Dive code must be 4-5 characters, got '{dive_code}' ({len(dive_code)} chars)",
            )

        # Extract position (last character must be A-D)
        position = dive_code[-1]
        if position not in ("A", "B", "C", "D"):
            return (
                0,
                0,
                "",
                f"Position must be A-D, got '{position}' in code '{dive_code}'",
            )

        # Extract digits
        digits = dive_code[:-1]
        if not digits.isdigit():
            return (
                0,
                0,
                "",
                f"Dive code digits must be numeric, got '{digits}' in code '{dive_code}'",
            )

        # Extract group (first digit)
        group = int(digits[0])
        if group < 1 or group > 6:
            return (
                0,
                0,
                "",
                f"Group (first digit) must be 1-6, got {group} in code '{dive_code}'",
            )

        # Extract direction (second digit)
        # For groups 1-4: this is the flying flag (0 or 1), but we report it as direction=group
        # For group 5: this is the actual direction (1-4)
        # For group 6: this is the direction (0-5)

        if group in [1, 2, 3, 4]:
            # Groups 1-4: [GROUP][FLYING][ROTATIONS][POSITION]
            flying = int(digits[1])
            if flying not in [0, 1]:
                return (
                    0,
                    0,
                    "",
                    f"Flying flag must be 0-1, got {flying} in code '{dive_code}'",
                )
            # For groups 1-4, "direction" conceptually equals the group
            direction = group

        elif group == 5:
            # Group 5: [5][DIRECTION][ROTATIONS][TWISTS][POSITION]
            direction = int(digits[1])
            if direction < 1 or direction > 4:
                return (
                    0,
                    0,
                    "",
                    f"Group 5 direction must be 1-4, got {direction} in code '{dive_code}'",
                )
        else:  # group == 6
            # Group 6: [6][DIRECTION][ROTATIONS][POSITION]
            direction = int(digits[1])
            if direction < 0 or direction > 5:
                return (
                    0,
                    0,
                    "",
                    f"Group 6 direction must be 0-5, got {direction} in code '{dive_code}'",
                )

        return group, direction, position, None

    @classmethod
    def _is_height(cls, value: str) -> bool:
        """Check if a value is a valid height (case-insensitive)"""
        # Normalize to lowercase for comparison
        value_lower = value.lower()
        return value_lower in cls.VALID_HEIGHTS

    @classmethod
    def _normalize_height(cls, height: str) -> str:
        """Normalize height (e.g., 7m → 7.5m for FINA standard)"""
        # Always lowercase first
        height_lower = height.lower()
        return cls.HEIGHT_NORMALIZATION.get(height_lower, height_lower)

    @classmethod
    def parse_batch(cls, raw_inputs: list) -> list:
        """Parse multiple dive codes"""
        return [cls.parse(raw_input) for raw_input in raw_inputs]

    @classmethod
    def to_dict(cls, data: DiveCodeData) -> dict:
        """Convert DiveCodeData to dictionary"""
        return {
            "dive_code": data.dive_code,
            "group": data.group,
            "direction": data.direction,
            "position": data.position,
            "performance": data.performance,  # Legacy single-phase
            "performance_numeric": data.performance_numeric,
            "phase1_performance": data.phase1_performance,  # Two-phase
            "phase1_numeric": data.phase1_numeric,
            "phase2_performance": data.phase2_performance,  # Two-phase
            "phase2_numeric": data.phase2_numeric,
            "height": data.height,
            "platform_type": data.platform_type,
            "is_sync": data.is_sync,
            "is_smack": data.is_smack,
            "is_valid": data.is_valid,
            "error": data.error,
        }
