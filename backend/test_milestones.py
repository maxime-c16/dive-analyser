"""
Test suite for milestone detection engine.
Tests the narrative-based progress tracking system.
"""

from datetime import datetime, timedelta
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.milestones import (
    MilestoneDetector,
    JourneyNarrator,
    Milestone,
    MilestoneType,
    DiveAttempt,
)


def create_test_attempt(
    dive_code: str,
    height: str,
    performance: str,
    date: datetime,
    is_sync: bool = False,
    is_smack: bool = False,
) -> DiveAttempt:
    """Helper to create test dive attempts."""
    return DiveAttempt(
        uuid=f"uuid-{dive_code}-{height}-{date.timestamp()}",
        dive_code=dive_code,
        height=height,
        performance=performance,
        date=date,
        is_sync=is_sync,
        is_smack=is_smack,
    )


def test_import_validation():
    """Test 1: Verify all imports work correctly."""
    print("\n✅ TEST 1: Import Validation")
    print("   Testing imports of milestone classes...")

    assert MilestoneDetector is not None
    assert JourneyNarrator is not None
    assert MilestoneType is not None
    assert DiveAttempt is not None
    assert Milestone is not None

    print("   ✓ All imports successful")
    print(f"   ✓ MilestoneType has {len(list(MilestoneType))} types")


def test_milestone_type_enum():
    """Test 2: Verify all milestone types are defined."""
    print("\n✅ TEST 2: Milestone Type Enum")

    expected_types = {
        "FIRST_ATTEMPT",
        "FIRST_FROM_HEIGHT",
        "AVOIDED_DIVE_ATTEMPTED",
        "FIRST_SUCCESS",
        "FIRST_GOOD",
        "FIRST_PERFECT",
        "BREAKTHROUGH",
        "REDEMPTION",
        "COMEBACK",
        "PLATEAU_BROKEN",
        "NEW_HEIGHT_CONQUERED",
        "CONSISTENCY_ACHIEVED",
        "SUCCESS_STREAK",
        "PERFECT_STREAK",
        "TRAINING_STREAK",
        "SYNCHRO_FIRST_SUCCESS",
        "PERSONAL_BEST",
    }

    actual_types = {m.name for m in MilestoneType}

    print(f"   Expected: {len(expected_types)} types")
    print(f"   Found: {len(actual_types)} types")

    missing = expected_types - actual_types
    if missing:
        print(f"   ✗ Missing types: {missing}")
        raise AssertionError(f"Missing milestone types: {missing}")

    print("   ✓ All expected milestone types present")


def test_dive_attempt_properties():
    """Test 3: Verify DiveAttempt property calculations."""
    print("\n✅ TEST 3: DiveAttempt Properties")

    base_date = datetime(2024, 1, 1)

    # Test Failed
    failed = create_test_attempt("101B", "3m", "F", base_date)
    assert failed.performance_value == 0
    assert not failed.is_success
    assert not failed.is_good
    assert not failed.is_perfect
    print("   ✓ Failed (F) properties correct")

    # Test Bad
    bad = create_test_attempt("101B", "3m", "B", base_date)
    assert bad.performance_value == 1
    assert not bad.is_success
    print("   ✓ Bad (B) properties correct")

    # Test Medium
    medium = create_test_attempt("101B", "3m", "M", base_date)
    assert medium.performance_value == 2
    assert medium.is_success
    assert not medium.is_good
    print("   ✓ Medium (M) properties correct")

    # Test Good
    good = create_test_attempt("101B", "3m", "G", base_date)
    assert good.performance_value == 3
    assert good.is_success
    assert good.is_good
    assert not good.is_perfect
    print("   ✓ Good (G) properties correct")

    # Test Perfect
    perfect = create_test_attempt("101B", "3m", "P", base_date)
    assert perfect.performance_value == 4
    assert perfect.is_success
    assert perfect.is_good
    assert perfect.is_perfect
    print("   ✓ Perfect (P) properties correct")


