"""Full-scope ranking equivalence and bounded ORM loading on SQLite and PostgreSQL."""
import os
import random
from datetime import datetime, timedelta
from statistics import median
from uuid import uuid4

import pytest
from sqlalchemy import Float, create_engine, event, literal, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema

from app.database import Base
from app.models.dive import Dive
from app.models.diver import Diver
from app.models.session import Session as TrainingSession
from app.models.user_auth import AppUser, UserDiverAccess
from app.services.community_leaderboard import (
    BOARD_SIZE,
    _ranking_statement,
    _round_half_even_sql,
    leaderboard,
)
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


@pytest.mark.parametrize('raw,expected', [
    # Positive and negative ties, even and odd: SQL must use ties-to-even
    # like the previous Python _round, not round-half-away-from-zero.
    (1.125, 1.12), (-1.125, -1.12), (2.125, 2.12), (-2.125, -2.12),
    (1.375, 1.38), (-1.375, -1.38), (0.125, 0.12), (-0.125, -0.12),
    (0.625, 0.62), (-0.625, -0.62), (3.625, 3.62), (-3.625, -3.62),
    # Ordinary values behave like round() on both dialects.
    (1.135, 1.14), (1.005, 1.0), (1.12, 1.12), (-1.12, -1.12),
    (2.5, 2.5), (-2.5, -2.5), (0.0, 0.0),
    (10.0, 10.0), (2.75, 2.75), (7.0, 7.0), (4.5, 4.5), (5.625, 5.62),
    (-1.13, -1.13), (1.13, 1.13),
])
def test_round_half_even_sql_matches_python(board_db, raw, expected):
    assert round(raw, 2) == expected
    value = board_db.execute(select(_round_half_even_sql(literal(raw, Float)))).scalar()
    assert float(value) == expected


@pytest.mark.parametrize('period,previous_days,expected_streak', [('week', 9, 2), ('month', 40, 1)])
def test_progress_delta_ties_use_previous_rounding(board_db, period, previous_days, expected_streak):
    """A delta of 1.125 displays 1.12 (not 1.13), positive and negative.

    Regression test for the review finding: SQL round(..., 2) rounds ties
    away from zero while the previous Python _round uses ties-to-even. All
    fixtures use exact-binary scores, so SQLite and PostgreSQL must both
    match Python round(). Progress ranking reads the same SQL expression as
    the display (m.delta), so the two can never disagree; the tie member
    below sits exactly on the top-10 boundary (progress rank 10), which
    locks that ranking behavior in place.
    """
    db = board_db
    now = datetime(2026, 10, 28, 12)
    training = TrainingSession(date=now.date())
    db.add(training)
    db.flush()

    def dives(diver_id, stamp, grades):
        for grade, phase1, phase2 in grades:
            db.add(Dive(session_id=training.id, diver_id=diver_id, dive_datetime=stamp,
                        dive_code='101B', height='3m', performance=grade or '', performance_numeric=0,
                        phase1_performance=phase1, phase2_performance=phase2,
                        visibility='public', is_lineup=False))

    recent_stamp, previous_stamp = now - timedelta(days=2), now - timedelta(days=previous_days)
    # (recent grades, previous grades, expected delta): 5.625/4.5-style mixes.
    two_phase_gm = ('G', 'G', 'M')  # 7*0.45 + 4.5*0.55 = 5.625
    two_phase_gb = ('G', 'G', 'B')  # 7*0.45 + 2*0.55 = 4.25
    plans = {
        # Six high-progress fillers occupying progress ranks 1-6.
        **{f'fill{i}': ([('P', None, None)] * 5, [('F', None, None)] * 5, 10.0) for i in range(6)},
        'high': ([('G', None, None)] * 5, [two_phase_gb] * 5, 2.75),
        'high2': ([('G', None, None)] * 5, [two_phase_gb] * 5, 2.75),
        'odd_tie': ([('G', None, None)] * 5, [two_phase_gm] * 5, 1.38),
        'tie': ([two_phase_gm] * 5, [('M', None, None)] * 5, 1.12),
        'neg_tie': ([('M', None, None)] * 8, [two_phase_gm] * 5, -1.12),
    }
    ids = {}
    # fix creation order so the tie member is last in uid order: it must not
    # leak into the top 10 through the attempts/codes/streak boards, only
    # through progress rank 10.
    for index, name in enumerate(['neg_tie'] + [f'fill{i}' for i in range(6)] + ['high', 'high2', 'odd_tie', 'tie']):
        recent, previous, _expected = plans[name]
        user = AppUser(email=f'tie-{name}@example.test', display_name=f'Tie {name}', role='friend')
        diver = Diver(display_name=f'Tie {name}', canonical_name=f'tie-{name}')
        db.add_all([user, diver])
        db.flush()
        db.add(UserDiverAccess(user_id=user.id, diver_id=diver.id, access_kind='OWNER'))
        dives(diver.id, recent_stamp, recent)
        dives(diver.id, previous_stamp, previous)
        ids[name] = user.id
    db.flush()
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
        board = leaderboard(db, visible_dive_clause(()), period, now, None)
    finally:
        event.remove(db, 'loaded_as_persistent', on_load)
        event.remove(db.bind, 'before_cursor_execute', on_query)

    by_id = {row['user_id']: row for row in board['members']}
    assert set(by_id) == set(ids.values()), 'every tie-board member stays selected in SQL'
    for name, (_recent, _previous, expected) in plans.items():
        assert by_id[ids[name]]['delta'] == expected, (name, by_id[ids[name]]['delta'])
    assert by_id[ids['tie']]['median'] == round(5.625, 2)
    assert by_id[ids['tie']]['attempts'] == 5
    assert by_id[ids['neg_tie']]['attempts'] == 8
    assert by_id[ids['neg_tie']]['streak_weeks'] == expected_streak
    # Ranking still happens in SQL before profiles are materialized.
    assert len(loaded) <= 4 * BOARD_SIZE + 1
    assert len(queries) == 1

    # The ranked progress value is the displayed value: the tie member sits
    # exactly on the top-10 boundary. Rank assertions use the same statement
    # the leaderboard executes (white-box: ranking is the fixed behavior).
    ranks = {row._mapping['uid']: row._mapping['rank_2']
             for row in db.execute(_ranking_statement(visible_dive_clause(()), period, now, None)).all()}
    assert ranks[ids['tie']] == 10
    assert ranks[ids['neg_tie']] == 11
