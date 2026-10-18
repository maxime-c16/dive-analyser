"""Calendar event, response and follow writes (Task03).

Every write first resolves the target through the Task02 read policy
(calendar_access): a record the actor cannot see answers 404, exactly like a
missing one. Editing then requires calendar_access.can_publish_to_calendar.
Functions flush only; the API commits, so each event write and its
calendar_change_log row land in one transaction.

- Optimistic concurrency: edits/cancels carry expected_version (409
  stale_version); rows are locked FOR UPDATE before the comparison.
- Idempotent create: an actor-scoped Idempotency-Key replays the original
  event; the same key with another payload is refused.
- Time and venue edits update occurrences in place, so interest rows (keyed
  by occurrence) are retained. Cancellation keeps the event and responses.
- Editing an imported record marks its source mapping locally_overridden,
  so a later import proposes a conflict instead of overwriting it.
- No notification is sent inline: log_change/invite write the Task05 alert
  outbox in the same transaction; the alerts worker delivers later.
"""
import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.calendar import (
    Calendar, CalendarChangeLog, CalendarEvent, CalendarEventFollow, CalendarIdempotencyKey,
    CalendarSourceMapping, CalendarSubscription, EventInvitation, EventOccurrence, EventResource,
    OccurrenceAbsenceReport,
    OccurrenceDiveLink, OccurrenceInterest,
)
from app.models.dive import Dive
from app.models.user_auth import AppUser
from app.services import calendar_access as access
from app.services.calendar_membership import fail, valid_timezone

MAX_TIMED_HOURS = 7 * 24
MAX_ALL_DAY_DAYS = 31
MAX_CREATES_PER_HOUR = 30
MAX_INVITES_PER_EVENT = 200


# --- Time handling ---------------------------------------------------------------

def local_to_utc(local: datetime, tz_name: str) -> datetime:
    """Naive local wall time -> naive UTC. Nonexistent (DST gap) and
    ambiguous (DST overlap) times are refused, never silently shifted."""
    tz = ZoneInfo(tz_name)
    early, late = local.replace(tzinfo=tz, fold=0), local.replace(tzinfo=tz, fold=1)
    utc = early.astimezone(timezone.utc)
    if utc.astimezone(tz).replace(tzinfo=None) != local:
        fail(422, "nonexistent_local_time", "This local time does not exist (clock change); choose another time")
    if early.utcoffset() != late.utcoffset():
        fail(422, "ambiguous_local_time", "This local time occurs twice (clock change); choose another time")
    return utc.replace(tzinfo=None)


def utc_to_local(value: datetime, tz_name: str) -> datetime:
    return value.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz_name)).replace(tzinfo=None)


def occurrence_fields(when, tz_name: str) -> dict:
    """Validated occurrence columns from an OccurrenceTimes payload."""
    if when.all_day:
        if when.start_date is None:
            fail(422, "invalid_time", "A start date is required")
        end = when.end_date or when.start_date + timedelta(days=1)
        if end <= when.start_date or (end - when.start_date).days > MAX_ALL_DAY_DAYS:
            fail(422, "invalid_time", f"End date must be after the start and within {MAX_ALL_DAY_DAYS} days")
        start_utc = local_to_utc(datetime.combine(when.start_date, time()), tz_name)
        end_utc = local_to_utc(datetime.combine(end, time()), tz_name)
        return dict(is_all_day=True, start_date=when.start_date, end_date=end, starts_at=None, ends_at=None,
                    window_start=start_utc, window_end=end_utc)
    if when.start_local is None or when.end_local is None:
        fail(422, "invalid_time", "Start and end times are required")
    start, end = local_to_utc(when.start_local, tz_name), local_to_utc(when.end_local, tz_name)
    if end <= start or end - start > timedelta(hours=MAX_TIMED_HOURS):
        fail(422, "invalid_time", "End must be after the start and within 7 days")
    return dict(is_all_day=False, start_date=None, end_date=None, starts_at=start, ends_at=end,
                window_start=start, window_end=end)


TIME_COLUMNS = ("is_all_day", "starts_at", "ends_at", "start_date", "end_date", "window_start", "window_end")


def _jsonable(value):
    if isinstance(value, datetime):
        return value.isoformat() + "Z"
    if isinstance(value, date):
        return value.isoformat()
    return value


# --- Lookups ------------------------------------------------------------------------

