"""D1 durable-derivative foundation on real PostgreSQL (disposable calendar_test_* DB only).

Scope: additive schema + shared original-selector policy. D1 is publish-
and read-inert: no job references `media_derivatives`, no route serves it,
no `persist_derivative` network publisher exists yet (deferred to the
publication slice after fencing).

Proves on disposable PostgreSQL (CI `postgres` tier, never production):

- the real migration file builds D1 objects from a TRUE pre-D1 baseline
  (applied twice: idempotent re-run);
- model/migration semantic parity (nullable/NULL-default contract, status
  server default, CHECK allowlists, required index coverage);
- ledger identity + CHECK constraints + ``ON CONFLICT (column list)``
  upsert shape (not ``ON CONSTRAINT <name>``);
- legacy-row compatibility (rows written the way old code writes them —
  without the new columns — read back with NULLs; old SELECT shapes still
  work);
- original-selector regressions via the ACTUAL selectors: every
  pre-existing selector keeps its exact behavior for all legitimate
  rendition semantics and only gains exclusion of future ``derived_*``
  rows. Guest/download coverage calls the real shared helper
  ``newest_original_revision`` (the function both endpoints call), not a
  rebuilt query.

Pure key/selector-policy unit tests (no PG needed) live in
``tests/test_media_derivatives_d1.py`` so normal backend CI covers them.

Scope hygiene: only ``photos_assets``, ``media_cache_entries``,
``media_jobs``, ``media_blobs``, ``media_blob_locations``,
``media_revisions`` and ``media_derivatives`` (+ FK closure) are created
if missing; the fixture first drops D1 objects to reach a true pre-D1
baseline (D1-owned table/columns only — no other test owns them), then
applies the real migration twice. Rows use a per-test key prefix and are
deleted afterwards. Nothing outside the disposable database is touched.
"""

import hashlib
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = REPO_ROOT / "backend/migrations/add_media_derivatives.sql"

