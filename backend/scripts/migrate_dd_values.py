#!/usr/bin/env python3
"""
Sprint 6 Migration Script: Populate official_dd for all dives

This script uses the Sprint 3 DDCalculator to populate the official_dd field
for all 1,721+ dives in the production database.

Usage:
    python scripts/migrate_dd_values.py                    # Dry run
    python scripts/migrate_dd_values.py --execute           # Actually commit
    python scripts/migrate_dd_values.py --batch-size 200    # Custom batch size
    python scripts/migrate_dd_values.py --execute --batch-size 50

Modes:
    --dry-run (default)     : Shows what would happen, doesn't commit
    --execute               : Commits changes to database
    --verify-only           : Skips migration, just verifies most recent one
    --rollback MIGRATION_ID : Rolls back a migration
"""

import argparse
import json
import sys
from datetime import datetime

# Add backend to path so we can import app modules
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.services.migration_service import MigrationService
from app.services.data_integrity_validator import DataIntegrityValidator


def print_section(title: str):
    """Print a formatted section header"""
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}\n")


def print_result(label: str, value, color: str = ""):
    """Print a result with formatting"""
    if isinstance(value, bool):
        value_str = "✓ YES" if value else "✗ NO"
    elif isinstance(value, float):
        value_str = f"{value:.1f}%"
    elif isinstance(value, int):
        value_str = f"{value:,}"
    else:
        value_str = str(value)

    print(f"  {label:<40} {value_str}")


def validate_readiness(migration_svc: MigrationService):
    """Check if system is ready for migration"""
    print_section("Pre-Migration Readiness Check")

    readiness = migration_svc.validate_dd_population_readiness()

    print_result("System Ready", readiness["ready"])
    print_result("Total Dives", readiness["total_dives"])
    print_result("DD Lookups Available", readiness["dd_lookups_available"])
    print_result("Estimated Coverage", readiness["estimated_coverage"])
    print_result("Dives Without Height", readiness["dives_without_height"])
    print_result("Dives Without Code", readiness["dives_without_code"])

    if readiness["blockers"]:
        print("\n  BLOCKERS:")
        for blocker in readiness["blockers"]:
            print(f"    ✗ {blocker}")
        return False

    if readiness["warnings"]:
        print("\n  WARNINGS:")
        for warning in readiness["warnings"]:
            print(f"    ! {warning}")

    return readiness["ready"]


def run_migration(migration_svc: MigrationService, batch_size: int, dry_run: bool):
    """Execute the migration"""
    print_section(f"Migration Execution ({'DRY RUN' if dry_run else 'LIVE'})")

    mode = "DRY RUN (no commits)" if dry_run else "LIVE (will commit)"
    print(f"  Mode: {mode}")
    print(f"  Batch Size: {batch_size}\n")

    result = migration_svc.populate_official_dd_batch(
        batch_size=batch_size,
        dry_run=dry_run,
        created_by="migrate_dd_values.py script",
    )

    print_result("Total Dives Processed", result["total_dives"])
    print_result("Successfully Assigned", result["success_count"])
    print_result("Failed Lookups", result["failed_count"])
    success_rate = (
        (result["success_count"] / result["total_dives"] * 100)
        if result["total_dives"] > 0
        else 0
    )
    print_result("Success Rate", success_rate)

    if result["error_details"]:
        print(f"\n  ERRORS ({len(result['error_details'])} total):")
        # Show first 5 errors
        for error in result["error_details"][:5]:
            print(f"    - Dive {error.get('dive_id', '?')}: {error.get('error', '?')}")
        if len(result["error_details"]) > 5:
            print(f"    ... and {len(result['error_details']) - 5} more")

    if not dry_run and result["migration_log_id"]:
        print(f"\n  Migration Log ID: {result['migration_log_id']}")

    return result


