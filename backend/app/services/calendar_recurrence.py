"""Weekly series, scoped schedule edits and camp itineraries (Task04).

Model: a series is one calendar_events row plus one calendar_event_recurrences
pattern (ISO weekdays, local wall times, explicit season end) and durable
excluded dates. Every date is materialized as an event_occurrences row when
the pattern is saved: the season is bounded (MAX_SEASON_DAYS,
MAX_SERIES_OCCURRENCES), so there is no rolling horizon or background worker.
Rows stay the source of truth.

Identity: each generated row records its pattern slot (series_date) and keeps
its id when moved, so interest, absence reports and dive links follow it.

Scoped edits (preview -> apply):
- one:    this session only. The row becomes ``detached``: later pattern edits
          never overwrite it.
- future: this session and the following ones (pivot = selected session date,
          never before today).
- all:    every upcoming session (pivot = today or the season start). Past
          sessions are history and are never rewritten.
Regeneration from the pivot pairs existing rows with the new dates: exact slot
first, then within the same ISO week (a weekday change moves the row and keeps
responses). Leftover rows are cancelled (never deleted); leftover dates are
created. Cancelled and detached rows are kept and occupy their slot, so a
regeneration never resurrects a cancellation nor wipes an individual edit.

Apply recomputes the plan under row locks and refuses (409 stale_preview) if
it differs from the previewed plan hash, or if the event version moved.

Imported schedules (KCPM PDFs) are explicit authoritative dates without a
pattern: pattern edits are refused (409 imported_series); single sessions stay
editable and are marked locally_overridden for the importer.
"""
import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.calendar import (
    CalendarEvent, CalendarEventRecurrence, CalendarRecurrenceExclusion, CalendarSourceMapping, EventItineraryItem,
    EventOccurrence, OccurrenceAbsenceReport, OccurrenceDiveLink, OccurrenceInterest,
)
from app.models.user_auth import AppUser
from app.services import calendar_events as events
from app.services.calendar_membership import fail

MAX_SEASON_DAYS = 400
MAX_SERIES_OCCURRENCES = 200
MAX_EXCLUSIONS = 120
MAX_ITINERARY_ITEMS = 20
WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


# --- Pattern helpers -------------------------------------------------------------------

def weekday_mask(weekdays) -> int:
    days = set(weekdays or ())
    if not days or not days <= set(range(1, 8)):
        fail(422, "invalid_weekdays", "Choose at least one weekday")
    return sum(1 << (d - 1) for d in days)


def weekdays_of(mask: int) -> list:
    return [d for d in range(1, 8) if mask & (1 << (d - 1))]


def parse_time(value: str) -> time:
    try:
        hh, mm = value.split(":")
        return time(int(hh), int(mm))
    except (ValueError, AttributeError):
        fail(422, "invalid_time", "Times use HH:MM")


def pattern_dates(start: date, until: date, mask: int, excluded: set) -> list:
    out, day = [], start
    while day <= until:
        if mask & (1 << day.weekday()) and day not in excluded:
            out.append(day)
        day += timedelta(days=1)
    return out


def slot_fields(day: date, start: time, end: time, tz: str) -> dict:
    """Timed occurrence columns for one date; raises for a DST gap/overlap."""
    a = events.local_to_utc(datetime.combine(day, start), tz)
    b = events.local_to_utc(datetime.combine(day, end), tz)
    return dict(is_all_day=False, start_date=None, end_date=None, starts_at=a, ends_at=b, window_start=a,
                window_end=b)


def check_local_times(days, start: time, end: time, tz: str) -> None:
    """Refuse the whole pattern, listing every date whose wall time falls in a
    clock change, so the editor can exclude those dates or pick another time."""
    bad = []
    for day in days:
        for t in (start, end):
            local = datetime.combine(day, t)
            z = ZoneInfo(tz)
            early, late = local.replace(tzinfo=z, fold=0), local.replace(tzinfo=z, fold=1)
            if early.utcoffset() != late.utcoffset() or \
                    early.astimezone(ZoneInfo("UTC")).astimezone(z).replace(tzinfo=None) != local:
                bad.append(day.isoformat())
                break
    if bad:
        fail(422, "dst_local_time",
             f"The time does not exist or occurs twice on {', '.join(bad)} (clock change); "
             "exclude these dates or choose another time")


