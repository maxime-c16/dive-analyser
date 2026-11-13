"""Reliable calendar alerts (Task05): outbox, worker and read-time rendering.

Write side (inside the caller's transaction, never commits):
- calendar_events.log_change attaches every change-log row to one
  CalendarAlertOutbox row per event per transaction (outbox_for), and
  invite() records new invitees on it (note_invitations). A rollback removes
  the event write, its change log and its outbox row together.

Worker (run_once, CLI scripts/calendar_alerts_worker.py), each phase bounded:
1. expand: claim pending outbox rows (row lease), turn each into
   per-recipient deliveries with a unique delivery_key, mark it done.
2. plan reminders: previous-day reminders whose due time is now (within a
   grace window). Nothing older is ever planned, so downtime never replays
   old reminders.
3. dispatch: claim due deliveries, re-check freshness, account state,
   current visibility (Task02 predicates: membership/group loss, revoked
   invitation), occurrence version/status and preferences; then commit the
   inbox row together with the delivery state (one inbox row per delivery
   key, enforced by a conditional update and a unique notification_id).
   Web Push runs only after that commit and is best-effort.
4. push retry: a push interrupted by a crash is retried within 15 minutes;
   older ones expire. External push cannot be exactly-once.
Overlapping runs are excluded by a leased calendar_worker_state row; rows
carry their own leases so an expired run lease can never double-deliver.
Failures retry with exponential backoff and become "dead" (visible in
status/health) after MAX_ATTEMPTS.

Read side: calendar inbox rows store only a generic title. The API resolves
the event at read time for the reader; when the reader can no longer see it
the row is redacted (no title, details or link). Push previews carry the real
details (what/where/group/when): each is built at send time, right after the
recipient passed the visibility re-check, and Web Push payloads are encrypted
to the recipient's device.
"""
import logging
import os
import socket
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, inspect, or_
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.calendar_launch import enabled as calendar_enabled
from app.models.calendar import (
    Calendar, CalendarAlertDelivery, CalendarAlertOutbox, CalendarChangeLog, CalendarEvent, CalendarEventFollow,
    CalendarSubscription, CalendarWorkerState, ClubMembership, EventInvitation, EventOccurrence,
    OccurrenceAbsenceReport, OccurrenceInterest, TrainingGroupMembership,
)
from app.models.notification import Notification, NotificationPref
from app.models.user_auth import AppUser
from app.services import calendar_access as access
from app.services import notification_service

logger = logging.getLogger(__name__)

WORKER_NAME = "calendar-alerts"
RUN_LEASE = timedelta(minutes=12)
ROW_LEASE = timedelta(minutes=10)
MAX_ATTEMPTS = 6
BACKOFF_BASE_SECONDS = 30
BACKOFF_MAX_SECONDS = 3600
CHANGE_TTL = timedelta(days=7)
REMINDER_GRACE = timedelta(hours=6)
REMINDER_LOOKAHEAD = timedelta(hours=48)
PUSH_RETRY_WINDOW = timedelta(minutes=15)
DEFAULT_BATCH = 100
MAX_BATCH = 500
MAX_RECIPIENTS = 2000
MAX_DETAIL_OCCURRENCES = 10
MAX_AFFECTED_OCCURRENCES = 400
# Identity ledger of an alert's affected sessions (exact union count on
# merge). Bounded far above any real event's occurrence count; past it the
# total degrades to the safe lower bound.
MAX_UNION_IDS = 1000
STALE_WORKER = timedelta(minutes=int(os.getenv("CALENDAR_ALERTS_STALE_MINUTES", "15")))
SCHEMA_TABLES = ("calendar_alert_outbox", "calendar_alert_deliveries", "calendar_worker_state")

PARTICIPANT_INTEREST = ("interested", "maybe")
CHANGE_INVITATION = ("pending", "accepted")

# Inbox titles are generic on purpose: event details are resolved per reader
# at read time (redacted once access is lost). English like other inbox rows;
# the web UI renders localized FR/EN text from the structured payload. Push
# previews keep these generic titles but carry the real details in their body
# (push_payload, built at send time behind the visibility re-check).
GENERIC_TITLES = {
    "invitation": "Calendar invitation",
    "change": "Calendar event changed",
    "cancellation": "Calendar event cancelled",
    "reminder": "Calendar reminder: tomorrow",
    "new_event": "New event in a calendar you follow",
}
PUSH_BODY_PRIVATE = "Open the app to see the details."
PUSH_MORE_UNCOUNTED = "and more sessions"
PUSH_TITLE_SESSION_CANCELLED = "Calendar session cancelled"
REDACTED_TITLE = "Calendar update"


def utcnow() -> datetime:
    return datetime.utcnow()


# --- Write side: transaction-aware outbox ----------------------------------------------------------

_TX_KEY = "calendar_alert_outbox"


def outbox_for(db: Session, event: CalendarEvent, actor: Optional[AppUser] = None,
               from_import: bool = False) -> CalendarAlertOutbox:
    """The outbox row of this event in the current transaction (created once).

    Cached per root transaction object: a new transaction (after commit or
    rollback) gets a new row, and a row discarded by a rolled-back savepoint
    is no longer in the session, so it is replaced."""
    tx = db.get_transaction()
    cache = db.info.get(_TX_KEY)
    if tx is None or cache is None or cache[0] is not tx:
        cache = (tx, {})
        db.info[_TX_KEY] = cache
    row = cache[1].get(event.id)
    if row is None or row not in db:
        row = CalendarAlertOutbox(event_id=event.id, actor_user_id=actor.id if actor else None,
                                  from_import=from_import, invitee_ids=[], status="pending",
                                  attempts=0, next_attempt_at=utcnow(), created_at=utcnow())
        db.add(row)
        cache[1][event.id] = row
    elif from_import and not row.from_import:
        row.from_import = True
    return row


def note_invitations(db: Session, event: CalendarEvent, actor: AppUser, user_ids: Iterable[int]) -> None:
    ids = sorted({int(u) for u in user_ids})
    if not ids:
        return
    row = outbox_for(db, event, actor)
    row.invitee_ids = sorted(set(row.invitee_ids or []) | set(ids))  # reassign: JSON change tracking


# --- Small helpers --------------------------------------------------------------------------------

def schema_ready(db: Session) -> bool:
    insp = inspect(db.get_bind())
    return all(insp.has_table(name) for name in SCHEMA_TABLES)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() + "Z" if value else None


def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(BACKOFF_BASE_SECONDS * 2 ** max(attempts - 1, 0), BACKOFF_MAX_SECONDS))