def test_first_attempt_detection():
    """Test 4: Detect FIRST_ATTEMPT milestone."""
    print("\n✅ TEST 4: First Attempt Detection")

    base_date = datetime(2024, 1, 1)

    # Single first attempt
    attempts = [create_test_attempt("5253B", "10m", "F", base_date)]
    detector = MilestoneDetector(attempts)
    milestones = detector.detect_all()

    first_milestones = [m for m in milestones if m.type == MilestoneType.FIRST_ATTEMPT]
    assert len(first_milestones) == 1, f"Expected 1 FIRST_ATTEMPT, got {len(first_milestones)}"

    m = first_milestones[0]
    assert m.dive_code == "5253B"
    assert m.height == "10m"
    assert m.significance == 2
    assert "first time" in m.narrative.lower()

    print("   ✓ FIRST_ATTEMPT detected correctly")
    print(f"   ✓ Narrative: {m.narrative[:80]}...")


def test_first_success_detection():
    """Test 5: Detect FIRST_SUCCESS milestone."""
    print("\n✅ TEST 5: First Success Detection")

    base_date = datetime(2024, 1, 1)

    # Failed attempt, then success
    attempts = [
        create_test_attempt("5253B", "10m", "F", base_date),
        create_test_attempt("5253B", "10m", "B", base_date + timedelta(days=1)),
        create_test_attempt("5253B", "10m", "M", base_date + timedelta(days=2)),  # First success
    ]

    detector = MilestoneDetector(attempts)
    milestones = detector.detect_all()

    success_milestones = [m for m in milestones if m.type == MilestoneType.FIRST_SUCCESS]
    assert len(success_milestones) == 1

    m = success_milestones[0]
    assert m.failures_before == 2
    assert m.significance == 3
    assert "persistence paid off" in m.narrative.lower()

    print("   ✓ FIRST_SUCCESS detected with 2 prior failures")
    print(f"   ✓ Narrative: {m.narrative[:80]}...")


def test_breakthrough_detection():
    """Test 6: Detect BREAKTHROUGH milestone (success after 3+ failures)."""
    print("\n✅ TEST 6: Breakthrough Detection")

    base_date = datetime(2024, 1, 1)

    # 4 failures, then success
    attempts = [
        create_test_attempt("307C", "3m", "F", base_date),
        create_test_attempt("307C", "3m", "F", base_date + timedelta(days=1)),
        create_test_attempt("307C", "3m", "F", base_date + timedelta(days=2)),
        create_test_attempt("307C", "3m", "F", base_date + timedelta(days=3)),
        create_test_attempt("307C", "3m", "G", base_date + timedelta(days=4)),  # Breakthrough!
    ]

    detector = MilestoneDetector(attempts)
    milestones = detector.detect_all()

    breakthrough = [m for m in milestones if m.type == MilestoneType.BREAKTHROUGH]
    assert len(breakthrough) == 1

    m = breakthrough[0]
    assert m.failures_before == 4
    assert m.significance == 5  # Maximum significance
    assert "refusal to stop trying" in m.narrative.lower()
    assert "🔥" in m.emoji

    print("   ✓ BREAKTHROUGH detected after 4 consecutive failures")
    print(f"   ✓ Significance: {m.significance}/5 (maximum)")
    print(f"   ✓ Narrative: {m.narrative[:80]}...")


def test_redemption_detection():
    """Test 7: Detect REDEMPTION milestone (perfect after smack)."""
    print("\n✅ TEST 7: Redemption Detection")

    base_date = datetime(2024, 1, 1)

    # Smack followed by perfect
    attempts = [
        create_test_attempt("201C", "5m", "M", base_date, is_smack=True),
        create_test_attempt("201C", "5m", "P", base_date + timedelta(days=5)),  # Redemption!
    ]

    detector = MilestoneDetector(attempts)
    milestones = detector.detect_all()

    redemption = [m for m in milestones if m.type == MilestoneType.REDEMPTION]
    assert len(redemption) == 1

    m = redemption[0]
    assert m.significance == 5
    assert "belly flop to perfection" in m.narrative.lower()
    assert "🦅" in m.emoji
    assert m.days_since_last == 5

    print("   ✓ REDEMPTION detected: smack → perfect")
    print(f"   ✓ Days between: {m.days_since_last}")
    print(f"   ✓ Emoji: {m.emoji}")


def test_comeback_detection():
    """Test 8: Detect COMEBACK milestone (return after 30+ days)."""
    print("\n✅ TEST 8: Comeback Detection")

    base_date = datetime(2024, 1, 1)

    # Gap of 45 days
    attempts = [
        create_test_attempt("103B", "1m", "G", base_date),
        create_test_attempt("103B", "1m", "M", base_date + timedelta(days=45)),  # Comeback!
    ]

    detector = MilestoneDetector(attempts)
    milestones = detector.detect_all()

    comebacks = [m for m in milestones if m.type == MilestoneType.COMEBACK]
    assert len(comebacks) == 1

    m = comebacks[0]
    assert m.days_since_last == 45
    assert m.significance == 3
    assert "returned" in m.narrative.lower()
    assert "🔄" in m.emoji

    print("   ✓ COMEBACK detected after 45-day gap")
    print(f"   ✓ Days since last: {m.days_since_last}")


