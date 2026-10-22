"""Canary 2 GiB budget on real PostgreSQL (disposable calendar_test_* only).

Wired into the CI ``postgres`` tier (``ci/postgres.sh``). Proves what SQLite
cannot (advisory xact locks, concurrent TX, real UNIQUE/B-tree behavior):

- two concurrent attempts for DIFFERENT objects with combined size > cap:
  exactly one commits, the other fails with ``CanaryBudgetExceeded``
  (advisory lock serializes the short reservation TX; no overshoot);
- an orphan reservation (reserved, never promoted) survives the publisher
  unit's rollback and stays counted (monotonic, never released);
- the SAME key attempted twice (same SHA/size) charges TWICE -- each PUT
  may store a new B2 version, and concurrent racers that both miss the
  pre-PUT reuse GET each PUT, so per-attempt charging is the bound (the
  one-package lease does NOT serialize duplicate HTTP); a verified reuse
  (same key already proves the bytes) skips the PUT and charges nothing;
- two concurrent same-key attempts serialize on the advisory lock and
  each charge; two concurrent attempts whose combined size overshoots
  the cap elect exactly one winner (the loser fails before its PUT);
- migration/model parity: the ``canary_slot_reservations`` table carries
  the exact-key columns + unique (bucket, object_key) index, the apply is
  idempotent (re-runnable), and this file never touches other tables'
  data (own-namespace rows only, parameterized deletes, no TRUNCATE, no
  DROP of public objects).

No real B2 (thread-safe in-memory S3 fake). No prod DB: refuses anything
but ``calendar_test_*``.
"""

