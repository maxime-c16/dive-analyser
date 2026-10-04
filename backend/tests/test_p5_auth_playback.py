"""P5 backend security matrix: user auth, ownership authorization, and the
authenticated B2 playback grant route.

Covers the MEDIA_BACKBONE_P5_ACCELERATED_AUTH_PLAYBACK_V1 §37 matrix plus
the §12 IDOR firewall (two synthetic users/divers) and §25 session tests.
Live-provider behaviors (presign validity/expiry, browser <video> Range/
seek) are covered by the live canary + browser matrix, not here; here the
presigner is a fake that records (bucket, key, ttl) and returns a URL with
a canary marker used to prove the URL is never logged or persisted.
"""

import hashlib
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.database import Base, get_db
from app.main import app
from app.models.dive import Dive
from app.models.diver import Diver
from app.models.media_backbone import MediaBlobLocation, MediaRevision
from app.models.media import MediaCacheEntry
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


SHA_A = _sha("p5-media-owner-diver-a")
SHA_B = _sha("p5-media-owner-diver-b")
SHA_DEV_ONLY = _sha("p5-media-dev-only")
SHA_UNVERIFIED = _sha("p5-media-unverified")
SHA_AMBIGUOUS = _sha("p5-media-ambiguous")

UUID_A = "A1000000-0000-4000-8000-00000000000A"
UUID_B = "B2000000-0000-4000-8000-00000000000B"
UUID_DEV_ONLY = "C3000000-0000-4000-8000-00000000000C"
UUID_UNVERIFIED = "D4000000-0000-4000-8000-00000000000D"
UUID_AMBIGUOUS = "E5000000-0000-4000-8000-00000000000E"


@pytest.fixture()
def db():
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
            AppUser.__table__,
            UserCredential.__table__,
            UserSession.__table__,
            UserDiverAccess.__table__,
            LoginAttempt.__table__,
            MediaPlaybackGrant.__table__,
            SecurityAuditEvent.__table__,
            PhotosAsset.__table__,
            MediaCacheEntry.__table__,
        ],
    )
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    _seed_world(session)
    yield session
    session.close()
    engine.dispose()


def _seed_world(db):
    now = datetime.utcnow()
    d1 = Diver(display_name="Diver A", canonical_name="diver-a", is_primary_user=False)
    d2 = Diver(display_name="Diver B", canonical_name="diver-b", is_primary_user=False)
    db.add_all([d1, d2])
    db.flush()
    s1 = SessionModel(date=now.date(), location="Pool")
    s2 = SessionModel(date=(now - timedelta(days=1)).date(), location="Pool")
    db.add_all([s1, s2])
    db.flush()
    dive_a = Dive(
        session_id=s1.id,
        dive_code="101B",
        performance="G",
        performance_numeric=3,
        height="1m",
        video_uuid=UUID_A,
        diver_id=d1.id,
        dive_datetime=now - timedelta(hours=1),
    )
    dive_b = Dive(
        session_id=s2.id,
        dive_code="101B",
        performance="G",
        performance_numeric=3,
        height="1m",
        video_uuid=UUID_B,
        diver_id=d2.id,
        dive_datetime=now - timedelta(hours=2),
    )
    dive_dev_only = Dive(
        session_id=s1.id,
        dive_code="201B",
        performance="B",
        performance_numeric=2,
        height="3m",
        video_uuid=UUID_DEV_ONLY,
        diver_id=d1.id,
        dive_datetime=now - timedelta(hours=3),
    )
    dive_unverified = Dive(
        session_id=s1.id,
        dive_code="301B",
        performance="B",
        performance_numeric=2,
        height="3m",
        video_uuid=UUID_UNVERIFIED,
        diver_id=d1.id,
        dive_datetime=now - timedelta(hours=4),
    )
    dive_ambiguous = Dive(
        session_id=s1.id,
        dive_code="401B",
        performance="B",
        performance_numeric=2,
        height="3m",
        video_uuid=UUID_AMBIGUOUS,
        diver_id=d1.id,
        dive_datetime=now - timedelta(hours=5),
    )
    db.add_all([dive_a, dive_b, dive_dev_only, dive_unverified, dive_ambiguous])
    db.flush()

    def _revision(uuid, sha):
        db.add(MediaRevision(video_uuid=uuid, blob_sha256=sha))
        db.add(MediaBlobLocation(blob_sha256=sha, environment="dev", storage_backend="b2", bucket=DEV_BUCKET, object_key=f"blobs/sha256/{sha[:2]}/{sha}.mov", verified=True))

    _revision(UUID_A, SHA_A)
    _revision(UUID_B, SHA_B)
    _revision(UUID_DEV_ONLY, SHA_DEV_ONLY)
    _revision(UUID_UNVERIFIED, SHA_UNVERIFIED)
    _revision(UUID_AMBIGUOUS, SHA_AMBIGUOUS)

    # PROD locations: verified for A and B; DEV-only / unverified / ambiguous
    # cases as named.
    db.add(MediaBlobLocation(blob_sha256=SHA_A, environment="prod", storage_backend="b2", bucket=PROD_BUCKET, object_key=f"blobs/sha256/{SHA_A[:2]}/{SHA_A}.mov", verified=True, verified_at=now))
    db.add(MediaBlobLocation(blob_sha256=SHA_B, environment="prod", storage_backend="b2", bucket=PROD_BUCKET, object_key=f"blobs/sha256/{SHA_B[:2]}/{SHA_B}.mov", verified=True, verified_at=now))
    db.add(MediaBlobLocation(blob_sha256=SHA_UNVERIFIED, environment="prod", storage_backend="b2", bucket=PROD_BUCKET, object_key=f"blobs/sha256/{SHA_UNVERIFIED[:2]}/{SHA_UNVERIFIED}.mov", verified=False))
    db.add(MediaBlobLocation(blob_sha256=SHA_AMBIGUOUS, environment="prod", storage_backend="b2", bucket=PROD_BUCKET, object_key=f"blobs/sha256/{SHA_AMBIGUOUS[:2]}/{SHA_AMBIGUOUS}-r1.mov", verified=True, verified_at=now))
    db.add(MediaBlobLocation(blob_sha256=SHA_AMBIGUOUS, environment="prod", storage_backend="b2", bucket=PROD_BUCKET, object_key=f"blobs/sha256/{SHA_AMBIGUOUS[:2]}/{SHA_AMBIGUOUS}-r2.mov", verified=True, verified_at=now))
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
    return users


