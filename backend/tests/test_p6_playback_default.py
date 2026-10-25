"""P6 backend matrix: B2-default playback with authenticated legacy
fallback, legacy IDOR closure, rate-limit DoS resistance, session cleanup,
and Origin (CSRF defense-in-depth) validation.

Covers the MEDIA_BACKBONE_P6_ACCELERATED_DEFAULT_PLAYBACK_V1 §33 additions
beyond the P5 suite. The presigner is faked (like P5) so no live provider
is needed here; live canary/cohort evidence is collected separately.
"""

import hashlib
from datetime import datetime, timedelta
from pathlib import Path

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
from app.models.media import MediaCacheEntry
from app.models.media_backbone import MediaBlobLocation, MediaRevision
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
from app.services import sessions as sessions_authority
from app.services.passwords import hash_password

PROD_BUCKET = "diveanalyzer-prod-media"
DEV_BUCKET = "diveanalyzer-dev-media"
PRESIGN_MARKER = "Fakesigmarker00000000000000000000000000000000000000000000"


def _sha(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


UUID_A = "A1000000-0000-4000-8000-00000000000A"
UUID_B = "B2000000-0000-4000-8000-00000000000B"
UUID_NO_B2 = "F6000000-0000-4000-8000-00000000000F"
UUID_AMBIGUOUS = "E5000000-0000-4000-8000-00000000000E"

SHA_A = _sha("p6-a")
SHA_B = _sha("p6-b")
SHA_NO_B2 = _sha("p6-no-b2")
SHA_AMBIGUOUS = _sha("p6-ambiguous")


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
            MediaBlobLocation.__table__,
            MediaRevision.__table__,
            PhotosAsset.__table__,
            MediaCacheEntry.__table__,
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
    s2 = SessionModel(date=(now - timedelta(days=1)).date(), location="Pool")
    db.add_all([s1, s2])
    db.flush()

    def _dive(uuid, code, diver, session_row, hours_ago):
        return Dive(
            visibility="private",
            session_id=session_row.id,
            dive_code=code,
            performance="G",
            performance_numeric=3,
            height="1m",
            video_uuid=uuid,
            diver_id=diver.id,
            dive_datetime=now - timedelta(hours=hours_ago),
        )

    dive_a = _dive(UUID_A, "101B", d1, s1, 1)
    dive_b = _dive(UUID_B, "101B", d2, s2, 2)
    dive_no_b2 = _dive(UUID_NO_B2, "201B", d1, s1, 3)
    dive_ambiguous = _dive(UUID_AMBIGUOUS, "401B", d1, s1, 5)
    db.add_all([dive_a, dive_b, dive_no_b2, dive_ambiguous])
    db.flush()

    for uuid, sha in ((UUID_A, SHA_A), (UUID_B, SHA_B), (UUID_NO_B2, SHA_NO_B2), (UUID_AMBIGUOUS, SHA_AMBIGUOUS)):
        db.add(MediaRevision(video_uuid=uuid, blob_sha256=sha))

    # PROD verified B2 replicas for A and B only.
    db.add(MediaBlobLocation(blob_sha256=SHA_A, environment="prod", storage_backend="b2", bucket=PROD_BUCKET, object_key=f"blobs/sha256/{SHA_A[:2]}/{SHA_A}.mov", verified=True, verified_at=now))
    db.add(MediaBlobLocation(blob_sha256=SHA_B, environment="prod", storage_backend="b2", bucket=PROD_BUCKET, object_key=f"blobs/sha256/{SHA_B[:2]}/{SHA_B}.mov", verified=True, verified_at=now))
    # Ambiguous: two verified PROD locations (fail-closed integrity case).
    db.add(MediaBlobLocation(blob_sha256=SHA_AMBIGUOUS, environment="prod", storage_backend="b2", bucket=PROD_BUCKET, object_key=f"blobs/sha256/{SHA_AMBIGUOUS[:2]}/{SHA_AMBIGUOUS}-r1.mov", verified=True, verified_at=now))
    db.add(MediaBlobLocation(blob_sha256=SHA_AMBIGUOUS, environment="prod", storage_backend="b2", bucket="foreign-bucket", object_key=f"blobs/sha256/{SHA_AMBIGUOUS[:2]}/{SHA_AMBIGUOUS}-r2.mov", verified=True, verified_at=now))
    # DEV-only verified location for the NO_B2 revision.
    db.add(MediaBlobLocation(blob_sha256=SHA_NO_B2, environment="dev", storage_backend="b2", bucket=DEV_BUCKET, object_key=f"blobs/sha256/{SHA_NO_B2[:2]}/{SHA_NO_B2}.mov", verified=True))

    # Photos assets + cache renditions: legacy sources for A and NO_B2
    # (real files in tmp_path so server-side streaming is exercised).
    assets = {}
    for uuid in (UUID_A, UUID_B, UUID_NO_B2, UUID_AMBIGUOUS):
        asset = PhotosAsset(video_uuid=uuid, media_type="video")
        db.add(asset)
        db.flush()
        assets[uuid] = asset

    def _cache_file(name: str) -> str:
        p = tmp_path / name
        p.write_bytes(b"FAKELEGACYVIDEOBYTES" * 100)
        return str(p)

    db.add(MediaCacheEntry(
        photos_asset_id=assets[UUID_A].id,
        media_key=f"k-a-{_sha('cache-a')[:24]}",
        rendition="proxy_720p",
        storage_path=_cache_file("a-720p.mp4"),
        content_type="video/mp4",
        size_bytes=2000,
        status="ready",
    ))
    db.add(MediaCacheEntry(
        photos_asset_id=assets[UUID_NO_B2].id,
        media_key=f"k-c-{_sha('cache-c')[:24]}",
        rendition="proxy_360p",
        storage_path=_cache_file("c-360p.mp4"),
        content_type="video/mp4",
        size_bytes=2000,
        status="ready",
    ))
    db.add(MediaCacheEntry(
        photos_asset_id=assets[UUID_AMBIGUOUS].id,
        media_key=f"k-d-{_sha('cache-d')[:24]}",
        rendition="proxy_720p",
        storage_path=_cache_file("d-720p.mp4"),
        content_type="video/mp4",
        size_bytes=2000,
        status="ready",
    ))
    db.add(MediaCacheEntry(
        photos_asset_id=assets[UUID_B].id,
        media_key=f"k-b-{_sha('cache-b')[:24]}",
        rendition="poster",
        storage_path=_cache_file("b-poster.jpg"),
        content_type="image/jpeg",
        size_bytes=500,
        status="ready",
    ))
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
def fake_presign(monkeypatch, request):
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
def python_streamed_media():
    """TestClient cannot honor X-Accel-Redirect (no nginx inside the loop);
    byte-level assertions exercise the in-process streaming path, so they
    run with the accel off."""
    settings = get_settings()
    saved = (settings.media_xaccel_enabled, settings.media_xaccel_prefix)
    settings.media_xaccel_enabled = False
    yield
    settings.media_xaccel_enabled, settings.media_xaccel_prefix = saved


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


def _revision_id(db, uuid):
    return db.query(MediaRevision).filter_by(video_uuid=uuid).one().id


def _login(client, email="user-a@example.test", password="correct-horse-battery", ip=None):
    headers = {"X-Forwarded-For": ip} if ip else {}
    return client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}, headers=headers
    )


