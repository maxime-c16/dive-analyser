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
        'testsrc2=size=640x360:rate=30', '-t', '6', '-g', '15', '-c:v', 'libx264',
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
    from app.services import poster_visuals
    import os
    generate = av.generate
    def previously_orphaned(path, deadline=None):
        result = generate(path, deadline)
        if result:
            marker = poster_visuals.orphan_marker(result[0])
            marker.touch()
            os.utime(marker, (0, 0))
        return result
    monkeypatch.setattr(av, 'generate', previously_orphaned)
    result = av.backfill(test_db, 1)
    assert result['generated'] == result['scanned'] == 1
    entry = test_db.query(MediaCacheEntry).filter_by(rendition='animated').one()
    assert not poster_visuals.orphan_marker(entry.storage_path).exists()
    data = Path(entry.storage_path).read_bytes()
    assert len(data) <= 80_000
    assert hashlib.sha256(data).hexdigest() == entry.checksum_sha256
    assert entry.checksum_sha256 in entry.storage_path
    with Image.open(entry.storage_path) as image:
        assert image.is_animated and image.width <= 360
        assert image.n_frames == av.STOP_MOTION_FRAMES
        duration = 0
        for i in range(image.n_frames):
            image.seek(i)
            image.load()
            duration += image.info['duration']
        assert duration == av.STOP_MOTION_FRAMES * av.FRAME_MS
    # Stills are sampled across the whole clip, the last near its end.
    seeks = []
    real_run = av.subprocess.run
    def record(command, **kwargs):
        if command[0] == 'nice':
            seeks.append(float(command[command.index('-ss') + 1]))
        return real_run(command, **kwargs)
    monkeypatch.setattr(av.subprocess, 'run', record)
    assert av.generate(path)
    assert len(seeks) == av.STOP_MOTION_FRAMES
    assert seeks[0] < 0.5 and seeks[-1] > 5.4
    assert av.backfill(test_db, 1)['scanned'] == 0
    assert _preferred_entry([entry]) is None
    payload = _thumbnail_status_for_entries(test_db, asset.video_uuid, [entry])
    assert payload['status'] == 'ready' and payload['playback_url'] is None
    assert payload['animated_url'].startswith('/media/cache/signed/')


def _proxy(db, root, uuid, rendition, checksum):
    asset = db.query(PhotosAsset).filter_by(video_uuid=uuid).one_or_none()
    if asset is None:
        asset = PhotosAsset(video_uuid=uuid)
        db.add(asset)
        db.flush()
    entry = MediaCacheEntry(photos_asset_id=asset.id, media_key=f'{uuid}-{rendition}',
        rendition=rendition, storage_path=str(root / f'{uuid}-{rendition}.mp4'), size_bytes=10,
        checksum_sha256=checksum, status='ready')
    db.add(entry)
    db.commit()
    return asset, entry


def test_tick_selection_replaces_old_tiles_and_skips_failures(test_db, root, monkeypatch):
    asset, hq = _proxy(test_db, root, 'both', 'proxy_720p', 'a' * 64)
    _proxy(test_db, root, 'both', 'proxy_360p', 'b' * 64)
    _, low = _proxy(test_db, root, 'low-only', 'proxy_360p', 'c' * 64)
    _, broken = _proxy(test_db, root, 'broken', 'proxy_720p', 'd' * 64)
    first_second = MediaCacheEntry(photos_asset_id=asset.id, media_key='animated-v1-old',
        rendition='animated', storage_path=str(root / 'old.webp'), size_bytes=5, status='ready')
    test_db.add(first_second)
    test_db.commit()
    # One proxy per asset (720p preferred), newest first; v1 tiles don't count.
    assert [row.id for row in av.pending_proxies(test_db, 16)] == [broken.id, low.id, hq.id]
    test_db.rollback()
    def generate(source, deadline=None):
        if source.endswith('broken-proxy_720p.mp4'):
            return None
        checksum = hashlib.sha256(source.encode()).hexdigest()
        path = root / 'animated' / checksum[:2] / f'{checksum}.webp'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'x' * 10)
        return str(path), checksum, 10
    monkeypatch.setattr(av, 'generate', generate)
    assert av.backfill(test_db, 4) == dict(scanned=3, generated=2, failed=1)
    tiles = test_db.query(MediaCacheEntry).filter_by(rendition='animated').all()
    assert {t.source_blob_sha256 for t in tiles} == {'a' * 64, 'c' * 64}
    assert all(t.transform_version == av.TRANSFORM_VERSION for t in tiles)
    # Nothing left: done assets are fenced, the failure is not retried every tick.
    assert av.backfill(test_db, 4)['scanned'] == 0


