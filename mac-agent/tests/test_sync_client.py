"""Tests for sync client implementation."""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock

from src.sync_client import SyncClient
from src.types import SyncResult, BatchSyncResult


@pytest.mark.asyncio
async def test_sync_single_video_success(sync_client, sample_video_data, mock_http_client):
    """Test successful single video sync."""
    # Arrange
    mock_http_client.set_response(
        '/api/v1/videos/sync',
        status_code=201,
        json_data={'dive_id': 42, 'video_uuid': sample_video_data['video_uuid']},
    )
    sync_client.client.post = mock_http_client.post

    # Act
    result = await sync_client.sync_video(sample_video_data)

    # Assert
    assert result.success is True
    assert result.dive_id == 42
    assert result.http_status == 201
    assert result.video_uuid == sample_video_data['video_uuid']
    assert result.retry_count == 0
    assert mock_http_client.call_count == 1


@pytest.mark.asyncio
async def test_sync_single_video_duplicate(sync_client, sample_video_data, mock_http_client):
    """Test sync of duplicate video (409 Conflict)."""
    # Arrange
    mock_http_client.set_response(
        '/api/v1/videos/sync',
        status_code=409,
        json_data={'detail': 'Duplicate video'},
    )
    sync_client.client.post = mock_http_client.post

    # Act
    result = await sync_client.sync_video(sample_video_data)

    # Assert
    assert result.success is False
    assert result.http_status == 409
    assert 'Duplicate' in result.error_message
    assert result.retry_count == 0
    assert mock_http_client.call_count == 1  # No retry for 409


@pytest.mark.asyncio
async def test_sync_single_video_validation_error(sync_client, sample_video_data, mock_http_client):
    """Test sync with validation error (400 Bad Request)."""
    # Arrange
    mock_http_client.set_response(
        '/api/v1/videos/sync',
        status_code=400,
        json_data={'detail': 'Invalid dive code'},
    )
    sync_client.client.post = mock_http_client.post

    # Act
    result = await sync_client.sync_video(sample_video_data)

    # Assert
    assert result.success is False
    assert result.http_status == 400
    assert 'Invalid dive code' in result.error_message
    assert result.retry_count == 0
    assert mock_http_client.call_count == 1  # No retry for 400


@pytest.mark.asyncio
async def test_sync_single_video_auth_error(sync_client, sample_video_data, mock_http_client):
    """Test sync with auth error (401 Unauthorized)."""
    # Arrange
    mock_http_client.set_response(
        '/api/v1/videos/sync',
        status_code=401,
        json_data={'detail': 'Invalid API key'},
    )
    sync_client.client.post = mock_http_client.post

    # Act
    result = await sync_client.sync_video(sample_video_data)

    # Assert
    assert result.success is False
    assert result.http_status == 401
    assert result.retry_count == 0
    assert mock_http_client.call_count == 1  # No retry for 401


@pytest.mark.asyncio
async def test_sync_single_video_server_error(sync_client, sample_video_data, mock_http_client):
    """Test sync with server error (500) - should retry."""
    # Arrange
    mock_http_client.set_next_response(status_code=500, json_data={'detail': 'Server error'})
    sync_client.client.post = mock_http_client.post

    # Act
    result = await sync_client.sync_video(sample_video_data)

    # Assert
    assert result.success is False
    assert result.http_status == 500
    assert result.retry_count > 0  # Should have retried
    assert mock_http_client.call_count > 1  # Multiple attempts


