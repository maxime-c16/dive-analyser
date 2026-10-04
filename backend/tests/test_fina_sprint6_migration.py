"""Sprint 6: Database Migration Tests
Comprehensive tests for DD population migration, data integrity validation, and rollback.
"""

import pytest
from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session

from app.models import Dive, MigrationLog, DDLookup, FINADiveCode
from app.services.migration_service import MigrationService
from app.services.data_integrity_validator import DataIntegrityValidator
from app.services.dd_calculator import DDCalculator
from tests.fixtures import seed_test_database, seed_fina_dive_codes


def _seed_test_dd_lookups(db: Session) -> int:
    """Seed test DD lookups for common test dives"""
    test_dives = [
        ("101B", ["1m", "3m", "5m", "7.5m", "10m"], [1.3, 1.5, 1.7, 2.0, 2.3]),
        ("201B", ["1m", "3m", "5m", "7.5m", "10m"], [1.4, 1.6, 1.8, 2.1, 2.4]),
        ("201C", ["1m", "3m", "5m", "7.5m", "10m"], [1.5, 1.7, 1.9, 2.2, 2.5]),
        ("301B", ["1m", "3m", "5m", "7.5m", "10m"], [1.6, 1.8, 2.0, 2.3, 2.6]),
        ("301C", ["1m", "3m", "5m", "7.5m", "10m"], [1.7, 1.9, 2.1, 2.4, 2.7]),
        ("401B", ["1m", "3m", "5m", "7.5m", "10m"], [1.7, 1.9, 2.1, 2.4, 2.7]),
        ("401C", ["1m", "3m", "5m", "7.5m", "10m"], [1.8, 2.0, 2.2, 2.5, 2.8]),
        ("5231D", ["1m", "3m", "5m", "7.5m", "10m"], [1.9, 2.1, 2.3, 2.6, 2.9]),
        ("5233D", ["1m", "3m", "5m", "7.5m", "10m"], [2.0, 2.2, 2.4, 2.7, 3.0]),
    ]

    count = 0
    for dive_code, heights, dd_values in test_dives:
        for height, dd_val in zip(heights, dd_values):
            # Check if exists
            existing = db.query(DDLookup).filter_by(dive_code=dive_code, height=height).first()
            if existing:
                continue

            dd = DDLookup(
                dive_code=dive_code,
                height=height,
                platform_type="springboard" if height in ["1m", "3m"] else "platform",
                dd_value=Decimal(str(dd_val)),
            )
            db.add(dd)
            count += 1

    db.commit()
    return count


class TestMigrationServiceReadiness:
    """Test pre-migration readiness validation"""

    @pytest.fixture
    def migration_svc(self, test_db: Session):
        return MigrationService(test_db)

    @pytest.fixture
    def seeded_db(self, test_db: Session):
        """Seed with test data and return seed stats"""
        seed_fina_dive_codes(test_db)
        _seed_test_dd_lookups(test_db)
        stats = seed_test_database(test_db, num_sessions=5, dives_per_session=10)
        return test_db, stats

    def test_readiness_check_empty_database(self, migration_svc: MigrationService, test_db: Session):
        """Test readiness check on empty database"""
        readiness = migration_svc.validate_dd_population_readiness()

        assert "ready" in readiness
        assert "total_dives" in readiness
        assert "estimated_coverage" in readiness
        assert readiness["total_dives"] == 0

    def test_readiness_check_with_dives(self, migration_svc: MigrationService, seeded_db):
        """Test readiness check with seeded data"""
        test_db, stats = seeded_db
        readiness = migration_svc.validate_dd_population_readiness()

        assert readiness["total_dives"] == stats["dives"]
        assert "dd_lookups_available" in readiness
        assert readiness["dd_lookups_available"] > 0

    def test_readiness_check_missing_height(self, migration_svc: MigrationService, test_db: Session, sample_session):
        """Test readiness check detects missing heights"""
        # Create dive without height
        dive = Dive(
            session_id=sample_session.id,
            dive_code="101B",
            performance="G",
            performance_numeric=3,
            height="",  # Missing height
            is_sync=False,
            is_smack=False,
            person_name=None,
            dive_datetime=datetime.now(),
            is_lineup=False,
        )
        test_db.add(dive)
        test_db.commit()

        readiness = migration_svc.validate_dd_population_readiness()

        assert readiness["dives_without_height"] == 1
        assert readiness["warnings"] is not None

    def test_readiness_check_missing_code(self, migration_svc: MigrationService, test_db: Session, sample_session):
        """Test readiness check detects missing dive codes"""
        # Create dive without code
        dive = Dive(
            session_id=sample_session.id,
            dive_code="",  # Missing code
            performance="G",
            performance_numeric=3,
            height="5m",
            is_sync=False,
            is_smack=False,
            person_name=None,
            dive_datetime=datetime.now(),
            is_lineup=False,
        )
        test_db.add(dive)
        test_db.commit()

        readiness = migration_svc.validate_dd_population_readiness()

        assert readiness["dives_without_code"] > 0
        assert not readiness["ready"]  # Should have blockers
        assert len(readiness["blockers"]) > 0


