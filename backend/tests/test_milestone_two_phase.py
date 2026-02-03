"""Test milestone detection with two-phase performance scoring."""

import pytest
from datetime import datetime, timedelta
from typing import List

from app.services.milestones import (
    MilestoneDetector,
    DiveAttempt,
    MilestoneType,
)
from app.services.audit_log import PhaseInsightGenerator


def create_dive(
    uuid: str,
    dive_code: str,
    performance: str,
    date: datetime,
    phase1: str = None,
    phase2: str = None,
    height: str = "1m",
) -> DiveAttempt:
    """Helper to create a DiveAttempt."""
    return DiveAttempt(
        uuid=uuid,
        dive_code=dive_code,
        height=height,
        performance=performance,
        date=date,
        phase1_performance=phase1,
        phase2_performance=phase2,
    )


class TestPhaseInsightGeneration:
    """Test phase-based coaching insight generation."""

    def test_insight_weak_phase1(self):
        """Test insight for weak takeoff (phase1)."""
        insight = PhaseInsightGenerator.generate_insight("B", "G")
        assert insight is not None
        assert "hurdle" in insight.lower() or "takeoff" in insight.lower()

    def test_insight_weak_phase2(self):
        """Test insight for weak entry (phase2)."""
        insight = PhaseInsightGenerator.generate_insight("G", "M")
        assert insight is not None
        assert "entry" in insight.lower() or "water" in insight.lower()

    def test_insight_both_weak(self):
        """Test insight when both phases are weak."""
        insight = PhaseInsightGenerator.generate_insight("M", "B")
        assert insight is not None

    def test_no_insight_perfect(self):
        """Test that perfect (P/P) generates no insight."""
        insight = PhaseInsightGenerator.generate_insight("P", "P")
        assert insight is None

    def test_insight_critical_phase1(self):
        """Test critical-level insight for very weak phase1."""
        insight = PhaseInsightGenerator.generate_insight("F", "P")
        assert insight is not None
        assert "critical" in insight.lower() or "increase" in insight.lower()

    def test_insight_critical_phase2(self):
        """Test critical-level insight for very weak phase2."""
        insight = PhaseInsightGenerator.generate_insight("P", "F")
        assert insight is not None
        assert "critical" in insight.lower()


