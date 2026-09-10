"""P8 multi-user productionization tests (MEDIA_BACKBONE_P8 §11/§44/§45).

Covers: operator CLI lifecycle (create/disable/enable/reset/bind/unbind/
revoke), the multi-user IDOR matrix across the B2 playback route and the
legacy media endpoints, login rate limiting, Origin validation, the
security audit trail, and the auth metrics endpoint.

Follows the P5/P6 test architecture: isolated in-memory SQLite world,
central policy exercised through the real routes, provider faked.
"""

import json
from argparse import Namespace
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
from app.models.media import MediaCacheEntry
from app.models.media_backbone import MediaBlobLocation, MediaRevision
from app.models.photos_asset import PhotosAsset
from app.models.security_audit_log import SecurityAuditEvent
from app.models.session import Session as SessionModel
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

import scripts.manage_user as manage_user

PROD_BUCKET = "diveanalyzer-prod-media"
DEV_BUCKET = "diveanalyzer-dev-media"
PRESIGN_MARKER = "Fakesigmarker00000000000000000000000000000000000000000000"
PW_A = "correct-horse-battery"

UUID_A = "A1000000-0000-4000-8000-00000000000A"
UUID_B = "B2000000-0000-4000-8000-00000000000B"

import hashlib

SHA_A = hashlib.sha256(UUID_A.encode()).hexdigest()
SHA_B = hashlib.sha256(UUID_B.encode()).hexdigest()


def _ns(**kw):
    return Namespace(**kw)


@pytest.fixture()
def db():
    import shutil as _shutil
    import tempfile as _tempfile

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
            PhotosAsset.__table__,
            MediaCacheEntry.__table__,
            SecurityAuditEvent.__table__,
        ],
    )
    # Real, existing cache file inside a temp cache root: the legacy cache
    # routes resolve the file through get_playable_entry (root + existence).
    tmp_cache_root = _tempfile.mkdtemp(prefix="p8-cache-")
    settings = get_settings()
    saved_cache_root = settings.media_cache_root
    settings.media_cache_root = tmp_cache_root
    cache_file = f"{tmp_cache_root}/x.mp4"
    with open(cache_file, "wb") as fh:
        fh.write(b"\x00" * 64)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    _seed_world(session, cache_file)
    yield session
    settings.media_cache_root = saved_cache_root
    _shutil.rmtree(tmp_cache_root, ignore_errors=True)
    session.close()
    engine.dispose()


def _seed_world(db, cache_file):
    now = datetime.utcnow()
    d1 = Diver(display_name="Diver A", canonical_name="diver-a", is_primary_user=False)
    d2 = Diver(display_name="Diver B", canonical_name="diver-b", is_primary_user=False)
    db.add_all([d1, d2])
    db.flush()
    s1 = SessionModel(date=now.date(), location="Pool")
    s2 = SessionModel(date=(now - timedelta(days=1)).date(), location="Pool")
    db.add_all([s1, s2])
    db.flush()
    dive_a = Dive(session_id=s1.id, dive_code="101B", performance="G",
                  performance_numeric=3, height="1m", video_uuid=UUID_A,
                  diver_id=d1.id, dive_datetime=now - timedelta(hours=1))
    dive_b = Dive(session_id=s2.id, dive_code="101B", performance="G",
                  performance_numeric=3, height="1m", video_uuid=UUID_B,
                  diver_id=d2.id, dive_datetime=now - timedelta(hours=2))
    db.add_all([dive_a, dive_b])
    db.flush()
    for uuid, sha in ((UUID_A, SHA_A), (UUID_B, SHA_B)):
        db.add(MediaRevision(video_uuid=uuid, blob_sha256=sha))
        db.add(MediaBlobLocation(blob_sha256=sha, environment="dev",
                                 storage_backend="b2", bucket=DEV_BUCKET,
                                 object_key=f"blobs/sha256/{sha[:2]}/{sha}.mov",
                                 verified=True))
        db.add(MediaBlobLocation(blob_sha256=sha, environment="prod",
                                 storage_backend="b2", bucket=PROD_BUCKET,
                                 object_key=f"blobs/sha256/{sha[:2]}/{sha}.mov",
                                 verified=True, verified_at=now))
    # One cache entry + photos asset for the legacy-route matrix.
    asset = PhotosAsset(video_uuid=UUID_A, cloud_guid="photos-a")
    db.add(asset)
    db.flush()
    db.add(MediaCacheEntry(photos_asset_id=asset.id, rendition="proxy_360p",
                           status="ready", storage_path=cache_file,
                           content_type="video/mp4", media_key="mk-a",
                           size_bytes=64))
    users = {}
    for email, diver in (("user-a@example.test", d1), ("user-b@example.test", d2)):
        user = AppUser(email=email, display_name=email.split("@")[0])
        db.add(user)
        db.flush()
        db.add(UserCredential(user_id=user.id,
                              password_hash=hash_password(PW_A),
                              password_algo="argon2id"))
        db.add(UserDiverAccess(user_id=user.id, diver_id=diver.id,
                               access_kind="OWNER"))
        users[email] = user
    db.commit()
    return users