# ------------------------------------------------------- §16/§21/§22/§13 default + fallback


def test_owner_b2_default_when_provider_healthy(client, db, fake_presign):
    behavior, calls = fake_presign
    r = client.get(f"/api/v1/media/revisions/{_revision_id(db, UUID_A)}/play", follow_redirects=False)
    assert r.status_code == 302
    assert "Location" in r.headers
    assert "X-Amz-Signature" in r.headers["Location"]
    assert calls and calls[-1]["bucket"] == PROD_BUCKET
    assert r.headers.get("Cache-Control") == "private, no-store"
    assert r.headers.get("Referrer-Policy") == "no-referrer"


def test_b2_failure_falls_back_to_authenticated_legacy(client, db, fake_presign, python_streamed_media):
    behavior, calls = fake_presign
    behavior["fail"] = True
    r = client.get(f"/api/v1/media/revisions/{_revision_id(db, UUID_A)}/play", follow_redirects=False)
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("video/mp4")
    assert r.headers["Accept-Ranges"] == "bytes"
    assert b"FAKELEGACYVIDEOBYTES" in r.content
    assert r.headers.get("Referrer-Policy") == "no-referrer"


def test_b2_failure_with_range_served_206(client, db, fake_presign, python_streamed_media):
    behavior, calls = fake_presign
    behavior["fail"] = True
    r = client.get(
        f"/api/v1/media/revisions/{_revision_id(db, UUID_A)}/play",
        headers={"Range": "bytes=0-99"},
    )
    assert r.status_code == 206
    assert len(r.content) == 100