def _local_to_utc(local: datetime, tz_name: str) -> datetime:
    return local.replace(tzinfo=ZoneInfo(tz_name), fold=0).astimezone(timezone.utc).replace(tzinfo=None)


def _push_when(occ: Optional[EventOccurrence], event: CalendarEvent) -> str:
    """Compact English when in the event's own timezone: 'Fri 14 Nov 18:30'
    (all-day: 'Fri 14 Nov'). Stored times are naive UTC, like the inbox row."""
    if occ is None:
        return ""
    if occ.is_all_day:
        return occ.start_date.strftime("%a %d %b") if occ.start_date else ""
    if not occ.starts_at:
        return ""
    local = occ.starts_at.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(event.timezone))
    return local.strftime("%a %d %b %H:%M")


def _push_iso(value, event: CalendarEvent, all_day: bool = False) -> str:
    """A stored ISO instant ('...Z') rendered like _push_when ('' on garbage).
    All-day moves render as dates only: their window_start is local midnight,
    and the model defines all-day events by local dates — no real time."""
    try:
        instant = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=timezone.utc)
        local = instant.astimezone(ZoneInfo(event.timezone))
        return local.strftime("%a %d %b" if all_day else "%a %d %b %H:%M")
    except (TypeError, ValueError):
        return ""


def _local_day(occurrence: EventOccurrence, event: CalendarEvent) -> date:
    if occurrence.is_all_day:
        return occurrence.start_date
    return occurrence.window_start.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(event.timezone)).date()


def reminder_due(occurrence: EventOccurrence, event: CalendarEvent) -> datetime:
    """Previous local day at CALENDAR_REMINDER_HOUR (event timezone), as UTC."""
    hour = get_settings().calendar_reminder_hour
    return _local_to_utc(datetime.combine(_local_day(occurrence, event) - timedelta(days=1), time(hour)),
                         event.timezone)


def _occurrence_url(occurrence_id: Optional[int]) -> str:
    return f"/calendar/o/{int(occurrence_id)}" if occurrence_id else "/calendar"


def _enabled_map(db: Session, user_ids: List[int], notif_type: str) -> Dict[int, bool]:
    default = notification_service._ALL_DEFAULTS[notif_type]
    out = {uid: default for uid in user_ids}
    if user_ids:
        for row in db.query(NotificationPref).filter(NotificationPref.user_id.in_(user_ids),
                                                     NotificationPref.notif_type == notif_type):
            out[row.user_id] = bool(row.enabled)
    return out


def _group_members(db: Session, event: CalendarEvent, calendar: Calendar, on: date) -> List[int]:
    """Members expected at a training session without responding: the current
    assignment of a group calendar, or active members for club-wide training
    (the same population as absence reporting)."""
    if event.event_type != "training" or calendar.club_id is None:
        return []
    if event.audience == "group" and calendar.training_group_id is not None:
        rows = db.query(TrainingGroupMembership.user_id).join(
            ClubMembership, ClubMembership.id == TrainingGroupMembership.club_membership_id).filter(
            TrainingGroupMembership.group_id == calendar.training_group_id,
            TrainingGroupMembership.effective_from <= on,
            or_(TrainingGroupMembership.effective_to.is_(None), TrainingGroupMembership.effective_to > on),
            ClubMembership.ended_at.is_(None)).limit(MAX_RECIPIENTS)
        return [r[0] for r in rows]
    if event.audience == "club":
        rows = db.query(ClubMembership.user_id).filter(
            ClubMembership.club_id == calendar.club_id, ClubMembership.ended_at.is_(None)).limit(MAX_RECIPIENTS)
        return [r[0] for r in rows]
    return []


# --- Run lease and row leases -------------------------------------------------------------------------

def _worker_state(db: Session) -> CalendarWorkerState:
    state = db.get(CalendarWorkerState, WORKER_NAME, populate_existing=True)
    if state is None:
        db.add(CalendarWorkerState(name=WORKER_NAME, runs=0, failures=0, last_stats={}))
        try:
            db.commit()
        except Exception:
            db.rollback()  # created concurrently
        state = db.get(CalendarWorkerState, WORKER_NAME)
    return state


def acquire_run(db: Session, owner: str, now: datetime) -> bool:
    _worker_state(db)
    claimed = db.query(CalendarWorkerState).filter(
        CalendarWorkerState.name == WORKER_NAME,
        or_(CalendarWorkerState.lease_until.is_(None), CalendarWorkerState.lease_until < now)).update(
        {"lease_owner": owner, "lease_until": now + RUN_LEASE, "last_started_at": now,
         "runs": CalendarWorkerState.runs + 1}, synchronize_session=False)
    db.commit()
    return claimed == 1


def finish_run(db: Session, owner: str, now: datetime, stats: dict, error: Optional[str] = None) -> None:
    values = {"lease_owner": None, "lease_until": None, "last_stats": stats}
    if error is None:
        values["last_success_at"] = now
    else:
        values.update(last_error=error[:200], last_error_at=now, failures=CalendarWorkerState.failures + 1)
    db.query(CalendarWorkerState).filter(CalendarWorkerState.name == WORKER_NAME,
                                         CalendarWorkerState.lease_owner == owner).update(
        values, synchronize_session=False)
    db.commit()


def _claim(db: Session, model, owner: str, now: datetime, batch: int, *filters) -> List[int]:
    """Lease up to `batch` due rows. Each claim is a conditional UPDATE, so
    two workers can never hold the same row; ids are claimed in ascending
    order (consistent lock order on PostgreSQL)."""
    free = or_(model.lease_until.is_(None), model.lease_until < now)
    ids = sorted(r[0] for r in db.query(model.id).filter(
        model.status == "pending", model.next_attempt_at <= now, free, *filters).order_by(
        model.next_attempt_at, model.id).limit(batch))
    claimed = []
    for row_id in ids:
        if db.query(model).filter(model.id == row_id, model.status == "pending", free).update(
                {"lease_owner": owner, "lease_until": now + ROW_LEASE}, synchronize_session=False):
            claimed.append(row_id)
    db.commit()
    return claimed


def _record_failure(db: Session, model, row_id: int, owner: str, now: datetime, exc: Exception) -> str:
    db.rollback()
    row = db.get(model, row_id, populate_existing=True)
    if row is None or row.lease_owner != owner:
        db.rollback()
        return "lost"
    row.attempts = (row.attempts or 0) + 1
    row.last_error = type(exc).__name__[:200]
    row.lease_owner = row.lease_until = None
    if row.attempts >= MAX_ATTEMPTS:
        row.status = "dead"
    else:
        row.next_attempt_at = now + _backoff(row.attempts)
    db.commit()
    logger.error("calendar alert %s %s failed (attempt %s, %s)", model.__tablename__, row_id, row.attempts,
                 row.last_error)
    return row.status