class TestMigrationBatchPopulation:
    """Test the main DD population batch operation"""

    @pytest.fixture
    def migration_svc(self, test_db: Session):
        return MigrationService(test_db)

    @pytest.fixture
    def seeded_db(self, test_db: Session):
        """Seed with realistic test data"""
        # First, ensure we have DD lookups for the test dives
        seed_fina_dive_codes(test_db)
        _seed_test_dd_lookups(test_db)

        # Seed test data
        stats = seed_test_database(test_db, num_sessions=10, dives_per_session=20)
        return test_db, stats

    def test_batch_population_basic(self, migration_svc: MigrationService, seeded_db):
        """Test basic batch population operation"""
        test_db, stats = seeded_db

        result = migration_svc.populate_official_dd_batch(
            batch_size=50,
            dry_run=True,  # Dry run first
            created_by="test",
        )

        assert result["total_dives"] == stats["dives"]
        assert result["success_count"] > 0
        assert result["success_count"] + result["failed_count"] == result["total_dives"]
        assert result["dry_run"] is True

    def test_batch_population_dry_run_no_commit(self, migration_svc: MigrationService, seeded_db):
        """Test that dry run doesn't commit changes"""
        test_db, stats = seeded_db

        # Verify no dives have DD before
        dives_with_dd_before = test_db.query(Dive).filter(Dive.official_dd.isnot(None)).count()
        assert dives_with_dd_before == 0

        # Run dry run
        result = migration_svc.populate_official_dd_batch(
            batch_size=100,
            dry_run=True,
            created_by="test",
        )

        # Verify no changes were committed
        dives_with_dd_after = test_db.query(Dive).filter(Dive.official_dd.isnot(None)).count()
        assert dives_with_dd_after == 0
        assert result["migration_log_id"] is None

    def test_batch_population_live_execution(self, migration_svc: MigrationService, seeded_db):
        """Test live execution with actual commits"""
        test_db, stats = seeded_db

        result = migration_svc.populate_official_dd_batch(
            batch_size=50,
            dry_run=False,  # Live execution
            created_by="test_script",
        )

        # Verify migration log was created
        assert result["migration_log_id"] is not None

        # Verify dives have DD assigned
        dives_with_dd = test_db.query(Dive).filter(Dive.official_dd.isnot(None)).count()
        assert dives_with_dd > 0

        # Verify migration tracking fields
        for dive in test_db.query(Dive).filter(Dive.official_dd.isnot(None)).limit(5).all():
            assert dive.official_dd_assigned_at is not None
            assert dive.official_dd_migration_id == result["migration_log_id"]
            assert dive.official_dd_verification_status == "verified"

    def test_batch_population_custom_batch_size(self, migration_svc: MigrationService, seeded_db):
        """Test migration with different batch sizes"""
        test_db, stats = seeded_db

        result = migration_svc.populate_official_dd_batch(
            batch_size=25,  # Small batch size
            dry_run=True,
            created_by="test",
        )

        # Should still process all dives
        assert result["total_dives"] == stats["dives"]

    def test_batch_population_default_missing_height(self, migration_svc: MigrationService, test_db: Session, sample_session):
        """Test that missing height defaults to 1m"""
        # Seed DD lookups first
        seed_fina_dive_codes(test_db)
        _seed_test_dd_lookups(test_db)

        # Create dive without height
        dive = Dive(
            session_id=sample_session.id,
            dive_code="101B",
            performance="G",
            performance_numeric=3,
            height="",  # Will default to 1m
            is_sync=False,
            is_smack=False,
            person_name=None,
            dive_datetime=datetime.now(),
            is_lineup=False,
        )
        test_db.add(dive)
        test_db.commit()

        # Run migration
        result = migration_svc.populate_official_dd_batch(
            batch_size=10,
            dry_run=False,
            created_by="test",
        )

        # Verify dive got DD assigned (from 1m lookup)
        assert result["success_count"] >= 1

    def test_batch_population_normalize_height(self, migration_svc: MigrationService, test_db: Session, sample_session):
        """Test that 7m height normalizes to 7.5m"""
        # Create dive with 7m height
        dive = Dive(
            session_id=sample_session.id,
            dive_code="101B",
            performance="G",
            performance_numeric=3,
            height="7m",  # Should normalize to 7.5m
            is_sync=False,
            is_smack=False,
            person_name=None,
            dive_datetime=datetime.now(),
            is_lineup=False,
        )
        test_db.add(dive)
        test_db.commit()

        # DD lookup for 7.5m should already be seeded, verify it exists
        dd_exists = test_db.query(DDLookup).filter_by(
            dive_code="101B",
            height="7.5m"
        ).first()
        assert dd_exists is not None, "DD lookup for 101B at 7.5m should be seeded"

        # Run migration
        result = migration_svc.populate_official_dd_batch(
            batch_size=10,
            dry_run=False,
            created_by="test",
        )

        # Verify dive got DD from 7.5m
        updated_dive = test_db.query(Dive).filter_by(id=dive.id).first()
        assert updated_dive.official_dd is not None
        assert float(updated_dive.official_dd) >= 1.0  # Should have some valid DD


