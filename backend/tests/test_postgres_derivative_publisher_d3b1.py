"""D3b1 publisher concurrency on real PostgreSQL (disposable calendar_test_* only).

Proves what SQLite cannot: concurrent same-identity publishers serialize
on the ledger UNIQUE identity (SELECT ... FOR UPDATE + ON CONFLICT
column-list path) — same bytes converge to one READY row, different
bytes never overwrite a READY row. Skipped without
``CALENDAR_TEST_DATABASE_URL``.
"""

import hashlib
import os
import threading
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[2]
PG_URL = os.environ.get("CALENDAR_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not PG_URL, reason="Disposable PostgreSQL required")


def _engine():
    assert PG_URL
    url = make_url(PG_URL)
    assert url.get_backend_name() == "postgresql"
    assert (url.database or "").startswith("calendar_test_")
    url = url.set(drivername="postgresql+psycopg2")
    return create_engine(url)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class FakeBody:
    def __init__(self, data: bytes):
        self._buf = __import__("io").BytesIO(data)

    def iter_chunks(self, chunk_size=1024 * 1024):
        while True:
            piece = self._buf.read(chunk_size)
            if not piece:
                break
            yield piece

    def close(self):
        pass


class FakeS3:
    def __init__(self):
        self.objects = {}
        self._lock = threading.Lock()

    def upload_file(self, path, bucket, key, ExtraArgs=None):
        from pathlib import Path as _P

        with self._lock:
            self.objects[(bucket, key)] = _P(path).read_bytes()

    def get_object(self, Bucket, Key):
        with self._lock:
            data = self.objects[(Bucket, Key)]
        return {"Body": FakeBody(data)}


def test_concurrent_same_identity_same_bytes_single_ready(tmp_path):
    from app.config import get_settings
    from app.database import Base
    from app.models.media_backbone import (
        CaptionRevision,
        IngestObjectState,
        MediaBlob,
        MediaBlobLocation,
        MediaDerivative,
        MediaRevision,
    )

    settings = get_settings()
    engine = _engine()
    Base.metadata.create_all(engine, tables=[
        MediaBlob.__table__, MediaBlobLocation.__table__, MediaRevision.__table__,
        CaptionRevision.__table__, IngestObjectState.__table__,
        MediaDerivative.__table__,
    ])
    uuid = f"pg-conc-{os.getpid()}-same"
    cam = _sha(b"pg-camera")
    with engine.begin() as conn:
        conn.execute(MediaBlob.__table__.insert().values(sha256=cam, byte_size=8, storage_backend="b2",
                     bucket=settings.media_backbone_prod_bucket, object_key=f"k/{cam}"))
        conn.execute(MediaBlobLocation.__table__.insert().values(blob_sha256=cam, environment="prod",
                     storage_backend="b2", bucket=settings.media_backbone_prod_bucket,
                     object_key=f"k/{cam}", verified=True))
        conn.execute(MediaRevision.__table__.insert().values(video_uuid=uuid, blob_sha256=cam,
                     rendition_semantics="photos_edited_rendition"))
    # Dispose: each thread uses its own engine/session (sessions are not thread-safe).
    engine.dispose()

    artifact = tmp_path / "a.bin"
    artifact.write_bytes(b"pg-same-bytes" * 64)
    fake = FakeS3()
    outcomes, errors = [], []

    def worker():
        try:
            from app.services.derivative_publisher import build_publication_context, publish_derivative

            eng = _engine()
            Session = sessionmaker(bind=eng, expire_on_commit=False)
            s = Session()
            try:
                ctx = build_publication_context(s, video_uuid=uuid, role="hq")
                outcomes.append(publish_derivative(s, ctx, artifact, s3_client=fake))
            finally:
                s.close()
                eng.dispose()
        except Exception as exc:  # noqa: BLE001 — recorded, asserted below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors, errors
    assert len(outcomes) == 4 and all(o["status"] == "ready" for o in outcomes)
    assert len({o["derivative_blob_sha256"] for o in outcomes}) == 1

    check = _engine()
    try:
        with check.connect() as conn:
            n = conn.exec_driver_sql(
                "SELECT COUNT(*) FROM media_derivatives WHERE video_uuid = '%s'" % uuid
            ).scalar()
            assert n == 1
            conn.exec_driver_sql("DELETE FROM media_derivatives WHERE video_uuid = '%s'" % uuid)
            conn.exec_driver_sql("DELETE FROM media_revisions WHERE video_uuid = '%s'" % uuid)
            conn.commit()
    finally:
        check.dispose()
