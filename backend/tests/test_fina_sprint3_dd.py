"""Sprint 3: DD Calculations Tests
Comprehensive tests for DD Calculator, Lookup Manager, and Auto-Assignment services.
"""

import pytest
from decimal import Decimal
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models import FINADiveCode, DDLookup
from app.services.dd_calculator import DDCalculator
from app.services.dd_lookup_manager import DDLookupManager
from app.services.dd_auto_assign import DDAutoAssigner


client = TestClient(app)


class TestDDCalculator:
    """Test the DD Calculator service"""

    @pytest.fixture
    def setup_test_data(self, test_db: Session):
        """Setup test FINA dives and DD values"""
        # Get existing test dive from seeded data
        dive = test_db.query(FINADiveCode).filter_by(dive_code="101B").first()
        if not dive:
            dive = FINADiveCode(
                dive_code="101B",
                group=1,
                direction=1,
                position="B",
                rotations=1,
                official_name="Forward Dive",
                group_name="Forward Dives",
            )
            test_db.add(dive)
            test_db.commit()

        # Create DD entries for different heights (if they don't exist)
        for height, dd_val in [("1m", 1.3), ("3m", 1.5), ("5m", 1.7)]:
            existing_dd = test_db.query(DDLookup).filter_by(
                dive_code="101B", height=height
            ).first()
            if not existing_dd:
                dd = DDLookup(
                    dive_code="101B",
                    height=height,
                    platform_type="springboard" if height in ["1m", "3m"] else "platform",
                    dd_value=Decimal(str(dd_val)),
                )
                test_db.add(dd)
        test_db.commit()

        return dive

    def test_lookup_dd_found(self, test_db: Session, setup_test_data):
        """Test looking up existing DD value"""
        calculator = DDCalculator(test_db)
        dd_value = calculator.lookup_dd("101B", "1m")

        assert dd_value is not None
        assert dd_value == Decimal("1.3")

    def test_lookup_dd_not_found(self, test_db: Session):
        """Test looking up non-existent DD value"""
        calculator = DDCalculator(test_db)
        dd_value = calculator.lookup_dd("999Z", "1m")

        assert dd_value is None

    def test_lookup_dd_height_normalization(self, test_db: Session, setup_test_data):
        """Test that 7m normalizes to 7.5m"""
        calculator = DDCalculator(test_db)

        # Add 7.5m entry
        dd = DDLookup(
            dive_code="101B",
            height="7.5m",
            platform_type="platform",
            dd_value=Decimal("2.0"),
        )
        test_db.add(dd)
        test_db.commit()

        # Lookup with 7m should find 7.5m
        dd_value = calculator.lookup_dd("101B", "7m")
        assert dd_value == Decimal("2.0")

    def test_lookup_dd_all_heights(self, test_db: Session, setup_test_data):
        """Test looking up DD for all heights"""
        calculator = DDCalculator(test_db)
        dd_values = calculator.lookup_dd_all_heights("101B")

        assert len(dd_values) == 3
        assert dd_values["1m"] == Decimal("1.3")
        assert dd_values["3m"] == Decimal("1.5")
        assert dd_values["5m"] == Decimal("1.7")

    def test_get_statistics(self, test_db: Session, setup_test_data):
        """Test getting DD statistics"""
        calculator = DDCalculator(test_db)
        stats = calculator.get_statistics("1m")

        assert stats["count"] >= 1
        assert float(stats["min"]) <= 1.3
        assert float(stats["max"]) >= 1.3

    def test_validate_dd_value_valid(self, test_db: Session):
        """Test DD validation with valid values"""
        calculator = DDCalculator(test_db)

        for dd in [1.2, 1.5, 2.0, 3.5, 4.1]:
            is_valid, error = calculator.validate_dd_value(Decimal(str(dd)))
            assert is_valid, f"DD {dd} should be valid"

    def test_validate_dd_value_invalid(self, test_db: Session):
        """Test DD validation with invalid values"""
        calculator = DDCalculator(test_db)

        invalid_values = [0.5, 5.5, 1.25]  # Out of range or invalid increment
        for dd in invalid_values:
            is_valid, error = calculator.validate_dd_value(Decimal(str(dd)))
            assert not is_valid, f"DD {dd} should be invalid"

    def test_estimate_dd_from_components(self, test_db: Session):
        """Test DD estimation from dive components"""
        calculator = DDCalculator(test_db)

        # Forward dive with 1 rotation
        estimated = calculator.estimate_dd_from_components(
            group=1,
            rotations=1,
            twists=0,
            is_flying=False,
        )
        assert estimated is not None
        assert estimated >= Decimal("1.2")

    def test_dd_cache(self, test_db: Session, setup_test_data):
        """Test that DD calculator caches results"""
        calculator = DDCalculator(test_db)

        # First lookup
        dd1 = calculator.lookup_dd("101B", "1m")
        assert dd1 == Decimal("1.3")

        # Check cache is populated
        assert "101B_1m" in calculator._dd_cache

        # Clear cache
        calculator.clear_cache()
        assert len(calculator._dd_cache) == 0


