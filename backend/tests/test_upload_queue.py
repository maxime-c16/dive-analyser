"""Queue privacy, restart recovery and publication atomicity."""
from datetime import datetime
from pathlib import Path
from sqlalchemy.orm import sessionmaker
from tests.test_member_dive_visibility import workspace
from app.models.browser_upload import BrowserUploadJob
from app.models.dive import Dive
from app.services.dive_access import owned_diver_ids


def fields(db, user, upload_id='12345678-1234-1234-1234-123456789012'):
    return dict(dive_code='103B', height='3m', performance='G', dive_datetime='2026-10-05T12:00:00', diver_id=owned_diver_ids(db, user.id)[0], upload_id=upload_id, filename='video.mp4')


def upload(client, data, filename='video.mp4', content=b'video'):
    result = client.post('/api/v1/dives/uploads', json={**data, 'filename': filename})
    if result.status_code == 202 and result.json()['status'] == 'receiving':
        return client.put('/api/v1/dives/uploads/' + data['upload_id'] + '/content', content=content)
    return result


def test_queue_is_durable_idempotent_and_account_private(workspace, monkeypatch):
    from app.services import upload_queue
    db, login, _, users, _ = workspace
    monkeypatch.setattr(upload_queue.shutil, 'disk_usage', lambda _: type('Disk', (), {'free': 100 * 1024**3})())
    data = fields(db, users['bob'])
    result = upload(login('bob'), data)
    assert result.status_code == 202, result.text
    assert result.json()['status'] == 'queued'
    retry = upload(login('bob'), data, 'different.mp4', b'other bytes')
    assert retry.json() == result.json()
    job = db.query(BrowserUploadJob).one()
    assert Path(job.storage_path).read_bytes() == b'video'
    assert login('alice').get('/api/v1/dives/uploads/' + data['upload_id']).status_code == 404
    assert login('bob').get('/api/v1/dives/uploads/' + data['upload_id']).json()['status'] == 'queued'


def test_failed_publication_keeps_no_dive_and_can_be_retried(workspace, monkeypatch):
    from app.services import upload_queue
    from app.api.v1 import dives
    from fastapi import HTTPException
    db, login, _, users, _ = workspace
    monkeypatch.setattr(upload_queue.shutil, 'disk_usage', lambda _: type('Disk', (), {'free': 100 * 1024**3})())
    data = fields(db, users['bob'])
    upload(login('bob'), data)
    monkeypatch.setattr(upload_queue, 'engine', db.get_bind())
    monkeypatch.setattr(upload_queue, 'SessionLocal', sessionmaker(bind=db.get_bind(), expire_on_commit=False))
    before = db.query(Dive).count()
    def fail(**kw):
        raise HTTPException(503, 'Video storage unavailable; please retry')
    monkeypatch.setattr(dives, 'upload_dive', fail)
    assert upload_queue.process_one() is True
    db.expire_all()
    job = db.query(BrowserUploadJob).one()
    assert job.status == 'failed'
    assert not Path(job.storage_path).exists()
    assert db.query(Dive).count() == before
    assert upload(login('bob'), data).json()['status'] == 'queued'
    assert db.query(BrowserUploadJob).count() == 1


def test_interrupted_processing_resumes_and_marks_ready(workspace, monkeypatch):
    from app.services import upload_queue
    from app.api.v1 import dives
    db, login, _, users, _ = workspace
    monkeypatch.setattr(upload_queue.shutil, 'disk_usage', lambda _: type('Disk', (), {'free': 100 * 1024**3})())
    data = fields(db, users['bob'])
    upload(login('bob'), data)
    job = db.query(BrowserUploadJob).one()
    job.status, job.attempts = 'processing', 1
    db.commit()
    monkeypatch.setattr(upload_queue, 'engine', db.get_bind())
    monkeypatch.setattr(upload_queue, 'SessionLocal', sessionmaker(bind=db.get_bind(), expire_on_commit=False))
    calls = []
    def publish(**kw):
        calls.append(kw['file'].file.read())
        return {'id': 123}
    monkeypatch.setattr(dives, 'upload_dive', publish)
    assert upload_queue.process_one() is True
    db.expire_all()
    job = db.query(BrowserUploadJob).one()
    assert (job.status, job.result_id, job.attempts) == ('ready', 123, 2)
    assert calls == [b'video']
    assert upload_queue.process_one() is False


