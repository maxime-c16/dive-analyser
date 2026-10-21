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
    # A faulty retry with the SAME local bytes but a corrupt store:
    # verify fails, existing ready untouched.
    fake_bad = FakeS3(mode="corrupt")
    # Share the good store so the corrupt GET still resolves against good bytes.
    fake_bad.objects = fake_ok.objects
    with pytest.raises(VerificationFailed):
        publish_derivative(db, ctx, good, s3_client=fake_bad)
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
    uploads_before = fake.calls["upload"]
    with pytest.raises(DerivativeIdentityConflict):
        publish_derivative(db, ctx, b, s3_client=fake)
    row = db.query(MediaDerivative).filter_by(video_uuid=uuid, role="hq").one()
    assert row.status == "ready" and row.derivative_blob_sha256 == first["derivative_blob_sha256"]
    # Clear conflict preflights BEFORE any network upload: no new object,
    # no new upload call for the losing attempt.
    assert fake.calls["upload"] == uploads_before
    assert len(fake.objects) == 1
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
    with pytest.raises(Exception):
        publish_derivative(db, None, artifact, s3_client=FakeS3())
    # Direct construction without the private factory token is rejected —
    # only build_publication_context can mint a context.
    with pytest.raises(Exception):
        PublicationContext(video_uuid=uuid, source_blob_sha256="0" * 64,
                           source_revision_id=1, source_size_bytes=1, role="hq",
                           transform_version="ffmpeg-h264-web-v1", environment="prod",
                           bucket="b", object_prefix="p")
    # Even a token-less forgery smuggled past construction is revalidated:
    # publish recomputes the scope from current settings and the live DB.
    forged = PublicationContext.__new__(PublicationContext)
    object.__setattr__(forged, "video_uuid", uuid)
    object.__setattr__(forged, "source_blob_sha256", "0" * 64)
    object.__setattr__(forged, "source_revision_id", 1)
    object.__setattr__(forged, "source_size_bytes", 1)
    object.__setattr__(forged, "role", "hq")
    object.__setattr__(forged, "transform_version", "ffmpeg-h264-web-v1")
    object.__setattr__(forged, "environment", "prod")
    object.__setattr__(forged, "bucket", "elsewhere-bucket")
    object.__setattr__(forged, "object_prefix", "p")
    object.__setattr__(forged, "_factory_token", None)
    fake = FakeS3()
    with pytest.raises(Exception):
        publish_derivative(db, forged, artifact, s3_client=fake)
    assert fake.calls["upload"] == 0


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


# ---------------------------------------------------------------------------
# D3b1 hardening: review-findings coverage (SQLite tier).
# Real-PostgreSQL concurrency lives in
# test_postgres_derivative_publisher_d3b1.py (CI postgres tier).
# ---------------------------------------------------------------------------

from app.services import derivative_publisher as _publisher_mod
from app.services.derivative_publisher import (
    DerivativePublishError,
    MissingSourceError,
)


def _seed_ledger_row(db, video_uuid, source_sha, role, derivative_sha, status):
    row = MediaDerivative(
        video_uuid=video_uuid,
        source_blob_sha256=source_sha,
        role=role,
        transform_version="ffmpeg-h264-web-v1",
        derivative_blob_sha256=derivative_sha,
        status=status,
        verified_at=None,
    )
    db.add(row)
    db.commit()
    return row


@pytest.mark.parametrize("bad_uuid", ["  padded  ", "has|pipe", "", "x" * 101])
def test_builder_rejects_bad_identity_early(db, creds, bad_uuid):
    _seed_camera_source(db, "clip-uuid-shape")
    with pytest.raises(ValueError):
        build_publication_context(db, video_uuid=bad_uuid, role="hq")


@pytest.mark.parametrize("bad_version", ["  padded  ", "has|pipe", "", "v" * 41])
def test_builder_rejects_bad_transform_version_early(db, creds, bad_version):
    _seed_camera_source(db, "clip-version-shape")
    with pytest.raises(ValueError):
        build_publication_context(db, video_uuid="clip-version-shape", role="hq",
                                  transform_version=bad_version)