def test_tick_selects_only_newest_proxy_generation(test_db, root, monkeypatch):
    asset = PhotosAsset(video_uuid='regen')
    test_db.add(asset)
    test_db.flush()
    old = MediaCacheEntry(photos_asset_id=asset.id, media_key='regen-720p-old',
        rendition='proxy_720p', storage_path=str(root / 'regen-old.mp4'), size_bytes=10,
        checksum_sha256='e' * 64, status='ready')
    new = MediaCacheEntry(photos_asset_id=asset.id, media_key='regen-720p-new',
        rendition='proxy_720p', storage_path=str(root / 'regen-new.mp4'), size_bytes=10,
        checksum_sha256='f' * 64, status='ready')
    legacy = PhotosAsset(video_uuid='regen-prefers-hq')
    test_db.add(legacy)
    test_db.flush()
    legacy_low = MediaCacheEntry(photos_asset_id=legacy.id, media_key='regen-hq-old',
        rendition='proxy_720p', storage_path=str(root / 'regen-hq-old.mp4'), size_bytes=10,
        checksum_sha256='10' * 32, status='ready')
    legacy_new_low = MediaCacheEntry(photos_asset_id=legacy.id, media_key='regen-low-new',
        rendition='proxy_360p', storage_path=str(root / 'regen-low-new.mp4'), size_bytes=10,
        checksum_sha256='11' * 32, status='ready')
    test_db.add_all([old, new, legacy_low, legacy_new_low])
    test_db.commit()
    # One row per asset: the newest 720p generation; 720p still wins over a
    # newer 360p. Batching both generations would tile the older over the newer.
    rows = {row.photos_asset_id: row for row in av.pending_proxies(test_db, 16)}
    assert rows[asset.id].id == new.id
    assert rows[legacy.id].id == legacy_low.id
    test_db.rollback()
    seen = []
    def generate(source, deadline=None):
        seen.append(source)
        checksum = hashlib.sha256(source.encode()).hexdigest()
        path = root / 'animated' / checksum[:2] / f'{checksum}.webp'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'x' * 10)
        return str(path), checksum, 10
    monkeypatch.setattr(av, 'generate', generate)
    assert av.backfill(test_db, 4) == dict(scanned=2, generated=2, failed=0)
    # Newest first: the 720p-over-newer-360p asset (higher ids) tiles first.
    assert seen == [str(root / 'regen-hq-old.mp4'), str(root / 'regen-new.mp4')]
    tiles = {t.photos_asset_id: t for t in test_db.query(MediaCacheEntry).filter_by(rendition='animated')}
    assert tiles[asset.id].source_blob_sha256 == 'f' * 64
    assert tiles[legacy.id].source_blob_sha256 == '10' * 32


def test_generate_honours_expired_deadline(root, monkeypatch):
    import time
    path = root / 'proxy.mp4'
    path.touch()
    monkeypatch.setattr(av.subprocess, 'run', lambda *a, **k: pytest.fail('ffmpeg after deadline'))
    with pytest.raises(av.BudgetExceeded):
        av.generate(path, time.monotonic() - 1)
    # Less than one quantum left also yields instead of starting doomed ffmpeg.
    with pytest.raises(av.BudgetExceeded):
        av.generate(path, time.monotonic() + 0.1)


def test_backfill_expired_budget_defers_without_fencing(test_db, root, monkeypatch):
    _, proxy = _proxy(test_db, root, 'expired', 'proxy_720p', 'a' * 64)
    monkeypatch.setattr(av.subprocess, 'run', lambda *a, **k: pytest.fail('ffmpeg after deadline'))
    assert av.backfill(test_db, 4, time_budget=0) == dict(scanned=1, generated=0, failed=0)
    assert [row.id for row in av.pending_proxies(test_db, 16)] == [proxy.id]
    test_db.rollback()


