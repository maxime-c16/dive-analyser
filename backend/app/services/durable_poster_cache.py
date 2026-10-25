"""Copy durable posters into the local media cache for the Library grid.

The grid (POST /media/status/batch) serves posters from the local cache
only: nginx X-Accel bytes, browser-cacheable, no B2 grant/HEAD/302 per tile.
Durable web packages (B2 + ``media_derivatives``) carry a poster for every
migrated clip, but never wrote a cache row, so tiles fell back to loading a
video. This step closes that gap: once per clip, the server streams the
D5-servable poster (current source + transform, trusted PROD replica) from
B2, verifies its SHA-256 against the ledger, and records a ready ``poster``
cache entry. Bounded per call, idempotent, never overwrites an existing
cache row, never deletes anything. Network I/O runs with no open
transaction (production kills idle transactions after 30 s).
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from sqlalchemy import exists, func, select

from app.config import get_settings
from app.models.media import MediaCacheEntry
from app.models.media_backbone import MediaDerivative, MediaRevision
from app.models.photos_asset import PhotosAsset
from app.services.media_keys import build_media_key

BATCH = 40
# Candidates resolved per pass (each D5 resolution is a handful of
# queries). Sampled in random order so clips that are not (yet) servable
# can never wall off the rest of the backlog.
SCAN = 60
DRIFT_SAMPLE = 10
MAX_POSTER_BYTES = 5 * 1024 * 1024
# Keep the server cache above the package gate's floor.
MIN_FREE_BYTES = 26 * 1024**3


def _candidates(db, limit: int) -> list[tuple[int, str]]:
    """Assets with a ready durable poster but no poster cache row at all."""
    from app.services.derivative_read import _current_transform_version

    has_cache_row = exists().where(
        MediaCacheEntry.photos_asset_id == PhotosAsset.id,
        MediaCacheEntry.rendition == "poster",
    )
    has_durable_poster = exists().where(
        MediaDerivative.video_uuid == PhotosAsset.video_uuid,
        MediaDerivative.role == "poster",
        MediaDerivative.status == "ready",
        MediaDerivative.transform_version == _current_transform_version(),
    )
    # EXISTS (not JOIN + DISTINCT): PostgreSQL refuses DISTINCT with an
    # ORDER BY expression outside the select list.
    rows = db.execute(
        select(PhotosAsset.id, PhotosAsset.video_uuid)
        .where(has_durable_poster, ~has_cache_row)
        .order_by(func.random())
        .limit(limit)
    ).all()
    return [(int(asset_id), uuid) for asset_id, uuid in rows]


def _still_current(db, item: dict[str, Any]) -> bool:
    """Re-resolve D5 in the inserting transaction: the poster must still be
    the servable one for the clip's CURRENT source + transform."""
    from app.services.derivative_read import safe_resolve_clip_derivatives

    clip = safe_resolve_clip_derivatives(db, item["video_uuid"])
    decision = clip.roles.get("poster") if clip is not None else None
    if decision is None or decision.state != "ready" or not decision.revision_id:
        return False
    revision = db.get(MediaRevision, decision.revision_id)
    return (revision is not None and revision.blob_sha256.lower() == item["sha256"]
            and clip.source_sha256 == item["source_sha256"]
            and clip.transform_version == item["transform_version"])


def _plan_item(db, asset_id: int, video_uuid: str, replace_id: int | None = None) -> dict[str, Any] | None:
    """The D5-servable poster to copy for one clip, or None (fail closed)."""
    from app.services.derivative_read import safe_resolve_clip_derivatives
    from app.services.media_backbone import trusted_prod_location

    clip = safe_resolve_clip_derivatives(db, video_uuid)
    decision = clip.roles.get("poster") if clip is not None else None
    if decision is None or decision.state != "ready" or not decision.revision_id:
        return None
    revision = db.get(MediaRevision, decision.revision_id)
    if revision is None:
        return None
    location, deny = trusted_prod_location(db, revision.blob_sha256, get_settings().media_backbone_prod_bucket)
    if deny is not None:
        return None
    return {
        "asset_id": asset_id,
        "video_uuid": video_uuid,
        "sha256": revision.blob_sha256.lower(),
        "bucket": location.bucket,
        "object_key": location.object_key,
        "source_sha256": clip.source_sha256,
        "transform_version": clip.transform_version,
        "replace_id": replace_id,
    }


