"""Judge score models for performance scoring in competitions"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, CheckConstraint, Index, Numeric
from sqlalchemy.orm import relationship

from app.database import Base


class JudgePanel(Base):
    """Panel of judges for a competitive dive"""

    __tablename__ = "judge_panels"

    id = Column(Integer, primary_key=True, index=True)

    # Event/competition context
    event_id = Column(Integer, nullable=True)  # Future: Link to Event model
    dive_id = Column(Integer, ForeignKey("dives.id", ondelete="CASCADE"), nullable=False)

    # Panel configuration
    # Valid values: 7 (individual), 11 (synchronized)
    judge_count = Column(Integer, default=7, nullable=False)

    # Whether this panel is for execution or synchronization scoring
    # Valid values: "execution", "synchronization"
    panel_type = Column(String(20), default="execution")

    # Panel average score (0-10 in 0.5 increments)
    # Calculated as: (sum of middle 3 scores) / 3
    panel_average = Column(Numeric(3, 1), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    dive = relationship("Dive")
    scores = relationship("JudgeScore", back_populates="panel", cascade="all, delete-orphan")

    # Constraints
    __table_args__ = (
        CheckConstraint("judge_count IN (7, 11)", name="check_judge_count"),
        CheckConstraint("panel_type IN ('execution', 'synchronization')", name="check_panel_type"),
        Index("idx_judge_panels_dive", "dive_id"),
    )

    def __repr__(self) -> str:
        return f"<JudgePanel(dive_id={self.dive_id}, judges={self.judge_count}, avg={self.panel_average})>"

    def is_valid_for_final_calculation(self) -> bool:
        """Check if panel has enough valid scores for calculation"""
        if not self.scores:
            return False
        # Need at least judge_count scores
        valid_scores = [s for s in self.scores if s.score is not None]
        return len(valid_scores) >= self.judge_count

    def calculate_aggregate_score(self) -> float | None:
        """
        Calculate aggregate score using FINA rules:
        - Sort scores
        - Drop 2 highest and 2 lowest
        - Average remaining 3
        - Result is 0-10 in 0.5 increments
        """
        if not self.is_valid_for_final_calculation():
            return None

        # Get all valid scores
        scores = [float(s.score) for s in self.scores if s.score is not None]
        scores.sort()

        # Drop 2 lowest and 2 highest
        remaining = scores[2:-2]

        # Average the remaining scores
        if not remaining:
            return None

        average = sum(remaining) / len(remaining)

        # Round to nearest 0.5
        return round(average * 2) / 2


class JudgeScore(Base):
    """Individual judge's score for a dive"""

    __tablename__ = "judge_scores"

    id = Column(Integer, primary_key=True, index=True)

    # Reference to panel
    panel_id = Column(Integer, ForeignKey("judge_panels.id", ondelete="CASCADE"), nullable=False)

    # Judge identifier (1-7 for regular, 1-11 for synchronized)
    judge_number = Column(Integer, nullable=False)

    # Judge name (optional, for reference)
    judge_name = Column(String(100), nullable=True)

    # The score (0-10 in 0.5 increments)
    # Valid values: 0.0, 0.5, 1.0, 1.5, ..., 9.5, 10.0
    score = Column(Numeric(3, 1), nullable=False)

    # Notes (e.g., "deduction for entry angle")
    notes = Column(String(255), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    panel = relationship("JudgePanel", back_populates="scores")

    # Constraints
    __table_args__ = (
        CheckConstraint("score >= 0 AND score <= 10", name="check_score_range"),
        # Note: 0.5 increment validation is handled by application logic, not database constraints
        # (PostgreSQL-specific casting would break SQLite compatibility)
        Index("idx_judge_scores_panel", "panel_id"),
        Index("idx_judge_scores_judge_number", "panel_id", "judge_number"),
    )

    def __repr__(self) -> str:
        return f"<JudgeScore(judge={self.judge_number}, score={self.score})>"
