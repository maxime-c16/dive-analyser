"""Batched reclaim-orphan drain: bounded lookups, dedup, fail-closed (SQLite).

Covers review comment on ``drain_reclaim_orphans`` (media_cache.py): one
lookup per queued path scans ``MediaJob.upload_tmp_path`` N times. The
drain must use batched ``IN`` reference lookups instead — bounded bind
chunks, stable-order dedup, zero queries when empty, fail-closed files on
DB error, and referenced paths (even shared by several jobs) preserved.
"""

import math

import pytest

from app.models.media import MediaJob
from app.models.photos_asset import PhotosAsset
from app.services.media_cache import drain_reclaim_orphans, queue_reclaim_orphans

# Review bound: lookup chunks carry at most this many binds (SQLite/PG
# limits). Tests use the literal, never the implementation constant.
MAX_BINDS_PER_LOOKUP = 500


def _asset(test_db):
    asset = PhotosAsset(video_uuid="22222222-2222-2222-2222-222222222222", media_type="video")
    test_db.add(asset)
    test_db.flush()
    return asset


def _job_with_tmp(test_db, asset, media_key, tmp_path_str):
    job = MediaJob(
        photos_asset_id=asset.id,
        media_key=media_key,
        rendition="poster",
        status="claimed",
        upload_tmp_path=tmp_path_str,
    )
    test_db.add(job)
    test_db.flush()
    return job


class _ExecuteCounter:
    """Count Session.execute calls without changing their behaviour."""

    def __init__(self, session):
        self.calls = []
        self._orig = session.execute

    def __call__(self, *args, **kwargs):
        self.calls.append(args[0] if args else None)
        return self._orig(*args, **kwargs)


def test_drain_batches_lookups_dedups_and_protects_referenced(test_db, tmp_path, monkeypatch):
    asset = _asset(test_db)

    shared = tmp_path / "shared.bin"
    shared.write_bytes(b"shared-live")
    solo = tmp_path / "solo.bin"
    solo.write_bytes(b"solo-live")
    # Same tmp referenced by TWO jobs: still referenced, must be kept.
    _job_with_tmp(test_db, asset, "a" + "0" * 63, str(shared))
    _job_with_tmp(test_db, asset, "b" + "0" * 63, str(shared))
    _job_with_tmp(test_db, asset, "c" + "0" * 63, str(solo))
    test_db.commit()

    n_unique = 1050
    orphans = []
    for i in range(n_unique):
        p = tmp_path / f"orphan-{i:05d}.bin"
        p.write_bytes(b"x")
        orphans.append(str(p))
    # Duplicates: same paths queued again must not cost extra lookups.
    queued = orphans + orphans[:120] + [str(shared)] * 3 + [str(solo)] * 2
    queue_reclaim_orphans(test_db, queued)
    test_db.commit()

    counter = _ExecuteCounter(test_db)
    monkeypatch.setattr(test_db, "execute", counter, raising=False)
    removed = drain_reclaim_orphans(test_db)

    assert removed == n_unique
    assert shared.read_bytes() == b"shared-live"
    assert solo.read_bytes() == b"solo-live"
    assert not (tmp_path / "orphan-00000.bin").exists()
    assert not (tmp_path / f"orphan-{n_unique - 1:05d}.bin").exists()

    unique_count = n_unique + 2
    expected_batches = math.ceil(unique_count / MAX_BINDS_PER_LOOKUP)
    assert expected_batches >= 2
    # Bounded batches: far fewer queries than queued paths, but more than
    # one — a single unbounded IN would be 1, per-path would be len(queued).
    assert len(counter.calls) == expected_batches
    assert len(counter.calls) < len(queued) // 10


def test_drain_empty_queue_runs_zero_queries(test_db, monkeypatch):
    counter = _ExecuteCounter(test_db)
    monkeypatch.setattr(test_db, "execute", counter, raising=False)
    assert drain_reclaim_orphans(test_db) == 0
    assert counter.calls == []


def test_drain_db_error_keeps_all_files(test_db, tmp_path, monkeypatch):
    victim = tmp_path / "victim.bin"
    victim.write_bytes(b"keep-me")
    queue_reclaim_orphans(test_db, [str(victim)])
    test_db.commit()

    def _boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(test_db, "execute", _boom, raising=False)
    assert drain_reclaim_orphans(test_db) == 0
    assert victim.read_bytes() == b"keep-me"


def test_reference_lookup_compiles_on_sqlite_and_postgres():
    """The batched IN select must compile on both query dialects."""
    from sqlalchemy import select
    from sqlalchemy.dialects import sqlite

    from app.models.media import MediaJob as _Job

    chunk = [f"/tmp/q-{i}.staging" for i in range(MAX_BINDS_PER_LOOKUP)]
    stmt = select(_Job.upload_tmp_path).where(_Job.upload_tmp_path.in_(chunk))
    stmt.compile(dialect=sqlite.dialect())
    pg = pytest.importorskip("sqlalchemy.dialects.postgresql")
    stmt.compile(dialect=pg.dialect())
