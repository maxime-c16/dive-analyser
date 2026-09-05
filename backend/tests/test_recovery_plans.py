"""Tests for mental block recovery plans."""

import pytest
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.models.journey import Journey
from app.models.emotional_state import RecoveryPlan
from app.services.journey_service import JourneyService


@pytest.fixture
def sample_journey(test_db: Session) -> Journey:
    """Create a sample journey for testing recovery plans."""
    journey = Journey(
        journey_code="recovery_test_journey",
        description="Test journey for recovery plans",
        total_dives=0,
        milestones_count=0,
        success_rate=0
    )
    test_db.add(journey)
    test_db.commit()
    test_db.refresh(journey)
    return journey


class TestRecoveryPlanGeneration:
    """Test mental block recovery plan generation."""

    def test_generate_recovery_plan_basic(self, test_db: Session, sample_journey: Journey):
        """Test basic recovery plan generation."""
        service = JourneyService()
        result = service.generate_mental_block_recovery_plan(
            db=test_db,
            journey_id=sample_journey.id,
            blocked_dives=["101B", "201C"]
        )

        assert result["success"] is True
        assert result["plan_id"] is not None
        assert result["blocked_dives"] == ["101B", "201C"]
        assert "phase_details" in result
        assert len(result["phase_details"]) == 3  # 3 phases

    def test_recovery_plan_phase_details(self, test_db: Session, sample_journey: Journey):
        """Test recovery plan includes detailed phase information."""
        service = JourneyService()
        result = service.generate_mental_block_recovery_plan(
            db=test_db,
            journey_id=sample_journey.id,
            blocked_dives=["301B"]
        )

        phases = result["phase_details"]

        # Check phase 1
        assert phases[0]["phase"] == 1
        assert phases[0]["name"] == "Confidence Rebuilding"
        assert phases[0]["duration_days"] == 14
        assert "activities" in phases[0]
        assert "success_criteria" in phases[0]

        # Check phase 2
        assert phases[1]["phase"] == 2
        assert phases[1]["name"] == "Psychological Preparation"
        assert phases[1]["duration_days"] == 14

        # Check phase 3
        assert phases[2]["phase"] == 3
        assert phases[2]["name"] == "Controlled Exposure"
        assert phases[2]["duration_days"] == 21

    def test_recovery_plan_daily_actions(self, test_db: Session, sample_journey: Journey):
        """Test recovery plan includes daily action recommendations."""
        service = JourneyService()
        result = service.generate_mental_block_recovery_plan(
            db=test_db,
            journey_id=sample_journey.id,
            blocked_dives=["401B"]
        )

        actions = result["daily_actions"]
        assert "phase_1" in actions
        assert "phase_2" in actions
        assert "phase_3" in actions
        assert len(actions["phase_1"]) > 0
        assert len(actions["phase_2"]) > 0
        assert len(actions["phase_3"]) > 0

    def test_recovery_plan_duration_calculation(self, test_db: Session, sample_journey: Journey):
        """Test total duration calculation."""
        service = JourneyService()
        result = service.generate_mental_block_recovery_plan(
            db=test_db,
            journey_id=sample_journey.id,
            blocked_dives=["501B"]
        )

        # 14 + 14 + 21 = 49 days
        assert result["total_duration"] == 49

    def test_recovery_plan_estimated_completion(self, test_db: Session, sample_journey: Journey):
        """Test estimated completion date is calculated."""
        service = JourneyService()
        before_time = datetime.utcnow()

        result = service.generate_mental_block_recovery_plan(
            db=test_db,
            journey_id=sample_journey.id,
            blocked_dives=["101B"]
        )

        # Parse estimated completion
        completion = datetime.fromisoformat(result["estimated_completion"])
        days_from_now = (completion - before_time).days

        # Should be 49 days from now
        assert 48 <= days_from_now <= 50

    def test_recovery_plan_invalid_journey(self, test_db: Session):
        """Test recovery plan generation with invalid journey."""
        service = JourneyService()
        result = service.generate_mental_block_recovery_plan(
            db=test_db,
            journey_id=99999,
            blocked_dives=["101B"]
        )

        assert result["success"] is False
        assert "error" in result

    def test_recovery_plan_fear_baseline(self, test_db: Session, sample_journey: Journey):
        """Test recovery plan captures fear baseline."""
        service = JourneyService()
        result = service.generate_mental_block_recovery_plan(
            db=test_db,
            journey_id=sample_journey.id,
            blocked_dives=["201B"]
        )

        assert "fear_baseline" in result
        assert "average_fear_coefficient" in result["fear_baseline"]
        assert "interpretation" in result["fear_baseline"]


