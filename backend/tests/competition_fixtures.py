"""Shared isolated competition fixtures."""
import pytest

from app.models.fina_scoring_rule import FINAScoringRule
from app.services.event_manager import EventManager


@pytest.fixture
def event_mgr(test_db):
    return EventManager(test_db)


@pytest.fixture
def competition(event_mgr, test_db):
    rule = FINAScoringRule(
        event_type="test_springboard", event_name="Test Springboard",
        event_category="springboard", height="1m", gender="men",
        platform_type="springboard", mandatory_dive_count=1, mandatory_groups=[1],
    )
    test_db.add(rule)
    test_db.commit()
    return event_mgr.create_event("State Championships 2026", "TEST-2026", rule.id)


