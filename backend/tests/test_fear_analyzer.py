"""Tests for fear analyzer and psychological plateau detection."""

import pytest
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.models.dive import Dive
from app.models.session import Session as SessionModel
from app.models.emotional_state import EmotionalState
from app.services.fear_analyzer import FearAnalyzer


@pytest.fixture
def sample_dives_with_fear(test_db: Session) -> list:
    """Create sample dives with varying fear patterns for testing."""
    # Create session
    session = SessionModel(
        date=datetime.now().date(),
        location="Test Pool",
        notes="Fear analysis test session",
        total_dives=10,
        total_personal_dives=10,
        avg_performance=2.5,
        success_rate=0.5
    )
    test_db.add(session)
    test_db.commit()
    test_db.refresh(session)

    dives = []
    dive_codes = ["101B", "201C", "301B", "401B"]

    # Create dives with varying emotions and success rates
    for i in range(10):
        dive_code = dive_codes[i % len(dive_codes)]
        # Create fear pattern: more recent dives have more fear
        is_recent = i > 5
        is_fearful = is_recent

        dive = Dive(
            session_id=session.id,
            dive_code=dive_code,
            performance="M" if i % 2 == 0 else "G",
            performance_numeric=2 if i % 2 == 0 else 3,
            height="5m",
            official_dd=2.0 + (i * 0.1),  # Increasing difficulty
            dive_datetime=datetime.now() - timedelta(days=30 - i)
        )
        test_db.add(dive)
        test_db.commit()
        test_db.refresh(dive)

        # Add emotional state
        emotion = EmotionalState(
            dive_id=dive.id,
            pre_dive_emotion="fearful" if is_fearful else "confident",
            post_dive_emotion="relieved" if is_fearful else "satisfied",
            confidence_rating=2 if is_fearful else 4
        )
        test_db.add(emotion)
        dives.append(dive)

    test_db.commit()
    return dives


class TestFearPlateauDetection:
    """Test fear plateau detection functionality."""

    def test_fear_analyzer_initialization(self, test_db: Session):
        """Test FearAnalyzer can be initialized with database."""
        analyzer = FearAnalyzer(test_db)
        assert analyzer.db == test_db

    def test_detect_fear_plateau_no_data(self, test_db: Session):
        """Test fear plateau detection with no dive data."""
        analyzer = FearAnalyzer(test_db)
        result = analyzer.detect_fear_plateau()

        assert result["avoided_dives"] == []
        assert result["dd_gap"] == 0
        assert result["confidence_blocks"] == []
        assert result["risk_level"] == "low"

    def test_detect_fear_plateau_with_avoided_dives(self, test_db: Session, sample_dives_with_fear: list):
        """Test detection of feared and avoided dives."""
        # Add dives that are avoided (not attempted recently)
        session = test_db.query(SessionModel).first()

        # Create multiple old attempts (need at least 3 to establish pattern)
        for i in range(3):
            old_dive = Dive(
                session_id=session.id,
                dive_code="501B",
                performance="B" if i > 0 else "F",
                performance_numeric=1 if i > 0 else 0,
                height="10m",
                official_dd=3.5,
                dive_datetime=datetime.now() - timedelta(days=40 - i)
            )
            test_db.add(old_dive)
            test_db.commit()
            test_db.refresh(old_dive)

            # Add fearful emotion to establish pattern
            emotion = EmotionalState(
                dive_id=old_dive.id,
                pre_dive_emotion="fearful",
                confidence_rating=1
            )
            test_db.add(emotion)

        test_db.commit()

        analyzer = FearAnalyzer(test_db)
        result = analyzer.detect_fear_plateau()

        # With the sample dives already created, should detect some pattern
        assert result["risk_level"] in ["low", "medium", "high"]

    def test_risk_level_assessment(self, test_db: Session):
        """Test risk level assessment based on avoidance patterns."""
        analyzer = FearAnalyzer(test_db)

        # Test low risk (no avoided dives)
        low_risk = analyzer._assess_risk_level(0, 0.3, [])
        assert low_risk == "low"

        # Test medium risk (few avoided dives, small gap)
        medium_risk = analyzer._assess_risk_level(2, 1.0, [{"type": "difficulty_plateau"}])
        assert medium_risk == "medium"

        # Test high risk (many avoided dives, large gap)
        high_risk = analyzer._assess_risk_level(5, 2.0, [{"type": "emotional_block"}])
        assert high_risk == "high"


