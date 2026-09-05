"""Extract dive video metadata from macOS Photos library using osxphotos."""

import osxphotos
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path
import logging
import asyncio

from .error_recovery import (
    ErrorRecoveryManager,
    PhotosLibraryHealthCheck,
    PhotosLibraryUnavailableError,
    DatabaseLockedError,
    PermissionError,
    RetryConfig,
)

logger = logging.getLogger(__name__)


class PhotosReader:
    """Read videos from macOS Photos library with caption metadata."""

    def __init__(
        self,
        library_path: Optional[str] = None,
        retry_config: Optional[RetryConfig] = None
    ):
        """
        Initialize Photos database reader.

        Args:
            library_path: Path to Photos library (auto-detects if None)
            retry_config: Configuration for retry behavior
        """
        self.library_path = library_path
        self.db = None
        self.recovery = ErrorRecoveryManager(retry_config)
        self.health_check = None

        try:
            self._refresh_database()
        except PermissionError as e:
            logger.error(f"Permission denied accessing Photos library: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize Photos library: {e}")
            raise

    def _refresh_database(self) -> None:
        """Open a fresh read-only PhotosDB view before each metadata scan.

        Photos updates its SQLite library while the agent is running. osxphotos
        keeps a database handle, so reusing that handle can hide newly captioned
        videos until the LaunchAgent restarts.
        """
        if self.library_path:
            self.health_check = PhotosLibraryHealthCheck(self.library_path)
            self.db = osxphotos.PhotosDB(str(self.library_path))
        else:
            self.db = osxphotos.PhotosDB()
            if self.db.library_path:
                self.health_check = PhotosLibraryHealthCheck(self.db.library_path)
        logger.info("Refreshed Photos library view from %s", self.db.library_path)

    async def validate_library_accessible(self) -> bool:
        """Validate that Photos library is accessible."""
        if not self.health_check:
            logger.warning("No health check configured for Photos library")
            return False

        try:
            await self.health_check.validate_or_raise()
            return True
        except (PhotosLibraryUnavailableError, PermissionError) as e:
            logger.error(f"Photos library validation failed: {e}")
            return False

    async def get_all_videos(self) -> List[Dict[str, Any]]:
        """Get all videos with captions from Photos library."""
        async def _fetch_all_videos():
            videos = []
            try:
                self._refresh_database()
                for photo in self.db.photos(images=False, movies=True):
                    if photo.description:
                        videos.append({
                            'uuid': photo.uuid,
                            'caption': photo.description,
                            'date': photo.date,
                            'path': photo.path if not photo.ismissing else None,
                            'filename': photo.filename,
                            'cloud_guid': getattr(photo, 'cloud_guid', None) or getattr(photo, 'fingerprint', None),
                        })
                return videos
            except OSError as e:
                if "database is locked" in str(e).lower():
                    raise DatabaseLockedError(
                        "Photos.sqlite is locked. "
                        "Close Photos app or wait for lock to be released."
                    )
                else:
                    raise PermissionError(f"File access error: {e}")

        try:
            videos = await self.recovery.retry_with_backoff(
                _fetch_all_videos,
                operation_name="fetch all videos"
            )
            logger.info(f"Found {len(videos)} videos with captions")
            return videos
        except Exception as e:
            if self.recovery.handle_extraction_error(e, "fetching all videos"):
                return []
            else:
                logger.error(f"Fatal error reading videos: {e}")
                return []

    async def get_captioned_catalog_records(self) -> List[Dict[str, Any]]:
        """Return read-only metadata for every captioned movie in one DB scan."""
        def _fetch():
            self._refresh_database()
            records = []
            for photo in self.db.photos(images=False, movies=True):
                caption = (photo.description or "").strip()
                if not caption:
                    continue
                path = photo.path if not photo.ismissing else None
                size = None
                for attribute in ("original_filesize", "filesize", "file_size"):
                    value = getattr(photo, attribute, None)
                    if isinstance(value, (int, float)) and value > 0:
                        size = int(value)
                        break
                records.append({
                    "agent_local_uuid": photo.uuid,
                    "cloud_fingerprint": getattr(photo, "cloud_guid", None) or getattr(photo, "fingerprint", None),
                    "raw_caption": caption,
                    "captured_at": photo.date.isoformat() if photo.date else None,
                    "duration_seconds": getattr(photo, "duration", None),
                    "width": getattr(photo, "width", None),
                    "height": getattr(photo, "height", None),
                    "estimated_source_bytes": size,
                    "filename": photo.filename,
                    "local_available": bool(path),
                    "is_missing": bool(getattr(photo, "ismissing", False)),
                    "in_cloud": bool(getattr(photo, "incloud", False)),
                    "is_hidden": bool(getattr(photo, "hidden", False)),
                })
            return records

        return await asyncio.to_thread(_fetch)

    async def get_videos_since(self, since: datetime) -> List[Dict[str, Any]]:
        """
        Get videos added/modified since timestamp with retry logic.

        Args:
            since: Datetime to filter from (inclusive)

        Returns:
            List of video metadata dicts
        """
        async def _fetch_videos():
            videos = []
            try:
                self._refresh_database()
                for photo in self.db.photos(images=False, movies=True, from_date=since):
                    if photo.description:
                        videos.append({
                            'uuid': photo.uuid,
                            'caption': photo.description,
                            'date': photo.date,
                            'path': photo.path if not photo.ismissing else None,
                            'filename': photo.filename,
                            'cloud_guid': getattr(photo, 'cloud_guid', None) or getattr(photo, 'fingerprint', None),
                        })
                return videos
            except OSError as e:
                if "database is locked" in str(e).lower():
                    raise DatabaseLockedError(
                        "Photos.sqlite is locked. "
                        "Close Photos app or wait for lock to be released."
                    )
                else:
                    raise PermissionError(f"File access error: {e}")

        try:
            videos = await self.recovery.retry_with_backoff(
                _fetch_videos,
                operation_name="fetch videos since timestamp"
            )
            logger.info(f"Found {len(videos)} videos since {since}")
            return videos
        except Exception as e:
            if self.recovery.handle_extraction_error(e, "fetching videos"):
                logger.warning(f"Recovering from error: {e}")
                return []
            else:
                logger.error(f"Fatal error reading videos: {e}")
                return []

    async def get_video_by_uuid(self, uuid: str) -> Optional[Dict[str, Any]]:
        """
        Get specific video by UUID with retry logic.

        Args:
            uuid: Photo UUID

        Returns:
            Video metadata dict or None if not found
        """
        async def _fetch_video():
            try:
                self._refresh_database()
                photo = self.db.photos(uuid=[uuid])
                if not photo:
                    return None

                photo = photo[0]
                if not photo.description:
                    return None

                return {
                    'uuid': photo.uuid,
                    'caption': photo.description,
                    'date': photo.date,
                    'path': photo.path if not photo.ismissing else None,
                    'filename': photo.filename,
                    'cloud_guid': getattr(photo, 'cloud_guid', None) or getattr(photo, 'fingerprint', None),
                }
            except OSError as e:
                if "database is locked" in str(e).lower():
                    raise DatabaseLockedError(
                        "Photos.sqlite is locked. "
                        "Close Photos app or wait for lock to be released."
                    )
                else:
                    raise PermissionError(f"File access error: {e}")

        try:
            video = await self.recovery.retry_with_backoff(
                _fetch_video,
                operation_name=f"fetch video {uuid}"
            )
            return video
        except Exception as e:
            if not self.recovery.handle_extraction_error(
                e,
                f"fetching video {uuid}"
            ):
                logger.error(f"Fatal error reading video {uuid}: {e}")
            return None

    async def get_library_stats(self) -> Dict[str, Any]:
        """Get statistics about Photos library."""
        async def _fetch_stats():
            try:
                all_photos = self.db.photos()
                all_videos = self.db.photos(images=False, movies=True)
                videos_with_captions = [p for p in all_videos if p.description]

                return {
                    'total_photos': len(all_photos),
                    'total_videos': len(all_videos),
                    'videos_with_captions': len(videos_with_captions),
                    'library_path': str(self.db.library_path),
                }
            except OSError as e:
                if "database is locked" in str(e).lower():
                    raise DatabaseLockedError(
                        "Photos.sqlite is locked. "
                        "Close Photos app or wait for lock to be released."
                    )
                else:
                    raise PermissionError(f"File access error: {e}")

        try:
            stats = await self.recovery.retry_with_backoff(
                _fetch_stats,
                operation_name="fetch library stats"
            )
            return stats
        except Exception as e:
            if not self.recovery.handle_extraction_error(e, "fetching stats"):
                logger.error(f"Fatal error getting library stats: {e}")
            return {}
