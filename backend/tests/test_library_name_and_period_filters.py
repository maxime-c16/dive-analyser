"""Library figure-name and period filters: bounded, scope-safe, pagination-stable.

The Library UI derives exact candidate codes from the dive-naming catalog and
sends them as `code_filter`; range searches send `date_from`/`date_to`. Both
apply before paging so every Library page and the per-code aggregates cover
the same authorized scope, and the IN-list is validated with a hard cap so a
request can never smuggle an unbounded probe.
"""

from datetime import datetime, timedelta

import pytest

from app.models.dive import Dive
from app.models.session import Session as TrainingSession
from app.services.diver_identity import get_primary_diver
from app.services.library_query import CODE_FILTER_MAX, sanitize_code_filter


def _seed(db, rows):
    primary = get_primary_diver(db)
    for row in rows:
        date, code, height = row[:3]
        caption = row[3] if len(row) > 3 else None
        session = db.query(TrainingSession).filter_by(date=date.date()).one_or_none()
        if session is None:
            session = TrainingSession(date=date.date())
            db.add(session)
            db.flush()
        db.add(Dive(
            session_id=session.id, diver_id=primary.id, dive_code=code,
            performance="G", performance_numeric=0, height=height,
            is_lineup=False, dive_datetime=date, raw_caption=caption,
        ))
    db.commit()


@pytest.fixture
def two_codes(test_db):
    now = datetime.utcnow()
    _seed(test_db, [
        (now - timedelta(days=10, hours=3), "101A", "1m"),
        (now - timedelta(days=20, hours=3), "201C", "1m"),
        (now - timedelta(days=30, hours=3), "201C", "3m"),
        (now - timedelta(days=40, hours=3), "202A", "3m"),
    ])


def test_code_filter_returns_only_exact_codes(api_client, test_db, two_codes):
    rows = api_client.get("/api/v1/dives/library", params={"code_filter": "201c"}).json()
    assert [item["dive_code"] for item in rows["items"]] == ["201C", "201C"]
    assert rows["next_cursor"] is None

    payload = api_client.get("/api/v1/dives/library/codes", params={"code_filter": "201C,202a"}).json()
    assert [item["dive_code"] for item in payload["codes"]] == ["201C", "202A"]
    assert payload["codes"][0]["attempt_count"] == 2


def test_code_filter_combines_with_prefix_and_paging(api_client, test_db, two_codes):
    first = api_client.get(
        "/api/v1/dives/library", params={"code_filter": "201C,202A", "limit": 1}
    ).json()
    assert len(first["items"]) == 1 and first["next_cursor"]
    second = api_client.get(
        "/api/v1/dives/library",
        params={"code_filter": "201C,202A", "limit": 1, "cursor": first["next_cursor"]},
    ).json()
    # Cursor paging covers the whole filtered scope, not the first page twice.
    assert second["items"]
    assert first["items"][0]["id"] not in [item["id"] for item in second["items"]]


def test_code_filter_never_adds_unowned_rows(api_client, test_db, two_codes):
    rows = api_client.get(
        "/api/v1/dives/library",
        params={"code_filter": "101A,201C,202A,5231D", "diver_scope": "all"},
    ).json()
    assert {item["dive_code"] for item in rows["items"]} == {"101A", "201C", "202A"}


def test_name_codes_or_caption_phrase(api_client, test_db):
    now = datetime.utcnow()
    _seed(test_db, [
        # Caption-less 201C can only be reached through the name codes...
        (now - timedelta(days=3), "201C", "1m"),
        # ...and a captioned 103B only through the phrase.
        (now - timedelta(days=2), "103B", "3m", "back dive workout"),
        (now - timedelta(days=1), "102A", "1m"),
    ])
    both = api_client.get(
        "/api/v1/dives/library",
        params={"code_filter": "201A,201B,201C,201D", "search_text": "back dive"},
    ).json()
    assert {item["dive_code"] for item in both["items"]} == {"201C", "103B"}

    only_phrase = api_client.get("/api/v1/dives/library", params={"search_text": "back dive"}).json()
    assert {item["dive_code"] for item in only_phrase["items"]} == {"103B"}

    aggregates = api_client.get(
        "/api/v1/dives/library/codes",
        params={"code_filter": "201A,201B,201C,201D", "search_text": "back dive"},
    ).json()
    assert {item["dive_code"] for item in aggregates["codes"]} == {"103B", "201C"}


def test_code_filter_validation_is_rejecting_not_truncating(api_client, test_db, two_codes):
    for params in (
        {"code_filter": "201C,DIVE"},
        {"code_filter": "201C," + ",".join(f"{i}A" for i in range(100, 100 + CODE_FILTER_MAX + 1))},
        {"code_filter": "x" * 9000},
    ):
        response = api_client.get("/api/v1/dives/library", params=params)
        assert response.status_code == 422, params
    # A large-but-valid set stays within every bound and keeps working.
    ok = ",".join(f"{i}A" for i in range(100, 700))
    assert api_client.get("/api/v1/dives/library", params={"code_filter": ok}).status_code == 200


def test_sanitize_unit_bounds():
    assert sanitize_code_filter("") == []
    assert sanitize_code_filter("103C, 5231d") == ["103C", "5231D"]
    with pytest.raises(Exception):
        sanitize_code_filter(",".join(["101A"] * (CODE_FILTER_MAX + 2)))
    with pytest.raises(Exception):
        sanitize_code_filter("invalid-code")


def test_period_bounds_pages_and_aggregates(api_client, test_db, two_codes):
    since = (datetime.utcnow() - timedelta(days=21)).isoformat()
    rows = api_client.get("/api/v1/dives/library", params={"date_from": since}).json()
    assert {item["dive_code"] for item in rows["items"]} == {"101A", "201C"}

    payload = api_client.get("/api/v1/dives/library/codes", params={"date_from": since}).json()
    counts = {item["dive_code"]: item["attempt_count"] for item in payload["codes"]}
    assert counts == {"101A": 1, "201C": 1}

    until = (datetime.utcnow() - timedelta(days=25)).isoformat()
    rows = api_client.get("/api/v1/dives/library", params={"date_to": until}).json()
    # date_to includes everything older than the bound.
    assert {item["dive_code"] for item in rows["items"]} == {"201C", "202A"}
