"""Fail-closed canary budget regressions (SQLite + PG when available, no prod/B2).

Authoritative budget proof must NEVER return a false 0 when the DB
proof is incomplete. Every case below must raise (no silent 0) and
must not insert a new charge row / must not authorize a PUT:

- ledger query error (DBAPI failure)
- missing ledger table (migration not applied)
- missing baseline tables (media_derivatives / media_blobs)
- NULL / negative / zero ledger sizes
- NULL / non-positive baseline blob sizes
- unbounded scans (>5000 rows) on ledger and baseline
- misconfigured scope lookup must raise, not return False

PG section (skipped without CALENDAR_TEST_DATABASE_URL) proves the
same fail-closed behavior on real PostgreSQL, including the
SAVEPOINT-isolated baseline probe (a baseline failure must not poison
the caller's transaction with InFailedSqlTransaction).
"""

import hashlib

import pytest
from sqlalchemy import text

from app.services.canary_budget import (
    CanaryBudgetExceeded,
    canary_accounted_bytes,
    canary_ledger_bytes,
    canary_legacy_ready_bytes,
    canary_reserved_bytes,
    canary_reserved_keys,
    canary_reserved_shas,
    canary_scope_for_job_id,
    check_publish_budget,
    db_admitted_uuids,
    reserve_canary_upload,
)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _reserve_kwargs(sha: str, size: int, tag: str = "a"):
    return {
        "sha256": sha,
        "size_bytes": size,
        "job_id": 1,
        "slot": "light",
        "bucket": "test-bucket",
        "object_key": f"blobs/sha256/{sha[:2]}/light-ffmpeg-h264-web-v1-{tag}-{sha}",
        "environment": "dev",
    }


def _ledger_count(db) -> int:
    from app.models.canary_ledger import CanarySlotReservation

    try:
        return int(db.query(CanarySlotReservation).count())
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return -1


def test_reserved_bytes_query_error_raises_no_false_zero(test_db, monkeypatch):
    sha = _sha(b"failclosed-qerr")
    reserve_canary_upload(test_db, **_reserve_kwargs(sha, 1000, tag="q0"))
    assert canary_accounted_bytes(test_db) >= 1000
    before = _ledger_count(test_db)

    def _boom(*a, **k):
        raise RuntimeError("injected query failure")

    monkeypatch.setattr(test_db, "query", _boom)
    with pytest.raises(Exception):
        canary_reserved_bytes(test_db)
    with pytest.raises(Exception):
        canary_accounted_bytes(test_db)
    with pytest.raises(Exception):
        check_publish_budget(test_db, 10)
    with pytest.raises(Exception):
        reserve_canary_upload(test_db, **_reserve_kwargs(_sha(b"q1"), 10, tag="q1"))
    # No new charge row may have been committed by the failed reserve.
    # (query is broken so count itself is unverifiable; restore first.)
    monkeypatch.undo()
    test_db.rollback()
    assert _ledger_count(test_db) == before


def test_missing_ledger_table_fails_without_put(test_db):
    sha = _sha(b"failclosed-noledeger")
    test_db.execute(text("DROP TABLE canary_slot_reservations"))
    with pytest.raises(CanaryBudgetExceeded):
        canary_reserved_bytes(test_db)
    with pytest.raises(CanaryBudgetExceeded):
        canary_reserved_keys(test_db)
    with pytest.raises(CanaryBudgetExceeded):
        canary_reserved_shas(test_db)
    with pytest.raises(CanaryBudgetExceeded):
        canary_accounted_bytes(test_db)
    with pytest.raises(CanaryBudgetExceeded):
        canary_ledger_bytes(test_db)
    with pytest.raises(CanaryBudgetExceeded):
        check_publish_budget(test_db, 10)
    with pytest.raises(CanaryBudgetExceeded):
        reserve_canary_upload(test_db, **_reserve_kwargs(sha, 10, tag="miss"))
    # Still missing: no row could have been charged.
    with pytest.raises(Exception):
        test_db.execute(text("SELECT COUNT(*) FROM canary_slot_reservations")).scalar()


def test_missing_baseline_table_fails_closed(test_db):
    test_db.execute(text("DROP TABLE media_derivatives"))
    test_db.rollback()
    with pytest.raises(CanaryBudgetExceeded):
        canary_legacy_ready_bytes(test_db)
    with pytest.raises(CanaryBudgetExceeded):
        canary_accounted_bytes(test_db)
    with pytest.raises(CanaryBudgetExceeded):
        check_publish_budget(test_db, 10)
    with pytest.raises(CanaryBudgetExceeded):
        reserve_canary_upload(test_db, **_reserve_kwargs(_sha(b"nobs"), 10, tag="nobs"))


