"""Dataset-revision caching regressions: analytics, journey milestones, sessions page."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import event

from app.api.v1 import journey as journey_api
from app.config import get_settings
from app.models.dive import Dive
from app.models.session import Session as TrainingSession
from app.services import dataset_cache
from app.services.diver_identity import get_primary_diver
from app.services.milestones import MilestoneDetector


@pytest.fixture(autouse=True)
def _clear_dataset_cache():
    dataset_cache.reset_cache()
    yield
    dataset_cache.reset_cache()


def seed_history(db, count=4):
    primary = get_primary_diver(db)
    dives = []
    for index in range(count):
        training = TrainingSession(date=(datetime(2026, 1, 1) + timedelta(days=index)).date())
        db.add(training)
        db.flush()
        dive = Dive(
            session_id=training.id, diver_id=primary.id, dive_code="103B",
            performance="G", performance_numeric=3, height="1m", position="B",
            is_lineup=False, dive_datetime=datetime(2026, 1, 1) + timedelta(days=index),
            updated_at=datetime(2026, 1, 1) + timedelta(days=index),
        )
        db.add(dive)
        db.flush()
        dives.append(dive)
    return dives


class _CountingDetector(MilestoneDetector):
    detect_calls = 0

    def detect_all(self):
        type(self).detect_calls += 1
        return super().detect_all()


@pytest.fixture()
def api_client_with_ttl(api_client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "analytics_cache_ttl_seconds", 60)
    return api_client


def test_analytics_second_call_serves_cache_and_edit_busts_it(api_client_with_ttl, test_db):
    dives = seed_history(test_db, 3)

    first = api_client_with_ttl.get("/api/v1/analytics/overall", params={"diver_scope": "all"})
    assert first.status_code == 200
    with patch.object(dataset_cache, "dive_dataset_revision", wraps=dataset_cache.dive_dataset_revision) as counter:
        second = api_client_with_ttl.get("/api/v1/analytics/overall", params={"diver_scope": "all"})
        assert second.status_code == 200
        assert second.json() == first.json()
        # Revision stamp is still checked per call (that's the invalidation).
        assert counter.call_count >= 1

    newest = max(dives, key=lambda dive: dive.id)
    newest.performance = "B"
    newest.performance_numeric = 1
    test_db.add(newest)
    test_db.commit()

    third = api_client_with_ttl.get("/api/v1/analytics/overall", params={"diver_scope": "all"})
    assert third.json()["success_rate"] != first.json()["success_rate"]


def test_journey_milestones_detect_once_per_dataset_state(api_client_with_ttl, test_db):
    seed_history(test_db, 3)

    with patch.object(journey_api, "MilestoneDetector", _CountingDetector):
        _CountingDetector.detect_calls = 0
        assert api_client_with_ttl.get("/api/v1/journey/milestones").status_code == 200
        assert api_client_with_ttl.get("/api/v1/journey").status_code == 200
        assert api_client_with_ttl.get("/api/v1/journey/breakthroughs").status_code == 200
        assert _CountingDetector.detect_calls == 1

    dive = test_db.query(Dive).first()
    dive.performance = "M"
    test_db.add(dive)
    test_db.commit()

    with patch.object(journey_api, "MilestoneDetector", _CountingDetector):
        _CountingDetector.detect_calls = 0
        assert api_client_with_ttl.get("/api/v1/journey/milestones").status_code == 200
        assert _CountingDetector.detect_calls == 1


def test_sessions_page_loads_dives_once(api_client_with_ttl, test_db):
    seed_history(test_db, 5)
    statements = []
    binder = test_db.get_bind()

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(" ".join(statement.split()))

    event.listen(binder, "before_cursor_execute", capture)
    try:
        response = api_client_with_ttl.get("/api/v1/sessions", params={"limit": 100})
    finally:
        event.remove(binder, "before_cursor_execute", capture)
    assert response.status_code == 200
    assert len(response.json()) == 5
    dive_selects = [
        s for s in statements
        if s.startswith("SELECT") and f" FROM dives" in s
    ]
    assert len(dive_selects) <= 1, f"expected the batched dive query only, saw {len(dive_selects)}"
    first = response.json()[0]
    assert first["total_dives"] >= 1
    assert "avg_performance" in first