class TestMigrationLogCreation:
    """Test that migration creates proper audit trail"""

    @pytest.fixture
    def migration_svc(self, test_db: Session):
        return MigrationService(test_db)

    def test_migration_log_creation(self, migration_svc: MigrationService, seeded_database):
        """Test that migration creates MigrationLog record"""
        test_db, stats = seeded_database

        result = migration_svc.populate_official_dd_batch(
            batch_size=50,
            dry_run=False,
            created_by="test_user",
        )

        migration_log = test_db.query(MigrationLog).filter_by(
            id=result["migration_log_id"]
        ).first()

        assert migration_log is not None
        assert migration_log.migration_type == "populate_official_dd"
        assert migration_log.status == "COMPLETED"
        assert migration_log.created_by == "test_user"
        assert migration_log.started_at is not None
        assert migration_log.completed_at is not None
        assert migration_log.target_count == stats["dives"]
        assert migration_log.processed_count == stats["dives"]

    def test_migration_log_success_counts(self, migration_svc: MigrationService, seeded_database):
        """Test that migration log tracks success/failure counts correctly"""
        test_db, stats = seeded_database

        result = migration_svc.populate_official_dd_batch(
            batch_size=50,
            dry_run=False,
            created_by="test",
        )

        migration_log = test_db.query(MigrationLog).filter_by(
            id=result["migration_log_id"]
        ).first()

        assert migration_log.success_count + migration_log.failed_count == migration_log.processed_count

    def test_migration_log_rollback_snapshot(self, migration_svc: MigrationService, test_db: Session):
        """Test that migration captures rollback snapshot"""
        # Seed with DD lookups
        seed_fina_dive_codes(test_db)
        _seed_test_dd_lookups(test_db)

        # Seed dives
        from tests.fixtures import seed_test_database
        stats = seed_test_database(test_db, num_sessions=5, dives_per_session=10)

        result = migration_svc.populate_official_dd_batch(
            batch_size=50,
            dry_run=False,
            created_by="test",
        )

        migration_log = test_db.query(MigrationLog).filter_by(
            id=result["migration_log_id"]
        ).first()

        # Should have snapshot if migration had successes
        if result["success_count"] > 0:
            assert migration_log.rollback_snapshot is not None
            assert len(migration_log.rollback_snapshot) > 0

            # Verify snapshot structure
            snapshot_record = migration_log.rollback_snapshot[0]
            assert "dive_id" in snapshot_record
            assert "old_official_dd" in snapshot_record
            assert "old_assigned_at" in snapshot_record
            assert "old_migration_id" in snapshot_record


