"""Pre-accept staging cleanup for the upload route (PR139 review finding).

Contract:
- file.read / write_upload_chunk / file.close failure or cancellation during
  streaming must remove ONLY this request's unique .staging file. The
  DB-backed cleaner never sees it, so without this it leaks forever.
- Once the cancellation-safe hash+accept+commit worker takes over, the file
  is owned by the job pointer: NEVER unlink the committed pointer, even if
  run_to_completion re-raises CancelledError after the worker committed.
  No outer blind finally, no TOCTOU DB check — stage ownership only.

Synthetic private fixtures only (tmp_path + in-memory SQLite).
"""

import asyncio
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.api.v1 import media as media_api
from app.config import get_settings
from app.models.media import MediaAgent, MediaJob
from app.models.photos_asset import PhotosAsset
from app.schemas.media import MediaJobLeaseRequest
from app.services import media_cache

KEY = "k" * 48
AGENT = "mac-media-01"


def _agent(test_db, agent_id=AGENT):
    agent = MediaAgent(
        id=agent_id,
        hostname="mac-server.local",
        api_key_sha256=hashlib.sha256(KEY.encode()).hexdigest(),
        active=True,
        leasing_enabled=True,
        capabilities=["poster", "proxy_360p", "proxy_720p"],
    )
    test_db.add(agent)
    test_db.flush()
    return agent


def _asset(test_db, uuid="aaaaaaaa-1111-1111-1111-111111111111"):
    asset = PhotosAsset(video_uuid=uuid, media_type="video")
    test_db.add(asset)
    test_db.flush()
    return asset


def _queued_job(test_db, asset, rendition="poster"):
    job = MediaJob(
        photos_asset_id=asset.id,
        media_key="e" + "0" * 63,
        rendition=rendition,
        status="queued",
    )
    test_db.add(job)
    test_db.flush()
    return job


def _lease(test_db):
    req = MediaJobLeaseRequest(
        agent_id=AGENT,
        capabilities=["poster"],
        max_jobs=1,
        supports_lease_token=True,
    )
    from app.services.media_jobs import lease_media_jobs

    leased = lease_media_jobs(test_db, req)
    assert len(leased) == 1
    return leased[0]


def _staging_files(tmp_path: Path) -> set[Path]:
    d = tmp_path / "tmp"
    if not d.exists():
        return set()
    return {p for p in d.iterdir() if p.suffix == ".staging"}


class _FakeUpload:
    """Minimal UploadFile stub: async read/close only."""

    def __init__(self, chunks, on_read=None, close_exc=None):
        self._chunks = list(chunks)
        self._on_read = on_read
        self._close_exc = close_exc
        self.close_calls = 0
        self.read_calls = 0

    async def read(self, n=-1):
        self.read_calls += 1
        if self._on_read is not None:
            action = self._on_read(self.read_calls)
            if action == "raise_runtime":
                raise RuntimeError("synthetic-read-boom")
            if action == "raise_cancel":
                raise asyncio.CancelledError("synthetic-stream-cancel")
            if action is not None:
                return action
        if not self._chunks:
            return b""
        return self._chunks.pop(0)

    async def close(self):
        self.close_calls += 1
        if self._close_exc is not None:
            raise self._close_exc


def _seed_old_and_sibling(test_db, tmp_path, job_id, lease_token):
    """Old accepted pointer + unrelated sibling staging; both must survive pre-accept failure."""
    old_path = media_cache.cache_upload_staging_path(job_id, lease_token)
    old_path.write_bytes(b"old-accepted-bytes")
    sibling_path = media_cache.cache_upload_staging_path(job_id, lease_token)
    assert sibling_path != old_path
    sibling_path.write_bytes(b"sibling-bytes")
    # Point the job at the old artifact (previous successful accept).
    job = test_db.get(MediaJob, job_id)
    job.upload_tmp_path = str(old_path)
    job.status = "uploading"
    test_db.add(job)
    test_db.commit()
    return old_path, sibling_path


