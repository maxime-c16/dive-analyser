"""
Mock HTTP server for testing mac-agent sync client without a real backend.

Provides a simple mock server that simulates sync endpoint responses,
supports configurable delays and errors for testing resilience.
"""

from typing import List, Dict, Optional, Callable
from datetime import datetime
import json
from unittest.mock import MagicMock, AsyncMock, patch
import httpx


class MockSyncServer:
    """
    Mock HTTP server for testing mac-agent sync client.

    Simulates POST /api/v1/videos/sync and POST /api/v1/videos/batch endpoints.
    Allows configuration of responses (success, error, timeout, delay).
    """

    def __init__(self):
        """Initialize mock server state"""
        self.requests: List[Dict] = []  # All received requests
        self.config = {
            "success_rate": 1.0,  # 100% success by default
            "response_delay": 0.0,  # No delay by default
            "timeout_after_requests": None,  # Timeout after N requests
            "error_code": 500,  # What error to return
            "duplicates": [],  # UUIDs that should return 409
        }
        self.next_dive_id = 1000

    def set_success_rate(self, rate: float) -> None:
        """Set success rate (0.0-1.0) for random failures"""
        self.config["success_rate"] = rate

    def set_delay(self, seconds: float) -> None:
        """Set response delay in seconds"""
        self.config["response_delay"] = seconds

    def set_timeout_after(self, request_count: int) -> None:
        """Timeout after N requests"""
        self.config["timeout_after_requests"] = request_count

    def mark_duplicate(self, video_uuid: str) -> None:
        """Mark UUID as duplicate for future syncs"""
        self.config["duplicates"].append(video_uuid)

    def reset(self) -> None:
        """Reset mock server state"""
        self.requests = []
        self.next_dive_id = 1000
        self.config = {
            "success_rate": 1.0,
            "response_delay": 0.0,
            "timeout_after_requests": None,
            "error_code": 500,
            "duplicates": [],
        }

    def get_requests(self) -> List[Dict]:
        """Get all requests received"""
        return self.requests

    def get_request_count(self) -> int:
        """Get number of requests received"""
        return len(self.requests)

    async def handle_sync_single(self, data: Dict) -> tuple[int, Dict]:
        """
        Handle POST /api/v1/videos/sync request

        Args:
            data: Request body

        Returns:
            Tuple of (status_code, response_body)
        """
        self.requests.append({
            "endpoint": "/api/v1/videos/sync",
            "timestamp": datetime.now().isoformat(),
            "data": data,
        })

        # Check for timeout
        if (self.config["timeout_after_requests"] and
            len(self.requests) > self.config["timeout_after_requests"]):
            raise httpx.TimeoutException("Mock server timeout")

        # Check for duplicate
        video_uuid = data.get("video_uuid")
        if video_uuid in self.config["duplicates"]:
            return 409, {
                "error": "Duplicate video",
                "message": f"Video {video_uuid} already synced"
            }

        # Check for random failure
        import random
        if random.random() > self.config["success_rate"]:
            return self.config["error_code"], {
                "error": "Server error",
                "message": "Mock server error"
            }

        # Success response
        await self._simulate_delay()
        return 201, {
            "dive_id": self.next_dive_id,
            "message": "Video synced successfully",
            "created": True,
        }

    async def handle_sync_batch(self, data: Dict) -> tuple[int, Dict]:
        """
        Handle POST /api/v1/videos/batch request

        Args:
            data: Request body with 'videos' list

        Returns:
            Tuple of (status_code, response_body)
        """
        videos = data.get("videos", [])

        self.requests.append({
            "endpoint": "/api/v1/videos/batch",
            "timestamp": datetime.now().isoformat(),
            "video_count": len(videos),
            "data": data,
        })

        # Check for timeout
        if (self.config["timeout_after_requests"] and
            len(self.requests) > self.config["timeout_after_requests"]):
            raise httpx.TimeoutException("Mock server timeout")

        # Process each video
        succeeded = 0
        failed = 0
        errors = []

        for video in videos:
            video_uuid = video.get("video_uuid")

            # Check for duplicate
            if video_uuid in self.config["duplicates"]:
                failed += 1
                errors.append({
                    "video_uuid": video_uuid,
                    "error": "Duplicate video"
                })
                continue

            # Check for random failure
            import random
            if random.random() > self.config["success_rate"]:
                failed += 1
                errors.append({
                    "video_uuid": video_uuid,
                    "error": "Internal server error"
                })
                continue

            # Success
            succeeded += 1
            self.next_dive_id += 1

        await self._simulate_delay()

        return 200, {
            "total": len(videos),
            "succeeded": succeeded,
            "failed": failed,
            "errors": errors,
        }

    async def _simulate_delay(self) -> None:
        """Simulate response delay"""
        import asyncio
        if self.config["response_delay"] > 0:
            await asyncio.sleep(self.config["response_delay"])


class MockHTTPClient:
    """
    Mock HTTPX client for testing sync client in isolation.

    Wraps MockSyncServer to simulate HTTP responses.
    """

    def __init__(self, mock_server: Optional[MockSyncServer] = None):
        """
        Initialize mock HTTP client

        Args:
            mock_server: MockSyncServer instance (created if not provided)
        """
        self.mock_server = mock_server or MockSyncServer()
        self.headers = {}
        self.timeout = 30.0

    async def post(self, url: str, json: Dict = None, **kwargs) -> "MockResponse":
        """
        Mock POST request

        Args:
            url: Request URL
            json: JSON body
            **kwargs: Additional arguments (headers, timeout, etc.)

        Returns:
            MockResponse object
        """
        self.headers = kwargs.get("headers", {})
        self.timeout = kwargs.get("timeout", 30.0)

        try:
            # Route to appropriate handler
            if "/videos/sync" in url and "/batch" not in url:
                status, body = await self.mock_server.handle_sync_single(json or {})
            elif "/videos/batch" in url:
                status, body = await self.mock_server.handle_sync_batch(json or {})
            else:
                status, body = 404, {"error": "Not found"}

            return MockResponse(status, body, url)

        except httpx.TimeoutException as e:
            raise httpx.TimeoutException("Mock timeout") from e

    def get_requests(self) -> List[Dict]:
        """Get all requests received"""
        return self.mock_server.get_requests()

    def reset(self) -> None:
        """Reset mock server"""
        self.mock_server.reset()


class MockResponse:
    """Mock HTTP response"""

    def __init__(self, status_code: int, json_data: Dict, url: str = ""):
        self.status_code = status_code
        self._json_data = json_data
        self.url = url
        self.headers = {"content-type": "application/json"}

    def json(self) -> Dict:
        """Get JSON response body"""
        return self._json_data

    def raise_for_status(self) -> None:
        """Raise exception if status is error"""
        if 400 <= self.status_code < 600:
            raise httpx.HTTPStatusError(
                f"{self.status_code}",
                request=None,
                response=self
            )


async def create_mock_client_fixture() -> MockHTTPClient:
    """
    Pytest fixture that creates a configured mock HTTP client.

    Usage in tests:
        async def test_sync(mock_client):
            response = await mock_client.post(
                "http://localhost:8000/api/v1/videos/sync",
                json=test_metadata
            )
            assert response.status_code == 201
    """
    return MockHTTPClient()
