"""Reliable calendar alerts (Task05): outbox, worker, suppression, read side.

Same fixture and engines as Task02-04: SQLite by default; with
CALENDAR_TEST_DATABASE_URL the four SQL migrations are applied twice to a
disposable PostgreSQL (idempotence, parity) and the concurrency cases run.
The worker is driven with an injected clock and a recording push sender.
"""
import os
import threading
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

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
    assert item["calendar"]["changes"][0]["venue"] == "Piscine Maurice Thorez"  # the session's own venue
    assert item["calendar"]["calendar_name"] == "Groupe A" and item["calendar"]["calendar_kind"] == "group"
    # The deep link is authorized for the recipient only.
    assert cal["login"]("alice").get(f"{API}/occurrences/{occ.id}").status_code == 200
    assert cal["login"]("bob").get(f"{API}/occurrences/{occ.id}").status_code == 404
    assert inbox(cal, "bob") == [] and inbox(cal, "coach") == []
    # Private (group) event: the push preview still carries the real details
    # (what/new venue/group/when in the event timezone) plus the deep link.
    start = cal["db"].get(EventOccurrence, occ.id).starts_at
    expected_when = start.replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Europe/Paris")).strftime(
        "%a %d %b %H:%M")
    assert {p["title"] for _u, p in pushes} == {alerts.GENERIC_TITLES["change"]}
    assert {p["body"] for _u, p in pushes} == {
        f"Groupe A training · New venue: Piscine Maurice Thorez · Groupe A · {expected_when}"}
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
    expected_utc = datetime.combine(day, time(14), tzinfo=ZoneInfo("Europe/Paris")).astimezone(timezone.utc)
    expected_new = expected_utc.replace(tzinfo=None).isoformat() + "Z"
    assert change["old_start"] == original and change["new_start"] == expected_new


def test_push_body_pairs_the_delivery_occurrence_with_its_change_item(cal):
    """Merged details come back sorted by occurrence id (_merge_details) while
    the delivery keeps the newest alert's first session: the push must select
    the change item of its own occurrence, never items[0]."""
    from tests.test_calendar_domain import _occ
    db, occ = cal["db"], cal["occ"]["ga"]
    event = db.get(type(cal["events"]["ga"]), cal["events"]["ga"].id)
    other = _occ(db, event, "ga-2", 2)
    live = db.get(EventOccurrence, occ.id)
    live.venue_name = "Bassin A"
    db.commit()
    details = {"occurrences": [
        {"id": other.id, "kinds": ["time_changed"], "old_start": other.starts_at.isoformat() + "Z",
         "new_start": other.starts_at.isoformat() + "Z"},
        {"id": live.id, "kinds": ["venue_changed"]},
    ], "total": 2}
    db.add(alerts._new_delivery(delivery_key="push-pair", kind="change", notif_type="calendar_change",
                                user_id=uid(cal, "alice"), event_id=occ.event_id, occurrence_id=live.id,
                                details=details, expires_at=datetime.utcnow() + timedelta(days=1),
                                now=datetime.utcnow()))
    db.commit()
    payload = alerts.push_payload(db, deliveries(cal, delivery_key="push-pair")[0])
    start = live.starts_at
    expected_when = start.replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Europe/Paris")).strftime(
        "%a %d %b %H:%M")
    # This delivery's own change (the venue) is described; the other session's
    # moved-from/to times are not spliced into this push (+1 more: the merge
    # affected a second session).
    assert payload["body"] == f"Groupe A training · New venue: Bassin A · Groupe A · {expected_when} · +1 more"


