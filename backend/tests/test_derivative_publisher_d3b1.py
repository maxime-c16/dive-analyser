"""D3b1 derivative publisher — inert internal service tests (no network/prod).

Fake S3 only (in-memory dict, no moto dependency, no B2). SQLite by
default; real-PostgreSQL concurrency lives in
``test_postgres_derivative_publisher_d3b1.py`` (disposable
``calendar_test_*`` only).
"""

import hashlib
import io

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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
from app.services.derivative_publisher import (
    DerivativeIdentityConflict,
    MissingCredentials,
    PublicationContext,
    StaleSourceError,
    VerificationFailed,
    build_publication_context,
    derivative_object_key,
    publish_derivative,
    resolve_canonical_source_revision,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        MediaBlob.__table__,
        MediaBlobLocation.__table__,
        MediaRevision.__table__,
        CaptionRevision.__table__,
        IngestObjectState.__table__,
        MediaDerivative.__table__,
        Base.metadata.tables["media_jobs"],
        Base.metadata.tables["photos_assets"],
    ]
    Base.metadata.create_all(engine, tables=tables)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def creds(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "b2_upload_key_id", "test-key")
    monkeypatch.setattr(settings, "b2_upload_key_secret", "test-secret-xyz")
    monkeypatch.setattr(settings, "b2_upload_region", "test-region")
    monkeypatch.setattr(settings, "b2_upload_environment", "prod")
    monkeypatch.setattr(settings, "b2_upload_endpoint_url", "")
    return settings


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class FakeBody(io.BytesIO):
    def iter_chunks(self, chunk_size=1024 * 1024):
        while True:
            piece = self.read(chunk_size)
            if not piece:
                break
            yield piece


class FakeS3:
    """In-memory S3 with fault injection (no network)."""

    def __init__(self, mode="ok"):
        self.objects: dict[tuple[str, str], bytes] = {}
        self.mode = mode
        self.calls = {"upload": 0, "get": 0}
        self.last_extra = None

    def upload_file(self, path, bucket, key, ExtraArgs=None):
        from pathlib import Path

        self.calls["upload"] += 1
        self.last_extra = ExtraArgs
        if self.mode == "upload_error":
            raise RuntimeError("boom")
        self.objects[(bucket, key)] = Path(path).read_bytes()

    def get_object(self, Bucket, Key):
        self.calls["get"] += 1
        if self.mode == "get_error":
            raise RuntimeError("boom")
        data = self.objects.get((Bucket, Key), b"")
        if self.mode == "corrupt":
            data = b"corrupt:" + data
        elif self.mode == "truncate":
            data = data[: max(0, len(data) - 1)] if data else b""
        elif self.mode == "wrong_size":
            data = data + b"\x00"
        return {"Body": FakeBody(data)}


def _seed_camera_source(db, video_uuid, raw=b"camera-bytes-v1", semantics="photos_edited_rendition"):
    settings = get_settings()
    sha = _sha(raw)
    db.add(MediaBlob(sha256=sha, byte_size=len(raw), storage_backend="b2",
                     bucket=settings.media_backbone_prod_bucket, object_key=f"blobs/sha256/{sha[:2]}/{sha}"))
    db.add(MediaBlobLocation(blob_sha256=sha, environment="prod", storage_backend="b2",
                             bucket=settings.media_backbone_prod_bucket,
                             object_key=f"blobs/sha256/{sha[:2]}/{sha}", verified=True))
    rev = MediaRevision(video_uuid=video_uuid, blob_sha256=sha, rendition_semantics=semantics)
    db.add(rev)
    db.commit()
    return sha


def _ctx(db, video_uuid, role="hq"):
    return build_publication_context(db, video_uuid=video_uuid, role=role)


