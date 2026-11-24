"""Official meet results attached to a competition calendar event.

SQL authority: backend/migrations/add_meet_results.sql (migration-only, like
the calendar domain it hangs off). One import per calendar event; a re-import
replaces it in one transaction. Numbers are the published sheet's, stored as
printed (docs/SCORING.md §4). Diver names are text from the sheet, not
accounts: nothing here grants access to anyone's dives or media.
"""
from datetime import datetime

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, Numeric, SmallInteger, String, UniqueConstraint,
)

from app.database import Base
from app.models.calendar import MIGRATION_ONLY


class MeetResult(Base):
    __tablename__ = "meet_results"
    id = Column(Integer, primary_key=True)
    calendar_event_id = Column(Integer, ForeignKey("calendar_events.id", ondelete="CASCADE"), nullable=False, unique=True)
    source_name = Column(String(200), nullable=False)
    source_sha256 = Column(String(64), nullable=False)
    meet_date = Column(Date, nullable=True)
    imported_by_user_id = Column(Integer, ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True)
    imported_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = MIGRATION_ONLY


class MeetResultEvent(Base):
    """One event of the meet as printed, e.g. "Elite - Messieurs - 3m"."""
    __tablename__ = "meet_result_events"
    id = Column(Integer, primary_key=True)
    result_id = Column(Integer, ForeignKey("meet_results.id", ondelete="CASCADE"), nullable=False)
    position = Column(Integer, nullable=False)
    title = Column(String(200), nullable=False)
    board = Column(String(16), nullable=False)
    __table_args__ = (UniqueConstraint("result_id", "position", name="uq_meet_result_event_position"), MIGRATION_ONLY)


class MeetResultEntry(Base):
    __tablename__ = "meet_result_entries"
    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("meet_result_events.id", ondelete="CASCADE"), nullable=False)
    position = Column(Integer, nullable=False)
    rank = Column(Integer, nullable=True)
    diver_name = Column(String(120), nullable=False)
    birth_year = Column(SmallInteger, nullable=True)
    club_name = Column(String(120), nullable=False)
    total = Column(Numeric(7, 2), nullable=False)
    # As printed by DiveRecorder after the club; NULL = finished normally.
    status = Column(String(16), nullable=True)
    guest = Column(Boolean, nullable=False, default=False)
    # Set only by an unambiguous automatic match (services/meet_result_links).
    user_id = Column(Integer, ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True)
    __table_args__ = (
        UniqueConstraint("event_id", "position", name="uq_meet_result_entry_position"),
        Index("ix_meet_result_entries_user", "user_id"),
        CheckConstraint("status IS NULL OR status IN ('disqualified', 'withdrawn', 'knocked_out')",
                        name="ck_meet_result_entry_status"),
        MIGRATION_ONLY,
    )


class MeetResultDive(Base):
    __tablename__ = "meet_result_dives"
    id = Column(Integer, primary_key=True)
    entry_id = Column(Integer, ForeignKey("meet_result_entries.id", ondelete="CASCADE"), nullable=False)
    position = Column(SmallInteger, nullable=False)
    dive_code = Column(String(8), nullable=False)
    height = Column(Numeric(3, 1), nullable=False)
    dd = Column(Numeric(3, 1), nullable=False)
    # Judge marks in half steps (0–20 → 0–10), in printed order J1..Jn.
    judge_half_steps = Column(JSON, nullable=False)
    cumul = Column(Numeric(5, 1), nullable=False)
    points = Column(Numeric(6, 2), nullable=False)
    running_total = Column(Numeric(7, 2), nullable=False)
    # DiveRecorder penalty code: 1 failed, 2 false start, 3 position, 4 arms.
    penalty = Column(SmallInteger, nullable=True)
    __table_args__ = (UniqueConstraint("entry_id", "position", name="uq_meet_result_dive_position"), MIGRATION_ONLY)
