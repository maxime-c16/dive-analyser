"""Dive modifier model."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Index
from sqlalchemy.orm import relationship

from app.database import Base


class DiveModifier(Base):
    """Caption-derived drill/modifier tags for a dive."""

    __tablename__ = "dive_modifiers"

    id = Column(Integer, primary_key=True, index=True)
    dive_id = Column(Integer, ForeignKey("dives.id", ondelete="CASCADE"), nullable=False)
    modifier_code = Column(String(20), nullable=False)
    modifier_type = Column(String(30), nullable=False, default="drill")
    source = Column(String(30), nullable=False, default="caption")
    raw_caption = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    dive = relationship("Dive", back_populates="modifiers")

    __table_args__ = (
        UniqueConstraint("dive_id", "modifier_code", name="uq_dive_modifier"),
        Index("ix_dive_modifiers_code", "modifier_code"),
        Index("ix_dive_modifiers_type", "modifier_type"),
    )
