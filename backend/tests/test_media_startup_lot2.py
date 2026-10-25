import base64
import hashlib
import hmac
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit, parse_qs

import pytest
from PIL import Image
from app.config import get_settings
from app.models.media import MediaCacheEntry
from app.models.photos_asset import PhotosAsset
from app.services import poster_visuals, signed_media
from app.services.media_cache import playback_url, thumb_url


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), 'media_cache_root', str(tmp_path))
    monkeypatch.setattr(poster_visuals.shutil, 'disk_usage', lambda p: SimpleNamespace(free=100 * 1024**3))
    return tmp_path


def poster(db, root):
    asset = PhotosAsset(video_uuid='lot2-synthetic')
    db.add(asset)
    db.flush()
    path = root / 'poster.jpg'
    Image.new('RGB', (1080, 1920), '#2277aa').save(path)
    entry = MediaCacheEntry(photos_asset_id=asset.id, media_key='lot2', rendition='poster',
        storage_path=str(path), status='ready', size_bytes=path.stat().st_size,
        checksum_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    db.add(entry)
    db.flush()
    entry_id = entry.id
    db.commit()
    poster_visuals.enrich_committed_poster(entry_id, bind=db.get_bind())
    db.refresh(entry)
    return entry


def test_all_poster_writes_refresh_visuals_and_reads_do_not(test_db, root, monkeypatch):
    entry = poster(test_db, root)
    old_hash, old_thumb = entry.thumbhash, entry.thumb_storage_path
    assert len(base64.b64decode(old_hash)) >= 5
    with Image.open(old_thumb) as thumb:
        assert thumb.format == 'WEBP' and thumb.size == (480, 853)
    assert entry.thumb_checksum_sha256 == hashlib.sha256(Path(old_thumb).read_bytes()).hexdigest()
    assert '/thumb?' in thumb_url(entry)
    calls = []
    original = poster_visuals.enrich_poster
    monkeypatch.setattr(poster_visuals, 'enrich_poster', lambda e: calls.append(e.id) or original(e))
    from datetime import datetime
    entry.last_accessed_at = datetime.utcnow()
    test_db.commit()
    assert calls == []
    # Same row refresh, as durable_poster_cache._refresh does.
    path = root / 'updated.jpg'
    Image.new('RGB', (1080, 1920), '#ee9922').save(path)
    poster_visuals.clear_visuals(entry)
    entry.storage_path = str(path)
    entry.checksum_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    test_db.commit()
    assert calls == []
    entry_id = entry.id
    test_db.rollback()
    poster_visuals.enrich_committed_poster(entry_id, bind=test_db.get_bind())
    test_db.refresh(entry)
    assert calls == [entry.id]
    assert entry.thumbhash != old_hash and entry.thumb_storage_path != old_thumb
    assert Path(old_thumb).is_file() # live old capabilities retain immutable bytes


def test_floor_still_computes_color_and_clears_stale_thumb(test_db, root, monkeypatch):
    entry = poster(test_db, root)
    monkeypatch.setattr(poster_visuals.shutil, 'disk_usage', lambda p: SimpleNamespace(free=poster_visuals.MIN_FREE_BYTES))
    poster_visuals.enrich_poster(entry)
    assert entry.thumbhash and entry.thumb_storage_path is None
    test_db.commit()
    assert poster_visuals.backfill(test_db, limit=1) == {'scanned': 1, 'after_id': entry.id}
    assert poster_visuals.backfill(test_db, limit=1, after_id=entry.id)['scanned'] == 0


def test_signing_buckets_paths_checksum_and_secret(root, monkeypatch):
    monkeypatch.setenv('MEDIA_SIGNED_URLS_ENABLED', 'true')
    monkeypatch.setenv('MEDIA_SIGNING_SECRET', 'a' * 64)
    path = root / 'poster' / 'abc.jpg'
    first = signed_media.signed_url(path, 'b'*64, now=1800000001)
    assert first == signed_media.signed_url(path, 'b'*64, now=1800000899)
    assert first != signed_media.signed_url(path, 'b'*64, now=1800000900)
    assert first != signed_media.signed_url(path, 'c'*64, now=1800000001)
    url = urlsplit(first)
    q = parse_qs(url.query)
    assert 3600 <= int(q['expires'][0]) - 1800000001 <= 4500
    assert q['sig'][0] == hmac.new(b'a'*64, (q['expires'][0]+'\n'+url.path).encode(), hashlib.sha256).hexdigest()
    assert signed_media.signed_url(root.parent / 'private', 'b'*64) is None
    assert signed_media.signed_url(path, None) is None
    monkeypatch.setenv('MEDIA_SIGNING_SECRET', 'bad')
    assert signed_media.signed_url(path, 'b'*64) is None


def test_thumb_serves_authorized_and_versioned(api_client, test_db, root, monkeypatch):
    from app.api.v1 import media
    entry = poster(test_db, root)
    monkeypatch.setattr(get_settings(), 'media_xaccel_enabled', False)
    response = api_client.get(thumb_url(entry))
    assert response.status_code == 200
    assert response.headers['content-type'] == 'image/webp'
    assert 'immutable' in response.headers['cache-control']
    assert api_client.get(f'/api/v1/media/cache/{entry.id}/thumb?v=old').headers['cache-control'] == 'private, no-cache'
    monkeypatch.setattr(media, 'require_legacy_media_user', lambda *a: object())
    monkeypatch.setattr(media, 'can_user_access_cache_entry', lambda *a: SimpleNamespace(allowed=False))
    assert api_client.get(thumb_url(entry)).status_code == 404


def test_library_and_batch_include_visuals(api_client, test_db, root):
    from tests.test_library_media_payloads import seed_dive_with_asset
    entry = poster(test_db, root)
    dive = seed_dive_with_asset(test_db, 'lot2-synthetic')
    dive.photos_asset_id = entry.photos_asset_id
    test_db.commit()
    row = api_client.get('/api/v1/dives/library', params={'diver_scope':'all'}).json()['items'][0]
    assert row['thumbhash'] == entry.thumbhash
    assert row['thumb_url'] == thumb_url(entry)
    tile = api_client.post('/api/v1/media/status/batch', json={'video_uuids':['lot2-synthetic']}).json()['lot2-synthetic']
    assert tile['thumbhash'] == entry.thumbhash and tile['thumb_url'] == row['thumb_url']


def test_thumbhash_matches_reference_javascript_vector():
    from thumbhash import rgba_to_thumb_hash
    # evanw/thumbhash 0.1.1 rgbaToThumbHash(1,1,[34,119,170,255]).
    assert base64.b64encode(bytes(rgba_to_thumb_hash(1,1,[34,119,170,255]))).decode() == 'G1U1vyoI9wiIh4hwj3CI+AiIcH/494cP'


def test_thumbnail_accounting_and_reference_aware_cleanup(test_db, root):
    import os
    import time
    from app.services.media_cache import _cache_size, cleanup_cache
    entry = poster(test_db, root)
    thumb = Path(entry.thumb_storage_path)
    size = thumb.stat().st_size
    # Multiple rows referencing identical bytes must not double count files.
    assert _cache_size(test_db) == entry.size_bytes + size
    shared = MediaCacheEntry(photos_asset_id=entry.photos_asset_id,
        media_key='shared-thumb', rendition='poster', storage_path=entry.storage_path,
        size_bytes=entry.size_bytes, status='ready', thumb_storage_path=str(thumb))
    test_db.add(shared)
    test_db.commit()
    assert _cache_size(test_db) == 2 * entry.size_bytes + size
    test_db.delete(shared)
    test_db.commit()
    old = time.time() - poster_visuals.THUMB_GRACE_SECONDS - 10
    os.utime(thumb, (old, old))
    test_db.rollback()
    assert poster_visuals.cleanup_orphan_thumbnails(test_db) == 0
    assert thumb.exists()
    # Refresh detaches the old thumbnail; grace protects outstanding URLs.
    entry = test_db.get(MediaCacheEntry, entry.id)
    poster_visuals.clear_visuals(entry)
    test_db.commit()
    os.utime(thumb, None)
    assert poster_visuals.cleanup_orphan_thumbnails(test_db) == 0
    os.utime(thumb, (old, old))
    _, freed, total = cleanup_cache(test_db, max_bytes=1)
    assert freed == size and total == entry.size_bytes
    assert not thumb.exists() and Path(entry.storage_path).exists()


def test_thumbnail_cleanup_preserves_symlinks_and_bounds_unlinks(test_db, root):
    import os
    import time
    directory = root / 'thumb' / 'ab'
    directory.mkdir(parents=True)
    outside = root / 'precious'
    outside.write_bytes(b'original')
    (directory / ('a' * 64 + '.webp')).symlink_to(outside)
    for letter in ('b', 'c'):
        path = directory / (letter * 64 + '.webp')
        path.write_bytes(b'old')
        os.utime(path, (0, 0))
    assert poster_visuals.cleanup_orphan_thumbnails(test_db, limit=1) == 3
    assert outside.read_bytes() == b'original'
    assert len(list(poster_visuals.thumbnail_files())) == 1
