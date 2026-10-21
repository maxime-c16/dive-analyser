"""D3b1 publisher concurrency on real PostgreSQL (disposable calendar_test_* only).

Wired into the CI ``postgres`` tier (``ci/postgres.sh``). Proves what
SQLite cannot:

- concurrent same-identity publishers serialize on the ledger identity
  (``SELECT ... FOR UPDATE`` + UNIQUE identity index + ``IntegrityError``
  rival path): same bytes converge to ONE ready row; different bytes
  elect exactly one ready winner and every loser gets
  ``DerivativeIdentityConflict`` (the ready row is never overwritten);
- absent-row insert races resolve through the ``IntegrityError`` rival
  path — deterministic via an upload-gate barrier shared by all racing
  threads, not timing;
- the ``FOR UPDATE`` lock is real, not mocked: a holder transaction
  blocks a concurrent same-bytes publisher until commit (event-ordered,
  no timing asserts), and the waiter then observes the committed row
  (identity-map refresh via ``populate_existing``), returning an
  idempotent ready instead of re-promoting;
- every ready decision rechecks the canonical source on PG too
  (drifted replay → stale, never ready; existing ready untouched);
- session hygiene: scoped fixtures (per-test ``uuid4`` namespaces,
  own-row cleanup only, parameterized SQL) so this file runs in the
  full ordered tier alongside D1/D2 tests sharing one database without
  touching other namespaces.

Skipped without ``CALENDAR_TEST_DATABASE_URL``. Nothing outside the
disposable database is touched; no real B2 (thread-safe in-memory S3
fake), no mocks of the locking path.
"""

