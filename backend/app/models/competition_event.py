"""Competition Event models for FINA event management"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, CheckConstraint, Index
from sqlalchemy.orm import relationship

from app.database import Base


class CompetitionEvent(Base):
    """Official competition event"""

    __tablename__ = "competition_events"

    id = Column(Integer, primary_key=True, index=True)

    # Event identification
    event_name = Column(String(255), nullable=False)
    event_code = Column(String(50), nullable=False, unique=True, index=True)

    # Reference to FINA scoring rules
    fina_scoring_rule_id = Column(Integer, ForeignKey("fina_scoring_rules.id"), nullable=False)

    # Event status
    status = Column(String(20), default="DRAFT", nullable=False, index=True)
    # Values: DRAFT, REGISTRATION, ACTIVE, COMPLETED

    # Event details
    location = Column(String(255), nullable=True)
    organizer = Column(String(255), nullable=True)
    is_fina_official = Column(Boolean, default=False)

    # Dates
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    scoring_rule = relationship("FINAScoringRule")
    rounds = relationship("CompetitionRound", back_populates="event", cascade="all, delete-orphan")
    competitors = relationship("CompetitionCompetitor", back_populates="event", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT', 'REGISTRATION', 'ACTIVE', 'COMPLETED')",
            name="check_event_status"
        ),
        Index("idx_competition_events_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<CompetitionEvent(code={self.event_code}, status={self.status})>"


class CompetitionRound(Base):
    """Round within a competition event"""

    __tablename__ = "competition_rounds"

    id = Column(Integer, primary_key=True, index=True)

    event_id = Column(Integer, ForeignKey("competition_events.id", ondelete="CASCADE"), nullable=False)
    round_number = Column(Integer, nullable=False)
    round_type = Column(String(20), nullable=False)
    # Values: PRELIMINARY, SEMI_FINAL, FINAL

    # DD limit for synchronized events (NULL for no limit)
    dd_limit = Column(Integer, nullable=True)  # e.g., 2 for first 2 rounds of synchronized

    completed = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    event = relationship("CompetitionEvent", back_populates="rounds")
    heats = relationship("CompetitionHeat", back_populates="round", cascade="all, delete-orphan")
    dive_entries = relationship("CompetitionDiveEntry", back_populates="round", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(
            "round_type IN ('PRELIMINARY', 'SEMI_FINAL', 'FINAL')",
            name="check_round_type"
        ),
        Index("idx_competition_rounds_event", "event_id"),
        Index("idx_competition_rounds_type", "round_type"),
    )

    def __repr__(self) -> str:
        return f"<CompetitionRound(event_id={self.event_id}, round={self.round_number})>"


class CompetitionHeat(Base):
    """Heat (group) within a round"""

    __tablename__ = "competition_heats"

    id = Column(Integer, primary_key=True, index=True)

    round_id = Column(Integer, ForeignKey("competition_rounds.id", ondelete="CASCADE"), nullable=False)
    heat_number = Column(Integer, nullable=False)
    heat_name = Column(String(100), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    round = relationship("CompetitionRound", back_populates="heats")

    __table_args__ = (
        Index("idx_competition_heats_round", "round_id"),
    )

    def __repr__(self) -> str:
        return f"<CompetitionHeat(round_id={self.round_id}, heat={self.heat_number})>"


class CompetitionCompetitor(Base):
    """Competitor in a competition event"""

    __tablename__ = "competition_competitors"

    id = Column(Integer, primary_key=True, index=True)

    event_id = Column(Integer, ForeignKey("competition_events.id", ondelete="CASCADE"), nullable=False)
    competitor_name = Column(String(255), nullable=False)
    country_code = Column(String(2), nullable=True)  # ISO 3166-1 alpha-2

    world_rank = Column(Integer, nullable=True)

    status = Column(String(20), default="REGISTERED", nullable=False)
    # Values: REGISTERED, COMPETING, DISQUALIFIED, WITHDREW

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    event = relationship("CompetitionEvent", back_populates="competitors")
    dive_entries = relationship("CompetitionDiveEntry", back_populates="competitor", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(
            "status IN ('REGISTERED', 'COMPETING', 'DISQUALIFIED', 'WITHDREW')",
            name="check_competitor_status"
        ),
        Index("idx_competition_competitors_event", "event_id"),
    )

    def __repr__(self) -> str:
        return f"<CompetitionCompetitor(event_id={self.event_id}, name={self.competitor_name})>"


class CompetitionDiveEntry(Base):
    """Dive entry in a competitor's lineup"""

    __tablename__ = "competition_dive_entries"

    id = Column(Integer, primary_key=True, index=True)

    round_id = Column(Integer, ForeignKey("competition_rounds.id", ondelete="CASCADE"), nullable=False)
    competitor_id = Column(Integer, ForeignKey("competition_competitors.id", ondelete="CASCADE"), nullable=False)

    dive_order = Column(Integer, nullable=False)  # 1-6 or 1-5
    dive_code = Column(String(10), nullable=False)
    planned_dd = Column(Integer, nullable=False)  # Stored as hundredths (130 = 1.3)

    status = Column(String(20), default="PENDING", nullable=False)
    # Values: PENDING, COMPLETED, PASSED, DISQUALIFIED

    notes = Column(String(500), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    round = relationship("CompetitionRound", back_populates="dive_entries")
    competitor = relationship("CompetitionCompetitor", back_populates="dive_entries")

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'COMPLETED', 'PASSED', 'DISQUALIFIED')",
            name="check_dive_entry_status"
        ),
        Index("idx_competition_dive_entries_round", "round_id"),
        Index("idx_competition_dive_entries_competitor", "competitor_id"),
    )

    def __repr__(self) -> str:
        return f"<CompetitionDiveEntry(round_id={self.round_id}, competitor_id={self.competitor_id}, dive={self.dive_code})>"
