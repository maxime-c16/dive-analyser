"""D5 read contract: shared derivative resolver + revision-bound HTTP proof.

Covers the mission slice, all without a Mac, a media cache, or prod:
fake presign/HEAD (P5/P6 pattern), synthetic SHAs, no media bytes in Git.

* resolver: ready hq/light/poster ONLY for the current canonical
  camera-original source SHA + current transform + verified PROD
  location; stale/dev/ambiguous/wrong-version/old-source rows never
  servable; small-source HQ aliases durable light (dims known), refuses
  without dims; missing source yields honest missing (no arbitrary
  newest-original fallback).
* HTTP: authorized B2 302 with grant ledger rows, stranger 404, Range
  passes through as 302, presign failure on a derivative is an
  explicit 503 (never legacy bytes), missing derivative storage is a
  uniform 404 (never legacy bytes), renewal mints a fresh grant per
  play, status advertises the honest hq/light/original choice with
  starter light, legacy-only clips keep working, old-schema DBs keep
  serving legacy status.
"""

import hashlib
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.database import Base, get_db
from app.main import app
from app.models.dive import Dive
from app.models.diver import Diver
from app.models.evaluation import EvaluationRequest
from app.models.media import MediaCacheEntry, MediaJob
from app.models.media_backbone import (
    MediaBlob,
    MediaBlobLocation,
    MediaDerivative,
    MediaRevision,
)
from app.models.photos_asset import PhotosAsset
from app.models.session import Session as SessionModel
from app.models.security_audit_log import SecurityAuditEvent
from app.models.user_auth import (
    AppUser,
    LoginAttempt,
    MediaPlaybackGrant,
    UserCredential,
    UserDiverAccess,
    UserSession,
)
from app.services.passwords import hash_password

PROD_BUCKET = "diveanalyzer-prod-media"
DEV_BUCKET = "diveanalyzer-dev-media"
PRESIGN_MARKER = "Fakesigmarker00000000000000000000000000000000000000000000"


def _sha(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


UUID_FULL = "D5000000-0000-4000-8000-000000000001"
UUID_SMALL = "D5000000-0000-4000-8000-000000000002"
UUID_SMALL_NODIMS = "D5000000-0000-4000-8000-000000000003"
UUID_STALE = "D5000000-0000-4000-8000-000000000004"
UUID_OLDVERSION = "D5000000-0000-4000-8000-000000000005"
UUID_DEVONLY = "D5000000-0000-4000-8000-000000000006"
UUID_AMBIG = "D5000000-0000-4000-8000-000000000007"
UUID_NOSRC = "D5000000-0000-4000-8000-000000000008"
UUID_OLDSRC = "D5000000-0000-4000-8000-000000000009"
UUID_LEGACY = "D5000000-0000-4000-8000-000000000010"
UUID_SMALL_RECORDEDHQ = "D5000000-0000-4000-8000-000000000011"

SRC_FULL = _sha("d5-full-src")
SRC_SMALL = _sha("d5-small-src")
SRC_SMALL_NODIMS = _sha("d5-small-nodims-src")
SRC_STALE = _sha("d5-stale-src")
SRC_OLDVERSION = _sha("d5-oldversion-src")
SRC_DEVONLY = _sha("d5-devonly-src")
SRC_AMBIG = _sha("d5-ambig-src")
SRC_NOSRC = _sha("d5-nosrc-src")
SRC_OLDSRC_NEW = _sha("d5-oldsrc-new")
SRC_OLDSRC_OLD = _sha("d5-oldsrc-old")
SRC_LEGACY = _sha("d5-legacy-src")
SRC_SMALL_RECORDEDHQ = _sha("d5-small-recordedhq-src")


def _loc(db, sha, env, bucket, key):
    db.add(
        MediaBlobLocation(
            blob_sha256=sha,
            environment=env,
            storage_backend="b2",
            bucket=bucket,
            object_key=key,
            verified=True,
            verified_at=datetime.utcnow(),
        )
    )


def _rev(db, uuid, sha, semantics="photos_edited_rendition"):
    row = MediaRevision(video_uuid=uuid, blob_sha256=sha, rendition_semantics=semantics)
    db.add(row)
    db.flush()
    return row


def _derivative(db, uuid, source_sha, role, deriv_sha, status="ready", transform=None):
    row = MediaDerivative(
        video_uuid=uuid,
        source_blob_sha256=source_sha,
        role=role,
        transform_version=transform or get_settings().media_derivative_transform_version,
        derivative_blob_sha256=deriv_sha,
        status=status,
        verified_at=datetime.utcnow() if status == "ready" else None,
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            SessionModel.__table__,
            Dive.__table__,
            Diver.__table__,
            MediaBlob.__table__,
            MediaBlobLocation.__table__,
            MediaRevision.__table__,
            MediaDerivative.__table__,
            PhotosAsset.__table__,
            MediaCacheEntry.__table__,
            MediaJob.__table__,
            EvaluationRequest.__table__,
            AppUser.__table__,
            UserCredential.__table__,
            UserSession.__table__,
            UserDiverAccess.__table__,
            LoginAttempt.__table__,
            MediaPlaybackGrant.__table__,
            SecurityAuditEvent.__table__,
        ],
    )
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    settings = get_settings()
    saved_cache_root = settings.media_cache_root
    settings.media_cache_root = str(tmp_path)
    _seed_world(session, tmp_path)
    yield session
    settings.media_cache_root = saved_cache_root
    session.close()
    engine.dispose()


