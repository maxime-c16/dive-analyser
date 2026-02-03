"""DD Lookup Table Manager - manages bulk DD lookups and updates"""

from typing import List, Dict, Optional, Tuple
from decimal import Decimal
from datetime import datetime
from sqlalchemy.orm import Session

from app.models import DDLookup, FINADiveCode


class DDLookupError(Exception):
    """Raised when DD lookup operations fail"""
    pass


class DDLookupManager:
    """Manages DD lookup table operations"""

    def __init__(self, db: Session):
        """Initialize manager with database session"""
        self.db = db

    def add_dd_entry(
        self,
        dive_code: str,
        height: str,
        dd_value: Decimal,
        platform_type: str = "springboard",
        notes: Optional[str] = None,
    ) -> DDLookup:
        """
        Add a DD entry to the database.

        Args:
            dive_code: FINA dive code
            height: Height (1m, 3m, 5m, 7.5m, 10m)
            dd_value: DD value
            platform_type: springboard or platform
            notes: Optional notes

        Returns:
            Created DDLookup object
        """
        # Validate dive code exists
        dive = self.db.query(FINADiveCode).filter_by(dive_code=dive_code).first()
        if not dive:
            raise DDLookupError(f"Dive code '{dive_code}' not found in FINA database")

        # Normalize height
        height = self._normalize_height(height)

        # Validate DD value
        valid, error_msg = self._validate_dd(dd_value)
        if not valid:
            raise DDLookupError(f"Invalid DD value: {error_msg}")

        # Create or update entry
        existing = (
            self.db.query(DDLookup)
            .filter_by(dive_code=dive_code, height=height, platform_type=platform_type)
            .first()
        )

        if existing:
            # Update existing
            existing.dd_value = dd_value
            existing.notes = notes
            existing.updated_at = datetime.utcnow()
            self.db.commit()
            return existing
        else:
            # Create new
            entry = DDLookup(
                dive_code=dive_code,
                height=height,
                platform_type=platform_type,
                dd_value=dd_value,
                notes=notes,
                effective_date=datetime.utcnow(),
            )
            self.db.add(entry)
            self.db.commit()
            return entry

    def add_dd_batch(self, entries: List[Dict]) -> Tuple[int, List[str]]:
        """
        Add multiple DD entries in batch.

        Args:
            entries: List of dicts with dive_code, height, dd_value, platform_type, notes

        Returns:
            (successfully_added, errors)
        """
        success_count = 0
        errors = []

        for i, entry in enumerate(entries):
            try:
                self.add_dd_entry(
                    dive_code=entry["dive_code"],
                    height=entry.get("height", "1m"),
                    dd_value=Decimal(str(entry["dd_value"])),
                    platform_type=entry.get("platform_type", "springboard"),
                    notes=entry.get("notes"),
                )
                success_count += 1
            except DDLookupError as e:
                errors.append(f"Entry {i}: {str(e)}")
            except Exception as e:
                errors.append(f"Entry {i}: Unexpected error: {str(e)}")

        return success_count, errors

    def update_dd_value(
        self,
        dive_code: str,
        height: str,
        new_dd_value: Decimal,
        platform_type: str = "springboard",
    ) -> bool:
        """
        Update a DD value.

        Returns: True if updated, False if not found
        """
        height = self._normalize_height(height)

        lookup = (
            self.db.query(DDLookup)
            .filter_by(dive_code=dive_code, height=height, platform_type=platform_type)
            .first()
        )

        if not lookup:
            return False

        valid, error_msg = self._validate_dd(new_dd_value)
        if not valid:
            raise DDLookupError(f"Invalid DD value: {error_msg}")

        lookup.dd_value = new_dd_value
        lookup.updated_at = datetime.utcnow()
        self.db.commit()
        return True

    def delete_dd_entry(
        self,
        dive_code: str,
        height: str,
        platform_type: str = "springboard",
    ) -> bool:
        """
        Delete a DD entry.

        Returns: True if deleted, False if not found
        """
        height = self._normalize_height(height)

        lookup = (
            self.db.query(DDLookup)
            .filter_by(dive_code=dive_code, height=height, platform_type=platform_type)
            .first()
        )

        if not lookup:
            return False

        self.db.delete(lookup)
        self.db.commit()
        return True

    def get_dd_by_dive(self, dive_code: str) -> List[Dict]:
        """Get all DD entries for a dive code"""
        lookups = self.db.query(DDLookup).filter_by(dive_code=dive_code).all()

        return [
            {
                "height": lookup.height,
                "platform_type": lookup.platform_type,
                "dd_value": float(lookup.dd_value),
            }
            for lookup in lookups
        ]

    def get_dd_by_height(self, height: str) -> List[Dict]:
        """Get all DD entries for a specific height"""
        height = self._normalize_height(height)

        lookups = self.db.query(DDLookup).filter_by(height=height).all()

        return [
            {
                "dive_code": lookup.dive_code,
                "dd_value": float(lookup.dd_value),
            }
            for lookup in lookups
        ]

    def get_dd_statistics(self) -> Dict:
        """Get statistics about DD table coverage"""
        total_lookups = self.db.query(DDLookup).count()

        heights = self.db.query(DDLookup.height).distinct().all()
        platforms = self.db.query(DDLookup.platform_type).distinct().all()

        return {
            "total_entries": total_lookups,
            "heights": [h[0] for h in heights],
            "platforms": [p[0] for p in platforms],
        }

    def verify_completeness(self) -> Dict:
        """
        Verify that DD table is complete.

        Returns dict with coverage information
        """
        # Get all FINA dives
        all_dives = self.db.query(FINADiveCode).count()

        # Get unique dive codes in DD table
        dd_dives = self.db.query(DDLookup.dive_code).distinct().count()

        # Get heights covered
        heights = ["1m", "3m", "5m", "7.5m", "10m"]
        coverage_by_height = {}

        for height in heights:
            count = self.db.query(DDLookup).filter_by(height=height).count()
            coverage_by_height[height] = count

        return {
            "total_fina_dives": all_dives,
            "dives_with_dd": dd_dives,
            "coverage_percentage": (dd_dives / all_dives * 100) if all_dives > 0 else 0,
            "coverage_by_height": coverage_by_height,
            "total_dd_entries": self.db.query(DDLookup).count(),
        }

    def _normalize_height(self, height: str) -> str:
        """Normalize height"""
        height = height.lower().strip()
        normalization = {"7m": "7.5m"}
        return normalization.get(height, height)

    def _validate_dd(self, dd_value: Decimal) -> Tuple[bool, Optional[str]]:
        """Validate DD value"""
        try:
            dd_float = float(dd_value)

            if dd_float < 1.0 or dd_float > 5.0:
                return False, f"DD value must be between 1.0 and 5.0, got {dd_float}"

            # Check increments (0.1 allowed)
            remainder = (dd_float * 10) % 1
            if remainder > 0.01 and remainder < 0.99:
                return False, f"DD value must be in 0.1 increments, got {dd_float}"

            return True, None
        except Exception as e:
            return False, str(e)
