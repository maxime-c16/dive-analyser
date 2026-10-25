"""Manual migration and bounded visual backfill against disposable local PG."""
from pathlib import Path
from sqlalchemy import text
from tests.test_postgres_media_startup_lot1 import pg  # noqa: F401
from tests.test_media_startup_lot2 import root, poster  # noqa: F401
from app.models.media import MediaCacheEntry
from app.services.poster_visuals import backfill


def test_manual_migration_is_additive_and_idempotent(pg):
    engine, _, _ = pg
    migration = (Path(__file__).parents[1] / 'migrations/add_poster_visuals.sql').read_text()
    with engine.begin() as conn:
        # Temporary relation shadows only this test connection's table.
        conn.execute(text('CREATE TEMP TABLE media_cache_entries (id integer) ON COMMIT DROP'))
        for _ in range(2):
            conn.execute(text(migration))
        conn.execute(text('SELECT thumbhash, thumb_storage_path, thumb_checksum_sha256, thumb_size_bytes FROM media_cache_entries'))


def test_poster_roundtrip_and_bounded_backfill_on_postgres(pg, root):
    _, factory, _ = pg
    with factory() as db:
        entry = poster(db, root)
        old_hash = entry.thumbhash
        entry.thumbhash = entry.thumb_storage_path = None
        db.commit()
        assert backfill(db, limit=1, after_id=entry.id-1)['after_id'] == entry.id
        db.expire_all()
        assert db.get(MediaCacheEntry, entry.id).thumbhash == old_hash


def test_refresh_fences_enrichment_without_holding_connection(pg, root, monkeypatch):
    from tests.test_poster_enrichment_offload import exercise_refresh_race
    engine, factory, _ = pg
    with factory() as db:
        entry = poster(db, root)
        entry_id = entry.id
    exercise_refresh_race(engine, entry_id, root, monkeypatch)


def test_thumbnail_accounting_and_cleanup_on_postgres(pg, root):
    from tests.test_media_startup_lot2 import test_thumbnail_accounting_and_reference_aware_cleanup
    _, factory, _ = pg
    with factory() as db:
        test_thumbnail_accounting_and_reference_aware_cleanup(db, root)


def test_cleanup_racing_publication_never_leaves_dangling_thumb(pg, root, monkeypatch):
    import os
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from app.services import poster_visuals
    _, factory, _ = pg
    with factory() as db:
        entry_id = poster(db, root).id
    locked = threading.Event()
    generated = threading.Event()
    files = poster_visuals.thumbnail_files
    enrich = poster_visuals.enrich_poster

    def wait_for_generation():
        locked.set()  # cleanup holds the inter-process filesystem lock
        assert generated.wait(5)
        yield from files()

    def delayed_publication(snapshot):
        enrich(snapshot)
        # Model a long-delayed publisher whose generated file aged out.
        os.utime(snapshot.thumb_storage_path, (0, 0))
        generated.set()

    monkeypatch.setattr(poster_visuals, 'thumbnail_files', wait_for_generation)
    monkeypatch.setattr(poster_visuals, 'enrich_poster', delayed_publication)
    with factory() as db:
        entry = db.get(MediaCacheEntry, entry_id)
        poster_visuals.clear_visuals(entry)
        db.commit()
    def cleanup():
        with factory() as db:
            return poster_visuals.cleanup_orphan_thumbnails(db)
    with ThreadPoolExecutor(max_workers=2) as pool:
        cleaning = pool.submit(cleanup)
        assert locked.wait(5)
        publishing = pool.submit(poster_visuals.enrich_committed_poster, entry_id, bind=pg[0])
        assert cleaning.result(10) > 0
        assert publishing.result(10)
    with factory() as db:
        entry = db.get(MediaCacheEntry, entry_id)
        assert entry.thumb_storage_path is None
        assert entry.status == 'ready'
        assert Path(entry.storage_path).is_file()