def test_missing_blob_table_fails_closed_with_ready_row(test_db):
    from app.models.media_backbone import MediaBlob, MediaDerivative
    from app.models.photos_asset import PhotosAsset
    from app.models.media_backbone import MediaBlobLocation, MediaRevision

    from app.config import get_settings

    settings = get_settings()
    video_uuid = "clip-failclosed-blob"
    raw = b"src-bytes"
    sha = _sha(raw + video_uuid.encode())
    test_db.add(PhotosAsset(video_uuid=video_uuid))
    test_db.flush()
    test_db.add(MediaBlob(sha256=sha, byte_size=len(raw), storage_backend="b2",
                          bucket=settings.media_backbone_prod_bucket,
                          object_key=f"blobs/sha256/{sha[:2]}/{sha}",
                          width=1280, height=720, duration_seconds=10.0))
    dsha = _sha(b"deriv-failclosed")
    test_db.add(MediaBlob(sha256=dsha, byte_size=1000, storage_backend="b2",
                          bucket=settings.media_backbone_prod_bucket,
                          object_key=f"blobs/sha256/{dsha[:2]}/{dsha}"))
    test_db.add(MediaDerivative(video_uuid=video_uuid, source_blob_sha256=sha,
                                role="light", transform_version="ffmpeg-h264-web-v1",
                                derivative_blob_sha256=dsha, status="ready"))
    test_db.commit()
    # Drop the blob table AFTER seeding a READY row: baseline sizes are now
    # unverifiable and must raise, never silently count 0.
    test_db.execute(text("DROP TABLE media_blobs"))
    test_db.rollback()
    with pytest.raises(CanaryBudgetExceeded):
        canary_legacy_ready_bytes(test_db)
    with pytest.raises(CanaryBudgetExceeded):
        canary_accounted_bytes(test_db)


def test_invalid_ledger_sizes_fail_closed(test_db):
    from sqlalchemy.exc import IntegrityError

    sha_ok = _sha(b"ok-size")
    reserve_canary_upload(test_db, **_reserve_kwargs(sha_ok, 100, tag="ok"))
    # NULL size is blocked by the NOT NULL schema itself (fail closed at
    # write): no charge row, no PUT.
    sha_null = _sha(b"null-size")
    with pytest.raises(IntegrityError):
        test_db.execute(
            text("INSERT INTO canary_slot_reservations "
                 "(object_sha256, size_bytes, bucket, object_key, environment, job_id, slot, status, created_at) "
                 "VALUES (:sha, NULL, :bkt, :key, 'dev', 2, 'light', 'reserved', CURRENT_TIMESTAMP)"),
            {"sha": sha_null, "bkt": "test-bucket",
             "key": f"blobs/sha256/{sha_null[:2]}/light-ffmpeg-h264-web-v1-null-{sha_null}"},
        )
    test_db.rollback()
    assert canary_reserved_bytes(test_db) >= 100
    # Negative size (no CHECK in ORM-created SQLite; PG migration has
    # CHECK>0): the read path must refuse.
    sha_neg = _sha(b"neg-size")
    test_db.execute(
        text("INSERT INTO canary_slot_reservations "
             "(object_sha256, size_bytes, bucket, object_key, environment, job_id, slot, status, created_at) "
             "VALUES (:sha, -5, :bkt, :key, 'dev', 3, 'light', 'reserved', CURRENT_TIMESTAMP)"),
        {"sha": sha_neg, "bkt": "test-bucket",
         "key": f"blobs/sha256/{sha_neg[:2]}/light-ffmpeg-h264-web-v1-neg-{sha_neg}"},
    )
    with pytest.raises(CanaryBudgetExceeded):
        canary_reserved_bytes(test_db)
    test_db.rollback()
    # Zero size.
    sha_zero = _sha(b"zero-size")
    test_db.execute(
        text("INSERT INTO canary_slot_reservations "
             "(object_sha256, size_bytes, bucket, object_key, environment, job_id, slot, status, created_at) "
             "VALUES (:sha, 0, :bkt, :key, 'dev', 4, 'light', 'reserved', CURRENT_TIMESTAMP)"),
        {"sha": sha_zero, "bkt": "test-bucket",
         "key": f"blobs/sha256/{sha_zero[:2]}/light-ffmpeg-h264-web-v1-zero-{sha_zero}"},
    )
    with pytest.raises(CanaryBudgetExceeded):
        canary_reserved_bytes(test_db)
    test_db.rollback()


