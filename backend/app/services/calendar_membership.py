"""Club / membership / training-group writes (Task02 administration).

Callers commit; functions only flush, so signup can create the account and
its membership in one transaction. Errors are HTTPException with a stable
``code`` so the API stays a thin layer.
"""
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.calendar import (
    Calendar, CalendarEvent, Club, ClubMembership, EventInvitation, TrainingGroup,
    TrainingGroupMembership,
)
from app.models.user_auth import AppUser
from app.services import calendar_access as access


def fail(status: int, code: str, message: str):
    raise HTTPException(status, detail={"code": code, "message": message})


def valid_timezone(name: str) -> str:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        fail(422, "invalid_timezone", "Unknown IANA timezone")
    return name


def _usable_club(db: Session, club_id: int) -> Club:
    # Serialize club administration, even when there is no assignment row.
    club = db.query(Club).filter(Club.id == club_id).with_for_update().one_or_none()
    if club is None or club.archived_at is not None:
        fail(404, "club_not_found", "Club not found")
    return club


def _active_target(db: Session, user_id: int) -> AppUser:
    user = db.get(AppUser, user_id)
    if user is None or not user.is_active:
        fail(422, "user_unavailable", "User is missing or deactivated")
    return user


def _membership_in_club(db: Session, club_id: int, membership_id: int, lock: bool = False) -> ClubMembership:
    query = db.query(ClubMembership).filter(
        ClubMembership.id == membership_id, ClubMembership.club_id == club_id, ClubMembership.ended_at.is_(None))
    row = (query.with_for_update() if lock else query).one_or_none()
    if row is None:
        fail(404, "membership_not_found", "Membership not found")
    return row


def _manager_count(db: Session, club_id: int) -> int:
    return db.query(ClubMembership).filter(
        ClubMembership.club_id == club_id, ClubMembership.role == "manager",
        ClubMembership.ended_at.is_(None)).count()


def _club_actor(db: Session, actor: AppUser, club_id: int, allow_admin: bool) -> Optional[ClubMembership]:
    """Manager of THIS club, or (where allowed) an app administrator.
    Non-members get the same 404 as a missing club (no oracle)."""
    _usable_club(db, club_id)
    m = access.active_membership(db, actor, club_id)
    if access.can_manage_members(m) or (allow_admin and actor.is_admin):
        return m
    if m is None and not actor.is_admin:
        fail(404, "club_not_found", "Club not found")
    fail(403, "forbidden", "Club manager access required")


# --- Clubs -----------------------------------------------------------------

def create_club(db: Session, admin: AppUser, slug: str, name: str, short_name: Optional[str],
                timezone: str, self_join_enabled: bool) -> Club:
    if db.query(Club).filter(Club.slug == slug).one_or_none() is not None:
        fail(409, "club_exists", "A club with this slug already exists")
    club = Club(slug=slug, name=name, short_name=short_name, timezone=valid_timezone(timezone),
                self_join_enabled=self_join_enabled, created_by_user_id=admin.id)
    db.add(club)
    db.flush()
    db.add(Calendar(kind="club", club_id=club.id, name=name))
    db.flush()
    return club


def create_group(db: Session, actor: AppUser, club_id: int, slug: str, name: str) -> TrainingGroup:
    _club_actor(db, actor, club_id, allow_admin=True)
    if db.query(TrainingGroup).filter_by(club_id=club_id, slug=slug).one_or_none() is not None:
        fail(409, "group_exists", "A group with this slug already exists")
    if db.query(TrainingGroup.id).filter(
            TrainingGroup.club_id == club_id, TrainingGroup.archived_at.is_(None)).limit(500).count() >= 500:
        fail(422, "too_many_groups", "A club can have at most 500 active training groups")
    group = TrainingGroup(club_id=club_id, slug=slug, name=name)
    db.add(group)
    db.flush()
    db.add(Calendar(kind="group", club_id=club_id, training_group_id=group.id, name=name))
    db.flush()
    return group


# --- Memberships -------------------------------------------------------------

def signup_club(db: Session, club_id: int) -> Club:
    """Validate a signup club choice BEFORE any account/invite is consumed."""
    club = db.get(Club, club_id)
    if club is None or club.archived_at is not None or not club.self_join_enabled:
        fail(422, "club_unavailable", "This club is not open for selection")
    return club


def add_signup_membership(db: Session, user: AppUser, club: Club) -> ClubMembership:
    """Self-declared affiliation: plain active member, no role, no group."""
    m = ClubMembership(club_id=club.id, user_id=user.id, role="member", source="signup",
                       created_by_user_id=user.id)
    db.add(m)
    db.flush()
    return m


def admin_add_membership(db: Session, admin: AppUser, club_id: int, user_id: int, role: str) -> ClubMembership:
    """Legacy-account association / manager appointment. App admins only."""
    _usable_club(db, club_id)
    target = _active_target(db, user_id)
    if access.active_membership(db, target, club_id) is not None:
        fail(409, "already_member", "User already has an active membership in this club")
    m = ClubMembership(club_id=club_id, user_id=target.id, role=role, source="admin_legacy",
                       created_by_user_id=admin.id)
    db.add(m)
    db.flush()
    return m


