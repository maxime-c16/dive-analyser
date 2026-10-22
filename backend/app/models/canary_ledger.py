"""Canary-only durable upload-attempt ledger (additive, local review).

One row per unique attempted B2 object (content-addressed by SHA-256).
Counts EVERY attempted unique upload including safe orphans (B2 bytes
verified but never promoted after a stale/fenced rejection, crash
retry with different bytes, SAR refusal, mid-upload re-lease). Retry of
the SAME bytes dedupes on the unique SHA (no double charge). Monotonic:
rows are never updated or deleted.

Scope: CANARY ONLY. This table does not cap future non-canary
packages; the 2 GiB bound is enforced only on the canary paths
(web_package slot publish + canary ops tool) that read this ledger.
"""

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, String

from app.database import Base


class CanarySlotReservation(Base):
    __tablename__ = "canary_slot_reservations"

    id = Column(Integer, primary_key=True, index=True)
    # Exact B2 object identity: one row per DISTINCT stored object
    # (bucket + object_key). Identical bytes stored under different keys
    # (different clip/source/role/version) are distinct B2 objects and
    # count separately -- never deduped on content SHA alone.
    # Legacy rows (pre-exact-key) carry NULL bucket/object_key and keep
    # counting as orphans (monotonic, never deleted).
    object_sha256 = Column(String(64), nullable=False, index=True)
    size_bytes = Column(BigInteger, nullable=False)
    bucket = Column(String(255), nullable=True)
    object_key = Column(String(1024), nullable=True)
    environment = Column(String(20), nullable=True)
    job_id = Column(Integer, nullable=True)
    slot = Column(String(20), nullable=True)
    status = Column(String(20), nullable=False, default="reserved")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_canary_slot_reservations_created", "created_at"),
        Index("ix_canary_slot_reservations_sha", "object_sha256"),
        Index(
            "uq_canary_slot_reservation_bucket_key",
            "bucket",
            "object_key",
            unique=True,
        ),
    )
