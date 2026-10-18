"""Calendar authorization contract (Task02). Reused by Task03 writes.

Every rule reads server-side rows only; a client-supplied role or group is
never trusted. Read filtering is a SQL expression applied before ORDER BY /
LIMIT, so pagination, counts and direct-ID lookups share one policy and an
inaccessible id is indistinguishable from a missing one (404).

Grants (independent, none implies another):
- club membership (active row)          -> club-audience events, club resources
- staff role (coach/manager, per club)  -> both group calendars of THAT club
- current group assignment              -> that group's calendar only
- invitation (not revoked)              -> that invited-audience event only
- organizer                             -> own event (club events: while a member)
- subscription                          -> nothing (display preference)
App administrators manage clubs and appoint managers; ``is_admin`` never
grants club publishing, staff powers or private event/roster reads.
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import and_, exists, false, or_
from sqlalchemy.orm import Session

from app.models.calendar import (
    Calendar, CalendarEvent, ClubMembership, EventInvitation, EventOccurrence,
    EventResource, TrainingGroupMembership,
)
from app.models.user_auth import AppUser

MAX_RESOURCE_RESULTS = 200
STAFF_ROLES = ("coach", "manager")
# Task03: a declined invitee keeps read access (they may change their mind);
# only revocation, or leaving the club, removes the grant.
ACTIVE_INVITATION = ("pending", "accepted", "declined")
VISIBLE_EVENT_STATUSES = ("published", "cancelled")  # cancellation is retained history

# Which audiences each calendar kind may publish (write contract for Task03).
ALLOWED_AUDIENCES = {
    "club": ("club", "community", "invited"),
    "group": ("group", "invited"),
    "personal": ("invited", "community"),
    "federal": ("community",),
}


def today() -> date:
    return datetime.utcnow().date()


def _usable(user: Optional[AppUser]) -> bool:
    return user is not None and bool(user.is_active)


# --- Row-level membership helpers ----------------------------------------

def active_membership(db: Session, user: Optional[AppUser], club_id: int) -> Optional[ClubMembership]:
    if not _usable(user):
        return None
    return db.query(ClubMembership).filter(
        ClubMembership.club_id == club_id, ClubMembership.user_id == user.id,
        ClubMembership.ended_at.is_(None)).one_or_none()


def is_staff(m: Optional[ClubMembership]) -> bool:
    return m is not None and m.role in STAFF_ROLES


def can_publish(m: Optional[ClubMembership]) -> bool:
    """Club managers, and coaches a manager authorized, publish club calendars."""
    return m is not None and (m.role == "manager" or (m.role == "coach" and bool(m.can_publish)))


def can_assign_groups(m: Optional[ClubMembership]) -> bool:
    return m is not None and (m.role == "manager" or (m.role == "coach" and bool(m.can_assign_groups)))


def can_manage_members(m: Optional[ClubMembership]) -> bool:
    return m is not None and m.role == "manager"


def can_publish_to_calendar(db: Session, user: Optional[AppUser], calendar: Calendar) -> bool:
    """Write-side contract for Task03 event create/edit/cancel."""
    if not _usable(user) or calendar is None or calendar.archived_at is not None:
        return False
    if calendar.kind in ("club", "group"):
        return can_publish(active_membership(db, user, calendar.club_id))
    if calendar.kind == "personal":
        return calendar.owner_user_id == user.id
    return bool(user.is_admin)  # federal dates are curated by app administrators


def current_group_assignment(db: Session, user_id: int, club_id: int, on: Optional[date] = None):
    on = on or today()
    return db.query(TrainingGroupMembership).join(
        ClubMembership, ClubMembership.id == TrainingGroupMembership.club_membership_id).filter(
        TrainingGroupMembership.club_id == club_id, TrainingGroupMembership.user_id == user_id,
        TrainingGroupMembership.effective_from <= on,
        or_(TrainingGroupMembership.effective_to.is_(None), TrainingGroupMembership.effective_to > on),
        ClubMembership.ended_at.is_(None)).one_or_none()


# --- SQL policy expressions (correlated to Calendar / CalendarEvent) ------

def _member_of_calendar_club(uid: int, roles=None):
    clause = and_(ClubMembership.club_id == Calendar.club_id, ClubMembership.user_id == uid,
                  ClubMembership.ended_at.is_(None))
    if roles:
        clause = and_(clause, ClubMembership.role.in_(roles))
    return exists().where(clause)


def _publisher_of_calendar_club(uid: int):
    return exists().where(and_(
        ClubMembership.club_id == Calendar.club_id, ClubMembership.user_id == uid,
        ClubMembership.ended_at.is_(None),
        or_(ClubMembership.role == "manager", and_(ClubMembership.role == "coach", ClubMembership.can_publish.is_(True)))))


def _assigned_to_calendar_group(uid: int, on: date):
    return exists().where(and_(
        TrainingGroupMembership.group_id == Calendar.training_group_id,
        TrainingGroupMembership.user_id == uid,
        TrainingGroupMembership.effective_from <= on,
        or_(TrainingGroupMembership.effective_to.is_(None), TrainingGroupMembership.effective_to > on),
        ClubMembership.id == TrainingGroupMembership.club_membership_id,
        ClubMembership.ended_at.is_(None)))


def calendar_visible_clause(user: Optional[AppUser], on: Optional[date] = None):
    """Calendars a user may list: own club, permitted group, own personal, federal."""
    if not _usable(user):
        return false()
    on, uid = on or today(), user.id
    return and_(Calendar.archived_at.is_(None), or_(
        and_(Calendar.kind == "club", _member_of_calendar_club(uid)),
        and_(Calendar.kind == "group", or_(_member_of_calendar_club(uid, STAFF_ROLES),
                                           _assigned_to_calendar_group(uid, on))),
        and_(Calendar.kind == "personal", Calendar.owner_user_id == uid),
        Calendar.kind == "federal"))


def event_visible_clause(user: Optional[AppUser], on: Optional[date] = None):
    """The single read policy for events, occurrences and their resources.

    Requires CalendarEvent joined to Calendar in the enclosing query.
    """
    if not _usable(user):
        return false()
    on, uid = on or today(), user.id
    in_club_or_clubless = or_(Calendar.club_id.is_(None), _member_of_calendar_club(uid))
    organizer = and_(CalendarEvent.organizer_user_id == uid, in_club_or_clubless)
    invited = exists().where(and_(
        EventInvitation.event_id == CalendarEvent.id, EventInvitation.invitee_user_id == uid,
        EventInvitation.status.in_(ACTIVE_INVITATION)))
    audience = or_(
        CalendarEvent.audience == "community",
        and_(CalendarEvent.audience == "club", _member_of_calendar_club(uid)),
        and_(CalendarEvent.audience == "group", Calendar.training_group_id.isnot(None),
             or_(_member_of_calendar_club(uid, STAFF_ROLES), _assigned_to_calendar_group(uid, on))),
        and_(CalendarEvent.audience == "invited", invited))
    draft_editor = or_(_publisher_of_calendar_club(uid), Calendar.owner_user_id == uid)
    return or_(
        organizer,
        and_(CalendarEvent.status.in_(VISIBLE_EVENT_STATUSES), audience),
        and_(CalendarEvent.status == "draft", draft_editor))


def resource_visible_clause(user: Optional[AppUser]):
    """Extra filter for event resources (event visibility applied separately):
    club-restricted links (e.g. a chat invitation) need club membership even
    when the event itself is shared with the app community."""
    if not _usable(user):
        return false()
    return or_(EventResource.restricted_to_club.is_(False),
               and_(Calendar.club_id.isnot(None), _member_of_calendar_club(user.id)))


# --- Query builders --------------------------------------------------------

def visible_events(db: Session, user: AppUser, on: Optional[date] = None):
    return db.query(CalendarEvent).join(Calendar, Calendar.id == CalendarEvent.calendar_id).filter(
        event_visible_clause(user, on))


def visible_occurrences(db: Session, user: AppUser, on: Optional[date] = None):
    return db.query(EventOccurrence, CalendarEvent, Calendar).join(
        CalendarEvent, CalendarEvent.id == EventOccurrence.event_id).join(
        Calendar, Calendar.id == CalendarEvent.calendar_id).filter(event_visible_clause(user, on))


def visible_calendars(db: Session, user: AppUser, on: Optional[date] = None):
    return db.query(Calendar).filter(calendar_visible_clause(user, on))


def visible_event_resources(db: Session, user: AppUser, event_ids):
    if not event_ids:
        return []
    return db.query(EventResource).join(CalendarEvent, CalendarEvent.id == EventResource.event_id).join(
        Calendar, Calendar.id == CalendarEvent.calendar_id).filter(
        EventResource.event_id.in_(list(event_ids)), event_visible_clause(user),
        resource_visible_clause(user)).order_by(EventResource.id).limit(MAX_RESOURCE_RESULTS).all()


def club_resources(db: Session, user: AppUser, club_id: int):
    """Club-wide resources: active members only."""
    if active_membership(db, user, club_id) is None:
        return None
    return db.query(EventResource).filter(EventResource.club_id == club_id).order_by(EventResource.id).limit(MAX_RESOURCE_RESULTS).all()