def test_avoided_dive_detection():
    """Test 9: Detect AVOIDED_DIVE_ATTEMPTED milestone."""
    print("\n✅ TEST 9: Avoided Dive Detection")

    base_date = datetime(2024, 1, 1)

    # High failure rate dive with long gap
    attempts = [
        create_test_attempt("5231D", "7m", "F", base_date),
        create_test_attempt("5231D", "7m", "F", base_date + timedelta(days=1)),
        create_test_attempt("5231D", "7m", "F", base_date + timedelta(days=2)),
        create_test_attempt("5231D", "7m", "B", base_date + timedelta(days=3)),
        # 30 day gap...
        create_test_attempt("5231D", "7m", "G", base_date + timedelta(days=35)),  # Avoided, then attempted!
    ]

    detector = MilestoneDetector(attempts)
    milestones = detector.detect_all()

    avoided = [m for m in milestones if m.type == MilestoneType.AVOIDED_DIVE_ATTEMPTED]
    assert len(avoided) == 1

    m = avoided[0]
    assert m.days_since_last == 32
    assert m.significance == 4
    assert "struggled" in m.narrative.lower()
    assert "🦁" in m.emoji

    print("   ✓ AVOIDED_DIVE_ATTEMPTED detected")
    print(f"   ✓ Gap: {m.days_since_last} days")
    print(f"   ✓ Failure rate: {(3/4)*100:.0f}%")


def test_success_streak_detection():
    """Test 10: Detect SUCCESS_STREAK milestone."""
    print("\n✅ TEST 10: Success Streak Detection")

    base_date = datetime(2024, 1, 1)

    # 5 consecutive successes
    attempts = [
        create_test_attempt("101B", "1m", "M", base_date),
        create_test_attempt("101B", "1m", "G", base_date + timedelta(days=1)),
        create_test_attempt("101B", "1m", "M", base_date + timedelta(days=2)),
        create_test_attempt("101B", "1m", "G", base_date + timedelta(days=3)),
        create_test_attempt("101B", "1m", "P", base_date + timedelta(days=4)),  # 5-streak!
    ]

    detector = MilestoneDetector(attempts)
    milestones = detector.detect_all()

    streaks = [m for m in milestones if m.type == MilestoneType.SUCCESS_STREAK and m.streak_length == 5]
    assert len(streaks) == 1

    m = streaks[0]
    assert m.significance == 3
    assert "🔥" in m.emoji

    print("   ✓ SUCCESS_STREAK (5x) detected")
    print(f"   ✓ Significance: {m.significance}")


def test_consistency_achieved():
    """Test 11: Detect CONSISTENCY_ACHIEVED milestone."""
    print("\n✅ TEST 11: Consistency Achieved Detection")

    base_date = datetime(2024, 1, 1)

    # 10 consistent Good performances
    attempts = [
        create_test_attempt("203C", "3m", "G", base_date + timedelta(days=i))
        for i in range(10)
    ]

    detector = MilestoneDetector(attempts)
    milestones = detector.detect_all()

    consistency = [m for m in milestones if m.type == MilestoneType.CONSISTENCY_ACHIEVED]
    assert len(consistency) == 1

    m = consistency[0]
    assert m.significance == 4
    assert "competition-ready" in m.narrative.lower()
    assert "🎯" in m.emoji

    print("   ✓ CONSISTENCY_ACHIEVED detected over 10 attempts")
    print(f"   ✓ Narrative: {m.narrative[:80]}...")


