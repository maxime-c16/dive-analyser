"""Club open-training windows before competitions.

Allows a club manager or authorized publisher coach to open all group training
sessions of their club during a local-date window (default: the competition
week + the preceding week = 2 calendar training weeks) to members of a given
training group (e.g. Confirmés).

Access is opt-in: members of the eligible group see other groups' sessions in
that window and may click "Je viens" (OccurrenceInterest(state='interested'))
without becoming default-expected or able to report absence on them.
"""
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import and_, exists, func, or_
from sqlalchemy.orm import Session

from app.models.calendar import (
    Calendar, CalendarEvent, Club, ClubMembership, ClubTrainingOpening, EventOccurrence,
    TrainingGroup, TrainingGroupMembership,
)
from app.models.user_auth import AppUser
from app.services import calendar_access as access
from app.services.calendar_membership import _usable_club, fail

MAX_OPENING_DAYS = 60
MAX_OPENINGS_PER_CLUB = 100


def default_opening_window(competition_start: date) -> Tuple[date, date]:
    """Two calendar weeks of training before competition_start (inclusive).

    - Tue..Sun competition: Monday of the previous week through the day before
      (competition week + preceding week = 2 training weeks).
    - Mon competition: two full calendar weeks ending the Sunday before.
    """
    if competition_start.weekday() == 0:
        starts_on = competition_start - timedelta(days=14)
    else:
        starts_on = competition_start - timedelta(days=competition_start.weekday() + 7)
    return starts_on, competition_start - timedelta(days=1)


def utc_bounds_for_local_dates(starts_on: date, ends_on: date, tz_name: str) -> Tuple[datetime, datetime]:
    """Inclusive local dates -> naive UTC half-open [window_start, window_end)."""
    if ends_on < starts_on:
        fail(422, "invalid_dates", "End date must be on or after start date")
    if (ends_on - starts_on).days > MAX_OPENING_DAYS:
        fail(422, "invalid_dates", f"An opening window can span at most {MAX_OPENING_DAYS + 1} days")
    tz = ZoneInfo(tz_name)
    start_utc = datetime.combine(starts_on, time()).replace(tzinfo=tz, fold=0).astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = datetime.combine(ends_on + timedelta(days=1), time()).replace(tzinfo=tz, fold=0).astimezone(timezone.utc).replace(tzinfo=None)
    if end_utc <= start_utc:
        fail(422, "invalid_dates", "Invalid date window")
    return start_utc, end_utc


def _occurrence_local_date(occ: EventOccurrence, tz_name: str) -> date:
    if occ.is_all_day and occ.start_date is not None:
        return occ.start_date
    return occ.window_start.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz_name)).date()


def competition_start_date(db: Session, event: CalendarEvent) -> Optional[date]:
    occ = db.query(EventOccurrence).filter(
        EventOccurrence.event_id == event.id,
        EventOccurrence.status == "scheduled",
    ).order_by(EventOccurrence.window_start, EventOccurrence.id).first()
    if occ is None:
        return None
    return _occurrence_local_date(occ, event.timezone)


def _club_publisher(db: Session, actor: AppUser, club_id: int) -> Tuple[Club, ClubMembership]:
    club = _usable_club(db, club_id)
    own = access.active_membership(db, actor, club_id)
    if own is None:
        fail(404, "club_not_found", "Club not found")
    if not access.can_publish(own):
        fail(403, "forbidden", "Club publisher access required")
    return club, own


def _serialize_openings(db: Session, rows: List[ClubTrainingOpening]) -> List[dict]:
    if not rows:
        return []
    group_ids = {r.eligible_group_id for r in rows}
    event_ids = {r.competition_event_id for r in rows if r.competition_event_id is not None}
    groups = {g.id: g.name for g in db.query(TrainingGroup).filter(TrainingGroup.id.in_(group_ids))} if group_ids else {}
    events = {e.id: e.title for e in db.query(CalendarEvent).filter(CalendarEvent.id.in_(event_ids))} if event_ids else {}
    return [
        dict(
            id=r.id,
            club_id=r.club_id,
            eligible_group_id=r.eligible_group_id,
            eligible_group_name=groups.get(r.eligible_group_id, ""),
            competition_event_id=r.competition_event_id,
            competition_title=events.get(r.competition_event_id) if r.competition_event_id else None,
            label=r.label,
            starts_on=r.starts_on,
            ends_on=r.ends_on,
        )
        for r in rows
    ]


