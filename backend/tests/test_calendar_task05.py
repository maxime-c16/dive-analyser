"""Reliable calendar alerts (Task05): outbox, worker, suppression, read side.

Same fixture and engines as Task02-04: SQLite by default; with
CALENDAR_TEST_DATABASE_URL the four SQL migrations are applied twice to a
disposable PostgreSQL (idempotence, parity) and the concurrency cases run.
The worker is driven with an injected clock and a recording push sender.
"""
import os
import threading
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.calendar import (
    CalendarAlertDelivery, CalendarAlertOutbox, CalendarChangeLog, CalendarSubscription, CalendarWorkerState,
    EventOccurrence, OccurrenceInterest,
)
from app.models.notification import Notification
from app.models.user_auth import AppUser
from app.services import calendar_access as access
from app.services import calendar_alerts as alerts
from app.services import calendar_events as events
from app.services import calendar_import as ci
from app.services import calendar_membership as membership
from tests.test_calendar_domain import PG_URL, TODAY, cal, flags  # noqa: F401
from tests.test_calendar_task03 import OPTS, run_import, synthetic_bundle, training_rows

API = "/api/v1/calendar"


class Pushes(list):
    def __call__(self, db, notification, payload):
        self.append((notification.user_id, payload))
        return True


def factory(cal):
    return sessionmaker(bind=cal["db"].get_bind(), expire_on_commit=False)


def run(cal, now=None, pushes=None, **kw):
    cal["db"].rollback()
    result = alerts.run_once(factory(cal), now=now or datetime.utcnow() + timedelta(seconds=1),
                             sender=pushes if pushes is not None else Pushes(), **kw)
    cal["db"].expire_all()
    return result


def inbox(cal, who):
    response = cal["login"](who).get("/api/v1/notifications")
    assert response.status_code == 200, response.text
    return [i for i in response.json()["items"] if i["type"].startswith("calendar_")]


def deliveries(cal, **filters):
    cal["db"].expire_all()
    return cal["db"].query(CalendarAlertDelivery).filter_by(**filters).order_by(CalendarAlertDelivery.id).all()


def uid(cal, name):
    return cal["users"][name].id


def version(cal, occ_id):
    return cal["login"]("coach").get(f"{API}/occurrences/{occ_id}").json()["version"]


def patch_occ(cal, who, occ_id, **body):
    client = cal["login"](who)
    current = client.get(f"{API}/occurrences/{occ_id}").json()
    r = client.patch(f"{API}/occurrences/{occ_id}", json={"expected_version": current["version"], **body})
    assert r.status_code == 200, r.text
    return r.json()


def when(day: date, start="19:00", end="20:30"):
    return {"start_local": f"{day}T{start}", "end_local": f"{day}T{end}"}


def place_on(cal, key, day: date, hour_utc=17):
    """Move a fixture occurrence directly (setup only, no change log)."""
    db = cal["db"]
    occ = db.get(EventOccurrence, cal["occ"][key].id)
    start = datetime.combine(day, time(hour_utc))
    occ.starts_at = occ.window_start = start
    occ.ends_at = occ.window_end = start + timedelta(hours=2)
    db.commit()
    return occ


def interest(cal, who, key, state="interested"):
    r = cal["login"](who).put(f"{API}/occurrences/{cal['occ'][key].id}/interest", json={"state": state})
    assert r.status_code == 200, r.text


def due_of(cal, key):
    db = cal["db"]
    occ = db.get(EventOccurrence, cal["occ"][key].id)
    return alerts.reminder_due(occ, db.get(type(cal["events"][key]), occ.event_id))


# --- Outbox atomicity ----------------------------------------------------------------------------------

