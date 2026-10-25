"""Historical migration on real PostgreSQL (private disposable schema only).

The migration tables are created by the SHIPPED SQL file (applied twice:
idempotent), never by the ORM, so the controller is exercised against the
exact production DDL. Concurrency: parallel ticks, tick vs automatic
new-ingest queueing, pause vs lease, and a killed tick.
"""
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.skipif(not os.getenv("CALENDAR_TEST_DATABASE_URL"), reason="Disposable PostgreSQL required")

SQL = Path(__file__).resolve().parents[1] / "migrations" / "add_media_migration_runs.sql"
GIB = 1024**3


@pytest.fixture
def pg(monkeypatch):
    from app.database import Base
    import app.models  # noqa: F401
    from app.config import get_settings
    from app.services import automatic_packages as ap

    url = make_url(os.environ["CALENDAR_TEST_DATABASE_URL"])
    assert url.get_backend_name() == "postgresql" and (url.database or "").startswith("calendar_test_")
    url = url.set(drivername="postgresql+psycopg2")
    admin = create_engine(url)
    schema = "media_migration_" + uuid4().hex
    with admin.begin() as c:
        c.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, pool_size=10)

    @event.listens_for(engine, "connect")
    def set_schema(conn, _):
        with conn.cursor() as c:
            c.execute(f'SET search_path TO "{schema}"')
        conn.commit()

    try:
        wanted = {"dives", "media_jobs", "photos_assets", "media_agents", "media_blobs", "media_blob_locations",
                  "media_revisions", "media_derivatives", "media_cache_entries"}
        tables = {Base.metadata.tables[n] for n in wanted}
        while True:
            expanded = tables | {fk.column.table for t in tables for fk in t.foreign_keys}
            if expanded == tables:
                break
            tables = expanded
        assert not any(t.name.startswith("media_migration") for t in tables)
        Base.metadata.create_all(engine, tables=list(tables))
        ddl = SQL.read_text()
        for _ in range(2):  # idempotent re-apply
            with engine.begin() as c:
                c.exec_driver_sql(ddl)
        settings = get_settings()
        monkeypatch.setattr(settings, "media_web_packages_enabled", True)
        monkeypatch.setattr(settings, "media_web_packages_auto_ingest_enabled", True)
        monkeypatch.setattr(settings, "media_web_packages_auto_ingest_since",
                            (datetime.utcnow() - timedelta(minutes=5)).isoformat() + "Z")
        monkeypatch.setattr(ap.shutil, "disk_usage", lambda _: SimpleNamespace(free=36 * GIB))
        yield engine, sessionmaker(bind=engine, expire_on_commit=False)
    finally:
        engine.dispose()
        with admin.begin() as c:
            c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _seed(factory, n_clips):
    from app.models.dive import Dive
    from app.models.media import MediaAgent
    from app.models.session import Session as TrainingSession
    from backend.tests.test_media_migration import _source
    from backend.tests.test_web_package_fenced_slots_d3b2 import _asset, _fresh_capable_agent

    uuids = []
    with factory() as d:
        _fresh_capable_agent(d)
        d.get(MediaAgent, "mac-media-01").storage_status = {"package_resources": {
            "available": True, "scratch_free_bytes": 15 * GIB, "memory_pressure": "0"}}
        training = TrainingSession(date=datetime.utcnow().date())
        d.add(training)
        d.flush()
        for n in range(n_clips):
            uuid = str(uuid4()).upper()
            a = _asset(d, uuid=uuid)
            d.add(Dive(session_id=training.id, dive_datetime=datetime(2026, 1, 1) + timedelta(days=n),
                       dive_code="101A", performance="G", performance_numeric=3, height="3",
                       photos_asset_id=a.id, video_uuid=uuid))
            _source(d, uuid, f"pg-camera-{n}-{uuid}".encode())
            uuids.append(uuid)
        d.commit()
    return uuids


def _run_threads(n, target):
    gate = threading.Barrier(n)
    errors, results = [], []

    def run(i):
        try:
            gate.wait(timeout=10)
            results.append(target(i))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not any(t.is_alive() for t in threads)
    return results, errors


def test_shipped_sql_matches_models_and_enforces_one_open_run(pg):
    from app.models.media_migration import MediaMigrationItem, MediaMigrationRun

    engine, factory = pg
    insp = inspect(engine)
    for model in (MediaMigrationRun, MediaMigrationItem):
        db_cols = {c["name"] for c in insp.get_columns(model.__tablename__)}
        assert db_cols == set(model.__table__.columns.keys()), model.__tablename__
    with factory() as d:
        d.add(MediaMigrationRun(transform_version="v", budget_bytes=1, status="active"))
        d.commit()
        d.add(MediaMigrationRun(transform_version="v", budget_bytes=1, status="paused"))
        with pytest.raises(IntegrityError):
            d.commit()
        d.rollback()
        d.add(MediaMigrationRun(transform_version="v", budget_bytes=1, status="cancelled"))
        d.commit()
        d.add(MediaMigrationRun(transform_version="v", budget_bytes=1, status="active", priority=10))
        with pytest.raises(IntegrityError):  # background priority enforced by the DDL
            d.commit()