@pytest.mark.asyncio
async def test_preaccept_read_failure_after_first_chunk_cleans_only_this_staging(test_db, tmp_path, monkeypatch):
    settings = get_settings()
    saved = settings.media_cache_root
    settings.media_cache_root = str(tmp_path)
    try:
        _agent(test_db)
        asset = _asset(test_db)
        _queued_job(test_db, asset)
        leased = _lease(test_db)
        job_id, token = leased.job_id, leased.lease_token
        old_path, sibling_path = _seed_old_and_sibling(test_db, tmp_path, job_id, token)
        before = _staging_files(tmp_path)
        assert old_path in before and sibling_path in before

        monkeypatch.setattr(media_api, "_agent_auth", lambda *a, **k: None)

        def on_read(call):
            if call == 1:
                return b"x" * 16
            return "raise_runtime"

        fake = _FakeUpload([], on_read=on_read)
        body_size = 64
        with pytest.raises(RuntimeError, match="synthetic-read-boom"):
            await media_api.upload_job_artifact(
                job_id, AGENT, "d" * 64, body_size, fake, token, test_db, {"key": "test"}
            )
        after = _staging_files(tmp_path)
        assert after == before, f"only this request staging removed, got new={[p.name for p in after - before]} missing={[p.name for p in before - after]}"
        assert old_path.read_bytes() == b"old-accepted-bytes"
        assert sibling_path.read_bytes() == b"sibling-bytes"
        job = test_db.get(MediaJob, job_id)
        assert job.status != "verifying"
        assert job.upload_tmp_path == str(old_path)
    finally:
        settings.media_cache_root = saved


@pytest.mark.asyncio
async def test_preaccept_write_failure_cleans_only_this_staging(test_db, tmp_path, monkeypatch):
    settings = get_settings()
    saved = settings.media_cache_root
    settings.media_cache_root = str(tmp_path)
    try:
        _agent(test_db)
        asset = _asset(test_db, uuid="bbbbbbbb-2222-2222-2222-222222222222")
        _queued_job(test_db, asset)
        leased = _lease(test_db)
        job_id, token = leased.job_id, leased.lease_token
        old_path, sibling_path = _seed_old_and_sibling(test_db, tmp_path, job_id, token)
        before = _staging_files(tmp_path)

        monkeypatch.setattr(media_api, "_agent_auth", lambda *a, **k: None)

        def boom_write(path, chunk):
            raise OSError("synthetic-write-boom")

        monkeypatch.setattr(media_api, "write_upload_chunk", boom_write)
        fake = _FakeUpload([b"y" * 32])
        with pytest.raises(OSError, match="synthetic-write-boom"):
            await media_api.upload_job_artifact(
                job_id, AGENT, "d" * 64, 32, fake, token, test_db, {"key": "test"}
            )
        after = _staging_files(tmp_path)
        assert after == before
        assert old_path.read_bytes() == b"old-accepted-bytes"
        assert sibling_path.read_bytes() == b"sibling-bytes"
        job = test_db.get(MediaJob, job_id)
        assert job.status != "verifying"
        assert job.upload_tmp_path == str(old_path)
    finally:
        settings.media_cache_root = saved


@pytest.mark.asyncio
async def test_preaccept_stream_cancel_cleans_only_this_staging(test_db, tmp_path, monkeypatch):
    settings = get_settings()
    saved = settings.media_cache_root
    settings.media_cache_root = str(tmp_path)
    try:
        _agent(test_db)
        asset = _asset(test_db, uuid="cccccccc-3333-3333-3333-333333333333")
        _queued_job(test_db, asset)
        leased = _lease(test_db)
        job_id, token = leased.job_id, leased.lease_token
        old_path, sibling_path = _seed_old_and_sibling(test_db, tmp_path, job_id, token)
        before = _staging_files(tmp_path)

        monkeypatch.setattr(media_api, "_agent_auth", lambda *a, **k: None)

        def on_read(call):
            if call == 1:
                return b"z" * 16
            return "raise_cancel"

        fake = _FakeUpload([], on_read=on_read)
        with pytest.raises(asyncio.CancelledError):
            await media_api.upload_job_artifact(
                job_id, AGENT, "d" * 64, 64, fake, token, test_db, {"key": "test"}
            )
        after = _staging_files(tmp_path)
        assert after == before
        assert old_path.read_bytes() == b"old-accepted-bytes"
        assert sibling_path.read_bytes() == b"sibling-bytes"
        job = test_db.get(MediaJob, job_id)
        assert job.status != "verifying"
        assert job.upload_tmp_path == str(old_path)
    finally:
        settings.media_cache_root = saved


