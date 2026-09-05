"""Offline video queue with persistent storage."""

import asyncio
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import tempfile
import os

logger = logging.getLogger(__name__)


class VideoQueue:
    """
    Persistent queue for videos pending sync.

    Stores videos in ~/.diveanalyzer/queue.json with atomic writes.
    Prevents duplicates by video_uuid. Survives app restarts.
    """

    def __init__(self, queue_path: Optional[str] = None):
        """
        Initialize queue.

        Args:
            queue_path: Path to queue.json (default: ~/.diveanalyzer/queue.json)
        """
        if queue_path:
            self.queue_path = Path(queue_path).expanduser()
        else:
            self.queue_path = Path.home() / '.diveanalyzer' / 'queue.json'

        self.queue_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_queue_size = 10_000  # Max videos in queue
        self.videos = []
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        """Load queue from disk file."""
        try:
            if self.queue_path.exists():
                with open(self.queue_path, 'r') as f:
                    data = json.load(f)
                    self.videos = data.get('videos', [])
                logger.info(f"Loaded {len(self.videos)} videos from queue")
            else:
                self.videos = []
                logger.info("Queue is empty (file does not exist)")
        except Exception as e:
            logger.error(f"Failed to load queue from disk: {e}")
            self.videos = []

    async def _save_to_disk(self) -> None:
        """
        Save queue to disk atomically.

        Uses temp file + rename pattern to prevent corruption.
        """
        try:
            data = {
                'videos': self.videos,
                'timestamp': datetime.now().isoformat(),
                'count': len(self.videos),
            }

            # Write to temp file in same directory (atomic rename)
            temp_fd, temp_path = tempfile.mkstemp(
                dir=str(self.queue_path.parent),
                prefix='.queue_',
                suffix='.tmp',
            )

            try:
                with os.fdopen(temp_fd, 'w') as f:
                    json.dump(data, f, indent=2)
                # Atomic rename
                os.replace(temp_path, str(self.queue_path))
            except Exception as e:
                # Clean up temp file if rename fails
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass
                raise e

            logger.debug(f"Queue saved: {len(self.videos)} videos")

        except Exception as e:
            logger.error(f"Failed to save queue to disk: {e}")

    async def add_video(self, video_data: Dict[str, Any]) -> bool:
        """
        Add video to queue (or update if already present).

        Args:
            video_data: Video metadata dict

        Returns:
            True if added/updated, False if queue is full
        """
        video_uuid = video_data.get('video_uuid')
        if not video_uuid:
            logger.error("Cannot queue video without video_uuid")
            return False

        # Check queue size
        if len(self.videos) >= self.max_queue_size:
            logger.error(
                f"Queue is full ({self.max_queue_size} videos). "
                "Cannot add more videos."
            )
            return False

        # Check for duplicate
        existing = next(
            (v for v in self.videos if v.get('video_uuid') == video_uuid),
            None,
        )

        if existing:
            logger.debug(f"Video {video_uuid} already in queue, updating")
            # Update existing entry
            existing.update(video_data)
        else:
            # Add new entry with timestamp
            video_entry = {
                **video_data,
                'queued_at': datetime.now().isoformat(),
            }
            self.videos.append(video_entry)
            logger.debug(f"Added {video_uuid} to queue")

        await self._save_to_disk()
        return True

    async def get_pending(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get pending videos from queue.

        Args:
            limit: Maximum number of videos to return (None = all)

        Returns:
            List of video metadata dicts
        """
        if limit:
            return self.videos[:limit]
        else:
            return self.videos.copy()

    async def mark_synced(self, video_uuid: str) -> bool:
        """
        Mark video as synced and remove from queue.

        Args:
            video_uuid: UUID of video to remove

        Returns:
            True if video was in queue and removed, False if not found
        """
        initial_count = len(self.videos)
        self.videos = [v for v in self.videos if v.get('video_uuid') != video_uuid]

        if len(self.videos) < initial_count:
            logger.debug(f"Removed {video_uuid} from queue")
            await self._save_to_disk()
            return True
        else:
            logger.debug(f"Video {video_uuid} not found in queue")
            return False

    async def mark_batch_synced(self, video_uuids: List[str]) -> int:
        """
        Mark multiple videos as synced.

        Args:
            video_uuids: List of UUIDs to remove

        Returns:
            Number of videos removed
        """
        initial_count = len(self.videos)
        uuid_set = set(video_uuids)
        self.videos = [
            v for v in self.videos
            if v.get('video_uuid') not in uuid_set
        ]

        removed = initial_count - len(self.videos)
        if removed > 0:
            logger.info(f"Removed {removed} videos from queue")
            await self._save_to_disk()

        return removed

    async def clear(self) -> None:
        """Clear all videos from queue."""
        count = len(self.videos)
        self.videos = []
        await self._save_to_disk()
        logger.info(f"Cleared queue ({count} videos removed)")

    def get_status(self) -> Dict[str, Any]:
        """Get queue status."""
        oldest_video = None
        if self.videos:
            # Find oldest queued video
            oldest = min(
                self.videos,
                key=lambda v: v.get('queued_at', datetime.now().isoformat()),
            )
            oldest_video = {
                'video_uuid': oldest.get('video_uuid'),
                'queued_at': oldest.get('queued_at'),
            }

        return {
            'queue_size': len(self.videos),
            'max_size': self.max_queue_size,
            'percent_full': (len(self.videos) / self.max_queue_size) * 100,
            'oldest_video': oldest_video,
            'queue_path': str(self.queue_path),
        }

    async def get_stats(self) -> Dict[str, Any]:
        """Get detailed queue statistics."""
        return {
            **self.get_status(),
            'timestamp': datetime.now().isoformat(),
        }
