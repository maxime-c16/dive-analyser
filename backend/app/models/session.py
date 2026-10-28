"""Session model (training days)"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Date, Numeric, DateTime, Index, text
from sqlalchemy.orm import relationship

from app.database import Base


class Session(Base):
    """Training session (day)"""

    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, index=True)
    # SQL migration owns the FK (avoids a metadata cycle with filmed_session_id).
    calendar_occurrence_id = Column(Integer, unique=True)
    calendar_notify_cursor = Column(Integer, nullable=False, default=0, server_default="0")
    calendar_notified_at = Column(DateTime)
    location = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    weather = Column(String(50), nullable=True)

    # Aggregated stats
    total_dives = Column(Integer, default=0)
    total_personal_dives = Column(Integer, default=0)
    # Scores can reach 10.00; Numeric(3, 2) tops out at 9.99.
    avg_performance = Column(Numeric(4, 2), nullable=True)
    success_rate = Column(Numeric(5, 2), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    dives = relationship("Dive", back_populates="session", cascade="all, delete-orphan")

    # Indexes
    __table_args__ = (
        Index("uq_sessions_day_fallback", "date", unique=True, postgresql_where=text("calendar_occurrence_id IS NULL"), sqlite_where=text("calendar_occurrence_id IS NULL")),
        Index("idx_sessions_date", "date", postgresql_using="btree"),
    )

    def __repr__(self) -> str:
        return f"<Session(id={self.id}, date={self.date}, dives={self.total_dives})>"