import hashlib
import os
import threading
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[2]
PG_URL = os.environ.get("CALENDAR_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not PG_URL, reason="Disposable PostgreSQL required")


def _engine():
    assert PG_URL, "CALENDAR_TEST_DATABASE_URL is required"
    url = make_url(PG_URL)
    assert url.get_backend_name() == "postgresql", "PostgreSQL only"
    assert (url.database or "").startswith("calendar_test_"), (
        "Disposable calendar_test_* database required — refusing anything else"
    )
    url = url.set(drivername="postgresql+psycopg2")
    return create_engine(url)


def _make_tables(engine):
    from app.database import Base
    from app.models.media_backbone import (  # noqa: F401 — mapper registration
        CaptionRevision,
        IngestObjectState,
        MediaBlob,
        MediaBlobLocation,
        MediaDerivative,
        MediaRevision,
    )

    Base.metadata.create_all(
        engine,
        tables=[
            MediaBlob.__table__,
            MediaBlobLocation.__table__,
            MediaRevision.__table__,
            CaptionRevision.__table__,
            IngestObjectState.__table__,
            MediaDerivative.__table__,
        ],
    )


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
    """Thread-safe in-memory S3 with an optional upload gate (fault-free)."""

    def __init__(self, gate=None):
        self.objects = {}
        self._lock = threading.Lock()
        self._gate = gate
        self.uploads = 0

    def upload_file(self, path, bucket, key, ExtraArgs=None):
        if self._gate is not None:
            self._gate.wait(timeout=60)
        from pathlib import Path as _P

        with self._lock:
            self.uploads += 1
            self.objects[(bucket, key)] = _P(path).read_bytes()

    def get_object(self, Bucket, Key):
        with self._lock:
            data = self.objects[(Bucket, Key)]
        return {"Body": FakeBody(data)}


class Scope:
    """Per-test namespace + own-row-only cleanup for the shared tier DB."""

    def __init__(self, tag: str):
        self.tag = tag
        self.videos: list[str] = []
        self.shas: list[str] = []

    def video(self, name: str) -> str:
        v = f"pg-d3b1-{self.tag}-{name}-{uuid4().hex[:12]}"
        self.videos.append(v)
        return v

    def track_sha(self, sha: str) -> str:
        self.shas.append(sha)
        return sha

    def cleanup(self, engine) -> None:
        from app.database import Base

        tables = Base.metadata.tables
        with engine.begin() as conn:
            if self.videos:
                for name in ("media_derivatives", "media_revisions", "ingest_object_state"):
                    conn.execute(
                        tables[name].delete().where(tables[name].c.video_uuid.in_(self.videos))
                    )
            if self.shas:
                conn.execute(
                    tables["media_blob_locations"].delete().where(
                        tables["media_blob_locations"].c.blob_sha256.in_(self.shas)
                    )
                )
                conn.execute(
                    tables["media_blobs"].delete().where(
                        tables["media_blobs"].c.sha256.in_(self.shas)
                    )
                )


@pytest.fixture()
def scope(request):
    tag = request.node.name.replace("[", "-").replace("]", "").replace(" ", "")[:40]
    sc = Scope(tag)
    engine = _engine()
    _make_tables(engine)
    yield sc
    try:
        sc.cleanup(engine)
    finally:
        engine.dispose()


@pytest.fixture()
def creds(monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "b2_upload_key_id", "test-key")
    monkeypatch.setattr(settings, "b2_upload_key_secret", "test-secret-xyz")
    monkeypatch.setattr(settings, "b2_upload_region", "test-region")
    monkeypatch.setattr(settings, "b2_upload_environment", "prod")
    monkeypatch.setattr(settings, "b2_upload_endpoint_url", "")
    return settings


def _seed_camera(engine, scope, video_uuid, raw: bytes, semantics="photos_edited_rendition"):
    from app.config import get_settings
    from app.models.media_backbone import MediaBlob, MediaBlobLocation, MediaRevision

    settings = get_settings()
    sha = _sha(raw)
    scope.track_sha(sha)
    with engine.begin() as conn:
        conn.execute(
            MediaBlob.__table__.insert().values(
                sha256=sha, byte_size=len(raw), storage_backend="b2",
                bucket=settings.media_backbone_prod_bucket,
                object_key=f"blobs/sha256/{sha[:2]}/{sha}",
            )
        )
        conn.execute(
            MediaBlobLocation.__table__.insert().values(
                blob_sha256=sha, environment="prod", storage_backend="b2",
                bucket=settings.media_backbone_prod_bucket,
                object_key=f"blobs/sha256/{sha[:2]}/{sha}", verified=True,
            )
        )
        conn.execute(
            MediaRevision.__table__.insert().values(
                video_uuid=video_uuid, blob_sha256=sha, rendition_semantics=semantics
            )
        )
    return sha


def _run_workers(n, target):
    errors: list = []
    results: list = []
    lock = threading.Lock()

    def _wrap(*args):
        try:
            out = target(*args)
            with lock:
                results.append(out)
        except Exception as exc:  # noqa: BLE001 — recorded, asserted below
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=_wrap, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
        assert not t.is_alive(), "worker thread hung"
    return results, errors


def test_concurrent_same_identity_same_bytes_single_ready(tmp_path, scope, creds):
    """Absent-row race, same bytes: one row, every publisher ready."""
    from app.services.derivative_publisher import build_publication_context, publish_derivative

    engine = _engine()
    try:
        uuid = scope.video("same")
        _seed_camera(engine, scope, uuid, b"pg-camera-same")
        artifact = tmp_path / "a.bin"
        artifact.write_bytes(b"pg-same-bytes" * 64)
        scope.track_sha(_sha(b"pg-same-bytes" * 64))
        gate = threading.Barrier(4)
        fake = FakeS3(gate=gate)

        def worker(_i):
            eng = _engine()
            try:
                Session = sessionmaker(bind=eng, expire_on_commit=False)
                s = Session()
                try:
                    ctx = build_publication_context(s, video_uuid=uuid, role="hq")
                    return publish_derivative(s, ctx, artifact, s3_client=fake)
                finally:
                    s.close()
            finally:
                eng.dispose()

        results, errors = _run_workers(4, worker)
        assert not errors, errors
        assert len(results) == 4 and all(o["status"] == "ready" for o in results)
        assert len({o["derivative_blob_sha256"] for o in results}) == 1
        with engine.connect() as conn:
            n = conn.execute(
                text("SELECT COUNT(*) FROM media_derivatives WHERE video_uuid = :v"),
                {"v": uuid},
            ).scalar()
            assert n == 1
    finally:
        engine.dispose()


def test_concurrent_same_identity_different_bytes_single_winner(tmp_path, scope, creds):
    """Absent-row race, distinct bytes: exactly one winner, losers conflict.

    Every loser either preflights the conflict before upload or loses the
    ledger race after uploading (that orphan is retained, never deleted);
    the ready row always holds the winner's bytes.
    """
    from app.services.derivative_publisher import (
        DerivativeIdentityConflict,
        build_publication_context,
        publish_derivative,
    )

    engine = _engine()
    try:
        uuid = scope.video("diff")
        _seed_camera(engine, scope, uuid, b"pg-camera-diff")
        gate = threading.Barrier(4)
        fake = FakeS3(gate=gate)
        paths = []
        for i in range(4):
            p = tmp_path / f"w{i}.bin"
            p.write_bytes(b"pg-diff-bytes-%d" % i * 64)
            paths.append(p)
            scope.track_sha(_sha(b"pg-diff-bytes-%d" % i * 64))

        def worker(i):
            eng = _engine()
            try:
                Session = sessionmaker(bind=eng, expire_on_commit=False)
                s = Session()
                try:
                    ctx = build_publication_context(s, video_uuid=uuid, role="hq")
                    return publish_derivative(s, ctx, paths[i], s3_client=fake)
                finally:
                    s.close()
            finally:
                eng.dispose()

        results, errors = _run_workers(4, worker)
        assert len(results) + len(errors) == 4
        assert len(results) == 1 and results[0]["status"] == "ready"
        assert len(errors) == 3 and all(
            isinstance(e, DerivativeIdentityConflict) for e in errors
        ), errors
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT derivative_blob_sha256, status FROM media_derivatives "
                    "WHERE video_uuid = :v"
                ),
                {"v": uuid},
            ).all()
            assert len(rows) == 1
            assert rows[0][1] == "ready"
            assert rows[0][0] == results[0]["derivative_blob_sha256"]
            # Winner bytes durable; orphans retained (never deleted).
            assert (results[0]["bucket"], results[0]["object_key"]) in fake.objects
    finally:
        engine.dispose()