def verify_migration(migration_svc: MigrationService, migration_id: int = None):
    """Verify migration results"""
    print_section("Post-Migration Verification")

    verification = migration_svc.verify_migration(migration_id)

    if "error" in verification:
        print(f"  ERROR: {verification['error']}")
        return False

    print_result("Verification Status", verification["status"])
    print_result("Total Processed", verification["total_processed"])
    print_result("Success Count", verification["success_count"])
    print_result("Failed Count", verification["failed_count"])
    print_result("Success Rate", verification["success_rate"])
    print_result("Dives With DD", verification["dives_with_dd"])
    print_result("Dives Without DD", verification["unassigned_dives"])

    if verification["validation_issues"]:
        print("\n  VALIDATION ISSUES:")
        for issue in verification["validation_issues"]:
            print(f"    ! {issue}")

    return verification["status"] == "SUCCESS"


def validate_data_integrity(validator: DataIntegrityValidator):
    """Run comprehensive data integrity checks"""
    print_section("Data Integrity Validation")

    report = validator.generate_integrity_report()

    print_result("Overall Valid", report["overall_valid"])
    print_result("Total Dives", report["summary"]["total_dives"])
    print_result("Dives With DD", report["summary"]["dives_with_dd"])
    print_result("DD Coverage", report["summary"]["dd_coverage_percent"])

    if not report["overall_valid"]:
        print("\n  ISSUES FOUND:")
        for issue in report["all_issues"][:10]:
            print(f"    ! {issue}")
        if len(report["all_issues"]) > 10:
            print(f"    ... and {len(report['all_issues']) - 10} more")

    return report["overall_valid"]


def rollback_migration(migration_svc: MigrationService, migration_id: int):
    """Rollback a migration"""
    print_section(f"Rolling Back Migration {migration_id}")

    result = migration_svc.rollback_migration(migration_id)

    if result["success"]:
        print_result("Rollback Status", "SUCCESS")
        print_result("Dives Restored", result["dives_restored"])
        print(f"\n  Message: {result['message']}")
    else:
        print_result("Rollback Status", "FAILED")
        print(f"\n  Error: {result.get('error', 'Unknown error')}")

    return result["success"]


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Sprint 6: Migrate official_dd values for all dives",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually commit changes (default is dry run)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of dives per batch (default 100)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Skip migration, just verify most recent one",
    )
    parser.add_argument(
        "--rollback",
        type=int,
        metavar="MIGRATION_ID",
        help="Rollback a migration by ID",
    )
    parser.add_argument(
        "--check-integrity",
        action="store_true",
        help="Run comprehensive data integrity checks",
    )

    args = parser.parse_args()

    # Get database session
    db = SessionLocal()

    try:
        migration_svc = MigrationService(db)
        validator = DataIntegrityValidator(db)

        print_section("Sprint 6: Official DD Migration")
        print(f"  Timestamp: {datetime.now().isoformat()}")
        print(f"  Mode: {'LIVE' if args.execute else 'DRY RUN'}")

        # Handle rollback
        if args.rollback:
            success = rollback_migration(migration_svc, args.rollback)
            sys.exit(0 if success else 1)

        # Handle verify-only
        if args.verify_only:
            success = verify_migration(migration_svc)
            if args.check_integrity:
                validate_data_integrity(validator)
            sys.exit(0 if success else 1)

        # Normal migration flow
        # Step 1: Readiness check
        if not validate_readiness(migration_svc):
            print("\n  STOPPING: System not ready for migration")
            sys.exit(1)

        # Step 2: Run migration
        result = run_migration(migration_svc, args.batch_size, dry_run=not args.execute)

        if args.execute:
            # Step 3: Verify migration
            success = verify_migration(migration_svc, result["migration_log_id"])

            # Step 4: Optional integrity check
            if args.check_integrity:
                integrity_ok = validate_data_integrity(validator)
                success = success and integrity_ok

            print_section("Migration Complete")
            if success:
                print("  ✓ Migration completed successfully")
                print(f"  - {result['success_count']:,} dives populated with official_dd")
                print(f"  - {result['failed_count']} lookups failed")
                sys.exit(0)
            else:
                print("  ✗ Migration completed with issues")
                sys.exit(1)
        else:
            print_section("Dry Run Complete")
            print(f"  Would populate {result['success_count']:,} dives")
            print(f"  Would fail {result['failed_count']} lookups")
            print("\n  Run with --execute to actually commit changes")
            sys.exit(0)

    except Exception as e:
        print_section("ERROR")
        print(f"  {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    finally:
        db.close()


if __name__ == "__main__":
    main()
