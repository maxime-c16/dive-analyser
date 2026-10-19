"""Player status keeps real preparation transitions and terminal failures."""
from datetime import datetime, timedelta

import pytest

from app.models.media import MediaCacheEntry, MediaJob
from app.models.photos_asset import PhotosAsset


def seed_job(db, asset, status, *, rendition='proxy_720p', age=0):
    job = MediaJob(photos_asset_id=asset.id, media_key=f'{asset.id}-{rendition}-{status}-{age}',
        rendition=rendition, status=status, last_error='source retrieval failed' if status in ('failed', 'unavailable') else None,
        created_at=datetime.utcnow() - timedelta(seconds=age))
    db.add(job)
    db.commit()
    return job


@pytest.mark.parametrize('terminal', ['failed', 'unavailable'])
def test_polling_reports_source_retrieval_then_terminal_failure(api_client, test_db, monkeypatch, terminal):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), 'user_auth_enabled', False)
    asset = PhotosAsset(video_uuid='source-retrieval-status')
    test_db.add(asset); test_db.commit()
    job = seed_job(test_db, asset, 'materializing')
    path = f'/api/v1/media/{asset.video_uuid}/status'
    assert api_client.get(path).json()['status'] == 'materializing'
    job.status, job.last_error = terminal, 'source retrieval failed'
    test_db.commit()
    response = api_client.get(path)
    assert response.status_code == 200
    assert response.json()['status'] == terminal
    assert response.json()['job']['last_error'] == 'source retrieval failed'


def test_successful_poster_does_not_hide_failed_video(api_client, test_db, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), 'user_auth_enabled', False)
    asset = PhotosAsset(video_uuid='poster-is-not-video')
    test_db.add(asset); test_db.commit()
    seed_job(test_db, asset, 'failed', age=10)
    seed_job(test_db, asset, 'ready', rendition='poster')
    assert api_client.get(f'/api/v1/media/{asset.video_uuid}/status').json()['status'] == 'failed'


def test_newer_success_does_not_resurrect_old_failure_after_eviction(api_client, test_db, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), 'user_auth_enabled', False)
    asset = PhotosAsset(video_uuid='successful-retry-status')
    test_db.add(asset); test_db.commit()
    seed_job(test_db, asset, 'failed', age=10)
    seed_job(test_db, asset, 'ready')
    result = api_client.get(f'/api/v1/media/{asset.video_uuid}/status').json()
    assert result['status'] == 'missing'
    assert result['job'] is None


def test_ready_video_and_active_retry_take_precedence(api_client, test_db, monkeypatch, tmp_path):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), 'user_auth_enabled', False)
    asset = PhotosAsset(video_uuid='active-retry-status')
    test_db.add(asset); test_db.commit()
    seed_job(test_db, asset, 'failed', age=10)
    retry = seed_job(test_db, asset, 'queued')
    path = f'/api/v1/media/{asset.video_uuid}/status'
    assert api_client.get(path).json()['status'] == 'queued'
    retry.status = 'failed'
    video = tmp_path / 'ready.mp4'
    video.write_bytes(b'video')
    test_db.add(MediaCacheEntry(photos_asset_id=asset.id, media_key='ready-video', rendition='proxy_720p',
        storage_path=str(video), size_bytes=5, status='ready'))
    test_db.commit()
    assert api_client.get(path).json()['status'] == 'ready'