def validate_pattern(first: date, until: date, start: time, end: time, excluded: set) -> None:
    if end <= start:
        fail(422, "invalid_time", "End must be after the start (same day)")
    if until < first:
        fail(422, "invalid_season", "The season end must be on or after the first date")
    if (until - first).days > MAX_SEASON_DAYS:
        fail(422, "season_too_long", f"A series can span at most {MAX_SEASON_DAYS} days; set an earlier season end")
    if len(excluded) > MAX_EXCLUSIONS:
        fail(422, "too_many_exclusions", f"At most {MAX_EXCLUSIONS} excluded dates")


def local_today(tz: str) -> date:
    return datetime.now(ZoneInfo(tz)).date()


def slot_of(o: EventOccurrence, event: CalendarEvent) -> date:
    return o.series_date or events.occurrence_local_day(o, event)


def is_imported(db: Session, event_id: int) -> bool:
    return db.query(CalendarSourceMapping.id).filter(CalendarSourceMapping.event_id == event_id).first() is not None


def recurrence_out(db: Session, event: CalendarEvent) -> Optional[dict]:
    rule = db.get(CalendarEventRecurrence, event.id)
    if rule is None:
        return None
    excluded = [d for (d,) in db.query(CalendarRecurrenceExclusion.local_date).filter_by(event_id=event.id)
                .order_by(CalendarRecurrenceExclusion.local_date)]
    return dict(weekdays=weekdays_of(rule.weekdays), start_time=rule.start_time.strftime("%H:%M"),
                end_time=rule.end_time.strftime("%H:%M"), first_date=rule.first_date, until_date=rule.until_date,
                pattern_from=rule.pattern_from, excluded_dates=excluded)


# --- Create ----------------------------------------------------------------------------------

def create_series(db: Session, user: AppUser, event: CalendarEvent, first_occurrence: EventOccurrence,
                  spec) -> None:
    """Turn a freshly created single event into a weekly series. `spec` is
    schemas.RecurrenceSpec; the first occurrence's local times are the pattern."""
    if event.event_type == "camp" or first_occurrence.is_all_day:
        fail(422, "recurrence_not_supported", "Weekly repetition applies to timed sessions, not camps or all-day events")
    tz = event.timezone
    start_local = events.utc_to_local(first_occurrence.starts_at, tz)
    end_local = events.utc_to_local(first_occurrence.ends_at, tz)
    if start_local.date() != end_local.date():
        fail(422, "invalid_time", "A repeating session must start and end on the same day")
    first, start, end = start_local.date(), start_local.time(), end_local.time()
    excluded = set(spec.excluded_dates or ())
    validate_pattern(first, spec.until_date, start, end, excluded)
    mask = weekday_mask(spec.weekdays)
    days = pattern_dates(first, spec.until_date, mask, excluded)
    if not days:
        fail(422, "empty_series", "No session matches these weekdays and dates")
    if len(days) > MAX_SERIES_OCCURRENCES:
        fail(422, "too_many_sessions", f"A series can have at most {MAX_SERIES_OCCURRENCES} sessions")
    check_local_times(days, start, end, tz)
    db.add(CalendarEventRecurrence(event_id=event.id, weekdays=mask, start_time=start, end_time=end,
                                   first_date=first, until_date=spec.until_date, pattern_from=first))
    for d in sorted(excluded):
        db.add(CalendarRecurrenceExclusion(event_id=event.id, local_date=d, created_by_user_id=user.id))
    # The first created row becomes the first pattern slot (or is replaced).
    rows = []
    for i, d in enumerate(days):
        fields = slot_fields(d, start, end, tz)
        if i == 0:
            for k, v in fields.items():
                setattr(first_occurrence, k, v)
            first_occurrence.occurrence_key, first_occurrence.series_date = f"w:{d}", d
            rows.append(first_occurrence)
        else:
            row = EventOccurrence(event_id=event.id, occurrence_key=f"w:{d}", series_date=d, **fields)
            db.add(row)
            rows.append(row)
    db.flush()
    event.recurrence_rule = rule_text(mask, start, end, spec.until_date)
    events.log_change(db, event, "updated", user, {"sessions": (None, len(rows))})