class TestRecoveryPlanPhaseTracking:
    """Test recovery plan phase progression and tracking."""

    def test_update_plan_to_phase_2(self, test_db: Session, sample_journey: Journey):
        """Test progressing recovery plan to phase 2."""
        service = JourneyService()

        # Create plan
        create_result = service.generate_mental_block_recovery_plan(
            db=test_db,
            journey_id=sample_journey.id,
            blocked_dives=["101B"]
        )
        plan_id = create_result["plan_id"]

        # Move to phase 2
        update_result = service.update_recovery_plan_phase(
            db=test_db,
            plan_id=plan_id,
            current_phase=2,
            completion_percentage=50
        )

        assert update_result["success"] is True
        assert update_result["current_phase"] == 2
        assert update_result["completion_percentage"] == 50

    def test_update_plan_to_phase_3(self, test_db: Session, sample_journey: Journey):
        """Test progressing recovery plan to phase 3."""
        service = JourneyService()

        # Create plan
        create_result = service.generate_mental_block_recovery_plan(
            db=test_db,
            journey_id=sample_journey.id,
            blocked_dives=["301B"]
        )
        plan_id = create_result["plan_id"]

        # Move to phase 3
        update_result = service.update_recovery_plan_phase(
            db=test_db,
            plan_id=plan_id,
            current_phase=3,
            completion_percentage=75
        )

        assert update_result["current_phase"] == 3
        assert update_result["completion_percentage"] == 75

    def test_complete_recovery_plan(self, test_db: Session, sample_journey: Journey):
        """Test completing a recovery plan."""
        service = JourneyService()

        # Create plan
        create_result = service.generate_mental_block_recovery_plan(
            db=test_db,
            journey_id=sample_journey.id,
            blocked_dives=["401B"]
        )
        plan_id = create_result["plan_id"]

        # Complete plan
        update_result = service.update_recovery_plan_phase(
            db=test_db,
            plan_id=plan_id,
            current_phase=0,  # 0 means completed
            completion_percentage=100
        )

        assert update_result["success"] is True
        assert update_result["current_phase"] == 0
        assert update_result["status"] == "completed"
        assert update_result["completion_percentage"] == 100

    def test_plan_phase_timestamps(self, test_db: Session, sample_journey: Journey):
        """Test that plan tracks phase start/end times."""
        service = JourneyService()

        # Create plan
        create_result = service.generate_mental_block_recovery_plan(
            db=test_db,
            journey_id=sample_journey.id,
            blocked_dives=["501B"]
        )
        plan_id = create_result["plan_id"]

        # Start phase 1
        service.update_recovery_plan_phase(test_db, plan_id, 1)

        # Move to phase 2
        service.update_recovery_plan_phase(test_db, plan_id, 2)

        # Verify in database
        from app.models.emotional_state import RecoveryPlan
        from sqlalchemy import select

        plan = test_db.execute(select(RecoveryPlan).where(RecoveryPlan.id == plan_id)).scalar_one()

        assert plan.phase1_started_at is not None
        assert plan.phase1_completed_at is not None
        assert plan.phase2_started_at is not None

    def test_plan_completion_percentage_bounds(self, test_db: Session, sample_journey: Journey):
        """Test completion percentage stays within 0-100 bounds."""
        service = JourneyService()

        create_result = service.generate_mental_block_recovery_plan(
            db=test_db,
            journey_id=sample_journey.id,
            blocked_dives=["101B"]
        )
        plan_id = create_result["plan_id"]

        # Try to set > 100
        result = service.update_recovery_plan_phase(
            db=test_db,
            plan_id=plan_id,
            current_phase=1,
            completion_percentage=150
        )

        # Should be capped at 100
        assert result["completion_percentage"] <= 100

        # Try to set < 0
        result = service.update_recovery_plan_phase(
            db=test_db,
            plan_id=plan_id,
            current_phase=1,
            completion_percentage=-50
        )

        # Should be at least 0
        assert result["completion_percentage"] >= 0


