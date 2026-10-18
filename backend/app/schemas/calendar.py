"""Calendar API contracts (Task02). Timestamps are ISO-8601 UTC strings
ending in Z; all-day dates are local ISO dates with an exclusive end."""
from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

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


class RosterOut(BaseModel):
    club_id: int
    # App accounts only — never implies a complete club roster.
    items: List[RosterEntry]


class CalendarOut(BaseModel):
    id: int
    kind: str
    name: str
    club_id: Optional[int]
    training_group_id: Optional[int]
    following: bool


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
    is_filmed_session: bool
    version: int
    event: EventSummary
    # The caller's own state only; other members' responses are never listed.
    my_interest: Optional[str] = None
    my_absence_reported: bool = False


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


class OccurrenceDetail(OccurrenceOut):
    resources: List[ResourceOut]
    description: str
    venue_address: Optional[str]
