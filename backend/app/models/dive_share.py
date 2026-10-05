"""Opaque video capabilities and guest identities, separate from accounts."""
from datetime import datetime
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from app.database import Base


class DiveShare(Base):
    __tablename__ = 'dive_shares'
    id = Column(Integer, primary_key=True)
    dive_id = Column(Integer, ForeignKey('dives.id', ondelete='CASCADE'), nullable=False, index=True)
    created_by = Column(Integer, ForeignKey('app_users.id', ondelete='CASCADE'), nullable=False)
    video_uuid = Column(String(255), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    revoked_at = Column(DateTime)


class DiveGuest(Base):
    __tablename__ = 'dive_guests'
    id = Column(Integer, primary_key=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    display_name = Column(String(120), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class DiveGuestLike(Base):
    __tablename__ = 'dive_guest_likes'
    dive_id = Column(Integer, ForeignKey('dives.id', ondelete='CASCADE'), primary_key=True)
    guest_id = Column(Integer, ForeignKey('dive_guests.id', ondelete='CASCADE'), primary_key=True)


class DiveGuestAccess(Base):
    __tablename__ = 'dive_guest_access'
    share_id = Column(Integer, ForeignKey('dive_shares.id', ondelete='CASCADE'), primary_key=True)
    guest_id = Column(Integer, ForeignKey('dive_guests.id', ondelete='CASCADE'), primary_key=True)