def _seed_world(db, tmp_path):
    now = datetime.utcnow()
    d1 = Diver(display_name="Diver A", canonical_name="diver-a", is_primary_user=False)
    d2 = Diver(display_name="Diver B", canonical_name="diver-b", is_primary_user=False)
    db.add_all([d1, d2])
    db.flush()
    s1 = SessionModel(date=now.date(), location="Pool")
    db.add(s1)
    db.flush()

    specs = [
        (UUID_FULL, "101B", d1, (1920, 1080), SRC_FULL),
        (UUID_SMALL, "102B", d1, (640, 480), SRC_SMALL),
        (UUID_SMALL_NODIMS, "103B", d1, (None, None), SRC_SMALL_NODIMS),
        (UUID_STALE, "104B", d1, (1920, 1080), SRC_STALE),
        (UUID_OLDVERSION, "105B", d1, (1920, 1080), SRC_OLDVERSION),
        (UUID_DEVONLY, "106B", d1, (1920, 1080), SRC_DEVONLY),
        (UUID_AMBIG, "107B", d1, (1920, 1080), SRC_AMBIG),
        (UUID_NOSRC, "108B", d1, (1920, 1080), SRC_NOSRC),
        (UUID_OLDSRC, "109B", d1, (1920, 1080), SRC_OLDSRC_NEW),
        (UUID_LEGACY, "110B", d1, (1920, 1080), SRC_LEGACY),
        (UUID_SMALL_RECORDEDHQ, "111B", d1, (640, 480), SRC_SMALL_RECORDEDHQ),
    ]
    for uuid, code, diver, dims, src in specs:
        db.add(
            Dive(
                visibility="private",
                session_id=s1.id,
                dive_code=code,
                performance="G",
                performance_numeric=3,
                height="1m",
                video_uuid=uuid,
                diver_id=diver.id,
                dive_datetime=now - timedelta(hours=1),
            )
        )
        width, height = dims
        db.add(MediaBlob(sha256=src, byte_size=10_000_000, width=width, height=height))
        rev = _rev(db, uuid, src)
        # Canonical PROD camera-original replica for every clip EXCEPT
        # the no-source case (proves: no fallback without a source).
        if uuid != UUID_NOSRC:
            _loc(db, src, "prod", PROD_BUCKET, f"blobs/sha256/{src[:2]}/{src}.mov")
        asset = PhotosAsset(video_uuid=uuid, media_type="video")
        db.add(asset)
        db.flush()
        asset_id = asset.id

        if uuid == UUID_FULL:
            for role in ("hq", "light", "poster"):
                dsha = _sha(f"d5-full-{role}")
                _derivative(db, uuid, src, role, dsha)
                semantics = {"hq": "derived_hq", "light": "derived_light", "poster": "derived_poster"}[role]
                _rev(db, uuid, dsha, semantics)
                _loc(db, dsha, "prod", PROD_BUCKET, f"blobs/sha256/derived/{role}-{dsha[:8]}.bin")
        elif uuid == UUID_SMALL:
            for role in ("light", "poster"):
                dsha = _sha(f"d5-small-{role}")
                _derivative(db, uuid, src, role, dsha)
                semantics = "derived_light" if role == "light" else "derived_poster"
                _rev(db, uuid, dsha, semantics)
                _loc(db, dsha, "prod", PROD_BUCKET, f"blobs/sha256/derived/{role}-{dsha[:8]}.bin")
        elif uuid == UUID_SMALL_NODIMS:
            dsha = _sha("d5-small-nodims-light")
            _derivative(db, uuid, src, "light", dsha)
            _rev(db, uuid, dsha, "derived_light")
            _loc(db, dsha, "prod", PROD_BUCKET, f"blobs/sha256/derived/light-{dsha[:8]}.bin")
        elif uuid == UUID_SMALL_RECORDEDHQ:
            # Small source WITH a recorded (stale) HQ row: a distinct HQ
            # was attempted, so light must never be served as HQ.
            for role, status, semantics in (
                ("light", "ready", "derived_light"),
                ("hq", "stale", "derived_hq"),
            ):
                dsha = _sha(f"d5-small-recordedhq-{role}")
                _derivative(db, uuid, src, role, dsha, status=status)
                _rev(db, uuid, dsha, semantics)
                _loc(db, dsha, "prod", PROD_BUCKET, f"blobs/sha256/derived/{role}-{dsha[:8]}.bin")
        elif uuid == UUID_STALE:
            dsha = _sha("d5-stale-light")
            _derivative(db, uuid, src, "light", dsha, status="stale")
            _rev(db, uuid, dsha, "derived_light")
            _loc(db, dsha, "prod", PROD_BUCKET, f"blobs/sha256/derived/light-{dsha[:8]}.bin")
        elif uuid == UUID_OLDVERSION:
            dsha = _sha("d5-oldversion-light")
            _derivative(db, uuid, src, "light", dsha, transform="ffmpeg-h264-web-v0")
            _rev(db, uuid, dsha, "derived_light")
            _loc(db, dsha, "prod", PROD_BUCKET, f"blobs/sha256/derived/light-{dsha[:8]}.bin")
        elif uuid == UUID_DEVONLY:
            dsha = _sha("d5-devonly-light")
            _derivative(db, uuid, src, "light", dsha)
            _rev(db, uuid, dsha, "derived_light")
            _loc(db, dsha, "dev", DEV_BUCKET, f"blobs/sha256/derived/light-{dsha[:8]}.bin")
        elif uuid == UUID_AMBIG:
            dsha = _sha("d5-ambig-light")
            _derivative(db, uuid, src, "light", dsha)
            _rev(db, uuid, dsha, "derived_light")
            _loc(db, dsha, "prod", PROD_BUCKET, f"blobs/sha256/derived/light-{dsha[:8]}a.bin")
            _loc(db, dsha, "prod", PROD_BUCKET, f"blobs/sha256/derived/light-{dsha[:8]}b.bin")
        elif uuid == UUID_NOSRC:
            # A ready derivative for a clip whose canonical source has NO
            # verified PROD replica: must never serve (no arbitrary
            # fallback to whatever the derivative claims).
            dsha = _sha("d5-nosrc-light")
            db.add(
                MediaDerivative(
                    video_uuid=uuid,
                    source_blob_sha256=src,
                    role="light",
                    transform_version=get_settings().media_derivative_transform_version,
                    derivative_blob_sha256=dsha,
                    status="ready",
                    verified_at=now,
                )
            )
            _rev(db, uuid, dsha, "derived_light")
            _loc(db, dsha, "prod", PROD_BUCKET, f"blobs/sha256/derived/light-{dsha[:8]}.bin")
        elif uuid == UUID_OLDSRC:
            # Ready derivative of an OLD source revision; the canonical
            # source has since moved. Must not serve as current.
            dsha = _sha("d5-oldsrc-light")
            db.add(MediaBlob(sha256=SRC_OLDSRC_OLD, byte_size=9_000_000, width=1920, height=1080))
            _derivative(db, uuid, SRC_OLDSRC_OLD, "light", dsha)
            _rev(db, uuid, dsha, "derived_light")
            _loc(db, dsha, "prod", PROD_BUCKET, f"blobs/sha256/derived/light-{dsha[:8]}.bin")

    # Legacy-only clip: a real cache file, no derivatives at all.
    asset = db.query(PhotosAsset).filter_by(video_uuid=UUID_LEGACY).one()
    legacy = tmp_path / "legacy-720p.mp4"
    legacy.write_bytes(b"FAKELEGACYVIDEOBYTES" * 100)
    db.add(
        MediaCacheEntry(
            photos_asset_id=asset.id,
            media_key="d5-legacy-key",
            rendition="proxy_720p",
            storage_path=str(legacy),
            content_type="video/mp4",
            size_bytes=2000,
            status="ready",
        )
    )
    # Legacy file on the full-derivative clip too: proves the derivative
    # play route never falls back to legacy bytes on provider failure.
    asset_full = db.query(PhotosAsset).filter_by(video_uuid=UUID_FULL).one()
    legacy_full = tmp_path / "full-720p.mp4"
    legacy_full.write_bytes(b"FAKELEGACYVIDEOBYTES" * 100)
    db.add(
        MediaCacheEntry(
            photos_asset_id=asset_full.id,
            media_key="d5-full-legacy-key",
            rendition="proxy_720p",
            storage_path=str(legacy_full),
            content_type="video/mp4",
            size_bytes=2000,
            status="ready",
        )
    )
    # Legacy file on the dev-only clip: proves missing derivative storage
    # is a 404, not a silent legacy substitution.
    asset_dev = db.query(PhotosAsset).filter_by(video_uuid=UUID_DEVONLY).one()
    legacy_dev = tmp_path / "devonly-720p.mp4"
    legacy_dev.write_bytes(b"FAKELEGACYVIDEOBYTES" * 100)
    db.add(
        MediaCacheEntry(
            photos_asset_id=asset_dev.id,
            media_key="d5-devonly-legacy-key",
            rendition="proxy_720p",
            storage_path=str(legacy_dev),
            content_type="video/mp4",
            size_bytes=2000,
            status="ready",
        )
    )
    db.commit()

    users = {}
    for email, diver in (("user-a@example.test", d1), ("user-b@example.test", d2)):
        user = AppUser(email=email, display_name=email.split("@")[0])
        db.add(user)
        db.flush()
        db.add(
            UserCredential(
                user_id=user.id,
                password_hash=hash_password("correct-horse-battery"),
                password_algo="argon2id",
            )
        )
        db.add(UserDiverAccess(user_id=user.id, diver_id=diver.id, access_kind="OWNER"))
        users[email] = user
    db.commit()


