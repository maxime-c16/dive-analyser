"""Media backbone P1 backend tests: additive schema, idempotent commit service,
caption revision raw semantics, migration safety guard, and legacy
compatibility (disabled flag = unchanged behavior)."""

import hashlib
import re
from pathlib import Path

import pytest
from app.database import Base
from app.models import (
    CaptionRevision,
    IngestObjectState,
    MediaBlob,
    MediaRevision,
)
from app.models.media import MediaCacheEntry
from app.services.media_backbone import (
    caption_sha256,
    commit_verified_ingest,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKBONE_TABLES = [
    MediaBlob.__table__,
    MediaRevision.__table__,
    CaptionRevision.__table__,
    IngestObjectState.__table__,
    MediaCacheEntry.__table__,
]


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=BACKBONE_TABLES)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    yield session
    session.close()
    engine.dispose()


BLOB_SHA = hashlib.sha256(b"clip-bytes").hexdigest()
CAPTION = "107B | 7.5 | H:3 | drill:no-arms | note:à revoir"


def _commit(session, **overrides):
    kwargs = {
        "video_uuid": "A1B2C3D4E5F60718293A4B5C6D7E8F90",
        "blob_sha256": BLOB_SHA,
        "byte_size": 1024,
        "object_key": f"blobs/sha256/{BLOB_SHA[:2]}/{BLOB_SHA}",
        "storage_backend": "b2",
        "bucket": "diveanalyzer-dev-media",
        "caption_raw": CAPTION,
        "caption_sha": caption_sha256(CAPTION),
        "caption_provider": "osxphotos_description_stable",
        "shadow_provider": "photokit_direct_sqlite_shadow",
        "shadow_raw": CAPTION,
        "shadow_sha256": caption_sha256(CAPTION),
        "shadow_available": True,
        "width": 1920,
        "height": 1080,
        "duration_seconds": 12.5,
        "source_provenance": {"cloud_guid": "guid-1"},
    }
    kwargs.update(overrides)
    return commit_verified_ingest(session, **kwargs)


class TestCommitService:
    def test_commits_blob_revision_caption_once(self, db):
        result = _commit(db)
        assert result["blob_existed"] is False
        assert result["media_revision_existed"] is False
        assert result["caption_revision_existed"] is False
        assert db.get(MediaBlob, BLOB_SHA).byte_size == 1024
        assert db.get(MediaBlob, BLOB_SHA).rendition_semantics == "photos_edited_rendition"
        assert db.query(MediaRevision).count() == 1
        assert db.query(CaptionRevision).count() == 1

    def test_recommit_same_content_is_idempotent(self, db):
        first = _commit(db)
        second = _commit(db)
        assert second["blob_existed"] is True
        assert second["media_revision_existed"] is True
        assert second["caption_revision_existed"] is True
        assert first["media_revision_id"] == second["media_revision_id"]
        assert first["caption_revision_id"] == second["caption_revision_id"]
        assert db.query(MediaBlob).count() == 1
        assert db.query(MediaRevision).count() == 1
        assert db.query(CaptionRevision).count() == 1

    def test_caption_change_appends_new_revision_same_blob_zero_new_blobs(self, db):
        _commit(db)
        new_caption = CAPTION + " (revised)"
        second = _commit(
            db,
            caption_raw=new_caption,
            caption_sha=caption_sha256(new_caption),
        )
        assert second["caption_revision_existed"] is False
        assert second["blob_existed"] is True
        assert db.query(CaptionRevision).count() == 2
        assert db.query(MediaBlob).count() == 1
        assert db.query(MediaRevision).count() == 1

    def test_media_change_appends_new_revision(self, db):
        _commit(db)
        new_blob = hashlib.sha256(b"re-edited-clip").hexdigest()
        _commit(db, blob_sha256=new_blob)
        assert db.query(MediaRevision).count() == 2
        assert db.query(CaptionRevision).count() == 1

    def test_caption_sha_must_match_persisted_bytes(self, db):
        with pytest.raises(ValueError, match="caption_sha256"):
            _commit(db, caption_sha="0" * 64)

    def test_unverified_commit_refused(self, db):
        with pytest.raises(ValueError, match="unverified"):
            _commit(db, verified=False)
        assert db.query(MediaBlob).count() == 0

    def test_malformed_blob_sha_refused(self, db):
        with pytest.raises(ValueError, match="malformed sha256"):
            _commit(db, blob_sha256="XYZ")
        with pytest.raises(ValueError, match="malformed sha256"):
            _commit(db, blob_sha256=BLOB_SHA.upper())

    def test_caption_raw_exact_byte_roundtrip(self, db):
        captions = [
            "107B | 7.5 | H:3 | drill:no-arms | note:à revoir",
            "emoji 🤿 clip",
            "multiple   internal    spaces",
            "line1\nline2",
            "tabs\tand|pipes:",
            "accents éèàç",
        ]
        for i, caption in enumerate(captions):
            _commit(
                db,
                video_uuid=f"VID{i:032d}",
                caption_raw=caption,
                caption_sha=caption_sha256(caption),
                shadow_raw=caption,
                shadow_sha256=caption_sha256(caption),
                shadow_available=True,
            )
            row = (
                db.query(CaptionRevision)
                .filter_by(video_uuid=f"VID{i:032d}")
                .one()
            )
            assert row.caption_raw == caption
            assert row.caption_raw.encode("utf-8") == caption.encode("utf-8")
            assert row.caption_sha256 == hashlib.sha256(caption.encode("utf-8")).hexdigest()
            assert row.exact_equal is True

    def test_shadow_mismatch_records_exact_equal_false(self, db):
        _commit(
            db,
            shadow_raw="different!",
            shadow_sha256=hashlib.sha256(b"different!").hexdigest(),
        )
        row = db.query(CaptionRevision).one()
        assert row.exact_equal is False

    def test_shadow_unavailable_leaves_exact_equal_null(self, db):
        _commit(
            db,
            shadow_raw=None,
            shadow_sha256=None,
            shadow_available=False,
        )
        row = db.query(CaptionRevision).one()
        assert row.exact_equal is None
        assert row.shadow_available is False

    def test_parser_does_not_mutate_raw(self, db):
        _commit(db, parsed_json={"dive_code": "107B", "note": "à revoir"})
        row = db.query(CaptionRevision).one()
        assert row.caption_raw == CAPTION
        assert row.parsed_json["dive_code"] == "107B"