@pytest.fixture()
def client(db, flags, fake_presign):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    # Authenticated-by-default client (P5 flags ON via `flags`); the
    # unauthenticated cases build their own fresh client explicitly.
    test_client.post(
        "/api/v1/auth/login",
        json={"email": "user-a@example.test", "password": "correct-horse-battery"},
    )
    yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def flags(monkeypatch):
    """Flip the cached settings singleton to P5-on; restore at teardown."""
    settings = get_settings()
    saved = (
        settings.user_auth_enabled,
        settings.b2_playback_canary_enabled,
        settings.auth_cookie_secure,
        settings.media_playback_presign_ttl_seconds,
    )
    settings.user_auth_enabled = True
    settings.b2_playback_canary_enabled = True
    # Test environment policy (packet §5): the isolated plain-HTTP test
    # environment may use a non-Secure cookie so the test client can carry
    # it; production always runs Secure (asserted explicitly below).
    settings.auth_cookie_secure = False
    settings.media_playback_presign_ttl_seconds = 120
    yield settings
    (
        settings.user_auth_enabled,
        settings.b2_playback_canary_enabled,
        settings.auth_cookie_secure,
        settings.media_playback_presign_ttl_seconds,
    ) = saved


@pytest.fixture()
def fake_presign(monkeypatch):
    calls = []

    def _fake(bucket, object_key, ttl_seconds=None, storage_location_id=None):
        from app.services.b2_presign import PresignResult, clamp_ttl

        effective = clamp_ttl(ttl_seconds)
        calls.append(
            {
                "bucket": bucket,
                "object_key": object_key,
                "ttl": effective,
                "storage_location_id": storage_location_id,
            }
        )
        return PresignResult(
            url=f"https://s3.eu-central-003.backblazeb2.com/{bucket}/{object_key}"
            f"?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature={PRESIGN_MARKER}",
            ttl_seconds=effective,
            storage_location_id=storage_location_id,
        )

    import app.api.v1.media_playback as playback_module

    def _head_ok(bucket, object_key):
        return True

    monkeypatch.setattr(playback_module.b2_presign, "presign_get", _fake)
    monkeypatch.setattr(playback_module.b2_presign, "head_object", _head_ok)
    return calls


def _login(client, email="user-a@example.test", password="correct-horse-battery", ip=None):
    headers = {"X-Forwarded-For": ip} if ip else {}
    return client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}, headers=headers
    )


# ---------------------------------------------------------------- §6/§25 auth


def test_valid_login_sets_hardened_cookie(client):
    settings = get_settings()
    saved = settings.auth_cookie_secure
    settings.auth_cookie_secure = True  # production policy
    try:
        r = _login(client)
    finally:
        settings.auth_cookie_secure = saved
    assert r.status_code == 200
    set_cookie = r.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "SameSite=strict" in set_cookie
    assert "Path=/" in set_cookie
    assert get_settings().auth_cookie_name in set_cookie


