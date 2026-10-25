"""Real-handler version of advisory_lock_probe.py; disposable local PG only.

MEDIA_STARTUP_TEST_DATABASE_URL must name calendar_test_* on loopback or a
Unix socket. MEDIA_STARTUP_PG_LOG optionally checks idle-in-tx kills too.
"""
import asyncio
from contextlib import ExitStack
import json
import os
from pathlib import Path
import time
import socket
import threading
import uvicorn
from uuid import uuid4

from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.api.v1 import media, ws_sync
from app.models.media import MediaAgent, MediaJob, MediaCacheEntry
from app.models.photos_asset import PhotosAsset
from app.schemas.media import MediaJobLeaseRequest
from app.services.media_jobs import create_or_reuse_media_job


@pytest.fixture
def pg(monkeypatch):
    dsn = os.getenv('MEDIA_STARTUP_TEST_DATABASE_URL')
    if not dsn:
        pytest.skip('local disposable Postgres not configured')
    url = make_url(dsn)
    assert url.get_backend_name() == 'postgresql'
    assert url.database.startswith('calendar_test_')
    assert url.host in (None, 'localhost', '127.0.0.1', '/tmp')
    engine = create_engine(dsn, pool_size=10, max_overflow=2,
        connect_args={'options': '-c idle_in_transaction_session_timeout=5000'})
    # Isolated schema, including all model dependencies used by real status.
    schema = 'probe_' + uuid4().hex
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA {schema}'))
    engine.dispose()
    engine = create_engine(dsn, pool_size=10, max_overflow=2, connect_args={
        'options': f'-c search_path={schema} -c idle_in_transaction_session_timeout=5000'})
    from app.models.photos_asset import PhotosAssetAgentIdentity
    from app.models.user_auth import AppUser, UserSession, UserDiverAccess
    from app.models.media_backbone import MediaRevision, MediaBlobLocation
    tables = {m.__table__ for m in (PhotosAsset, MediaJob, MediaCacheEntry,
        MediaAgent, PhotosAssetAgentIdentity, AppUser, UserSession, UserDiverAccess, MediaRevision, MediaBlobLocation)}
    pending = list(tables)
    while pending:
        for fk in pending.pop().foreign_keys:
            if fk.column.table not in tables:
                tables.add(fk.column.table)
                pending.append(fk.column.table)
    Base.metadata.create_all(engine, tables=list(tables))
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(ws_sync, 'SessionLocal', factory)
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), 'user_auth_enabled', False)
    monkeypatch.setattr(media, '_agent_auth', lambda *a, **kw: type('Agent', (), {'capabilities': ['poster']})())
    with factory() as db:
        agent = MediaAgent(id='probe-agent', hostname='probe', api_key_sha256='a' * 64,
            capabilities=['poster'], active=True, leasing_enabled=True)
        asset = PhotosAsset(video_uuid='probe-clip')
        db.add_all([agent, asset])
        db.flush()
        db.add(MediaJob(photos_asset_id=asset.id, media_key='probe-key', rendition='poster', status='queued'))
        db.commit()
    def dependency():
        with factory() as db:
            try:
                yield db
            finally:
                db.rollback()
    app = FastAPI()
    app.dependency_overrides[get_db] = dependency
    app.add_api_route('/status/{video_uuid}', media.get_media_status)
    # Real lease handler, bypassing only machine API-key dependency.
    def lease(db=Depends(get_db)):
        return media.lease_jobs(MediaJobLeaseRequest(agent_id='probe-agent', capabilities=['poster'], supports_lease_token=True), db, {})
    app.add_api_route('/lease', lease, methods=['POST'])
    app.include_router(ws_sync.socket_router)
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level='critical'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started:
        assert thread.is_alive() and time.monotonic() < deadline
        time.sleep(.01)
    app.state.probe_url = f'http://127.0.0.1:{listener.getsockname()[1]}'
    try:
        yield engine, factory, app
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
    engine.dispose()
    with engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
    engine.dispose()


