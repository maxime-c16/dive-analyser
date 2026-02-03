"""Journey and Milestone models for tracking diver progression."""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, CheckConstraint, Index
from sqlalchemy.orm import relationship

from app.database import Base


class Journey(Base):
    """A diver's progression and milestone history."""

    __tablename__ = "journeys"

    id = Column(Integer, primary_key=True, index=True)

    # Journey identification
    journey_code = Column(String(50), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)

    # Timeline
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_milestone_date = Column(DateTime, nullable=True, index=True)

    # Statistics
    total_dives = Column(Integer, default=0)
    milestones_count = Column(Integer, default=0)
    success_rate = Column(Integer, default=0)  # Percentage: 0-100

    # Status
    is_active = Column(Integer, default=1, index=True)  # 1=active, 0=archived

    # Relationships
    milestones = relationship("JourneyMilestone", back_populates="journey", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_journeys_created", "created_at", postgresql_using="btree"),
        Index("idx_journeys_last_milestone", "last_milestone_date", postgresql_using="btree"),
    )

    def __repr__(self) -> str:
        return f"<Journey(id={self.id}, code={self.journey_code}, milestones={self.milestones_count})>"


class JourneyMilestone(Base):
    """A meaningful moment detected in a Journey."""

    __tablename__ = "journey_milestones"

    id = Column(Integer, primary_key=True, index=True)
    journey_id = Column(Integer, ForeignKey("journeys.id", ondelete="CASCADE"), nullable=False, index=True)

    # Milestone type and context
    type = Column(String(50), nullable=False, index=True)  # e.g., 'first_success', 'breakthrough'
    dive_code = Column(String(10), nullable=True, index=True)
    height = Column(String(5), nullable=True)

    # Narrative
    title = Column(String(255), nullable=False)  # e.g., "First Perfect Dive"
    narrative = Column(Text, nullable=False)  # Human-readable description

    # Context metrics
    attempts_before = Column(Integer, default=0)
    failures_before = Column(Integer, default=0)
    days_since_last = Column(Integer, default=0)
    streak_length = Column(Integer, default=0)

    # Visual representation
    emoji = Column(String(10), default="🏊")
    significance = Column(Integer, default=1)  # 1-5 scale: importance of milestone

    # Reference to triggering dive
    dive_uuid = Column(String(100), nullable=True, index=True)

    # Two-phase performance insights (new Jan 2026)
    phase1_performance = Column(String(1), nullable=True)  # Hurdle + Flight
    phase2_performance = Column(String(1), nullable=True)  # Opening + Entry
    phase_insight = Column(Text, nullable=True)  # Coaching recommendation

    # Timestamps
    detected_date = Column(DateTime, default=datetime.utcnow, index=True)  # When detected
    occurrence_date = Column(DateTime, nullable=False, index=True)  # When the milestone happened

    # Relationship
    journey = relationship("Journey", back_populates="milestones")

    __table_args__ = (
        CheckConstraint("significance >= 1 AND significance <= 5", name="check_milestone_significance"),
        Index("idx_milestones_journey_date", "journey_id", "occurrence_date", postgresql_using="btree"),
        Index("idx_milestones_type", "type", postgresql_using="btree"),
        Index("idx_milestones_dive_code", "dive_code", postgresql_using="btree"),
    )

    def __repr__(self) -> str:
        return f"<JourneyMilestone(id={self.id}, type={self.type}, journey={self.journey_id})>"