def test_merged_details_never_drop_the_delivery_occurrence():
    """The cap on merged details keeps the delivery's own session: a merge
    over more than MAX_DETAIL_OCCURRENCES sessions cannot cut the item the
    push and the read row are keyed to."""
    old = {"occurrences": [{"id": i, "kinds": ["venue_changed"]} for i in range(1, 12)],
           "ids": list(range(1, 12)), "total": 11}
    new = {"occurrences": [{"id": 50, "kinds": ["time_changed"],
                            "old_start": "2026-11-13T18:00:00Z", "new_start": "2026-11-13T19:00:00Z"}],
           "ids": [50], "total": 1}
    merged = alerts._merge_details(old, new, keep_id=50)
    ids = [o["id"] for o in merged["occurrences"]]
    assert len(ids) == alerts.MAX_DETAIL_OCCURRENCES and 50 in ids
    assert merged["total"] == 12 and merged["total_exact"] is True
    # Unchanged cap semantics without a keep_id.
    assert 50 not in [o["id"] for o in alerts._merge_details(old, new)["occurrences"]]


def test_merged_details_count_every_represented_session(cal):
    """Two pending alerts about two different sessions merge into one alert
    whose total counts both (push '+1 more', read row '+N more sessions') —
    a 1+1 merge must never read as 1."""
    old = {"occurrences": [{"id": 7, "kinds": ["venue_changed"]}], "ids": [7], "total": 1}
    new = {"occurrences": [{"id": 9, "kinds": ["time_changed"],
                            "old_start": "2026-11-13T18:00:00Z", "new_start": "2026-11-13T19:00:00Z"}],
           "ids": [9], "total": 1}
    merged = alerts._merge_details(old, new, keep_id=9)
    assert merged["total"] == 2 and len(merged["occurrences"]) == 2
    assert merged["total_exact"] is True
    # A capped union still reports the larger total, not the capped list.
    big_old = {"occurrences": [{"id": i, "kinds": ["venue_changed"]} for i in range(1, 12)],
               "total": 15}
    assert alerts._merge_details(big_old, new, keep_id=9)["total"] == 15
    # The push carries the same count.
    db, occ = cal["db"], cal["occ"]["ga"]
    live = db.get(EventOccurrence, occ.id)
    db.add(alerts._new_delivery(delivery_key="push-merge-count", kind="change", notif_type="calendar_change",
                                user_id=uid(cal, "alice"), event_id=occ.event_id, occurrence_id=live.id,
                                details=merged, expires_at=datetime.utcnow() + timedelta(days=1),
                                now=datetime.utcnow()))
    db.commit()
    payload = alerts.push_payload(db, deliveries(cal, delivery_key="push-merge-count")[0])
    assert payload["body"].endswith("· +1 more")


def test_merged_details_count_disjoint_sessions_exactly(cal):
    """The ids ledger makes the union exact across the cap: a capped alert
    (total 15, 10 listed) merged with a distinct session counts 16 — both in
    the merged details and in the push."""
    old = {"occurrences": [{"id": i, "kinds": ["venue_changed"]} for i in range(100, 110)],
           "ids": list(range(100, 115)), "total": 15}
    new = {"occurrences": [{"id": 200, "kinds": ["time_changed"],
                            "old_start": "2026-11-13T18:00:00Z", "new_start": "2026-11-13T19:00:00Z"}],
           "ids": [200], "total": 1}
    merged = alerts._merge_details(old, new, keep_id=200)
    assert merged["total"] == 16 and len(merged["ids"]) == 16
    assert merged["total_exact"] is True
    assert len(merged["occurrences"]) == alerts.MAX_DETAIL_OCCURRENCES
    assert [o["id"] for o in merged["occurrences"]][-1] == 200  # keep_id survives the cap
    # Legacy rows (no ledger) keep the safe lower bound: unknowable overlap —
    # and it must not be presented as an exact number.
    legacy = {"occurrences": old["occurrences"], "total": 15}
    legacy_merged = alerts._merge_details(legacy, new, keep_id=200)
    assert legacy_merged["total"] == 15 and legacy_merged["total_exact"] is False
    # The push carries the exact count when the ledger proves the union…
    db, occ = cal["db"], cal["occ"]["ga"]
    live = db.get(EventOccurrence, occ.id)
    db.add(alerts._new_delivery(delivery_key="push-union", kind="change", notif_type="calendar_change",
                                user_id=uid(cal, "alice"), event_id=occ.event_id, occurrence_id=live.id,
                                details=merged, expires_at=datetime.utcnow() + timedelta(days=1),
                                now=datetime.utcnow()))
    # …and no fake-precise number when a legacy side hid its sessions.
    db.add(alerts._new_delivery(delivery_key="push-union-legacy", kind="change", notif_type="calendar_change",
                                user_id=uid(cal, "bob"), event_id=occ.event_id, occurrence_id=live.id,
                                details=legacy_merged, expires_at=datetime.utcnow() + timedelta(days=1),
                                now=datetime.utcnow()))
    db.commit()
    assert alerts.push_payload(db, deliveries(cal, delivery_key="push-union")[0])["body"].endswith("+15 more")
    assert alerts.push_payload(db, deliveries(cal, delivery_key="push-union-legacy")[0])["body"].endswith(
        alerts.PUSH_MORE_UNCOUNTED)


