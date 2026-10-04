"""DD (Difficulty Degree) Calculator service - handles DD lookups and calculations"""

from typing import Optional, Dict, List, Tuple
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models import FINADiveCode
from app.services.world_aquatics_dd import OfficialDDUndefined, calculate_official_dd, normalize_height


class DDCalculationError(Exception):
    """Raised when DD calculation fails"""
    pass


class DDCalculator:
    """Calculates DD values from the versioned World Aquatics component rules."""

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
        # The rulebook formula is authoritative. The legacy database table is
        # intentionally not a silent fallback because it is incomplete and
        # contains historical manually-seeded values.
        height = self._normalize_height(height)

        # Create cache key
        cache_key = f"{dive_code}_{height}"
        if cache_key in self._dd_cache:
            return self._dd_cache[cache_key]

        try:
            result = calculate_official_dd(dive_code, height).dd
        except OfficialDDUndefined:
            result = None

        # Cache result
        self._dd_cache[cache_key] = result
        return result

    def lookup_dd_all_heights(self, dive_code: str) -> Dict[str, Decimal]:
        """
        Look up DD values for all heights for a specific dive code.

        Returns: Dict mapping height → DD value
        """
        result: Dict[str, Decimal] = {}
        for height in ("1m", "3m", "5m", "7.5m", "10m"):
            dd_value = self.lookup_dd(dive_code, height)
            if dd_value is not None:
                result[height] = dd_value
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

        dives = self.db.query(FINADiveCode).all()
        values = [float(value) for dive in dives if (value := self.lookup_dd(dive.dive_code, height)) is not None]

        if not values:
            return {"count": 0, "min": None, "max": None, "average": None}

        return {
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "average": sum(values) / len(values),
        }

    def validate_dd_value(self, dd_value: Decimal) -> Tuple[bool, Optional[str]]:
        """
        Validate that a DD value is within FINA acceptable range.

        This guards manually entered compatibility values. Formula-derived
        values are produced directly by ``calculate_official_dd``.

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

        if dd_float > 6.0:
            return False, f"DD value must be <= 6.0, got {dd_float}"

        # Check increment (should be in 0.1 increments for FINA)
        # Allow small float precision errors
        remainder = (dd_float * 10) % 1
        if remainder > 0.01 and remainder < 0.99:
            return False, f"DD value must be in 0.1 increments (e.g., 1.3, 2.5), got {dd_float}"

        return True, None

    def _normalize_height(self, height: str) -> str:
        """Normalize height (7m → 7.5m for FINA standard)"""
        return normalize_height(height)

    def get_all_dds(self) -> List[Dict]:
        """Return formula-defined values for the maintained dive-code catalogue."""
        entries: List[Dict] = []
        for dive in self.db.query(FINADiveCode).order_by(FINADiveCode.dive_code).all():
            for height, dd_value in self.lookup_dd_all_heights(dive.dive_code).items():
                entries.append({
                    "dive_code": dive.dive_code,
                    "height": height,
                    "platform_type": "springboard" if height in ("1m", "3m") else "platform",
                    "dd_value": float(dd_value),
                    "reference": "formula",
                })
        return entries

    def clear_cache(self):
        """Clear the DD cache"""
        self._dd_cache.clear()