@pytest.fixture()
def flags(monkeypatch):
    settings = get_settings()
    saved = (
        settings.user_auth_enabled,
        settings.b2_playback_canary_enabled,
        settings.auth_cookie_secure,
        settings.media_playback_presign_ttl_seconds,
        settings.auth_login_max_failures,
        settings.auth_login_ip_max_failures,
    )
    settings.user_auth_enabled = True
    settings.b2_playback_canary_enabled = True
    settings.auth_cookie_secure = False
    settings.media_playback_presign_ttl_seconds = 120
    settings.auth_login_max_failures = 20
    settings.auth_login_ip_max_failures = 10
    yield settings
    (
        settings.user_auth_enabled,
        settings.b2_playback_canary_enabled,
        settings.auth_cookie_secure,
        settings.media_playback_presign_ttl_seconds,
        settings.auth_login_max_failures,
        settings.auth_login_ip_max_failures,
    ) = saved


@pytest.fixture()
def fake_presign(monkeypatch):
    behavior = {"fail": False}
    calls = []

    def _fake(bucket, object_key, ttl_seconds=None, storage_location_id=None):
        from app.services.b2_presign import PresignResult, PresignUnavailable, clamp_ttl

        calls.append({"bucket": bucket, "object_key": object_key, "storage_location_id": storage_location_id})
        if behavior["fail"]:
            raise PresignUnavailable("injected playback-credential failure")
        effective = clamp_ttl(ttl_seconds)
        return PresignResult(
            url=f"https://s3.eu-central-003.backblazeb2.com/{bucket}/{object_key}"
            f"?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature={PRESIGN_MARKER}",
            ttl_seconds=effective,
            storage_location_id=storage_location_id,
        )

    def _head_ok(bucket, object_key):
        return True

    import app.api.v1.media_playback as playback_module

    monkeypatch.setattr(playback_module.b2_presign, "presign_get", _fake)
    monkeypatch.setattr(playback_module.b2_presign, "head_object", _head_ok)
    yield behavior, calls


@pytest.fixture()
def client(db, flags, fake_presign):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    test_client.post(
        "/api/v1/auth/login",
        json={"email": "user-a@example.test", "password": "correct-horse-battery"},
    )
    yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def python_streamed_media():
    settings = get_settings()
    saved = (settings.media_xaccel_enabled, settings.media_xaccel_prefix)
    settings.media_xaccel_enabled = False
    yield
    settings.media_xaccel_enabled, settings.media_xaccel_prefix = saved


def _derived_revision_id(db, uuid, semantics):
    return (
        db.query(MediaRevision)
        .filter_by(video_uuid=uuid, rendition_semantics=semantics)
        .order_by(MediaRevision.id.desc())
        .first()
        .id
    )


def _status(client, uuid):
    r = client.get(f"/api/v1/media/{uuid}/status")
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------- resolver matrix


