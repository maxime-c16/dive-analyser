"""Media backbone additive schema (DIVE_ANALYZER_MEDIA_BACKBONE_V1).

Content-addressed media blobs, append-only media revisions and caption
revisions, and the server-side durable commit ledger. Strictly additive:
no legacy table is altered. `video_uuid` is the existing application-owned
logical clip identity (dives.video_uuid / photos_assets.video_uuid); it is
recorded as an indexed string here (no FK cascade entanglement) so the
migration is fully reversible by dropping these tables alone.

STATE AUTHORITY (repair R3): there is ONE coherent model with two layers —
- LOCAL EXECUTION JOURNAL (mac-agent per-clip JSON state file,
  `mac-agent/src/ingest/state_store.py`): the ONLY authority for pre-commit /
  restart / retry mechanics on macOS.
- SERVER DB (media_blobs / media_revisions / caption_revisions + the
  `ingest_object_state` COMMIT LEDGER): the ONLY authority for the durable
  committed logical result. `ingest_object_state` is written exactly once per
  verified ingest commit by `commit_verified_ingest` and is NEVER read by
  agent-side orchestration — it is not a second state machine.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)

from app.database import Base


class MediaBlob(Base):
    __tablename__ = "media_blobs"

    sha256 = Column(String(64), primary_key=True, index=True)
    byte_size = Column(BigInteger, nullable=False)
    codec = Column(String(40), nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    duration_seconds = Column(Numeric, nullable=True)
    rendition_semantics = Column(
        String(60), nullable=False, default="photos_edited_rendition"
    )
    storage_backend = Column(String(40), nullable=False, default="b2")
    bucket = Column(String(120), nullable=True)
    object_key = Column(String(160), nullable=True, index=True)
    remote_object_id = Column(String(120), nullable=True)
    ingest_impl_version = Column(String(40), nullable=False, default="media_backbone_v1")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class MediaRevision(Base):
    __tablename__ = "media_revisions"

    id = Column(Integer, primary_key=True, index=True)
    video_uuid = Column(String(100), nullable=False, index=True)
    blob_sha256 = Column(
        String(64), nullable=False, index=True
    )
    photos_edit_fingerprint = Column(String(120), nullable=True)
    rendition_semantics = Column(
        String(60), nullable=False, default="photos_edited_rendition"
    )
    source_provenance = Column(JSON, nullable=False, default=dict)
    observed_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index(
            "ix_media_revisions_clip_blob_unique",
            "video_uuid",
            "blob_sha256",
            unique=True,
        ),
    )


class CaptionRevision(Base):
    __tablename__ = "caption_revisions"

    id = Column(Integer, primary_key=True, index=True)
    video_uuid = Column(String(100), nullable=False, index=True)
    caption_raw = Column(Text, nullable=False)
    caption_sha256 = Column(String(64), nullable=False, index=True)
    caption_provider = Column(String(60), nullable=False)
    parser_version = Column(String(40), nullable=True)
    parsed_json = Column(JSON, nullable=True)
    shadow_provider = Column(String(60), nullable=True)
    shadow_raw = Column(Text, nullable=True)
    shadow_sha256 = Column(String(64), nullable=True)
    shadow_available = Column(Boolean, nullable=True)
    exact_equal = Column(Boolean, nullable=True)
    observed_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index(
            "ix_caption_revisions_clip_sha_unique",
            "video_uuid",
            "caption_sha256",
            unique=True,
        ),
    )


class IngestObjectState(Base):
    """Server-side durable commit ledger (repair R3).

    Written exactly once per verified ingest commit (`DB_COMMITTED` evidence);
    never read by agent-side orchestration, which uses the local execution
    journal only.
    """

    __tablename__ = "ingest_object_state"

    id = Column(Integer, primary_key=True, index=True)
    video_uuid = Column(String(100), nullable=False, index=True)
    object_key = Column(String(160), nullable=False, index=True)
    state = Column(String(40), nullable=False, default="DISCOVERED", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    error_family = Column(String(60), nullable=True)
    local_temp_path = Column(Text, nullable=True)
    blob_sha256 = Column(String(64), nullable=True, index=True)
    caption_sha256 = Column(String(64), nullable=True, index=True)
    verified = Column(Boolean, nullable=False, default=False)
    db_committed_at = Column(DateTime, nullable=True)
    environment = Column(String(20), nullable=False, default="dev")
    storage_backend = Column(String(40), nullable=False, default="b2")
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index(
            "ix_ingest_object_state_clip_key_unique",
            "video_uuid",
            "object_key",
            unique=True,
        ),
    )
