"""WebSocket-based sync status tracking and broadcasting."""

import json
import logging
from typing import Set, Dict, Optional, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum
import asyncio

logger = logging.getLogger(__name__)


class SyncEventType(Enum):
    """Types of sync events."""
    SYNC_STARTED = "sync_started"
    SYNC_PROGRESS = "sync_progress"
    SYNC_COMPLETE = "sync_complete"
    SYNC_ERROR = "sync_error"
    MILESTONE_DETECTED = "milestone_detected"
    HEARTBEAT = "heartbeat"


@dataclass
class SyncEvent:
    """A sync status event."""
    type: SyncEventType
    timestamp: str
    sync_id: str
    data: Dict

    def to_json(self) -> str:
        """Convert to JSON for WebSocket transmission."""
        return json.dumps({
            "type": self.type.value,
            "timestamp": self.timestamp,
            "sync_id": self.sync_id,
            "data": self.data,
        })


@dataclass
class SyncStatus:
    """Current status of a sync operation."""
    sync_id: str
    status: str  # 'started', 'in_progress', 'complete', 'error'
    total_videos: int
    synced_count: int = 0
    error_count: int = 0
    started_at: datetime = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    last_update: datetime = None

    @property
    def progress_percent(self) -> int:
        """Get progress percentage."""
        if self.total_videos == 0:
            return 0
        return int((self.synced_count / self.total_videos) * 100)

    @property
    def duration_seconds(self) -> float:
        """Get operation duration in seconds."""
        end = self.completed_at or datetime.utcnow()
        if not self.started_at:
            return 0
        return (end - self.started_at).total_seconds()

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "sync_id": self.sync_id,
            "status": self.status,
            "total_videos": self.total_videos,
            "synced_count": self.synced_count,
            "error_count": self.error_count,
            "progress_percent": self.progress_percent,
            "duration_seconds": self.duration_seconds,
            "error_message": self.error_message,
        }


class SyncStatusTracker:
    """Track active sync operations."""

    def __init__(self):
        """Initialize tracker."""
        self.active_syncs: Dict[str, SyncStatus] = {}
        self.completed_syncs: Dict[str, SyncStatus] = {}
        self.max_completed_history = 100  # Keep last 100 completed syncs

    def start_sync(self, sync_id: str, total_videos: int) -> SyncStatus:
        """Register start of sync operation.

        Args:
            sync_id: Unique sync identifier
            total_videos: Total videos in this sync

        Returns:
            SyncStatus object
        """
        status = SyncStatus(
            sync_id=sync_id,
            status="started",
            total_videos=total_videos,
            started_at=datetime.utcnow(),
            last_update=datetime.utcnow(),
        )
        self.active_syncs[sync_id] = status
        logger.info(f"Sync started: {sync_id} ({total_videos} videos)")
        return status

    def update_progress(
        self,
        sync_id: str,
        synced_count: int,
        error_count: int = 0,
    ) -> Optional[SyncStatus]:
        """Update sync progress.

        Args:
            sync_id: Sync identifier
            synced_count: Number of videos synced
            error_count: Number of errors

        Returns:
            Updated SyncStatus or None if not found
        """
        if sync_id not in self.active_syncs:
            logger.warning(f"Sync not found: {sync_id}")
            return None

        status = self.active_syncs[sync_id]
        status.synced_count = synced_count
        status.error_count = error_count
        status.status = "in_progress"
        status.last_update = datetime.utcnow()

        logger.debug(
            f"Sync progress: {sync_id} ({synced_count}/{status.total_videos})"
        )
        return status

    def complete_sync(self, sync_id: str) -> Optional[SyncStatus]:
        """Mark sync as completed.

        Args:
            sync_id: Sync identifier

        Returns:
            Completed SyncStatus or None if not found
        """
        if sync_id not in self.active_syncs:
            logger.warning(f"Sync not found: {sync_id}")
            return None

        status = self.active_syncs.pop(sync_id)
        status.status = "complete"
        status.completed_at = datetime.utcnow()
        status.last_update = status.completed_at

        # Keep in history
        self.completed_syncs[sync_id] = status

        # Trim old history
        if len(self.completed_syncs) > self.max_completed_history:
            oldest_id = next(iter(self.completed_syncs))
            del self.completed_syncs[oldest_id]

        logger.info(
            f"Sync completed: {sync_id} in {status.duration_seconds:.1f}s"
        )
        return status

    def error_sync(self, sync_id: str, error_message: str) -> Optional[SyncStatus]:
        """Mark sync as errored.

        Args:
            sync_id: Sync identifier
            error_message: Error description

        Returns:
            SyncStatus with error or None if not found
        """
        if sync_id not in self.active_syncs:
            logger.warning(f"Sync not found: {sync_id}")
            return None

        status = self.active_syncs.pop(sync_id)
        status.status = "error"
        status.error_message = error_message
        status.completed_at = datetime.utcnow()
        status.last_update = status.completed_at

        # Keep in history
        self.completed_syncs[sync_id] = status

        logger.error(f"Sync error: {sync_id} - {error_message}")
        return status

    def get_status(self, sync_id: str) -> Optional[SyncStatus]:
        """Get current status of a sync.

        Args:
            sync_id: Sync identifier

        Returns:
            SyncStatus or None if not found
        """
        return self.active_syncs.get(sync_id) or self.completed_syncs.get(sync_id)

    def get_all_active(self) -> Dict[str, SyncStatus]:
        """Get all active syncs.

        Returns:
            Dictionary of active syncs
        """
        return dict(self.active_syncs)

    def get_all_completed(self) -> Dict[str, SyncStatus]:
        """Get all completed syncs (history).

        Returns:
            Dictionary of completed syncs
        """
        return dict(self.completed_syncs)

    def cleanup_old_completed(self, older_than_hours: int = 24) -> int:
        """Clean up completed syncs older than specified duration.

        Args:
            older_than_hours: Delete syncs completed older than this

        Returns:
            Number of syncs deleted
        """
        cutoff = datetime.utcnow() - timedelta(hours=older_than_hours)
        to_delete = [
            sync_id
            for sync_id, status in self.completed_syncs.items()
            if status.completed_at and status.completed_at < cutoff
        ]

        for sync_id in to_delete:
            del self.completed_syncs[sync_id]

        if to_delete:
            logger.info(f"Cleaned up {len(to_delete)} old completed syncs")

        return len(to_delete)