@pytest.mark.parametrize("role", ["hq", "light", "poster"])
def test_publish_roundtrip_ready_all_roles(db, creds, tmp_path, role):
    uuid = f"clip-{role}-ready"
    _seed_camera_source(db, uuid)
    ctx = _ctx(db, uuid, role)
    artifact = tmp_path / f"{role}.bin"
    artifact.write_bytes(b"derivative-bytes-" + role.encode() * 64)
    fake = FakeS3()
    out = publish_derivative(db, ctx, artifact, s3_client=fake)
    assert out["status"] == "ready" and out["deduplicated"] is False
    assert fake.calls == {"upload": 1, "get": 1}
    # Ledger consistency: blob + verified location + derived_* revision + ready row.
    blob = db.get(MediaBlob, out["derivative_blob_sha256"])
    assert blob is not None and blob.byte_size == out["byte_size"]
    loc = db.query(MediaBlobLocation).filter_by(blob_sha256=out["derivative_blob_sha256"], environment="prod", verified=True).one()
    assert loc.bucket == creds.media_backbone_prod_bucket and loc.object_key == out["object_key"]
    rev = db.query(MediaRevision).filter_by(video_uuid=uuid, blob_sha256=out["derivative_blob_sha256"]).one()
    assert rev.rendition_semantics == {"hq": "derived_hq", "light": "derived_light", "poster": "derived_poster"}[role]
    row = db.query(MediaDerivative).filter_by(video_uuid=uuid, role=role).one()
    assert row.status == "ready" and row.derivative_blob_sha256 == out["derivative_blob_sha256"]
    assert out["object_key"].startswith(f"{creds.media_backbone_object_prefix.strip().strip('/')}/derived/")
    assert f"/{ctx.source_blob_sha256[:2]}/" in out["object_key"]


@pytest.mark.parametrize("mode", ["corrupt", "truncate", "wrong_size", "get_error", "upload_error"])
def test_verify_failures_fail_closed_no_ledger(db, creds, tmp_path, mode):
    uuid = f"clip-fail-{mode}"
    _seed_camera_source(db, uuid)
    ctx = _ctx(db, uuid)
    artifact = tmp_path / "a.bin"
    artifact.write_bytes(b"good-derivative-bytes" * 32)
    fake = FakeS3(mode=mode)
    with pytest.raises(VerificationFailed):
        publish_derivative(db, ctx, artifact, s3_client=fake)
    assert db.query(MediaDerivative).count() == 0
    assert db.query(MediaRevision).filter(MediaRevision.rendition_semantics.like("derived\\_%", escape="\\")).count() == 0


def test_existing_ready_survives_failed_republish(db, creds, tmp_path):
    uuid = "clip-ready-stays"
    _seed_camera_source(db, uuid)
    ctx = _ctx(db, uuid)
    good = tmp_path / "good.bin"
    good.write_bytes(b"good-bytes" * 100)
    fake_ok = FakeS3()
    first = publish_derivative(db, ctx, good, s3_client=fake_ok)
    assert first["status"] == "ready"
    # A faulty retry with DIFFERENT local bytes fails verify: existing ready untouched.
    bad = tmp_path / "bad.bin"
    bad.write_bytes(b"different-bytes" * 100)
    fake_bad = FakeS3(mode="corrupt")
    # Share the good store so the corrupt GET still resolves against good bytes.
    fake_bad.objects = fake_ok.objects
    with pytest.raises(VerificationFailed):
        publish_derivative(db, ctx, bad, s3_client=fake_bad)
    row = db.query(MediaDerivative).filter_by(video_uuid=uuid, role="hq").one()
    assert row.status == "ready" and row.derivative_blob_sha256 == first["derivative_blob_sha256"]


