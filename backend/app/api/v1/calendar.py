"""Calendar read API + minimal club administration (Task02, default-off).

CALENDAR_ENABLED=false -> every route 404s; signup never touches calendar tables.
Enabled without the SQL migration -> 503, never a half-created schema.
The public signup club list lives at /auth/signup-clubs (pre-session).
Reads apply calendar_access policies in SQL before pagination; a private id
answers exactly like a missing one. Task03 adds event/occurrence writes,
invitations, interest/absence, follows and dive links (services in
calendar_events); every write re-resolves its target through the same read
policy, so a hidden id answers 404 for writes too.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy import and_, func, inspect, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.admin_users import require_admin
from app.api.v1.auth import _origin_allowed, get_current_user
from app.config import get_settings
from app.services.calendar_launch import enabled as calendar_enabled
from app.database import get_db
from app.models.calendar import (
    Calendar, CalendarChangeLog, CalendarEvent, CalendarEventFollow, CalendarSourceMapping, CalendarSubscription,
    Club, ClubMembership, EventInvitation, EventOccurrence, OccurrenceAbsenceReport, OccurrenceDiveLink,
    OccurrenceInterest, TrainingGroup, TrainingGroupMembership,
)
from app.models.dive import Dive
from app.models.media import MediaCacheEntry
from app.models.user_auth import AppUser
from app.schemas import calendar as s
from app.services import calendar_access as access
from app.services import calendar_events as events
from app.services import calendar_recurrence as recurrence
from app.services import calendar_membership as membership
from app.services.media_cache import playback_url
from app.services.member_avatar import avatar_identity

MAX_WINDOW_DAYS = 100
MAX_LIMIT = 200
_schema_ready = False


def calendar_gate(db: Session = Depends(get_db)) -> None:
    global _schema_ready
    if not calendar_enabled(db):
        raise HTTPException(404, "Not found")
    if not _schema_ready:
        # A table of the newest calendar migration (Task05).
        if not inspect(db.get_bind()).has_table("calendar_alert_deliveries"):
            raise HTTPException(503, "Calendar schema not installed")
        _schema_ready = True


def private_responses(response: Response) -> None:
    # Account-scoped data: never stored by shared or service-worker caches.
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(prefix="/calendar", dependencies=[Depends(calendar_gate), Depends(private_responses)])


def writer(request: Request, user: AppUser = Depends(get_current_user)) -> AppUser:
    if not _origin_allowed(request):
        raise HTTPException(403, "Origin not allowed")
    return user


def admin_writer(request: Request, user: AppUser = Depends(require_admin)) -> AppUser:
    return writer(request, user)


def iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() + "Z" if value else None


def utc_naive(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, detail={"code": "conflict", "message": "Conflicting concurrent change"})


# --- Payload builders --------------------------------------------------------

def club_out(c: Club) -> s.ClubOut:
    return s.ClubOut(id=c.id, slug=c.slug, name=c.name, short_name=c.short_name, timezone=c.timezone,
                     self_join_enabled=bool(c.self_join_enabled))


def membership_out(m: ClubMembership) -> s.MembershipOut:
    return s.MembershipOut(id=m.id, club_id=m.club_id, user_id=m.user_id, role=m.role,
                           can_publish=bool(m.can_publish), can_assign_groups=bool(m.can_assign_groups),
                           status=m.status, source=m.source, started_at=iso(m.started_at), ended_at=iso(m.ended_at))


def group_out(g: TrainingGroup) -> s.GroupOut:
    return s.GroupOut(id=g.id, club_id=g.club_id, slug=g.slug, name=g.name)


def resource_out(r) -> s.ResourceOut:
    return s.ResourceOut(id=r.id, kind=r.kind, label=r.label, url=r.url, deadline_kind=r.deadline_kind,
                         due_at=iso(r.due_at), edition_label=r.edition_label,
                         source_verified_at=iso(r.source_verified_at))


def event_summary(e: CalendarEvent, c: Calendar) -> dict:
    return dict(id=e.id, calendar_id=c.id, calendar_kind=c.kind, club_id=c.club_id, event_type=e.event_type,
                audience=e.audience, status=e.status, title=e.title, timezone=e.timezone, version=e.version,
                calendar_name=c.name, training_group_id=c.training_group_id)


def local_view(o: EventOccurrence, e: CalendarEvent) -> dict:
    first, last = recurrence.local_range(e, o)
    if o.is_all_day:
        return dict(local_date=first, local_start=None, local_end=None, local_end_date=last)
    start, end = events.utc_to_local(o.starts_at, e.timezone), events.utc_to_local(o.ends_at, e.timezone)
    return dict(local_date=start.date(), local_start=start.strftime("%H:%M"), local_end=end.strftime("%H:%M"),
                local_end_date=last)


def recent_changes(db: Session, event_id: int, occurrence_id: Optional[int] = None) -> list:
    """Published time/venue/cancel changes (newest first) for the in-app notice."""
    query = db.query(CalendarChangeLog).filter(
        CalendarChangeLog.event_id == event_id,
        CalendarChangeLog.change_kind.in_(("time_changed", "venue_changed", "cancelled")))
    if occurrence_id is not None:
        query = query.filter(or_(CalendarChangeLog.occurrence_id.is_(None),
                                 CalendarChangeLog.occurrence_id == occurrence_id))
    return [s.ChangeOut(kind=r.change_kind, at=iso(r.created_at), fields=sorted((r.changes or {}).keys()))
            for r in query.order_by(CalendarChangeLog.id.desc()).limit(5)]


def occurrence_payloads(db: Session, user: AppUser, rows) -> list:
    ids = [o.id for o, _e, _c in rows]
    interest, absent = {}, set()
    if ids:
        interest = dict(db.query(OccurrenceInterest.occurrence_id, OccurrenceInterest.state).filter(
            OccurrenceInterest.user_id == user.id, OccurrenceInterest.occurrence_id.in_(ids)).all())
        absent = {oid for (oid,) in db.query(OccurrenceAbsenceReport.occurrence_id).filter(
            OccurrenceAbsenceReport.user_id == user.id, OccurrenceAbsenceReport.withdrawn_at.is_(None),
            OccurrenceAbsenceReport.occurrence_id.in_(ids))}
    imported = set()
    if ids:
        imported = {oid for (oid,) in db.query(CalendarSourceMapping.occurrence_id).filter(
            CalendarSourceMapping.occurrence_id.in_(ids))}
    return [dict(id=o.id, occurrence_key=o.occurrence_key, status=o.status, is_all_day=bool(o.is_all_day),
                 starts_at=iso(o.starts_at), ends_at=iso(o.ends_at), start_date=o.start_date, end_date=o.end_date,
                 venue_name=o.venue_name or e.venue_name, is_filmed_session=o.filmed_session_id is not None,
                 version=o.version, event=event_summary(e, c), my_interest=interest.get(o.id),
                 my_absence_reported=o.id in absent, imported=o.id in imported, series_date=o.series_date,
                 detached=bool(o.detached), **local_view(o, e))
            for o, e, c in rows]


GOING_PEOPLE = 8


def going_summary(db: Session, occurrence_id: int) -> s.GoingOut:
    """Counts and the first faces of "interested"/"maybe" answers (active accounts only)."""
    base = [OccurrenceInterest.occurrence_id == occurrence_id, AppUser.is_active.is_(True),
            OccurrenceInterest.state.in_(("interested", "maybe"))]
    counts = dict(db.query(OccurrenceInterest.state, func.count()).join(
        AppUser, AppUser.id == OccurrenceInterest.user_id).filter(*base).group_by(OccurrenceInterest.state).all())

    def faces(state: str, budget: int) -> list:
        if budget <= 0:
            return []
        return db.query(AppUser).join(
            OccurrenceInterest, OccurrenceInterest.user_id == AppUser.id).filter(
            *base, OccurrenceInterest.state == state).order_by(
            OccurrenceInterest.updated_at.desc()).limit(budget).all()

    interested = faces("interested", GOING_PEOPLE)
    maybe = faces("maybe", GOING_PEOPLE - len(interested))
    return s.GoingOut(
        interested=counts.get("interested", 0), maybe=counts.get("maybe", 0),
        people=[s.AttendeeOut(user_id=u.id, display_name=u.display_name, **avatar_identity(u))
                for u in interested + maybe])


# --- Authenticated reads -------------------------------------------------------

@router.get("/me", response_model=s.MeOut)
def me(user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(ClubMembership, Club).join(Club, Club.id == ClubMembership.club_id).filter(
        ClubMembership.user_id == user.id, ClubMembership.ended_at.is_(None), Club.archived_at.is_(None)) \
        .order_by(Club.id, ClubMembership.id).limit(MAX_LIMIT).all()
    on = access.today()
    membership_ids = [m.id for m, _c in rows]
    groups = {assignment.club_membership_id: group for assignment, group in db.query(
        TrainingGroupMembership, TrainingGroup).join(TrainingGroup,
            TrainingGroup.id == TrainingGroupMembership.group_id).filter(
        TrainingGroupMembership.club_membership_id.in_(membership_ids),
        TrainingGroupMembership.user_id == user.id, TrainingGroupMembership.effective_from <= on,
        or_(TrainingGroupMembership.effective_to.is_(None), TrainingGroupMembership.effective_to > on))
        .order_by(TrainingGroupMembership.id).limit(MAX_LIMIT)} if membership_ids else {}
    clubs = []
    for m, c in rows:
        group = groups.get(m.id)
        clubs.append(s.MyClubOut(club=club_out(c), membership=membership_out(m),
                                 group=group_out(group) if group else None, self_declared=m.source == "signup"))
    return s.MeOut(clubs=clubs)


@router.get("/calendars", response_model=s.CalendarsOut)
def calendars(user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = access.visible_calendars(db, user).order_by(Calendar.kind, Calendar.id).limit(MAX_LIMIT).all()
    following = {cid for (cid,) in db.query(CalendarSubscription.calendar_id).filter(
        CalendarSubscription.user_id == user.id, CalendarSubscription.calendar_id.in_([c.id for c in rows]))}
    # A personal calendar is created on the first outing (calendar_id=null).
    club_ids = {c.club_id for c in rows if c.club_id is not None}
    memberships = {m.club_id: m for m in db.query(ClubMembership).filter(
        ClubMembership.user_id == user.id, ClubMembership.ended_at.is_(None),
        ClubMembership.club_id.in_(club_ids)).limit(MAX_LIMIT)} if club_ids else {}
    writable = {c.id for c in rows if user.is_active and c.archived_at is None and (
        access.can_publish(memberships.get(c.club_id)) if c.kind in ("club", "group") else
        c.owner_user_id == user.id if c.kind == "personal" else bool(user.is_admin))}
    items = [s.CalendarOut(id=c.id, kind=c.kind, name=c.name, club_id=c.club_id,
                           training_group_id=c.training_group_id, following=c.id in following,
                           can_publish=c.id in writable,
                           allowed_audiences=list(access.ALLOWED_AUDIENCES[c.kind]) if c.id in writable else [])
             for c in rows]
    return s.CalendarsOut(items=items)


@router.get("/occurrences", response_model=s.OccurrencePage)
def occurrences(
    start: datetime = Query(..., alias="from"), end: datetime = Query(..., alias="to"),
    calendar_id: Optional[int] = Query(None, gt=0), limit: int = Query(100, ge=1, le=MAX_LIMIT),
    cursor: Optional[str] = Query(None, max_length=64),
    user: AppUser = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Occurrences overlapping [from, to), at most MAX_WINDOW_DAYS wide."""
    start, end = utc_naive(start), utc_naive(end)
    if end <= start or end - start > timedelta(days=MAX_WINDOW_DAYS):
        raise HTTPException(422, f"'to' must be after 'from' and within {MAX_WINDOW_DAYS} days")
    query = access.visible_occurrences(db, user).filter(
        EventOccurrence.window_start < end, EventOccurrence.window_end > start)
    if calendar_id is not None:
        query = query.filter(Calendar.id == calendar_id)
    if cursor:
        try:
            raw_ts, raw_id = cursor.rsplit("|", 1)
            cursor_ts, cursor_id = datetime.fromisoformat(raw_ts), int(raw_id)
        except ValueError:
            raise HTTPException(422, "Invalid cursor")
        query = query.filter(or_(EventOccurrence.window_start > cursor_ts,
                                 and_(EventOccurrence.window_start == cursor_ts, EventOccurrence.id > cursor_id)))
    rows = query.order_by(EventOccurrence.window_start, EventOccurrence.id).limit(limit + 1).all()
    more = len(rows) > limit
    rows = rows[:limit]
    last = rows[-1][0] if more else None
    return s.OccurrencePage(items=occurrence_payloads(db, user, rows),
                            next_cursor=f"{last.window_start.isoformat()}|{last.id}" if last else None)


