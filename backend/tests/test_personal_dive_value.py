from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.models.dive import Dive
from app.models.dive_modifier import DiveModifier
from app.models.session import Session as SessionModel
from app.services.diver_identity import resolve_diver
from app.services.personal_dive_value import (
    PersonalDiveValueError,
    PersonalDiveValueService,
    VERSION,
    technical_component,
)


def _seed(test_db, ratings=("B", "M", "G", "P"), code="103B", start=datetime(2026, 1, 1)):
    primary = resolve_diver(test_db, None)
    session = SessionModel(date=start.date())
    test_db.add(session); test_db.flush()
    dives = []
    for index, rating in enumerate(ratings):
        dive = Dive(session_id=session.id, dive_code=code, position=code[-1], performance=rating, performance_numeric={"F": 0, "B": 1, "M": 2, "G": 3, "P": 4}[rating], height="1m", platform_type="springboard", is_lineup=False, is_sync=False, diver_id=primary.id, dive_datetime=start + timedelta(days=index), video_uuid=f"personal-value-{code}-{start.date()}-{index:020d}")
        test_db.add(dive); dives.append(dive)
    test_db.commit()
    return primary, dives


def test_deterministic_chronological_explanation_and_contributions(test_db):
    _, dives = _seed(test_db, ("B", "M", "G", "G", "P", "P"))
    service = PersonalDiveValueService(test_db)
    first = service.calculate(dives[-1]); second = service.calculate(dives[-1])
    assert first["version"] == VERSION
    assert first["value"] == second["value"]
    assert first["confidence"]["level"] == "medium"
    assert first["components"]["same_dive_relative"]["percentile"] == 100.0
    assert round(sum(component["weighted_contribution"] for component in first["components"].values()), 1) == first["value"]
    assert sum(PersonalDiveValueService.configuration()["weights"].values()) == 1.0
    assert 0 <= first["value"] <= 100


def test_no_future_leakage_and_equal_timestamp_id_order(test_db):
    _, dives = _seed(test_db, ("B", "P"))
    dives[1].dive_datetime = dives[0].dive_datetime
    test_db.commit()
    first = PersonalDiveValueService(test_db).calculate(dives[0])
    second = PersonalDiveValueService(test_db).calculate(dives[1])
    assert first["confidence"]["same_dive_support"] == 0
    assert second["confidence"]["same_dive_support"] == 1


def test_zero_guard_monotonic_score_and_undefined_dd(test_db):
    _, dives = _seed(test_db, ("F", "G"))
    service = PersonalDiveValueService(test_db)
    assert service.calculate(dives[0])["value"] <= 20
    assert service.calculate(dives[1])["value"] > service.calculate(dives[0])["value"]
    _, undefined = _seed(test_db, ("G",), code="999B", start=datetime(2026, 2, 1))
    result = service.calculate(undefined[0])
    assert result["value"] is None
    assert result["confidence"]["level"] == "undefined"
    assert technical_component(7.0, 1.2) < technical_component(7.0, 2.4)


def test_primary_scope_and_pattern_excludes_current_and_future(test_db):
    primary, dives = _seed(test_db, ("B", "M", "G", "P", "G", "P"))
    other = resolve_diver(test_db, "Other")
    other_dive = Dive(session_id=dives[0].session_id, dive_code="103B", position="B", performance="P", performance_numeric=4, height="1m", is_lineup=False, is_sync=False, diver_id=other.id, person_name="Other", dive_datetime=dives[-1].dive_datetime + timedelta(days=1), video_uuid="other-personal-value")
    test_db.add(other_dive); test_db.add(DiveModifier(dive_id=dives[3].id, modifier_code="DB", modifier_type="drill")); test_db.commit()
    service = PersonalDiveValueService(test_db)
    with pytest.raises(PersonalDiveValueError):
        service.calculate(other_dive)
    patterns = service.patterns(dives[-1])
    assert all(item["attempt_id"] < dives[-1].id for item in patterns)
    assert len(patterns) <= 3


def test_api_disabled_version_limit_and_primary_isolation(api_client, test_db, monkeypatch):
    import app.api.v1.personal_dive_value as api
    primary, dives = _seed(test_db, ("B", "M", "G", "P", "P", "P"))
    headers = {"X-API-Key": "personal-value-test-key"}
    disabled = api_client.get(f"/api/v1/dives/{dives[-1].id}/personal-value", headers=headers)
    assert disabled.status_code == 404
    monkeypatch.setattr(api, "get_settings", lambda: SimpleNamespace(personal_dive_value_enabled=True))
    ok = api_client.get(f"/api/v1/dives/{dives[-1].id}/personal-value", headers=headers)
    assert ok.status_code == 200 and ok.json()["value"] is not None
    public_read = api_client.get(f"/api/v1/dives/{dives[-1].id}/personal-value")
    assert public_read.status_code == 200
    invalid_version = api_client.get(f"/api/v1/dives/{dives[-1].id}/personal-value?version=v2", headers=headers)
    assert invalid_version.status_code == 422
    bounded = api_client.get("/api/v1/dive-analysis/103B/personal-values?limit=251", headers=headers)
    assert bounded.status_code == 422
    collection = api_client.get("/api/v1/dive-analysis/103B/personal-values?limit=2", headers=headers)
    assert collection.status_code == 200 and len(collection.json()["values"]) == 2
    other = resolve_diver(test_db, "Other API")
    foreign = Dive(session_id=dives[0].session_id, dive_code="103B", position="B", performance="P", performance_numeric=4, height="1m", is_lineup=False, is_sync=False, diver_id=other.id, person_name="Other API", dive_datetime=datetime(2026, 3, 1), video_uuid="foreign-api-personal-value")
    test_db.add(foreign); test_db.commit()
    forbidden = api_client.get(f"/api/v1/dives/{foreign.id}/personal-value", headers=headers)
    assert forbidden.status_code == 403
    straight_dive = Dive(session_id=dives[0].session_id, dive_code="100B", position="B", performance="G", performance_numeric=3, height="1m", is_lineup=False, is_sync=False, diver_id=primary.id, dive_datetime=datetime(2026, 3, 2), video_uuid="straight-api-personal-value")
    test_db.add(straight_dive); test_db.commit()
    straight = api_client.get(f"/api/v1/dives/{straight_dive.id}/personal-value", headers=headers)
    assert straight.status_code == 422
    straight_collection = api_client.get("/api/v1/dive-analysis/100B/personal-values", headers=headers)
    assert straight_collection.status_code == 422
    patterns = api_client.get(f"/api/v1/dives/{dives[-1].id}/personal-value/patterns", headers=headers)
    assert patterns.status_code == 200
    assert len(patterns.json()["matches"]) <= 3
    if patterns.json()["matches"]:
        assert patterns.json()["matches"][0]["dive_code"] == "103B"
        assert "trailing_scores" in patterns.json()["matches"][0]
