"""Post-commit poster enrichment must neither hold SQL nor freeze the loop."""
import asyncio
import hashlib
import threading
import time

from fastapi import FastAPI
import httpx
from PIL import Image
import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.api.v1 import media
from app.models.media import MediaCacheEntry
from app.schemas.media import MediaJobFinalizeRequest
from app.services import poster_visuals
from tests.test_media_offload_cancellation import _seed_verifying_job
from tests.test_media_startup_lot2 import root  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.parametrize('fails', [False, True])
async def test_finalizing_poster_keeps_light_request_under_100ms(test_db, root, monkeypatch, fails):
    job = _seed_verifying_job(test_db, root)
    job.rendition = 'poster'
    Image.new('RGB', (64, 64), '#2277aa').save(job.upload_tmp_path, format='JPEG')
    from pathlib import Path
    data = Path(job.upload_tmp_path).read_bytes()
    job_id = job.id
    test_db.commit()
    monkeypatch.setattr(media, '_agent_auth', lambda *a: None)
    started, release = threading.Event(), threading.Event()
    loop_thread = threading.get_ident()
    original = poster_visuals.enrich_poster
    engine = test_db.get_bind()
    loop_sql = []
    def capture(conn, cursor, statement, *args):
        if threading.get_ident() == loop_thread:
            loop_sql.append(statement)
    event.listen(engine, 'before_cursor_execute', capture)

    def slow(snapshot):
        assert threading.get_ident() != loop_thread
        assert not test_db.in_transaction(), 'poster writer still holds a transaction'
        # The poster/job commit is already visible independently of enrichment.
        with Session(bind=engine) as db:
            assert db.get(MediaCacheEntry, snapshot.id).status == 'ready'
        started.set()
        assert release.wait(5)
        if fails:
            raise RuntimeError('injected optional image failure')
        original(snapshot)
    monkeypatch.setattr(poster_visuals, 'enrich_poster', slow)
    payload = MediaJobFinalizeRequest(agent_id='agent-x', checksum_sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data), content_type='image/jpeg')
    app = FastAPI()
    @app.post('/finalize')
    async def finalize():
        return await media.finalize_job_artifact(job_id, payload, test_db, {})
    @app.get('/light')
    async def light():
        return {'ok': True}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://local') as client:
            task = asyncio.create_task(client.post('/finalize'))
            try:
                assert await asyncio.to_thread(started.wait, 5)
                before = time.perf_counter()
                response = await asyncio.wait_for(client.get('/light'), timeout=.1)
                elapsed = time.perf_counter() - before
                assert response.status_code == 200 and elapsed < .1
                assert not task.done(), 'enrichment should still be running'
                print(f'light request during blocked enrichment: {elapsed*1000:.2f} ms (fails={fails})')
            finally:
                release.set()
            response = await task
            assert response.status_code == 200
            assert loop_sql == [], 'finalize ran SQL on the event loop'
    finally:
        release.set()
        event.remove(engine, 'before_cursor_execute', capture)
    row = test_db.get(MediaCacheEntry, response.json()['cache_entry_id'])
    assert row.thumbhash is None if fails else row.thumbhash is not None


def test_flush_never_invokes_image_work(test_db, root, monkeypatch):
    from app.models.photos_asset import PhotosAsset
    monkeypatch.setattr(poster_visuals, 'enrich_poster', lambda *a: pytest.fail('image work during flush'))
    asset = PhotosAsset(video_uuid='flush-no-image')
    test_db.add(asset)
    test_db.flush()
    row = MediaCacheEntry(photos_asset_id=asset.id, media_key='flush-only', rendition='poster',
        storage_path=str(root/'poster.jpg'), checksum_sha256='a'*64, size_bytes=1, status='ready')
    test_db.add(row)
    test_db.flush()
    test_db.commit()
    row.storage_path = str(root/'refresh.jpg')
    row.checksum_sha256 = 'b'*64
    test_db.commit()
    assert row.thumbhash is None and row.thumb_storage_path is None


def exercise_refresh_race(bind, entry_id, root, monkeypatch):
    """Pause old enrichment outside SQL; publish and enrich a newer poster."""
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path
    from sqlalchemy import update
    with Session(bind=bind) as db:
        old_checksum = db.get(MediaCacheEntry, entry_id).checksum_sha256
    started, release = threading.Event(), threading.Event()
    original = poster_visuals.enrich_poster
    def blocked(snapshot):
        original(snapshot)
        if snapshot.checksum_sha256 == old_checksum:
            if hasattr(bind.pool, 'checkedout'):
                assert bind.pool.checkedout() == 0, 'SQL connection retained during image work'
            started.set()
            assert release.wait(5)
    monkeypatch.setattr(poster_visuals, 'enrich_poster', blocked)
    with ThreadPoolExecutor(max_workers=1) as worker:
        old_result = worker.submit(poster_visuals.enrich_committed_poster, entry_id, bind=bind)
        try:
            assert started.wait(5)
            new_path = root/'new-version.jpg'
            Image.new('RGB', (1080, 1920), '#ee9922').save(new_path)
            new_sha = hashlib.sha256(new_path.read_bytes()).hexdigest()
            with Session(bind=bind) as db:
                db.execute(update(MediaCacheEntry).where(MediaCacheEntry.id == entry_id).values(
                    storage_path=str(new_path), checksum_sha256=new_sha,
                    **{name: None for name in poster_visuals.VISUAL_FIELDS}))
                db.commit()
            assert poster_visuals.enrich_committed_poster(entry_id, bind=bind)
            with Session(bind=bind) as db:
                row = db.get(MediaCacheEntry, entry_id)
                new_hash, new_thumb = row.thumbhash, row.thumb_storage_path
                assert new_hash and Path(new_thumb).is_file()
        finally:
            release.set()
        assert old_result.result(timeout=5) is False
    with Session(bind=bind) as db:
        row = db.get(MediaCacheEntry, entry_id)
        assert row.checksum_sha256 == new_sha
        assert row.thumbhash == new_hash and row.thumb_storage_path == new_thumb


def test_refresh_fences_old_enrichment(test_db, root, monkeypatch):
    from tests.test_media_startup_lot2 import poster
    entry = poster(test_db, root)
    entry_id = entry.id
    test_db.rollback()
    exercise_refresh_race(test_db.get_bind(), entry_id, root, monkeypatch)


def test_unexpected_image_error_logs_and_persists_null_fields(test_db, root, monkeypatch, caplog):
    from tests.test_media_startup_lot2 import poster
    entry = poster(test_db, root)
    entry_id = entry.id
    test_db.rollback()
    def fail(snapshot):
        raise RuntimeError('unexpected encoder error')
    monkeypatch.setattr(poster_visuals, 'enrich_poster', fail)
    assert poster_visuals.enrich_committed_poster(entry_id, bind=test_db.get_bind())
    with Session(bind=test_db.get_bind()) as db:
        row = db.get(MediaCacheEntry, entry_id)
        assert all(getattr(row, name) is None for name in poster_visuals.VISUAL_FIELDS)
    assert 'Poster enrichment failed' in caplog.text