def visible_event(db: Session, user: AppUser, event_id: int, lock: bool = False):
    row = access.visible_events(db, user).add_entity(Calendar).filter(CalendarEvent.id == event_id).one_or_none()
    if row is None:
        fail(404, "event_not_found", "Event not found")
    if lock:
        db.query(CalendarEvent).filter(CalendarEvent.id == event_id).with_for_update().one()
        db.refresh(row[0])
    return row


def visible_occurrence(db: Session, user: AppUser, occurrence_id: int, lock: bool = False):
    row = access.visible_occurrences(db, user).filter(EventOccurrence.id == occurrence_id).one_or_none()
    if row is None:
        fail(404, "occurrence_not_found", "Occurrence not found")
    if lock:
        db.query(EventOccurrence).filter(EventOccurrence.id == occurrence_id).with_for_update().one()
        db.refresh(row[0])
    return row


def can_edit(db: Session, user: AppUser, calendar: Calendar) -> bool:
    return access.can_publish_to_calendar(db, user, calendar)


def editable_event(db: Session, user: AppUser, event_id: int):
    event, calendar = visible_event(db, user, event_id, lock=True)
    if not can_edit(db, user, calendar):
        fail(403, "forbidden", "Only the organizer or an authorized club publisher can change this event")
    return event, calendar


def _check_version(row, expected: int, what: str) -> None:
    if row.version != expected:
        fail(409, "stale_version",
             f"This {what} changed since you opened it (now version {row.version}); reload and try again")


def _mark_overridden(db: Session, event_id: int, occurrence_id: Optional[int] = None) -> None:
    query = db.query(CalendarSourceMapping)
    query = query.filter(CalendarSourceMapping.occurrence_id == occurrence_id) if occurrence_id else \
        query.filter(CalendarSourceMapping.event_id == event_id)
    query.update({"locally_overridden": True}, synchronize_session=False)


def log_change(db: Session, event: CalendarEvent, kind: str, actor: Optional[AppUser], changes: dict,
               occurrence: Optional[EventOccurrence] = None, import_run_id: Optional[int] = None) -> None:
    """Audit row + (Task05) its alert outbox row, in the caller's transaction."""
    from app.services import calendar_alerts

    outbox = calendar_alerts.outbox_for(db, event, actor, from_import=import_run_id is not None)
    db.add(CalendarChangeLog(event_id=event.id, occurrence_id=occurrence.id if occurrence else None,
                             event_version=event.version, change_kind=kind,
                             actor_user_id=actor.id if actor else None, import_run_id=import_run_id,
                             changes={k: [_jsonable(a), _jsonable(b)] for k, (a, b) in changes.items()},
                             outbox=outbox))


def personal_calendar(db: Session, user: AppUser) -> Calendar:
    cal = db.query(Calendar).filter(Calendar.kind == "personal", Calendar.owner_user_id == user.id,
                                    Calendar.archived_at.is_(None)).order_by(Calendar.id).first()
    if cal is None:
        cal = Calendar(kind="personal", owner_user_id=user.id, name=user.display_name or "Personal")
        db.add(cal)
        db.flush()
    return cal


# --- Events ------------------------------------------------------------------------

def request_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def replay(db: Session, user: AppUser, key: Optional[str], digest: str) -> Optional[CalendarEvent]:
    if not key:
        return None
    row = db.get(CalendarIdempotencyKey, (user.id, key))
    if row is None:
        return None
    if row.request_hash != digest or row.event_id is None:
        fail(422, "idempotency_key_reused", "This request key was already used for a different event")
    return db.get(CalendarEvent, row.event_id)


