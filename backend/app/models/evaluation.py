"""Community evaluation requests.

One request per dive, owned by the current dive owner. The request uses the
current owner of the Dive for authorization (UserDiverAccess OWNER chain);
``created_by_user_id`` only records who opened it and never replaces the
ownership link. Deleting a Dive cascades to its request, and votes (added in
ticket 2) cascade from the request.

Activation requires an attributed dive (``diver_id``) and a video identity
(``video_uuid``); a not-yet-ready video can be requested and only enters the
jury queue (ticket 2) once media is available. Visibility of the Dive is never
modified by the toggle.
"""
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint

from app.database import Base


class EvaluationRequest(Base):
    """Owner opt-in to have one dive judged by the community."""

    __tablename__ = "evaluation_requests"

    id = Column(Integer, primary_key=True)
    dive_id = Column(Integer, ForeignKey("dives.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    active = Column(Boolean, nullable=False, default=False, index=True)
    prompt = Column(String(1000), nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("app_users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("prompt IS NULL OR length(prompt) <= 1000", name="ck_evaluation_request_prompt"),
        Index("idx_evaluation_requests_active", "active", "created_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<EvaluationRequest(id={self.id}, dive_id={self.dive_id}, active={self.active})>"


class EvaluationRating(Base):
    """One member's immutable judgment of one evaluation request.

    ``score_half_steps`` is 0–20 and displays as score/2 (0–10 by half points).
    Votes never modify dive scores, DD, journeys or official panels. Deactivating
    the request keeps votes and their panel; deleting the Dive cascades them.
    The snapshot columns freeze the technical dive context as the evaluator saw
    it (code, height, platform, diver name, request prompt) so a later edit by
    the owner cannot rewrite what was judged.
    """

    __tablename__ = "evaluation_ratings"

    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey("evaluation_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    evaluator_user_id = Column(Integer, ForeignKey("app_users.id"), nullable=False, index=True)
    score_half_steps = Column(Integer, nullable=False)  # 0–20; display /2
    comment = Column(String(2000), nullable=True)
    dive_code = Column(String(10), nullable=False)
    height = Column(String(5), nullable=False)
    platform_type = Column(String(20), nullable=False)
    dive_name = Column(String(100), nullable=False)
    prompt_snapshot = Column(String(1000), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("request_id", "evaluator_user_id", name="uq_evaluation_rating_once"),
        CheckConstraint("score_half_steps >= 0 AND score_half_steps <= 20", name="ck_evaluation_rating_score"),
        CheckConstraint("comment IS NULL OR length(comment) BETWEEN 1 AND 2000", name="ck_evaluation_rating_comment"),
        Index("idx_evaluation_ratings_evaluator", "evaluator_user_id", "created_at"),
    )


class EvaluationSession(Base):
    """Server-side jury session for one account (24 h, not revocable locally).

    Votes stay tied to the account, never to the session. ``client_session_id``
    is the caller's idempotency key; an unexpired live session for the account
    is reused regardless of the presented id so multiple tabs of one account
    share one queue.
    """

    __tablename__ = "evaluation_sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False, index=True)
    client_session_id = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False, index=True)
    revoked_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("client_session_id", name="uq_evaluation_session_client"),
    )


class EvaluationSessionRequest(Base):
    """Marked proposals of one session: queue allocation bookkeeping.

    Unique (session_id, request_id) so a request is proposed at most once per
    session; state 'proposed' → 'skipped' when the evaluator passes it out.
    Exclusions do NOT survive the session: a skipped request returns in the
    next session while it stays active and unrated.
    """

    __tablename__ = "evaluation_session_requests"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("evaluation_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    request_id = Column(Integer, ForeignKey("evaluation_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    batch_id = Column(String(64), nullable=False)
    state = Column(String(16), nullable=False, default="proposed")
    proposed_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("session_id", "request_id", name="uq_evaluation_session_request"),
        CheckConstraint("state IN ('proposed', 'skipped')", name="ck_evaluation_session_request_state"),
        Index("idx_evaluation_session_requests_batch", "session_id", "batch_id"),
    )
