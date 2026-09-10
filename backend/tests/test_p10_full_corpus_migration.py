"""P10 full-corpus migration backend tests.

Packet MEDIA_BACKBONE_P10_OVERNIGHT_FULL_DIVE_ANALYZER_MIGRATION_V1.

Covers:
- media-only commit (§23): verified media bytes + truthful MediaRevision
  baseline committed WITHOUT a fabricated CaptionRevision; ledger state
  MEDIA_VERIFIED_METADATA_PENDING; caption data forbidden in that mode;
- media-only rejection when no reason is given / caption data is attached;
- normal caption commit unchanged;
- the P10 domain-driven inventory endpoint: dives.video_uuid is the
  inventory boundary (NOT media_revisions), duplicate-free dedupe,
  backbone facts attached per distinct identity;
- storage migration must not create UserDiverAccess rows (§4).
"""

import hashlib
from datetime import datetime

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
    MediaBlobLocation,
    MediaRevision,
)
from app.models.user_auth import UserDiverAccess

try:
    from app.models.dive import Dive
except Exception:  # pragma: no cover - depends on legacy model importability
    Dive = None

TEST_API_KEY = "test-api-key-1234567890abcdef"
PROD_BUCKET = "diveanalyzer-prod-media"


MEDIA_SHA = hashlib.sha256(b"p10-media-bytes").hexdigest()
MEDIA_SHA2 = hashlib.sha256(b"p10-media-bytes-2").hexdigest()
CAPTION_RAW = "103B | 7.5 | H:3 | p10-caption"
CAPTION_SHA = hashlib.sha256(CAPTION_RAW.encode("utf-8")).hexdigest()
VIDEO_UUID = "D766186E-E867-456D-BC7A-D9313B180954"
VIDEO_UUID2 = "E6ACBCF6-9801-439B-937D-852718BA8815"
OBJECT_KEY = f"blobs/sha256/{MEDIA_SHA[:2]}/{MEDIA_SHA}.mov"
OBJECT_KEY2 = f"blobs/sha256/{MEDIA_SHA2[:2]}/{MEDIA_SHA2}.mov"


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
        UserDiverAccess.__table__,
    ]
    if Dive is not None:
        try:
            # Probe sqlite compatibility of the legacy Dive model; skip
            # domain-inventory coverage if the model cannot exist on sqlite.
            Dive.__table__.create(engine)
            tables.append(Dive.__table__)
        except Exception:
            pass
    Base.metadata.create_all(engine, tables=tables)
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
    test_client = TestClient(app, headers={"X-API-Key": TEST_API_KEY})
    yield test_client
    app.dependency_overrides.clear()


def _media_only_document(
    sha=MEDIA_SHA,
    object_key=OBJECT_KEY,
    video_uuid=VIDEO_UUID,
    byte_size=4096,
):
    return {
        "payload": {
            "video_uuid": video_uuid,
            "ingest_impl_version": "media_backbone_p10_full_corpus_v1",
            "rendition_semantics": "photos_edited_rendition",
            "caption": None,
            "blob": {
                "sha256": sha,
                "byte_size": byte_size,
                "object_key": object_key,
                "storage_backend": "b2",
                "bucket": PROD_BUCKET,
            },
            "remote_verified": True,
        },
        "extra": {
            "environment": "prod",
            "media_only": True,
            "media_only_reason": "caption authority temporarily unresolved",
            "source_provenance": {"p10_domain_baseline": True},
        },
    }