def test_outbox_row_commits_and_rolls_back_with_the_event_write(cal):
    db, occ = cal["db"], cal["occ"]["ga"]
    patch_occ(cal, "coach", occ.id, venue_name="Piscine Maurice Thorez")
    logs = db.query(CalendarChangeLog).filter_by(occurrence_id=occ.id).all()
    assert logs and all(log.outbox_id for log in logs)
    last_log_id = logs[-1].id
    assert db.query(CalendarAlertOutbox).count() == 1
    # A refused (stale) write leaves no outbox row.
    stale = cal["login"]("coach").patch(f"{API}/occurrences/{occ.id}", json={"expected_version": 1,
                                                                             "venue_name": "X"})
    assert stale.status_code == 409 and db.query(CalendarAlertOutbox).count() == 1
    # Service write then rollback: event change, change log and outbox vanish together.
    v = version(cal, occ.id)  # API calls expunge the shared session: load ORM rows after them
    coach = db.get(AppUser, uid(cal, "coach"))
    events.cancel_occurrence(db, coach, occ.id, v)
    db.flush()
    assert db.query(CalendarAlertOutbox).count() == 2
    db.rollback()
    assert db.query(CalendarAlertOutbox).count() == 1
    assert db.query(CalendarChangeLog).filter_by(change_kind="cancelled").count() == 0
    assert db.get(EventOccurrence, occ.id).status == "scheduled"
    # Several writes in one transaction share one outbox row per event; the
    # next transaction gets its own.
    v = version(cal, occ.id)
    coach = db.get(AppUser, uid(cal, "coach"))
    events.cancel_occurrence(db, coach, occ.id, v)
    events.log_change(db, db.get(type(cal["events"]["ga"]), cal["events"]["ga"].id), "updated", coach,
                      {"note": (None, 1)})
    db.commit()
    assert db.query(CalendarAlertOutbox).count() == 2
    assert {log.outbox_id for log in db.query(CalendarChangeLog).filter(CalendarChangeLog.id > last_log_id)} == {
        db.query(CalendarAlertOutbox.id).order_by(CalendarAlertOutbox.id.desc()).first()[0]}


# --- Change alerts, idempotence, deep links ---------------------------------------------------------------

def test_change_alerts_participants_once_with_authorized_deep_link(cal):
    occ = cal["occ"]["ga"]
    interest(cal, "manager", "ga", "maybe")  # staff with interest: a participant too
    patch_occ(cal, "coach", occ.id, venue_name="Piscine Maurice Thorez")
    pushes = Pushes()
    first = run(cal, pushes=pushes)
    assert first["status"] == "ok" and first["delivered"] == 2, first
    assert {d.user_id for d in deliveries(cal)} == {uid(cal, "alice"), uid(cal, "manager")}  # not the coach (actor)
    items = inbox(cal, "alice")
    assert len(items) == 1
    item = items[0]
    assert item["type"] == "calendar_change" and item["title"] == "Groupe A training"
    assert item["calendar"]["url"] == f"/calendar/o/{occ.id}" and item["calendar"]["kind"] == "change"
    assert item["calendar"]["changes"][0]["kinds"] == ["venue_changed"]
    assert item["calendar"]["venue_name"] == "Piscine Maurice Thorez"
    # The deep link is authorized for the recipient only.
    assert cal["login"]("alice").get(f"{API}/occurrences/{occ.id}").status_code == 200
    assert cal["login"]("bob").get(f"{API}/occurrences/{occ.id}").status_code == 404
    assert inbox(cal, "bob") == [] and inbox(cal, "coach") == []
    # Private (group) event: generic push preview, deep link in payload.
    assert {p["body"] for _u, p in pushes} == {alerts.PUSH_BODY_PRIVATE}
    assert {p["url"] for _u, p in pushes} == {f"/calendar/o/{occ.id}"}
    # Re-running never duplicates: one inbox row per delivery key.
    again = run(cal)
    assert again["delivered"] == 0 and again["deliveries_created"] == 0
    db = cal["db"]
    assert db.query(Notification).filter(Notification.type.like("calendar_%")).count() == 2
    assert all(d.notification_id for d in deliveries(cal))


def test_pending_changes_are_merged_into_one_up_to_date_alert(cal):
    occ, day = cal["occ"]["invite"], TODAY + timedelta(days=5)
    patch_occ(cal, "alice", occ.id, when=when(day, "10:00", "12:00"))
    patch_occ(cal, "alice", occ.id, when=when(day, "14:00", "16:00"))
    run(cal)
    rows = deliveries(cal, user_id=uid(cal, "una"))
    assert [(d.status, d.suppressed_reason) for d in rows] == [("suppressed", "superseded"), ("delivered", None)]
    change = inbox(cal, "una")[0]["calendar"]["changes"][0]
    original = datetime.combine(TODAY + timedelta(days=1), time(18)).isoformat() + "Z"
    assert change["old_start"] == original and change["new_start"].startswith(f"{day}T12:00")


