"""Batched live-readiness scope: ``_live_ready_map`` batch bounds and merge semantics.

``catalog_summary`` and ``catalog_population_plan`` call ``_live_ready_map``
with every catalogued asset id. A single unbounded ``IN`` clause would exceed
database bind-parameter limits (SQLite ~999, Postgres ~65535) on large
catalogs. These tests pin the batch bound and prove multi-batch results merge
correctly while absent, out-of-scope and duplicate ids stay safe.
"""

import math

from sqlalchemy import event

from app.models.media import MediaCacheEntry
from app.models.photos_asset import PhotosAsset
from app.services import media_catalog
from app.services.media_catalog import (
    LIVE_CATALOG_RENDITIONS,
    _LIVE_READY_BATCH_SIZE,
    _live_ready_map,
)

# Lowest common driver ceiling: SQLite allows ~999 bound parameters per
# statement (Postgres allows ~65535, so SQLite is the binding constraint).
SQLITE_MAX_BINDS = 999


def _seed_asset(test_db, tag, ready_renditions=(), extra_entries=()):
    asset = PhotosAsset(video_uuid=f"live-batch-{tag}", cloud_guid=f"cloud-live-batch-{tag}")
    test_db.add(asset)
    test_db.flush()
    for index, rendition in enumerate(ready_renditions):
        test_db.add(MediaCacheEntry(
            photos_asset_id=asset.id,
            media_key=f"live-batch-{tag}-{rendition}-{index}-{asset.id}",
            rendition=rendition,
            storage_path=f"/tmp/live-batch-{tag}-{rendition}",
            content_type="video/mp4",
            size_bytes=100,
            status="ready",
        ))
    for index, (rendition, status) in enumerate(extra_entries):
        test_db.add(MediaCacheEntry(
            photos_asset_id=asset.id,
            media_key=f"live-batch-{tag}-extra-{index}-{asset.id}",
            rendition=rendition,
            storage_path=f"/tmp/live-batch-{tag}-extra-{index}",
            content_type="video/mp4",
            size_bytes=100,
            status=status,
        ))
    test_db.flush()
    return asset


def test_live_ready_batch_size_fits_sqlite_and_postgres_bind_limits():
    max_binds_per_batch = (
        _LIVE_READY_BATCH_SIZE + 1 + len(LIVE_CATALOG_RENDITIONS)
    )
    assert _LIVE_READY_BATCH_SIZE <= 500
    assert max_binds_per_batch <= SQLITE_MAX_BINDS


def test_live_ready_map_merges_batches_without_leaving_scope(test_db, monkeypatch):
    monkeypatch.setattr(media_catalog, "_LIVE_READY_BATCH_SIZE", 3)

    assets = [
        _seed_asset(test_db, "full", ("poster", "proxy_720p")),
        _seed_asset(test_db, "fallback", ("poster", "proxy_360p")),
        _seed_asset(test_db, "poster-only", ("poster",)),
        _seed_asset(test_db, "proxy-only", ("proxy_720p",)),
        _seed_asset(test_db, "empty"),
        # Non-ready entries must never count as live readiness.
        _seed_asset(test_db, "failed", (), (("proxy_720p", "failed"),)),
        _seed_asset(test_db, "queued", (), (("poster", "queued"),)),
    ]
    out_of_scope = _seed_asset(test_db, "out-of-scope", ("poster", "proxy_720p"))
    test_db.commit()

    absent_id = max([asset.id for asset in assets] + [out_of_scope.id]) + 1000
    query_ids = {asset.id for asset in assets} | {absent_id}
    # Duplicates and falsy ids must not change the scope or the queries.
    query_ids.update([assets[0].id, assets[0].id, 0, None])

    engine = test_db.get_bind()
    batch_param_counts: list[int] = []

    def _before_cursor(conn, cursor, statement, parameters, context, executemany):
        if "media_cache_entries" in statement and "photos_asset_id" in statement:
            batch_param_counts.append(len(parameters))

    event.listen(engine, "before_cursor_execute", _before_cursor)
    try:
        result = _live_ready_map(test_db, query_ids)
    finally:
        event.remove(engine, "before_cursor_execute", _before_cursor)

    # Eight unique in-scope ids over batches of three: three batched queries,
    # none of them unbounded, none of them touching the whole cache table.
    assert len(batch_param_counts) == math.ceil((len(assets) + 1) / 3)
    assert batch_param_counts, "expected batched live-readiness queries"
    assert max(batch_param_counts) <= 3 + 1 + len(LIVE_CATALOG_RENDITIONS)

    assert result[assets[0].id] == {"poster", "proxy_720p"}
    assert result[assets[1].id] == {"poster", "proxy_360p"}
    assert result[assets[2].id] == {"poster"}
    assert result[assets[3].id] == {"proxy_720p"}
    assert result[assets[4].id] == set()
    assert result[assets[5].id] == set()
    assert result[assets[6].id] == set()
    # Absent ids map to empty sets; out-of-scope cache rows never leak in.
    assert result[absent_id] == set()
    assert out_of_scope.id not in result
    assert 0 not in result
    assert sorted(result) == sorted({asset.id for asset in assets} | {absent_id})


def test_live_ready_map_empty_scope_queries_nothing(test_db):
    assert _live_ready_map(test_db, set()) == {}
    assert _live_ready_map(test_db, {0, None}) == {}
