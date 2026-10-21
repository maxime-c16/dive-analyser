"""D5 read fallback on real PostgreSQL (disposable calendar_test_* DB only).

Wired into the CI ``postgres`` tier (``ci/postgres.sh``, before the
calendar wipes). Proves what SQLite cannot:

- absent ``media_derivatives`` on PG raises real SQLSTATE 42P01
  (``UndefinedTable``) inside a SAVEPOINT; ``safe_resolve`` returns
  ``None`` and the SAME session stays usable for legacy queries (no
  25P02 transaction poisoning);
- the 42P01 detector is narrow: an unrelated missing relation (same
  SQLSTATE, different table) propagates instead of masquerading as
  "no derivatives";
- old-schema Library status on PG serves legacy ``ready`` with
  ``derivatives None`` and a fabricated derivative play URL fails
  closed (404, no legacy bytes).

Scope hygiene: each test owns a unique private schema
(``d5_read_<hex>``) reached via ``search_path``. Tables are created
ONLY inside that schema; cleanup is ``DROP SCHEMA ... CASCADE`` on the
owned schema. No public table is dropped, truncated, or deleted; no
global cleanup. Skipped without ``CALENDAR_TEST_DATABASE_URL``.

No B2, no Mac, no media jobs. Both package admission flags stay OFF;
D2 lease-token fencing untouched.
"""

import hashlib
import os
from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

