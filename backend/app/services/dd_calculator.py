"""DD (Difficulty Degree) Calculator service - handles DD lookups and calculations"""

from typing import Optional, Dict, List, Tuple
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models import DDLookup, FINADiveCode
from app.services.dive_code_parser import DiveCodeParser


class DDCalculationError(Exception):
    """Raised when DD calculation fails"""
    pass


class DDCalculator:
    """Calculates DD values for dives based on FINA official tables"""

    def __init__(self, db: Session):
        """Initialize calculator with database session"""
        self.db = db
        self._dd_cache: Dict[str, Optional[Decimal]] = {}

    def lookup_dd(self, dive_code: str, height: str) -> Optional[Decimal]:
        """
        Look up official DD value for a dive at a specific height.

        Args:
            dive_code: The FINA dive code (e.g., "101B")
            height: The height (e.g., "1m", "3m", "5m", "7m", "7.5m", "10m")

        Returns:
            DD value as Decimal (e.g., Decimal("1.3")), or None if not found
        """
        # Normalize height (7m → 7.5m)
        height = self._normalize_height(height)

        # Create cache key
        cache_key = f"{dive_code}_{height}"
        if cache_key in self._dd_cache:
            return self._dd_cache[cache_key]

        # Query database
        dd_lookup = (
            self.db.query(DDLookup)
            .filter_by(dive_code=dive_code, height=height)
            .first()
        )

        result = dd_lookup.dd_value if dd_lookup else None

        # Cache result
        self._dd_cache[cache_key] = result
        return result

    def lookup_dd_all_heights(self, dive_code: str) -> Dict[str, Decimal]:
        """
        Look up DD values for all heights for a specific dive code.

        Returns: Dict mapping height → DD value
        """
        lookups = (
            self.db.query(DDLookup)
            .filter_by(dive_code=dive_code)
            .all()
        )

        result = {lookup.height: lookup.dd_value for lookup in lookups}
        return result

    def lookup_dd_by_group(self, group: int, height: str) -> List[Dict]:
        """
        Look up DD values for all dives in a group at a specific height.

        Args:
            group: FINA group (1-6)
            height: Height (will be normalized)

        Returns: List of dicts with dive_code and dd_value
        """
        height = self._normalize_height(height)

        # Get all dives in this group
        dives = (
            self.db.query(FINADiveCode)
            .filter_by(group=group)
            .all()
        )

        results = []
        for dive in dives:
            dd_value = self.lookup_dd(dive.dive_code, height)
            if dd_value:
                results.append({
                    "dive_code": dive.dive_code,
                    "group": dive.group,
                    "official_name": dive.official_name,
                    "dd_value": float(dd_value),
                })

        return results

    def get_statistics(self, height: str) -> Dict:
        """
        Get DD statistics for all dives at a specific height.

        Returns:
            Dict with min, max, average, std_dev, count
        """
        height = self._normalize_height(height)

        lookups = (
            self.db.query(DDLookup)
            .filter_by(height=height)
            .all()
        )

        if not lookups:
            return {
                "count": 0,
                "min": None,
                "max": None,
                "average": None,
            }

        values = [float(lookup.dd_value) for lookup in lookups]

        return {
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "average": sum(values) / len(values),
        }

    def validate_dd_value(self, dd_value: Decimal) -> Tuple[bool, Optional[str]]:
        """
        Validate that a DD value is within FINA acceptable range.

        DD values typically range from 1.2 to 4.1+

        Args:
            dd_value: The DD value to validate

        Returns:
            (is_valid, error_message)
        """
        if not isinstance(dd_value, (Decimal, float, int)):
            return False, "DD value must be numeric"

        dd_float = float(dd_value)

        if dd_float < 1.0:
            return False, f"DD value must be >= 1.0, got {dd_float}"

        if dd_float > 5.0:
            return False, f"DD value must be <= 5.0, got {dd_float}"

        # Check increment (should be in 0.1 increments for FINA)
        # Allow small float precision errors
        remainder = (dd_float * 10) % 1
        if remainder > 0.01 and remainder < 0.99:
            return False, f"DD value must be in 0.1 increments (e.g., 1.3, 2.5), got {dd_float}"

        return True, None

    def estimate_dd_from_components(
        self,
        group: int,
        rotations: int,
        twists: int = 0,
        is_flying: bool = False,
    ) -> Optional[Decimal]:
        """
        Estimate DD based on dive components (simplified heuristic).

        This is a rough estimation and should not replace official FINA tables.

        Args:
            group: FINA group (1-6)
            rotations: Number of half rotations
            twists: Number of half twists (group 5 only)
            is_flying: Whether dive has flying action

        Returns:
            Estimated DD value, or None if not possible
        """
        # Base DD values by complexity
        base_dd = {
            1: Decimal("1.3"),  # Forward
            2: Decimal("1.4"),  # Back
            3: Decimal("1.5"),  # Reverse
            4: Decimal("1.6"),  # Inward
            5: Decimal("2.0"),  # Twisting
            6: Decimal("2.5"),  # Armstand
        }

        if group not in base_dd:
            return None

        dd = base_dd[group]

        # Add for rotations (simplified: 0.3 per rotation)
        if rotations > 1:
            dd += Decimal("0.3") * (rotations - 1)

        # Add for twists (simplified: 0.4 per twist)
        if twists > 0:
            dd += Decimal("0.4") * twists

        # Add for flying (simplified: 0.2)
        if is_flying:
            dd += Decimal("0.2")

        # Round to nearest 0.1
        return (dd * 10).quantize(Decimal("1")) / 10

    def _normalize_height(self, height: str) -> str:
        """Normalize height (7m → 7.5m for FINA standard)"""
        height = height.lower().strip()

        normalization = {
            "7m": "7.5m",
        }

        return normalization.get(height, height)

    def get_all_dds(self) -> List[Dict]:
        """Get all DD values from database"""
        lookups = self.db.query(DDLookup).all()

        return [
            {
                "dive_code": lookup.dive_code,
                "height": lookup.height,
                "platform_type": lookup.platform_type,
                "dd_value": float(lookup.dd_value),
                "effective_date": lookup.effective_date.isoformat() if lookup.effective_date else None,
            }
            for lookup in lookups
        ]

    def clear_cache(self):
        """Clear the DD cache"""
        self._dd_cache.clear()
