"""Competition lifecycle tests against the persisted event service contract."""
import pytest

from tests.competition_fixtures import competition, event_mgr


def test_create_event(competition, test_db):
    assert competition.id is not None
    assert competition.event_name == "State Championships 2026"
    assert competition.status == "DRAFT"
    test_db.expire_all()
    assert competition.scoring_rule.mandatory_groups == [1]


def test_create_round(event_mgr, competition):
    round_obj = event_mgr.create_round(competition.id, 1, "PRELIMINARY")
    assert round_obj.id is not None
    assert round_obj.event_id == competition.id
    assert round_obj.round_number == 1
    assert round_obj.round_type == "PRELIMINARY"


def test_invalid_round_is_rejected(event_mgr, competition):
    with pytest.raises(ValueError, match="Invalid round_type"):
        event_mgr.create_round(competition.id, 1, "Heat 1")
    with pytest.raises(ValueError, match="not found"):
        event_mgr.create_round(competition.id + 100, 1, "FINAL")


def test_register_competitor(event_mgr, competition):
    competitor = event_mgr.register_competitor(competition.id, "John Doe", "FRA")
    assert competitor.id is not None
    assert competitor.competitor_name == "John Doe"
    assert competitor.country_code == "FRA"
    assert [c.id for c in event_mgr.get_event_competitors(competition.id)] == [competitor.id]


def test_event_registration_lifecycle(event_mgr, competition):
    assert event_mgr.start_event_registration(competition.id)
    assert competition.status == "REGISTRATION"
    assert competition.start_date is not None
    assert event_mgr.close_event_registration(competition.id)
    assert competition.status == "ACTIVE"


def test_finalize_event(event_mgr, competition):
    result = event_mgr.finalize_event(competition.id)
    assert result == {"event_id": competition.id, "status": "COMPLETED"}
    assert competition.status == "COMPLETED"
    assert competition.end_date is not None
    with pytest.raises(ValueError, match="not found"):
        event_mgr.finalize_event(competition.id + 100)