def list_club_openings(db: Session, user: AppUser, club_id: int) -> dict:
    club = db.query(Club).filter(Club.id == club_id, Club.archived_at.is_(None)).one_or_none()
    own = access.active_membership(db, user, club_id) if club is not None else None
    if club is None or own is None:
        fail(404, "club_not_found", "Club not found")
    rows = db.query(ClubTrainingOpening).filter(
        ClubTrainingOpening.club_id == club_id,
    ).order_by(ClubTrainingOpening.starts_on.desc(), ClubTrainingOpening.id.desc()).limit(MAX_OPENINGS_PER_CLUB).all()
    return dict(club_id=club_id, can_manage=access.can_publish(own), items=_serialize_openings(db, rows))


def _validate_competition_for_club(db: Session, actor: AppUser, club: Club, event_id: int) -> CalendarEvent:
    row = access.visible_events(db, actor).add_entity(Calendar).filter(CalendarEvent.id == event_id).one_or_none()
    if row is None:
        fail(404, "event_not_found", "Competition not found")
    event, cal = row
    if event.event_type != "competition" or event.status != "published":
        fail(422, "invalid_competition", "Only published competition events can open training windows")
    # Ensure every active member of this club can see the linked competition title (no private-event leak).
    club_shared = (
        event.audience == "community"
        or cal.kind == "federal"
        or (cal.club_id == club.id and event.audience == "club")
    )
    if not club_shared:
        fail(422, "invalid_competition", "Competition must be visible to the club")
    return event


def create_opening(
    db: Session,
    actor: AppUser,
    club_id: int,
    eligible_group_id: int,
    competition_event_id: Optional[int],
    label: Optional[str],
    starts_on: Optional[date],
    ends_on: Optional[date],
) -> dict:
    club, _own = _club_publisher(db, actor, club_id)
    group = db.get(TrainingGroup, eligible_group_id)
    if group is None or group.club_id != club_id or group.archived_at is not None:
        fail(422, "invalid_group", "Group does not belong to this club")

    count = db.query(func.count(ClubTrainingOpening.id)).filter(
        ClubTrainingOpening.club_id == club_id,
    ).scalar() or 0
    if count >= MAX_OPENINGS_PER_CLUB:
        fail(422, "too_many_openings", f"A club can have at most {MAX_OPENINGS_PER_CLUB} training openings")

    comp: Optional[CalendarEvent] = None
    if competition_event_id is not None:
        comp = _validate_competition_for_club(db, actor, club, competition_event_id)
        existing = db.query(ClubTrainingOpening.id).filter(
            ClubTrainingOpening.club_id == club_id,
            ClubTrainingOpening.eligible_group_id == eligible_group_id,
            ClubTrainingOpening.competition_event_id == competition_event_id,
        ).first()
        if existing is not None:
            fail(409, "opening_exists", "An opening already exists for this group and competition")
        if starts_on is None or ends_on is None:
            comp_day = competition_start_date(db, comp)
            if comp_day is None:
                fail(422, "invalid_dates", "Competition has no scheduled date; provide start and end dates")
            default_start, default_end = default_opening_window(comp_day)
            starts_on = starts_on or default_start
            ends_on = ends_on or default_end
    elif starts_on is None or ends_on is None:
        fail(422, "invalid_dates", "Start and end dates are required")

    clean_label = (label or "").strip() or None
    window_start, window_end = utc_bounds_for_local_dates(starts_on, ends_on, club.timezone)
    row = ClubTrainingOpening(
        club_id=club_id,
        eligible_group_id=eligible_group_id,
        competition_event_id=comp.id if comp else None,
        label=clean_label,
        starts_on=starts_on,
        ends_on=ends_on,
        window_start=window_start,
        window_end=window_end,
        created_by_user_id=actor.id,
    )
    db.add(row)
    db.flush()
    return _serialize_openings(db, [row])[0]


def delete_opening(db: Session, actor: AppUser, club_id: int, opening_id: int) -> None:
    _club_publisher(db, actor, club_id)
    row = db.query(ClubTrainingOpening).filter(
        ClubTrainingOpening.id == opening_id,
        ClubTrainingOpening.club_id == club_id,
    ).with_for_update().one_or_none()
    if row is None:
        fail(404, "opening_not_found", "Training opening not found")
    db.delete(row)
    db.flush()


