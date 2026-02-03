"""DD Lookup model for official FINA Degree of Difficulty values"""

from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, CheckConstraint, Index, Numeric, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base


class DDLookup(Base):
    """Official FINA Degree of Difficulty (DD) lookup table"""

    __tablename__ = "dd_lookups"

    id = Column(Integer, primary_key=True, index=True)

    # Foreign key to FINADiveCode
    dive_code = Column(String(10), ForeignKey("fina_dive_codes.dive_code", ondelete="CASCADE"), nullable=False, index=True)

    # Height where this DD applies
    # Valid values: 1m, 3m, 5m, 7.5m, 10m
    height = Column(String(10), nullable=False, index=True)

    # Platform type
    # Valid values: springboard, platform
    platform_type = Column(String(20), nullable=False, default="springboard")

    # The official DD value (Degree of Difficulty)
    # Range: 1.2 to 4.1+ in 0.1 increments
    dd_value = Column(Numeric(3, 1), nullable=False)  # e.g., 1.2, 2.5, 3.8

    # Notes about this DD (e.g., "Official FINA 2025 table")
    notes = Column(String(255), nullable=True)

    # Effective date of this DD value (in case FINA updates tables)
    effective_date = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    fina_dive_code = relationship("FINADiveCode", back_populates="dd_lookups")

    # Constraints and indexes
    # Note: All CHECK constraints are defined in PostgreSQL migration for production
    # SQLAlchemy models keep only UNIQUE constraint for integrity
    __table_args__ = (
        # Unique constraint: each dive code + height + platform type combo has one DD value
        UniqueConstraint("dive_code", "height", "platform_type", name="uq_dive_code_height_platform"),
        # Indexes
        Index("idx_dd_lookups_dive_code_height", "dive_code", "height", postgresql_using="btree"),
        Index("idx_dd_lookups_platform", "platform_type", postgresql_using="btree"),
        Index("idx_dd_lookups_dd_value", "dd_value", postgresql_using="btree"),
    )

    def __repr__(self) -> str:
        return f"<DDLookup(dive_code={self.dive_code}, height={self.height}, dd={self.dd_value})>"
