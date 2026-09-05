from datetime import datetime, timedelta

from app.models.dive import Dive
from app.services.dive_analysis_service import (
    build_insights,
    canonical_dive_code,
    is_analytics_dive,
    rolling_median,
    phase_analysis,
    sample_label,
    summarize,
    trend,
)
from app.api.v1.dive_analysis import _parse_date_bound


def attempt(attempt_id: int, days: int, performance: str, phase1=None, phase2=None):
    return Dive(
        id=attempt_id,
        session_id=1,
        dive_code="103B",
        performance=performance,
        performance_numeric={"F": 0, "B": 1, "M": 2, "G": 3, "P": 4}[performance],
        phase1_performance=phase1,
        phase2_performance=phase2,
        height="1M",
        dive_datetime=datetime(2026, 1, 1) + timedelta(days=days),
    )


def test_code_normalization_and_straight_jump_exclusion():
    assert canonical_dive_code(" 103b ") == "103B"
    assert is_analytics_dive("103B") is True
    assert is_analytics_dive("100B") is False


def test_date_only_bounds_cover_the_full_selected_day():
    assert _parse_date_bound("2026-07-10").hour == 0
    end = _parse_date_bound("2026-07-10", end_of_day=True)
    assert (end.hour, end.minute, end.second) == (23, 59, 59)


def test_summary_uses_calibrated_score_and_visible_success_threshold():
    dives = [attempt(1, 0, "B"), attempt(2, 1, "M"), attempt(3, 2, "G"), attempt(4, 3, "P")]
    result = summarize(dives, "G")
    assert result["attempt_count"] == 4
    assert result["median"] == 5.75
    assert result["success_rate"] == 50.0
    assert result["success_threshold"] == "G"
    assert result["session_count"] == 1


def test_two_phase_attempt_uses_weighted_precise_score():
    result = summarize([attempt(1, 0, "G", "G", "M")])
    assert result["average"] == 5.62


def test_difficulty_adjusted_execution_is_explicit_and_not_a_raw_score_replacement():
    easy_high_execution = attempt(1, 0, "P")  # 103B at 1m: DD 1.7
    difficult_lower_execution = attempt(2, 1, "G")
    difficult_lower_execution.dive_code = "309B"
    difficult_lower_execution.height = "3m"  # DD 4.7
    result = summarize([easy_high_execution, difficult_lower_execution])
    assert result["average"] == 8.5
    assert result["average_dd"] == 3.2
    assert result["dd_coverage_rate"] == 100.0
    # 7.0 × 4.7 outranks 10.0 × 1.7 in the separate DD-adjusted index.
    assert result["dd_adjusted_execution_average"] == 24.95
    assert result["dd_reference"] == "ffn_world_aquatics_diving_2022_2025_appendix_1_3"


def test_rolling_median_preserves_atomic_attempt_ids():
    dives = [attempt(index, index, score) for index, score in enumerate(["F", "B", "P", "G", "M", "P"], 1)]
    rolling = rolling_median(dives, window=5)
    assert set(rolling) == {1, 2, 3, 4, 5, 6}
    assert rolling[5] == 4.5


def test_trend_requires_sample_and_date_span():
    assert trend([attempt(1, 0, "M"), attempt(2, 30, "G")])["direction"] == "insufficient_data"
    dives = [attempt(index, index * 15, score) for index, score in enumerate(["B", "M", "M", "G", "G", "P"], 1)]
    assert trend(dives)["direction"] == "improving"


def test_insight_language_reports_observation_not_causation():
    previous_dives = [attempt(index, index, "M") for index in range(1, 7)]
    current_dives = [attempt(index + 10, index + 30, "G") for index in range(1, 7)]
    insights = build_insights(summarize(current_dives), summarize(previous_dives), current_dives, previous_dives)
    assert any("Observed median" in item["message"] for item in insights)
    assert all("caused" not in item["message"].lower() for item in insights)


def test_session_weighting_prevents_large_session_from_dominating():
    dives = [attempt(index, index, "P") for index in range(1, 10)]
    for dive in dives:
        dive.session_id = 1
    low_session = attempt(20, 20, "B")
    low_session.session_id = 2
    dives.append(low_session)
    attempt_weighted = summarize(dives, weighting="attempts")
    session_weighted = summarize(dives, weighting="sessions")
    assert attempt_weighted["average"] == 9.2
    assert session_weighted["average"] == 6.0
    assert session_weighted["session_count"] == 2


def test_phase_analysis_preserves_missing_values():
    dives = [attempt(1, 0, "G", "G", "M"), attempt(2, 1, "M", None, "G"), attempt(3, 2, "B")]
    phases = phase_analysis(dives, [])
    assert phases["total_attempts"] == 3
    assert phases["phases"]["phase1"]["available_count"] == 1
    assert phases["phases"]["phase1"]["missing_count"] == 2
    assert phases["phases"]["phase2"]["available_count"] == 2


def test_descriptive_sample_labels_are_exact():
    assert [sample_label(value) for value in (0, 2, 5, 11, 12)] == [
        "no_data", "insufficient", "exploratory", "moderate_sample", "stronger_descriptive_sample"
    ]
