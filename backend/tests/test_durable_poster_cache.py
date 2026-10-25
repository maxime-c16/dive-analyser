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