PG_URL = os.environ.get("CALENDAR_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not PG_URL, reason="Disposable PostgreSQL required")


def _guard_url():
    assert PG_URL, "CALENDAR_TEST_DATABASE_URL is required"
    url = make_url(PG_URL)
    assert url.get_backend_name() == "postgresql", "PostgreSQL only"
    assert (url.database or "").startswith("calendar_test_"), (
        "Disposable calendar_test_* database required — refusing anything else"
    )
    return url.set(drivername="postgresql+psycopg2")


def _admin_engine():
    return create_engine(_guard_url(), isolation_level="AUTOCOMMIT")


def _schema_engine(schema: str):
    return create_engine(
        _guard_url(),
        connect_args={"options": f"-csearch_path={schema}"},
    )


def _qualified_models():
    from app.database import Base  # noqa: F401 — registry only
    from app.main import app  # noqa: F401 — register the complete mapper set

    from app.models.dive import Dive  # noqa: F401
    from app.models.diver import Diver  # noqa: F401
    from app.models.media import MediaCacheEntry, MediaJob  # noqa: F401
    from app.models.media_backbone import (  # noqa: F401
        MediaBlob,
        MediaBlobLocation,
        MediaDerivative,
        MediaRevision,
    )
    from app.models.photos_asset import PhotosAsset  # noqa: F401
    from app.models.session import Session as SessionModel  # noqa: F401
    from app.models.user_auth import (  # noqa: F401
        AppUser,
        LoginAttempt,
        MediaPlaybackGrant,
        UserCredential,
        UserDiverAccess,
        UserSession,
    )
    from app.database import Base as _Base

    return _Base


def _create_tables(schema_engine, *, include_ledger: bool, include_locations: bool = True):
    Base = _qualified_models()
    from app.models.media_backbone import (
        MediaBlob,
        MediaBlobLocation,
        MediaDerivative,
        MediaRevision,
    )

    tables = [MediaBlob.__table__, MediaRevision.__table__]
    if include_locations:
        tables.append(MediaBlobLocation.__table__)
    if include_ledger:
        tables.append(MediaDerivative.__table__)
    Base.metadata.create_all(schema_engine, tables=tables)


def _sha(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


@pytest.fixture()
def pg_schema():
    admin = _admin_engine()
    schema = f"d5_read_{uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        yield schema
    finally:
        # Scoped cleanup: only the owned private schema. Never touches
        # public shared tables.
        with admin.connect() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


def _seed_canonical_source(session, video_uuid: str, src: str, prod_bucket: str):
    from app.models.media_backbone import MediaBlob, MediaBlobLocation, MediaRevision

    session.add(MediaBlob(sha256=src, byte_size=10_000_000, width=1920, height=1080))
    session.flush()
    session.add(MediaRevision(video_uuid=video_uuid, blob_sha256=src))
    session.flush()
    session.add(
        MediaBlobLocation(
            blob_sha256=src,
            environment="prod",
            storage_backend="b2",
            bucket=prod_bucket,
            object_key=f"blobs/{src[:8]}.mov",
            verified=True,
            verified_at=datetime.utcnow(),
        )
    )
    session.commit()


def test_missing_ledger_returns_none_and_session_stays_usable(pg_schema):
    """Real 42P01 for absent ledger → None, same session usable."""
    from sqlalchemy.exc import ProgrammingError

    from app.config import get_settings
    from app.models.media_backbone import MediaBlob
    from app.services.derivative_read import safe_resolve_clip_derivatives

    prod_bucket = get_settings().media_backbone_prod_bucket
    schema_engine = _schema_engine(pg_schema)
    try:
        # Pre-D1 shape: source tables exist, ledger table absent.
        _create_tables(schema_engine, include_ledger=False)
        video_uuid = f"D5000000-0000-4000-8000-{uuid4().hex[:12]}"
        src = _sha(f"d5-pg-old-{pg_schema}")

        Session = sessionmaker(bind=schema_engine)
        session = Session()
        try:
            _seed_canonical_source(session, video_uuid, src, prod_bucket)

            # Prove the baseline is a REAL Postgres undefined-table: the
            # direct probe raises SQLSTATE 42P01 naming media_derivatives.
            try:
                session.execute(text("SELECT * FROM media_derivatives LIMIT 1"))
                raise AssertionError("expected UndefinedTable for absent ledger")
            except ProgrammingError as exc:
                assert getattr(exc.orig, "pgcode", None) == "42P01", (
                    f"expected 42P01, got {getattr(exc.orig, 'pgcode', None)!r}"
                )
                assert "media_derivatives" in str(exc.orig).lower()
                session.rollback()

            # The guarded read swallows ONLY this case and returns None.
            assert safe_resolve_clip_derivatives(session, video_uuid) is None

            # Same session stays usable: no 25P02 poisoning. Legacy
            # queries keep serving after the aborted ledger probe.
            assert session.query(MediaBlob).count() == 1
            assert session.execute(text("SELECT 1")).scalar() == 1
        finally:
            session.close()
    finally:
        schema_engine.dispose()


def test_unrelated_missing_table_propagates_not_masked(pg_schema):
    """Same SQLSTATE, different table → must raise, never None."""
    from sqlalchemy.exc import ProgrammingError

    from app.config import get_settings
    from app.services.derivative_read import safe_resolve_clip_derivatives

    prod_bucket = get_settings().media_backbone_prod_bucket
    schema_engine = _schema_engine(pg_schema)
    try:
        # Ledger present, but an unrelated source table is absent: the
        # resolver's source lookup hits 42P01 for media_blob_locations.
        # The narrow detector must NOT mask it as "old schema".
        _create_tables(schema_engine, include_ledger=True, include_locations=False)
        video_uuid = f"D5000000-0000-4000-8000-{uuid4().hex[:12]}"

        Session = sessionmaker(bind=schema_engine)
        session = Session()
        try:
            with pytest.raises(ProgrammingError) as excinfo:
                safe_resolve_clip_derivatives(session, video_uuid)
            assert getattr(excinfo.value.orig, "pgcode", None) == "42P01"
            assert "media_derivatives" not in str(excinfo.value.orig).lower()
            # The savepoint rolled back: the session itself is still
            # usable for an independent statement.
            assert session.execute(text("SELECT 1")).scalar() == 1
        finally:
            session.close()
    finally:
        schema_engine.dispose()


def test_old_schema_library_status_ready_without_derivatives(pg_schema, tmp_path):
    """Old-schema PG status: legacy ready, derivatives None, play 404."""
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.database import get_db
    from app.main import app
    from app.models.dive import Dive
    from app.models.diver import Diver
    from app.models.media import MediaCacheEntry, MediaJob
    from app.models.media_backbone import MediaBlob, MediaBlobLocation, MediaRevision
    from app.models.photos_asset import PhotosAsset
    from app.models.session import Session as SessionModel
    from app.models.user_auth import (
        AppUser,
        LoginAttempt,
        MediaPlaybackGrant,
        UserCredential,
        UserDiverAccess,
        UserSession,
    )
    from app.services.passwords import hash_password

    Base = _qualified_models()
    from app.main import app as _app  # noqa: F401 — register complete mapper set
    from app.models.migration_log import MigrationLog

    schema_engine = _schema_engine(pg_schema)
    try:
        # Old-schema shape in the private schema: legacy status tables
        # plus FK closure (migration_logs for dives), but NO ledger.
        # Scoped to the owned schema; public untouched.
        _all = _qualified_models().metadata.tables
        _need = [
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
            MigrationLog.__table__,
        ]
        Base.metadata.create_all(schema_engine, tables=_need)
        settings = get_settings()
        saved = (
            settings.user_auth_enabled,
            settings.b2_playback_canary_enabled,
            settings.media_cache_root,
            settings.auth_cookie_secure,
        )
        settings.user_auth_enabled = True
        settings.b2_playback_canary_enabled = True
        settings.media_cache_root = str(tmp_path)
        settings.auth_cookie_secure = False
        try:
            prod_bucket = settings.media_backbone_prod_bucket
            video_uuid = f"D5000000-0000-4000-8000-{uuid4().hex[:12]}"
            src = _sha(f"d5-pg-http-{pg_schema}")

            Session = sessionmaker(bind=schema_engine)
            session = Session()
            now = datetime.utcnow()
            diver = Diver(display_name="PG Old D", canonical_name=f"pg-old-{pg_schema[:8]}")
            session.add(diver)
            session.flush()
            sess = SessionModel(date=now.date(), location="Pool")
            session.add(sess)
            session.flush()
            session.add(
                Dive(
                    visibility="private",
                    session_id=sess.id,
                    dive_code="101B",
                    performance="G",
                    performance_numeric=3,
                    height="1m",
                    video_uuid=video_uuid,
                    diver_id=diver.id,
                    dive_datetime=now,
                )
            )
            session.add(MediaBlob(sha256=src, byte_size=1000))
            session.add(MediaRevision(video_uuid=video_uuid, blob_sha256=src))
            session.flush()
            session.add(
                MediaBlobLocation(
                    blob_sha256=src,
                    environment="prod",
                    storage_backend="b2",
                    bucket=prod_bucket,
                    object_key=f"blobs/{src[:8]}.mov",
                    verified=True,
                    verified_at=now,
                )
            )
            asset = PhotosAsset(video_uuid=video_uuid, media_type="video")
            session.add(asset)
            session.flush()
            cached = tmp_path / "pg-old-720p.mp4"
            cached.write_bytes(b"FAKELEGACYVIDEOBYTES" * 10)
            session.add(
                MediaCacheEntry(
                    photos_asset_id=asset.id,
                    media_key=f"pg-old-{pg_schema[:8]}",
                    rendition="proxy_720p",
                    storage_path=str(cached),
                    content_type="video/mp4",
                    size_bytes=200,
                    status="ready",
                )
            )
            user = AppUser(email=f"pg-old-{pg_schema[:8]}@example.test", display_name="pg-old")
            session.add(user)
            session.flush()
            session.add(
                UserCredential(
                    user_id=user.id,
                    password_hash=hash_password("correct-horse-battery"),
                    password_algo="argon2id",
                )
            )
            session.add(UserDiverAccess(user_id=user.id, diver_id=diver.id, access_kind="OWNER"))
            session.commit()

            def override_get_db():
                yield session

            app.dependency_overrides[get_db] = override_get_db
            try:
                test_client = TestClient(app, raise_server_exceptions=False)
                login = test_client.post(
                    "/api/v1/auth/login",
                    json={
                        "email": f"pg-old-{pg_schema[:8]}@example.test",
                        "password": "correct-horse-battery",
                    },
                )
                assert login.status_code == 200, login.text
                r = test_client.get(f"/api/v1/media/{video_uuid}/status")
                assert r.status_code == 200, r.text
                body = r.json()
                assert body["derivatives"] is None
                assert body["status"] == "ready"
                # Direct derivative play with no ledger row fails closed.
                r = test_client.get("/api/v1/media/revisions/999999999/play")
                assert r.status_code == 404, r.text
                assert b"FAKELEGACYVIDEOBYTES" not in r.content
            finally:
                app.dependency_overrides.clear()
                session.close()
        finally:
            (
                settings.user_auth_enabled,
                settings.b2_playback_canary_enabled,
                settings.media_cache_root,
                settings.auth_cookie_secure,
            ) = saved
    finally:
        schema_engine.dispose()