@pytest.fixture()
def flags(monkeypatch):
    settings = get_settings()
    saved = (
        settings.user_auth_enabled,
        settings.b2_playback_canary_enabled,
        settings.auth_cookie_secure,
        settings.media_playback_presign_ttl_seconds,
    )
    settings.user_auth_enabled = True
    settings.b2_playback_canary_enabled = True
    settings.auth_cookie_secure = False
    settings.media_playback_presign_ttl_seconds = 120
    yield settings
    (settings.user_auth_enabled, settings.b2_playback_canary_enabled,
     settings.auth_cookie_secure, settings.media_playback_presign_ttl_seconds) = saved


@pytest.fixture()
def fake_presign(monkeypatch):
    import app.api.v1.media_playback as playback_module
    from app.services.b2_presign import PresignResult, clamp_ttl

    def _fake(bucket, object_key, ttl_seconds=None, storage_location_id=None):
        effective = clamp_ttl(ttl_seconds)
        return PresignResult(
            url=f"https://s3.eu-central-003.backblazeb2.com/{bucket}/{object_key}"
                f"?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature={PRESIGN_MARKER}",
            ttl_seconds=effective,
            storage_location_id=storage_location_id,
        )

    monkeypatch.setattr(playback_module.b2_presign, "presign_get", _fake)
    monkeypatch.setattr(playback_module.b2_presign, "head_object",
                        lambda bucket, object_key: True)


@pytest.fixture()
def client(db, flags, fake_presign):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    test_client.post("/api/v1/auth/login",
                     json={"email": "user-a@example.test", "password": PW_A})
    yield test_client
    app.dependency_overrides.clear()


def _client_as(db, flags, fake_presign, email, password=PW_A):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", json={"email": email, "password": password})
    return c, r


REV_A_ID = 1
REV_B_ID = 2
CACHE_ENTRY_ID = 1


# ------------------------------------------------- §11 multi-user IDOR matrix


