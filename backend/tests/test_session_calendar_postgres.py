"""Run only against a dedicated disposable PostgreSQL database."""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.config import get_settings
from app.models.calendar import OccurrenceInterest, OccurrenceAbsenceReport
from app.models.notification import Notification
from app.models.session_video import SessionVideo
from app.models.user_auth import AppUser
from app.services import session_videos as service
from tests.test_session_calendar import setup_group

URL = os.environ.get('SESSION_CALENDAR_TEST_DATABASE_URL')
pytestmark = pytest.mark.skipif(not URL, reason='Dedicated PostgreSQL database required')


def test_migration_preserves_answers_and_concurrent_first_arrival(monkeypatch):
    assert make_url(URL).database.startswith('calendar_test_'), 'Disposable calendar_test_* database required'
    engine = create_engine(URL)
    with engine.begin() as conn:
        conn.exec_driver_sql('DROP SCHEMA public CASCADE; CREATE SCHEMA public')
    from tests.test_calendar_domain import _legacy_tables
    names = {'session_videos', 'clubs', 'club_memberships', 'training_groups', 'training_group_memberships',
             'calendars', 'calendar_events', 'event_occurrences', 'occurrence_interests', 'occurrence_absence_reports'}
    tables = set(_legacy_tables()) | {Base.metadata.tables[name] for name in names}
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.sorted_tables if t in tables])
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(get_settings(), 'calendar_enabled', True)
    pushes, emails = [], []
    monkeypatch.setattr('app.services.push_service.fanout_for_rows', lambda db, rows: pushes.extend(r.user_id for r in rows))
    monkeypatch.setattr('app.services.email_service.is_email_configured', lambda: True)
    monkeypatch.setattr('app.services.email_service.send_message', lambda msg, address: emails.append(address) or (True, ''))
    with factory() as db:
        users = {n: AppUser(email=f'{n}@test.invalid', display_name=n, role='diver', session_email_enabled=n!='bob')
                 for n in ('alice', 'bob', 'viewer')}
        db.add_all(users.values()); db.commit()
        o = setup_group(db, users); oid = o.id
        db.add_all([OccurrenceInterest(occurrence_id=oid, user_id=users['alice'].id, state='interested'),
                    OccurrenceInterest(occurrence_id=oid, user_id=users['bob'].id, state='maybe'),
                    OccurrenceAbsenceReport(occurrence_id=oid, user_id=users['viewer'].id)])
        db.commit()
        owner_id = users['alice'].id
    # Reconstruct the old day uniqueness and absence of new columns before
    # exercising the actual SQL twice, with production-shaped RSVP rows.
    with engine.begin() as conn:
        conn.exec_driver_sql('ALTER TABLE sessions DROP COLUMN calendar_occurrence_id, DROP COLUMN calendar_notify_cursor, DROP COLUMN calendar_notified_at')
        conn.exec_driver_sql('ALTER TABLE notifications DROP COLUMN session_id')
        conn.exec_driver_sql('DROP INDEX ix_sessions_date')
        conn.exec_driver_sql('CREATE UNIQUE INDEX ix_sessions_date ON sessions(date)')
    migration = (Path(__file__).parents[1]/'migrations/add_session_calendar.sql').read_text()
    drop_legacy = (Path(__file__).parents[1]/'migrations/add_session_calendar_drop_legacy.sql').read_text()
    with engine.connect() as conn:
        conn.exec_driver_sql(migration)
        conn.exec_driver_sql(migration)
        conn.exec_driver_sql(drop_legacy)
        conn.exec_driver_sql(drop_legacy)
        conn.commit()
    gate = Barrier(2)
    def arrive(_):
        with factory() as db:
            gate.wait(timeout=10)
            training = service.training_session_for(db, date(2026, 10, 17), datetime(2026, 10, 17, 11, 5))
            sid = training.id
            db.commit()
            return sid
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(arrive, range(2)))
    assert ids[0] == ids[1]
    with factory() as db:
        video = SessionVideo(bucket='test', object_key='inbox/test.MOV', owner_user_id=owner_id, session_id=ids[0], status='ready')
        db.add(video); db.commit(); vid = video.id
    gate = Barrier(2)
    def notify(_):
        with factory() as db:
            gate.wait(timeout=10)
            service._notify_once(db, vid)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(notify, range(2)))
    with factory() as db:
        rows = db.query(Notification).filter_by(session_id=ids[0]).all()
        assert len(rows) == len(pushes) == 2
        assert len(emails) == 1
        assert {r.state for r in db.query(OccurrenceInterest)} == {'interested', 'maybe'}
    engine.dispose()