def test_push_body_counts_sessions_around_a_partial_cancellation(cal):
    """One cancelled session inside a multi-session alert still shows how many
    sessions are affected; only an event-wide cancellation omits the count."""
    db, occ = cal["db"], cal["occ"]["ga"]
    live = db.get(EventOccurrence, occ.id)
    other_id = live.id + 1
    partial = {"occurrences": [
        {"id": live.id, "kinds": ["cancelled"]},
        {"id": other_id, "kinds": ["time_changed"], "old_start": live.starts_at.isoformat() + "Z",
         "new_start": live.starts_at.isoformat() + "Z"},
    ], "total": 2, "ids": [live.id, other_id], "event_cancelled": False}
    db.add(alerts._new_delivery(delivery_key="push-partial-cancel", kind="cancellation",
                                notif_type="calendar_change", user_id=uid(cal, "alice"),
                                event_id=occ.event_id, occurrence_id=live.id, details=partial,
                                expires_at=datetime.utcnow() + timedelta(days=1), now=datetime.utcnow()))
    event_wide = {"occurrences": [{"id": live.id, "kinds": ["cancelled"]},
                                  {"id": other_id, "kinds": ["cancelled"]},
                                  {"id": other_id + 1, "kinds": ["cancelled"]}],
                  "total": 3, "ids": [live.id, other_id, other_id + 1], "event_cancelled": True}
    db.add(alerts._new_delivery(delivery_key="push-event-cancel", kind="cancellation",
                                notif_type="calendar_change", user_id=uid(cal, "bob"),
                                event_id=occ.event_id, occurrence_id=live.id, details=event_wide,
                                expires_at=datetime.utcnow() + timedelta(days=1), now=datetime.utcnow()))
    db.commit()
    partial_push = alerts.push_payload(db, deliveries(cal, delivery_key="push-partial-cancel")[0])
    assert "Cancelled" in partial_push["body"] and partial_push["body"].endswith("+1 more")
    assert partial_push["title"] == alerts.GENERIC_TITLES["change"]  # one session, not the event
    wide_push = alerts.push_payload(db, deliveries(cal, delivery_key="push-event-cancel")[0])
    assert "Cancelled" in wide_push["body"] and "+2 more" not in wide_push["body"]
    assert wide_push["title"] == alerts.GENERIC_TITLES["cancellation"]  # the whole event