@pytest.mark.asyncio
async def test_sync_retry_succeeds_on_second_attempt(sync_client, sample_video_data, mock_http_client):
    """Test retry logic: first request fails, second succeeds."""
    # Arrange
    call_count = [0]

    async def mock_post_with_retry(path, json=None, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            # First call fails with 500
            return MagicMock(
                status_code=500,
                json=lambda: {'detail': 'Temporary error'},
            )
        else:
            # Second call succeeds
            return MagicMock(
                status_code=201,
                json=lambda: {'dive_id': 99, 'video_uuid': sample_video_data['video_uuid']},
            )

    sync_client.client.post = mock_post_with_retry
    sync_client.retry_config.initial_delay = 0.01  # Fast retry for test

    # Act
    result = await sync_client.sync_video(sample_video_data)

    # Assert
    assert result.success is True
    assert result.dive_id == 99
    assert result.retry_count == 1
    assert call_count[0] == 2


@pytest.mark.asyncio
async def test_sync_retry_exhaustion(sync_client, sample_video_data, mock_http_client):
    """Test that retries are exhausted after max_retries."""
    # Arrange
    mock_http_client.set_next_response(status_code=503)  # Always return 503
    sync_client.client.post = mock_http_client.post
    sync_client.retry_config.max_retries = 2
    sync_client.retry_config.initial_delay = 0.01  # Fast retry for test

    # Act
    result = await sync_client.sync_video(sample_video_data)

    # Assert
    assert result.success is False
    assert result.retry_count == 2
    assert mock_http_client.call_count == 3  # Initial + 2 retries


@pytest.mark.asyncio
async def test_sync_batch_single_chunk(sync_client, multiple_videos, mock_http_client):
    """Test batch sync with single chunk."""
    # Arrange
    success_count = [0]

    async def mock_post(path, json=None, **kwargs):
        success_count[0] += 1
        return MagicMock(
            status_code=201,
            json=lambda: {'dive_id': success_count[0]},
        )

    sync_client.client.post = mock_post

    # Act
    result = await sync_client.sync_batch(multiple_videos[:5], batch_size=10)

    # Assert
    assert isinstance(result, BatchSyncResult)
    assert result.total == 5
    assert result.succeeded == 5
    assert result.failed == 0
    assert result.success_rate == 100.0


@pytest.mark.asyncio
async def test_sync_batch_multiple_chunks(sync_client, multiple_videos, mock_http_client):
    """Test batch sync with multiple chunks."""
    # Arrange
    sync_client.client.post = mock_http_client.post
    call_count = [0]

    async def mock_post(path, json=None, **kwargs):
        call_count[0] += 1
        return MagicMock(
            status_code=201,
            json=lambda: {'dive_id': call_count[0]},
        )

    sync_client.client.post = mock_post

    # Act
    result = await sync_client.sync_batch(multiple_videos, batch_size=3)

    # Assert
    assert result.total == 10
    assert result.succeeded == 10
    assert result.failed == 0
    assert call_count[0] == 10  # 10 individual requests


@pytest.mark.asyncio
async def test_sync_batch_mixed_results(sync_client, multiple_videos):
    """Test batch with mixed success/failure results."""
    # Arrange
    call_count = [0]

    async def mock_post(path, json=None, **kwargs):
        call_count[0] += 1
        # Every 3rd request fails
        if call_count[0] % 3 == 0:
            return MagicMock(
                status_code=400,
                json=lambda: {'detail': 'Invalid'},
            )
        else:
            return MagicMock(
                status_code=201,
                json=lambda: {'dive_id': call_count[0]},
            )

    sync_client.client.post = mock_post

    # Act
    result = await sync_client.sync_batch(multiple_videos, batch_size=5)

    # Assert
    assert result.total == 10
    assert result.succeeded == 7  # 3 fail (every 3rd)
    assert result.failed == 3
    assert result.success_rate == 70.0


@pytest.mark.asyncio
async def test_sync_rate_limiting(sync_client, sample_video_data, mock_http_client):
    """Test handling of rate limiting (429)."""
    # Arrange
    mock_http_client.set_response(
        '/api/v1/videos/sync',
        status_code=429,
        json_data={'detail': 'Rate limited'},
        headers={'Retry-After': '2'},
    )
    sync_client.client.post = mock_http_client.post

    # Act
    result = await sync_client.sync_video(sample_video_data)

    # Assert
    assert result.success is False
    assert result.http_status == 429
    assert sync_client.rate_limit_reset_time is not None


@pytest.mark.asyncio
async def test_sync_statistics_tracking(sync_client, multiple_videos):
    """Test that sync statistics are properly tracked."""
    # Arrange
    call_count = [0]

    async def mock_post(path, json=None, **kwargs):
        call_count[0] += 1
        if call_count[0] <= 2:
            return MagicMock(
                status_code=201,
                json=lambda: {'dive_id': call_count[0]},
            )
        else:
            return MagicMock(
                status_code=400,
                json=lambda: {'detail': 'Invalid'},
            )

    sync_client.client.post = mock_post
    sync_client.reset_stats()

    # Act
    result = await sync_client.sync_batch(multiple_videos[:5], batch_size=5)

    # Assert
    stats = sync_client.get_stats()
    assert stats['total_attempts'] == 5
    assert stats['successful_syncs'] == 2
    assert stats['failed_syncs'] == 3


@pytest.mark.asyncio
async def test_batch_size_validation(sync_client, multiple_videos):
    """Test that invalid batch sizes are corrected."""
    # Arrange
    async def mock_post(path, json=None, **kwargs):
        return MagicMock(
            status_code=201,
            json=lambda: {'dive_id': 1},
        )

    sync_client.client.post = mock_post

    # Act - batch_size too large (> 200) should default to 50
    result = await sync_client.sync_batch(multiple_videos, batch_size=300)

    # Assert
    assert result.total == 10


@pytest.mark.asyncio
async def test_sync_client_timeout_handling(sync_client, sample_video_data):
    """Test timeout handling with retry."""
    # Arrange
    call_count = [0]

    async def mock_post(path, json=None, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise asyncio.TimeoutError()
        else:
            return MagicMock(
                status_code=201,
                json=lambda: {'dive_id': 42},
            )

    sync_client.client.post = mock_post
    sync_client.retry_config.initial_delay = 0.01

    # Act
    result = await sync_client.sync_video(sample_video_data)

    # Assert
    assert result.success is True
    assert result.retry_count == 1


@pytest.mark.asyncio
async def test_sync_client_stats_reset(sync_client, sample_video_data):
    """Test that stats can be reset."""
    # Arrange
    sync_client.sync_stats['successful_syncs'] = 10
    sync_client.sync_stats['total_attempts'] = 10

    # Act
    sync_client.reset_stats()

    # Assert
    stats = sync_client.get_stats()
    assert stats['successful_syncs'] == 0
    assert stats['total_attempts'] == 0
