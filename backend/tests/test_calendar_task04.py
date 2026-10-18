"""Weekly series, scoped edits and camps (Task04).

Same fixture and engines as Task02/03: SQLite by default; with
CALENDAR_TEST_DATABASE_URL the three SQL migrations are applied twice to a
disposable PostgreSQL (idempotence) and the row-locking race runs too.
"""
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.calendar import (
    CalendarChangeLog, CalendarEventRecurrence, EventItineraryItem, EventOccurrence, EventResource,
    OccurrenceAbsenceReport, OccurrenceInterest,
)
from app.services import calendar_import as ci
from tests.test_calendar_domain import PG_URL, TODAY, cal, flags  # noqa: F401
from tests.test_calendar_task03 import OPTS, run_import, synthetic_bundle, training_rows

API = "/api/v1/calendar"


def last_sunday(year: int, month: int) -> date:
    d = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    return d - timedelta(days=(d.weekday() - 6) % 7)


def next_transition(month: int) -> date:
    """Next Europe/Paris clock change (last Sunday of March/October) at least
    three weeks away, so every scoped edit below targets future sessions."""
    year = TODAY.year
    while last_sunday(year, month) < TODAY + timedelta(days=21):
        year += 1
    return last_sunday(year, month)


def monday_before(d: date, weeks: int) -> date:
    return d - timedelta(days=d.weekday()) - timedelta(weeks=weeks)


def series(cal, first: date, until: date, weekdays=(2,), start="19:00", end="20:30", excluded=(), **over):
    body = {"calendar_id": cal["cals"]["a"].id, "event_type": "training", "audience": "group",
            "title": "Entraînement hebdo", "timezone": "Europe/Paris",
            "when": {"start_local": f"{first}T{start}", "end_local": f"{first}T{end}"},
            "recurrence": {"weekdays": list(weekdays), "until_date": until.isoformat(),
                           "excluded_dates": [d.isoformat() for d in excluded]}}
    body.update(over)
    return cal["login"]("coach").post(f"{API}/events", json=body)


def occs(cal, event_id):
    return cal["login"]("coach").get(f"{API}/events/{event_id}").json()["occurrences"]


def edit(cal, event_id, body, who="coach"):
    client = cal["login"](who)
    pre = client.post(f"{API}/events/{event_id}/schedule/preview", json=body)
    if pre.status_code != 200:
        return pre, None
    applied = client.post(f"{API}/events/{event_id}/schedule/apply", json={**body, "plan_hash": pre.json()["plan_hash"]})
    return pre, applied


# --- Generation ------------------------------------------------------------------------------

def test_weekly_series_keeps_wall_time_across_both_dst_changes(cal):
    fall, spring = next_transition(10), next_transition(3)
    first = monday_before(fall, 2) + timedelta(days=1)  # a Tuesday before the fall change
    made = series(cal, first, first + timedelta(weeks=5), weekdays=(2, 7), excluded=[first + timedelta(weeks=1)])
    assert made.status_code == 201, made.text
    rows = made.json()["occurrences"]
    assert {(o["local_start"], o["local_end"]) for o in rows} == {("19:00", "20:30")}
    days = [o["local_date"] for o in rows]
    assert (first + timedelta(weeks=1)).isoformat() not in days and fall.isoformat() in days
    offsets = {o["starts_at"][11:16] for o in rows}
    assert offsets == {"17:00", "18:00"}  # UTC shifts by an hour; the local time does not
    assert all(o["series_date"] == o["local_date"] and o["occurrence_key"] == f"w:{o['local_date']}" for o in rows)
    rec = made.json()["recurrence"]
    assert rec["weekdays"] == [2, 7] and rec["start_time"] == "19:00" and rec["excluded_dates"]
    # Spring: the series is generated in local wall time on both sides too.
    s_first = spring - timedelta(days=12)
    spring_rows = series(cal, s_first, spring + timedelta(days=12), weekdays=(7,), title="Spring").json()["occurrences"]
    assert {o["local_start"] for o in spring_rows} == {"19:00"} and len({o["starts_at"][11:16] for o in spring_rows}) == 2


