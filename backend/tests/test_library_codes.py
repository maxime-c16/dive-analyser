"""Per-code Library summaries cover the whole filtered scope, not one page."""

import json
from datetime import datetime, timedelta

from app.models.dive import Dive
from app.models.session import Session as TrainingSession
from app.services import code_summaries
from app.services.code_summaries import summarize_codes
from app.services.diver_identity import get_primary_diver


def _seed(db, code, performances, *, start, step_days=1, height="1m", lineup=False, phases=None):
    primary = get_primary_diver(db)
    created = []
    for index, performance in enumerate(performances):
        when = start + timedelta(days=index * step_days)
        session = db.query(TrainingSession).filter_by(date=when.date()).one_or_none()
        if session is None:
            session = TrainingSession(date=when.date())
            db.add(session)
            db.flush()
        phase1, phase2 = phases[index] if phases else (None, None)
        dive = Dive(
            session_id=session.id, diver_id=primary.id, dive_code=code, performance=performance,
            performance_numeric=0, height=height, is_lineup=lineup, dive_datetime=when,
            phase1_performance=phase1, phase2_performance=phase2,
        )
        db.add(dive)
        db.flush()
        created.append(dive)
    db.commit()
    return created


def test_codes_cover_every_page_and_skip_lineups(api_client, test_db):
    start = datetime.now() - timedelta(days=150)
    _seed(test_db, "5122D", ["M"] * 107, start=start, step_days=1)
    _seed(test_db, "5122D", ["P"], start=start, lineup=True)
    _seed(test_db, "201C", ["G", "P"], start=start)

    page = api_client.get("/api/v1/dives/library", params={"limit": 100}).json()
    assert len(page["items"]) == 100 and page["next_cursor"]

    payload = api_client.get("/api/v1/dives/library/codes").json()
    codes = {item["dive_code"]: item for item in payload["codes"]}
    assert codes["5122D"]["attempt_count"] == 107
    assert codes["5122D"]["session_count"] == 107
    assert codes["5122D"]["median"] == 4.5
    assert codes["201C"]["best"] == 10.0
    assert codes["201C"]["success_rate"] == 100.0
    assert codes["201C"]["ratings"] == {"P": 1, "G": 1}
    # Newest code first; recent attempts are newest first and bounded.
    assert payload["codes"][0]["dive_code"] == "5122D"
    recent = codes["5122D"]["recent"]
    assert len(recent) == 16
    assert recent[0]["dive_datetime"] > recent[-1]["dive_datetime"]
    assert codes["5122D"]["latest"]["id"] == recent[0]["id"]


def test_code_filter_and_straight_jumps(api_client, test_db):
    start = datetime.now() - timedelta(days=5)
    _seed(test_db, "101B", ["G", "M"], start=start)
    _seed(test_db, "100A", ["G"], start=start)

    filtered = api_client.get("/api/v1/dives/library/codes", params={"code_prefix": "101"}).json()
    assert [item["dive_code"] for item in filtered["codes"]] == ["101B"]

    everything = {item["dive_code"]: item for item in api_client.get("/api/v1/dives/library/codes").json()["codes"]}
    assert everything["100A"]["analytics"] is False
    assert everything["100A"]["trend"] is None and everything["100A"]["spark"] == []
    assert everything["101B"]["analytics"] is True


class _Row:
    def __init__(self, ident, code, when, performance, phases=(None, None), session=1, height="1m"):
        self.id, self.dive_code, self.dive_datetime, self.performance = ident, code, when, performance
        self.phase1_performance, self.phase2_performance = phases
        self.session_id, self.height, self.video_uuid = session, height, f"uuid-{ident}"


def test_trend_compares_recent_weeks_to_the_months_before():
    now = datetime(2026, 10, 25, 12)
    rows = [_Row(i, "301C", now - timedelta(days=100 + i), "M") for i in range(5)]
    rows += [_Row(10 + i, "301C", now - timedelta(days=3 + i), "G") for i in range(5)]
    rows += [_Row(20, "403B", now - timedelta(days=2), "G", phases=("G", "P"))]
    result = summarize_codes(rows, {"uuid-14": {"thumb_url": "/thumb"}}, now)
    codes = {item["dive_code"]: item for item in result["codes"]}
    assert codes["301C"]["trend"] == {"delta": 2.5, "recent_count": 5, "baseline_count": 5}
    # Too few attempts on either side: no trend rather than a noisy one.
    assert codes["403B"]["trend"] is None
    # Two-phase attempts use the weighted phase score.
    assert codes["403B"]["best"] == 8.65
    assert codes["301C"]["latest"]["id"] == 10 and codes["301C"]["latest"]["video_uuid"] == "uuid-10"
    assert result["activity"]["current"]["attempt_count"] == 6
    assert result["activity"]["current"]["code_count"] == 2
    assert len(result["activity"]["weeks"]) == 26
    assert sum(week["attempt_count"] for week in result["activity"]["weeks"]) == 11
    assert codes["301C"]["months"]["2026-10"]["count"] == 5