def test_push_title_and_marker_follow_the_delivery_occurrence(cal):
    """Cancellation wording is scoped: another session's cancellation is a
    plain change for this row; the row's own cancelled session says so."""
    db, occ = cal["db"], cal["occ"]["ga"]
    live = db.get(EventOccurrence, occ.id)
    other_id = live.id + 1
    # Another session was cancelled; this delivery's session stays scheduled.
    elsewhere = {"occurrences": [
        {"id": live.id, "kinds": ["time_changed"], "old_start": live.starts_at.isoformat() + "Z",
         "new_start": live.starts_at.isoformat() + "Z"},
        {"id": other_id, "kinds": ["cancelled"]},
    ], "total": 2, "ids": [live.id, other_id], "event_cancelled": False}
    db.add(alerts._new_delivery(delivery_key="push-other-cancel", kind="cancellation",
                                notif_type="calendar_change", user_id=uid(cal, "alice"),
                                event_id=occ.event_id, occurrence_id=live.id, details=elsewhere,
                                expires_at=datetime.utcnow() + timedelta(days=1), now=datetime.utcnow()))
    db.commit()
    elsewhere_push = alerts.push_payload(db, deliveries(cal, delivery_key="push-other-cancel")[0])
    assert elsewhere_push["title"] == alerts.GENERIC_TITLES["change"]
    assert "Cancelled" not in elsewhere_push["body"] and elsewhere_push["body"].endswith("+1 more")
    # This delivery's own session is the cancelled one.
    live.status, live.cancelled_at = "cancelled", datetime.utcnow()
    own = {"occurrences": [{"id": live.id, "kinds": ["cancelled"]}],
           "total": 1, "ids": [live.id], "event_cancelled": False}
    db.add(alerts._new_delivery(delivery_key="push-own-cancel", kind="cancellation",
                                notif_type="calendar_change", user_id=uid(cal, "bob"),
                                event_id=occ.event_id, occurrence_id=live.id, details=own,
                                expires_at=datetime.utcnow() + timedelta(days=1), now=datetime.utcnow()))
    db.commit()
    own_push = alerts.push_payload(db, deliveries(cal, delivery_key="push-own-cancel")[0])
    assert own_push["title"] == alerts.PUSH_TITLE_SESSION_CANCELLED
    assert "Cancelled" in own_push["body"]


def test_push_body_formats_form_changes_separately(cal):
    """A timed <-> all-day change formats each endpoint with its own shape:
    the old local midnight is a date, a new all-day endpoint keeps its date,
    a new timed endpoint keeps its time."""
    db, occ, club = cal["db"], cal["occ"]["ga"], cal["occ"]["club"]
    live, camp = db.get(EventOccurrence, occ.id), db.get(EventOccurrence, club.id)
    timed_old = live.starts_at.isoformat() + "Z"  # the previous timed slot
    # ga: timed -> all-day (Sun 15 Nov); camp: all-day -> timed (Mon 16 Nov 16:00).
    live.is_all_day, live.starts_at, live.ends_at = True, None, None
    live.start_date, live.end_date = TODAY + timedelta(days=2), TODAY + timedelta(days=3)
    live.window_start = datetime.combine(TODAY + timedelta(days=2), time())
    live.window_end = datetime.combine(TODAY + timedelta(days=3), time())
    camp.is_all_day, camp.start_date, camp.end_date = False, None, None
    camp.starts_at = datetime.combine(TODAY + timedelta(days=3), time(15))
    camp.ends_at = camp.starts_at + timedelta(hours=2)
    camp.window_start, camp.window_end = camp.starts_at, camp.ends_at
    ga_details = {"occurrences": [{"id": live.id, "kinds": ["time_changed"], "old_start": timed_old,
                                   "new_start": live.window_start.isoformat() + "Z",
                                   "old_all_day": False, "new_all_day": True}],
                  "total": 1, "ids": [live.id], "total_exact": True}
    club_details = {"occurrences": [{"id": camp.id, "kinds": ["time_changed"],
                                     "old_start": (TODAY + timedelta(days=3)).isoformat() + "T00:00:00Z",
                                     "new_start": camp.starts_at.isoformat() + "Z",
                                     "old_all_day": True, "new_all_day": False}],
                    "total": 1, "ids": [camp.id], "total_exact": True}
    for key, who, details, occ_row in (("push-form-ga", "alice", ga_details, live),
                                       ("push-form-club", "bob", club_details, camp)):
        db.add(alerts._new_delivery(delivery_key=key, kind="change", notif_type="calendar_change",
                                    user_id=uid(cal, who), event_id=occ_row.event_id,
                                    occurrence_id=occ_row.id,
                                    details=details, expires_at=datetime.utcnow() + timedelta(days=1),
                                    now=datetime.utcnow()))
    db.commit()
    ga_push = alerts.push_payload(db, deliveries(cal, delivery_key="push-form-ga")[0])
    assert ga_push["body"] == ("Groupe A training · Groupe A · "
                               "Moved from Sat 14 Nov 19:00 to Sun 15 Nov · Sun 15 Nov")
    club_push = alerts.push_payload(db, deliveries(cal, delivery_key="push-form-club")[0])
    assert club_push["body"] == "Club camp · Moved from Mon 16 Nov to Mon 16 Nov 16:00 · Mon 16 Nov 16:00"


