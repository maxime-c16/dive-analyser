"""Named date ranges used to contextualize training attempts."""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, Integer, String, Text, Index

from app.database import Base


class TrainingPeriod(Base):
    __tablename__ = "training_periods"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    period_type = Column(String(40), nullable=False, default="custom", index=True)
    start_date = Column(Date, nullable=False, index=True)
    end_date = Column(Date, nullable=False, index=True)
    description = Column(Text, nullable=True)
    active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="check_training_period_dates"),
        Index("ix_training_periods_range", "start_date", "end_date"),
    )