def test_idor_matrix_across_play_and_legacy_routes(client, db):
    """A owns Diver A, B owns Diver B. Both directions, both families."""
    b_client, _ = _client_as(db, None, None, "user-b@example.test")

    # B2 playback route
    assert client.get(f"/api/v1/media/revisions/{REV_A_ID}/play", follow_redirects=False).status_code == 302
    assert client.get(f"/api/v1/media/revisions/{REV_B_ID}/play", follow_redirects=False).status_code == 404
    assert b_client.get(f"/api/v1/media/revisions/{REV_B_ID}/play", follow_redirects=False).status_code == 302
    assert b_client.get(f"/api/v1/media/revisions/{REV_A_ID}/play", follow_redirects=False).status_code == 404

    # Legacy media endpoints
    assert client.get(f"/api/v1/videos/check/{UUID_A}").status_code == 200
    assert client.get(f"/api/v1/videos/check/{UUID_B}").status_code == 404
    _rb = b_client.get(f"/api/v1/videos/check/{UUID_B}")
    if _rb.status_code != 200:
        from app.models.user_auth import UserDiverAccess as UDA, AppUser as AU
        from app.services.user_access import can_user_access_video as cua
        bu = db.query(AU).filter_by(email="user-b@example.test").one()
        print("DBG decision:", cua(db, bu, UUID_B))
        print("DBG users:", [(u.id, u.email, u.is_active) for u in db.query(AU).all()])
        print("DBG bindings:", [(r.user_id, r.diver_id) for r in db.query(UDA).all()])
        print("DBG dives:", [(dv.id, dv.video_uuid, dv.diver_id) for dv in db.query(Dive).all()])
    assert _rb.status_code == 200
    assert b_client.get(f"/api/v1/videos/check/{UUID_A}").status_code == 404

    # events/viewed + cache play (authorization before bytes/files)
    assert client.post(f"/api/v1/media/events/viewed?entry_id={CACHE_ENTRY_ID}"
                       ).status_code == 200
    assert b_client.post(f"/api/v1/media/events/viewed?entry_id={CACHE_ENTRY_ID}"
                         ).status_code == 404
    assert b_client.get(f"/api/v1/media/cache/{CACHE_ENTRY_ID}/play").status_code == 404

    # Unauthenticated: denied everywhere, no fallback
    anon = TestClient(app)
    assert anon.get(f"/api/v1/media/revisions/{REV_A_ID}/play", follow_redirects=False).status_code == 401
    assert anon.get(f"/api/v1/videos/check/{UUID_A}").status_code == 401
    assert anon.post(f"/api/v1/media/events/viewed?entry_id={CACHE_ENTRY_ID}"
                     ).status_code == 401


def test_unbind_revokes_access_and_rebind_restores(client, db):
    # Unbind B from diver B via CLI
    manage_user.cmd_bind(db, _ns(email="user-b@example.test", diver_id=2,
                                 diver_canonical_name=None, actor_note=None), False)
    b_client, _ = _client_as(db, None, None, "user-b@example.test")
    assert b_client.get(f"/api/v1/media/revisions/{REV_B_ID}/play", follow_redirects=False).status_code == 404
    # Rebind restores access
    manage_user.cmd_bind(db, _ns(email="user-b@example.test", diver_id=2,
                                 diver_canonical_name=None, actor_note=None), True)
    b_client2, _ = _client_as(db, None, None, "user-b@example.test")
    assert b_client2.get(f"/api/v1/media/revisions/{REV_B_ID}/play", follow_redirects=False).status_code == 302


# ------------------------------------------------- §44 disable live semantics


def test_disable_revokes_sessions_and_denies_login(db, flags, fake_presign):
    b_client, r = _client_as(db, None, None, "user-b@example.test")
    assert r.status_code == 200
    assert b_client.get("/api/v1/auth/me").status_code == 200

    manage_user.cmd_set_active(db, _ns(email="user-b@example.test",
                                       actor_note=None), False)

    # Existing session loses access immediately (revoked at disable).
    assert b_client.get("/api/v1/auth/me").status_code == 401
    assert b_client.get(f"/api/v1/media/revisions/{REV_B_ID}/play", follow_redirects=False).status_code == 401
    # New login denied with the generic failure.
    assert b_client.post("/api/v1/auth/login",
                         json={"email": "user-b@example.test", "password": PW_A}
                         ).status_code == 401

    # Enable restores login.
    manage_user.cmd_set_active(db, _ns(email="user-b@example.test",
                                       actor_note=None), True)
    b_client2, r2 = _client_as(db, None, None, "user-b@example.test")
    assert r2.status_code == 200


# ------------------------------------------------- §45 password reset


