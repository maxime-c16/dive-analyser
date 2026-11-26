"""Session clip auto-detection runs, fast triage candidates, and GT matches.

Tables come from backend/migrations/add_session_clip_triage.sql only.
"""
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)

from app.database import Base

_MIGRATION_ONLY = {"sql_migration_only": True}


class SessionClipRun(Base):
    __tablename__ = "session_clip_runs"
    __table_args__ = (
        Index("ix_session_clip_runs_video", "session_video_id", "created_at", "id"),
        {"info": _MIGRATION_ONLY},
    )

    id = Column(Integer, primary_key=True)
    session_video_id = Column(
        Integer, ForeignKey("session_videos.id", ondelete="CASCADE"), nullable=False
    )
    detector_name = Column(String(80), nullable=False)
    detector_version = Column(String(80), nullable=False)
    params_json = Column(JSON, nullable=True)
    submitted_by_user_id = Column(
        Integer, ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True
    )
    submitted_count = Column(Integer, nullable=False, default=0)
    created_count = Column(Integer, nullable=False, default=0)
    deduped_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class SessionClipCandidate(Base):
    __tablename__ = "session_clip_candidates"
    __table_args__ = (
        CheckConstraint("start_s >= 0 AND end_s > start_s", name="ck_session_clip_bounds"),
        CheckConstraint(
            "(trimmed_start_s IS NULL AND trimmed_end_s IS NULL) "
            "OR (trimmed_start_s IS NOT NULL AND trimmed_end_s IS NOT NULL "
            "AND trimmed_start_s >= 0 AND trimmed_end_s > trimmed_start_s)",
            name="ck_session_clip_trimmed_bounds",
        ),
        CheckConstraint(
            "triage_status IN ('pending', 'kept', 'rejected')",
            name="ck_session_clip_triage_status",
        ),
        CheckConstraint(
            "extraction_status IN ('none', 'queued', 'claimed', 'extracting', 'ready', 'published', 'failed')",
            name="ck_session_clip_extraction_status",
        ),
        CheckConstraint(
            "visibility IN ('private', 'public')",
            name="ck_session_clip_visibility",
        ),
        Index("ix_session_clip_candidates_queue", "triage_status", "skipped_at", "id"),
        Index("ix_session_clip_candidates_video", "session_video_id", "triage_status", "start_s"),
        Index("ix_session_clip_candidates_bounds", "session_video_id", "start_s", "end_s"),
        Index("ix_session_clip_candidates_trimmed", "session_video_id", "trimmed_start_s", "trimmed_end_s"),
        Index("ix_session_clip_candidates_extract", "extraction_status", "claimed_until", "id"),
        {"info": _MIGRATION_ONLY},
    )

    id = Column(Integer, primary_key=True)
    session_video_id = Column(
        Integer, ForeignKey("session_videos.id", ondelete="CASCADE"), nullable=False
    )
    first_run_id = Column(
        Integer, ForeignKey("session_clip_runs.id", ondelete="SET NULL"), nullable=True
    )
    latest_run_id = Column(
        Integer, ForeignKey("session_clip_runs.id", ondelete="SET NULL"), nullable=True
    )
    start_s = Column(Float, nullable=False)
    end_s = Column(Float, nullable=False)
    trimmed_start_s = Column(Float, nullable=True)
    trimmed_end_s = Column(Float, nullable=True)
    confidence = Column(Float, nullable=True)
    detector_label = Column(String(80), nullable=True)
    detector_meta = Column(JSON, nullable=True)

    triage_status = Column(String(16), nullable=False, default="pending")
    reject_reason = Column(String(32), nullable=True)
    triaged_by_user_id = Column(
        Integer, ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True
    )
    triaged_at = Column(DateTime, nullable=True)
    skipped_at = Column(DateTime, nullable=True)

    diver_id = Column(Integer, ForeignKey("divers.id", ondelete="SET NULL"), nullable=True)
    dive_code = Column(String(10), nullable=True)
    height = Column(String(5), nullable=True)
    performance = Column(String(1), nullable=True)
    phase1_performance = Column(String(1), nullable=True)
    phase2_performance = Column(String(1), nullable=True)
    notes = Column(Text, nullable=True)
    visibility = Column(String(10), nullable=False, default="private")

    extraction_status = Column(String(20), nullable=False, default="none")
    cut_revision = Column(Integer, nullable=False, default=1)
    lease_token = Column(String(36), nullable=True)
    claimed_by = Column(String(100), nullable=True)
    claimed_at = Column(DateTime, nullable=True)
    claimed_until = Column(DateTime, nullable=True)
    extraction_attempts = Column(Integer, nullable=False, default=0)
    extraction_error = Column(String(240), nullable=True)
    clip_video_uuid = Column(String(100), unique=True, nullable=True)
    photos_asset_id = Column(
        Integer, ForeignKey("photos_assets.id", ondelete="SET NULL"), nullable=True
    )
    dive_id = Column(Integer, ForeignKey("dives.id", ondelete="SET NULL"), nullable=True)
    publish_requested_at = Column(DateTime, nullable=True)
    publish_requested_by_user_id = Column(
        Integer, ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True
    )
    published_at = Column(DateTime, nullable=True)
    source_etag = Column(String(80), nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def effective_start_s(self) -> float:
        return self.trimmed_start_s if self.trimmed_start_s is not None else self.start_s

    @property
    def effective_end_s(self) -> float:
        return self.trimmed_end_s if self.trimmed_end_s is not None else self.end_s


class SessionClipRunMatch(Base):
    __tablename__ = "session_clip_run_matches"
    __table_args__ = (
        UniqueConstraint("run_id", "candidate_id", name="uq_session_clip_run_match"),
        Index("ix_session_clip_run_matches_run", "run_id"),
        Index("ix_session_clip_run_matches_candidate", "candidate_id"),
        {"info": _MIGRATION_ONLY},
    )

    id = Column(Integer, primary_key=True)
    run_id = Column(
        Integer, ForeignKey("session_clip_runs.id", ondelete="CASCADE"), nullable=False
    )
    candidate_id = Column(
        Integer, ForeignKey("session_clip_candidates.id", ondelete="CASCADE"), nullable=False
    )
    raw_start_s = Column(Float, nullable=False)
    raw_end_s = Column(Float, nullable=False)
    confidence = Column(Float, nullable=True)
    was_new = Column(Boolean, nullable=False, default=False)
    overlap_iou = Column(Float, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class SessionClipOrphanObject(Base):
    """Durable ledger of B2 clip-cut objects staged before DB commit, for grace-period reclamation."""

    __tablename__ = "session_clip_orphan_objects"
    __table_args__ = (
        UniqueConstraint("bucket", "object_key", name="uq_session_clip_orphan_key"),
        CheckConstraint(
            "status IN ('pending', 'deleting', 'reclaimed', 'retained')",
            name="ck_session_clip_orphan_status",
        ),
        Index("ix_session_clip_orphan_due", "status", "eligible_after", "id"),
        {"info": _MIGRATION_ONLY},
    )

    id = Column(Integer, primary_key=True)
    bucket = Column(String(120), nullable=False)
    object_key = Column(String(200), nullable=False)
    blob_sha256 = Column(String(64), nullable=False)
    byte_size = Column(BigInteger, nullable=False, default=0)
    candidate_id = Column(
        Integer, ForeignKey("session_clip_candidates.id", ondelete="SET NULL"), nullable=True
    )
    status = Column(String(20), nullable=False, default="pending")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    eligible_after = Column(DateTime, nullable=False)
    reclaimed_at = Column(DateTime, nullable=True)
    last_error = Column(String(240), nullable=True)
