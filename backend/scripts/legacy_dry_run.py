#!/usr/bin/env python
"""LEGACY DRY-RUN inventory tool (packet MEDIA_BACKBONE_P9 §35) — DRY-RUN ONLY.

HARDCODED SAFETY CONTRACT:
  - this tool NEVER deletes, moves, truncates, hides or uploads anything;
  - there is NO --delete flag, NO destructive mode, NO execution mode;
    P9 requires only a trustworthy deletion-candidate inventory;
  - it performs read-only filesystem stat/list operations and read-only DB
    queries; B2 (if --b2-env-file is given) is queried with LIST only.

Output: a JSON manifest where every entry carries
    path, size, category, why_candidate (or why_keeper),
    authoritative_replacement (verified B2 revision / iCloud source),
    recovery_proof, and blocking_dependency (what still prevents deletion).

Storage-class taxonomy (LEGACY_DECOMMISSION_PLAN_V1 §1):
    legacy_cache_derivatives   server media/cache (posters, 360p, 720p)
    legacy_media_videos        server media/videos (icloudpd originals)
    science_data               science authorities (ALWAYS KEEP, out of scope)

Usage (server host or backend container):
    python scripts/legacy_dry_run.py --media-root /home/mcauchy/dive-analyser/media
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from app.database import SessionLocal, init_db
from app.models.dive import Dive
from app.models.media import MediaCacheEntry
from app.models.media_backbone import MediaBlobLocation, MediaRevision
from app.models.photos_asset import PhotosAsset

VIDEOS_CATEGORY = "legacy_media_videos"
CACHE_CATEGORY = "legacy_cache_derivatives"
SCIENCE_CATEGORY = "science_data"


def _load_db_facts():
    init_db()
    with SessionLocal() as db:
        dive_video_uuids = {
            row[0] for row in db.execute(select(Dive.video_uuid)).all() if row[0]
        }
        asset_uuid_by_id = dict(
            db.execute(select(PhotosAsset.id, PhotosAsset.video_uuid)).all()
        )
        # verified PROD blob shas keyed by video_uuid (via MediaRevision)
        verified_by_video_uuid = {}
        for revision, loc in (
            db.execute(
                select(MediaRevision, MediaBlobLocation)
                .join(
                    MediaBlobLocation,
                    MediaBlobLocation.blob_sha256 == MediaRevision.blob_sha256,
                )
                .where(
                    MediaBlobLocation.environment == "prod",
                    MediaBlobLocation.verified.is_(True),
                )
            ).all()
        ):
            verified_by_video_uuid.setdefault(revision.video_uuid, revision.id)
        cache_entries = [
            {
                "id": r[0],
                "photos_asset_id": r[1],
                "rendition": r[2],
                "storage_path": r[3],
                "size_bytes": r[4],
            }
            for r in db.execute(
                select(
                    MediaCacheEntry.id,
                    MediaCacheEntry.photos_asset_id,
                    MediaCacheEntry.rendition,
                    MediaCacheEntry.storage_path,
                    MediaCacheEntry.size_bytes,
                )
            ).all()
        ]
    return dive_video_uuids, asset_uuid_by_id, verified_by_video_uuid, cache_entries


def classify_videos_file(path: Path, dive_video_uuids: set[str]) -> dict:
    if path.stem in dive_video_uuids:
        return {
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "category": VIDEOS_CATEGORY,
            "why_candidate": False,
            "why": "matches a dive video_uuid — ACTIVE legacy fallback authority",
            "authoritative_replacement": "B2 verified PROD replica (edited rendition)",
            "blocking_dependency": "authenticated legacy fallback rollback path",
        }
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "category": VIDEOS_CATEGORY,
        "why_candidate": True,
        "why": (
            "icloudpd-downloaded iCloud ORIGINAL cache artifact; no dives row "
            "references it (production dives.video_path is NULL for every dive "
            "and legacy fallback routes resolve only UUID-named files)"
        ),
        "authoritative_replacement": "iCloud originals (icloudpd re-download) + Photos library; B2 backbone for edited renditions",
        "recovery_proof": "icloudpd --size original re-download; iCloud is source authority",
        "blocking_dependency": (
            "P9 prerequisites: CONTINUOUS_NATURAL_INGEST must be GREEN and the "
            "rollback strategy independent of legacy bytes; deletion is NOT "
            "authorized by this tool"
        ),
    }


def classify_cache_file(entry: dict, asset_uuid_by_id: dict, verified_by_video_uuid: dict) -> dict:
    video_uuid = asset_uuid_by_id.get(entry["photos_asset_id"])
    verified_revision = verified_by_video_uuid.get(video_uuid)
    if verified_by_video_uuid and verified_revision is not None:
        return {
            "path": entry["storage_path"],
            "size_bytes": entry["size_bytes"],
            "category": CACHE_CATEGORY,
            "rendition": entry["rendition"],
            "why_candidate": True,
            "why": (
                f"cache derivative of an asset whose media revision "
                f"(revision {verified_revision}) is byte-verified on B2"
            ),
            "authoritative_replacement": f"B2 verified PROD object for revision {verified_revision}",
            "recovery_proof": "re-transcode from the verified B2 replica",
            "blocking_dependency": (
                "the cache is the ACTIVE playback/poster substrate of the "
                "product UI (dives list, analysis, representative gallery); "
                "posters/proxies are consumed directly by the landmark pipeline"
            ),
        }
    return {
        "path": entry["storage_path"],
        "size_bytes": entry["size_bytes"],
        "category": CACHE_CATEGORY,
        "rendition": entry["rendition"],
        "why_candidate": False,
        "why": "no verified B2 replica resolves for this asset — conservative KEEP",
        "authoritative_replacement": None,
        "blocking_dependency": "no authoritative replacement identified",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--media-root", default="/home/mcauchy/dive-analyser/media")
    parser.add_argument(
        "--science-root", default=None,
        help="science data root to ENUMERATE (counts only, always KEEP)",
    )
    args = parser.parse_args(argv)

    media_root = Path(args.media_root)
    videos_dir = media_root / "videos"
    cache_dir = media_root / "cache"

    (
        dive_video_uuids,
        asset_uuid_by_id,
        verified_by_video_uuid,
        cache_entries,
    ) = _load_db_facts()

    entries: list[dict] = []

    if videos_dir.is_dir():
        for f in sorted(videos_dir.iterdir()):
            if f.is_file():
                entries.append(classify_videos_file(f, dive_video_uuids))

    classified_paths = set()
    cache_by_asset: dict[int, list[dict]] = {}
    for entry in cache_entries:
        cache_by_asset.setdefault(entry["photos_asset_id"], []).append(entry)
    for asset_entries in cache_by_asset.values():
        for entry in asset_entries:
            if Path(entry["storage_path"]).is_file():
                entries.append(classify_cache_file(entry, asset_uuid_by_id, verified_by_video_uuid))
                classified_paths.add(entry["storage_path"])
    if cache_dir.is_dir():
        for f in sorted(cache_dir.rglob("*")):
            if f.is_file() and str(f) not in classified_paths:
                entries.append(
                    {
                        "path": str(f),
                        "size_bytes": f.stat().st_size,
                        "category": CACHE_CATEGORY,
                        "why_candidate": False,
                        "why": "untracked by media_cache_entries — conservative KEEP pending manual classification",
                        "authoritative_replacement": None,
                        "blocking_dependency": "unclassified cache artifact",
                    }
                )

    if args.science_root:
        sci = Path(args.science_root)
        if sci.is_dir():
            files = [p for p in sci.rglob("*") if p.is_file()]
            entries.append(
                {
                    "path": str(sci),
                    "category": SCIENCE_CATEGORY,
                    "why_candidate": False,
                    "why": "SCIENCE AUTHORITY — always excluded from product reclamation",
                    "file_count": len(files),
                    "size_bytes": sum(p.stat().st_size for p in files),
                }
            )

    summary: dict[str, dict] = {}
    for entry in entries:
        bucket = summary.setdefault(
            entry["category"],
            {"files": 0, "bytes": 0, "candidates": 0, "candidate_bytes": 0},
        )
        bucket["files"] += 1
        bucket["bytes"] += entry.get("size_bytes", 0) or 0
        if entry.get("why_candidate"):
            bucket["candidates"] += 1
            bucket["candidate_bytes"] += entry.get("size_bytes", 0) or 0

    manifest = {
        "tool": "legacy_dry_run_v1",
        "mode": "DRY_RUN_ONLY",
        "deletion_authorized": False,
        "hardcoded_safety": {
            "delete_flag_exists": False,
            "destructive_mode_exists": False,
            "b2_write_operations": 0,
            "b2_delete_or_hide": 0,
            "legacy_deletes": 0,
        },
        "summary": summary,
        "candidates": entries,
    }
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
