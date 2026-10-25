"""Content version gates caching for every cache-entry URL, including X-Accel."""
import hashlib
from urllib.parse import urlencode

import pytest

from app.config import get_settings
from app.models.media import MediaCacheEntry
from app.models.photos_asset import PhotosAsset
from app.services.media_cache import playback_url, versioned_cache_url, to_cache_summary


@pytest.mark.parametrize('xaccel', [False, True])
@pytest.mark.parametrize('method,headers', [('GET', {}), ('HEAD', {}), ('GET', {'Range': 'bytes=0-2'})])
@pytest.mark.parametrize('version', ['matching', 'old', 'missing', 'unknown_checksum'])
def test_only_current_content_version_is_immutable(api_client, test_db, tmp_path, monkeypatch, xaccel, method, headers, version):
    monkeypatch.setattr(get_settings(), 'media_cache_root', str(tmp_path))
    monkeypatch.setattr(get_settings(), 'media_xaccel_enabled', xaccel)
    monkeypatch.setattr(get_settings(), 'user_auth_enabled', False)
    path = tmp_path / 'proxy.mp4'
    path.write_bytes(b'content')
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    asset = PhotosAsset(video_uuid='version-policy')
    test_db.add(asset)
    test_db.flush()
    entry = MediaCacheEntry(photos_asset_id=asset.id, media_key='version-policy', rendition='proxy_720p',
        storage_path=str(path), size_bytes=7, status='ready', checksum_sha256=checksum if version != 'unknown_checksum' else None)
    test_db.add(entry)
    test_db.commit()
    url = f'/api/v1/media/cache/{entry.id}/play'
    if version != 'missing':
        url += '?' + urlencode({'v': checksum[:12] if version != 'old' else 'old-version'})
    response = api_client.request(method, url, headers=headers)
    assert response.status_code in (200, 206)
    if version == 'matching':
        assert response.headers['cache-control'] == 'private, max-age=31536000, immutable'
        assert to_cache_summary(entry).playback_url == playback_url(entry) == url
    else:
        assert response.headers['cache-control'] == 'private, no-cache'
    if xaccel and method == 'GET':
        assert response.headers['x-accel-redirect'].startswith('/internal-media-cache/')


def test_version_helper_preserves_quality_query_and_fails_closed():
    entry = MediaCacheEntry(id=10, checksum_sha256='A' * 64)
    assert playback_url(entry) == '/api/v1/media/cache/10/play?v=' + 'a' * 12
    assert versioned_cache_url('/play?rendition=original', entry) == '/play?rendition=original&v=' + 'a' * 12
    entry.checksum_sha256 = 'malformed'
    assert playback_url(entry) == '/api/v1/media/cache/10/play'
