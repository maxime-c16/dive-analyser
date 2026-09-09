"""Media backbone P4 backend tests: authenticated commit endpoint.

Covers packet MEDIA_BACKBONE_P4_PRODUCTION_DUAL_WRITE_CANARY_V1 §11-§13,
§26, §29: API-key authentication, environment/bucket firewall, idempotence
(including lost-response retry), validation fail-closed behavior, and
environment-scoped DB rows.
"""

import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import (
    CaptionRevision,
    IngestObjectState,
    MediaBlob,
    MediaRevision,
)

TEST_API_KEY = "test-api-key-1234567890abcdef"
PROD_BUCKET = "diveanalyzer-prod-media"
DEV_BUCKET = "diveanalyzer-dev-media"

MEDIA_SHA = hashlib.sha256(b"p4-canary-media-bytes").hexdigest()
CAPTION_RAW = "107B | 7.5 | H:3 | p4-canary-caption"
CAPTION_SHA = hashlib.sha256(CAPTION_RAW.encode("utf-8")).hexdigest()
VIDEO_UUID = "B4C5D6E7-F809-0A1B-2C3D-4E5F60718293"


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Only the backbone tables: the full metadata cannot be created on sqlite
    # (postgres-UUID analysis models — a pre-existing, documented limitation).
    Base.metadata.create_all(
        engine,
        tables=[
            MediaBlob.__table__,
            MediaRevision.__table__,
            CaptionRevision.__table__,
            IngestObjectState.__table__,
        ],
    )
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    # No context manager: entering TestClient triggers the postgres lifespan
    # (init_db) which must not run against the sqlite test database.
    test_client = TestClient(app, headers={"X-API-Key": TEST_API_KEY})
    yield test_client
    app.dependency_overrides.clear()


def _body(**overrides):
    body = {
        "video_uuid": VIDEO_UUID,
        "ingest_impl_version": "media_backbone_v1",
        "rendition_semantics": "photos_edited_rendition",
        "caption_raw": CAPTION_RAW,
        "caption_sha256": CAPTION_SHA,
        "caption_provider": "current_stable_caption_provider",
        "blob_sha256": MEDIA_SHA,
        "byte_size": 2048,
        "object_key": f"blobs/sha256/{MEDIA_SHA[:2]}/{MEDIA_SHA}.mov",
        "storage_backend": "b2",
        "bucket": PROD_BUCKET,
        "remote_verified": True,
        "environment": "prod",
        "codec": "hevc",
        "width": 1920,
        "height": 1080,
        "duration_seconds": 9.288,
        "photos_edit_fingerprint": "fp2:test-fingerprint",
        "source_provenance": {"hasadjustments": True},
        "shadow_provider": None,
        "shadow_raw": None,
        "shadow_sha256": None,
        "shadow_available": None,
        "parser_version": "grammar_v1",
        "parsed_json": {"dive_code": "107B"},
    }
    body.update(overrides)
    return body


BACKBONE_COUNTS = (
    (MediaBlob, "blob"),
    (MediaRevision, "media_revision"),
    (CaptionRevision, "caption_revision"),
    (IngestObjectState, "ingest_state"),
)


def _row_counts(db):
    return {name: len(db.execute(select(model)).scalars().all()) for model, name in BACKBONE_COUNTS}


