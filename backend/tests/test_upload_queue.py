"""Queue privacy, restart recovery and publication atomicity."""
from datetime import datetime
from pathlib import Path
from sqlalchemy.orm import sessionmaker
from tests.test_member_dive_visibility import workspace
from app.models.browser_upload import BrowserUploadJob
from app.models.dive import Dive
from app.services.dive_access import owned_diver_ids


def fields(db, user, upload_id='12345678-1234-1234-1234-123456789012'):
    return dict(dive_code='103B', height='3m', performance='G', dive_datetime='2026-10-05T12:00:00', diver_id=str(owned_diver_ids(db, user.id)[0]), upload_id=upload_id)


def test_queue_is_durable_idempotent_and_account_private(workspace, monkeypatch):
    from app.services import upload_queue
    db, login, _, users, _ = workspace
    monkeypatch.setattr(upload_queue.shutil, 'disk_usage', lambda _: type('Disk', (), {'free': 100 * 1024**3})())
    data = fields(db, users['bob'])
    result = login('bob').post('/api/v1/dives/uploads', data=data, files={'file': ('video.mp4', b'video')})
    assert result.status_code == 202, result.text
    assert result.json()['status'] == 'queued'
    retry = login('bob').post('/api/v1/dives/uploads', data=data, files={'file': ('different.mp4', b'other bytes')})
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
    login('bob').post('/api/v1/dives/uploads', data=data, files={'file': ('video.mp4', b'video')})
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
    assert login('bob').post('/api/v1/dives/uploads', data=data, files={'file': ('video.mp4', b'video')}).json()['status'] == 'queued'
    assert db.query(BrowserUploadJob).count() == 1


def test_interrupted_processing_resumes_and_marks_ready(workspace, monkeypatch):
    from app.services import upload_queue
    from app.api.v1 import dives
    db, login, _, users, _ = workspace
    monkeypatch.setattr(upload_queue.shutil, 'disk_usage', lambda _: type('Disk', (), {'free': 100 * 1024**3})())
    data = fields(db, users['bob'])
    login('bob').post('/api/v1/dives/uploads', data=data, files={'file': ('video.mp4', b'video')})
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
    assert login('alice').post('/api/v1/dives/uploads', data=data, files={'file': ('video.mp4', b'video')}).status_code == 403
    for identity in ['12345678-1234-1234-1234-123456789012', '22345678-1234-1234-1234-123456789012']:
        data['upload_id'] = identity
        assert login('bob').post('/api/v1/dives/uploads', data=data, files={'file': ('video.mp4', b'video')}).status_code == 202
    data['upload_id'] = '32345678-1234-1234-1234-123456789012'
    assert login('bob').post('/api/v1/dives/uploads', data=data, files={'file': ('video.mp4', b'video')}).status_code == 429
    assert db.query(BrowserUploadJob).count() == 2