def update_membership(db: Session, actor: AppUser, club_id: int, membership_id: int, role: Optional[str],
                      can_publish: Optional[bool], can_assign_groups: Optional[bool]) -> ClubMembership:
    """Managers set member/coach roles and coach grants; only an app
    administrator appoints or demotes a manager (never self-elevation)."""
    own = _club_actor(db, actor, club_id, allow_admin=True)
    m = _membership_in_club(db, club_id, membership_id, lock=True)
    _active_target(db, m.user_id)
    if m.role == "manager" or role == "manager":
        if not actor.is_admin:
            fail(403, "forbidden", "Only an app administrator appoints or changes managers")
    elif not access.can_manage_members(own):
        fail(403, "forbidden", "Roles and coach grants belong to the club manager")
    if m.role == "manager" and role not in (None, "manager") and _manager_count(db, club_id) <= 1:
        fail(409, "last_manager", "Appoint another manager first")
    if role is not None:
        m.role = role
    if m.role == "member":
        m.can_publish = m.can_assign_groups = False
    else:
        if can_publish is not None:
            m.can_publish = can_publish
        if can_assign_groups is not None:
            m.can_assign_groups = can_assign_groups
    db.flush()
    return m


def _close_open_assignment(db: Session, m: ClubMembership, actor: AppUser, on: date) -> None:
    row = db.query(TrainingGroupMembership).filter(
        TrainingGroupMembership.club_membership_id == m.id,
        TrainingGroupMembership.effective_to.is_(None)).with_for_update().one_or_none()
    if row is not None:
        row.effective_to = max(on, row.effective_from + timedelta(days=1))
        row.ended_by_user_id = actor.id


def end_membership(db: Session, actor: AppUser, club_id: int, membership_id: int) -> ClubMembership:
    """Leave (self) or removal (manager/admin). History is kept; access ends
    because every policy requires an ACTIVE membership. Invited-only club
    events also lose their invitation grant."""
    _usable_club(db, club_id)  # club lock before membership lock
    m = _membership_in_club(db, club_id, membership_id, lock=True)
    leaving = m.user_id == actor.id
    if not leaving:
        _club_actor(db, actor, club_id, allow_admin=True)
        if m.role == "manager" and not actor.is_admin:
            fail(403, "forbidden", "Only an app administrator removes a manager")
    if m.role == "manager" and _manager_count(db, club_id) <= 1:
        fail(409, "last_manager", "Appoint another manager first")
    now = datetime.utcnow()
    m.status, m.ended_at, m.ended_by_user_id = ("left" if leaving else "removed"), now, actor.id
    _close_open_assignment(db, m, actor, now.date())
    club_event_ids = db.query(CalendarEvent.id).join(Calendar, Calendar.id == CalendarEvent.calendar_id).filter(
        Calendar.club_id == club_id, CalendarEvent.audience == "invited")
    db.query(EventInvitation).filter(
        EventInvitation.invitee_user_id == m.user_id, EventInvitation.event_id.in_(club_event_ids.scalar_subquery()),
        EventInvitation.status.in_(access.ACTIVE_INVITATION)).update(
        {"status": "revoked", "revoked_at": now}, synchronize_session=False)
    db.flush()
    return m


# --- Training groups -----------------------------------------------------------

def assign_group(db: Session, actor: AppUser, club_id: int, user_id: int, group_id: Optional[int],
                 effective_from: Optional[date]) -> Optional[TrainingGroupMembership]:
    """Effective-dated assignment/transfer by a manager or authorized coach.

    The previous open row ends exactly where the new one starts (history is
    preserved, never overwritten). group_id=None ends the assignment.
    """
    _usable_club(db, club_id)
    own = access.active_membership(db, actor, club_id)
    if not access.can_assign_groups(own):
        if own is None:
            fail(404, "club_not_found", "Club not found")
        fail(403, "forbidden", "Group assignment requires a manager or authorized coach")
    target = _active_target(db, user_id)
    m = access.active_membership(db, target, club_id)
    if m is None:
        fail(422, "not_member", "User is not an active member of this club")
    if group_id is not None:
        group = db.get(TrainingGroup, group_id)
        if group is None or group.club_id != club_id or group.archived_at is not None:
            fail(422, "invalid_group", "Group does not belong to this club")
    start = effective_from or access.today()
    current = db.query(TrainingGroupMembership).filter(
        TrainingGroupMembership.club_membership_id == m.id,
        TrainingGroupMembership.effective_to.is_(None)).with_for_update().one_or_none()
    if current is not None:
        if current.group_id == group_id:
            return current
        if start <= current.effective_from:
            fail(422, "invalid_effective_date", "Transfer must start after the current assignment began")
        current.effective_to, current.ended_by_user_id = start, actor.id
        db.flush()
    if group_id is None:
        db.flush()
        return None
    # A new open period cannot overlap saved history after an unassignment.
    overlap = db.query(TrainingGroupMembership.id).filter(
        TrainingGroupMembership.club_id == club_id,
        TrainingGroupMembership.user_id == target.id,
        or_(TrainingGroupMembership.effective_to.is_(None),
            TrainingGroupMembership.effective_to > start)).first()
    if overlap is not None:
        fail(422, "invalid_effective_date", "Assignment overlaps an existing group period")
    row = TrainingGroupMembership(club_id=club_id, group_id=group_id, club_membership_id=m.id, user_id=target.id,
                                  effective_from=start, assigned_by_user_id=actor.id)
    db.add(row)
    db.flush()
    return row