class WebSocketManager:
    """Manage WebSocket connections and broadcasting."""

    def __init__(self, status_tracker: SyncStatusTracker):
        """Initialize manager.

        Args:
            status_tracker: SyncStatusTracker instance
        """
        self.status_tracker = status_tracker
        self.active_connections: Dict[str, Set] = {}  # client_id -> set of websockets
        self.client_metadata: Dict = {}  # client_id -> metadata
        self.event_callbacks: Dict[SyncEventType, list] = {}  # event_type -> [callbacks]
        self.broadcast_task: Optional[asyncio.Task] = None

    async def connect(self, websocket, client_id: str, metadata: Dict = None) -> None:
        """Register a new WebSocket connection.

        Args:
            websocket: WebSocket connection
            client_id: Unique client identifier
            metadata: Optional client metadata
        """
        if client_id not in self.active_connections:
            self.active_connections[client_id] = set()

        self.active_connections[client_id].add(websocket)
        self.client_metadata[client_id] = metadata or {}

        # Send welcome message
        welcome = SyncEvent(
            type=SyncEventType.HEARTBEAT,
            timestamp=datetime.utcnow().isoformat(),
            sync_id="welcome",
            data={"client_id": client_id, "message": "Connected"},
        )
        await websocket.send_text(welcome.to_json())

        logger.info(f"Client connected: {client_id}")

    async def disconnect(self, websocket, client_id: str) -> None:
        """Unregister a WebSocket connection.

        Args:
            websocket: WebSocket connection
            client_id: Client identifier
        """
        if client_id in self.active_connections:
            self.active_connections[client_id].discard(websocket)
            if not self.active_connections[client_id]:
                del self.active_connections[client_id]
                if client_id in self.client_metadata:
                    del self.client_metadata[client_id]

        logger.info(f"Client disconnected: {client_id}")

    async def broadcast(self, event: SyncEvent, client_id: str = None) -> None:
        """Broadcast event to connected clients.

        Args:
            event: SyncEvent to broadcast
            client_id: If set, send only to this client
        """
        message = event.to_json()

        if client_id:
            # Send to specific client
            if client_id in self.active_connections:
                disconnected = set()
                for websocket in self.active_connections[client_id]:
                    try:
                        await websocket.send_text(message)
                    except Exception as e:
                        logger.warning(f"Failed to send to {client_id}: {e}")
                        disconnected.add(websocket)

                # Remove disconnected
                for ws in disconnected:
                    await self.disconnect(ws, client_id)
        else:
            # Send to all clients
            disconnected = {}
            for cid, websockets in self.active_connections.items():
                for websocket in websockets:
                    try:
                        await websocket.send_text(message)
                    except Exception as e:
                        logger.warning(f"Failed to send to {cid}: {e}")
                        if cid not in disconnected:
                            disconnected[cid] = set()
                        disconnected[cid].add(websocket)

            # Clean up disconnected
            for cid, websockets in disconnected.items():
                for ws in websockets:
                    await self.disconnect(ws, cid)

    async def emit_sync_started(self, sync_id: str, total_videos: int) -> None:
        """Emit sync started event.

        Args:
            sync_id: Sync identifier
            total_videos: Total videos in batch
        """
        event = SyncEvent(
            type=SyncEventType.SYNC_STARTED,
            timestamp=datetime.utcnow().isoformat(),
            sync_id=sync_id,
            data={"total_videos": total_videos},
        )
        await self.broadcast(event)

    async def emit_sync_progress(
        self,
        sync_id: str,
        synced_count: int,
        total_videos: int,
        error_count: int = 0,
    ) -> None:
        """Emit sync progress event.

        Args:
            sync_id: Sync identifier
            synced_count: Dives synced so far
            total_videos: Total dives
            error_count: Number of errors
        """
        event = SyncEvent(
            type=SyncEventType.SYNC_PROGRESS,
            timestamp=datetime.utcnow().isoformat(),
            sync_id=sync_id,
            data={
                "synced_count": synced_count,
                "total_videos": total_videos,
                "error_count": error_count,
                "progress_percent": int((synced_count / total_videos * 100)),
            },
        )
        await self.broadcast(event)

    async def emit_sync_complete(self, sync_id: str, synced_count: int) -> None:
        """Emit sync completed event.

        Args:
            sync_id: Sync identifier
            synced_count: Final count of synced dives
        """
        event = SyncEvent(
            type=SyncEventType.SYNC_COMPLETE,
            timestamp=datetime.utcnow().isoformat(),
            sync_id=sync_id,
            data={"synced_count": synced_count},
        )
        await self.broadcast(event)

    async def emit_sync_error(self, sync_id: str, error_message: str) -> None:
        """Emit sync error event.

        Args:
            sync_id: Sync identifier
            error_message: Error description
        """
        event = SyncEvent(
            type=SyncEventType.SYNC_ERROR,
            timestamp=datetime.utcnow().isoformat(),
            sync_id=sync_id,
            data={"error": error_message},
        )
        await self.broadcast(event)

    async def emit_milestone_detected(
        self,
        sync_id: str,
        milestone_type: str,
        title: str,
        narrative: str,
    ) -> None:
        """Emit milestone detected event.

        Args:
            sync_id: Sync identifier
            milestone_type: Type of milestone
            title: Milestone title
            narrative: Milestone description
        """
        event = SyncEvent(
            type=SyncEventType.MILESTONE_DETECTED,
            timestamp=datetime.utcnow().isoformat(),
            sync_id=sync_id,
            data={
                "type": milestone_type,
                "title": title,
                "narrative": narrative,
            },
        )
        await self.broadcast(event)

    def get_connected_clients(self) -> int:
        """Get count of connected clients.

        Returns:
            Number of unique connected clients
        """
        return len(self.active_connections)

    def get_total_connections(self) -> int:
        """Get total number of active WebSocket connections.

        Returns:
            Total connections across all clients
        """
        return sum(len(ws) for ws in self.active_connections.values())


# Global instances
_status_tracker: Optional[SyncStatusTracker] = None
_ws_manager: Optional[WebSocketManager] = None


def get_status_tracker() -> SyncStatusTracker:
    """Get or create global SyncStatusTracker."""
    global _status_tracker
    if _status_tracker is None:
        _status_tracker = SyncStatusTracker()
    return _status_tracker


def get_ws_manager() -> WebSocketManager:
    """Get or create global WebSocketManager."""
    global _ws_manager
    if _ws_manager is None:
        _ws_manager = WebSocketManager(get_status_tracker())
    return _ws_manager
