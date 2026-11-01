"""Library height facets: the filter select told the truth.

profil 12 C1 (2026-11-01): once height=3m was applied, the Height select
listed only All/3m — its options came from the loaded page — and after
switching to All the options stayed stale until a cold reload answered the
other list for the same URL. Options now come from one DISTINCT query over
the authorized scope with every OTHER filter applied and the height filter
absent: same URL, same options; switching the dimension never needs /All.
"""

from datetime import datetime, timedelta

import pytest

from app.models.dive import Dive
from app.models.session import Session as TrainingSession
from app.services.diver_identity import get_primary_diver


def _seed(db, rows):
    primary = get_primary_diver(db)
    for date, code, height, performance in rows:
        session = db.query(TrainingSession).filter_by(date=date.date()).one_or_none()
        if session is None:
            session = TrainingSession(date=date.date())
            db.add(session)
            db.flush()
        db.add(Dive(
            session_id=session.id, diver_id=primary.id, dive_code=code,
            performance=performance, performance_numeric=0, height=height,
            is_lineup=False, dive_datetime=date,
        ))
    db.commit()


@pytest.fixture
def failed_fives(test_db):
    now = datetime.utcnow()
    _seed(test_db, [
        (now - timedelta(days=10, hours=3), "101B", "1m", "F"),
        (now - timedelta(days=9, hours=3), "201A", "1m", "F"),
        (now - timedelta(days=8, hours=3), "101B", "5m", "F"),
        (now - timedelta(days=7, hours=3), "301B", "5m", "F"),
        (now - timedelta(days=6, hours=3), "401B", "5m", "F"),
        (now - timedelta(days=5, hours=3), "101A", "3m", "G"),
        (now - timedelta(days=4, hours=3), "201C", "3mp", "G"),
    ])


def test_facets_answer_every_height_the_scope_really_has(api_client, test_db, failed_fives):
    heights = api_client.get("/api/v1/dives/library/facets").json()["heights"]
    assert heights == ["1m", "3m", "3mp", "5m"]


def test_other_filters_apply_and_height_never_gates_its_own_dimension(api_client, test_db, failed_fives):
    # Under F·Failed the scope really contains 1m and 5m; the select must say
    # so whether or not a height is currently selected — the exact repeatability
    # profil 12 measured (1: options shrink; 2: stale after switching; 3: only
    # a cold reload was right).
    filtered = api_client.get("/api/v1/dives/library/facets", params={"performance": "F"}).json()["heights"]
    assert filtered == ["1m", "5m"]

    with_height = api_client.get(
        "/api/v1/dives/library/facets", params={"performance": "F", "height": "3m"},
    ).json()["heights"]
    assert with_height == filtered, "same other filters, same options"

    switched = api_client.get(
        "/api/v1/dives/library/facets", params={"performance": "F", "height": "5m"},
    ).json()["heights"]
    assert switched == filtered


def test_facets_stay_empty_on_a_scope_without_rows_and_are_scope_safe(api_client, test_db):
    now = datetime.utcnow()
    from app.models.diver import Diver
    from app.services.diver_identity import get_primary_diver
    db = test_db
    stranger = Diver(display_name="Stranger", canonical_name="Stranger")
    session = TrainingSession(date=(now - timedelta(days=2)).date())
    db.add_all([stranger, session])
    db.flush()
    db.add(Dive(session_id=session.id, diver_id=stranger.id, dive_code="101B",
                performance="G", performance_numeric=0, height="7m", is_lineup=False,
                dive_datetime=now, visibility="public"))
    db.commit()
    # Nothing of my own scope: the facet is empty, not mislabeled with weeds.
    assert api_client.get("/api/v1/dives/library/facets").json()["heights"] == []
