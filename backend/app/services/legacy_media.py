"""P6 authenticated legacy media fallback (server-side streaming).

Used ONLY after session authentication AND central OWNER authorization
have both succeeded for a media revision. The browser never receives a
legacy URL: this module resolves a legacy source and streams it from the
backend with HTTP Range support, so the fallback cannot leak an
unauthenticated address.

Resolution order (deterministic, evidence-based):
1. media-cache renditions for the revision's video_uuid (original >
   proxy_720p > proxy_360p; posters are never used as playback sources);
2. the legacy server-side file locations used by GET /api/v1/videos/
   {video_uuid} (mounted /videos, absolute dive.video_path,
   /photos_library copies), always constrained to the same allowed-root
   check.

Fail-closed: no source found -> None (caller decides 404 vs 503 per the
P6 failure-semantics matrix). No DEV media, no unverified replicas, no
storage mutations of any kind.
"""

import mimetypes
import os
from pathlib import Path
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.dive import Dive
from app.models.media import MediaCacheEntry
from app.models.media_backbone import MediaRevision
from app.models.photos_asset import PhotosAsset

_PLAYBACK_RENDITION_PREFERENCE = {
    "original": 0,
    "proxy_720p": 1,
    "proxy_360p": 2,
}

_ALLOWED_ROOTS = (
    os.path.realpath("/videos"),
    os.path.realpath("/photos_library"),
    os.path.realpath("/tmp/dive_downloads"),
)


def _ready_cache_entries_for_uuid(
    db: Session, video_uuid: str
) -> list[MediaCacheEntry]:
    stmt = (
        select(MediaCacheEntry)
        .join(PhotosAsset, PhotosAsset.id == MediaCacheEntry.photos_asset_id)
        .where(
            PhotosAsset.video_uuid == video_uuid,
            MediaCacheEntry.status == "ready",
        )
        .order_by(MediaCacheEntry.created_at.desc())
    )
    return list(db.execute(stmt).scalars().all())


def _entry_is_playable_video(entry: MediaCacheEntry) -> bool:
    return (entry.rendition or "") != "poster" and bool(entry.storage_path)


def _legacy_file_candidates(db: Session, revision: MediaRevision) -> list[str]:
    """The exact legacy locations GET /videos/{video_uuid} serves from."""
    dive = db.query(Dive).filter(Dive.video_uuid == revision.video_uuid).one_or_none()
    video_path = getattr(dive, "video_path", None) if dive is not None else None
    return [
        f"/videos/{revision.video_uuid}.mp4",
        f"/videos/{os.path.basename(video_path)}" if video_path else None,
        video_path if video_path and os.path.isabs(video_path) else None,
        f"/photos_library/Masters/{video_path}" if video_path else None,
        f"/photos_library/{video_path}" if video_path else None,
    ]


def resolve_legacy_media_source(
    db: Session, revision: MediaRevision
) -> Optional[Tuple[str, str]]:
    """Resolve (path, content_type) for authorized legacy playback.

    Prefers cache renditions (already transcoded, content-typed), then
    legacy files. Never returns a poster, never returns a path outside the
    allowed roots, never mutates storage.
    """
    entries = [
        entry
        for entry in _ready_cache_entries_for_uuid(db, revision.video_uuid)
        if _entry_is_playable_video(entry)
    ]
    if entries:
        entry = min(
            entries,
            key=lambda e: _PLAYBACK_RENDITION_PREFERENCE.get(e.rendition, 99),
        )
        candidate = Path(entry.storage_path).resolve()
        cache_root = Path(get_settings().media_cache_root).resolve()
        try:
            candidate.relative_to(cache_root)
        except ValueError:
            # Same path-safety invariant as the legacy cache route: storage
            # paths must stay inside the configured cache root.
            candidate = None
        if candidate is not None and candidate.exists():
            content_type = entry.content_type or "video/mp4"
            return str(candidate), content_type

    for alt in filter(None, _legacy_file_candidates(db, revision)):
        if os.path.exists(alt):
            real_path = os.path.realpath(alt)
            if not any(
                real_path.startswith(root + os.sep) or real_path == root
                for root in _ALLOWED_ROOTS
            ):
                continue
            mime_type, _ = mimetypes.guess_type(real_path)
            if not mime_type:
                mime_type = "video/quicktime"
            return real_path, mime_type
    return None