def test_row_lock_serializes_concurrent_publisher(tmp_path, scope, creds):
    """The FOR UPDATE lock is real: a holder blocks a publisher until commit.

    Event-ordered (no timing asserts): while the holder keeps the ledger
    row locked in an open transaction, the same-bytes publisher must not
    finish; after commit it observes the committed row and returns an
    idempotent ready.
    """
    from app.services import derivative_publisher as mod
    from app.services.derivative_publisher import build_publication_context, publish_derivative

    engine = _engine()
    try:
        uuid = scope.video("lock")
        _seed_camera(engine, scope, uuid, b"pg-camera-lock")
        artifact = tmp_path / "a.bin"
        artifact.write_bytes(b"pg-lock-bytes" * 64)
        scope.track_sha(_sha(b"pg-lock-bytes" * 64))

        Session = sessionmaker(bind=engine, expire_on_commit=False)
        seed = Session()
        ctx0 = build_publication_context(seed, video_uuid=uuid, role="hq")
        first = publish_derivative(seed, ctx0, artifact, s3_client=FakeS3())
        assert first["status"] == "ready"
        seed.close()

        holder = Session()
        locked = threading.Event()
        release = threading.Event()
        done: list = []
        holder_errors: list = []

        def hold():
            try:
                s = Session()
                try:
                    hctx = build_publication_context(s, video_uuid=uuid, role="hq")
                    row = mod._read_existing_ledger_row(s, hctx, for_update=True)
                    assert row is not None and row.status == "ready"
                    locked.set()
                    assert release.wait(timeout=60), "release never signaled"
                    s.commit()
                finally:
                    s.close()
            except Exception as exc:  # noqa: BLE001
                holder_errors.append(exc)
                locked.set()

        def publish_waiter():
            eng = _engine()
            try:
                Session2 = sessionmaker(bind=eng, expire_on_commit=False)
                s = Session2()
                try:
                    ctx = build_publication_context(s, video_uuid=uuid, role="hq")
                    done.append(publish_derivative(s, ctx, artifact, s3_client=FakeS3()))
                finally:
                    s.close()
            finally:
                eng.dispose()

        t_hold = threading.Thread(target=hold)
        t_hold.start()
        assert locked.wait(timeout=60), "holder never took the lock"
        t_pub = threading.Thread(target=publish_waiter)
        t_pub.start()
        # While the row lock is held, the publisher must still be blocked
        # inside its locked read (generous head start, event-decided below).
        t_pub.join(timeout=5)
        assert t_pub.is_alive(), "publisher finished while the row lock was held"
        release.set()
        t_pub.join(timeout=120)
        t_hold.join(timeout=120)
        assert not holder_errors, holder_errors
        assert len(done) == 1
        assert done[0]["status"] == "ready" and done[0]["deduplicated"] is True
        assert done[0]["derivative_blob_sha256"] == first["derivative_blob_sha256"]
    finally:
        engine.dispose()


