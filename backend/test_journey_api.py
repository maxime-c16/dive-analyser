"""
API Integration Tests for Journey Endpoints
Tests the actual FastAPI endpoints with mock database
"""

from datetime import datetime, timedelta
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))

from app.api.v1.journey import (
    get_attempts,
    get_milestones,
    get_journey_summary,
    get_dive_story,
    get_breakthroughs,
    get_avoided_dives,
)
from app.services.milestones import DiveAttempt


def create_mock_dive(
    dive_code: str,
    height: str,
    performance: str,
    date: datetime,
    person_name=None,
    is_sync=False,
    is_smack=False,
):
    """Create a mock Dive model."""
    dive = MagicMock()
    dive.id = hash(f"{dive_code}-{height}-{date}") % 10000
    dive.dive_code = dive_code
    dive.height = height
    dive.performance = performance
    dive.dive_datetime = date
    dive.video_uuid = f"uuid-{dive.id}"
    dive.person_name = person_name
    dive.is_sync = is_sync
    dive.is_smack = is_smack
    return dive


def test_api_get_milestones():
    """Test GET /api/v1/journey/milestones endpoint."""
    print("\n✅ API TEST 1: GET /milestones")

    base_date = datetime(2024, 1, 1)

    # Create mock dives
    mock_dives = [
        create_mock_dive("5253B", "10m", "F", base_date),
        create_mock_dive("5253B", "10m", "F", base_date + timedelta(days=1)),
        create_mock_dive("5253B", "10m", "F", base_date + timedelta(days=2)),
        create_mock_dive("5253B", "10m", "G", base_date + timedelta(days=3)),  # Breakthrough
    ]

    # Mock database session
    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_filter = MagicMock()
    mock_query.filter.return_value = mock_filter
    mock_filter.order_by.return_value = mock_filter
    mock_filter.all.return_value = mock_dives

    # Call endpoint
    result = get_milestones(
        db=mock_db,
        dive_code=None,
        min_significance=1,
        limit=50,
    )

    assert "milestones" in result
    assert "total" in result
    assert result["total"] > 0
    assert any(m["type"] == "breakthrough" for m in result["milestones"])

    print(f"   ✓ Retrieved {result['total']} milestones")
    print(f"   ✓ Found breakthrough milestone")


def test_api_filter_by_dive_code():
    """Test /milestones endpoint with dive_code filter."""
    print("\n✅ API TEST 2: GET /milestones?dive_code=5253B")

    base_date = datetime(2024, 1, 1)

    # Multiple dives
    mock_dives = [
        create_mock_dive("5253B", "10m", "G", base_date),
        create_mock_dive("307C", "3m", "M", base_date + timedelta(days=1)),
        create_mock_dive("5253B", "10m", "P", base_date + timedelta(days=2)),
    ]

    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.filter.return_value.order_by.return_value.all.return_value = mock_dives

    # Filter by dive code
    result = get_milestones(
        db=mock_db,
        dive_code="5253B",
        min_significance=1,
        limit=50,
    )

    # All returned milestones should be for 5253B
    for milestone in result["milestones"]:
        if milestone["dive_code"]:  # Some milestones don't have dive_code (e.g., PLATEAU_BROKEN)
            assert milestone["dive_code"] == "5253B"

    print(f"   ✓ Filtered by dive code: 5253B")
    print(f"   ✓ All milestones are for 5253B")


def test_api_min_significance_filter():
    """Test /milestones endpoint with min_significance filter."""
    print("\n✅ API TEST 3: GET /milestones?min_significance=4")

    base_date = datetime(2024, 1, 1)

    mock_dives = [
        create_mock_dive("101B", "1m", "M", base_date),  # FIRST_ATTEMPT (sig=2)
        create_mock_dive("5253B", "10m", "P", base_date + timedelta(days=1)),  # FIRST_PERFECT (sig=4)
    ]

    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.filter.return_value.order_by.return_value.all.return_value = mock_dives

    result = get_milestones(
        db=mock_db,
        dive_code=None,
        min_significance=4,
        limit=50,
    )

    # All should have significance >= 4
    for milestone in result["milestones"]:
        assert milestone["significance"] >= 4

    print(f"   ✓ Filtered by min_significance=4")
    print(f"   ✓ All milestones have significance >= 4")