def test_idempotent_same_bytes_no_duplicates(db, creds, tmp_path):
    uuid = "clip-idem"
    _seed_camera_source(db, uuid)
    ctx = _ctx(db, uuid)
    artifact = tmp_path / "a.bin"
    artifact.write_bytes(b"same-bytes" * 64)
    fake = FakeS3()
    first = publish_derivative(db, ctx, artifact, s3_client=fake)
    n_blob = db.query(MediaBlob).count()
    n_loc = db.query(MediaBlobLocation).count()
    n_rev = db.query(MediaRevision).count()
    n_der = db.query(MediaDerivative).count()
    second = publish_derivative(db, ctx, artifact, s3_client=fake)
    assert second["status"] == "ready" and second["deduplicated"] is True
    assert second["derivative_blob_sha256"] == first["derivative_blob_sha256"]
    assert db.query(MediaBlob).count() == n_blob
    assert db.query(MediaBlobLocation).count() == n_loc
    assert db.query(MediaRevision).count() == n_rev
    assert db.query(MediaDerivative).count() == n_der


def test_same_identity_different_bytes_conflict_keeps_ready(db, creds, tmp_path):
    uuid = "clip-conflict"
    _seed_camera_source(db, uuid)
    ctx = _ctx(db, uuid)
    a = tmp_path / "a.bin"
    a.write_bytes(b"bytes-A" * 100)
    fake = FakeS3()
    first = publish_derivative(db, ctx, a, s3_client=fake)
    b = tmp_path / "b.bin"
    b.write_bytes(b"bytes-B-DIFFERENT" * 100)
    with pytest.raises(DerivativeIdentityConflict):
        publish_derivative(db, ctx, b, s3_client=fake)
    row = db.query(MediaDerivative).filter_by(video_uuid=uuid, role="hq").one()
    assert row.status == "ready" and row.derivative_blob_sha256 == first["derivative_blob_sha256"]
    # B2 orphan from the losing attempt is retained; winner untouched.
    assert len(fake.objects) == 2
    assert (first["bucket"], first["object_key"]) in fake.objects


def test_source_drift_commits_stale_never_ready(db, creds, tmp_path):
    uuid = "clip-drift"
    _seed_camera_source(db, uuid, raw=b"camera-v1")
    ctx = _ctx(db, uuid)
    # New camera revision lands after the context was built.
    _seed_camera_source(db, uuid, raw=b"camera-v2-newer")
    artifact = tmp_path / "a.bin"
    artifact.write_bytes(b"derivative-for-v1" * 64)
    with pytest.raises(StaleSourceError):
        publish_derivative(db, ctx, artifact, s3_client=FakeS3())
    rows = db.query(MediaDerivative).filter_by(video_uuid=uuid).all()
    assert len(rows) == 1 and rows[0].status == "stale"
    assert db.query(MediaDerivative).filter_by(video_uuid=uuid, status="ready").count() == 0
    # No autoqueue: no media_jobs rows created by the publisher.
    from app.models.media import MediaJob

    assert db.query(MediaJob).count() == 0


def test_canonical_source_prefers_camera_over_playback_and_skips_derived(db, creds):
    uuid = "clip-policy"
    settings = get_settings()
    cam_sha = _sha(b"true-camera")
    play_sha = _sha(b"already-transcoded-proxy")
    for sha, sem in [(cam_sha, "browser_original"), (play_sha, "browser_playback")]:
        db.add(MediaBlob(sha256=sha, byte_size=10, storage_backend="b2",
                         bucket=settings.media_backbone_prod_bucket, object_key=f"k/{sha}"))
        db.add(MediaBlobLocation(blob_sha256=sha, environment="prod", storage_backend="b2",
                                 bucket=settings.media_backbone_prod_bucket, object_key=f"k/{sha}", verified=True))
        db.add(MediaRevision(video_uuid=uuid, blob_sha256=sha, rendition_semantics=sem))
    db.commit()
    # Newest row is the transcode; canonical must still be the camera bytes.
    rev, _, _ = resolve_canonical_source_revision(db, uuid)
    assert rev.blob_sha256 == cam_sha
    # A newest derived_* row must never become the source.
    dsha = _sha(b"derived-bytes")
    db.add(MediaBlob(sha256=dsha, byte_size=10, storage_backend="b2",
                     bucket=settings.media_backbone_prod_bucket, object_key=f"k/{dsha}"))
    db.add(MediaBlobLocation(blob_sha256=dsha, environment="prod", storage_backend="b2",
                             bucket=settings.media_backbone_prod_bucket, object_key=f"k/{dsha}", verified=True))
    db.add(MediaRevision(video_uuid=uuid, blob_sha256=dsha, rendition_semantics="derived_hq"))
    db.commit()
    rev2, _, _ = resolve_canonical_source_revision(db, uuid)
    assert rev2.blob_sha256 == cam_sha
    ctx = build_publication_context(db, video_uuid=uuid, role="light")
    assert ctx.source_blob_sha256 == cam_sha