# --- Phase 1: outbox expansion ---------------------------------------------------------------------------

def _details_from_logs(logs: List[CalendarChangeLog]) -> tuple:
    """(per-occurrence changes, event_cancelled, event_venue, event_venue_name).

    event_venue marks an event-level change of ANY venue field (the writer
    logs venue_name, venue_address and map_url alike); event_venue_name
    says whether the venue NAME itself changed — only that reaches the
    sessions' effective venue."""
    per: Dict[int, dict] = {}
    event_cancelled = event_venue = event_venue_name = False
    for log in logs:
        kind = log.change_kind
        if kind == "cancelled":
            if log.occurrence_id:
                per.setdefault(log.occurrence_id, {"kinds": set()})["kinds"].add("cancelled")
            else:
                event_cancelled = True
        elif kind == "time_changed" and log.occurrence_id:
            entry = per.setdefault(log.occurrence_id, {"kinds": set()})
            entry["kinds"].add("time_changed")
            old, new = (log.changes or {}).get("window_start", [None, None])
            entry.setdefault("old_start", old)
            entry["new_start"] = new
            # A form change (all-day <-> timed) carries each endpoint's shape:
            # the old local midnight must not render as "00:00", and the new
            # all-day endpoint must not drop its date (latest log wins).
            shapes = (log.changes or {}).get("is_all_day")
            if isinstance(shapes, (list, tuple)) and len(shapes) == 2:
                entry["old_all_day"], entry["new_all_day"] = bool(shapes[0]), bool(shapes[1])
        elif kind == "venue_changed":
            if log.occurrence_id:
                entry = per.setdefault(log.occurrence_id, {"kinds": set()})
                entry["kinds"].add("venue_changed")
                # The session's own new venue: a merged alert can mix venue
                # changes across sessions, and the delivery session's venue is
                # not theirs. Writers record ("old", "new"); event-level
                # synthesized items fall back to the delivery venue.
                new_venue = (log.changes or {}).get("venue_name")
                if isinstance(new_venue, (list, tuple)) and len(new_venue) == 2:
                    entry["venue"] = new_venue[1]
                elif isinstance(new_venue, str):
                    entry["venue"] = new_venue
            else:
                event_venue = True
                if "venue_name" in (log.changes or {}):
                    event_venue_name = True
    return per, event_cancelled, event_venue, event_venue_name


def _merge_details(old: dict, new: dict, keep_id: Optional[int] = None) -> dict:
    """Combine a superseded pending alert with the newer one: kinds union,
    the oldest 'old_start' and the newest 'new_start' per occurrence.
    The rendered list is capped by occurrence id, except `keep_id` — the
    surviving delivery's own session — which the cap never drops: the push
    and the read row are keyed to that session. The `ids` ledger keeps the
    union of both alerts' sessions, so `total` is the exact session count
    whenever both sides carry the ledger (only legacy rows lack it, or a
    past-MAX_UNION_IDS union degrades to the safe lower bound)."""
    old_occ = old.get("occurrences") or []
    new_occ = new.get("occurrences") or []
    merged = {o["id"]: dict(o) for o in old_occ}
    for item in new_occ:
        prev = merged.get(item["id"])
        if prev is None:
            merged[item["id"]] = dict(item)
            continue
        prev["kinds"] = sorted(set(prev.get("kinds", [])) | set(item.get("kinds", [])))
        if item.get("new_start"):
            prev.setdefault("old_start", item.get("old_start"))
            if prev.get("old_start") is None:
                prev["old_start"] = item.get("old_start")
            prev["new_start"] = item["new_start"]
        # All-day shapes ride along with the times they describe: the oldest
        # old shape and the newest new shape, like the times themselves.
        if "old_all_day" in item:
            prev.setdefault("old_all_day", item["old_all_day"])
        if "new_all_day" in item:
            prev["new_all_day"] = item["new_all_day"]
        if item.get("venue") is not None:
            prev["venue"] = item["venue"]
    known = set(merged)  # the ids ledger keys: the union of listed sessions
    for side in (old.get("ids"), new.get("ids")):
        if isinstance(side, list):
            known.update(i for i in side if isinstance(i, int))
    ordered_ids = sorted(known)[:MAX_UNION_IDS]
    # Exactness must survive merges: a side whose history is already inexact
    # (legacy rows, a past bound) keeps every later union inexact too, even
    # when both sides carry an ids ledger.
    exact = (isinstance(old.get("ids"), list) and isinstance(new.get("ids"), list)
             and len(known) <= MAX_UNION_IDS
             and old.get("total_exact", True) and new.get("total_exact", True))
    out = dict(new)
    out["ids"] = ordered_ids
    # A legacy side (no ledger) hides its unlisted sessions: the count is a
    # safe lower bound and consumers must not present it as exact.
    out["total_exact"] = exact
    out["total"] = len(known) if exact else max(old.get("total") or 0, new.get("total") or 0,
                                                len(ordered_ids))
    capped = sorted(merged.values(), key=lambda o: o["id"])[:MAX_DETAIL_OCCURRENCES]
    if keep_id is not None and keep_id in merged and all(o["id"] != keep_id for o in capped):
        capped = sorted(capped[:MAX_DETAIL_OCCURRENCES - 1] + [merged[keep_id]],
                        key=lambda o: o["id"])
    out["occurrences"] = capped
    out["event_cancelled"] = bool(old.get("event_cancelled") or new.get("event_cancelled"))
    out["event_venue"] = bool(old.get("event_venue") or new.get("event_venue"))
    out["event_venue_name"] = bool(old.get("event_venue_name") or new.get("event_venue_name"))
    return out


def _new_delivery(**values) -> CalendarAlertDelivery:
    now = values.pop("now")
    return CalendarAlertDelivery(status="pending", attempts=0, due_at=now, next_attempt_at=now, created_at=now,
                                 **values)