def test_push_body_announces_only_changed_venues(cal):
    """'New venue' fires only when the session's effective venue name changed:
    an address/map_url-only event edit changes no pool, and an event-level
    name change never reaches a session with its own venue override."""
    db, occ = cal["db"], cal["occ"]["ga"]
    live = db.get(EventOccurrence, occ.id)
    event_row = db.get(type(cal["events"]["ga"]), occ.event_id)
    event_row.venue_name = "Piscine X"  # the event's pool, unchanged by edits below
    synthesized = [{"id": live.id, "kinds": ["venue_changed"]}]
    db.commit()

    def delivery(key, details):
        db.add(alerts._new_delivery(delivery_key=key, kind="change", notif_type="calendar_change",
                                    user_id=uid(cal, "alice"), event_id=occ.event_id, occurrence_id=live.id,
                                    details=details, expires_at=datetime.utcnow() + timedelta(days=1),
                                    now=datetime.utcnow()))
        db.commit()
        return alerts.push_payload(db, deliveries(cal, delivery_key=key)[0])["body"]

    # Address-only edit: the pool did not change.
    body = delivery("venue-address-only", {"occurrences": synthesized, "total": 1, "ids": [live.id],
                                           "event_venue": True, "event_venue_name": False,
                                           "total_exact": True})
    assert "New venue" not in body and "Piscine X" in body
    # Event-level name change, the session has its own override: unchanged.
    live.venue_name = "Bassin A"
    db.commit()
    body = delivery("venue-override", {"occurrences": synthesized, "total": 1, "ids": [live.id],
                                       "event_venue": True, "event_venue_name": True,
                                       "total_exact": True})
    assert "New venue" not in body and "Bassin A" in body
    # Event-level name change, the session inherits the event venue: changed.
    live.venue_name = None
    db.commit()
    body = delivery("venue-inherited", {"occurrences": synthesized, "total": 1, "ids": [live.id],
                                        "event_venue": True, "event_venue_name": True,
                                        "total_exact": True})
    assert "New venue: Piscine X" in body
    # Legacy rows (no flag) keep the previous behavior.
    assert "New venue" in delivery("venue-legacy", {"occurrences": synthesized, "total": 1,
                                                    "ids": [live.id], "event_venue": True,
                                                    "total_exact": True})


