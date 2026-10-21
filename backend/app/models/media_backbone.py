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
- SERVER DB (media_blobs / media_blob_locations / media_revisions /
  caption_revisions + the `ingest_object_state` COMMIT LEDGER): the ONLY
  authority for the durable committed logical result. `ingest_object_state`
  is written once per verified ingest commit by `commit_verified_ingest` and
  is NEVER read by agent-side orchestration — it is not a second state
  machine.

STORAGE AUTHORITY (repair P4.3): CONTENT IDENTITY and PHYSICAL STORAGE
REPLICAS are separate concepts.
- `MediaBlob` is content identity ONLY: one row per unique SHA-256, with
  immutable content-level metadata. Its `storage_backend` / `bucket` /
  `object_key` / `remote_object_id` columns are TRANSITIONAL and
  NON-AUTHORITATIVE location fields retained for compatibility; they record
  the first-seen location only and MUST NOT be used to answer "where is the
  verified replica of this blob in environment E?".
- `MediaBlobLocation` is the authoritative per-replica physical storage
  record: one row per (storage_backend, bucket, object_key) replica of a
  blob, carrying its environment and verification state. The same SHA may
  have any number of replicas (e.g. one in the DEV bucket and one in the
  PROD bucket) without either being lost or overwritten.
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
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
    # TRANSITIONAL / NON-AUTHORITATIVE location fields (P4.3): retained for
    # compatibility, record the first-seen location only. The authoritative
    # replica records live in media_blob_locations.
    storage_backend = Column(String(40), nullable=False, default="b2")
    bucket = Column(String(120), nullable=True)
    object_key = Column(String(160), nullable=True, index=True)
    remote_object_id = Column(String(120), nullable=True)
    ingest_impl_version = Column(String(40), nullable=False, default="media_backbone_v1")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class MediaBlobLocation(Base):
    """Authoritative physical storage replica of a content blob (P4.3).

    One row per physical object: (storage_backend, bucket, object_key)
    identifies the replica; blob_sha256 ties it to content identity;
    environment is the commit/storage context (dev|prod), NOT a property of
    the SHA itself. The same blob may exist in the DEV and PROD buckets as
    two distinct replicas; neither replica is derived from or overwritten by
    the other.

    Lookup contract (P5 precondition): given a blob SHA and an environment,
    the verified location for that environment is deterministic.
    """

    __tablename__ = "media_blob_locations"

    id = Column(Integer, primary_key=True, index=True)
    blob_sha256 = Column(String(64), nullable=False, index=True)
    environment = Column(String(20), nullable=False)
    storage_backend = Column(String(40), nullable=False, default="b2")
    bucket = Column(String(120), nullable=False)
    object_key = Column(String(160), nullable=False)
    remote_object_id = Column(String(120), nullable=True)
    verified = Column(Boolean, nullable=False, default=False)
    verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        # Physical replica identity: a location key belongs to exactly one
        # content SHA (same key with conflicting SHA must never be inserted).
        Index(
            "ix_media_blob_locations_replica_unique",
            "storage_backend",
            "bucket",
            "object_key",
            unique=True,
        ),
        # Per-blob replica: the same content in the same physical location is
        # one row (idempotent dedupe of storage locations).
        Index(
            "ix_media_blob_locations_blob_replica_unique",
            "blob_sha256",
            "storage_backend",
            "bucket",
            "object_key",
            unique=True,
        ),
        # Deterministic environment lookup: SHA + environment → verified row.
        Index("ix_media_blob_locations_blob_env", "blob_sha256", "environment"),
    )


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

    Written once per verified ingest commit (`DB_COMMITTED` evidence); never
    read by agent-side orchestration, which uses the local execution journal
    only.

    Ledger identity (P4.3): one row per (video_uuid, environment, object_key)
    logical ingest event. The same content-addressed object_key can be
    committed in the DEV and PROD environments as two distinct ledger rows;
    the pre-P4.3 (video_uuid, object_key) uniqueness conflated the two
    environments and was replaced by environment-scoped uniqueness.
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
            "ix_ingest_object_state_clip_env_key_unique",
            "video_uuid",
            "environment",
            "object_key",
            unique=True,
        ),
    )


class MediaDerivative(Base):
    """D1 durable-derivative ledger (HQ/light/poster web renditions).

    One row per derivation: the (video_uuid, source revision, role,
    transform version) identity that a future publisher (D3, after D2
    fencing) commits alongside `commit_verified_ingest`, whose revision
    carries the matching `derived_*` rendition semantics. D1 is
    publish- and read-inert: no job references this table and no route
    serves it, so rows can only be written by hand/tests until D3. A
    `ready` row in D1 therefore proves nothing about storage (no
    roundtrip verify ran); the future publisher may mark `ready` only
    after the D3 upload→roundtrip-verify→commit sequence.

    STORAGE AUTHORITY: by convention `video_uuid` is the
    application-owned logical clip identity recorded as an indexed string
    (no FK cascade entanglement) and both SHAs are content identities with
    no FK to `media_blobs` — the same convention as `MediaRevision`
    (whose `blob_sha256` likewise carries no FK). The future publisher
    commits the blob, its verified location, the `derived_*` revision and
    this ledger row in one transaction with application-level ordering.

    Ledger identity is a UNIQUE INDEX (`uq_media_derivative_identity`),
    not a table constraint, so the future publisher upserts with
    `ON CONFLICT (video_uuid, source_blob_sha256, role, transform_version)`
    (column list), never `ON CONSTRAINT <name>`. `finalized_slots` on
    `media_jobs` ships NULL-default in D1 (NULL = no slot finalized yet);
    D3 must treat NULL as empty.

    Schema rollback is NOT supported (runbook: never roll back this
    migration — drops would destroy ledger history later slices depend
    on). Old code boots on the new schema (it never touches these
    columns).
    """

    __tablename__ = "media_derivatives"

    id = Column(Integer, primary_key=True, index=True)
    video_uuid = Column(String(100), nullable=False, index=True)
    source_blob_sha256 = Column(String(64), nullable=False, index=True)
    role = Column(String(20), nullable=False, index=True)
    transform_version = Column(String(40), nullable=False)
    derivative_blob_sha256 = Column(String(64), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="verifying", server_default="verifying", index=True)
    verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        CheckConstraint(
            "role IN ('hq', 'light', 'poster')", name="ck_media_derivative_role"
        ),
        CheckConstraint(
            "status IN ('verifying', 'ready', 'stale', 'superseded')",
            name="ck_media_derivative_status",
        ),
        Index(
            "uq_media_derivative_identity",
            "video_uuid",
            "source_blob_sha256",
            "role",
            "transform_version",
            unique=True,
        ),
        Index(
            "ix_media_derivative_clip_role",
            "video_uuid",
            "role",
            "status",
        ),
    )