def test_disk_deferral_is_retried_after_recovery(test_db, root, monkeypatch):
    _, proxy = _proxy(test_db, root, 'deferred', 'proxy_720p', 'a' * 64)
    (root / 'deferred-proxy_720p.mp4').touch()
    monkeypatch.setattr(av.shutil, 'disk_usage', lambda _: SimpleNamespace(free=av.MIN_FREE_BYTES))
    assert av.backfill(test_db, 4) == dict(scanned=1, generated=0, failed=0)
    # Deferred, not fenced: the proxy is still selectable on the next tick.
    assert [row.id for row in av.pending_proxies(test_db, 16)] == [proxy.id]
    test_db.rollback()
    monkeypatch.setattr(av.shutil, 'disk_usage', lambda _: SimpleNamespace(free=100 * 1024**3))
    def generate(source, deadline=None):
        checksum = hashlib.sha256(source.encode()).hexdigest()
        path = root / 'animated' / checksum[:2] / f'{checksum}.webp'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'x' * 10)
        return str(path), checksum, 10
    monkeypatch.setattr(av, 'generate', generate)
    assert av.backfill(test_db, 4) == dict(scanned=1, generated=1, failed=0)


def test_budget_bound_timeout_defers_without_fencing(test_db, root, monkeypatch):
    import time
    _, proxy = _proxy(test_db, root, 'slow-budget', 'proxy_720p', 'a' * 64)
    (root / 'slow-budget-proxy_720p.mp4').touch()
    def slow_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get('timeout'))
    monkeypatch.setattr(av.subprocess, 'run', slow_run)
    # 5 s left on the tick: ffprobe gets a 5 s budget-bound timeout, so the
    # proxy waits for the next tick instead of being fenced as broken.
    assert av.backfill(test_db, 4, time_budget=5.0) == dict(scanned=1, generated=0, failed=0)
    assert [row.id for row in av.pending_proxies(test_db, 16)] == [proxy.id]
    test_db.rollback()


def test_full_cap_timeout_still_fences(test_db, root, monkeypatch):
    _, proxy = _proxy(test_db, root, 'hung', 'proxy_720p', 'b' * 64)
    (root / 'hung-proxy_720p.mp4').touch()
    def hung_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get('timeout'))
    monkeypatch.setattr(av.subprocess, 'run', hung_run)
    # Full 40 s budget: ffprobe gets its whole 15 s cap, so a hang is the
    # proxy's fault and the proxy is fenced like any permanent failure.
    assert av.backfill(test_db, 4)['failed'] == 1
    assert av.backfill(test_db, 4)['scanned'] == 0


def test_disk_floor_and_path_confinement(root, monkeypatch):
    path = root / 'proxy.mp4'
    path.touch()
    monkeypatch.setattr(av.shutil, 'disk_usage', lambda _: SimpleNamespace(free=av.MIN_FREE_BYTES))
    monkeypatch.setattr(av.subprocess, 'run', lambda *a, **k: pytest.fail('ffmpeg below floor'))
    with pytest.raises(av.Deferred):
        av.generate(path)
    # A vanished source is a permanent per-proxy failure, not a deferral.
    assert av.generate(root / 'missing.mp4') is None
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
    def generate(_, deadline=None):
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
    os.utime(poster_visuals.orphan_marker(path), (0, 0))
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
    assert poster_visuals.cleanup_orphan_thumbnails(test_db, namespace='animated') == 0
    for path in poster_visuals.thumbnail_files('animated'):
        os.utime(poster_visuals.orphan_marker(path), (0, 0))
    assert poster_visuals.cleanup_orphan_thumbnails(test_db, limit=1, namespace='animated') in (3, 100)
    assert len(list(poster_visuals.thumbnail_files('animated'))) == 2
    assert protected.read_bytes() == b'precious'


