"""Automatic community reviews, independent of owner-requested evaluations."""
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, CheckConstraint
from app.database import Base


class ReviewExclusion(Base):
    __tablename__ = 'review_exclusions'
    dive_id = Column(Integer, ForeignKey('dives.id', ondelete='CASCADE'), primary_key=True)
    excluded = Column(Boolean, nullable=False, default=True)


class ReviewStack(Base):
    __tablename__ = 'review_stacks'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('app_users.id', ondelete='CASCADE'), nullable=False, index=True)
    key = Column(String(80), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint('user_id', 'key', name='uq_review_stack_key'),)


class ReviewStackItem(Base):
    __tablename__ = 'review_stack_items'
    id = Column(Integer, primary_key=True)
    stack_id = Column(Integer, ForeignKey('review_stacks.id', ondelete='CASCADE'), nullable=False, index=True)
    dive_id = Column(Integer, ForeignKey('dives.id', ondelete='CASCADE'), nullable=False, index=True)
    position = Column(Integer, nullable=False)
    skipped_at = Column(DateTime, nullable=True)
    __table_args__ = (UniqueConstraint('stack_id', 'dive_id', name='uq_review_stack_dive'),)


class AutomaticRating(Base):
    __tablename__ = 'automatic_ratings'
    id = Column(Integer, primary_key=True)
    dive_id = Column(Integer, ForeignKey('dives.id', ondelete='CASCADE'), nullable=False, index=True)
    evaluator_user_id = Column(Integer, ForeignKey('app_users.id'), nullable=False, index=True)
    score_half_steps = Column(Integer, nullable=False)
    comment = Column(String(2000), nullable=True)
    dive_code = Column(String(10), nullable=False)
    height = Column(String(5), nullable=False)
    platform_type = Column(String(20), nullable=True)
    dive_name = Column(String(100), nullable=False)
    video_uuid = Column(String(100), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint('dive_id', 'evaluator_user_id', name='uq_automatic_rating_once'),
        CheckConstraint('score_half_steps BETWEEN 0 AND 20', name='ck_automatic_rating_score'),
        CheckConstraint('comment IS NULL OR length(comment) BETWEEN 1 AND 2000', name='ck_automatic_rating_comment'),
    )
