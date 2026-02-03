"""Execution Fault model - represents faults detected during dive execution analysis"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, CheckConstraint, Index, Numeric
from sqlalchemy.orm import relationship

from app.database import Base


class ExecutionFault(Base):
    """Individual execution fault detected in a dive"""

    __tablename__ = "execution_faults"

    id = Column(Integer, primary_key=True, index=True)
    dive_id = Column(Integer, ForeignKey("dives.id", ondelete="CASCADE"), nullable=False)

    # Fault identification
    # Valid codes: UR (under-rotation), OR (over-rotation), LE (late entry),
    # EE (early entry), LS (lack of spin/twist), LH (lack of height),
    # PH (pike/twist issue), SA (starting approach issue), LK (lack of control)
    fault_code = Column(String(5), nullable=False, index=True)

    # Severity levels: HIGH, MEDIUM, LOW
    # HIGH: Significant deduction (>1.0 point), impacts scoring substantially
    # MEDIUM: Moderate deduction (0.5-1.0 point), typical coaching focus
    # LOW: Minor deduction (<0.5 point), cosmetic issues
    severity = Column(String(10), nullable=False)

    # Which phase the fault occurred (1 or 2, or None for overall)
    # Phase 1: Hurdle + Flight (takeoff quality)
    # Phase 2: Opening + Water Splash + Entry (landing quality)
    phase = Column(Integer, nullable=True)

    # Human-readable description of the fault
    description = Column(Text, nullable=True)

    # Coaching recommendation for correcting this fault
    coaching_recommendation = Column(Text, nullable=True)

    # FINA fault category (from official FINA scoring guidelines)
    # Used for official competition compliance
    fina_category = Column(String(100), nullable=True)

    # Points deducted from final score due to this fault (calculated from severity)
    points_deducted = Column(Numeric(3, 1), nullable=True)

    # Raw metric value that triggered this fault (e.g., rotation angle, entry distance)
    raw_metric = Column(Numeric(5, 2), nullable=True)

    # Threshold that was exceeded to trigger this fault
    metric_threshold = Column(Numeric(5, 2), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    dive = relationship("Dive", back_populates="execution_faults")

    # Constraints and indexes
    __table_args__ = (
        CheckConstraint("severity IN ('HIGH', 'MEDIUM', 'LOW')", name="check_severity"),
        CheckConstraint("phase IS NULL OR (phase >= 1 AND phase <= 2)", name="check_phase"),
        Index("idx_execution_faults_dive", "dive_id", postgresql_using="btree"),
        Index("idx_execution_faults_fault_code", "fault_code", postgresql_using="btree"),
        Index("idx_execution_faults_severity", "severity", postgresql_using="btree"),
        Index("idx_execution_faults_phase", "phase", postgresql_using="btree"),
        # Composite index for common queries
        Index("idx_execution_faults_dive_phase", "dive_id", "phase", postgresql_using="btree"),
        # UNIQUE constraint: (dive_id, fault_code, phase) - one instance of each fault per phase per dive
        Index("idx_execution_faults_unique", "dive_id", "fault_code", "phase", unique=True, postgresql_using="btree"),
    )

    def __repr__(self) -> str:
        return f"<ExecutionFault(id={self.id}, dive_id={self.dive_id}, code={self.fault_code}, severity={self.severity})>"