def create_event(db: Session, user: AppUser, payload, key: Optional[str]) -> tuple[CalendarEvent, bool]:
    """Returns (event, replayed)."""
    digest = request_hash(payload.model_dump(mode="json"))
    existing = replay(db, user, key, digest)
    if existing is not None:
        return existing, True
    if payload.calendar_id is None:
        calendar = personal_calendar(db, user)
    else:
        calendar = access.visible_calendars(db, user).filter(Calendar.id == payload.calendar_id).one_or_none()
        if calendar is None:
            fail(404, "calendar_not_found", "Calendar not found")
    if not can_edit(db, user, calendar):
        fail(403, "forbidden", "You cannot publish to this calendar")
    if payload.audience not in access.ALLOWED_AUDIENCES[calendar.kind]:
        fail(422, "invalid_audience", "This audience is not available for this calendar")
    recent = db.query(func.count(CalendarEvent.id)).filter(
        CalendarEvent.created_by_user_id == user.id,
        CalendarEvent.created_at > datetime.utcnow() - timedelta(hours=1)).scalar()
    if recent >= MAX_CREATES_PER_HOUR:
        fail(429, "rate_limited", "Too many events created recently; try again later")
    tz = valid_timezone(payload.timezone)
    times = occurrence_fields(payload.when, tz)
    now = datetime.utcnow()
    event = CalendarEvent(
        calendar_id=calendar.id, organizer_user_id=user.id, created_by_user_id=user.id,
        event_type=payload.event_type, audience=payload.audience, status=payload.status, title=payload.title.strip(),
        description=payload.description or "", venue_name=payload.venue_name, venue_address=payload.venue_address,
        map_url=payload.map_url, timezone=tz, published_at=now if payload.status == "published" else None)
    db.add(event)
    db.flush()
    occurrence = EventOccurrence(event_id=event.id, occurrence_key="single", venue_name=None, **times)
    db.add(occurrence)
    db.flush()
    log_change(db, event, "created", user, {"title": (None, event.title)}, occurrence)
    from app.services import calendar_recurrence as recurrence  # Task04 (imports this module)
    if payload.recurrence is not None:
        recurrence.create_series(db, user, event, occurrence, payload.recurrence)
    recurrence.set_itinerary(db, event, occurrence, payload.itinerary)
    set_registration(db, event, payload.registration_url)
    if payload.status == "published":
        log_change(db, event, "published", user, {"status": ("draft", "published")})
    if key:
        db.add(CalendarIdempotencyKey(user_id=user.id, idempotency_key=key, request_hash=digest, event_id=event.id))
    db.flush()
    return event, False


EVENT_FIELDS = ("title", "description", "venue_name", "venue_address", "map_url", "audience", "event_type")


def update_event(db: Session, user: AppUser, event_id: int, payload) -> CalendarEvent:
    event, calendar = editable_event(db, user, event_id)
    _check_version(event, payload.expected_version, "event")
    if event.status == "cancelled":
        fail(409, "event_cancelled", "A cancelled event cannot be edited")
    sent = payload.model_fields_set
    changes = {}
    for field in EVENT_FIELDS:
        if field in sent:
            value = getattr(payload, field)
            if field in ("title", "audience", "event_type") and value is None:
                fail(422, "invalid_field", f"{field} cannot be empty")
            if field == "description":
                value = value or ""
            if value != getattr(event, field):
                changes[field] = (getattr(event, field), value)
    if "audience" in changes and payload.audience not in access.ALLOWED_AUDIENCES[calendar.kind]:
        fail(422, "invalid_audience", "This audience is not available for this calendar")
    if changes.get("event_type", (None, None))[1] == "camp" and event.recurrence_rule:
        fail(422, "recurrence_not_supported", "A weekly series cannot become a camp")
    occurrence, time_changes = None, {}
    if payload.when is not None:
        occurrences = db.query(EventOccurrence).filter(EventOccurrence.event_id == event.id).with_for_update().all()
        if len(occurrences) != 1 or event.recurrence_rule:
            fail(422, "edit_occurrence", "This event has several dates; edit one occurrence at a time")
        occurrence = occurrences[0]
        new = occurrence_fields(payload.when, event.timezone)
        time_changes = {k: (getattr(occurrence, k), v) for k, v in new.items() if getattr(occurrence, k) != v}
        for field, (_old, value) in time_changes.items():
            setattr(occurrence, field, value)
    publish = payload.status == "published" and event.status == "draft"
    from app.services import calendar_recurrence as recurrence
    extra = {}
    if "itinerary" in sent:
        rows = db.query(EventOccurrence).filter(EventOccurrence.event_id == event.id).all()
        if occurrence is None and len(rows) == 1:
            occurrence = rows[0]
        if recurrence.set_itinerary(db, event, occurrence if len(rows) == 1 else None, payload.itinerary or []):
            extra["itinerary"] = (None, len(payload.itinerary or []))
    elif time_changes:
        recurrence.check_itinerary_range(db, event, occurrence)
    if "registration_url" in sent and set_registration(db, event, payload.registration_url):
        extra["registration_url"] = (None, payload.registration_url)
    if not changes and not time_changes and not publish and not extra:
        return event
    event.version += 1
    for field, (_old, value) in changes.items():
        setattr(event, field, value)
    if time_changes:
        occurrence.version += 1
        log_change(db, event, "time_changed", user, time_changes, occurrence)
    venue = {k: v for k, v in changes.items() if k in ("venue_name", "venue_address", "map_url")}
    if venue:
        log_change(db, event, "venue_changed", user, venue)
    other = {k: v for k, v in changes.items() if k not in venue}
    other.update(extra)
    if other:
        log_change(db, event, "updated", user, other)
    if publish:
        event.status, event.published_at = "published", datetime.utcnow()
        log_change(db, event, "published", user, {"status": ("draft", "published")})
    _mark_overridden(db, event.id)
    db.flush()
    return event