def test_commit_rejects_missing_and_invalid_api_key(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        anonymous = TestClient(app)
        response = anonymous.post("/api/v1/media/backbone/commit", json=_body())
        assert response.status_code == 401
        wrong = TestClient(app, headers={"X-API-Key": "wrong-key"})
        response = wrong.post("/api/v1/media/backbone/commit", json=_body())
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_prod_commit_creates_environment_scoped_rows(client, db):
    response = client.post("/api/v1/media/backbone/commit", json=_body())
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["environment"] == "prod"
    assert result["blob_sha256"] == MEDIA_SHA
    assert result["blob_existed"] is False
    assert result["media_revision_existed"] is False
    assert result["caption_revision_existed"] is False
    counts = _row_counts(db)
    assert counts == {
        "blob": 1,
        "media_revision": 1,
        "caption_revision": 1,
        "ingest_state": 1,
    }
    state = db.execute(select(IngestObjectState)).scalars().one()
    assert state.environment == "prod"
    blob = db.execute(select(MediaBlob)).scalars().one()
    assert blob.bucket == PROD_BUCKET
    assert blob.storage_backend == "b2"


def test_idempotent_replay_and_lost_response_retry(client, db):
    first = client.post("/api/v1/media/backbone/commit", json=_body())
    assert first.status_code == 200
    # Simulated lost response / network retry: the SAME identical request is
    # re-sent. Must return the same logical result and create zero duplicates.
    for _ in range(3):
        retry = client.post("/api/v1/media/backbone/commit", json=_body())
        assert retry.status_code == 200
        result = retry.json()
        assert result["blob_sha256"] == first.json()["blob_sha256"]
        assert result["blob_existed"] is True
        assert result["media_revision_existed"] is True
        assert result["caption_revision_existed"] is True
        assert result["media_revision_id"] == first.json()["media_revision_id"]
        assert result["caption_revision_id"] == first.json()["caption_revision_id"]
    assert _row_counts(db) == {
        "blob": 1,
        "media_revision": 1,
        "caption_revision": 1,
        "ingest_state": 1,
    }


def test_caption_hash_mismatch_rejected(client):
    body = _body(caption_sha256="0" * 64)
    response = client.post("/api/v1/media/backbone/commit", json=body)
    assert response.status_code == 422
    assert "caption_sha256" in response.json()["detail"].lower() or "caption" in response.json()["detail"].lower()


def test_unverified_commit_rejected(client):
    response = client.post("/api/v1/media/backbone/commit", json=_body(remote_verified=False))
    assert response.status_code == 422


def test_environment_bucket_firewall(client):
    # PROD bucket claimed under dev environment -> rejected
    response = client.post("/api/v1/media/backbone/commit", json=_body(environment="dev"))
    assert response.status_code == 422
    assert "allowlisted" in response.json()["detail"]
    # DEV bucket claimed under prod environment -> rejected
    response = client.post(
        "/api/v1/media/backbone/commit",
        json=_body(
            environment="prod",
            bucket=DEV_BUCKET,
            blob_sha256=hashlib.sha256(b"dev-bytes").hexdigest(),
        ),
    )
    assert response.status_code == 422
    # unknown bucket -> rejected
    response = client.post(
        "/api/v1/media/backbone/commit",
        json=_body(bucket="diveanalyzer-unknown-media"),
    )
    assert response.status_code == 422
    # dev environment with the allowlisted dev bucket -> accepted (0 dup risk:
    # distinct caption/sha)
    dev_sha = hashlib.sha256(b"dev-api-test-bytes").hexdigest()
    dev_caption = "107B | 7.5 | dev-api-row"
    response = client.post(
        "/api/v1/media/backbone/commit",
        json=_body(
            environment="dev",
            bucket=DEV_BUCKET,
            blob_sha256=dev_sha,
            object_key=f"blobs/sha256/{dev_sha[:2]}/{dev_sha}.mov",
            caption_raw=dev_caption,
            caption_sha256=hashlib.sha256(dev_caption.encode("utf-8")).hexdigest(),
        ),
    )
    assert response.status_code == 200, response.text
    assert response.json()["environment"] == "dev"


def test_object_key_must_match_blob_sha(client):
    other_sha = hashlib.sha256(b"other-bytes").hexdigest()
    response = client.post(
        "/api/v1/media/backbone/commit",
        json=_body(object_key=f"blobs/sha256/{other_sha[:2]}/{other_sha}.mov"),
    )
    assert response.status_code == 422
    assert "content-addressed" in response.json()["detail"]


def test_malformed_identifiers_rejected(client):
    for override in (
        {"video_uuid": "not-a-uuid"},
        {"blob_sha256": "XYZ"},
        {"caption_sha256": "XYZ"},
        {"environment": "staging"},
        {"storage_backend": "r2"},
        {"byte_size": 0},
    ):
        response = client.post("/api/v1/media/backbone/commit", json=_body(**override))
        assert response.status_code == 422, override