def test_b2_failure_no_legacy_copy_is_explicit_503(client, db, fake_presign):
    """UUID_B (owned by user-b) has a verified PROD location but NO playback
    cache rendition (poster only) and no legacy files → explicit provider
    failure."""
    behavior, calls = fake_presign
    behavior["fail"] = True
    fresh = TestClient(app)
    assert _login(fresh, email="user-b@example.test").status_code == 200
    r = fresh.get(f"/api/v1/media/revisions/{_revision_id(db, UUID_B)}/play")
    assert r.status_code == 503


def test_no_prod_b2_replica_uses_legacy_fallback(client, db, fake_presign, python_streamed_media):
    """NO_B2 revision: DEV-only verified location → authorized legacy."""
    behavior, calls = fake_presign
    r = client.get(f"/api/v1/media/revisions/{_revision_id(db, UUID_NO_B2)}/play")
    assert r.status_code == 200
    assert calls == []  # never touched the provider
    assert b"FAKELEGACYVIDEOBYTES" in r.content


def test_ambiguous_prod_location_fails_closed_no_fallback(client, db, fake_presign):
    # One of the verified PROD replicas sits outside the allowlisted bucket.
    behavior, calls = fake_presign
    r = client.get(f"/api/v1/media/revisions/{_revision_id(db, UUID_AMBIGUOUS)}/play")
    assert r.status_code == 404
    assert calls == []  # never signed an ambiguous object


def test_legacy_fallback_absent_after_location_deny_is_404(client, db, fake_presign):
    """Unverified-revision style case: no PROD replica + no legacy source."""
    import app.services.legacy_media as legacy_media_module

    revision = db.query(MediaRevision).filter_by(video_uuid=UUID_NO_B2).one()
    saved_entries = legacy_media_module._ready_cache_entries_for_uuid
    saved_candidates = legacy_media_module._legacy_file_candidates
    legacy_media_module._ready_cache_entries_for_uuid = lambda d, u: []
    legacy_media_module._legacy_file_candidates = lambda d, r: []
    try:
        r = client.get(f"/api/v1/media/revisions/{revision.id}/play")
    finally:
        legacy_media_module._ready_cache_entries_for_uuid = saved_entries
        legacy_media_module._legacy_file_candidates = saved_candidates
    assert r.status_code == 404


# ------------------------------------------------------------------- §23 wrong-owner DENY


def test_wrong_owner_denied_b2_copy(client, db):
    b2_client = TestClient(app)
    assert _login(b2_client, email="user-b@example.test").status_code == 200
    r = b2_client.get(f"/api/v1/media/revisions/{_revision_id(db, UUID_A)}/play", follow_redirects=False)
    assert r.status_code == 404
    assert "Location" not in r.headers


def test_wrong_owner_denied_when_b2_fails(client, db, fake_presign):
    behavior, calls = fake_presign
    behavior["fail"] = True
    b2_client = TestClient(app)
    assert _login(b2_client, email="user-b@example.test").status_code == 200
    r = b2_client.get(f"/api/v1/media/revisions/{_revision_id(db, UUID_A)}/play", follow_redirects=False)
    assert r.status_code == 404


def test_wrong_owner_denied_legacy_copy(client, db):
    b2_client = TestClient(app)
    assert _login(b2_client, email="user-b@example.test").status_code == 200
    # UUID_A also has an authorized-legacy cache rendition: still DENY.
    r = b2_client.get(f"/api/v1/media/revisions/{_revision_id(db, UUID_A)}/play", follow_redirects=False)
    assert r.status_code == 404


