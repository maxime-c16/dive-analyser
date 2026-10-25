"""Durable posters are copied once into the local grid cache (sha-verified)."""
import io
from types import SimpleNamespace

import pytest

from app.config import get_settings
from app.models.media import MediaCacheEntry
from app.services import b2_presign
from app.services import durable_poster_cache as dpc
from backend.tests.test_media_migration import _clip, _ledger, env  # noqa: F401  (fixture)

GIB = 1024**3


def _poster_bytes(uuid, source_sha):
    # _ledger derives each role's SHA from these exact bytes.
    return f"{uuid}{source_sha}poster".encode()


@pytest.fixture
def cache(env, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "media_cache_root", str(tmp_path))
    monkeypatch.setattr(__import__("shutil"), "disk_usage",
                        lambda _: SimpleNamespace(free=40 * GIB))
    store = {}

    def fake_stream(bucket, key):
        raw = store[key]
        return io.BytesIO(raw), len(raw)

    monkeypatch.setattr(b2_presign, "open_get_stream", fake_stream)
    return SimpleNamespace(db=env, root=tmp_path, store=store)


def _durable_clip(c, n, *, bytes_override=None):
    asset, sha = _clip(c.db, n)
    _ledger(c.db, asset.video_uuid, sha)
    c.db.commit()
    from app.models.media_backbone import MediaBlobLocation, MediaDerivative

    poster = c.db.query(MediaDerivative).filter_by(video_uuid=asset.video_uuid, role="poster").one()
    loc = c.db.query(MediaBlobLocation).filter_by(blob_sha256=poster.derivative_blob_sha256).one()
    c.store[loc.object_key] = bytes_override or _poster_bytes(asset.video_uuid, sha)
    return asset


def _poster_rows(db):
    return db.query(MediaCacheEntry).filter_by(rendition="poster").all()


def test_durable_poster_lands_in_grid_cache_once(cache):
    asset = _durable_clip(cache, 1)
    out = dpc.materialize_durable_posters(cache.db)
    assert out["cached"] == 1
    (row,) = _poster_rows(cache.db)
    assert row.photos_asset_id == asset.id and row.status == "ready" and row.pinned
    assert open(row.storage_path, "rb").read() == cache.store[next(iter(cache.store))]
    # Idempotent: nothing left to plan.
    assert dpc.materialize_durable_posters(cache.db)["planned"] == 0


def test_grid_batch_serves_the_copied_poster_locally(cache):
    from app.api.v1.media import _thumbnail_status_for_entries

    asset = _durable_clip(cache, 1)
    dpc.materialize_durable_posters(cache.db)
    entries = cache.db.query(MediaCacheEntry).filter_by(photos_asset_id=asset.id).all()
    payload = _thumbnail_status_for_entries(cache.db, asset.video_uuid, entries, None)
    assert payload["poster_url"].startswith("/api/v1/media/cache/")


def test_checksum_mismatch_records_nothing(cache):
    _durable_clip(cache, 1, bytes_override=b"tampered")
    out = dpc.materialize_durable_posters(cache.db)
    assert out["failed"] == 1 and _poster_rows(cache.db) == []
    assert not [p for p in cache.root.rglob("*") if p.is_file()]


def test_existing_cache_poster_is_never_replaced(cache):
    asset = _durable_clip(cache, 1)
    cache.db.add(MediaCacheEntry(photos_asset_id=asset.id, media_key="legacy-poster-key", rendition="poster",
                                 storage_path="/legacy.jpg", size_bytes=1, status="ready"))
    cache.db.commit()
    assert dpc.materialize_durable_posters(cache.db)["planned"] == 0
    assert [r.media_key for r in _poster_rows(cache.db)] == ["legacy-poster-key"]


def test_low_disk_does_nothing(cache, monkeypatch):
    import shutil

    _durable_clip(cache, 1)
    monkeypatch.setattr(shutil, "disk_usage", lambda _: SimpleNamespace(free=10 * GIB))
    assert dpc.materialize_durable_posters(cache.db)["cached"] == 0
    assert _poster_rows(cache.db) == []