def test_invalid_login_generic_response(client):
    wrong_pw = _login(client, password="nope-not-it")
    unknown = _login(client, email="nobody@example.test")
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json() == unknown.json() == {"detail": "Invalid credentials"}


def test_password_hashed_with_argon2id_and_token_hashed_at_rest(client, db):
    r = _login(client)
    assert r.status_code == 200
    creds = db.query(UserCredential).all()
    assert creds
    for cred in creds:
        assert cred.password_hash.startswith("$argon2id$")
        assert cred.password_algo == "argon2id"
    cookie = r.headers.get("set-cookie", "")
    raw_token = cookie.split(";")[0].split("=", 1)[1]
    session_rows = db.query(UserSession).all()
    assert session_rows
    for row in session_rows:
        assert row.token_hash != raw_token
        assert len(row.token_hash) == 64


def test_me_requires_and_accepts_session(client):
    fresh = TestClient(app)
    assert fresh.get("/api/v1/auth/me").status_code == 401
    assert fresh.get("/api/v1/auth/me", cookies={"da_session": "garbage"}).status_code == 401
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == "user-a@example.test"
    assert body["divers"][0]["access_kind"] == "OWNER"


def test_expired_session_denied(client, db):
    _login(client)
    row = db.query(UserSession).order_by(UserSession.id.desc()).first()
    row.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_revoked_session_denied(client, db):
    _login(client)
    row = db.query(UserSession).order_by(UserSession.id.desc()).first()
    row.revoked_at = datetime.utcnow()
    db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_logout_revokes_and_clears(client, db):
    _login(client)
    assert client.get("/api/v1/auth/me").status_code == 200
    out = client.post("/api/v1/auth/logout")
    assert out.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401
    assert all(row.revoked_at is not None for row in db.query(UserSession).all())


def test_login_rotates_token_and_revokes_previous(client, db):
    first = _login(client)
    token1 = first.headers.get("set-cookie", "").split(";")[0]
    second = _login(client)
    token2 = second.headers.get("set-cookie", "").split(";")[0]
    assert token1 != token2
    assert len(db.query(UserSession).filter(UserSession.revoked_at.is_(None)).all()) == 1


# ------------------------------------------------------------- §38 rate limit


def test_login_rate_limit_bounded_window(client, db, monkeypatch):
    # P6 two-tier repair: distinct source IPs so the per-IP cap does not
    # fire before the identifier ceiling is reached.
    id_cap = get_settings().auth_login_max_failures
    for i in range(id_cap):
        ip = f"203.0.113.{i + 1}"
        assert _login(client, password="wrong", ip=ip).status_code == 401
    # Even the CORRECT password is refused while the identifier window is
    # exhausted (bounded, NOT durable).
    fresh = TestClient(app)
    assert _login(fresh).status_code == 429
    # Window roll-off resets: no permanent lockout.
    for row in db.query(LoginAttempt).all():
        row.created_at = datetime.utcnow() - timedelta(
            seconds=get_settings().auth_login_failure_window_seconds + 1
        )
    db.commit()
    assert _login(fresh).status_code == 200


# ------------------------------------------------- §9/§11/§12 ownership + IDOR


def _revision_id(db, sha):
    return db.execute(select(MediaRevision).where(MediaRevision.blob_sha256 == sha)).scalar_one().id