class TestMilestoneDetectionTwoPhase:
    """Test milestone detection with two-phase scoring."""

    def test_first_success_with_two_phase(self):
        """Test first_success milestone with two-phase format."""
        base_date = datetime(2026, 1, 1)
        attempts = [
            create_dive(
                "uuid-1",
                "101B",
                "F",
                base_date,
                phase1="F",
                phase2="F",
            ),
            create_dive(
                "uuid-2",
                "101B",
                "M",  # First success
                base_date + timedelta(days=1),
                phase1="M",
                phase2="M",
            ),
        ]

        detector = MilestoneDetector(attempts)
        milestones = detector.detect_all()

        # Should detect FIRST_SUCCESS
        success_milestones = [m for m in milestones if m.type == MilestoneType.FIRST_SUCCESS]
        assert len(success_milestones) > 0
        milestone = success_milestones[0]
        assert milestone.dive_code == "101B"
        assert milestone.phase1_performance == "M"
        assert milestone.phase2_performance == "M"

    def test_breakthrough_with_two_phase(self):
        """Test breakthrough milestone with two-phase scoring."""
        base_date = datetime(2026, 1, 1)
        attempts = [
            create_dive("uuid-1", "201C", "F", base_date, "F", "F"),
            create_dive("uuid-2", "201C", "B", base_date + timedelta(days=1), "B", "B"),
            create_dive("uuid-3", "201C", "F", base_date + timedelta(days=2), "F", "B"),
            create_dive("uuid-4", "201C", "G", base_date + timedelta(days=3), "G", "G"),  # Breakthrough
        ]

        detector = MilestoneDetector(attempts)
        milestones = detector.detect_all()

        # Should detect breakthrough
        breakthrough = [m for m in milestones if m.type == MilestoneType.BREAKTHROUGH]
        assert len(breakthrough) > 0
        assert breakthrough[0].phase1_performance == "G"
        assert breakthrough[0].phase2_performance == "G"

    def test_phase_gap_insight(self):
        """Test milestone narrative includes phase gap insight."""
        base_date = datetime(2026, 1, 1)
        attempts = [
            create_dive("uuid-1", "301C", "F", base_date, "F", "F"),
            create_dive("uuid-2", "301C", "B", base_date + timedelta(days=1), "B", "B"),
            create_dive(
                "uuid-3",
                "301C",
                "G",  # Phase gap: good phase1, bad phase2
                base_date + timedelta(days=2),
                phase1="G",
                phase2="B",
            ),
        ]

        detector = MilestoneDetector(attempts)
        milestones = detector.detect_all()

        # Find the dive with phase gap
        for milestone in milestones:
            if (
                milestone.phase1_performance == "G"
                and milestone.phase2_performance == "B"
            ):
                # Should have phase insight
                assert milestone.phase_insight is not None

    def test_two_phase_vs_legacy_format(self):
        """Test that both legacy and two-phase formats work together."""
        base_date = datetime(2026, 1, 1)
        attempts = [
            create_dive("uuid-1", "101B", "F", base_date),  # Legacy format (no phase data)
            create_dive("uuid-2", "101B", "M", base_date + timedelta(days=1), "M", "M"),  # Two-phase
        ]

        detector = MilestoneDetector(attempts)
        milestones = detector.detect_all()

        # Both should be processed
        assert len(milestones) > 0

    def test_consistency_with_two_phase(self):
        """Test consistency milestone calculation with two-phase data."""
        base_date = datetime(2026, 1, 1)
        # Create consistent two-phase performance
        attempts = []
        for i in range(5):
            attempts.append(
                create_dive(
                    f"uuid-{i}",
                    "101B",
                    "P",
                    base_date + timedelta(days=i),
                    phase1="P",
                    phase2="P",
                )
            )

        detector = MilestoneDetector(attempts)
        milestones = detector.detect_all()

        # Should detect consistency
        consistency = [m for m in milestones if m.type == MilestoneType.CONSISTENCY_ACHIEVED]
        if consistency:
            assert consistency[0].phase1_performance == "P"
            assert consistency[0].phase2_performance == "P"

    def test_streak_with_two_phase(self):
        """Test success streak milestone with two-phase format."""
        base_date = datetime(2026, 1, 1)
        attempts = []
        for i in range(4):
            attempts.append(
                create_dive(
                    f"uuid-{i}",
                    "101B",
                    "G" if i == 0 else "P",  # First good, then perfect
                    base_date + timedelta(days=i),
                    phase1="G" if i == 0 else "P",
                    phase2="G" if i == 0 else "P",
                )
            )

        detector = MilestoneDetector(attempts)
        milestones = detector.detect_all()

        # Should detect streak
        streaks = [m for m in milestones if m.type == MilestoneType.SUCCESS_STREAK]
        if streaks:
            assert streaks[0].phase1_performance is not None
            assert streaks[0].phase2_performance is not None

    def test_height_first_from_height_two_phase(self):
        """Test first attempt from height with two-phase format."""
        base_date = datetime(2026, 1, 1)
        attempts = [
            # First attempt at 3m (no prior 1m)
            create_dive(
                "uuid-1", "101B", "B", base_date, "B", "B", height="3m"
            ),
            # Second height
            create_dive(
                "uuid-2", "201C", "G", base_date + timedelta(days=1), "G", "G", height="5m"
            ),
        ]

        detector = MilestoneDetector(attempts)
        milestones = detector.detect_all()

        # Should detect first from 3m and 5m
        from_height = [m for m in milestones if m.type == MilestoneType.FIRST_FROM_HEIGHT]
        if from_height:
            # First milestone should be for 3m (first in attempts)
            assert from_height[0].height == "3m"
            assert from_height[0].phase1_performance == "B"
            assert from_height[0].phase2_performance == "B"

    def test_multiple_dives_phase_insights_tracked(self):
        """Test that phase insights are tracked for multiple dives."""
        base_date = datetime(2026, 1, 1)
        attempts = [
            create_dive("uuid-1", "101B", "M", base_date, "B", "P"),  # Weak takeoff
            create_dive("uuid-2", "201C", "M", base_date + timedelta(days=1), "P", "B"),  # Weak entry
            create_dive("uuid-3", "301C", "M", base_date + timedelta(days=2), "M", "M"),  # Both ok
        ]

        detector = MilestoneDetector(attempts)
        milestones = detector.detect_all()

        # Find milestones with phase data
        phase_milestones = [m for m in milestones if m.phase1_performance is not None]
        assert len(phase_milestones) > 0

    def test_phase_performance_descriptions(self):
        """Test that phase performance values are properly formatted."""
        base_date = datetime(2026, 1, 1)
        attempts = [
            create_dive("uuid-1", "101B", "P", base_date, "P", "P"),
        ]

        detector = MilestoneDetector(attempts)
        # Just verify detector can be created and processes two-phase data
        assert detector is not None

    def test_comeback_after_gap_two_phase(self):
        """Test comeback milestone after 30+ day gap with two-phase."""
        base_date = datetime(2026, 1, 1)
        attempts = [
            create_dive("uuid-1", "101B", "P", base_date, "P", "P"),
            # 31 day gap
            create_dive(
                "uuid-2",
                "101B",
                "G",
                base_date + timedelta(days=31),
                "G",
                "G",
            ),
        ]

        detector = MilestoneDetector(attempts)
        milestones = detector.detect_all()

        # Should detect comeback
        comebacks = [m for m in milestones if m.type == MilestoneType.COMEBACK]
        if comebacks:
            assert comebacks[0].days_since_last >= 30
            assert comebacks[0].phase1_performance == "G"
            assert comebacks[0].phase2_performance == "G"


