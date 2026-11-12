"""Regression tests for the official grade names (PR #206).

Each rating letter has exactly one canonical name, aligned with the
FFN judging scale:
  P Parfait/Perfect, G Bon/Good, M Moyen/Medium,
  B Non satisfaisant/Unsatisfactory, F Manqué/Failed.
No narrative text may use a retired label (e.g. "Bad", "Below target").
"""

from datetime import datetime

from app.services.milestones import DiveAttempt, MilestoneDetector


def _detector() -> MilestoneDetector:
    attempt = DiveAttempt(
        uuid="uuid-1",
        dive_code="101B",
        height="1m",
        performance="M",
        date=datetime(2026, 1, 1),
    )
    return MilestoneDetector([attempt])


class TestOfficialGradeNames:
    def test_letter_b_maps_to_unsatisfactory(self):
        detector = _detector()
        assert detector._performance_name("B") == "Unsatisfactory"

    def test_full_letter_map_uses_canonical_names(self):
        detector = _detector()
        assert detector._performance_name("F") == "Failed"
        assert detector._performance_name("M") == "Medium"
        assert detector._performance_name("G") == "Good"
        assert detector._performance_name("P") == "Perfect"

    def test_range_labels_never_use_retired_bad(self):
        detector = _detector()
        for value in (0.0, 1.5, 3.25, 4.0, 5.75, 6.5, 8.5, 10.0):
            label = detector._performance_name_from_value(value)
            assert "Bad" not in label, f"value {value} -> {label!r}"

    def test_mid_range_label_uses_canonical_b_name(self):
        detector = _detector()
        assert detector._performance_name_from_value(4.0) == "Unsatisfactory-Medium"

    def test_phase_descriptions_use_unsatisfactory(self):
        attempt = DiveAttempt(
            uuid="uuid-2",
            dive_code="101B",
            height="1m",
            performance="B",
            date=datetime(2026, 1, 1),
            phase1_performance="B",
            phase2_performance="B",
        )
        assert attempt.phase1_description == "Unsatisfactory"
        assert attempt.phase2_description == "Unsatisfactory"
