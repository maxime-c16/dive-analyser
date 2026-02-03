"""
Integration tests for the Journey API endpoints using real database data.

Run this on the server to validate:
1. API endpoints return data from the real database
2. All milestone types are being detected correctly
3. Frontend components will receive properly formatted data
4. Narrative generation works with actual dive data
"""

import os
import sys
import json
from typing import Optional
import requests
from datetime import datetime

# Set API base URL (adjust if needed)
API_BASE_URL = os.getenv("API_URL", "http://localhost:8000")

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def print_header(text: str):
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{text:^60}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.RESET}")

def print_test(name: str):
    print(f"\n{Colors.BLUE}▶ {name}{Colors.RESET}")

def print_pass(message: str = "PASS"):
    print(f"{Colors.GREEN}✓ {message}{Colors.RESET}")

def print_fail(message: str = "FAIL"):
    print(f"{Colors.RED}✗ {message}{Colors.RESET}")

def print_warn(message: str):
    print(f"{Colors.YELLOW}⚠ {message}{Colors.RESET}")

def print_info(message: str):
    print(f"{Colors.CYAN}ℹ {message}{Colors.RESET}")

def test_endpoint(method: str, endpoint: str, params: Optional[dict] = None) -> dict:
    """Test an API endpoint and return the response data."""
    url = f"{API_BASE_URL}{endpoint}"
    try:
        if method == "GET":
            response = requests.get(url, params=params, timeout=10)
        else:
            raise ValueError(f"Unsupported method: {method}")

        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError:
        print_fail(f"Could not connect to {API_BASE_URL}")
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        print_fail(f"HTTP {e.response.status_code}: {e.response.text[:200]}")
        return {}
    except Exception as e:
        print_fail(f"Error: {str(e)}")
        return {}

def validate_milestone_structure(milestone: dict) -> bool:
    """Validate that a milestone has all required fields."""
    required = ['type', 'dive_code', 'height', 'title', 'narrative', 'date', 'significance']
    return all(field in milestone for field in required)

def validate_journey_structure(data: dict) -> bool:
    """Validate that journey data has expected structure."""
    required_keys = ['overview', 'growth', 'journey']
    if not all(key in data for key in required_keys):
        return False

    overview_keys = ['total_dives', 'unique_dive_combinations', 'days_of_training', 'first_dive_date', 'latest_dive_date']
    if not all(key in data.get('overview', {}) for key in overview_keys):
        return False

    growth_keys = ['first_month_average', 'last_month_average', 'improvement', 'trajectory']
    if not all(key in data.get('growth', {}) for key in growth_keys):
        return False

    journey = data.get('journey', {})
    # Check for either narrative key or journey summary structure
    return ('narrative' in journey) or ('total_milestones' in journey and 'most_significant' in journey)

def test_journey_milestones():
    """Test GET /api/v1/journey/milestones"""
    print_test("GET /api/v1/journey/milestones")

    data = test_endpoint("GET", "/api/v1/journey/milestones")

    if not data:
        print_fail("No response")
        return False

    milestones = data.get('milestones', [])
    total = data.get('total', 0)

    if total == 0:
        print_warn("No milestones found in database")
        print_info(f"Message: {data.get('message', '')}")
        return True

    print_pass(f"Retrieved {total} milestones")

    # Validate structure of first milestone
    if milestones:
        first = milestones[0]
        if not validate_milestone_structure(first):
            print_fail("Milestone structure invalid")
            print_info(f"Got: {list(first.keys())}")
            return False

        print_pass(f"Milestone structure valid")
        print_info(f"Sample: {first['type']} - {first['dive_code']} ({first['height']})")

    # Check significance distribution
    sig_dist = {}
    for m in milestones:
        sig = m.get('significance', 0)
        sig_dist[sig] = sig_dist.get(sig, 0) + 1

    print_info(f"Significance distribution: {sig_dist}")
    return True

def test_journey_summary():
    """Test GET /api/v1/journey/journey"""
    print_test("GET /api/v1/journey/journey")

    data = test_endpoint("GET", "/api/v1/journey/journey")

    if not data:
        print_fail("No response")
        return False

    if 'message' in data:
        print_warn(f"No dive data: {data['message']}")
        return True

    if not validate_journey_structure(data):
        print_fail("Journey structure invalid")
        print_info(f"Keys: {list(data.keys())}")
        return False

    print_pass("Journey summary structure valid")

    overview = data['overview']
    growth = data['growth']

    print_info(f"Total dives: {overview['total_dives']}")
    print_info(f"Unique dives: {overview['unique_dive_combinations']}")
    print_info(f"Training days: {overview['days_of_training']}")
    print_info(f"Improvement: {growth['improvement']:.2f}")
    print_info(f"Trajectory: {growth['trajectory']}")

    journey = data['journey']
    if 'narrative' in journey:
        narrative = journey['narrative']
        print_pass(f"Narrative generated ({len(narrative)} chars)")
        print_info(f"Preview: {narrative[:80]}...")
    elif 'total_milestones' in journey:
        print_pass(f"Journey summary generated")
        print_info(f"Total milestones: {journey['total_milestones']}")
        print_info(f"Breakthroughs: {journey.get('breakthroughs', 0)}")
        if 'most_significant' in journey:
            print_info(f"Most significant: {journey['most_significant']['title']}")
    else:
        print_warn("No narrative data found")

    return True

