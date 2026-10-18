"""Working calendar writes and reviewed import (Task03).

Reuses the Task02 fixture (two clubs, two KCPM groups, staff/members/outsiders).
SQLite by default; CALENDAR_TEST_DATABASE_URL runs the same tests on a
disposable PostgreSQL built from both SQL migrations. CALENDAR_IMPORT_BUNDLE
(private, never committed) additionally imports the real supplied bundle.
"""
import hashlib
import json
import os
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.calendar import (
    CalendarChangeLog, CalendarEvent, CalendarIdempotencyKey, CalendarImportRun, CalendarSource,
    CalendarSourceMapping, EventInvitation, EventOccurrence, EventResource, OccurrenceDiveLink, OccurrenceInterest,
)
from app.models.dive import Dive
from app.models.diver import Diver
from app.models.session import Session as TrainingSession
from app.models.user_auth import UserDiverAccess
from app.services import calendar_import as ci
from tests.test_calendar_domain import PG_URL, TODAY, cal, flags  # noqa: F401

API = "/api/v1/calendar"
DAY = (TODAY + timedelta(days=5)).isoformat()


def outing(**over):
    body = {"title": "Sortie fosse", "audience": "invited", "event_type": "outing", "venue_name": "Piscine A",
            "when": {"start_local": f"{DAY}T10:00", "end_local": f"{DAY}T12:00"}}
    body.update(over)
    return body


def create(client, body, key=None):
    return client.post(f"{API}/events", json=body, headers={"Idempotency-Key": key} if key else {})


def ids(cal, name):
    return cal["users"][name].id


# --- Event create / edit / cancel ------------------------------------------------------

def test_idempotent_create_and_key_reuse(cal):
    alice = cal["login"]("alice")
    first = create(alice, outing(), "k-1")
    assert first.status_code == 201, first.text
    again = create(alice, outing(), "k-1")
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]
    assert create(alice, outing(title="Autre"), "k-1").json()["detail"]["code"] == "idempotency_key_reused"
    db = cal["db"]
    assert db.query(CalendarEvent).filter(CalendarEvent.title == "Sortie fosse").count() == 1
    assert db.query(CalendarIdempotencyKey).count() == 1
    # Keys are actor-scoped: another account using the same key creates its own event.
    assert create(cal["login"]("bob"), outing(), "k-1").status_code == 201
    detail = first.json()
    assert detail["calendar_kind"] == "personal" and detail["can_edit"] and detail["audience"] == "invited"
    occ = detail["occurrences"][0]
    assert (occ["local_date"], occ["local_start"], occ["local_end"]) == (DAY, "10:00", "12:00")
    kinds = [r.change_kind for r in db.query(CalendarChangeLog).filter_by(event_id=detail["id"])]
    assert kinds == ["created", "published"]


def test_publishing_rights_and_audiences(cal):
    k, a = cal["cals"]["k"], cal["cals"]["a"]
    assert create(cal["login"]("alice"), outing(calendar_id=k.id, audience="club")).status_code == 403
    coach = cal["login"]("coach")
    assert create(coach, outing(calendar_id=a.id, audience="club")).json()["detail"]["code"] == "invalid_audience"
    made = create(coach, outing(calendar_id=a.id, audience="group", event_type="training"))
    assert made.status_code == 201
    # Another club's coach cannot target this club's calendars (indistinguishable from missing).
    assert create(cal["login"]("ocoach"), outing(calendar_id=k.id, audience="club")).status_code == 404
    # The app administrator is not a club publisher.
    assert create(cal["login"]("admin"), outing(calendar_id=k.id, audience="club")).status_code == 404
    # Group B member cannot see or touch a group A event by direct id.
    eid = made.json()["id"]
    bob = cal["login"]("bob")
    assert bob.patch(f"{API}/events/{eid}", json={"expected_version": 1, "title": "x"}).status_code == 404
    assert cal["login"]("alice").patch(f"{API}/events/{eid}", json={"expected_version": 1, "title": "x"}) \
        .status_code == 403


