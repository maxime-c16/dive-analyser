"""Effective synchronized participants, independent of Photos import fields."""
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, JSON, func
from app.database import Base


class DiveSyncPair(Base):
    __tablename__ = 'dive_sync_pairs'
    dive_id = Column(Integer, ForeignKey('dives.id', ondelete='CASCADE'), primary_key=True)
    first_diver_id = Column(Integer, ForeignKey('divers.id'), nullable=True)
    second_diver_id = Column(Integer, ForeignKey('divers.id'), nullable=True)
    source = Column(String(20), nullable=False)  # caption or reviewed
    complete = Column(Boolean, nullable=False, default=False)
    conflict = Column(Boolean, nullable=False, default=False)
    caption_sha256 = Column(String(64), nullable=False)
    latest_caption_sha256 = Column(String(64), nullable=False)
    evidence = Column(JSON, nullable=False, default=dict)
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
