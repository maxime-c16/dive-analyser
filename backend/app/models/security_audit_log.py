"""P8 security audit trail model (MEDIA_BACKBONE_P8 §26).

Minimal, privacy-safe audit trail for account/authorization lifecycle
events. Records event type, actor/operator context, target ids, timestamp
and non-secret metadata. NEVER stores passwords, session tokens, cookies,
presigned URLs or credential material. Strictly additive; reversible by
dropping the table (see backend/migrations/add_security_audit_log.sql).
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, String, Text

from app.database import Base


class SecurityAuditEvent(Base):
    __tablename__ = "security_audit_log"

    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String(40), nullable=False, index=True)
    actor_context = Column(String(40), nullable=False, default="system")
    actor_note = Column(String(120), nullable=True)
    target_user_id = Column(Integer, nullable=True, index=True)
    target_diver_id = Column(Integer, nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, index=True
    )

    __table_args__ = (
        Index("ix_security_audit_event_time", "event_type", "created_at"),
        Index("ix_security_audit_target_user_time", "target_user_id", "created_at"),
    )