def test_copy_never_targets_the_legacy_poster_path(cache):
    from app.services.media_keys import build_media_key

    asset = _durable_clip(cache, 1)
    dpc.materialize_durable_posters(cache.db)
    (row,) = _poster_rows(cache.db)
    assert not row.storage_path.endswith(f"{build_media_key(asset.video_uuid, 'poster')}.jpg")


def test_unservable_candidates_do_not_wall_off_the_backlog(cache, monkeypatch):
    good = _durable_clip(cache, 1)
    bad = [_durable_clip(cache, n) for n in range(2, 6)]
    from app.services import derivative_read

    original = derivative_read.safe_resolve_clip_derivatives
    monkeypatch.setattr(derivative_read, "safe_resolve_clip_derivatives",
                        lambda db, uuid, **kw: None if uuid != good.video_uuid else original(db, uuid, **kw))
    assert dpc.materialize_durable_posters(cache.db, limit=1)["cached"] == 1
    assert [r.photos_asset_id for r in _poster_rows(cache.db)] == [good.id]


def test_source_change_during_download_discards_the_copy(cache, monkeypatch):
    asset = _durable_clip(cache, 1)
    real = dpc._download

    def download_then_source_changes(item, dest):
        size = real(item, dest)
        from backend.tests.test_media_migration import _source

        _source(cache.db, asset.video_uuid, b"new-camera-original")
        cache.db.commit()
        return size

    monkeypatch.setattr(dpc, "_download", download_then_source_changes)
    out = dpc.materialize_durable_posters(cache.db)
    assert out["cached"] == 0 and out["skipped"] == 1
    assert _poster_rows(cache.db) == []
    assert not [p for p in cache.root.rglob("*") if p.is_file()]


def test_drifted_copy_is_refreshed_in_place(cache):
    from backend.tests.test_media_migration import _source

    asset = _durable_clip(cache, 1)
    dpc.materialize_durable_posters(cache.db)
    (row,) = _poster_rows(cache.db)
    old_path = row.storage_path
    # A new source lands after the copy committed, and gets its own package.
    new_sha = _source(cache.db, asset.video_uuid, b"new-camera-original")
    _ledger(cache.db, asset.video_uuid, new_sha)
    cache.db.commit()
    from app.models.media_backbone import MediaBlobLocation, MediaDerivative

    poster = cache.db.query(MediaDerivative).filter_by(video_uuid=asset.video_uuid, role="poster",
                                                       source_blob_sha256=new_sha).one()
    loc = cache.db.query(MediaBlobLocation).filter_by(blob_sha256=poster.derivative_blob_sha256).one()
    cache.store[loc.object_key] = _poster_bytes(asset.video_uuid, new_sha)
    out = dpc.materialize_durable_posters(cache.db)
    assert out["refreshed"] == 1
    cache.db.expire_all()
    (row,) = _poster_rows(cache.db)
    assert row.source_blob_sha256 == new_sha and row.storage_path != old_path
    assert row.checksum_sha256 == poster.derivative_blob_sha256


def test_mac_poster_rows_are_never_refreshed(cache):
    asset = _durable_clip(cache, 1)
    cache.db.add(MediaCacheEntry(photos_asset_id=asset.id, media_key="legacy-poster-key", rendition="poster",
                                 storage_path="/cache/poster/legacy-poster-key.jpg", size_bytes=1,
                                 checksum_sha256="0" * 64, status="ready"))
    cache.db.commit()
    out = dpc.materialize_durable_posters(cache.db)
    assert out["refreshed"] == 0 and out["cached"] == 0


