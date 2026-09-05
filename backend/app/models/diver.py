"""Normalized diver identities and explicit aliases."""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


class Diver(Base):
    __tablename__ = "divers"

    id = Column(Integer, primary_key=True, index=True)
    display_name = Column(String(100), nullable=False)
    canonical_name = Column(String(100), nullable=False, unique=True, index=True)
    is_primary_user = Column(Boolean, nullable=False, default=False, index=True)
    active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    aliases = relationship("DiverAlias", back_populates="diver", cascade="all, delete-orphan")
    dives = relationship("Dive", back_populates="diver")


class DiverAlias(Base):
    __tablename__ = "diver_aliases"

    id = Column(Integer, primary_key=True, index=True)
    diver_id = Column(Integer, ForeignKey("divers.id", ondelete="CASCADE"), nullable=False, index=True)
    alias = Column(String(100), nullable=False)
    canonical_alias = Column(String(100), nullable=False, unique=True, index=True)
    source = Column(String(30), nullable=False, default="manual")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    diver = relationship("Diver", back_populates="aliases")

    __table_args__ = (Index("ix_diver_aliases_diver_canonical", "diver_id", "canonical_alias"),)