def test_cancellation_and_publication_alerts(cal):
    db = cal["db"]
    # A follower of the club calendar hears about a newly published event; the
    # publisher does not.
    db.add(CalendarSubscription(calendar_id=cal["cals"]["k"].id, user_id=uid(cal, "una")))
    db.commit()
    coach = cal["login"]("coach")
    made = coach.post(f"{API}/events", json={
        "calendar_id": cal["cals"]["k"].id, "event_type": "outing", "audience": "club", "status": "published",
        "title": "Sortie fosse", "timezone": "Europe/Paris", "when": when(TODAY + timedelta(days=9))})
    assert made.status_code == 201, made.text
    occ_id = made.json()["occurrences"][0]["id"]
    interest_r = cal["login"]("alice").put(f"{API}/occurrences/{occ_id}/interest", json={"state": "interested"})
    assert interest_r.status_code == 200
    run(cal)
    assert [i["calendar"]["kind"] for i in inbox(cal, "una")] == ["new_event"]
    assert inbox(cal, "una")[0]["type"] == "calendar_follow"
    assert inbox(cal, "alice") == [] and inbox(cal, "coach") == []
    detail = coach.get(f"{API}/events/{made.json()['id']}").json()
    assert coach.post(f"{API}/events/{detail['id']}/cancel", json={"expected_version": detail["version"]}).status_code == 200
    run(cal)
    items = inbox(cal, "alice")
    assert [i["calendar"]["kind"] for i in items] == ["cancellation"] and items[0]["calendar"]["status"] == "cancelled"


def test_invitations_wait_for_publication_and_revocation_suppresses(cal):
    alice = cal["login"]("alice")
    made = alice.post(f"{API}/events", json={
        "event_type": "outing", "audience": "invited", "status": "draft", "title": "Plongée privée",
        "timezone": "Europe/Paris", "when": when(TODAY + timedelta(days=6))})
    assert made.status_code == 201, made.text
    event_id = made.json()["id"]
    assert alice.post(f"{API}/events/{event_id}/invitations",
                      json={"user_ids": [uid(cal, "una"), uid(cal, "bob")]}).status_code == 200
    assert run(cal)["deliveries_created"] == 0  # draft: nobody is told yet
    detail = alice.get(f"{API}/events/{event_id}").json()
    assert alice.patch(f"{API}/events/{event_id}", json={"expected_version": detail["version"],
                                                         "status": "published"}).status_code == 200
    # Bob's invitation is revoked after the alert was queued, before dispatch.
    cal["db"].rollback()
    assert alerts.expand_outbox(factory(cal), "w", datetime.utcnow() + timedelta(seconds=1), 100)[
        "deliveries_created"] == 2
    assert cal["login"]("alice").post(
        f"{API}/events/{event_id}/invitations/{uid(cal, 'bob')}/revoke").status_code == 200
    run(cal)
    reasons = {d.user_id: (d.kind, d.status, d.suppressed_reason) for d in deliveries(cal, event_id=event_id)}
    assert reasons[uid(cal, "una")] == ("invitation", "delivered", None)
    assert reasons[uid(cal, "bob")][1:] == ("suppressed", "no_access")
    assert inbox(cal, "bob") == []
    assert inbox(cal, "una")[0]["calendar"]["kind"] == "invitation"


# --- Access loss: suppression and read-time redaction ---------------------------------------------------------

def test_membership_loss_suppresses_pending_and_redacts_delivered(cal):
    db, occ = cal["db"], cal["occ"]["ga"]
    patch_occ(cal, "coach", occ.id, venue_name="Bassin A")
    run(cal)
    assert inbox(cal, "alice")[0]["calendar"]["redacted"] is False
    patch_occ(cal, "coach", occ.id, venue_name="Bassin B")
    db.rollback()
    alerts.expand_outbox(factory(cal), "w", datetime.utcnow() + timedelta(seconds=1), 100)  # queued, not sent
    manager = db.get(AppUser, uid(cal, "manager"))
    m = access.active_membership(db, db.get(AppUser, uid(cal, "alice")), cal["clubs"]["k"].id)
    membership.end_membership(db, manager, cal["clubs"]["k"].id, m.id)
    db.commit()
    run(cal)
    latest = deliveries(cal, user_id=uid(cal, "alice"))[-1]
    assert (latest.status, latest.suppressed_reason) == ("suppressed", "no_access")
    items = inbox(cal, "alice")
    assert len(items) == 1
    assert items[0]["title"] == alerts.REDACTED_TITLE and items[0]["calendar"] == {"redacted": True}
    assert "Groupe A" not in str(items[0])
    # The stored inbox row never held event details in the first place.
    row = db.get(Notification, items[0]["id"])
    assert row.title == alerts.GENERIC_TITLES["change"] and row.body is None