def test_builder_rejects_unknown_role(db, creds):
    _seed_camera_source(db, "clip-badrole")
    with pytest.raises(ValueError):
        build_publication_context(db, video_uuid="clip-badrole", role="raw")


def test_publish_revalidates_scope_before_upload(db, creds, tmp_path, monkeypatch):
    """Settings changed after build (or forged fields) fail before upload."""
    uuid = "clip-scope-drift"
    _seed_camera_source(db, uuid)
    ctx = _ctx(db, uuid)
    artifact = tmp_path / "a.bin"
    artifact.write_bytes(b"scope-bytes" * 64)
    fake = FakeS3()
    # Bucket no longer matches what the context was built with.
    monkeypatch.setattr(creds, "media_backbone_prod_bucket", "other-prod-bucket")
    with pytest.raises(DerivativePublishError):
        publish_derivative(db, ctx, artifact, s3_client=fake)
    assert fake.calls["upload"] == 0
    assert db.query(MediaDerivative).count() == 0


def test_publish_revalidates_environment_before_upload(db, creds, tmp_path, monkeypatch):
    uuid = "clip-env-drift"
    _seed_camera_source(db, uuid)
    ctx = _ctx(db, uuid)
    assert ctx.environment == "prod"
    monkeypatch.setattr(creds, "b2_upload_environment", "dev")
    artifact = tmp_path / "a.bin"
    artifact.write_bytes(b"env-bytes" * 64)
    fake = FakeS3()
    with pytest.raises(DerivativePublishError):
        publish_derivative(db, ctx, artifact, s3_client=fake)
    assert fake.calls["upload"] == 0


@pytest.mark.parametrize("status", ["verifying", "stale", "superseded"])
@pytest.mark.parametrize("same_bytes", [True, False])
def test_nonready_row_promotes_to_ready_when_source_current(db, creds, tmp_path, status, same_bytes):
    """Every non-ready state promotes (same or new bytes) while current."""
    uuid = f"clip-promote-{status}-{int(same_bytes)}"
    source_sha = _seed_camera_source(db, uuid)
    ctx = _ctx(db, uuid)
    artifact = tmp_path / "a.bin"
    artifact.write_bytes(b"promote-bytes" * 64)
    ledger_sha = _sha(b"promote-bytes" * 64) if same_bytes else _sha(b"older-other-bytes")
    _seed_ledger_row(db, uuid, source_sha, "hq", ledger_sha, status)
    out = publish_derivative(db, ctx, artifact, s3_client=FakeS3())
    assert out["status"] == "ready" and out["deduplicated"] is False
    row = db.query(MediaDerivative).filter_by(video_uuid=uuid, role="hq").one()
    assert row.status == "ready"
    assert row.derivative_blob_sha256 == _sha(b"promote-bytes" * 64)
    assert row.verified_at is not None


@pytest.mark.parametrize("status", ["verifying", "stale", "superseded"])
@pytest.mark.parametrize("same_bytes", [True, False])
def test_nonready_row_goes_stale_when_source_drifted(db, creds, tmp_path, status, same_bytes):
    """Drifted non-ready rows (ANY prior status, same or new bytes) → stale.

    Regression: the old same-bytes branch left the prior status in place.
    """
    uuid = f"clip-drifted-{status}-{int(same_bytes)}"
    old_source = _seed_camera_source(db, uuid, raw=b"camera-v1")
    ctx = _ctx(db, uuid)
    _seed_camera_source(db, uuid, raw=b"camera-v2-newer")
    artifact = tmp_path / "a.bin"
    artifact.write_bytes(b"derived-for-v1" * 64)
    ledger_sha = _sha(b"derived-for-v1" * 64) if same_bytes else _sha(b"older-other-bytes")
    _seed_ledger_row(db, uuid, old_source, "hq", ledger_sha, status)
    with pytest.raises(StaleSourceError):
        publish_derivative(db, ctx, artifact, s3_client=FakeS3())
    rows = db.query(MediaDerivative).filter_by(video_uuid=uuid).all()
    assert len(rows) == 1
    assert rows[0].status == "stale"
    assert rows[0].derivative_blob_sha256 == _sha(b"derived-for-v1" * 64)
    assert db.query(MediaDerivative).filter_by(video_uuid=uuid, status="ready").count() == 0


