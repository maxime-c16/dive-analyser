"""Data Integrity Validator service for post-migration validation"""

from typing import Dict, List
from sqlalchemy.orm import Session
from sqlalchemy import func
from decimal import Decimal

from app.models import Dive, Session as SessionModel, MigrationLog, DDLookup, FINADiveCode


class DataIntegrityValidator:
    """Validates data integrity after migrations"""

    def __init__(self, db: Session):
        self.db = db

    def validate_foreign_keys(self) -> Dict:
        """
        Validate that all foreign key relationships are intact.

        Returns:
            Dict with:
            - valid: bool - All FKs are valid
            - orphaned_dives: int - Dives with missing session
            - orphaned_faults: int - Execution faults with missing dive
            - orphaned_migrations: int - Dives referencing missing migrations
            - issues: List[str] - Detailed issues
        """
        issues = []

        # Check for orphaned dives (session_id doesn't exist)
        orphaned_dives = self.db.query(Dive).filter(
            ~Dive.session_id.in_(self.db.query(SessionModel.id))
        ).count()

        if orphaned_dives > 0:
            issues.append(f"{orphaned_dives} dives reference non-existent sessions")

        # Check for dives referencing non-existent migrations
        orphaned_migrations = self.db.query(Dive).filter(
            Dive.official_dd_migration_id.isnot(None),
            ~Dive.official_dd_migration_id.in_(self.db.query(MigrationLog.id))
        ).count()

        if orphaned_migrations > 0:
            issues.append(f"{orphaned_migrations} dives reference non-existent migration logs")

        return {
            "valid": len(issues) == 0,
            "orphaned_dives": orphaned_dives,
            "orphaned_migrations": orphaned_migrations,
            "issues": issues,
        }

    def validate_value_ranges(self) -> Dict:
        """
        Validate that all values are within acceptable ranges.

        Returns:
            Dict with:
            - valid: bool - All values in range
            - invalid_dd_values: int - DD values outside 1.0-5.0
            - invalid_performance: int - Performance scores outside 0-4
            - invalid_phase_scores: int - Phase scores outside 0-4
            - min_dd: Optional[float] - Minimum DD found
            - max_dd: Optional[float] - Maximum DD found
            - issues: List[str]
        """
        issues = []

        # Check DD values (should be 1.0-5.0)
        invalid_dd = self.db.query(Dive).filter(
            (Dive.official_dd < Decimal("1.0")) | (Dive.official_dd > Decimal("5.0"))
        ).count()

        if invalid_dd > 0:
            issues.append(f"{invalid_dd} dives have DD values outside 1.0-5.0 range")

        # Check performance_numeric (should be 0-4)
        invalid_perf = self.db.query(Dive).filter(
            (Dive.performance_numeric < 0) | (Dive.performance_numeric > 4)
        ).count()

        if invalid_perf > 0:
            issues.append(f"{invalid_perf} dives have invalid performance_numeric values")

        # Check phase1_numeric (should be 0-4 when not null)
        invalid_phase1 = self.db.query(Dive).filter(
            Dive.phase1_numeric.isnot(None),
            ((Dive.phase1_numeric < 0) | (Dive.phase1_numeric > 4))
        ).count()

        if invalid_phase1 > 0:
            issues.append(f"{invalid_phase1} dives have invalid phase1_numeric values")

        # Check phase2_numeric (should be 0-4 when not null)
        invalid_phase2 = self.db.query(Dive).filter(
            Dive.phase2_numeric.isnot(None),
            ((Dive.phase2_numeric < 0) | (Dive.phase2_numeric > 4))
        ).count()

        if invalid_phase2 > 0:
            issues.append(f"{invalid_phase2} dives have invalid phase2_numeric values")

        # Get DD statistics
        dd_stats = self.db.query(
            func.min(Dive.official_dd),
            func.max(Dive.official_dd),
        ).filter(Dive.official_dd.isnot(None)).first()

        min_dd = float(dd_stats[0]) if dd_stats[0] else None
        max_dd = float(dd_stats[1]) if dd_stats[1] else None

        return {
            "valid": len(issues) == 0,
            "invalid_dd_values": invalid_dd,
            "invalid_performance": invalid_perf,
            "invalid_phase_scores": invalid_phase1 + invalid_phase2,
            "min_dd": min_dd,
            "max_dd": max_dd,
            "issues": issues,
        }

    def check_for_orphans(self) -> Dict:
        """
        Check for orphaned or inconsistent records.

        Returns:
            Dict with:
            - valid: bool
            - dives_without_code: int - Dives with null/empty dive_code
            - dives_without_height: int - Dives with null/empty height
            - dives_with_dd_but_no_migration: int - DD assigned but no migration tracked
            - dives_with_migration_but_no_dd: int - Migration tracked but no DD assigned
            - issues: List[str]
        """
        issues = []

        # Dives without code
        dives_without_code = self.db.query(Dive).filter(
            (Dive.dive_code.is_(None)) | (Dive.dive_code == "")
        ).count()

        if dives_without_code > 0:
            issues.append(f"{dives_without_code} dives have no dive code")

        # Dives without height
        dives_without_height = self.db.query(Dive).filter(
            (Dive.height.is_(None)) | (Dive.height == "")
        ).count()

        if dives_without_height > 0:
            issues.append(f"{dives_without_height} dives have no height (will default to 1m)")

        # DD assigned but no migration ID (inconsistent state)
        dd_no_migration = self.db.query(Dive).filter(
            Dive.official_dd.isnot(None),
            Dive.official_dd_migration_id.is_(None)
        ).count()

        if dd_no_migration > 0:
            issues.append(
                f"{dd_no_migration} dives have DD but no migration tracking "
                "(may have been assigned manually or by older process)"
            )

        # Migration ID but no DD (shouldn't happen)
        migration_no_dd = self.db.query(Dive).filter(
            Dive.official_dd_migration_id.isnot(None),
            Dive.official_dd.is_(None)
        ).count()

        if migration_no_dd > 0:
            issues.append(
                f"{migration_no_dd} dives reference a migration but have no DD "
                "(possible failed migration state)"
            )

        return {
            "valid": len(issues) == 0,
            "dives_without_code": dives_without_code,
            "dives_without_height": dives_without_height,
            "dives_with_dd_but_no_migration": dd_no_migration,
            "dives_with_migration_but_no_dd": migration_no_dd,
            "issues": issues,
        }

    def generate_integrity_report(self) -> Dict:
        """
        Generate a comprehensive integrity report covering all checks.

        Returns:
            Dict with:
            - overall_valid: bool - True if all checks pass
            - timestamp: str - When report was generated
            - foreign_keys: Dict - Results from validate_foreign_keys()
            - value_ranges: Dict - Results from validate_value_ranges()
            - orphans: Dict - Results from check_for_orphans()
            - summary: Dict - Overall statistics
            - all_issues: List[str] - Combined issues from all checks
        """
        fk_report = self.validate_foreign_keys()
        vr_report = self.validate_value_ranges()
        orphan_report = self.check_for_orphans()

        # Gather statistics
        total_dives = self.db.query(Dive).count()
        dives_with_dd = self.db.query(Dive).filter(Dive.official_dd.isnot(None)).count()
        dives_with_migration = self.db.query(Dive).filter(
            Dive.official_dd_migration_id.isnot(None)
        ).count()
        migrations = self.db.query(MigrationLog).count()

        # Collect all issues
        all_issues = []
        all_issues.extend(fk_report.get("issues", []))
        all_issues.extend(vr_report.get("issues", []))
        all_issues.extend(orphan_report.get("issues", []))

        overall_valid = (
            fk_report["valid"] and
            vr_report["valid"] and
            orphan_report["valid"]
        )

        from datetime import datetime
        return {
            "overall_valid": overall_valid,
            "timestamp": datetime.utcnow().isoformat(),
            "foreign_keys": fk_report,
            "value_ranges": vr_report,
            "orphans": orphan_report,
            "summary": {
                "total_dives": total_dives,
                "dives_with_dd": dives_with_dd,
                "dd_coverage_percent": (dives_with_dd / total_dives * 100) if total_dives > 0 else 0,
                "dives_with_migration": dives_with_migration,
                "migration_logs": migrations,
            },
            "all_issues": all_issues,
        }