class TestDDLookupManager:
    """Test the DD Lookup Manager service"""

    @pytest.fixture
    def setup_fina_dive(self, test_db: Session):
        """Create test FINA dive"""
        dive = test_db.query(FINADiveCode).filter_by(dive_code="101B").first()
        if not dive:
            dive = FINADiveCode(
                dive_code="101B",
                group=1,
                direction=1,
                position="B",
                rotations=1,
            )
            test_db.add(dive)
            test_db.commit()
        return dive

    def test_add_dd_entry_new(self, test_db: Session, setup_fina_dive):
        """Test adding new DD entry"""
        manager = DDLookupManager(test_db)

        result = manager.add_dd_entry(
            dive_code="101B",
            height="1m",
            dd_value=Decimal("1.3"),
            platform_type="springboard",
        )

        assert result is not None
        assert result.dd_value == Decimal("1.3")

    def test_add_dd_entry_update(self, test_db: Session, setup_fina_dive):
        """Test updating existing DD entry"""
        manager = DDLookupManager(test_db)

        # Add initial
        manager.add_dd_entry("101B", "1m", Decimal("1.3"))

        # Update
        result = manager.add_dd_entry("101B", "1m", Decimal("1.4"))

        assert result.dd_value == Decimal("1.4")

    def test_add_dd_entry_invalid_dive(self, test_db: Session):
        """Test adding DD for non-existent dive"""
        manager = DDLookupManager(test_db)

        with pytest.raises(Exception):
            manager.add_dd_entry("999Z", "1m", Decimal("1.3"))

    def test_batch_add_dd_entries(self, test_db: Session, setup_fina_dive):
        """Test batch adding DD entries"""
        manager = DDLookupManager(test_db)

        entries = [
            {"dive_code": "101B", "height": "1m", "dd_value": 1.3},
            {"dive_code": "101B", "height": "3m", "dd_value": 1.5},
            {"dive_code": "101B", "height": "5m", "dd_value": 1.7},
        ]

        success, errors = manager.add_dd_batch(entries)

        assert success == 3
        assert len(errors) == 0

    def test_update_dd_value(self, test_db: Session, setup_fina_dive):
        """Test updating DD value"""
        manager = DDLookupManager(test_db)

        # Add entry first
        manager.add_dd_entry("101B", "1m", Decimal("1.3"))

        # Update
        result = manager.update_dd_value("101B", "1m", Decimal("1.4"))

        assert result is True

    def test_delete_dd_entry(self, test_db: Session, setup_fina_dive):
        """Test deleting DD entry"""
        manager = DDLookupManager(test_db)

        # Add then delete
        manager.add_dd_entry("101B", "1m", Decimal("1.3"))
        result = manager.delete_dd_entry("101B", "1m")

        assert result is True

    def test_get_dd_statistics(self, test_db: Session, setup_fina_dive):
        """Test getting DD table statistics"""
        manager = DDLookupManager(test_db)

        # Add some entries
        manager.add_dd_entry("101B", "1m", Decimal("1.3"))
        manager.add_dd_entry("101B", "3m", Decimal("1.5"))

        stats = manager.get_dd_statistics()

        assert stats["total_entries"] >= 2
        assert len(stats["heights"]) > 0

    def test_verify_completeness(self, test_db: Session, setup_fina_dive):
        """Test DD completeness verification"""
        manager = DDLookupManager(test_db)

        # Add one entry
        manager.add_dd_entry("101B", "1m", Decimal("1.3"))

        coverage = manager.verify_completeness()

        assert coverage["total_fina_dives"] >= 1
        assert coverage["dives_with_dd"] >= 1


