"""Tests for Mac-agent clip-cut background worker and raw MP4 upload client."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src import clip_cut_jobs
from src.config import ServerConfig
from src.sync_client import SyncClient, SyncHTTPError


def test_build_cut_ffmpeg_command_strips_metadata_handles_hdr_and_if_match(tmp_path):
    mp4 = tmp_path / "clip.mp4"
    sdr_cmd = clip_cut_jobs.build_cut_ffmpeg_command(
        ffmpeg_path="ffmpeg",
        source_url="https://b2.example/session.mov?X-Amz-Signature=secret",
        start_s=100.0,
        end_s=112.0,
        mp4_path=mp4,
        color_transfer="bt709",
        source_etag='"abc123etag"',
    )
    assert "-map_metadata" in sdr_cmd
    assert sdr_cmd[sdr_cmd.index("-map_metadata") + 1] == "-1"
    assert "-map_chapters" in sdr_cmd
    assert sdr_cmd[sdr_cmd.index("-map_chapters") + 1] == "-1"
    assert "-headers" in sdr_cmd
    assert sdr_cmd[sdr_cmd.index("-headers") + 1] == 'If-Match: "abc123etag"\r\n'
    vf_sdr = sdr_cmd[sdr_cmd.index("-vf") + 1]
    assert "zscale" not in vf_sdr

    hdr_cmd = clip_cut_jobs.build_cut_ffmpeg_command(
        ffmpeg_path="ffmpeg",
        source_url="https://b2.example/hdr.mov",
        start_s=10.0,
        end_s=22.0,
        mp4_path=mp4,
        color_transfer="arib-std-b67",
    )
    vf_hdr = hdr_cmd[hdr_cmd.index("-vf") + 1]
    assert "zscale=t=linear:npl=100" in vf_hdr
    assert "tonemap=tonemap=hable:desat=0" in vf_hdr
    assert "-color_trc" in hdr_cmd
    assert hdr_cmd[hdr_cmd.index("-color_trc") + 1] == "bt709"


def test_validate_cut_window_and_error_redaction():
    assert clip_cut_jobs.validate_cut_window(0.0, 10.0) == (0.0, 10.0)
    with pytest.raises(ValueError):
        clip_cut_jobs.validate_cut_window(float("nan"), 10.0)
    with pytest.raises(ValueError):
        clip_cut_jobs.validate_cut_window(10.0, 90.0)  # > 60s span
    with pytest.raises(ValueError):
        clip_cut_jobs.validate_cut_window(10.0, 10.2)  # < 0.5s span

    leaked = "Error opening https://b2.example/bucket/key.mov?X-Amz-Signature=TOPSECRET: 403 Forbidden"
    cleaned = clip_cut_jobs.sanitize_cut_error(leaked)
    assert "TOPSECRET" not in cleaned
    assert "https://" not in cleaned


@pytest.mark.asyncio
async def test_process_clip_cut_once_cuts_and_completes(tmp_path, monkeypatch):
    mp4 = tmp_path / "clip.mp4"
    mp4.write_bytes(b"fake-mp4-data")

    monkeypatch.setattr(
        clip_cut_jobs,
        "_cut_clip_async",
        AsyncMock(return_value=mp4),
    )

    sync_client = SimpleNamespace(
        lease_clip_cuts=AsyncMock(
            return_value=[
                {
                    "candidate_id": 77,
                    "lease_token": "tok-12345678",
                    "cut_revision": 2,
                    "start_s": 100.0,
                    "end_s": 110.5,
                    "color_transfer": "bt709",
                    "source_etag": "etag-77",
                    "source_url": "https://b2.example/session.mov?sig=secret",
                }
            ]
        ),
        heartbeat_clip_cut=AsyncMock(return_value={"status": "extracting"}),
        complete_clip_cut=AsyncMock(
            return_value={"candidate_id": 77, "extraction_status": "published", "dive_id": 999}
        ),
        fail_clip_cut=AsyncMock(),
    )

    config = SimpleNamespace(
        media=SimpleNamespace(
            temp_dir=str(tmp_path / "scratch"),
            ffmpeg_path="ffmpeg",
            ffprobe_path="ffprobe",
        )
    )

    processed = await clip_cut_jobs.process_clip_cut_once(config, sync_client, "mac-media-01")
    assert processed == 1
    sync_client.heartbeat_clip_cut.assert_awaited_once_with(77, "mac-media-01", "tok-12345678", 2)
    sync_client.complete_clip_cut.assert_awaited_once_with(
        candidate_id=77,
        agent_id="mac-media-01",
        lease_token="tok-12345678",
        cut_revision=2,
        mp4_path=str(mp4),
    )
    sync_client.fail_clip_cut.assert_not_called()


@pytest.mark.asyncio
async def test_process_clip_cut_once_reports_ffmpeg_b2_404_and_redacts_url(tmp_path, monkeypatch):
    secret_url = "https://b2.example/bucket/IMG.MOV?X-Amz-Credential=SECRETKEY"
    # Even when ffmpeg reports HTTP 404 from B2, fail_clip_cut MUST be called (never confused with dead lease!)
    monkeypatch.setattr(
        clip_cut_jobs,
        "_cut_clip_async",
        AsyncMock(side_effect=clip_cut_jobs._CutError(f"HTTP 404 Not Found reading {secret_url}")),
    )
    sync_client = SimpleNamespace(
        lease_clip_cuts=AsyncMock(
            return_value=[
                {
                    "candidate_id": 88,
                    "lease_token": "tok-abcdef01",
                    "cut_revision": 1,
                    "start_s": 10.0,
                    "end_s": 20.0,
                    "source_url": secret_url,
                }
            ]
        ),
        heartbeat_clip_cut=AsyncMock(return_value={"status": "extracting"}),
        complete_clip_cut=AsyncMock(),
        fail_clip_cut=AsyncMock(),
    )
    config = SimpleNamespace(
        media=SimpleNamespace(
            temp_dir=str(tmp_path / "scratch"),
            ffmpeg_path="ffmpeg",
            ffprobe_path="ffprobe",
        )
    )
    processed = await clip_cut_jobs.process_clip_cut_once(config, sync_client, "mac-media-01")
    assert processed == 0
    sync_client.fail_clip_cut.assert_awaited_once()
    reported_error = sync_client.fail_clip_cut.call_args.args[4]
    assert "SECRETKEY" not in reported_error
    assert "https://" not in reported_error


@pytest.mark.asyncio
async def test_422_leased_window_error_still_calls_fail_clip_cut(tmp_path, monkeypatch):
    mp4 = tmp_path / "clip.mp4"
    mp4.write_bytes(b"mp4-bytes")
    monkeypatch.setattr(clip_cut_jobs, "_cut_clip_async", AsyncMock(return_value=mp4))

    # A 422 message containing the word "leased" must NOT be misclassified as a dead lease!
    sync_client = SimpleNamespace(
        lease_clip_cuts=AsyncMock(
            return_value=[
                {
                    "candidate_id": 95,
                    "lease_token": "tok-422msg",
                    "cut_revision": 1,
                    "start_s": 10.0,
                    "end_s": 20.0,
                    "source_url": "https://b2.example/session.mov",
                }
            ]
        ),
        heartbeat_clip_cut=AsyncMock(return_value={"status": "extracting"}),
        complete_clip_cut=AsyncMock(
            side_effect=RuntimeError("clip cut complete failed: 422 duration does not match leased window")
        ),
        fail_clip_cut=AsyncMock(),
    )
    config = SimpleNamespace(
        media=SimpleNamespace(
            temp_dir=str(tmp_path / "scratch"),
            ffmpeg_path="ffmpeg",
            ffprobe_path="ffprobe",
        )
    )
    processed = await clip_cut_jobs.process_clip_cut_once(config, sync_client, "mac-media-01")
    assert processed == 0
    sync_client.fail_clip_cut.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_clip_cut_once_retries_transient_429_without_burning_attempt(tmp_path, monkeypatch):
    mp4 = tmp_path / "clip.mp4"
    mp4.write_bytes(b"mp4-bytes")
    monkeypatch.setattr(clip_cut_jobs, "_cut_clip_async", AsyncMock(return_value=mp4))
    monkeypatch.setattr(clip_cut_jobs, "UPLOAD_RETRY_BACKOFF_S", 0.01)

    complete_mock = AsyncMock(
        side_effect=[
            SyncHTTPError("clip cut complete failed: 429 Clip upload processor busy", status_code=429),
            {"candidate_id": 91, "extraction_status": "ready", "dive_id": None},
        ]
    )
    sync_client = SimpleNamespace(
        lease_clip_cuts=AsyncMock(
            return_value=[
                {
                    "candidate_id": 91,
                    "lease_token": "tok-retry429",
                    "cut_revision": 1,
                    "start_s": 10.0,
                    "end_s": 20.0,
                    "source_url": "https://b2.example/session.mov",
                }
            ]
        ),
        heartbeat_clip_cut=AsyncMock(return_value={"status": "extracting"}),
        complete_clip_cut=complete_mock,
        fail_clip_cut=AsyncMock(),
    )
    config = SimpleNamespace(
        media=SimpleNamespace(
            temp_dir=str(tmp_path / "scratch"),
            ffmpeg_path="ffmpeg",
            ffprobe_path="ffprobe",
        )
    )
    processed = await clip_cut_jobs.process_clip_cut_once(config, sync_client, "mac-media-01")
    assert processed == 1
    assert complete_mock.await_count == 2
    sync_client.fail_clip_cut.assert_not_called()


@pytest.mark.asyncio
async def test_sync_client_complete_clip_cut_streams_raw_mp4_with_stdin_headers(tmp_path, monkeypatch):
    mp4 = tmp_path / "clip.mp4"
    mp4.write_bytes(b"mp4-bytes")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["input"] = kwargs.get("input", "")
        return SimpleNamespace(stdout='{"candidate_id": 5, "extraction_status": "ready"}\n200', returncode=0)

    monkeypatch.setattr("src.sync_client.subprocess.run", fake_run)
    client = SyncClient(ServerConfig(url="https://dive.example", api_key="super-secret-worker-key"))
    res = await client.complete_clip_cut(
        candidate_id=5,
        agent_id="mac-media-01",
        lease_token="tok-12345678",
        cut_revision=3,
        mp4_path=str(mp4),
    )
    assert res["extraction_status"] == "ready"
    assert "super-secret-worker-key" not in " ".join(captured["cmd"])
    assert "-K" in captured["cmd"]
    assert "--data-binary" in captured["cmd"]
    assert f"@{mp4}" in captured["cmd"]
    assert 'header = "X-API-Key: super-secret-worker-key"' in captured["input"]
    assert 'header = "X-Media-Agent-Id: mac-media-01"' in captured["input"]
    assert 'header = "X-Lease-Token: tok-12345678"' in captured["input"]
    assert 'header = "X-Cut-Revision: 3"' in captured["input"]


@pytest.mark.asyncio
async def test_503_with_404_in_body_is_not_classified_as_dead_lease(tmp_path, monkeypatch):
    mp4 = tmp_path / "clip.mp4"
    mp4.write_bytes(b"mp4-bytes")
    monkeypatch.setattr(clip_cut_jobs, "_cut_clip_async", AsyncMock(return_value=mp4))
    monkeypatch.setattr(clip_cut_jobs, "UPLOAD_RETRY_BACKOFF_S", 0.01)

    # HTTP 503 whose body text mentions " 404 " MUST be treated as transient 503, NEVER dead lease!
    err_503_with_404_text = SyncHTTPError(
        "clip cut complete failed: 503 upstream 404 while staging", status_code=503
    )
    assert clip_cut_jobs._is_server_lease_dead(err_503_with_404_text) is False
    assert clip_cut_jobs._is_transient_upload_busy(err_503_with_404_text) is True

    # Structured 409 IS a dead lease and suppresses fail_clip_cut.
    err_409 = SyncHTTPError("clip cut complete failed: 409 superseded", status_code=409)
    assert clip_cut_jobs._is_server_lease_dead(err_409) is True

    complete_mock = AsyncMock(side_effect=err_503_with_404_text)
    sync_client = SimpleNamespace(
        lease_clip_cuts=AsyncMock(
            return_value=[
                {
                    "candidate_id": 98,
                    "lease_token": "tok-503text",
                    "cut_revision": 1,
                    "start_s": 10.0,
                    "end_s": 20.0,
                    "source_url": "https://b2.example/session.mov",
                }
            ]
        ),
        heartbeat_clip_cut=AsyncMock(return_value={"status": "extracting"}),
        complete_clip_cut=complete_mock,
        fail_clip_cut=AsyncMock(),
    )
    config = SimpleNamespace(
        media=SimpleNamespace(
            temp_dir=str(tmp_path / "scratch"),
            ffmpeg_path="ffmpeg",
            ffprobe_path="ffprobe",
        )
    )
    processed = await clip_cut_jobs.process_clip_cut_once(config, sync_client, "mac-media-01")
    assert processed == 0
    assert complete_mock.await_count == clip_cut_jobs.MAX_UPLOAD_RETRY_ATTEMPTS
    sync_client.fail_clip_cut.assert_awaited_once()

    # SyncClient itself raises SyncHTTPError with integer status_code.
    monkeypatch.setattr(
        "src.sync_client.subprocess.run",
        lambda *a, **k: SimpleNamespace(stdout='{"detail": "upstream 404"}\n503', returncode=0),
    )
    client = SyncClient(ServerConfig(url="https://dive.example", api_key="k"))
    with pytest.raises(SyncHTTPError) as exc_info:
        await client.complete_clip_cut(
            candidate_id=98,
            agent_id="mac-media-01",
            lease_token="tok-503text",
            cut_revision=1,
            mp4_path=str(mp4),
        )
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_media_job_loop_interleaves_clip_cuts_under_continuous_media_load(monkeypatch):
    """Clip cut polling must not starve when normal media batches are continuously non-empty."""
    import asyncio
    import src.media_jobs as media_jobs

    stop = asyncio.Event()
    media_calls = 0
    clip_calls = 0

    async def fake_process_once():
        nonlocal media_calls
        media_calls += 1
        if media_calls >= media_jobs.CLIP_INTERLEAVE_EVERY_BATCHES * 2:
            stop.set()
        return 1

    async def fake_clip_once(cfg, client, agent_id):
        nonlocal clip_calls
        clip_calls += 1
        return 1

    monkeypatch.setattr(
        media_jobs,
        "MediaJobProcessor",
        lambda *_: SimpleNamespace(process_once=fake_process_once, agent_id="mac-media-01"),
    )
    monkeypatch.setattr(clip_cut_jobs, "process_clip_cut_once", fake_clip_once)

    config = SimpleNamespace(
        media=SimpleNamespace(enabled=True, interval_seconds=60, max_jobs=1, leasing_enabled=True)
    )
    sync_client = SimpleNamespace(lease_clip_cuts=AsyncMock(return_value=[]))

    await asyncio.wait_for(media_jobs.run_media_job_loop(config, sync_client, stop), timeout=2)
    assert media_calls == media_jobs.CLIP_INTERLEAVE_EVERY_BATCHES * 2
    assert clip_calls >= 1