def test_invalid_baseline_blob_sizes_fail_closed(test_db):
    from sqlalchemy.exc import IntegrityError

    from app.config import get_settings
    from app.models.media_backbone import MediaBlob, MediaDerivative
    from app.models.photos_asset import PhotosAsset

    settings = get_settings()
    # NULL blob size is blocked by the NOT NULL schema (fail closed at write).
    video_uuid = "clip-failclosed-nullblob-probe"
    raw = b"src-nullblob"
    sha = _sha(raw + video_uuid.encode())
    dsha = _sha(b"deriv-nullblob")
    test_db.add(PhotosAsset(video_uuid=video_uuid))
    test_db.flush()
    test_db.add(MediaBlob(sha256=sha, byte_size=len(raw), storage_backend="b2",
                          bucket=settings.media_backbone_prod_bucket,
                          object_key=f"blobs/sha256/{sha[:2]}/{sha}",
                          width=1280, height=720, duration_seconds=10.0))
    test_db.commit()
    with pytest.raises(IntegrityError):
        test_db.execute(
            text("INSERT INTO media_blobs (sha256, byte_size, storage_backend, bucket, object_key) "
                 "VALUES (:sha, NULL, 'b2', :bkt, :key)"),
            {"sha": dsha, "bkt": settings.media_backbone_prod_bucket,
             "key": f"blobs/sha256/{dsha[:2]}/{dsha}"},
        )
    test_db.rollback()
    test_db.execute(text("DELETE FROM media_blobs WHERE sha256 = :s"), {"s": sha})
    test_db.execute(text("DELETE FROM photos_assets WHERE video_uuid = :u"), {"u": video_uuid})
    test_db.commit()
    for tag, bad_size in (("negblob", -7), ("zeroblob", 0)):
        video_uuid = f"clip-failclosed-{tag}"
        raw = f"src-{tag}".encode()
        sha = _sha(raw + video_uuid.encode())
        dsha = _sha(f"deriv-{tag}".encode())
        test_db.add(PhotosAsset(video_uuid=video_uuid))
        test_db.flush()
        test_db.add(MediaBlob(sha256=sha, byte_size=len(raw), storage_backend="b2",
                              bucket=settings.media_backbone_prod_bucket,
                              object_key=f"blobs/sha256/{sha[:2]}/{sha}",
                              width=1280, height=720, duration_seconds=10.0))
        # Insert the derivative blob with the bad size via the ORM (SQLite
        # has no CHECK>0; PG migration does -- the read path must refuse).
        test_db.add(MediaBlob(sha256=dsha, byte_size=bad_size, storage_backend="b2",
                              bucket=settings.media_backbone_prod_bucket,
                              object_key=f"blobs/sha256/{dsha[:2]}/{dsha}"))
        test_db.add(MediaDerivative(video_uuid=video_uuid, source_blob_sha256=sha,
                                    role="light", transform_version="ffmpeg-h264-web-v1",
                                    derivative_blob_sha256=dsha, status="ready"))
        test_db.commit()
        with pytest.raises(CanaryBudgetExceeded):
            canary_legacy_ready_bytes(test_db)
        with pytest.raises(CanaryBudgetExceeded):
            canary_accounted_bytes(test_db)
        # Clean the bad READY row + blob so later tags start clean.
        test_db.execute(text("DELETE FROM media_derivatives WHERE video_uuid = :u"),
                        {"u": video_uuid})
        test_db.execute(text("DELETE FROM media_blobs WHERE sha256 = :s"), {"s": dsha})
        test_db.execute(text("DELETE FROM media_blobs WHERE sha256 = :s"), {"s": sha})
        test_db.execute(text("DELETE FROM photos_assets WHERE video_uuid = :u"), {"u": video_uuid})
        test_db.commit()


def test_ledger_bounded_scan_refuses_over_cap(test_db):
    from app.models.canary_ledger import CanarySlotReservation

    rows = [
        CanarySlotReservation(
            object_sha256=_sha(f"bound-{i}".encode()),
            size_bytes=1,
            bucket="test-bucket",
            object_key=f"blobs/sha256/ab/light-ffmpeg-h264-web-v1-bound-{i}-{_sha(f'bound-{i}'.encode())}",
            environment="dev",
            job_id=i,
            slot="light",
            status="reserved",
        )
        for i in range(5001)
    ]
    test_db.bulk_save_objects(rows)
    test_db.commit()
    with pytest.raises(CanaryBudgetExceeded):
        canary_reserved_bytes(test_db)
    with pytest.raises(CanaryBudgetExceeded):
        canary_reserved_keys(test_db)
    with pytest.raises(CanaryBudgetExceeded):
        canary_reserved_shas(test_db)
    with pytest.raises(CanaryBudgetExceeded):
        canary_accounted_bytes(test_db)
    with pytest.raises(CanaryBudgetExceeded):
        check_publish_budget(test_db, 1)