def test_media_only_commit_creates_media_without_caption(client, db):
    response = client.post(
        "/api/v1/media/backbone/commit", json=_media_only_document()
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["media_only"] is True
    assert result["caption_revision_id"] is None
    assert result["caption_revision_existed"] is False
    assert result["ledger_state"] == "MEDIA_VERIFIED_METADATA_PENDING"
    assert db.query(MediaBlob).count() == 1
    assert db.query(MediaRevision).count() == 1
    assert db.query(CaptionRevision).count() == 0
    ledger = db.query(IngestObjectState).one()
    assert ledger.state == "MEDIA_VERIFIED_METADATA_PENDING"


def test_media_only_commit_requires_reason(client):
    doc = _media_only_document()
    doc["extra"]["media_only_reason"] = ""
    response = client.post("/api/v1/media/backbone/commit", json=doc)
    assert response.status_code == 422
    assert "media_only_reason" in response.json()["detail"]


def test_media_only_commit_rejects_caption_data(client):
    doc = _media_only_document()
    doc["payload"]["caption"] = {
        "raw": CAPTION_RAW,
        "sha256": CAPTION_SHA,
        "provider": "x",
    }
    response = client.post("/api/v1/media/backbone/commit", json=doc)
    assert response.status_code == 422


def test_media_only_commit_idempotent(client, db):
    first = client.post(
        "/api/v1/media/backbone/commit", json=_media_only_document()
    )
    assert first.status_code == 200
    second = client.post(
        "/api/v1/media/backbone/commit", json=_media_only_document()
    )
    assert second.status_code == 200
    result = second.json()
    assert result["blob_existed"] is True
    assert result["blob_location_existed"] is True
    assert result["media_revision_existed"] is True
    assert db.query(MediaBlob).count() == 1
    assert db.query(MediaBlobLocation).count() == 1
    assert db.query(IngestObjectState).count() == 1


def test_caption_commit_path_unchanged(client, db):
    doc = _media_only_document()
    doc["extra"] = {"environment": "prod"}
    doc["payload"]["caption"] = {
        "raw": CAPTION_RAW,
        "sha256": CAPTION_SHA,
        "provider": "osxphotos_description_stable",
    }
    response = client.post("/api/v1/media/backbone/commit", json=doc)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["media_only"] is False
    assert result["ledger_state"] == "DB_COMMITTED"
    assert result["caption_revision_id"] is not None
    assert db.query(CaptionRevision).count() == 1


def test_media_only_commit_does_not_create_user_diver_access(client, db):
    before = db.query(UserDiverAccess).count()
    assert before == 0
    response = client.post(
        "/api/v1/media/backbone/commit", json=_media_only_document()
    )
    assert response.status_code == 200
    after = db.query(UserDiverAccess).count()
    assert after == 0


@pytest.mark.skipif(Dive is None, reason="Dive model unavailable on sqlite")
def test_domain_inventory_uses_dives_as_boundary(client, db):
    dive_ok = Dive(
        session_id=1,
        dive_code="100B",
        performance="G",
        performance_numeric=2,
        height="1",
        dive_datetime=datetime(2026, 1, 1, 10, 0, 0),
        video_uuid=VIDEO_UUID,
        video_filename=f"{VIDEO_UUID}.mov",
        diver_id=1,
    )
    dive_norev = Dive(
        session_id=1,
        dive_code="5122D",
        performance="G",
        performance_numeric=2,
        height="1",
        dive_datetime=datetime(2026, 1, 1, 11, 0, 0),
        video_uuid=VIDEO_UUID2,
        video_filename=f"{VIDEO_UUID2}.mov",
        diver_id=2,
    )
    db.add_all([dive_ok, dive_norev])
    response = client.post(
        "/api/v1/media/backbone/commit", json=_media_only_document()
    )
    assert response.status_code == 200

    items = client.get(
        "/api/v1/media/backbone/migration/domain_inventory"
    ).json()
    assert len(items) == 2  # distinct video_uuid boundary, not revisions
    by_uuid = {i["video_uuid"]: i for i in items}
    assert set(by_uuid) == {VIDEO_UUID, VIDEO_UUID2}
    covered = by_uuid[VIDEO_UUID]
    assert covered["media_revision_id"] is not None
    assert covered["verified_prod"] is True
    assert covered["blob_sha256"] == MEDIA_SHA
    assert covered["video_filename"] == f"{VIDEO_UUID}.mov"
    uncovered = by_uuid[VIDEO_UUID2]
    assert uncovered["media_revision_id"] is None
    assert uncovered["blob_sha256"] is None
    assert uncovered["verified_prod"] is False


@pytest.mark.skipif(Dive is None, reason="Dive model unavailable on sqlite")
def test_domain_inventory_boundary_is_distinct_video_uuid(client, db):
    # dives.video_uuid is UNIQUE (DB-enforced); the inventory boundary is one
    # item per DISTINCT video_uuid, and two dives with different video_uuids
    # but the same recorded asset filename produce two logical items that
    # share one underlying asset identity (content-addressed dedupe applies
    # at the blob level).
    db.add_all(
        [
            Dive(
                session_id=1,
                dive_code="100B",
                performance="G",
                performance_numeric=2,
                height="1",
                dive_datetime=datetime(2026, 1, 1, 10, 0, 0),
                video_uuid=VIDEO_UUID,
                video_filename="20E90523-7B91-422C-9EB7-F91A1CEB12D1.mov",
                diver_id=1,
            ),
            Dive(
                session_id=1,
                dive_code="5122D",
                performance="G",
                performance_numeric=2,
                height="1",
                dive_datetime=datetime(2026, 1, 1, 12, 0, 0),
                video_uuid=VIDEO_UUID2,
                video_filename="20E90523-7B91-422C-9EB7-F91A1CEB12D1.mov",
                diver_id=1,
            ),
        ]
    )
    items = client.get(
        "/api/v1/media/backbone/migration/domain_inventory"
    ).json()
    assert len(items) == 2
    fns = {i["video_filename"] for i in items}
    assert fns == {"20E90523-7B91-422C-9EB7-F91A1CEB12D1.mov"}
    divers = {i["diver_id"] for i in items}
    assert divers == {1}
