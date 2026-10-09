"""Member achievements: one row per (user, achievement key).

The catalogue (keys, categories, unlock rules) lives in
app/services/achievements.py; this table only records who unlocked what and
when. Maps backend/migrations/add_user_achievements.sql.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String

from app.database import Base


class UserAchievement(Base):
    __tablename__ = "user_achievements"

    user_id = Column(
        Integer, ForeignKey("app_users.id", ondelete="CASCADE"), primary_key=True
    )
    key = Column(String(64), primary_key=True)
    unlocked_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    # NULL until the member has seen the unlock toast / opened the list.
    seen_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_user_achievements_user_unlocked", "user_id", "unlocked_at"),
    )
