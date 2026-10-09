"""Proxy/poster jobs transcode from the verified B2 original when the backend offers one."""

import asyncio
import hashlib
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src import b2_source
from src.b2_source import B2SourceError, download_b2_source
from src.media_jobs import MediaJobProcessor
from src.transcoder import RenditionArtifact

PAYLOAD = b"original-mov-bytes" * 64
SHA = hashlib.sha256(PAYLOAD).hexdigest()
SIGNED = "https://s3.example/blobs/x.mov?X-Amz-Signature=secret"


def fake_curl(payload=PAYLOAD, code=0):
    calls = []

    def run(url, dest):
        calls.append(url)
        if code == 0:
            Path(dest).write_bytes(payload)
        return subprocess.CompletedProcess(["curl"], code, "", "boom")
    return run, calls


def job(**extra):
    return {"job_id": 7, "video_uuid": "local", "canonical_video_uuid": "canon", "rendition": "proxy_720p",
            "media_key": "k" * 64, "source_url": SIGNED, "source_sha256": SHA, "source_size_bytes": len(PAYLOAD), **extra}


def test_no_offer_means_no_download(tmp_path, monkeypatch):
    run, calls = fake_curl()
    monkeypatch.setattr(b2_source, "_curl", run)
    assert asyncio.run(download_b2_source({"job_id": 1}, tmp_path)) is None
    assert calls == []


def test_verified_download_is_returned(tmp_path, monkeypatch):
    run, calls = fake_curl()
    monkeypatch.setattr(b2_source, "_curl", run)
    path = asyncio.run(download_b2_source(job(), tmp_path))
    assert path.read_bytes() == PAYLOAD and calls == [SIGNED]


@pytest.mark.parametrize("payload,code,extra,reason", [
    (PAYLOAD, 22, {}, "download_failed"),
    (PAYLOAD[:-1], 0, {}, "size_mismatch"),
    (b"x" * len(PAYLOAD), 0, {}, "checksum_mismatch"),
    (PAYLOAD, 0, {"source_sha256": None}, "checksum_missing"),
])
def test_bad_downloads_are_rejected_and_removed(tmp_path, monkeypatch, payload, code, extra, reason):
    run, _ = fake_curl(payload, code)
    monkeypatch.setattr(b2_source, "_curl", run)
    with pytest.raises(B2SourceError, match=reason):
        asyncio.run(download_b2_source(job(**extra), tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_signed_url_never_reaches_the_logs(tmp_path, monkeypatch, caplog):
    run, _ = fake_curl(code=22)
    monkeypatch.setattr(b2_source, "_curl", run)
    caplog.set_level("DEBUG")
    with pytest.raises(B2SourceError):
        asyncio.run(download_b2_source(job(), tmp_path))
    assert "X-Amz-Signature" not in caplog.text


def processor(tmp_path):
    config = SimpleNamespace(agent=SimpleNamespace(id="mac-media-01"), media=SimpleNamespace(
        enabled=True, source_vault=SimpleNamespace(enabled=False), temp_dir=str(tmp_path)))
    sync = SimpleNamespace(heartbeat_media_job=AsyncMock(), fail_media_job=AsyncMock())
    proc = MediaJobProcessor.__new__(MediaJobProcessor)
    proc.config, proc.sync_client, proc.agent_id, proc.source_vault, proc.dual_write = config, sync, "mac-media-01", None, None
    exporter = SimpleNamespace(source_for_job=AsyncMock(), cleanup_source_after_success=MagicMock())
    seen = {}

    async def build(source, media_key, rendition):
        seen["source"] = Path(source).read_bytes()
        out = tmp_path / "out.mp4"; out.write_bytes(b"mp4")
        return RenditionArtifact(path=out, content_type="video/mp4", checksum_sha256="0" * 64, size_bytes=3)
    transcoder = SimpleNamespace(build=build)
    uploader = SimpleNamespace(upload_and_finalize=AsyncMock(return_value={"cache_entry_id": 1}))
    proc._build_pipeline = lambda: (exporter, transcoder, uploader)
    proc._trigger_dual_write = AsyncMock()
    return proc, exporter, uploader, seen


def test_job_transcodes_the_b2_original_and_skips_photos(tmp_path, monkeypatch):
    run, _ = fake_curl()
    monkeypatch.setattr(b2_source, "_curl", run)
    proc, exporter, uploader, seen = processor(tmp_path)
    asyncio.run(proc._process_job(job()))
    assert seen["source"] == PAYLOAD
    exporter.source_for_job.assert_not_called()
    proc._trigger_dual_write.assert_not_called()  # already in the object store
    uploader.upload_and_finalize.assert_awaited_once()
    assert not any(p.name.startswith("b2-source-") for p in tmp_path.iterdir())  # temp original removed


def test_unusable_b2_original_falls_back_to_photos_export(tmp_path, monkeypatch):
    run, _ = fake_curl(code=22)
    monkeypatch.setattr(b2_source, "_curl", run)
    proc, exporter, uploader, seen = processor(tmp_path)
    photos = tmp_path / "photos.mov"; photos.write_bytes(b"from-photos")
    exporter.source_for_job.return_value = photos
    asyncio.run(proc._process_job(job()))
    assert seen["source"] == b"from-photos"
    exporter.source_for_job.assert_awaited_once()
    proc._trigger_dual_write.assert_awaited_once()
    proc.sync_client.fail_media_job.assert_not_called()