class TestDDAutoAssigner:
    """Test the DD Auto-Assignment service"""

    def test_estimate_dd_for_dive_existing(self, test_db: Session):
        """Test estimating DD for existing dive"""
        # Get or create dive
        dive = test_db.query(FINADiveCode).filter_by(dive_code="101B").first()
        if not dive:
            dive = FINADiveCode(
                dive_code="101B",
                group=1,
                direction=1,
                position="B",
                rotations=1,
            )
            test_db.add(dive)
            test_db.commit()

        # Add DD entry if not exists
        existing_dd = test_db.query(DDLookup).filter_by(
            dive_code="101B", height="1m"
        ).first()
        if not existing_dd:
            dd = DDLookup(
                dive_code="101B",
                height="1m",
                platform_type="springboard",
                dd_value=Decimal("1.3"),
            )
            test_db.add(dd)
            test_db.commit()

        assigner = DDAutoAssigner(test_db)
        estimated = assigner.estimate_dd_for_dive("101B", "1m")

        assert estimated == Decimal("1.3")

    def test_estimate_dd_for_dive_missing(self, test_db: Session):
        """Test estimating DD for non-existent dive"""
        assigner = DDAutoAssigner(test_db)
        estimated = assigner.estimate_dd_for_dive("999Z", "1m")

        # Should return None or estimate
        assert estimated is None or isinstance(estimated, Decimal)


class TestDDAPIEndpoints:
    """Test DD API endpoints"""

    @pytest.fixture
    def setup_api_data(self, test_db: Session):
        """Setup data for API tests"""
        # Get or create dive
        dive = test_db.query(FINADiveCode).filter_by(dive_code="101B").first()
        if not dive:
            dive = FINADiveCode(
                dive_code="101B",
                group=1,
                direction=1,
                position="B",
                rotations=1,
                official_name="Forward Dive",
                group_name="Forward Dives",
            )
            test_db.add(dive)

        # Create DD entries if not exists
        for height, dd_val in [("1m", 1.3), ("3m", 1.5)]:
            existing_dd = test_db.query(DDLookup).filter_by(
                dive_code="101B", height=height
            ).first()
            if not existing_dd:
                dd = DDLookup(
                    dive_code="101B",
                    height=height,
                    platform_type="springboard",
                    dd_value=Decimal(str(dd_val)),
                )
                test_db.add(dd)

        test_db.commit()

    def test_lookup_endpoint(self, test_db, setup_api_data):
        """Test GET /dd/lookup/{dive_code}/{height}"""
        response = client.get("/api/v1/dd/lookup/101B/1m")

        assert response.status_code == 200
        data = response.json()
        assert data["dive_code"] == "101B"
        assert data["height"] == "1m"
        assert data["dd_value"] == 1.3

    def test_lookup_all_heights_endpoint(self, test_db, setup_api_data):
        """Test GET /dd/lookup-all/{dive_code}"""
        response = client.get("/api/v1/dd/lookup-all/101B")

        assert response.status_code == 200
        data = response.json()
        assert data["dive_code"] == "101B"
        assert "heights" in data

    def test_lookup_by_group_endpoint(self, test_db, setup_api_data):
        """Test GET /dd/by-group/{group}/{height}"""
        response = client.get("/api/v1/dd/by-group/1/1m")

        assert response.status_code == 200
        data = response.json()
        assert data["group"] == 1
        assert data["height"] == "1m"

    def test_statistics_endpoint(self, test_db, setup_api_data):
        """Test GET /dd/statistics/{height}"""
        response = client.get("/api/v1/dd/statistics/1m")

        assert response.status_code == 200
        data = response.json()
        assert "count" in data
        assert "min" in data or data["count"] == 0

    def test_get_all_dds_endpoint(self, test_db, setup_api_data):
        """Test GET /dd/all"""
        response = client.get("/api/v1/dd/all")

        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "entries" in data

    def test_add_dd_entry_endpoint(self, test_db, setup_api_data):
        """Test POST /dd/add-entry"""
        response = client.post(
            "/api/v1/dd/add-entry",
            json={
                "dive_code": "101B",
                "height": "5m",
                "dd_value": 1.7,
                "platform_type": "platform",
            },
        )

        # May fail if dive already exists, but should be valid request
        assert response.status_code in [200, 400]

    def test_coverage_endpoint(self, test_db, setup_api_data):
        """Test GET /dd/coverage"""
        response = client.get("/api/v1/dd/coverage")

        assert response.status_code == 200
        data = response.json()
        assert "total_fina_dives" in data
        assert "dives_with_dd" in data


