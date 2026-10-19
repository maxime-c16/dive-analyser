"""Shared launch switch for API, signup and scheduled workers.

An installed singleton overrides the legacy environment default. No process-local
cache: turning the calendar off also stops subsequent worker sends.
"""
from datetime import datetime, timedelta

from sqlalchemy import inspect
from app.config import get_settings
from app.models.calendar import CalendarLaunchControl


def installed(db):
    return inspect(db.connection()).has_table(CalendarLaunchControl.__tablename__)


def enabled(db):
    if not installed(db):
        return bool(get_settings().calendar_enabled)
    row = db.get(CalendarLaunchControl, 1, populate_existing=True)
    return bool(row.enabled) if row and row.enabled is not None else bool(get_settings().calendar_enabled)


def probe_ready(row, now=None):
    now = now or datetime.utcnow()
    return bool(row and row.probe_count >= 2 and row.last_probe_at and
                now - row.last_probe_at < timedelta(minutes=15))


def record_probe(db, now):
    if not installed(db):
        return
    row = db.query(CalendarLaunchControl).filter_by(id=1).with_for_update().one_or_none()
    if row is None:
        return
    # One observation per scheduled minute; repeated manual calls cannot count
    # as two scheduled observations. Installation still needs operator evidence.
    if row.last_probe_at is None or now - row.last_probe_at >= timedelta(seconds=45):
        row.probe_count = (row.probe_count + 1 if row.last_probe_at and
                           now - row.last_probe_at < timedelta(minutes=15) else 1)
        row.last_probe_at = now
        db.commit()
