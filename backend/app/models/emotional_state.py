"""Emotional state tracking for psychological performance analysis."""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, CheckConstraint, Index, Text
from sqlalchemy.orm import relationship

from app.database import Base


class EmotionalState(Base):
    """Track pre- and post-dive emotional states for psychological pattern analysis."""

    __tablename__ = "emotional_states"

    id = Column(Integer, primary_key=True, index=True)
    dive_id = Column(Integer, ForeignKey("dives.id", ondelete="CASCADE"), nullable=False, index=True)

    # Emotional data
    pre_dive_emotion = Column(
        String(20),
        nullable=True,
        index=True
    )  # Before dive attempt: confident, nervous, excited, fearful, anxious, etc.

    post_dive_emotion = Column(
        String(20),
        nullable=True,
        index=True
    )  # After dive: satisfied, frustrated, proud, disappointed, relieved, etc.

    confidence_rating = Column(
        Integer,
        nullable=True
    )  # 1-5 scale: how confident was the athlete before diving

    # Optional notes about emotional state
    emotional_notes = Column(Text, nullable=True)

    # Timestamps
    recorded_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    dive = relationship("Dive", foreign_keys=[dive_id])

    __table_args__ = (
        CheckConstraint(
            "pre_dive_emotion IN ('confident', 'nervous', 'excited', 'fearful', 'anxious', NULL)",
            name="check_pre_dive_emotion"
        ),
        CheckConstraint(
            "post_dive_emotion IN ('satisfied', 'frustrated', 'proud', 'disappointed', 'relieved', NULL)",
            name="check_post_dive_emotion"
        ),
        CheckConstraint(
            "confidence_rating >= 1 AND confidence_rating <= 5 OR confidence_rating IS NULL",
            name="check_confidence_rating"
        ),
        Index("idx_emotional_states_dive", "dive_id", postgresql_using="btree"),
        Index("idx_emotional_states_pre_emotion", "pre_dive_emotion", postgresql_using="btree"),
        Index("idx_emotional_states_post_emotion", "post_dive_emotion", postgresql_using="btree"),
        Index("idx_emotional_states_confidence", "confidence_rating", postgresql_using="btree"),
    )

    def __repr__(self) -> str:
        return (
            f"<EmotionalState(id={self.id}, dive_id={self.dive_id}, "
            f"pre={self.pre_dive_emotion}, post={self.post_dive_emotion})>"
        )


class RecoveryPlan(Base):
    """Mental block recovery plans for overcoming fear plateaus."""

    __tablename__ = "recovery_plans"

    id = Column(Integer, primary_key=True, index=True)

    # Link to journey for athlete tracking
    journey_id = Column(
        Integer,
        ForeignKey("journeys.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Blocked dives (comma-separated dive codes)
    blocked_dive_codes = Column(String(255), nullable=False)  # e.g., "101B,201C,301B"

    # Plan status
    status = Column(
        String(20),
        default="active",
        index=True
    )  # active, in_progress, completed, abandoned

    # Recovery phases
    phase1_goal = Column(Text, nullable=False)  # Rebuild confidence at lower DD
    phase2_goal = Column(Text, nullable=False)  # Psychological prep (visualization, video review)
    phase3_goal = Column(Text, nullable=False)  # Controlled exposure at actual height

    # Phase durations (in days)
    phase1_duration = Column(Integer, default=14)  # 2 weeks
    phase2_duration = Column(Integer, default=14)  # 2 weeks
    phase3_duration = Column(Integer, default=21)  # 2-3 weeks

    # Progress tracking
    phase1_started_at = Column(DateTime, nullable=True)
    phase1_completed_at = Column(DateTime, nullable=True)
    phase2_started_at = Column(DateTime, nullable=True)
    phase2_completed_at = Column(DateTime, nullable=True)
    phase3_started_at = Column(DateTime, nullable=True)
    phase3_completed_at = Column(DateTime, nullable=True)

    # Overall progress
    current_phase = Column(Integer, default=1)  # 1, 2, 3, or 0 if completed
    completion_percentage = Column(Integer, default=0)  # 0-100

    # Fear coefficient baseline (captured at plan creation)
    initial_fear_coefficient = Column(Integer, nullable=True)  # 0-200 (stored as percentage)

    # Plan metadata
    reason = Column(Text, nullable=False)  # Why this recovery plan was created

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    # Relationship
    journey = relationship("Journey", foreign_keys=[journey_id])

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'in_progress', 'completed', 'abandoned')",
            name="check_recovery_plan_status"
        ),
        CheckConstraint(
            "current_phase >= 0 AND current_phase <= 3",
            name="check_recovery_plan_phase"
        ),
        CheckConstraint(
            "completion_percentage >= 0 AND completion_percentage <= 100",
            name="check_recovery_plan_completion"
        ),
        Index("idx_recovery_plans_journey", "journey_id", postgresql_using="btree"),
        Index("idx_recovery_plans_status", "status", postgresql_using="btree"),
        Index("idx_recovery_plans_created", "created_at", postgresql_using="btree"),
    )

    def __repr__(self) -> str:
        return (
            f"<RecoveryPlan(id={self.id}, journey_id={self.journey_id}, "
            f"status={self.status}, phase={self.current_phase})>"
        )