def test_full_clip_all_roles_ready_with_starter_light(client, db):
    body = _status(client, UUID_FULL)
    deriv = body["derivatives"]
    assert deriv["transform_version"] == get_settings().media_derivative_transform_version
    assert deriv["start"] == "light"
    assert deriv["recommended"] == "hq"
    for role, semantics in (("hq", "derived_hq"), ("light", "derived_light"), ("poster", "derived_poster")):
        entry = deriv[role]
        assert entry["state"] == "ready", role
        assert entry["aliased_to"] is None, role
        assert entry["revision_id"] == _derived_revision_id(db, UUID_FULL, semantics), role
        assert entry["playback_url"] == f"/api/v1/media/revisions/{entry['revision_id']}/play", role
    # Starter + tile poster resolve to durable B2 bytes (no local cache
    # files were seeded for this clip); the camera original stays the
    # explicit full-quality choice, never the default.
    assert body["preview_url"] == deriv["light"]["playback_url"]
    assert body["poster_url"] == deriv["poster"]["playback_url"]
    assert body["full_quality_url"].endswith("/play")
    assert body["full_quality_url"] != body["preview_url"]


def test_small_source_hq_aliases_durable_light(client, db):
    body = _status(client, UUID_SMALL)
    deriv = body["derivatives"]
    assert deriv["light"]["state"] == "ready"
    assert deriv["hq"]["state"] == "ready"
    assert deriv["hq"]["aliased_to"] == "light"
    assert deriv["hq"]["playback_url"] == deriv["light"]["playback_url"]
    assert deriv["hq"]["revision_id"] == deriv["light"]["revision_id"]
    assert deriv["start"] == "light"
    assert deriv["recommended"] == "hq"


def test_small_source_without_dims_refuses_alias(client):
    body = _status(client, UUID_SMALL_NODIMS)
    deriv = body["derivatives"]
    assert deriv["light"]["state"] == "ready"
    assert deriv["hq"]["state"] == "missing"
    assert deriv["hq"]["playback_url"] is None


def test_stale_ledger_row_never_servable(client):
    body = _status(client, UUID_STALE)
    deriv = body["derivatives"]
    assert deriv["light"]["state"] == "stale"
    assert deriv["light"]["playback_url"] is None


def test_old_transform_version_ignored(client):
    body = _status(client, UUID_OLDVERSION)
    deriv = body["derivatives"]
    assert deriv["light"]["state"] == "missing"
    assert deriv["light"]["playback_url"] is None


def test_dev_only_publish_never_ready_in_prod(client):
    body = _status(client, UUID_DEVONLY)
    deriv = body["derivatives"]
    assert deriv["light"]["state"] == "unavailable"
    assert deriv["light"]["playback_url"] is None


def test_identical_bytes_under_two_trusted_keys_are_ready(client):
    # Two clips with a byte-identical poster share one blob that the
    # publisher stored under two per-source keys: both replicas are verified
    # copies of the same SHA, so the oldest one serves.
    body = _status(client, UUID_AMBIG)
    deriv = body["derivatives"]
    assert deriv["light"]["state"] == "ready"
    assert deriv["light"]["playback_url"]


def test_replica_outside_trusted_bucket_fails_closed(client, db):
    light_sha = (
        db.query(MediaDerivative.derivative_blob_sha256)
        .filter_by(video_uuid=UUID_AMBIG, role="light")
        .scalar()
    )
    _loc(db, light_sha, "prod", DEV_BUCKET, "blobs/sha256/derived/light-foreign.bin")
    db.commit()
    deriv = _status(client, UUID_AMBIG)["derivatives"]
    assert deriv["light"]["state"] == "unavailable"
    assert deriv["light"]["playback_url"] is None


def test_ready_derivative_without_canonical_source_never_served(client):
    body = _status(client, UUID_NOSRC)
    deriv = body["derivatives"]
    assert deriv["source_revision_id"] is None
    assert deriv["light"]["state"] == "missing"
    assert deriv["light"]["playback_url"] is None


def test_ready_derivative_of_old_source_never_served_as_current(client):
    body = _status(client, UUID_OLDSRC)
    deriv = body["derivatives"]
    assert deriv["light"]["state"] == "missing"
    assert deriv["light"]["playback_url"] is None


def test_legacy_clip_keeps_working_without_derivatives_block(client):
    body = _status(client, UUID_LEGACY)
    deriv = body["derivatives"]
    assert deriv["light"]["state"] == "missing"
    assert deriv["hq"]["state"] == "missing"
    assert deriv["poster"]["state"] == "missing"
    assert body["status"] == "ready"
    assert body["preview_url"].startswith("/api/v1/media/cache/")
    assert body["full_quality_url"].endswith("/play")