def test_parallel_ticks_admit_exactly_queue_depth(pg):
    from app.models.media import MediaJob
    from app.services import media_migration as mm

    engine, factory = pg
    _seed(factory, 6)
    with factory() as d:
        mm.start_run(d, budget_bytes=10 * GIB, queue_depth=2)
        d.commit()

    def tick(_):
        with factory() as d:
            out = mm.tick(d)
            d.commit()
            return out["status"]

    results, errors = _run_threads(4, tick)
    assert not errors, errors
    assert "ok" in results and set(results) <= {"ok", "busy"}
    for _ in range(3):  # later ticks never exceed the bound
        tick(0)
    with factory() as d:
        jobs = d.execute(select(MediaJob).where(MediaJob.rendition == "web_package")).scalars().all()
        assert len(jobs) == 2 and all(j.priority == 70 and j.max_attempts == 2 for j in jobs)


def test_tick_and_new_ingest_event_race_one_job_per_clip(pg):
    from app.models.media import MediaJob
    from app.services import automatic_packages as ap
    from app.services import media_migration as mm
    from app.services.derivative_publisher import resolve_canonical_source_revision

    engine, factory = pg
    (uuid,) = _seed(factory, 1)
    with factory() as d:
        from app.models.photos_asset import PhotosAsset

        asset = d.execute(select(PhotosAsset).where(PhotosAsset.video_uuid == uuid)).scalar_one()
        d.add(MediaJob(photos_asset_id=asset.id, media_key="legacy" + uuid[:20], rendition="proxy_720p",
                       status="ready", request_reason="new_captioned_ingestion"))
        rev, _, _ = resolve_canonical_source_revision(d, uuid)
        revision = rev.id
        mm.start_run(d, budget_bytes=10 * GIB, queue_depth=2)
        d.commit()

    def work(i):
        with factory() as d:
            if i == 0:
                mm.tick(d)
            else:
                ap.queue_after_verified_original(d, uuid, revision, "prod")
            d.commit()

    results, errors = _run_threads(2, work)
    assert not errors, errors
    with factory() as d:
        mm.tick(d)
        d.commit()
        jobs = d.execute(select(MediaJob).where(MediaJob.rendition == "web_package")).scalars().all()
        assert len(jobs) == 1
        from app.models.media_migration import MediaMigrationItem

        item = d.execute(select(MediaMigrationItem)).scalar_one()
        assert item.status == "queued" and item.media_job_id == jobs[0].id


def test_pause_racing_lease_never_cancels_a_claimed_job(pg, monkeypatch):
    from app.models.media import MediaJob
    from app.models.media_migration import MediaMigrationItem
    from app.schemas.media import MediaJobLeaseRequest
    from app.services import b2_presign
    from app.services import media_jobs as mj
    from app.services import media_migration as mm

    monkeypatch.setattr(b2_presign, "presign_get", lambda **kw: SimpleNamespace(url="https://b2.test/x"))
    engine, factory = pg
    _seed(factory, 2)
    with factory() as d:
        mm.start_run(d, budget_bytes=10 * GIB, queue_depth=1)
        mm.tick(d)
        d.commit()

    def work(i):
        with factory() as d:
            if i == 0:
                mj.lease_media_jobs(d, MediaJobLeaseRequest(agent_id="mac-media-01", capabilities=["web_package"],
                                                            max_jobs=1, supports_lease_token=True))
            else:
                mm.pause_run(d, "race")
            d.commit()

    results, errors = _run_threads(2, work)
    assert not errors, errors
    with factory() as d:
        job = d.execute(select(MediaJob).where(MediaJob.rendition == "web_package")).scalar_one()
        item = d.execute(select(MediaMigrationItem).where(MediaMigrationItem.media_job_id.is_not(None))).scalars().all()
        if job.status == "claimed":
            assert len(item) == 1 and item[0].status == "queued" and job.lease_token
        else:
            assert job.status == "cancelled" and item == [] and job.attempts == 0


def test_killed_tick_leaves_no_partial_state(pg):
    from app.models.media import MediaJob
    from app.models.media_migration import MediaMigrationItem
    from app.services import media_migration as mm

    engine, factory = pg
    _seed(factory, 3)
    with factory() as d:
        mm.start_run(d, budget_bytes=10 * GIB, queue_depth=2)
        d.commit()
    conn = engine.raw_connection()
    try:
        d = factory(bind=engine)
        mm.tick(d)
        # The process dies before COMMIT: terminate the backend holding locks.
        pid = d.execute(text("SELECT pg_backend_pid()")).scalar()
        with conn.cursor() as c:
            c.execute("SELECT pg_terminate_backend(%s)", (pid,))
        conn.commit()
        try:
            d.close()
        except Exception:
            pass
    finally:
        conn.close()
    engine.dispose()
    with factory() as d:
        assert d.execute(select(MediaJob).where(MediaJob.rendition == "web_package")).scalars().all() == []
        assert {i.status for i in d.execute(select(MediaMigrationItem)).scalars()} == {"pending"}
        out = mm.tick(d)
        d.commit()
        assert out["status"] == "ok" and out["admission"]["admitted"] == 2


def test_durable_poster_candidates_query_runs_on_postgres(pg):
    """The grid-poster candidate query (EXISTS + random order) is valid SQL."""
    from app.services import durable_poster_cache as dpc

    engine, factory = pg
    _seed(factory, 2)
    with factory() as d:
        assert dpc._candidates(d, 10) == []