def test_stale_version_retained_interest_and_change_log(cal):
    alice = cal["login"]("alice")
    event = create(alice, outing(audience="community"), "k-2").json()
    occ_id = event["occurrences"][0]["id"]
    bob = cal["login"]("bob")
    assert bob.put(f"{API}/occurrences/{occ_id}/interest", json={"state": "interested"}).status_code == 200
    alice = cal["login"]("alice")
    moved = alice.patch(f"{API}/events/{event['id']}", json={
        "expected_version": 1, "venue_name": "Piscine B",
        "when": {"start_local": f"{DAY}T14:00", "end_local": f"{DAY}T16:00"}})
    assert moved.status_code == 200, moved.text
    body = moved.json()
    assert body["version"] == 2 and body["occurrences"][0]["id"] == occ_id
    assert body["occurrences"][0]["local_start"] == "14:00"
    assert {c["kind"] for c in body["changes"]} == {"time_changed", "venue_changed"}
    stale = alice.patch(f"{API}/events/{event['id']}", json={"expected_version": 1, "title": "Late"})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "stale_version"
    # Interest survives time and venue changes (keyed by the stable occurrence).
    assert cal["db"].get(OccurrenceInterest, (occ_id, ids(cal, "bob"))).state == "interested"
    assert cal["login"]("bob").get(f"{API}/occurrences/{occ_id}").json()["my_interest"] == "interested"
    alice = cal["login"]("alice")  # one shared test client: switch the session back
    # No-op edit does not bump the version.
    assert alice.patch(f"{API}/events/{event['id']}", json={"expected_version": 2, "venue_name": "Piscine B"}) \
        .json()["version"] == 2
    cancelled = alice.post(f"{API}/events/{event['id']}/cancel", json={"expected_version": 2})
    assert cancelled.json()["status"] == "cancelled"
    # Retrying the cancel is harmless; the event and responses are kept.
    assert alice.post(f"{API}/events/{event['id']}/cancel", json={"expected_version": 2}).status_code == 200
    assert cal["db"].get(OccurrenceInterest, (occ_id, ids(cal, "bob"))) is not None
    assert cal["login"]("bob").put(f"{API}/occurrences/{occ_id}/interest",
                                   json={"state": "maybe"}).json()["detail"]["code"] == "not_open"
    alice = cal["login"]("alice")
    assert alice.patch(f"{API}/events/{event['id']}", json={"expected_version": 3, "title": "x"}) \
        .json()["detail"]["code"] == "event_cancelled"


def test_dst_gap_and_validation_keep_nothing(cal):
    alice = cal["login"]("alice")
    gap = outing(when={"start_local": "2027-03-28T02:30", "end_local": "2027-03-28T04:00"})
    assert alice.post(f"{API}/events", json=gap).json()["detail"]["code"] == "nonexistent_local_time"
    overlap = outing(when={"start_local": "2026-10-25T02:30", "end_local": "2026-10-25T04:00"})
    assert alice.post(f"{API}/events", json=overlap).json()["detail"]["code"] == "ambiguous_local_time"
    reversed_ = outing(when={"start_local": f"{DAY}T12:00", "end_local": f"{DAY}T10:00"})
    assert alice.post(f"{API}/events", json=reversed_).status_code == 422
    assert alice.post(f"{API}/events", json=outing(title="   ")).status_code == 422
    assert alice.post(f"{API}/events", json=outing(map_url="javascript:alert(1)")).status_code == 422
    assert cal["db"].query(CalendarEvent).filter(CalendarEvent.title == "Sortie fosse").count() == 0
    all_day = outing(when={"all_day": True, "start_date": DAY})
    occ = alice.post(f"{API}/events", json=all_day).json()["occurrences"][0]
    assert occ["is_all_day"] and occ["end_date"] == (date.fromisoformat(DAY) + timedelta(days=1)).isoformat()


def test_occurrence_edit_and_cancel_by_authorized_coach(cal):
    occ = cal["occ"]["ga"]
    alice = cal["login"]("alice")
    assert alice.put(f"{API}/occurrences/{occ.id}/interest", json={"state": "maybe"}).status_code == 200
    assert alice.patch(f"{API}/occurrences/{occ.id}", json={"expected_version": 1, "venue_name": "X"}) \
        .status_code == 403
    coach = cal["login"]("coach")
    edited = coach.patch(f"{API}/occurrences/{occ.id}", json={"expected_version": 1, "venue_name": "INSEP"})
    assert edited.status_code == 200 and edited.json()["venue_name"] == "INSEP" and edited.json()["version"] == 2
    assert coach.post(f"{API}/occurrences/{occ.id}/cancel", json={"expected_version": 1}).status_code == 409
    done = coach.post(f"{API}/occurrences/{occ.id}/cancel", json={"expected_version": 2})
    assert done.json()["status"] == "cancelled"
    assert cal["db"].get(OccurrenceInterest, (occ.id, ids(cal, "alice"))).state == "maybe"
    # Coach of the other club: 404 on direct ids.
    assert cal["login"]("ocoach").patch(f"{API}/occurrences/{occ.id}", json={"expected_version": 3}) \
        .status_code == 404


# --- Invitations --------------------------------------------------------------------------

