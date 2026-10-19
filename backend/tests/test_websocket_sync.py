"""WebSocket sync status tests - integration and performance."""

import pytest
import asyncio
import json
import time
from datetime import datetime

from app.services.sync_status import (
    SyncStatusTracker,
    WebSocketManager,
    SyncEventType,
)
from app.services.ws_client import SyncStatusClient, SyncStatusClientPool


class TestSyncStatusTracker:
    """Test SyncStatusTracker functionality."""

    def test_start_sync(self):
        """Test starting a sync."""
        tracker = SyncStatusTracker()
        status = tracker.start_sync("sync-1", 100)

        assert status.sync_id == "sync-1"
        assert status.total_videos == 100
        assert status.status == "started"
        assert status.synced_count == 0

    def test_progress_tracking(self):
        """Test progress updates."""
        tracker = SyncStatusTracker()
        tracker.start_sync("sync-1", 100)

        tracker.update_progress("sync-1", 50, 0)
        status = tracker.get_status("sync-1")

        assert status.synced_count == 50
        assert status.progress_percent == 50

    def test_complete_sync(self):
        """Test completing a sync."""
        tracker = SyncStatusTracker()
        tracker.start_sync("sync-1", 100)
        tracker.update_progress("sync-1", 100, 0)
        completed = tracker.complete_sync("sync-1")

        assert completed.status == "complete"
        assert "sync-1" not in tracker.get_all_active()
        assert "sync-1" in tracker.get_all_completed()

    def test_error_sync(self):
        """Test sync with error."""
        tracker = SyncStatusTracker()
        tracker.start_sync("sync-1", 100)
        error_status = tracker.error_sync("sync-1", "Network timeout")

        assert error_status.status == "error"
        assert error_status.error_message == "Network timeout"

    def test_progress_percent_calculation(self):
        """Test progress percentage."""
        tracker = SyncStatusTracker()
        status = tracker.start_sync("sync-1", 200)

        tracker.update_progress("sync-1", 50)
        assert status.progress_percent == 25

        tracker.update_progress("sync-1", 100)
        assert status.progress_percent == 50

        tracker.update_progress("sync-1", 200)
        assert status.progress_percent == 100

    def test_duration_tracking(self):
        """Test operation duration."""
        tracker = SyncStatusTracker()
        tracker.start_sync("sync-1", 10)
        tracker.update_progress("sync-1", 10)
        time.sleep(0.1)
        completed = tracker.complete_sync("sync-1")

        assert completed.duration_seconds >= 0.1

    def test_cleanup_old_completed(self):
        """Test cleanup of old completed syncs."""
        tracker = SyncStatusTracker()
        tracker.max_completed_history = 5

        # Create 10 completed syncs
        for i in range(10):
            tracker.start_sync(f"sync-{i}", 10)
            tracker.complete_sync(f"sync-{i}")

        # Should keep only last 5
        completed = tracker.get_all_completed()
        assert len(completed) == 5


class TestWebSocketManager:
    """Test WebSocketManager functionality."""

    @pytest.mark.asyncio
    async def test_manager_creation(self):
        """Test creating a WebSocketManager."""
        tracker = SyncStatusTracker()
        manager = WebSocketManager(tracker)

        assert manager.status_tracker is tracker
        assert manager.get_connected_clients() == 0
        assert manager.get_total_connections() == 0

    @pytest.mark.asyncio
    async def test_sync_started_event(self):
        """Test emit sync started event."""
        tracker = SyncStatusTracker()
        manager = WebSocketManager(tracker)

        # This should not raise
        await manager.emit_sync_started("sync-1", 100)

    @pytest.mark.asyncio
    async def test_sync_progress_event(self):
        """Test emit sync progress event."""
        tracker = SyncStatusTracker()
        manager = WebSocketManager(tracker)

        await manager.emit_sync_progress("sync-1", 50, 100, 0)

    @pytest.mark.asyncio
    async def test_sync_complete_event(self):
        """Test emit sync complete event."""
        tracker = SyncStatusTracker()
        manager = WebSocketManager(tracker)

        await manager.emit_sync_complete("sync-1", 100)

    @pytest.mark.asyncio
    async def test_sync_error_event(self):
        """Test emit sync error event."""
        tracker = SyncStatusTracker()
        manager = WebSocketManager(tracker)

        await manager.emit_sync_error("sync-1", "Network error")

    @pytest.mark.asyncio
    async def test_milestone_detected_event(self):
        """Test emit milestone detected event."""
        tracker = SyncStatusTracker()
        manager = WebSocketManager(tracker)

        await manager.emit_milestone_detected(
            "sync-1",
            "first_success",
            "First Successful Dive",
            "You nailed your first dive!"
        )


