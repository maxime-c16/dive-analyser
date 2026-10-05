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
    user_id = Column(Integer, ForeignKey('app_users.id', ondelete='CASCADE'), nullable=False)
    body = Column(String(2000), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (CheckConstraint('length(body) BETWEEN 1 AND 2000', name='ck_dive_comment_length'),)
