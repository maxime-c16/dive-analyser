"""Sprint 1 Foundation Tests - FINA Integration
Tests for FINADiveCode, DDLookup, FINAScoringRule models and FINAValidator service.

Note: Tests focus on the FINAValidator service which validates FINA rules.
Model constraint tests are tested at the PostgreSQL migration level since SQLite
doesn't support all the complex CHECK constraints used in production.
"""

import pytest
from decimal import Decimal
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models import FINADiveCode, DDLookup, FINAScoringRule
from app.services.fina_validator import FINAValidator, FINAValidationError


class TestFINADiveCodeModel:
    """Test FINADiveCode model - basic creation"""

    def test_create_forward_dive_101b(self, test_db: Session):
        """Test creating a valid forward dive (101B)"""
        dive = FINADiveCode(
            dive_code="101B",
            group=1,
            direction=1,
            has_flying=0,
            rotations=1,
            twists=0,
            position="B",
            is_twisting=0,
            is_flying=0,
            is_armstand=0,
            official_name="Forward Dive",
            group_name="Forward Dives",
            position_name="Pike",
        )
        test_db.add(dive)
        test_db.commit()

        retrieved = test_db.query(FINADiveCode).filter_by(dive_code="101B").first()
        assert retrieved is not None
        assert retrieved.group == 1
        assert retrieved.position == "B"

    def test_create_multiple_dives(self, test_db: Session):
        """Test creating multiple valid FINA dives"""
        dives = [
            FINADiveCode(dive_code="101B", group=1, direction=1, rotations=1, position="B", has_flying=0),
            FINADiveCode(dive_code="5231D", group=5, direction=4, rotations=3, twists=3, position="D", is_twisting=1),
            FINADiveCode(dive_code="111C", group=1, direction=1, rotations=1, position="C", has_flying=1, is_flying=1),
            FINADiveCode(dive_code="6031B", group=6, direction=0, rotations=3, position="B", is_armstand=1),
        ]
        for dive in dives:
            test_db.add(dive)
        test_db.commit()

        assert test_db.query(FINADiveCode).count() == 4


class TestDDLookupModel:
    """Test DDLookup model - basic creation"""

    @pytest.fixture
    def sample_fina_dive(self, test_db: Session):
        """Create a sample FINA dive code"""
        dive = FINADiveCode(
            dive_code="101B",
            group=1,
            direction=1,
            rotations=1,
            position="B",
        )
        test_db.add(dive)
        test_db.commit()
        return dive

    def test_create_dd_lookup_1m_springboard(self, test_db: Session, sample_fina_dive):
        """Test creating a DD lookup for 1m springboard"""
        dd = DDLookup(
            dive_code="101B",
            height="1m",
            platform_type="springboard",
            dd_value=Decimal("1.3"),
            notes="Official FINA 2025",
        )
        test_db.add(dd)
        test_db.commit()

        retrieved = test_db.query(DDLookup).filter_by(dive_code="101B", height="1m").first()
        assert retrieved is not None
        assert retrieved.dd_value == Decimal("1.3")

    def test_create_multiple_heights(self, test_db: Session, sample_fina_dive):
        """Test creating DD lookups for multiple heights"""
        lookups = [
            DDLookup(dive_code="101B", height="1m", platform_type="springboard", dd_value=Decimal("1.3")),
            DDLookup(dive_code="101B", height="3m", platform_type="springboard", dd_value=Decimal("1.5")),
            DDLookup(dive_code="101B", height="10m", platform_type="platform", dd_value=Decimal("2.1")),
        ]
        for lookup in lookups:
            test_db.add(lookup)
        test_db.commit()

        assert test_db.query(DDLookup).count() == 3


