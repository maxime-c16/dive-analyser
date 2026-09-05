"""Tests for the curl-backed SyncClient contract."""

import pytest

from src.config import ServerConfig
from src.error_recovery import RetryConfig
from src.sync_client import SyncClient


def _client(ca_cert_path: str = "") -> SyncClient:
    return SyncClient(
        ServerConfig(
            url="https://server.local:6443",
            api_key="test-machine-key",
            timeout_seconds=30,
            ca_cert_path=ca_cert_path,
        ),
        RetryConfig(max_retries=2, initial_delay=0.001, max_delay=0.001),
    )


def _video(uuid: str = "test-uuid-12345") -> dict:
    return {
        "dive_code": "101B",
        "height": "1m",
        "performance": "G",
        "video_uuid": uuid,
        "date": "2026-09-05T12:00:00",
        "is_sync": False,
        "is_smack": False,
        "person_name": None,
    }


@pytest.mark.asyncio
async def test_sync_single_video_success(monkeypatch):
    calls = []

    def fake_post(url, data, api_key, timeout, ca_cert_path=""):
        calls.append((url, data, api_key, timeout, ca_cert_path))
        return 201, '{"dive_id": 42, "video_uuid": "test-uuid-12345"}'

    monkeypatch.setattr("src.sync_client._curl_post", fake_post)
    result = await _client("/tmp/local-ca.pem").sync_video(_video())

    assert result.success is True
    assert result.dive_id == 42
    assert result.http_status == 201
    assert result.retry_count == 0
    assert calls[0][0] == "https://server.local:6443/api/v1/videos/sync"
    assert calls[0][2] == "test-machine-key"
    assert calls[0][4] == "/tmp/local-ca.pem"


@pytest.mark.asyncio
async def test_sync_single_video_duplicate_is_terminal(monkeypatch):
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(args)
        return 409, '{"detail": "Duplicate video"}'

    monkeypatch.setattr("src.sync_client._curl_post", fake_post)
    result = await _client().sync_video(_video())

    assert result.success is False
    assert result.http_status == 409
    assert "Duplicate" in result.error_message
    assert result.retry_count == 0
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_sync_retries_server_errors(monkeypatch):
    responses = [(500, '{"detail": "temporary"}'), (201, '{"dive_id": 99}')]

    def fake_post(*args, **kwargs):
        return responses.pop(0)

    async def fake_sleep(_delay):
        return None

    monkeypatch.setattr("src.sync_client._curl_post", fake_post)
    monkeypatch.setattr("src.sync_client.asyncio.sleep", fake_sleep)
    result = await _client().sync_video(_video())

    assert result.success is True
    assert result.dive_id == 99
    assert result.retry_count == 1


@pytest.mark.asyncio
async def test_sync_batch_preserves_individual_results(monkeypatch):
    statuses = [(201, '{"dive_id": 1}'), (400, '{"detail": "Invalid"}'), (201, '{"dive_id": 3}')]

    def fake_post(*args, **kwargs):
        return statuses.pop(0)

    async def fake_sleep(_delay):
        return None

    monkeypatch.setattr("src.sync_client._curl_post", fake_post)
    monkeypatch.setattr("src.sync_client.asyncio.sleep", fake_sleep)
    result = await _client().sync_batch([_video("u1"), _video("u2"), _video("u3")], batch_size=2)

    assert result.total == 3
    assert result.succeeded == 2
    assert result.failed == 1
    assert result.success_rate == pytest.approx(66.666, rel=1e-3)


def test_stats_reset():
    client = _client()
    client.sync_stats["successful_syncs"] = 10

    client.reset_stats()

    assert client.sync_stats["successful_syncs"] == 0
    assert client.sync_stats["failed_syncs"] == 0