def expand_one(db: Session, outbox: CalendarAlertOutbox, now: datetime) -> int:
    """Create the deliveries of one outbox row (flush only). Returns count."""
    event = db.get(CalendarEvent, outbox.event_id)
    if event is None or event.status == "draft":
        return 0  # drafts notify nobody; pending invitees are told at publish
    written = outbox.created_at or now
    if now - written > CHANGE_TTL:
        return 0  # e.g. written while the worker was off: never announced late
    horizon = written + CHANGE_TTL
    calendar = db.get(Calendar, event.calendar_id)
    logs = db.query(CalendarChangeLog).filter(CalendarChangeLog.outbox_id == outbox.id).order_by(
        CalendarChangeLog.id).all()
    actor = outbox.actor_user_id
    per, event_cancelled, event_venue, event_venue_name = _details_from_logs(logs)
    occurrences = {o.id: o for o in db.query(EventOccurrence).filter(
        EventOccurrence.event_id == event.id, EventOccurrence.window_end > now).order_by(
        EventOccurrence.window_start).limit(MAX_AFFECTED_OCCURRENCES)}
    affected = {oid: info for oid, info in per.items() if oid in occurrences}
    if event_cancelled or event_venue:
        for oid in occurrences:
            entry = affected.setdefault(oid, {"kinds": set()})
            entry["kinds"].add("cancelled" if event_cancelled else "venue_changed")
    deliveries: Dict[str, CalendarAlertDelivery] = {}
    created = 0

    def add(key, **values):
        if key not in deliveries:
            deliveries[key] = _new_delivery(delivery_key=key, event_id=event.id, outbox_id=outbox.id, now=now,
                                            **values)

    if affected:
        # Who takes part in which affected occurrence.
        per_user: Dict[int, set] = {}
        follow_only: set = set()
        for oid, uid in db.query(OccurrenceInterest.occurrence_id, OccurrenceInterest.user_id).filter(
                OccurrenceInterest.occurrence_id.in_(list(affected)),
                OccurrenceInterest.state.in_(PARTICIPANT_INTEREST)).limit(MAX_RECIPIENTS):
            per_user.setdefault(uid, set()).add(oid)
        everyone = [r[0] for r in db.query(EventInvitation.invitee_user_id).filter(
            EventInvitation.event_id == event.id, EventInvitation.status.in_(CHANGE_INVITATION)).limit(MAX_RECIPIENTS)]
        everyone += _group_members(db, event, calendar, now.date())
        for uid in everyone:
            per_user.setdefault(uid, set()).update(affected)
        for (uid,) in db.query(CalendarEventFollow.user_id).filter(
                CalendarEventFollow.event_id == event.id).limit(MAX_RECIPIENTS):
            if uid not in per_user:
                follow_only.add(uid)
                per_user[uid] = set(affected)
        per_user.pop(actor, None)
        for uid, oids in list(per_user.items())[:MAX_RECIPIENTS]:
            items = []
            for oid in sorted(oids, key=lambda i: occurrences[i].window_start):
                info = affected[oid]
                item = {"id": oid, "kinds": sorted(info["kinds"]), "old_start": info.get("old_start"),
                        "new_start": info.get("new_start")}
                # Each endpoint's all-day shape (a form change formats its two
                # ends independently; the current shape is the fallback).
                shape_now = bool(occurrences[oid].is_all_day)
                item["old_all_day"] = bool(info.get("old_all_day", shape_now))
                item["new_all_day"] = bool(info.get("new_all_day", shape_now))
                if info.get("venue") is not None:
                    item["venue"] = info["venue"]
                items.append(item)
            cancelled = event_cancelled or any("cancelled" in i["kinds"] for i in items)
            kind = "cancellation" if cancelled else "change"
            details = {"occurrences": items[:MAX_DETAIL_OCCURRENCES], "total": len(items),
                       "ids": [i["id"] for i in items], "total_exact": True,
                       "event_cancelled": event_cancelled, "event_venue": event_venue,
                       "event_venue_name": event_venue_name}
            # Supersede pending, undelivered change alerts of the same event:
            # one up-to-date alert instead of a stale sequence.
            for old in db.query(CalendarAlertDelivery).filter(
                    CalendarAlertDelivery.user_id == uid, CalendarAlertDelivery.event_id == event.id,
                    CalendarAlertDelivery.kind.in_(("change", "cancellation")),
                    CalendarAlertDelivery.status == "pending",
                    or_(CalendarAlertDelivery.lease_until.is_(None), CalendarAlertDelivery.lease_until < now)):
                details = _merge_details(old.details or {}, details, keep_id=items[0]["id"])
                old.status, old.suppressed_reason = "suppressed", "superseded"
            if details.get("event_cancelled") or any("cancelled" in i["kinds"] for i in details["occurrences"]):
                kind = "cancellation"
            last_end = max(occurrences[i].window_end for i in oids)
            add(f"o{outbox.id}:u{uid}:alert", kind=kind,
                notif_type="calendar_follow" if uid in follow_only else "calendar_change",
                user_id=uid, occurrence_id=items[0]["id"], details=details,
                expires_at=min(horizon, last_end))
        # Obsolete reminders: a moved or cancelled occurrence never reminds
        # anyone of the old slot (dispatch re-checks too).
        moved = [oid for oid, info in affected.items() if info["kinds"] & {"time_changed", "cancelled"}]
        if moved:
            db.query(CalendarAlertDelivery).filter(
                CalendarAlertDelivery.kind == "reminder", CalendarAlertDelivery.status == "pending",
                CalendarAlertDelivery.occurrence_id.in_(moved),
                or_(CalendarAlertDelivery.lease_until.is_(None), CalendarAlertDelivery.lease_until < now)).update(
                {"status": "suppressed", "suppressed_reason": "changed"}, synchronize_session=False)

    upcoming = [o for o in occurrences.values() if o.status == "scheduled"]
    if event.status == "published" and upcoming:
        first = min(upcoming, key=lambda o: o.window_start)
        expires = min(horizon, max(o.window_end for o in upcoming))
        published = any(log.change_kind == "published" for log in logs)
        invitees = set(outbox.invitee_ids or [])
        if published:
            invitees |= {r[0] for r in db.query(EventInvitation.invitee_user_id).filter(
                EventInvitation.event_id == event.id, EventInvitation.status == "pending").limit(MAX_RECIPIENTS)}
            if not outbox.from_import:
                for (uid,) in db.query(CalendarSubscription.user_id).filter(
                        CalendarSubscription.calendar_id == event.calendar_id).limit(MAX_RECIPIENTS):
                    if uid != actor and uid not in invitees:
                        add(f"o{outbox.id}:u{uid}:new", kind="new_event", notif_type="calendar_follow",
                            user_id=uid, occurrence_id=first.id, details={}, expires_at=expires)
        for uid in sorted(invitees):
            if uid != actor:
                add(f"o{outbox.id}:u{uid}:invitation", kind="invitation", notif_type="calendar_invitation",
                    user_id=uid, occurrence_id=first.id, details={}, expires_at=expires)

    existing = {r[0] for r in db.query(CalendarAlertDelivery.delivery_key).filter(
        CalendarAlertDelivery.delivery_key.in_(list(deliveries)))} if deliveries else set()
    for key, row in deliveries.items():
        if key not in existing:
            db.add(row)
            created += 1
    db.flush()
    return created


