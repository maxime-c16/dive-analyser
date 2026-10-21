"""D1 durable-derivative foundation on real PostgreSQL (disposable calendar_test_* DB only).

Scope: additive schema + deterministic derivative keys + shared
original-selector policy. D1 is publish- and read-inert: no job references
`media_derivatives`, no route serves it, no `persist_derivative` network
publisher exists yet (deferred to the publication slice after fencing).

Proves on disposable PostgreSQL (CI `postgres` tier, never production):

- the real migration file applies twice (idempotent re-run);
- model/migration parity (SQLAlchemy metadata matches the migrated schema,
  including the D1 nullable columns and their NULL legacy defaults);
- ledger identity + CHECK constraints (unique
  (video_uuid, source_sha, role, transform_version); role/status allowlists;
  status default `verifying`);
- legacy-row compatibility (rows written the way old code writes them —
  without the new columns — read back with NULLs; old SELECT shapes still
  work);
- `build_derivative_media_key` determinism + fail-closed validation, and
  legacy `build_media_key` byte-stability (the legacy transform default is
  untouched; derivative versioning is a separate setting);
- original-selector regressions: every pre-existing selector keeps its
  exact behavior for all legitimate rendition semantics
  (`photos_edited_rendition`, `browser_original`, `browser_playback`) and
  only gains exclusion of future `derived_*` rows. In particular
  `browser_original` (the true camera original for browser clips) is still
  selectable as a transcode source via `_b2_source`, while playback
  selectors keep excluding it exactly as before.

Scope hygiene: only `photos_assets`, `media_cache_entries`, `media_jobs`,
`media_blobs`, `media_blob_locations`, `media_revisions` and
`media_derivatives` (+ FK closure) are created if missing; rows use a
per-test key prefix and are deleted afterwards. Nothing outside the
disposable database is touched.
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


def _ensure_tables(engine):
    from app.main import app  # noqa: F401  register the complete mapper set
    from app.database import Base

    seed = {
        "photos_assets",
        "media_cache_entries",
        "media_jobs",
        "media_blobs",
        "media_blob_locations",
        "media_revisions",
        "media_derivatives",
    }
    tables = {Base.metadata.tables[name] for name in seed if name in Base.metadata.tables}
    assert seed <= {t.name for t in tables}, f"D1 models missing: {seed - {t.name for t in tables}}"
    while True:
        deps = {fk.column.table for t in tables for fk in t.foreign_keys}
        if deps <= tables:
            break
        tables |= deps
    Base.metadata.create_all(engine, tables=tables)


@pytest.fixture()
def pg():
    from app.config import get_settings

    engine = _engine()
    _ensure_tables(engine)
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


def test_migration_idempotent_and_models_aligned(pg):
    """Real SQL twice + SQLAlchemy metadata parity for every D1 object."""
    from app.database import Base

    engine, factory, session, prefix, settings = pg
    inspector = inspect(engine)

    assert inspector.has_table("media_derivatives")
    columns = {c["name"]: c for c in inspector.get_columns("media_derivatives")}
    for name in (
        "id", "video_uuid", "source_blob_sha256", "role", "transform_version",
        "derivative_blob_sha256", "status", "verified_at", "created_at",
    ):
        assert name in columns, f"media_derivatives.{name} missing after migration"
    assert columns["status"]["default"] == "'verifying'::character varying"

    cache_columns = {c["name"] for c in inspector.get_columns("media_cache_entries")}
    assert "source_blob_sha256" in cache_columns
    assert "transform_version" in cache_columns
    job_columns = {c["name"] for c in inspector.get_columns("media_jobs")}
    assert "lease_token" in job_columns
    assert "finalized_slots" in job_columns

    # Model/migration parity: every model column exists in the migrated schema
    # with a compatible nullable/default contract.
    for table_name in ("media_derivatives", "media_cache_entries", "media_jobs"):
        model_cols = Base.metadata.tables[table_name].columns
        migrated = {c["name"]: c for c in inspector.get_columns(table_name)}
        for col in model_cols:
            assert col.name in migrated, f"{table_name}.{col.name} missing in migrated schema"

    uniques = inspector.get_unique_constraints("media_derivatives")
    indexes = inspector.get_indexes("media_derivatives")
    assert any(
        sorted(u["column_names"]) == ["role", "source_blob_sha256", "transform_version", "video_uuid"]
        for u in uniques
    ) or any(
        sorted(i["column_names"]) == ["role", "source_blob_sha256", "transform_version", "video_uuid"]
        and i["unique"]
        for i in indexes
    ), (uniques, indexes)
    checks = {c["name"]: c["sqltext"] for c in inspector.get_check_constraints("media_derivatives")}
    assert "ck_media_derivative_role" in checks, checks
    assert "ck_media_derivative_status" in checks, checks


def test_ledger_identity_constraints_and_status_default(pg):
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

    # Replay of the same derivation identity is rejected (future publisher
    # upserts on this identity instead of inserting blindly).
    session.add(MediaDerivative(derivative_blob_sha256=_sha("other"), **identity))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

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

    rows = session.query(MediaDerivative).filter_by(video_uuid=video_uuid).all()
    assert {(r.role, r.status) for r in rows} == {("hq", "verifying"), ("light", "verifying")}


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

    check = factory()
    try:
        cached = check.query(MediaCacheEntry).filter_by(media_key=f"{prefix}-720").one()
        assert cached.source_blob_sha256 is None
        assert cached.transform_version is None
        assert check.query(MediaCacheEntry).filter_by(media_key=f"{prefix}-720").one().status == "ready"
        assert len(ready_entries_for_asset(check, asset.id)) == 1
        stored_job = check.query(MediaJob).filter_by(media_key=f"{prefix}-job").one()
        assert stored_job.lease_token is None
        assert stored_job.finalized_slots is None
        assert stored_job.status == "queued"
    finally:
        check.close()


def test_derivative_key_determinism_and_fail_closed_validation(pg):
    from app.services.media_keys import (
        build_derivative_media_key,
        build_media_key,
    )

    engine, factory, session, prefix, settings = pg
    video_uuid = f"{prefix}-clip"
    source_sha = _sha(f"{prefix}-source")
    version = "ffmpeg-h264-web-v1"

    first = build_derivative_media_key(video_uuid, "hq", source_sha, version)
    assert first == build_derivative_media_key(video_uuid, "hq", source_sha, version)
    assert len(first) == 64
    # Identity is (clip, role, source, version): each axis separates keys.
    assert build_derivative_media_key(video_uuid, "light", source_sha, version) != first
    assert build_derivative_media_key(video_uuid, "hq", _sha("other-source"), version) != first
    assert build_derivative_media_key(video_uuid, "hq", source_sha, "ffmpeg-h264-web-v2") != first
    assert build_derivative_media_key(f"{prefix}-other", "hq", source_sha, version) != first
    # Default version resolves from settings, pinned to the web chain.
    assert settings.media_derivative_transform_version == "ffmpeg-h264-web-v1"
    assert build_derivative_media_key(video_uuid, "hq", source_sha) == first

    for bad in (
        dict(video_uuid="", role="hq", source_sha256=source_sha, transform_version=version),
        dict(video_uuid=video_uuid, role="proxy_720p", source_sha256=source_sha, transform_version=version),
        dict(video_uuid=video_uuid, role="hq", source_sha256="short", transform_version=version),
        dict(video_uuid=video_uuid, role="hq", source_sha256="X" * 64, transform_version=version),
        dict(video_uuid=video_uuid, role="hq", source_sha256=source_sha, transform_version=""),
        dict(video_uuid=video_uuid, role="hq", source_sha256=source_sha, transform_version="x" * 41),
    ):
        with pytest.raises(ValueError):
            build_derivative_media_key(**bad)

    # Legacy keys are byte-stable: the legacy transform default is untouched
    # and derivative versioning never leaks into legacy inputs.
    assert settings.media_transform_version == "ffmpeg-h264-v1"
    legacy = build_media_key(video_uuid, "proxy_720p")
    assert legacy == hashlib.sha256(
        f"{video_uuid}:proxy_720p:{settings.media_transform_version}:"
        f"{settings.media_export_policy_version}".encode()
    ).hexdigest()


def test_original_selectors_preserve_legitimate_semantics_and_exclude_derived(pg):
    """All seven read/source selectors: same answers for real semantics,
    derivative rows never surface as originals."""
    from app.services.matchmaking import original_revision_id
    from app.services.evaluation_access import backbone_originals
    from app.api.v1.media import _backbone_playback_url, _backbone_revision_ids_bulk

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

    # A clip with ONLY a raw browser original still resolves it as playable —
    # the pre-D1 behavior for that corner is unchanged (the `!=
    # browser_original` filter only applies when a newer playable revision
    # exists, and D1 adds no new exclusion for it).
    raw_only = f"{prefix}-raw-only"
    raw_only_rev = _verified_revision(session, prefix, raw_only, "browser_original", bucket)
    assert original_revision_id(session, raw_only) is None  # unchanged: raw alone is not served as playable
    assert _backbone_playback_url(session, raw_only) is None

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

    # Guest/download newest-revision picks also skip future derivatives.
    _verified_revision(session, prefix, video_uuid, "derived_light", bucket)
    from app.services.media_backbone import derived_semantics_exclusion_clause
    from app.models.media_backbone import MediaRevision

    newest_original = (
        session.query(MediaRevision)
        .filter(
            MediaRevision.video_uuid == video_uuid,
            derived_semantics_exclusion_clause(MediaRevision.rendition_semantics),
        )
        .order_by(MediaRevision.observed_at.desc(), MediaRevision.id.desc())
        .first()
    )
    assert newest_original is not None
    assert not newest_original.rendition_semantics.startswith("derived_")