def test_quota_and_permissions_are_checked_before_staging(workspace, monkeypatch):
    from app.services import upload_queue
    db, login, _, users, _ = workspace
    monkeypatch.setattr(upload_queue.shutil, 'disk_usage', lambda _: type('Disk', (), {'free': 100 * 1024**3})())
    data = fields(db, users['bob'])
    assert upload(login('alice'), data).status_code == 403
    for identity in ['12345678-1234-1234-1234-123456789012', '22345678-1234-1234-1234-123456789012']:
        data['upload_id'] = identity
        assert upload(login('bob'), data).status_code == 202
    data['upload_id'] = '32345678-1234-1234-1234-123456789012'
    assert upload(login('bob'), data).status_code == 429
    assert db.query(BrowserUploadJob).count() == 2


def test_reservation_precedes_bytes_and_rejects_unreserved_or_oversized_body(workspace, monkeypatch):
    from app.services import upload_queue
    db, login, _, users, _ = workspace
    monkeypatch.setattr(upload_queue.shutil, 'disk_usage', lambda _: type('Disk', (), {'free': 100 * 1024**3})())
    data = fields(db, users['bob'])
    client = login('bob')
    url = '/api/v1/dives/uploads/' + data['upload_id'] + '/content'
    assert client.put(url, content=b'video').status_code == 404
    assert client.post('/api/v1/dives/uploads', json=data).json()['status'] == 'receiving'
    job = db.query(BrowserUploadJob).one()
    job_id, job_path = job.id, Path(job.storage_path)
    assert not job_path.exists()
    assert login('alice').put(url, content=b'video').status_code == 404
    monkeypatch.setattr(upload_queue, 'MAX_BYTES', 3)
    assert login('bob').put(url, content=b'too large').status_code == 413
    db.expire_all()
    assert db.get(BrowserUploadJob, job_id).status == 'failed'
    assert not job_path.exists()


def test_retired_multipart_route_cannot_bypass_reservations(workspace):
    db, login, _, _, _ = workspace
    response = login('bob').post('/api/v1/dives/upload', files={'file': ('video.mp4', b'video')})
    assert response.status_code == 410
    assert db.query(BrowserUploadJob).count() == 0


def test_chunked_ingress_enforces_actual_byte_limit(workspace, monkeypatch):
    import asyncio
    import pytest
    from types import SimpleNamespace
    from fastapi import HTTPException
    from app.models.user_auth import AppUser
    from app.services import upload_queue
    db, login, _, users, _ = workspace
    monkeypatch.setattr(upload_queue.shutil, 'disk_usage', lambda _: type('Disk', (), {'free': 100 * 1024**3})())
    data = fields(db, users['bob'])
    user_id = users['bob'].id
    login('bob').post('/api/v1/dives/uploads', json=data)
    async def stream():
        yield b'ab'
        yield b'cd'
    monkeypatch.setattr(upload_queue, 'MAX_BYTES', 3)
    with pytest.raises(HTTPException) as error:
        asyncio.run(upload_queue.receive(db, db.get(AppUser, user_id), data['upload_id'], SimpleNamespace(headers={}, stream=stream)))
    assert error.value.status_code == 413
    job = db.query(BrowserUploadJob).one()
    assert job.status == 'failed'
    assert not Path(job.storage_path).exists()


def test_active_stream_refreshes_its_receiving_lease(workspace, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from datetime import timedelta
    from app.models.user_auth import AppUser
    from app.services import upload_queue
    db, login, _, users, _ = workspace
    monkeypatch.setattr(upload_queue.shutil, 'disk_usage', lambda _: type('Disk', (), {'free': 100 * 1024**3})())
    data = fields(db, users['bob'])
    user_id = users['bob'].id
    login('bob').post('/api/v1/dives/uploads', json=data)
    clock = [0]
    monkeypatch.setattr(upload_queue, 'monotonic', lambda: clock[0])
    async def stream():
        db.query(BrowserUploadJob).update({'updated_at': datetime.utcnow() - timedelta(hours=2)})
        db.commit()
        clock[0] = 40
        yield b'a'
        db.expire_all()
        assert db.query(BrowserUploadJob).one().updated_at > datetime.utcnow() - timedelta(minutes=1)
        db.rollback()
        yield b'b'
    result = asyncio.run(upload_queue.receive(db, db.get(AppUser, user_id), data['upload_id'], SimpleNamespace(headers={}, stream=stream)))
    assert result['status'] == 'queued'
