"""Per-code Library summaries cover the whole filtered scope, not one page."""

from datetime import datetime, timedelta

from app.models.dive import Dive
from app.models.session import Session as TrainingSession
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
