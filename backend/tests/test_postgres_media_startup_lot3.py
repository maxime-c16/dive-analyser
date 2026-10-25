from tests.test_postgres_media_startup_lot1 import pg  # noqa: F401
from tests.test_media_startup_lot3 import root, test_real_ffmpeg_bounded_webp_and_backfill as exercise  # noqa: F401


def test_animated_roundtrip_postgres(pg, root, monkeypatch):
    _, factory, _ = pg
    with factory() as db:
        exercise(db, root, monkeypatch)


def test_animated_refresh_orphan_accounted_and_reclaimed(pg, root, monkeypatch):
    from tests.test_media_startup_lot3 import test_backfill_releases_connection_and_fences_changed_proxy
    with pg[1]() as db:
        test_backfill_releases_connection_and_fences_changed_proxy(db, root, monkeypatch)


def test_animated_shared_reference_cleanup(pg, root):
    from tests.test_media_startup_lot3 import test_animation_cleanup_preserves_shared_references_and_bounds
    # The generic eviction path clears real resolution-upgrade FK pointers.
    from app.database import Base
    from app.models.media_catalog import MediaResolutionUpgradeItem
    tables = {MediaResolutionUpgradeItem.__table__}
    pending = list(tables)
    while pending:
        for fk in pending.pop().foreign_keys:
            if fk.column.table not in tables:
                tables.add(fk.column.table)
                pending.append(fk.column.table)
    Base.metadata.create_all(pg[0], tables=list(tables))
    with pg[1]() as db:
        test_animation_cleanup_preserves_shared_references_and_bounds(db, root)


def test_animated_cleanup_racing_delayed_publisher(pg, root, monkeypatch):
    import os
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from app.models.media import MediaCacheEntry
    from app.models.photos_asset import PhotosAsset
    from app.services import animated_visuals, poster_visuals
    with pg[1]() as db:
        asset = PhotosAsset(video_uuid='animated-delayed')
        db.add(asset)
        db.flush()
        db.add(MediaCacheEntry(photos_asset_id=asset.id, media_key='delayed-proxy',
            rendition='proxy_720p', storage_path=str(root / 'proxy.mp4'),
            size_bytes=10, checksum_sha256='a' * 64, status='ready'))
        db.commit()
    locked = threading.Event()
    generated = threading.Event()
    files = poster_visuals.thumbnail_files
    def wait_for_generation(namespace='thumb'):
        assert namespace == 'animated'
        locked.set()
        assert generated.wait(5)
        yield from files(namespace)
    def generate(_):
        path = root / 'animated' / 'cc' / ('c' * 64 + '.webp')
        path.parent.mkdir(parents=True)
        path.write_bytes(b'animation')
        os.utime(path, (0, 0))
        generated.set()
        return str(path), 'c' * 64, 9
    monkeypatch.setattr(poster_visuals, 'thumbnail_files', wait_for_generation)
    monkeypatch.setattr(animated_visuals, 'generate', generate)
    def cleanup():
        with pg[1]() as db:
            return poster_visuals.cleanup_orphan_thumbnails(db, namespace='animated')
    def publish():
        with pg[1]() as db:
            return animated_visuals.backfill(db, 1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        cleaning = pool.submit(cleanup)
        assert locked.wait(5)
        publishing = pool.submit(publish)
        assert cleaning.result(10) == 9
        assert publishing.result(10)['generated'] == 0
    with pg[1]() as db:
        assert db.query(MediaCacheEntry).filter_by(rendition='animated').count() == 0
