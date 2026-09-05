"""Tests for Sprint 4: Performance Scoring System (FINA Compliance)"""

import pytest
from decimal import Decimal
from sqlalchemy.orm import Session

from app.models.dive import Dive
from app.models.session import Session as SessionModel
from app.models.dd_lookup import DDLookup
from app.models.fina_dive_code import FINADiveCode
from app.services.performance_scorer import PerformanceScorer, JudgeRating
from app.database import Base, SessionLocal


@pytest.fixture
def db():
    """Create test database"""
    engine = SessionLocal().get_bind()
    Base.metadata.create_all(engine)
    db = SessionLocal()
    yield db
    db.close()
    Base.metadata.drop_all(engine)


@pytest.fixture
def setup_test_data(db: Session):
    """Set up test dives, dive codes, and DD lookups"""
    # Create FINA dive code (Group 1 = Forward, direction=1, 1 somersault, Tuck position)
    fina_code = FINADiveCode(
        dive_code="101B",
        group=1,
        direction=1,
        has_flying=0,
        rotations=1,  # 1 somersault = 2 half rotations, but rotations field is actually full rotations
        twists=0,
        position="B"  # B = Pike position (not Tuck)
    )
    db.add(fina_code)

    # Create session
    session = SessionModel()
    db.add(session)
    db.flush()

    # Create dive
    dive = Dive(
        session_id=session.id,
        dive_code="101B",
        position="B",
        direction=1,
        performance="G",
        performance_numeric=3,
        height="1m",
        platform_type="springboard",
        dive_datetime=db.query(SessionModel).first().created_at
    )
    db.add(dive)
    db.flush()

    # Create DD lookup
    dd_lookup = DDLookup(
        dive_code="101B",
        height="1m",
        dd_value=Decimal("1.3")
    )
    db.add(dd_lookup)
    db.commit()

    return {
        "dive": dive,
        "session": session,
        "fina_code": fina_code,
        "dd_lookup": dd_lookup
    }


class TestJudgeScoreValidation:
    """Test judge score validation per FINA rules"""

    def test_validate_judge_score_valid(self):
        """Valid 0.5 increment scores should pass"""
        scorer = PerformanceScorer()

        valid_scores = [0.0, 0.5, 1.0, 5.5, 9.5, 10.0]
        for score in valid_scores:
            is_valid, error = scorer.validate_judge_score(score)
            assert is_valid, f"Score {score} should be valid: {error}"

    def test_validate_judge_score_invalid_range(self):
        """Scores outside 0-10 should fail"""
        scorer = PerformanceScorer()

        invalid_scores = [-0.5, -1.0, 10.5, 11.0, 15.0]
        for score in invalid_scores:
            is_valid, error = scorer.validate_judge_score(score)
            assert not is_valid, f"Score {score} should be invalid"

    def test_validate_judge_score_invalid_increments(self):
        """Scores not in 0.5 increments should fail"""
        scorer = PerformanceScorer()

        invalid_scores = [0.3, 0.7, 1.2, 1.3, 5.1]
        for score in invalid_scores:
            is_valid, error = scorer.validate_judge_score(score)
            assert not is_valid, f"Score {score} should not be in 0.5 increments"


class TestAggregateScore:
    """Test FINA aggregate score calculation (drop 2 high, 2 low)"""

    def test_aggregate_score_7_judges(self):
        """Calculate aggregate from 7 judges: drop 2 high, 2 low"""
        scorer = PerformanceScorer()

        ratings = [
            JudgeRating("judge1", Decimal("8.5")),
            JudgeRating("judge2", Decimal("9.0")),
            JudgeRating("judge3", Decimal("8.0")),
            JudgeRating("judge4", Decimal("8.5")),
            JudgeRating("judge5", Decimal("7.5")),
            JudgeRating("judge6", Decimal("9.0")),
            JudgeRating("judge7", Decimal("8.0")),
        ]

        aggregate, details = scorer.calculate_aggregate_score(ratings)

        # Sorted: [7.5, 8.0, 8.0, 8.5, 8.5, 9.0, 9.0]
        # Drop 2 low [7.5, 8.0], drop 2 high [9.0, 9.0]
        # Remaining: [8.0, 8.5, 8.5] → average 8.5
        assert details["judge_count"] == 7
        assert float(aggregate) == 8.5

    def test_aggregate_score_11_judges(self):
        """Calculate aggregate from 11 judges"""
        scorer = PerformanceScorer()

        ratings = [
            JudgeRating(f"judge{i}", Decimal(str(7.0 + (i % 3) * 0.5)))
            for i in range(1, 12)
        ]

        aggregate, details = scorer.calculate_aggregate_score(ratings)

        assert details["judge_count"] == 11
        assert len(details["trimmed_scores"]) == 7  # 11 - 2 - 2 = 7

    def test_aggregate_score_insufficient_judges(self):
        """Panel with wrong judge count should fail"""
        scorer = PerformanceScorer()

        ratings = [
            JudgeRating("judge1", Decimal("8.5")),
            JudgeRating("judge2", Decimal("9.0")),
            JudgeRating("judge3", Decimal("8.0")),
        ]

        aggregate, details = scorer.calculate_aggregate_score(ratings)

        assert "error" in details


