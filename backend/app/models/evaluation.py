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

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String

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
