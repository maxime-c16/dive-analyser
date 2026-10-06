"""Fediverse opt-in (Option 1: manual cross-post only).

Additive only: no existing table is altered. The dives table is untouched so
dive reads keep working on a database without this migration applied.
- UserFediversePrefs — one row per user, default OFF. Turning the global
  toggle ON never publishes anything by itself; per-dive opt-in is still
  required and only public dives are eligible.
- DiveFediverseOptin — one row per opted-in dive (row presence = opt-in).
  No row means OFF, so existing public dives stay unfederated until each is
  explicitly opted in. There is no backfill.
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer

from app.database import Base


class UserFediversePrefs(Base):
    __tablename__ = "user_fediverse_prefs"

    user_id = Column(Integer, ForeignKey("app_users.id", ondelete="CASCADE"), primary_key=True)
    enabled = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class DiveFediverseOptin(Base):
    __tablename__ = "dive_fediverse_optins"

    dive_id = Column(Integer, ForeignKey("dives.id", ondelete="CASCADE"), primary_key=True)
    enabled = Column(Boolean, nullable=False, default=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
