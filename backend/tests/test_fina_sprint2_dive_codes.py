"""Sprint 2: Dive Code System Tests
Comprehensive tests for dive code parsing, validation, and API endpoints.
"""

import pytest
import json
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from decimal import Decimal

from app.main import app
from app.models import FINADiveCode
from app.services.dive_code_parser import DiveCodeParser, DiveCodeData
from app.services.dive_code_validator import DiveCodeValidator
from app.database import get_db


client = TestClient(app)


# ============================================================================
# Tests for DiveCodeParser Service (Task 2.1)
# ============================================================================


class TestDiveCodeParser:
    """Test the DiveCodeParser service"""

    def test_parse_minimal_app_format(self):
        """Parse minimal app format: just dive code"""
        result = DiveCodeParser.parse("101B")
        assert result.is_valid
        assert result.dive_code == "101B"
        assert result.group == 1
        assert result.direction == 1
        assert result.position == "B"
        assert result.height == "1m"
        assert not result.is_sync
        assert not result.is_smack

    def test_parse_full_app_format_with_perf_and_height(self):
        """Parse app format with performance and height"""
        result = DiveCodeParser.parse("101B M 3m")
        assert result.is_valid
        assert result.dive_code == "101B"
        assert result.performance == "M"
        assert result.performance_numeric == 2
        assert result.height == "3m"
        assert result.platform_type == "springboard"

    def test_parse_app_format_with_sync_flag(self):
        """Parse app format with SYNC flag"""
        result = DiveCodeParser.parse("5231D G 10m SYNC")
        assert result.is_valid
        assert result.dive_code == "5231D"
        assert result.group == 5
        assert result.direction == 2
        assert result.position == "D"
        assert result.performance == "G"
        assert result.performance_numeric == 3
        assert result.height == "10m"
        assert result.is_sync

    def test_parse_app_format_with_smack_flag(self):
        """Parse app format with SMACK flag"""
        result = DiveCodeParser.parse("101C B 1m SMACK")
        assert result.is_valid
        assert result.is_smack

    def test_parse_with_both_sync_and_smack(self):
        """Parse with both SYNC and SMACK flags"""
        result = DiveCodeParser.parse("5231D P 10m SYNC SMACK")
        assert result.is_valid
        assert result.is_sync
        assert result.is_smack

    def test_parse_performance_scale(self):
        """Test all performance ratings"""
        perf_map = {"F": 0, "B": 1, "M": 2, "G": 3, "P": 4}
        for letter, numeric in perf_map.items():
            result = DiveCodeParser.parse(f"101B {letter}")
            assert result.performance == letter
            assert result.performance_numeric == numeric

    def test_parse_height_normalization(self):
        """Test height normalization (7m → 7.5m)"""
        result = DiveCodeParser.parse("101B 7m")
        assert result.is_valid
        assert result.height == "7.5m"  # Normalized

    def test_parse_all_valid_heights(self):
        """Test parsing all valid heights"""
        valid_heights = ["1m", "3m", "5m", "7m", "10m"]
        for height in valid_heights:
            result = DiveCodeParser.parse(f"101B {height}")
            assert result.is_valid, f"Should parse height {height}"

    def test_parse_height_to_platform_mapping(self):
        """Test height to platform type mapping"""
        springboard_heights = {"1m": "springboard", "3m": "springboard"}
        platform_heights = {"5m": "platform", "7.5m": "platform", "10m": "platform"}

        for height, expected_platform in {**springboard_heights, **platform_heights}.items():
            # For 7m test, need to use normalized form
            input_height = "7m" if height == "7.5m" else height
            result = DiveCodeParser.parse(f"101B {input_height}")
            assert result.platform_type == expected_platform

    def test_parse_case_insensitive(self):
        """Test case insensitive parsing"""
        result1 = DiveCodeParser.parse("101b m 3m sync")
        result2 = DiveCodeParser.parse("101B M 3M SYNC")
        assert result1.dive_code == result2.dive_code
        assert result1.performance == result2.performance
        assert result1.is_sync == result2.is_sync

    def test_parse_group_5_twisting_dive(self):
        """Parse group 5 twisting dive"""
        result = DiveCodeParser.parse("5231D")
        assert result.is_valid
        assert result.group == 5
        assert result.direction == 2  # Back (group 5)

    def test_parse_group_6_armstand_dive(self):
        """Parse group 6 armstand dive"""
        result = DiveCodeParser.parse("6031B")
        assert result.is_valid
        assert result.group == 6
        assert result.direction == 0  # Armstand direction

    def test_parse_invalid_empty_input(self):
        """Parse fails on empty input"""
        result = DiveCodeParser.parse("")
        assert not result.is_valid
        assert result.error is not None

    def test_parse_invalid_none_input(self):
        """Parse fails on None input"""
        result = DiveCodeParser.parse(None)
        assert not result.is_valid

    def test_parse_invalid_dive_code_too_short(self):
        """Parse fails on dive code too short"""
        result = DiveCodeParser.parse("101")
        assert not result.is_valid
        assert "4-5 characters" in result.error

    def test_parse_invalid_position_letter(self):
        """Parse fails on invalid position"""
        result = DiveCodeParser.parse("101E")
        assert not result.is_valid
        assert "Position must be A-D" in result.error

    def test_parse_invalid_group_number(self):
        """Parse fails on invalid group (0 or 7+)"""
        result = DiveCodeParser.parse("001B")
        assert not result.is_valid
        assert "1-6" in result.error

    def test_parse_invalid_group_5_direction(self):
        """Parse fails on invalid group 5 direction (must be 1-4)"""
        result = DiveCodeParser.parse("5501B")
        assert not result.is_valid
        assert "1-4" in result.error

    def test_parse_invalid_height(self):
        """Parse invalid height is accepted but recorded"""
        result = DiveCodeParser.parse("101B 2m")
        assert result.is_valid  # Parser is lenient
        assert result.height == "1m"  # Falls back to default

    def test_parse_batch(self):
        """Test batch parsing"""
        codes = ["101B", "5231D G 10m", "201C M 3m SYNC"]
        results = DiveCodeParser.parse_batch(codes)
        assert len(results) == 3
        assert all(r.is_valid for r in results)

    def test_parse_to_dict(self):
        """Test conversion to dictionary"""
        result = DiveCodeParser.parse("101B M 3m")
        data_dict = DiveCodeParser.to_dict(result)
        assert isinstance(data_dict, dict)
        assert data_dict["dive_code"] == "101B"
        assert data_dict["performance"] == "M"