class TestDDIntegration:
    """Integration tests for DD system"""

    def test_full_dd_lookup_flow(self, test_db: Session):
        """Test complete DD lookup flow"""
        # Get or create dive
        dive = test_db.query(FINADiveCode).filter_by(dive_code="101B").first()
        if not dive:
            dive = FINADiveCode(
                dive_code="101B",
                group=1,
                direction=1,
                position="B",
                rotations=1,
            )
            test_db.add(dive)

        # Add DD entry if not exists
        existing_dd = test_db.query(DDLookup).filter_by(
            dive_code="101B", height="1m"
        ).first()
        if not existing_dd:
            dd = DDLookup(
                dive_code="101B",
                height="1m",
                platform_type="springboard",
                dd_value=Decimal("1.3"),
            )
            test_db.add(dd)
        test_db.commit()

        # Use calculator
        calculator = DDCalculator(test_db)
        dd_value = calculator.lookup_dd("101B", "1m")

        assert dd_value == Decimal("1.3")

    def test_dd_height_normalization_flow(self, test_db: Session):
        """Test height normalization across services"""
        # Get or create dive
        dive = test_db.query(FINADiveCode).filter_by(dive_code="101B").first()
        if not dive:
            dive = FINADiveCode(
                dive_code="101B",
                group=1,
                direction=1,
                position="B",
                rotations=1,
            )
            test_db.add(dive)

        # Add 7.5m entry if not exists
        existing_dd = test_db.query(DDLookup).filter_by(
            dive_code="101B", height="7.5m"
        ).first()
        if not existing_dd:
            dd = DDLookup(
                dive_code="101B",
                height="7.5m",
                platform_type="platform",
                dd_value=Decimal("2.0"),
            )
            test_db.add(dd)
        test_db.commit()

        # Lookup with 7m should normalize
        calculator = DDCalculator(test_db)
        dd_value = calculator.lookup_dd("101B", "7m")

        assert dd_value == Decimal("2.0")

    def test_batch_operation_consistency(self, test_db: Session):
        """Test batch operations maintain consistency"""
        # Get or create dive
        dive = test_db.query(FINADiveCode).filter_by(dive_code="101B").first()
        if not dive:
            dive = FINADiveCode(
                dive_code="101B",
                group=1,
                direction=1,
                position="B",
                rotations=1,
            )
            test_db.add(dive)
            test_db.commit()

        manager = DDLookupManager(test_db)

        entries = [
            {"dive_code": "101B", "height": "1m", "dd_value": 1.3},
            {"dive_code": "101B", "height": "3m", "dd_value": 1.5},
        ]

        success, errors = manager.add_dd_batch(entries)
        # Some may exist, but should be successful or updated
        assert success >= 0

        # Verify all were added or updated
        calculator = DDCalculator(test_db)
        for entry in entries:
            dd = calculator.lookup_dd(entry["dive_code"], entry["height"])
            assert dd == Decimal(str(entry["dd_value"]))
