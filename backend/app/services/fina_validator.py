"""FINA diving rules validator service"""

from typing import Optional, Dict, List, Tuple
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models import FINADiveCode, DDLookup, FINAScoringRule


class FINAValidationError(Exception):
    """Raised when FINA rule validation fails"""
    pass


class FINAValidator:
    """Validates dives and events against official FINA standards"""

    # FINA Group definitions
    GROUPS = {
        1: {"name": "Forward", "allow_flying": True},
        2: {"name": "Back", "allow_flying": True},
        3: {"name": "Reverse", "allow_flying": True},
        4: {"name": "Inward", "allow_flying": True},
        5: {"name": "Twisting", "allow_flying": False},
        6: {"name": "Armstand", "allow_flying": False},
    }

    # Valid positions
    POSITIONS = {"A": "Straight", "B": "Pike", "C": "Tuck", "D": "Free"}

    # Valid heights
    # Note: "7m" is an app-level alias for "7.5m" (official FINA height)
    HEIGHTS = ["1m", "3m", "5m", "7m", "7.5m", "10m"]

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

    # Valid DD range
    # Compatibility validation only. Official values come from the versioned
    # component formula and must not be constrained by the former lookup
    # table's 4.1 ceiling.
    DD_MIN = Decimal("1.0")
    DD_MAX = Decimal("6.0")

    def __init__(self, db: Session):
        """Initialize validator with database session"""
        self.db = db
        self._dd_cache: Dict[str, Dict] = {}

    def normalize_height(self, height: str) -> str:
        """
        Normalize height format to official FINA standard.

        Converts app-level aliases (e.g., "7m") to official FINA heights (e.g., "7.5m").

        Args:
            height: The height (e.g., "1m", "7m", "7.5m")

        Returns:
            Normalized height (e.g., "1m", "7.5m")

        Raises:
            FINAValidationError: If height is invalid
        """
        if height not in self.HEIGHTS:
            raise FINAValidationError(
                f"Invalid height '{height}'. Must be one of {self.HEIGHTS}"
            )

        # Apply normalization if needed
        return self.HEIGHT_NORMALIZATION.get(height, height)

    def validate_dive_code_format(self, dive_code: str) -> Dict[str, any]:
        """
        Validate dive code format and extract components.

        Args:
            dive_code: The dive code (e.g., "101B", "5231D")

        Returns:
            Dict with extracted components: group, direction, rotations, twists, position

        Raises:
            FINAValidationError: If format is invalid
        """
        if not dive_code or not isinstance(dive_code, str):
            raise FINAValidationError("Dive code must be a non-empty string")

        if len(dive_code) < 4 or len(dive_code) > 5:
            raise FINAValidationError(f"Dive code must be 4-5 characters, got '{dive_code}'")

        # Parse components
        try:
            group = int(dive_code[0])
        except ValueError:
            raise FINAValidationError(f"First character must be group number 1-6, got '{dive_code[0]}'")

        if group < 1 or group > 6:
            raise FINAValidationError(f"Group must be 1-6, got {group}")

        # For groups 1-4: [GROUP][FLYING][ROTATIONS][POSITION]
        # For group 5 (twisting): [5][DIRECTION][ROTATIONS][TWISTS][POSITION]
        # For group 6 (armstand): [6][DIRECTION][ROTATIONS][POSITION]

        if group in [1, 2, 3, 4]:
            # Standard groups: 4-5 characters
            if len(dive_code) < 4:
                raise FINAValidationError(f"Standard dive code must be >=4 chars, got '{dive_code}'")

            has_flying = int(dive_code[1])
            if has_flying not in [0, 1]:
                raise FINAValidationError(f"Flying flag must be 0-1, got {has_flying}")

            rotations = int(dive_code[2])
            if rotations < 1 or rotations > 8:
                raise FINAValidationError(f"Rotations must be 1-8, got {rotations}")

            position = dive_code[3]
            if position not in self.POSITIONS:
                raise FINAValidationError(f"Position must be A-D, got '{position}'")

            return {
                "group": group,
                "direction": group,
                "has_flying": has_flying,
                "rotations": rotations,
                "twists": 0,
                "position": position,
                "is_twisting": False,
                "is_flying": has_flying == 1,
                "is_armstand": False,
            }

        elif group == 5:
            # Twisting dives: [5][DIRECTION][ROTATIONS][TWISTS][POSITION]
            if len(dive_code) != 5:
                raise FINAValidationError(f"Twisting dive must be 5 chars, got '{dive_code}'")

            direction = int(dive_code[1])
            if direction < 1 or direction > 4:
                raise FINAValidationError(f"Twisting direction (1-4) must be 1-4, got {direction}")

            rotations = int(dive_code[2])
            if rotations < 1 or rotations > 8:
                raise FINAValidationError(f"Rotations must be 1-8, got {rotations}")

            twists = int(dive_code[3])
            if twists < 1 or twists > 8:
                raise FINAValidationError(f"Twists must be 1-8, got {twists}")

            position = dive_code[4]
            if position not in self.POSITIONS:
                raise FINAValidationError(f"Position must be A-D, got '{position}'")

            return {
                "group": 5,
                "direction": direction,
                "has_flying": 0,
                "rotations": rotations,
                "twists": twists,
                "position": position,
                "is_twisting": True,
                "is_flying": False,
                "is_armstand": False,
            }

        elif group == 6:
            # Armstand dives: [6][DIRECTION][ROTATIONS][POSITION]
            if len(dive_code) != 4:
                raise FINAValidationError(f"Armstand dive must be 4 chars, got '{dive_code}'")

            direction = int(dive_code[1])
            if direction < 0 or direction > 5:
                raise FINAValidationError(f"Armstand direction must be 0-5, got {direction}")

            rotations = int(dive_code[2])
            if rotations < 1 or rotations > 8:
                raise FINAValidationError(f"Rotations must be 1-8, got {rotations}")

            position = dive_code[3]
            if position not in self.POSITIONS:
                raise FINAValidationError(f"Position must be A-D, got '{position}'")

            return {
                "group": 6,
                "direction": direction,
                "has_flying": 0,
                "rotations": rotations,
                "twists": 0,
                "position": position,
                "is_twisting": False,
                "is_flying": False,
                "is_armstand": True,
            }

    def lookup_dd(self, dive_code: str, height: str) -> Optional[Decimal]:
        """
        Look up official DD value for a dive code at a specific height.

        Accepts both app-level height aliases (e.g., "7m") and official FINA heights (e.g., "7.5m").

        Args:
            dive_code: The FINA dive code (e.g., "101B")
            height: The height (e.g., "1m", "3m", "7m", "7.5m", "10m")

        Returns:
            DD value as Decimal, or None if not found

        Raises:
            FINAValidationError: If height is invalid
        """
        # Normalize height to official FINA standard
        normalized_height = self.normalize_height(height)

        # Check cache (using normalized height)
        cache_key = f"{dive_code}_{normalized_height}"
        if cache_key in self._dd_cache:
            return self._dd_cache[cache_key]

        # Query database using normalized height
        stmt = select(DDLookup.dd_value).where(
            (DDLookup.dive_code == dive_code) &
            (DDLookup.height == normalized_height)
        )
        result = self.db.execute(stmt).scalar_one_or_none()

        # Cache result
        self._dd_cache[cache_key] = result
        return result

    def validate_dd_value(self, dd_value: Decimal) -> bool:
        """
        Validate that a DD value is within official FINA range.

        Args:
            dd_value: The DD value to validate

        Returns:
            True if valid, False otherwise
        """
        try:
            dd = Decimal(str(dd_value))
            return self.DD_MIN <= dd <= self.DD_MAX
        except:
            return False

    def validate_event_compliance(
        self,
        event_type: str,
        dive_codes: List[str],
        heights: List[str],
    ) -> Tuple[bool, str]:
        """
        Validate that a set of dives complies with event requirements.

        Args:
            event_type: The event type (e.g., "springboard_1m_men")
            dive_codes: List of FINA dive codes
            heights: List of heights for each dive

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Get event rule
        stmt = select(FINAScoringRule).where(FINAScoringRule.event_type == event_type)
        rule = self.db.execute(stmt).scalar_one_or_none()

        if not rule:
            return False, f"Event type '{event_type}' not found in FINA rules"

        # Validate rule itself
        is_valid, errors = rule.validate_all_fina_rules()
        if not is_valid:
            return False, f"Event rule '{event_type}' has violations: {'; '.join(errors)}"

        # Check dive count
        if len(dive_codes) != rule.mandatory_dive_count:
            return False, f"Event requires {rule.mandatory_dive_count} dives, got {len(dive_codes)}"

        # Extract groups from dive codes and validate each
        groups_used = set()
        for dive_code in dive_codes:
            try:
                components = self.validate_dive_code_format(dive_code)
                groups_used.add(components["group"])

                # Validate dive code structure
                if not self._validate_dive_structure(components):
                    return False, f"Dive code '{dive_code}' violates FINA structure rules"

            except FINAValidationError as e:
                return False, f"Invalid dive code '{dive_code}': {str(e)}"

        # Check mandatory groups
        required_groups = set(rule.mandatory_groups)
        missing_groups = required_groups - groups_used

        if missing_groups:
            missing_str = ", ".join(str(g) for g in sorted(missing_groups))
            return False, f"Missing required groups: {missing_str}"

        return True, ""

    def _validate_dive_structure(self, components: Dict) -> bool:
        """
        Validate dive code structure against FINA rules.

        Returns: True if valid, False otherwise
        """
        group = components["group"]
        direction = components["direction"]
        twists = components["twists"]
        is_flying = components["is_flying"]

        # CRITICAL: Group 5 direction must be 1-4
        if group == 5 and not (1 <= direction <= 4):
            return False

        # CRITICAL: Group 5 must have twists >= 1
        if group == 5 and twists == 0:
            return False

        # Non-group-5 must have twists = 0
        if group != 5 and twists > 0:
            return False

        # Flying only in groups 1-4
        if is_flying and group > 4:
            return False

        return True

    def get_fina_dive_code_info(self, dive_code: str) -> Optional[Dict]:
        """
        Get FINA metadata for a dive code from database.

        Args:
            dive_code: The FINA dive code

        Returns:
            Dict with FINA metadata or None if not found
        """
        stmt = select(FINADiveCode).where(FINADiveCode.dive_code == dive_code)
        fdc = self.db.execute(stmt).scalar_one_or_none()

        if not fdc:
            return None

        return {
            "dive_code": fdc.dive_code,
            "official_name": fdc.official_name,
            "group": fdc.group,
            "position": fdc.position,
            "rotations": fdc.rotations,
            "twists": fdc.twists,
            "is_twisting": bool(fdc.is_twisting),
            "is_armstand": bool(fdc.is_armstand),
        }

    def clear_cache(self):
        """Clear DD lookup cache"""
        self._dd_cache.clear()