def rule_text(mask: int, start: time, end: time, until: date) -> str:
    """Human-readable metadata kept in the Task02 recurrence_rule column."""
    return (f"WEEKLY {','.join(WEEKDAY_NAMES[d - 1] for d in weekdays_of(mask))} "
            f"{start:%H:%M}-{end:%H:%M} until {until}")


# --- Scoped schedule edits -----------------------------------------------------------------------

def _counts(db: Session, ids: list) -> dict:
    out = defaultdict(lambda: {"interested": 0, "maybe": 0, "declined": 0, "absences": 0, "dive_links": 0})
    if not ids:
        return out
    for oid, state, n in db.query(OccurrenceInterest.occurrence_id, OccurrenceInterest.state, func.count()).filter(
            OccurrenceInterest.occurrence_id.in_(ids)).group_by(OccurrenceInterest.occurrence_id,
                                                                OccurrenceInterest.state):
        out[oid][state] = n
    for oid, n in db.query(OccurrenceAbsenceReport.occurrence_id, func.count()).filter(
            OccurrenceAbsenceReport.occurrence_id.in_(ids), OccurrenceAbsenceReport.withdrawn_at.is_(None)) \
            .group_by(OccurrenceAbsenceReport.occurrence_id):
        out[oid]["absences"] = n
    for oid, n in db.query(OccurrenceDiveLink.occurrence_id, func.count()).filter(
            OccurrenceDiveLink.occurrence_id.in_(ids)).group_by(OccurrenceDiveLink.occurrence_id):
        out[oid]["dive_links"] = n
    return out


def _local(o_fields: dict, tz: str) -> dict:
    if o_fields.get("is_all_day"):
        return {"date": o_fields["start_date"].isoformat(), "start": None, "end": None}
    a, b = events.utc_to_local(o_fields["starts_at"], tz), events.utc_to_local(o_fields["ends_at"], tz)
    return {"date": a.date().isoformat(), "start": a.strftime("%H:%M"), "end": b.strftime("%H:%M")}


def _row_fields(o: EventOccurrence) -> dict:
    return {k: getattr(o, k) for k in events.TIME_COLUMNS}


def _iso_week(d: date):
    return d.isocalendar()[:2]


