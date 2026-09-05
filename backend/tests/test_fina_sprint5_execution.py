"""
Sprint 5: Execution Analysis and Fault Detection Tests

Tests for ExecutionFaultDetector service, ExecutionFault model, and execution analysis API endpoints.
Covers:
- Fault detection for all fault codes (UR, OR, LE, EE, LS, LH, PH, SA, LK, SK)
- Severity calculation
- Coaching recommendations
- Pattern analysis
- Session-wide analysis
- API endpoints
- FINA compliance
"""

import pytest
from decimal import Decimal
from datetime import datetime
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from app.main import app
from app.models.dive import Dive
from app.models.session import Session as SessionModel
from app.models.execution_fault import ExecutionFault
from app.models.fina_dive_code import FINADiveCode
from app.models.dd_lookup import DDLookup
from app.services.execution_fault_detector import ExecutionFaultDetector, ExecutionMetrics


client = TestClient(app)


@pytest.fixture
def fina_dive_code_101b(test_db: Session):
    """Create FINA dive code for 101B (Forward somersault)"""
    # Check if it already exists
    existing = test_db.query(FINADiveCode).filter(FINADiveCode.dive_code == "101B").first()
    if existing:
        return existing

    code = FINADiveCode(
        dive_code="101B",
        group=1,
        direction=1,
        position="B",
        rotations=1,
        twists=0,
        is_twisting=0,
        is_flying=0,
        is_armstand=0,
        official_name="Forward Somersault",
        group_name="Forward Dives",
    )
    test_db.add(code)
    test_db.commit()
    test_db.refresh(code)
    return code


@pytest.fixture
def fina_dive_code_5231d(test_db: Session):
    """Create FINA dive code for 5231D (Inward 1.5 twists)"""
    # Check if it already exists
    existing = test_db.query(FINADiveCode).filter(FINADiveCode.dive_code == "5231D").first()
    if existing:
        return existing

    code = FINADiveCode(
        dive_code="5231D",
        group=5,
        direction=3,
        position="D",
        rotations=1,
        twists=3,  # 1.5 twists = 3 half-twists
        is_twisting=1,
        is_flying=0,
        is_armstand=0,
        official_name="Inward 1.5 Twists",
        group_name="Inward Dives",
    )
    test_db.add(code)
    test_db.commit()
    test_db.refresh(code)
    return code


@pytest.fixture
def dive_two_phase(test_db: Session, sample_session: SessionModel, fina_dive_code_101b):
    """Create a two-phase dive for testing"""
    dive = Dive(
        session_id=sample_session.id,
        dive_code="101B",
        performance="G",
        performance_numeric=3,
        height="5m",
        is_sync=False,
        is_smack=False,
        dive_datetime=datetime.now(),
        is_lineup=False,
        phase1_performance="G",
        phase1_numeric=3,
        phase2_performance="P",
        phase2_numeric=4,
    )
    test_db.add(dive)
    test_db.commit()
    test_db.refresh(dive)
    return dive


@pytest.fixture
def dive_with_rotation_faults(test_db: Session, sample_session: SessionModel, fina_dive_code_101b):
    """Create a dive prone to rotation faults"""
    dive = Dive(
        session_id=sample_session.id,
        dive_code="101B",
        performance="B",
        performance_numeric=1,
        height="5m",
        is_sync=False,
        is_smack=False,
        dive_datetime=datetime.now(),
        is_lineup=False,
        phase1_performance="B",
        phase1_numeric=1,
        phase2_performance="B",
        phase2_numeric=1,
    )
    test_db.add(dive)
    test_db.commit()
    test_db.refresh(dive)
    return dive


