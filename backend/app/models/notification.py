"""Backend notification inbox models (PR1).

Maps exactly the tables created by backend/migrations/add_notifications.sql.
The push_subscriptions table is schema-only in PR1; its API arrives in PR3.
"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)

from app.database import Base


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type = Column(String(64), nullable=False)
    title = Column(String(200), nullable=False)
    body = Column(String(600), nullable=True)
    dive_id = Column(
        Integer, ForeignKey("dives.id", ondelete="CASCADE"), nullable=True, index=True
    )
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True)
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_notifications_user_created", "user_id", "created_at"),
    )


class PushSubscription(Base):
    """WebPush endpoint storage. Schema fixed in PR1; API in PR3."""

    __tablename__ = "push_subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    endpoint = Column(Text, nullable=False, unique=True)
    p256dh = Column(Text, nullable=False)
    auth = Column(Text, nullable=False)
    device_label = Column(String(100), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_push_subscriptions_user", "user_id"),
    )


class NotificationPref(Base):
    __tablename__ = "notification_prefs"

    user_id = Column(
        Integer, ForeignKey("app_users.id", ondelete="CASCADE"), primary_key=True
    )
    notif_type = Column(String(64), primary_key=True)
    enabled = Column(Boolean, nullable=False, default=True)