def build_plan(db: Session, event: CalendarEvent, edit, occurrences: list) -> dict:
    """Deterministic diff for a scoped edit (no writes). `occurrences` are the
    event's rows (locked by the caller when applying)."""
    tz = event.timezone
    today = local_today(tz)
    by_id = {o.id: o for o in occurrences}
    target = by_id.get(edit.occurrence_id) if edit.occurrence_id else None
    if edit.occurrence_id and target is None:
        fail(404, "occurrence_not_found", "Occurrence not found")
    plan = {"scope": edit.scope, "event_id": event.id, "event_version": event.version, "created": [], "moved": [],
            "cancelled": [], "kept": [], "unchanged": 0, "venue_name": None, "pattern": None, "excluded": None,
            "pivot": None, "basis": sorted([o.id, o.version, o.status] for o in occurrences)}
    venue_sent = "venue_name" in edit.model_fields_set
    if venue_sent:
        plan["venue_name"] = edit.venue_name

    if edit.scope == "one":
        if target is None:
            fail(422, "occurrence_required", "Choose the session to change")
        if target.status == "cancelled":
            fail(409, "event_cancelled", "This session is already cancelled")
        old = _local(_row_fields(target), tz)
        if edit.cancel:
            plan["cancelled"].append({"occurrence_id": target.id, **old})
        else:
            new_fields = events.occurrence_fields(edit.when, tz) if edit.when is not None else _row_fields(target)
            check_itinerary_range(db, event, EventOccurrence(**new_fields))
            new = _local(new_fields, tz)
            venue_change = venue_sent and edit.venue_name != target.venue_name
            if new != old or venue_change:
                plan["moved"].append({"occurrence_id": target.id, "from": old, "to": new,
                                      "fields": {k: events._jsonable(v) for k, v in new_fields.items()}})
            else:
                plan["unchanged"] = 1
        _attach_counts(db, plan)
        return plan

    if is_imported(db, event.id):
        fail(409, "imported_series",
             "These dates come from the club's imported schedule and are kept exactly as published. "
             "Change sessions one at a time, or import a corrected schedule.")
    rule = db.get(CalendarEventRecurrence, event.id)
    if rule is None:
        fail(422, "not_recurring", "This event does not repeat; edit it directly")
    if edit.scope == "future":
        if target is None:
            fail(422, "occurrence_required", "Choose the session the change starts from")
        pivot = max(slot_of(target, event), today, rule.first_date)
    else:
        pivot = max(rule.first_date, today)
    start = parse_time(edit.start_time) if edit.start_time else rule.start_time
    end = parse_time(edit.end_time) if edit.end_time else rule.end_time
    until = edit.until_date or rule.until_date
    mask = weekday_mask(edit.weekdays) if edit.weekdays is not None else rule.weekdays
    old_excluded = {d for (d,) in db.query(CalendarRecurrenceExclusion.local_date).filter_by(event_id=event.id)}
    if edit.excluded_dates is not None:
        excluded = {d for d in old_excluded if d < pivot} | {d for d in edit.excluded_dates if d >= pivot}
    else:
        excluded = set(old_excluded)
    validate_pattern(rule.first_date, until, start, end, excluded)
    if until < pivot:
        fail(422, "invalid_season", f"The season end must be on or after {pivot.isoformat()}")
    plan.update(pivot=pivot.isoformat(),
                pattern={"weekdays": weekdays_of(mask), "start_time": start.strftime("%H:%M"),
                         "end_time": end.strftime("%H:%M"), "until_date": until.isoformat()},
                excluded=sorted(d.isoformat() for d in excluded))
    wanted = pattern_dates(pivot, until, mask, excluded)
    check_local_times(wanted, start, end, tz)

    in_scope = [o for o in occurrences if slot_of(o, event) >= pivot]
    blocked, free = set(), []
    for o in sorted(in_scope, key=lambda o: (slot_of(o, event), o.id)):
        if o.status == "cancelled" or o.detached:
            blocked.add(slot_of(o, event))
            plan["kept"].append({"occurrence_id": o.id, "reason": "cancelled" if o.status == "cancelled"
                                 else "edited_individually", **_local(_row_fields(o), tz)})
        else:
            free.append(o)
    targets = [d for d in wanted if d not in blocked]
    pairs, remaining = [], []
    by_slot = {}
    for o in free:
        by_slot.setdefault(slot_of(o, event), []).append(o)
    left = []
    for d in targets:
        if by_slot.get(d):
            pairs.append((by_slot[d].pop(0), d))
        else:
            left.append(d)
    remaining = [o for rows in by_slot.values() for o in rows]
    weeks_old, weeks_new = defaultdict(list), defaultdict(list)
    for o in sorted(remaining, key=lambda o: (slot_of(o, event), o.id)):
        weeks_old[_iso_week(slot_of(o, event))].append(o)
    for d in left:
        weeks_new[_iso_week(d)].append(d)
    to_cancel, to_create = [], []
    for week in sorted(set(weeks_old) | set(weeks_new)):
        olds, news = weeks_old.get(week, []), weeks_new.get(week, [])
        pairs += list(zip(olds, news))
        to_cancel += olds[len(news):]
        to_create += news[len(olds):]

    total = sum(1 for o in occurrences if o.status == "scheduled") - len(to_cancel) + len(to_create)
    if total > MAX_SERIES_OCCURRENCES:
        fail(422, "too_many_sessions", f"A series can have at most {MAX_SERIES_OCCURRENCES} sessions")
    for o, d in sorted(pairs, key=lambda p: p[1]):
        fields = slot_fields(d, start, end, tz)
        venue_change = venue_sent and edit.venue_name != o.venue_name
        if _row_fields(o) == fields and slot_of(o, event) == d and not venue_change:
            plan["unchanged"] += 1
            continue
        plan["moved"].append({"occurrence_id": o.id, "from": _local(_row_fields(o), tz),
                              "to": _local(fields, tz), "series_date": d.isoformat()})
    for o in to_cancel:
        plan["cancelled"].append({"occurrence_id": o.id, **_local(_row_fields(o), tz)})
    for d in to_create:
        plan["created"].append({"series_date": d.isoformat(), **_local(slot_fields(d, start, end, tz), tz)})
    plan["moved"].sort(key=lambda m: m["to"]["date"])
    plan["cancelled"].sort(key=lambda m: m["date"])
    _attach_counts(db, plan)
    return plan