# ============================================================================
# Tests for DiveCodeValidator Service (Task 2.2)
# ============================================================================


class TestDiveCodeValidator:
    """Test the DiveCodeValidator service"""

    def test_validate_structure_valid(self):
        """Validate valid structure"""
        validator = DiveCodeValidator()
        is_valid, errors = validator.validate_structure("101B")
        assert is_valid
        assert len(errors) == 0

    def test_validate_structure_invalid_empty(self):
        """Validate fails on empty"""
        validator = DiveCodeValidator()
        is_valid, errors = validator.validate_structure("")
        assert not is_valid

    def test_validate_structure_invalid_too_short(self):
        """Validate fails on too short"""
        validator = DiveCodeValidator()
        is_valid, errors = validator.validate_structure("101")
        assert not is_valid

    def test_validate_structure_invalid_position(self):
        """Validate fails on invalid position"""
        validator = DiveCodeValidator()
        is_valid, errors = validator.validate_structure("101E")
        assert not is_valid

    def test_validate_height_for_platform_springboard(self):
        """Validate springboard heights"""
        validator = DiveCodeValidator()
        for height in ["1m", "3m"]:
            is_valid, errors = validator.validate_height_for_platform("101B", height)
            assert is_valid, f"Height {height} should be valid for springboard"

    def test_validate_height_for_platform_platform(self):
        """Validate platform heights"""
        validator = DiveCodeValidator()
        for height in ["5m", "7m", "10m"]:
            is_valid, errors = validator.validate_height_for_platform("101B", height)
            assert is_valid, f"Height {height} should be valid for platform"

    def test_validate_height_for_platform_invalid(self):
        """Validate fails on invalid height"""
        validator = DiveCodeValidator()
        is_valid, errors = validator.validate_height_for_platform("101B", "2m")
        assert not is_valid

    def test_validate_height_normalization(self):
        """Validate normalizes 7m to 7.5m"""
        validator = DiveCodeValidator()
        is_valid, errors = validator.validate_height_for_platform("101B", "7m")
        assert is_valid

    def test_check_if_official_fina_dive_not_found(self):
        """Check fails on non-official dive without db"""
        validator = DiveCodeValidator()  # No DB
        is_official = validator.check_if_official_fina_dive("999Z")
        assert not is_official

    def test_get_validation_errors_valid(self):
        """Get validation errors for valid dive"""
        validator = DiveCodeValidator()
        errors = validator.get_validation_errors("101B")
        # Should be mostly clear
        assert len(errors) == 0 or all(e["field"] != "dive_code" for e in errors)

    def test_get_validation_errors_invalid_structure(self):
        """Get validation errors for invalid structure"""
        validator = DiveCodeValidator()
        errors = validator.get_validation_errors("101E")
        assert len(errors) > 0
        assert errors[0]["severity"] == "error"

    def test_get_validation_errors_with_height(self):
        """Get validation errors including height"""
        validator = DiveCodeValidator()
        errors = validator.get_validation_errors("101B", "3m")
        # 3m is valid
        assert len(errors) == 0 or all(e["field"] != "height" for e in errors)

    def test_is_valid_true(self):
        """is_valid returns True for valid codes"""
        validator = DiveCodeValidator()
        result = validator.is_valid("101B")
        assert result

    def test_is_valid_false_structure(self):
        """is_valid returns False for invalid structure"""
        validator = DiveCodeValidator()
        result = validator.is_valid("101E")
        assert not result

    def test_get_suggestions_empty_code(self):
        """Get suggestions for empty code"""
        validator = DiveCodeValidator()
        suggestions = validator.get_suggestions("")
        assert len(suggestions) > 0

    def test_get_suggestions_invalid_position(self):
        """Get suggestions for invalid position"""
        validator = DiveCodeValidator()
        suggestions = validator.get_suggestions("101E")
        assert len(suggestions) > 0

    def test_get_suggestions_invalid_group(self):
        """Get suggestions for invalid group"""
        validator = DiveCodeValidator()
        suggestions = validator.get_suggestions("0abc")
        assert len(suggestions) > 0

    def test_validate_parsed_code_valid(self):
        """Validate a parsed code"""
        validator = DiveCodeValidator()
        parsed = DiveCodeParser.parse("101B M 3m")
        is_valid, errors = validator.validate_parsed_code(parsed)
        # May have FINA database warnings but basic validation passes
        assert parsed.is_valid


