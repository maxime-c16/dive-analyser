"""Calendar identity and default attendance for shared recordings.

All instants are naive UTC; effective membership dates use the event timezone.
Legacy interested/maybe answers carry no attendance meaning and remain intact.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo
from email.message import EmailMessage
import logging

from sqlalchemy import and_, exists, or_, case, func

from app.models.calendar import (Calendar, CalendarEvent, EventOccurrence, ClubMembership,
    TrainingGroupMembership, OccurrenceAbsenceReport, OccurrenceInterest)
from app.models.session import Session as TrainingSession
from app.models.user_auth import AppUser

logger = logging.getLogger(__name__)
MARGIN = timedelta(minutes=30)
# Group fan-out bounds: members per batch and batches per invocation. The
# persisted account cursor resumes the rest on a later pass.
_NOTIFY_BATCH_SIZE = 100
_NOTIFY_MAX_BATCHES = 5


def matching_occurrence(db, recorded_at):
    from app.services.calendar_launch import enabled
    if not enabled(db):
        return None
    # Only published, timed group training can own an automatic recording.
    return db.query(EventOccurrence).join(CalendarEvent, CalendarEvent.id == EventOccurrence.event_id).join(Calendar, Calendar.id == CalendarEvent.calendar_id).filter(
        Calendar.kind == 'group', CalendarEvent.event_type == 'training',
        CalendarEvent.status == 'published', EventOccurrence.status == 'scheduled',
        EventOccurrence.is_all_day.is_(False), Calendar.archived_at.is_(None),
        EventOccurrence.window_start <= recorded_at + MARGIN,
        EventOccurrence.window_end > recorded_at - MARGIN,
    ).order_by(case((and_(EventOccurrence.window_start <= recorded_at,
                          EventOccurrence.window_end > recorded_at), 0), else_=1),
               func.abs(func.extract('epoch', EventOccurrence.window_start) - recorded_at.replace(tzinfo=timezone.utc).timestamp()),
               EventOccurrence.id).first()


def occurrence_members(db, occurrence_id, *, include_absent=False):
    """SQL full-scope eligibility; callers count or keyset-page before loading."""
    row = db.query(EventOccurrence, CalendarEvent, Calendar).join(CalendarEvent, CalendarEvent.id == EventOccurrence.event_id).join(Calendar, Calendar.id == CalendarEvent.calendar_id).filter(
        EventOccurrence.id == occurrence_id).first()
    if row is None:
        return db.query(AppUser).filter(False)
    o, e, c = row
    if e.event_type != 'training' or c.club_id is None or e.audience not in ('group', 'club'):
        return db.query(AppUser).filter(False)
    day = o.window_start.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(e.timezone)).date()
    q = db.query(AppUser).filter(AppUser.is_active.is_(True), exists().where(and_(
        ClubMembership.club_id == c.club_id, ClubMembership.user_id == AppUser.id,
        ClubMembership.status == 'active', ClubMembership.ended_at.is_(None))))
    if e.audience == 'group':
        q = q.filter(exists().where(and_(TrainingGroupMembership.user_id == AppUser.id,
            TrainingGroupMembership.group_id == c.training_group_id,
            TrainingGroupMembership.effective_from <= day,
            or_(TrainingGroupMembership.effective_to.is_(None), TrainingGroupMembership.effective_to > day))))
    if not include_absent:
        q = q.filter(~exists().where(and_(OccurrenceAbsenceReport.user_id == AppUser.id,
            OccurrenceAbsenceReport.occurrence_id == o.id, OccurrenceAbsenceReport.withdrawn_at.is_(None))),
            ~exists().where(and_(OccurrenceInterest.user_id == AppUser.id,
                OccurrenceInterest.occurrence_id == o.id, OccurrenceInterest.state == 'declined')))
    return q


def session_titles(db, ids):
    if not ids:
        return {}
    rows = db.query(EventOccurrence, CalendarEvent).join(CalendarEvent).filter(EventOccurrence.id.in_(ids)).all()
    weekdays = ('lun.', 'mar.', 'mer.', 'jeu.', 'ven.', 'sam.', 'dim.')
    result = {}
    for o, e in rows:
        local = o.window_start.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(e.timezone))
        clock = f'{local.hour}h' + (f'{local.minute:02}' if local.minute else '')
        result[o.id] = f'{e.title} {weekdays[local.weekday()]} {clock}' + (f' · {o.venue_name or e.venue_name}' if o.venue_name or e.venue_name else '')
    return result


def notify_session(db, video):
    """One inbox per session/member, in 100-account transactions.

    The cursor and inbox commit together under the session lock. Duplicate
    B2 events and later videos resume safely without re-notifying. External
    push/email are best-effort, at-most-once attempts after commit. Work per
    invocation is capped at _NOTIFY_MAX_BATCHES batches; the persisted
    cursor lets a later pass (reconciliation resume or a new arrival)
    continue where this one stopped.
    """
    from app.services import notification_service, push_service, email_service
    from app.config import get_settings
    session_id = video.session_id
    for _ in range(_NOTIFY_MAX_BATCHES):
        training = db.query(TrainingSession).filter_by(id=session_id).with_for_update().populate_existing().one()
        if training.calendar_occurrence_id is None:
            return False
        if training.calendar_notified_at is not None:
            db.commit()
            return True
        users = occurrence_members(db, training.calendar_occurrence_id).filter(
            AppUser.id > training.calendar_notify_cursor).order_by(AppUser.id).limit(_NOTIFY_BATCH_SIZE).all()
        title = session_titles(db, [training.calendar_occurrence_id])[training.calendar_occurrence_id]
        path = f'/sessions/shared/{session_id}'
        pending = []
        for user in users:
            row = notification_service.stage(db, user_id=user.id, type='session_video', title='Nouvelle séance en ligne', body=title)
            row.session_id = session_id
            pending.append((SimpleNamespace(id=row.id, user_id=row.user_id, type=row.type,
                title=row.title, body=row.body, dive_id=None, conversation_id=None),
                user.email, user.session_email_enabled))
        if users:
            training.calendar_notify_cursor = users[-1].id
        if len(users) < _NOTIFY_BATCH_SIZE:
            training.calendar_notified_at = datetime.utcnow()
        db.commit()
        for row, email, email_on in pending:
            row._push_payload = {'title': row.title, 'body': title, 'url': path}
            try:
                push_service.fanout_for_rows(db, [row])
            except Exception as exc:
                db.rollback()
                logger.warning('Session push failed (%s)', type(exc).__name__)
            if email_on and email_service.is_email_configured():
                msg = EmailMessage()
                msg['Subject'] = 'Nouvelle séance en ligne'
                msg['From'] = get_settings().email_from
                msg.set_content(title + '\n' + get_settings().app_public_url.rstrip('/') + path)
                email_service.send_message(msg, email)
        if len(users) < _NOTIFY_BATCH_SIZE:
            return True
    # Batch cap reached with members remaining: cursor is committed, a later
    # pass resumes. Report the group path as active.
    return True