def test_unauthenticated_denied(client, db):
    fresh = TestClient(app)
    r = fresh.get(f"/api/v1/media/revisions/{_revision_id(db, UUID_A)}/play")
    assert r.status_code == 401


def test_unknown_revision_denied(client):
    fresh = TestClient(app)
    assert _login(fresh).status_code == 200
    r = fresh.get("/api/v1/media/revisions/999999/play")
    assert r.status_code == 404


# --------------------------------------------------------- §10/§14 legacy IDOR closure


def test_legacy_video_route_unauthenticated_401(client):
    fresh = TestClient(app)
    r = fresh.get(f"/api/v1/videos/{UUID_A}")
    assert r.status_code == 401


def test_legacy_video_route_wrong_owner_404(client, db):
    fresh = TestClient(app)
    assert _login(fresh, email="user-b@example.test").status_code == 200
    r = fresh.get(f"/api/v1/videos/{UUID_A}")
    assert r.status_code == 404


def test_legacy_video_check_wrong_owner_404(client):
    fresh = TestClient(app)
    assert _login(fresh, email="user-b@example.test").status_code == 200
    r = fresh.get(f"/api/v1/videos/check/{UUID_A}")
    assert r.status_code == 404


def test_legacy_cache_play_wrong_owner_404(client, db):
    fresh = TestClient(app)
    assert _login(fresh, email="user-b@example.test").status_code == 200
    entry = db.query(MediaCacheEntry).filter_by(rendition="proxy_720p").first()
    r = fresh.get(f"/api/v1/media/cache/{entry.id}/play")
    assert r.status_code == 404


def test_legacy_cache_route_owner_allowed_with_range(client, db, python_streamed_media):
    entry = db.query(MediaCacheEntry).filter_by(rendition="proxy_720p").first()
    r = client.head(f"/api/v1/media/cache/{entry.id}/play")
    assert r.status_code == 200
    assert r.headers["Accept-Ranges"] == "bytes"
    r = client.get(
        f"/api/v1/media/cache/{entry.id}/play", headers={"Range": "bytes=0-19"}
    )
    assert r.status_code == 206
    assert len(r.content) == 20


def test_legacy_routes_unauthenticated_when_flags_off(client, db, flags):
    """Emergency rollback semantics: flags OFF → exact legacy behavior."""
    import app.api.v1.media_playback as playback_module

    settings = get_settings()
    settings.user_auth_enabled = False
    settings.b2_playback_canary_enabled = False
    fresh = TestClient(app)
    # Cache play route: legacy unauthenticated behavior (404 from missing
    # entry is the historical contract; 401/ownership gating is gone).
    entry = db.query(MediaCacheEntry).filter_by(rendition="proxy_720p").first()
    r = fresh.get(f"/api/v1/media/cache/{entry.id}/play")
    assert r.status_code == 200
    # Play route: fail-closed 404 (P5 semantics unchanged).
    r = fresh.get(f"/api/v1/media/revisions/{_revision_id(db, UUID_A)}/play")
    assert r.status_code == 404


# --------------------------------------------------------------- §7 rate-limit DoS resistance


def test_wrong_password_burst_from_one_source_throttled(client, db):
    """IP cap trips BEFORE the identifier ceiling: one source cannot hold
    the identifier at its failure limit nor spray guesses."""
    for i in range(get_settings().auth_login_ip_max_failures):
        r = _login(client, password=f"nope-{i}", ip="203.0.113.7")
        assert r.status_code == 401
    r = _login(client, password="nope-more", ip="203.0.113.7")
    assert r.status_code == 429


def test_owner_recoverable_from_other_source(client, db):
    """A throttled attacker source does not lock the legitimate owner's
    source: correct password from a different IP succeeds."""
    for i in range(get_settings().auth_login_ip_max_failures):
        assert _login(client, password=f"nope-{i}", ip="203.0.113.7").status_code == 401
    fresh = TestClient(app)
    r = _login(fresh, ip="198.51.100.9")
    assert r.status_code == 200


