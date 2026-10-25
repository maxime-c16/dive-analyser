import hashlib
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from app.config import get_settings
from app.models.media import MediaCacheEntry
from app.models.photos_asset import PhotosAsset
from app.services import animated_visuals as av
from app.api.v1.media import _preferred_entry, _thumbnail_status_for_entries


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), 'media_cache_root', str(tmp_path))
    monkeypatch.setattr(av.shutil, 'disk_usage', lambda _: SimpleNamespace(free=100 * 1024**3))
    return tmp_path


def test_real_ffmpeg_bounded_webp_and_backfill(test_db, root, monkeypatch):
    if not shutil.which('ffmpeg'):
        pytest.skip('ffmpeg required')
    path = root / 'proxy.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
        'testsrc2=size=640x360:rate=30', '-t', '2', '-c:v', 'libx264',
        '-pix_fmt', 'yuv420p', str(path)], check=True)
    asset = PhotosAsset(video_uuid='lot3-synthetic')
    test_db.add(asset)
    test_db.flush()
    proxy = MediaCacheEntry(photos_asset_id=asset.id, media_key='lot3-proxy',
        rendition='proxy_720p', storage_path=str(path), size_bytes=path.stat().st_size,
        checksum_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), status='ready')
    test_db.add(proxy)
    test_db.commit()
    monkeypatch.setenv('MEDIA_SIGNED_URLS_ENABLED', 'true')
    monkeypatch.setenv('MEDIA_SIGNING_SECRET', 'b' * 64)
    result = av.backfill(test_db, 1)
    assert result['generated'] == result['scanned'] == 1
    entry = test_db.query(MediaCacheEntry).filter_by(rendition='animated').one()
    data = Path(entry.storage_path).read_bytes()
    assert len(data) <= 80_000
    assert hashlib.sha256(data).hexdigest() == entry.checksum_sha256
    assert entry.checksum_sha256 in entry.storage_path
    with Image.open(entry.storage_path) as image:
        assert image.is_animated and image.width <= 360
        duration = 0
        for i in range(image.n_frames):
            image.seek(i)
            image.load()
            duration += image.info['duration']
        assert 800 <= duration <= 1100
    assert av.backfill(test_db, 1)['generated'] == 0
    assert _preferred_entry([entry]) is None
    payload = _thumbnail_status_for_entries(test_db, asset.video_uuid, [entry])
    assert payload['status'] == 'ready' and payload['playback_url'] is None
    assert payload['animated_url'].startswith('/media/cache/signed/')


def test_disk_floor_and_path_confinement(root, monkeypatch):
    path = root / 'proxy.mp4'
    path.touch()
    monkeypatch.setattr(av.shutil, 'disk_usage', lambda _: SimpleNamespace(free=av.MIN_FREE_BYTES))
    monkeypatch.setattr(av.subprocess, 'run', lambda *a, **k: pytest.fail('ffmpeg below floor'))
    assert av.generate(path) is None
    with pytest.raises(ValueError):
        av.generate(root.parent / 'outside.mp4')


def test_backfill_releases_connection_and_fences_changed_proxy(test_db, root, monkeypatch):
    from sqlalchemy.orm import Session
    asset = PhotosAsset(video_uuid='lot3-race')
    test_db.add(asset)
    test_db.flush()
    entry = MediaCacheEntry(photos_asset_id=asset.id, media_key='lot3-race', rendition='proxy_720p',
        storage_path=str(root / 'proxy.mp4'), size_bytes=10, checksum_sha256='a' * 64, status='ready')
    test_db.add(entry)
    test_db.commit()
    entry_id = entry.id
    test_db.rollback()
    bind = test_db.get_bind()
    def generate(_):
        assert not test_db.in_transaction()
        with Session(bind=bind) as other:
            source = other.get(MediaCacheEntry, entry_id)
            source.storage_path = str(root / 'replacement.mp4')
            source.checksum_sha256 = 'b' * 64
            other.commit()
        path = root / 'animated' / 'cc' / ('c' * 64 + '.webp')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'x' * 100)
        return str(path), 'c' * 64, 100
    monkeypatch.setattr(av, 'generate', generate)
    assert av.backfill(test_db, 1)['generated'] == 0
    assert test_db.query(MediaCacheEntry).filter_by(rendition='animated').count() == 0
    from app.services import poster_visuals
    from app.services.media_cache import _cache_size
    path = next(poster_visuals.thumbnail_files("animated"))
    assert _cache_size(test_db) == 110  # proxy + abandoned physical generation
    assert poster_visuals.cleanup_orphan_thumbnails(test_db, namespace="animated") == 0
    import os
    os.utime(path, (0, 0))
    assert poster_visuals.cleanup_orphan_thumbnails(test_db, namespace="animated") == 100
    assert _cache_size(test_db) == 10


