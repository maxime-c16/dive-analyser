"""Cancellation-safety of offloaded media work (review P2 on PR14).

Contract: when the awaiting handler is cancelled (client gone), an
offloaded unit that touches the request session must run to completion —
including its commit — before the request's session teardown can observe
the cancellation. A cancelled finalize must not strand a `verifying` job
with its temp file promoted, or a half transaction.
"""

import asyncio
import hashlib
import threading

import pytest

from app.api.v1 import media as media_api
from app.config import get_settings
from app.models.media import MediaJob
from app.models.photos_asset import PhotosAsset
from app.schemas.media import MediaJobFinalizeRequest
from app.services import media_cache


def _seed_verifying_job(test_db, cache_root):
    root = cache_root / "media-cache"
    tmp_dir = root / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    artifact = tmp_dir / "artifact.bin"
    artifact.write_bytes(b"tiny")
    asset = PhotosAsset(video_uuid="clip-cancel")
    test_db.add(asset)
    test_db.flush()
    job = MediaJob(
        photos_asset_id=asset.id, media_key="z" * 64, rendition="proxy_360p",
        status="verifying", claimed_by="agent-x", upload_tmp_path=str(artifact),
    )
    test_db.add(job)
    test_db.commit()
    return job


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_count", [1, 2])
async def test_cancelled_finalize_runs_to_completion(test_db, tmp_path, monkeypatch, cancel_count):
    """run_to_completion: cancel the awaiter mid-work; the cancellation
    only re-raises after the unit — here the finalize+commit — finished,
    mirroring the guard that must sit between the worker and get_db
    teardown."""
    settings = get_settings()
    saved_root = settings.media_cache_root
    settings.media_cache_root = str(tmp_path)
    try:
        job = _seed_verifying_job(test_db, tmp_path)
        job_id = job.id
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        original_hash = media_cache.sha256_file

        def blocked_hash(path):
            started.set()
            try:
                assert release.wait(5), "test did not release the hashing worker"
                return original_hash(path)
            finally:
                finished.set()

        monkeypatch.setattr(media_cache, "sha256_file", blocked_hash)
        monkeypatch.setattr(media_api, "_agent_auth", lambda *args, **kwargs: None)
        request = MediaJobFinalizeRequest(
            agent_id="agent-x", checksum_sha256=hashlib.sha256(b"tiny").hexdigest(),
            size_bytes=4, content_type="video/mp4",
        )
        handler = asyncio.create_task(media_api.finalize_job_artifact(
            job_id, request, test_db, {"key": "test"},
        ))
        try:
            assert await asyncio.to_thread(started.wait, 5)
            for _ in range(cancel_count):
                handler.cancel()
                await asyncio.sleep(0)
            assert not handler.done(), "handler exited before its worker finished"
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await handler

        assert finished.is_set()
        test_db.expire_all()
        refreshed = test_db.get(MediaJob, job_id)
        assert refreshed.status == "ready"
    finally:
        settings.media_cache_root = saved_root