def test_successful_login_clears_identifier_failures(client, db):
    """Non-destructive recovery: after a success the identifier counter is
    cleared, so the next burst cycle starts from zero."""
    ipcap = get_settings().auth_login_ip_max_failures
    idcap = get_settings().auth_login_max_failures
    assert idcap > ipcap
    # Distributed failures below the identifier ceiling but over the IP cap
    # for their own sources:
    for i in range(ipcap):
        assert _login(client, password="nope", ip=f"203.0.113.{i+1}").status_code == 401
    for i in range(ipcap, min(idcap, 2 * ipcap)):
        assert _login(client, password="nope", ip=f"203.0.113.{i+1}").status_code == 401
    # Identifier ceiling now reached → owner is throttled too (bounded).
    fresh = TestClient(app)
    assert _login(fresh, ip="198.51.100.9").status_code == 429
    # Window roll-off, then a legitimate login SUCCEEDS and clears rows:
    for row in db.query(LoginAttempt).all():
        row.created_at = datetime.utcnow() - timedelta(
            seconds=get_settings().auth_login_failure_window_seconds + 1
        )
    db.commit()
    assert _login(fresh, ip="198.51.100.9").status_code == 200
    db.expire_all()
    remaining = (
        db.query(LoginAttempt)
        .filter(LoginAttempt.identifier == "user-a@example.test", LoginAttempt.success.is_(False))
        .count()
    )
    assert remaining == 0


def test_different_identifier_not_globally_locked(client, db):
    ipcap = get_settings().auth_login_ip_max_failures
    for i in range(ipcap):
        assert _login(client, email="user-a@example.test", password="nope", ip=f"203.0.113.{i+1}").status_code == 401
    fresh = TestClient(app)
    r = _login(fresh, email="user-b@example.test", ip="198.51.100.9")
    assert r.status_code == 200


def test_rate_limit_state_expires(client, db):
    cap = get_settings().auth_login_ip_max_failures
    for i in range(cap):
        assert _login(client, password="nope", ip="203.0.113.77").status_code == 401
    assert _login(client, password="nope", ip="203.0.113.77").status_code == 429
    for row in db.query(LoginAttempt).all():
        row.created_at = datetime.utcnow() - timedelta(
            seconds=get_settings().auth_login_failure_window_seconds + 1
        )
    db.commit()
    fresh = TestClient(app)
    assert _login(fresh, ip="203.0.113.77").status_code == 200


def test_generic_429_response_no_lock_semantics(client, db):
    cap = get_settings().auth_login_ip_max_failures
    for i in range(cap):
        _login(client, password="nope", ip="203.0.113.8")
    r = _login(client, ip="203.0.113.8")
    assert r.status_code == 429
    assert r.json() == {"detail": "Too many attempts"}


# --------------------------------------------------------------- §8 session cleanup


def test_stale_sessions_cleaned_on_login(client, db):
    user = db.query(AppUser).filter_by(email="user-a@example.test").one()
    now = datetime.utcnow()
    old_expired = UserSession(user_id=user.id, token_hash="a" * 64, created_at=now - timedelta(days=3), expires_at=now - timedelta(days=2))
    old_revoked = UserSession(user_id=user.id, token_hash="b" * 64, created_at=now - timedelta(days=3), expires_at=now + timedelta(days=1), revoked_at=now - timedelta(days=2))
    fresh_revoked = UserSession(user_id=user.id, token_hash="c" * 64, created_at=now, expires_at=now + timedelta(days=1), revoked_at=now)
    db.add_all([old_expired, old_revoked, fresh_revoked])
    db.commit()
    r = _login(client)
    assert r.status_code == 200
    hashes = {s.token_hash for s in db.query(UserSession).all()}
    assert "a" * 64 not in hashes  # expired → deleted
    assert "b" * 64 not in hashes  # revoked beyond retention → deleted
    assert "c" * 64 in hashes  # recent revocation kept (auditability window)
    live = [s for s in db.query(UserSession).all() if s.revoked_at is None]
    assert len(live) == 1


# --------------------------------------------------------------- §9 CSRF / Origin


def test_hostile_origin_rejected(client):
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "user-a@example.test", "password": "correct-horse-battery"},
        headers={"Origin": "https://attacker.example"},
    )
    assert r.status_code == 403


