"""Media cache and request job models."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.database import Base


class MediaCacheEntry(Base):
    """A verified media artifact that Debian can serve."""

    __tablename__ = "media_cache_entries"

    id = Column(Integer, primary_key=True, index=True)
    photos_asset_id = Column(Integer, ForeignKey("photos_assets.id", ondelete="CASCADE"), nullable=False, index=True)
    media_key = Column(String(64), unique=True, nullable=False, index=True)
    rendition = Column(String(40), nullable=False, index=True)

    storage_backend = Column(String(30), nullable=False, default="local_fs")
    storage_path = Column(Text, nullable=False)
    content_type = Column(String(100), nullable=True)
    size_bytes = Column(BigInteger, nullable=False)
    checksum_sha256 = Column(String(64), nullable=True)

    thumbhash = Column(String(128), nullable=True)
    thumb_storage_path = Column(Text, nullable=True)
    thumb_checksum_sha256 = Column(String(64), nullable=True)
    thumb_size_bytes = Column(BigInteger, nullable=True)

    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    duration_seconds = Column(Numeric, nullable=True)
    status = Column(String(30), nullable=False, default="ready", index=True)

    pinned = Column(Boolean, nullable=False, default=False)
    last_accessed_at = Column(DateTime, nullable=True, index=True)
    expires_at = Column(DateTime, nullable=True, index=True)
    # D1 durable derivatives (additive, nullable): the source revision and
    # transform version a future `hq`/`light`/`poster` cache row was derived
    # from. Legacy rows keep NULL (= pre-derivative stock, served under the
    # #134 sole-copy rules until a durable derivative replaces them). D1
    # writes nothing here; no read path consults these columns yet.
    source_blob_sha256 = Column(String(64), nullable=True, index=True)
    transform_version = Column(String(40), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    asset = relationship("PhotosAsset")


class MediaJob(Base):
    """A Mac-fulfillable request for one asset rendition."""

    __tablename__ = "media_jobs"

    id = Column(Integer, primary_key=True, index=True)
    photos_asset_id = Column(Integer, ForeignKey("photos_assets.id", ondelete="CASCADE"), nullable=False, index=True)
    media_key = Column(String(64), nullable=False, index=True)
    rendition = Column(String(40), nullable=False, index=True)

    status = Column(String(40), nullable=False, default="queued", index=True)
    priority = Column(Integer, nullable=False, default=100)
    request_reason = Column(String(40), nullable=True)

    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=5)
    claimed_by = Column(String(100), nullable=True)
    claimed_at = Column(DateTime, nullable=True)
    claimed_until = Column(DateTime, nullable=True, index=True)

    progress = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    upload_tmp_path = Column(Text, nullable=True)
    output_checksum_sha256 = Column(String(64), nullable=True)
    output_size_bytes = Column(BigInteger, nullable=True)
    # D1 reservations for D2 fencing / D3 package finalization (additive,
    # nullable): `lease_token` is the D2 claim token verified on
    # heartbeat/upload/finalize alongside `claimed_by` (stale attempts
    # rejected after re-lease); `finalized_slots` accumulates the D3
    # per-slot (`hq`/`light`/`poster`) finalize record. D1 writes nothing
    # here; old code ignores both columns.
    lease_token = Column(String(36), nullable=True)
    finalized_slots = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    asset = relationship("PhotosAsset")

    __table_args__ = (
        Index("ix_media_jobs_active_key_status", "media_key", "status"),
        Index("ix_media_jobs_asset_rendition", "photos_asset_id", "rendition"),
    )


class MediaPopulationRun(Base):
    """Auditable bounded media population run."""

    __tablename__ = "media_population_runs"

    id = Column(Integer, primary_key=True, index=True)
    population_type = Column(String(60), nullable=False, default="representative_manifest", index=True)
    tier = Column(Integer, nullable=False, default=1, index=True)
    status = Column(String(30), nullable=False, default="planned", index=True)
    requested_renditions = Column(JSON, nullable=False)
    manifest_snapshot = Column(JSON, nullable=False)

    total_items = Column(Integer, nullable=False, default=0)
    total_jobs = Column(Integer, nullable=False, default=0)
    ready_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)
    unavailable_count = Column(Integer, nullable=False, default=0)
    skipped_count = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)

    items = relationship("MediaPopulationRunItem", back_populates="run", cascade="all, delete-orphan")


class MediaPopulationRunItem(Base):
    """One planned rendition for one representative attempt."""

    __tablename__ = "media_population_run_items"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("media_population_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    dive_id = Column(Integer, ForeignKey("dives.id", ondelete="CASCADE"), nullable=False, index=True)
    video_uuid = Column(String(100), nullable=False, index=True)
    dive_code = Column(String(10), nullable=False, index=True)
    selection_band = Column(String(20), nullable=False, index=True)
    rendition = Column(String(40), nullable=False, index=True)
    media_key = Column(String(64), nullable=False, index=True)
    media_job_id = Column(Integer, ForeignKey("media_jobs.id"), nullable=True, index=True)
    status = Column(String(30), nullable=False, default="planned", index=True)
    last_error = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    run = relationship("MediaPopulationRun", back_populates="items")
    job = relationship("MediaJob")

    __table_args__ = (
        Index("ix_media_population_items_run_media_key", "run_id", "media_key"),
        Index("ix_media_population_items_run_status", "run_id", "status"),
    )


class RepresentativeMediaSelection(Base):
    """Auditable active representative attempt selection for a dive-code role."""

    __tablename__ = "representative_media_selections"

    id = Column(Integer, primary_key=True, index=True)
    dive_code = Column(String(10), nullable=False, index=True)
    selection_role = Column(String(20), nullable=False, index=True)
    dive_id = Column(Integer, ForeignKey("dives.id", ondelete="CASCADE"), nullable=False, index=True)
    selection_version = Column(Integer, nullable=False, default=1)
    selection_reason = Column(String(40), nullable=False, default="initial_manifest", index=True)
    replaced_selection_id = Column(Integer, ForeignKey("representative_media_selections.id"), nullable=True)
    active = Column(Boolean, nullable=False, default=True, index=True)
    created_by = Column(String(80), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    dive = relationship("Dive")
    replaced_selection = relationship("RepresentativeMediaSelection", remote_side=[id])

    __table_args__ = (
        Index("ix_representative_selection_code_role_active", "dive_code", "selection_role", "active"),
    )


class MediaAgent(Base):
    """Allow-listed macOS worker and its operational heartbeat."""

    __tablename__ = "media_agents"

    id = Column(String(100), primary_key=True)
    hostname = Column(String(255), nullable=False)
    api_key_sha256 = Column(String(64), unique=True, nullable=False, index=True)
    active = Column(Boolean, nullable=False, default=True, index=True)
    leasing_enabled = Column(Boolean, nullable=False, default=False, index=True)
    capabilities = Column(JSON, nullable=False, default=list)
    photos_access_status = Column(String(40), nullable=False, default="unknown")
    last_successful_photos_query_at = Column(DateTime, nullable=True)
    last_permission_error_at = Column(DateTime, nullable=True)
    last_query_timeout_at = Column(DateTime, nullable=True)
    last_successful_export_at = Column(DateTime, nullable=True)
    last_materialization_success_at = Column(DateTime, nullable=True)
    internal_free_bytes = Column(BigInteger, nullable=True)
    vault_volume_uuid = Column(String(64), nullable=True)
    vault_free_bytes = Column(BigInteger, nullable=True)
    vault_mounted = Column(Boolean, nullable=False, default=False)
    storage_status = Column(JSON, nullable=True)
    last_seen_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class RecalledMediaSource(Base):
    """Validated source file retained on one allow-listed Mac agent."""

    __tablename__ = "recalled_media_sources"

    id = Column(Integer, primary_key=True, index=True)
    video_uuid = Column(String(100), nullable=False, index=True)
    dive_id = Column(Integer, ForeignKey("dives.id", ondelete="CASCADE"), nullable=True, index=True)
    agent_id = Column(String(100), ForeignKey("media_agents.id", ondelete="CASCADE"), nullable=False, index=True)
    source_kind = Column(String(50), nullable=False)
    source_path = Column(Text, nullable=False)
    volume_uuid = Column(String(64), nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    checksum_sha256 = Column(String(64), nullable=False)
    retention_class = Column(String(40), nullable=False, default="temporary", index=True)
    active = Column(Boolean, nullable=False, default=True, index=True)
    validated_at = Column(DateTime, nullable=False)
    last_seen_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    agent = relationship("MediaAgent")
    dive = relationship("Dive")

    __table_args__ = (
        Index("ix_recalled_source_uuid_agent_active", "video_uuid", "agent_id", "active"),
        Index("ix_recalled_source_retention_expiry", "retention_class", "expires_at"),
    )


# All poster writers (including durable refresh and browser uploads) share this
# hook. Reads and access timestamp updates never decode images.
from sqlalchemy import event, inspect

@event.listens_for(MediaCacheEntry, "before_insert")
@event.listens_for(MediaCacheEntry, "before_update")
def _poster_visuals(mapper, connection, entry):
    if entry.rendition != "poster" or entry.status != "ready":
        return
    state = inspect(entry)
    if state.pending or any(state.attrs[name].history.has_changes()
                            for name in ("storage_path", "checksum_sha256")):
        from app.services.poster_visuals import enrich_poster
        enrich_poster(entry)
