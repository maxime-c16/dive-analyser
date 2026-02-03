"""Sprint 4: Performance Scoring Tests"""

import pytest
from decimal import Decimal

from app.services.performance_scorer import PerformanceScorer, JudgeRating


class TestPerformanceScorer:
    """Test the Performance Scorer service"""

    @pytest.fixture
    def scorer(self):
        """Create scorer instance"""
        return PerformanceScorer()

    def test_validate_score_valid(self, scorer):
        """Test validating valid scores"""
        for score in [0.0, 5.0, 9.5, 10.0]:
            is_valid, error = scorer.validate_score(Decimal(str(score)))
            assert is_valid, f"Score {score} should be valid"

    def test_validate_score_invalid_range(self, scorer):
        """Test validating scores out of range"""
        for score in [-1.0, 10.5, 15.0]:
            is_valid, error = scorer.validate_score(Decimal(str(score)))
            assert not is_valid, f"Score {score} should be invalid"

    def test_aggregate_score_basic(self, scorer):
        """Test basic aggregate score calculation"""
        ratings = [
            JudgeRating("judge1", Decimal("8.0")),
            JudgeRating("judge2", Decimal("8.5")),
            JudgeRating("judge3", Decimal("8.0")),
        ]

        aggregate, details = scorer.calculate_aggregate_score(ratings)

        assert aggregate > Decimal("0")
        assert details["judge_count"] == 3

    def test_aggregate_score_removes_extremes(self, scorer):
        """Test that aggregate removes highest and lowest"""
        ratings = [
            JudgeRating("judge1", Decimal("7.0")),  # Will be removed
            JudgeRating("judge2", Decimal("8.0")),
            JudgeRating("judge3", Decimal("8.0")),
            JudgeRating("judge4", Decimal("9.0")),
            JudgeRating("judge5", Decimal("9.5")),
            JudgeRating("judge6", Decimal("9.5")),
            JudgeRating("judge7", Decimal("10.0")),  # Will be removed
        ]

        aggregate, details = scorer.calculate_aggregate_score(ratings)

        assert len(details["trimmed_scores"]) == 5  # 7 - 2 = 5
        assert details["min_score"] == 7.0
        assert details["max_score"] == 10.0

    def test_aggregate_score_minimum_judges(self, scorer):
        """Test minimum judges requirement"""
        ratings = [
            JudgeRating("judge1", Decimal("8.0")),
        ]

        aggregate, details = scorer.calculate_aggregate_score(ratings)

        assert "error" in details

    def test_calculate_final_score(self, scorer):
        """Test final score calculation"""
        performance = Decimal("8.0")
        dd = Decimal("2.0")

        final_score = scorer.calculate_final_score(performance, dd)

        # (8.0 / 10.0) * 2.0 = 1.6
        assert final_score == Decimal("1.6")

    def test_rank_dives(self, scorer):
        """Test ranking dives"""
        dives = [
            {"dive_code": "101B", "final_score": 15.0},
            {"dive_code": "201C", "final_score": 18.0},
            {"dive_code": "301A", "final_score": 12.0},
        ]

        ranked = scorer.rank_dives(dives)

        assert ranked[0]["rank"] == 1
        assert ranked[0]["final_score"] == 18.0
        assert ranked[1]["rank"] == 2
        assert ranked[2]["rank"] == 3

    def test_calculate_consistency(self, scorer):
        """Test consistency calculation"""
        scores = [Decimal("8.0"), Decimal("8.5"), Decimal("8.0"), Decimal("8.2")]

        stats = scorer.calculate_consistency(scores)

        assert "mean" in stats
        assert "std_dev" in stats
        assert "coefficient_of_variation" in stats
        assert stats["mean"] > 0

    def test_consistency_with_few_scores(self, scorer):
        """Test consistency with insufficient data"""
        scores = [Decimal("8.0")]

        stats = scorer.calculate_consistency(scores)

        assert "error" in stats


class TestScoringIntegration:
    """Integration tests for scoring"""

    def test_full_scoring_flow(self):
        """Test complete scoring flow"""
        scorer = PerformanceScorer()

        # Judge ratings
        ratings = [
            JudgeRating("judge1", Decimal("8.0")),
            JudgeRating("judge2", Decimal("8.5")),
            JudgeRating("judge3", Decimal("8.0")),
            JudgeRating("judge4", Decimal("8.2")),
        ]

        # Get aggregate
        aggregate, details = scorer.calculate_aggregate_score(ratings)
        assert aggregate > 0

        # Calculate final score with DD
        dd = Decimal("1.5")
        final = scorer.calculate_final_score(aggregate, dd)
        assert final > 0

        # Validate
        is_valid, _ = scorer.validate_score(aggregate)
        assert is_valid

    def test_consistency_across_dives(self):
        """Test consistency calculation across multiple dives"""
        scorer = PerformanceScorer()

        # Dives with multiple attempts
        dive1_scores = [Decimal("8.0"), Decimal("7.8"), Decimal("8.2")]
        dive2_scores = [Decimal("7.0"), Decimal("6.5"), Decimal("7.5")]

        stats1 = scorer.calculate_consistency(dive1_scores)
        stats2 = scorer.calculate_consistency(dive2_scores)

        # Dive 1 should be more consistent (lower std dev)
        assert stats1["std_dev"] < stats2["std_dev"]