def test_invitations_lifecycle_and_revocation(cal):
    alice = cal["login"]("alice")
    event = create(alice, outing(), "k-inv").json()
    eid, occ_id = event["id"], event["occurrences"][0]["id"]
    assert cal["login"]("una").get(f"{API}/events/{eid}").status_code == 404
    alice = cal["login"]("alice")
    first = alice.post(f"{API}/events/{eid}/invitations", json={"user_ids": [ids(cal, "una"), ids(cal, "outsider")]})
    assert first.status_code == 200 and len(first.json()["items"]) == 2
    # Retrying is idempotent.
    assert len(alice.post(f"{API}/events/{eid}/invitations", json={"user_ids": [ids(cal, "una")]})
               .json()["items"]) == 2
    assert cal["db"].query(EventInvitation).filter_by(event_id=eid).count() == 2
    assert alice.post(f"{API}/events/{eid}/invitations", json={"user_ids": [999999]}).status_code == 422
    una = cal["login"]("una")
    assert una.get(f"{API}/events/{eid}").json()["my_invitation"] == "pending"
    assert una.get(f"{API}/events/{eid}/invitations").status_code == 403  # no guest list for invitees
    assert una.put(f"{API}/occurrences/{occ_id}/interest", json={"state": "interested"}).status_code == 200
    assert una.put(f"{API}/events/{eid}/invitation", json={"status": "declined"}).json()["my_invitation"] == "declined"
    assert una.get(f"{API}/events/{eid}").status_code == 200  # can still change their mind
    alice = cal["login"]("alice")
    revoked = alice.post(f"{API}/events/{eid}/invitations/{ids(cal, 'una')}/revoke")
    assert {i["status"] for i in revoked.json()["items"] if i["user_id"] == ids(cal, "una")} == {"revoked"}
    una = cal["login"]("una")
    assert una.get(f"{API}/events/{eid}").status_code == 404
    assert una.put(f"{API}/events/{eid}/invitation", json={"status": "accepted"}).status_code == 404
    assert cal["db"].get(OccurrenceInterest, (occ_id, ids(cal, "una"))) is None
    # Re-invitation restores a pending grant.
    alice = cal["login"]("alice")
    alice.post(f"{API}/events/{eid}/invitations", json={"user_ids": [ids(cal, "una")]})
    assert cal["login"]("una").get(f"{API}/events/{eid}").json()["my_invitation"] == "pending"


def test_club_invitations_need_members_and_invited_audience(cal):
    coach = cal["login"]("coach")
    club_event = create(coach, outing(calendar_id=cal["cals"]["k"].id, audience="invited")).json()
    assert coach.post(f"{API}/events/{club_event['id']}/invitations",
                      json={"user_ids": [ids(cal, "outsider")]}).json()["detail"]["code"] == "not_member"
    assert coach.post(f"{API}/events/{club_event['id']}/invitations",
                      json={"user_ids": [ids(cal, "una")]}).status_code == 200
    open_event = create(coach, outing(calendar_id=cal["cals"]["k"].id, audience="club")).json()
    assert coach.post(f"{API}/events/{open_event['id']}/invitations",
                      json={"user_ids": [ids(cal, "una")]}).json()["detail"]["code"] == "not_invited_audience"


# --- Interest, absence, following ------------------------------------------------------------

def test_interest_and_absence_are_independent_and_scoped(cal):
    o = cal["occ"]
    alice = cal["login"]("alice")
    for state in ("interested", "interested", "declined"):
        assert alice.put(f"{API}/occurrences/{o['ga'].id}/interest", json={"state": state}).status_code == 200
    absent = alice.put(f"{API}/occurrences/{o['ga'].id}/absence", json={"absent": True})
    assert absent.json()["my_absence_reported"] and absent.json()["my_interest"] == "declined"
    assert alice.put(f"{API}/occurrences/{o['ga'].id}/absence", json={"absent": True}).status_code == 200
    cleared = alice.put(f"{API}/occurrences/{o['ga'].id}/interest", json={"state": None}).json()
    assert cleared["my_interest"] is None and cleared["my_absence_reported"]
    assert alice.put(f"{API}/occurrences/{o['ga'].id}/absence", json={"absent": False}).json()[
        "my_absence_reported"] is False
    assert alice.put(f"{API}/occurrences/{o['gb'].id}/interest", json={"state": "maybe"}).status_code == 404
    assert alice.put(f"{API}/occurrences/{o['draft'].id}/interest", json={"state": "maybe"}).status_code == 404
    assert alice.put(f"{API}/occurrences/{o['club'].id}/absence", json={"absent": True}).status_code == 403  # camp
    coach = cal["login"]("coach")
    assert coach.get(f"{API}/occurrences/{o['ga'].id}").json()["can_report_absence"] is False
    assert coach.put(f"{API}/occurrences/{o['ga'].id}/absence", json={"absent": True}).status_code == 403
    assert cal["login"]("una").put(f"{API}/occurrences/{o['ga'].id}/absence",
                                   json={"absent": True}).status_code == 404  # unassigned: not visible


def test_following_is_preference_only(cal):
    bob = cal["login"]("bob")
    assert bob.put(f"{API}/calendars/{cal['cals']['a'].id}/follow").status_code == 404
    assert bob.put(f"{API}/calendars/{cal['cals']['b'].id}/follow").status_code == 204
    assert bob.put(f"{API}/calendars/{cal['cals']['b'].id}/follow").status_code == 204
    following = {c["id"] for c in bob.get(f"{API}/calendars").json()["items"] if c["following"]}
    assert following == {cal["cals"]["b"].id}
    assert bob.put(f"{API}/events/{cal['events']['ga'].id}/follow").status_code == 404
    assert bob.put(f"{API}/events/{cal['events']['club'].id}/follow").status_code == 204
    assert bob.get(f"{API}/events/{cal['events']['club'].id}").json()["following"] is True
    assert bob.delete(f"{API}/events/{cal['events']['club'].id}/follow").status_code == 204
    writable = {c["id"]: c for c in cal["login"]("coach").get(f"{API}/calendars").json()["items"]}
    assert writable[cal["cals"]["a"].id]["can_publish"] and writable[cal["cals"]["a"].id]["allowed_audiences"] == [
        "group", "invited"]
    assert not {c["id"] for c in cal["login"]("alice").get(f"{API}/calendars").json()["items"]
                if c["can_publish"] and c["kind"] != "personal"}