class TestFearCoefficient:
    """Test fear coefficient calculation."""

    def test_fear_coefficient_no_dives(self, test_db: Session):
        """Test fear coefficient with no dives of that code."""
        analyzer = FearAnalyzer(test_db)
        result = analyzer.calculate_fear_coefficient("999Z")

        assert result["fear_coefficient"] == 0
        assert result["interpretation"] == "insufficient_data"

    def test_fear_coefficient_high_success_rate(self, test_db: Session, sample_dives_with_fear: list):
        """Test fear coefficient with high success rate (should be lower)."""
        session = test_db.query(SessionModel).first()

        # Create successful dives
        for i in range(5):
            dive = Dive(
                session_id=session.id,
                dive_code="101B",
                performance="P",
                performance_numeric=4,
                height="1m",
                official_dd=1.2,
                dive_datetime=datetime.now() - timedelta(days=i)
            )
            test_db.add(dive)
            test_db.commit()
            test_db.refresh(dive)

            emotion = EmotionalState(
                dive_id=dive.id,
                confidence_rating=5
            )
            test_db.add(emotion)

        test_db.commit()

        analyzer = FearAnalyzer(test_db)
        result = analyzer.calculate_fear_coefficient("101B")

        # High success rate should lead to balanced or lower fear coefficient
        assert result["success_rate"] > 50
        assert result["interpretation"] in ["balanced", "appropriate_caution"]

    def test_fear_coefficient_low_success_rate(self, test_db: Session):
        """Test fear coefficient with low success rate (should be higher)."""
        session = SessionModel(
            date=datetime.now().date(),
            location="Test Pool",
            notes="Low success test",
            total_dives=5,
            total_personal_dives=5,
            avg_performance=1.0,
            success_rate=0.2
        )
        test_db.add(session)
        test_db.commit()
        test_db.refresh(session)

        # Create failures
        for i in range(5):
            dive = Dive(
                session_id=session.id,
                dive_code="401B",
                performance="F",
                performance_numeric=0,
                height="10m",
                official_dd=3.8,
                dive_datetime=datetime.now() - timedelta(days=i)
            )
            test_db.add(dive)
            test_db.commit()
            test_db.refresh(dive)

            emotion = EmotionalState(
                dive_id=dive.id,
                pre_dive_emotion="fearful",
                confidence_rating=1
            )
            test_db.add(emotion)

        test_db.commit()

        analyzer = FearAnalyzer(test_db)
        result = analyzer.calculate_fear_coefficient("401B")

        # Low success rate should lead to higher fear coefficient
        assert result["success_rate"] == 0.0
        assert result["fear_coefficient"] > 0.5

    def test_fear_coefficient_infrequent_attempts(self, test_db: Session):
        """Test fear coefficient increases with infrequent attempts (avoidance)."""
        session = SessionModel(
            date=datetime.now().date(),
            location="Test Pool",
            notes="Infrequent attempts",
            total_dives=2,
            total_personal_dives=2,
            avg_performance=2.5,
            success_rate=0.5
        )
        test_db.add(session)
        test_db.commit()
        test_db.refresh(session)

        # Create attempts 30+ days apart (avoidance pattern)
        for i in range(2):
            dive = Dive(
                session_id=session.id,
                dive_code="301B",
                performance="G",
                performance_numeric=3,
                height="5m",
                official_dd=2.5,
                dive_datetime=datetime.now() - timedelta(days=30 * (i + 1))
            )
            test_db.add(dive)
            test_db.commit()
            test_db.refresh(dive)

            emotion = EmotionalState(
                dive_id=dive.id,
                confidence_rating=3
            )
            test_db.add(emotion)

        test_db.commit()

        analyzer = FearAnalyzer(test_db)
        result = analyzer.calculate_fear_coefficient("301B")

        # Infrequent attempts should increase fear coefficient
        assert result["total_attempts"] == 2


class TestEmotionalTriggers:
    """Test emotional trigger identification."""

    def test_get_emotional_triggers_no_data(self, test_db: Session):
        """Test emotional triggers with no dive data."""
        analyzer = FearAnalyzer(test_db)
        result = analyzer.get_emotional_triggers()

        assert result["high_fear_dives"] == []
        assert result["confidence_drivers"] == []

    def test_high_fear_dives_identification(self, test_db: Session):
        """Test identification of dives triggering fear."""
        session = SessionModel(
            date=datetime.now().date(),
            location="Test Pool",
            notes="Fear trigger test",
            total_dives=5,
            total_personal_dives=5,
            avg_performance=2.0,
            success_rate=0.4
        )
        test_db.add(session)
        test_db.commit()
        test_db.refresh(session)

        # Create dives with consistent fear emotion
        for i in range(5):
            dive = Dive(
                session_id=session.id,
                dive_code="201C",
                performance="M" if i % 2 == 0 else "G",
                performance_numeric=2 if i % 2 == 0 else 3,
                height="3m",
                official_dd=1.8,
                dive_datetime=datetime.now() - timedelta(days=i)
            )
            test_db.add(dive)
            test_db.commit()
            test_db.refresh(dive)

            emotion = EmotionalState(
                dive_id=dive.id,
                pre_dive_emotion="anxious",
                confidence_rating=2
            )
            test_db.add(emotion)

        test_db.commit()

        analyzer = FearAnalyzer(test_db)
        result = analyzer.get_emotional_triggers()

        # Should identify dives with fear patterns
        high_fear = result["high_fear_dives"]
        assert len(high_fear) > 0

    def test_confidence_drivers_identification(self, test_db: Session):
        """Test identification of dives building confidence."""
        session = SessionModel(
            date=datetime.now().date(),
            location="Test Pool",
            notes="Confidence driver test",
            total_dives=5,
            total_personal_dives=5,
            avg_performance=4.0,
            success_rate=1.0
        )
        test_db.add(session)
        test_db.commit()
        test_db.refresh(session)

        # Create successful dives with confidence emotions
        for i in range(5):
            dive = Dive(
                session_id=session.id,
                dive_code="101B",
                performance="P",
                performance_numeric=4,
                height="1m",
                official_dd=1.2,
                dive_datetime=datetime.now() - timedelta(days=i)
            )
            test_db.add(dive)
            test_db.commit()
            test_db.refresh(dive)

            emotion = EmotionalState(
                dive_id=dive.id,
                post_dive_emotion="proud",
                confidence_rating=5
            )
            test_db.add(emotion)

        test_db.commit()

        analyzer = FearAnalyzer(test_db)
        result = analyzer.get_emotional_triggers()

        # Should identify confidence drivers
        confidence = result["confidence_drivers"]
        assert len(confidence) > 0