def set_registration(db: Session, event: CalendarEvent, url: Optional[str]) -> bool:
    """External registration link (e.g. the organizer's booking page), kept
    as an event resource. It is separate from in-app interest."""
    row = db.query(EventResource).filter_by(event_id=event.id, kind="registration").order_by(EventResource.id).first()
    if not url:
        if row is None:
            return False
        db.delete(row)
        return True
    if row is None:
        db.add(EventResource(event_id=event.id, kind="registration", label="Registration (external site)", url=url))
        return True
    if row.url == url:
        return False
    row.url = url
    return True


def cancel_event(db: Session, user: AppUser, event_id: int, expected_version: int) -> CalendarEvent:
    event, _calendar = editable_event(db, user, event_id)
    if event.status == "cancelled":
        return event  # retry of a completed cancel
    _check_version(event, expected_version, "event")
    old = event.status
    event.version += 1
    event.status, event.cancelled_at = "cancelled", datetime.utcnow()
    log_change(db, event, "cancelled", user, {"status": (old, "cancelled")})
    _mark_overridden(db, event.id)
    db.flush()
    return event


def update_occurrence(db: Session, user: AppUser, occurrence_id: int, payload) -> EventOccurrence:
    occurrence, event, calendar = visible_occurrence(db, user, occurrence_id, lock=True)
    if not can_edit(db, user, calendar):
        fail(403, "forbidden", "Only an authorized publisher can change this session")
    _check_version(occurrence, payload.expected_version, "session")
    if event.status == "cancelled" or occurrence.status == "cancelled":
        fail(409, "event_cancelled", "A cancelled session cannot be edited")
    changes = {}
    if payload.when is not None:
        new = occurrence_fields(payload.when, event.timezone)
        from app.services import calendar_recurrence as recurrence
        recurrence.check_itinerary_range(db, event, EventOccurrence(**new))
        changes = {k: (getattr(occurrence, k), v) for k, v in new.items() if getattr(occurrence, k) != v}
    venue = None
    if "venue_name" in payload.model_fields_set and payload.venue_name != occurrence.venue_name:
        venue = (occurrence.venue_name, payload.venue_name)
    if not changes and venue is None:
        return occurrence
    occurrence.version += 1
    for field, (_old, value) in changes.items():
        setattr(occurrence, field, value)
    if changes:
        log_change(db, event, "time_changed", user, changes, occurrence)
    if venue is not None:
        occurrence.venue_name = venue[1]
        log_change(db, event, "venue_changed", user, {"venue_name": venue}, occurrence)
    # A weekly-series session edited on its own is kept by later pattern edits.
    occurrence.detached = occurrence.series_date is not None
    _mark_overridden(db, event.id, occurrence.id)
    db.flush()
    return occurrence


def cancel_occurrence(db: Session, user: AppUser, occurrence_id: int, expected_version: int) -> EventOccurrence:
    occurrence, event, calendar = visible_occurrence(db, user, occurrence_id, lock=True)
    if not can_edit(db, user, calendar):
        fail(403, "forbidden", "Only an authorized publisher can cancel this session")
    if occurrence.status == "cancelled":
        return occurrence
    _check_version(occurrence, expected_version, "session")
    occurrence.version += 1
    occurrence.status, occurrence.cancelled_at = "cancelled", datetime.utcnow()
    log_change(db, event, "cancelled", user, {"status": ("scheduled", "cancelled")}, occurrence)
    _mark_overridden(db, event.id, occurrence.id)
    db.flush()
    return occurrence


# --- Invitations ----------------------------------------------------------------------

