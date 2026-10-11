"""One durable ingestion worker; bounded disk and concurrency, short SQL writes.

The PostgreSQL session advisory lock serializes workers across Uvicorn
processes without holding a SQL transaction during transcode/B2 verification.
Interrupted processing jobs resume after the prior process releases that lock.
"""
import logging
import shutil
import threading
from time import monotonic
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from sqlalchemy import select, text
from starlette.requests import Request
from app.config import get_settings
from app.database import SessionLocal, engine
from app.models.browser_upload import BrowserUploadJob
from app.models.user_auth import AppUser
from app.services.browser_upload import MAX_BYTES

logger = logging.getLogger(__name__)
_LOCK = threading.Lock()
_ADVISORY_KEY = 834928
ACTIVE = ('receiving', 'queued', 'processing')


def summary(job):
    return dict(upload_id=job.upload_id, status=job.status, dive_id=job.result_id, error=job.last_error)


def enqueue(db, user, file, payload):
    from app.services.dive_access import owned_diver_ids
    from app.services.dive_code_parser import DiveCodeParser
    from app.models.diver import Diver
    from app.services.dive_access import unscoped_reads
    from uuid import UUID
    try:
        UUID(payload['upload_id'])
    except ValueError:
        raise HTTPException(422, 'Invalid upload identity') from None
    if not user or not user.is_active:
        raise HTTPException(401, 'Authentication required')
    owned = payload['diver_id'] in owned_diver_ids(db, user.id)
    if not owned and not user.is_admin:
        raise HTTPException(403, 'Choose a diver you own')
    with unscoped_reads(db):
        if db.get(Diver, payload['diver_id']) is None:
            raise HTTPException(404, 'Diver not found')
    parsed = DiveCodeParser.parse(f"{payload['dive_code']} {payload['performance']} {payload['height']}")
    if not parsed.is_valid:
        raise HTTPException(422, parsed.error or 'Invalid dive code')
    # One row lock serializes all reservations (also across Uvicorn workers).
    # The lock is released before copying any upload bytes.
    db.execute(select(AppUser.id).order_by(AppUser.id).limit(1).with_for_update()).first()
    existing = db.query(BrowserUploadJob).filter_by(user_id=user.id, upload_id=payload['upload_id']).first()
    if existing and existing.status != 'failed':
        return summary(existing)
    active = db.query(BrowserUploadJob).filter(BrowserUploadJob.status.in_(ACTIVE)).all()
    if len(active) >= 8 or sum(job.user_id == user.id for job in active) >= 2:
        raise HTTPException(429, 'Upload queue is full; wait for current videos to finish')
    root = Path(get_settings().media_cache_root).resolve() / 'upload-queue'
    root.mkdir(parents=True, exist_ok=True)
    # Reserve worst-case space for staged source, processing copy, full-size
    # encode and poster. Encoding expansion is additionally guarded below.
    if shutil.disk_usage(root).free < (len(active) + 1) * 4 * MAX_BYTES + MAX_BYTES:
        raise HTTPException(507, 'Video storage is temporarily full')
    path = root / uuid4().hex
    job = existing or BrowserUploadJob(user_id=user.id, upload_id=payload['upload_id'])
    job.payload = payload
    job.filename = Path(file.filename or 'video.mp4').name[:255]
    job.storage_path = str(path)
    job.status = 'receiving'
    job.attempts = 0
    job.last_error = None
    job.updated_at = datetime.utcnow()
    db.add(job)
    db.commit()
    try:
        size = 0
        with path.open('xb') as target:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise HTTPException(413, 'Video exceeds 1 GB')
                target.write(chunk)
        if not size:
            raise HTTPException(422, 'Empty video')
        job.status = 'queued'
        db.commit()
        return summary(job)
    except BaseException:
        db.rollback()
        path.unlink(missing_ok=True)
        job.status = 'failed'
        job.last_error = 'Upload interrupted; please retry'
        db.commit()
        raise


def process_one():
    if not _LOCK.acquire(blocking=False):
        return False
    connection = None
    locked = False
    try:
        if engine.dialect.name == 'postgresql':
            connection = engine.connect()
            locked = bool(connection.execute(text('SELECT pg_try_advisory_lock(:key)'), {'key': _ADVISORY_KEY}).scalar())
            connection.commit()
            if not locked:
                return False
        with SessionLocal() as db:
            # A crashed receiver never becomes processable; free its slot.
            abandoned = db.query(BrowserUploadJob).filter(BrowserUploadJob.status == 'receiving', BrowserUploadJob.updated_at < datetime.utcnow() - timedelta(hours=1)).all()
            for job in abandoned:
                Path(job.storage_path).unlink(missing_ok=True)
                job.status, job.last_error = 'failed', 'Upload interrupted; please retry'
            job = db.query(BrowserUploadJob).filter(BrowserUploadJob.status.in_(('queued', 'processing'))).order_by(BrowserUploadJob.created_at, BrowserUploadJob.id).first()
            if job is None:
                db.commit()
                return False
            if job.attempts >= 3:
                Path(job.storage_path).unlink(missing_ok=True)
                job.status, job.last_error = 'failed', 'Video processing interrupted repeatedly; please retry'
                db.commit()
                return True
            job.status = 'processing'
            job.attempts += 1
            job_id, user_id = job.id, job.user_id
            payload, path, filename = dict(job.payload), Path(job.storage_path), job.filename
            db.commit()
        try:
            with SessionLocal() as db:
                from app.api.v1.dives import upload_dive
                from app.services.dive_access import owned_diver_ids
                user = db.get(AppUser, user_id)
                if not user or not user.is_active:
                    raise HTTPException(403, 'Upload account is no longer active')
                db.info['member_access'] = dict(user_id=user.id, diver_ids=owned_diver_ids(db, user.id), is_admin=bool(user.is_admin))
                request = Request({'type': 'http', 'method': 'POST', 'path': '/api/v1/dives/upload', 'headers': []})
                request.state.member_user = user
                with path.open('rb') as source:
                    file = UploadFile(source, filename=filename)
                    from datetime import datetime as dt
                    payload['dive_datetime'] = dt.fromisoformat(payload['dive_datetime'])
                    result = upload_dive(request=request, file=file, db=db, **payload)
                    result_id = result['id'] if isinstance(result, dict) else result.id
            status, error = 'ready', None
        except Exception as exc:
            logger.exception('Browser upload job %s failed', job_id)
            status, result_id = 'failed', None
            error = exc.detail if isinstance(exc, HTTPException) and isinstance(exc.detail, str) else 'Video processing failed; please retry'
        with SessionLocal() as db:
            job = db.get(BrowserUploadJob, job_id)
            job.status, job.result_id, job.last_error = status, result_id, error[:200] if error else None
            db.commit()
        path.unlink(missing_ok=True)
        return True
    finally:
        if connection is not None:
            try:
                if locked:
                    connection.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': _ADVISORY_KEY})
                    connection.commit()
            finally:
                connection.close()
        _LOCK.release()


def start_worker():
    stop = threading.Event()
    def run():
        last_cleanup = 0.0
        while not stop.is_set():
            try:
                busy = process_one()
                if not busy and monotonic() - last_cleanup > 600:
                    from app.services.media_cache import cleanup_cache
                    with SessionLocal() as db:
                        cleanup_cache(db)
                        db.commit()
                    last_cleanup = monotonic()
            except Exception:
                logger.exception('Upload queue worker unavailable')
                busy = False
            stop.wait(1 if busy else 3)
    thread = threading.Thread(target=run, daemon=True, name='browser-upload-worker')
    thread.start()
    return stop
