"""Python WebSocket client library for testing and monitoring."""

import asyncio
import json
import logging
from typing import Callable, Dict, Optional, List
from datetime import datetime
import websockets
from websockets.client import WebSocketClientProtocol

logger = logging.getLogger(__name__)


class SyncStatusClient:
    """WebSocket client for receiving sync status updates."""

    def __init__(self, url: str, client_id: str = None):
        """Initialize WebSocket client.

        Args:
            url: WebSocket URL (e.g., "ws://localhost:8000/api/v1/ws/sync")
            client_id: Optional client identifier
        """
        self.url = url
        self.client_id = client_id
        self.websocket: Optional[WebSocketClientProtocol] = None
        self.connected = False
        self.event_handlers: Dict[str, List[Callable]] = {}
        self.received_events: List[Dict] = []
        self.last_sync_id: Optional[str] = None
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 1.0  # seconds

    async def connect(self) -> bool:
        """Connect to WebSocket server.

        Returns:
            True if connected, False otherwise
        """
        try:
            query_param = f"?client_id={self.client_id}" if self.client_id else ""
            connect_url = f"{self.url}{query_param}"

            self.websocket = await websockets.connect(connect_url)
            self.connected = True
            self.reconnect_attempts = 0
            logger.info(f"Connected to WebSocket: {self.client_id}")

            # Start listening
            asyncio.create_task(self._listen())
            return True

        except Exception as e:
            logger.error(f"Failed to connect to WebSocket: {e}")
            self.connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnect from WebSocket server."""
        if self.websocket:
            try:
                await self.websocket.close()
            except Exception as e:
                logger.warning(f"Error closing WebSocket: {e}")
        self.connected = False
        logger.info(f"Disconnected from WebSocket: {self.client_id}")

    async def _listen(self) -> None:
        """Listen for messages from server (runs in background)."""
        try:
            async for message in self.websocket:
                try:
                    event = json.loads(message)
                    self.received_events.append(event)

                    # Update last sync id
                    if event.get("sync_id"):
                        self.last_sync_id = event["sync_id"]

                    # Call event handlers
                    event_type = event.get("type", "unknown")
                    await self._dispatch_event(event_type, event)

                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON received: {e}")
        except Exception as e:
            logger.error(f"Error in WebSocket listener: {e}")
            self.connected = False
            await self._attempt_reconnect()

    async def _dispatch_event(self, event_type: str, event: Dict) -> None:
        """Dispatch event to registered handlers.

        Args:
            event_type: Type of event
            event: Event data
        """
        if event_type in self.event_handlers:
            for handler in self.event_handlers[event_type]:
                try:
                    result = handler(event)
                    # Handle both sync and async handlers
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    logger.error(f"Error in event handler for {event_type}: {e}")

    async def _attempt_reconnect(self) -> None:
        """Attempt to reconnect to server."""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.error(f"Max reconnect attempts ({self.max_reconnect_attempts}) reached")
            return

        self.reconnect_attempts += 1
        delay = self.reconnect_delay * (2 ** (self.reconnect_attempts - 1))
        logger.info(f"Attempting to reconnect in {delay}s (attempt {self.reconnect_attempts})")

        await asyncio.sleep(delay)
        await self.connect()

    def on_event(self, event_type: str, handler: Callable) -> None:
        """Register handler for event type.

        Args:
            event_type: Event type to listen for
            handler: Async function to handle event (takes event dict as parameter)
        """
        if event_type not in self.event_handlers:
            self.event_handlers[event_type] = []
        self.event_handlers[event_type].append(handler)

    async def send_heartbeat(self) -> None:
        """Send heartbeat to server."""
        if not self.connected or not self.websocket:
            logger.warning("Cannot send heartbeat: not connected")
            return

        try:
            message = json.dumps({"type": "heartbeat"})
            await self.websocket.send(message)
            logger.debug("Heartbeat sent")
        except Exception as e:
            logger.error(f"Failed to send heartbeat: {e}")
            self.connected = False

    async def get_sync_status(self, sync_id: str) -> None:
        """Request status of a specific sync.

        Args:
            sync_id: Sync identifier
        """
        if not self.connected or not self.websocket:
            logger.warning("Cannot get status: not connected")
            return

        try:
            message = json.dumps({
                "type": "get_status",
                "sync_id": sync_id,
            })
            await self.websocket.send(message)
            logger.debug(f"Status request sent for sync {sync_id}")
        except Exception as e:
            logger.error(f"Failed to send status request: {e}")
            self.connected = False

    def get_received_events(self, event_type: str = None) -> List[Dict]:
        """Get received events.

        Args:
            event_type: Optional filter by event type

        Returns:
            List of received events
        """
        if event_type:
            return [e for e in self.received_events if e.get("type") == event_type]
        return list(self.received_events)

    def clear_events(self) -> None:
        """Clear received events."""
        self.received_events.clear()

    async def wait_for_event(self, event_type: str, timeout: float = 10.0) -> Optional[Dict]:
        """Wait for specific event type.

        Args:
            event_type: Event type to wait for
            timeout: Maximum seconds to wait

        Returns:
            Event data if received, None if timeout
        """
        start_time = datetime.now()
        while True:
            # Check if we already have the event
            for event in self.received_events:
                if event.get("type") == event_type:
                    return event

            # Check timeout
            elapsed = (datetime.now() - start_time).total_seconds()
            if elapsed > timeout:
                logger.warning(f"Timeout waiting for {event_type}")
                return None

            # Wait a bit before checking again
            await asyncio.sleep(0.1)

    async def wait_for_events(
        self,
        event_types: List[str],
        timeout: float = 10.0
    ) -> Dict[str, Optional[Dict]]:
        """Wait for multiple event types.

        Args:
            event_types: List of event types to wait for
            timeout: Maximum seconds to wait

        Returns:
            Dictionary mapping event_type to event data (None if not received)
        """
        results = {}
        start_time = datetime.now()

        for event_type in event_types:
            while True:
                # Check if we already have the event
                for event in self.received_events:
                    if event.get("type") == event_type:
                        results[event_type] = event
                        break

                if event_type in results:
                    break

                # Check timeout
                elapsed = (datetime.now() - start_time).total_seconds()
                if elapsed > timeout:
                    results[event_type] = None
                    break

                await asyncio.sleep(0.1)

        return results


class SyncStatusClientPool:
    """Manage multiple WebSocket client connections."""

    def __init__(self, url: str):
        """Initialize client pool.

        Args:
            url: WebSocket server URL
        """
        self.url = url
        self.clients: Dict[str, SyncStatusClient] = {}

    async def add_client(self, client_id: str) -> SyncStatusClient:
        """Add a new client to the pool.

        Args:
            client_id: Unique client identifier

        Returns:
            SyncStatusClient instance
        """
        if client_id in self.clients:
            return self.clients[client_id]

        client = SyncStatusClient(self.url, client_id)
        success = await client.connect()

        if success:
            self.clients[client_id] = client
            logger.info(f"Added client to pool: {client_id}")
            return client
        else:
            raise Exception(f"Failed to connect client: {client_id}")

    async def remove_client(self, client_id: str) -> None:
        """Remove client from pool.

        Args:
            client_id: Client identifier
        """
        if client_id in self.clients:
            await self.clients[client_id].disconnect()
            del self.clients[client_id]
            logger.info(f"Removed client from pool: {client_id}")

    async def disconnect_all(self) -> None:
        """Disconnect all clients."""
        for client in self.clients.values():
            await client.disconnect()
        self.clients.clear()
        logger.info("Disconnected all clients")

    def get_client(self, client_id: str) -> Optional[SyncStatusClient]:
        """Get client from pool.

        Args:
            client_id: Client identifier

        Returns:
            SyncStatusClient or None if not found
        """
        return self.clients.get(client_id)

    def get_all_clients(self) -> Dict[str, SyncStatusClient]:
        """Get all clients in pool.

        Returns:
            Dictionary of all clients
        """
        return dict(self.clients)

    async def broadcast_heartbeat(self) -> int:
        """Send heartbeat to all connected clients.

        Returns:
            Number of clients that sent heartbeat
        """
        count = 0
        for client in self.clients.values():
            if client.connected:
                await client.send_heartbeat()
                count += 1
        return count

    async def collect_events(self, event_type: str = None) -> Dict[str, List[Dict]]:
        """Collect events from all clients.

        Args:
            event_type: Optional filter by event type

        Returns:
            Dictionary mapping client_id to events
        """
        events = {}
        for client_id, client in self.clients.items():
            events[client_id] = client.get_received_events(event_type)
        return events
