"""Cancellation-safety of offloaded media work (review P2 on PR14).

Contract: when the awaiting handler is cancelled (client gone), an
offloaded unit that touches the request session must run to completion —
including its commit — before the request's session teardown can observe
the cancellation. A cancelled finalize must not strand a `verifying` job
with its temp file promoted, or a half transaction.
"""

import asyncio
import hashlib

import pytest

from app.api.v1 import media as media_api
from app.config import get_settings
from app.models.media import MediaJob
from app.models.photos_asset import PhotosAsset
from app.services.offload import run_to_completion


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
async def test_cancelled_finalize_runs_to_completion(test_db, tmp_path, monkeypatch):
    """run_to_completion: cancel the awaiter mid-work; the cancellation
    only re-raises after the unit — here the finalize+commit — finished,
    mirroring the guard that must sit between the worker and get_db
    teardown."""
    settings = get_settings()
    saved_root = settings.media_cache_root
    settings.media_cache_root = str(tmp_path)
    try:
        job = _seed_verifying_job(test_db, tmp_path)
        ran = {"finalize": 0}

        def finalize_flow():
            ran["finalize"] += 1
            checksum = hashlib.sha256(b"tiny").hexdigest()
            entry = media_api.finalize_cache_entry(
                db=test_db, job=job, checksum_sha256=checksum,
                size_bytes=4, content_type="video/mp4",
            )
            media_api.mark_job_ready(test_db, job)
            test_db.commit()
            return entry

        async def awaiting_handler():
            return await run_to_completion(asyncio.to_thread(finalize_flow))

        handler = asyncio.ensure_future(awaiting_handler())
        await asyncio.sleep(0.001)  # let the worker enter the slow block
        handler.cancel()
        with pytest.raises(asyncio.CancelledError):
            await handler

        assert ran["finalize"] == 1
        test_db.expire_all()
        refreshed = test_db.get(MediaJob, job.id)
        assert refreshed.status == "ready"
    finally:
        settings.media_cache_root = saved_root
