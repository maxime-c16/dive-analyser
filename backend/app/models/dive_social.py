"""Member reactions and discussion, scoped through the dive foreign key."""
from datetime import datetime
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, CheckConstraint
from app.database import Base


class DiveLike(Base):
    __tablename__ = 'dive_likes'
    dive_id = Column(Integer, ForeignKey('dives.id', ondelete='CASCADE'), primary_key=True)
    user_id = Column(Integer, ForeignKey('app_users.id', ondelete='CASCADE'), primary_key=True)


class DiveComment(Base):
    __tablename__ = 'dive_comments'
    id = Column(Integer, primary_key=True)
    dive_id = Column(Integer, ForeignKey('dives.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('app_users.id', ondelete='CASCADE'))
    guest_id = Column(Integer, ForeignKey('dive_guests.id', ondelete='CASCADE'))
    parent_id = Column(Integer, ForeignKey('dive_comments.id', ondelete='CASCADE'), nullable=True, index=True)
    body = Column(String(2000), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (CheckConstraint('(user_id IS NULL) <> (guest_id IS NULL)', name='ck_dive_comment_author'), CheckConstraint('length(body) BETWEEN 1 AND 2000', name='ck_dive_comment_length'),)


class DiveCommentLike(Base):
    __tablename__ = 'dive_comment_likes'
    comment_id = Column(Integer, ForeignKey('dive_comments.id', ondelete='CASCADE'), primary_key=True)
    user_id = Column(Integer, ForeignKey('app_users.id', ondelete='CASCADE'), primary_key=True)


class DiveGuestCommentLike(Base):
    __tablename__ = 'dive_guest_comment_likes'
    comment_id = Column(Integer, ForeignKey('dive_comments.id', ondelete='CASCADE'), primary_key=True)
    guest_id = Column(Integer, ForeignKey('dive_guests.id', ondelete='CASCADE'), primary_key=True)
