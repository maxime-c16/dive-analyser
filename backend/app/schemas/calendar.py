"""Calendar API contracts (Task02). Timestamps are ISO-8601 UTC strings
ending in Z; all-day dates are local ISO dates with an exclusive end."""
from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

Slug = Field(..., min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
ClubRole = Literal["member", "coach", "manager"]


class ClubCreate(BaseModel):
    slug: str = Slug
    name: str = Field(..., min_length=1, max_length=160)
    short_name: Optional[str] = Field(None, max_length=40)
    timezone: str = Field("Europe/Paris", max_length=64)
    self_join_enabled: bool = False


class GroupCreate(BaseModel):
    slug: str = Slug
    name: str = Field(..., min_length=1, max_length=120)


class AdminMembershipCreate(BaseModel):
    user_id: int = Field(..., gt=0)
    role: ClubRole = "member"


class MembershipUpdate(BaseModel):
    role: Optional[ClubRole] = None
    can_publish: Optional[bool] = None
    can_assign_groups: Optional[bool] = None


class GroupAssignment(BaseModel):
    user_id: int = Field(..., gt=0)
    group_id: Optional[int] = Field(None, gt=0)
    effective_from: Optional[date] = None


class ClubOut(BaseModel):
    id: int
    slug: str
    name: str
    short_name: Optional[str]
    timezone: str
    self_join_enabled: bool


class GroupOut(BaseModel):
    id: int
    club_id: int
    slug: str
    name: str


class MembershipOut(BaseModel):
    id: int
    club_id: int
    user_id: int
    role: ClubRole
    can_publish: bool
    can_assign_groups: bool
    status: str
    source: str
    started_at: str
    ended_at: Optional[str]


class AssignmentOut(BaseModel):
    id: int
    club_id: int
    group_id: int
    user_id: int
    effective_from: date
    effective_to: Optional[date]


class MyClubOut(BaseModel):
    club: ClubOut
    membership: MembershipOut
    # None = "your training group has not been assigned" (never a default group).
    group: Optional[GroupOut]
    self_declared: bool


class MeOut(BaseModel):
    clubs: List[MyClubOut]


class RosterEntry(BaseModel):
    user_id: int
    display_name: str
    role: ClubRole
    # Only staff see other members' groups; members see none here.
    group_id: Optional[int] = None
    # Staff-only administration fields (None for plain members).
    membership_id: Optional[int] = None
    can_publish: Optional[bool] = None
    can_assign_groups: Optional[bool] = None
    self_declared: Optional[bool] = None
    group_since: Optional[date] = None


class RosterOut(BaseModel):
    club_id: int
    my_role: Optional[ClubRole] = None
    can_assign_groups: bool = False
    can_manage_members: bool = False
    groups: List[GroupOut] = []
    # App accounts only — never implies a complete club roster.
    items: List[RosterEntry]


class CalendarOut(BaseModel):
    id: int
    kind: str
    name: str
    club_id: Optional[int]
    training_group_id: Optional[int]
    following: bool
    # Task03: server-computed write permission and allowed audiences.
    can_publish: bool = False
    allowed_audiences: List[str] = []


class CalendarsOut(BaseModel):
    items: List[CalendarOut]


class ResourceOut(BaseModel):
    id: int
    kind: str
    label: str
    url: Optional[str]
    deadline_kind: Optional[str]
    due_at: Optional[str]
    edition_label: Optional[str]
    source_verified_at: Optional[str]


class EventSummary(BaseModel):
    id: int
    calendar_id: int
    calendar_kind: str
    club_id: Optional[int]
    event_type: str
    audience: str
    status: str
    title: str
    timezone: str
    version: int
    calendar_name: Optional[str] = None
    training_group_id: Optional[int] = None


class OccurrenceOut(BaseModel):
    id: int
    occurrence_key: str
    status: str
    is_all_day: bool
    starts_at: Optional[str]
    ends_at: Optional[str]
    start_date: Optional[date]
    end_date: Optional[date]
    venue_name: Optional[str]
    shared_session_id: Optional[int] = None
    is_filmed_session: bool
    version: int
    event: EventSummary
    # The caller's own state; the detail view adds a `going` summary.
    my_interest: Optional[str] = None
    my_absence_reported: bool = False
    # Local wall-clock view in the event timezone (display/filtering).
    local_date: Optional[date] = None
    local_start: Optional[str] = None
    local_end: Optional[str] = None
    imported: bool = False
    # Task04: inclusive last local day (multi-day camps), weekly-series slot.
    local_end_date: Optional[date] = None
    series_date: Optional[date] = None
    detached: bool = False


class OccurrencePage(BaseModel):
    items: List[OccurrenceOut]
    next_cursor: Optional[str]


class EventDetail(EventSummary):
    description: str
    venue_name: Optional[str]
    venue_address: Optional[str]
    map_url: Optional[str]
    recurrence_rule: Optional[str]
    organizer_user_id: Optional[int]
    organizer_name: Optional[str]
    my_invitation: Optional[str]
    resources: List[ResourceOut]
    occurrences: List[OccurrenceOut]
    following: bool = False
    can_edit: bool = False
    changes: List["ChangeOut"] = []
    recurrence: Optional["RecurrenceOut"] = None
    itinerary: List["ItineraryItem"] = []
    imported: bool = False


class AttendeeOut(BaseModel):
    user_id: int
    display_name: str
    avatar_url: Optional[str] = None
    avatar_hud: str = "reticle"


class GoingOut(BaseModel):
    """Expected members who have not reported absence. Legacy field names are kept for API compatibility."""
    interested: int = 0
    maybe: int = 0
    people: List[AttendeeOut] = []  # interested first, newest answers first, capped


class OccurrenceDetail(OccurrenceOut):
    going: GoingOut = GoingOut()
    resources: List[ResourceOut]
    description: str
    venue_address: Optional[str]
    map_url: Optional[str] = None
    can_edit: bool = False
    can_report_absence: bool = False
    following: bool = False
    my_invitation: Optional[str] = None
    organizer_name: Optional[str] = None
    changes: List["ChangeOut"] = []


# --- Task03 write contracts ------------------------------------------------------
# Local wall times are naive ISO datetimes in the event timezone; the server
# converts them (refusing DST-gap/overlap times). All-day end is exclusive.

EventType = Literal["training", "camp", "outing", "competition", "other"]
Audience = Literal["group", "club", "community", "invited"]
InterestState = Literal["interested", "maybe", "declined"]
OptionalText200 = Field(None, max_length=200)


class OccurrenceTimes(BaseModel):
    all_day: bool = False
    start_local: Optional[datetime] = None
    end_local: Optional[datetime] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None


def _plain_url(value: Optional[str]) -> Optional[str]:
    if value in (None, ""):
        return None
    if not value.startswith(("https://", "http://")):
        raise ValueError("Links must start with https:// or http://")
    return value


HHMM = Field(None, pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")


class RecurrenceSpec(BaseModel):
    """Weekly repetition from the first session's date and times."""
    weekdays: List[int] = Field(..., min_length=1, max_length=7)  # ISO: 1 = Monday
    until_date: date  # explicit season end, inclusive
    excluded_dates: List[date] = Field(default_factory=list, max_length=120)

    @field_validator("weekdays")
    @classmethod
    def _days(cls, v: List[int]) -> List[int]:
        if any(d < 1 or d > 7 for d in v):
            raise ValueError("Weekdays are 1 (Monday) to 7 (Sunday)")
        return sorted(set(v))


class RecurrenceOut(BaseModel):
    weekdays: List[int]
    start_time: str
    end_time: str
    first_date: date
    until_date: date
    pattern_from: date
    excluded_dates: List[date]


class ItineraryItem(BaseModel):
    """Camp itinerary block: informational, never separately bookable."""
    local_date: date
    start_time: Optional[str] = HHMM
    end_time: Optional[str] = HHMM
    venue_name: Optional[str] = Field(None, max_length=200)
    label: Optional[str] = Field(None, max_length=200)


class EventCreate(BaseModel):
    calendar_id: Optional[int] = Field(None, gt=0)  # None = own personal calendar
    event_type: EventType = "outing"
    audience: Audience = "invited"
    status: Literal["draft", "published"] = "published"
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field("", max_length=4000)
    venue_name: Optional[str] = OptionalText200
    venue_address: Optional[str] = Field(None, max_length=300)
    map_url: Optional[str] = Field(None, max_length=500)
    timezone: str = Field("Europe/Paris", max_length=64)
    when: OccurrenceTimes
    recurrence: Optional[RecurrenceSpec] = None
    itinerary: Optional[List[ItineraryItem]] = Field(None, max_length=20)
    registration_url: Optional[str] = Field(None, max_length=1000)

    @field_validator("map_url", "registration_url")
    @classmethod
    def _url(cls, v: Optional[str]) -> Optional[str]:
        return _plain_url(v)

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Title is required")
        return v.strip()


class EventUpdate(BaseModel):
    expected_version: int = Field(..., ge=1)
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=4000)
    venue_name: Optional[str] = OptionalText200
    venue_address: Optional[str] = Field(None, max_length=300)
    map_url: Optional[str] = Field(None, max_length=500)
    audience: Optional[Audience] = None
    event_type: Optional[EventType] = None
    status: Optional[Literal["published"]] = None
    when: Optional[OccurrenceTimes] = None
    itinerary: Optional[List[ItineraryItem]] = Field(None, max_length=20)
    registration_url: Optional[str] = Field(None, max_length=1000)

    @field_validator("map_url", "registration_url")
    @classmethod
    def _url(cls, v: Optional[str]) -> Optional[str]:
        return _plain_url(v)


class OccurrenceUpdate(BaseModel):
    expected_version: int = Field(..., ge=1)
    when: Optional[OccurrenceTimes] = None
    venue_name: Optional[str] = OptionalText200


class ScheduleEdit(BaseModel):
    """Scoped change to a series (Task04). one: the chosen session only;
    future: it and the following ones; all: every upcoming session."""
    expected_version: int = Field(..., ge=1)  # event version
    scope: Literal["one", "future", "all"]
    occurrence_id: Optional[int] = Field(None, gt=0)
    # scope=one
    when: Optional[OccurrenceTimes] = None
    cancel: bool = False
    # scope=future/all (omitted fields keep the current pattern)
    weekdays: Optional[List[int]] = Field(None, min_length=1, max_length=7)
    start_time: Optional[str] = HHMM
    end_time: Optional[str] = HHMM
    until_date: Optional[date] = None
    excluded_dates: Optional[List[date]] = Field(None, max_length=120)
    # every scope
    venue_name: Optional[str] = OptionalText200


class ScheduleApply(ScheduleEdit):
    plan_hash: str = Field(..., min_length=64, max_length=64)


class SchedulePreviewOut(BaseModel):
    plan: dict
    plan_hash: str
    summary: dict
    event_version: Optional[int] = None


class VersionedAction(BaseModel):
    expected_version: int = Field(..., ge=1)


class InvitationsCreate(BaseModel):
    user_ids: List[int] = Field(..., min_length=1, max_length=50)


class InvitationResponse(BaseModel):
    status: Literal["accepted", "declined"]


class InterestWrite(BaseModel):
    state: Optional[InterestState] = None  # null clears the response


class AbsenceWrite(BaseModel):
    absent: bool


class InvitationOut(BaseModel):
    user_id: int
    display_name: str
    status: str
    responded_at: Optional[str]


class InvitationsOut(BaseModel):
    items: List[InvitationOut]


class LinkedDiveOut(BaseModel):
    id: int
    dive_code: str
    dive_datetime: str
    linked: bool
    height: Optional[str] = None
    performance: Optional[str] = None
    phase1_performance: Optional[str] = None
    phase2_performance: Optional[str] = None
    poster_url: Optional[str] = None  # ready cached poster only, never an original


class LinkedDivesOut(BaseModel):
    items: List[LinkedDiveOut]


class ChangeOut(BaseModel):
    kind: str
    at: str
    fields: List[str]


EventDetail.model_rebuild()
OccurrenceDetail.model_rebuild()