def test_password_reset_revokes_sessions_and_rotates(db, flags, fake_presign,
                                                     monkeypatch):
    b_client, _ = _client_as(db, None, None, "user-b@example.test")
    assert b_client.get("/api/v1/auth/me").status_code == 200

    monkeypatch.setattr(manage_user, "_prompt_password",
                        lambda confirm=True: "brand-new-password-9")
    manage_user.cmd_reset_password(db, _ns(email="user-b@example.test",
                                           actor_note=None))

    # Old session revoked.
    assert b_client.get("/api/v1/auth/me").status_code == 401
    # Old password fails, new password works.
    assert b_client.post("/api/v1/auth/login",
                         json={"email": "user-b@example.test", "password": PW_A}
                         ).status_code == 401
    b2, r = _client_as(db, None, None, "user-b@example.test",
                       password="brand-new-password-9")
    assert r.status_code == 200


# ------------------------------------------------- rate limiting + origin


def test_login_ip_rate_limit(client):
    ip = "203.0.113.77"
    for _ in range(get_settings().auth_login_ip_max_failures):
        r = client.post("/api/v1/auth/login",
                        json={"email": "user-a@example.test",
                              "password": "wrong"},
                        headers={"X-Forwarded-For": ip})
        assert r.status_code == 401
    r = client.post("/api/v1/auth/login",
                    json={"email": "user-a@example.test", "password": PW_A},
                    headers={"X-Forwarded-For": ip})
    assert r.status_code == 429


def test_foreign_origin_rejected(client):
    r = client.post("/api/v1/auth/login",
                    json={"email": "user-a@example.test", "password": PW_A},
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


# ------------------------------------------------- §25 metrics + §26 audit


def test_auth_metrics_endpoint(client):
    r = client.get("/api/v1/auth/metrics")
    assert r.status_code == 200
    body = r.json()
    for key in ("login_success", "login_failure", "login_rate_limited",
                "session_revocations", "active_sessions_approx"):
        assert key in body
    assert body["active_sessions_approx"] >= 1


def test_security_audit_trail_records_lifecycle_events(db, flags, fake_presign,
                                                       monkeypatch):
    manage_user.cmd_set_active(db, _ns(email="user-b@example.test",
                                       actor_note="p8-test"), False)
    monkeypatch.setattr(manage_user, "_prompt_password",
                        lambda confirm=True: "brand-new-password-9")
    manage_user.cmd_reset_password(db, _ns(email="user-b@example.test",
                                           actor_note=None))
    # Grant requires a real (absent) binding: unbind first, then re-grant.
    manage_user.cmd_bind(db, _ns(email="user-b@example.test", diver_id=2,
                                 diver_canonical_name=None, actor_note=None),
                         False)
    manage_user.cmd_bind(db, _ns(email="user-b@example.test", diver_id=2,
                                 diver_canonical_name=None, actor_note=None),
                         True)

    types = {e.event_type for e in db.query(SecurityAuditEvent).all()}
    assert {"user_disabled", "password_reset", "ownership_granted"} <= types
    for event in db.query(SecurityAuditEvent).all():
        blob = json.dumps({"m": event.metadata_json, "n": event.actor_note})
        assert PW_A not in blob
        assert "brand-new-password" not in blob


def test_revoke_all_sessions_counts(db):
    b_client, _ = _client_as(db, None, None, "user-b@example.test")
    user = db.query(AppUser).filter_by(email="user-b@example.test").one()
    assert sessions_authority.revoke_all_user_sessions(db, user.id) >= 1
    assert sessions_authority.revoke_all_user_sessions(db, user.id) == 0


def test_cli_create_user_end_to_end(db, flags, fake_presign, monkeypatch):
    monkeypatch.setattr(manage_user, "_prompt_password",
                        lambda confirm=True: "fresh-operator-pass-1")
    manage_user.cmd_create_user(
        db, _ns(email="new-athlete@example.test", diver_id=2, diver_id_present=None,
                diver_canonical_name=None, display_name="Athlete",
                disabled=False, actor_note=None)
    )
    c, r = _client_as(db, None, None, "new-athlete@example.test",
                      password="fresh-operator-pass-1")
    assert r.status_code == 200
    # Bound to diver B -> can play revision B, not A
    assert c.get(f"/api/v1/media/revisions/{REV_B_ID}/play", follow_redirects=False).status_code == 302
    assert c.get(f"/api/v1/media/revisions/{REV_A_ID}/play", follow_redirects=False).status_code == 404
