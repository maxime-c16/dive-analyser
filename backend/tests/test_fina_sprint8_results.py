"""Sprint 8: Results and Scoring Tests"""

import pytest

from app.services.results_aggregator import ResultsAggregator


class TestResultsAggregator:
    """Test results aggregator service"""

    @pytest.fixture
    def aggregator(self):
        return ResultsAggregator()

    def test_aggregate_scores(self, aggregator):
        """Test aggregating dive scores"""
        scores = [
            {"dive_code": "101B", "total_score": 15.5},
            {"dive_code": "201C", "total_score": 18.2},
            {"dive_code": "301A", "total_score": 12.3},
        ]

        result = aggregator.aggregate_scores(scores)
        assert len(result) == 3
        assert result[0]["total_score"] == 18.2  # Highest first

    def test_calculate_session_total(self, aggregator):
        """Test calculating session total"""
        scores = [
            {"total_score": 10},
            {"total_score": 15},
            {"total_score": 8},
        ]

        total = aggregator.calculate_session_total(scores)
        assert total == 33

    def test_rank_competitors(self, aggregator):
        """Test ranking competitors"""
        competitors = [
            {"name": "Alice", "total_score": 100},
            {"name": "Bob", "total_score": 120},
            {"name": "Charlie", "total_score": 90},
        ]

        ranked = aggregator.rank_competitors(competitors)
        assert ranked[0]["rank"] == 1
        assert ranked[0]["name"] == "Bob"
        assert ranked[2]["rank"] == 3

    def test_generate_leaderboard(self, aggregator):
        """Test generating leaderboard"""
        competitors = [
            {"name": "Alice", "total_score": 100},
            {"name": "Bob", "total_score": 120},
        ]

        leaderboard = aggregator.generate_leaderboard(1, competitors)
        assert leaderboard["event_id"] == 1
        assert leaderboard["total_competitors"] == 2
        assert len(leaderboard["leaderboard"]) == 2

    def test_export_json(self, aggregator):
        """Test JSON export"""
        results = {"event_id": 1, "leaderboard": []}
        exported = aggregator.export_results(results, "json")
        assert isinstance(exported, str)
        assert "event_id" in exported

    def test_export_csv(self, aggregator):
        """Test CSV export"""
        results = {
            "leaderboard": [
                {"rank": 1, "name": "Alice", "total_score": 100},
            ]
        }
        exported = aggregator.export_results(results, "csv")
        assert "rank" in exported
        assert "Alice" in exported
