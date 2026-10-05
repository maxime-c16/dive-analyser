"""Fediverse opt-in (Option 1: manual cross-post only).

Additive only: no existing table is altered in a breaking way.
- UserFediversePrefs — one row per user, default OFF. Turning the global
  toggle ON never publishes anything by itself; per-dive opt-in is still
  required and only public dives are eligible.
- Dive.federate_enabled — per-dive override flag (see app/models/dive.py).
  Private dives can never be federated, even if the flag was set while
  public and the dive later becomes private.
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer

from app.database import Base


class UserFediversePrefs(Base):
    __tablename__ = "user_fediverse_prefs"

    user_id = Column(Integer, ForeignKey("app_users.id", ondelete="CASCADE"), primary_key=True)
    enabled = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
