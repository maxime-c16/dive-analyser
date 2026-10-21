"""D3b2 package publish timeout (review fix).

Proves the client uses a separate bounded per-request timeout for the whole
multipart upload + server ffprobe/decode/B2 roundtrip + full GET — NOT the
30 s generic API default — with real client forwarding (not a mock constant).
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config import ServerConfig
from src.error_recovery import RetryConfig
from src.sync_client import SyncClient


def _client(timeout=30, package_timeout=600, max_retries=2):
    return SyncClient(
        ServerConfig(
            url="https://server.local:6443",
            api_key="k" * 48,
            timeout_seconds=timeout,
            package_publish_timeout_seconds=package_timeout,
        ),
        RetryConfig(max_retries=max_retries, initial_delay=0.001, max_delay=0.001),
    )


def test_package_publish_timeout_default_600():
    cfg = ServerConfig(url="https://server.local:6443", api_key="k" * 48)
    assert cfg.package_publish_timeout_seconds == 600
    assert cfg.timeout_seconds == 30


def test_package_publish_timeout_validation_bounds(tmp_path, monkeypatch):
    from src.config import Config

    monkeypatch.setattr("pathlib.Path.exists", lambda self: True)
    monkeypatch.setattr("pathlib.Path.is_dir", lambda self: True)
    base = {
        "server": {"url": "https://s.local", "api_key": "k" * 48, "timeout_seconds": 30},
        "agent": {},
        "photos": {"library_path": str(tmp_path)},
        "sync": {},
        "media": {},
        "logging": {},
    }
    for bad in (30, 59, 0, -1, 1801, 10000):
        data = {"server": {**base["server"], "package_publish_timeout_seconds": bad}, **{k: v for k, v in base.items() if k != "server"}}
        cfg = Config._from_dict(data)
        with pytest.raises(Exception, match="package_publish_timeout_seconds"):
            cfg.validate()
    # Non-integer is rejected at parse time (fail-closed, never unbounded).
    data = {"server": {**base["server"], "package_publish_timeout_seconds": "unbounded"}, **{k: v for k, v in base.items() if k != "server"}}
    with pytest.raises(Exception):
        Config._from_dict(data)
    for good in (60, 600, 900, 1800):
        data = {"server": {**base["server"], "package_publish_timeout_seconds": good}, **{k: v for k, v in base.items() if k != "server"}}
        cfg = Config._from_dict(data)
        assert cfg.server.package_publish_timeout_seconds == good


@pytest.mark.asyncio
async def test_publish_uses_dedicated_timeout_not_generic(monkeypatch, tmp_path):
    """Real client forwarding: dedicated timeout reaches the transport."""
    calls = []

    async def fake_to_thread(fn, *args, **kwargs):
        # Capture the timeout forwarded to _curl_multipart_post.
        assert args[0].endswith("/package/slots")
        calls.append({"timeout": args[4], "fields": args[1]})
        return 200, '{"job_ready": false}'

    monkeypatch.setattr("src.sync_client.asyncio.to_thread", fake_to_thread)
    client = _client(timeout=30, package_timeout=600)
    f = tmp_path / "hq.mp4"
    f.write_bytes(b"x" * 10)
    await client.publish_package_slot(
        7, "mac-media-01", "tok", "hq", str(f),
        "a" * 64, 10, "video/mp4", "b" * 64,
        transform_version="ffmpeg-h264-web-v1",
    )
    assert len(calls) == 1
    assert calls[0]["timeout"] == 600
    assert calls[0]["fields"]["transform_version"] == "ffmpeg-h264-web-v1"


@pytest.mark.asyncio
async def test_publish_custom_timeout_forwarded_and_legacy_keeps_30s(monkeypatch, tmp_path):
    calls = []

    async def fake_to_thread(fn, *args, **kwargs):
        calls.append((fn.__name__, args))
        if fn.__name__ == "_curl_multipart_post":
            return 200, '{"job_ready": false}'
        return 200, '{"ok": true}'

    monkeypatch.setattr("src.sync_client.asyncio.to_thread", fake_to_thread)
    client = _client(timeout=30, package_timeout=900)
    f = tmp_path / "hq.mp4"
    f.write_bytes(b"x" * 10)
    await client.publish_package_slot(
        7, "mac-media-01", "tok", "hq", str(f),
        "a" * 64, 10, "video/mp4", "b" * 64,
        transform_version="ffmpeg-h264-web-v1",
    )
    # Legacy finalize still uses the 30 s generic default.
    artifact = SimpleNamespace(checksum_sha256="a" * 64, size_bytes=10, content_type="video/mp4")
    await client.finalize_media_job(7, artifact, "mac-media-01", "tok")
    multipart = [c for c in calls if c[0] == "_curl_multipart_post"]
    posts = [c for c in calls if c[0] == "_curl_post"]
    assert multipart and multipart[0][1][4] == 900
    # _curl_post(url, data, api_key, timeout, ca_cert_path): timeout is index 3.
    assert posts and posts[0][1][3] == 30


@pytest.mark.asyncio
async def test_publish_retries_transient_not_409(monkeypatch, tmp_path):
    """Transient timeout/5xx retry with same bytes; 409 fails immediately."""
    from src import sync_client as sc

    f = tmp_path / "hq.mp4"
    f.write_bytes(b"x" * 10)

    # Transient then success: 2 transport calls, same fields (idempotent).
    attempts = []

    async def fake_thread(fn, *a, **k):
        attempts.append(a[4])
        if len(attempts) == 1:
            return 0, ""  # timeout
        return 200, '{"job_ready": false}'

    monkeypatch.setattr(sc.asyncio, "to_thread", fake_thread)
    monkeypatch.setattr(sc.asyncio, "sleep", AsyncMock(return_value=None))
    client = _client(package_timeout=600, max_retries=2)
    out = await client.publish_package_slot(
        7, "mac-media-01", "tok", "hq", str(f),
        "a" * 64, 10, "video/mp4", "b" * 64,
        transform_version="ffmpeg-h264-web-v1",
    )
    assert out == {"job_ready": False}
    assert len(attempts) == 2
    assert all(t == 600 for t in attempts)

    # 409 is terminal: single call, no retry.
    calls_409 = []

    async def fake_409(fn, *a, **k):
        calls_409.append(True)
        return 409, '{"detail": "stale"}'

    monkeypatch.setattr(sc.asyncio, "to_thread", fake_409)
    with pytest.raises(RuntimeError, match="409"):
        await client.publish_package_slot(
            7, "mac-media-01", "tok", "hq", str(f),
            "a" * 64, 10, "video/mp4", "b" * 64,
            transform_version="ffmpeg-h264-web-v1",
        )
    assert len(calls_409) == 1


@pytest.mark.asyncio
async def test_keepalive_spans_slow_publish(tmp_path, monkeypatch):
    """Whole-job keepalive stays alive across a slow fenced publish."""
    import src.package_jobs as pj

    events: list[str] = []

    async def fake_keepalive(job_id, lease_token, phase, lease_lost):
        events.append("keepalive_start")
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            events.append("keepalive_cancelled")
            raise

    async def fake_heartbeat(job_id, status_value, progress, lease_token, lease_lost, phase):
        events.append(f"heartbeat:{status_value}")
        return None

    def fake_raise(lease_lost, job_id, artifact=None):
        if lease_lost.is_set():
            raise RuntimeError("lease lost")

    async def slow_publish(*args, **kwargs):
        events.append("publish_start")
        # Keepalive runs concurrently via create_task: wait until it has
        # started (proves concurrent span, not sequential await).
        for _ in range(200):
            if "keepalive_start" in events:
                break
            await asyncio.sleep(0.01)
        assert "keepalive_start" in events
        assert "keepalive_cancelled" not in events
        await asyncio.sleep(0.1)
        events.append("publish_end")
        return {"job_ready": True}

    sync_client = SimpleNamespace(
        heartbeat_media_job=AsyncMock(return_value={}),
        fail_media_job=AsyncMock(return_value={}),
        lease_media_jobs=AsyncMock(return_value={"jobs": []}),
        publish_package_slot=slow_publish,
    )
    media = SimpleNamespace(
        enabled=True,
        enforce_storage_thresholds=False,
        source_vault=SimpleNamespace(enabled=False),
        capabilities=["poster", "proxy_720p", "web_package"],
        max_jobs=2,
        interval_seconds=30,
        fail_unimplemented_jobs=False,
        temp_dir=str(tmp_path),
        ffmpeg_path="ffmpeg",
        ffprobe_path="ffprobe",
        transcode_timeout_seconds=2700,
    )
    config = SimpleNamespace(agent=SimpleNamespace(id="mac-media-01"), media=media)
    proc = SimpleNamespace(
        config=config,
        sync_client=sync_client,
        agent_id="mac-media-01",
        source_vault=SimpleNamespace(mark_media_ready=MagicMock()),
        _heartbeat_checked=fake_heartbeat,
        _raise_if_lease_lost=fake_raise,
        _keep_lease_alive=fake_keepalive,
        _photos_lock=asyncio.Lock(),
        _build_pipeline=lambda: (SimpleNamespace(cleanup_source_after_success=MagicMock()), None, None),
    )
    job = {
        "job_id": 7,
        "video_uuid": "local-uuid",
        "canonical_video_uuid": "11111111-1111-1111-1111-111111111111",
        "rendition": "web_package",
        "media_key": "p" + "0" * 63,
        "source_url": "https://b2.test/signed",
        "source_sha256": "a" * 64,
        "source_size_bytes": 12,
        "lease_token": "tok",
        "transform_version": "ffmpeg-h264-web-v1",
    }
    result = SimpleNamespace(
        video_uuid="11111111-1111-1111-1111-111111111111",
        source_sha256="a" * 64,
        source_w=1920,
        source_h=1080,
        hq=None,
        hq_aliased_to="light",
        light=SimpleNamespace(role="light", path=tmp_path / "light.mp4", sha256="c" * 64, size_bytes=8, width=640, height=360),
        poster=SimpleNamespace(role="poster", path=tmp_path / "poster.jpg", sha256="d" * 64, size_bytes=4, width=320, height=180),
        ready=True,
        result_dir=tmp_path / "pkg-test",
        cleanup=lambda: None,
    )
    (tmp_path / "pkg-test").mkdir(exist_ok=True)
    result.light.path.write_bytes(b"x" * 8)
    result.poster.path.write_bytes(b"y" * 4)

    async def fake_build(*a, **k):
        return result

    monkeypatch.setattr("src.package_encoder.build_package", fake_build)
    monkeypatch.setattr("src.b2_source.download_b2_source", AsyncMock(return_value=tmp_path / "src.mov"))
    (tmp_path / "src.mov").write_bytes(b"camera-bytes")
    monkeypatch.setattr("src.package_jobs._sha256_file", lambda p: "a" * 64)

    out = await pj.process_package_job(proc, job)
    assert out == {"job_ready": True}
    assert "keepalive_start" in events
    assert events.index("keepalive_start") < events.index("publish_end")
    assert events.index("publish_end") < events.index("keepalive_cancelled")