def _attach_counts(db: Session, plan: dict) -> None:
    ids = [m["occurrence_id"] for m in plan["moved"]] + [m["occurrence_id"] for m in plan["cancelled"]]
    counts = _counts(db, ids)
    for item in plan["moved"] + plan["cancelled"]:
        item["responses"] = dict(counts[item["occurrence_id"]])


def plan_hash(plan: dict) -> str:
    """Identifies the schedule change itself. Response counts are shown for
    information only: a new response between preview and apply does not
    invalidate the preview, but any change to a session or the event does."""
    core = {k: v for k, v in plan.items() if k not in ("moved", "cancelled")}
    core["moved"] = [{k: v for k, v in m.items() if k != "responses"} for m in plan["moved"]]
    core["cancelled"] = [{k: v for k, v in m.items() if k != "responses"} for m in plan["cancelled"]]
    return hashlib.sha256(json.dumps(core, sort_keys=True, default=str).encode()).hexdigest()


def summary(plan: dict) -> dict:
    affected = plan["moved"] + plan["cancelled"]
    return {"created": len(plan["created"]), "moved": len(plan["moved"]), "cancelled": len(plan["cancelled"]),
            "unchanged": plan["unchanged"], "kept": len(plan["kept"]),
            "responses_kept": sum(i["responses"]["interested"] + i["responses"]["maybe"] + i["responses"]["declined"]
                                  for i in plan["moved"]),
            "responses_on_cancelled": sum(i["responses"]["interested"] + i["responses"]["maybe"]
                                          for i in plan["cancelled"]),
            "absences_affected": sum(i["responses"]["absences"] for i in affected)}


def _locked_rows(db: Session, user: AppUser, event_id: int, lock: bool):
    if lock:
        event, calendar = events.editable_event(db, user, event_id)
        rows = db.query(EventOccurrence).filter(EventOccurrence.event_id == event.id) \
            .order_by(EventOccurrence.id).with_for_update().all()
        for row in rows:
            db.refresh(row)
    else:
        event, calendar = events.visible_event(db, user, event_id)
        if not events.can_edit(db, user, calendar):
            fail(403, "forbidden", "Only the organizer or an authorized club publisher can change this event")
        rows = db.query(EventOccurrence).filter(EventOccurrence.event_id == event.id).order_by(EventOccurrence.id).all()
    return event, rows


def preview(db: Session, user: AppUser, event_id: int, edit) -> dict:
    event, rows = _locked_rows(db, user, event_id, lock=False)
    events._check_version(event, edit.expected_version, "event")
    if event.status == "cancelled":
        fail(409, "event_cancelled", "A cancelled event cannot be edited")
    plan = build_plan(db, event, edit, rows)
    return {"plan": plan, "plan_hash": plan_hash(plan), "summary": summary(plan)}


