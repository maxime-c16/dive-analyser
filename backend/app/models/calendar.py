"""Club calendar domain (Task02 foundation, default-off).

SQL authority: backend/migrations/add_calendar_domain.sql. Every table is
tagged ``sql_migration_only`` so app startup (init_db) never creates them:
the migration is an explicit deployment step, applied before CALENDAR_ENABLED.

Identity is app_users, never diver display names. Grants are separate rows:
club membership, staff role, training-group assignment (effective-dated),
event invitation, calendar subscription (grants nothing) and organizer.
Interest and absence are independent; neither reserves a place nor proves
attendance. Timestamps are naive UTC like the rest of the schema.
"""
from datetime import datetime

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey,
    ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint, text,
)

from app.database import Base

MIGRATION_ONLY = {"info": {"sql_migration_only": True}}

CLUB_ROLES = ("member", "coach", "manager")
MEMBERSHIP_STATUSES = ("active", "left", "removed")
MEMBERSHIP_SOURCES = ("signup", "admin_legacy", "manager")
CALENDAR_KINDS = ("club", "group", "personal", "federal")
EVENT_TYPES = ("training", "camp", "outing", "competition", "other")
EVENT_AUDIENCES = ("group", "club", "community", "invited")
EVENT_STATUSES = ("draft", "published", "cancelled")
OCCURRENCE_STATUSES = ("scheduled", "cancelled")
INVITATION_STATUSES = ("pending", "accepted", "declined", "revoked")
INTEREST_STATES = ("interested", "maybe", "declined")
RESOURCE_KINDS = ("official_info", "registration", "dive_sheets", "results", "club_chat", "rules", "other")
DEADLINE_KINDS = ("club_cutoff", "official_entry", "dive_sheet")
SOURCE_KINDS = ("workbook", "pdf_schedule", "organizer_page", "federation_page", "manual")
IMPORT_STATUSES = ("previewed", "applied", "failed")
MAPPING_TARGETS = ("event", "occurrence", "resource")
REVIEW_STATUSES = ("needs_review", "historical", "conflict", "missing_from_source", "resolved")
CHANGE_KINDS = ("created", "published", "updated", "time_changed", "venue_changed", "cancelled", "imported")


def _in(column, values):
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Club(Base):
    __tablename__ = "clubs"
    id = Column(Integer, primary_key=True)
    slug = Column(String(64), nullable=False, unique=True)
    name = Column(String(160), nullable=False)
    short_name = Column(String(40), nullable=True)
    timezone = Column(String(64), nullable=False, default="Europe/Paris", server_default="Europe/Paris")
    self_join_enabled = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    archived_at = Column(DateTime, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = MIGRATION_ONLY


class ClubMembership(Base):
    """One row per membership period; history is kept after leaving."""
    __tablename__ = "club_memberships"
    id = Column(Integer, primary_key=True)
    club_id = Column(Integer, ForeignKey("clubs.id", ondelete="RESTRICT"), nullable=False)
    user_id = Column(Integer, ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(16), nullable=False, default="member", server_default="member")
    # Per-club grants a manager gives a coach. Managers hold both implicitly.
    can_publish = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    can_assign_groups = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    status = Column(String(16), nullable=False, default="active", server_default="active")
    source = Column(String(16), nullable=False)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True)
    ended_by_user_id = Column(Integer, ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True)
    __table_args__ = (
        CheckConstraint(_in("role", CLUB_ROLES), name="ck_club_membership_role"),
        CheckConstraint(_in("status", MEMBERSHIP_STATUSES), name="ck_club_membership_status"),
        CheckConstraint(_in("source", MEMBERSHIP_SOURCES), name="ck_club_membership_source"),
        CheckConstraint("(status = 'active') = (ended_at IS NULL)", name="ck_club_membership_ended"),
        UniqueConstraint("id", "club_id", name="uq_club_membership_id_club"),
        Index("uq_club_membership_active", "club_id", "user_id", unique=True,
              postgresql_where=text("ended_at IS NULL"), sqlite_where=text("ended_at IS NULL")),
        Index("ix_club_memberships_user", "user_id", "club_id"),
        MIGRATION_ONLY,
    )