def test_ready_same_bytes_with_drift_goes_stale_without_touching_ready(db, creds, tmp_path):
    """Every ready decision rechecks the source — even idempotent replays.

    Regression: the old early-return served ready without a drift check.
    The drifted replay commits stale (backbone durable) but the existing
    ready row is never modified or downgraded.
    """
    uuid = "clip-ready-drift"
    _seed_camera_source(db, uuid, raw=b"camera-v1")
    ctx = _ctx(db, uuid)
    artifact = tmp_path / "a.bin"
    artifact.write_bytes(b"derived-for-v1" * 64)
    first = publish_derivative(db, ctx, artifact, s3_client=FakeS3())
    assert first["status"] == "ready"
    # New camera revision lands after the context was built.
    _seed_camera_source(db, uuid, raw=b"camera-v2-newer")
    with pytest.raises(StaleSourceError):
        publish_derivative(db, ctx, artifact, s3_client=FakeS3())
    row = db.query(MediaDerivative).filter_by(video_uuid=uuid, role="hq").one()
    assert row.status == "ready"
    assert row.derivative_blob_sha256 == first["derivative_blob_sha256"]
    assert db.query(MediaDerivative).filter_by(video_uuid=uuid, status="ready").count() == 1


def test_ready_different_bytes_with_drift_goes_stale_not_conflict(db, creds, tmp_path):
    """Drift wins over conflict: the old ready row keeps serving, no overwrite."""
    uuid = "clip-ready-drift-conflict"
    _seed_camera_source(db, uuid, raw=b"camera-v1")
    ctx = _ctx(db, uuid)
    a = tmp_path / "a.bin"
    a.write_bytes(b"winner-A" * 100)
    first = publish_derivative(db, ctx, a, s3_client=FakeS3())
    _seed_camera_source(db, uuid, raw=b"camera-v2-newer")
    b = tmp_path / "b.bin"
    b.write_bytes(b"loser-B" * 100)
    with pytest.raises(StaleSourceError):
        publish_derivative(db, ctx, b, s3_client=FakeS3())
    row = db.query(MediaDerivative).filter_by(video_uuid=uuid, role="hq").one()
    assert row.status == "ready" and row.derivative_blob_sha256 == first["derivative_blob_sha256"]


def test_precommit_recheck_catches_late_source_change(db, creds, tmp_path, monkeypatch):
    """A source that moves between the drift check and commit never goes ready."""
    uuid = "clip-late-drift"
    source_sha = _seed_camera_source(db, uuid, raw=b"camera-v1")
    ctx = _ctx(db, uuid)
    artifact = tmp_path / "a.bin"
    artifact.write_bytes(b"late-bytes" * 64)

    real_resolve = _publisher_mod._resolve_current_source_sha
    calls = {"n": 0}

    def _flaky_resolve(session, video):
        calls["n"] += 1
        if calls["n"] >= 2:
            # Source moved after the unit's drift check: pre-commit recheck
            # must observe it (simulates a concurrent source commit).
            return None, True
        return real_resolve(session, video)

    monkeypatch.setattr(_publisher_mod, "_resolve_current_source_sha", _flaky_resolve)
    with pytest.raises(StaleSourceError):
        publish_derivative(db, ctx, artifact, s3_client=FakeS3())
    # Exactly two source resolutions in the ready path: the drift check
    # and the pre-commit recheck. This pins the recheck policy.
    assert calls["n"] == 2
    assert db.query(MediaDerivative).filter_by(video_uuid=uuid).count() == 0
    # Nothing committed for the attempt: no derived revision either.
    assert (
        db.query(MediaRevision)
        .filter(MediaRevision.video_uuid == uuid,
                MediaRevision.rendition_semantics.like("derived\\_%", escape="\\"))
        .count()
        == 0
    )
    assert source_sha is not None


