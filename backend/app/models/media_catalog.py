"""Durable captioned Photos catalog and rolling population state."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class CaptionedMediaCatalog(Base):
    __tablename__ = "captioned_media_catalog"

    id = Column(Integer, primary_key=True, index=True)
    canonical_video_uuid = Column(String(100), nullable=True, index=True)
    agent_id = Column(String(100), ForeignKey("media_agents.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_local_uuid = Column(String(100), nullable=False, index=True)
    cloud_fingerprint = Column(String(100), nullable=True, index=True)
    photos_asset_id = Column(Integer, ForeignKey("photos_assets.id", ondelete="SET NULL"), nullable=True, index=True)
    dive_id = Column(Integer, ForeignKey("dives.id", ondelete="SET NULL"), nullable=True, index=True)
    raw_caption = Column(Text, nullable=False)
    canonical_dive_code = Column(String(10), nullable=True, index=True)
    captured_at = Column(DateTime, nullable=True, index=True)
    duration_seconds = Column(Numeric, nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    estimated_source_bytes = Column(BigInteger, nullable=True)
    photos_local_state = Column(String(40), nullable=False, default="unknown", index=True)
    media_state = Column(String(40), nullable=False, default="missing", index=True)
    poster_state = Column(String(40), nullable=False, default="missing", index=True)
    proxy_state = Column(String(40), nullable=False, default="missing", index=True)
    source_state = Column(String(40), nullable=False, default="missing", index=True)
    representative_role = Column(String(20), nullable=True, index=True)
    eligibility = Column(String(30), nullable=False, default="excluded", index=True)
    exclusion_code = Column(String(60), nullable=True, index=True)
    last_cataloged_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    last_media_attempt_at = Column(DateTime, nullable=True)
    last_media_success_at = Column(DateTime, nullable=True)
    last_error_code = Column(String(100), nullable=True, index=True)
    catalog_revision = Column(Integer, nullable=False, default=1, index=True)
    metadata_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_captioned_catalog_agent_local_unique", "agent_id", "agent_local_uuid", unique=True),
        Index("ix_captioned_catalog_revision_eligibility", "catalog_revision", "eligibility"),
    )


class MediaCatalogRun(Base):
    __tablename__ = "media_catalog_runs"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String(100), ForeignKey("media_agents.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(30), nullable=False, default="requested", index=True)
    catalog_revision = Column(Integer, nullable=False, index=True)
    checkpoint = Column(Integer, nullable=False, default=0)
    observed_count = Column(Integer, nullable=False, default=0)
    eligible_count = Column(Integer, nullable=False, default=0)
    excluded_count = Column(Integer, nullable=False, default=0)
    error_count = Column(Integer, nullable=False, default=0)
    photos_library_bytes_start = Column(BigInteger, nullable=True)
    photos_library_bytes_end = Column(BigInteger, nullable=True)
    free_bytes_start = Column(BigInteger, nullable=True)
    free_bytes_end = Column(BigInteger, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    paused_at = Column(DateTime, nullable=True)
    pause_reason = Column(String(100), nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class MediaCatalogPopulationRun(Base):
    __tablename__ = "media_catalog_population_runs"

    id = Column(Integer, primary_key=True, index=True)
    catalog_revision = Column(Integer, nullable=False, index=True)
    status = Column(String(30), nullable=False, default="planned", index=True)
    scope = Column(String(60), nullable=False, default="all_eligible_captioned")
    stage = Column(Integer, nullable=False, default=1)
    total_items = Column(Integer, nullable=False, default=0)
    completed_items = Column(Integer, nullable=False, default=0)
    ready_items = Column(Integer, nullable=False, default=0)
    partial_items = Column(Integer, nullable=False, default=0)
    unavailable_items = Column(Integer, nullable=False, default=0)
    skipped_items = Column(Integer, nullable=False, default=0)
    current_item_id = Column(Integer, nullable=True)
    plan_snapshot = Column(JSON, nullable=False, default=dict)
    started_at = Column(DateTime, nullable=True)
    paused_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    pause_reason = Column(String(100), nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    items = relationship("MediaCatalogPopulationItem", back_populates="run", cascade="all, delete-orphan")


class MediaCatalogPopulationItem(Base):
    __tablename__ = "media_catalog_population_items"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("media_catalog_population_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    catalog_item_id = Column(Integer, ForeignKey("captioned_media_catalog.id", ondelete="CASCADE"), nullable=False, index=True)
    priority = Column(Integer, nullable=False, index=True)
    priority_class = Column(String(10), nullable=False, index=True)
    status = Column(String(40), nullable=False, default="planned", index=True)
    poster_status = Column(String(30), nullable=False, default="missing")
    proxy_status = Column(String(30), nullable=False, default="missing")
    source_status = Column(String(30), nullable=False, default="missing")
    attempt_count = Column(Integer, nullable=False, default=0)
    poster_job_id = Column(Integer, ForeignKey("media_jobs.id"), nullable=True)
    proxy_job_id = Column(Integer, ForeignKey("media_jobs.id"), nullable=True)
    last_error_code = Column(String(100), nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    run = relationship("MediaCatalogPopulationRun", back_populates="items")

    __table_args__ = (
        Index("ix_catalog_population_run_item_unique", "run_id", "catalog_item_id", unique=True),
        Index("ix_catalog_population_run_priority", "run_id", "priority", "id"),
    )


class MediaResolutionUpgradeRun(Base):
    """A sequential, resumable cache-rendition upgrade run."""

    __tablename__ = "media_resolution_upgrade_runs"

    id = Column(Integer, primary_key=True, index=True)
    target_rendition = Column(String(40), nullable=False, default="proxy_720p")
    scope = Column(String(20), nullable=False, default="self")
    status = Column(String(30), nullable=False, default="scheduled", index=True)
    starts_after_population_run_id = Column(Integer, ForeignKey("media_catalog_population_runs.id"), nullable=True)
    total_items = Column(Integer, nullable=False, default=0)
    completed_items = Column(Integer, nullable=False, default=0)
    upgraded_items = Column(Integer, nullable=False, default=0)
    failed_items = Column(Integer, nullable=False, default=0)
    skipped_pinned_items = Column(Integer, nullable=False, default=0)
    current_item_id = Column(Integer, nullable=True)
    plan_snapshot = Column(JSON, nullable=False, default=dict)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    paused_at = Column(DateTime, nullable=True)
    pause_reason = Column(String(100), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    items = relationship("MediaResolutionUpgradeItem", back_populates="run", cascade="all, delete-orphan")


class MediaResolutionUpgradeItem(Base):
    __tablename__ = "media_resolution_upgrade_items"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("media_resolution_upgrade_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    catalog_item_id = Column(Integer, ForeignKey("captioned_media_catalog.id", ondelete="CASCADE"), nullable=False, index=True)
    # Items without a 360p proxy are upgraded directly from their validated source.
    old_cache_entry_id = Column(Integer, ForeignKey("media_cache_entries.id"), nullable=True, index=True)
    upgrade_job_id = Column(Integer, ForeignKey("media_jobs.id"), nullable=True, index=True)
    status = Column(String(40), nullable=False, default="planned", index=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    run = relationship("MediaResolutionUpgradeRun", back_populates="items")

    __table_args__ = (
        Index("ix_resolution_upgrade_item_unique", "run_id", "catalog_item_id", unique=True),
        Index("ix_resolution_upgrade_item_status", "run_id", "status", "id"),
    )