def test_read_side_strips_uneffective_venue_changes(cal):
    """The read row drops a venue_changed kind that did not change the
    session's effective venue instead of claiming 'Place changed' — judged
    per occurrence, so a session that inherits the event venue keeps its
    line even when the delivery session has its own override."""
    from tests.test_calendar_domain import _occ
    db, occ = cal["db"], cal["occ"]["ga"]
    live = db.get(EventOccurrence, occ.id)
    live.venue_name = "Bassin A"  # the delivery session's own override
    other = _occ(db, db.get(type(cal["events"]["ga"]), occ.event_id), "ga-2", 2)  # inherits
    db.commit()
    items = [{"id": live.id, "kinds": ["venue_changed"]}, {"id": other.id, "kinds": ["venue_changed"]}]
    for key, event_venue_name in (("read-address-only", False), ("read-override", True)):
        details = {"occurrences": items, "total": len(items), "ids": [live.id, other.id],
                   "event_venue": True, "event_venue_name": event_venue_name, "total_exact": True}
        row = alerts.notification_service.stage(db, user_id=uid(cal, "alice"), type="calendar_change",
                                                title=alerts.GENERIC_TITLES["change"])
        db.add(alerts._new_delivery(delivery_key=key, kind="change", notif_type="calendar_change",
                                    user_id=uid(cal, "alice"), event_id=occ.event_id, occurrence_id=live.id,
                                    details=details, notification_id=row.id,
                                    expires_at=datetime.utcnow() + timedelta(days=1), now=datetime.utcnow()))
    db.commit()
    reader = db.get(AppUser, uid(cal, "alice"))
    for key, expected in (("read-address-only", [[], []]), ("read-override", [[], ["venue_changed"]])):
        delivery_row = deliveries(cal, delivery_key=key)[0]
        notification = db.get(Notification, delivery_row.notification_id)
        view = alerts.render_for_reader(db, reader, [notification])[notification.id]
        assert [c["kinds"] for c in view["calendar"]["changes"]] == expected


def test_merged_details_stay_inexact_after_a_legacy_merge():
    """A false total_exact survives later merges: a legacy side's unlisted
    sessions are missing from every future union, whatever the ledgers."""
    legacy = {"occurrences": [{"id": i, "kinds": ["venue_changed"]} for i in range(100, 110)], "total": 15}
    first = alerts._merge_details(legacy, {"occurrences": [{"id": 200, "kinds": ["time_changed"],
                                                            "old_start": "2026-11-13T18:00:00Z",
                                                            "new_start": "2026-11-13T19:00:00Z"}],
                                           "ids": [200], "total": 1}, keep_id=200)
    assert first["total_exact"] is False and first["total"] == 15
    second = alerts._merge_details(first, {"occurrences": [{"id": 300, "kinds": ["time_changed"],
                                                            "old_start": "2026-11-13T18:00:00Z",
                                                            "new_start": "2026-11-13T19:00:00Z"}],
                                           "ids": [300], "total": 1}, keep_id=200)
    # Still the lower bound, never presented as an exact 12.
    assert second["total_exact"] is False and second["total"] == 15


def test_push_body_renders_all_day_moves_as_dates(cal):
    """All-day sessions have no real time (local dates define them): a move
    renders 'Moved from Sun 15 Nov to Mon 16 Nov', never a '00:00'."""
    db, occ = cal["db"], cal["occ"]["club"]
    live = db.get(EventOccurrence, occ.id)
    details = {"occurrences": [{"id": live.id, "kinds": ["time_changed"],
                                "old_start": (TODAY + timedelta(days=2)).isoformat() + "T00:00:00Z",
                                "new_start": (TODAY + timedelta(days=3)).isoformat() + "T00:00:00Z"}],
               "total": 1}
    db.add(alerts._new_delivery(delivery_key="push-allday-move", kind="change", notif_type="calendar_change",
                                user_id=uid(cal, "alice"), event_id=live.event_id, occurrence_id=live.id,
                                details=details, expires_at=datetime.utcnow() + timedelta(days=1),
                                now=datetime.utcnow()))
    db.commit()
    payload = alerts.push_payload(db, deliveries(cal, delivery_key="push-allday-move")[0])
    assert payload["body"] == "Club camp · Moved from Sun 15 Nov to Mon 16 Nov · Mon 16 Nov"
    assert "00:00" not in payload["body"]