def test_dirty_session_refused_before_upload(db, creds, tmp_path):
    """Caller-owned pending work is never committed/rolled back by publish."""
    uuid = "clip-dirty"
    _seed_camera_source(db, uuid)
    ctx = _ctx(db, uuid)
    artifact = tmp_path / "a.bin"
    artifact.write_bytes(b"dirty-bytes" * 64)
    fake = FakeS3()
    pending = MediaBlob(sha256=_sha(b"caller-unrelated"), byte_size=5,
                        storage_backend="b2", bucket="b", object_key="k/unrelated")
    db.add(pending)
    assert len(db.new) == 1
    with pytest.raises(DerivativePublishError):
        publish_derivative(db, ctx, artifact, s3_client=fake)
    assert fake.calls["upload"] == 0
    # Caller work untouched: still pending, ledger empty.
    assert len(db.new) == 1
    assert db.query(MediaDerivative).count() == 0


def test_ambiguous_source_replicas_fail_closed(db, creds):
    """A second verified replica (non-B2) breaks the exactly-one contract."""
    from app.models.media_backbone import MediaBlobLocation

    uuid = "clip-ambiguous"
    settings = get_settings()
    cam_sha = _seed_camera_source(db, uuid)
    db.add(MediaBlobLocation(blob_sha256=cam_sha, environment="prod",
                             storage_backend="local",
                             bucket="local-cache",
                             object_key=f"cache/{cam_sha}", verified=True))
    db.commit()
    with pytest.raises(MissingSourceError):
        build_publication_context(db, video_uuid=uuid, role="hq")
    assert settings.media_backbone_prod_bucket != "local-cache"


def test_wrong_bucket_verified_source_fails_closed(db, creds, tmp_path):
    """A verified replica outside the allowlisted bucket is not a source."""
    import app.services.matchmaking as _matchmaking

    uuid = "clip-wrongbucket"
    settings = get_settings()
    raw = b"camera-bytes"
    sha = _sha(raw)
    db.add(MediaBlob(sha256=sha, byte_size=len(raw), storage_backend="b2",
                     bucket="rogue-bucket", object_key=f"blobs/sha256/{sha[:2]}/{sha}"))
    db.add(MediaBlobLocation(blob_sha256=sha, environment="prod", storage_backend="b2",
                             bucket="rogue-bucket",
                             object_key=f"blobs/sha256/{sha[:2]}/{sha}", verified=True))
    db.add(MediaRevision(video_uuid=uuid, blob_sha256=sha,
                         rendition_semantics="photos_edited_rendition"))
    db.commit()
    assert settings.media_backbone_prod_bucket != "rogue-bucket"
    with pytest.raises(MissingSourceError):
        build_publication_context(db, video_uuid=uuid, role="hq")
    assert _matchmaking is not None


def test_dev_publish_never_creates_prod_location(db, creds, tmp_path, monkeypatch):
    """Source stays PROD; the derivative location lands in the DEV bucket only."""
    monkeypatch.setattr(creds, "b2_upload_environment", "dev")
    uuid = "clip-devenv"
    _seed_camera_source(db, uuid)
    ctx = _ctx(db, uuid)
    assert ctx.environment == "dev"
    assert ctx.bucket == creds.media_backbone_dev_bucket
    artifact = tmp_path / "a.bin"
    artifact.write_bytes(b"dev-bytes" * 64)
    out = publish_derivative(db, ctx, artifact, s3_client=FakeS3())
    assert out["status"] == "ready" and out["environment"] == "dev"
    from app.models.media_backbone import MediaBlobLocation

    locs = db.query(MediaBlobLocation).filter_by(blob_sha256=out["derivative_blob_sha256"]).all()
    assert len(locs) == 1
    assert locs[0].environment == "dev" and locs[0].bucket == creds.media_backbone_dev_bucket