def test_dst_gap_or_overlap_in_any_date_refuses_the_whole_series(cal):
    spring, fall = next_transition(3), next_transition(10)
    gap = series(cal, spring - timedelta(weeks=2), spring + timedelta(weeks=1), weekdays=(7,), start="02:30",
                 end="03:30")
    body = gap.json()["detail"]
    assert gap.status_code == 422 and body["code"] == "dst_local_time" and spring.isoformat() in body["message"]
    overlap = series(cal, fall - timedelta(weeks=1), fall + timedelta(weeks=1), weekdays=(7,), start="02:15",
                     end="03:30")
    assert overlap.json()["detail"]["code"] == "dst_local_time"
    # The actionable fix works: exclude the clock-change Sunday.
    fixed = series(cal, spring - timedelta(weeks=2), spring + timedelta(weeks=1), weekdays=(7,), start="02:30",
                   end="03:30", excluded=[spring])
    assert fixed.status_code == 201 and len(fixed.json()["occurrences"]) == 3


def test_generation_is_bounded(cal):
    first = TODAY + timedelta(days=7)
    assert series(cal, first, first + timedelta(days=401)).json()["detail"]["code"] == "season_too_long"
    daily = series(cal, first, first + timedelta(days=300), weekdays=range(1, 8))
    assert daily.json()["detail"]["code"] == "too_many_sessions"
    many = [first + timedelta(days=i) for i in range(121)]
    assert series(cal, first, first + timedelta(days=200), excluded=many).status_code == 422
    assert series(cal, first, first - timedelta(days=1)).json()["detail"]["code"] == "invalid_season"
    camp = series(cal, first, first + timedelta(days=30), event_type="camp")
    assert camp.json()["detail"]["code"] == "recurrence_not_supported"
    assert cal["db"].query(CalendarEventRecurrence).count() == 0


# --- Scoped edits ---------------------------------------------------------------------------------

def _season(cal, weeks=6):
    first = monday_before(TODAY, -2) + timedelta(days=1)  # Tuesday in two weeks
    made = series(cal, first, first + timedelta(weeks=weeks - 1))
    assert made.status_code == 201, made.text
    return made.json(), first


def test_scope_one_detaches_and_later_pattern_edits_keep_it(cal):
    event, first = _season(cal)
    rows = event["occurrences"]
    target = rows[2]
    alice = cal["login"]("alice")
    assert alice.put(f"{API}/occurrences/{target['id']}/interest", json={"state": "interested"}).status_code == 200
    moved_day = (date.fromisoformat(target["local_date"]) + timedelta(days=1)).isoformat()
    pre, done = edit(cal, event["id"], {"expected_version": event["version"], "scope": "one",
                                        "occurrence_id": target["id"],
                                        "when": {"start_local": f"{moved_day}T18:00", "end_local": f"{moved_day}T19:30"}})
    assert pre.status_code == 200 and pre.json()["plan"]["moved"][0]["responses"]["interested"] == 1
    assert done.status_code == 200, done.text
    after = {o["id"]: o for o in occs(cal, event["id"])}
    assert after[target["id"]]["detached"] and after[target["id"]]["local_date"] == moved_day
    # "All upcoming": new time for the pattern; the individually edited session is kept.
    version = done.json()["event_version"]
    pre, done = edit(cal, event["id"], {"expected_version": version, "scope": "all", "start_time": "18:30",
                                        "end_time": "20:00"})
    plan = pre.json()["plan"]
    assert [k["occurrence_id"] for k in plan["kept"]] == [target["id"]]
    assert len(plan["moved"]) == len(rows) - 1 and not plan["created"] and not plan["cancelled"]
    assert done.status_code == 200
    after2 = {o["id"]: o for o in occs(cal, event["id"])}
    assert set(after2) == set(after)  # stable ids, nothing deleted or duplicated
    assert after2[target["id"]]["local_start"] == "18:00"
    assert {o["local_start"] for i, o in after2.items() if i != target["id"]} == {"18:30"}
    db = cal["db"]
    assert db.get(OccurrenceInterest, (target["id"], cal["users"]["alice"].id)).state == "interested"


