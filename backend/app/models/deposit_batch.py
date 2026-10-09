"""Deposit-batch models: evaluator notes, magic-link claim tokens, email outbox.

Maps exactly the tables created by backend/migrations/add_deposit_batches.sql.
See that file for the product contract (pending acceptance, depositor access,
one email per diver per batch).
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)

from app.database import Base


class EvaluatorNote(Base):
    """Maintainer note attached at deposit time (one per dive).

    score_half_steps stays NULL for a note-only evaluation (0-20 when the
    maintainer also scores). The jury stack can later adopt these rows.
    """

    __tablename__ = "evaluator_notes"

    id = Column(Integer, primary_key=True, index=True)
    dive_id = Column(Integer, ForeignKey("dives.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    author_user_id = Column(Integer, ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False, index=True)
    score_half_steps = Column(Integer, nullable=True)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        CheckConstraint(
            "score_half_steps IS NULL OR (score_half_steps >= 0 AND score_half_steps <= 20)",
            name="ck_evaluator_note_score",
        ),
        CheckConstraint(
            "comment IS NOT NULL OR score_half_steps IS NOT NULL",
            name="ck_evaluator_note_content",
        ),
    )


class ClaimToken(Base):
    """Single-purpose magic-link token for the batch email button.

    Only the SHA-256 hash is stored (same pattern as user_sessions).
    Redeeming mints a normal user session and marks the token used.
    """

    __tablename__ = "claim_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False, index=True)
    batch_id = Column(String(36), nullable=False, index=True)
    # A batch id can span several divers (agent-day batches), and one email
    # is sent per diver: the link opens that diver's clips only.
    diver_id = Column(Integer, ForeignKey("divers.id", ondelete="CASCADE"), nullable=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    created_by_user_id = Column(Integer, ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class BatchEmailOutbox(Base):
    """One email per (batch, recipient). Status machine for the sender cron."""

    __tablename__ = "batch_email_outbox"

    STATUS_PENDING = "pending"
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(String(36), nullable=False, index=True)
    diver_id = Column(Integer, ForeignKey("divers.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    scheduled_for = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    sent_at = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("status IN ('pending', 'sent', 'failed')", name="ck_batch_email_status"),
        Index("uq_batch_email_recipient", "batch_id", "diver_id", "user_id", unique=True),
        Index("ix_batch_email_due", "status", "scheduled_for"),
    )
