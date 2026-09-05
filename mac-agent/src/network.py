"""Network connectivity detection and monitoring.

Uses curl subprocess for connectivity checks because macOS Sequoia blocks
direct Python socket access from LaunchAgent daemons.
"""

import asyncio
import logging
import subprocess
from typing import Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


async def is_online(server_url: str, timeout: float = 5.0) -> bool:
    """
    Check if network is online and server is reachable via curl.

    Args:
        server_url: Server URL to check connectivity
        timeout: Timeout in seconds for the check

    Returns:
        True if online and reachable, False otherwise
    """
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             "--max-time", str(int(timeout)), server_url],
            capture_output=True, text=True, timeout=timeout + 5,
        )
        status = result.stdout.strip()
        if status and status != "000":
            logger.debug(f"Server reachable: HTTP {status}")
            return True
        logger.debug(f"Server not reachable: curl returned {status}")
        return False
    except Exception as e:
        logger.debug(f"Network check failed: {e}")
        return False


async def wait_for_network(
    server_url: str,
    timeout: float = 300.0,
    check_interval: float = 5.0,
) -> bool:
    """
    Wait for network to become available.

    Checks connectivity every check_interval seconds with exponential backoff.

    Args:
        server_url: Server URL to check
        timeout: Maximum time to wait in seconds (default: 5 minutes)
        check_interval: Initial interval between checks in seconds (grows exponentially)

    Returns:
        True if network becomes available, False if timeout exceeded
    """
    start_time = datetime.now()
    deadline = start_time + timedelta(seconds=timeout)
    current_interval = check_interval
    max_interval = 60.0  # Cap backoff at 60 seconds

    while datetime.now() < deadline:
        logger.info("Checking if network is available...")

        if await is_online(server_url, timeout=min(5.0, current_interval)):
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.info(f"Network is back online (waited {elapsed:.1f}s)")
            return True

        # Calculate time remaining
        time_remaining = (deadline - datetime.now()).total_seconds()
        if time_remaining <= 0:
            logger.error(f"Network timeout after {timeout:.1f}s")
            return False

        # Wait before next check with exponential backoff
        wait_time = min(current_interval, time_remaining)
        logger.info(
            f"Network offline. Retrying in {wait_time:.1f}s "
            f"({time_remaining:.0f}s remaining)"
        )

        try:
            await asyncio.sleep(wait_time)
            # Exponential backoff: 5s, 10s, 20s, 40s, 60s, 60s, ...
            current_interval = min(current_interval * 2, max_interval)
        except asyncio.CancelledError:
            logger.info("Network wait cancelled")
            return False

    logger.error(f"Network timeout exceeded ({timeout:.1f}s)")
    return False


class NetworkMonitor:
    """Monitor network connectivity with exponential backoff retry."""

    def __init__(
        self,
        server_url: str,
        check_interval: float = 30.0,
    ):
        """
        Initialize network monitor.

        Args:
            server_url: Server URL to monitor
            check_interval: Interval between checks in seconds
        """
        self.server_url = server_url
        self.check_interval = check_interval
        self.is_online = True
        self.last_check = datetime.now()
        self.offline_since = None

    async def check_connectivity(self) -> bool:
        """
        Check current network status.

        Returns:
            True if online, False if offline
        """
        now = datetime.now()

        # Only check if interval has elapsed
        if (now - self.last_check).total_seconds() < self.check_interval:
            return self.is_online

        # Perform check
        was_online = self.is_online
        self.is_online = await is_online(self.server_url, timeout=5.0)
        self.last_check = now

        # Log state changes
        if was_online and not self.is_online:
            self.offline_since = now
            logger.warning("Network went offline")
        elif not was_online and self.is_online:
            if self.offline_since:
                duration = (now - self.offline_since).total_seconds()
                logger.info(f"Network came back online (was offline for {duration:.0f}s)")
            self.offline_since = None

        return self.is_online

    def get_offline_duration(self) -> Optional[float]:
        """
        Get how long network has been offline.

        Returns:
            Duration in seconds if offline, None if online
        """
        if self.offline_since:
            return (datetime.now() - self.offline_since).total_seconds()
        return None

    def get_status(self) -> dict:
        """Get network monitor status."""
        return {
            'is_online': self.is_online,
            'last_check': self.last_check.isoformat(),
            'offline_since': self.offline_since.isoformat() if self.offline_since else None,
            'offline_duration': self.get_offline_duration(),
        }
