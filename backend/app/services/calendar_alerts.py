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
the row is redacted (no title, details or link). Push previews of
non-community events are generic.
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
STALE_WORKER = timedelta(minutes=int(os.getenv("CALENDAR_ALERTS_STALE_MINUTES", "15")))
SCHEMA_TABLES = ("calendar_alert_outbox", "calendar_alert_deliveries", "calendar_worker_state")

PARTICIPANT_INTEREST = ("interested", "maybe")
CHANGE_INVITATION = ("pending", "accepted")

# Inbox titles are generic on purpose: event details are resolved per reader
# at read time (redacted once access is lost). English like other inbox rows;
# the web UI renders localized FR/EN text from the structured payload.
GENERIC_TITLES = {
    "invitation": "Calendar invitation",
    "change": "Calendar event changed",
    "cancellation": "Calendar event cancelled",
    "reminder": "Calendar reminder: tomorrow",
    "new_event": "New event in a calendar you follow",
}
PUSH_BODY_PRIVATE = "Open the app to see the details."
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


def _local_day(occurrence: EventOccurrence, event: CalendarEvent) -> date:
    if occurrence.is_all_day:
        return occurrence.start_date
    return occurrence.window_start.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(event.timezone)).date()


def reminder_due(occurrence: EventOccurrence, event: CalendarEvent) -> datetime:
    """Previous local day at CALENDAR_REMINDER_HOUR (event timezone), as UTC."""
    hour = get_settings().calendar_reminder_hour
    return _local_to_utc(datetime.combine(_local_day(occurrence, event) - timedelta(days=1), time(hour)),
                         event.timezone)


def _is_private(event: CalendarEvent, calendar: Optional[Calendar]) -> bool:
    return event.audience != "community" or (calendar is not None and calendar.kind == "personal")


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
    """(per-occurrence changes, event_cancelled, event_venue_changed)."""
    per: Dict[int, dict] = {}
    event_cancelled = event_venue = False
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
        elif kind == "venue_changed":
            if log.occurrence_id:
                per.setdefault(log.occurrence_id, {"kinds": set()})["kinds"].add("venue_changed")
            else:
                event_venue = True
    return per, event_cancelled, event_venue


def _merge_details(old: dict, new: dict) -> dict:
    """Combine a superseded pending alert with the newer one: kinds union,
    the oldest 'old_start' and the newest 'new_start' per occurrence."""
    merged = {o["id"]: dict(o) for o in (old.get("occurrences") or [])}
    for item in new.get("occurrences") or []:
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
    out = dict(new)
    out["occurrences"] = sorted(merged.values(), key=lambda o: o["id"])[:MAX_DETAIL_OCCURRENCES]
    out["event_cancelled"] = bool(old.get("event_cancelled") or new.get("event_cancelled"))
    out["event_venue"] = bool(old.get("event_venue") or new.get("event_venue"))
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
    per, event_cancelled, event_venue = _details_from_logs(logs)
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
                items.append({"id": oid, "kinds": sorted(info["kinds"]), "old_start": info.get("old_start"),
                              "new_start": info.get("new_start")})
            cancelled = event_cancelled or any("cancelled" in i["kinds"] for i in items)
            kind = "cancellation" if cancelled else "change"
            details = {"occurrences": items[:MAX_DETAIL_OCCURRENCES], "total": len(items),
                       "event_cancelled": event_cancelled, "event_venue": event_venue}
            # Supersede pending, undelivered change alerts of the same event:
            # one up-to-date alert instead of a stale sequence.
            for old in db.query(CalendarAlertDelivery).filter(
                    CalendarAlertDelivery.user_id == uid, CalendarAlertDelivery.event_id == event.id,
                    CalendarAlertDelivery.kind.in_(("change", "cancellation")),
                    CalendarAlertDelivery.status == "pending",
                    or_(CalendarAlertDelivery.lease_until.is_(None), CalendarAlertDelivery.lease_until < now)):
                details = _merge_details(old.details or {}, details)
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
    event = db.get(CalendarEvent, d.event_id)
    calendar = db.get(Calendar, event.calendar_id) if event else None
    title = GENERIC_TITLES[d.kind]
    if event is None or _is_private(event, calendar):
        body = PUSH_BODY_PRIVATE
    else:
        body = event.title
    return {"title": title, "body": body, "url": _occurrence_url(d.occurrence_id)}


def _push(db: Session, delivery_id: int, owner: str, sender, now: datetime, budget=None) -> str:
    d = db.get(CalendarAlertDelivery, delivery_id, populate_existing=True)
    if d is None or d.lease_owner != owner or d.push_state != "pending":
        db.rollback()
        return "lost"
    # Recheck immediately before every send, including crash-window retries.
    # The inbox commit may predate revoked access, an edited session or a
    # preference change. Keep the durable inbox row, but suppress its push.
    reason = "feature_disabled" if not get_settings().calendar_enabled else suppression_reason(db, d, now)
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
    """One bounded worker run. Never runs when the feature is off."""
    if not get_settings().calendar_enabled:
        return {"status": "disabled"}
    now = now or utcnow()
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
    out = {"enabled": bool(get_settings().calendar_enabled), "schema": False, "worker": "missing",
           "ready": False, "problems": []}
    if not schema_ready(db):
        out["problems"].append("schema_missing")
        return out
    out["schema"] = True
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

def render_for_reader(db: Session, user: AppUser, rows: List[Notification]) -> Dict[int, dict]:
    """Per-reader view of calendar inbox rows: {notification_id: overrides}.

    Visible -> current event title + structured details + authorized deep
    link. No longer visible (or feature/schema off) -> redacted."""
    cal_rows = [r for r in rows if r.type in notification_service.CALENDAR_TYPES]
    if not cal_rows:
        return {}
    redacted = {r.id: {"title": REDACTED_TITLE, "body": None, "calendar": {"redacted": True}} for r in cal_rows}
    if not get_settings().calendar_enabled or not schema_ready(db):
        return redacted
    deliveries = {d.notification_id: d for d in db.query(CalendarAlertDelivery).filter(
        CalendarAlertDelivery.notification_id.in_([r.id for r in cal_rows]))}
    occ_ids = {d.occurrence_id for d in deliveries.values() if d.occurrence_id}
    visible = {o.id: (o, e) for o, e, _c in access.visible_occurrences(db, user).filter(
        EventOccurrence.id.in_(occ_ids))} if occ_ids else {}
    out = dict(redacted)
    for r in cal_rows:
        d = deliveries.get(r.id)
        if d is None or d.occurrence_id not in visible:
            continue
        occ, event = visible[d.occurrence_id]
        details = d.details or {}
        out[r.id] = {"title": event.title, "body": None, "calendar": {
            "redacted": False, "kind": d.kind, "event_id": event.id, "occurrence_id": occ.id,
            "url": _occurrence_url(occ.id), "event_title": event.title, "timezone": event.timezone,
            "starts_at": _iso(occ.starts_at), "start_date": occ.start_date.isoformat() if occ.start_date else None,
            "all_day": bool(occ.is_all_day), "venue_name": occ.venue_name or event.venue_name,
            "status": "cancelled" if "cancelled" in (event.status, occ.status) else "scheduled",
            "changes": [{"kinds": i.get("kinds", []), "old_start": i.get("old_start"),
                         "new_start": i.get("new_start")} for i in details.get("occurrences", [])],
            "total": details.get("total", 0)}}
    return out