def event_opening_scopes(db: Session, user: AppUser, event_id: int) -> dict:
    """For a competition event, return club scopes where the caller can publish,
    their groups, existing openings linked to this event, and default 2-week dates."""
    row = access.visible_events(db, user).add_entity(Calendar).filter(CalendarEvent.id == event_id).one_or_none()
    if row is None:
        fail(404, "event_not_found", "Event not found")
    event, cal = row
    if event.event_type != "competition" or event.status != "published":
        return dict(event_id=event.id, default_starts_on=None, default_ends_on=None, clubs=[])

    comp_day = competition_start_date(db, event)
    default_start, default_end = default_opening_window(comp_day) if comp_day else (None, None)

    memberships = db.query(ClubMembership, Club).join(Club, Club.id == ClubMembership.club_id).filter(
        ClubMembership.user_id == user.id,
        ClubMembership.ended_at.is_(None),
        Club.archived_at.is_(None),
        or_(ClubMembership.role == "manager", and_(ClubMembership.role == "coach", ClubMembership.can_publish.is_(True))),
    ).order_by(Club.id).limit(50).all()

    eligible_clubs = [
        club for _m, club in memberships
        if (event.audience == "community" or cal.kind == "federal" or (cal.club_id == club.id and event.audience == "club"))
    ]
    if not eligible_clubs:
        return dict(event_id=event.id, default_starts_on=default_start, default_ends_on=default_end, clubs=[])

    club_ids = [c.id for c in eligible_clubs]
    groups_by_club: Dict[int, list] = {cid: [] for cid in club_ids}
    for g in db.query(TrainingGroup).filter(
        TrainingGroup.club_id.in_(club_ids),
        TrainingGroup.archived_at.is_(None),
    ).order_by(TrainingGroup.name, TrainingGroup.id).limit(500):
        groups_by_club[g.club_id].append(dict(id=g.id, club_id=g.club_id, slug=g.slug, name=g.name))

    openings_rows = db.query(ClubTrainingOpening).filter(
        ClubTrainingOpening.club_id.in_(club_ids),
        ClubTrainingOpening.competition_event_id == event.id,
    ).order_by(ClubTrainingOpening.id).limit(len(club_ids) * MAX_OPENINGS_PER_CLUB).all()
    openings_by_club: Dict[int, list] = {cid: [] for cid in club_ids}
    for item in _serialize_openings(db, openings_rows):
        openings_by_club[item["club_id"]].append(item)

    return dict(
        event_id=event.id,
        default_starts_on=default_start,
        default_ends_on=default_end,
        clubs=[
            dict(
                club_id=c.id,
                club_name=c.short_name or c.name,
                groups=groups_by_club[c.id],
                openings=openings_by_club[c.id],
            )
            for c in eligible_clubs
        ],
    )


def open_access_occurrence_ids(db: Session, user: AppUser, rows: Iterable[tuple]) -> Set[int]:
    """Return occurrence IDs among `rows` that are opened to `user` via a
    ClubTrainingOpening (another group's training session in an open window).

    Bounded to at most 2 bulk queries regardless of page size.
    """
    candidates = [
        (o, e, c) for o, e, c in rows
        if e.event_type == "training" and e.audience == "group"
        and c.kind == "group" and c.club_id is not None and c.training_group_id is not None
    ]
    if not candidates or not access.openings_schema_ready(db):
        return set()

    club_ids = {c.club_id for _o, _e, c in candidates}
    on = access.today()
    my_groups = {
        club_id: group_id
        for club_id, group_id in db.query(
            TrainingGroupMembership.club_id, TrainingGroupMembership.group_id
        ).join(
            ClubMembership, ClubMembership.id == TrainingGroupMembership.club_membership_id
        ).filter(
            TrainingGroupMembership.user_id == user.id,
            TrainingGroupMembership.club_id.in_(club_ids),
            TrainingGroupMembership.effective_from <= on,
            or_(TrainingGroupMembership.effective_to.is_(None), TrainingGroupMembership.effective_to > on),
            ClubMembership.ended_at.is_(None),
        ).limit(len(club_ids))
    }
    if not my_groups:
        return set()

    other_group = [
        (o, c) for o, _e, c in candidates
        if c.club_id in my_groups and my_groups[c.club_id] != c.training_group_id
    ]
    if not other_group:
        return set()

    occ_ids = [o.id for o, _c in other_group]
    target_clubs = {c.club_id for _o, c in other_group}
    pair_cond = or_(*(
        and_(
            ClubTrainingOpening.club_id == cid,
            ClubTrainingOpening.eligible_group_id == my_groups[cid],
        )
        for cid in target_clubs
    ))
    matched = db.query(EventOccurrence.id).join(
        CalendarEvent, CalendarEvent.id == EventOccurrence.event_id
    ).join(
        Calendar, Calendar.id == CalendarEvent.calendar_id
    ).filter(
        EventOccurrence.id.in_(occ_ids),
        exists().where(and_(
            ClubTrainingOpening.club_id == Calendar.club_id,
            pair_cond,
            ClubTrainingOpening.window_start <= EventOccurrence.window_start,
            ClubTrainingOpening.window_end > EventOccurrence.window_start,
        )),
    ).limit(len(occ_ids)).all()
    return {oid for (oid,) in matched}
