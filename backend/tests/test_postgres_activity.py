"""Execute the production UNION builder on PostgreSQL (the #96 regression)."""
import os
from datetime import datetime

import pytest
from sqlalchemy import create_engine, literal, union_all
from sqlalchemy.engine import make_url

from app.api.v1.users import _arm


@pytest.mark.skipif(not os.environ.get('CALENDAR_TEST_DATABASE_URL'), reason='Disposable PostgreSQL required')
def test_activity_union_executes_with_nullable_member_guest_and_comment_ids():
    url = make_url(os.environ['CALENDAR_TEST_DATABASE_URL'])
    assert url.get_backend_name() == 'postgresql' and (url.database or '').startswith('calendar_test_')
    engine = create_engine(url)
    stamp, number, empty = literal(datetime(2026, 10, 8)), literal(1), literal(None)
    query = union_all(
        _arm(0, 'dive_like', 'sent', stamp, number, number, number, number, empty, empty),
        _arm(1, 'comment_like', 'sent', stamp, number, number, number, number, empty, empty),
        _arm(2, 'comment', 'received', stamp, number, number, number, empty, number, number),
    )
    try:
        with engine.connect() as conn:
            rows = conn.execute(query).mappings().all()
        assert len(rows) == 3
        assert [r['actor_guest_id'] for r in rows] == [None, None, 1]
        assert [r['actor_user_id'] for r in rows] == [1, 1, None]
        assert [r['comment_id'] for r in rows] == [None, None, 1]
    finally:
        engine.dispose()