def _is_ours(entry: MediaCacheEntry | None) -> bool:
    """A row this module wrote (content-specific path), never a Mac poster."""
    return (entry is not None and entry.rendition == "poster" and bool(entry.checksum_sha256)
            and Path(entry.storage_path or "").stem.endswith(f"-d{entry.checksum_sha256[:16]}"))


def _drifted(db, sample: int) -> list[dict[str, Any]]:
    """Recovery: copies whose clip moved to a newer source/transform.

    Source changes are not serialized with this copy (the publisher's own
    drift guard is best-effort too), so a copy can land just before a new
    source commits. A random sample of our rows is re-resolved every pass;
    a stale one is refreshed in place with the current poster.
    """
    rows = db.execute(
        select(MediaCacheEntry, PhotosAsset.video_uuid)
        .join(PhotosAsset, PhotosAsset.id == MediaCacheEntry.photos_asset_id)
        .where(MediaCacheEntry.rendition == "poster", MediaCacheEntry.storage_path.like("%-d%.jpg"))
        .order_by(func.random())
        .limit(sample)
    ).all()
    plan = []
    for entry, video_uuid in rows:
        if not _is_ours(entry):
            continue
        item = _plan_item(db, entry.photos_asset_id, video_uuid, replace_id=entry.id)
        if item is not None and (item["sha256"] != entry.checksum_sha256.lower()
                                 or item["source_sha256"] != entry.source_blob_sha256
                                 or item["transform_version"] != entry.transform_version):
            plan.append(item)
    return plan


def _plan(db, limit: int) -> list[dict[str, Any]]:
    """New copies (bounded) plus refreshes of drifted copies."""
    plan = []
    for asset_id, video_uuid in _candidates(db, SCAN):
        if len(plan) >= limit:
            break
        item = _plan_item(db, asset_id, video_uuid)
        if item is not None:
            plan.append(item)
    return plan + _drifted(db, DRIFT_SAMPLE)


def _final_path(media_key: str, sha256: str) -> Path:
    """Content-specific path: never the legacy ``<media_key>.jpg`` a Mac
    poster job finalizes to, so a racing writer can't overwrite its bytes;
    two durable passes racing write identical verified bytes."""
    root = Path(get_settings().media_cache_root).resolve()
    final_dir = root / "poster" / media_key[:2] / media_key[2:4]
    final_dir.mkdir(parents=True, exist_ok=True)
    return final_dir / f"{media_key}-d{sha256[:16]}.jpg"


def _download(item: dict[str, Any], dest: Path) -> int:
    """Stream the object to ``dest``; verify size bound and SHA-256."""
    from app.services import b2_presign

    body, length = b2_presign.open_get_stream(item["bucket"], item["object_key"])
    try:
        if length <= 0 or length > MAX_POSTER_BYTES:
            raise ValueError("poster size out of bounds")
        digest = hashlib.sha256()
        size = 0
        with open(dest, "wb") as handle:
            for chunk in iter(lambda: body.read(256 * 1024), b""):
                size += len(chunk)
                if size > MAX_POSTER_BYTES:
                    raise ValueError("poster size out of bounds")
                digest.update(chunk)
                handle.write(chunk)
    finally:
        body.close()
    if size != length or digest.hexdigest() != item["sha256"]:
        raise ValueError("poster checksum mismatch")
    return size


