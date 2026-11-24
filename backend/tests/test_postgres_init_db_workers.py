"""Concurrent worker startups must not race on CREATE TABLE.

uvicorn runs init_db() in every worker. A deploy that adds a model table
makes each worker try to create it; without serialization the losers fail
with a duplicate-object error and that worker never starts.
"""
import os
import threading
from uuid import uuid4

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, text
from sqlalchemy.orm import declarative_base

pytestmark = pytest.mark.skipif(
    not os.getenv("CALENDAR_TEST_DATABASE_URL"), reason="Disposable PostgreSQL required"
)


def test_concurrent_init_db_creates_new_tables_once(monkeypatch):
    from app import database

    schema = f"initdb_{uuid4().hex[:10]}"
    admin = create_engine(os.environ["CALENDAR_TEST_DATABASE_URL"])
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        os.environ["CALENDAR_TEST_DATABASE_URL"],
        connect_args={"options": f"-csearch_path={schema}"},
        pool_size=8,
    )
    base = declarative_base(metadata=MetaData())
    for index in range(6):
        Table(f"new_table_{index}", base.metadata, Column("id", Integer, primary_key=True))
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "Base", base)

    errors, start = [], threading.Barrier(4)

    def worker():
        start.wait()
        try:
            database.init_db()
        except Exception as exc:  # pragma: no cover - the failure being proven
            errors.append(type(exc).__name__)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    try:
        [thread.start() for thread in threads]
        [thread.join(30) for thread in threads]
        assert errors == []
        with engine.connect() as connection:
            count = connection.execute(text(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema = :s"), {"s": schema}).scalar()
        assert count == 6
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
