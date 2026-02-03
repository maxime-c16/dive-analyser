"""Sprint 5: Execution Analysis Tests"""

import pytest
from decimal import Decimal

from app.services.execution_analyzer import ExecutionAnalyzer, ExecutionMetric


class TestExecutionAnalyzer:
    """Test the Execution Analyzer service"""

    @pytest.fixture
    def analyzer(self):
        return ExecutionAnalyzer()

    def test_analyze_execution_basic(self, analyzer):
        """Test basic execution analysis"""
        metrics = [
            ExecutionMetric("approach", 7.5),
            ExecutionMetric("takeoff", 7.5),
            ExecutionMetric("flight", 8.0),
            ExecutionMetric("entry", 7.0),
        ]

        score, analysis = analyzer.analyze_execution(metrics)

        assert score > Decimal("0")
        assert analysis["metrics_count"] == 4

    def test_analyze_execution_weighted(self, analyzer):
        """Test weighted score calculation"""
        metrics = [
            ExecutionMetric("flight", 10.0),  # High weight (0.40)
            ExecutionMetric("approach", 0.0),  # Low weight (0.15)
        ]

        score, analysis = analyzer.analyze_execution(metrics)

        # Flight has high weight, so should dominate
        assert score > Decimal("5.0")

    def test_rate_approach(self, analyzer):
        """Test approach phase rating"""
        rating = analyzer.rate_approach({})
        assert 0 <= rating <= 10

    def test_rate_takeoff(self, analyzer):
        """Test takeoff phase rating"""
        rating = analyzer.rate_takeoff({})
        assert 0 <= rating <= 10

    def test_rate_flight(self, analyzer):
        """Test flight phase rating"""
        rating = analyzer.rate_flight({})
        assert 0 <= rating <= 10

    def test_rate_entry(self, analyzer):
        """Test entry phase rating"""
        rating = analyzer.rate_entry({})
        assert 0 <= rating <= 10

    def test_identify_faults(self, analyzer):
        """Test fault identification"""
        faults = analyzer.identify_faults({})
        assert isinstance(faults, list)

    def test_get_execution_report(self, analyzer):
        """Test generating full execution report"""
        report = analyzer.get_execution_report(1, {})

        assert "dive_id" in report
        assert "execution_score" in report
        assert "faults" in report
        assert report["dive_id"] == 1