def _refresh(db, item: dict[str, Any], tmp: Path, final: Path, size: int) -> str:
    """Point a drifted copy of ours at the current poster (row locked)."""
    entry = db.get(MediaCacheEntry, item["replace_id"], with_for_update=True, populate_existing=True)
    if not _is_ours(entry) or not _still_current(db, item):
        db.rollback()
        tmp.unlink(missing_ok=True)
        return "skipped"
    os.replace(tmp, final)
    os.chmod(final, 0o644)
    entry.storage_path = str(final)
    entry.size_bytes = size
    entry.checksum_sha256 = item["sha256"]
    entry.source_blob_sha256 = item["source_sha256"]
    entry.transform_version = item["transform_version"]
    entry.status = "ready"
    db.commit()  # the old file stays on disk (never deleted here)
    return "refreshed"


def materialize_durable_posters(db, limit: int = BATCH) -> dict[str, int]:
    """One bounded pass. The caller's session must be clean; commits itself."""
    import shutil

    counts = {"planned": 0, "cached": 0, "refreshed": 0, "skipped": 0, "failed": 0}
    settings = get_settings()
    try:
        if shutil.disk_usage(settings.media_cache_root).free < MIN_FREE_BYTES:
            counts["skipped"] = -1  # disk floor: do nothing this pass
            return counts
    except OSError:
        return counts
    plan = _plan(db, limit)
    db.rollback()  # end the read transaction before any network I/O
    counts["planned"] = len(plan)
    for item in plan:
        media_key = build_media_key(item["video_uuid"], "poster")
        final = _final_path(media_key, item["sha256"])
        tmp = final.with_name(f".{final.name}.{os.getpid()}.tmp")
        try:
            # Per download, with room for this poster: never cross the floor.
            if shutil.disk_usage(settings.media_cache_root).free < MIN_FREE_BYTES + MAX_POSTER_BYTES:
                break
        except OSError:
            break
        try:
            size = _download(item, tmp)
        except Exception:  # noqa: BLE001 - provider/IO/verify failure: retry next pass
            tmp.unlink(missing_ok=True)
            counts["failed"] += 1
            continue
        if item["replace_id"] is not None:
            counts[_refresh(db, item, tmp, final, size)] += 1
            continue
        # Re-check under a fresh transaction: another writer (a Mac poster
        # job, a parallel pass) may have produced the row meanwhile.
        taken = db.execute(select(MediaCacheEntry.id).where(
            (MediaCacheEntry.media_key == media_key)
            | ((MediaCacheEntry.photos_asset_id == item["asset_id"]) & (MediaCacheEntry.rendition == "poster"))
        ).limit(1)).scalar_one_or_none()
        if taken is not None or not _still_current(db, item):
            # Already cached, or the source changed during the download.
            # (A change after this check is caught by the drift sample.)
            db.rollback()
            tmp.unlink(missing_ok=True)
            counts["skipped"] += 1
            continue
        os.replace(tmp, final)
        os.chmod(final, 0o644)  # nginx re-serves it via X-Accel (see finalize_cache_entry)
        db.add(MediaCacheEntry(
            photos_asset_id=item["asset_id"],
            media_key=media_key,
            rendition="poster",
            storage_backend="local_fs",
            storage_path=str(final),
            content_type="image/jpeg",
            size_bytes=size,
            checksum_sha256=item["sha256"],
            status="ready",
            # A durable B2 copy exists, but the grid depends on this row:
            # keep it out of both cleaner paths like every poster.
            pinned=True,
            expires_at=None,
            source_blob_sha256=item["source_sha256"],
            transform_version=item["transform_version"],
        ))
        try:
            db.commit()
        except Exception:  # noqa: BLE001 - unique race lost: keep the winner
            db.rollback()
            # Remove our file unless the winning row uses the same path.
            if db.execute(select(MediaCacheEntry.id).where(
                MediaCacheEntry.storage_path == str(final)
            ).limit(1)).scalar_one_or_none() is None:
                final.unlink(missing_ok=True)
            db.rollback()
            counts["skipped"] += 1
            continue
        counts["cached"] += 1
    return counts
