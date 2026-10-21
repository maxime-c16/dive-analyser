"""D2 worker integrity: ffmpeg timeout, whole-job keepalive, lease-lost abandonment.

Synthetic only (no ffmpeg binary, no Photos, no server): subprocesses and
the sync client are faked at the seams the production code uses.
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import src.media_jobs as jobs_module
from src.media_jobs import MediaJobProcessor, _is_lease_error
from src.transcoder import Transcoder, TranscodeError


def _processor(sync_client, **media_extra):
    media = SimpleNamespace(
        enabled=True,
        enforce_storage_thresholds=False,
        source_vault=SimpleNamespace(enabled=False),
        capabilities=["poster", "proxy_720p"],
        max_jobs=2,
        interval_seconds=30,
        fail_unimplemented_jobs=False,
        temp_dir="/tmp/d2-test",
        ffmpeg_path="ffmpeg",
        transcode_timeout_seconds=2700,
        **media_extra,
    )
    config = SimpleNamespace(agent=SimpleNamespace(id="mac-media-01"), media=media)
    return MediaJobProcessor(config, sync_client)


class HangingProcess:
    """Fake ffmpeg that never exits until killed."""

    def __init__(self):
        self.killed = False
        self.waited = False
        self.returncode = None

    async def communicate(self):
        await asyncio.sleep(30)
        return b"", b""

    def kill(self):
        self.killed = True
        self.returncode = -9

    async def wait(self):
        self.waited = True
        return self.returncode


def _fake_exec_factory(process, created_output=None):
    async def fake_exec(*cmd, **kwargs):
        if created_output is not None:
            created_output.write_bytes(b"partial")
        return process

    return fake_exec


def test_transcode_timeout_kills_reaps_and_cleans_output(tmp_path, monkeypatch):
    source = tmp_path / "source.mov"
    source.write_bytes(b"camera-bytes")
    output = tmp_path / "clip.jpg"
    output.write_bytes(b"partial")
    process = HangingProcess()
    monkeypatch.setattr(
        "src.transcoder.asyncio.create_subprocess_exec", _fake_exec_factory(process)
    )
    transcoder = Transcoder(str(tmp_path), timeout_seconds=0.05)

    with pytest.raises(TranscodeError, match="ffmpeg_timeout"):
        asyncio.run(transcoder.build(source, "clip", "poster"))

    assert process.killed and process.waited
    assert not output.exists()
    assert source.read_bytes() == b"camera-bytes"


def test_transcode_cancel_reaps_and_cleans_output_without_touching_source(tmp_path, monkeypatch):
    source = tmp_path / "source.mov"
    source.write_bytes(b"camera-bytes")
    process = HangingProcess()
    created = tmp_path / "clip.jpg"
    monkeypatch.setattr(
        "src.transcoder.asyncio.create_subprocess_exec",
        _fake_exec_factory(process, created_output=created),
    )
    transcoder = Transcoder(str(tmp_path), timeout_seconds=30)

    async def run_and_cancel():
        task = asyncio.create_task(transcoder.build(source, "clip", "poster"))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run_and_cancel())
    assert process.killed and process.waited
    assert not created.exists()
    assert source.read_bytes() == b"camera-bytes"


def test_lease_error_classification():
    assert _is_lease_error(RuntimeError("heartbeat failed: 409 media_job_lease_token_mismatch"))
    assert _is_lease_error(RuntimeError("fail failed: 404 {\"detail\": \"Media job not found\"}"))
    assert _is_lease_error(RuntimeError("media_job_lease_expired"))
    assert not _is_lease_error(RuntimeError("boom: connection reset"))
    assert not _is_lease_error(RuntimeError("upload failed: 500 internal error"))


def test_process_job_abandons_without_resurrection_on_mid_job_lease_loss(tmp_path, monkeypatch):
    source = tmp_path / "source.mov"
    source.write_bytes(b"camera-bytes")
    artifact_path = tmp_path / "clip.mp4"
    artifact_path.write_bytes(b"encoded")
    monkeypatch.setattr("src.media_jobs.download_b2_source", AsyncMock(return_value=source))
    # Keepalive can never fire here; the loss surfaces on the main path.
    monkeypatch.setattr("src.media_jobs.LEASE_KEEPALIVE_SECONDS", 3600)

    heartbeat = AsyncMock(side_effect=[
        {},  # materializing
        {},  # transcoding
        RuntimeError("heartbeat failed: 409 media_job_lease_token_mismatch"),  # uploading
    ])
    fail = AsyncMock()
    sync_client = SimpleNamespace(heartbeat_media_job=heartbeat, fail_media_job=fail)
    processor = _processor(sync_client)

    built = {}

    class FakeTranscoder:
        async def build(self, *_args):
            built["ran"] = True
            return SimpleNamespace(
                path=artifact_path,
                cleanup=lambda: artifact_path.unlink(missing_ok=True),
            )

    uploader = SimpleNamespace(upload_and_finalize=AsyncMock())
    monkeypatch.setattr(processor, "_build_pipeline", lambda: (None, FakeTranscoder(), uploader))

    job = {
        "job_id": 7, "video_uuid": "v", "canonical_video_uuid": "v",
        "rendition": "proxy_720p", "media_key": "clip", "lease_token": "tok-live",
    }
    asyncio.run(processor._process_job(job))

    assert built.get("ran") is True
    # No resurrection: no upload, no finalize, no fail after the loss.
    assert uploader.upload_and_finalize.await_count == 0
    assert fail.await_count == 0
    assert not artifact_path.exists()


def test_keepalive_covers_encode_and_upload_then_stops(tmp_path, monkeypatch):
    source = tmp_path / "source.mov"
    source.write_bytes(b"camera-bytes")
    monkeypatch.setattr("src.media_jobs.download_b2_source", AsyncMock(return_value=source))
    monkeypatch.setattr("src.media_jobs.LEASE_KEEPALIVE_SECONDS", 0.01)

    seen = []
    heartbeats = []

    async def heartbeat(job_id, agent_id, status_value, progress, lease_token=None):
        heartbeats.append((status_value, progress, lease_token))
        return {}

    async def fail(job_id, agent_id, error, status_value="failed", lease_token=None):
        seen.append(("fail", error))
        return {}

    sync_client = SimpleNamespace(heartbeat_media_job=heartbeat, fail_media_job=fail)
    processor = _processor(sync_client)

    async def slow_build(*_args):
        await asyncio.sleep(0.05)
        return SimpleNamespace(path=tmp_path / "a.mp4", cleanup=lambda: None)

    async def slow_upload(job_id, artifact, lease_token=None):
        await asyncio.sleep(0.05)
        artifact.cleanup()
        return {"cache_entry_id": 1}

    monkeypatch.setattr(
        processor, "_build_pipeline", lambda: (None, SimpleNamespace(build=slow_build), SimpleNamespace(upload_and_finalize=slow_upload))
    )
    job = {
        "job_id": 9, "video_uuid": "v", "canonical_video_uuid": "v",
        "rendition": "poster", "media_key": "clip", "lease_token": "tok-9",
    }
    asyncio.run(processor._process_job(job))

    statuses = [status for status, _, _ in heartbeats]
    assert "transcoding" in statuses and "uploading" in statuses
    # Keepalive echoed the live phase (more than the 3 main heartbeats)…
    assert len(heartbeats) > 3
    assert all(token == "tok-9" for _, _, token in heartbeats)
    assert seen == []
    # …and stopped when the job finished (cancelled in `finally`).
    count = len(heartbeats)
    asyncio.run(asyncio.sleep(0.05))
    assert len(heartbeats) == count


def test_concurrent_slot_failure_does_not_abandon_sibling():
    jobs = [
        {"job_id": 1, "video_uuid": "a", "canonical_video_uuid": "a",
         "rendition": "poster", "media_key": "a", "lease_token": "t1"},
        {"job_id": 2, "video_uuid": "b", "canonical_video_uuid": "b",
         "rendition": "poster", "media_key": "b", "lease_token": "t2"},
    ]
    sync_client = SimpleNamespace(
        lease_media_jobs=AsyncMock(return_value={"jobs": jobs}),
        heartbeat_media_job=AsyncMock(),
    )
    processor = _processor(sync_client)
    entered = asyncio.Event()
    completed = []

    async def fake_process(job):
        if job["job_id"] == 1:
            entered.set()
            raise RuntimeError("slot-1 boom")
        await asyncio.wait_for(entered.wait(), 1)
        await asyncio.sleep(0.01)
        completed.append(job["job_id"])

    processor._process_job = fake_process
    assert asyncio.run(processor.process_once()) == 2
    # The sibling ran to completion despite the other slot's crash, and the
    # crash surfaced as a log — not as a raised error or a hung poll.
    assert completed == [2]


def test_lease_payload_negotiates_token_and_mutations_echo_it(monkeypatch):
    from src.config import ServerConfig
    from src.error_recovery import RetryConfig
    from src.sync_client import SyncClient

    calls = []

    def fake_post(url, data, api_key, timeout, ca_cert_path=""):
        calls.append((url, data))
        if url.endswith("/jobs/lease"):
            return 200, '{"jobs": [{"job_id": 1, "lease_token": "tok-echo"}]}'
        return 200, "{}"

    monkeypatch.setattr("src.sync_client._curl_post", fake_post)
    client = SyncClient(
        ServerConfig(url="https://server.local:6443", api_key="k", timeout_seconds=5, ca_cert_path=""),
        RetryConfig(max_retries=1, initial_delay=0.001, max_delay=0.001),
    )
    leased = asyncio.run(client.lease_media_jobs("mac-1", ["poster"], 1, 300))
    assert leased["jobs"][0]["lease_token"] == "tok-echo"
    assert calls[0][1]["supports_lease_token"] is True

    artifact = SimpleNamespace(path="/tmp/x.mp4", checksum_sha256="a" * 64, size_bytes=3, content_type="video/mp4")
    asyncio.run(client.heartbeat_media_job(1, "mac-1", "transcoding", 35, "tok-echo"))
    asyncio.run(client.finalize_media_job(1, artifact, "mac-1", "tok-echo"))
    assert calls[1][1]["lease_token"] == "tok-echo"
    assert calls[2][1]["lease_token"] == "tok-echo"
