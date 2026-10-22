"""Canary admit lock on real PostgreSQL (disposable calendar_test_* only).

Wired into the CI ``postgres`` tier (``ci/postgres.sh``). Proves what SQLite
cannot:

- the admit PG advisory xact lock serializes two concurrent short TX
  (second waiter blocks until the first commits);
- the ONE authoritative ``_decide_admission`` recomputes the DB cohort fresh
  on real PG SQL: 4 admitted passes for 1 new, then after a 5th commits +
  ``expire_all`` the same candidate is refused as 6th (no stale cap).

No real B2/prod: own-namespace rows only (``pgadmit-<uuid>`` uuids + keys),
parameterized deletes, no TRUNCATE/DROP. Skipped without PG_URL.
"""

import hashlib
import os
import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
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
        "Disposable calendar_test_* database required -- refusing anything else"
    )
    return create_engine(url.set(drivername="postgresql+psycopg2"))


def _make_tables(engine):
    from app.database import Base
    from app.models.canary_ledger import CanarySlotReservation  # noqa: F401
    from app.models.media import MediaJob  # noqa: F401
    from app.models.media_backbone import (  # noqa: F401
        MediaBlob,
        MediaBlobLocation,
        MediaDerivative,
        MediaRevision,
    )
    from app.models.photos_asset import PhotosAsset  # noqa: F401

    tables = [
        Base.metadata.tables["photos_assets"],
        Base.metadata.tables["media_jobs"],
        Base.metadata.tables["media_blobs"],
        Base.metadata.tables["media_blob_locations"],
        Base.metadata.tables["media_revisions"],
        Base.metadata.tables["media_derivatives"],
        Base.metadata.tables["canary_slot_reservations"],
    ]
    Base.metadata.create_all(bind=engine, tables=tables, checkfirst=True)
    Base.metadata.create_all(bind=engine, tables=tables, checkfirst=True)


def _ns() -> str:
    return f"pgadmit-{uuid4().hex[:8]}"


def _cleanup(engine, ns: str) -> None:
    like = f"{ns}%"
    with engine.begin() as conn:
        for tbl, col in (
            ("media_derivatives", "video_uuid"),
            ("media_revisions", "video_uuid"),
            ("media_jobs", None),
            ("photos_assets", "video_uuid"),
            ("media_blob_locations", "blob_sha256"),
            ("media_blobs", "sha256"),
        ):
            if col is None:
                continue
            conn.execute(
                text(f"DELETE FROM {tbl} WHERE {col} LIKE :p"), {"p": like}
            )
        # MediaJobs reference assets: delete jobs for namespaced assets.
        conn.execute(
            text(
                "DELETE FROM media_jobs WHERE photos_asset_id IN "
                "(SELECT id FROM photos_assets WHERE video_uuid LIKE :p)"
            ),
            {"p": like},
        )
        conn.execute(
            text("DELETE FROM canary_slot_reservations WHERE object_key LIKE :p"),
            {"p": f"%{ns}%"},
        )


def _seed_source(db, video_uuid, raw=b"camera-bytes-v1"):
    from app.config import get_settings
    from app.models.media_backbone import MediaBlob, MediaBlobLocation, MediaRevision
    from app.models.photos_asset import PhotosAsset

    sha = _sha(raw + video_uuid.encode())
    db.add(PhotosAsset(video_uuid=video_uuid))
    db.flush()
    s = get_settings()
    db.add(MediaBlob(sha256=sha, byte_size=len(raw), storage_backend="b2",
                     bucket=s.media_backbone_prod_bucket,
                     object_key=f"blobs/sha256/{sha[:2]}/{sha}",
                     width=1280, height=720, duration_seconds=10.0))
    db.add(MediaBlobLocation(blob_sha256=sha, environment="prod", storage_backend="b2",
                             bucket=s.media_backbone_prod_bucket,
                             object_key=f"blobs/sha256/{sha[:2]}/{sha}", verified=True))
    db.add(MediaRevision(video_uuid=video_uuid, blob_sha256=sha,
                         rendition_semantics="photos_edited_rendition"))
    db.commit()
    return sha