def invite(db: Session, user: AppUser, event_id: int, user_ids: list[int]) -> list[EventInvitation]:
    event, calendar = editable_event(db, user, event_id)
    if event.audience != "invited":
        fail(422, "not_invited_audience", "Invitations apply to invited-only events")
    if event.status == "cancelled":
        fail(409, "event_cancelled", "A cancelled event cannot receive invitations")
    targets = []
    for uid in dict.fromkeys(user_ids):
        target = db.get(AppUser, uid)
        if target is None or not target.is_active or uid == event.organizer_user_id:
            fail(422, "user_unavailable", "An invitee is missing, deactivated or the organizer")
        if calendar.club_id is not None and access.active_membership(db, target, calendar.club_id) is None:
            fail(422, "not_member", "Club events can only invite active club members")
        targets.append(target)
    rows = {r.invitee_user_id: r for r in db.query(EventInvitation).filter(
        EventInvitation.event_id == event.id, EventInvitation.invitee_user_id.in_([t.id for t in targets]))
        .with_for_update()}
    live = db.query(func.count()).select_from(EventInvitation).filter(
        EventInvitation.event_id == event.id, EventInvitation.status != "revoked").scalar()
    added = sum(1 for t in targets if t.id not in rows or rows[t.id].status == "revoked")
    if live + added > MAX_INVITES_PER_EVENT:
        fail(422, "too_many_invitations", f"An event can have at most {MAX_INVITES_PER_EVENT} invitations")
    out, fresh = [], []
    for target in targets:
        row = rows.get(target.id)
        if row is None:
            row = EventInvitation(event_id=event.id, invitee_user_id=target.id, invited_by_user_id=user.id)
            db.add(row)
            fresh.append(target.id)
        elif row.status == "revoked":  # re-invite after revocation
            row.status, row.revoked_at, row.responded_at, row.invited_by_user_id = "pending", None, None, user.id
            fresh.append(target.id)
        out.append(row)
    from app.services import calendar_alerts
    calendar_alerts.note_invitations(db, event, user, fresh)
    db.flush()
    return out


def revoke_invitation(db: Session, user: AppUser, event_id: int, invitee_id: int) -> EventInvitation:
    event, _calendar = editable_event(db, user, event_id)
    row = db.query(EventInvitation).filter_by(event_id=event.id, invitee_user_id=invitee_id).with_for_update() \
        .one_or_none()
    if row is None:
        fail(404, "invitation_not_found", "Invitation not found")
    if row.status != "revoked":
        row.status, row.revoked_at = "revoked", datetime.utcnow()
        db.flush()
        target = db.get(AppUser, invitee_id)
        still_visible = target is not None and access.visible_events(db, target).filter(
            CalendarEvent.id == event.id).first() is not None
        if not still_visible:  # no other grant: drop their active participation
            occurrence_ids = db.query(EventOccurrence.id).filter(EventOccurrence.event_id == event.id)
            db.query(OccurrenceInterest).filter(
                OccurrenceInterest.user_id == invitee_id,
                OccurrenceInterest.occurrence_id.in_(occurrence_ids.scalar_subquery())).delete(
                synchronize_session=False)
            db.query(CalendarEventFollow).filter_by(event_id=event.id, user_id=invitee_id).delete(
                synchronize_session=False)
        db.flush()
    return row


def respond_invitation(db: Session, user: AppUser, event_id: int, status: str) -> EventInvitation:
    visible_event(db, user, event_id)
    row = db.query(EventInvitation).filter_by(event_id=event_id, invitee_user_id=user.id).with_for_update() \
        .one_or_none()
    if row is None or row.status == "revoked":
        fail(404, "invitation_not_found", "Invitation not found")
    if row.status != status:
        row.status, row.responded_at = status, datetime.utcnow()
        db.flush()
    return row


# --- Responses ---------------------------------------------------------------------------

def _open_occurrence(db: Session, user: AppUser, occurrence_id: int):
    occurrence, event, calendar = visible_occurrence(db, user, occurrence_id)
    if event.status != "published" or occurrence.status != "scheduled":
        fail(409, "not_open", "Responses are closed for a draft or cancelled session")
    return occurrence, event, calendar