import hashlib
import os
import threading
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[2]
PG_URL = os.environ.get("CALENDAR_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not PG_URL, reason="Disposable PostgreSQL required")


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _engine():
    assert PG_URL, "CALENDAR_TEST_DATABASE_URL is required"
    url = make_url(PG_URL)
    assert url.get_backend_name() == "postgresql", "PostgreSQL only"
    assert (url.database or "").startswith("calendar_test_"), (
        "Disposable calendar_test_* database required — refusing anything else"
    )
    return create_engine(url.set(drivername="postgresql+psycopg2"))


def _make_tables(engine):
    from app.database import Base
    from app.models.media_backbone import (  # noqa: F401 — mapper registration
        MediaBlob,
        MediaBlobLocation,
        MediaDerivative,
        MediaRevision,
    )

    # The ledger table plus the backbone tables the READY-baseline probe
    # reads (per-exact-object, ALWAYS counted plus all charges). Never the
    # full metadata (some legacy tables carry non-portable defaults).
    # Idempotent (checkfirst).
    tables = [
        Base.metadata.tables["canary_slot_reservations"],
        MediaBlob.__table__,
        MediaBlobLocation.__table__,
        MediaRevision.__table__,
        MediaDerivative.__table__,
    ]
    Base.metadata.create_all(bind=engine, tables=tables, checkfirst=True)
    # Idempotency proof: a second create_all must be a no-op, not an error.
    Base.metadata.create_all(bind=engine, tables=tables, checkfirst=True)


def _ns() -> str:
    return f"pgcb-{uuid4().hex[:10]}"


def _cleanup_keys(engine, like: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM canary_slot_reservations WHERE object_key LIKE :p"),
            {"p": like},
        )


class _Body:
    def __init__(self, data: bytes):
        import io as _io

        self._buf = _io.BytesIO(data)

    def iter_chunks(self, chunk_size=1024 * 1024):
        while True:
            piece = self._buf.read(chunk_size)
            if piece:
                yield piece
            else:
                break

    def close(self):
        pass


class _FakeS3:
    def __init__(self):
        self.objects: dict = {}
        self.uploads = 0
        self._lock = threading.Lock()

    def upload_file(self, path, bucket, key, ExtraArgs=None):
        from pathlib import Path as _P

        with self._lock:
            self.uploads += 1
            self.objects[(bucket, key)] = _P(path).read_bytes()

    def get_object(self, Bucket, Key):
        with self._lock:
            data = self.objects[(Bucket, Key)]
        return {"Body": _Body(data)}


def test_migration_model_parity_exact_key():
    engine = _engine()
    try:
        _make_tables(engine)
        # The additive SQL migrations must apply cleanly on top of the
        # model-created table (idempotent re-runs) on real PostgreSQL.
        # NOTE: executed via driver SQL (not sqlalchemy text()), because
        # the file comments contain "[:2]" slices that text() would parse
        # as bind parameters. Production applies via psql (unaffected).
        for fname in (
            "add_canary_slot_reservations.sql",
            "add_canary_slot_reservation_exact_key.sql",
            "add_canary_put_attempt_charges.sql",
        ):
            sql = (REPO_ROOT / "backend" / "migrations" / fname).read_text()
            with engine.begin() as conn:
                conn.exec_driver_sql(sql)
            with engine.begin() as conn:
                conn.exec_driver_sql(sql)  # second apply is a no-op
        insp = inspect(engine)
        assert insp.has_table("canary_slot_reservations"), "ledger table missing"
        cols = {c["name"]: c for c in insp.get_columns("canary_slot_reservations")}
        for name in ("object_sha256", "size_bytes", "bucket", "object_key",
                     "environment", "job_id", "slot", "status", "created_at"):
            assert name in cols, f"ledger missing column {name}"
        indexes = {i["name"] for i in insp.get_indexes("canary_slot_reservations")} | {
            u["name"] for u in insp.get_unique_constraints("canary_slot_reservations")
        }
        # Per-PUT charging: same-key duplicates allowed, so the legacy
        # UNIQUE bucket+key constraint must be GONE (replaced by a plain
        # index); each PUT attempt inserts its own charge row.
        assert "uq_canary_slot_reservation_bucket_key" not in indexes, (
            f"UNIQUE bucket+key still present (same-key race would dedupe): {sorted(indexes)}"
        )
        assert "ix_canary_slot_reservation_bucket_key" in indexes, (
            f"bucket+key index missing: {sorted(indexes)}"
        )
        # Model parity: every model column exists in the applied table.
        from app.database import Base

        model_cols = {c.name for c in Base.metadata.tables["canary_slot_reservations"].columns}
        assert model_cols <= set(cols), f"model/table drift: {model_cols - set(cols)}"
    finally:
        engine.dispose()


def test_concurrent_distinct_objects_cap_one_fails():
    from app.services.canary_budget import CANARY_BUDGET_BYTES, CanaryBudgetExceeded

    engine = _engine()
    ns = _ns()
    like = f"%{ns}%"
    try:
        _make_tables(engine)
        names = [f"{ns}-A", f"{ns}-B"]
        # Each within the hq per-slot cap (1.2 GB); combined 2.4 GB > 2 GiB.
        size_each = 1_200_000_000
        assert 2 * size_each > CANARY_BUDGET_BYTES
        results: dict = {}
        barrier = threading.Barrier(2)

        def attempt(idx: int):
            from app.services.canary_budget import reserve_canary_upload

            sha = _sha(f"{ns}-obj-{idx}".encode())
            key = f"pgtest/{ns}/hq-ffmpeg-h264-web-v1-{sha}"
            factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
            db = factory()
            try:
                barrier.wait(timeout=30)
                reserve_canary_upload(
                    db, sha, size_each, job_id=100 + idx, slot="hq",
                    bucket="pgtest-bucket", object_key=key, environment="dev",
                )
                results[idx] = "reserved"
            except CanaryBudgetExceeded:
                try:
                    db.rollback()
                except Exception:
                    pass
                results[idx] = "budget-exceeded"
            except Exception as exc:  # fail loudly, never silently pass
                try:
                    db.rollback()
                except Exception:
                    pass
                results[idx] = f"error:{type(exc).__name__}"
            finally:
                try:
                    db.close()
                except Exception:
                    pass

        threads = [threading.Thread(target=attempt, args=(i,)) for i in (0, 1)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        assert sorted(results.values()) == ["budget-exceeded", "reserved"], results
        # Exactly one row persisted for this namespace.
        with sessionmaker(bind=engine)() as db:
            rows = db.execute(
                text("SELECT COUNT(*) FROM canary_slot_reservations "
                     "WHERE object_key LIKE :p"),
                {"p": like},
            ).scalar_one()
            assert int(rows) == 1
    finally:
        try:
            _cleanup_keys(engine, like)
        finally:
            engine.dispose()


def test_orphan_survives_publisher_rollback_and_same_key_charges_again():
    from app.services.canary_budget import canary_accounted_bytes, reserve_canary_upload

    engine = _engine()
    ns = _ns()
    like = f"%{ns}%"
    try:
        _make_tables(engine)
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        sha = _sha(f"{ns}-orphan".encode())
        key = f"pgtest/{ns}/light-ffmpeg-h264-web-v1-{sha}"
        db = factory()
        try:
            before = canary_accounted_bytes(db)
            reserve_canary_upload(
                db, sha, 4096, job_id=7, slot="light",
                bucket="pgtest-bucket", object_key=key, environment="dev",
            )
            # Simulate the publisher unit rolling back AFTER the reservation
            # commit: the orphan row must survive (separate committed TX).
            db.rollback()
            assert canary_accounted_bytes(db) == before + 4096
            # Same-key retry is a NEW PUT attempt: charges AGAIN (each PUT
            # may store a new version). Only verified reuse avoids charge.
            reserve_canary_upload(
                db, sha, 4096, job_id=7, slot="light",
                bucket="pgtest-bucket", object_key=key, environment="dev",
            )
            assert canary_accounted_bytes(db) == before + 8192
            # Same key, different bytes fails closed (corrupt claim): no charge.
            with pytest.raises(ValueError):
                reserve_canary_upload(
                    db, _sha(f"{ns}-other".encode()), 4096, job_id=8, slot="light",
                    bucket="pgtest-bucket", object_key=key, environment="dev",
                )
            assert canary_accounted_bytes(db) == before + 8192
        finally:
            try:
                db.close()
            except Exception:
                pass
        # Two charge rows for this namespace (per-PUT, not deduped).
        with factory() as db2:
            rows = db2.execute(
                text("SELECT COUNT(*) FROM canary_slot_reservations "
                     "WHERE object_key LIKE :p"),
                {"p": like},
            ).scalar_one()
            assert int(rows) == 2
    finally:
        try:
            _cleanup_keys(engine, like)
        finally:
            engine.dispose()


def test_verified_reuse_skips_second_put(tmp_path):
    from app.services.derivative_publisher import _upload_and_roundtrip_verify

    data = b"x" * 65536
    import hashlib as _hl

    sha = _hl.sha256(data).hexdigest()
    artifact = tmp_path / "slot.bin"
    artifact.write_bytes(data)
    s3 = _FakeS3()
    bucket, key = "pgtest-bucket", f"pgtest/{_ns()}/hq-ffmpeg-h264-web-v1-{sha}"
    _upload_and_roundtrip_verify(
        client=s3, bucket=bucket, key=key, local_path=artifact,
        content_type="video/mp4", derivative_sha=sha,
        derivative_size=len(data), attempt_reuse=True,
    )
    assert s3.uploads == 1
    # Second publish of the same bytes reuses the verified object: no new PUT.
    _upload_and_roundtrip_verify(
        client=s3, bucket=bucket, key=key, local_path=artifact,
        content_type="video/mp4", derivative_sha=sha,
        derivative_size=len(data), attempt_reuse=True,
    )
    assert s3.uploads == 1


def test_concurrent_same_key_both_charge():
    """Same-key racers that both miss the reuse GET each charge (PG lock)."""
    from app.services.canary_budget import canary_accounted_bytes

    engine = _engine()
    ns = _ns()
    like = f"%{ns}%"
    try:
        _make_tables(engine)
        sha = _sha(f"{ns}-samekey".encode())
        key = f"pgtest/{ns}/light-ffmpeg-h264-web-v1-{sha}"
        size_each = 4096
        results: dict = {}
        barrier = threading.Barrier(2)

        def attempt(idx: int):
            from app.services.canary_budget import reserve_canary_upload

            factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
            db = factory()
            try:
                barrier.wait(timeout=30)
                reserve_canary_upload(
                    db, sha, size_each, job_id=200 + idx, slot="light",
                    bucket="pgtest-bucket", object_key=key, environment="dev",
                )
                results[idx] = "reserved"
            except Exception as exc:  # fail loudly, never silently pass
                try:
                    db.rollback()
                except Exception:
                    pass
                results[idx] = f"error:{type(exc).__name__}"
            finally:
                try:
                    db.close()
                except Exception:
                    pass

        threads = [threading.Thread(target=attempt, args=(i,)) for i in (0, 1)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        assert results == {0: "reserved", 1: "reserved"}, results
        # Two charge rows for the SAME key (per-PUT, never deduped).
        with sessionmaker(bind=engine)() as db:
            rows = db.execute(
                text("SELECT COUNT(*), COALESCE(SUM(size_bytes),0) "
                     "FROM canary_slot_reservations WHERE object_key LIKE :p"),
                {"p": like},
            ).one()
            assert int(rows[0]) == 2
            assert int(rows[1]) == 2 * size_each
    finally:
        try:
            _cleanup_keys(engine, like)
        finally:
            engine.dispose()


def test_concurrent_same_key_cap_one_wins_before_put():
    """Cap refuses the second same-key racer before its PUT (PG lock)."""
    from app.services.canary_budget import CANARY_BUDGET_BYTES, CanaryBudgetExceeded

    engine = _engine()
    ns = _ns()
    like = f"%{ns}%"
    try:
        _make_tables(engine)
        from app.services.canary_budget import canary_accounted_bytes

        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        size_each = 4096
        # Pre-fill to cap - size_each with this namespace's rows: room for
        # exactly ONE more attempt of size_each.
        db0 = factory()
        try:
            from app.services.canary_budget import reserve_canary_upload

            before_ns = canary_accounted_bytes(db0)
            _ = before_ns
            remaining_fill = CANARY_BUDGET_BYTES - before_ns - size_each
            assert remaining_fill > 0
            idx = 0
            # hq chunks (<=1.2G) then light chunks (<=700M).
            while remaining_fill > 0:
                chunk = min(remaining_fill, 700_000_000)
                fsha = _sha(f"{ns}-capfill-{idx}".encode())
                fkey = f"pgtest/{ns}/capfill-{idx}-{fsha}"
                reserve_canary_upload(
                    db0, fsha, chunk, job_id=300 + idx, slot="light",
                    bucket="pgtest-bucket", object_key=fkey, environment="dev",
                )
                remaining_fill -= chunk
                idx += 1
        finally:
            try:
                db0.close()
            except Exception:
                pass
        sha = _sha(f"{ns}-caprace".encode())
        key = f"pgtest/{ns}/light-ffmpeg-h264-web-v1-{sha}"
        results: dict = {}
        barrier = threading.Barrier(2)

        def attempt(idx: int):
            from app.services.canary_budget import reserve_canary_upload

            db = factory()
            try:
                barrier.wait(timeout=30)
                reserve_canary_upload(
                    db, sha, size_each, job_id=400 + idx, slot="light",
                    bucket="pgtest-bucket", object_key=key, environment="dev",
                )
                results[idx] = "reserved"
            except CanaryBudgetExceeded:
                try:
                    db.rollback()
                except Exception:
                    pass
                results[idx] = "budget-exceeded"
            except Exception as exc:
                try:
                    db.rollback()
                except Exception:
                    pass
                results[idx] = f"error:{type(exc).__name__}"
            finally:
                try:
                    db.close()
                except Exception:
                    pass

        threads = [threading.Thread(target=attempt, args=(i,)) for i in (0, 1)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        assert sorted(results.values()) == ["budget-exceeded", "reserved"], results
        # Exactly one charge row for the raced key.
        with factory() as db2:
            rows = db2.execute(
                text("SELECT COUNT(*) FROM canary_slot_reservations "
                     "WHERE object_key = :k"),
                {"k": key},
            ).scalar_one()
            assert int(rows) == 1
    finally:
        try:
            _cleanup_keys(engine, like)
        finally:
            engine.dispose()
