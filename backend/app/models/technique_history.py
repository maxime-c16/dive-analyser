"""Private technique history, deliberately independent of caption modifiers.

Annotations are private to the current diver owner.
"""
from datetime import datetime
from sqlalchemy import (Column, Integer, String, DateTime, ForeignKey, Boolean,
                        JSON, CheckConstraint, UniqueConstraint, Index)
from app.database import Base


class TechniqueTrack(Base):
    __tablename__ = 'technique_tracks'
    id = Column(Integer, primary_key=True)
    diver_id = Column(Integer, ForeignKey('divers.id'), nullable=False)
    name = Column(String(80), nullable=False)
    revision = Column(Integer, nullable=False, default=0)
    __table_args__ = (UniqueConstraint('diver_id', 'name'),)


class Technique(Base):
    __tablename__ = 'techniques'
    id = Column(Integer, primary_key=True)
    track_id = Column(Integer, ForeignKey('technique_tracks.id'), nullable=False)
    label = Column(String(120), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class TechniqueEpisode(Base):
    __tablename__ = 'technique_episodes'
    id = Column(Integer, primary_key=True)
    track_id = Column(Integer, ForeignKey('technique_tracks.id'), nullable=False)
    technique_id = Column(Integer, ForeignKey('techniques.id'), nullable=True)
    scope = Column(String(10), nullable=False)
    apparatus = Column(String(20), nullable=False)
    height = Column(String(5), nullable=False)
    position = Column(String(1), nullable=True)
    sync = Column(Boolean, nullable=True)
    start_at = Column(DateTime, nullable=False)
    start_id = Column(Integer, nullable=False)
    end_at = Column(DateTime, nullable=True)
    end_id = Column(Integer, nullable=True)
    uncertain_until = Column(DateTime, nullable=True)
    anchor_id = Column(Integer, ForeignKey('dives.id', ondelete='SET NULL'), nullable=True)
    precision = Column(String(20), nullable=False)
    timezone = Column(String(80), nullable=False)
    gap = Column(Boolean, nullable=False, default=False)
    source_episode_id = Column(Integer, ForeignKey('technique_episodes.id'), nullable=True)
    notes = Column(String(2000), nullable=False, default='')
    deleted = Column(Boolean, nullable=False, default=False)
    __table_args__ = (
        CheckConstraint('(gap AND technique_id IS NULL) OR (NOT gap AND technique_id IS NOT NULL)', name='ck_technique_episode_state'),
        CheckConstraint('(end_at IS NULL AND end_id IS NULL) OR (end_at IS NOT NULL AND end_id IS NOT NULL)', name='ck_technique_episode_end'),
        Index('ix_technique_episode_lookup', 'track_id', 'apparatus', 'height', 'scope', 'start_at', 'start_id'),
    )


class TechniqueAssignment(Base):
    __tablename__ = 'technique_assignments'
    id = Column(Integer, primary_key=True)
    track_id = Column(Integer, ForeignKey('technique_tracks.id'), nullable=False)
    dive_id = Column(Integer, ForeignKey('dives.id', ondelete='CASCADE'), nullable=False)
    # Original identity/context fences prevent attribution moving on reassignment.
    diver_id = Column(Integer, ForeignKey('divers.id'), nullable=False)
    code = Column(String(10), nullable=False)
    apparatus = Column(String(20), nullable=False)
    height = Column(String(5), nullable=False)
    position = Column(String(1), nullable=True)
    sync = Column(Boolean, nullable=False)
    state = Column(String(12), nullable=False)
    technique_id = Column(Integer, ForeignKey('techniques.id'), nullable=True)
    episode_id = Column(Integer, ForeignKey('technique_episodes.id'), nullable=True)
    __table_args__ = (
        UniqueConstraint('track_id', 'dive_id'),
        CheckConstraint("(state = 'technique' AND technique_id IS NOT NULL) OR (state IN ('mixed', 'unknown') AND technique_id IS NULL)", name='ck_technique_assignment_state'),
    )


class TechniqueRevision(Base):
    __tablename__ = 'technique_revisions'
    id = Column(Integer, primary_key=True)
    track_id = Column(Integer, ForeignKey('technique_tracks.id'), nullable=False)
    revision = Column(Integer, nullable=False)
    author_id = Column(Integer, ForeignKey('app_users.id'), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    operation = Column(String(30), nullable=False)
    before = Column(JSON, nullable=False)
    after = Column(JSON, nullable=False)
    __table_args__ = (UniqueConstraint('track_id', 'revision'),)


class TechniqueSessionState(Base):
    __tablename__ = 'technique_session_states'
    id = Column(Integer, primary_key=True)
    track_id = Column(Integer, ForeignKey('technique_tracks.id'), nullable=False)
    session_id = Column(Integer, ForeignKey('sessions.id', ondelete='CASCADE'), nullable=False)
    code = Column(String(10), nullable=False)
    apparatus = Column(String(20), nullable=False)
    height = Column(String(5), nullable=False)
    position = Column(String(1), nullable=False)
    sync = Column(Boolean, nullable=False)
    state = Column(String(12), nullable=False)
    __table_args__ = (
        UniqueConstraint('track_id', 'session_id', 'code', 'apparatus', 'height', 'position', 'sync'),
        CheckConstraint("state IN ('mixed', 'unknown')", name='ck_technique_session_state'),
    )
