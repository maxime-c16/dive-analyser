"""Unread inbox probes on real PostgreSQL (private disposable schema).

The unread_only page and its has_more probe carry the `read_at IS NULL`
keyset (notification_service). This test applies the SHIPPED DDL
(add_notifications.sql, then the partial-index migration twice to prove
idempotence), seeds a grown READ history plus a small unread window, and
asserts both probe shapes plan against the partial index — i.e. the
LIMIT-capped page answers out of the unread subset instead of filtering
the whole read history.
"""
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url

pytestmark = pytest.mark.skipif(
    not os.getenv("CALENDAR_TEST_DATABASE_URL"), reason="Disposable PostgreSQL required"
)

NOTIFICATIONS_SQL = Path(__file__).resolve().parents[1] / "migrations" / "add_notifications.sql"
INDEX_SQL = Path(__file__).resolve().parents[1] / "migrations" / "add_notifications_unread_index.sql"

USER_ID = 4
# Keyset probes exactly mirror notification_service: (created_at, id) tuples
# over unread rows. The anchor lands past the seeded unread window.
PAGE_SQL = f"""
SELECT id FROM notifications
WHERE user_id = {USER_ID}
  AND (created_at < timestamp '2026-11-01 10:00:00'
       OR (created_at = timestamp '2026-11-01 10:00:00' AND id < 100000))
  AND read_at IS NULL
ORDER BY created_at DESC, id DESC
LIMIT 50
"""
HAS_MORE_SQL = f"""
SELECT id FROM notifications
WHERE user_id = {USER_ID}
  AND (created_at < timestamp '2026-11-01 10:00:00'
       OR (created_at = timestamp '2026-11-01 10:00:00' AND id < 100000))
  AND read_at IS NULL
LIMIT 1
"""


@pytest.fixture
def pg():
    from app.database import Base
    import app.models  # noqa: F401

    url = make_url(os.environ["CALENDAR_TEST_DATABASE_URL"])
    assert url.get_backend_name() == "postgresql" and (url.database or "").startswith("calendar_test_")
    url = url.set(drivername="postgresql+psycopg2")
    admin = create_engine(url)
    schema = f"notifications_unread_{uuid4().hex}"
    with admin.begin() as c:
        c.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, isolation_level="AUTOCOMMIT")

    @event.listens_for(engine, "connect")
    def set_schema(conn, _):
        c = conn.cursor()
        c.execute(f'SET search_path TO "{schema}"')
        conn.commit()

    try:
        # The shipped notifications DDL carries FKs to dives/sessions/
        # conversations/app_users: create their real transitive closure from
        # the ORM metadata first, then let the shipped migration create the
        # notifications tables. (Postgres validates FK targets at CREATE
        # TABLE; a user-only closure failed setup with a missing relations.)
        tables = {Base.metadata.tables["notifications"], Base.metadata.tables["app_users"]}
        while True:
            expanded = tables | {fk.column.table for t in tables for fk in t.foreign_keys}
            if expanded == tables:
                break
            tables = expanded
        tables.discard(Base.metadata.tables["notifications"])
        Base.metadata.create_all(engine, tables=list(tables))
        for ddl_path, passes in ((NOTIFICATIONS_SQL, 2), (INDEX_SQL, 2)):
            ddl = ddl_path.read_text()
            for _ in range(passes):
                with engine.connect() as c:
                    c.exec_driver_sql(ddl)
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as c:
            c.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


def _seed(engine):
    with engine.begin() as c:
        # The real app_users contract: SQLAlchemy renders NO server default
        # for python-side defaults, and a plain INSERT bypasses the ORM —
        # every NOT NULL column without a DEFAULT is supplied (role, both
        # flags, both timestamps), as the CI NotNullViolation on `role`
        # demonstrated. If the model gains another such column, this seed
        # must list it too (re-compile the CREATE TABLE when editing).
        c.execute(text(
            "INSERT INTO app_users (id, email, display_name, is_admin, role, is_active, created_at, updated_at) "
            f"VALUES ({USER_ID}, 'probe@example.com', 'Probe', TRUE, 'owner', TRUE, NOW(), NOW())"
        ))
        # 30 unread rows inside the anchor range, plus 2000 read rows of the
        # kind the probes must not scroll through.
        c.execute(text(
            "INSERT INTO notifications (user_id, type, title, read_at, created_at) "
            f"SELECT {USER_ID}, 'milestone', 'Unread #' || g, NULL, "
            "timestamp '2026-11-01 09:00:00' - (g - 1) * interval '1 minute' "
            "FROM generate_series(1, 30) AS g"
        ))
        c.execute(text(
            "INSERT INTO notifications (user_id, type, title, read_at, created_at) "
            f"SELECT {USER_ID}, 'milestone', 'Read #' || g, "
            "timestamp '2026-11-01 09:00:00', "
            "timestamp '2026-09-01 09:00:00' - g * interval '1 minute' "
            "FROM generate_series(1, 2000) AS g"
        ))


def _plans_use_partial_index(engine, sql) -> bool:
    with engine.connect() as c:
        raw = c.exec_driver_sql(f"EXPLAIN (FORMAT JSON) {sql}").fetchall()[0][0]
    plan_text = json.dumps(json.loads(raw))
    return "ix_notifications_user_unread_recent" in plan_text


def test_unread_keyset_probes_ride_the_partial_index(pg):
    _seed(pg)
    assert _plans_use_partial_index(pg, PAGE_SQL)
    assert _plans_use_partial_index(pg, HAS_MORE_SQL)
