"""Type definitions for sync client."""

from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import datetime


@dataclass
class SyncResult:
    """Result of a single video sync operation."""

    success: bool
    video_uuid: str
    dive_id: Optional[int] = None
    http_status: Optional[int] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    timestamp: datetime = None

    def __post_init__(self):
        """Ensure timestamp is set."""
        if self.timestamp is None:
            self.timestamp = datetime.now()

    def __str__(self) -> str:
        """String representation."""
        if self.success:
            return f"✓ {self.video_uuid} → dive_id {self.dive_id}"
        else:
            status_str = f" ({self.http_status})" if self.http_status else ""
            return f"✗ {self.video_uuid}{status_str}: {self.error_message}"


@dataclass
class BatchSyncResult:
    """Result of a batch sync operation."""

    total: int
    succeeded: int
    failed: int
    results: list  # List of SyncResult objects
    errors: list  # List of error dicts: {video_uuid, error, status}

    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        if self.total == 0:
            return 0.0
        return (self.succeeded / self.total) * 100

    def __str__(self) -> str:
        """String representation."""
        return (
            f"Batch: {self.succeeded}/{self.total} succeeded "
            f"({self.success_rate:.1f}%)"
        )
