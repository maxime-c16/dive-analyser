"""Dive code validator service - validates dive codes against FINA rules"""

from typing import List, Tuple, Optional
from sqlalchemy.orm import Session

from app.models import FINADiveCode
from app.services.fina_validator import FINAValidator, FINAValidationError
from app.services.dive_code_parser import DiveCodeParser, DiveCodeData


class DiveCodeValidator:
    """Validates dive codes against FINA rules and application constraints"""

    def __init__(self, db: Optional[Session] = None):
        """Initialize validator with optional database session"""
        self.db = db
        self.fina_validator = FINAValidator(db) if db else None

    def validate_structure(self, dive_code: str) -> Tuple[bool, List[str]]:
        """
        Validate dive code structure (format, syntax).

        Returns: (is_valid, error_messages)
        """
        errors = []

        if not dive_code or not isinstance(dive_code, str):
            return False, ["Dive code must be a non-empty string"]

        dive_code = dive_code.strip().upper()

        # Must be 4-5 characters
        if len(dive_code) < 4 or len(dive_code) > 5:
            errors.append(
                f"Dive code must be 4-5 characters (digits + position), got '{dive_code}' ({len(dive_code)} chars)"
            )
            return False, errors

        # Last character must be A-D
        position = dive_code[-1]
        if position not in ("A", "B", "C", "D"):
            errors.append(f"Position must be A-D, got '{position}'")
            return False, errors

        # First 3-4 characters must be digits
        digits = dive_code[:-1]
        if not digits.isdigit():
            errors.append(f"Dive code digits must be numeric, got '{digits}'")
            return False, errors

        # First digit must be 1-6 (group)
        group = int(digits[0])
        if group < 1 or group > 6:
            errors.append(f"Group (first digit) must be 1-6, got {group}")
            return False, errors

        return len(errors) == 0, errors

    def validate_with_fina_rules(self, dive_code: str) -> Tuple[bool, List[str]]:
        """
        Validate dive code against official FINA rules.

        Returns: (is_valid, error_messages)
        """
        # First validate structure
        is_valid, struct_errors = self.validate_structure(dive_code)
        if not is_valid:
            return False, struct_errors

        errors = []
        dive_code = dive_code.strip().upper()

        # Check if dive code exists in database (if connected)
        if self.db:
            fina_dive = self.db.query(FINADiveCode).filter_by(dive_code=dive_code).first()
            if not fina_dive:
                # Not in official FINA database
                errors.append(f"Dive code '{dive_code}' is not in official FINA database")
                # Still try to validate structure with FINA rules
            else:
                # Validate the model
                is_fina_valid, fina_errors = fina_dive.validate_fina_structure()
                if not is_fina_valid:
                    errors.extend(fina_errors)

        # Parse to check FINA semantic rules
        try:
            group = int(dive_code[0])
            direction = int(dive_code[1])

            # Group 5 (twisting) specific rules
            if group == 5:
                if direction < 1 or direction > 4:
                    errors.append(f"Group 5 (twisting) direction must be 1-4, got {direction}")

            # Flying dives only in groups 1-4
            # (We would need full parsing to check this, skip for now)

        except (ValueError, IndexError):
            pass

        return len(errors) == 0, errors

    def validate_height_for_platform(self, dive_code: str, height: str) -> Tuple[bool, List[str]]:
        """
        Validate that height is appropriate for the dive code's platform requirements.

        Returns: (is_valid, error_messages)
        """
        errors = []

        if not height:
            return False, ["Height must be specified"]

        # Normalize to lowercase for consistent comparison
        height = height.lower().strip()

        # Normalize height (e.g., 7m → 7.5m)
        height = DiveCodeParser.HEIGHT_NORMALIZATION.get(height, height)

        if height not in DiveCodeParser.VALID_HEIGHTS:
            errors.append(
                f"Height must be one of {DiveCodeParser.VALID_HEIGHTS}, got '{height}'"
            )
            return False, errors

        # Get platform type for this height
        platform_type = DiveCodeParser.HEIGHT_PLATFORM_MAPPING.get(height, "springboard")

        # For now, most dives can be done at any height/platform
        # Add specific constraints here if needed
        # For example: 6031B (armstand) only on platform, etc.

        return len(errors) == 0, errors

    def check_if_official_fina_dive(self, dive_code: str) -> bool:
        """Check if dive code is in official FINA database"""
        if not self.db:
            return False

        dive_code = dive_code.strip().upper()
        fina_dive = self.db.query(FINADiveCode).filter_by(dive_code=dive_code).first()
        return fina_dive is not None

    def get_validation_errors(
        self, dive_code: str, height: Optional[str] = None
    ) -> List[dict]:
        """
        Get comprehensive list of validation errors.

        Returns: List of error dicts with field, message, severity
        """
        errors = []

        # Validate structure
        struct_valid, struct_errors = self.validate_structure(dive_code)
        if not struct_valid:
            for error in struct_errors:
                errors.append({
                    "field": "dive_code",
                    "message": error,
                    "severity": "error",
                })
            return errors

        # Validate FINA rules
        fina_valid, fina_errors = self.validate_with_fina_rules(dive_code)
        if not fina_valid:
            for error in fina_errors:
                errors.append({
                    "field": "dive_code",
                    "message": error,
                    "severity": "error",
                })

        # Validate height if provided
        if height:
            height_valid, height_errors = self.validate_height_for_platform(dive_code, height)
            if not height_valid:
                for error in height_errors:
                    errors.append({
                        "field": "height",
                        "message": error,
                        "severity": "error",
                    })

        return errors

    def is_valid(self, dive_code: str, height: Optional[str] = None) -> bool:
        """Quick check if dive code is valid"""
        struct_valid, _ = self.validate_structure(dive_code)
        if not struct_valid:
            return False

        fina_valid, _ = self.validate_with_fina_rules(dive_code)
        if not fina_valid:
            return False

        if height:
            height_valid, _ = self.validate_height_for_platform(dive_code, height)
            if not height_valid:
                return False

        return True

    def get_suggestions(self, dive_code: str) -> List[str]:
        """Get suggestions for correcting invalid dive code"""
        suggestions = []

        if not dive_code:
            suggestions.append("Enter a dive code in format: DIVECODE PERF [HEIGHT] [FLAGS]")
            suggestions.append("Example: 101B M 3m")
            suggestions.append("Example: 5231D G 10m SYNC")
            return suggestions

        dive_code = dive_code.strip().upper()

        # If too short, suggest format
        if len(dive_code) < 4:
            suggestions.append("Dive code must be at least 4 characters (e.g., 101B)")
            suggestions.append(
                "Format: GROUP + DIRECTION + SOMERSAULTS + POSITION (e.g., 1-0-1-B)"
            )
            return suggestions

        # If invalid position, suggest valid ones
        if dive_code[-1] not in ("A", "B", "C", "D"):
            suggestions.append(f"Position must be A (Straight), B (Pike), C (Tuck), or D (Free)")
            suggestions.append(f"Did you mean: {dive_code[:-1]}A/B/C/D?")
            return suggestions

        # If group is invalid, suggest valid groups
        try:
            group = int(dive_code[0])
            if group < 1 or group > 6:
                suggestions.append("Group (first digit) must be 1-6")
                suggestions.append("1=Forward, 2=Back, 3=Reverse, 4=Inward, 5=Twisting, 6=Armstand")
        except ValueError:
            suggestions.append("First character must be a group number (1-6)")

        return suggestions

    def validate_parsed_code(self, parsed: DiveCodeData) -> Tuple[bool, List[str]]:
        """Validate a previously parsed DiveCodeData"""
        if not parsed.is_valid:
            return False, [parsed.error or "Invalid parse"]

        # Validate structure
        struct_valid, struct_errors = self.validate_structure(parsed.dive_code)
        if not struct_valid:
            return False, struct_errors

        # Validate FINA rules
        fina_valid, fina_errors = self.validate_with_fina_rules(parsed.dive_code)

        # Validate height
        height_valid, height_errors = self.validate_height_for_platform(
            parsed.dive_code, parsed.height
        )

        all_errors = struct_errors + fina_errors + height_errors
        return len(all_errors) == 0, all_errors