class TestSchemaAdditivity:
    def test_new_tables_exist_and_legacy_untouched(self, db):
        assert db.get(MediaBlob, BLOB_SHA) is None
        _commit(db)
        legacy_columns = {c.name for c in MediaCacheEntry.__table__.columns}
        assert "storage_backend" in legacy_columns
        legacy = MediaCacheEntry(
            media_key="key-1",
            photos_asset_id=1,
            rendition="proxy_360p",
            storage_path="/tmp/x",
            checksum_sha256=BLOB_SHA,
            size_bytes=10,
        )
        db.add(legacy)
        db.flush()
        assert legacy.storage_backend == "local_fs"
        blob = db.get(MediaBlob, BLOB_SHA)
        assert blob.storage_backend == "b2"

    def test_video_uuid_not_fk_coupled(self, db):
        _commit(db)
        fks = list(MediaRevision.__table__.foreign_keys)
        assert fks == [] or all(
            fk.column.table.name == "media_blobs" for fk in fks
        )

    def test_ingest_state_mirror(self, db):
        _commit(db)
        state = db.query(IngestObjectState).one()
        assert state.state == "DB_COMMITTED"
        assert state.verified is True
        assert state.db_committed_at is not None
        assert state.environment == "dev"


class TestMigrationSafetyGuard:
    """Static guard: the migration file is additive and reversible."""

    MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "add_media_backbone_tables.sql"

    def test_migration_file_exists(self):
        assert self.MIGRATION.is_file()

    def test_only_create_statements(self):
        sql = self.MIGRATION.read_text()
        statements = [
            line.strip()
            for line in sql.splitlines()
            if line.strip() and not line.strip().startswith("--")
        ]
        joined = "\n".join(statements)
        for forbidden in re.finditer(
            r"^\s*(ALTER\s+TABLE|DROP\s+COLUMN|UPDATE\s+|DELETE\s+FROM|INSERT\s+INTO|TRUNCATE)",
            joined,
            re.MULTILINE | re.IGNORECASE,
        ):
            raise AssertionError(f"non-additive statement found: {forbidden.group(0)!r}")
        assert joined.count("CREATE TABLE IF NOT EXISTS") == 4
        assert joined.count("CREATE INDEX IF NOT EXISTS") == 7
        assert joined.count("CREATE UNIQUE INDEX IF NOT EXISTS") == 3

    def test_no_reference_to_legacy_tables(self):
        sql = self.MIGRATION.read_text()
        for legacy in ("dives", "photos_assets", "media_cache_entries", "media_jobs"):
            assert not re.search(
                rf"\b{legacy}\b", sql
            ), f"migration references legacy table {legacy}"

    def test_reversibility_comment_present(self):
        sql = self.MIGRATION.read_text()
        assert "DROP TABLE IF EXISTS media_blobs" in sql