def _normalise(payload):
    """JSON-round-trip datetimes/dates to ISO strings so HTTP and direct-call outputs compare."""
    return json.loads(json.dumps(payload, default=lambda value: value.isoformat()))


def test_sql_path_matches_reference_implementation(api_client, test_db):
    from statistics import median as stat_median

    from app.services.performance_scoring import attempt_score_10

    assert not hasattr(code_summaries, "accumulate_ordered")
    start = datetime.now() - timedelta(days=150)
    _seed(test_db, "5122D", ["M"] * 107, start=start, step_days=1)
    _seed(test_db, "5122D", ["P"], start=start, lineup=True)
    _seed(test_db, "201C", ["G", "P"], start=start)
    _seed(test_db, "403B", ["G", "M", "B", "F"], start=start, step_days=7,
          phases=[("G", "P"), ("M", "M"), (None, None), (None, "P")])
    _seed(test_db, "100A", ["G"], start=start)
    # No ungraded seed: the schema CHECK forbids it (performance IN F/B/M/G/P),
    # so the falsy-performance guards are defensive only; the frontend suite
    # covers that path with mocked attempts.
    _seed(test_db, "205C", ["M", "M", "G", "G"], start=start, step_days=3)

    fresh = api_client.get("/api/v1/dives/library/codes").json()
    # The endpoint filters lineups; the reference input is pre-filtered the same way.
    rows = [dive for dive in test_db.query(Dive).all() if not dive.is_lineup]
    scores = [attempt_score_10(d.performance, d.phase1_performance, d.phase2_performance)
              for d in rows if d.performance]
    assert len(scores) == sum(item["scored_count"] for item in fresh["codes"])
    reference = _normalise(summarize_codes(rows, {}, datetime.now()))
    candidate = _normalise(fresh)
    reference.pop("generated_at")
    candidate.pop("generated_at")
    assert candidate == reference
    even = next(item for item in fresh["codes"] if item["dive_code"] == "205C")
    assert even["median"] == stat_median([4.5, 4.5, 7.0, 7.0]) == 5.75
    two_phase = next(item for item in fresh["codes"] if item["dive_code"] == "403B")
    assert two_phase["best"] == 8.65


def test_library_codes_height_and_performance_filters(api_client, test_db):
    start = datetime.now() - timedelta(days=5)
    _seed(test_db, "101B", ["G", "M"], start=start, height="3m")
    _seed(test_db, "101B", ["P"], start=start + timedelta(days=10), height="1m")

    good = api_client.get("/api/v1/dives/library/codes", params={"performance": "G"}).json()
    assert [item["dive_code"] for item in good["codes"]] == ["101B"]
    assert good["codes"][0]["attempt_count"] == 1

    high = api_client.get("/api/v1/dives/library/codes", params={"height": "3m"}).json()
    assert [item["dive_code"] for item in high["codes"]] == ["101B"]
    assert high["codes"][0]["attempt_count"] == 2


def test_median_from_hist_matches_statistics():
    from statistics import median as stat_median

    from app.services.code_summaries import _median_from_hist

    cases = [
        [(4.5, 107)],
        [(0.0, 1), (2.0, 1), (4.5, 5), (7.0, 4), (10.0, 1)],
        [(4.5, 2), (7.0, 2)],
        [(8.65, 1), (7.0, 3), (4.5, 2)],
        [(10.0, 1)],
    ]
    for pairs in cases:
        expanded = [score for score, count in pairs for _ in range(count)]
        assert _median_from_hist(pairs) == stat_median(expanded)
    assert _median_from_hist([]) is None


def test_large_history_keeps_bounded_rows_and_exact_medians(api_client, test_db):
    from statistics import median as stat_median

    from app.services.performance_scoring import attempt_score_10

    start = datetime.now() - timedelta(days=600)
    grades = ["F", "B", "M", "G", "P"]
    _seed(test_db, "5122D", [grades[index % len(grades)] for index in range(500)], start=start, step_days=1)

    payload = api_client.get("/api/v1/dives/library/codes").json()
    code = next(item for item in payload["codes"] if item["dive_code"] == "5122D")
    assert code["attempt_count"] == 500
    assert len(code["recent"]) == 16
    assert len(code["spark"]) == 40
    expected = stat_median(
        attempt_score_10(grade, None, None) for grade in (grades[index % len(grades)] for index in range(500))
    )
    assert code["median"] == expected
    assert code["months"] and all(entry["count"] > 0 for entry in code["months"].values())