# --- Reminders ---------------------------------------------------------------------------------------------------------

def test_previous_day_reminder_once_and_never_replayed(cal):
    place_on(cal, "ga", TODAY + timedelta(days=3))
    place_on(cal, "gb", TODAY + timedelta(days=3))
    interest(cal, "alice", "ga")
    interest(cal, "bob", "gb")
    due = due_of(cal, "ga")
    assert due > datetime.utcnow()
    assert run(cal, now=due - timedelta(minutes=1))["reminders_planned"] == 0
    pushes = Pushes()
    result = run(cal, now=due + timedelta(minutes=1), pushes=pushes)
    assert result["reminders_planned"] == 2 and result["delivered"] == 2
    assert run(cal, now=due + timedelta(minutes=2))["reminders_planned"] == 0
    item = inbox(cal, "alice")[0]
    assert item["calendar"]["kind"] == "reminder" and item["type"] == "calendar_reminder"
    # After downtime past the grace window nothing is replayed.
    db = cal["db"]
    db.query(CalendarAlertDelivery).delete()
    db.query(Notification).delete()
    db.commit()
    late = run(cal, now=due + alerts.REMINDER_GRACE + timedelta(minutes=1))
    assert late["reminders_planned"] == 0 and late["delivered"] == 0


def test_move_and_cancel_invalidate_planned_reminders(cal):
    db = cal["db"]
    place_on(cal, "fed", TODAY + timedelta(days=3), hour_utc=8)
    place_on(cal, "ga", TODAY + timedelta(days=3), hour_utc=8)
    interest(cal, "alice", "fed")
    interest(cal, "alice", "ga")
    due = due_of(cal, "fed")
    planned = alerts.plan_reminders(factory(cal), due + timedelta(minutes=1), 100)
    assert planned["reminders_planned"] == 2
    day = TODAY + timedelta(days=3)
    patch_occ(cal, "admin", cal["occ"]["fed"].id, when=when(day, "15:00", "17:00"))  # federal: admin curates
    coach = cal["login"]("coach")
    assert coach.post(f"{API}/occurrences/{cal['occ']['ga'].id}/cancel",
                      json={"expected_version": version(cal, cal["occ"]["ga"].id)}).status_code == 200
    run(cal, now=due + timedelta(minutes=2))
    rows = {(d.occurrence_id, d.kind, d.status, d.suppressed_reason, d.target_start) for d in deliveries(cal)
            if d.kind == "reminder"}
    old = [r for r in rows if r[2] == "suppressed"]
    assert {(r[0], r[3]) for r in old} == {(cal["occ"]["fed"].id, "changed"), (cal["occ"]["ga"].id, "changed")}
    # The moved session gets one reminder for its new slot; the cancelled one none.
    sent = [r for r in rows if r[2] == "delivered"]
    assert len(sent) == 1 and sent[0][0] == cal["occ"]["fed"].id
    assert sent[0][4] == db.get(EventOccurrence, cal["occ"]["fed"].id).window_start
    kinds = sorted(i["calendar"]["kind"] for i in inbox(cal, "alice"))
    assert kinds == ["cancellation", "change", "reminder"]