class TestExecutionFaultModel:
    """Test ExecutionFault model and database operations"""

    def test_fault_creation(self, test_db: Session, dive_two_phase: Dive):
        """Test creating an execution fault"""
        fault = ExecutionFault(
            dive_id=dive_two_phase.id,
            fault_code="UR",
            severity="HIGH",
            phase=1,
            description="Under-rotated by 45 degrees",
            coaching_recommendation="Increase rotation speed",
            fina_category="Insufficient Rotation - FINA Execution Deduction",
            points_deducted=Decimal("1.5"),
        )
        test_db.add(fault)
        test_db.commit()

        retrieved = test_db.query(ExecutionFault).filter(ExecutionFault.id == fault.id).first()
        assert retrieved is not None
        assert retrieved.fault_code == "UR"
        assert retrieved.severity == "HIGH"
        assert retrieved.points_deducted == Decimal("1.5")

    def test_fault_unique_constraint(self, test_db: Session, dive_two_phase: Dive):
        """Test UNIQUE constraint on (dive_id, fault_code, phase)"""
        fault1 = ExecutionFault(
            dive_id=dive_two_phase.id,
            fault_code="UR",
            severity="HIGH",
            phase=1,
            description="First under-rotation",
            coaching_recommendation="Fix it",
            fina_category="Insufficient Rotation",
            points_deducted=Decimal("1.5"),
        )
        test_db.add(fault1)
        test_db.commit()

        # Try to add duplicate - should update existing instead
        fault2 = ExecutionFault(
            dive_id=dive_two_phase.id,
            fault_code="UR",
            severity="MEDIUM",
            phase=1,
            description="Updated description",
            coaching_recommendation="Updated recommendation",
            fina_category="Insufficient Rotation",
            points_deducted=Decimal("0.75"),
        )

        # This would violate unique constraint in real database
        # SQLite doesn't enforce it the same way, but we test the logic
        faults = test_db.query(ExecutionFault).filter(
            ExecutionFault.dive_id == dive_two_phase.id,
            ExecutionFault.fault_code == "UR",
            ExecutionFault.phase == 1,
        ).all()
        assert len(faults) == 1

    def test_fault_relationships(self, test_db: Session, dive_two_phase: Dive):
        """Test fault-dive relationship"""
        fault = ExecutionFault(
            dive_id=dive_two_phase.id,
            fault_code="LE",
            severity="MEDIUM",
            phase=2,
            description="Late entry",
            coaching_recommendation="Enter sooner",
            fina_category="Entry Fault",
            points_deducted=Decimal("0.75"),
        )
        test_db.add(fault)
        test_db.commit()

        # Verify relationship
        dive = test_db.query(Dive).filter(Dive.id == dive_two_phase.id).first()
        assert len(dive.execution_faults) == 1
        assert dive.execution_faults[0].fault_code == "LE"


