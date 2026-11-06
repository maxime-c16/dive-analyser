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
    calls = []

    def fake_post(url, data, api_key, timeout, ca_cert_path=""):
        calls.append((url, data))
        assert url.endswith("/api/v1/videos/batch")
        assert "videos" in data
        # Fail the video whose uuid is u2, succeed the rest of the chunk.
        errors = [
            {"video_uuid": v["video_uuid"], "error": "Invalid"}
            for v in data["videos"]
            if v["video_uuid"] == "u2"
        ]
        import json as _json
        return 200, _json.dumps({"total": len(data["videos"]), "succeeded": len(data["videos"]) - len(errors), "failed": len(errors), "errors": errors})

    async def fake_sleep(_delay):
        return None

    monkeypatch.setattr("src.sync_client._curl_post", fake_post)
    monkeypatch.setattr("src.sync_client.asyncio.sleep", fake_sleep)
    result = await _client().sync_batch([_video("u1"), _video("u2"), _video("u3")], batch_size=2)

    assert result.total == 3
    assert result.succeeded == 2
    assert result.failed == 1
    assert result.success_rate == pytest.approx(66.666, rel=1e-3)
    # Two chunks (2 + 1) → two batch requests, not three single syncs.
    assert len(calls) == 2
    assert [v["video_uuid"] for v in calls[0][1]["videos"]] == ["u1", "u2"]
    assert [v["video_uuid"] for v in calls[1][1]["videos"]] == ["u3"]
    failed = [r for r in result.results if not r.success]
    assert [r.video_uuid for r in failed] == ["u2"]


@pytest.mark.asyncio
async def test_sync_batch_fail_fast_leaves_siblings_retryable(monkeypatch):
    """Server prevalidation fail-fast (succeeded=0, errors naming only the
    invalid clip) must not mark the valid-but-unwritten siblings synced —
    the extractor would checkpoint them and never retry."""
    import json as _json

    def fake_post(url, data, api_key, timeout, ca_cert_path=""):
        assert url.endswith("/api/v1/videos/batch")
        return 200, _json.dumps({
            "total": 2, "succeeded": 0, "failed": 1,
            "errors": [{"video_uuid": "bad", "error": "phase combination invalid"}],
        })

    monkeypatch.setattr("src.sync_client._curl_post", fake_post)
    result = await _client().sync_batch([_video("bad"), _video("good")], batch_size=50)

    assert result.succeeded == 0
    assert result.failed == 2
    by_uuid = {r.video_uuid: r for r in result.results}
    assert by_uuid["bad"].success is False
    assert "phase combination invalid" in (by_uuid["bad"].error_message or "")
    # The valid sibling was never written: failed + retryable (not 409, so
    # the extractor does not mark it synced).
    assert by_uuid["good"].success is False
    assert by_uuid["good"].http_status != 409


@pytest.mark.asyncio
async def test_sync_batch_uses_one_request_per_chunk(monkeypatch):
    """One extractor batch → one POST /videos/batch, so the server writes
    its grouped per-diver notification instead of one row per dive."""
    calls = []

    def fake_post(url, data, api_key, timeout, ca_cert_path=""):
        calls.append((url, data))
        import json as _json
        return 200, _json.dumps({"total": len(data["videos"]), "succeeded": len(data["videos"]), "failed": 0, "errors": []})

    monkeypatch.setattr("src.sync_client._curl_post", fake_post)
    result = await _client().sync_batch([_video(f"uuid-{i}") for i in range(5)], batch_size=50)

    assert result.succeeded == 5
    assert len(calls) == 1
    assert calls[0][0].endswith("/api/v1/videos/batch")
    assert len(calls[0][1]["videos"]) == 5


def test_stats_reset():
    client = _client()
    client.sync_stats["successful_syncs"] = 10

    client.reset_stats()

    assert client.sync_stats["successful_syncs"] == 0
    assert client.sync_stats["failed_syncs"] == 0