def test_push_body_omits_change_strings_without_the_delivery_occurrence(cal):
    """Rows written before the cap kept the delivery's session (or any row
    whose item went missing) degrade to what/where/group/when: another
    session's moved-from/to is never paired with this session's date."""
    db, occ = cal["db"], cal["occ"]["ga"]
    live = db.get(EventOccurrence, occ.id)
    live.venue_name = "Bassin A"
    db.commit()
    details = {"occurrences": [{"id": live.id + 100, "kinds": ["time_changed"],
                                "old_start": live.starts_at.isoformat() + "Z",
                                "new_start": live.starts_at.isoformat() + "Z"}], "total": 2}
    db.add(alerts._new_delivery(delivery_key="push-noitem", kind="change", notif_type="calendar_change",
                                user_id=uid(cal, "alice"), event_id=occ.event_id, occurrence_id=live.id,
                                details=details, expires_at=datetime.utcnow() + timedelta(days=1),
                                now=datetime.utcnow()))
    db.commit()
    payload = alerts.push_payload(db, deliveries(cal, delivery_key="push-noitem")[0])
    start = live.starts_at
    expected_when = start.replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Europe/Paris")).strftime(
        "%a %d %b %H:%M")
    assert payload["body"] == f"Groupe A training · Bassin A · Groupe A · {expected_when} · +1 more"


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
    # The whole event was cancelled: the row's session is still "scheduled"
    # (cancel_event leaves occurrences untouched) and event_cancelled says so.
    assert [i["calendar"]["kind"] for i in items] == ["cancellation"]
    assert items[0]["calendar"]["event_cancelled"] is True and items[0]["calendar"]["status"] == "scheduled"


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
    assert item["calendar"]["calendar_name"] == "Groupe A"
    # The reminder push carries the real details: what, group, when (no venue
    # in this fixture — the pool shows up as soon as the event has one).
    start = cal["db"].get(EventOccurrence, cal["occ"]["ga"].id).starts_at
    expected_when = start.replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Europe/Paris")).strftime(
        "%a %d %b %H:%M")
    alice_push = next(p for u, p in pushes if u == uid(cal, "alice"))
    assert alice_push["title"] == alerts.GENERIC_TITLES["reminder"]
    assert alice_push["body"] == f"Groupe A training · Groupe A · {expected_when}"
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


@pytest.mark.parametrize("change,reason", [
    ("membership", "no_access"), ("preference", "pref_off"),
    ("move", "changed"), ("cancel", "cancelled"),
    ("absence", "absent"), ("feature", "feature_disabled"), ("expired", "stale"), ("none", None),
])
def test_crash_window_push_retry_rechecks_current_eligibility(cal, flags, change, reason):
    place_on(cal, "ga", TODAY + timedelta(days=3))
    interest(cal, "alice", "ga")
    now = due_of(cal, "ga") + timedelta(minutes=1)
    run(cal, now=now)
    db = cal["db"]
    delivery = deliveries(cal, user_id=uid(cal, "alice"), kind="reminder")[0]
    delivery_id, notification_id = delivery.id, delivery.notification_id
    # Simulate a crash after the inbox commit, before the push attempt.
    delivery.push_state, delivery.lease_owner, delivery.lease_until = "pending", None, None
    if change == "membership":
        member = access.active_membership(db, cal["users"]["alice"], cal["clubs"]["k"].id)
        member.status, member.ended_at = "left", datetime.utcnow()
    elif change == "move":
        db.get(EventOccurrence, delivery.occurrence_id).version += 1
    elif change == "cancel":
        occurrence = db.get(EventOccurrence, delivery.occurrence_id)
        occurrence.status, occurrence.cancelled_at = "cancelled", datetime.utcnow()
    elif change == "expired":
        delivery.expires_at = now
    db.commit()
    if change == "preference":
        assert cal["login"]("alice").put("/api/v1/notification-prefs", json={
            "type": "calendar_reminder", "enabled": False}).status_code == 200
    elif change == "absence":
        assert cal["login"]("alice").put(f"{API}/occurrences/{delivery.occurrence_id}/absence",
                                               json={"absent": True}).status_code == 200
    elif change == "feature":
        flags.calendar_enabled = False
    db.rollback()
    pushes = Pushes()
    alerts.retry_push(factory(cal), "retry-worker", now + timedelta(minutes=1), 100, pushes)
    db.expire_all()
    saved = db.get(CalendarAlertDelivery, delivery_id)
    assert saved.status == "delivered" and saved.notification_id == notification_id
    assert db.get(Notification, notification_id) is not None
    assert saved.suppressed_reason == reason
    assert saved.push_state == ("sent" if reason is None else "skipped")
    assert len(pushes) == (1 if reason is None else 0)


