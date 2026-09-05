"""Crash recovery and heartbeat system."""

import asyncio
import json
import logging
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class HeartbeatManager:
    """Manages heartbeat file for crash detection."""

    HEARTBEAT_FILE = Path.home() / '.diveanalyzer' / 'heartbeat'
    HEARTBEAT_INTERVAL = 30  # seconds
    HEARTBEAT_TIMEOUT = 60  # seconds (stale if older)

    def __init__(self):
        """Initialize heartbeat manager."""
        self.heartbeat_task = None
        self.last_sync_time = None

    async def start(self) -> None:
        """Start periodic heartbeat writing."""
        logger.debug("Starting heartbeat monitor")
        self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def stop(self) -> None:
        """Stop heartbeat writing."""
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except asyncio.CancelledError:
                pass
            logger.debug("Heartbeat monitor stopped")

    async def _heartbeat_loop(self) -> None:
        """Write heartbeat file periodically."""
        while True:
            try:
                self.write_heartbeat()
                await asyncio.sleep(self.HEARTBEAT_INTERVAL)
            except Exception as e:
                logger.warning(f"Heartbeat write failed: {e}")
                await asyncio.sleep(self.HEARTBEAT_INTERVAL)

    def write_heartbeat(self) -> None:
        """Write heartbeat file with current timestamp."""
        try:
            self.HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)

            data = {
                'timestamp': datetime.utcnow().isoformat(),
                'process_id': os.getpid(),
                'last_sync': self.last_sync_time.isoformat() if self.last_sync_time else None,
                'version': '1.0'
            }

            self.HEARTBEAT_FILE.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.warning(f"Failed to write heartbeat: {e}")

    def update_sync_time(self) -> None:
        """Update last successful sync time."""
        self.last_sync_time = datetime.utcnow()

    @classmethod
    def is_recovery_needed(cls) -> bool:
        """Check if agent needs to recover from crash."""
        if not cls.HEARTBEAT_FILE.exists():
            return False

        try:
            data = json.loads(cls.HEARTBEAT_FILE.read_text())
            heartbeat_time = datetime.fromisoformat(data['timestamp'])
            age = datetime.utcnow() - heartbeat_time

            if age > timedelta(seconds=cls.HEARTBEAT_TIMEOUT):
                logger.warning(f"Stale heartbeat detected (age: {age.total_seconds():.0f}s)")
                return True
        except Exception as e:
            logger.warning(f"Could not check heartbeat: {e}")
            return False

        return False

    @classmethod
    async def recover_from_crash(cls, queue) -> None:
        """Recover from crash by resuming offline queue."""
        logger.info("Recovering from previous crash...")

        try:
            # Load offline queue
            pending_count = len(queue.videos)

            if pending_count > 0:
                logger.info(f"Recovered {pending_count} pending videos from offline queue")
                logger.info("These will be synced in the next batch")
            else:
                logger.info("No pending videos to recover")

            # Cleanup stale heartbeat
            if cls.HEARTBEAT_FILE.exists():
                cls.HEARTBEAT_FILE.unlink()

        except Exception as e:
            logger.warning(f"Error during crash recovery: {e}")

    def get_status(self) -> dict:
        """Get heartbeat status."""
        if not self.HEARTBEAT_FILE.exists():
            return {
                'status': 'no_heartbeat',
                'message': 'No heartbeat file found'
            }

        try:
            data = json.loads(self.HEARTBEAT_FILE.read_text())
            age = (datetime.utcnow() - datetime.fromisoformat(data['timestamp'])).total_seconds()

            return {
                'status': 'active' if age < self.HEARTBEAT_TIMEOUT else 'stale',
                'timestamp': data['timestamp'],
                'age_seconds': age,
                'process_id': data.get('process_id'),
                'last_sync': data.get('last_sync')
            }
        except Exception as e:
            return {
                'status': 'error',
                'message': str(e)
            }