@pytest.mark.asyncio
async def test_preaccept_close_failure_cleans_only_this_staging(test_db, tmp_path, monkeypatch):
    settings = get_settings()
    saved = settings.media_cache_root
    settings.media_cache_root = str(tmp_path)
    try:
        _agent(test_db)
        asset = _asset(test_db, uuid="dddddddd-4444-4444-4444-444444444444")
        _queued_job(test_db, asset)
        leased = _lease(test_db)
        job_id, token = leased.job_id, leased.lease_token
        old_path, sibling_path = _seed_old_and_sibling(test_db, tmp_path, job_id, token)
        before = _staging_files(tmp_path)

        monkeypatch.setattr(media_api, "_agent_auth", lambda *a, **k: None)
        fake = _FakeUpload([b"w" * 16], close_exc=RuntimeError("synthetic-close-boom"))
        with pytest.raises(RuntimeError, match="synthetic-close-boom"):
            await media_api.upload_job_artifact(
                job_id, AGENT, "d" * 64, 16, fake, token, test_db, {"key": "test"}
            )
        after = _staging_files(tmp_path)
        assert after == before
        assert old_path.read_bytes() == b"old-accepted-bytes"
        assert sibling_path.read_bytes() == b"sibling-bytes"
        job = test_db.get(MediaJob, job_id)
        assert job.status != "verifying"
        assert job.upload_tmp_path == str(old_path)
    finally:
        settings.media_cache_root = saved


@pytest.mark.asyncio
async def test_valid_upload_accepted_and_sibling_untouched(test_db, tmp_path, monkeypatch):
    settings = get_settings()
    saved = settings.media_cache_root
    settings.media_cache_root = str(tmp_path)
    try:
        _agent(test_db)
        asset = _asset(test_db, uuid="eeeeeeee-5555-5555-5555-555555555555")
        _queued_job(test_db, asset)
        leased = _lease(test_db)
        job_id, token = leased.job_id, leased.lease_token
        # Sibling from another in-flight request; must survive the valid accept.
        sibling_path = media_cache.cache_upload_staging_path(job_id, token)
        sibling_path.write_bytes(b"sibling-bytes")

        monkeypatch.setattr(media_api, "_agent_auth", lambda *a, **k: None)
        body = b"valid-upload-bytes-1234"
        digest = hashlib.sha256(body).hexdigest()
        fake = _FakeUpload([body])
        resp = await media_api.upload_job_artifact(
            job_id, AGENT, digest, len(body), fake, token, test_db, {"key": "test"}
        )
        assert resp.status == "verifying"
        assert resp.upload_tmp_path.endswith(".staging")
        accepted = Path(resp.upload_tmp_path)
        assert accepted.read_bytes() == body
        assert sibling_path.read_bytes() == b"sibling-bytes"
        job = test_db.get(MediaJob, job_id)
        assert job.status == "verifying"
        assert job.upload_tmp_path == str(accepted)
    finally:
        settings.media_cache_root = saved


@pytest.mark.asyncio
async def test_oversized_stream_rejected_before_write_sibling_intact(test_db, tmp_path, monkeypatch):
    """Regression: oversized stream rejected AS SOON AS cumulative bytes
    exceed the CLAIMED size -- the oversize chunk is never written, the
    request staging is cleaned, and old pointer + sibling survive."""
    from fastapi import HTTPException as _HTTPException

    settings = get_settings()
    saved = settings.media_cache_root
    settings.media_cache_root = str(tmp_path)
    try:
        _agent(test_db)
        asset = _asset(test_db, uuid="22222222-8888-8888-8888-888888888888")
        _queued_job(test_db, asset)
        leased = _lease(test_db)
        job_id, token = leased.job_id, leased.lease_token
        old_path, sibling_path = _seed_old_and_sibling(test_db, tmp_path, job_id, token)
        before = _staging_files(tmp_path)

        monkeypatch.setattr(media_api, "_agent_auth", lambda *a, **k: None)
        writes: list[int] = []

        def _counting_write(path, chunk):
            writes.append(len(chunk))
            return media_cache.write_upload_chunk(path, chunk)

        monkeypatch.setattr(media_api, "write_upload_chunk", _counting_write)
        # Claim 16 bytes; stream 16 OK + 16 over (2nd chunk must not be written).
        fake = _FakeUpload([b"x" * 16, b"y" * 16, b"z" * 16])
        with pytest.raises(_HTTPException) as exc:
            await media_api.upload_job_artifact(
                job_id, AGENT, "d" * 64, 16, fake, token, test_db, {"key": "test"}
            )
        assert exc.value.status_code == 400
        assert "mismatch" in str(exc.value.detail).lower()
        # Only the first in-claim chunk reached the disk.
        assert writes == [16], f"oversize chunk must not be written, got {writes}"
        assert fake.close_calls >= 1
        after = _staging_files(tmp_path)
        assert after == before
        assert old_path.read_bytes() == b"old-accepted-bytes"
        assert sibling_path.read_bytes() == b"sibling-bytes"
        job = test_db.get(MediaJob, job_id)
        assert job.status != "verifying"
        assert job.upload_tmp_path == str(old_path)
    finally:
        settings.media_cache_root = saved


