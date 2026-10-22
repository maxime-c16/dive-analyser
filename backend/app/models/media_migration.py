"""Historical web-package migration ledger (see docs/design/media-global-migration.md).

``MediaMigrationRun`` is the durable control row (status, pause reason,
budget, queue depth, last tick); ``MediaMigrationItem`` is one clip
(``dives.video_uuid``). Items reference normal ``media_jobs`` rows: the
producer, publisher, fencing and read contract are the existing ones.
Schema: ``backend/migrations/add_media_migration_runs.sql`` (manual apply).
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    text,
)

from app.database import Base


class MediaMigrationRun(Base):
    __tablename__ = "media_migration_runs"

    id = Column(Integer, primary_key=True)
    kind = Column(String(40), nullable=False, default="web_package_backfill")
    status = Column(String(20), nullable=False, default="active")
    pause_reason = Column(Text, nullable=True)
    transform_version = Column(String(40), nullable=False)
    priority = Column(Integer, nullable=False, default=70)
    max_attempts = Column(Integer, nullable=False, default=2)
    queue_depth = Column(Integer, nullable=False, default=2)
    budget_bytes = Column(BigInteger, nullable=False)
    admission_cap = Column(Integer, nullable=True)
    admitted_jobs = Column(Integer, nullable=False, default=0)
    sweep_cursor = Column(Integer, nullable=False, default=0)
    last_tick_at = Column(DateTime, nullable=True)
    last_tick = Column(JSON, nullable=True)
    created_by = Column(String(80), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("status IN ('active', 'paused', 'cancelled')", name="ck_media_migration_run_status"),
        CheckConstraint("priority >= 60", name="ck_media_migration_run_priority"),
        CheckConstraint("max_attempts BETWEEN 1 AND 2", name="ck_media_migration_run_attempts"),
        CheckConstraint("queue_depth BETWEEN 1 AND 5", name="ck_media_migration_run_depth"),
        CheckConstraint("budget_bytes > 0", name="ck_media_migration_run_budget"),
        Index(
            "uq_media_migration_one_open_run",
            text("(1)"),
            unique=True,
            postgresql_where=text("status IN ('active', 'paused')"),
            sqlite_where=text("status IN ('active', 'paused')"),
        ),
    )


class MediaMigrationItem(Base):
    __tablename__ = "media_migration_items"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("media_migration_runs.id", ondelete="CASCADE"), nullable=False)
    video_uuid = Column(String(100), nullable=False)
    photos_asset_id = Column(Integer, ForeignKey("photos_assets.id", ondelete="SET NULL"), nullable=True)
    # Admission order: most recent dives first.
    sort_key = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    reason = Column(String(80), nullable=True)
    source_sha256 = Column(String(64), nullable=True)
    source_revision_id = Column(Integer, nullable=True)
    media_job_id = Column(Integer, ForeignKey("media_jobs.id", ondelete="SET NULL"), nullable=True)
    # True when this run created the job (priority/attempts are ours); an
    # adopted job (new-ingest/interactive/canary) keeps its own settings.
    job_owned = Column(Boolean, nullable=False, default=False)
    estimated_bytes = Column(BigInteger, nullable=True)
    published_bytes = Column(BigInteger, nullable=True)
    published_objects = Column(Integer, nullable=True)
    # Budget charge settled by FINISHED jobs of this item (cumulative across
    # source changes/cancellations); in-flight jobs are reserved separately.
    settled_bytes = Column(BigInteger, nullable=False, default=0)
    hq_aliased_to = Column(String(10), nullable=True)
    source_changes = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    admitted_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'queued', 'complete', 'skipped_complete', 'blocked', 'failed')",
            name="ck_media_migration_item_status",
        ),
        Index("uq_media_migration_item_run_uuid", "run_id", "video_uuid", unique=True),
        Index("ix_media_migration_items_run_status", "run_id", "status"),
        Index("ix_media_migration_items_job", "media_job_id"),
    )