def test_provider_client_error_sanitized_from_none(db, creds, tmp_path, monkeypatch):
    """Boto3 provider failures never propagate raw (may echo credentials)."""
    import sys
    import types

    uuid = "clip-provider"
    _seed_camera_source(db, uuid)
    ctx = _ctx(db, uuid)
    artifact = tmp_path / "a.bin"
    artifact.write_bytes(b"provider-bytes" * 64)
    secret_marker = "SECRET-LEAK-PROBE-xyz"
    stub = types.ModuleType("boto3")

    def _boom(**kwargs):
        raise RuntimeError(f"endpoint down {secret_marker} key=test-secret-xyz")

    stub.client = _boom
    monkeypatch.setitem(sys.modules, "boto3", stub)
    with pytest.raises(MissingCredentials) as exc:
        publish_derivative(db, ctx, artifact)
    assert secret_marker not in str(exc.value)
    assert "test-secret-xyz" not in str(exc.value)
    assert exc.value.__cause__ is None
    assert db.query(MediaDerivative).count() == 0


def test_identity_map_refresh_sees_concurrent_ready(db, creds, tmp_path):
    """A caller-cached non-ready row must not shadow a concurrent ready commit."""
    from sqlalchemy.orm import sessionmaker

    uuid = "clip-idmap"
    source_sha = _seed_camera_source(db, uuid)
    ctx = _ctx(db, uuid)
    artifact = tmp_path / "a.bin"
    artifact.write_bytes(b"idmap-bytes" * 64)
    ledger_sha = _sha(b"idmap-bytes" * 64)
    row = _seed_ledger_row(db, uuid, source_sha, "hq", ledger_sha, "verifying")
    # Cache the non-ready row in this session's identity map.
    cached = db.get(MediaDerivative, row.id)
    assert cached.status == "verifying"
    # A concurrent publisher promotes the same row and commits.
    Session2 = sessionmaker(bind=db.bind, expire_on_commit=False)
    s2 = Session2()
    try:
        rival = s2.get(MediaDerivative, row.id)
        rival.status = "ready"
        from datetime import datetime

        rival.verified_at = datetime.utcnow()
        s2.commit()
    finally:
        s2.close()
    out = publish_derivative(db, ctx, artifact, s3_client=FakeS3())
    # populate_existing refresh defeats the stale cache: idempotent replay.
    assert out["status"] == "ready" and out["deduplicated"] is True


def test_stale_attempt_records_backbone_without_ready_or_jobs(db, creds, tmp_path):
    """Drifted fresh identity: stale ledger + durable backbone, no autoqueue."""
    uuid = "clip-stale-backbone"
    _seed_camera_source(db, uuid, raw=b"camera-v1")
    ctx = _ctx(db, uuid)
    _seed_camera_source(db, uuid, raw=b"camera-v2-newer")
    artifact = tmp_path / "a.bin"
    artifact.write_bytes(b"stale-derived" * 64)
    with pytest.raises(StaleSourceError):
        publish_derivative(db, ctx, artifact, s3_client=FakeS3())
    sha = _sha(b"stale-derived" * 64)
    blob = db.get(MediaBlob, sha)
    assert blob is not None and blob.byte_size == len(b"stale-derived" * 64)
    from app.models.media_backbone import MediaBlobLocation

    loc = db.query(MediaBlobLocation).filter_by(blob_sha256=sha).one()
    assert loc.verified is True and loc.bucket == creds.media_backbone_prod_bucket
    rev = db.query(MediaRevision).filter_by(video_uuid=uuid, blob_sha256=sha).one()
    assert rev.rendition_semantics == "derived_hq"
    from app.models.media import MediaJob

    assert db.query(MediaJob).count() == 0