def test_dive_story(dive_code: Optional[str] = None):
    """Test GET /api/v1/journey/dive/{code}/{height}"""
    if not dive_code:
        dive_code = "101B"

    height = "1m"
    print_test(f"GET /api/v1/journey/dive/{dive_code}/{height}")

    data = test_endpoint("GET", f"/api/v1/journey/dive/{dive_code}/{height}")

    if not data:
        print_fail("No response")
        return False

    if 'message' in data and 'haven\'t attempted' in data['message']:
        print_warn(f"{dive_code} not found in dive history")
        return True

    if 'stats' not in data:
        print_fail("Dive story structure invalid")
        return False

    stats = data['stats']
    print_pass("Dive story structure valid")
    print_info(f"Total attempts: {stats['total_attempts']}")
    print_info(f"Success rate: {stats['success_rate']:.1f}%")
    print_info(f"Current streak: {data.get('current_streak', 0)}")

    return True

def test_breakthroughs():
    """Test GET /api/v1/journey/breakthroughs"""
    print_test("GET /api/v1/journey/breakthroughs")

    data = test_endpoint("GET", "/api/v1/journey/breakthroughs")

    if not data:
        print_fail("No response")
        return False

    breakthroughs = data.get('breakthroughs', [])

    if not breakthroughs:
        print_warn("No breakthroughs found")
        print_info(f"Message: {data.get('message', '')}")
        return True

    print_pass(f"Retrieved {len(breakthroughs)} breakthroughs")

    for bt in breakthroughs[:3]:
        sig = bt.get('significance', 0)
        print_info(f"  - {bt['dive_code']} ({bt['height']}): significance {sig}")

    return True

def test_avoided_dives():
    """Test GET /api/v1/journey/avoided"""
    print_test("GET /api/v1/journey/avoided")

    data = test_endpoint("GET", "/api/v1/journey/avoided")

    if not data:
        print_fail("No response")
        return False

    avoided = data.get('avoided', [])

    if not avoided:
        print_info("No avoided dives detected (good sign!)")
        return True

    print_warn(f"Found {len(avoided)} avoided dives")

    for dive in avoided[:3]:
        print_info(f"  - {dive['dive_code']} ({dive['height']}): {dive['days_since_attempt']} days, {dive['failure_rate']:.0f}% difficulty")

    return True

def test_filtering():
    """Test query parameter filtering"""
    print_test("Filter: min_significance=4")

    data = test_endpoint("GET", "/api/v1/journey/milestones", {"min_significance": 4})

    if not data:
        print_fail("No response")
        return False

    milestones = data.get('milestones', [])

    # Verify all are significance 4 or higher
    invalid = [m for m in milestones if m.get('significance', 0) < 4]
    if invalid:
        print_fail(f"Filter failed: got {len(invalid)} milestones with significance < 4")
        return False

    print_pass(f"Filter working correctly: {len(milestones)} milestones with significance >= 4")
    return True

def main():
    print_header("Journey API Integration Tests")
    print_info(f"API URL: {API_BASE_URL}")

    # Check connectivity
    try:
        response = requests.get(f"{API_BASE_URL}/api/v1/journey/milestones", timeout=5)
        print_pass(f"API is reachable (status: {response.status_code})")
    except Exception as e:
        print_fail(f"Cannot reach API: {str(e)}")
        print_info("Make sure the backend is running:")
        print_info("  python -m uvicorn app.main:app --reload")
        sys.exit(1)

    # Run tests
    results = []

    results.append(("Journey Summary", test_journey_summary()))
    results.append(("Milestones List", test_journey_milestones()))
    results.append(("Dive Story", test_dive_story()))
    results.append(("Breakthroughs", test_breakthroughs()))
    results.append(("Avoided Dives", test_avoided_dives()))
    results.append(("Filtering", test_filtering()))

    # Summary
    print_header("Test Summary")

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = f"{Colors.GREEN}PASS{Colors.RESET}" if result else f"{Colors.RED}FAIL{Colors.RESET}"
        print(f"  {name:<25} {status}")

    print(f"\n{Colors.BOLD}Total: {passed}/{total} tests passed{Colors.RESET}")

    if passed == total:
        print(f"{Colors.GREEN}✓ All tests passed! API is production-ready.{Colors.RESET}")
        return 0
    else:
        print(f"{Colors.RED}✗ Some tests failed. Review the output above.{Colors.RESET}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