class TestFINAScoringRuleModel:
    """Test FINAScoringRule model - basic creation"""

    def test_create_springboard_1m_men_rules(self, test_db: Session):
        """Test creating event rules for springboard 1m men"""
        rule = FINAScoringRule(
            event_type="springboard_1m_men",
            event_name="Men's 1m Springboard",
            event_category="springboard",
            height="1m",
            gender="men",
            platform_type="springboard",
            mandatory_dive_count=6,
            mandatory_groups=[1, 2, 3, 4, 5],
            judge_count_execution=7,
        )
        test_db.add(rule)
        test_db.commit()

        retrieved = test_db.query(FINAScoringRule).filter_by(event_type="springboard_1m_men").first()
        assert retrieved is not None
        assert retrieved.mandatory_dive_count == 6

    def test_validate_mandatory_groups(self, test_db: Session):
        """Test mandatory_groups validation method"""
        rule = FINAScoringRule(
            event_type="springboard_1m_men",
            event_name="Men's 1m Springboard",
            event_category="springboard",
            height="1m",
            gender="men",
            platform_type="springboard",
            mandatory_dive_count=6,
            mandatory_groups=[1, 2, 3, 4, 5],
        )
        is_valid, errors = rule.validate_mandatory_groups()
        assert is_valid is True
        assert len(errors) == 0

    def test_validate_dive_count(self, test_db: Session):
        """Test dive_count validation method"""
        rule = FINAScoringRule(
            event_type="springboard_1m_men",
            event_name="Men's 1m Springboard",
            event_category="springboard",
            height="1m",
            gender="men",
            platform_type="springboard",
            mandatory_dive_count=6,
            mandatory_groups=[1, 2, 3, 4, 5],
        )
        is_valid, errors = rule.validate_dive_count()
        assert is_valid is True
        assert len(errors) == 0

    def test_validate_dive_count_women(self, test_db: Session):
        """Test dive_count validation for women's events (5 dives)"""
        rule = FINAScoringRule(
            event_type="springboard_1m_women",
            event_name="Women's 1m Springboard",
            event_category="springboard",
            height="1m",
            gender="women",
            platform_type="springboard",
            mandatory_dive_count=5,
            mandatory_groups=[1, 2, 3, 4, 5],
        )
        is_valid, errors = rule.validate_dive_count()
        assert is_valid is True
        assert len(errors) == 0

    def test_fina_dive_code_validation(self, test_db: Session):
        """Test FINADiveCode validation methods"""
        # Valid dive code
        dive = FINADiveCode(
            dive_code="101B",
            group=1,
            direction=1,
            rotations=1,
            position="B",
        )
        is_valid, errors = dive.validate_fina_structure()
        assert is_valid is True
        assert len(errors) == 0

    def test_group5_must_have_twists(self, test_db: Session):
        """Test that Group 5 dives must have twists >= 1"""
        dive = FINADiveCode(
            dive_code="5110D",
            group=5,
            direction=1,
            rotations=1,
            twists=0,  # INVALID for group 5
            position="D",
            is_twisting=1,
        )
        is_valid, errors = dive.validate_fina_structure()
        assert is_valid is False
        assert any("twists" in err.lower() for err in errors)

    def test_group5_direction_must_be_1_4(self, test_db: Session):
        """Test that Group 5 direction must be 1-4"""
        dive = FINADiveCode(
            dive_code="5510D",
            group=5,
            direction=5,  # INVALID: must be 1-4
            rotations=1,
            twists=1,
            position="D",
            is_twisting=1,
        )
        is_valid, errors = dive.validate_fina_structure()
        assert is_valid is False
        assert any("direction" in err.lower() for err in errors)

    def test_rule_validate_all_fina_rules(self, test_db: Session):
        """Test comprehensive FINA rule validation"""
        rule = FINAScoringRule(
            event_type="springboard_1m_men",
            event_name="Men's 1m Springboard",
            event_category="springboard",
            height="1m",
            gender="men",
            platform_type="springboard",
            mandatory_dive_count=6,
            mandatory_groups=[1, 2, 3, 4, 5],
            allows_armstand=0,
        )
        is_valid, errors = rule.validate_all_fina_rules()
        assert is_valid is True
        assert len(errors) == 0

    def test_armstand_platform_validation(self, test_db: Session):
        """Test armstand platform type matching"""
        # Invalid: springboard with armstand
        rule = FINAScoringRule(
            event_type="springboard_1m_men",
            event_name="Men's 1m Springboard",
            event_category="springboard",
            height="1m",
            gender="men",
            platform_type="springboard",
            mandatory_dive_count=6,
            mandatory_groups=[1, 2, 3, 4, 5],
            allows_armstand=1,  # INVALID
        )
        is_valid, errors = rule.validate_armstand_platform_match()
        assert is_valid is False
        assert any("armstand" in err.lower() for err in errors)


class TestFINAValidator:
    """Test FINAValidator service"""

    @pytest.fixture
    def validator(self, test_db: Session):
        """Create a validator instance"""
        return FINAValidator(test_db)

    def test_validate_forward_dive_101b(self, validator: FINAValidator):
        """Test validating forward dive format"""
        result = validator.validate_dive_code_format("101B")
        assert result["group"] == 1
        assert result["direction"] == 1
        assert result["position"] == "B"
        assert result["rotations"] == 1
        assert result["is_twisting"] is False

    def test_validate_twisting_dive_5231d(self, validator: FINAValidator):
        """Test validating twisting dive format (Back twist 1.5 somersaults 1.5 twists free)"""
        result = validator.validate_dive_code_format("5231D")
        assert result["group"] == 5
        assert result["direction"] == 2  # 2 = Back
        assert result["position"] == "D"  # Free
        assert result["rotations"] == 3  # 1.5 somersaults
        assert result["twists"] == 1  # 0.5 twist
        assert result["is_twisting"] is True

    def test_validate_flying_dive_111c(self, validator: FINAValidator):
        """Test validating flying dive format"""
        result = validator.validate_dive_code_format("111C")
        assert result["group"] == 1
        assert result["has_flying"] == 1
        assert result["is_flying"] is True

    def test_validate_invalid_group(self, validator: FINAValidator):
        """Test that invalid group is rejected"""
        with pytest.raises(FINAValidationError):
            validator.validate_dive_code_format("999A")

    def test_validate_invalid_position(self, validator: FINAValidator):
        """Test that invalid position is rejected"""
        with pytest.raises(FINAValidationError):
            validator.validate_dive_code_format("101X")

    def test_validate_invalid_rotations_too_high(self, validator: FINAValidator):
        """Test that rotations > 8 are rejected"""
        with pytest.raises(FINAValidationError):
            validator.validate_dive_code_format("1099A")

    def test_dd_value_validation_valid(self, validator: FINAValidator):
        """Test validating valid DD values"""
        assert validator.validate_dd_value(Decimal("1.2")) is True
        assert validator.validate_dd_value(Decimal("2.5")) is True
        assert validator.validate_dd_value(Decimal("4.1")) is True
        assert validator.validate_dd_value("3.0") is True

    def test_dd_value_validation_invalid(self, validator: FINAValidator):
        """Test rejecting invalid DD values"""
        assert validator.validate_dd_value(Decimal("1.0")) is False
        assert validator.validate_dd_value(Decimal("4.2")) is False
        assert validator.validate_dd_value("invalid") is False

    def test_invalid_height_in_lookup(self, validator: FINAValidator):
        """Test that invalid height raises error"""
        with pytest.raises(FINAValidationError):
            validator.lookup_dd("101B", "2m")

    def test_clear_dd_cache(self, validator: FINAValidator):
        """Test that cache can be cleared"""
        validator._dd_cache["test"] = "value"
        assert len(validator._dd_cache) > 0
        validator.clear_cache()
        assert len(validator._dd_cache) == 0
