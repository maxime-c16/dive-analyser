"""Canary-only durable PUT-attempt charge ledger (additive, local review).

One row per attempted B2 PUT (content-addressed by EXACT B2 namespace
bucket+object_key, which embeds the content SHA). EVERY actual PUT
attempt inserts its own row and counts its bytes separately -- including
safe orphans (B2 bytes verified but never promoted after a stale/fenced
rejection, crash retry, SAR refusal, mid-upload re-lease) and concurrent
same-key retries that both miss the pre-PUT full-GET reuse check (each
PUT may create a distinct stored version; each is charged). Monotonic:
rows are never updated, refunded, or deleted; a later publish-unit
rollback never removes the committed charge.

A verified full-GET reuse (same key already proves the same bytes)
skips the PUT and charges nothing new. But once the GET misses, the
attempt MUST charge before the PUT -- two racers that both miss each
charge, even for the same key. Idempotent replay therefore over-counts
instead of under-counting (safe direction); the exact same attempt is
never silently re-charged-free while another PUT could still happen.

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
    # Exact B2 object identity per PUT ATTEMPT: one row per attempted PUT
    # (bucket + object_key), each charged separately. Identical bytes
    # stored under different keys (different clip/source/role/version)
    # are distinct objects and count separately; the SAME key retried
    # (same bytes, concurrent racers that both missed the pre-PUT
    # full-GET reuse check) inserts one row PER ATTEMPT -- each PUT may
    # create a distinct stored version, so each is charged. Only a
    # verified full-GET reuse (no PUT at all) avoids a new charge.
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
        # Non-unique by design: each PUT attempt inserts its own charge
        # row (see add_canary_put_attempt_charges.sql, which drops the
        # earlier UNIQUE bucket+key index). Same-key duplicates are
        # concurrent/retry attempts, each counted.
        Index(
            "ix_canary_slot_reservation_bucket_key",
            "bucket",
            "object_key",
        ),
    )
