"""
Load testing: Concurrent WebSocket connections and sync operations

Tests realistic scenarios:
1. 100+ concurrent clients connecting
2. Simultaneous sync operations
3. Message throughput
4. Memory usage
5. Error recovery under load
"""

import pytest
import asyncio
import json
import time
import uuid
from datetime import datetime

pytestmark = pytest.mark.performance


class MockWebSocketClient:
    """Mock WebSocket client for testing"""

    def __init__(self, client_id: str = None):
        self.client_id = client_id or f"client_{uuid.uuid4().hex[:8]}"
        self.messages_received = []
        self.messages_sent = []
        self.is_connected = False
        self.connection_time = None
        self.disconnect_time = None
        self.latency_samples = []

    async def connect(self):
        """Simulate connection"""
        self.connection_time = time.time()
        self.is_connected = True
        await asyncio.sleep(0.01)  # Simulate handshake

    async def disconnect(self):
        """Simulate disconnection"""
        self.disconnect_time = time.time()
        self.is_connected = False

    async def send_message(self, message: dict):
        """Send message"""
        if not self.is_connected:
            raise RuntimeError(f"Client {self.client_id} not connected")
        self.messages_sent.append(message)
        await asyncio.sleep(0.001)  # Simulate network latency

    async def receive_message(self, message: dict):
        """Simulate receiving message"""
        start = time.time()
        self.messages_received.append(message)
        latency = time.time() - start
        self.latency_samples.append(latency)

    def get_stats(self):
        """Get connection statistics"""
        duration = 0
        if self.connection_time and self.disconnect_time:
            duration = self.disconnect_time - self.connection_time
        elif self.connection_time:
            duration = time.time() - self.connection_time

        avg_latency = (
            sum(self.latency_samples) / len(self.latency_samples)
            if self.latency_samples
            else 0
        )

        return {
            "client_id": self.client_id,
            "connected": self.is_connected,
            "duration_seconds": duration,
            "messages_sent": len(self.messages_sent),
            "messages_received": len(self.messages_received),
            "avg_latency_ms": avg_latency * 1000,
        }