def apply(db: Session, user: AppUser, event_id: int, edit, expected_hash: str) -> dict:
    event, rows = _locked_rows(db, user, event_id, lock=True)
    events._check_version(event, edit.expected_version, "event")
    if event.status == "cancelled":
        fail(409, "event_cancelled", "A cancelled event cannot be edited")
    plan = build_plan(db, event, edit, rows)
    if plan_hash(plan) != expected_hash:
        fail(409, "stale_preview", "The schedule changed since your preview; review the new preview before applying")
    by_id = {o.id: o for o in rows}
    tz, now = event.timezone, datetime.utcnow()
    event.version += 1
    if plan["scope"] == "one":
        for m in plan["moved"]:
            o = by_id[m["occurrence_id"]]
            new = events.occurrence_fields(edit.when, tz) if edit.when is not None else _row_fields(o)
            changes = {k: (getattr(o, k), v) for k, v in new.items() if getattr(o, k) != v}
            for k, (_a, v) in changes.items():
                setattr(o, k, v)
            if changes:
                events.log_change(db, event, "time_changed", user, changes, o)
            if "venue_name" in edit.model_fields_set and o.venue_name != edit.venue_name:
                events.log_change(db, event, "venue_changed", user, {"venue_name": (o.venue_name, edit.venue_name)}, o)
                o.venue_name = edit.venue_name
            o.version += 1
            o.detached = o.series_date is not None
            events._mark_overridden(db, event.id, o.id)
    else:
        rule = db.get(CalendarEventRecurrence, event.id)
        pattern, pivot = plan["pattern"], date.fromisoformat(plan["pivot"])
        old_text = event.recurrence_rule
        rule.weekdays = weekday_mask(pattern["weekdays"])
        rule.start_time, rule.end_time = parse_time(pattern["start_time"]), parse_time(pattern["end_time"])
        rule.until_date, rule.pattern_from = date.fromisoformat(pattern["until_date"]), pivot
        wanted = {date.fromisoformat(d) for d in plan["excluded"]}
        current = {x.local_date: x for x in db.query(CalendarRecurrenceExclusion).filter_by(event_id=event.id)}
        for d, row in current.items():
            if d not in wanted:
                db.delete(row)  # pattern input only; the cancelled rows themselves are kept
        for d in sorted(wanted - set(current)):
            db.add(CalendarRecurrenceExclusion(event_id=event.id, local_date=d, created_by_user_id=user.id))
        event.recurrence_rule = rule_text(rule.weekdays, rule.start_time, rule.end_time, rule.until_date)
        for m in plan["moved"]:
            o = by_id[m["occurrence_id"]]
            d = date.fromisoformat(m["series_date"])
            new = slot_fields(d, rule.start_time, rule.end_time, tz)
            changes = {k: (getattr(o, k), v) for k, v in new.items() if getattr(o, k) != v}
            for k, (_a, v) in changes.items():
                setattr(o, k, v)
            o.series_date = d
            if changes:
                events.log_change(db, event, "time_changed", user, changes, o)
            if "venue_name" in edit.model_fields_set and o.venue_name != edit.venue_name:
                events.log_change(db, event, "venue_changed", user, {"venue_name": (o.venue_name, edit.venue_name)}, o)
                o.venue_name = edit.venue_name
            o.version += 1
        keys = {o.occurrence_key for o in rows}
        for c in plan["created"]:
            d = date.fromisoformat(c["series_date"])
            key, n = f"w:{d}", 1
            while key in keys:
                n += 1
                key = f"w:{d}:{n}"
            keys.add(key)
            row = EventOccurrence(event_id=event.id, occurrence_key=key, series_date=d,
                                  venue_name=edit.venue_name if "venue_name" in edit.model_fields_set else None,
                                  **slot_fields(d, rule.start_time, rule.end_time, tz))
            db.add(row)
            db.flush()
            events.log_change(db, event, "created", user, {"series_date": (None, d)}, row)
        events.log_change(db, event, "updated", user, {"schedule": (old_text, event.recurrence_rule),
                                                       "scope": (None, f"{plan['scope']} from {plan['pivot']}")})
    for m in plan["cancelled"]:
        o = by_id[m["occurrence_id"]]
        o.version += 1
        o.status, o.cancelled_at = "cancelled", now
        events.log_change(db, event, "cancelled", user, {"status": ("scheduled", "cancelled")}, o)
        events._mark_overridden(db, event.id, o.id)
    db.flush()
    return {"plan": plan, "summary": summary(plan), "event_version": event.version}