def test_group_reminder_is_opt_in_and_respects_absence(cal):
    place_on(cal, "ga", TODAY + timedelta(days=3))
    place_on(cal, "gb", TODAY + timedelta(days=3))
    bob = cal["login"]("bob")
    assert bob.put("/api/v1/notification-prefs", json={"type": "calendar_group_reminder",
                                                       "enabled": True}).status_code == 200
    alice = cal["login"]("alice")
    assert alice.put("/api/v1/notification-prefs", json={"type": "calendar_group_reminder",
                                                         "enabled": True}).status_code == 200
    assert alice.put(f"{API}/occurrences/{cal['occ']['ga'].id}/absence", json={"absent": True}).status_code == 200
    run(cal, now=due_of(cal, "gb") + timedelta(minutes=1))
    assert [i["type"] for i in inbox(cal, "bob")] == ["calendar_group_reminder"]
    assert inbox(cal, "alice") == []  # reported absent
    assert {d.suppressed_reason for d in deliveries(cal, user_id=uid(cal, "alice"))} == {"absent"}
    assert inbox(cal, "una") == []  # unassigned member: no group reminder


# --- Preferences -------------------------------------------------------------------------------------------------------

def test_preferences_gate_and_suppress(cal, flags):
    alice = cal["login"]("alice")
    prefs = alice.get("/api/v1/notification-prefs").json()["prefs"]
    assert {k: v for k, v in prefs.items() if k.startswith("calendar_")} == {
        "calendar_invitation": True, "calendar_change": True, "calendar_reminder": True,
        "calendar_group_reminder": False, "calendar_follow": True}
    assert alice.put("/api/v1/notification-prefs", json={"type": "calendar_change", "enabled": False}).status_code == 200
    patch_occ(cal, "coach", cal["occ"]["ga"].id, venue_name="Bassin C")
    run(cal)
    assert [(d.status, d.suppressed_reason) for d in deliveries(cal)] == [("suppressed", "pref_off")]
    assert inbox(cal, "alice") == []
    flags.calendar_enabled = False
    prefs = alice.get("/api/v1/notification-prefs").json()
    assert not any(k.startswith("calendar_") for k in prefs["prefs"]) and prefs["explicit"] == []
    assert alice.put("/api/v1/notification-prefs", json={"type": "calendar_change", "enabled": True}).status_code == 422


# --- Worker reliability ------------------------------------------------------------------------------------------------

def test_retry_backoff_dead_letter_and_requeue(cal, monkeypatch):
    patch_occ(cal, "coach", cal["occ"]["ga"].id, venue_name="Bassin D")
    real_stage = alerts.notification_service.stage
    failures = {"left": 1}

    def flaky(db, **kw):
        if failures["left"]:
            failures["left"] -= 1
            raise RuntimeError("inbox unavailable")
        return real_stage(db, **kw)

    monkeypatch.setattr(alerts.notification_service, "stage", flaky)
    t0 = datetime.utcnow() + timedelta(seconds=1)
    assert run(cal, now=t0)["delivery_failed"] == 1
    d = deliveries(cal)[0]
    assert (d.status, d.attempts, d.last_error) == ("pending", 1, "RuntimeError")
    assert d.next_attempt_at == t0 + timedelta(seconds=alerts.BACKOFF_BASE_SECONDS) and d.lease_owner is None
    assert run(cal, now=t0 + timedelta(seconds=10))["delivered"] == 0  # backing off
    assert run(cal, now=t0 + timedelta(seconds=31))["delivered"] == 1
    assert len(inbox(cal, "alice")) == 1
    # Permanent failure: dead after MAX_ATTEMPTS, visible in health, requeue is explicit.
    patch_occ(cal, "coach", cal["occ"]["ga"].id, venue_name="Bassin E")
    failures["left"] = 99
    now = t0 + timedelta(minutes=1)
    for _ in range(alerts.MAX_ATTEMPTS):
        run(cal, now=now)
        now += timedelta(hours=2)
    dead = deliveries(cal)[-1]
    assert (dead.status, dead.attempts) == ("dead", alerts.MAX_ATTEMPTS)
    db = cal["db"]
    report = alerts.health(db, now)
    assert "deliveries_dead_letters" in report["problems"] and report["queues"]["deliveries"]["dead"] == 1
    assert alerts.dead_letters(db)[0]["last_error"] == "RuntimeError"
    assert alerts.requeue_dead(db, "delivery", now=now) == 1
    failures["left"] = 0
    result = run(cal, now=now + timedelta(seconds=1))
    # Requeued but already past its freshness window -> suppressed, not replayed.
    assert result["delivered"] + result["suppressed"] == 1