def test_same_origin_allowed(client):
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "user-a@example.test", "password": "correct-horse-battery"},
        headers={"Origin": "https://testserver", "Host": "testserver"},
    )
    assert r.status_code == 200


def test_origin_absent_allowed(client):
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "user-a@example.test", "password": "correct-horse-battery"},
    )
    assert r.status_code == 200


# --------------------------------------------------------------- §27 metrics endpoint


def test_playback_metrics_endpoint_counts_and_never_leaks(client, db, fake_presign):
    behavior, calls = fake_presign
    client.get(f"/api/v1/media/revisions/{_revision_id(db, UUID_A)}/play", follow_redirects=False)
    behavior["fail"] = True
    client.get(
        f"/api/v1/media/revisions/{_revision_id(db, UUID_A)}/play",
        headers={"Range": "bytes=0-49"},
    )
    r = client.get("/api/v1/media/playback/metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["b2_selected"] >= 1
    assert body["legacy_fallback_selected"] >= 1
    assert body["range_successes"] >= 1
    text = r.text.lower()
    assert "signature" not in text
    assert PRESIGN_MARKER.lower() not in text
    assert "da_session" not in text


def test_provider_health_failure_falls_back_to_legacy(client, db, fake_presign, python_streamed_media):
    """§13 B2_TEMPORARY_FAILURE via the grant-time HEAD proof: a locally
    signed URL is NEVER handed to the browser when the credential cannot
    actually read the object (§29)."""
    behavior, calls = fake_presign
    import app.api.v1.media_playback as playback_module

    def _head_fail(bucket, object_key):
        raise playback_module.b2_presign.PresignUnavailable("invalid playback credential")

    saved_head = playback_module.b2_presign.head_object
    playback_module.b2_presign.head_object = _head_fail
    try:
        r = client.get(
            f"/api/v1/media/revisions/{_revision_id(db, UUID_A)}/play",
            follow_redirects=False,
        )
    finally:
        playback_module.b2_presign.head_object = saved_head
    assert r.status_code == 200
    assert b"FAKELEGACYVIDEOBYTES" in r.content
    assert calls == []  # never presigned an unusable grant


# ------------------------------------------------------- accel byte-serving


def test_cache_root_file_redirects_to_internal_media_location(client, db):
    """Files inside the cache root stream through nginx, not Python: the
    auth/path checks stay in this process and the body leaves empty with an
    internal redirect nginx resolves against the same cache root."""
    entry = db.query(MediaCacheEntry).filter_by(rendition="proxy_720p").first()
    r = client.get(f"/api/v1/media/cache/{entry.id}/play")
    assert r.status_code == 200
    redirect = r.headers["X-Accel-Redirect"]
    assert redirect.startswith("/internal-media-cache/")
    assert ".." not in redirect
    assert "X-Amz-Signature" not in redirect
    assert "Cache-Control" in r.headers
    assert r.headers.get("Referrer-Policy") == "no-referrer"
    assert b"FAKELEGACYVIDEOBYTES" not in r.content
    # The real body is empty and nginx owns the length: an upstream
    # Content-Length made uvicorn abort every accelerated response with
    # "Response content shorter than Content-Length" in production.
    assert "Content-Length" not in r.headers


def test_out_of_root_file_still_streams_through_python(client, db):
    """Legacy/guest sources rooted outside the cache must not silently
    become unresolvable internal redirects."""
    import os
    settings = get_settings()
    outside = Path(settings.media_cache_root).parent / "outside.txt"
    outside.write_bytes(b"FAKEOUTSIDEBYTES")
    saved = (settings.media_xaccel_enabled, settings.media_xaccel_prefix)
    try:
        settings.media_xaccel_enabled = True
        from app.api.v1.media import _serve_media_file
        client_request_type = type("FakeRequest", (), {"headers": {}})
        response = _serve_media_file(outside, "text/plain", client_request_type())
        body_attr = getattr(response, "body_iterator", None) or getattr(response, "body", None)
        assert body_attr is not None
        assert "X-Accel-Redirect" not in response.headers
    finally:
        os.unlink(outside)
        settings.media_xaccel_enabled, settings.media_xaccel_prefix = saved
