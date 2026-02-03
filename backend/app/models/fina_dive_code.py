"""FINA Dive Code model with official FINA structure"""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, String, Text, Integer, DateTime, CheckConstraint, Index, Numeric
from sqlalchemy.orm import relationship

from app.database import Base


class FINADiveCode(Base):
    """Official FINA dive code reference with parsed components and metadata"""

    __tablename__ = "fina_dive_codes"

    # Primary key: the full dive code (e.g., "101B", "5231D")
    dive_code = Column(String(10), primary_key=True, index=True)

    # Parsed FINA components (for validation and analysis)
    # Group: 1=Forward, 2=Back, 3=Reverse, 4=Inward, 5=Twisting, 6=Armstand
    group = Column(Integer, nullable=False, index=True)

    # Direction (first digit of dive number for groups 1-4, or direction for group 5)
    # For group 5 (twisting): 1=Forward, 2=Back, 3=Reverse, 4=Inward
    direction = Column(Integer, nullable=False, index=True)

    # Flying: 0 = no flying, 1 = flying action present (second digit of dive number)
    has_flying = Column(Integer, default=0)

    # Number of half somersaults (1-8)
    rotations = Column(Integer, nullable=False)

    # Number of half twists (1-8+, for group 5 only)
    # For non-twisting dives, this is 0
    twists = Column(Integer, default=0)

    # Position: A=Straight, B=Pike, C=Tuck, D=Free
    position = Column(String(1), nullable=False, index=True)

    # Is this a twisting dive (group 5)?
    is_twisting = Column(Integer, default=0, index=True)

    # Is this a flying dive?
    is_flying = Column(Integer, default=0)

    # Is this an armstand dive (group 6)?
    is_armstand = Column(Integer, default=0)

    # FINA official description
    official_name = Column(String(255), nullable=True)  # e.g., "Forward Somersault"
    group_name = Column(String(100), nullable=True)  # e.g., "Forward Dives"
    position_name = Column(String(50), nullable=True)  # e.g., "Pike"

    # Additional FINA details
    description = Column(Text, nullable=True)

    # Statistics (updated by application)
    total_attempts = Column(Integer, default=0)
    avg_performance = Column(Numeric(3, 2), nullable=True)  # 0.00 to 9.99
    success_rate = Column(Numeric(5, 2), nullable=True)  # 0.00 to 100.00

    last_attempted = Column(DateTime, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    dd_lookups = relationship("DDLookup", back_populates="fina_dive_code", cascade="all, delete-orphan")

    # Constraints and indexes
    # Note: All CHECK constraints are defined in PostgreSQL migration for production
    # SQLAlchemy models don't include them to support SQLite testing
    # Validation is handled by FINAValidator service
    __table_args__ = (
        # Indexes only
        Index("idx_fina_dive_codes_group", "group", postgresql_using="btree"),
        Index("idx_fina_dive_codes_direction", "direction", postgresql_using="btree"),
        Index("idx_fina_dive_codes_position", "position", postgresql_using="btree"),
        Index("idx_fina_dive_codes_is_twisting", "is_twisting", postgresql_using="btree"),
    )

    def __repr__(self) -> str:
        return f"<FINADiveCode(code={self.dive_code}, group={self.group}, name={self.official_name})>"

    def validate_fina_structure(self) -> tuple[bool, list[str]]:
        """
        Validate dive code against official FINA rules.

        Returns: (is_valid, list of error messages)
        """
        errors = []

        # Handle nullable fields
        group = self.group or 0
        direction = self.direction or 0
        rotations = self.rotations or 0
        twists = self.twists or 0
        is_flying = self.is_flying or 0

        # Check group range
        if not (1 <= group <= 6):
            errors.append(f"Group must be 1-6, got {self.group}")

        # Check direction range
        if not (1 <= direction <= 5):
            errors.append(f"Direction must be 1-5, got {self.direction}")

        # Check position valid
        if self.position and self.position not in ("A", "B", "C", "D"):
            errors.append(f"Position must be A-D, got {self.position}")

        # Check rotations range
        if rotations and not (1 <= rotations <= 8):
            errors.append(f"Rotations must be 1-8, got {self.rotations}")

        # Check twists range
        if not (0 <= twists <= 8):
            errors.append(f"Twists must be 0-8, got {twists}")

        # CRITICAL: Group 5 (twisting) must have twists 1-8, not 0
        if group == 5 and twists == 0:
            errors.append("Group 5 (twisting) dives must have twists >= 1")

        # CRITICAL: Group 5 (twisting) direction must be 1-4
        if group == 5 and not (1 <= direction <= 4):
            errors.append(f"Group 5 (twisting) direction must be 1-4, got {self.direction}")

        # Flying dives only in groups 1-4
        if is_flying == 1 and group > 4:
            errors.append(f"Flying dives only allowed in groups 1-4, got group {self.group}")

        # Non-twisting dives must have twists = 0
        if group != 5 and twists > 0:
            errors.append(f"Non-twisting dives (group {group}) must have twists = 0")

        return len(errors) == 0, errors
