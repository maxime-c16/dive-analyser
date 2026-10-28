"""Whole training-session videos stored as-is in the sessions B2 bucket.

One B2 object -> one row (unique bucket/key), attached to the `sessions` day.
Tables come from backend/migrations/add_session_videos.sql only.
"""
from datetime import datetime

from sqlalchemy import (
    BigInteger, Column, Date, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint,
)

from app.database import Base

_MIGRATION_ONLY = {"sql_migration_only": True}


class SessionVideo(Base):
    __tablename__ = "session_videos"
    __table_args__ = (
        UniqueConstraint("bucket", "object_key", name="uq_session_videos_object"),
        Index("ix_session_videos_recorded", "recorded_at"),
        {"info": _MIGRATION_ONLY},
    )

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=True, index=True)
    owner_user_id = Column(Integer, ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False)
    bucket = Column(String(63), nullable=False)
    object_key = Column(String(1024), nullable=False)
    size_bytes = Column(BigInteger, nullable=True)
    etag = Column(String(80), nullable=True)
    # pending -> probing -> ready | failed (retried while attempts < limit)
    status = Column(String(16), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    claimed_at = Column(DateTime, nullable=True)
    last_error = Column(String(200), nullable=True)
    recorded_at = Column(DateTime, nullable=True)  # UTC
    recorded_date = Column(Date, nullable=True)  # Europe/Paris day
    duration_seconds = Column(Float, nullable=True)
    video_codec = Column(String(32), nullable=True)
    video_profile = Column(String(32), nullable=True)
    codec_string = Column(String(64), nullable=True)  # RFC 6381, e.g. hvc1.2.4.L123.B0
    audio_codec_string = Column(String(32), nullable=True)
    pix_fmt = Column(String(32), nullable=True)
    color_transfer = Column(String(32), nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    fps = Column(Float, nullable=True)
    bit_rate = Column(BigInteger, nullable=True)
    notified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class SessionVideoShare(Base):
    __tablename__ = "session_video_shares"
    __table_args__ = ({"info": _MIGRATION_ONLY},)

    id = Column(Integer, primary_key=True)
    session_video_id = Column(Integer, ForeignKey("session_videos.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by = Column(Integer, ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    revoked_at = Column(DateTime, nullable=True)


class SessionVideoGuestAccess(Base):
    """Guest identities are the dive-sharing ones (dive_guests)."""
    __tablename__ = "session_video_guest_access"
    __table_args__ = ({"info": _MIGRATION_ONLY},)

    share_id = Column(Integer, ForeignKey("session_video_shares.id", ondelete="CASCADE"), primary_key=True)
    guest_id = Column(Integer, ForeignKey("dive_guests.id", ondelete="CASCADE"), primary_key=True)


class SessionVideoPlaybackIssue(Base):
    """Device could not show the original (no UI; counted for the product)."""
    __tablename__ = "session_video_playback_issues"
    __table_args__ = (
        Index("ix_session_video_issues_video_created", "session_video_id", "created_at"),
        {"info": _MIGRATION_ONLY},
    )

    id = Column(Integer, primary_key=True)
    session_video_id = Column(Integer, ForeignKey("session_videos.id", ondelete="CASCADE"), nullable=False)
    reason = Column(String(16), nullable=False)
    viewer_user_id = Column(Integer, ForeignKey("app_users.id", ondelete="CASCADE"), nullable=True)
    viewer_guest_id = Column(Integer, ForeignKey("dive_guests.id", ondelete="CASCADE"), nullable=True)
    user_agent = Column(String(200), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