def test_library_materializes_only_latest_ready_visuals(api_client, test_db, root, monkeypatch):
    from sqlalchemy import event
    from tests.test_library_media_payloads import seed_dive_with_asset
    seed_dive_with_asset(test_db, uuid='lot3-history')
    asset = PhotosAsset(video_uuid='lot3-history')
    test_db.add(asset)
    test_db.flush()
    asset_id = asset.id
    latest = {}
    for rendition in ('poster', 'animated'):
        for generation in range(30):
            entry = MediaCacheEntry(photos_asset_id=asset_id,
                media_key=f'{rendition}-{generation}', rendition=rendition,
                storage_path=str(root / f'{rendition}-{generation}.webp'),
                size_bytes=100, checksum_sha256='e' * 64, status='ready',
                thumbhash=f'hash-{generation}' if rendition == 'poster' else None)
            test_db.add(entry)
            test_db.flush()
            latest[rendition] = entry.id
        # A newer failed generation must not mask the usable ready one.
        test_db.add(MediaCacheEntry(photos_asset_id=asset_id,
            media_key=f'{rendition}-failed', rendition=rendition,
            storage_path='failed.webp', size_bytes=0, status='failed'))
    test_db.commit()
    test_db.expunge_all()
    monkeypatch.setenv('MEDIA_SIGNED_URLS_ENABLED', 'false')
    loaded = []
    def record_load(entry, _):
        loaded.append(entry.id)
    event.listen(MediaCacheEntry, 'load', record_load)
    try:
        response = api_client.get('/api/v1/dives/library', params={'diver_scope': 'all'})
    finally:
        event.remove(MediaCacheEntry, 'load', record_load)
    assert response.status_code == 200
    item = next(i for i in response.json()['items'] if i['video_uuid'] == 'lot3-history')
    assert item['thumbhash'] == 'hash-29'
    assert item['animated_url'].startswith(f"/api/v1/media/cache/{latest['animated']}/play")
    assert sorted(loaded) == sorted(latest.values())


@pytest.mark.parametrize('endpoint', ['library', 'batch', 'status'])
def test_media_queries_bound_historical_generations(api_client, test_db, root, endpoint, monkeypatch):
    from sqlalchemy import event
    from tests.test_library_media_payloads import seed_dive_with_asset
    seed_dive_with_asset(test_db, uuid='bounded-batch')
    asset = PhotosAsset(video_uuid='bounded-batch')
    test_db.add(asset)
    test_db.flush()
    expected = {}
    from datetime import datetime, timedelta
    for rendition in ('poster', 'animated', 'proxy_720p', 'proxy_360p', 'original'):
        for generation in range(12):
            entry = MediaCacheEntry(photos_asset_id=asset.id,
                media_key=f'batch-{rendition}-{generation}', rendition=rendition,
                storage_path=str(root / f'{rendition}-{generation}'), size_bytes=100,
                status='ready', created_at=datetime(2026, 1, 1) + timedelta(seconds=generation),
                thumbhash=str(generation) if rendition == 'poster' else None)
            test_db.add(entry)
            test_db.flush()
            expected[rendition] = entry.id
        test_db.add(MediaCacheEntry(photos_asset_id=asset.id,
            media_key=f'batch-{rendition}-failed', rendition=rendition,
            storage_path='failed', size_bytes=0, status='failed'))
    test_db.commit()
    test_db.expunge_all()
    monkeypatch.setenv('MEDIA_SIGNED_URLS_ENABLED', 'false')
    loaded = []
    def record_load(entry, _):
        loaded.append(entry.id)
    event.listen(MediaCacheEntry, 'load', record_load)
    try:
        if endpoint == 'status':
            response = api_client.get('/api/v1/media/bounded-batch/status')
            item = response.json()
            renditions = tuple(expected)
            assert sorted(e['id'] for e in item['cache_entries']) == sorted(expected.values())
            assert item['playback_url'] == f"/api/v1/media/cache/{expected['proxy_720p']}/play"
            assert item['full_quality_url'] == f"/api/v1/media/cache/{expected['original']}/play"
        elif endpoint == 'batch':
            response = api_client.post('/api/v1/media/status/batch', json={'video_uuids': ['bounded-batch']})
            item = response.json()['bounded-batch']
            renditions = ('poster', 'animated', 'proxy_720p', 'proxy_360p')
            assert item['playback_url'] == f"/api/v1/media/cache/{expected['proxy_720p']}/play"
        else:
            response = api_client.get('/api/v1/dives/library', params={'diver_scope': 'all'})
            item = next(i for i in response.json()['items'] if i['video_uuid'] == 'bounded-batch')
            renditions = ('poster', 'animated')
    finally:
        event.remove(MediaCacheEntry, 'load', record_load)
    assert response.status_code == 200
    assert item['thumbhash'] == '11'
    if endpoint != 'status':
        assert item['animated_url'] == f"/api/v1/media/cache/{expected['animated']}/play"
    assert sorted(loaded) == sorted(expected[r] for r in renditions)