def test_publisher_requires_validated_context(db, creds, tmp_path):
    uuid = "clip-guard"
    _seed_camera_source(db, uuid)
    artifact = tmp_path / "a.bin"
    artifact.write_bytes(b"x" * 128)
    with pytest.raises(Exception):
        publish_derivative(db, {"video_uuid": uuid}, artifact, s3_client=FakeS3())
    with pytest.raises(Exception):
        publish_derivative(db, "not-a-context", artifact, s3_client=FakeS3())
    handmade = PublicationContext(video_uuid=uuid, source_blob_sha256="0" * 64,
                                  source_revision_id=1, source_size_bytes=1, role="hq",
                                  transform_version="ffmpeg-h264-web-v1", environment="prod",
                                  bucket="b", object_prefix="p", _validated=False)
    with pytest.raises(Exception):
        publish_derivative(db, handmade, artifact, s3_client=FakeS3())


def test_key_format_and_no_secrets_in_errors(db, creds, tmp_path, monkeypatch):
    uuid = "clip-keys"
    _seed_camera_source(db, uuid)
    key = derivative_object_key(source_sha256="a" * 64, role="hq",
                                transform_version="ffmpeg-h264-web-v1", derivative_sha256="b" * 64)
    assert key == f"{creds.media_backbone_object_prefix}/derived/aa/hq-ffmpeg-h264-web-v1-{'b' * 64}"
    monkeypatch.setattr(creds, "b2_upload_key_id", "")
    ctx = build_publication_context(db, video_uuid=uuid, role="hq")
    artifact = tmp_path / "k.bin"
    artifact.write_bytes(b"z" * 256)
    with pytest.raises(MissingCredentials) as exc:
        publish_derivative(db, ctx, artifact)
    assert "test-secret-xyz" not in str(exc.value)
    # Verification errors never echo secrets either.
    monkeypatch.setattr(creds, "b2_upload_key_id", "k")
    ctx = build_publication_context(db, video_uuid=uuid, role="hq")
    artifact = tmp_path / "a.bin"
    artifact.write_bytes(b"z" * 256)
    with pytest.raises(VerificationFailed) as exc2:
        publish_derivative(db, ctx, artifact, s3_client=FakeS3(mode="corrupt"))
    assert "test-secret-xyz" not in str(exc2.value)


def test_never_trusts_head_metadata(db, creds, tmp_path):
    """A client reporting success via HEAD/upload alone still fails without GET proof."""
    uuid = "clip-nohead"
    _seed_camera_source(db, uuid)
    ctx = _ctx(db, uuid)
    artifact = tmp_path / "a.bin"
    artifact.write_bytes(b"real-bytes" * 64)

    class HeadOnly(FakeS3):
        def head_object(self, **kw):
            return {"ContentLength": 999, "Metadata": {"sha256": "0" * 64}}

    fake = HeadOnly(mode="corrupt")
    with pytest.raises(VerificationFailed):
        publish_derivative(db, ctx, artifact, s3_client=fake)
    assert fake.calls["get"] == 1
    assert db.query(MediaDerivative).count() == 0
