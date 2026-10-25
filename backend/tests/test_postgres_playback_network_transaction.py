"""Real PG idle-transaction timeout during playback HEAD; private schema only."""
import os
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import OperationalError

from tests.test_derivative_read_d5 import flags, _seed_world, UUID_FULL
from tests.test_postgres_derivative_read_d5 import pg_schema, _schema_engine, _qualified_models

from app.database import get_db
from app.main import app
from app.models.media_backbone import MediaRevision
from app.models.user_auth import MediaPlaybackGrant

pytestmark = pytest.mark.skipif(not os.environ.get("CALENDAR_TEST_DATABASE_URL"), reason="Disposable PostgreSQL required")

@pytest.mark.parametrize("derived", [False, True])
def test_slow_head_survives_real_pg_idle_timeout(pg_schema, flags, tmp_path, monkeypatch, derived):
    import app.api.v1.media_playback as playback
    from app.services.b2_presign import PresignResult

    engine = _schema_engine(pg_schema)
    base = _qualified_models()
    # Same compact synthetic world as the SQLite route suite. Every table
    # is inside the unique owned search_path, never public/prod.
    # Use the same registered models as the synthetic route fixtures.
    import tests.test_derivative_read_d5 as d5
    models = [d5.SessionModel, d5.Dive, d5.Diver, d5.MediaBlob, d5.MediaBlobLocation,
              d5.MediaRevision, d5.MediaDerivative, d5.PhotosAsset, d5.MediaCacheEntry,
              d5.MediaJob, d5.EvaluationRequest, d5.AppUser, d5.UserCredential,
              d5.UserSession, d5.UserDiverAccess, d5.LoginAttempt,
              d5.MediaPlaybackGrant, d5.SecurityAuditEvent]
    tables = {model.__table__ for model in models}
    pending = list(tables)
    while pending:
        for fk in pending.pop().foreign_keys:
            dependency = fk.column.table
            if dependency not in tables:
                tables.add(dependency)
                pending.append(dependency)
    base.metadata.create_all(engine, tables=list(tables))
    db = sessionmaker(bind=engine)()
    saved_overrides = dict(app.dependency_overrides)
    monkeypatch.setattr(flags, "media_cache_root", str(tmp_path))
    try:
        _seed_world(db, tmp_path)
        app.dependency_overrides[get_db] = lambda: db

        # Arm the original 100ms timeout at the provider boundary, after
        # authorization/derivative SQL. The hosted failure was before HEAD:
        # runner scheduling exceeded 100ms between preflight SQL statements.
        # SET LOCAL remains active if the handler forgets its rollback.
        storage_identity = playback._storage_identity
        armed = False
        def identity_and_arm(revision, location):
            nonlocal armed
            identity = storage_identity(revision, location)
            if not armed:
                db.execute(text("SET LOCAL idle_in_transaction_session_timeout = '100ms'"))
                armed = True
            return identity
        monkeypatch.setattr(playback, "_storage_identity", identity_and_arm)

        def slow_head(**kwargs):
            # The provider call exceeds the real request-connection timeout.
            # No mocked SQL error stands in for PostgreSQL enforcement.
            assert not db.in_transaction(), "provider I/O retained the request transaction"
            assert armed
            # A real control transaction proves PostgreSQL enforces the same
            # 100ms timeout during this HEAD; no retries or relaxed threshold.
            with engine.connect() as control:
                control.execute(text("SET LOCAL idle_in_transaction_session_timeout = '100ms'"))
                control.execute(text("SELECT 1"))
                time.sleep(0.35)
                with pytest.raises(OperationalError):
                    control.execute(text("SELECT 1"))
                control.rollback()

        monkeypatch.setattr(playback.b2_presign, "head_object", slow_head)
        monkeypatch.setattr(playback.b2_presign, "presign_get", lambda **kwargs:
                            PresignResult(url="https://storage.example.test/object", ttl_seconds=120,
                                          storage_location_id=kwargs["storage_location_id"]))
        with TestClient(app) as client:
            login = client.post("/api/v1/auth/login", json={"email": "user-a@example.test", "password": "correct-horse-battery"})
            assert login.status_code == 200
            semantic = "derived_light" if derived else "photos_edited_rendition"
            revision = db.query(MediaRevision).filter_by(video_uuid=UUID_FULL, rendition_semantics=semantic).one()
            revision_id = revision.id
            db.rollback()
            response = client.get(f"/api/v1/media/revisions/{revision_id}/play", follow_redirects=False)
            assert response.status_code == 302, response.text
            assert db.query(MediaPlaybackGrant).filter_by(outcome="ALLOWED", media_revision_id=revision_id).count() == 1
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved_overrides)
        db.close()
        engine.dispose()