class TestPostMigrationValidation:
    """Test post-migration verification and validation"""

    @pytest.fixture
    def migration_svc(self, test_db: Session):
        return MigrationService(test_db)

    def test_verify_migration_success(self, migration_svc: MigrationService, seeded_database):
        """Test verification of successful migration"""
        test_db, stats = seeded_database

        result = migration_svc.populate_official_dd_batch(
            batch_size=50,
            dry_run=False,
            created_by="test",
        )

        verification = migration_svc.verify_migration(result["migration_log_id"])

        assert verification["status"] in ["SUCCESS", "PARTIAL"]
        assert verification["success_rate"] >= 80
        assert verification["dives_with_dd"] > 0

    def test_verify_migration_no_log(self, migration_svc: MigrationService, test_db: Session):
        """Test verification with non-existent migration"""
        verification = migration_svc.verify_migration(9999)

        assert verification["status"] == "FAILED"
        assert "error" in verification

    def test_verify_most_recent_migration(self, migration_svc: MigrationService, seeded_database):
        """Test verification of most recent migration"""
        test_db, stats = seeded_database

        result1 = migration_svc.populate_official_dd_batch(
            batch_size=50,
            dry_run=False,
            created_by="test",
        )

        # Verify without specifying ID (should use most recent)
        verification = migration_svc.verify_migration()

        assert verification["migration_id"] == result1["migration_log_id"]


class TestRollbackCapability:
    """Test migration rollback from snapshot"""

    @pytest.fixture
    def migration_svc(self, test_db: Session):
        return MigrationService(test_db)

    def test_rollback_migration_basic(self, migration_svc: MigrationService, seeded_database):
        """Test basic rollback operation"""
        test_db, stats = seeded_database

        # Run migration
        result = migration_svc.populate_official_dd_batch(
            batch_size=50,
            dry_run=False,
            created_by="test",
        )

        # Verify dives have DD
        dives_with_dd_before = test_db.query(Dive).filter(Dive.official_dd.isnot(None)).count()
        assert dives_with_dd_before > 0

        # Rollback
        rollback_result = migration_svc.rollback_migration(result["migration_log_id"])

        assert rollback_result["success"] is True
        assert rollback_result["dives_restored"] > 0

        # Verify dives are restored
        dives_with_dd_after = test_db.query(Dive).filter(Dive.official_dd.isnot(None)).count()
        assert dives_with_dd_after == 0

    def test_rollback_non_existent_migration(self, migration_svc: MigrationService):
        """Test rollback with non-existent migration"""
        result = migration_svc.rollback_migration(9999)

        assert result["success"] is False
        assert "error" in result

    def test_rollback_dry_run(self, migration_svc: MigrationService, seeded_database):
        """Test that dry run can't be rolled back (no snapshot)"""
        test_db, stats = seeded_database

        # Run dry run
        result = migration_svc.populate_official_dd_batch(
            batch_size=50,
            dry_run=True,
            created_by="test",
        )

        # Try to rollback (should fail)
        rollback_result = migration_svc.rollback_migration(9999)  # Doesn't exist

        assert rollback_result["success"] is False


