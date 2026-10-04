"""Orchestrate metadata extraction from Photos library."""

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Set
from pathlib import Path
import json

from .photos_reader import PhotosReader
from .metadata import parse_dive_caption, parse_video_label, DiveMetadata
from .config import Config
from .error_recovery import (
    ErrorRecoveryManager,
    CaptionParseError,
    RetryConfig,
)

logger = logging.getLogger(__name__)


class MetadataExtractor:
    """Orchestrate photo extraction, parsing, and formatting for sync.

    Uses UUID+caption-hash tracking instead of a simple timestamp checkpoint.
    This ensures:
    - Retroactive caption edits are detected and re-synced
    - Failed syncs are retried (only successfully synced UUIDs are recorded)
    - No videos are permanently skipped due to checkpoint advancement
    """

    def __init__(self, config: Config):
        self.config = config
        retry_config = RetryConfig(
            max_retries=config.sync.max_retries,
            initial_delay=1.0,
            max_delay=30.0,
        )
        self.reader = PhotosReader(config.photos.library_path, retry_config)
        self.recovery = ErrorRecoveryManager(retry_config)
        self.state_file = Path.home() / '.diveanalyzer' / 'sync_state.json'
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.synced: Dict[str, str] = {}  # uuid -> caption_hash
        self._load_state()
        self.extraction_stats = {
            'total_videos': 0,
            'successfully_parsed': 0,
            'skipped_invalid': 0,
            'skipped_already_synced': 0,
            'labels_parsed': 0,
            'errors': 0,
        }

    @staticmethod
    def _caption_hash(caption: str) -> str:
        """Short hash of caption to detect edits."""
        return hashlib.md5(caption.encode()).hexdigest()[:12]

    def _load_state(self) -> None:
        """Load synced UUID set from state file."""
        # Try new state file first
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    self.synced = data.get('synced', {})
                    logger.info(f"Loaded sync state: {len(self.synced)} synced UUIDs")
                    return
            except Exception as e:
                logger.warning(f"Failed to load sync state: {e}")

        # Fall back to legacy checkpoint.json — treat as empty (will do full scan)
        legacy = self.state_file.parent / 'checkpoint.json'
        if legacy.exists():
            logger.info("No sync_state.json found, starting fresh (will deduplicate via server 409s)")
        self.synced = {}

    def _save_state(self) -> None:
        """Persist synced UUID set."""
        try:
            tmp_state_file = self.state_file.with_suffix('.json.tmp')
            with open(tmp_state_file, 'w') as f:
                json.dump({
                    'synced': self.synced,
                    'count': len(self.synced),
                    'updated_at': datetime.now().isoformat(),
                }, f)
            tmp_state_file.replace(self.state_file)
        except Exception as e:
            logger.error(f"Failed to save sync state: {e}")

    async def extract_pending_videos(self) -> List[Dict[str, Any]]:
        """
        Extract metadata for pending (new/modified) videos.

        A video is pending if:
        - Its UUID has never been synced, OR
        - Its caption has changed since last sync (hash mismatch)

        Returns:
            List of dicts ready for /api/v1/videos/sync POST
        """
        # Reset stats for this extraction run
        self.extraction_stats = {
            'total_videos': 0,
            'successfully_parsed': 0,
            'skipped_invalid': 0,
            'skipped_already_synced': 0,
            'labels_parsed': 0,
            'errors': 0,
        }

        videos_to_sync = []
        labels_to_sync = []

        try:
            # Get ALL captioned videos (not filtered by date)
            video_records = await self.reader.get_all_videos()
            self.extraction_stats['total_videos'] = len(video_records)
            logger.info(f"Found {len(video_records)} videos with captions in library")

            for video in video_records:
                try:
                    caption = video.get('caption', '').strip()
                    uuid = video['uuid']

                    if not caption:
                        self.extraction_stats['skipped_invalid'] += 1
                        continue

                    # Check if already synced with same caption
                    cap_hash = self._caption_hash(caption)
                    if uuid in self.synced and self.synced[uuid] == cap_hash:
                        self.extraction_stats['skipped_already_synced'] += 1
                        continue

                    # Parse caption
                    metadata = parse_dive_caption(caption)
                    if not metadata:
                        label = parse_video_label(caption)
                        if not label:
                            self.extraction_stats['skipped_invalid'] += 1
                            logger.debug(f"Invalid caption format: {caption}")
                            continue

                        labels_to_sync.append({
                            'video_uuid': uuid,
                            'label_type': label.label_type,
                            'label_value': label.label_value,
                            'raw_caption': label.raw_caption,
                            'date': video['date'].isoformat() if video['date'] else datetime.now().isoformat(),
                            'filename': video.get('filename'),
                            'source': 'photos_caption',
                            '_caption_hash': cap_hash,
                        })
                        self.extraction_stats['labels_parsed'] += 1
                        continue

                    # Build sync-ready dict
                    sync_ready = {
                        'dive_code': metadata.dive_code,
                        'height': metadata.height,
                        'performance': metadata.performance,
                        'phase1_performance': metadata.phase1_performance,
                        'phase2_performance': metadata.phase2_performance,
                        'video_uuid': uuid,
                        'date': video['date'].isoformat() if video['date'] else datetime.now().isoformat(),
                        'is_sync': metadata.is_sync,
                        'is_smack': metadata.is_smack,
                        'person_name': metadata.person_name,
                        'modifiers': metadata.modifiers or [],
                        'raw_caption': caption,
                        'caption_hash': cap_hash,
                        'filename': video.get('filename'),
                        'photos_path': video.get('path'),
                        'local_available': bool(video.get('path')),
                        'agent_id': self.config.agent.id,
                        'cloud_guid': video.get('cloud_guid'),
                        '_caption_hash': cap_hash,  # internal, stripped before POST
                    }

                    videos_to_sync.append(sync_ready)
                    self.extraction_stats['successfully_parsed'] += 1

                except Exception as e:
                    self.extraction_stats['errors'] += 1
                    logger.warning(f"Error processing video {video.get('uuid')}: {e}")
                    continue

            logger.info(
                f"Extracted {self.extraction_stats['successfully_parsed']} dives ready to sync "
                f"({self.extraction_stats['skipped_already_synced']} already synced)"
            )
            if self.extraction_stats['labels_parsed'] > 0:
                logger.info(
                    f"Extracted {self.extraction_stats['labels_parsed']} labels ready to sync"
                )
            if self.extraction_stats['skipped_invalid'] > 0:
                logger.info(f"Skipped {self.extraction_stats['skipped_invalid']} videos with invalid captions")
            if self.extraction_stats['errors'] > 0:
                logger.warning(f"Encountered {self.extraction_stats['errors']} errors during extraction")

            return {
                'videos': videos_to_sync,
                'labels': labels_to_sync,
            }

        except Exception as e:
            self.extraction_stats['errors'] += 1
            if self.recovery.handle_extraction_error(e, "extracting pending videos"):
                logger.warning(f"Recoverable error during extraction: {e}")
                return {
                    'videos': videos_to_sync,
                    'labels': labels_to_sync,
                }
            else:
                logger.error(f"Fatal error extracting pending videos: {e}")
                return {
                    'videos': videos_to_sync,
                    'labels': labels_to_sync,
                }

    async def extract_batch(self, pending: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """Format pending records as a sync batch."""
        return pending

    def mark_synced(self, results: list) -> None:
        """Record successfully synced UUIDs (called from main after batch sync).

        Args:
            results: List of SyncResult objects from sync_batch
        """
        newly_synced = 0
        for r in results:
            if r.success or (hasattr(r, 'http_status') and r.http_status == 409):
                # 409 = duplicate on server, still means it's synced
                uuid = r.video_uuid
                # Find the caption hash from the video data we sent
                # (stored as _caption_hash in the sync-ready dict)
                if uuid not in self.synced:
                    newly_synced += 1
                self.synced[uuid] = getattr(r, '_caption_hash', '')

        if newly_synced > 0:
            self._save_state()
            logger.info(f"Marked {newly_synced} new UUIDs as synced (total: {len(self.synced)})")

    def mark_video_synced(self, video_uuid: str, caption_hash: str) -> None:
        """Mark a single video as synced."""
        self.synced[video_uuid] = caption_hash

    def update_checkpoint(self) -> None:
        """Legacy compatibility — just saves state."""
        self._save_state()
        logger.info("Updated sync state")

    async def run_extraction_loop(self, stop_event: asyncio.Event) -> None:
        """Run continuous extraction loop."""
        logger.info(f"Starting extraction loop (interval: {self.config.sync.interval_seconds}s)")

        while not stop_event.is_set():
            try:
                pending = await self.extract_pending_videos()
                videos = pending.get('videos', [])
                labels = pending.get('labels', [])

                if videos or labels:
                    batch = await self.extract_batch(pending)
                    logger.info(
                        f"Ready to sync {len(videos)} videos and {len(labels)} labels"
                    )

                    yield batch

            except Exception as e:
                logger.error(f"Error in extraction loop: {e}")

            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=self.config.sync.interval_seconds
                )
                break
            except asyncio.TimeoutError:
                continue