@router.get("/occurrences/{occurrence_id}", response_model=s.OccurrenceDetail)
def occurrence_detail(occurrence_id: int, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    row = access.visible_occurrences(db, user).filter(EventOccurrence.id == occurrence_id).one_or_none()
    if row is None:
        raise HTTPException(404, "Occurrence not found")
    o, e, c = row
    payload = occurrence_payloads(db, user, [row])[0]
    resources = [resource_out(r) for r in access.visible_event_resources(db, user, [e.id])]
    organizer = db.get(AppUser, e.organizer_user_id) if e.organizer_user_id else None
    return s.OccurrenceDetail(
        **payload, going=going_summary(db, o.id), resources=resources, description=e.description, venue_address=e.venue_address,
        map_url=e.map_url, can_edit=events.can_edit(db, user, c),
        can_report_absence=events.absence_allowed(db, user, e, c),
        following=db.get(CalendarEventFollow, (e.id, user.id)) is not None,
        my_invitation=db.query(EventInvitation.status).filter_by(event_id=e.id, invitee_user_id=user.id).scalar(),
        organizer_name=organizer.display_name if organizer else None, changes=recent_changes(db, e.id, o.id))


@router.get("/occurrences/{occurrence_id}/export.ics")
def export_occurrence(occurrence_id: int, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.calendar_ics import render

    row = access.visible_occurrences(db, user).filter(EventOccurrence.id == occurrence_id).one_or_none()
    if row is None:
        raise HTTPException(404, "Occurrence not found")
    occurrence, event, _calendar = row
    return Response(render(event, occurrence), media_type="text/calendar", headers={
        "Cache-Control": "private, no-store",
        "Content-Disposition": f'attachment; filename="calendar-{occurrence.id}.ics"',
        "X-Content-Type-Options": "nosniff",
    })


@router.get("/events/{event_id}", response_model=s.EventDetail)
def event_detail(event_id: int, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    row = access.visible_events(db, user).add_entity(Calendar).filter(CalendarEvent.id == event_id).one_or_none()
    if row is None:
        raise HTTPException(404, "Event not found")
    e, c = row
    occ = db.query(EventOccurrence, CalendarEvent, Calendar).join(
        CalendarEvent, CalendarEvent.id == EventOccurrence.event_id).join(
        Calendar, Calendar.id == CalendarEvent.calendar_id).filter(
        EventOccurrence.event_id == e.id).order_by(EventOccurrence.window_start, EventOccurrence.id).limit(MAX_LIMIT).all()
    organizer = db.get(AppUser, e.organizer_user_id) if e.organizer_user_id else None
    invitation = db.query(EventInvitation.status).filter_by(event_id=e.id, invitee_user_id=user.id).scalar()
    return s.EventDetail(
        **event_summary(e, c), description=e.description, venue_name=e.venue_name, venue_address=e.venue_address,
        map_url=e.map_url, recurrence_rule=e.recurrence_rule, organizer_user_id=e.organizer_user_id,
        organizer_name=organizer.display_name if organizer else None, my_invitation=invitation,
        resources=[resource_out(r) for r in access.visible_event_resources(db, user, [e.id])],
        occurrences=occurrence_payloads(db, user, occ),
        following=db.get(CalendarEventFollow, (e.id, user.id)) is not None,
        can_edit=events.can_edit(db, user, c), changes=recent_changes(db, e.id),
        recurrence=recurrence.recurrence_out(db, e), itinerary=recurrence.itinerary_out(db, e.id),
        imported=recurrence.is_imported(db, e.id))


@router.get("/clubs/{club_id}/members", response_model=s.RosterOut)
def club_members(club_id: int, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    own = access.active_membership(db, user, club_id)
    if own is None:
        raise HTTPException(404, "Club not found")
    rows = db.query(ClubMembership, AppUser).join(AppUser, AppUser.id == ClubMembership.user_id).filter(
        ClubMembership.club_id == club_id, ClubMembership.ended_at.is_(None), AppUser.is_active.is_(True)).order_by(
        AppUser.display_name, AppUser.id).limit(500).all()
    staff = access.is_staff(own)
    groups, club_groups = {}, []
    if staff:
        on = access.today()
        groups = {uid: (gid, since) for uid, gid, since in db.query(
            TrainingGroupMembership.user_id, TrainingGroupMembership.group_id,
            TrainingGroupMembership.effective_from).filter(
            TrainingGroupMembership.club_id == club_id,
            TrainingGroupMembership.user_id.in_([u.id for _m, u in rows]),
            TrainingGroupMembership.effective_from <= on,
            or_(TrainingGroupMembership.effective_to.is_(None), TrainingGroupMembership.effective_to > on))
            .order_by(TrainingGroupMembership.id).limit(500).all()}
        club_groups = [group_out(g) for g in db.query(TrainingGroup).filter(
            TrainingGroup.club_id == club_id, TrainingGroup.archived_at.is_(None))
            .order_by(TrainingGroup.name, TrainingGroup.id).limit(500)]

    def entry(m, u):
        base = dict(user_id=u.id, display_name=u.display_name, role=m.role)
        if not staff:
            return s.RosterEntry(**base)
        gid, since = groups.get(u.id, (None, None))
        return s.RosterEntry(**base, group_id=gid, group_since=since, membership_id=m.id,
                             can_publish=bool(m.can_publish), can_assign_groups=bool(m.can_assign_groups),
                             self_declared=m.source == "signup")
    return s.RosterOut(club_id=club_id, my_role=own.role, can_assign_groups=access.can_assign_groups(own),
                       can_manage_members=access.can_manage_members(own), groups=club_groups,
                       items=[entry(m, u) for m, u in rows])


@router.get("/clubs/{club_id}/resources", response_model=list[s.ResourceOut])
def club_resources(club_id: int, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = access.club_resources(db, user, club_id)
    if rows is None:
        raise HTTPException(404, "Club not found")
    return [resource_out(r) for r in rows]


# --- Task05: alert pipeline readiness (app administrators) -------------------------

@router.get("/admin/alerts/health")
def alerts_health(response: Response, admin: AppUser = Depends(require_admin), db: Session = Depends(get_db)):
    """503 until the alerts worker has succeeded recently (missing/stale
    worker); counts only, never event titles or recipients."""
    from app.services import calendar_alerts

    report = calendar_alerts.health(db)
    if not report["ready"]:
        response.status_code = 503
    return report


# --- Administration writes ---------------------------------------------------------

@router.post("/admin/clubs", status_code=201, response_model=s.ClubOut)
def create_club(payload: s.ClubCreate, admin: AppUser = Depends(admin_writer), db: Session = Depends(get_db)):
    club = membership.create_club(db, admin, payload.slug, payload.name, payload.short_name, payload.timezone,
                                  payload.self_join_enabled)
    commit(db)
    return club_out(club)


@router.post("/admin/clubs/{club_id}/memberships", status_code=201, response_model=s.MembershipOut)
def admin_add_membership(club_id: int, payload: s.AdminMembershipCreate, admin: AppUser = Depends(admin_writer),
                         db: Session = Depends(get_db)):
    """Legacy-account association and manager appointment (app admin only)."""
    m = membership.admin_add_membership(db, admin, club_id, payload.user_id, payload.role)
    commit(db)
    return membership_out(m)


@router.patch("/clubs/{club_id}/memberships/{membership_id}", response_model=s.MembershipOut)
def update_membership(club_id: int, membership_id: int, payload: s.MembershipUpdate,
                      user: AppUser = Depends(writer), db: Session = Depends(get_db)):
    m = membership.update_membership(db, user, club_id, membership_id, payload.role, payload.can_publish,
                                     payload.can_assign_groups)
    commit(db)
    return membership_out(m)


@router.post("/clubs/{club_id}/memberships/{membership_id}/end", response_model=s.MembershipOut)
def end_membership(club_id: int, membership_id: int, user: AppUser = Depends(writer), db: Session = Depends(get_db)):
    m = membership.end_membership(db, user, club_id, membership_id)
    commit(db)
    return membership_out(m)


@router.post("/clubs/{club_id}/leave", response_model=s.MembershipOut)
def leave_club(club_id: int, user: AppUser = Depends(writer), db: Session = Depends(get_db)):
    own = access.active_membership(db, user, club_id)
    if own is None:
        raise HTTPException(404, "Club not found")
    m = membership.end_membership(db, user, club_id, own.id)
    commit(db)
    return membership_out(m)


@router.post("/clubs/{club_id}/groups", status_code=201, response_model=s.GroupOut)
def create_group(club_id: int, payload: s.GroupCreate, user: AppUser = Depends(writer), db: Session = Depends(get_db)):
    group = membership.create_group(db, user, club_id, payload.slug, payload.name)
    commit(db)
    return group_out(group)


@router.put("/clubs/{club_id}/group-assignment", response_model=Optional[s.AssignmentOut])
def assign_group(club_id: int, payload: s.GroupAssignment, user: AppUser = Depends(writer),
                 db: Session = Depends(get_db)):
    row = membership.assign_group(db, user, club_id, payload.user_id, payload.group_id, payload.effective_from)
    commit(db)
    if row is None:
        return None
    return s.AssignmentOut(id=row.id, club_id=row.club_id, group_id=row.group_id, user_id=row.user_id,
                           effective_from=row.effective_from, effective_to=row.effective_to)


# --- Task03: events and occurrences --------------------------------------------------

def event_detail_out(db: Session, user: AppUser, event_id: int) -> s.EventDetail:
    return event_detail(event_id, user, db)


@router.post("/events", status_code=201, response_model=s.EventDetail)
def create_event(payload: s.EventCreate, response: Response, user: AppUser = Depends(writer),
                 db: Session = Depends(get_db),
                 idempotency_key: Optional[str] = Header(None, max_length=80)):
    """Create a single-date event. Retrying with the same Idempotency-Key
    returns the original event (200) instead of a duplicate."""
    try:
        event, replayed = events.create_event(db, user, payload, idempotency_key)
        db.commit()
    except IntegrityError:
        db.rollback()  # a concurrent retry with the same key won the race
        digest = events.request_hash(payload.model_dump(mode="json"))
        event, replayed = events.replay(db, user, idempotency_key, digest), True
        if event is None:
            raise HTTPException(409, detail={"code": "conflict", "message": "Conflicting concurrent change"})
    if replayed:
        response.status_code = 200
    return event_detail_out(db, user, event.id)


@router.patch("/events/{event_id}", response_model=s.EventDetail)
def update_event(event_id: int, payload: s.EventUpdate, user: AppUser = Depends(writer),
                 db: Session = Depends(get_db)):
    events.update_event(db, user, event_id, payload)
    commit(db)
    return event_detail_out(db, user, event_id)


@router.post("/events/{event_id}/cancel", response_model=s.EventDetail)
def cancel_event(event_id: int, payload: s.VersionedAction, user: AppUser = Depends(writer),
                 db: Session = Depends(get_db)):
    events.cancel_event(db, user, event_id, payload.expected_version)
    commit(db)
    return event_detail_out(db, user, event_id)


@router.patch("/occurrences/{occurrence_id}", response_model=s.OccurrenceDetail)
def update_occurrence(occurrence_id: int, payload: s.OccurrenceUpdate, user: AppUser = Depends(writer),
                      db: Session = Depends(get_db)):
    events.update_occurrence(db, user, occurrence_id, payload)
    commit(db)
    return occurrence_detail(occurrence_id, user, db)


@router.post("/occurrences/{occurrence_id}/cancel", response_model=s.OccurrenceDetail)
def cancel_occurrence(occurrence_id: int, payload: s.VersionedAction, user: AppUser = Depends(writer),
                      db: Session = Depends(get_db)):
    events.cancel_occurrence(db, user, occurrence_id, payload.expected_version)
    commit(db)
    return occurrence_detail(occurrence_id, user, db)


# --- Task04: scoped schedule edits (preview -> apply) -------------------------------

@router.post("/events/{event_id}/schedule/preview", response_model=s.SchedulePreviewOut)
def preview_schedule(event_id: int, payload: s.ScheduleEdit, user: AppUser = Depends(writer),
                     db: Session = Depends(get_db)):
    """Read-only: the dates that would be created, moved or cancelled and the
    responses on them. Writer-guarded (Origin) because it is an edit step."""
    out = recurrence.preview(db, user, event_id, payload)
    db.rollback()
    return out


@router.post("/events/{event_id}/schedule/apply", response_model=s.SchedulePreviewOut)
def apply_schedule(event_id: int, payload: s.ScheduleApply, user: AppUser = Depends(writer),
                   db: Session = Depends(get_db)):
    out = recurrence.apply(db, user, event_id, payload, payload.plan_hash)
    commit(db)
    return {**out, "plan_hash": payload.plan_hash}


# --- Task03: invitations (existing accounts only) -------------------------------------

def invitations_out(db: Session, event_id: int) -> s.InvitationsOut:
    rows = db.query(EventInvitation, AppUser).join(AppUser, AppUser.id == EventInvitation.invitee_user_id).filter(
        EventInvitation.event_id == event_id).order_by(AppUser.display_name, AppUser.id).limit(500).all()
    return s.InvitationsOut(items=[s.InvitationOut(user_id=u.id, display_name=u.display_name, status=i.status,
                                                   responded_at=iso(i.responded_at)) for i, u in rows])


@router.get("/events/{event_id}/invitations", response_model=s.InvitationsOut)
def list_invitations(event_id: int, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """Organizer/publisher view only; invitees never see the guest list."""
    _e, c = events.visible_event(db, user, event_id)
    if not events.can_edit(db, user, c):
        raise HTTPException(403, detail={"code": "forbidden", "message": "Organizer access required"})
    return invitations_out(db, event_id)


@router.post("/events/{event_id}/invitations", response_model=s.InvitationsOut)
def create_invitations(event_id: int, payload: s.InvitationsCreate, user: AppUser = Depends(writer),
                       db: Session = Depends(get_db)):
    """Idempotent: re-inviting an invited user changes nothing."""
    events.invite(db, user, event_id, payload.user_ids)
    commit(db)
    return invitations_out(db, event_id)


@router.post("/events/{event_id}/invitations/{invitee_id}/revoke", response_model=s.InvitationsOut)
def revoke_invitation(event_id: int, invitee_id: int, user: AppUser = Depends(writer),
                      db: Session = Depends(get_db)):
    events.revoke_invitation(db, user, event_id, invitee_id)
    commit(db)
    return invitations_out(db, event_id)


@router.put("/events/{event_id}/invitation", response_model=s.EventDetail)
def respond_invitation(event_id: int, payload: s.InvitationResponse, user: AppUser = Depends(writer),
                       db: Session = Depends(get_db)):
    events.respond_invitation(db, user, event_id, payload.status)
    commit(db)
    return event_detail_out(db, user, event_id)


# --- Task03: interest, absence, following ------------------------------------------------

@router.put("/occurrences/{occurrence_id}/interest", response_model=s.OccurrenceDetail)
def set_interest(occurrence_id: int, payload: s.InterestWrite, user: AppUser = Depends(writer),
                 db: Session = Depends(get_db)):
    """Interest only: no place, booking or attendance meaning. Idempotent."""
    events.set_interest(db, user, occurrence_id, payload.state)
    commit(db)
    return occurrence_detail(occurrence_id, user, db)


@router.put("/occurrences/{occurrence_id}/absence", response_model=s.OccurrenceDetail)
def set_absence(occurrence_id: int, payload: s.AbsenceWrite, user: AppUser = Depends(writer),
                db: Session = Depends(get_db)):
    events.set_absence(db, user, occurrence_id, payload.absent)
    commit(db)
    return occurrence_detail(occurrence_id, user, db)


@router.put("/calendars/{calendar_id}/follow", status_code=204)
def follow_calendar(calendar_id: int, user: AppUser = Depends(writer), db: Session = Depends(get_db)):
    events.follow_calendar(db, user, calendar_id, True)
    commit(db)


@router.delete("/calendars/{calendar_id}/follow", status_code=204)
def unfollow_calendar(calendar_id: int, user: AppUser = Depends(writer), db: Session = Depends(get_db)):
    events.follow_calendar(db, user, calendar_id, False)
    commit(db)


@router.put("/events/{event_id}/follow", status_code=204)
def follow_event(event_id: int, user: AppUser = Depends(writer), db: Session = Depends(get_db)):
    events.follow_event(db, user, event_id, True)
    commit(db)


@router.delete("/events/{event_id}/follow", status_code=204)
def unfollow_event(event_id: int, user: AppUser = Depends(writer), db: Session = Depends(get_db)):
    events.follow_event(db, user, event_id, False)
    commit(db)


# --- Task03: explicit dive links (caller's own dives only) ---------------------------------

@router.get("/occurrences/{occurrence_id}/dives", response_model=s.LinkedDivesOut)
def occurrence_dives(occurrence_id: int, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """The caller's own dives on this date and whether each is linked. Links
    are private to the caller and never change dive/media visibility."""
    o, e, _c = events.visible_occurrence(db, user, occurrence_id)
    linked = {did for (did,) in db.query(OccurrenceDiveLink.dive_id).filter(
        OccurrenceDiveLink.occurrence_id == o.id, OccurrenceDiveLink.user_id == user.id)}
    rows = events.linkable_dives_query(db, user, o, e).order_by(Dive.dive_datetime, Dive.id).limit(MAX_LIMIT).all()
    posters = {}
    asset_ids = {d.photos_asset_id for d in rows if d.photos_asset_id}
    if asset_ids:
        for p in db.query(MediaCacheEntry).filter(MediaCacheEntry.photos_asset_id.in_(asset_ids),
                                                  MediaCacheEntry.rendition == "poster", MediaCacheEntry.status == "ready"):
            posters[p.photos_asset_id] = playback_url(p)
    return s.LinkedDivesOut(items=[s.LinkedDiveOut(
        id=d.id, dive_code=d.dive_code, dive_datetime=d.dive_datetime.isoformat(), linked=d.id in linked,
        height=d.height, performance=d.performance, phase1_performance=d.phase1_performance,
        phase2_performance=d.phase2_performance, poster_url=posters.get(d.photos_asset_id)) for d in rows])


@router.put("/occurrences/{occurrence_id}/dives/{dive_id}", response_model=s.LinkedDivesOut)
def link_dive(occurrence_id: int, dive_id: int, user: AppUser = Depends(writer), db: Session = Depends(get_db)):
    events.link_dive(db, user, occurrence_id, dive_id, True)
    commit(db)
    return occurrence_dives(occurrence_id, user, db)


@router.delete("/occurrences/{occurrence_id}/dives/{dive_id}", response_model=s.LinkedDivesOut)
def unlink_dive(occurrence_id: int, dive_id: int, user: AppUser = Depends(writer), db: Session = Depends(get_db)):
    events.link_dive(db, user, occurrence_id, dive_id, False)
    commit(db)
    return occurrence_dives(occurrence_id, user, db)
