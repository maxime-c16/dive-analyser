"""Tests for emotional state capture and tracking."""

import pytest
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.models.dive import Dive
from app.models.session import Session as SessionModel
from app.models.emotional_state import EmotionalState, RecoveryPlan
from app.models.journey import Journey
from tests.fixtures import seed_test_database, clear_test_database


@pytest.fixture
def sample_dive_emotion(test_db: Session) -> Dive:
    """Create a sample dive for testing emotional states."""
    # Create session
    session = SessionModel(
        date=datetime.now().date(),
        location="Test Pool",
        notes="Test session",
        total_dives=1,
        total_personal_dives=1,
        avg_performance=3.0,
        success_rate=0.75
    )
    test_db.add(session)
    test_db.commit()
    test_db.refresh(session)

    # Create dive
    dive = Dive(
        session_id=session.id,
        dive_code="101B",
        performance="G",
        performance_numeric=3,
        height="5m",
        is_sync=False,
        is_smack=False,
        dive_datetime=datetime.now()
    )
    test_db.add(dive)
    test_db.commit()
    test_db.refresh(dive)

    return dive


class TestEmotionalStateCapture:
    """Test emotional state logging and capture."""

    def test_create_emotional_state(self, test_db: Session, sample_dive_emotion: Dive):
        """Test creating an emotional state record."""
        emotional = EmotionalState(
            dive_id=sample_dive_emotion.id,
            pre_dive_emotion="confident",
            post_dive_emotion="satisfied",
            confidence_rating=4
        )
        test_db.add(emotional)
        test_db.commit()
        test_db.refresh(emotional)

        assert emotional.id is not None
        assert emotional.dive_id == sample_dive_emotion.id
        assert emotional.pre_dive_emotion == "confident"
        assert emotional.post_dive_emotion == "satisfied"
        assert emotional.confidence_rating == 4

    def test_emotional_state_with_notes(self, test_db: Session, sample_dive_emotion: Dive):
        """Test emotional state with optional notes."""
        emotional = EmotionalState(
            dive_id=sample_dive_emotion.id,
            pre_dive_emotion="nervous",
            confidence_rating=2,
            emotional_notes="Struggled with board movement, but landed entry well"
        )
        test_db.add(emotional)
        test_db.commit()
        test_db.refresh(emotional)

        assert emotional.emotional_notes == "Struggled with board movement, but landed entry well"

    def test_update_emotional_state(self, test_db: Session, sample_dive_emotion: Dive):
        """Test updating an existing emotional state."""
        emotional = EmotionalState(
            dive_id=sample_dive_emotion.id,
            pre_dive_emotion="nervous",
            confidence_rating=2
        )
        test_db.add(emotional)
        test_db.commit()
        test_db.refresh(emotional)

        # Update
        emotional.post_dive_emotion = "frustrated"
        emotional.confidence_rating = 1
        test_db.add(emotional)
        test_db.commit()
        test_db.refresh(emotional)

        assert emotional.post_dive_emotion == "frustrated"
        assert emotional.confidence_rating == 1

    def test_emotional_state_timestamps(self, test_db: Session, sample_dive_emotion: Dive):
        """Test that emotional states record creation and update times."""
        emotional = EmotionalState(
            dive_id=sample_dive_emotion.id,
            pre_dive_emotion="excited",
            confidence_rating=5
        )
        test_db.add(emotional)
        test_db.commit()
        test_db.refresh(emotional)

        before_update = datetime.utcnow()
        emotional.post_dive_emotion = "proud"
        test_db.add(emotional)
        test_db.commit()
        test_db.refresh(emotional)
        after_update = datetime.utcnow()

        assert emotional.recorded_at is not None
        assert emotional.updated_at is not None

    def test_confidence_rating_validation(self, test_db: Session, sample_dive_emotion: Dive):
        """Test confidence rating constraints (1-5)."""
        # Valid rating
        emotional = EmotionalState(
            dive_id=sample_dive_emotion.id,
            confidence_rating=3
        )
        test_db.add(emotional)
        test_db.commit()

        # Retrieve and verify
        retrieved = test_db.query(EmotionalState).filter_by(dive_id=sample_dive_emotion.id).first()
        assert retrieved.confidence_rating == 3

    def test_null_emotions_allowed(self, test_db: Session, sample_dive_emotion: Dive):
        """Test that emotional states can be partial (only pre or post)."""
        emotional = EmotionalState(
            dive_id=sample_dive_emotion.id,
            pre_dive_emotion="anxious"
            # post_dive_emotion is NULL
        )
        test_db.add(emotional)
        test_db.commit()
        test_db.refresh(emotional)

        assert emotional.pre_dive_emotion == "anxious"
        assert emotional.post_dive_emotion is None