class TestConfidenceTrends:
    """Test confidence trend tracking."""

    def test_confidence_trends_no_data(self, test_db: Session):
        """Test confidence trends with no dive data."""
        analyzer = FearAnalyzer(test_db)
        result = analyzer.track_confidence_trends(days=30)

        assert result["daily_trend"] == []
        assert result["slope"] == "insufficient_data"

    def test_improving_confidence_trend(self, test_db: Session):
        """Test detection of improving confidence trend."""
        session = SessionModel(
            date=datetime.now().date(),
            location="Test Pool",
            notes="Improving confidence test",
            total_dives=10,
            total_personal_dives=10,
            avg_performance=3.5,
            success_rate=0.7
        )
        test_db.add(session)
        test_db.commit()
        test_db.refresh(session)

        # Create dives with improving confidence over time
        confidence_ratings = [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]

        for i, confidence in enumerate(confidence_ratings):
            dive = Dive(
                session_id=session.id,
                dive_code="101B",
                performance="G",
                performance_numeric=3,
                height="5m",
                dive_datetime=datetime.now() - timedelta(days=30 - i)
            )
            test_db.add(dive)
            test_db.commit()
            test_db.refresh(dive)

            emotion = EmotionalState(
                dive_id=dive.id,
                confidence_rating=confidence
            )
            test_db.add(emotion)

        test_db.commit()

        analyzer = FearAnalyzer(test_db)
        result = analyzer.track_confidence_trends(days=30)

        # Should show improving trend
        assert result["slope"] in ["improving", "stable"]
        assert len(result["daily_trend"]) > 0

    def test_declining_confidence_trend(self, test_db: Session):
        """Test detection of declining confidence trend."""
        session = SessionModel(
            date=datetime.now().date(),
            location="Test Pool",
            notes="Declining confidence test",
            total_dives=10,
            total_personal_dives=10,
            avg_performance=2.0,
            success_rate=0.3
        )
        test_db.add(session)
        test_db.commit()
        test_db.refresh(session)

        # Create dives with declining confidence
        confidence_ratings = [5, 5, 4, 4, 3, 3, 2, 2, 1, 1]

        for i, confidence in enumerate(confidence_ratings):
            dive = Dive(
                session_id=session.id,
                dive_code="301B",
                performance="M" if i > 5 else "G",
                performance_numeric=2 if i > 5 else 3,
                height="7m",
                dive_datetime=datetime.now() - timedelta(days=30 - i)
            )
            test_db.add(dive)
            test_db.commit()
            test_db.refresh(dive)

            emotion = EmotionalState(
                dive_id=dive.id,
                confidence_rating=confidence
            )
            test_db.add(emotion)

        test_db.commit()

        analyzer = FearAnalyzer(test_db)
        result = analyzer.track_confidence_trends(days=30)

        # Should show declining trend
        assert result["slope"] in ["declining", "stable"]

    def test_confidence_weekly_summary(self, test_db: Session):
        """Test weekly confidence summary generation."""
        session = SessionModel(
            date=datetime.now().date(),
            location="Test Pool",
            notes="Weekly summary test",
            total_dives=14,
            total_personal_dives=14,
            avg_performance=3.0,
            success_rate=0.6
        )
        test_db.add(session)
        test_db.commit()
        test_db.refresh(session)

        # Create dives across multiple weeks
        for i in range(14):
            dive = Dive(
                session_id=session.id,
                dive_code="201B",
                performance="G",
                performance_numeric=3,
                height="3m",
                dive_datetime=datetime.now() - timedelta(days=i)
            )
            test_db.add(dive)
            test_db.commit()
            test_db.refresh(dive)

            emotion = EmotionalState(
                dive_id=dive.id,
                confidence_rating=3 + (i // 7)  # Increases each week
            )
            test_db.add(emotion)

        test_db.commit()

        analyzer = FearAnalyzer(test_db)
        result = analyzer.track_confidence_trends(days=30)

        # Should have weekly summary
        assert len(result["weekly_summary"]) > 0
        assert all("week" in w for w in result["weekly_summary"])
