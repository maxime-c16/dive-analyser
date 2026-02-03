"""Audit log model for data change tracking"""

from datetime import datetime
from typing import Optional, Any, Dict
from sqlalchemy import Column, Integer, String, DateTime, Index, JSON

from app.database import Base


class AuditLog(Base):
    """Audit log for tracking data changes"""

    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)
    table_name = Column(String(50), nullable=True, index=True)
    record_id = Column(Integer, nullable=True, index=True)
    action = Column(String(20), nullable=True)  # INSERT, UPDATE, DELETE
    old_values = Column(JSON, nullable=True)
    new_values = Column(JSON, nullable=True)
    changed_by = Column(String(100), default="system")
    changed_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_audit_log_table", "table_name", "record_id"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog(id={self.id}, table={self.table_name}, action={self.action})>"