def test_scope_lookup_error_raises_not_false(test_db, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("scope db down")

    monkeypatch.setattr(test_db, "get", _boom)
    with pytest.raises(Exception):
        canary_scope_for_job_id(test_db, 1)


def test_cohort_query_error_raises_not_empty(test_db, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("cohort db down")

    monkeypatch.setattr(test_db, "query", _boom)
    with pytest.raises(Exception):
        db_admitted_uuids(test_db)


# ---------------------------------------------------------------------------
# PostgreSQL fail-closed proof (disposable calendar_test_* only, skipped
# without CALENDAR_TEST_DATABASE_URL). Mirrors the SQLite regressions on
# the real backend: missing ledger/baseline must refuse (no false 0), and
# a baseline failure must not poison the caller's transaction (the
# SAVEPOINT-isolated probe re-raises fail-closed; a later reserve in the
# same unit still fails on its own terms, never with
# InFailedSqlTransaction).
# ---------------------------------------------------------------------------

import os as _os

_PG_URL = _os.environ.get("CALENDAR_TEST_DATABASE_URL")
_pg_requires = pytest.mark.skipif(not _PG_URL, reason="Disposable PostgreSQL required")


def _pg_engine():
    assert _PG_URL, "CALENDAR_TEST_DATABASE_URL is required"
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    url = make_url(_PG_URL)
    assert url.get_backend_name() == "postgresql", "PostgreSQL only"
    assert (url.database or "").startswith("calendar_test_"), (
        "Disposable calendar_test_* database required"
    )
    return create_engine(url.set(drivername="postgresql+psycopg2"))


def _pg_make_tables(engine):
    from app.database import Base
    from app.models.media_backbone import (  # noqa: F401
        MediaBlob,
        MediaBlobLocation,
        MediaDerivative,
        MediaRevision,
    )

    tables = [
        Base.metadata.tables["canary_slot_reservations"],
        MediaBlob.__table__,
        MediaBlobLocation.__table__,
        MediaRevision.__table__,
        MediaDerivative.__table__,
    ]
    Base.metadata.create_all(bind=engine, tables=tables, checkfirst=True)


@_pg_requires
def test_pg_missing_ledger_fails_without_put():
    from sqlalchemy.orm import sessionmaker

    engine = _pg_engine()
    try:
        from sqlalchemy import text as _text

        with engine.begin() as conn:
            conn.execute(_text("DROP TABLE IF EXISTS canary_slot_reservations"))
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        db = factory()
        try:
            with pytest.raises(CanaryBudgetExceeded):
                canary_reserved_bytes(db)
            with pytest.raises(CanaryBudgetExceeded):
                canary_accounted_bytes(db)
            with pytest.raises(CanaryBudgetExceeded):
                check_publish_budget(db, 10)
            with pytest.raises(CanaryBudgetExceeded):
                reserve_canary_upload(db, **_reserve_kwargs(_sha(b"pg-miss"), 10, tag="pgmiss"))
        finally:
            try:
                db.close()
            except Exception:
                pass
    finally:
        try:
            _pg_make_tables(engine)
        finally:
            engine.dispose()


@_pg_requires
def test_pg_baseline_failure_does_not_poison_tx():
    from sqlalchemy.orm import sessionmaker

    engine = _pg_engine()
    try:
        _pg_make_tables(engine)
        from sqlalchemy import text as _text

        with engine.begin() as conn:
            conn.execute(_text("DROP TABLE IF EXISTS media_derivatives"))
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        db = factory()
        try:
            with pytest.raises(CanaryBudgetExceeded):
                canary_legacy_ready_bytes(db)
            # Same unit, later reserve: must fail closed on its own terms
            # (missing baseline), never with InFailedSqlTransaction.
            try:
                reserve_canary_upload(db, **_reserve_kwargs(_sha(b"pg-poison"), 10, tag="pgpois"))
                raise AssertionError("reserve should have refused")
            except CanaryBudgetExceeded:
                pass
            except Exception as exc:
                assert "InFailedSql" not in type(exc).__name__, f"poisoned TX: {exc!r}"
                raise
        finally:
            try:
                db.close()
            except Exception:
                pass
    finally:
        try:
            _pg_make_tables(engine)
        finally:
            engine.dispose()