class TestSyncStatusClient:
    """Test SyncStatusClient functionality."""

    def test_client_creation(self):
        """Test creating a client."""
        client = SyncStatusClient("ws://localhost:8000/ws", "client-1")

        assert client.url == "ws://localhost:8000/ws"
        assert client.client_id == "client-1"
        assert client.connected is False

    def test_event_handler_registration(self):
        """Test registering event handlers."""
        client = SyncStatusClient("ws://localhost:8000/ws", "client-1")

        def handler(event):
            pass

        client.on_event("sync_started", handler)
        assert "sync_started" in client.event_handlers
        assert handler in client.event_handlers["sync_started"]

    def test_received_events_tracking(self):
        """Test tracking received events."""
        client = SyncStatusClient("ws://localhost:8000/ws", "client-1")

        # Simulate receiving events
        client.received_events.append({
            "type": "sync_started",
            "sync_id": "sync-1",
            "data": {"total_videos": 100}
        })

        events = client.get_received_events("sync_started")
        assert len(events) == 1
        assert events[0]["type"] == "sync_started"

    def test_clear_events(self):
        """Test clearing received events."""
        client = SyncStatusClient("ws://localhost:8000/ws", "client-1")

        client.received_events.append({"type": "sync_started"})
        assert len(client.received_events) == 1

        client.clear_events()
        assert len(client.received_events) == 0

    @pytest.mark.asyncio
    async def test_wait_for_event(self):
        """Test waiting for specific event."""
        client = SyncStatusClient("ws://localhost:8000/ws", "client-1")

        # Simulate receiving an event in background
        async def add_event():
            await asyncio.sleep(0.1)
            client.received_events.append({
                "type": "sync_complete",
                "sync_id": "sync-1"
            })

        task = asyncio.create_task(add_event())
        event = await client.wait_for_event("sync_complete", timeout=2.0)

        await task
        assert event is not None
        assert event["type"] == "sync_complete"

    @pytest.mark.asyncio
    async def test_wait_for_event_timeout(self):
        """Test timeout waiting for event."""
        client = SyncStatusClient("ws://localhost:8000/ws", "client-1")

        event = await client.wait_for_event("nonexistent", timeout=0.1)
        assert event is None


class TestSyncStatusClientPool:
    """Test SyncStatusClientPool functionality."""

    def test_pool_creation(self):
        """Test creating a client pool."""
        pool = SyncStatusClientPool("ws://localhost:8000/ws")

        assert pool.url == "ws://localhost:8000/ws"
        assert len(pool.get_all_clients()) == 0

    @pytest.mark.asyncio
    async def test_client_pool_management(self):
        """Test adding and removing clients from pool."""
        pool = SyncStatusClientPool("ws://localhost:8000/ws")

        # Note: This test won't actually connect to a server
        # It just tests the pool management logic
        pool.clients["client-1"] = SyncStatusClient(
            "ws://localhost:8000/ws",
            "client-1"
        )

        assert pool.get_client("client-1") is not None
        assert len(pool.get_all_clients()) == 1

        await pool.remove_client("client-1")
        assert pool.get_client("client-1") is None