class TestRecoveryPlan:
    """Test mental block recovery plan creation and tracking."""

    @pytest.fixture
    def sample_journey(self, test_db: Session) -> Journey:
        """Create a sample journey for testing."""
        journey = Journey(
            journey_code="test_journey",
            description="Test journey for recovery plan",
            total_dives=0,
            milestones_count=0,
            success_rate=0
        )
        test_db.add(journey)
        test_db.commit()
        test_db.refresh(journey)
        return journey

    def test_create_recovery_plan(self, test_db: Session, sample_journey: Journey):
        """Test creating a recovery plan."""
        plan = RecoveryPlan(
            journey_id=sample_journey.id,
            blocked_dive_codes="101B,201C",
            status="active",
            phase1_goal="Rebuild confidence at lower heights",
            phase2_goal="Psychological preparation and visualization",
            phase3_goal="Controlled exposure at target height",
            reason="Athlete avoiding 101B after heavy smack"
        )
        test_db.add(plan)
        test_db.commit()
        test_db.refresh(plan)

        assert plan.id is not None
        assert plan.journey_id == sample_journey.id
        assert plan.blocked_dive_codes == "101B,201C"
        assert plan.status == "active"
        assert plan.current_phase == 1
        assert plan.completion_percentage == 0

    def test_recovery_plan_phase_progression(self, test_db: Session, sample_journey: Journey):
        """Test tracking phase progression through recovery plan."""
        plan = RecoveryPlan(
            journey_id=sample_journey.id,
            blocked_dive_codes="301B",
            status="active",
            phase1_goal="Test goal 1",
            phase2_goal="Test goal 2",
            phase3_goal="Test goal 3",
            reason="Test recovery"
        )
        test_db.add(plan)
        test_db.commit()
        test_db.refresh(plan)

        # Simulate phase 1 progress
        plan.current_phase = 1
        plan.phase1_started_at = datetime.utcnow()
        plan.completion_percentage = 25
        test_db.add(plan)
        test_db.commit()
        test_db.refresh(plan)

        assert plan.current_phase == 1
        assert plan.phase1_started_at is not None
        assert plan.completion_percentage == 25

        # Progress to phase 2
        plan.phase1_completed_at = datetime.utcnow()
        plan.phase2_started_at = datetime.utcnow()
        plan.current_phase = 2
        plan.completion_percentage = 50
        test_db.add(plan)
        test_db.commit()
        test_db.refresh(plan)

        assert plan.current_phase == 2
        assert plan.phase2_started_at is not None
        assert plan.completion_percentage == 50

        # Complete plan
        plan.phase3_completed_at = datetime.utcnow()
        plan.current_phase = 0  # Completed
        plan.status = "completed"
        plan.completed_at = datetime.utcnow()
        plan.completion_percentage = 100
        test_db.add(plan)
        test_db.commit()
        test_db.refresh(plan)

        assert plan.current_phase == 0
        assert plan.status == "completed"
        assert plan.completion_percentage == 100

    def test_recovery_plan_durations(self, test_db: Session, sample_journey: Journey):
        """Test recovery plan phase durations."""
        plan = RecoveryPlan(
            journey_id=sample_journey.id,
            blocked_dive_codes="401B",
            status="active",
            phase1_goal="Goal 1",
            phase2_goal="Goal 2",
            phase3_goal="Goal 3",
            phase1_duration=14,
            phase2_duration=14,
            phase3_duration=21,
            reason="Test durations"
        )
        test_db.add(plan)
        test_db.commit()
        test_db.refresh(plan)

        assert plan.phase1_duration == 14
        assert plan.phase2_duration == 14
        assert plan.phase3_duration == 21
        # Total should be 49 days
        total = plan.phase1_duration + plan.phase2_duration + plan.phase3_duration
        assert total == 49

    def test_recovery_plan_fear_coefficient_baseline(self, test_db: Session, sample_journey: Journey):
        """Test storing fear coefficient baseline in recovery plan."""
        plan = RecoveryPlan(
            journey_id=sample_journey.id,
            blocked_dive_codes="501B",
            status="active",
            phase1_goal="Goal 1",
            phase2_goal="Goal 2",
            phase3_goal="Goal 3",
            initial_fear_coefficient=180,  # 1.8 stored as 180
            reason="High fear coefficient"
        )
        test_db.add(plan)
        test_db.commit()
        test_db.refresh(plan)

        assert plan.initial_fear_coefficient == 180
        # Convert back to decimal: 180/100 = 1.8
        fear_coeff = plan.initial_fear_coefficient / 100
        assert fear_coeff == 1.8

    def test_recovery_plan_status_values(self, test_db: Session, sample_journey: Journey):
        """Test all valid recovery plan status values."""
        statuses = ["active", "in_progress", "completed", "abandoned"]

        for status in statuses:
            plan = RecoveryPlan(
                journey_id=sample_journey.id,
                blocked_dive_codes="101B",
                status=status,
                phase1_goal="Goal",
                phase2_goal="Goal",
                phase3_goal="Goal",
                reason=f"Test status {status}"
            )
            test_db.add(plan)

        test_db.commit()

        # Verify all were created
        plans = test_db.query(RecoveryPlan).filter_by(journey_id=sample_journey.id).all()
        stored_statuses = {p.status for p in plans}
        assert stored_statuses == set(statuses)

    def test_recovery_plan_multiple_dives(self, test_db: Session, sample_journey: Journey):
        """Test recovery plan with multiple blocked dives."""
        dive_codes = "101B,201C,301B,401B,5231D"
        plan = RecoveryPlan(
            journey_id=sample_journey.id,
            blocked_dive_codes=dive_codes,
            status="active",
            phase1_goal="Goal 1",
            phase2_goal="Goal 2",
            phase3_goal="Goal 3",
            reason="Multiple dive block"
        )
        test_db.add(plan)
        test_db.commit()
        test_db.refresh(plan)

        retrieved_codes = plan.blocked_dive_codes.split(",")
        assert len(retrieved_codes) == 5
        assert "301B" in retrieved_codes
        assert "5231D" in retrieved_codes