def test_future_weekday_change_moves_rows_and_keeps_responses(cal):
    event, first = _season(cal)
    rows = event["occurrences"]
    pivot, before = rows[3], rows[1]
    alice = cal["login"]("alice")
    for o in (rows[1], rows[4]):
        alice.put(f"{API}/occurrences/{o['id']}/interest", json={"state": "maybe"})
    alice.put(f"{API}/occurrences/{rows[4]['id']}/absence", json={"absent": True})
    pre, done = edit(cal, event["id"], {"expected_version": event["version"], "scope": "future",
                                        "occurrence_id": pivot["id"], "weekdays": [3],
                                        "until_date": (date.fromisoformat(rows[-1]["local_date"])
                                                       + timedelta(days=1)).isoformat()})
    plan = pre.json()["plan"]
    assert plan["pivot"] == pivot["local_date"] and len(plan["moved"]) == 3 and not plan["cancelled"]
    moved = {m["occurrence_id"]: m for m in plan["moved"]}
    assert moved[rows[4]["id"]]["responses"] == {"interested": 0, "maybe": 1, "declined": 0, "absences": 1,
                                                 "dive_links": 0}
    assert pre.json()["summary"]["responses_kept"] == 1
    assert done.status_code == 200, done.text
    after = {o["id"]: o for o in occs(cal, event["id"])}
    assert set(after) == {o["id"] for o in rows}
    assert after[before["id"]]["local_date"] == before["local_date"]  # before the pivot: untouched
    for o in rows[3:]:
        new_day = date.fromisoformat(after[o["id"]]["local_date"])
        assert new_day.isoweekday() == 3 and new_day - date.fromisoformat(o["local_date"]) == timedelta(days=1)
        assert after[o["id"]]["occurrence_key"] == o["occurrence_key"]
    db, alice_id = cal["db"], cal["users"]["alice"].id
    assert db.get(OccurrenceInterest, (rows[4]["id"], alice_id)).state == "maybe"
    assert db.get(OccurrenceAbsenceReport, (rows[4]["id"], alice_id)).withdrawn_at is None
    kinds = [c.change_kind for c in db.query(CalendarChangeLog).filter_by(event_id=event["id"])]
    assert kinds.count("time_changed") == 3 and "updated" in kinds


def test_exclusions_and_season_end_cancel_durably_and_never_resurrect(cal):
    event, first = _season(cal)
    rows = event["occurrences"]
    holiday = rows[2]
    alice = cal["login"]("alice")
    alice.put(f"{API}/occurrences/{holiday['id']}/interest", json={"state": "interested"})
    pre, done = edit(cal, event["id"], {"expected_version": event["version"], "scope": "all",
                                        "excluded_dates": [holiday["local_date"]],
                                        "until_date": rows[4]["local_date"]})
    plan = pre.json()["plan"]
    assert [c["occurrence_id"] for c in plan["cancelled"]] == [holiday["id"], rows[5]["id"]]
    assert pre.json()["summary"]["responses_on_cancelled"] == 1
    v = done.json()["event_version"]
    after = {o["id"]: o for o in occs(cal, event["id"])}
    assert len(after) == len(rows) and after[holiday["id"]]["status"] == "cancelled"
    assert cal["db"].get(OccurrenceInterest, (holiday["id"], cal["users"]["alice"].id)) is not None
    # Removing the exclusion and extending the season again: the cancelled
    # rows stay cancelled (no resurrection); only never-generated dates appear.
    later = date.fromisoformat(rows[5]["local_date"]) + timedelta(weeks=1)
    pre, done = edit(cal, event["id"], {"expected_version": v, "scope": "all", "excluded_dates": [],
                                        "until_date": later.isoformat()})
    plan = pre.json()["plan"]
    assert {k["occurrence_id"] for k in plan["kept"]} == {holiday["id"], rows[5]["id"]}
    assert [c["series_date"] for c in plan["created"]] == [later.isoformat()]
    after = occs(cal, event["id"])
    assert len(after) == len(rows) + 1
    assert sum(o["status"] == "cancelled" for o in after) == 2


