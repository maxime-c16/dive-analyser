"""FINA Scoring Rules model for event requirements and compliance"""

from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, Text, CheckConstraint, Index, JSON, Numeric
from sqlalchemy.orm import relationship

from app.database import Base


class FINAScoringRule(Base):
    """Official FINA event requirements and scoring rules"""

    __tablename__ = "fina_scoring_rules"

    id = Column(Integer, primary_key=True, index=True)

    # Event type identifier (e.g., "springboard_1m_men", "platform_10m_women", "synchronized_3m_women")
    event_type = Column(String(100), nullable=False, index=True, unique=True)

    # Descriptive name
    event_name = Column(String(255), nullable=False)

    # Event category
    # Valid values: springboard, platform, synchronized
    event_category = Column(String(50), nullable=False, index=True)

    # Height for this event
    # Valid values: 1m, 3m, 5m, 7.5m, 10m
    height = Column(String(10), nullable=False)

    # Gender category
    # Valid values: men, women, mixed
    gender = Column(String(20), nullable=False)

    # Platform type
    # Valid values: springboard, platform
    platform_type = Column(String(20), nullable=False)

    # Number of mandatory dives
    mandatory_dive_count = Column(Integer, nullable=False)

    # DD (Degree of Difficulty) limit for initial rounds (if applicable)
    # For synchronized events, first 2 rounds limited to 2.0
    # Stored as numeric or NULL (for non-synchronized events)
    dd_limit_initial = Column(Numeric(3, 1), nullable=True)  # e.g., 1.2, 1.4, 1.6, 1.8, 2.0, or NULL

    # DD (Degree of Difficulty) limit for final rounds (if applicable)
    # Stored as numeric or NULL
    dd_limit_final = Column(Numeric(3, 1), nullable=True)  # e.g., 3.0, 3.5, or NULL for unlimited

    # Required dive groups (as JSON array, e.g., [1, 2, 3, 4, 5])
    # Must include at least one dive from each group
    mandatory_groups = Column(JSON, nullable=False)  # e.g., [1, 2, 3, 4, 5]

    # Maximum mandatory groups (some platforms allow all 6)
    max_mandatory_groups = Column(Integer, default=5)

    # Whether armstand (group 6) can be used
    allows_armstand = Column(Integer, default=0)

    # Number of judges for execution
    judge_count_execution = Column(Integer, default=7)

    # Number of judges for synchronization (if synchronized event)
    judge_count_sync = Column(Integer, nullable=True)

    # Description of event rules
    description = Column(Text, nullable=True)

    # Notes about compliance
    notes = Column(Text, nullable=True)

    # Effective date of these rules
    effective_date = Column(DateTime, default=datetime.utcnow)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Constraints and indexes
    # Note: All CHECK constraints are defined in PostgreSQL migration for production
    # SQLAlchemy models don't include them to support SQLite testing
    # Validation is handled by FINAScoringRule.validate_* methods and FINAValidator service
    __table_args__ = (
        # Indexes only
        Index("idx_fina_scoring_rules_event_type", "event_type", postgresql_using="btree"),
        Index("idx_fina_scoring_rules_event_category", "event_category", postgresql_using="btree"),
        Index("idx_fina_scoring_rules_height", "height", postgresql_using="btree"),
    )

    def __repr__(self) -> str:
        return f"<FINAScoringRule(event={self.event_type}, dives={self.mandatory_dive_count})>"

    def validate_mandatory_groups(self) -> tuple[bool, list[str]]:
        """
        Validate that mandatory_groups contains valid FINA group numbers.

        Returns: (is_valid, list of error messages)
        """
        errors = []

        if not isinstance(self.mandatory_groups, list):
            errors.append("mandatory_groups must be a list")
            return False, errors

        if len(self.mandatory_groups) < 5:
            errors.append(f"mandatory_groups must contain at least 5 groups, got {len(self.mandatory_groups)}")

        # Check all groups are valid
        for group in self.mandatory_groups:
            if not isinstance(group, int) or group < 1 or group > 6:
                errors.append(f"Invalid group {group}. Must be 1-6")

        # Check event-specific requirements
        if self.event_category in ['springboard', 'synchronized']:
            if set(self.mandatory_groups) != {1, 2, 3, 4, 5}:
                errors.append(f"{self.event_category} events must require exactly groups [1, 2, 3, 4, 5], got {sorted(self.mandatory_groups)}")

        elif self.event_category == 'platform':
            required_set = set(self.mandatory_groups)
            if not (required_set == {1, 2, 3, 4, 5} or required_set == {1, 2, 3, 4, 5, 6}):
                errors.append(f"Platform events must require [1, 2, 3, 4, 5] or [1, 2, 3, 4, 5, 6], got {sorted(self.mandatory_groups)}")

        return len(errors) == 0, errors

    def validate_dive_count(self) -> tuple[bool, list[str]]:
        """
        Validate that mandatory_dive_count matches official FINA requirements.

        Returns: (is_valid, list of error messages)
        """
        errors = []

        event_configs = {
            'springboard_1m_men': 6,
            'springboard_1m_women': 5,
            'springboard_3m_men': 6,
            'springboard_3m_women': 5,
            'platform_5m_men': 6,
            'platform_5m_women': 6,
            'platform_7.5m_men': 6,
            'platform_7.5m_women': 6,
            'platform_7m_men': 6,  # 7m is alias for 7.5m
            'platform_7m_women': 6,
            'platform_10m_men': 6,
            'platform_10m_women': 6,
            'synchronized_3m_women': 5,
            'synchronized_3m_men': 5,
            'synchronized_10m_women': 5,
            'synchronized_10m_men': 5,
            'synchronized_10m_mixed': 5,
        }

        required = event_configs.get(self.event_type)
        if required and self.mandatory_dive_count != required:
            errors.append(f"Event '{self.event_type}' requires {required} dives, got {self.mandatory_dive_count}")

        return len(errors) == 0, errors

    def validate_armstand_platform_match(self) -> tuple[bool, list[str]]:
        """
        Validate that armstand rules match platform type.

        Returns: (is_valid, list of error messages)
        """
        errors = []

        if self.platform_type == 'springboard' and self.allows_armstand == 1:
            errors.append("Armstand (group 6) not allowed for springboard events")

        if self.platform_type == 'platform' and self.allows_armstand == 0 and self.event_category != 'synchronized':
            # Platform events (except some synchronized) should allow armstand
            errors.append(f"Platform event '{self.event_type}' should allow armstand (group 6)")

        return len(errors) == 0, errors

    def validate_all_fina_rules(self) -> tuple[bool, list[str]]:
        """
        Validate entire rule set against FINA standards.

        Returns: (is_valid, list of error messages)
        """
        all_errors = []

        # Run all validation checks
        is_valid, errors = self.validate_mandatory_groups()
        all_errors.extend(errors)

        is_valid, errors = self.validate_dive_count()
        all_errors.extend(errors)

        is_valid, errors = self.validate_armstand_platform_match()
        all_errors.extend(errors)

        return len(all_errors) == 0, all_errors