def test_existing_ready_refreshes_stale_identity_map(tmp_path, scope, creds):
    """A session caching a non-ready row still resolves the concurrent ready."""
    from app.models.media_backbone import MediaDerivative
    from app.services.derivative_publisher import build_publication_context, publish_derivative
    from datetime import datetime

    engine = _engine()
    try:
        uuid = scope.video("idmap")
        source_sha = _seed_camera(engine, scope, uuid, b"pg-camera-idmap")
        payload = b"pg-idmap-bytes" * 64
        ledger_sha = scope.track_sha(_sha(payload))
        artifact = tmp_path / "a.bin"
        artifact.write_bytes(payload)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        s1 = Session()
        s1.add(
            MediaDerivative(
                video_uuid=uuid,
                source_blob_sha256=source_sha,
                role="hq",
                transform_version="ffmpeg-h264-web-v1",
                derivative_blob_sha256=ledger_sha,
                status="verifying",
            )
        )
        s1.commit()
        cached = s1.query(MediaDerivative).filter_by(video_uuid=uuid, role="hq").one()
        assert cached.status == "verifying"
        s2 = Session()
        try:
            rival = s2.query(MediaDerivative).filter_by(video_uuid=uuid, role="hq").one()
            rival.status = "ready"
            rival.verified_at = datetime.utcnow()
            s2.commit()
        finally:
            s2.close()
        ctx = build_publication_context(s1, video_uuid=uuid, role="hq")
        out = publish_derivative(s1, ctx, artifact, s3_client=FakeS3())
        assert out["status"] == "ready" and out["deduplicated"] is True
        s1.close()
    finally:
        engine.dispose()


def test_drifted_ready_replay_goes_stale_on_pg(tmp_path, scope, creds):
    """Every ready decision rechecks the source — including idempotent replays."""
    from app.services.derivative_publisher import (
        StaleSourceError,
        build_publication_context,
        publish_derivative,
    )

    engine = _engine()
    try:
        uuid = scope.video("drift")
        _seed_camera(engine, scope, uuid, b"pg-camera-v1")
        artifact = tmp_path / "a.bin"
        artifact.write_bytes(b"pg-drift-bytes" * 64)
        scope.track_sha(_sha(b"pg-drift-bytes" * 64))
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        s = Session()
        try:
            ctx = build_publication_context(s, video_uuid=uuid, role="hq")
            first = publish_derivative(s, ctx, artifact, s3_client=FakeS3())
            assert first["status"] == "ready"
        finally:
            s.close()
        # New camera revision lands after the context was built. The stale
        # context (frozen data, reused across sessions) must go stale.
        _seed_camera(engine, scope, uuid, b"pg-camera-v2-newer")
        s = Session()
        try:
            with pytest.raises(StaleSourceError):
                publish_derivative(s, ctx, artifact, s3_client=FakeS3())
        finally:
            s.close()
        with engine.connect() as conn:
            n_ready = conn.execute(
                text(
                    "SELECT COUNT(*) FROM media_derivatives "
                    "WHERE video_uuid = :v AND status = 'ready'"
                ),
                {"v": uuid},
            ).scalar()
            assert n_ready == 1
    finally:
        engine.dispose()
