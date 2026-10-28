"""Full-scope ranking equivalence and bounded ORM loading on SQLite and PostgreSQL."""
import os
import random
from datetime import datetime, timedelta
from statistics import median
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema

from app.database import Base
from app.models.dive import Dive
from app.models.diver import Diver
from app.models.session import Session as TrainingSession
from app.models.user_auth import AppUser, UserDiverAccess
from app.services.community_leaderboard import BOARD_SIZE, leaderboard
from app.services.dive_access import visible_dive_clause
from app.services.performance_scoring import attempt_score_10


@pytest.fixture(params=['sqlite', 'postgres'])
def board_db(request):
    if request.param == 'postgres':
        url = os.environ.get('CALENDAR_TEST_DATABASE_URL')
        if not url:
            pytest.skip('Disposable PostgreSQL required')
        parsed = make_url(url)
        assert parsed.get_backend_name() == 'postgresql' and (parsed.database or '').startswith('calendar_test_')
    else:
        url = 'sqlite:///:memory:'
    engine = create_engine(url)
    with engine.connect() as connection:
        transaction = connection.begin()
        if request.param == 'postgres':
            # Transaction-local schema creation: rollback removes only this test's
            # schema; no application tables or other tests' schemas are reset.
            schema = f'review_board_{uuid4().hex}'
            connection.execute(CreateSchema(schema))
            connection = connection.execution_options(schema_translate_map={None: schema})
        required = {model.__table__ for model in (AppUser, UserDiverAccess, Diver, Dive, TrainingSession)}
        pending = list(required)
        while pending:
            for fk in pending.pop().foreign_keys:
                table = fk.column.table
                if table not in required:
                    required.add(table)
                    pending.append(table)
        Base.metadata.create_all(connection, tables=list(required))
        db = Session(connection)
        try:
            yield db
        finally:
            db.close()
            transaction.rollback()
    engine.dispose()


def reference_streak(times, now):
    weeks = {(stamp.date() - timedelta(days=stamp.weekday())) for stamp in times}
    cursor = now.date() - timedelta(days=now.weekday())
    if cursor not in weeks:
        cursor -= timedelta(weeks=1)
    result = 0
    while cursor in weeks and result < 26:
        result += 1
        cursor -= timedelta(weeks=1)
    return result


@pytest.mark.parametrize('period,days', [('week', 7), ('month', 30)])
def test_ranks_complete_scope_before_materializing_members(board_db, period, days):
    db = board_db
    now = datetime(2026, 10, 28, 12)
    training = TrainingSession(date=now.date())
    db.add(training)
    db.flush()
    rng = random.Random(537)
    expected = {}
    for index in range(72):
        user = AppUser(email=f'board-{index}@example.test', display_name=f'Board {index}', role='friend')
        diver = Diver(display_name=f'Board {index}', canonical_name=f'board-{index}')
        db.add_all([user, diver])
        db.flush()
        db.add(UserDiverAccess(user_id=user.id, diver_id=diver.id, access_kind='OWNER'))
        attempts = []
        for number in range(36):
            stamp = now - timedelta(days=rng.randrange(65), hours=number)
            grade = rng.choice(['P', 'G', 'M', 'B', 'F'])
            phase1, phase2 = rng.choice([(None, None), ('P', 'B'), ('G', 'M')])
            code = f'10{rng.randrange(1, 5)}B'
            public, lineup = number % 7 != 0, number % 13 == 0
            db.add(Dive(session_id=training.id, diver_id=diver.id, dive_datetime=stamp,
                        dive_code=code, height='3m', performance=grade or '', performance_numeric=0,
                        phase1_performance=phase1, phase2_performance=phase2,
                        visibility='public' if public else 'private', is_lineup=lineup))
            if public and not lineup:
                attempts.append((stamp, code, attempt_score_10(grade, phase1, phase2) if grade else None))
        current = [a for a in attempts if a[0] >= now - timedelta(days=days)]
        previous = [a for a in attempts if now - timedelta(days=2 * days) <= a[0] < now - timedelta(days=days)]
        scores = [a[2] for a in current if a[2] is not None]
        old_scores = [a[2] for a in previous if a[2] is not None]
        streak = reference_streak([a[0] for a in attempts], now)
        if current or streak:
            expected[user.id] = {
                'user_id': user.id, 'attempts': len(current), 'sessions': int(bool(current)),
                'codes': len({a[1] for a in current}),
                'median': round(median(scores), 2) if scores else None,
                'delta': round(median(scores) - median(old_scores), 2) if min(len(scores), len(old_scores)) >= 5 else None,
                'streak_weeks': streak,
                'last_attempt_at': max(a[0] for a in current).isoformat() if current else None,
            }
    viewer = AppUser(email='zero-viewer@example.test', display_name='Zero viewer', role='friend')
    db.add(viewer)
    db.flush()
    viewer_id = viewer.id
    expected[viewer_id] = dict(user_id=viewer_id, attempts=0, sessions=0, codes=0,
                               median=None, delta=None, streak_weeks=0, last_attempt_at=None)
    db.expunge_all()
    loaded, queries = [], []
    def on_load(_session, row):
        if isinstance(row, AppUser):
            loaded.append(row.id)
    def on_query(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith(('SELECT', 'WITH')):
            queries.append(statement)
    event.listen(db, 'loaded_as_persistent', on_load)
    event.listen(db.bind, 'before_cursor_execute', on_query)
    try:
        board = leaderboard(db, visible_dive_clause(()), period, now, viewer_id)
    finally:
        event.remove(db, 'loaded_as_persistent', on_load)
        event.remove(db.bind, 'before_cursor_execute', on_query)
    keep = {viewer_id}
    for field in ('attempts', 'codes', 'delta', 'streak_weeks'):
        ranked = sorted(expected.values(), key=lambda row: (-(row[field] or 0), -row['attempts'], row['user_id']))
        keep.update(row['user_id'] for row in ranked[:BOARD_SIZE])
    assert {row['user_id'] for row in board['members']} == keep
    for row in board['members']:
        for field, value in expected[row['user_id']].items():
            assert row[field] == value, (row['user_id'], field, row[field], value)
    assert len(loaded) <= 4 * BOARD_SIZE + 1
    assert len(queries) == 1
    assert [row['user_id'] for row in board['members']] == sorted(keep, key=lambda uid: (-expected[uid]['attempts'], uid))