def test_animated_reaches_authorized_library_and_batch(api_client, test_db, root, monkeypatch):
    from tests.test_library_media_payloads import seed_dive_with_asset
    seed_dive_with_asset(test_db, uuid='lot3-library')
    asset = PhotosAsset(video_uuid='lot3-library')
    test_db.add(asset)
    test_db.flush()
    entry = MediaCacheEntry(photos_asset_id=asset.id, media_key='lot3-library-animation',
        rendition='animated', storage_path=str(root / 'animated.webp'), size_bytes=100,
        checksum_sha256='e' * 64, status='ready')
    test_db.add(entry)
    test_db.commit()
    monkeypatch.setenv('MEDIA_SIGNED_URLS_ENABLED', 'true')
    monkeypatch.setenv('MEDIA_SIGNING_SECRET', 'b' * 64)
    batch = api_client.post('/api/v1/media/status/batch', json={'video_uuids': ['lot3-library']})
    assert batch.status_code == 200
    assert batch.json()['lot3-library']['animated_url'].startswith('/media/cache/signed/')
    page = api_client.get('/api/v1/dives/library', params={'diver_scope': 'all'})
    assert page.status_code == 200
    item = next(i for i in page.json()['items'] if i['video_uuid'] == 'lot3-library')
    assert item['animated_url'] == batch.json()['lot3-library']['animated_url']


def test_animation_cleanup_preserves_shared_references_and_bounds(test_db, root):
    import os
    from app.services import poster_visuals
    from app.services.media_cache import _cache_size, cleanup_cache
    asset = PhotosAsset(video_uuid='lot3-shared')
    test_db.add(asset)
    test_db.flush()
    directory = root / 'animated' / 'aa'
    directory.mkdir(parents=True)
    path = directory / ('a' * 64 + '.webp')
    path.write_bytes(b'x' * 100)
    os.utime(path, (0, 0))
    # Pinned reference protects shared content even when another row expires.
    for key, pinned in [('expired', False), ('retained', True)]:
        test_db.add(MediaCacheEntry(photos_asset_id=asset.id, media_key=key,
            rendition='animated', storage_path=str(path), size_bytes=100,
            status='ready', pinned=pinned))
    test_db.commit()
    assert _cache_size(test_db) == 200  # existing conservative row accounting
    assert cleanup_cache(test_db, max_bytes=1) == (1, 0, 100)
    assert path.exists()
    remaining = test_db.query(MediaCacheEntry).filter_by(media_key='retained').one()
    remaining.status = 'failed'
    test_db.commit()
    assert _cache_size(test_db) == 100  # failed rows no longer hide physical files
    assert poster_visuals.cleanup_orphan_thumbnails(test_db, namespace='animated') == 0
    test_db.delete(remaining)
    test_db.commit()
    for letter in ('b', 'c'):
        orphan = directory / (letter * 64 + '.webp')
        orphan.write_bytes(b'old')
        os.utime(orphan, (0, 0))
    protected = root / 'original.mp4'
    protected.write_bytes(b'precious')
    (directory / ('d' * 64 + '.webp')).symlink_to(protected)
    assert poster_visuals.cleanup_orphan_thumbnails(test_db, limit=1, namespace='animated') in (3, 100)
    assert len(list(poster_visuals.thumbnail_files('animated'))) == 2
    assert protected.read_bytes() == b'precious'