def test_journey_narrator():
    """Test 12: Journey Narrator generates summary."""
    print("\n✅ TEST 12: Journey Narrator")

    base_date = datetime(2024, 1, 1)

    # Complex journey with multiple milestones
    attempts = [
        create_test_attempt("5253B", "10m", "F", base_date),
        create_test_attempt("5253B", "10m", "F", base_date + timedelta(days=1)),
        create_test_attempt("5253B", "10m", "F", base_date + timedelta(days=2)),
        create_test_attempt("5253B", "10m", "G", base_date + timedelta(days=3)),  # Breakthrough
        create_test_attempt("5253B", "10m", "P", base_date + timedelta(days=4)),
        create_test_attempt("5253B", "10m", "P", base_date + timedelta(days=5)),
    ]

    detector = MilestoneDetector(attempts)
    milestones = detector.detect_all()
    narrator = JourneyNarrator(milestones)

    summary = narrator.generate_journey_summary()

    assert summary["total_milestones"] > 0
    assert summary["breakthroughs"] >= 1
    assert summary["most_recent"] is not None
    assert summary["timeline"] is not None

    print(f"   ✓ Total milestones: {summary['total_milestones']}")
    print(f"   ✓ Breakthroughs: {summary['breakthroughs']}")
    print(f"   ✓ Most significant: {summary['most_significant']['type']}")


def test_dive_story_generation():
    """Test 13: Generate complete dive story."""
    print("\n✅ TEST 13: Dive Story Generation")

    base_date = datetime(2024, 1, 1)

    # Journey from first attempt to consistency
    attempts = [
        create_test_attempt("307C", "3m", "F", base_date),
        create_test_attempt("307C", "3m", "M", base_date + timedelta(days=5)),
        create_test_attempt("307C", "3m", "G", base_date + timedelta(days=10)),
        create_test_attempt("307C", "3m", "G", base_date + timedelta(days=15)),
        create_test_attempt("307C", "3m", "P", base_date + timedelta(days=20)),
    ]

    detector = MilestoneDetector(attempts)
    all_milestones = detector.detect_all()
    narrator = JourneyNarrator(all_milestones)

    story = narrator.generate_dive_story("307C", "3m")

    assert story["dive_code"] == "307C"
    assert story["height"] == "3m"
    assert story["opening"] is not None
    assert story["closing"] is not None
    assert len(story["chapters"]) > 0

    print(f"   ✓ Dive story created for 307C from 3m")
    print(f"   ✓ Opening: {story['opening'][:70]}...")
    print(f"   ✓ Chapters: {len(story['chapters'])}")
    print(f"   ✓ Closing: {story['closing']}")


def test_empty_data_handling():
    """Test 14: Handle empty dive data."""
    print("\n✅ TEST 14: Empty Data Handling")

    # No attempts
    attempts = []
    detector = MilestoneDetector(attempts)
    milestones = detector.detect_all()

    assert len(milestones) == 0

    narrator = JourneyNarrator(milestones)
    summary = narrator.generate_journey_summary()

    assert summary["narrative"] is not None
    assert "beginner" in summary["narrative"].lower()

    print("   ✓ Empty data handled gracefully")
    print(f"   ✓ Narrative: {summary['narrative']}")


def test_milestone_to_dict():
    """Test 15: Milestone serialization to dict."""
    print("\n✅ TEST 15: Milestone Serialization")

    base_date = datetime(2024, 1, 15, 14, 30, 0)

    milestone = Milestone(
        type=MilestoneType.BREAKTHROUGH,
        dive_code="5253B",
        height="10m",
        date=base_date,
        title="Breakthrough on 5253B",
        narrative="You landed 5253B after 4 consecutive failed attempts.",
        failures_before=4,
        emoji="🔥",
        significance=5,
    )

    data = milestone.to_dict()

    assert data["type"] == "breakthrough"
    assert data["dive_code"] == "5253B"
    assert data["height"] == "10m"
    assert data["title"] == "Breakthrough on 5253B"
    assert data["significance"] == 5
    assert "2024-01-15" in data["date"]

    print("   ✓ Milestone serializes to dict correctly")
    print(f"   ✓ Keys: {list(data.keys())}")


def run_all_tests():
    """Run all tests."""
    print("\n" + "="*70)
    print("MILESTONE DETECTION ENGINE - TEST SUITE")
    print("="*70)

    tests = [
        test_import_validation,
        test_milestone_type_enum,
        test_dive_attempt_properties,
        test_first_attempt_detection,
        test_first_success_detection,
        test_breakthrough_detection,
        test_redemption_detection,
        test_comeback_detection,
        test_avoided_dive_detection,
        test_success_streak_detection,
        test_consistency_achieved,
        test_journey_narrator,
        test_dive_story_generation,
        test_empty_data_handling,
        test_milestone_to_dict,
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
    success = run_all_tests()
    sys.exit(0 if success else 1)
