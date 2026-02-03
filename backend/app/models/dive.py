"""Dive model (individual dives)"""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, CheckConstraint, Index, Numeric, func
from sqlalchemy.orm import relationship

from app.database import Base


class Dive(Base):
    """Individual dive attempt"""

    __tablename__ = "dives"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)

    # Core dive info
    dive_code = Column(String(10), nullable=False, index=True)
    dive_number = Column(String(5), nullable=True)
    position = Column(String(1), nullable=True)
    direction = Column(Integer, nullable=True, index=True)

    # Performance
    # Legacy single performance score (for backwards compatibility)
    performance = Column(String(1), nullable=False)  # F, B, M, G, P
    performance_numeric = Column(Integer, nullable=False)  # 0-4

    # New two-phase performance scoring (as of Jan 2026)
    # Phase 1: Hurdle + Flight (takeoff quality)
    # Phase 2: Opening + Water Splash + Entry (landing quality)
    phase1_performance = Column(String(1), nullable=True)  # F, B, M, G, P (hurdle + flight)
    phase1_numeric = Column(Integer, nullable=True)  # 0-4

    phase2_performance = Column(String(1), nullable=True)  # F, B, M, G, P (opening + entry)
    phase2_numeric = Column(Integer, nullable=True)  # 0-4

    # Conditions
    height = Column(String(5), nullable=False, index=True)
    platform_type = Column(String(20), default="springboard")

    # Flags
    is_lineup = Column(Boolean, default=False, index=True)
    is_sync = Column(Boolean, default=False)
    is_smack = Column(Boolean, default=False)

    # Metadata
    raw_caption = Column(Text, nullable=True)
    person_name = Column(String(100), nullable=True, index=True)
    notes = Column(Text, nullable=True)
    video_uuid = Column(String(100), unique=True, nullable=True, index=True)
    video_filename = Column(String(255), nullable=True)
    video_path = Column(Text, nullable=True)

    # Phase insight (coaching recommendation based on two-phase scores)
    phase_insight = Column(Text, nullable=True)  # e.g., "Focus on hurdle height"

    # Psychological tracking (Phase 5 - Emotional State Capture)
    pre_dive_emotion = Column(String(20), nullable=True)  # confident, nervous, excited, fearful, anxious
    post_dive_emotion = Column(String(20), nullable=True)  # satisfied, frustrated, proud, disappointed, relieved
    confidence_rating = Column(Integer, nullable=True)  # 1-5 scale

    # Official FINA Degree of Difficulty (separate from execution-based performance)
    # This is the official FINA DD value (1.2-4.1+) assigned to this dive code/height combo
    # NEW SIGNAL for journey analysis (not merged with execution-based difficulty)
    official_dd = Column(Numeric(3, 1), nullable=True)  # e.g., 1.2, 2.5, 3.8

    # Sprint 6: Migration tracking for DD population
    official_dd_assigned_at = Column(DateTime, nullable=True)  # When official_dd was assigned
    official_dd_migration_id = Column(Integer, ForeignKey("migration_logs.id"), nullable=True)  # Migration that assigned this
    official_dd_verification_status = Column(String(20), nullable=True)  # "verified", "pending_review", "failed_lookup"

    # Sync tracking
    synced_at = Column(DateTime, nullable=True, index=True)  # When video was synced from mac-agent

    # Timestamps
    dive_datetime = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    session = relationship("Session", back_populates="dives")
    execution_faults = relationship("ExecutionFault", back_populates="dive", cascade="all, delete-orphan")

    # Constraints and indexes
    __table_args__ = (
        CheckConstraint("direction >= 1 AND direction <= 5", name="check_direction"),
        CheckConstraint("performance IN ('F', 'B', 'M', 'G', 'P')", name="check_performance"),
        CheckConstraint("performance_numeric >= 0 AND performance_numeric <= 4", name="check_performance_numeric"),
        CheckConstraint("confidence_rating >= 1 AND confidence_rating <= 5 OR confidence_rating IS NULL", name="check_confidence_rating"),
        Index("idx_dives_session_date", "session_id", "dive_datetime", postgresql_using="btree"),
        Index("idx_dives_performance", "performance_numeric", postgresql_using="btree"),
        Index("idx_dives_lineup", "is_lineup", postgresql_using="btree"),
        Index("idx_dives_personal", "person_name", postgresql_using="btree"),
        Index("idx_dives_official_dd", "official_dd", postgresql_using="btree"),
        Index("idx_dives_dd_migration", "official_dd_migration_id", postgresql_using="btree"),
        Index("idx_dives_dd_verification", "official_dd_verification_status", postgresql_using="btree"),
        Index("idx_dives_pre_emotion", "pre_dive_emotion", postgresql_using="btree"),
        Index("idx_dives_post_emotion", "post_dive_emotion", postgresql_using="btree"),
        Index("idx_dives_confidence", "confidence_rating", postgresql_using="btree"),
    )

    def __repr__(self) -> str:
        return f"<Dive(id={self.id}, code={self.dive_code}, performance={self.performance})>"