def test_disk_floor_is_rechecked_before_each_download(cache, monkeypatch):
    import shutil

    for n in (1, 2, 3):
        _durable_clip(cache, n)
    free = iter([40 * GIB, 40 * GIB, dpc.MIN_FREE_BYTES])  # pass gate, 1st download, then floor
    monkeypatch.setattr(shutil, "disk_usage", lambda _: SimpleNamespace(free=next(free, dpc.MIN_FREE_BYTES)))
    out = dpc.materialize_durable_posters(cache.db)
    assert out["cached"] == 1 and len(_poster_rows(cache.db)) == 1


def test_refresh_versions_status_batch_and_old_url_revalidates(cache, api_client, monkeypatch):
    from app.api.v1.media import get_media_status_batch, get_media_status
    from app.schemas.media import MediaStatusBatchRequest
    from app.services.media_cache import playback_url
    from backend.tests.test_media_migration import _source

    # Exercise cache fallback on the full player status as well as grid batch.
    monkeypatch.setattr(get_settings(), 'user_auth_enabled', False)
    asset = _durable_clip(cache, 1)
    dpc.materialize_durable_posters(cache.db)
    (row,) = _poster_rows(cache.db)
    old_id, old_url = row.id, playback_url(row)
    request = MediaStatusBatchRequest(video_uuids=[asset.video_uuid])
    before_status = get_media_status(asset.video_uuid, cache.db)
    before_batch = get_media_status_batch(request, cache.db)
    assert before_status.poster_url == old_url
    assert old_url in str(before_batch)
    assert old_url.endswith('?v=' + row.checksum_sha256[:12])
    assert 'immutable' in api_client.get(old_url).headers['cache-control']

    new_sha = _source(cache.db, asset.video_uuid, b'new-camera-original')
    _ledger(cache.db, asset.video_uuid, new_sha)
    cache.db.commit()
    from app.models.media_backbone import MediaBlobLocation, MediaDerivative
    poster = cache.db.query(MediaDerivative).filter_by(video_uuid=asset.video_uuid,
        role='poster', source_blob_sha256=new_sha).one()
    loc = cache.db.query(MediaBlobLocation).filter_by(blob_sha256=poster.derivative_blob_sha256).one()
    cache.store[loc.object_key] = _poster_bytes(asset.video_uuid, new_sha)
    assert dpc.materialize_durable_posters(cache.db)['refreshed'] == 1
    cache.db.expire_all()
    (row,) = _poster_rows(cache.db)
    new_url = playback_url(row)
    assert row.id == old_id and new_url != old_url
    assert get_media_status(asset.video_uuid, cache.db).poster_url == new_url
    after_batch = get_media_status_batch(request, cache.db)
    assert new_url in str(after_batch) and old_url not in str(after_batch)
    old_response = api_client.get(old_url)
    assert old_response.status_code == 200
    assert old_response.headers['cache-control'] == 'private, no-cache'
    assert 'immutable' in api_client.get(new_url).headers['cache-control']


def test_durable_writer_generates_thumbhash_and_refreshes_it(cache, monkeypatch):
    from PIL import Image
    from app.services import poster_visuals
    from backend.tests.test_media_migration import _source

    asset = _durable_clip(cache, 1)
    color = ['#2277aa']
    # Isolate transport verification (covered above); run real durable SQL/files
    # and the shared poster-write hook with an actual decodable poster.
    def download(item, dest):
        Image.new('RGB', (1080, 1920), color[0]).save(dest, format='JPEG')
        return dest.stat().st_size
    monkeypatch.setattr(dpc, '_download', download)
    assert dpc.materialize_durable_posters(cache.db)['cached'] == 1
    (row,) = _poster_rows(cache.db)
    first = row.thumbhash
    first_thumb = row.thumb_storage_path
    assert first and first_thumb
    new_sha = _source(cache.db, asset.video_uuid, b'changed-camera')
    _ledger(cache.db, asset.video_uuid, new_sha)
    cache.db.commit()
    color[0] = '#ee9922'
    assert dpc.materialize_durable_posters(cache.db)['refreshed'] == 1
    assert row.thumbhash and row.thumbhash != first
    assert row.thumb_storage_path != first_thumb
