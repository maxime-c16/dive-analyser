"""Canary 2 GiB budget on real PostgreSQL (disposable calendar_test_* only).

Wired into the CI ``postgres`` tier (``ci/postgres.sh``). Proves what SQLite
cannot (advisory xact locks, concurrent TX, real UNIQUE/B-tree behavior):

- two concurrent attempts for DIFFERENT objects with combined size > cap:
  exactly one commits, the other fails with ``CanaryBudgetExceeded``
  (advisory lock serializes the short reservation TX; no overshoot);
- an orphan reservation (reserved, never promoted) survives the publisher
  unit's rollback and stays counted (monotonic, never released);
- same-identity replay dedupes: same (bucket, key, sha, size) costs nothing
  new, and the verified-reuse path skips the second PUT (no new B2
  version; safe-put semantics);
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

    # Create ONLY the owned ledger table — never the full metadata (some
    # legacy tables carry non-portable defaults). Idempotent (checkfirst).
    tables = [Base.metadata.tables["canary_slot_reservations"]]
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
        insp = inspect(engine)
        assert insp.has_table("canary_slot_reservations"), "ledger table missing"
        cols = {c["name"]: c for c in insp.get_columns("canary_slot_reservations")}
        for name in ("object_sha256", "size_bytes", "bucket", "object_key",
                     "environment", "job_id", "slot", "status", "created_at"):
            assert name in cols, f"ledger missing column {name}"
        indexes = {i["name"] for i in insp.get_indexes("canary_slot_reservations")} | {
            u["name"] for u in insp.get_unique_constraints("canary_slot_reservations")
        }
        assert "uq_canary_slot_reservation_bucket_key" in indexes, (
            f"exact-key unique index missing: {sorted(indexes)}"
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


def test_orphan_survives_publisher_rollback_and_same_key_dedupes():
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
            # Same-identity replay dedupes: no new charge, same remaining.
            remaining1 = reserve_canary_upload(
                db, sha, 4096, job_id=7, slot="light",
                bucket="pgtest-bucket", object_key=key, environment="dev",
            )
            assert canary_accounted_bytes(db) == before + 4096
            # Same key, different bytes fails closed (corrupt claim).
            with pytest.raises(ValueError):
                reserve_canary_upload(
                    db, _sha(f"{ns}-other".encode()), 4096, job_id=8, slot="light",
                    bucket="pgtest-bucket", object_key=key, environment="dev",
                )
            assert remaining1 is not None
        finally:
            try:
                db.close()
            except Exception:
                pass
        # One row for this namespace (dedupe, not two versions charged).
        with factory() as db2:
            rows = db2.execute(
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