def test_stale_previews_are_refused_and_nothing_changes(cal):
    event, first = _season(cal)
    rows = event["occurrences"]
    coach = cal["login"]("coach")
    body = {"expected_version": event["version"], "scope": "all", "start_time": "17:00", "end_time": "18:00"}
    pre = coach.post(f"{API}/events/{event['id']}/schedule/preview", json=body).json()
    # A concurrent single-session edit (does not bump the event version).
    patch = coach.patch(f"{API}/occurrences/{rows[1]['id']}", json={"expected_version": 1, "venue_name": "Other"})
    assert patch.status_code == 200
    stale = coach.post(f"{API}/events/{event['id']}/schedule/apply", json={**body, "plan_hash": pre["plan_hash"]})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "stale_preview"
    # An applied scoped edit bumps the event version: an older form is stale.
    fresh = coach.post(f"{API}/events/{event['id']}/schedule/preview", json=body).json()
    assert coach.post(f"{API}/events/{event['id']}/schedule/apply",
                      json={**body, "plan_hash": fresh["plan_hash"]}).status_code == 200
    again = coach.post(f"{API}/events/{event['id']}/schedule/preview", json=body)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "stale_version"
    assert {o["local_start"] for o in occs(cal, event["id"]) if not o["detached"]} == {"17:00"}


def test_scope_edits_need_publishing_rights_and_hide_private_events(cal):
    event, _first = _season(cal)
    body = {"expected_version": 1, "scope": "all", "start_time": "17:00", "end_time": "18:00"}
    assert cal["login"]("alice").post(f"{API}/events/{event['id']}/schedule/preview", json=body).status_code == 403
    assert cal["login"]("bob").post(f"{API}/events/{event['id']}/schedule/preview", json=body).status_code == 404
    assert cal["login"]("ocoach").post(f"{API}/events/{event['id']}/schedule/apply",
                                       json={**body, "plan_hash": "0" * 64}).status_code == 404
    # Whole-event PATCH cannot rewrite a series' dates behind the scoped flow.
    coach = cal["login"]("coach")
    when = {"start_local": f"{_first}T10:00", "end_local": f"{_first}T11:00"}
    assert coach.patch(f"{API}/events/{event['id']}", json={"expected_version": 1, "when": when}) \
        .json()["detail"]["code"] == "edit_occurrence"


def test_imported_schedule_refuses_pattern_edits_but_allows_one_session(cal, tmp_path):
    db = cal["db"]
    run_import(db, synthetic_bundle(tmp_path), tmp_path / "artifacts")
    before = {o.id: (o.starts_at, o.status) for o in training_rows(db)}
    first = training_rows(db)[0]
    occ_id, event_id = first.id, first.event_id
    coach = cal["login"]("coach")
    event = coach.get(f"{API}/events/{event_id}").json()
    assert event["imported"] and event["recurrence"] is None
    refused = coach.post(f"{API}/events/{event_id}/schedule/preview",
                         json={"expected_version": event["version"], "scope": "all", "start_time": "17:00"})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "imported_series"
    db.expire_all()
    assert {o.id: (o.starts_at, o.status) for o in training_rows(db)} == before
    # Single-session cancel is explicit and marks the importer override.
    pre, done = edit(cal, event_id, {"expected_version": event["version"], "scope": "one",
                                     "occurrence_id": occ_id, "cancel": True})
    assert done.status_code == 200 and done.json()["summary"]["cancelled"] == 1
    db.expire_all()
    preview = ci.preview(db, ci.load_bundle(synthetic_bundle(tmp_path)), OPTS, tmp_path / "artifacts", None)
    assert preview["summary"]["training"]["create"] == 0


# --- Camps ------------------------------------------------------------------------------------------