def test_writes_check_origin(cal):
    alice = cal["login"]("alice")
    bad = {"Origin": "https://evil.example"}
    assert alice.post(f"{API}/events", json=outing(), headers=bad).status_code == 403
    assert alice.put(f"{API}/occurrences/{cal['occ']['ga'].id}/interest", json={"state": "maybe"},
                     headers=bad).status_code == 403


# --- Dive links ------------------------------------------------------------------------------------

def test_dive_links_are_private_and_never_change_visibility(cal):
    db, u, occ = cal["db"], cal["users"], cal["occ"]["ga"]
    day = occ.starts_at.date()
    diver = Diver(display_name="Alice diver", canonical_name="alice-diver")
    other = Diver(display_name="Bob diver", canonical_name="bob-diver")
    db.add_all([diver, other])
    db.flush()
    db.add_all([UserDiverAccess(user_id=u["alice"].id, diver_id=diver.id, access_kind="OWNER"),
                UserDiverAccess(user_id=u["bob"].id, diver_id=other.id, access_kind="OWNER")])
    session = TrainingSession(date=day)
    db.add(session)
    db.flush()
    mine = Dive(session_id=session.id, diver_id=diver.id, dive_code="101B", performance="G", performance_numeric=3,
                height="3m", dive_datetime=datetime.combine(day, datetime.min.time()) + timedelta(hours=19),
                visibility="private")
    theirs = Dive(session_id=session.id, diver_id=other.id, dive_code="103B", performance="G",
                  performance_numeric=3, height="1m", dive_datetime=mine.dive_datetime, visibility="public")
    db.add_all([mine, theirs])
    db.commit()
    mine_id, theirs_id = mine.id, theirs.id
    alice = cal["login"]("alice")
    listed = alice.get(f"{API}/occurrences/{occ.id}/dives").json()["items"]
    assert [d["id"] for d in listed] == [mine_id]
    assert alice.put(f"{API}/occurrences/{occ.id}/dives/{theirs_id}").json()["detail"]["code"] == "dive_not_linkable"
    linked = alice.put(f"{API}/occurrences/{occ.id}/dives/{mine_id}").json()["items"]
    assert linked[0]["linked"] is True
    assert alice.put(f"{API}/occurrences/{occ.id}/dives/{mine_id}").status_code == 200  # idempotent
    db.expire_all()
    assert db.get(Dive, mine_id).visibility == "private"
    assert db.query(OccurrenceDiveLink).count() == 1
    # Coach sees the occurrence but never alice's link or dive.
    assert cal["login"]("coach").get(f"{API}/occurrences/{occ.id}/dives").json()["items"] == []
    assert cal["login"]("bob").get(f"{API}/occurrences/{occ.id}/dives").status_code == 404
    assert cal["login"]("alice").delete(f"{API}/occurrences/{occ.id}/dives/{mine_id}").json()["items"][0][
        "linked"] is False


def test_auth_me_exposes_feature_flag(cal, flags):
    alice = cal["login"]("alice")
    assert alice.get("/api/v1/auth/me").json()["features"] == {"calendar": True}
    flags.calendar_enabled = False
    assert alice.get("/api/v1/auth/me").json()["features"] == {"calendar": False}
    assert alice.post(f"{API}/events", json=outing()).status_code == 404


def test_roster_admin_fields_are_staff_only(cal):
    k = cal["clubs"]["k"].id
    member = cal["login"]("alice").get(f"{API}/clubs/{k}/members").json()
    assert member["groups"] == [] and all(e["membership_id"] is None for e in member["items"])
    staff = cal["login"]("coach").get(f"{API}/clubs/{k}/members").json()
    assert staff["can_assign_groups"] and not staff["can_manage_members"] and len(staff["groups"]) == 2
    alice = next(e for e in staff["items"] if e["display_name"] == "Alice")
    assert alice["group_id"] == cal["groups"]["a"].id and alice["membership_id"]