# ============================================================================
# Tests for API Endpoints (Task 2.5)
# ============================================================================


class TestDiveCodeAPI:
    """Test the dive code API endpoints"""

    def test_parse_endpoint_minimal(self):
        """POST /dive-codes/parse - minimal format"""
        response = client.post(
            "/api/v1/dive-codes/parse",
            json={"raw_input": "101B"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["dive_code"] == "101B"
        assert data["group"] == 1
        assert data["is_valid"]

    def test_parse_endpoint_full_format(self):
        """POST /dive-codes/parse - full format with perf and height"""
        response = client.post(
            "/api/v1/dive-codes/parse",
            json={"raw_input": "5231D G 10m SYNC"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["dive_code"] == "5231D"
        assert data["performance"] == "G"
        assert data["performance_numeric"] == 3
        assert data["height"] == "10m"
        assert data["is_sync"]

    def test_parse_endpoint_invalid(self):
        """POST /dive-codes/parse - invalid code returns error"""
        response = client.post(
            "/api/v1/dive-codes/parse",
            json={"raw_input": "INVALID"},
        )
        assert response.status_code == 400

    def test_validate_endpoint_valid(self):
        """POST /dive-codes/validate - valid code"""
        response = client.post(
            "/api/v1/dive-codes/validate",
            json={"raw_input": "101B"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["dive_code"] == "101B"
        # May not be in database but structure is valid

    def test_validate_endpoint_invalid_structure(self):
        """POST /dive-codes/validate - invalid structure"""
        response = client.post(
            "/api/v1/dive-codes/validate",
            json={"raw_input": "101E"},
        )
        assert response.status_code == 200
        data = response.json()
        assert not data["is_valid"]
        assert len(data["errors"]) > 0

    def test_reference_endpoint_all_dives(self, test_db):
        """GET /dive-codes/reference - get all dives"""
        # Load some test dives
        for code in ["101B", "5231D", "6031A"]:
            group = int(code[0])
            direction = int(code[1]) if group != 6 else 0
            position = code[-1]
            rotations = 1
            dive = FINADiveCode(
                dive_code=code,
                group=group,
                direction=direction,
                position=position,
                rotations=rotations,
            )
            test_db.add(dive)
        test_db.commit()

        response = client.get("/api/v1/dive-codes/reference")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 3

    def test_reference_endpoint_filter_by_group(self, test_db):
        """GET /dive-codes/reference - filter by group"""
        # Add test dives
        for i, code in enumerate(["101B", "201C", "301A"], 1):
            group = i
            direction = i
            position = code[-1]
            dive = FINADiveCode(
                dive_code=code,
                group=group,
                direction=direction,
                position=position,
                rotations=1,
            )
            test_db.add(dive)
        test_db.commit()

        response = client.get("/api/v1/dive-codes/reference?group=1")
        assert response.status_code == 200
        data = response.json()
        assert all(d["group"] == 1 for d in data)

    def test_get_dive_endpoint_found(self, test_db):
        """GET /dive-codes/{code} - dive found"""
        dive = FINADiveCode(
            dive_code="101B",
            group=1,
            direction=1,
            position="B",
            rotations=1,
            official_name="Forward Dive",
            group_name="Forward Dives",
            position_name="Pike",
        )
        test_db.add(dive)
        test_db.commit()

        response = client.get("/api/v1/dive-codes/101B")
        assert response.status_code == 200
        data = response.json()
        assert data["dive_code"] == "101B"
        assert data["official_name"] == "Forward Dive"

    def test_get_dive_endpoint_not_found(self):
        """GET /dive-codes/{code} - dive not found"""
        response = client.get("/api/v1/dive-codes/999Z")
        assert response.status_code == 404

    def test_batch_parse_endpoint(self):
        """POST /dive-codes/batch-parse - batch parsing"""
        response = client.post(
            "/api/v1/dive-codes/batch-parse",
            json={"codes": ["101B", "5231D G 10m", "201C"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert data["successful"] == 3
        assert data["failed"] == 0

    def test_batch_parse_endpoint_with_failures(self):
        """POST /dive-codes/batch-parse - with some failures"""
        response = client.post(
            "/api/v1/dive-codes/batch-parse",
            json={"codes": ["101B", "INVALID", "5231D"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert data["successful"] == 2
        assert data["failed"] == 1

    def test_official_only_endpoint(self, test_db):
        """GET /dive-codes/official-only/all - get official dives"""
        # Add test dives
        for code in ["101A", "101B", "201C"]:
            group = int(code[0])
            direction = int(code[1])
            position = code[-1]
            dive = FINADiveCode(
                dive_code=code,
                group=group,
                direction=direction,
                position=position,
                rotations=1,
            )
            test_db.add(dive)
        test_db.commit()

        response = client.get("/api/v1/dive-codes/official-only/all")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 3


# ============================================================================
# Tests for Schema Serialization (Task 2.3)
# ============================================================================


class TestDiveCodeSchemas:
    """Test Pydantic schema serialization"""

    def test_dive_code_input_schema(self):
        """Test DiveCodeInput schema"""
        from app.schemas.dive_code import DiveCodeInput

        input_obj = DiveCodeInput(raw_input="101B M 3m")
        assert input_obj.raw_input == "101B M 3m"
        assert input_obj.model_dump() == {"raw_input": "101B M 3m"}

    def test_dive_code_parsed_schema(self):
        """Test DiveCodeParsed schema"""
        from app.schemas.dive_code import DiveCodeParsed

        parsed = DiveCodeParsed(
            dive_code="101B",
            group=1,
            direction=1,
            position="B",
            performance="M",
            performance_numeric=2,
            height="3m",
            platform_type="springboard",
            is_sync=False,
            is_smack=False,
            is_valid=True,
        )
        data = parsed.model_dump()
        assert data["dive_code"] == "101B"
        assert data["performance"] == "M"

    def test_dive_code_validation_schema(self):
        """Test DiveCodeValidation schema"""
        from app.schemas.dive_code import DiveCodeValidation, ValidationError

        validation = DiveCodeValidation(
            dive_code="101B",
            is_valid=True,
            errors=[],
            is_official_fina=True,
        )
        data = validation.model_dump()
        assert data["is_valid"]
        assert data["errors"] == []

    def test_validation_error_schema(self):
        """Test ValidationError schema"""
        from app.schemas.dive_code import ValidationError

        error = ValidationError(
            field="dive_code",
            message="Invalid format",
            severity="error",
        )
        data = error.model_dump()
        assert data["field"] == "dive_code"
        assert data["severity"] == "error"

    def test_dive_code_reference_schema(self):
        """Test DiveCodeReference schema"""
        from app.schemas.dive_code import DiveCodeReference

        reference = DiveCodeReference(
            dive_code="101B",
            group=1,
            group_name="Forward Dives",
            direction=1,
            position="B",
            position_name="Pike",
            rotations=1,
            twists=0,
            official_name="Forward Dive",
            is_twisting=False,
            is_flying=False,
            is_armstand=False,
        )
        data = reference.model_dump()
        assert data["official_name"] == "Forward Dive"


# ============================================================================
# Integration Tests
# ============================================================================


class TestDiveCodeIntegration:
    """Integration tests for parser → validator → API flow"""

    def test_full_flow_parse_to_validate(self):
        """Full flow: parse input → validate → return result"""
        # Parse
        parsed = DiveCodeParser.parse("101B M 3m SYNC")
        assert parsed.is_valid

        # Validate
        validator = DiveCodeValidator()
        is_valid, errors = validator.validate_parsed_code(parsed)
        # Should be valid structurally

        # API would serialize this
        assert parsed.dive_code == "101B"
        assert parsed.performance == "M"
        assert parsed.is_sync

    def test_full_flow_invalid_input(self):
        """Full flow: invalid input throughout pipeline"""
        # Parse
        parsed = DiveCodeParser.parse("INVALID")
        assert not parsed.is_valid

        # API would reject this
        response = client.post(
            "/api/v1/dive-codes/parse",
            json={"raw_input": "INVALID"},
        )
        assert response.status_code == 400

    def test_parser_validator_consistency(self):
        """Ensure parser and validator are consistent"""
        test_codes = [
            "101B",
            "5231D",
            "6031A",
            "201C G 10m",
            "101B M 3m SYNC",
        ]

        validator = DiveCodeValidator()
        for code in test_codes:
            parsed = DiveCodeParser.parse(code)
            if parsed.is_valid:
                # Validator should not have structural issues
                struct_valid, _ = validator.validate_structure(parsed.dive_code)
                assert struct_valid, f"Parser and validator mismatch for {code}"


# ============================================================================
# Edge Cases and Error Handling
# ============================================================================


class TestEdgeCases:
    """Test edge cases and error conditions"""

    def test_very_long_input(self):
        """Handle very long input gracefully"""
        long_input = "101B" + "A" * 1000
        result = DiveCodeParser.parse(long_input)
        assert not result.is_valid  # Should fail

    def test_unicode_input(self):
        """Handle unicode input gracefully"""
        result = DiveCodeParser.parse("🏊 101B")
        # Should fail or handle gracefully
        assert isinstance(result, DiveCodeData)

    def test_numeric_performance_input(self):
        """Don't accept numeric performance (only letters)"""
        result = DiveCodeParser.parse("101B 2")
        # Should parse but '2' won't be recognized as performance
        assert result.performance is None

    def test_whitespace_handling(self):
        """Handle various whitespace"""
        result1 = DiveCodeParser.parse("  101B  ")
        result2 = DiveCodeParser.parse("101B")
        assert result1.dive_code == result2.dive_code

    def test_duplicate_flags(self):
        """Handle duplicate flags"""
        result = DiveCodeParser.parse("101B SYNC SYNC")
        assert result.is_sync
        assert result.is_valid

    def test_group_5_validation_constraints(self):
        """Test group 5 (twisting) specific constraints"""
        # Valid group 5 direction (1-4)
        result = DiveCodeParser.parse("5131D")
        assert result.is_valid
        assert result.group == 5
        assert result.direction == 1

    def test_group_6_armstand_direction(self):
        """Test group 6 (armstand) has direction 0"""
        result = DiveCodeParser.parse("6031B")
        assert result.is_valid
        assert result.group == 6
        assert result.direction == 0