@pytest.mark.asyncio
async def test_hash_open_failure_cleans_only_this_staging(test_db, tmp_path, monkeypatch):
    """sha256 open failure: staging was streamed, then unreadable. Clean
    only this request file; old pointer + sibling survive, job not verifying."""
    from fastapi import HTTPException as _HTTPException

    settings = get_settings()
    saved = settings.media_cache_root
    settings.media_cache_root = str(tmp_path)
    try:
        _agent(test_db)
        asset = _asset(test_db, uuid="ffffffff-6666-6666-6666-666666666666")
        _queued_job(test_db, asset)
        leased = _lease(test_db)
        job_id, token = leased.job_id, leased.lease_token
        old_path, sibling_path = _seed_old_and_sibling(test_db, tmp_path, job_id, token)
        before = _staging_files(tmp_path)

        monkeypatch.setattr(media_api, "_agent_auth", lambda *a, **k: None)

        def boom_open(path):
            raise OSError("synthetic-hash-open-boom")

        monkeypatch.setattr(media_api, "sha256_file", boom_open)
        body = b"hash-open-bytes-1234"
        fake = _FakeUpload([body])
        with pytest.raises(_HTTPException) as exc:
            await media_api.upload_job_artifact(
                job_id, AGENT, hashlib.sha256(body).hexdigest(), len(body),
                fake, token, test_db, {"key": "test"},
            )
        assert exc.value.status_code == 400
        assert "unreadable" in exc.value.detail
        after = _staging_files(tmp_path)
        assert after == before
        assert old_path.read_bytes() == b"old-accepted-bytes"
        assert sibling_path.read_bytes() == b"sibling-bytes"
        job = test_db.get(MediaJob, job_id)
        assert job.status != "verifying"
        assert job.upload_tmp_path == str(old_path)
    finally:
        settings.media_cache_root = saved


@pytest.mark.asyncio
async def test_hash_read_failure_cleans_only_this_staging(test_db, tmp_path, monkeypatch):
    """sha256 mid-read failure: same ownership as open failure. Only this
    request file goes; old + sibling preserved, job not verifying."""
    from fastapi import HTTPException as _HTTPException

    settings = get_settings()
    saved = settings.media_cache_root
    settings.media_cache_root = str(tmp_path)
    try:
        _agent(test_db)
        asset = _asset(test_db, uuid="11111111-7777-7777-7777-777777777777")
        _queued_job(test_db, asset)
        leased = _lease(test_db)
        job_id, token = leased.job_id, leased.lease_token
        old_path, sibling_path = _seed_old_and_sibling(test_db, tmp_path, job_id, token)
        before = _staging_files(tmp_path)

        monkeypatch.setattr(media_api, "_agent_auth", lambda *a, **k: None)

        def boom_read(path):
            # Staging exists (streamed OK); the hash read itself fails.
            assert Path(path).exists()
            raise OSError("synthetic-hash-read-boom")

        monkeypatch.setattr(media_api, "sha256_file", boom_read)
        body = b"hash-read-bytes-5678"
        fake = _FakeUpload([body])
        with pytest.raises(_HTTPException) as exc:
            await media_api.upload_job_artifact(
                job_id, AGENT, hashlib.sha256(body).hexdigest(), len(body),
                fake, token, test_db, {"key": "test"},
            )
        assert exc.value.status_code == 400
        after = _staging_files(tmp_path)
        assert after == before
        assert old_path.read_bytes() == b"old-accepted-bytes"
        assert sibling_path.read_bytes() == b"sibling-bytes"
        job = test_db.get(MediaJob, job_id)
        assert job.status != "verifying"
        assert job.upload_tmp_path == str(old_path)
    finally:
        settings.media_cache_root = saved