def expand_outbox(factory: Callable[[], Session], owner: str, now: datetime, batch: int) -> dict:
    stats = {"outbox_done": 0, "deliveries_created": 0, "outbox_failed": 0}
    with factory() as db:
        claimed = _claim(db, CalendarAlertOutbox, owner, now, batch)
        for row_id in claimed:
            try:
                row = db.get(CalendarAlertOutbox, row_id, populate_existing=True)
                if row is None or row.lease_owner != owner or row.status != "pending":
                    db.rollback()
                    continue
                stats["deliveries_created"] += expand_one(db, row, now)
                row.status, row.processed_at = "done", now
                row.lease_owner = row.lease_until = None
                db.commit()
                stats["outbox_done"] += 1
            except Exception as exc:  # noqa: BLE001 - recorded with type only, retried with backoff
                _record_failure(db, CalendarAlertOutbox, row_id, owner, now, exc)
                stats["outbox_failed"] += 1
    return stats


# --- Phase 2: reminder planning ------------------------------------------------------------------------------

def plan_reminders(factory: Callable[[], Session], now: datetime, batch: int) -> dict:
    """Create the reminders that are due now. A reminder whose due time is
    more than REMINDER_GRACE in the past is never created (no replay)."""
    created = 0
    with factory() as db:
        candidates = db.query(EventOccurrence, CalendarEvent, Calendar).join(
            CalendarEvent, CalendarEvent.id == EventOccurrence.event_id).join(
            Calendar, Calendar.id == CalendarEvent.calendar_id).filter(
            EventOccurrence.status == "scheduled", CalendarEvent.status == "published",
            EventOccurrence.window_start > now, EventOccurrence.window_start <= now + REMINDER_LOOKAHEAD).order_by(
            EventOccurrence.window_start, EventOccurrence.id)

        def pages():
            cursor = None
            while True:
                query = candidates
                if cursor is not None:
                    start, occurrence_id = cursor
                    query = query.filter(or_(EventOccurrence.window_start > start,
                        (EventOccurrence.window_start == start) & (EventOccurrence.id > occurrence_id)))
                rows = query.limit(MAX_BATCH).all()
                if not rows:
                    return
                for row in rows:
                    yield row
                cursor = (rows[-1][0].window_start, rows[-1][0].id)
                if len(rows) < MAX_BATCH:
                    return

        for occ, event, calendar in pages():
            due = reminder_due(occ, event)
            if not (due <= now < due + REMINDER_GRACE):
                continue
            targets = {uid: "calendar_reminder" for (uid,) in db.query(OccurrenceInterest.user_id).filter(
                OccurrenceInterest.occurrence_id == occ.id, OccurrenceInterest.state == "interested").limit(
                MAX_RECIPIENTS)}
            members = [u for u in _group_members(db, event, calendar, now.date()) if u not in targets]
            for uid, on in _enabled_map(db, members, "calendar_group_reminder").items():
                if on:
                    targets[uid] = "calendar_group_reminder"
            if not targets:
                continue
            stamp = occ.window_start.strftime("%Y%m%dT%H%M")
            keys = {f"r{occ.id}:{stamp}:u{uid}": (uid, kind) for uid, kind in targets.items()}
            existing = {r[0] for r in db.query(CalendarAlertDelivery.delivery_key).filter(
                CalendarAlertDelivery.delivery_key.in_(list(keys)))}
            for key, (uid, kind) in keys.items():
                if key in existing:
                    continue
                db.add(_new_delivery(delivery_key=key, kind="reminder", notif_type=kind, user_id=uid,
                                     event_id=event.id, occurrence_id=occ.id, target_version=occ.version,
                                     target_start=occ.window_start, details={},
                                     expires_at=min(due + REMINDER_GRACE, occ.window_start), now=now))
                created += 1
            if created >= batch:
                break
        db.commit()
    return {"reminders_planned": created}


# --- Phase 3: dispatch ---------------------------------------------------------------------------------------------

def suppression_reason(db: Session, d: CalendarAlertDelivery, now: datetime) -> Optional[str]:
    """Why this delivery must not be sent now (None = send)."""
    if now >= d.expires_at:
        return "stale"
    user = db.get(AppUser, d.user_id)
    if user is None or not user.is_active:
        return "inactive"
    event = db.get(CalendarEvent, d.event_id)
    occ = db.get(EventOccurrence, d.occurrence_id) if d.occurrence_id else None
    if event is None or (d.occurrence_id and occ is None):
        return "missing"
    if event.status == "draft":
        return "unpublished"
    if d.occurrence_id:
        visible = access.visible_occurrences(db, user).filter(EventOccurrence.id == d.occurrence_id).first()
    else:
        visible = access.visible_events(db, user).filter(CalendarEvent.id == d.event_id).first()
    if visible is None:
        return "no_access"
    if d.kind == "reminder":
        if occ.status != "scheduled" or event.status != "published":
            return "cancelled"
        if occ.window_start != d.target_start or occ.version != d.target_version:
            return "changed"
        if d.notif_type == "calendar_reminder":
            interest = db.get(OccurrenceInterest, (occ.id, d.user_id))
            if interest is None or interest.state != "interested":
                return "not_interested"
        elif d.user_id not in _group_members(db, event, db.get(Calendar, event.calendar_id), now.date()):
            return "not_assigned"
        absence = db.get(OccurrenceAbsenceReport, (occ.id, d.user_id))
        if absence is not None and absence.withdrawn_at is None:
            return "absent"
    elif d.kind in ("invitation",):
        invitation = db.query(EventInvitation).filter_by(event_id=d.event_id, invitee_user_id=d.user_id).one_or_none()
        if invitation is None or invitation.status == "revoked":
            return "revoked"
        if invitation.status != "pending":
            return "answered"
    elif d.kind == "new_event":
        if event.status != "published":
            return "cancelled"
    if not notification_service.is_enabled(db, d.user_id, d.notif_type):
        return "pref_off"
    return None