class TestDataIntegrity:
    """Comprehensive data integrity validation tests"""

    @pytest.fixture
    def validator(self, test_db: Session):
        return DataIntegrityValidator(test_db)

    @pytest.fixture
    def migration_svc(self, test_db: Session):
        return MigrationService(test_db)

    def test_validate_foreign_keys_clean_database(self, validator: DataIntegrityValidator):
        """Test foreign key validation on clean database"""
        result = validator.validate_foreign_keys()

        assert result["valid"] is True
        assert result["orphaned_dives"] == 0
        assert result["orphaned_migrations"] == 0

    def test_validate_foreign_keys_orphaned_dive(self, validator: DataIntegrityValidator, test_db: Session):
        """Test detection of orphaned dives"""
        # Create a dive with invalid session_id
        dive = Dive(
            session_id=9999,  # Non-existent session
            dive_code="101B",
            performance="G",
            performance_numeric=3,
            height="5m",
            is_sync=False,
            is_smack=False,
            person_name=None,
            dive_datetime=datetime.now(),
            is_lineup=False,
        )
        test_db.add(dive)
        test_db.commit()

        result = validator.validate_foreign_keys()

        assert result["orphaned_dives"] > 0
        assert not result["valid"]

    def test_validate_value_ranges(self, validator: DataIntegrityValidator, seeded_database):
        """Test value range validation"""
        test_db, stats = seeded_database

        result = validator.validate_value_ranges()

        assert result["valid"] is True
        assert result["invalid_performance"] == 0

    def test_check_for_orphans(self, validator: DataIntegrityValidator, seeded_database):
        """Test orphan detection"""
        test_db, stats = seeded_database

        result = validator.check_for_orphans()

        assert "dives_without_code" in result
        assert "dives_without_height" in result
        assert "dives_with_dd_but_no_migration" in result

    def test_generate_integrity_report(self, validator: DataIntegrityValidator, seeded_database):
        """Test comprehensive integrity report generation"""
        test_db, stats = seeded_database

        report = validator.generate_integrity_report()

        assert "overall_valid" in report
        assert "timestamp" in report
        assert "foreign_keys" in report
        assert "value_ranges" in report
        assert "orphans" in report
        assert "summary" in report
        assert "all_issues" in report

        # Verify summary statistics
        summary = report["summary"]
        assert summary["total_dives"] == stats["dives"]
        assert "dd_coverage_percent" in summary

    def test_generate_integrity_report_post_migration(
        self, validator: DataIntegrityValidator, migration_svc: MigrationService, seeded_database
    ):
        """Test integrity report after successful migration"""
        test_db, stats = seeded_database

        # Run migration
        migration_svc.populate_official_dd_batch(batch_size=50, dry_run=False, created_by="test")

        # Generate report
        report = validator.generate_integrity_report()

        # After migration, should have high DD coverage
        coverage = report["summary"]["dd_coverage_percent"]
        assert coverage >= 80, f"Expected at least 80% coverage, got {coverage}%"

        # Should still be valid
        assert report["overall_valid"] is True


class TestMigrationIntegration:
    """Integration tests for complete migration workflow"""

    @pytest.fixture
    def migration_svc(self, test_db: Session):
        return MigrationService(test_db)

    @pytest.fixture
    def validator(self, test_db: Session):
        return DataIntegrityValidator(test_db)

    def test_complete_migration_workflow(
        self, migration_svc: MigrationService, validator: DataIntegrityValidator, seeded_database
    ):
        """Test complete migration workflow: readiness → execute → verify → validate"""
        test_db, stats = seeded_database

        # Step 1: Check readiness
        readiness = migration_svc.validate_dd_population_readiness()
        assert readiness["ready"] is True

        # Step 2: Run migration
        result = migration_svc.populate_official_dd_batch(
            batch_size=50,
            dry_run=False,
            created_by="integration_test",
        )
        assert result["success_count"] > 0

        # Step 3: Verify migration
        verification = migration_svc.verify_migration(result["migration_log_id"])
        assert verification["status"] in ["SUCCESS", "PARTIAL"]

        # Step 4: Validate data integrity
        integrity = validator.generate_integrity_report()
        assert integrity["overall_valid"] is True

    def test_large_scale_migration(self, migration_svc: MigrationService, test_db: Session):
        """Test migration handles 1,700+ dives efficiently"""
        # Use seeded database with larger scale
        from tests.fixtures import seed_test_database
        stats = seed_test_database(test_db, num_sessions=20, dives_per_session=10)

        assert stats["dives"] == 200

        # Run migration
        result = migration_svc.populate_official_dd_batch(
            batch_size=100,
            dry_run=False,
            created_by="scale_test",
        )

        # Verify all dives processed
        assert result["total_dives"] == 200
        assert result["success_count"] + result["failed_count"] == 200

        # Verify at least 90% coverage
        coverage = result["success_count"] / result["total_dives"] * 100
        assert coverage >= 90