def set_interest(db: Session, user: AppUser, occurrence_id: int, state: Optional[str]):
    occurrence, _event, _calendar = _open_occurrence(db, user, occurrence_id)
    row = db.get(OccurrenceInterest, (occurrence.id, user.id))
    if state is None:
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(OccurrenceInterest(occurrence_id=occurrence.id, user_id=user.id, state=state))
    elif row.state != state:
        row.state, row.updated_at = state, datetime.utcnow()
    db.flush()


def absence_allowed(db: Session, user: AppUser, event: CalendarEvent, calendar: Calendar) -> bool:
    """Absence applies to club/group training the member is expected at:
    assigned group sessions, or club-wide training for any active member."""
    if event.event_type != "training" or calendar.club_id is None or event.audience not in ("group", "club"):
        return False
    if access.active_membership(db, user, calendar.club_id) is None:
        return False
    if event.audience == "club":
        return True
    assignment = access.current_group_assignment(db, user.id, calendar.club_id)
    return assignment is not None and assignment.group_id == calendar.training_group_id


def set_absence(db: Session, user: AppUser, occurrence_id: int, absent: bool):
    occurrence, event, calendar = _open_occurrence(db, user, occurrence_id)
    if not absence_allowed(db, user, event, calendar):
        fail(403, "absence_not_applicable", "Absence reporting is for members assigned to this session")
    row = db.get(OccurrenceAbsenceReport, (occurrence.id, user.id))
    if absent:
        if row is None:
            db.add(OccurrenceAbsenceReport(occurrence_id=occurrence.id, user_id=user.id))
        elif row.withdrawn_at is not None:
            row.reported_at, row.withdrawn_at = datetime.utcnow(), None
    elif row is not None and row.withdrawn_at is None:
        row.withdrawn_at = datetime.utcnow()
    db.flush()


# --- Following --------------------------------------------------------------------------------

def follow_calendar(db: Session, user: AppUser, calendar_id: int, on: bool) -> None:
    if access.visible_calendars(db, user).filter(Calendar.id == calendar_id).one_or_none() is None:
        fail(404, "calendar_not_found", "Calendar not found")
    row = db.get(CalendarSubscription, (calendar_id, user.id))
    if on and row is None:
        db.add(CalendarSubscription(calendar_id=calendar_id, user_id=user.id))
    elif not on and row is not None:
        db.delete(row)
    db.flush()


def follow_event(db: Session, user: AppUser, event_id: int, on: bool) -> None:
    visible_event(db, user, event_id)
    row = db.get(CalendarEventFollow, (event_id, user.id))
    if on and row is None:
        db.add(CalendarEventFollow(event_id=event_id, user_id=user.id))
    elif not on and row is not None:
        db.delete(row)
    db.flush()


# --- Dive links ------------------------------------------------------------------------------------

def occurrence_local_day(occurrence: EventOccurrence, event: CalendarEvent) -> date:
    if occurrence.is_all_day:
        return occurrence.start_date
    return utc_to_local(occurrence.starts_at, event.timezone).date()


def linkable_dives_query(db: Session, user: AppUser, occurrence: EventOccurrence, event: CalendarEvent):
    """The caller's own dives on the occurrence's local date(s). Ownership
    uses the existing OWNER bindings; nothing about media access changes."""
    from app.services.dive_access import owned_diver_ids

    first = occurrence_local_day(occurrence, event)
    last = (occurrence.end_date - timedelta(days=1)) if occurrence.is_all_day else first
    owned = owned_diver_ids(db, user.id)
    return db.query(Dive).filter(
        Dive.diver_id.in_(owned or (-1,)),
        Dive.dive_datetime >= datetime.combine(first, time()),
        Dive.dive_datetime < datetime.combine(last + timedelta(days=1), time()))


def link_dive(db: Session, user: AppUser, occurrence_id: int, dive_id: int, on: bool) -> None:
    occurrence, event, _calendar = visible_occurrence(db, user, occurrence_id)
    row = db.get(OccurrenceDiveLink, (occurrence.id, dive_id))
    if not on:
        if row is not None and row.user_id == user.id:
            db.delete(row)
            db.flush()
        return
    dive = linkable_dives_query(db, user, occurrence, event).filter(Dive.id == dive_id).one_or_none()
    if dive is None:
        fail(422, "dive_not_linkable", "Only your own dives from this session date can be linked")
    if row is None:
        db.add(OccurrenceDiveLink(occurrence_id=occurrence.id, dive_id=dive.id, user_id=user.id))
        db.flush()
