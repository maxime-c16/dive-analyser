"""Lot 1: read-only status, bounded cache writes, socket lifetime and timings."""
from datetime import datetime, timedelta
import inspect

import pytest
from sqlalchemy import event

from app.api.v1 import media, ws_sync
from app.models.media import MediaCacheEntry
from app.models.photos_asset import PhotosAsset
from app.services import media_jobs
from app.services.media_cache import get_playable_entry


def test_status_selectors_never_reclaim(test_db, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("read path tried to reclaim jobs")
    monkeypatch.setattr(media_jobs, 'reclaim_expired_media_jobs', forbidden)
    asset = PhotosAsset(video_uuid='read-only-status')
    test_db.add(asset)
    test_db.commit()
    assert media_jobs.latest_active_job_for_asset(test_db, asset.id) is None
    assert media_jobs.active_job_for_key(test_db, 'absent') is None
    assert media.get_media_status(asset.video_uuid, test_db).video_uuid == asset.video_uuid


def test_cache_access_only_commits_hourly(test_db, tmp_path, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), 'media_cache_root', str(tmp_path))
    path = tmp_path / 'poster.jpg'
    path.write_bytes(b'poster')
    asset = PhotosAsset(video_uuid='cache-access')
    test_db.add(asset)
    test_db.flush()
    entry = MediaCacheEntry(photos_asset_id=asset.id, media_key='cache-access:poster',
        rendition='poster', storage_path=str(path), status='ready', storage_backend='local_fs', size_bytes=6)
    test_db.add(entry)
    test_db.commit()
    commits = []
    def committed(db):
        commits.append(1)
    event.listen(test_db, 'after_commit', committed)
    try:
        for _ in range(15):
            get_playable_entry(test_db, entry.id)
        assert len(commits) == 1
        entry.last_accessed_at = datetime.utcnow() - timedelta(hours=2)
        test_db.commit()
        commits.clear()
        get_playable_entry(test_db, entry.id)
        assert len(commits) == 1
    finally:
        event.remove(test_db, 'after_commit', committed)


def test_sync_routes_use_threads_and_socket_has_no_router_db():
    from app.main import app
    from app.api.v1 import auth, media_playback
    from app.services.dive_access import member_access_context
    for fn in [member_access_context, media.get_media_status, media.get_media_status_batch,
               media.play_cached_media, media.lease_jobs, auth.me, media_playback.play_media_revision]:
        assert not inspect.iscoroutinefunction(fn)
    route = next(r for r in app.routes if r.path == '/api/v1/ws/sync')
    assert route.dependant.dependencies == []


def test_server_timing_includes_numeric_only_spans(api_client):
    response = api_client.get('/api/v1/health')
    assert response.status_code == 200
    import re
    assert re.fullmatch(r'auth;dur=\d+\.\d+, db;dur=\d+\.\d+, app;dur=\d+\.\d+', response.headers['server-timing'])


def test_xray_metrics_admin_only(api_client, monkeypatch):
    from app.main import app
    from app.api.v1.auth import get_current_user
    from types import SimpleNamespace
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(is_admin=False)
    assert api_client.get('/api/v1/auth/xray').status_code == 403
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(is_admin=True)
    response = api_client.get('/api/v1/auth/xray')
    assert response.status_code == 200
    assert 'over_100ms_total' in response.json()['event_loop']


@pytest.mark.asyncio
async def test_loop_lag_detects_a_blocking_event_loop():
    import asyncio
    import time
    from app.services.xray import LoopLag
    lag = LoopLag()
    task = asyncio.create_task(lag.run())
    try:
        await asyncio.sleep(.02)
        time.sleep(.22)
        await asyncio.sleep(.01)
        assert lag.snapshot()['over_100ms_total'] >= 1
        assert lag.snapshot()['max_ms'] >= 100
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
