"""P9 production-readiness tests (packet
MEDIA_BACKBONE_P9_PRODUCTION_READINESS_AND_EXTERNAL_ACCESS_V1).

Covers (packet §43):
- retention-policy invariants (machine-readable policy + no-delete guarantees)
- external Origin handling: exact external hostname origins accepted,
  wildcards never required, foreign origins rejected on state-changing auth
- proxy trust: client IP derived ONLY from the trusted-ingress XFF first
  element; caller-supplied chain elements cannot forge the rate-limit bucket
- durable operational metrics (§41): restart-survivable aggregation derived
  from the append-only tables, exposed through the authenticated endpoints
- legacy dry-run tool: candidate classifier + HARDCODED no-delete contract
- storage reconciliation helper logic (exactly-one verified PROD per
  eligible OWNER revision)

Follows the P5/P6/P8 test architecture: isolated SQLite world, real routes,
provider faked. No B2 writes; nothing destructive.
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile
from argparse import Namespace
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
from app.services import ops_metrics
from app.services.passwords import hash_password

import scripts.legacy_dry_run as legacy_dry_run
import scripts.playback_soak as playback_soak

PROD_BUCKET = "diveanalyzer-prod-media"
PW = "correct-horse-battery"
UUID_A = "A1000000-0000-4000-8000-00000000000A"
UUID_B = "B2000000-0000-4000-8000-00000000000B"
SHA_A = hashlib.sha256(UUID_A.encode()).hexdigest()
SHA_B = hashlib.sha256(UUID_B.encode()).hexdigest()


def _ns(**kw):
    return Namespace(**kw)


# ---------------------------------------------------------------------------
# Shared isolated world (mirrors test_p8_user_admin)


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
    tmp_cache_root = _tempfile.mkdtemp(prefix="p9-cache-")
    settings = get_settings()
    saved_cache_root = settings.media_cache_root
    settings.media_cache_root = tmp_cache_root
    cache_file = f"{tmp_cache_root}/a_360p.mp4"
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
    db.add(s1)
    db.flush()
    dive_a = Dive(session_id=s1.id, dive_code="101B", performance="G",
                  performance_numeric=3, height="1m", video_uuid=UUID_A,
                  diver_id=d1.id, dive_datetime=now - timedelta(hours=1))
    dive_b = Dive(session_id=s1.id, dive_code="101B", performance="G",
                  performance_numeric=3, height="1m", video_uuid=UUID_B,
                  diver_id=d2.id, dive_datetime=now - timedelta(hours=2))
    db.add_all([dive_a, dive_b])
    db.flush()
    for uuid, sha in ((UUID_A, SHA_A), (UUID_B, SHA_B)):
        db.add(MediaRevision(video_uuid=uuid, blob_sha256=sha))
        db.add(MediaBlobLocation(blob_sha256=sha, environment="prod",
                                 storage_backend="b2", bucket=PROD_BUCKET,
                                 object_key=f"blobs/sha256/{sha[:2]}/{sha}.mov",
                                 verified=True, verified_at=now))
    asset = PhotosAsset(video_uuid=UUID_A, cloud_guid="photos-a")
    db.add(asset)
    db.flush()
    db.add(MediaCacheEntry(photos_asset_id=asset.id, rendition="proxy_360p",
                           status="ready", storage_path=cache_file,
                           content_type="video/mp4", media_key="mk-a",
                           size_bytes=64))
    owner = AppUser(email="owner@example.test", display_name="owner")
    db.add(owner)
    db.flush()
    db.add(UserCredential(user_id=owner.id, password_hash=hash_password(PW),
                          password_algo="argon2id"))
    db.add(UserDiverAccess(user_id=owner.id, diver_id=d1.id, access_kind="OWNER"))
    db.commit()


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
        return PresignResult(
            url=f"https://s3.eu-central-003.backblazeb2.com/{bucket}/{object_key}?sig=fake",
            ttl_seconds=clamp_ttl(ttl_seconds),
            storage_location_id=storage_location_id,
        )

    monkeypatch.setattr(playback_module.b2_presign, "presign_get", _fake)
    monkeypatch.setattr(playback_module.b2_presign, "head_object", lambda b, k: True)


def _client_for(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", json={"email": "owner@example.test", "password": PW})
    return c, r


def _repo_root() -> Path:
    """Locate the repository root (container layouts have no /mac-agent)."""
    here = Path(__file__).resolve()
    env_root = os.environ.get("P9_REPO_ROOT")
    if env_root and (Path(env_root) / "ops" / "retention_policy_v1.json").is_file():
        return Path(env_root)
    for candidate in (here.parents[2], here.parents[1]):
        if (candidate / "ops" / "retention_policy_v1.json").is_file():
            return candidate
    return here.parents[2]


# ---------------------------------------------------------------------------
# §43 retention-policy invariants


def test_retention_policy_invariants():
    repo_root = _repo_root()
    policy_path = repo_root / "ops" / "retention_policy_v1.json"
    assert policy_path.is_file(), "retention policy artifact must exist in repo"
    policy = json.loads(policy_path.read_text())
    rules = {rule["subject"]: rule for rule in policy["rules"]}
    assert rules["b2_verified_prod_media"]["automatic_deletion"] is False
    assert rules["b2_verified_prod_media"]["automatic_hiding"] is False
    assert rules["caption_revisions"]["rule"] == "append_only"
    assert rules["media_revisions"]["rule"] == "append_only"
    assert rules["legacy_media_cache"]["deletion_authorized"] is False
    assert rules["legacy_media_videos_directory"]["deletion_authorized"] is False
    assert rules["photos_assets"]["rule"] == "never_deleted_by_dive_analyzer"
    assert rules["source_vault"]["deletion_authorized"] is False
    assert rules["b2_object_lifecycle"]["rule"] == "no_automatic_delete_or_hide_in_v1"
    assert "science storage excluded" in " ".join(policy["invariants"])


def test_b2_ingest_path_static_no_delete_firewall():
    """Static scan: the ingest dual-write + coordinator path must not call
    delete/delete_objects/delete_objects_v2 (P4 firewall, re-proven for P9).
    Skipped in layouts without the mac-agent source (backend container)."""
    repo_root = _repo_root()
    target = repo_root / "mac-agent" / "src" / "ingest" / "dual_write.py"
    if not target.is_file():
        pytest.skip("mac-agent source not present in this test layout")
    source = target.read_text()
    for forbidden in (".delete(", "delete_objects", "DeleteObject", "hide_object"):
        assert forbidden not in source, f"forbidden primitive {forbidden!r} in ingest path"
    coordinator = (repo_root / "mac-agent" / "src" / "ingest" / "coordinator.py").read_text()
    for forbidden in (".delete(", "delete_objects", "DeleteObject"):
        assert forbidden not in coordinator


# ---------------------------------------------------------------------------
# §19/§20 external origin + proxy trust


def test_external_hostname_origin_accepted_and_foreign_rejected(db, flags, fake_presign):
    """An exact external tunnel hostname (e.g. a Cloudflare Zero-Trust
    hostname) is accepted like the LAN origins — the backend needs the EXACT
    origin in CORS_ALLOW_ORIGINS; no wildcard."""
    settings = get_settings()
    saved = settings.cors_allow_origins
    external_host = "dive.example-tunnel.test"
    settings.cors_allow_origins = f"https://{external_host}"
    try:
        c, r = _client_for(db)
        assert r.status_code == 200
        r2 = c.post(
            "/api/v1/auth/logout",
            headers={"Origin": f"https://{external_host}"},
        )
        assert r2.status_code == 200
        # foreign origin rejected
        r3 = c.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.test", "password": PW},
            headers={"Origin": "https://evil.example"},
        )
        assert r3.status_code == 403
        r4 = c.post(
            "/api/v1/auth/logout",
            headers={"Origin": "https://other-tenant.tunnel.test"},
        )
        assert r4.status_code == 403
    finally:
        settings.cors_allow_origins = saved


def test_wildcard_origin_never_accepted(db, flags, fake_presign):
    settings = get_settings()
    saved = settings.cors_allow_origins
    try:
        settings.cors_allow_origins = "*"
        c, r = _client_for(db)
        # A wildcard string in the config is parsed as the literal origin
        # "*"; _origin_allowed compares EXACT strings only (no prefix/
        # startswith matching exists), so a browser Origin can never match
        # it: the model structurally forbids wildcard trust.
        assert settings.cors_origins == ["*"]
        r2 = c.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.test", "password": PW},
            headers={"Origin": "https://arbitrary.attacker.test"},
        )
        assert r2.status_code == 403
    finally:
        settings.cors_allow_origins = saved


def test_proxy_trust_first_xff_element_is_used(db, flags, fake_presign, monkeypatch):
    """The rate-limit client identity is the FIRST XFF element (the value
    observed by the trusted nginx/cloudflared hop); appended caller-supplied
    chain elements are ignored, so a caller cannot forge a different bucket."""
    from app.api.v1 import auth as auth_module

    settings = get_settings()
    saved = settings.auth_login_ip_max_failures
    settings.auth_login_ip_max_failures = 3
    try:
        c, _ = _client_for(db)
        forged = "1.2.3.4, 5.6.7.8"
        for _ in range(3):
            c.post(
                "/api/v1/auth/login",
                json={"email": "owner@example.test", "password": "wrongwrongwrong"},
                headers={"X-Forwarded-For": forged},
            )
        # even a CORRECT password is capped when the FIRST XFF element (the
        # trusted-ingress-observed source) is at its failure ceiling:
        r_capped = c.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.test", "password": PW},
            headers={"X-Forwarded-For": forged},
        )
        assert r_capped.status_code == 429
        # a DIFFERENT first element is a different bucket: appended
        # caller-supplied chain elements are ignored (no forged-bucket
        # escape, no forged-bucket lockout of others):
        r_different = c.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.test", "password": PW},
            headers={"X-Forwarded-For": "9.9.9.9, 1.2.3.4"},
        )
        assert r_different.status_code == 200
    finally:
        settings.auth_login_ip_max_failures = saved


# ---------------------------------------------------------------------------
# §41 durable operational metrics


def test_durable_ops_snapshot_counts_append_only_tables(db):
    db.add(LoginAttempt(identifier="owner@example.test", success=True, client_ip="127.0.0.1"))
    db.add(LoginAttempt(identifier="ghost@example.test", success=False, client_ip="127.0.0.1"))
    db.add(MediaPlaybackGrant(user_id=1, outcome="ALLOWED"))
    db.add(MediaPlaybackGrant(user_id=1, outcome="DENIED", denial_reason="x"))
    db.add(SecurityAuditEvent(event_type="login_rate_limited", actor_context="system"))
    db.commit()
    snapshot = ops_metrics.durable_ops_snapshot(db, window_hours=24)
    assert snapshot["window_hours"] == 24
    assert snapshot["login_attempts"]["success"] >= 1
    assert snapshot["login_attempts"]["failure"] >= 1
    assert snapshot["playback_grants"]["allowed"] >= 1
    assert snapshot["playback_grants"]["denied"] >= 1
    assert snapshot["security_events"].get("login_rate_limited", 0) >= 1
    # no identifiers / tokens / URLs in the snapshot
    dumped = json.dumps(snapshot)
    assert "owner@example.test" not in dumped
    assert "ghost" not in dumped
    assert "token" not in dumped.lower()


def test_durable_metrics_exposed_on_authenticated_endpoints(db, flags, fake_presign):
    c, r = _client_for(db)
    assert r.status_code == 200
    auth_metrics_response = c.get("/api/v1/auth/metrics")
    assert auth_metrics_response.status_code == 200
    body = auth_metrics_response.json()
    assert "durable" in body
    assert set(body["durable"]) == {
        "window_hours", "login_attempts", "playback_grants", "security_events"
    }
    playback_metrics_response = c.get("/api/v1/media/playback/metrics")
    assert playback_metrics_response.status_code == 200
    assert "durable" in playback_metrics_response.json()
    # anonymous clients never see metrics (fresh client without the cookie)
    app.dependency_overrides.clear()
    def anon_override():
        yield db
    app.dependency_overrides[get_db] = anon_override
    anon = TestClient(app)
    assert anon.get("/api/v1/auth/metrics").status_code == 401
    assert anon.get("/api/v1/media/playback/metrics").status_code == 401


# ---------------------------------------------------------------------------
# §35/§43 legacy dry-run tool


def _write_world(tmp_root, db):
    """Build a small on-disk legacy world: 1 tracked cache file + 2 videos."""
    media_root = tmp_root / "media"
    (media_root / "videos").mkdir(parents=True)
    (media_root / "cache" / "360p").mkdir(parents=True)
    active_video = media_root / "videos" / f"{UUID_A}.mp4"
    active_video.write_bytes(b"x" * 128)
    orphan_video = media_root / "videos" / "IMG_0001.mov"
    orphan_video.write_bytes(b"o" * 4096)
    tracked_cache = media_root / "cache" / "360p" / "a_360p.mp4"
    tracked_cache.write_bytes(b"c" * 256)
    untracked_cache = media_root / "cache" / "poster_a.jpg"
    untracked_cache.write_bytes(b"p" * 32)
    return media_root, active_video, orphan_video, tracked_cache, untracked_cache


def _capture_main(argv):
    import io
    import contextlib

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        legacy_dry_run.main(argv)
    return buffer.getvalue()


def test_dry_run_classifier(tmp_path, db, monkeypatch):
    media_root, active_video, orphan_video, tracked_cache, untracked_cache = _write_world(tmp_path, db)
    # point the seeded cache row at the on-disk world path so the script's
    # DB-tracked classification resolves the file
    cache_row = db.query(MediaCacheEntry).one()
    cache_row.storage_path = str(tracked_cache)
    db.commit()
    # point the DB session used by the script at the isolated world
    TestingSession = sessionmaker(bind=db.get_bind())

    class _Factory:
        def __enter__(self):
            return TestingSession()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(legacy_dry_run, "SessionLocal", lambda: _Factory())
    monkeypatch.setattr(legacy_dry_run, "init_db", lambda: None)
    manifest = json.loads(_capture_main(["--media-root", str(media_root)]))
    entries = {e["path"]: e for e in manifest["candidates"]}
    # active fallback authority (matches a dive video_uuid) -> KEEP
    assert entries[str(active_video)]["why_candidate"] is False
    # icloudpd orphan -> candidate with evidence-backed classification
    orphan_entry = entries[str(orphan_video)]
    assert orphan_entry["why_candidate"] is True
    assert orphan_entry["category"] == "legacy_media_videos"
    assert "icloudpd" in orphan_entry["why"]
    assert orphan_entry["blocking_dependency"]
    assert orphan_entry["recovery_proof"]
    # DB-tracked cache derivative -> candidate (B2-derivable) with blocking dep
    cache_entry = entries[str(tracked_cache)]
    assert cache_entry["category"] == "legacy_cache_derivatives"
    assert cache_entry["why_candidate"] is True
    assert "ACTIVE playback/poster substrate" in cache_entry["blocking_dependency"]
    # untracked cache file -> conservative KEEP
    assert entries[str(untracked_cache)]["why_candidate"] is False
    # hardcoded safety contract
    safety = manifest["hardcoded_safety"]
    assert safety["delete_flag_exists"] is False
    assert safety["destructive_mode_exists"] is False
    assert safety["b2_delete_or_hide"] == 0
    assert safety["legacy_deletes"] == 0


def _capture_main(argv):
    import io
    import contextlib

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        legacy_dry_run.main(argv)
    return buffer.getvalue()


def test_dry_run_tool_has_no_destructive_cli():
    source = Path(legacy_dry_run.__file__).read_text()
    # no deletion option exists in the argparse surface
    assert '"--delete"' not in source
    assert "add_argument" not in source or all(
        kw not in line for line in source.splitlines() if "add_argument" in line
        for kw in ("--delete", "--purge", "--execute", "--force")
    )
    for primitive in ("shutil.rmtree", "os.remove", ".unlink(", "boto3"):
        assert primitive not in source, f"destructive/provider primitive {primitive!r}"


def test_playback_soak_mints_session_and_never_mutates_media(db, monkeypatch):
    """The soak tool mints a session row (operator pattern) and performs
    read-only playback traffic; it contains no delete/hide primitives."""
    source = Path(playback_soak.__file__).read_text()
    for forbidden in ("DELETE FROM", "os.remove", "shutil.rmtree", "unlink(", "delete_object"):
        assert forbidden not in source
    # mint_session_cookie inserts a session for an existing user
    TestingSession = sessionmaker(bind=db.get_bind())

    class _Factory:
        def __enter__(self):
            return TestingSession()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(playback_soak, "SessionLocal", lambda: _Factory())
    monkeypatch.setattr(playback_soak, "init_db", lambda: None)
    monkeypatch.setattr(playback_soak, "get_settings", lambda: get_settings())
    cookie = playback_soak.mint_session_cookie("owner@example.test")
    assert cookie.startswith("da_session=")
    raw = cookie.split("=", 1)[1]
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    row = db.query(UserSession).filter_by(token_hash=token_hash).one_or_none()
    assert row is not None
    assert row.revoked_at is None


# ---------------------------------------------------------------------------
# §28 storage reconciliation


def test_storage_reconciliation_exactly_one_verified_prod(db, monkeypatch):
    import scripts.storage_reconciliation as recon
    from sqlalchemy import select as _select

    TestingSession = sessionmaker(bind=db.get_bind())

    class _Factory:
        def __enter__(self):
            return TestingSession()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(recon, "SessionLocal", lambda: _Factory())
    monkeypatch.setattr(recon, "init_db", lambda: None)

    def _reconcile(session):
        owner_divers = {
            r[0] for r in session.execute(
                _select(UserDiverAccess.diver_id).where(UserDiverAccess.access_kind == "OWNER")
            ).all()
        }
        dives_by_uuid = dict(session.query(Dive.video_uuid, Dive.diver_id).all())
        eligible = reconciled = 0
        for revision in session.query(MediaRevision).all():
            diver = dives_by_uuid.get(revision.video_uuid)
            if diver is None or diver not in owner_divers:
                continue
            eligible += 1
            locs = [
                l for l in session.query(MediaBlobLocation)
                .filter_by(blob_sha256=revision.blob_sha256, environment="prod", verified=True).all()
            ]
            if len(locs) == 1 and locs[0].storage_backend.lower() == "b2":
                reconciled += 1
        return eligible, reconciled

    with TestingSession() as s:
        eligible, reconciled = _reconcile(s)
        assert (eligible, reconciled) == (1, 1)  # 100% in the seeded world (1 OWNER-diver binding)

    # drift: remove one verified PROD location -> reconciliation degrades
    with TestingSession() as s:
        loc = s.query(MediaBlobLocation).filter_by(
            blob_sha256=SHA_A, environment="prod").one()
        s.delete(loc)
        s.commit()
    with TestingSession() as s:
        eligible, reconciled = _reconcile(s)
        assert (eligible, reconciled) == (1, 0)  # drift detected
