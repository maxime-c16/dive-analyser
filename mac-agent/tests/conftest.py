"""Pytest fixtures for mac-agent tests."""

import pytest
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any
from unittest.mock import AsyncMock, MagicMock
import json

from src.config import ServerConfig, SyncConfig
from src.sync_client import SyncClient
from src.types import SyncResult


@pytest.fixture
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def server_config():
    """Server configuration for testing."""
    return ServerConfig(
        url="http://localhost:8000",
        api_key="test_api_key_1234567890",
        timeout_seconds=30,
    )


@pytest.fixture
def sync_config():
    """Sync configuration for testing."""
    return SyncConfig(
        interval_seconds=300,
        batch_size=50,
        max_retries=3,
    )


@pytest.fixture
def sample_video_data() -> Dict[str, Any]:
    """Sample video metadata for testing."""
    return {
        'dive_code': '101B',
        'height': '1m',
        'performance': 'G',
        'phase1_performance': None,
        'phase2_performance': None,
        'video_uuid': 'test-uuid-12345',
        'date': datetime.now().isoformat(),
        'is_sync': False,
        'is_smack': False,
        'person_name': None,
    }


@pytest.fixture
def multiple_videos() -> List[Dict[str, Any]]:
    """Multiple sample videos for batch testing."""
    videos = []
    for i in range(10):
        videos.append({
            'dive_code': f'10{i}B',
            'height': '1m',
            'performance': 'G',
            'phase1_performance': None,
            'phase2_performance': None,
            'video_uuid': f'test-uuid-{i:05d}',
            'date': (datetime.now() - timedelta(hours=i)).isoformat(),
            'is_sync': False,
            'is_smack': False,
            'person_name': None,
        })
    return videos


@pytest.fixture
async def sync_client(server_config, sync_config):
    """Create sync client for testing."""
    from src.error_recovery import RetryConfig

    retry_config = RetryConfig(
        max_retries=sync_config.max_retries,
        initial_delay=0.1,  # Fast backoff for tests
        max_delay=1.0,
    )
    client = SyncClient(server_config, retry_config)
    yield client
    await client.close()


class MockResponse:
    """Mock HTTP response."""

    def __init__(
        self,
        status_code: int,
        json_data: Dict = None,
        headers: Dict = None,
    ):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.headers = headers or {}

    def json(self):
        """Return JSON response."""
        return self._json_data


class MockHTTPClient:
    """Mock httpx.AsyncClient for testing."""

    def __init__(self):
        self.requests = []
        self.responses = {}
        self.next_response = None
        self.call_count = 0

    def set_response(
        self,
        path: str,
        status_code: int,
        json_data: Dict = None,
        headers: Dict = None,
    ):
        """Configure response for a path."""
        self.responses[path] = MockResponse(status_code, json_data, headers)

    def set_next_response(
        self,
        status_code: int,
        json_data: Dict = None,
        headers: Dict = None,
    ):
        """Set next response to return."""
        self.next_response = MockResponse(status_code, json_data, headers)

    async def post(self, path: str, json: Dict = None, **kwargs):
        """Mock POST request."""
        self.call_count += 1
        self.requests.append({
            'method': 'POST',
            'path': path,
            'json': json,
            'kwargs': kwargs,
        })

        if self.next_response:
            response = self.next_response
            self.next_response = None
            return response

        if path in self.responses:
            return self.responses[path]

        # Default response
        return MockResponse(500, {'detail': 'Not configured'})

    async def aclose(self):
        """Mock close."""
        pass

    def get_last_request(self):
        """Get last request made."""
        if self.requests:
            return self.requests[-1]
        return None


@pytest.fixture
def mock_http_client():
    """Mock HTTP client."""
    return MockHTTPClient()