KCPM_FEB_CAMP = [  # docs/design/calendar/KCPM_CAMP_SOURCE.md (Présidence KCPM email, 17 Oct 2026)
    {"local_date": "2027-02-19", "start_time": "18:00", "end_time": "21:00", "venue_name": "INSEP"},
    {"local_date": "2027-02-20", "start_time": "10:00", "end_time": "13:00", "venue_name": "INSEP"},
    {"local_date": "2027-02-20", "start_time": "15:00", "end_time": "18:00", "venue_name": "INSEP"},
    {"local_date": "2027-02-21", "start_time": "09:00", "end_time": "12:00",
     "venue_name": "Centre Aquatique Olympique, Saint-Denis"},
    {"local_date": "2027-02-21", "start_time": "15:00", "end_time": "18:00",
     "venue_name": "Centre Aquatique Olympique, Saint-Denis"},
]
HELLOASSO = ("https://www.helloasso.com/associations/kingfisher-club-plongeon-montreuil-kingfisher-plongeon-"
             "montreuil/evenements/stage-fevrier-2027-kcpm")


def camp_body(cal, **over):
    body = {"calendar_id": cal["cals"]["k"].id, "event_type": "camp", "audience": "club", "status": "draft",
            "title": "Stage février KCPM", "timezone": "Europe/Paris",
            "when": {"all_day": True, "start_date": "2027-02-19", "end_date": "2027-02-22"},
            "itinerary": KCPM_FEB_CAMP, "registration_url": HELLOASSO}
    body.update(over)
    return body


def test_real_kcpm_february_camp_is_one_event_with_itinerary(cal):
    coach = cal["login"]("coach")
    made = coach.post(f"{API}/events", json=camp_body(cal))
    assert made.status_code == 201, made.text
    camp = made.json()
    assert len(camp["occurrences"]) == 1  # one whole-camp occurrence: one interest
    occ = camp["occurrences"][0]
    assert (occ["local_date"], occ["local_end_date"], occ["end_date"]) == ("2027-02-19", "2027-02-21", "2027-02-22")
    assert [(i["local_date"], i["start_time"], i["venue_name"]) for i in camp["itinerary"]] == [
        (b["local_date"], b["start_time"], b["venue_name"]) for b in KCPM_FEB_CAMP]
    assert [r["url"] for r in camp["resources"] if r["kind"] == "registration"] == [HELLOASSO]
    coach.patch(f"{API}/events/{camp['id']}", json={"expected_version": camp["version"], "status": "published"})
    # Interest is on the whole camp; a window starting mid-camp still lists it.
    alice = cal["login"]("alice")
    assert alice.put(f"{API}/occurrences/{occ['id']}/interest", json={"state": "interested"}).status_code == 200
    window = alice.get(f"{API}/occurrences?from=2027-02-20T12:00:00Z&to=2027-02-21T00:00:00Z").json()["items"]
    assert [o["id"] for o in window] == [occ["id"]] and window[0]["my_interest"] == "interested"
    assert window[0]["is_all_day"] and window[0]["local_end_date"] == "2027-02-21"
    # Itinerary must stay inside the camp dates; shrinking the camp needs the itinerary updated too.
    coach = cal["login"]("coach")
    detail = coach.get(f"{API}/events/{camp['id']}").json()
    bad = coach.patch(f"{API}/events/{camp['id']}", json={
        "expected_version": detail["version"], "when": {"all_day": True, "start_date": "2027-02-19",
                                                        "end_date": "2027-02-21"}})
    assert bad.json()["detail"]["code"] == "itinerary_outside_dates"
    outside = camp_body(cal, itinerary=[{"local_date": "2027-02-23", "start_time": "10:00", "end_time": "11:00"}])
    assert coach.post(f"{API}/events", json=outside).json()["detail"]["code"] == "itinerary_outside_dates"
    assert cal["db"].query(EventItineraryItem).count() == 5
    assert cal["db"].query(EventResource).filter_by(kind="registration").count() == 1