class TestGetMentalBlocks:
    """Test retrieving mental block analysis."""

    def test_get_mental_blocks_analysis(self, test_db: Session, sample_journey: Journey):
        """Test retrieving mental block analysis for a journey."""
        service = JourneyService()
        result = service.get_mental_blocks(test_db, sample_journey.id)

        assert result["journey_id"] == sample_journey.id
        assert "plateau_analysis" in result
        assert "emotional_triggers" in result
        assert "confidence_trends" in result
        assert "active_recovery_plans" in result

    def test_mental_blocks_with_active_plans(self, test_db: Session, sample_journey: Journey):
        """Test mental block analysis includes active recovery plans."""
        service = JourneyService()

        # Create a recovery plan
        service.generate_mental_block_recovery_plan(
            db=test_db,
            journey_id=sample_journey.id,
            blocked_dives=["201B", "301B"]
        )

        # Get analysis
        result = service.get_mental_blocks(test_db, sample_journey.id)

        # Should list the active plan
        assert len(result["active_recovery_plans"]) > 0
        plan_info = result["active_recovery_plans"][0]
        assert "201B" in plan_info["blocked_dives"]
        assert plan_info["status"] == "active"

    def test_mental_blocks_invalid_journey(self, test_db: Session):
        """Test mental block analysis with invalid journey."""
        service = JourneyService()
        result = service.get_mental_blocks(test_db, 99999)

        # Should still return analysis results with empty data
        assert "journey_id" in result
        assert "plateau_analysis" in result
        assert "emotional_triggers" in result
        assert "confidence_trends" in result


class TestMultipleDiveRecoveryPlan:
    """Test recovery plans targeting multiple dives."""

    def test_recovery_plan_multiple_blocked_dives(self, test_db: Session, sample_journey: Journey):
        """Test recovery plan with multiple blocked dives."""
        service = JourneyService()
        blocked = ["101B", "201C", "301B", "401B", "5231D"]

        result = service.generate_mental_block_recovery_plan(
            db=test_db,
            journey_id=sample_journey.id,
            blocked_dives=blocked
        )

        assert result["blocked_dives"] == blocked
        assert len(result["blocked_dives"]) == 5

    def test_recovery_plan_single_dive(self, test_db: Session, sample_journey: Journey):
        """Test recovery plan with single blocked dive."""
        service = JourneyService()

        result = service.generate_mental_block_recovery_plan(
            db=test_db,
            journey_id=sample_journey.id,
            blocked_dives=["101B"]
        )

        assert result["blocked_dives"] == ["101B"]

    def test_recovery_plan_fear_coefficient_averaging(self, test_db: Session, sample_journey: Journey):
        """Test recovery plan averages fear coefficient across dives."""
        service = JourneyService()

        result = service.generate_mental_block_recovery_plan(
            db=test_db,
            journey_id=sample_journey.id,
            blocked_dives=["101B", "201C", "301B"]
        )

        # Should have fear baseline
        assert "fear_baseline" in result
        baseline = result["fear_baseline"]
        assert "average_fear_coefficient" in baseline
        assert 0 <= baseline["average_fear_coefficient"] <= 3.0


class TestRecoveryPlanProgressTracking:
    """Test progress tracking for recovery plans."""

    def test_plan_daily_actions_by_phase(self, test_db: Session, sample_journey: Journey):
        """Test plan includes daily actions for each phase."""
        service = JourneyService()
        result = service.generate_mental_block_recovery_plan(
            db=test_db,
            journey_id=sample_journey.id,
            blocked_dives=["101B"]
        )

        actions = result["daily_actions"]

        # Phase 1: Confidence rebuilding
        phase1_actions = actions["phase_1"]
        assert any("lineup" in action.lower() for action in phase1_actions)
        assert any("video" in action.lower() for action in phase1_actions)

        # Phase 2: Psychological prep
        phase2_actions = actions["phase_2"]
        assert any("visualization" in action.lower() for action in phase2_actions)
        assert any("breathing" in action.lower() or "grounding" in action.lower()
                   for action in phase2_actions)

        # Phase 3: Controlled exposure
        phase3_actions = actions["phase_3"]
        assert any("training" in action.lower() or "warm" in action.lower() or "focus" in action.lower()
                   for action in phase3_actions)

    def test_phase_success_criteria(self, test_db: Session, sample_journey: Journey):
        """Test each phase has defined success criteria."""
        service = JourneyService()
        result = service.generate_mental_block_recovery_plan(
            db=test_db,
            journey_id=sample_journey.id,
            blocked_dives=["201B"]
        )

        for phase in result["phase_details"]:
            assert "success_criteria" in phase
            criteria = phase["success_criteria"]

            if phase["phase"] == 1:
                assert "success_rate" in criteria
                assert ">70%" in criteria["success_rate"]
            elif phase["phase"] == 2:
                assert "confidence_rating" in criteria
                assert ">=" in criteria["confidence_rating"]
            elif phase["phase"] == 3:
                assert "success_rate" in criteria
                assert ">=" in criteria["success_rate"]