PG_URL = os.environ.get("CALENDAR_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not PG_URL, reason="Disposable PostgreSQL required")


def _engine():
    assert PG_URL, "CALENDAR_TEST_DATABASE_URL is required"
    url = make_url(PG_URL)
    assert url.get_backend_name() == "postgresql", "PostgreSQL only"
    assert (url.database or "").startswith("calendar_test_"), (
        "Disposable calendar_test_* database required — refusing anything else"
    )
    url = url.set(drivername="postgresql+psycopg2")
    return create_engine(url)


def _apply_sql_file(engine, path):
    """Execute a migration file the way `psql -f` does: whole file, driver-level."""
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql(path.read_text())


def _ensure_pre_d1_baseline(engine):
    """Create base tables, then strip D1 objects to reach TRUE pre-D1 state.

    ``Base.metadata.create_all`` uses the NEW metadata (it already knows
    ``media_derivatives`` and the new cache/job columns), so calling it
    alone would mask a migration that forgets CREATE/ALTER. Dropping the
    D1-owned table/columns FIRST forces the real migration file to be the
    only thing that can recreate them: if the migration's CREATE TABLE or
    any ALTER COLUMN is removed, the parity test below fails.
    Only D1-owned objects are dropped; no other test owns them.
    """
    from app.main import app  # noqa: F401  register the complete mapper set
    from app.database import Base

    seed = {
        "photos_assets",
        "media_cache_entries",
        "media_jobs",
        "media_blobs",
        "media_blob_locations",
        "media_revisions",
    }
    tables = {Base.metadata.tables[name] for name in seed if name in Base.metadata.tables}
    assert seed <= {t.name for t in tables}, f"baseline models missing: {seed - {t.name for t in tables}}"
    while True:
        deps = {fk.column.table for t in tables for fk in t.foreign_keys}
        if deps <= tables:
            break
        tables |= deps
    Base.metadata.create_all(engine, tables=tables)
    # Strip D1 objects -> true pre-D1 baseline (idempotent).
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS media_derivatives")
        conn.exec_driver_sql(
            "ALTER TABLE media_cache_entries DROP COLUMN IF EXISTS source_blob_sha256"
        )
        conn.exec_driver_sql(
            "ALTER TABLE media_cache_entries DROP COLUMN IF EXISTS transform_version"
        )
        conn.exec_driver_sql("ALTER TABLE media_jobs DROP COLUMN IF EXISTS lease_token")
        conn.exec_driver_sql("ALTER TABLE media_jobs DROP COLUMN IF EXISTS finalized_slots")


@pytest.fixture()
def pg():
    from app.config import get_settings

    engine = _engine()
    _ensure_pre_d1_baseline(engine)
    # Real migration, twice: idempotency is the deploy precondition.
    _apply_sql_file(engine, MIGRATION_PATH)
    _apply_sql_file(engine, MIGRATION_PATH)

    settings = get_settings()
    saved = (
        settings.user_auth_enabled,
        settings.b2_playback_canary_enabled,
        settings.media_backbone_prod_bucket,
    )
    settings.user_auth_enabled = True
    settings.b2_playback_canary_enabled = True

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    prefix = f"pg-d1-{uuid4().hex[:12]}"

    yield engine, factory, session, prefix, settings

    try:
        session.rollback()
        session.execute(text("DELETE FROM media_derivatives WHERE video_uuid LIKE :p"), {"p": prefix + "%"})
        session.execute(
            text("DELETE FROM media_revisions WHERE video_uuid LIKE :p"), {"p": prefix + "%"}
        )
        session.execute(
            text("DELETE FROM media_blob_locations WHERE object_key LIKE :p"), {"p": prefix + "%"}
        )
        for sha in session.info.get("pg_d1_blob_shas", set()):
            session.execute(text("DELETE FROM media_blob_locations WHERE blob_sha256 = :s"), {"s": sha})
            session.execute(text("DELETE FROM media_blobs WHERE sha256 = :s"), {"s": sha})
        session.execute(text("DELETE FROM media_cache_entries WHERE media_key LIKE :p"), {"p": prefix + "%"})
        session.execute(text("DELETE FROM media_jobs WHERE media_key LIKE :p"), {"p": prefix + "%"})
        session.execute(
            text("DELETE FROM photos_assets WHERE video_uuid LIKE :p"), {"p": prefix + "%"}
        )
        session.commit()
    finally:
        (settings.user_auth_enabled, settings.b2_playback_canary_enabled,
         settings.media_backbone_prod_bucket) = saved
        session.close()
        engine.dispose()


def _asset(session, prefix):
    from app.models.photos_asset import PhotosAsset

    asset = PhotosAsset(video_uuid=f"{prefix}-{uuid4().hex[:8]}")
    session.add(asset)
    session.commit()
    return asset


def _sha(tag):
    return hashlib.sha256(f"d1-{tag}".encode()).hexdigest()


def _verified_revision(session, prefix, video_uuid, semantics, bucket, *, tag=None):
    """One verified PROD replica + revision, satisfying verified_original_clause."""
    from app.models.media_backbone import MediaBlob, MediaBlobLocation, MediaRevision

    sha = _sha(tag or f"{video_uuid}-{semantics}")
    session.info.setdefault("pg_d1_blob_shas", set()).add(sha)
    if session.get(MediaBlob, sha) is None:
        session.add(MediaBlob(sha256=sha, byte_size=100, rendition_semantics=semantics))
        session.flush()
    key = f"{prefix}/{uuid4().hex[:8]}"
    session.add(
        MediaBlobLocation(
            blob_sha256=sha,
            environment="prod",
            storage_backend="b2",
            bucket=bucket,
            object_key=key,
            verified=True,
            verified_at=datetime.utcnow(),
        )
    )
    session.flush()
    revision = MediaRevision(
        video_uuid=video_uuid, blob_sha256=sha, rendition_semantics=semantics
    )
    session.add(revision)
    session.commit()
    return revision


def _col_type_str(col):
    return str(col.get("type", "")).upper()


def test_migration_creates_d1_objects_from_pre_d1_baseline(pg):
    """Real SQL builds D1 objects from pre-D1 state + semantic model parity.

    Fails if the migration's CREATE TABLE or any ALTER COLUMN is removed
    (the fixture strips D1 objects first, so only the migration can
    recreate them). Asserts semantic parity — nullable, NULL legacy
    defaults, status server default, types, CHECKs, required index
    coverage — not exact index names (model single-column index names and
    SQL names intentionally differ; coverage is what matters).
    """
    from app.database import Base

    engine, factory, session, prefix, settings = pg
    inspector = inspect(engine)

    # The migration (and only the migration) recreated these.
    assert inspector.has_table("media_derivatives")
    columns = {c["name"]: c for c in inspector.get_columns("media_derivatives")}
    for name in (
        "id", "video_uuid", "source_blob_sha256", "role", "transform_version",
        "derivative_blob_sha256", "status", "verified_at", "created_at",
    ):
        assert name in columns, f"media_derivatives.{name} missing after migration"

    # Semantic type parity: VARCHAR lengths + nullable + defaults.
    assert "100" in _col_type_str(columns["video_uuid"])
    assert "64" in _col_type_str(columns["source_blob_sha256"])
    assert "64" in _col_type_str(columns["derivative_blob_sha256"])
    assert "20" in _col_type_str(columns["role"])
    assert "40" in _col_type_str(columns["transform_version"])
    assert "20" in _col_type_str(columns["status"])
    assert columns["video_uuid"]["nullable"] is False
    assert columns["source_blob_sha256"]["nullable"] is False
    assert columns["derivative_blob_sha256"]["nullable"] is False
    assert columns["verified_at"]["nullable"] is True
    # Status server default proves the model/SQL parity the runbook needs:
    # a raw INSERT without status lands 'verifying' from the DB default.
    assert columns["status"]["default"] is not None
    assert "verifying" in columns["status"]["default"]

    cache_cols = {c["name"]: c for c in inspector.get_columns("media_cache_entries")}
    assert cache_cols["source_blob_sha256"]["nullable"] is True
    assert cache_cols["transform_version"]["nullable"] is True
    assert cache_cols["source_blob_sha256"]["default"] is None
    job_cols = {c["name"]: c for c in inspector.get_columns("media_jobs")}
    assert job_cols["lease_token"]["nullable"] is True
    assert job_cols["finalized_slots"]["nullable"] is True
    # finalized_slots ships NULL-default (not DEFAULT '[]'): NULL = no slot
    # finalized yet; D3 must treat NULL as empty.
    assert job_cols["finalized_slots"]["default"] is None

    # Every model column exists in the migrated schema.
    for table_name in ("media_derivatives", "media_cache_entries", "media_jobs"):
        model_cols = Base.metadata.tables[table_name].columns
        migrated = {c["name"]: c for c in inspector.get_columns(table_name)}
        for col in model_cols:
            assert col.name in migrated, f"{table_name}.{col.name} missing in migrated schema"
        for col in model_cols:
            if col.name in migrated and table_name == "media_derivatives":
                # Nullable contract must agree (types intentionally differ in
                # spelling: model String/DateTime vs SQL VARCHAR/TIMESTAMP).
                assert bool(col.nullable) == bool(migrated[col.name]["nullable"]), (
                    f"{table_name}.{col.name} nullable mismatch: "
                    f"model={col.nullable} sql={migrated[col.name]['nullable']}"
                )

    # Ledger identity: unique coverage on the full derivation identity,
    # whether as a unique constraint or a unique index.
    uniques = inspector.get_unique_constraints("media_derivatives")
    indexes = inspector.get_indexes("media_derivatives")
    identity = ["role", "source_blob_sha256", "transform_version", "video_uuid"]
    assert any(
        sorted(u["column_names"]) == identity for u in uniques
    ) or any(
        sorted(i["column_names"]) == identity and i["unique"] for i in indexes
    ), (uniques, indexes)
    # Required query coverage: clip+role+status composite exists (exact name
    # asserted — it is the shared lookup path — while single-column index
    # names are intentionally allowed to differ by convention).
    assert any(
        i["name"] == "ix_media_derivative_clip_role"
        and list(i["column_names"]) == ["video_uuid", "role", "status"]
        for i in indexes
    ), indexes
    # Single-column coverage (names may differ; columns must be indexed).
    indexed_cols = {c for i in indexes for c in i["column_names"]}
    for col in ("video_uuid", "source_blob_sha256", "derivative_blob_sha256"):
        assert col in indexed_cols, f"{col} has no index coverage: {indexes}"
    checks = {c["name"]: c["sqltext"] for c in inspector.get_check_constraints("media_derivatives")}
    assert "ck_media_derivative_role" in checks, checks
    assert "ck_media_derivative_status" in checks, checks
    assert "hq" in str(checks["ck_media_derivative_role"])
    assert "ready" in str(checks["ck_media_derivative_status"])


def test_ledger_identity_constraints_status_default_and_upsert_shape(pg):
    from app.models.media_backbone import MediaDerivative

    engine, factory, session, prefix, settings = pg
    video_uuid = f"{prefix}-clip"
    source_sha = _sha(f"{prefix}-source")
    derived_sha = _sha(f"{prefix}-derived")
    identity = dict(
        video_uuid=video_uuid,
        source_blob_sha256=source_sha,
        role="hq",
        transform_version="ffmpeg-h264-web-v1",
    )

    first = MediaDerivative(derivative_blob_sha256=derived_sha, **identity)
    session.add(first)
    session.commit()
    assert first.status == "verifying"
    assert first.verified_at is None

    # Server-side DEFAULT: a raw INSERT without status lands 'verifying'
    # (proves the SQL DEFAULT, independent of the ORM default).
    raw_uuid = f"{prefix}-raw-default"
    session.execute(
        text(
            "INSERT INTO media_derivatives "
            "(video_uuid, source_blob_sha256, role, transform_version, derivative_blob_sha256) "
            "VALUES (:v, :s, 'light', 'ffmpeg-h264-web-v1', :d)"
        ),
        {"v": raw_uuid, "s": _sha(f"{prefix}-raw-src"), "d": _sha(f"{prefix}-raw-der")},
    )
    session.commit()
    got = session.execute(
        text("SELECT status FROM media_derivatives WHERE video_uuid = :v"), {"v": raw_uuid}
    ).scalar_one()
    assert got == "verifying"

    # Replay of the same derivation identity is rejected (future publisher
    # upserts on this identity instead of inserting blindly).
    session.add(MediaDerivative(derivative_blob_sha256=_sha("other"), **identity))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    # Future-publisher upsert shape: ON CONFLICT (column list) — not
    # ON CONSTRAINT <name> — resolves the same identity.
    session.execute(
        text(
            "INSERT INTO media_derivatives "
            "(video_uuid, source_blob_sha256, role, transform_version, derivative_blob_sha256, status) "
            "VALUES (:v, :s, 'hq', 'ffmpeg-h264-web-v1', :d2, 'ready') "
            "ON CONFLICT (video_uuid, source_blob_sha256, role, transform_version) "
            "DO UPDATE SET status = EXCLUDED.status"
        ),
        {"v": video_uuid, "s": source_sha, "d2": _sha(f"{prefix}-upsert")},
    )
    session.commit()
    assert (
        session.query(MediaDerivative)
        .filter_by(video_uuid=video_uuid, role="hq")
        .one()
        .status
        == "ready"
    )

    # Same source, different role: distinct derivation.
    session.add(
        MediaDerivative(
            derivative_blob_sha256=_sha(f"{prefix}-light"),
            video_uuid=video_uuid,
            source_blob_sha256=source_sha,
            role="light",
            transform_version="ffmpeg-h264-web-v1",
        )
    )
    session.commit()

    # Role and status allowlists are enforced by the database.
    for bad_role, bad_status in (("proxy_720p", "verifying"), ("hq", "ready-ish")):
        row = MediaDerivative(
            video_uuid=video_uuid,
            source_blob_sha256=_sha(f"{prefix}-bad-{bad_role}-{bad_status}-{uuid4().hex[:6]}"),
            role=bad_role,
            transform_version="ffmpeg-h264-web-v1",
            derivative_blob_sha256=_sha(f"{prefix}-badsha-{bad_role}-{uuid4().hex[:6]}"),
            status=bad_status,
        )
        session.add(row)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_legacy_rows_default_null_and_old_code_shape(pg):
    """Old code writes rows without the new columns: NULLs, still servable."""
    from app.models.media import MediaCacheEntry, MediaJob
    from app.services.media_cache import ready_entries_for_asset

    engine, factory, session, prefix, settings = pg
    asset = _asset(session, prefix)

    # Exactly what the pre-D1 code inserts (no new kwargs).
    cache_row = MediaCacheEntry(
        photos_asset_id=asset.id,
        media_key=f"{prefix}-720",
        rendition="proxy_720p",
        storage_path="/tmp/d1-legacy.mp4",
        size_bytes=8,
        status="ready",
    )
    job = MediaJob(photos_asset_id=asset.id, media_key=f"{prefix}-job", rendition="proxy_720p")
    session.add_all([cache_row, job])
    session.commit()
    cache_id, job_id = cache_row.id, job.id

    # Raw SQL shape (what old code's SELECTs see): new columns read NULL.
    row = session.execute(
        text(
            "SELECT source_blob_sha256, transform_version FROM media_cache_entries WHERE id = :i"
        ),
        {"i": cache_id},
    ).one()
    assert row[0] is None and row[1] is None
    jrow = session.execute(
        text("SELECT lease_token, finalized_slots FROM media_jobs WHERE id = :i"),
        {"i": job_id},
    ).one()
    assert jrow[0] is None and jrow[1] is None

    check = factory()
    try:
        cached = check.query(MediaCacheEntry).filter_by(media_key=f"{prefix}-720").one()
        assert cached.source_blob_sha256 is None
        assert cached.transform_version is None
        assert check.query(MediaCacheEntry).filter_by(media_key=f"{prefix}-720").one().status == "ready"
        assert len(ready_entries_for_asset(check, asset.id)) == 1
        stored_job = check.query(MediaJob).filter_by(media_key=f"{prefix}-job").one()
        assert stored_job.lease_token is None
        # D3 contract: NULL finalized_slots means "no slot finalized yet".
        assert stored_job.finalized_slots is None
        assert (stored_job.finalized_slots or []) == []
        assert stored_job.status == "queued"
    finally:
        check.close()


def test_original_selectors_preserve_legitimate_semantics_and_exclude_derived(pg):
    """All seven read/source selectors: same answers for real semantics,
    derivative rows never surface as originals."""
    from app.services.matchmaking import original_revision_id
    from app.services.evaluation_access import backbone_originals
    from app.api.v1.media import _backbone_playback_url, _backbone_revision_ids_bulk
    from app.services.media_backbone import newest_original_revision

    engine, factory, session, prefix, settings = pg
    bucket = settings.media_backbone_prod_bucket
    video_uuid = f"{prefix}-clip"

    # Commit order: edited rendition, raw browser original, playable browser
    # transcode (newest non-derived), then a future derived row (newest).
    edited = _verified_revision(session, prefix, video_uuid, "photos_edited_rendition", bucket)
    raw = _verified_revision(session, prefix, video_uuid, "browser_original", bucket)
    playable = _verified_revision(session, prefix, video_uuid, "browser_playback", bucket)
    derived = _verified_revision(session, prefix, video_uuid, "derived_hq", bucket)

    # Playback selectors keep excluding the raw upload and now also skip the
    # future derivative: the served original stays the playable transcode.
    assert original_revision_id(session, video_uuid) == playable.id
    assert _backbone_playback_url(session, video_uuid) == f"/api/v1/media/revisions/{playable.id}/play"
    assert _backbone_revision_ids_bulk(session, [video_uuid]) == {video_uuid: playable.id}
    assert backbone_originals(session, [video_uuid]) == {video_uuid: playable.id}
    # Guest/download newest-revision pick via the ACTUAL shared helper both
    # endpoints call (not a rebuilt query): newest derived is skipped.
    assert newest_original_revision(session, video_uuid).id == playable.id

    # A clip with ONLY a raw browser original still resolves it as playable —
    # the pre-D1 behavior for that corner is unchanged (the `!=
    # browser_original` filter only applies when a newer playable revision
    # exists, and D1 adds no new exclusion for it).
    raw_only = f"{prefix}-raw-only"
    raw_only_rev = _verified_revision(session, prefix, raw_only, "browser_original", bucket)
    assert original_revision_id(session, raw_only) is None  # unchanged: raw alone is not served as playable
    assert _backbone_playback_url(session, raw_only) is None
    # The shared helper preserves legacy newest-first behavior for
    # non-derivative rows: the lone raw original is still returned.
    assert newest_original_revision(session, raw_only).id == raw_only_rev.id

    # The transcode source keeps the true camera original eligible: newest
    # verified revision regardless of (non-derivative) semantics.
    from types import SimpleNamespace
    from unittest.mock import patch

    from app.models.photos_asset import PhotosAsset
    from app.models.media import MediaJob
    from app.services.media_jobs import _b2_source

    asset = _asset(session, prefix)
    asset.video_uuid = video_uuid
    session.commit()
    job = MediaJob(photos_asset_id=asset.id, media_key=f"{prefix}-src", rendition="proxy_720p")
    session.add(job)
    session.commit()
    with patch(
        "app.services.b2_presign.presign_get",
        return_value=SimpleNamespace(url="https://b2.test/source", ttl_seconds=120),
    ):
        source = _b2_source(session, job)
        # Newest verified revision is the derived row → must be skipped, falling
        # back to the newest NON-derivative (the playable transcode).
        assert source.get("source_sha256") == playable.blob_sha256

        # Without any derived row, the source is the newest revision as before —
        # including a raw browser_original when it is newest (no quality
        # regression: the publisher still sees true camera bytes).
        session.delete(derived)
        session.commit()
        source = _b2_source(session, job)
        assert source.get("source_sha256") == playable.blob_sha256
        session.delete(playable)
        session.commit()
        source = _b2_source(session, job)
        assert source.get("source_sha256") == raw.blob_sha256

    # Guest/download helper also skips future derivatives added later.
    _verified_revision(session, prefix, video_uuid, "derived_light", bucket)
    newest_original = newest_original_revision(session, video_uuid)
    assert newest_original is not None
    assert not newest_original.rendition_semantics.startswith("derived_")