def test_timed_multi_day_and_cross_midnight_local_end_date(cal):
    alice = cal["login"]("alice")
    day = TODAY + timedelta(days=10)
    body = {"title": "Nuit", "audience": "invited", "event_type": "outing",
            "when": {"start_local": f"{day}T22:00", "end_local": f"{day + timedelta(days=1)}T01:00"}}
    occ = alice.post(f"{API}/events", json=body).json()["occurrences"][0]
    assert occ["local_end_date"] == (day + timedelta(days=1)).isoformat()
    body["when"] = {"start_local": f"{day}T22:00", "end_local": f"{day + timedelta(days=1)}T00:00"}
    occ = alice.post(f"{API}/events", json={**body, "title": "Minuit"}).json()["occurrences"][0]
    assert occ["local_end_date"] == day.isoformat()  # ends exactly at midnight: same day


# --- PostgreSQL row locking -----------------------------------------------------------------------

@pytest.mark.skipif(not PG_URL, reason="Requires PostgreSQL row locking")
def test_concurrent_applies_of_one_preview_change_once(cal):
    from fastapi import HTTPException
    from app.models.user_auth import AppUser
    from app.schemas.calendar import ScheduleEdit
    from app.services import calendar_recurrence as rec

    event, _first = _season(cal)
    body = {"expected_version": event["version"], "scope": "all", "start_time": "17:00", "end_time": "18:00"}
    pre = cal["login"]("coach").post(f"{API}/events/{event['id']}/schedule/preview", json=body).json()
    engine, coach_id = cal["db"].get_bind(), cal["users"]["coach"].id
    barrier, results = threading.Barrier(2), []

    def run():
        db = sessionmaker(bind=engine)()
        try:
            user = db.get(AppUser, coach_id)
            barrier.wait()
            rec.apply(db, user, event["id"], ScheduleEdit(**body), pre["plan_hash"])
            db.commit()
            results.append(200)
        except HTTPException as exc:
            db.rollback()
            results.append(exc.status_code)
        finally:
            db.close()
    threads = [threading.Thread(target=run) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == [200, 409]
    cal["db"].expire_all()
    assert cal["db"].query(EventOccurrence).filter_by(event_id=event["id"]).count() == len(event["occurrences"])


@pytest.mark.skipif(not __import__("os").environ.get("CALENDAR_IMPORT_BUNDLE"),
                    reason="Private supplied bundle (never committed)")
def test_real_kcpm_116_dates_stay_exact_and_refuse_pattern_edits(cal, tmp_path):
    import os
    db, path = cal["db"], Path(os.environ["CALENDAR_IMPORT_BUNDLE"])
    opts = ci.Options(club_slug="kcpm", groups={"beginners": ("groupe-a", "A"), "advanced": ("groupe-b", "B")},
                      season_start=date(2026, 9, 1))
    pre = ci.preview(db, ci.load_bundle(path), opts, tmp_path / "a", None)
    ci.apply(db, ci.load_bundle(path), opts, tmp_path / "a", None, pre["plan_hash"], pre["batch_id"])
    rows = training_rows(db)
    snapshot = sorted((o.occurrence_key, o.starts_at, o.status, o.series_date) for o in rows)
    assert len(snapshot) == 116 and all(s[3] is None for s in snapshot)
    event_ids = sorted({o.event_id for o in rows})
    coach = cal["login"]("coach")
    for event_id in event_ids:
        detail = coach.get(f"{API}/events/{event_id}").json()
        assert detail["recurrence"] is None and detail["imported"]
        for scope in ("future", "all"):
            r = coach.post(f"{API}/events/{event_id}/schedule/preview", json={
                "expected_version": detail["version"], "scope": scope, "occurrence_id": detail["occurrences"][0]["id"],
                "start_time": "17:00", "end_time": "18:00"})
            assert r.json()["detail"]["code"] == "imported_series"
    db.expire_all()
    assert sorted((o.occurrence_key, o.starts_at, o.status, o.series_date) for o in training_rows(db)) == snapshot
    again = ci.preview(db, ci.load_bundle(path), opts, tmp_path / "a", None)
    assert again["summary"]["training"]["create"] == 0