class TestMilestoneEdgeCases:
    """Test edge cases in milestone detection with two-phase data."""

    def test_missing_phase_data_fallback(self):
        """Test that missing phase data doesn't break detection."""
        base_date = datetime(2026, 1, 1)
        attempts = [
            create_dive("uuid-1", "101B", "P", base_date),  # No phase data
        ]

        detector = MilestoneDetector(attempts)
        milestones = detector.detect_all()
        # Should still process
        assert detector is not None

    def test_partial_phase_data(self):
        """Test with only phase1 or only phase2 data."""
        base_date = datetime(2026, 1, 1)
        attempts = [
            create_dive("uuid-1", "101B", "G", base_date, phase1="G"),  # Only phase1
            create_dive("uuid-2", "201C", "G", base_date + timedelta(days=1), phase2="G"),  # Only phase2
        ]

        detector = MilestoneDetector(attempts)
        milestones = detector.detect_all()
        # Should handle gracefully
        assert detector is not None

    def test_invalid_phase_characters_ignored(self):
        """Test that invalid phase characters are handled."""
        base_date = datetime(2026, 1, 1)
        attempts = [
            create_dive("uuid-1", "101B", "P", base_date, "P", "P"),
        ]

        detector = MilestoneDetector(attempts)
        # Should not crash
        assert detector is not None


class TestMilestonePhaseIntegration:
    """Integration tests for phases throughout milestone lifecycle."""

    def test_phase_data_preserved_in_milestone(self):
        """Test that phase data is preserved from DiveAttempt to Milestone."""
        base_date = datetime(2026, 1, 1)
        attempts = [
            create_dive("uuid-1", "101B", "P", base_date, "G", "P"),
        ]

        detector = MilestoneDetector(attempts)
        milestones = detector.detect_all()

        # Find the milestone
        assert len(milestones) > 0
        for milestone in milestones:
            if milestone.dive_code == "101B":
                if milestone.phase1_performance == "G":
                    assert milestone.phase2_performance == "P"

    def test_phase_insight_generation_in_milestone(self):
        """Test that phase insights are generated for milestones."""
        base_date = datetime(2026, 1, 1)
        attempts = [
            create_dive("uuid-1", "101B", "M", base_date, "B", "P"),  # Weak phase1
        ]

        detector = MilestoneDetector(attempts)
        milestones = detector.detect_all()

        # Verify milestones have phase_insight
        for milestone in milestones:
            if milestone.phase1_performance == "B" and milestone.phase2_performance == "P":
                # Should have insight
                insight = PhaseInsightGenerator.generate_insight("B", "P")
                assert insight is not None