class TestWebSocketPerformance:
    """Performance tests for WebSocket system."""

    def test_tracker_high_volume_syncs(self):
        """Keep high-volume correctness in the ordinary CI gate."""
        tracker = SyncStatusTracker()
        for i in range(1000):
            tracker.start_sync(f"sync-{i}", 100)

        active = tracker.get_all_active()
        assert len(active) == 1000
        assert all(active[f"sync-{i}"].total_videos == 100 for i in range(1000))

    @pytest.mark.performance
    def test_tracker_high_volume_timing(self):
        """Run the machine-speed benchmark separately on a quiet box."""
        tracker = SyncStatusTracker()
        start = time.perf_counter()

        # Start 1000 syncs
        for i in range(1000):
            tracker.start_sync(f"sync-{i}", 100)

        duration = time.perf_counter() - start

        assert len(tracker.get_all_active()) == 1000
        assert duration < 1.0  # Should complete in <1 second

    @pytest.mark.parametrize("benchmark", [False, pytest.param(True, marks=pytest.mark.performance)])
    def test_tracker_progress_updates(self, benchmark):
        """Test performance of progress updates."""
        tracker = SyncStatusTracker()

        # Start 100 syncs
        for i in range(100):
            tracker.start_sync(f"sync-{i}", 100)

        start = time.perf_counter()

        # Update all 100 syncs, 10 times each = 1000 updates
        for update in range(10):
            for i in range(100):
                tracker.update_progress(f"sync-{i}", (update + 1) * 10)

        duration = time.perf_counter() - start

        active = tracker.get_all_active()
        assert len(active) == 100
        assert all(s.synced_count == 100 for s in active.values())
        if benchmark:
            assert duration < 1.0  # 1000 updates in <1 second

    @pytest.mark.parametrize("benchmark", [False, pytest.param(True, marks=pytest.mark.performance)])
    def test_tracker_completion_performance(self, benchmark):
        """Test performance of completing syncs."""
        tracker = SyncStatusTracker()

        # Start 100 syncs (tracker maintains rolling window of 100 completed)
        for i in range(100):
            tracker.start_sync(f"sync-{i}", 100)

        start = time.perf_counter()

        # Complete all 100 syncs
        for i in range(100):
            tracker.complete_sync(f"sync-{i}")

        duration = time.perf_counter() - start

        assert len(tracker.get_all_completed()) == 100
        assert tracker.get_all_active() == {}
        if benchmark:
            assert duration < 0.5  # Complete 100 syncs in <500ms

    @pytest.mark.parametrize("benchmark", [False, pytest.param(True, marks=pytest.mark.performance)])
    def test_client_event_storage(self, benchmark):
        """Test client event storage performance."""
        client = SyncStatusClient("ws://localhost:8000/ws", "client-1")

        start = time.perf_counter()

        # Store 10000 events
        for i in range(10000):
            client.received_events.append({
                "type": "sync_progress",
                "sync_id": f"sync-{i % 100}",
                "data": {"progress": i % 100}
            })

        duration = time.perf_counter() - start

        assert len(client.received_events) == 10000
        assert client.received_events[0]['sync_id'] == 'sync-0'
        assert client.received_events[-1]['data']['progress'] == 99
        if benchmark:
            assert duration < 0.5  # Store 10000 events in <500ms

    @pytest.mark.parametrize("benchmark", [False, pytest.param(True, marks=pytest.mark.performance)])
    def test_event_filtering_performance(self, benchmark):
        """Test performance of filtering events."""
        client = SyncStatusClient("ws://localhost:8000/ws", "client-1")

        # Add 1000 events of different types
        for i in range(1000):
            event_type = ["sync_started", "sync_progress", "sync_complete"][i % 3]
            client.received_events.append({
                "type": event_type,
                "sync_id": f"sync-{i % 100}"
            })

        start = time.perf_counter()

        # Filter events 100 times
        for _ in range(100):
            events = client.get_received_events("sync_progress")

        duration = time.perf_counter() - start

        assert len(events) == 333
        assert all(event['type'] == 'sync_progress' for event in events)
        if benchmark:
            assert duration < 0.5  # 100 filters of 1000 events in <500ms


class TestWebSocketIntegration:
    """Integration tests for WebSocket system."""

    def test_sync_to_event_flow(self):
        """Test flow from sync tracking to events."""
        tracker = SyncStatusTracker()
        manager = WebSocketManager(tracker)

        # Start a sync
        status = tracker.start_sync("sync-1", 100)
        assert status.status == "started"

        # Progress updates
        tracker.update_progress("sync-1", 50)
        status = tracker.get_status("sync-1")
        assert status.progress_percent == 50

        # Complete
        completed = tracker.complete_sync("sync-1")
        assert completed.status == "complete"

    def test_multiple_tracker_instances(self):
        """Test multiple tracker instances are independent."""
        tracker1 = SyncStatusTracker()
        tracker2 = SyncStatusTracker()

        tracker1.start_sync("sync-1", 100)
        tracker2.start_sync("sync-2", 200)

        assert len(tracker1.get_all_active()) == 1
        assert len(tracker2.get_all_active()) == 1
        assert tracker1.get_status("sync-1") is not None
        assert tracker2.get_status("sync-2") is not None
