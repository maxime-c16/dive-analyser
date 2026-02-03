"""Migration Log model for tracking database migration operations"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, JSON, Index, CheckConstraint
from sqlalchemy.orm import relationship

from app.database import Base


class MigrationLog(Base):
    """Audit trail for migration operations"""

    __tablename__ = "migration_logs"

    id = Column(Integer, primary_key=True, index=True)

    # Type of migration (e.g., "populate_official_dd", "rollback_official_dd")
    migration_type = Column(String(50), nullable=False, index=True)

    # Status: PENDING, IN_PROGRESS, COMPLETED, FAILED
    status = Column(String(20), nullable=False, default="PENDING", index=True)

    # Target count of records to process
    target_count = Column(Integer, nullable=False, default=0)

    # Processed count (records attempted)
    processed_count = Column(Integer, nullable=False, default=0)

    # Successfully migrated records
    success_count = Column(Integer, nullable=False, default=0)

    # Failed records
    failed_count = Column(Integer, nullable=False, default=0)

    # JSON array of error details (for debugging)
    # Format: [{"dive_id": 123, "error": "Missing dive code", "timestamp": "2026-02-02T..."}]
    error_details = Column(JSON, nullable=True)

    # JSON snapshot of affected records before migration (for rollback)
    # Stored as list of {id, old_official_dd, old_assigned_at, old_migration_id}
    rollback_snapshot = Column(JSON, nullable=True)

    # Timestamps
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # User who initiated migration
    created_by = Column(String(100), default="system")

    # Additional notes
    notes = Column(String(500), nullable=True)

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED')",
            name="check_migration_status",
        ),
        CheckConstraint(
            "processed_count >= 0 AND success_count >= 0 AND failed_count >= 0",
            name="check_migration_counts_non_negative",
        ),
        CheckConstraint(
            "processed_count = success_count + failed_count",
            name="check_migration_counts_sum",
        ),
        Index("idx_migration_logs_type_status", "migration_type", "status"),
        Index("idx_migration_logs_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<MigrationLog(id={self.id}, type={self.migration_type}, "
            f"status={self.status}, success={self.success_count}/{self.target_count})>"
        )