def test_crashed_run_lease_expires_and_work_resumes(cal):
    db = cal["db"]
    patch_occ(cal, "coach", cal["occ"]["ga"].id, venue_name="Bassin F")
    t0 = datetime.utcnow() + timedelta(seconds=1)
    f = factory(cal)
    with f() as s:  # a worker that claimed its run and the outbox row, then died
        assert alerts.acquire_run(s, "dead-worker", t0)
        assert alerts._claim(s, CalendarAlertOutbox, "dead-worker", t0, 10)
    assert run(cal, now=t0 + timedelta(minutes=1))["status"] == "busy"
    resumed = run(cal, now=t0 + alerts.RUN_LEASE + timedelta(seconds=1))
    assert resumed["status"] == "ok" and resumed["outbox_done"] == 1 and resumed["delivered"] == 1
    state = db.get(CalendarWorkerState, alerts.WORKER_NAME)
    assert state.lease_owner is None and state.last_success_at is not None and state.runs == 2  # busy run not counted


def test_health_detects_missing_or_stale_worker(cal):
    db = cal["db"]
    admin = cal["login"]("admin")
    r = admin.get(f"{API}/admin/alerts/health")
    assert r.status_code == 503 and "worker_never_succeeded" in r.json()["problems"]
    assert cal["login"]("alice").get(f"{API}/admin/alerts/health").status_code == 403
    now = datetime.utcnow()
    run(cal, now=now)
    report = cal["login"]("admin").get(f"{API}/admin/alerts/health")
    assert report.status_code == 200 and report.json()["worker"] == "ok"
    assert alerts.health(db, now + alerts.STALE_WORKER + timedelta(minutes=1))["problems"] == ["worker_stale"]


def test_feature_off_worker_noop_and_calendar_rows_redacted(cal, flags):
    patch_occ(cal, "coach", cal["occ"]["ga"].id, venue_name="Bassin G")
    run(cal)
    patch_occ(cal, "coach", cal["occ"]["ga"].id, venue_name="Bassin H")
    flags.calendar_enabled = False
    assert alerts.run_once(factory(cal)) == {"status": "disabled"}
    assert deliveries(cal)[-1].status == "pending" or len(deliveries(cal)) == 1
    items = inbox(cal, "alice")
    assert items[0]["title"] == alerts.REDACTED_TITLE and items[0]["calendar"] == {"redacted": True}
    assert cal["login"]("alice").get(f"{API}/occurrences/{cal['occ']['ga'].id}").status_code == 404


def test_old_outbox_rows_are_never_announced_late(cal):
    patch_occ(cal, "coach", cal["occ"]["ga"].id, venue_name="Bassin I")
    db = cal["db"]
    db.query(CalendarAlertOutbox).update({"created_at": datetime.utcnow() - alerts.CHANGE_TTL - timedelta(hours=1)})
    db.commit()
    result = run(cal)
    assert result["outbox_done"] == 1 and result["deliveries_created"] == 0 and inbox(cal, "alice") == []


def test_schema_missing_is_detected(flags):
    from tests.test_calendar_domain import make_engine
    if PG_URL:
        pytest.skip("covered on SQLite; PostgreSQL schema is rebuilt per test")
    engine = make_engine(with_calendar=False)
    f = sessionmaker(bind=engine)
    with f() as db:
        assert alerts.schema_ready(db) is False
        assert alerts.health(db)["problems"] == ["schema_missing"]
    assert alerts.run_once(f) == {"status": "schema_missing"}
    engine.dispose()


def test_imports_never_blast_followers(cal, tmp_path):
    db = cal["db"]
    for name in ("alice", "una"):
        db.add(CalendarSubscription(calendar_id=cal["cals"]["a"].id, user_id=uid(cal, name)))
    db.commit()
    run_import(db, synthetic_bundle(tmp_path), tmp_path / "artifacts")
    run_import(db, synthetic_bundle(tmp_path, shift_minutes=30), tmp_path / "artifacts")
    assert db.query(CalendarAlertOutbox).filter_by(from_import=True).count() >= 1
    result = run(cal)
    assert result["deliveries_created"] == 0 and inbox(cal, "una") == []
    assert len(training_rows(db)) == 5


# --- PostgreSQL: concurrent workers -------------------------------------------------------------------------------------

