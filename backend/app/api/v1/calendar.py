"""Calendar read API + minimal club administration (Task02, default-off).

CALENDAR_ENABLED=false -> every route 404s; signup never touches calendar tables.
Enabled without the SQL migration -> 503, never a half-created schema.
The public signup club list lives at /auth/signup-clubs (pre-session).
Reads apply calendar_access policies in SQL before pagination; a private id
answers exactly like a missing one. Event/response writes arrive in Task03.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, inspect, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.admin_users import require_admin
from app.api.v1.auth import _origin_allowed, get_current_user
from app.config import get_settings
from app.database import get_db
from app.models.calendar import (
    Calendar, CalendarEvent, CalendarSubscription, Club, ClubMembership, EventInvitation, EventOccurrence,
    OccurrenceAbsenceReport, OccurrenceInterest, TrainingGroup, TrainingGroupMembership,
)
from app.models.user_auth import AppUser
from app.schemas import calendar as s
from app.services import calendar_access as access
from app.services import calendar_membership as membership

MAX_WINDOW_DAYS = 100
MAX_LIMIT = 200
_schema_ready = False


def calendar_gate(db: Session = Depends(get_db)) -> None:
    global _schema_ready
    if not get_settings().calendar_enabled:
        raise HTTPException(404, "Not found")
    if not _schema_ready:
        if not inspect(db.get_bind()).has_table("calendar_change_log"):
            raise HTTPException(503, "Calendar schema not installed")
        _schema_ready = True


router = APIRouter(prefix="/calendar", dependencies=[Depends(calendar_gate)])


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
                audience=e.audience, status=e.status, title=e.title, timezone=e.timezone, version=e.version)


def occurrence_payloads(db: Session, user: AppUser, rows) -> list:
    ids = [o.id for o, _e, _c in rows]
    interest, absent = {}, set()
    if ids:
        interest = dict(db.query(OccurrenceInterest.occurrence_id, OccurrenceInterest.state).filter(
            OccurrenceInterest.user_id == user.id, OccurrenceInterest.occurrence_id.in_(ids)).all())
        absent = {oid for (oid,) in db.query(OccurrenceAbsenceReport.occurrence_id).filter(
            OccurrenceAbsenceReport.user_id == user.id, OccurrenceAbsenceReport.withdrawn_at.is_(None),
            OccurrenceAbsenceReport.occurrence_id.in_(ids))}
    return [dict(id=o.id, occurrence_key=o.occurrence_key, status=o.status, is_all_day=bool(o.is_all_day),
                 starts_at=iso(o.starts_at), ends_at=iso(o.ends_at), start_date=o.start_date, end_date=o.end_date,
                 venue_name=o.venue_name or e.venue_name, is_filmed_session=o.filmed_session_id is not None,
                 version=o.version, event=event_summary(e, c), my_interest=interest.get(o.id),
                 my_absence_reported=o.id in absent) for o, e, c in rows]


# --- Authenticated reads -------------------------------------------------------

@router.get("/me", response_model=s.MeOut)
def me(user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(ClubMembership, Club).join(Club, Club.id == ClubMembership.club_id).filter(
        ClubMembership.user_id == user.id, ClubMembership.ended_at.is_(None), Club.archived_at.is_(None)).all()
    clubs = []
    for m, c in rows:
        assignment = access.current_group_assignment(db, user.id, c.id)
        group = db.get(TrainingGroup, assignment.group_id) if assignment else None
        clubs.append(s.MyClubOut(club=club_out(c), membership=membership_out(m),
                                 group=group_out(group) if group else None, self_declared=m.source == "signup"))
    return s.MeOut(clubs=clubs)


@router.get("/calendars", response_model=s.CalendarsOut)
def calendars(user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = access.visible_calendars(db, user).order_by(Calendar.kind, Calendar.id).limit(MAX_LIMIT).all()
    following = {cid for (cid,) in db.query(CalendarSubscription.calendar_id).filter(
        CalendarSubscription.user_id == user.id)}
    return s.CalendarsOut(items=[s.CalendarOut(id=c.id, kind=c.kind, name=c.name, club_id=c.club_id,
                                               training_group_id=c.training_group_id, following=c.id in following)
                                 for c in rows])


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
    _o, e, _c = row
    payload = occurrence_payloads(db, user, [row])[0]
    resources = [resource_out(r) for r in access.visible_event_resources(db, user, [e.id])]
    return s.OccurrenceDetail(**payload, resources=resources, description=e.description,
                              venue_address=e.venue_address)


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
        occurrences=occurrence_payloads(db, user, occ))


@router.get("/clubs/{club_id}/members", response_model=s.RosterOut)
def club_members(club_id: int, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    own = access.active_membership(db, user, club_id)
    if own is None:
        raise HTTPException(404, "Club not found")
    rows = db.query(ClubMembership, AppUser).join(AppUser, AppUser.id == ClubMembership.user_id).filter(
        ClubMembership.club_id == club_id, ClubMembership.ended_at.is_(None), AppUser.is_active.is_(True)).order_by(
        AppUser.display_name, AppUser.id).limit(500).all()
    groups = {}
    if access.is_staff(own):
        on = access.today()
        groups = dict(db.query(TrainingGroupMembership.user_id, TrainingGroupMembership.group_id).filter(
            TrainingGroupMembership.club_id == club_id, TrainingGroupMembership.effective_from <= on,
            or_(TrainingGroupMembership.effective_to.is_(None), TrainingGroupMembership.effective_to > on)).all())
    return s.RosterOut(club_id=club_id, items=[
        s.RosterEntry(user_id=u.id, display_name=u.display_name, role=m.role, group_id=groups.get(u.id))
        for m, u in rows])


@router.get("/clubs/{club_id}/resources", response_model=list[s.ResourceOut])
def club_resources(club_id: int, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = access.club_resources(db, user, club_id)
    if rows is None:
        raise HTTPException(404, "Club not found")
    return [resource_out(r) for r in rows]


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