@pytest.mark.skipif(not PG_URL, reason="Concurrent idempotency race needs PostgreSQL")
def test_concurrent_retries_create_one_event(cal):
    from app.services import calendar_events
    from app.schemas.calendar import EventCreate

    engine = cal["db"].get_bind()
    user_id = ids(cal, "alice")
    barrier, results = threading.Barrier(2), []

    def run():
        db = sessionmaker(bind=engine)()
        try:
            from app.models.user_auth import AppUser
            user = db.get(AppUser, user_id)
            barrier.wait()
            event, _ = calendar_events.create_event(db, user, EventCreate(**outing()), "race-key")
            db.commit()
            results.append(event.id)
        except Exception as exc:  # the loser hits the primary key
            db.rollback()
            results.append(type(exc).__name__)
        finally:
            db.close()
    threads = [threading.Thread(target=run) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    cal["db"].expire_all()
    assert cal["db"].query(CalendarEvent).filter(CalendarEvent.title == "Sortie fosse").count() == 1
    assert "IntegrityError" in results


# --- Import ------------------------------------------------------------------------------------------

def synthetic_bundle(tmp_path: Path, shift_minutes=0, drop_last=False, venue="SNMT") -> Path:
    """Synthetic stand-in for the private bundle: two groups, a workbook with
    dated/undated/historical candidates, resources and a WhatsApp link."""
    src = tmp_path / "sources"
    src.mkdir(exist_ok=True)
    files = {}
    for key, name in (("beginners", "b.pdf"), ("advanced", "a.pdf"), ("workbook", "w.xlsx")):
        path = src / name
        path.write_bytes(f"synthetic {key}".encode())
        files[key] = {"file": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    rows = []
    for group, days in (("beginners", (1, 3, 8)), ("advanced", (2, 4))):
        for i, d in enumerate(days):
            if drop_last and group == "advanced" and i == len(days) - 1:
                continue
            day = date(2026, 10, d)
            h, m = divmod(18 * 60 + shift_minutes, 60)
            start = f"{h:02d}:{m:02d}"
            end = f"{h + 2:02d}:{m:02d}"
            rows.append({"source_key": f"kcpm:2026-2027:{group}:{day}", "group_key": group,
                         "local_date": day.isoformat(), "start_local": start, "end_local": end,
                         "timezone": "Europe/Paris",
                         "start_at": f"{day}T{h - 2:02d}:{m:02d}:00+00:00",
                         "end_at": f"{day}T{h:02d}:{m:02d}:00+00:00", "venue_code": venue,
                         "source": {**files[group], "page": 1, "row": i + 1}})
    wb = {**files["workbook"], "sheet": "Compétitions"}
    meets = [
        {"title": "Future meet", "location_raw": "Lyon", "level_raw": "Masters", "date_raw": "11/13 dec 2026",
         "start_date": "2026-12-11", "end_date_exclusive": "2026-12-14", "registration_deadline_raw": "1 dec",
         "date_issue": None, "source": {**wb, "row": 37},
         "links": [{"cell": "E37", "url": "https://organizer.example/meet"},
                   {"cell": "I37", "url": "https://chat.whatsapp.com/SECRET"}]},
        {"title": "Old meet", "location_raw": "Nice", "level_raw": None, "date_raw": "2024",
         "start_date": "2024-03-16", "end_date_exclusive": "2024-03-18", "registration_deadline_raw": None,
         "date_issue": None, "source": {**wb, "row": 12}, "links": []},
        {"title": "Undated", "location_raw": None, "level_raw": None, "date_raw": "20267",
         "start_date": None, "end_date_exclusive": None, "registration_deadline_raw": None,
         "date_issue": "Malformed year; review original source", "source": {**wb, "row": 44}, "links": []},
    ]
    resources = [{"type": "Fédé", "title": "FFN", "url": "https://www.ffnatation.fr/x", "notes": None,
                  "source": {**wb, "row": 2}},
                 {"type": "Docs", "title": "Règlement 2023-24", "url": "https://drive.google.com/file/x",
                  "notes": None, "source": {**wb, "row": 3}}]
    bundle = tmp_path / f"bundle-{shift_minutes}-{drop_last}-{venue}.json"
    bundle.write_text(json.dumps({"format_version": 1, "sources": files, "training_occurrences": rows,
                                  "competition_candidates": meets, "resources": resources}))
    return bundle


OPTS = ci.Options(club_slug="kcpm", groups={"beginners": ("groupe-a", "A"), "advanced": ("groupe-b", "B")},
                  season_start=date(2026, 9, 1))


def run_import(db, path, artifacts):
    bundle = ci.load_bundle(path)
    preview = ci.preview(db, bundle, OPTS, artifacts, None)
    return preview, ci.apply(db, ci.load_bundle(path), OPTS, artifacts, None, preview["plan_hash"],
                             preview["batch_id"])


def training_rows(db):
    return db.query(EventOccurrence).join(
        CalendarSourceMapping, CalendarSourceMapping.occurrence_id == EventOccurrence.id).filter(
        CalendarSourceMapping.target_type == "occurrence").all()


def test_import_twice_without_duplicates_and_reviewed_candidates(cal, tmp_path):
    db, artifacts = cal["db"], tmp_path / "private-artifacts"
    path = synthetic_bundle(tmp_path)
    with pytest.raises(ci.ImportError_):  # no apply without the reviewed plan hash
        ci.apply(db, ci.load_bundle(path), OPTS, artifacts, None, "0" * 64)
    preview, applied = run_import(db, path, artifacts)
    assert preview["summary"]["training"]["create"] == 5
    assert preview["summary"]["competitions"] == {"draft": 1, "needs_review": 1, "historical": 1}
    assert applied["applied"]["occurrences_created"] == 5
    occs = training_rows(db)
    assert sorted(o.occurrence_key for o in occs) == sorted(
        f"kcpm:2026-2027:{g}:2026-10-{d:02d}" for g, ds in (("beginners", (1, 3, 8)), ("advanced", (2, 4)))
        for d in ds)
    assert all(o.starts_at.hour == 16 for o in occs)  # 18:00 Paris (CEST) = 16:00 UTC
    stored = list(artifacts.rglob("*.pdf")) + list(artifacts.rglob("*.xlsx"))
    assert len(stored) == 3 and all(oct(p.stat().st_mode)[-3:] == "600" for p in stored)
    assert db.query(CalendarSource).filter(CalendarSource.storage_ref.like("calendar-artifacts:%")).count() == 3
    # Second identical run: unchanged everywhere, nothing duplicated.
    again, applied2 = run_import(db, path, artifacts)
    assert again["summary"]["training"] == {"create": 0, "update": 0, "unchanged": 5, "conflict": 0,
                                            "missing_from_source": 0}
    assert again["summary"]["competition_actions"]["create"] == 0
    assert applied2["applied"]["occurrences_created"] == 0 and len(training_rows(db)) == 5
    assert db.query(EventResource).filter(EventResource.club_id == cal["clubs"]["k"].id).count() == 3  # 1 fixture
    assert db.query(CalendarImportRun).filter_by(status="applied").count() == 6
    # Members see their group's imported sessions; candidates stay drafts.
    alice = cal["login"]("alice")
    october = "from=2026-10-01T00:00:00Z&to=2026-11-01T00:00:00Z"
    seen = alice.get(f"{API}/occurrences?{october}").json()["items"]
    assert {o["local_date"] for o in seen if o["imported"]} == {"2026-10-01", "2026-10-03", "2026-10-08"}
    assert alice.get(f"{API}/occurrences?from=2026-12-01T00:00:00Z&to=2026-12-31T00:00:00Z").json()["items"] == []
    draft = db.query(CalendarEvent).filter_by(title="Future meet").one()
    assert draft.status == "draft"
    coach = cal["login"]("coach")
    chat = [r for r in coach.get(f"{API}/events/{draft.id}").json()["resources"] if r["kind"] == "club_chat"]
    assert len(chat) == 1
    assert {i["status"] for i in ci.review_queue(db, "kcpm")} >= {"needs_review", "historical", "draft_unpublished"}
    # No WhatsApp link becomes a crawlable source.
    assert not db.query(CalendarSource).filter(CalendarSource.url.like("%whatsapp%")).count()


def test_import_updates_in_place_respects_overrides_and_never_cancels(cal, tmp_path):
    db, artifacts = cal["db"], tmp_path / "private-artifacts"
    run_import(db, synthetic_bundle(tmp_path), artifacts)
    by_key = {o.occurrence_key: o.id for o in training_rows(db)}
    kept_id = by_key["kcpm:2026-2027:beginners:2026-10-01"]
    edited_id = by_key["kcpm:2026-2027:beginners:2026-10-03"]
    missing_key = "kcpm:2026-2027:advanced:2026-10-04"
    db.add(OccurrenceInterest(occurrence_id=kept_id, user_id=ids(cal, "alice"), state="interested"))
    db.commit()
    # A coach edits one session locally: the import must not overwrite it.
    coach = cal["login"]("coach")
    assert coach.patch(f"{API}/occurrences/{edited_id}", json={"expected_version": 1, "venue_name": "Annexe"}) \
        .status_code == 200
    changed = synthetic_bundle(tmp_path, shift_minutes=30, drop_last=True, venue="INSEP")
    preview, applied = run_import(db, changed, artifacts)
    s = preview["summary"]["training"]
    assert (s["update"], s["conflict"], s["missing_from_source"]) == (3, 1, 1)
    db.expire_all()
    kept = db.get(EventOccurrence, kept_id)
    assert (kept.starts_at.hour, kept.starts_at.minute, kept.venue_name) == (16, 30, "INSEP")
    assert db.get(OccurrenceInterest, (kept_id, ids(cal, "alice"))).state == "interested"
    assert db.get(EventOccurrence, edited_id).venue_name == "Annexe"
    assert db.get(EventOccurrence, by_key[missing_key]).status == "scheduled"  # flagged, never cancelled
    statuses = {m.external_key: m.review_status for m in db.query(CalendarSourceMapping)}
    assert statuses[missing_key] == "missing_from_source"
    assert statuses["kcpm:2026-2027:beginners:2026-10-03"] == "conflict"
    assert db.query(CalendarChangeLog).filter(CalendarChangeLog.change_kind == "time_changed",
                                              CalendarChangeLog.import_run_id.isnot(None)).count() == 3
    # A third identical run proposes nothing new and keeps the review items.
    third, _ = run_import(db, changed, artifacts)
    assert third["summary"]["training"] == {"create": 0, "update": 0, "unchanged": 3, "conflict": 1,
                                            "missing_from_source": 0}
    # Curator accepts the source value: the next reviewed import applies it.
    ci.resolve(db, "kcpm", "kcpm:2026-2027:beginners:2026-10-03", accept_source=True)
    fourth, _ = run_import(db, changed, artifacts)
    assert fourth["summary"]["training"]["update"] == 1
    db.expire_all()
    assert db.get(EventOccurrence, edited_id).venue_name == "INSEP"


def test_apply_refuses_a_plan_that_changed_after_preview(cal, tmp_path):
    db, artifacts = cal["db"], tmp_path / "a"
    path = synthetic_bundle(tmp_path)
    preview = ci.preview(db, ci.load_bundle(path), OPTS, artifacts, None)
    coach = cal["login"]("coach")  # database changes after review
    create(coach, outing(calendar_id=cal["cals"]["a"].id, audience="group"))
    ci.apply(db, ci.load_bundle(path), OPTS, artifacts, None, preview["plan_hash"], preview["batch_id"])  # unaffected
    preview2 = ci.preview(db, ci.load_bundle(synthetic_bundle(tmp_path, shift_minutes=15)), OPTS, artifacts, None)
    with pytest.raises(ci.ImportError_, match="changed since"):
        ci.apply(db, ci.load_bundle(synthetic_bundle(tmp_path, shift_minutes=45)), OPTS, artifacts, None,
                 preview2["plan_hash"], preview2["batch_id"])


def test_validation_rejects_tampered_artifacts_and_times(tmp_path):
    path = synthetic_bundle(tmp_path)
    data = json.loads(path.read_text())
    Path(data["sources"]["beginners"]["file"]).write_bytes(b"tampered")
    data["training_occurrences"][0]["start_at"] = "2026-10-01T17:00:00+00:00"
    path.write_text(json.dumps(data))
    with pytest.raises(ci.ImportError_) as exc:
        ci.validate(ci.load_bundle(path))
    assert "hash mismatch for beginners" in str(exc.value) and "disagrees" in str(exc.value)


REAL_BUNDLE = os.environ.get("CALENDAR_IMPORT_BUNDLE")


@pytest.mark.skipif(not REAL_BUNDLE, reason="Private supplied bundle (never committed)")
def test_real_bundle_imports_116_exact_dates_twice(cal, tmp_path):
    db = cal["db"]
    opts = ci.Options(club_slug="kcpm", groups={"beginners": ("groupe-a", "A"), "advanced": ("groupe-b", "B")},
                      season_start=date(2026, 9, 1))
    bundle = ci.load_bundle(Path(REAL_BUNDLE))
    for expected_create in (116, 0):
        preview = ci.preview(db, ci.load_bundle(Path(REAL_BUNDLE)), opts, tmp_path / "a", None)
        assert preview["summary"]["training"]["create"] == expected_create
        ci.apply(db, ci.load_bundle(Path(REAL_BUNDLE)), opts, tmp_path / "a", None, preview["plan_hash"],
                 preview["batch_id"])
    occs = {o.occurrence_key: o for o in training_rows(db)}
    assert len(occs) == 116
    for row in bundle.data["training_occurrences"]:
        o = occs[row["source_key"]]
        assert o.starts_at.isoformat() + "+00:00" == row["start_at"] and o.venue_name == row["venue_code"]


def test_import_rechecks_manual_change_after_preview(cal, tmp_path):
    db, artifacts = cal["db"], tmp_path / "private-artifacts"
    run_import(db, synthetic_bundle(tmp_path), artifacts)
    path = synthetic_bundle(tmp_path, shift_minutes=30)
    preview = ci.preview(db, ci.load_bundle(path), OPTS, artifacts, None)
    target = training_rows(db)[0]
    target_id = target.id
    # Keep a loaded identity-map snapshot while a separate request edits it.
    assert target.venue_name != "Manual pool"
    response = cal["login"]("coach").patch(f"{API}/occurrences/{target.id}", json={
        "expected_version": target.version, "venue_name": "Manual pool"})
    assert response.status_code == 200
    with pytest.raises(ci.ImportError_, match="changed since"):
        ci.apply(db, ci.load_bundle(path), OPTS, artifacts, None,
                 preview["plan_hash"], preview["batch_id"])
    db.rollback()
    db.expire_all()
    assert db.get(EventOccurrence, target_id).venue_name == "Manual pool"


def test_import_apply_selects_only_indexed_requested_batch(cal, tmp_path):
    db, artifacts = cal["db"], tmp_path / "artifacts"
    path = synthetic_bundle(tmp_path)
    preview = ci.preview(db, ci.load_bundle(path), OPTS, artifacts, None)
    source_id = db.get(CalendarImportRun, preview["runs"][0]).source_id
    for i in range(205):
        db.add(CalendarImportRun(source_id=source_id, source_sha256="a" * 64,
            parser_version=ci.PARSER_VERSION, status="previewed", batch_id=f"{i:032x}",
            summary={"batch_id": f"{i:032x}", "plan_hash": "unrelated"}))
    db.commit()
    result = ci.apply(db, ci.load_bundle(path), OPTS, artifacts, None,
                      preview["plan_hash"], preview["batch_id"])
    assert result["applied"]["occurrences_created"] == 5
    assert db.query(CalendarImportRun).filter(CalendarImportRun.status == "previewed").count() == 205
    assert db.query(CalendarImportRun).filter_by(batch_id=preview["batch_id"], status="applied").count() == 3


def test_new_club_preview_command_applies_without_unpersisted_batch(cal, tmp_path):
    from scripts.import_calendar_bundle import apply_hint
    db, artifacts = cal["db"], tmp_path / "artifacts"
    opts = ci.Options(club_slug="new-pilot", groups=OPTS.groups, season_start=OPTS.season_start,
                      create_club_name="New pilot", create_missing_groups=True)
    path = synthetic_bundle(tmp_path)
    preview = ci.preview(db, ci.load_bundle(path), opts, artifacts, None)
    assert preview["batch_id"] is None and preview["runs"] == []
    assert "--batch" not in apply_hint(preview)
    result = ci.apply(db, ci.load_bundle(path), opts, artifacts, None,
                      preview["plan_hash"], preview["batch_id"])
    assert result["applied"]["occurrences_created"] == 5
    again = ci.preview(db, ci.load_bundle(path), opts, artifacts, None)
    assert again["batch_id"] is not None and len(again["runs"]) == 3
    assert f"--batch {again['batch_id']}" in apply_hint(again)
    assert again["summary"]["training"]["create"] == 0


def test_apply_locks_only_current_bundle_sources(cal, tmp_path):
    from sqlalchemy import event
    db, artifacts = cal["db"], tmp_path / "artifacts"
    path = synthetic_bundle(tmp_path)
    run_import(db, path, artifacts)
    preview = ci.preview(db, ci.load_bundle(path), OPTS, artifacts, None)
    queries = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if "calendar_events.id IN (SELECT calendar_source_mappings.event_id" in statement:
            queries.append(statement)
    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        ci.apply(db, ci.load_bundle(path), OPTS, artifacts, None, preview["plan_hash"], preview["batch_id"])
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
    assert len(queries) == 1
    assert "calendar_source_mappings.source_id IN" in queries[0]
    assert "calendar_source_mappings.external_key IN" in queries[0]
    assert "calendar_source_mappings.target_type =" in queries[0]
    assert "JOIN calendar_sources" not in queries[0]


def test_import_review_streams_have_stable_bounded_cursors(cal, tmp_path):
    db = cal["db"]
    run_import(db, synthetic_bundle(tmp_path), tmp_path / "artifacts")
    expected = ci.review_queue(db, "kcpm", limit=200)
    first = ci.review_queue(db, "kcpm", limit=1)
    assert len(first) == 2 and {r["queue"] for r in first} == {"mapping", "draft"}
    cursors = {r["queue"]: r["mapping_id"] for r in first}
    second = ci.review_queue(db, "kcpm", limit=1,
        after_mapping_id=cursors["mapping"], after_draft_id=cursors["draft"])
    assert all(r["mapping_id"] > cursors[r["queue"]] for r in second)
    assert {(r["queue"], r["mapping_id"]) for r in first + second} == {
        (r["queue"], r["mapping_id"]) for r in expected}
    with pytest.raises(ci.ImportError_):
        ci.review_queue(db, "kcpm", limit=201)


def test_workbook_mapping_reads_only_current_bundle_keys(cal, tmp_path):
    from sqlalchemy import event
    db, artifacts = cal["db"], tmp_path / "artifacts"
    path = synthetic_bundle(tmp_path)
    run_import(db, path, artifacts)
    workbook = db.query(CalendarSource).filter_by(kind="workbook").one()
    db.add_all([CalendarSourceMapping(source_id=workbook.id, target_type=kind,
                                     external_key=f"historical-{kind}-{i}")
                for kind in ("event", "resource") for i in range(501)])
    db.commit()
    queries = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if "FROM calendar_source_mappings" in statement and parameters[0] == workbook.id:
            queries.append(statement)
    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        plan = ci.build_plan(db, ci.load_bundle(path), OPTS)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
    assert len(queries) == 2
    assert all("calendar_source_mappings.external_key IN" in query for query in queries)
    assert all(row["action"] == "unchanged" for row in plan["resources"])
    assert not any(row["action"] == "create" for row in plan["competitions"])


def test_import_private_links_stay_club_only_after_community_publication(cal, tmp_path):
    path = synthetic_bundle(tmp_path)
    data = json.loads(path.read_text())
    private_url = "https://docs.google.com/document/d/private-club-doc"
    data["competition_candidates"][0]["links"].append({"cell": "F37", "url": private_url})
    path.write_text(json.dumps(data))
    db = cal["db"]
    run_import(db, path, tmp_path / "artifacts")
    event = db.query(CalendarEvent).filter_by(title="Future meet").one()
    event.audience, event.status = "community", "published"
    db.commit()
    event_id = event.id
    member = cal["login"]("alice").get(f"{API}/events/{event_id}")
    outsider = cal["login"]("outsider").get(f"{API}/events/{event_id}")
    assert member.status_code == outsider.status_code == 200
    assert private_url in {r["url"] for r in member.json()["resources"]}
    assert {r["url"] for r in outsider.json()["resources"]} == {"https://organizer.example/meet"}
    club_doc = db.query(EventResource).filter_by(url="https://drive.google.com/file/x").one()
    assert club_doc.restricted_to_club
    public_doc = db.query(EventResource).filter_by(url="https://www.ffnatation.fr/x").one()
    assert not public_doc.restricted_to_club