@pytest.mark.skipif(not PG_URL, reason="Requires PostgreSQL concurrency")
def test_two_workers_deliver_each_key_once(cal):
    db = cal["db"]
    coach = db.get(AppUser, uid(cal, "coach"))
    for key in ("ga", "gb", "club", "fed"):
        o = cal["occ"][key]
        for name in ("alice", "bob", "una", "manager"):
            u = db.get(AppUser, uid(cal, name))
            if access.visible_occurrences(db, u).filter(EventOccurrence.id == o.id).first():
                db.merge(OccurrenceInterest(occurrence_id=o.id, user_id=u.id, state="interested"))
        events.log_change(db, cal["events"][key], "venue_changed", coach, {"venue_name": (None, "X")}, o)
        db.commit()
    now = datetime.utcnow() + timedelta(seconds=1)
    f = factory(cal)
    assert alerts.expand_outbox(f, "w0", now, 100)["outbox_done"] == 4
    expected = db.query(CalendarAlertDelivery).count()
    assert expected >= 5
    barrier = threading.Barrier(2)
    results = []

    def worker(owner):  # bypasses the run lease on purpose: row leases alone must hold
        barrier.wait(timeout=10)
        results.append(alerts.dispatch(f, owner, now, 100, sender=Pushes()))

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in (1, 2)]
    [t.start() for t in threads]
    [t.join(timeout=60) for t in threads]
    assert sum(r["delivered"] for r in results) == expected
    db.expire_all()
    assert db.query(Notification).count() == expected
    assert db.query(CalendarAlertDelivery).filter_by(status="delivered").count() == expected
    # Full runs started together: one holds the run lease, the other is excluded or finds nothing left.
    patch_occ(cal, "coach", cal["occ"]["ga"].id, venue_name="Y")
    statuses = []
    barrier2 = threading.Barrier(2)

    def full(owner):
        barrier2.wait(timeout=10)
        statuses.append(alerts.run_once(f, owner=owner, sender=Pushes()))

    threads = [threading.Thread(target=full, args=(f"r{i}",)) for i in (1, 2)]
    [t.start() for t in threads]
    [t.join(timeout=60) for t in threads]
    db.expire_all()
    # The run also plans the day-before reminders of these next-day sessions;
    # whatever it delivered, each delivery is counted once across both runs.
    delivered_now = db.query(CalendarAlertDelivery).filter_by(status="delivered").count()
    assert sum(s.get("delivered", 0) for s in statuses) == delivered_now - expected > 0
    assert sorted(s["status"] for s in statuses) in (["busy", "ok"], ["ok", "ok"])
    keys = [d.delivery_key for d in db.query(CalendarAlertDelivery)]
    assert len(keys) == len(set(keys))
    assert db.query(Notification).count() == db.query(CalendarAlertDelivery).filter_by(status="delivered").count()


@pytest.mark.skipif(not os.environ.get("CALENDAR_IMPORT_BUNDLE"), reason="Private supplied bundle (never committed)")
def test_real_kcpm_import_creates_no_alerts_and_stays_exact(cal, tmp_path):
    db, path = cal["db"], Path(os.environ["CALENDAR_IMPORT_BUNDLE"])
    opts = ci.Options(club_slug="kcpm", groups={"beginners": ("groupe-a", "A"), "advanced": ("groupe-b", "B")},
                      season_start=date(2026, 9, 1))
    for name in ("alice", "una"):
        db.add(CalendarSubscription(calendar_id=cal["cals"]["a"].id, user_id=uid(cal, name)))
    db.commit()
    pre = ci.preview(db, ci.load_bundle(path), opts, tmp_path / "a", None)
    ci.apply(db, ci.load_bundle(path), opts, tmp_path / "a", None, pre["plan_hash"], pre["batch_id"])
    snapshot = sorted((o.occurrence_key, o.starts_at, o.status) for o in training_rows(db))
    assert len(snapshot) == 116
    result = run(cal)
    assert result["deliveries_created"] == 0 and result["outbox_done"] >= 1
    db.expire_all()
    assert sorted((o.occurrence_key, o.starts_at, o.status) for o in training_rows(db)) == snapshot
    assert ci.preview(db, ci.load_bundle(path), opts, tmp_path / "a", None)["summary"]["training"]["create"] == 0