class TrainingGroup(Base):
    __tablename__ = "training_groups"
    id = Column(Integer, primary_key=True)
    club_id = Column(Integer, ForeignKey("clubs.id", ondelete="RESTRICT"), nullable=False)
    slug = Column(String(64), nullable=False)
    name = Column(String(120), nullable=False)
    archived_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint("club_id", "slug", name="uq_training_group_slug"),
        UniqueConstraint("id", "club_id", name="uq_training_group_id_club"),
        MIGRATION_ONLY,
    )


class TrainingGroupMembership(Base):
    """Effective-dated assignment; effective_to is exclusive, NULL = open.

    Composite FKs make a cross-club group/membership pairing impossible.
    """
    __tablename__ = "training_group_memberships"
    id = Column(Integer, primary_key=True)
    club_id = Column(Integer, nullable=False)
    group_id = Column(Integer, nullable=False)
    club_membership_id = Column(Integer, nullable=False)
    user_id = Column(Integer, ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date, nullable=True)
    assigned_by_user_id = Column(Integer, ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True)
    ended_by_user_id = Column(Integer, ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (
        ForeignKeyConstraint(["group_id", "club_id"], ["training_groups.id", "training_groups.club_id"],
                             ondelete="RESTRICT", name="fk_group_membership_group_club"),
        ForeignKeyConstraint(["club_membership_id", "club_id"], ["club_memberships.id", "club_memberships.club_id"],
                             ondelete="CASCADE", name="fk_group_membership_club_membership"),
        CheckConstraint("effective_to IS NULL OR effective_to > effective_from", name="ck_group_membership_dates"),
        Index("uq_group_membership_open", "club_id", "user_id", unique=True,
              postgresql_where=text("effective_to IS NULL"), sqlite_where=text("effective_to IS NULL")),
        Index("ix_group_memberships_group", "group_id", "effective_from"),
        Index("ix_group_memberships_user", "user_id", "club_id", "effective_from"),
        MIGRATION_ONLY,
    )


class Calendar(Base):
    """A publishing source. Kind fixes its owner; audience lives on events."""
    __tablename__ = "calendars"
    id = Column(Integer, primary_key=True)
    kind = Column(String(16), nullable=False)
    club_id = Column(Integer, ForeignKey("clubs.id", ondelete="RESTRICT"), nullable=True)
    training_group_id = Column(Integer, nullable=True)
    owner_user_id = Column(Integer, ForeignKey("app_users.id", ondelete="CASCADE"), nullable=True)
    name = Column(String(160), nullable=False)
    archived_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (
        ForeignKeyConstraint(["training_group_id", "club_id"], ["training_groups.id", "training_groups.club_id"],
                             ondelete="RESTRICT", name="fk_calendar_group_club"),
        CheckConstraint(_in("kind", CALENDAR_KINDS), name="ck_calendar_kind"),
        CheckConstraint(
            "(kind = 'club' AND club_id IS NOT NULL AND training_group_id IS NULL AND owner_user_id IS NULL)"
            " OR (kind = 'group' AND club_id IS NOT NULL AND training_group_id IS NOT NULL AND owner_user_id IS NULL)"
            " OR (kind = 'personal' AND owner_user_id IS NOT NULL AND club_id IS NULL AND training_group_id IS NULL)"
            " OR (kind = 'federal' AND club_id IS NULL AND training_group_id IS NULL AND owner_user_id IS NULL)",
            name="ck_calendar_owner"),
        Index("uq_calendar_club", "club_id", unique=True,
              postgresql_where=text("kind = 'club'"), sqlite_where=text("kind = 'club'")),
        Index("uq_calendar_group", "training_group_id", unique=True,
              postgresql_where=text("kind = 'group'"), sqlite_where=text("kind = 'group'")),
        MIGRATION_ONLY,
    )


class CalendarSubscription(Base):
    """Following a calendar: a display preference that never grants access."""
    __tablename__ = "calendar_subscriptions"
    calendar_id = Column(Integer, ForeignKey("calendars.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(Integer, ForeignKey("app_users.id", ondelete="CASCADE"), primary_key=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (Index("ix_calendar_subscriptions_user", "user_id"), MIGRATION_ONLY)


class CalendarEvent(Base):
    """One canonical event; recurrence_rule is metadata only (no expansion)."""
    __tablename__ = "calendar_events"
    id = Column(Integer, primary_key=True)
    calendar_id = Column(Integer, ForeignKey("calendars.id", ondelete="RESTRICT"), nullable=False)
    organizer_user_id = Column(Integer, ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True)
    event_type = Column(String(16), nullable=False)
    audience = Column(String(16), nullable=False)
    status = Column(String(16), nullable=False, default="draft", server_default="draft")
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False, default="", server_default="")
    venue_name = Column(String(200), nullable=True)
    venue_address = Column(String(300), nullable=True)
    map_url = Column(String(500), nullable=True)
    timezone = Column(String(64), nullable=False)
    recurrence_rule = Column(String(500), nullable=True)
    # Optional future scoring link; deliberately no FK so competitions stay optional.
    scoring_competition_id = Column(Integer, nullable=True)
    version = Column(Integer, nullable=False, default=1, server_default="1")
    published_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (
        CheckConstraint(_in("event_type", EVENT_TYPES), name="ck_calendar_event_type"),
        CheckConstraint(_in("audience", EVENT_AUDIENCES), name="ck_calendar_event_audience"),
        CheckConstraint(_in("status", EVENT_STATUSES), name="ck_calendar_event_status"),
        CheckConstraint("(status = 'cancelled') = (cancelled_at IS NOT NULL)", name="ck_calendar_event_cancelled"),
        CheckConstraint("version >= 1", name="ck_calendar_event_version"),
        Index("ix_calendar_events_calendar", "calendar_id", "status"),
        Index("ix_calendar_events_organizer", "organizer_user_id"),
        MIGRATION_ONLY,
    )


class EventOccurrence(Base):
    """A dated instance with a stable key. Timed: UTC instants. All-day:
    local dates, end exclusive. window_* (UTC) index both forms uniformly."""
    __tablename__ = "event_occurrences"
    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("calendar_events.id", ondelete="CASCADE"), nullable=False)
    occurrence_key = Column(String(120), nullable=False)
    is_all_day = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    starts_at = Column(DateTime, nullable=True)
    ends_at = Column(DateTime, nullable=True)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    window_start = Column(DateTime, nullable=False)
    window_end = Column(DateTime, nullable=False)
    status = Column(String(16), nullable=False, default="scheduled", server_default="scheduled")
    venue_name = Column(String(200), nullable=True)
    # Links an existing filmed session; never grants video access.
    filmed_session_id = Column(Integer, ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True)
    version = Column(Integer, nullable=False, default=1, server_default="1")
    cancelled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint("event_id", "occurrence_key", name="uq_occurrence_key"),
        CheckConstraint(_in("status", OCCURRENCE_STATUSES), name="ck_occurrence_status"),
        CheckConstraint("(status = 'cancelled') = (cancelled_at IS NOT NULL)", name="ck_occurrence_cancelled"),
        CheckConstraint(
            "(is_all_day AND start_date IS NOT NULL AND end_date > start_date AND starts_at IS NULL AND ends_at IS NULL)"
            " OR (NOT is_all_day AND starts_at IS NOT NULL AND ends_at > starts_at AND start_date IS NULL AND end_date IS NULL)",
            name="ck_occurrence_time_form"),
        CheckConstraint("window_end > window_start", name="ck_occurrence_window"),
        Index("ix_occurrences_window", "window_start", "id"),
        Index("ix_occurrences_event", "event_id", "window_start"),
        MIGRATION_ONLY,
    )