def push_payload(db: Session, d: CalendarAlertDelivery) -> dict:
    """Push preview: the kind label as title, the real details as body.

    Pilot feedback: "Open the app to see the details." conveys nothing on a
    lock screen. The body carries what/where/group/when, including for
    non-community events — it is built at send time, right after the
    recipient passed the visibility re-check (suppression_reason), and Web
    Push payloads are encrypted to the recipient's device, so no third
    party reads it in transit. The generic fallback is only for an event
    that vanished between the inbox commit and this read."""
    title = GENERIC_TITLES[d.kind]
    event = db.get(CalendarEvent, d.event_id)
    if event is None:
        return {"title": title, "body": PUSH_BODY_PRIVATE, "url": _occurrence_url(d.occurrence_id)}
    return {"title": _push_title(db, d, event), "body": _push_body(db, d, event),
            "url": _occurrence_url(d.occurrence_id)}


def _push_title(db: Session, d: CalendarAlertDelivery, event: CalendarEvent) -> str:
    """Cancellation wording follows its true scope: the whole event
    (event_cancelled), the recipient's own session (its occurrence is
    cancelled), or a plain change when another session was the cancelled
    one — models/EventOccurrence carries cancellation per occurrence."""
    if d.kind != "cancellation":
        return GENERIC_TITLES[d.kind]
    if (d.details or {}).get("event_cancelled"):
        return GENERIC_TITLES["cancellation"]
    occ = db.get(EventOccurrence, d.occurrence_id) if d.occurrence_id else None
    if occ is not None and occ.status == "cancelled":
        return PUSH_TITLE_SESSION_CANCELLED
    return GENERIC_TITLES["change"]


def _event_venue_reaches(details: dict, occ: Optional[EventOccurrence]) -> bool:
    """An event-level venue change marks every affected occurrence, but only
    a venue_NAME change reaches a session's effective venue — and only one
    without its own venue override. False for address/map_url-only edits
    (new rows); legacy rows (no flag) keep the previous behavior."""
    name_changed = details.get("event_venue_name")
    if name_changed is False:
        return False
    if name_changed is True:
        return occ is not None and occ.venue_name is None
    return True


def _push_body(db: Session, d: CalendarAlertDelivery, event: CalendarEvent) -> str:
    """'What · where · group · when' (plus what changed), ' · '-joined."""
    occ = db.get(EventOccurrence, d.occurrence_id) if d.occurrence_id else None
    details = d.details or {}
    items = details.get("occurrences") or []
    # d.occurrence_id is the newest alert's first affected session, but merged
    # details are sorted by occurrence id: select the change item of the
    # delivery's own session, so its moved-from/to times are never paired with
    # another session's date. If that session is absent from the list (legacy
    # rows written before _merge_details kept it under the cap), degrade to
    # what/where/group/when only — any change string would mispair.
    own = next((item for item in items if item.get("id") == d.occurrence_id), None)
    if own is None and items and d.occurrence_id is not None:
        own = {}
    kinds = set((own or {}).get("kinds") or [])
    # "Cancelled" describes this delivery's session, or a whole-event
    # cancellation — another session's cancellation never labels this row.
    cancelled = ("cancelled" in kinds or (occ is not None and occ.status == "cancelled")
                 or bool(details.get("event_cancelled")))
    parts: List[str] = [event.title]
    if cancelled:
        parts.append("Cancelled")
    venue = (occ.venue_name if occ is not None else None) or event.venue_name
    if venue:
        # "New venue" only when this session's effective venue name actually
        # changed: an occurrence-level log carries its own new venue, while an
        # event-level change reaches only sessions without their own override
        # and never an address/map_url-only edit.
        new_venue = "venue_changed" in kinds and (
            (own or {}).get("venue") is not None or _event_venue_reaches(details, occ))
        parts.append(f"New venue: {venue}" if new_venue else venue)
    calendar = db.get(Calendar, event.calendar_id)
    if calendar is not None and calendar.kind == "group" and calendar.name:
        parts.append(calendar.name)
    if "time_changed" in kinds:
        # Each endpoint formats with its own all-day shape (the current shape
        # is only the fallback): an old local midnight is a date, a new
        # all-day endpoint keeps its date, a new timed endpoint keeps its time.
        all_day = bool(occ is not None and occ.is_all_day)
        old_shape, new_shape = (own or {}).get("old_all_day"), (own or {}).get("new_all_day")
        old = _push_iso((own or {}).get("old_start"), event, all_day if old_shape is None else old_shape)
        new = _push_iso((own or {}).get("new_start"), event, all_day if new_shape is None else new_shape)
        if old and new:
            parts.append(f"Moved from {old} to {new}")
    when = _push_when(occ, event)
    if when:
        parts.append(when)
    # Partial change over several sessions: say how many are affected. Only an
    # event-wide cancellation says everything a count would — one cancelled
    # occurrence inside a multi-session alert still counts the others. A
    # non-exact total (a legacy side hides its unlisted sessions) is a lower
    # bound: say "more sessions" instead of a fake-precise number.
    total = details.get("total") or len(items)
    if not details.get("event_cancelled") and total > 1:
        parts.append(f"+{total - 1} more" if details.get("total_exact", True) else PUSH_MORE_UNCOUNTED)
    return " · ".join(part for part in parts if part)


def _push(db: Session, delivery_id: int, owner: str, sender, now: datetime, budget=None) -> str:
    d = db.get(CalendarAlertDelivery, delivery_id, populate_existing=True)
    if d is None or d.lease_owner != owner or d.push_state != "pending":
        db.rollback()
        return "lost"
    # Recheck immediately before every send, including crash-window retries.
    # The inbox commit may predate revoked access, an edited session or a
    # preference change. Keep the durable inbox row, but suppress its push.
    reason = "feature_disabled" if not calendar_enabled(db) else suppression_reason(db, d, now)
    if reason is not None:
        db.query(CalendarAlertDelivery).filter(
            CalendarAlertDelivery.id == delivery_id, CalendarAlertDelivery.lease_owner == owner,
            CalendarAlertDelivery.push_state == "pending").update(
                {"push_state": "skipped", "suppressed_reason": reason,
                 "lease_owner": None, "lease_until": None}, synchronize_session=False)
        db.commit()
        return "skipped"
    if budget is not None:
        if budget[0] <= 0:
            d.lease_owner = d.lease_until = None
            db.commit()
            return "deferred"
        budget[0] -= 1
    payload = push_payload(db, d)
    notification = db.get(Notification, d.notification_id) if d.notification_id else None
    db.rollback()  # never hold the row lock while talking to push services
    state = "skipped"
    try:
        if notification is not None and sender(db, notification, payload):
            state = "sent"
    except Exception as exc:  # noqa: BLE001 - push is best-effort
        logger.error("calendar push failed for user %s (%s)", d.user_id, type(exc).__name__)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
    db.query(CalendarAlertDelivery).filter(CalendarAlertDelivery.id == delivery_id,
                                           CalendarAlertDelivery.lease_owner == owner).update(
        {"push_state": state, "lease_owner": None, "lease_until": None}, synchronize_session=False)
    db.commit()
    return state