def test_animations_stay_out_of_video_only_consumers(test_db, root):
    from app.services.legacy_media import _entry_is_playable_video, _ready_cache_entries_for_uuid
    asset = PhotosAsset(video_uuid='animated-only-legacy')
    test_db.add(asset)
    test_db.flush()
    entry = MediaCacheEntry(photos_asset_id=asset.id, media_key='animated-only-legacy',
        rendition='animated', storage_path=str(root / 'animated.webp'), size_bytes=100, status='ready')
    test_db.add(entry)
    test_db.commit()
    assert not _entry_is_playable_video(entry)
    assert _ready_cache_entries_for_uuid(test_db, asset.video_uuid) == []
    from app.services.representative_media import _ready_cache_for_assets
    from app.services.dive_analysis_service import DiveAnalysisService
    assert not _ready_cache_for_assets(test_db, {asset.id})
    entries, _ = DiveAnalysisService(test_db).media_maps([SimpleNamespace(photos_asset_id=asset.id)])
    assert not entries


@pytest.mark.parametrize('references', [1, 2])
def test_trim_keeps_deferred_animation_bytes_in_quota(test_db, root, references):
    from app.services.media_cache import cleanup_cache
    from app.services import poster_visuals
    import os
    asset = PhotosAsset(video_uuid='deferred-quota')
    test_db.add(asset)
    test_db.flush()
    animation = root / 'animated' / 'aa' / ('a' * 64 + '.webp')
    animation.parent.mkdir(parents=True)
    animation.write_bytes(b'a' * 100)
    other = root / 'evictable-original.mp4'
    other.write_bytes(b'o' * 100)
    candidates = [(f'animation-{i}', 'animated', animation) for i in range(references)]
    candidates.append(('original', 'original', other))
    for key, rendition, path in candidates:
        test_db.add(MediaCacheEntry(photos_asset_id=asset.id, media_key=key,
            rendition=rendition, storage_path=str(path), size_bytes=100,
            status='ready', pinned=False))
    test_db.commit()
    # Evicting animation metadata frees no disk. Trim must continue to the
    # original rather than pretending it reached the 150-byte quota already.
    assert cleanup_cache(test_db, max_bytes=150) == (references + 1, 100, 100)
    assert animation.exists() and not other.exists()
    assert cleanup_cache(test_db, max_bytes=150) == (0, 0, 100)
    marker = poster_visuals.orphan_marker(animation)
    assert marker.exists()
    os.utime(marker, (0, 0))
    assert cleanup_cache(test_db, max_bytes=150) == (0, 100, 0)


@pytest.mark.parametrize('max_id', [1, 511, 512, 513, 1000, 3077, 10_000])
def test_tick_windows_are_bounded_and_cover_every_id(max_id):
    covered = set()
    cycle = -(-(max_id + 1) // av.SCAN_WINDOW)
    for minute in range(cycle):
        ranges = av._windows(max_id, minute * 60)
        assert sum(high - low for low, high in ranges) <= 2 * av.SCAN_WINDOW
        for low, high in ranges:
            covered.update(range(low + 1, high + 1))
    assert set(range(1, max_id + 1)) <= covered


def test_tick_scan_skips_old_ids_outside_windows_and_prunes_stale_failures(test_db, root, monkeypatch):
    _, old = _proxy(test_db, root, 'old', 'proxy_720p', 'e' * 64)
    _, recent = _proxy(test_db, root, 'recent', 'proxy_720p', 'f' * 64)
    monkeypatch.setattr(av, 'SCAN_WINDOW', 1)
    # Only the newest id and the rotating window are inspected per tick.
    minute_for_recent = av._windows(recent.id, 0)
    assert all(high - low <= 1 for low, high in minute_for_recent)
    failed = {old.id: 'stale-generation', recent.id: 'f' * 64, 999_999: 'gone'}
    ids = set()
    for minute in range(recent.id + 1):
        ids.update(row.id for row in av._candidates(test_db, 16, failed, minute * 60))
    # The current failure stays fenced; the replaced generation is pruned and retried.
    assert ids == {old.id}
    assert failed == {recent.id: 'f' * 64}