def test_old_schema_without_ledger_table_keeps_legacy_status(db, flags, fake_presign, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(
        engine,
        tables=[
            SessionModel.__table__,
            Dive.__table__,
            Diver.__table__,
            MediaBlob.__table__,
            MediaBlobLocation.__table__,
            MediaRevision.__table__,
            # NOTE: no MediaDerivative table (pre-D1 database).
            PhotosAsset.__table__,
            MediaCacheEntry.__table__,
            MediaJob.__table__,
            AppUser.__table__,
            UserCredential.__table__,
            UserSession.__table__,
            UserDiverAccess.__table__,
            LoginAttempt.__table__,
            MediaPlaybackGrant.__table__,
            SecurityAuditEvent.__table__,
        ],
    )
    OldSession = sessionmaker(bind=engine)
    old = OldSession()
    now = datetime.utcnow()
    diver = Diver(display_name="Old D", canonical_name="old-d", is_primary_user=False)
    old.add(diver)
    old.flush()
    sess = SessionModel(date=now.date(), location="Pool")
    old.add(sess)
    old.flush()
    old.add(
        Dive(
            visibility="private",
            session_id=sess.id,
            dive_code="101B",
            performance="G",
            performance_numeric=3,
            height="1m",
            video_uuid=UUID_LEGACY,
            diver_id=diver.id,
            dive_datetime=now,
        )
    )
    old.add(MediaBlob(sha256=SRC_LEGACY, byte_size=1000))
    old.add(MediaRevision(video_uuid=UUID_LEGACY, blob_sha256=SRC_LEGACY))
    _loc(old, SRC_LEGACY, "prod", PROD_BUCKET, f"blobs/{SRC_LEGACY}.mov")
    asset = PhotosAsset(video_uuid=UUID_LEGACY, media_type="video")
    old.add(asset)
    old.flush()
    cached = tmp_path / "old-720p.mp4"
    cached.write_bytes(b"FAKELEGACYVIDEOBYTES" * 10)
    old.add(
        MediaCacheEntry(
            photos_asset_id=asset.id,
            media_key="old-key",
            rendition="proxy_720p",
            storage_path=str(cached),
            content_type="video/mp4",
            size_bytes=200,
            status="ready",
        )
    )
    user = AppUser(email="old@example.test", display_name="old")
    old.add(user)
    old.flush()
    old.add(UserCredential(user_id=user.id, password_hash=hash_password("correct-horse-battery"), password_algo="argon2id"))
    old.add(UserDiverAccess(user_id=user.id, diver_id=diver.id, access_kind="OWNER"))
    old.commit()

    def override_get_db():
        yield old

    app.dependency_overrides[get_db] = override_get_db
    try:
        test_client = TestClient(app)
        test_client.post("/api/v1/auth/login", json={"email": "old@example.test", "password": "correct-horse-battery"})
        r = test_client.get(f"/api/v1/media/{UUID_LEGACY}/status")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["derivatives"] is None
        assert body["status"] == "ready"
        # The aborted ledger probe ran in a SAVEPOINT: the session still
        # serves legacy queries afterwards (on Postgres a naked failed
        # statement would poison the whole transaction).
        assert old.query(MediaCacheEntry).count() == 1
    finally:
        app.dependency_overrides.clear()
        old.close()
        engine.dispose()


def test_durable_starter_wins_playback_url_over_backbone_and_legacy(client, db):
    # Authoritative starter semantics: the verified durable light starter is
    # the default playback_url even when a backbone original exists (the
    # camera original stays the explicit full-quality choice). Legacy-only
    # clips without derivatives keep the backbone starter unchanged.
    full = _status(client, UUID_FULL)
    light_url = full["derivatives"]["light"]["playback_url"]
    assert light_url is not None
    assert full["status"] == "ready"
    assert full["playback_url"] == light_url
    assert full["preview_url"] == light_url
    assert full["full_quality_url"] is not None
    assert full["full_quality_url"] != light_url

    legacy = _status(client, UUID_LEGACY)
    assert legacy["derivatives"]["light"]["state"] == "missing"
    assert legacy["status"] == "ready"
    assert legacy["playback_url"] == legacy["full_quality_url"]


# ------------------------------------------------------- HTTP contract


def test_owner_derivative_play_redirects_with_grant(client, db):
    body = _status(client, UUID_FULL)
    light_url = body["derivatives"]["light"]["playback_url"]
    r = client.get(light_url, follow_redirects=False)
    assert r.status_code == 302, r.text
    assert "X-Amz-Signature" in r.headers["Location"]
    assert r.headers.get("Cache-Control") == "private, no-store"
    assert r.headers.get("Referrer-Policy") == "no-referrer"
    grants = db.query(MediaPlaybackGrant).filter_by(outcome="ALLOWED").all()
    assert len(grants) == 1
    assert grants[0].ttl_seconds == 120


@pytest.mark.parametrize("role", ["light", "original"])
def test_provider_head_has_no_open_transaction(client, db, monkeypatch, role):
    import app.api.v1.media_playback as playback_module

    body = _status(client, UUID_FULL)
    url = body["derivatives"]["light"]["playback_url"] if role == "light" else body["full_quality_url"]
    seen = []

    def head(bucket, object_key):
        seen.append(True)
        assert not db.in_transaction(), "provider I/O must not hold a DB transaction"

    monkeypatch.setattr(playback_module.b2_presign, "head_object", head)
    response = client.get(url, follow_redirects=False)
    assert response.status_code == 302, response.text
    assert seen == [True]


@pytest.mark.parametrize("change", ["owner", "session", "source", "ledger", "location", "failed_head_owner"])
def test_provider_wait_rechecks_authority(client, db, fake_presign, monkeypatch, change):
    import app.api.v1.media_playback as playback_module

    url = _status(client, UUID_FULL)["derivatives"]["light"]["playback_url"]
    revision_id = int(url.split("/")[-2])
    other_session = sessionmaker(bind=db.get_bind())

    def head(bucket, object_key):
        assert not db.in_transaction()
        with other_session() as writer:
            if change in ("owner", "failed_head_owner"):
                user = writer.query(AppUser).filter_by(email="user-a@example.test").one()
                writer.query(UserDiverAccess).filter_by(user_id=user.id).delete()
            elif change == "session":
                writer.query(UserSession).update({UserSession.revoked_at: datetime.utcnow()})
            elif change == "source":
                sha = _sha("source-changed-during-head")
                writer.add(MediaBlob(sha256=sha, byte_size=123, width=1920, height=1080))
                writer.add(MediaRevision(video_uuid=UUID_FULL, blob_sha256=sha))
                _loc(writer, sha, "prod", PROD_BUCKET, f"blobs/{sha}.mov")
            elif change == "ledger":
                writer.query(MediaDerivative).filter_by(video_uuid=UUID_FULL, role="light").update({MediaDerivative.status: "stale"})
            elif change == "location":
                revision = writer.get(MediaRevision, revision_id)
                writer.query(MediaBlobLocation).filter_by(blob_sha256=revision.blob_sha256).update({MediaBlobLocation.object_key: "changed-after-head"})
            writer.commit()
        if change == "failed_head_owner":
            raise playback_module.b2_presign.PresignUnavailable("fake provider outage")

    monkeypatch.setattr(playback_module.b2_presign, "head_object", head)
    response = client.get(url, follow_redirects=False)
    assert response.status_code == (401 if change == "session" else 404), response.text
    assert fake_presign[1] == []
    assert db.query(MediaPlaybackGrant).filter_by(outcome="ALLOWED").count() == 0


def test_grant_renewal_mints_fresh_grant_per_play(client, db):
    body = _status(client, UUID_FULL)
    light_url = body["derivatives"]["light"]["playback_url"]
    client.get(light_url, follow_redirects=False)
    client.get(light_url, follow_redirects=False)
    grants = db.query(MediaPlaybackGrant).filter_by(outcome="ALLOWED").all()
    assert len(grants) == 2


def test_range_request_passes_through_as_b2_redirect(client):
    body = _status(client, UUID_FULL)
    hq_url = body["derivatives"]["hq"]["playback_url"]
    r = client.get(hq_url, headers={"range": "bytes=0-1023"}, follow_redirects=False)
    # The backend never serves derivative bytes itself: Safari negotiates
    # Range/206 directly with B2 on the presigned URL.
    assert r.status_code == 302, r.text
    assert "Location" in r.headers


def test_stranger_gets_uniform_404_without_grant(db, flags, fake_presign, client):
    r = client.post("/api/v1/auth/logout")
    assert r.status_code in (200, 204)
    login = client.post("/api/v1/auth/login", json={"email": "user-b@example.test", "password": "correct-horse-battery"})
    assert login.status_code == 200, login.text
    # Stranger status: the asset is unknown outside the owner chain.
    r = client.get(f"/api/v1/media/{UUID_FULL}/status")
    assert r.status_code == 404
    light_rev = _derived_revision_id(db, UUID_FULL, "derived_light")
    r = client.get(f"/api/v1/media/revisions/{light_rev}/play", follow_redirects=False)
    assert r.status_code == 404
    assert db.query(MediaPlaybackGrant).filter_by(outcome="ALLOWED").count() == 0


def test_unauthenticated_derivative_play_rejected(client):
    client.post("/api/v1/auth/logout")
    r = client.get("/api/v1/media/revisions/1/play", follow_redirects=False)
    assert r.status_code in (401, 404)


def test_derivative_presign_failure_is_explicit_503_never_legacy(client, db, fake_presign, python_streamed_media):
    behavior, _calls = fake_presign
    body = _status(client, UUID_FULL)
    light_url = body["derivatives"]["light"]["playback_url"]
    behavior["fail"] = True
    try:
        r = client.get(light_url, follow_redirects=False)
        assert r.status_code == 503, r.text
        assert b"FAKELEGACYVIDEOBYTES" not in r.content
    finally:
        behavior["fail"] = False


def test_derivative_without_prod_storage_is_404_never_legacy(client, db, python_streamed_media):
    rev_id = _derived_revision_id(db, UUID_DEVONLY, "derived_light")
    r = client.get(f"/api/v1/media/revisions/{rev_id}/play", follow_redirects=False)
    assert r.status_code == 404, r.text
    assert b"FAKELEGACYVIDEOBYTES" not in r.content


def test_identical_trusted_replicas_play_from_oldest(client, db, python_streamed_media):
    rev_id = _derived_revision_id(db, UUID_AMBIG, "derived_light")
    r = client.get(f"/api/v1/media/revisions/{rev_id}/play", follow_redirects=False)
    assert r.status_code == 302, r.text
    assert "a.bin" in r.headers["location"]


# ------------------------------------------------------- evaluation
# Evaluation stays off the derivative read path until a real consumer
# cutover lands: per-item derivative resolution here would reintroduce
# N+1 round trips after the queue's batched probes. Library status keeps
# the shared resolver; evaluation keeps legacy entries + backbone only.


def test_evaluation_status_carries_no_derivatives(client, db, monkeypatch):
    import app.services.derivative_read as derivative_read_module
    from app.services import evaluation_access

    def _fail(_db, _uuid, **_kwargs):
        raise AssertionError("evaluation status must not resolve derivatives")

    monkeypatch.setattr(
        derivative_read_module, "safe_resolve_clip_derivatives", _fail
    )
    monkeypatch.setattr(
        derivative_read_module, "resolve_clip_derivatives", _fail
    )

    dive = db.query(Dive).filter_by(video_uuid=UUID_FULL).one()
    asset = db.query(PhotosAsset).filter_by(video_uuid=UUID_FULL).one()
    user = db.query(AppUser).filter_by(email="user-a@example.test").one()
    request_row = EvaluationRequest(dive_id=dive.id, active=True, created_by_user_id=user.id)
    db.add(request_row)
    db.flush()
    payload = evaluation_access.media_status(
        db, request_row, asset, prefetched=([], False), backbone_available=True
    )
    assert "derivatives" not in payload
    # Playback selection unchanged (legacy entries + backbone original).
    assert payload["playback_url"] == f"/api/v1/evaluations/requests/{request_row.id}/media/play"


def test_evaluation_queue_batch_does_not_call_derivative_resolver(db, monkeypatch):
    import app.services.derivative_read as derivative_read_module
    from app.services import evaluation_queue

    calls: list = []

    def _fail(_db, _uuid, **_kwargs):
        calls.append(_uuid)
        raise AssertionError("queue batch must not resolve derivatives per item")

    monkeypatch.setattr(
        derivative_read_module, "safe_resolve_clip_derivatives", _fail
    )
    monkeypatch.setattr(
        derivative_read_module, "resolve_clip_derivatives", _fail
    )

    user = db.query(AppUser).filter_by(email="user-a@example.test").one()
    pairs = []
    for uuid in (UUID_FULL, UUID_SMALL):
        dive = db.query(Dive).filter_by(video_uuid=uuid).one()
        request_row = EvaluationRequest(
            dive_id=dive.id, active=True, created_by_user_id=user.id
        )
        db.add(request_row)
        db.flush()
        pairs.append((request_row, dive))
    items = evaluation_queue._batch_payloads(db, pairs)
    assert calls == []
    assert len(items) == 2
    for item in items:
        assert set(item["media"]) == {"status", "poster_url", "playback_url"}
        assert "derivatives" not in item["media"]


# ------------------------------------------------------- review fixes


def test_small_source_with_recorded_hq_row_never_aliases(client):
    body = _status(client, UUID_SMALL_RECORDEDHQ)
    deriv = body["derivatives"]
    assert deriv["light"]["state"] == "ready"
    assert deriv["light"]["playback_url"] is not None
    # A recorded (stale) HQ row proves a distinct HQ was attempted for
    # this source + transform: the honest ledger state wins and light is
    # never served as HQ, even on a small source.
    assert deriv["hq"]["state"] == "stale"
    assert deriv["hq"]["playback_url"] is None
    assert deriv["hq"]["aliased_to"] is None
    assert deriv["start"] == "light"
    assert deriv["recommended"] == "light"


def test_derivative_play_denied_after_source_drift_zero_presign(client, db, fake_presign, monkeypatch):
    import app.api.v1.media_playback as playback_module

    _behavior, presign_calls = fake_presign
    head_calls = []
    real_head = playback_module.b2_presign.head_object

    def _counting_head(bucket, object_key):
        head_calls.append((bucket, object_key))
        return real_head(bucket, object_key)

    monkeypatch.setattr(playback_module.b2_presign, "head_object", _counting_head)

    body = _status(client, UUID_FULL)
    light_url = body["derivatives"]["light"]["playback_url"]
    r = client.get(light_url, follow_redirects=False)
    assert r.status_code == 302, r.text
    presigns_after_allow = len(presign_calls)
    heads_after_allow = len(head_calls)
    allowed_after_allow = db.query(MediaPlaybackGrant).filter_by(outcome="ALLOWED").count()
    assert allowed_after_allow == 1

    # The canonical source drifts: a newer verified PROD camera-original
    # revision lands. The previously valid derivative URL must die.
    new_src = _sha("d5-full-src-v2")
    db.add(MediaBlob(sha256=new_src, byte_size=10_000_001, width=1920, height=1080))
    db.flush()
    db.add(MediaRevision(video_uuid=UUID_FULL, blob_sha256=new_src))
    db.flush()
    _loc(db, new_src, "prod", PROD_BUCKET, f"blobs/sha256/{new_src[:2]}/{new_src}.mov")
    db.commit()

    r = client.get(light_url, follow_redirects=False)
    assert r.status_code == 404, r.text
    # Zero presign on deny: neither the provider HEAD nor presign ran, no
    # ALLOWED grant was minted; the denial is recorded as not-current.
    assert len(presign_calls) == presigns_after_allow
    assert len(head_calls) == heads_after_allow
    assert db.query(MediaPlaybackGrant).filter_by(outcome="ALLOWED").count() == allowed_after_allow
    denied = (
        db.query(MediaPlaybackGrant)
        .filter_by(outcome="DENIED", denial_reason="derivative_not_current")
        .all()
    )
    assert len(denied) == 1
    # Status agrees: the old derivative is no longer advertised.
    body = _status(client, UUID_FULL)
    assert body["derivatives"]["light"]["state"] == "missing"
    assert body["derivatives"]["light"]["playback_url"] is None


def test_derivative_play_denied_after_ledger_status_and_version_change(client, db, fake_presign):
    _behavior, presign_calls = fake_presign
    body = _status(client, UUID_FULL)
    light_url = body["derivatives"]["light"]["playback_url"]
    assert client.get(light_url, follow_redirects=False).status_code == 302
    presigns_after_allow = len(presign_calls)

    light_row = (
        db.query(MediaDerivative)
        .filter_by(video_uuid=UUID_FULL, role="light", source_blob_sha256=SRC_FULL)
        .one()
    )
    light_row.status = "stale"
    db.commit()
    try:
        r = client.get(light_url, follow_redirects=False)
        assert r.status_code == 404, r.text
        assert len(presign_calls) == presigns_after_allow
    finally:
        light_row.status = "ready"
        db.commit()

    # Back to ready, then the transform version moves on: same 404.
    light_row.transform_version = "ffmpeg-h264-web-v0"
    db.commit()
    try:
        r = client.get(light_url, follow_redirects=False)
        assert r.status_code == 404, r.text
        assert len(presign_calls) == presigns_after_allow
    finally:
        light_row.transform_version = get_settings().media_derivative_transform_version
        db.commit()


def test_replica_set_beyond_bounded_probe_fails_closed(client, db, python_streamed_media):
    from app.services.media_backbone import TRUSTED_REPLICA_PROBE

    light_sha = (
        db.query(MediaDerivative.derivative_blob_sha256)
        .filter_by(video_uuid=UUID_AMBIG, role="light")
        .scalar()
    )
    for n in range(TRUSTED_REPLICA_PROBE):
        _loc(db, light_sha, "prod", PROD_BUCKET, f"blobs/sha256/derived/light-extra-{n}.bin")
    db.commit()
    body = _status(client, UUID_AMBIG)
    assert body["derivatives"]["light"]["state"] == "unavailable"
    assert body["derivatives"]["light"]["playback_url"] is None
    rev_id = _derived_revision_id(db, UUID_AMBIG, "derived_light")
    r = client.get(f"/api/v1/media/revisions/{rev_id}/play", follow_redirects=False)
    assert r.status_code == 404, r.text


def test_status_discloses_no_signed_urls_or_secrets(client):
    import json

    body = _status(client, UUID_FULL)
    raw = json.dumps(body)
    assert "X-Amz-Signature" not in raw
    assert "backblazeb2" not in raw.lower()
    assert "bucket" not in raw
    assert "object_key" not in raw
    for role in ("hq", "light", "poster"):
        entry = body["derivatives"][role]
        assert entry["playback_url"].startswith("/api/v1/media/revisions/")
        assert entry["playback_url"].endswith("/play")


def test_unrelated_db_error_not_masked_as_missing_derivatives(client, monkeypatch):
    import sqlalchemy.exc

    import app.services.derivative_read as derivative_read_module

    def _boom(_db, _uuid, **_kwargs):
        raise sqlalchemy.exc.OperationalError("SELECT 1", {}, Exception("connection reset"))

    monkeypatch.setattr(derivative_read_module, "resolve_clip_derivatives", _boom)
    with pytest.raises(sqlalchemy.exc.OperationalError):
        client.get(f"/api/v1/media/{UUID_FULL}/status")


# ------------------------------------------------------- review round3
# Ready durable light/HQ is authoritative for a browser_original canonical
# source even with zero legacy cache entries and no backbone original
# (browser_original is excluded from the legacy original selector).
# Poster-only must NOT read ready; stale rows stay not-ready; an active
# legacy job must not override verified durable readiness.


UUID_BROWSER_LIGHT = "D5000000-0000-4000-8000-000000000021"
UUID_BROWSER_HQ = "D5000000-0000-4000-8000-000000000022"
UUID_BROWSER_POSTER = "D5000000-0000-4000-8000-000000000023"
UUID_BROWSER_JOB = "D5000000-0000-4000-8000-000000000024"
UUID_BROWSER_STALE = "D5000000-0000-4000-8000-000000000025"


def _seed_browser_clip(db, uuid, dive_code, roles, src_seed, status_by_role=None):
    """Minimal browser_original canonical clip with zero cache and no Mac.

    * source revision semantics ``browser_original`` + one verified PROD
      B2 replica (canonical for the durable resolver, excluded from the
      legacy backbone original selector);
    * requested durable roles as ready (current transform) with derived
      revisions + verified PROD locations;
    * no MediaCacheEntry rows, no MediaJob rows.
    """
    from datetime import datetime, timedelta

    status_by_role = status_by_role or {}
    diver = db.query(Diver).filter_by(canonical_name="diver-a").one()
    session_row = db.query(SessionModel).order_by(SessionModel.id).first()
    db.add(
        Dive(
            visibility="private",
            session_id=session_row.id,
            dive_code=dive_code,
            performance="G",
            performance_numeric=3,
            height="1m",
            video_uuid=uuid,
            diver_id=diver.id,
            dive_datetime=datetime.utcnow() - timedelta(hours=1),
        )
    )
    src = _sha(src_seed)
    db.add(MediaBlob(sha256=src, byte_size=10_000_000, width=1920, height=1080))
    db.flush()
    _rev(db, uuid, src, "browser_original")
    _loc(db, src, "prod", PROD_BUCKET, f"blobs/sha256/{src[:2]}/{src}.mov")
    for role in roles:
        dsha = _sha(f"{src_seed}-{role}")
        _derivative(db, uuid, src, role, dsha, status=status_by_role.get(role, "ready"))
        semantics = {"hq": "derived_hq", "light": "derived_light", "poster": "derived_poster"}[role]
        _rev(db, uuid, dsha, semantics)
        _loc(db, dsha, "prod", PROD_BUCKET, f"blobs/sha256/derived/{role}-{dsha[:8]}.bin")
    db.add(PhotosAsset(video_uuid=uuid, media_type="video"))
    db.commit()
    return src


def test_browser_original_light_only_is_ready_with_zero_cache(client, db):
    _seed_browser_clip(db, UUID_BROWSER_LIGHT, "201B", ("light", "poster"), "d5-browser-light-src")
    body = _status(client, UUID_BROWSER_LIGHT)
    deriv = body["derivatives"]
    assert deriv["light"]["state"] == "ready"
    light_url = deriv["light"]["playback_url"]
    assert light_url is not None
    # Authoritative readiness: no backbone original (browser_original
    # excluded), no legacy entries, yet playable.
    assert body["status"] == "ready"
    assert body["playback_url"] == light_url
    assert body["preview_url"] == light_url
    # Original discovery untouched: no backbone, no local original, and
    # the original must never be served as the web-ready starter.
    assert body["full_quality_url"] is None
    assert body["available_renditions"] == []
    assert body["preferred_rendition"] is None
    assert body["cache_entries"] == []
    assert body["job"] is None


def test_browser_original_hq_only_is_ready_with_zero_cache(client, db):
    _seed_browser_clip(db, UUID_BROWSER_HQ, "202B", ("hq",), "d5-browser-hq-src")
    body = _status(client, UUID_BROWSER_HQ)
    deriv = body["derivatives"]
    assert deriv["hq"]["state"] == "ready"
    assert deriv["light"]["state"] == "missing"
    hq_url = deriv["hq"]["playback_url"]
    assert hq_url is not None
    assert body["status"] == "ready"
    assert body["playback_url"] == hq_url
    assert body["preview_url"] == hq_url
    assert body["full_quality_url"] is None
    assert body["available_renditions"] == []
    assert body["cache_entries"] == []


def test_browser_original_poster_only_stays_not_ready(client, db):
    _seed_browser_clip(db, UUID_BROWSER_POSTER, "203B", ("poster",), "d5-browser-poster-src")
    body = _status(client, UUID_BROWSER_POSTER)
    deriv = body["derivatives"]
    assert deriv["poster"]["state"] == "ready"
    assert deriv["light"]["state"] == "missing"
    assert deriv["hq"]["state"] == "missing"
    # Poster alone is never playable readiness.
    assert body["status"] == "missing"
    assert body["playback_url"] is None
    assert body["preview_url"] is None
    assert body["poster_url"] == deriv["poster"]["playback_url"]


def test_browser_original_stale_light_stays_not_ready(client, db):
    _seed_browser_clip(
        db, UUID_BROWSER_STALE, "205B", ("light",), "d5-browser-stale-src",
        status_by_role={"light": "stale"},
    )
    body = _status(client, UUID_BROWSER_STALE)
    assert body["derivatives"]["light"]["state"] == "stale"
    assert body["derivatives"]["light"]["playback_url"] is None
    assert body["status"] == "missing"
    assert body["playback_url"] is None
    assert body["preview_url"] is None


def test_browser_original_active_job_does_not_override_durable_ready(client, db):
    src = _seed_browser_clip(db, UUID_BROWSER_JOB, "204B", ("light",), "d5-browser-job-src")
    asset = db.query(PhotosAsset).filter_by(video_uuid=UUID_BROWSER_JOB).one()
    db.add(
        MediaJob(
            photos_asset_id=asset.id,
            media_key="d5-browser-job-key",
            rendition="proxy_720p",
            status="queued",
            priority=5,
            request_reason="user_view",
        )
    )
    db.commit()
    body = _status(client, UUID_BROWSER_JOB)
    light_url = body["derivatives"]["light"]["playback_url"]
    assert light_url is not None
    assert body["status"] == "ready"
    assert body["playback_url"] == light_url
    assert body["preview_url"] == light_url
    # The active legacy job is still disclosed, but it does not override
    # verified durable readiness.
    assert body["job"] is not None
    assert body["job"]["status"] == "queued"