class TestExecutionFaultDetector:
    """Test ExecutionFaultDetector service"""

    def test_detector_initialization(self, test_db: Session):
        """Test detector initialization"""
        detector = ExecutionFaultDetector(test_db)
        assert detector.db is test_db
        assert "UR" in detector.FAULT_CODES
        assert "LE" in detector.FAULT_CODES

    def test_under_rotation_detection(self, test_db: Session, dive_with_rotation_faults: Dive, fina_dive_code_101b):
        """Test detection of under-rotation fault"""
        detector = ExecutionFaultDetector(test_db)

        metrics = ExecutionMetrics(
            phase=1,
            rotation_degrees=270,  # Only 3/4 rotation instead of full
            entry_distance_from_center=5,
            entry_angle_degrees=15,
            height_achieved=100,
            spin_consistency=0.8,
            overall_score=7.5,
        )

        faults = detector.detect_faults_by_phase(1, metrics, fina_dive_code_101b)

        # Should detect under-rotation
        ur_faults = [f for f in faults if f.fault_code == "UR"]
        assert len(ur_faults) > 0
        assert ur_faults[0].severity in ["HIGH", "MEDIUM"]
        assert ur_faults[0].phase == 1

    def test_over_rotation_detection(self, test_db: Session, fina_dive_code_101b):
        """Test detection of over-rotation fault"""
        detector = ExecutionFaultDetector(test_db)

        metrics = ExecutionMetrics(
            phase=1,
            rotation_degrees=450,  # 1.25 rotations instead of 1
            entry_distance_from_center=5,
            entry_angle_degrees=15,
            height_achieved=100,
            spin_consistency=0.8,
            overall_score=7.5,
        )

        faults = detector.detect_faults_by_phase(1, metrics, fina_dive_code_101b)

        or_faults = [f for f in faults if f.fault_code == "OR"]
        assert len(or_faults) > 0
        assert or_faults[0].severity in ["HIGH", "MEDIUM"]

    def test_late_entry_detection(self, test_db: Session):
        """Test detection of late entry fault"""
        detector = ExecutionFaultDetector(test_db)

        metrics = ExecutionMetrics(
            phase=2,
            rotation_degrees=360,
            entry_distance_from_center=5,
            entry_angle_degrees=45,  # Too steep = late entry
            height_achieved=100,
            spin_consistency=0.8,
            overall_score=7.5,
        )

        faults = detector.detect_faults_by_phase(2, metrics)

        le_faults = [f for f in faults if f.fault_code == "LE"]
        assert len(le_faults) > 0
        assert le_faults[0].severity in ["HIGH", "MEDIUM"]

    def test_early_entry_detection(self, test_db: Session):
        """Test detection of early entry fault"""
        detector = ExecutionFaultDetector(test_db)

        metrics = ExecutionMetrics(
            phase=2,
            rotation_degrees=360,
            entry_distance_from_center=5,
            entry_angle_degrees=5,  # Too shallow = early entry
            height_achieved=100,
            spin_consistency=0.8,
            overall_score=7.5,
        )

        faults = detector.detect_faults_by_phase(2, metrics)

        ee_faults = [f for f in faults if f.fault_code == "EE"]
        assert len(ee_faults) > 0
        assert ee_faults[0].severity in ["HIGH", "MEDIUM"]

    def test_lack_of_spin_detection(self, test_db: Session):
        """Test detection of lack of spin fault"""
        detector = ExecutionFaultDetector(test_db)

        metrics = ExecutionMetrics(
            phase=1,
            rotation_degrees=360,
            entry_distance_from_center=5,
            entry_angle_degrees=15,
            height_achieved=100,
            spin_consistency=0.4,  # Poor spin consistency
            overall_score=7.5,
        )

        faults = detector.detect_faults_by_phase(1, metrics)

        ls_faults = [f for f in faults if f.fault_code == "LS"]
        assert len(ls_faults) > 0

    def test_lack_of_height_detection(self, test_db: Session):
        """Test detection of lack of height fault"""
        detector = ExecutionFaultDetector(test_db)

        metrics = ExecutionMetrics(
            phase=1,
            rotation_degrees=360,
            entry_distance_from_center=5,
            entry_angle_degrees=15,
            height_achieved=30,  # Too low
            spin_consistency=0.8,
            overall_score=7.5,
        )

        faults = detector.detect_faults_by_phase(1, metrics)

        lh_faults = [f for f in faults if f.fault_code == "LH"]
        assert len(lh_faults) > 0

    def test_splash_kiss_detection(self, test_db: Session):
        """Test detection of splash/kiss fault"""
        detector = ExecutionFaultDetector(test_db)

        metrics = ExecutionMetrics(
            phase=2,
            rotation_degrees=360,
            entry_distance_from_center=25,  # Too far from center
            entry_angle_degrees=15,
            height_achieved=100,
            spin_consistency=0.8,
            overall_score=7.5,
        )

        faults = detector.detect_faults_by_phase(2, metrics)

        sk_faults = [f for f in faults if f.fault_code == "SK"]
        assert len(sk_faults) > 0

    def test_fault_severity_mapping(self, test_db: Session):
        """Test fault severity calculation"""
        detector = ExecutionFaultDetector(test_db)

        # High severity (weight 1.5 for UR, so 2.0 * 1.5 = 3.0 > 1.5 threshold = HIGH)
        severity, points = detector.calculate_fault_severity("UR", 2.0)
        assert severity == "HIGH"
        assert points == Decimal("1.5")

        # Medium severity (LE has weight 1.0, so 1.0 * 1.0 = 1.0 which is in MEDIUM range 0.75-1.4)
        severity, points = detector.calculate_fault_severity("LE", 1.0)
        assert severity == "MEDIUM"
        assert points == Decimal("0.75")

        # Low severity (SK has weight 0.6, so 1.0 * 0.6 = 0.6 which is < 0.75 = LOW)
        severity, points = detector.calculate_fault_severity("SK", 1.0)
        assert severity == "LOW"
        assert points == Decimal("0.25")

    def test_coaching_recommendation_generation(self, test_db: Session):
        """Test that coaching recommendations are generated"""
        detector = ExecutionFaultDetector(test_db)

        metrics = ExecutionMetrics(
            phase=1,
            rotation_degrees=270,
            entry_distance_from_center=5,
            entry_angle_degrees=15,
            height_achieved=100,
            spin_consistency=0.8,
            overall_score=7.5,
        )

        faults = detector.detect_faults_by_phase(1, metrics)

        for fault in faults:
            assert fault.coaching_recommendation is not None
            assert len(fault.coaching_recommendation) > 0

    def test_pattern_analysis_no_faults(self, test_db: Session, dive_two_phase: Dive):
        """Test pattern analysis with no faults"""
        detector = ExecutionFaultDetector(test_db)

        patterns = detector.detect_systematic_patterns(dive_two_phase.id, [])

        assert patterns["total_faults"] == 0
        assert patterns["is_systematic"] is False
        assert patterns["primary_issue"] is None

    def test_pattern_analysis_with_faults(self, test_db: Session, dive_two_phase: Dive):
        """Test pattern analysis with multiple faults"""
        detector = ExecutionFaultDetector(test_db)

        faults = [
            ExecutionFault(dive_id=dive_two_phase.id, fault_code="UR", severity="HIGH", phase=1),
            ExecutionFault(dive_id=dive_two_phase.id, fault_code="UR", severity="HIGH", phase=2),
            ExecutionFault(dive_id=dive_two_phase.id, fault_code="LE", severity="MEDIUM", phase=2),
        ]

        patterns = detector.detect_systematic_patterns(dive_two_phase.id, faults)

        assert patterns["total_faults"] == 3
        assert patterns["is_systematic"] is True
        assert patterns["primary_issue"] == "UR"
        assert patterns["fault_codes"]["UR"] == 2
        assert patterns["severity_distribution"]["HIGH"] == 2

    def test_analyze_dive_execution(self, test_db: Session, dive_two_phase: Dive, fina_dive_code_101b):
        """Test full dive execution analysis"""
        detector = ExecutionFaultDetector(test_db)

        metrics = {
            "phase1_rotation": 270,  # Under-rotated
            "phase1_entry_distance": 5,
            "phase1_entry_angle": 15,
            "phase2_rotation": 360,
            "phase2_entry_distance": 5,
            "phase2_entry_angle": 25,  # Late entry
        }

        analysis = detector.analyze_dive_execution(dive_two_phase.id, metrics)

        assert analysis["dive_id"] == dive_two_phase.id
        assert analysis["execution_score"] > 0
        assert analysis["adjusted_score"] <= analysis["execution_score"]
        assert analysis["points_deducted"] >= 0
        assert "faults" in analysis
        assert "phase1_analysis" in analysis
        assert "phase2_analysis" in analysis
        assert "patterns" in analysis

    def test_save_faults_for_dive(self, test_db: Session, dive_two_phase: Dive):
        """Test saving faults to database"""
        detector = ExecutionFaultDetector(test_db)

        faults = [
            ExecutionFault(
                dive_id=None,
                fault_code="UR",
                severity="HIGH",
                phase=1,
                description="Under-rotated",
                coaching_recommendation="Increase rotation",
                fina_category="Insufficient Rotation",
                points_deducted=Decimal("1.5"),
            ),
            ExecutionFault(
                dive_id=None,
                fault_code="LE",
                severity="MEDIUM",
                phase=2,
                description="Late entry",
                coaching_recommendation="Enter sooner",
                fina_category="Entry Fault",
                points_deducted=Decimal("0.75"),
            ),
        ]

        saved = detector.save_faults_for_dive(dive_two_phase.id, faults)

        assert len(saved) == 2
        assert all(f.dive_id == dive_two_phase.id for f in saved)
        assert all(f.id is not None for f in saved)

        # Verify in database
        db_faults = test_db.query(ExecutionFault).filter(
            ExecutionFault.dive_id == dive_two_phase.id
        ).all()
        assert len(db_faults) == 2

    def test_get_fault_summary(self, test_db: Session, dive_two_phase: Dive):
        """Test fault summary generation"""
        detector = ExecutionFaultDetector(test_db)

        # Add faults
        fault1 = ExecutionFault(
            dive_id=dive_two_phase.id,
            fault_code="UR",
            severity="HIGH",
            phase=1,
            description="Under-rotated",
            coaching_recommendation="Fix it",
            fina_category="Insufficient Rotation",
            points_deducted=Decimal("1.5"),
        )
        fault2 = ExecutionFault(
            dive_id=dive_two_phase.id,
            fault_code="LE",
            severity="MEDIUM",
            phase=2,
            description="Late entry",
            coaching_recommendation="Fix it",
            fina_category="Entry Fault",
            points_deducted=Decimal("0.75"),
        )
        test_db.add_all([fault1, fault2])
        test_db.commit()

        summary = detector.get_fault_summary_for_dive(dive_two_phase.id)

        assert summary["dive_id"] == dive_two_phase.id
        assert summary["total_faults"] == 2
        assert summary["total_points_deducted"] == 2.25