class EventInvitation(Base):
    __tablename__ = "event_invitations"
    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("calendar_events.id", ondelete="CASCADE"), nullable=False)
    invitee_user_id = Column(Integer, ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False)
    invited_by_user_id = Column(Integer, ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(16), nullable=False, default="pending", server_default="pending")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    responded_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    __table_args__ = (
        UniqueConstraint("event_id", "invitee_user_id", name="uq_event_invitation"),
        CheckConstraint(_in("status", INVITATION_STATUSES), name="ck_event_invitation_status"),
        CheckConstraint("(status = 'revoked') = (revoked_at IS NOT NULL)", name="ck_event_invitation_revoked"),
        Index("ix_event_invitations_invitee", "invitee_user_id", "status"),
        MIGRATION_ONLY,
    )


class OccurrenceInterest(Base):
    """Interest only: no capacity, reservation or attendance meaning."""
    __tablename__ = "occurrence_interests"
    occurrence_id = Column(Integer, ForeignKey("event_occurrences.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(Integer, ForeignKey("app_users.id", ondelete="CASCADE"), primary_key=True)
    state = Column(String(16), nullable=False)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (
        CheckConstraint(_in("state", INTEREST_STATES), name="ck_occurrence_interest_state"),
        MIGRATION_ONLY,
    )


class OccurrenceAbsenceReport(Base):
    """Independent of interest. No free text: avoids collecting health data."""
    __tablename__ = "occurrence_absence_reports"
    occurrence_id = Column(Integer, ForeignKey("event_occurrences.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(Integer, ForeignKey("app_users.id", ondelete="CASCADE"), primary_key=True)
    reported_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    withdrawn_at = Column(DateTime, nullable=True)
    __table_args__ = MIGRATION_ONLY


class CalendarSource(Base):
    """Source inventory: the workbook is provenance; embedded links are the
    upstreams. storage_ref points at private storage, never Git."""
    __tablename__ = "calendar_sources"
    id = Column(Integer, primary_key=True)
    kind = Column(String(24), nullable=False)
    label = Column(String(200), nullable=False)
    url = Column(String(1000), nullable=True)
    club_id = Column(Integer, ForeignKey("clubs.id", ondelete="RESTRICT"), nullable=True)
    parent_source_id = Column(Integer, ForeignKey("calendar_sources.id", ondelete="SET NULL"), nullable=True)
    is_private = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    artifact_sha256 = Column(String(64), nullable=True)
    storage_ref = Column(String(500), nullable=True)
    last_checked_at = Column(DateTime, nullable=True)
    last_success_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (
        CheckConstraint(_in("kind", SOURCE_KINDS), name="ck_calendar_source_kind"),
        Index("ix_calendar_sources_parent", "parent_source_id"),
        MIGRATION_ONLY,
    )


class CalendarImportRun(Base):
    """One import version: validate -> preview -> apply (Task03 service)."""
    __tablename__ = "calendar_import_runs"
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("calendar_sources.id", ondelete="RESTRICT"), nullable=False)
    source_sha256 = Column(String(64), nullable=False)
    parser_version = Column(String(40), nullable=False)
    status = Column(String(16), nullable=False)
    summary = Column(JSON, nullable=False, default=dict, server_default="{}")
    created_by_user_id = Column(Integer, ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    applied_at = Column(DateTime, nullable=True)
    __table_args__ = (
        CheckConstraint(_in("status", IMPORT_STATUSES), name="ck_calendar_import_status"),
        Index("ix_calendar_import_runs_source", "source_id", "created_at"),
        MIGRATION_ONLY,
    )


class EventResource(Base):
    """Typed link owned by an event or club-wide. restricted_to_club keeps
    e.g. a club chat invitation private even on a community-shared event."""
    __tablename__ = "event_resources"
    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("calendar_events.id", ondelete="CASCADE"), nullable=True)
    club_id = Column(Integer, ForeignKey("clubs.id", ondelete="RESTRICT"), nullable=True)
    kind = Column(String(24), nullable=False)
    label = Column(String(200), nullable=False)
    url = Column(String(1000), nullable=True)
    restricted_to_club = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    deadline_kind = Column(String(24), nullable=True)
    due_at = Column(DateTime, nullable=True)
    edition_label = Column(String(80), nullable=True)
    source_verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (
        CheckConstraint(_in("kind", RESOURCE_KINDS), name="ck_event_resource_kind"),
        CheckConstraint(f"deadline_kind IS NULL OR {_in('deadline_kind', DEADLINE_KINDS)}", name="ck_event_resource_deadline"),
        CheckConstraint("(event_id IS NULL) <> (club_id IS NULL)", name="ck_event_resource_owner"),
        Index("ix_event_resources_event", "event_id"),
        Index("ix_event_resources_club", "club_id"),
        MIGRATION_ONLY,
    )


class CalendarSourceMapping(Base):
    """Stable source key -> canonical record. Workbook row numbers are a
    snapshot locator in provenance, never the external_key."""
    __tablename__ = "calendar_source_mappings"
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("calendar_sources.id", ondelete="RESTRICT"), nullable=False)
    external_key = Column(String(200), nullable=False)
    target_type = Column(String(16), nullable=False)
    event_id = Column(Integer, ForeignKey("calendar_events.id", ondelete="SET NULL"), nullable=True)
    occurrence_id = Column(Integer, ForeignKey("event_occurrences.id", ondelete="SET NULL"), nullable=True)
    resource_id = Column(Integer, ForeignKey("event_resources.id", ondelete="SET NULL"), nullable=True)
    last_import_run_id = Column(Integer, ForeignKey("calendar_import_runs.id", ondelete="SET NULL"), nullable=True)
    locally_overridden = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    provenance = Column(JSON, nullable=False, default=dict, server_default="{}")
    # Task03 (add_calendar_task03.sql): unresolved import items stay here,
    # with no target, until a curator reviews them.
    review_status = Column(String(24), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint("source_id", "target_type", "external_key", name="uq_calendar_source_mapping"),
        CheckConstraint(_in("target_type", MAPPING_TARGETS), name="ck_calendar_mapping_target"),
        CheckConstraint(f"review_status IS NULL OR {_in('review_status', REVIEW_STATUSES)}",
                        name="ck_calendar_mapping_review"),
        Index("ix_calendar_mappings_event", "event_id"),
        Index("ix_calendar_mappings_occurrence", "occurrence_id"),
        MIGRATION_ONLY,
    )


class CalendarChangeLog(Base):
    """Versioned audit trail; the future notification outbox reads from here
    (written in the same transaction as the change) — no worker yet."""
    __tablename__ = "calendar_change_log"
    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("calendar_events.id", ondelete="CASCADE"), nullable=False)
    occurrence_id = Column(Integer, ForeignKey("event_occurrences.id", ondelete="SET NULL"), nullable=True)
    event_version = Column(Integer, nullable=False)
    change_kind = Column(String(16), nullable=False)
    actor_user_id = Column(Integer, ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True)
    import_run_id = Column(Integer, ForeignKey("calendar_import_runs.id", ondelete="SET NULL"), nullable=True)
    changes = Column(JSON, nullable=False, default=dict, server_default="{}")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (
        CheckConstraint(_in("change_kind", CHANGE_KINDS), name="ck_calendar_change_kind"),
        Index("ix_calendar_change_log_event", "event_id", "id"),
        MIGRATION_ONLY,
    )



# --- Task03 (backend/migrations/add_calendar_task03.sql) -------------------

class CalendarEventFollow(Base):
    """Following one event: display preference only, never an access grant."""
    __tablename__ = "calendar_event_follows"
    event_id = Column(Integer, ForeignKey("calendar_events.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(Integer, ForeignKey("app_users.id", ondelete="CASCADE"), primary_key=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (Index("ix_calendar_event_follows_user", "user_id"), MIGRATION_ONLY)


class CalendarIdempotencyKey(Base):
    """Actor-scoped create key; request_hash rejects reuse for another payload."""
    __tablename__ = "calendar_idempotency_keys"
    user_id = Column(Integer, ForeignKey("app_users.id", ondelete="CASCADE"), primary_key=True)
    idempotency_key = Column(String(80), primary_key=True)
    request_hash = Column(String(64), nullable=False)
    event_id = Column(Integer, ForeignKey("calendar_events.id", ondelete="CASCADE"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = MIGRATION_ONLY


class OccurrenceDiveLink(Base):
    """A member links one of their own dives to an occurrence. Private to
    that account; dive and media visibility are never changed."""
    __tablename__ = "occurrence_dive_links"
    occurrence_id = Column(Integer, ForeignKey("event_occurrences.id", ondelete="CASCADE"), primary_key=True)
    dive_id = Column(Integer, ForeignKey("dives.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(Integer, ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (Index("ix_occurrence_dive_links_user", "user_id", "occurrence_id"), MIGRATION_ONLY)