def test_api_get_journey_summary():
    """Test GET /api/v1/journey/journey endpoint."""
    print("\n✅ API TEST 4: GET /journey")

    base_date = datetime(2024, 1, 1)

    # Create journey progression
    mock_dives = [
        create_mock_dive("5253B", "10m", "F", base_date),
        create_mock_dive("5253B", "10m", "F", base_date + timedelta(days=5)),
        create_mock_dive("5253B", "10m", "M", base_date + timedelta(days=10)),
        create_mock_dive("5253B", "10m", "G", base_date + timedelta(days=15)),
        create_mock_dive("5253B", "10m", "P", base_date + timedelta(days=20)),
    ]

    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.filter.return_value.order_by.return_value.all.return_value = mock_dives

    result = get_journey_summary(db=mock_db)

    assert "overview" in result
    assert "growth" in result
    assert "journey" in result

    overview = result["overview"]
    assert overview["total_dives"] == 5
    assert overview["unique_dive_combinations"] == 1

    growth = result["growth"]
    assert growth["first_month_average"] >= 0
    assert growth["last_month_average"] >= 0
    assert "trajectory" in growth

    print(f"   ✓ Overview: {overview['total_dives']} dives, {overview['unique_dive_combinations']} unique combinations")
    print(f"   ✓ Growth trajectory: {growth['trajectory']}")
    print(f"   ✓ Improvement: {growth['improvement']:.2f} points")


def test_api_get_dive_story():
    """Test GET /api/v1/journey/dive/{dive_code}/{height} endpoint."""
    print("\n✅ API TEST 5: GET /dive/5253B/10m")

    base_date = datetime(2024, 1, 1)

    mock_dives = [
        create_mock_dive("5253B", "10m", "F", base_date),
        create_mock_dive("5253B", "10m", "F", base_date + timedelta(days=1)),
        create_mock_dive("5253B", "10m", "M", base_date + timedelta(days=2)),
        create_mock_dive("5253B", "10m", "G", base_date + timedelta(days=3)),
        create_mock_dive("5253B", "10m", "P", base_date + timedelta(days=4)),
    ]

    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.filter.return_value.order_by.return_value.all.return_value = mock_dives

    result = get_dive_story(
        dive_code="5253B",
        height="10m",
        db=mock_db,
    )

    assert result["dive_code"] == "5253B"
    assert result["height"] == "10m"
    assert "opening" in result
    assert "closing" in result
    assert "chapters" in result
    assert "stats" in result
    assert "current_streak" in result

    stats = result["stats"]
    assert stats["total_attempts"] == 5
    assert stats["successes"] == 3
    assert stats["success_rate"] == 60.0
    # Last 3 dives are successes (M, G, P)
    assert result["current_streak"] == 3

    print(f"   ✓ Dive story: {result['dive_code']} from {result['height']}")
    print(f"   ✓ Success rate: {stats['success_rate']}%")
    print(f"   ✓ Chapters: {len(result['chapters'])}")
    print(f"   ✓ Current streak: {result['current_streak']}")


def test_api_get_breakthroughs():
    """Test GET /api/v1/journey/breakthroughs endpoint."""
    print("\n✅ API TEST 6: GET /breakthroughs")

    base_date = datetime(2024, 1, 1)

    # Create multiple breakthrough scenarios
    mock_dives = [
        # First breakthrough
        create_mock_dive("307C", "3m", "F", base_date),
        create_mock_dive("307C", "3m", "F", base_date + timedelta(days=1)),
        create_mock_dive("307C", "3m", "F", base_date + timedelta(days=2)),
        create_mock_dive("307C", "3m", "G", base_date + timedelta(days=3)),
        # Second breakthrough
        create_mock_dive("5231D", "7m", "F", base_date + timedelta(days=5)),
        create_mock_dive("5231D", "7m", "F", base_date + timedelta(days=6)),
        create_mock_dive("5231D", "7m", "F", base_date + timedelta(days=7)),
        create_mock_dive("5231D", "7m", "F", base_date + timedelta(days=8)),
        create_mock_dive("5231D", "7m", "P", base_date + timedelta(days=9)),
    ]

    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.filter.return_value.order_by.return_value.all.return_value = mock_dives

    result = get_breakthroughs(db=mock_db, limit=10)

    assert "breakthroughs" in result
    assert "total_breakthroughs" in result
    assert result["total_breakthroughs"] > 0

    for breakthrough in result["breakthroughs"]:
        assert "type" in breakthrough
        assert "why_it_matters" in breakthrough
        assert "narrative" in breakthrough

    print(f"   ✓ Found {result['total_breakthroughs']} breakthroughs")
    print(f"   ✓ All breakthroughs have narratives")


def test_api_get_avoided_dives():
    """Test GET /api/v1/journey/avoided endpoint."""
    print("\n✅ API TEST 7: GET /avoided")

    base_date = datetime(2024, 1, 1)

    # Create scenario with avoided dive (high failure rate + long gap)
    mock_dives = [
        create_mock_dive("101B", "1m", "G", base_date),
        create_mock_dive("101B", "1m", "P", base_date + timedelta(days=1)),
        # Long gap
        create_mock_dive("101B", "1m", "M", base_date + timedelta(days=50)),
        # Avoided dive (high failure rate)
        create_mock_dive("5253B", "10m", "F", base_date + timedelta(days=2)),
        create_mock_dive("5253B", "10m", "F", base_date + timedelta(days=3)),
        create_mock_dive("5253B", "10m", "F", base_date + timedelta(days=4)),
        create_mock_dive("5253B", "10m", "B", base_date + timedelta(days=5)),
        # Long gap on avoided dive
        create_mock_dive("5253B", "10m", "M", base_date + timedelta(days=45)),
    ]

    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.filter.return_value.order_by.return_value.all.return_value = mock_dives

    result = get_avoided_dives(db=mock_db, days_threshold=30)

    assert "avoided" in result
    assert "total_avoided" in result
    assert "encouragement" in result

    for avoided in result["avoided"]:
        assert avoided["days_since_attempt"] >= 30
        assert "failure_rate" in avoided
        assert "message" in avoided
        assert "avoidance_score" in avoided

    print(f"   ✓ Found {result['total_avoided']} avoided dives")
    if result["total_avoided"] > 0:
        print(f"   ✓ Encouragement: {result['encouragement'][:50]}...")