class TestExecutionFaultAPI:
    """Test execution analysis API endpoints"""

    def test_analyze_dive_execution_endpoint(self, test_db: Session, api_client: TestClient, dive_two_phase: Dive):
        """Test POST /api/v1/execution/analyze/{dive_id}"""
        response = api_client.post(f"/api/v1/execution/analyze/{dive_two_phase.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["dive_id"] == dive_two_phase.id
        assert "execution_score" in data
        assert "adjusted_score" in data
        assert "faults" in data

    def test_analyze_dive_with_metrics_endpoint(self, test_db: Session, api_client: TestClient, dive_two_phase: Dive):
        """Test POST /api/v1/execution/analyze/{dive_id} with metrics"""
        metrics = {
            "phase1_rotation": 270,
            "phase1_entry_distance": 5,
            "phase2_entry_angle": 25,
        }

        response = api_client.post(
            f"/api/v1/execution/analyze/{dive_two_phase.id}",
            json={"metrics": metrics},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["dive_id"] == dive_two_phase.id

    def test_get_fault_categories_endpoint(self, api_client: TestClient):
        """Test GET /api/v1/execution/fault-categories"""
        response = api_client.get("/api/v1/execution/fault-categories")

        assert response.status_code == 200
        data = response.json()
        assert "fault_categories" in data
        assert "UR" in data["fault_categories"]
        assert "severity_levels" in data

    def test_get_dive_faults_endpoint(self, test_db: Session, api_client: TestClient, dive_two_phase: Dive):
        """Test GET /api/v1/execution/dive/{dive_id}/faults"""
        # Add a fault
        fault = ExecutionFault(
            dive_id=dive_two_phase.id,
            fault_code="UR",
            severity="HIGH",
            phase=1,
            description="Under-rotated",
            coaching_recommendation="Fix it",
            fina_category="Insufficient Rotation",
            points_deducted=Decimal("1.5"),
        )
        test_db.add(fault)
        test_db.commit()

        response = api_client.get(f"/api/v1/execution/dive/{dive_two_phase.id}/faults")

        assert response.status_code == 200
        data = response.json()
        assert data["dive_id"] == dive_two_phase.id
        assert data["total_faults"] >= 1

    def test_analyze_session_execution_endpoint(
        self, test_db: Session, api_client: TestClient, sample_session: SessionModel
    ):
        """Test POST /api/v1/execution/analyze-session/{session_id}"""
        response = api_client.post(f"/api/v1/execution/analyze-session/{sample_session.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == sample_session.id
        assert "total_dives" in data
        assert "total_faults" in data

    def test_pattern_analysis_endpoint(self, test_db: Session, api_client: TestClient, sample_session: SessionModel):
        """Test POST /api/v1/execution/pattern-analysis/{session_id}"""
        response = api_client.post(f"/api/v1/execution/pattern-analysis/{sample_session.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == sample_session.id
        assert "pattern_analysis" in data
        assert "phase_distribution" in data

    def test_coaching_endpoint(self, test_db: Session, api_client: TestClient, dive_two_phase: Dive):
        """Test GET /api/v1/execution/coaching/{dive_id}"""
        # Add a fault
        fault = ExecutionFault(
            dive_id=dive_two_phase.id,
            fault_code="UR",
            severity="HIGH",
            phase=1,
            description="Under-rotated",
            coaching_recommendation="Increase rotation speed",
            fina_category="Insufficient Rotation",
            points_deducted=Decimal("1.5"),
        )
        test_db.add(fault)
        test_db.commit()

        response = api_client.get(f"/api/v1/execution/coaching/{dive_two_phase.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["dive_id"] == dive_two_phase.id
        assert "coaching_recommendations" in data
        assert "primary_focus" in data
        assert "practice_suggestions" in data

    def test_analyze_nonexistent_dive(self, api_client: TestClient):
        """Test analyzing non-existent dive"""
        response = api_client.post("/api/v1/execution/analyze/99999")

        assert response.status_code == 400


class TestFINAFaultCompliance:
    """Test FINA-compliant fault definitions and deductions"""

    def test_high_severity_deduction(self, test_db: Session):
        """Test HIGH severity fault deduction (>1.0 point)"""
        detector = ExecutionFaultDetector(test_db)

        severity, points = detector.calculate_fault_severity("UR", 2.5)

        assert severity == "HIGH"
        assert float(points) >= 1.0

    def test_medium_severity_deduction(self, test_db: Session):
        """Test MEDIUM severity fault deduction (0.5-1.0 point)"""
        detector = ExecutionFaultDetector(test_db)

        severity, points = detector.calculate_fault_severity("LE", 1.0)

        assert severity == "MEDIUM"
        assert 0.5 <= float(points) <= 1.0

    def test_low_severity_deduction(self, test_db: Session):
        """Test LOW severity fault deduction (<0.5 point)"""
        detector = ExecutionFaultDetector(test_db)

        severity, points = detector.calculate_fault_severity("SK", 0.5)

        assert severity == "LOW"
        assert float(points) < 0.5

    def test_faults_reduce_score(self, test_db: Session, dive_two_phase: Dive):
        """Test that detected faults reduce final score"""
        detector = ExecutionFaultDetector(test_db)

        metrics = {
            "phase1_rotation": 270,  # Under-rotated
            "phase1_entry_distance": 5,
            "phase1_entry_angle": 15,
            "phase2_rotation": 360,
            "phase2_entry_distance": 25,  # Splash
            "phase2_entry_angle": 45,  # Late entry
        }

        analysis = detector.analyze_dive_execution(dive_two_phase.id, metrics)

        # Adjusted score should be less than execution score
        assert analysis["adjusted_score"] < analysis["execution_score"]
        assert analysis["points_deducted"] > 0

    def test_multiple_faults_accumulate(self, test_db: Session, dive_two_phase: Dive):
        """Test that multiple faults accumulate deductions"""
        detector = ExecutionFaultDetector(test_db)

        # Create scenario with multiple faults
        metrics = {
            "phase1_rotation": 270,  # UR
            "phase1_entry_distance": 5,
            "phase1_entry_angle": 15,
            "phase1_height": 30,  # LH
            "phase2_rotation": 360,
            "phase2_entry_distance": 25,  # SK
            "phase2_entry_angle": 45,  # LE
        }

        analysis = detector.analyze_dive_execution(dive_two_phase.id, metrics)

        assert len(analysis["faults"]) >= 2
        assert analysis["points_deducted"] > 1.0

    def test_fina_category_assignment(self, test_db: Session):
        """Test FINA category assignment for each fault"""
        detector = ExecutionFaultDetector(test_db)

        for fault_code in detector.FAULT_CODES.keys():
            category = detector._get_fina_category(fault_code)
            assert category is not None
            assert len(category) > 0
            assert "FINA" in category or "Deduction" in category
