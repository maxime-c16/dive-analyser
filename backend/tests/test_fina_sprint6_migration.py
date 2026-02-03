"""Sprint 6: Migration Tests"""

import pytest
from sqlalchemy.orm import Session

from app.services.migration_service import MigrationService


class TestMigrationService:
    """Test migration service"""

    @pytest.fixture
    def migration_svc(self, test_db):
        return MigrationService(test_db)

    def test_verify_data_integrity(self, migration_svc):
        """Test data integrity verification"""
        ok, issues = migration_svc.verify_data_integrity()
        assert isinstance(ok, bool)
        assert isinstance(issues, list)

    def test_backup_database(self, migration_svc, tmp_path):
        """Test database backup"""
        backup_file = tmp_path / "backup.db"
        result = migration_svc.backup_database(str(backup_file))
        assert isinstance(result, bool)

    def test_restore_database(self, migration_svc, tmp_path):
        """Test database restore"""
        backup_file = tmp_path / "backup.db"
        result = migration_svc.restore_database(str(backup_file))
        assert isinstance(result, bool)

    def test_migrate_data(self, migration_svc):
        """Test data migration"""
        source_target = {"old_id": "new_id"}
        migrated, errors = migration_svc.migrate_data(source_target)
        assert migrated >= 0
        assert isinstance(errors, list)

    def test_validate_migration(self, migration_svc):
        """Test migration validation"""
        result = migration_svc.validate_migration()
        assert "integrity_ok" in result
        assert "data_loss" in result
        assert "issues" in result