class TestJudgePanelDatabase:
    """Test judge panel creation and score management"""

    def test_create_judge_panel_7_judges(self, db: Session, setup_test_data):
        """Create panel with 7 judges"""
        scorer = PerformanceScorer(db)
        dive = setup_test_data["dive"]

        panel = scorer.create_judge_panel(dive_id=dive.id, judge_count=7)

        assert panel.id is not None
        assert panel.dive_id == dive.id
        assert panel.judge_count == 7

    def test_create_judge_panel_11_judges(self, db: Session, setup_test_data):
        """Create panel with 11 judges for synchronized"""
        scorer = PerformanceScorer(db)
        dive = setup_test_data["dive"]

        panel = scorer.create_judge_panel(
            dive_id=dive.id,
            judge_count=11,
            panel_type="synchronization"
        )

        assert panel.judge_count == 11
        assert panel.panel_type == "synchronization"

    def test_add_judge_score(self, db: Session, setup_test_data):
        """Add individual judge scores"""
        scorer = PerformanceScorer(db)
        dive = setup_test_data["dive"]
        panel = scorer.create_judge_panel(dive_id=dive.id)

        score = scorer.add_judge_score(panel.id, 1, 8.5, "Judge One")

        assert score.panel_id == panel.id
        assert score.judge_number == 1
        assert float(score.score) == 8.5

    def test_add_judge_score_invalid(self, db: Session, setup_test_data):
        """Invalid scores should be rejected"""
        scorer = PerformanceScorer(db)
        dive = setup_test_data["dive"]
        panel = scorer.create_judge_panel(dive_id=dive.id)

        with pytest.raises(ValueError):
            scorer.add_judge_score(panel.id, 1, 10.5)  # Out of range

    def test_calculate_panel_average(self, db: Session, setup_test_data):
        """Calculate panel average with all scores"""
        scorer = PerformanceScorer(db)
        dive = setup_test_data["dive"]
        panel = scorer.create_judge_panel(dive_id=dive.id)

        # Add 7 scores
        for i in range(1, 8):
            scorer.add_judge_score(panel.id, i, 8.0 + (i % 2) * 0.5)

        average = scorer.calculate_panel_average(panel.id)

        assert average is not None
        assert isinstance(average, float)

    def test_calculate_panel_average_incomplete(self, db: Session, setup_test_data):
        """Incomplete panel should return None"""
        scorer = PerformanceScorer(db)
        dive = setup_test_data["dive"]
        panel = scorer.create_judge_panel(dive_id=dive.id, judge_count=7)

        # Add only 5 scores
        for i in range(1, 6):
            scorer.add_judge_score(panel.id, i, 8.5)

        average = scorer.calculate_panel_average(panel.id)

        assert average is None


class TestFinalScoreCalculation:
    """Test final score calculation and ranking"""

    def test_calculate_final_score_legacy(self):
        """Test final score with direct parameters"""
        scorer = PerformanceScorer()

        final_score = scorer.calculate_final_score(
            dive_id=1,
            panel_id=1,
            aggregate_performance=Decimal("8.5"),
            dd_value=Decimal("1.3")
        )

        # (8.5 / 10) × 1.3 = 1.105
        assert float(final_score) == pytest.approx(1.105, rel=0.01)

    def test_rank_dives_dict_input(self):
        """Rank dives from dict input (legacy)"""
        scorer = PerformanceScorer()

        dives = [
            {"dive_code": "101B", "final_score": 15.0},
            {"dive_code": "201C", "final_score": 18.0},
            {"dive_code": "301A", "final_score": 12.0},
        ]

        ranked = scorer.rank_dives(dives)

        assert len(ranked) == 3
        assert ranked[0]["final_score"] == 18.0
        assert ranked[0]["rank"] == 1

    def test_calculate_consistency(self):
        """Test consistency metrics"""
        scorer = PerformanceScorer()

        scores = [Decimal("8.0"), Decimal("8.5"), Decimal("8.0"), Decimal("8.2")]
        stats = scorer.calculate_consistency(scores)

        assert "mean" in stats
        assert "std_dev" in stats
        assert "coefficient_of_variation" in stats
        assert stats["mean"] > 0