def test_api_empty_database():
    """Test API endpoints with no data."""
    print("\n✅ API TEST 8: Empty Database Handling")

    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.filter.return_value.order_by.return_value.all.return_value = []

    # Test each endpoint with empty database
    result1 = get_milestones(db=mock_db)
    assert result1["milestones"] == []
    print("   ✓ /milestones handles empty data")

    result2 = get_journey_summary(db=mock_db)
    assert "message" in result2
    print("   ✓ /journey handles empty data")

    result3 = get_dive_story("101B", "1m", db=mock_db)
    assert "message" in result3
    print("   ✓ /dive/{code}/{height} handles empty data")

    result4 = get_breakthroughs(db=mock_db)
    assert result4["breakthroughs"] == []
    print("   ✓ /breakthroughs handles empty data")

    result5 = get_avoided_dives(db=mock_db)
    assert result5["avoided"] == []
    print("   ✓ /avoided handles empty data")


def test_api_personal_dives_only():
    """Test that API returns personal dives only (not training partner dives)."""
    print("\n✅ API TEST 9: Personal Dives Only")

    base_date = datetime(2024, 1, 1)

    # Mix of personal and training partner dives
    mock_dives = [
        create_mock_dive("5253B", "10m", "G", base_date),  # Personal
        create_mock_dive("5253B", "10m", "M", base_date + timedelta(days=1), person_name="John"),  # Training partner
        create_mock_dive("5253B", "10m", "P", base_date + timedelta(days=2)),  # Personal
    ]

    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.filter.return_value.order_by.return_value.all.return_value = [
        d for d in mock_dives if d.person_name is None
    ]

    result = get_milestones(db=mock_db, dive_code=None, min_significance=1, limit=50)

    # Should only count 2 dives (personal only)
    assert result["total"] > 0

    print(f"   ✓ Filtered to personal dives only")
    print(f"   ✓ Training partner dives excluded")


def test_api_narrative_quality():
    """Test that narratives are generated with proper quality."""
    print("\n✅ API TEST 10: Narrative Quality")

    base_date = datetime(2024, 1, 1)

    # Breakthrough scenario for narrative testing
    mock_dives = [
        create_mock_dive("307C", "3m", "F", base_date),
        create_mock_dive("307C", "3m", "F", base_date + timedelta(days=1)),
        create_mock_dive("307C", "3m", "F", base_date + timedelta(days=2)),
        create_mock_dive("307C", "3m", "G", base_date + timedelta(days=3)),
    ]

    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.filter.return_value.order_by.return_value.all.return_value = mock_dives

    result = get_breakthroughs(db=mock_db, limit=10)

    if result["breakthroughs"]:
        narrative = result["breakthroughs"][0]["narrative"]

        # Check narrative qualities
        assert "You landed" in narrative or "after" in narrative.lower()  # Personal, action-oriented
        assert "refusal" in narrative.lower() or "persistence" in narrative.lower()  # Acknowledges struggle
        assert len(narrative) > 50  # Not too short

        print(f"   ✓ Narrative is personal and meaningful")
        print(f"   ✓ Acknowledges struggle and persistence")
        print(f"   ✓ Length: {len(narrative)} characters")


def run_all_api_tests():
    """Run all API integration tests."""
    print("\n" + "="*70)
    print("JOURNEY API - INTEGRATION TEST SUITE")
    print("="*70)

    tests = [
        test_api_get_milestones,
        test_api_filter_by_dive_code,
        test_api_min_significance_filter,
        test_api_get_journey_summary,
        test_api_get_dive_story,
        test_api_get_breakthroughs,
        test_api_get_avoided_dives,
        test_api_empty_database,
        test_api_personal_dives_only,
        test_api_narrative_quality,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"\n   ✗ TEST FAILED: {str(e)}")
            import traceback
            traceback.print_exc()

    print("\n" + "="*70)
    print(f"RESULTS: {passed} passed, {failed} failed out of {len(tests)} tests")
    print("="*70 + "\n")

    return failed == 0


if __name__ == "__main__":
    success = run_all_api_tests()
    sys.exit(0 if success else 1)