def web_push_sender(db: Session, notification: Notification, payload: dict) -> bool:
    """Default sender: existing Web Push fan-out with a calendar payload."""
    from app.services import push_service

    if not push_service.is_push_configured():
        return False
    notification._push_payload = payload
    push_service.fanout_for_rows(db, [notification])
    return True


def dispatch(factory: Callable[[], Session], owner: str, now: datetime, batch: int, sender=None, push_budget=None) -> dict:
    sender = web_push_sender if sender is None else sender
    stats = {"delivered": 0, "suppressed": 0, "delivery_failed": 0, "pushed": 0}
    with factory() as db:
        claimed = _claim(db, CalendarAlertDelivery, owner, now, batch)
        for row_id in claimed:
            try:
                d = db.get(CalendarAlertDelivery, row_id, populate_existing=True)
                if d is None or d.lease_owner != owner or d.status != "pending":
                    db.rollback()
                    continue
                reason = suppression_reason(db, d, now)
                if reason is not None:
                    d.status, d.suppressed_reason = "suppressed", reason
                    d.lease_owner = d.lease_until = None
                    db.commit()
                    stats["suppressed"] += 1
                    continue
                row = notification_service.stage(db, user_id=d.user_id, type=d.notif_type,
                                                 title=GENERIC_TITLES[d.kind])
                # Conditional transition: only the lease holder of a still
                # pending delivery may attach an inbox row. Anything else
                # rolls back the staged inbox row too.
                won = db.query(CalendarAlertDelivery).filter(
                    CalendarAlertDelivery.id == row_id, CalendarAlertDelivery.status == "pending",
                    CalendarAlertDelivery.lease_owner == owner).update(
                    {"status": "delivered", "notification_id": row.id, "delivered_at": now,
                     "push_state": "pending", "lease_until": now + ROW_LEASE}, synchronize_session=False)
                if won != 1:
                    db.rollback()
                    continue
                db.commit()
                stats["delivered"] += 1
            except Exception as exc:  # noqa: BLE001 - recorded with type only, retried with backoff
                _record_failure(db, CalendarAlertDelivery, row_id, owner, now, exc)
                stats["delivery_failed"] += 1
                continue
            if _push(db, row_id, owner, sender, now, push_budget) == "sent":
                stats["pushed"] += 1
    return stats


def retry_push(factory: Callable[[], Session], owner: str, now: datetime, batch: int, sender=None, push_budget=None) -> dict:
    """Pushes interrupted between the inbox commit and the send: retried
    within PUSH_RETRY_WINDOW, otherwise expired (inbox stays the reference)."""
    sender = web_push_sender if sender is None else sender
    stats = {"push_retried": 0, "push_expired": 0}
    with factory() as db:
        free = or_(CalendarAlertDelivery.lease_until.is_(None), CalendarAlertDelivery.lease_until < now)
        stats["push_expired"] = db.query(CalendarAlertDelivery).filter(
            CalendarAlertDelivery.status == "delivered", CalendarAlertDelivery.push_state == "pending",
            CalendarAlertDelivery.delivered_at < now - PUSH_RETRY_WINDOW, free).update(
            {"push_state": "expired", "lease_owner": None, "lease_until": None}, synchronize_session=False)
        db.commit()
        ids = sorted(r[0] for r in db.query(CalendarAlertDelivery.id).filter(
            CalendarAlertDelivery.status == "delivered", CalendarAlertDelivery.push_state == "pending",
            free).order_by(CalendarAlertDelivery.id).limit(batch))
        for row_id in ids:
            claimed = db.query(CalendarAlertDelivery).filter(
                CalendarAlertDelivery.id == row_id, CalendarAlertDelivery.push_state == "pending", free).update(
                {"lease_owner": owner, "lease_until": now + ROW_LEASE}, synchronize_session=False)
            db.commit()
            if claimed and _push(db, row_id, owner, sender, now, push_budget) in ("sent", "skipped"):
                stats["push_retried"] += 1
    return stats


# --- One bounded run ------------------------------------------------------------------------------------------------

def new_owner() -> str:
    return f"{socket.gethostname()[:30]}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def run_once(factory: Callable[[], Session], *, now: Optional[datetime] = None, owner: Optional[str] = None,
             batch: int = DEFAULT_BATCH, sender=None, push_limit=None) -> dict:
    """One bounded run; disabled mode only records a readiness observation."""
    now = now or utcnow()
    with factory() as db:
        if schema_ready(db):
            from app.services.calendar_launch import record_probe
            record_probe(db, now)
        if not calendar_enabled(db):
            return {"status": "disabled"}
    owner = owner or new_owner()
    batch = max(1, min(int(batch), MAX_BATCH))
    with factory() as db:
        if not schema_ready(db):
            return {"status": "schema_missing"}
        if not acquire_run(db, owner, now):
            return {"status": "busy"}
    stats: dict = {}
    try:
        stats.update(expand_outbox(factory, owner, now, batch))
        stats.update(plan_reminders(factory, now, batch))
        # Scheduled CLI defers all network work to the oldest-first push phase.
        # Inbox batches remain independent of the bounded network allowance.
        stats.update(dispatch(factory, owner, now, batch, sender, [0] if push_limit is not None else None))
        stats.update(retry_push(factory, owner, now, batch, sender,
                                [max(0, push_limit)] if push_limit is not None else None))
    except Exception as exc:
        with factory() as db:
            finish_run(db, owner, now, stats, error=type(exc).__name__)
        raise
    with factory() as db:
        finish_run(db, owner, now, stats)
    return {"status": "ok", **stats}


# --- Monitoring ---------------------------------------------------------------------------------------------------------