# --- Camp itinerary ------------------------------------------------------------------------------

def local_range(event: CalendarEvent, occurrence: EventOccurrence) -> tuple:
    """Inclusive first/last local day (all-day end dates are exclusive)."""
    first = events.occurrence_local_day(occurrence, event)
    last = (occurrence.end_date - timedelta(days=1)) if occurrence.is_all_day else \
        events.utc_to_local(occurrence.ends_at - timedelta(microseconds=1), event.timezone).date()
    return first, last


def check_itinerary_range(db: Session, event: CalendarEvent, occurrence: EventOccurrence) -> None:
    first, last = local_range(event, occurrence)
    outside = db.query(EventItineraryItem.id).filter(
        EventItineraryItem.event_id == event.id,
        (EventItineraryItem.local_date < first) | (EventItineraryItem.local_date > last)).first()
    if outside is not None:
        fail(422, "itinerary_outside_dates", "Some itinerary blocks fall outside the new dates; update them too")


def set_itinerary(db: Session, event: CalendarEvent, occurrence: Optional[EventOccurrence], items) -> bool:
    """Replace the itinerary. Blocks must fall inside the single camp date
    range; they are informational, never separately bookable."""
    if items is None:
        return False
    if len(items) > MAX_ITINERARY_ITEMS:
        fail(422, "too_many_blocks", f"At most {MAX_ITINERARY_ITEMS} itinerary blocks")
    if items and occurrence is None:
        fail(422, "itinerary_single_event", "An itinerary applies to a single (camp) event")
    if items:
        first, last = local_range(event, occurrence)
        for item in items:
            if not first <= item.local_date <= last:
                fail(422, "itinerary_outside_dates", "Itinerary blocks must fall within the event dates")
            if item.start_time and item.end_time and parse_time(item.end_time) <= parse_time(item.start_time):
                fail(422, "invalid_time", "A block must end after it starts")
    old = [(i.local_date, i.start_time, i.end_time, i.venue_name, i.label) for i in
           db.query(EventItineraryItem).filter_by(event_id=event.id).order_by(EventItineraryItem.position)]
    new = [(i.local_date, parse_time(i.start_time) if i.start_time else None,
            parse_time(i.end_time) if i.end_time else None, i.venue_name or None, i.label or None) for i in items]
    new.sort(key=lambda r: (r[0], r[1] or time()))
    if old == new:
        return False
    db.query(EventItineraryItem).filter_by(event_id=event.id).delete(synchronize_session=False)
    for pos, (d, a, b, venue, label) in enumerate(new):
        db.add(EventItineraryItem(event_id=event.id, position=pos, local_date=d, start_time=a, end_time=b,
                                  venue_name=venue, label=label))
    db.flush()
    return True


def itinerary_out(db: Session, event_id: int) -> list:
    return [dict(local_date=i.local_date, start_time=i.start_time.strftime("%H:%M") if i.start_time else None,
                 end_time=i.end_time.strftime("%H:%M") if i.end_time else None, venue_name=i.venue_name,
                 label=i.label)
            for i in db.query(EventItineraryItem).filter_by(event_id=event_id).order_by(EventItineraryItem.position)]