@pytest.mark.parametrize("queue", ["outbox", "delivery"])
def test_health_not_ready_with_dead_letters_even_after_success(cal, queue):
    now = datetime.utcnow()
    run(cal, now=now)
    patch_occ(cal, "coach", cal["occ"]["ga"].id, venue_name="Health regression")
    db = cal["db"]
    if queue == "delivery":
        # The HTTP write can take longer than one second on a loaded runner.
        # Drive the worker from the committed job's clock, not the timestamp
        # captured before that write (which may precede its eligibility).
        outbox = db.query(CalendarAlertOutbox).order_by(CalendarAlertOutbox.id.desc()).first()
        assert outbox is not None
        expand_at = outbox.next_attempt_at
        db.rollback()
        alerts.expand_outbox(factory(cal), "health-test", expand_at, 100)
        row = deliveries(cal)[0]
    else:
        row = db.query(CalendarAlertOutbox).order_by(CalendarAlertOutbox.id.desc()).first()
    row.status = "dead"
    db.commit()
    response = cal["login"]("admin").get(f"{API}/admin/alerts/health")
    assert response.status_code == 503
    assert response.json()["worker"] == "ok"
    assert response.json()["ready"] is False
    assert ("outbox_dead_letters" if queue == "outbox" else "deliveries_dead_letters") in response.json()["problems"]


def test_scheduled_push_budget_preserves_inbox_and_drains_oldest(cal):
    for key, who in (("ga", "alice"), ("gb", "bob")):
        place_on(cal, key, TODAY + timedelta(days=3))
        interest(cal, who, key)
    now = due_of(cal, "ga") + timedelta(minutes=1)
    pushes = Pushes()
    first = run(cal, now=now, pushes=pushes, push_limit=1)
    assert first["delivered"] == 2 and len(pushes) == 1
    rows = deliveries(cal)
    assert [d.push_state for d in rows] == ["sent", "pending"]
    assert all(d.notification_id is not None for d in rows)
    assert rows[1].lease_owner is None
    run(cal, now=now + timedelta(minutes=1), pushes=pushes, push_limit=1)
    assert len(pushes) == 2
    assert all(d.push_state == "sent" for d in deliveries(cal))


def test_reminders_page_past_500_candidates_and_preserve_idempotence(cal):
    from tests.test_calendar_domain import _occ
    db = cal["db"]
    event = cal["events"]["fed"]
    rows = [_occ(db, event, f"paging-{i}", 10, hour=8) for i in range(501)]
    last = rows[-1]
    last_id = last.id
    db.add(OccurrenceInterest(occurrence_id=last_id, user_id=uid(cal, "alice"), state="interested"))
    now = alerts.reminder_due(last, event) + timedelta(minutes=1)
    db.commit()
    assert alerts.plan_reminders(factory(cal), now, 100)["reminders_planned"] == 1
    assert alerts.plan_reminders(factory(cal), now, 100)["reminders_planned"] == 0
    assert deliveries(cal, kind="reminder")[0].occurrence_id == last_id
