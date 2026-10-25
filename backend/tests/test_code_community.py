"""Community stats on one code: other divers' public attempts only, bounded per diver."""
import random
from datetime import datetime, timedelta
from statistics import quantiles

from tests.test_member_dive_visibility import workspace  # noqa: F401 (fixture)
from app.models.dive import Dive
from app.models.diver import Diver
from app.services.code_community import _quantile
from app.services.code_summaries import SPARK_ATTEMPTS


def _add(db, session_id, diver_id, performances, *, code="5122D", height="1m", visibility="public", lineup=False, start=None):
    start = start or datetime(2026, 1, 1)
    for index, performance in enumerate(performances):
        db.add(Dive(session_id=session_id, diver_id=diver_id, dive_code=code, performance=performance,
                    performance_numeric=0, height=height, visibility=visibility, is_lineup=lineup,
                    dive_datetime=start + timedelta(days=index)))
    db.commit()


def _diver(db, name):
    return db.query(Diver).filter_by(canonical_name=name).one().id


def test_counts_only_other_divers_public_attempts(workspace):
    db, login, _, users, session_id = workspace
    alice, bob = _diver(db, "alice"), _diver(db, "bob")
    _add(db, session_id, bob, ["M", "G", "P", "B", "G"])
    _add(db, session_id, bob, ["P"] * 5, visibility="private")
    _add(db, session_id, bob, ["P"] * 5, lineup=True)
    _add(db, session_id, alice, ["F"] * 6)
    lone = Diver(display_name="LEO", canonical_name="leo")
    db.add(lone)
    db.commit()
    _add(db, session_id, lone.id, ["G", "G"])

    payload = login("alice").get("/api/v1/dives/library/codes/5122d/community").json()
    assert payload["dive_code"] == "5122D"
    assert [member["diver_id"] for member in payload["members"]] == [bob]
    assert payload["hidden_count"] == 1  # LEO: fewer than three graded attempts
    member = payload["members"][0]
    assert member["attempt_count"] == 5 and member["scored_count"] == 5
    # Scores 4.5, 7, 10, 2, 7 -> sorted 2, 4.5, 7, 7, 10.
    assert (member["q1"], member["median"], member["q3"]) == (4.5, 7.0, 7.0)
    assert member["account"]["user_id"] == users["bob"].id
    assert member["account"]["display_name"] == "bob"
    assert member["best"]["performance"] == "P" and member["best"]["visibility"] == "public"
    assert len(member["series"]) == 5

    # Bob sees Alice, not himself; a diverless viewer sees both.
    assert [m["diver_id"] for m in login("bob").get("/api/v1/dives/library/codes/5122D/community").json()["members"]] == [alice]
    viewer = login("viewer").get("/api/v1/dives/library/codes/5122D/community").json()
    assert sorted(m["diver_id"] for m in viewer["members"]) == sorted([alice, bob])


def test_follows_height_and_bounds_the_series(workspace):
    db, login, _, _, session_id = workspace
    bob = _diver(db, "bob")
    _add(db, session_id, bob, ["M"] * 60, height="1m")
    _add(db, session_id, bob, ["P"] * 4, height="3m", start=datetime(2026, 6, 1))

    one = login("alice").get("/api/v1/dives/library/codes/5122D/community", params={"height": "1m"}).json()["members"][0]
    assert one["scored_count"] == 60 and one["median"] == 4.5
    assert len(one["series"]) == SPARK_ATTEMPTS
    three = login("alice").get("/api/v1/dives/library/codes/5122D/community", params={"height": "3m"}).json()["members"][0]
    assert three["scored_count"] == 4 and three["median"] == 10.0
    # Newest of equal best scores wins.
    assert three["best"]["dive_datetime"].startswith("2026-06-04")


def test_histogram_quantiles_match_the_row_definition():
    rng = random.Random(7)
    for _ in range(200):
        values = [rng.choice([0, 2, 4.5, 7, 10, 3.15, 5.85]) for _ in range(rng.randint(1, 80))]
        counts: dict[float, int] = {}
        for value in values:
            counts[value] = counts.get(value, 0) + 1
        items = sorted(counts.items())
        ordered = sorted(values)
        for p in (0.25, 0.5, 0.75):
            position = (len(ordered) - 1) * p
            low, high = int(position), min(int(position) + 1, len(ordered) - 1)
            expected = ordered[low] + (ordered[high] - ordered[low]) * (position - low)
            assert abs(_quantile(items, p) - expected) < 1e-9
        if len(values) > 1:
            assert abs(_quantile(items, 0.5) - quantiles(values, n=4, method="inclusive")[1]) < 1e-9
