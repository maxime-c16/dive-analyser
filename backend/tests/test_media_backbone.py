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
    MediaBlobLocation,
    MediaRevision,
)
from app.models.media import MediaCacheEntry
from app.services.media_backbone import (
    caption_sha256,
    commit_verified_ingest,
    resolve_media_revision_location,
    resolve_verified_location,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKBONE_TABLES = [
    MediaBlob.__table__,
    MediaBlobLocation.__table__,
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
        _commit(db, blob_sha256=new_blob, object_key=f"blobs/sha256/{new_blob[:2]}/{new_blob}")
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


EXACTNESS_STRINGS = [
    "abc",
    " abc",
    "abc ",
    "  abc  ",
    "",
    " ",
    "  ",
    "a  b",
    "a\nb",
    "\na\n",
    "éèàç",
    "🤿",
    "107B | 7.5 | H:3",
]


class TestCaptionRawExactness:
    """R1: CaptionRevision.caption_raw preserves the provider-returned string
    before any application-level whitespace normalization."""

    def test_input_provider_string_equals_persisted_caption_raw(self, db):
        for i, caption in enumerate(EXACTNESS_STRINGS):
            _commit(
                db,
                video_uuid=f"RAW{i:031d}",
                caption_raw=caption,
                caption_sha=caption_sha256(caption),
            )
            row = db.query(CaptionRevision).filter_by(video_uuid=f"RAW{i:031d}").one()
            assert row.caption_raw == caption
            assert row.caption_raw.encode("utf-8") == caption.encode("utf-8")
            assert row.caption_sha256 == hashlib.sha256(caption.encode("utf-8")).hexdigest()

    def test_whitespace_variants_are_distinct_rows_and_hashes(self, db):
        for i, caption in enumerate(["abc", " abc", "abc ", "  abc  ", "\na\n", "a"]):
            _commit(
                db,
                video_uuid=f"VAR{i:031d}",
                caption_raw=caption,
                caption_sha=caption_sha256(caption),
            )
        hashes = {
            r.caption_raw: r.caption_sha256
            for r in db.query(CaptionRevision).filter(
                CaptionRevision.video_uuid.like("VAR%")
            ).all()
        }
        assert len(hashes) == 6
        assert hashes[" abc"] != hashes["abc"]
        assert hashes["abc "] != hashes["abc"]
        assert hashes["\na\n"] != hashes["a"]
        assert caption_sha256(" abc") != caption_sha256("abc")
        assert caption_sha256("abc ") != caption_sha256("abc")
        assert caption_sha256("\na\n") != caption_sha256("a")

    def test_persisted_exact_even_for_whitespace_only(self, db):
        _commit(
            db,
            video_uuid="W" * 32,
            caption_raw="  ",
            caption_sha=caption_sha256("  "),
        )
        row = db.query(CaptionRevision).filter_by(video_uuid="W" * 32).one()
        assert row.caption_raw == "  "
        assert row.caption_sha256 == hashlib.sha256(b"  ").hexdigest()


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


class TestStateAuthorityArchitecture:
    """R3 static assertion: the commit ledger is not a second orchestration
    journal — `ingest_object_state` is referenced ONLY by its model and the
    commit service; the agent coordinator never touches it."""

    def test_ledger_referenced_only_in_model_and_service(self):
        backend_dir = Path(__file__).resolve().parents[1]
        allowed = {
            backend_dir / "app" / "models" / "media_backbone.py",
            backend_dir / "app" / "services" / "media_backbone.py",
            backend_dir / "tests" / "test_media_backbone.py",
        }
        hits = []
        for py in backend_dir.rglob("*.py"):
            if py in allowed or "migrations" in py.parts:
                continue
            if "ingest_object_state" in py.read_text():
                hits.append(str(py))
        assert hits == []

    def test_agent_coordinator_does_not_reference_server_state(self):
        agent_coordinator = (
            Path(__file__).resolve().parents[2]
            / "mac-agent" / "src" / "ingest" / "coordinator.py"
        )
        src = agent_coordinator.read_text()
        assert "ingest_object_state" not in src
        assert "app.models" not in src


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


DEV_BUCKET_NAME = "diveanalyzer-dev-media"
PROD_BUCKET_NAME = "diveanalyzer-prod-media"

CROSS_ENV_UUID = "C1D2E3F4A5B60718293A4B5C6D7E8F90"
OTHER_SHA = hashlib.sha256(b"other-clip-bytes").hexdigest()


class TestStorageLocationModel:
    """P4.3 storage authority: content identity vs physical storage replicas.

    Packet MEDIA_BACKBONE_P4_3_OVERNIGHT_STORAGE_AUTHORITY_HARDENING_V1 §25:
    the same SHA must be representable in the DEV and PROD buckets
    simultaneously without losing either location.
    """

    def test_new_sha_in_dev_creates_blob_and_dev_location(self, db):
        result = _commit(db)
        assert result["blob_existed"] is False
        assert result["blob_location_existed"] is False
        location = db.query(MediaBlobLocation).one()
        assert location.blob_sha256 == BLOB_SHA
        assert location.environment == "dev"
        assert location.bucket == DEV_BUCKET_NAME
        assert location.verified is True
        assert location.verified_at is not None

    def test_same_sha_replay_dev_no_duplicates(self, db):
        first = _commit(db)
        replay = _commit(db)
        assert replay["blob_existed"] is True
        assert replay["blob_location_existed"] is True
        assert replay["media_blob_location_id"] == first["media_blob_location_id"]
        assert db.query(MediaBlob).count() == 1
        assert db.query(MediaBlobLocation).count() == 1
        assert db.query(IngestObjectState).count() == 1

    def test_same_sha_first_prod_commit_same_blob_plus_prod_location(self, db):
        _commit(db)  # DEV
        prod = _commit(
            db,
            bucket=PROD_BUCKET_NAME,
            environment="prod",
        )
        assert prod["blob_existed"] is True  # content dedupe across environments
        assert prod["blob_location_existed"] is False  # new physical replica
        locations = db.query(MediaBlobLocation).all()
        assert len(locations) == 2
        envs = sorted(l.environment for l in locations)
        assert envs == ["dev", "prod"]
        # One content row, two physical replicas; the transitional blob row
        # keeps its first-seen (DEV) location untouched.
        blob = db.get(MediaBlob, BLOB_SHA)
        assert blob.bucket == DEV_BUCKET_NAME

    def test_same_sha_replay_prod_no_duplicates(self, db):
        _commit(db)
        _commit(db, bucket=PROD_BUCKET_NAME, environment="prod")
        replay = _commit(db, bucket=PROD_BUCKET_NAME, environment="prod")
        assert replay["blob_existed"] is True
        assert replay["blob_location_existed"] is True
        assert db.query(MediaBlob).count() == 1
        assert db.query(MediaBlobLocation).count() == 2
        assert db.query(IngestObjectState).count() == 2

    def test_same_sha_dev_plus_prod_exactly_two_locations(self, db):
        _commit(db)
        _commit(db, bucket=PROD_BUCKET_NAME, environment="prod")
        assert db.query(MediaBlob).count() == 1
        assert db.query(MediaBlobLocation).count() == 2

    def test_wrong_bucket_for_environment_rejected(self, db):
        with pytest.raises(ValueError, match="must reference the"):
            _commit(db, bucket=PROD_BUCKET_NAME, environment="dev")

    def test_prod_environment_referencing_dev_location_rejected(self, db):
        with pytest.raises(ValueError, match="must reference the"):
            _commit(db, bucket=DEV_BUCKET_NAME, environment="prod")

    def test_dev_environment_referencing_prod_location_rejected(self, db):
        with pytest.raises(ValueError, match="must reference the"):
            _commit(db, bucket=PROD_BUCKET_NAME, environment="dev")

    def test_same_key_conflicting_sha_rejected(self, db):
        _commit(db)
        other_key = f"blobs/sha256/{BLOB_SHA[:2]}/{BLOB_SHA}"
        with pytest.raises(ValueError, match="conflicting SHA"):
            _commit(
                db,
                blob_sha256=OTHER_SHA,
                object_key=other_key,
                caption_raw="other caption bytes",
                caption_sha=caption_sha256("other caption bytes"),
            )

    def test_unverified_location_not_playback_eligible(self, db):
        from datetime import datetime

        db.add(
            MediaBlobLocation(
                blob_sha256=OTHER_SHA,
                environment="prod",
                storage_backend="b2",
                bucket=PROD_BUCKET_NAME,
                object_key=f"blobs/sha256/{OTHER_SHA[:2]}/{OTHER_SHA}",
                verified=False,
                verified_at=None,
            )
        )
        db.commit()
        assert resolve_verified_location(db, OTHER_SHA, "prod") is None

    def test_p5_lookup_media_revision_prod_deterministic(self, db):
        _commit(db, video_uuid=CROSS_ENV_UUID)
        _commit(
            db,
            video_uuid=CROSS_ENV_UUID,
            bucket=PROD_BUCKET_NAME,
            environment="prod",
        )
        location = resolve_media_revision_location(db, CROSS_ENV_UUID, "prod")
        assert location is not None
        assert location.blob_sha256 == BLOB_SHA
        assert location.environment == "prod"
        assert location.bucket == PROD_BUCKET_NAME
        assert location.verified is True
        again = resolve_media_revision_location(db, CROSS_ENV_UUID, "prod")
        assert again.id == location.id  # deterministic, stable answer
        assert resolve_media_revision_location(db, "FFFF0000-0000-4000-8000-000000000000", "prod") is None

    def test_ingest_state_env_scoped_uniqueness(self, db):
        _commit(db)  # (uuid, key, env=dev)
        _commit(db, bucket=PROD_BUCKET_NAME, environment="prod")
        states = db.query(IngestObjectState).order_by(IngestObjectState.id).all()
        assert len(states) == 2  # one logical ingest event per environment
        assert [s.environment for s in states] == ["dev", "prod"]
        assert all(s.blob_sha256 == BLOB_SHA for s in states)

    def test_blob_content_columns_untouched_by_location_repair(self, db):
        _commit(db)
        _commit(db, bucket=PROD_BUCKET_NAME, environment="prod")
        blob = db.get(MediaBlob, BLOB_SHA)
        # Transitional columns keep the first-seen location only.
        assert blob.bucket == DEV_BUCKET_NAME
        assert blob.object_key == f"blobs/sha256/{BLOB_SHA[:2]}/{BLOB_SHA}"


class TestBlobLocationsMigrationSafetyGuard:
    """Static guard for the P4.3 additive locations migration."""

    MIGRATION = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "add_media_blob_locations.sql"
    )

    def test_migration_file_exists(self):
        assert self.MIGRATION.is_file()

    def test_additive_statements_only(self):
        sql = self.MIGRATION.read_text()
        statements = [
            line.strip()
            for line in sql.splitlines()
            if line.strip() and not line.strip().startswith("--")
        ]
        joined = "\n".join(statements)
        for forbidden in re.finditer(
            r"^\s*(ALTER\s+TABLE|DROP\s+COLUMN|UPDATE\s+|DELETE\s+FROM|TRUNCATE)",
            joined,
            re.MULTILINE | re.IGNORECASE,
        ):
            raise AssertionError(f"non-additive statement found: {forbidden.group(0)!r}")
        # One new backbone table; idempotent INSERT..SELECT backfill allowed.
        assert joined.count("CREATE TABLE IF NOT EXISTS") == 1
        assert joined.count("INSERT INTO") == 1
        # The legacy uniqueness index is dropped only AFTER the replacement
        # authority exists (documented, reversible, non-destructive).
        assert joined.count("DROP INDEX IF EXISTS") == 1
        assert "ix_ingest_object_state_clip_key_unique" in joined

    def test_backfill_is_idempotent(self):
        sql = self.MIGRATION.read_text()
        assert "NOT EXISTS (" in sql

    def test_no_reference_to_legacy_tables(self):
        sql = self.MIGRATION.read_text()
        for legacy in ("dives", "photos_assets", "media_cache_entries", "media_jobs"):
            assert not re.search(rf"\b{legacy}\b", sql)

    def test_reversibility_comment_present(self):
        sql = self.MIGRATION.read_text()
        assert "DROP TABLE IF EXISTS media_blob_locations" in sql
