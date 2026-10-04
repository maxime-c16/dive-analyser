"""Photos asset model.

Stores the stable Photos-side identity and lightweight metadata for media assets.
The cache/job media architecture should reference this table instead of relying
on a local video_path on dives.
"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, Text, Index
from sqlalchemy.orm import relationship

from app.database import Base


class PhotosAsset(Base):
    """macOS Photos video asset metadata."""

    __tablename__ = "photos_assets"

    id = Column(Integer, primary_key=True, index=True)
    video_uuid = Column(String(100), unique=True, nullable=False, index=True)
    # iCloud fingerprints are stable across libraries but are not guaranteed unique.
    cloud_guid = Column(String(100), nullable=True, index=True)
    filename = Column(String(255), nullable=True)
    original_filename = Column(String(255), nullable=True)

    photos_path = Column(Text, nullable=True)
    local_available = Column(Boolean, nullable=True)
    is_missing = Column(Boolean, nullable=True)
    icloud_status = Column(String(40), nullable=True, default="unknown")

    media_type = Column(String(20), nullable=False, default="video")
    duration_seconds = Column(Numeric, nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    file_size_bytes = Column(BigInteger, nullable=True)

    raw_caption = Column(Text, nullable=True)
    caption_hash = Column(String(64), nullable=True)
    metadata_fingerprint = Column(String(64), nullable=True)

    photos_created_at = Column(DateTime, nullable=True)
    photos_modified_at = Column(DateTime, nullable=True)
    last_seen_on_mac_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    dives = relationship("Dive", back_populates="photos_asset")
    agent_identities = relationship("PhotosAssetAgentIdentity", back_populates="asset", cascade="all, delete-orphan")


class PhotosAssetAgentIdentity(Base):
    """Map one Photos asset to the local UUID used by a specific Mac library."""

    __tablename__ = "photos_asset_agent_identities"

    id = Column(Integer, primary_key=True, index=True)
    photos_asset_id = Column(Integer, ForeignKey("photos_assets.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id = Column(String(100), ForeignKey("media_agents.id", ondelete="CASCADE"), nullable=False, index=True)
    local_uuid = Column(String(100), nullable=False, index=True)
    cloud_guid = Column(String(100), nullable=True, index=True)
    last_seen_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    asset = relationship("PhotosAsset", back_populates="agent_identities")

    __table_args__ = (
        Index("ix_photos_asset_agent_identity_unique", "photos_asset_id", "agent_id", unique=True),
        Index("ix_photos_agent_local_uuid_unique", "agent_id", "local_uuid", unique=True),
    )