def test_authorized_owner_playback_redirect(client, db, fake_presign, caplog):
    revision_id = _revision_id(db, SHA_A)
    r = client.get(f"/api/v1/media/revisions/{revision_id}/play", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"].startswith("https://s3.eu-central-003.backblazeb2.com/")
    assert r.headers["location"].startswith(f"https://s3.eu-central-003.backblazeb2.com/{PROD_BUCKET}/")
    assert r.headers["cache-control"] == "private, no-store"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert fake_presign[0]["ttl"] == 120
    grant = db.query(MediaPlaybackGrant).one()
    assert grant.outcome == "ALLOWED"
    assert grant.storage_location_id is not None


def test_unauthenticated_playback_denied(client, db, fake_presign):
    revision_id = _revision_id(db, SHA_A)
    fresh = TestClient(app)
    r = fresh.get(f"/api/v1/media/revisions/{revision_id}/play", follow_redirects=False)
    assert r.status_code == 401
    assert not fake_presign


def test_wrong_owner_playback_denied_idor(client, db, fake_presign):
    # user-a (diver-a owner) must never resolve diver-b media (§12).
    revision_b = _revision_id(db, SHA_B)
    r = client.get(f"/api/v1/media/revisions/{revision_b}/play", follow_redirects=False)
    assert r.status_code == 404
    assert "location" not in r.headers
    grant = db.query(MediaPlaybackGrant).one()
    assert grant.outcome == "DENIED"
    assert grant.denial_reason == "no_owner_access"
    assert not fake_presign


def test_unknown_revision_denied(client, db, fake_presign):
    r = client.get("/api/v1/media/revisions/999999/play", follow_redirects=False)
    assert r.status_code == 404
    assert not fake_presign


def test_dev_only_location_denied(client, db, fake_presign):
    revision_id = _revision_id(db, SHA_DEV_ONLY)
    r = client.get(f"/api/v1/media/revisions/{revision_id}/play", follow_redirects=False)
    assert r.status_code == 404
    assert not fake_presign


def test_unverified_prod_location_denied(client, db, fake_presign):
    revision_id = _revision_id(db, SHA_UNVERIFIED)
    r = client.get(f"/api/v1/media/revisions/{revision_id}/play", follow_redirects=False)
    assert r.status_code == 404
    assert not fake_presign


def test_ambiguous_verified_prod_locations_denied(client, db, fake_presign):
    revision_id = _revision_id(db, SHA_AMBIGUOUS)
    r = client.get(f"/api/v1/media/revisions/{revision_id}/play", follow_redirects=False)
    assert r.status_code == 404
    assert not fake_presign


def test_feature_flags_off_fail_closed(client, db):
    settings = get_settings()
    revision_id = _revision_id(db, SHA_A)
    settings.b2_playback_canary_enabled = False
    r = client.get(f"/api/v1/media/revisions/{revision_id}/play", follow_redirects=False)
    assert r.status_code == 404
    settings.user_auth_enabled = False
    settings.b2_playback_canary_enabled = True
    r2 = client.get(f"/api/v1/media/revisions/{revision_id}/play", follow_redirects=False)
    assert r2.status_code in (401, 404)
    login_when_off = client.post(
        "/api/v1/auth/login",
        json={"email": "user-a@example.test", "password": "correct-horse-battery"},
    )
    assert login_when_off.status_code == 404


def test_presigned_url_never_logged_nor_stored(client, db, fake_presign, caplog):
    import logging

    revision_id = _revision_id(db, SHA_A)
    with caplog.at_level(logging.DEBUG, logger="uvicorn"):
        r = client.get(f"/api/v1/media/revisions/{revision_id}/play", follow_redirects=False)
    assert r.status_code == 302
    assert PRESIGN_MARKER in r.headers["location"]
    assert PRESIGN_MARKER not in caplog.text
    assert "X-Amz-Signature" not in caplog.text
    for grant in db.query(MediaPlaybackGrant).all():
        for value in vars(grant).values():
            assert not (isinstance(value, str) and PRESIGN_MARKER in value)


def test_provider_failure_is_explicit_no_fallback(client, db, monkeypatch):
    """§30: authorized user + B2 grant unavailable → explicit backend failure."""
    from app.services.b2_presign import PresignUnavailable
    import app.api.v1.media_playback as playback_module

    def _boom(**kwargs):
        raise PresignUnavailable("credential not configured")

    monkeypatch.setattr(playback_module.b2_presign, "presign_get", _boom)
    revision_id = _revision_id(db, SHA_A)
    r = client.get(f"/api/v1/media/revisions/{revision_id}/play", follow_redirects=False)
    assert r.status_code == 503
    assert r.headers.get("location") is None
    grant = db.query(MediaPlaybackGrant).one()
    assert grant.outcome == "PROVIDER_FAILURE"


def test_ttl_clamped_to_production_ceiling():
    from app.services.b2_presign import clamp_ttl

    assert clamp_ttl(120) == 120
    assert clamp_ttl(300) == 300
    assert clamp_ttl(10_000) == 300
    assert clamp_ttl(-5) == 1


def test_session_authority_never_stores_raw_token(db):
    user = db.query(AppUser).filter_by(email="user-a@example.test").one()
    raw, session = sessions_authority.create_session(
        db, user_id=user.id, ttl_seconds=3600, revoke_existing=False
    )
    stored = db.query(UserSession).filter_by(user_id=user.id).one()
    assert raw != stored.token_hash
    assert stored.token_hash == sessions_authority.hash_session_token(raw)
    resolved = sessions_authority.resolve_session(db, raw)
    assert resolved is not None
    assert sessions_authority.resolve_session(db, raw + "x") is None