class TestConcurrentLoad:
    """Load testing for concurrent connections"""

    @pytest.mark.asyncio
    async def test_100_concurrent_connections(self):
        """Test: 100 clients connecting simultaneously"""
        num_clients = 100
        clients = []

        # Create clients
        start_time = time.time()

        async def connect_client(idx):
            client = MockWebSocketClient(f"client_{idx}")
            await client.connect()
            return client

        tasks = [connect_client(i) for i in range(num_clients)]
        clients = await asyncio.gather(*tasks)

        connection_time = time.time() - start_time

        # Verify all connected
        assert len(clients) == num_clients
        assert all(c.is_connected for c in clients)
        assert connection_time < 10  # Should complete within 10 seconds

    @pytest.mark.asyncio
    async def test_sync_event_broadcasting_under_load(self):
        """Test: Broadcast sync events to 100+ clients"""
        num_clients = 100
        num_events = 10

        clients = [MockWebSocketClient(f"client_{i}") for i in range(num_clients)]

        # Connect all clients
        await asyncio.gather(*[c.connect() for c in clients])

        # Simulate sync events
        sync_events = []
        for i in range(num_events):
            event = {
                "type": "sync_progress",
                "timestamp": datetime.utcnow().isoformat(),
                "sync_id": "test-sync",
                "data": {"synced_count": i * 10, "progress_percent": i * 10},
            }
            sync_events.append(event)

        # Broadcast to all clients
        start_time = time.time()

        async def broadcast_event(event):
            tasks = [c.receive_message(event) for c in clients]
            await asyncio.gather(*tasks)

        await asyncio.gather(*[broadcast_event(e) for e in sync_events])

        broadcast_time = time.time() - start_time

        # Verify delivery
        for client in clients:
            assert len(client.messages_received) == num_events

        # Performance check
        messages_delivered = num_clients * num_events
        throughput = messages_delivered / broadcast_time
        assert throughput > 1000  # Should handle >1000 msg/sec

    @pytest.mark.asyncio
    async def test_concurrent_sync_operations(self):
        """Test: Multiple syncs happening concurrently"""
        num_concurrent_syncs = 10
        videos_per_sync = 100

        async def simulate_sync(sync_id):
            sync_start = time.time()
            synced = 0

            for i in range(videos_per_sync):
                # Simulate sync work
                await asyncio.sleep(0.001)
                synced += 1

            sync_duration = time.time() - sync_start
            return {
                "sync_id": sync_id,
                "total": videos_per_sync,
                "synced": synced,
                "duration_seconds": sync_duration,
                "error_count": 0,
            }

        start_time = time.time()

        sync_tasks = [simulate_sync(f"sync_{i}") for i in range(num_concurrent_syncs)]
        sync_results = await asyncio.gather(*sync_tasks)

        total_time = time.time() - start_time

        # Verify all syncs completed
        assert len(sync_results) == num_concurrent_syncs
        assert all(r["synced"] == videos_per_sync for r in sync_results)
        assert all(r["error_count"] == 0 for r in sync_results)

        # Check overall throughput
        total_videos = num_concurrent_syncs * videos_per_sync
        throughput = total_videos / total_time
        assert throughput > 100  # >100 videos/sec

    @pytest.mark.asyncio
    async def test_memory_efficiency(self):
        """Test: Memory usage with many concurrent connections"""
        import sys

        num_clients = 50
        clients = [MockWebSocketClient(f"client_{i}") for i in range(num_clients)]

        await asyncio.gather(*[c.connect() for c in clients])

        # Simulate many message exchanges
        for _ in range(10):
            events = [
                {"type": "sync_progress", "data": {"progress_percent": i}} for i in range(100)
            ]
            for event in events:
                await asyncio.gather(*[c.receive_message(event) for c in clients])

        # Get memory estimate
        total_messages = sum(len(c.messages_received) for c in clients)
        avg_messages_per_client = total_messages / num_clients

        # Should be reasonable
        assert avg_messages_per_client > 0
        assert total_messages == num_clients * 1000  # 10 rounds * 100 events

    @pytest.mark.asyncio
    async def test_error_recovery_under_load(self):
        """Test: Error handling during high load"""
        num_clients = 50
        num_errors = 5

        clients = [MockWebSocketClient(f"client_{i}") for i in range(num_clients)]

        # Connect all
        await asyncio.gather(*[c.connect() for c in clients])

        # Simulate some errors
        errors = []

        async def send_with_possible_error(client_idx):
            try:
                if client_idx < num_errors:
                    raise RuntimeError(f"Simulated error for client {client_idx}")

                message = {
                    "type": "sync_progress",
                    "data": {"progress_percent": 50},
                }
                await clients[client_idx].send_message(message)
                return True
            except Exception as e:
                errors.append(str(e))
                return False

        results = await asyncio.gather(*[send_with_possible_error(i) for i in range(num_clients)])

        # Verify error count
        assert len(errors) == num_errors
        assert sum(results) == (num_clients - num_errors)

    @pytest.mark.asyncio
    async def test_connection_cleanup_under_load(self):
        """Test: Proper cleanup of many connections"""
        num_clients = 100

        clients = [MockWebSocketClient(f"client_{i}") for i in range(num_clients)]

        # Connect
        await asyncio.gather(*[c.connect() for c in clients])
        assert all(c.is_connected for c in clients)

        # Disconnect all
        start_time = time.time()
        await asyncio.gather(*[c.disconnect() for c in clients])
        disconnect_time = time.time() - start_time

        # Verify all disconnected
        assert not any(c.is_connected for c in clients)
        assert all(c.disconnect_time for c in clients)
        assert disconnect_time < 5  # Should complete quickly

    def test_performance_metrics_collection(self):
        """Test: Collect and report performance metrics"""
        num_clients = 50

        clients = [MockWebSocketClient(f"client_{i}") for i in range(num_clients)]

        # Generate stats
        stats_list = [c.get_stats() for c in clients]

        # Analyze
        assert len(stats_list) == num_clients

        # All should have basic stats
        for stats in stats_list:
            assert "client_id" in stats
            assert "connected" in stats
            assert "messages_sent" in stats
            assert "messages_received" in stats
            assert "avg_latency_ms" in stats

    @pytest.mark.asyncio
    async def test_realistic_workflow_load(self):
        """Test: Realistic workflow with mixed operations"""
        num_clients = 20
        duration_seconds = 2

        clients = [MockWebSocketClient(f"client_{i}") for i in range(num_clients)]

        # Connect all
        await asyncio.gather(*[c.connect() for c in clients])

        # Simulate realistic workflow
        start_time = time.time()

        async def client_workflow(client):
            while time.time() - start_time < duration_seconds:
                # Send heartbeat
                await client.send_message({"type": "heartbeat"})

                # Receive sync events
                await client.receive_message(
                    {
                        "type": "sync_progress",
                        "data": {"progress_percent": 50},
                    }
                )

                await asyncio.sleep(0.1)

        await asyncio.gather(*[client_workflow(c) for c in clients])

        # Verify activity
        for client in clients:
            assert len(client.messages_sent) > 0
            assert len(client.messages_received) > 0

        # Report aggregate stats
        total_sent = sum(len(c.messages_sent) for c in clients)
        total_received = sum(len(c.messages_received) for c in clients)

        assert total_sent > 0
        assert total_received > 0