class TestEmotionalStateIntegration:
    """Integration tests for emotional states and dives."""

    def test_emotional_states_per_dive(self, test_db: Session):
        """Test multiple emotional states across different dives."""
        # Create session and dives
        session = SessionModel(
            date=datetime.now().date(),
            location="Test Pool",
            notes="Test session",
            total_dives=3,
            total_personal_dives=3,
            avg_performance=3.0,
            success_rate=0.75
        )
        test_db.add(session)
        test_db.commit()
        test_db.refresh(session)

        dives = []
        for i in range(3):
            dive = Dive(
                session_id=session.id,
                dive_code=f"10{i+1}B",
                performance="G",
                performance_numeric=3,
                height="5m",
                dive_datetime=datetime.now() + timedelta(hours=i)
            )
            dives.append(dive)
            test_db.add(dive)

        test_db.commit()

        # Create emotional states for each dive with different emotions
        emotions_data = [
            ("confident", "satisfied", 5),
            ("nervous", "proud", 3),
            ("excited", "frustrated", 2),
        ]

        for dive, (pre, post, conf) in zip(dives, emotions_data):
            emotional = EmotionalState(
                dive_id=dive.id,
                pre_dive_emotion=pre,
                post_dive_emotion=post,
                confidence_rating=conf
            )
            test_db.add(emotional)

        test_db.commit()

        # Query and verify
        all_emotional = test_db.query(EmotionalState).all()
        assert len(all_emotional) == 3

        # Verify each dive has exactly one emotional state
        for dive in dives:
            states = test_db.query(EmotionalState).filter_by(dive_id=dive.id).all()
            assert len(states) == 1

    def test_emotional_patterns_across_dives(self, test_db: Session):
        """Test analyzing emotional patterns across multiple dives."""
        # Create multiple dives with emotional tracking
        session = SessionModel(
            date=datetime.now().date(),
            location="Test Pool",
            notes="Test session",
            total_dives=5,
            total_personal_dives=5,
            avg_performance=2.5,
            success_rate=0.5
        )
        test_db.add(session)
        test_db.commit()
        test_db.refresh(session)

        dives = []
        for i in range(5):
            dive = Dive(
                session_id=session.id,
                dive_code="101B",
                performance="M" if i % 2 == 0 else "P",
                performance_numeric=2 if i % 2 == 0 else 4,
                height="5m",
                dive_datetime=datetime.now() + timedelta(hours=i)
            )
            dives.append(dive)
            test_db.add(dive)

        test_db.commit()

        # Add emotional states (fear pattern)
        for i, dive in enumerate(dives):
            emotional = EmotionalState(
                dive_id=dive.id,
                pre_dive_emotion="fearful" if i < 3 else "confident",
                post_dive_emotion="relieved" if i < 3 else "proud",
                confidence_rating=2 if i < 3 else 4
            )
            test_db.add(emotional)

        test_db.commit()

        # Query fearful emotions
        fearful_states = test_db.query(EmotionalState).filter_by(
            pre_dive_emotion="fearful"
        ).all()
        assert len(fearful_states) == 3

        # Check that fear emotions preceded some successes
        for state in fearful_states:
            dive = test_db.query(Dive).get(state.dive_id)
            assert dive is not None  # Fear didn't prevent all attempts