def _mk_job(db, video_uuid, status):
    from app.models.media import MediaJob
    from app.models.photos_asset import PhotosAsset
    from app.services.media_jobs import WEB_PACKAGE_RENDITION

    asset = db.query(PhotosAsset).filter(PhotosAsset.video_uuid == video_uuid).first()
    job = MediaJob(photos_asset_id=asset.id, media_key=f"mk-{video_uuid}-{status}",
                   rendition=WEB_PACKAGE_RENDITION, status=status,
                   request_reason="canary_web_package", priority=60,
                   attempts=0, max_attempts=2)
    db.add(job)
    db.commit()
    return job


def test_admit_advisory_lock_serializes():
    """Second xact waiter blocks until the first short TX commits (PG)."""
    from app.services.canary_budget import _CANARY_ADMIT_LOCK, _advisory_xact_lock

    engine = _engine()
    try:
        _make_tables(engine)
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        entered = threading.Event()
        release = threading.Event()
        order: list = []

        def first():
            db = factory()
            try:
                _advisory_xact_lock(db, _CANARY_ADMIT_LOCK)
                entered.set()
                assert release.wait(timeout=30)
                order.append("first-commit")
                db.commit()
            finally:
                try:
                    db.close()
                except Exception:
                    pass

        def second():
            assert entered.wait(timeout=30)
            db = factory()
            try:
                _advisory_xact_lock(db, _CANARY_ADMIT_LOCK)
                order.append("second-lock")
                db.commit()
            finally:
                try:
                    db.close()
                except Exception:
                    pass

        t1, t2 = threading.Thread(target=first), threading.Thread(target=second)
        t1.start()
        # Wait until t1 holds the xact lock, then let t2 block on it.
        assert entered.wait(timeout=30)
        time.sleep(0.2)
        t2.start()
        time.sleep(0.5)
        # t2 must still be blocked while t1 holds its transaction open.
        assert order == [], order
        release.set()
        t1.join(timeout=30)
        t2.join(timeout=30)
        assert order == ["first-commit", "second-lock"], order
    finally:
        engine.dispose()


def test_authoritative_cohort_recompute_on_pg(tmp_path):
    """4 admitted passes for 1 new; after a 5th commits the 6th refuses (PG)."""
    import importlib.util as _ilu

    engine = _engine()
    ns = _ns()
    try:
        _make_tables(engine)
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        db = factory()
        try:
            p = REPO_ROOT / "ops" / "canary_web_package.py"
            spec = _ilu.spec_from_file_location("canary_cli_pg_admit", p)
            ops = _ilu.module_from_spec(spec)
            spec.loader.exec_module(ops)
            clips4 = [f"{ns}-c{i}" for i in range(1, 5)]
            for uuid in clips4:
                _seed_source(db, uuid)
                _mk_job(db, uuid, "ready")
            cand = f"{ns}-new"
            _seed_source(db, cand)
            state = {"admitted": [], "ready_seen": [], "proven": [], "consecutive_failures": 0}
            ok = ops._decide_admission(
                db, phase=1, clips=[cand], phase1_cohort=None, state=dict(state),
                state_dir=tmp_path, fail_limit=2, host_facts_path=None,
                is_apply=False, mac_free_bytes=None, server_cache_free_bytes=None,
            )
            assert ok["uuid"] == cand
            # A 5th distinct clip commits (concurrent admit), then expire.
            race = f"{ns}-race"
            _seed_source(db, race)
            _mk_job(db, race, "ready")
            db.expire_all()
            with pytest.raises(Exception, match="phase 1 cumulative|REFUSED|cumulative"):
                try:
                    ops._decide_admission(
                        db, phase=1, clips=[cand], phase1_cohort=None,
                        state=dict(state), state_dir=tmp_path, fail_limit=2,
                        host_facts_path=None, is_apply=False,
                        mac_free_bytes=None, server_cache_free_bytes=None,
                    )
                except Exception as exc:
                    assert type(exc).__name__ in ("_AdmitRefused", "ValueError") or "cumulative" in str(exc)
                    raise
        finally:
            try:
                db.close()
            except Exception:
                pass
    finally:
        try:
            _cleanup(engine, ns)
        finally:
            engine.dispose()