def health(db: Session, now: Optional[datetime] = None) -> dict:
    """Readiness of the alert pipeline (CLI status + admin endpoint)."""
    now = now or utcnow()
    out = {"enabled": bool(calendar_enabled(db)), "schema": False, "worker": "missing",
           "ready": False, "problems": []}
    if not schema_ready(db):
        out["problems"].append("schema_missing")
        return out
    out["schema"] = True
    from app.models.calendar import CalendarLaunchControl
    from app.services.calendar_launch import installed, probe_ready
    launch_state = db.get(CalendarLaunchControl, 1) if installed(db) else None
    out["scheduled_checks_ready"] = probe_ready(launch_state, now)
    out["standby"] = bool(not out["enabled"] and launch_state and launch_state.last_probe_at
                          and now - launch_state.last_probe_at < STALE_WORKER)
    state = db.get(CalendarWorkerState, WORKER_NAME)
    last = state.last_success_at if state else None
    out["last_success_at"] = _iso(last)
    out["last_error"] = state.last_error if state else None
    out["last_error_at"] = _iso(state.last_error_at) if state else None
    out["runs"], out["failures"] = (state.runs, state.failures) if state else (0, 0)
    out["last_stats"] = state.last_stats if state else {}
    if last is None:
        out["problems"].append("worker_never_succeeded")
    elif now - last > STALE_WORKER:
        out["worker"] = "stale"
        out["problems"].append("worker_stale")
    else:
        out["worker"] = "ok"
    counts = {}
    for model, name in ((CalendarAlertOutbox, "outbox"), (CalendarAlertDelivery, "deliveries")):
        counts[name] = {status: n for status, n in db.query(model.status, func.count(model.id)).group_by(model.status)}
        oldest = db.query(func.min(model.next_attempt_at)).filter(model.status == "pending",
                                                                  model.next_attempt_at <= now).scalar()
        counts[name]["oldest_due_age_seconds"] = int((now - oldest).total_seconds()) if oldest else 0
        counts[name]["retrying"] = db.query(func.count(model.id)).filter(model.status == "pending",
                                                                          model.attempts > 0).scalar()
        counts[name]["retry_attempts"] = int(db.query(func.coalesce(func.sum(model.attempts), 0)).filter(
            model.status.in_(("pending", "dead"))).scalar() or 0)
        if counts[name].get("dead"):
            out["problems"].append(f"{name}_dead_letters")
    out["queues"] = counts
    if any(p.endswith("dead_letters") for p in out["problems"]):
        out["standby"] = False
    out["suppressed_by_reason"] = {reason: n for reason, n in db.query(
        CalendarAlertDelivery.suppressed_reason, func.count(CalendarAlertDelivery.id)).filter(
        CalendarAlertDelivery.status == "suppressed").group_by(CalendarAlertDelivery.suppressed_reason)}
    out["ready"] = out["enabled"] and out["worker"] == "ok" and not out["problems"]
    if not out["enabled"]:
        out["problems"].append("feature_disabled")
    return out


def dead_letters(db: Session, limit: int = 50) -> list:
    rows = []
    for model, name in ((CalendarAlertOutbox, "outbox"), (CalendarAlertDelivery, "delivery")):
        for r in db.query(model).filter(model.status == "dead").order_by(model.id).limit(limit):
            rows.append({"table": name, "id": r.id, "event_id": r.event_id, "attempts": r.attempts,
                         "last_error": r.last_error, "kind": getattr(r, "kind", None)})
    return rows


def requeue_dead(db: Session, table: str, row_id: Optional[int] = None, now: Optional[datetime] = None) -> int:
    """Explicit operator action: dead rows back to pending (attempts reset).
    Stale deliveries are still suppressed at dispatch, never replayed late."""
    model = CalendarAlertOutbox if table == "outbox" else CalendarAlertDelivery
    query = db.query(model).filter(model.status == "dead")
    if row_id is not None:
        query = query.filter(model.id == row_id)
    count = query.update({"status": "pending", "attempts": 0, "next_attempt_at": now or utcnow(),
                          "lease_owner": None, "lease_until": None}, synchronize_session=False)
    db.commit()
    return count


# --- Read side --------------------------------------------------------------------------------------------------------------

def _read_changes(details: dict, occ: EventOccurrence) -> list:
    """Per-item change view for the reader; a venue_changed kind that did not
    change this session's effective venue is dropped from the item."""
    out = []
    for item in details.get("occurrences", []):
        kinds = list(item.get("kinds", []))
        if ("venue_changed" in kinds and item.get("venue") is None
                and not _event_venue_reaches(details, occ)):
            kinds.remove("venue_changed")
        out.append({"kinds": kinds, "old_start": item.get("old_start"),
                    "new_start": item.get("new_start"),
                    "old_all_day": bool(item.get("old_all_day", occ.is_all_day)),
                    "new_all_day": bool(item.get("new_all_day", occ.is_all_day)),
                    "venue": item.get("venue")})
    return out


def render_for_reader(db: Session, user: AppUser, rows: List[Notification]) -> Dict[int, dict]:
    """Per-reader view of calendar inbox rows: {notification_id: overrides}.

    Visible -> current event title + structured details + authorized deep
    link. No longer visible (or feature/schema off) -> redacted."""
    cal_rows = [r for r in rows if r.type in notification_service.CALENDAR_TYPES]
    if not cal_rows:
        return {}
    redacted = {r.id: {"title": REDACTED_TITLE, "body": None, "calendar": {"redacted": True}} for r in cal_rows}
    if not calendar_enabled(db) or not schema_ready(db):
        return redacted
    deliveries = {d.notification_id: d for d in db.query(CalendarAlertDelivery).filter(
        CalendarAlertDelivery.notification_id.in_([r.id for r in cal_rows]))}
    occ_ids = {d.occurrence_id for d in deliveries.values() if d.occurrence_id}
    visible = {o.id: (o, e, c) for o, e, c in access.visible_occurrences(db, user).filter(
        EventOccurrence.id.in_(occ_ids))} if occ_ids else {}
    out = dict(redacted)
    for r in cal_rows:
        d = deliveries.get(r.id)
        if d is None or d.occurrence_id not in visible:
            continue
        occ, event, calendar = visible[d.occurrence_id]
        details = d.details or {}
        out[r.id] = {"title": event.title, "body": None, "calendar": {
            "redacted": False, "kind": d.kind, "event_id": event.id, "occurrence_id": occ.id,
            "url": _occurrence_url(occ.id), "event_title": event.title, "timezone": event.timezone,
            "calendar_name": calendar.name, "calendar_kind": calendar.kind,
            "starts_at": _iso(occ.starts_at), "start_date": occ.start_date.isoformat() if occ.start_date else None,
            "all_day": bool(occ.is_all_day), "venue_name": occ.venue_name or event.venue_name,
            "status": "cancelled" if occ.status == "cancelled" else "scheduled",
            "event_cancelled": bool(details.get("event_cancelled")),
            "changes": _read_changes(details, occ),
            "total": details.get("total", 0),
            "total_exact": bool(details.get("total_exact", True))}}
    return out