def test_three_status_one_lease_under_one_second_no_idle_kills(pg):
    engine, factory, app = pg
    log = Path(os.environ['MEDIA_STARTUP_PG_LOG']) if os.getenv('MEDIA_STARTUP_PG_LOG') else None
    offset = log.stat().st_size if log else 0
    statements = []
    def capture(conn, cursor, statement, *args):
        statements.append(statement)
    async def burst():
        async with httpx.AsyncClient(base_url=app.state.probe_url) as client:
            started = time.perf_counter()
            responses = await asyncio.gather(*[client.get('/status/probe-clip') for _ in range(3)], client.post('/lease'))
            elapsed = time.perf_counter() - started
            assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
            assert elapsed < 1
            return round(elapsed * 1000, 2)
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        rounds = [asyncio.run(burst()) for _ in range(6)]
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    # Only the lease's outer lock + its re-entrant reclaim lock, per round.
    assert sum('pg_advisory_xact_lock' in s for s in statements) == 12
    assert engine.pool.checkedout() == 0
    with factory() as db:
        assert db.execute(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND state='idle in transaction' AND pid <> pg_backend_pid()" )).scalar() == 0
    if log:
        with log.open() as stream:
            stream.seek(offset)
            assert 'terminating connection due to idle-in-transaction timeout' not in stream.read()
    result = {'real_handlers_worst_ms_per_round': rounds, 'idle_in_tx_kills': 0 if log else 'log not configured'}
    print(json.dumps(result))
    output = os.getenv('MEDIA_STARTUP_PROBE_RESULT')
    if output:
        Path(output).write_text(json.dumps(result, indent=2) + '\n')


def test_websockets_return_pool_connections_before_disconnect(pg, monkeypatch):
    engine, factory, app = pg
    from app.config import get_settings
    from app.models.user_auth import AppUser
    from app.services.sessions import create_session
    monkeypatch.setattr(get_settings(), 'user_auth_enabled', True)
    with factory() as db:
        user = AppUser(email='probe@example.test', display_name='Probe', is_admin=True)
        db.add(user)
        db.commit()
        token, _ = create_session(db, user_id=user.id, ttl_seconds=3600)
    with TestClient(app) as client, ExitStack() as stack:
        client.cookies.set(get_settings().auth_cookie_name, token)
        for _ in range(4):
            ws = stack.enter_context(client.websocket_connect('/ws/sync'))
            ws.send_text('{"type":"heartbeat"}')
        assert engine.pool.checkedout() == 0


def test_interactive_creation_lock_timeout(pg):
    engine, factory, app = pg
    with factory() as holder, factory() as contender:
        holder.execute(text('SELECT pg_advisory_xact_lock(73125, 1)'))
        asset = contender.query(PhotosAsset).first()
        started = time.perf_counter()
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            create_or_reuse_media_job(contender, asset, 'poster', 'probe')
        assert exc.value.status_code == 503
        assert exc.value.headers == {'Retry-After': '1'}
        assert time.perf_counter() - started < 1
        contender.rollback()


def test_concurrent_cache_viewers_write_once_per_hour(pg, tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from app.config import get_settings
    from app.services.media_cache import get_playable_entry
    engine, factory, app = pg
    monkeypatch.setattr(get_settings(), 'media_cache_root', str(tmp_path))
    path = tmp_path / 'poster.jpg'
    path.write_bytes(b'poster')
    with factory() as db:
        asset = db.query(PhotosAsset).first()
        entry = MediaCacheEntry(photos_asset_id=asset.id, media_key='cache-key',
            rendition='poster', storage_path=str(path), size_bytes=6, status='ready')
        db.add(entry)
        db.commit()
        entry_id = entry.id
    writes = []
    def committed(db):
        if db.bind is engine:
            writes.append(1)
    from sqlalchemy.orm import Session
    event.listen(Session, 'after_commit', committed)
    def view(_):
        with factory() as db:
            snapshot = get_playable_entry(db, entry_id)
            assert not db.in_transaction()
            assert snapshot.id == entry_id and snapshot.storage_path == str(path)
            assert not db.in_transaction()
    try:
        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(view, range(15)))
        assert len(writes) == 1
    finally:
        event.remove(Session, 'after_commit', committed)


def test_member_auth_sql_runs_off_loop_and_keeps_db_info(pg, monkeypatch):
    from app.config import get_settings
    from app.models.user_auth import AppUser
    from app.services.sessions import create_session
    from app.services.dive_access import member_access_context
    engine, factory, app = pg
    monkeypatch.setattr(get_settings(), 'user_auth_enabled', True)
    with factory() as db:
        user = AppUser(email='context@example.test', display_name='Context', is_admin=True)
        db.add(user)
        db.commit()
        token, _ = create_session(db, user_id=user.id, ttl_seconds=3600)
    loop_threads, sql_threads = [], []
    seen_sessions = []
    @app.get('/api/v1/context', dependencies=[Depends(member_access_context)])
    async def context(db=Depends(get_db)):
        loop_threads.append(threading.get_ident())
        seen_sessions.append(db)
        return {'admin': db.info['member_access']['is_admin']}
    def capture(*args):
        sql_threads.append(threading.get_ident())
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        response = httpx.get(app.state.probe_url + '/api/v1/context',
            cookies={get_settings().auth_cookie_name: token})
        assert response.status_code == 200, response.text
        assert response.json() == {'admin': True}
        deadline = time.monotonic() + 1
        while engine.pool.checkedout() and time.monotonic() < deadline:
            time.sleep(.001)
        assert sql_threads and not set(sql_threads).intersection(loop_threads)
        assert engine.pool.checkedout() == 0
        assert 'member_access' not in seen_sessions[0].info
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
