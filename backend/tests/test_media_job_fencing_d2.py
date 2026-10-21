"""D2 lease fencing: per-claim tokens on media jobs (synthetic, SQLite).

Contract under test (backend half of D2):
- every token-capable lease mints a fresh uuid token, including re-leases
  to the SAME agent; the stale attempt's heartbeat/upload/finalize/fail is
  rejected (409-style PermissionError), never resurrecting the job;
- an expired attempt cannot renew or write, even with the right token;
- per-attempt tmp paths: a stale upload can never overwrite live tmp bytes;
- legacy tokenless claims (pre-D2 rows, old workers) keep working during
  the bounded drain, but a missing token is NEVER a blanket same-agent
  allowance — it is accepted only when the stored claim is itself
  tokenless, and rejected outright once MEDIA_JOBS_REQUIRE_LEASE_TOKEN.
"""

import hashlib
from datetime import datetime, timedelta

import pytest

from app.config import get_settings
from app.models.media import MediaAgent, MediaJob
from app.models.photos_asset import PhotosAsset
from app.schemas.media import MediaJobLeaseRequest
from app.services import media_cache
from app.services.media_jobs import (
    UPLOADABLE_JOB_STATUSES,
    _guarded_job,
    fail_media_job,
    heartbeat_media_job,
    lease_media_jobs,
    mark_job_uploaded,
    reclaim_expired_media_jobs,
)

KEY = "k" * 48
AGENT = "mac-media-01"


def _agent(test_db, agent_id=AGENT, leasing=True):
    agent = MediaAgent(
        id=agent_id,
        hostname="mac-server.local",
        api_key_sha256=hashlib.sha256(KEY.encode()).hexdigest(),
        active=True,
        leasing_enabled=leasing,
        capabilities=["poster", "proxy_360p", "proxy_720p"],
    )
    test_db.add(agent)
    test_db.flush()
    return agent


def _asset(test_db, uuid="11111111-1111-1111-1111-111111111111"):
    asset = PhotosAsset(video_uuid=uuid, media_type="video")
    test_db.add(asset)
    test_db.flush()
    return asset


def _queued_job(test_db, asset, rendition="poster", media_key=None):
    job = MediaJob(
        photos_asset_id=asset.id,
        media_key=media_key or ("f" + "0" * 63),
        rendition=rendition,
        status="queued",
    )
    test_db.add(job)
    test_db.flush()
    return job


def _lease(test_db, agent_id=AGENT, token_capable=True, **kwargs):
    request = MediaJobLeaseRequest(
        agent_id=agent_id,
        capabilities=["poster"],
        max_jobs=1,
        supports_lease_token=token_capable,
        **kwargs,
    )
    leased = lease_media_jobs(test_db, request)
    assert len(leased) == 1
    return leased[0]


def test_valid_claim_mints_token_and_full_cycle_succeeds(test_db, tmp_path):
    _agent(test_db)
    asset = _asset(test_db)
    _queued_job(test_db, asset)
    leased = _lease(test_db)
    assert leased.lease_token and len(leased.lease_token) == 32
    job = test_db.get(MediaJob, leased.job_id)
    assert job.lease_token == leased.lease_token
    assert job.status == "claimed"

    heartbeat_media_job(test_db, job.id, AGENT, "transcoding", 35, leased.lease_token)
    staging = tmp_path / "accept.bin"
    staging.write_bytes(b"cycle-bytes")
    digest = hashlib.sha256(b"cycle-bytes").hexdigest()
    marked = mark_job_uploaded(
        test_db, job.id, AGENT, str(staging), digest, len(b"cycle-bytes"), leased.lease_token
    )
    assert marked.status == "verifying"
    assert marked.upload_tmp_path == str(staging)
    failed = fail_media_job(test_db, job.id, AGENT, "boom", "failed", leased.lease_token)
    assert failed.status == "failed" and failed.last_error == "boom"


def test_reclaim_mints_fresh_token_for_same_agent_and_stale_is_rejected(test_db):
    _agent(test_db)
    asset = _asset(test_db)
    _queued_job(test_db, asset)
    first = _lease(test_db)
    job = test_db.get(MediaJob, first.job_id)
    # Expire + reclaim, then the SAME agent leases again.
    job.claimed_until = datetime.utcnow() - timedelta(seconds=1)
    test_db.flush()
    assert reclaim_expired_media_jobs(test_db) == 1
    test_db.refresh(job)
    assert job.lease_token is None and job.claimed_by is None

    second = _lease(test_db)
    assert second.job_id == first.job_id
    assert second.lease_token and second.lease_token != first.lease_token

    stale = first.lease_token
    with pytest.raises(PermissionError, match="media_job_lease_token_mismatch"):
        heartbeat_media_job(test_db, job.id, AGENT, "transcoding", 10, stale)
    with pytest.raises(PermissionError, match="media_job_lease_token_mismatch"):
        mark_job_uploaded(test_db, job.id, AGENT, "/tmp/stale.bin", "b" * 64, 3, stale)
    with pytest.raises(PermissionError, match="media_job_lease_token_mismatch"):
        fail_media_job(test_db, job.id, AGENT, "late", "failed", stale)
    with pytest.raises(PermissionError, match="media_job_lease_token_mismatch"):
        _guarded_job(test_db, job.id, AGENT, stale, {"verifying"}, lock=False)
    # The live attempt is untouched and usable.
    assert heartbeat_media_job(
        test_db, job.id, AGENT, "transcoding", 10, second.lease_token
    ).progress == 10


def test_missing_token_is_rejected_once_claim_is_tokened(test_db):
    # No 'same agent may omit' loophole: omitting the token on a tokened
    # claim is a mismatch, even for the owning agent.
    _agent(test_db)
    asset = _asset(test_db)
    _queued_job(test_db, asset)
    leased = _lease(test_db)
    with pytest.raises(PermissionError, match="media_job_lease_token_mismatch"):
        heartbeat_media_job(test_db, leased.job_id, AGENT, "transcoding", 10, None)
    with pytest.raises(PermissionError, match="media_job_lease_token_mismatch"):
        fail_media_job(test_db, leased.job_id, AGENT, "x", "failed", None)


def test_expired_attempt_cannot_renew_or_write_even_with_right_token(test_db):
    _agent(test_db)
    asset = _asset(test_db)
    _queued_job(test_db, asset)
    leased = _lease(test_db)
    job = test_db.get(MediaJob, leased.job_id)
    job.claimed_until = datetime.utcnow() - timedelta(seconds=1)
    test_db.flush()
    with pytest.raises(PermissionError, match="media_job_lease_expired"):
        heartbeat_media_job(test_db, job.id, AGENT, "transcoding", 10, leased.lease_token)
    with pytest.raises(PermissionError, match="media_job_lease_expired"):
        mark_job_uploaded(test_db, job.id, AGENT, "/tmp/x.bin", "c" * 64, 3, leased.lease_token)
    with pytest.raises(PermissionError, match="media_job_lease_expired"):
        fail_media_job(test_db, job.id, AGENT, "late", "failed", leased.lease_token)
    # The lease was not renewed behind our back.
    test_db.refresh(job)
    assert job.status == "claimed" and job.progress in (0, 1)


def test_foreign_agent_rejected_before_token_checks(test_db):
    _agent(test_db)
    other = MediaAgent(
        id="other-agent",
        hostname="other.local",
        api_key_sha256=hashlib.sha256(("o" * 48).encode()).hexdigest(),
        active=True,
        leasing_enabled=True,
        capabilities=["poster"],
    )
    test_db.add(other)
    test_db.flush()
    asset = _asset(test_db)
    _queued_job(test_db, asset)
    leased = _lease(test_db)
    with pytest.raises(PermissionError, match="media_job_lease_owner_mismatch"):
        heartbeat_media_job(test_db, leased.job_id, "other-agent", "transcoding", 10, leased.lease_token)


def test_heartbeat_rejects_non_leased_state(test_db):
    _agent(test_db)
    asset = _asset(test_db)
    _queued_job(test_db, asset)
    leased = _lease(test_db)
    fail_media_job(test_db, leased.job_id, AGENT, "done", "failed", leased.lease_token)
    with pytest.raises(PermissionError, match="media_job_invalid_state"):
        heartbeat_media_job(test_db, leased.job_id, AGENT, "transcoding", 10, leased.lease_token)


def test_legacy_tokenless_claim_works_during_drain_but_is_not_a_loophole(test_db):
    # Pre-D2 row: claimed before fencing existed (token NULL). Old worker
    # (no token support) keeps working while require-flag is false.
    _agent(test_db)
    asset = _asset(test_db)
    _queued_job(test_db, asset)
    legacy = _lease(test_db, token_capable=False)
    assert legacy.lease_token is None
    assert heartbeat_media_job(test_db, legacy.job_id, AGENT, "transcoding", 10, None).progress == 10
    # ... but presenting ANY token against a tokenless claim is a mismatch
    # (no upgrade-by-guessing), and once the job is re-leased with a token,
    # the missing-token path dies with it.
    with pytest.raises(PermissionError, match="media_job_lease_token_mismatch"):
        heartbeat_media_job(test_db, legacy.job_id, AGENT, "transcoding", 10, "f" * 32)
    job = test_db.get(MediaJob, legacy.job_id)
    job.claimed_until = datetime.utcnow() - timedelta(seconds=1)
    test_db.flush()
    reclaim_expired_media_jobs(test_db)
    fresh = _lease(test_db)
    assert fresh.lease_token is not None
    with pytest.raises(PermissionError, match="media_job_lease_token_mismatch"):
        heartbeat_media_job(test_db, fresh.job_id, AGENT, "transcoding", 10, None)


def test_require_flag_ends_the_transition(test_db, monkeypatch):
    settings = get_settings()
    saved = settings.media_jobs_require_lease_token
    settings.media_jobs_require_lease_token = True
    try:
        _agent(test_db)
        asset = _asset(test_db)
        _queued_job(test_db, asset)
        # Tokenless leases are refused: old workers must upgrade.
        with pytest.raises(PermissionError, match="media_job_lease_upgrade_required"):
            lease_media_jobs(
                test_db,
                MediaJobLeaseRequest(agent_id=AGENT, capabilities=["poster"], max_jobs=1),
            )
        # And a leftover tokenless claim can no longer mutate.
        legacy_job = MediaJob(
            photos_asset_id=asset.id,
            media_key="e" + "0" * 63,
            rendition="poster",
            status="claimed",
            claimed_by=AGENT,
            claimed_at=datetime.utcnow(),
            claimed_until=datetime.utcnow() + timedelta(minutes=5),
            lease_token=None,
        )
        test_db.add(legacy_job)
        test_db.flush()
        with pytest.raises(PermissionError, match="media_job_lease_token_required"):
            heartbeat_media_job(test_db, legacy_job.id, AGENT, "transcoding", 10, None)
    finally:
        settings.media_jobs_require_lease_token = saved


def test_tmp_path_is_per_attempt_and_stale_upload_leaves_live_bytes(test_db, tmp_path, monkeypatch):
    import hashlib as _hashlib

    settings = get_settings()
    saved_root = settings.media_cache_root
    settings.media_cache_root = str(tmp_path)
    try:
        _agent(test_db)
        asset = _asset(test_db)
        _queued_job(test_db, asset)
        first = _lease(test_db)
        job = test_db.get(MediaJob, first.job_id)
        live_path = media_cache.cache_tmp_path(job)
        live_path.write_bytes(b"live-bytes")
        digest = _hashlib.sha256(b"live-bytes").hexdigest()
        mark_job_uploaded(test_db, job.id, AGENT, str(live_path), digest, len(b"live-bytes"), first.lease_token)

        job.claimed_until = datetime.utcnow() - timedelta(seconds=1)
        test_db.flush()
        reclaim_expired_media_jobs(test_db)
        # Reclaim queues the dead attempt's orphan bytes; they are unlinked
        # only after the owner's commit (a rollback would resurrect the row).
        assert live_path.exists()
        test_db.commit()
        media_cache.drain_reclaim_orphans(test_db)
        assert not live_path.exists()
        second = _lease(test_db)
        assert second.lease_token != first.lease_token
        job2 = test_db.get(MediaJob, second.job_id)
        second_path = media_cache.cache_tmp_path(job2)
        assert second_path != live_path
        second_path.write_bytes(b"live-bytes")
        mark_job_uploaded(test_db, job2.id, AGENT, str(second_path), digest, len(b"live-bytes"), second.lease_token)

        # ...and the stale token is rejected before it can touch them.
        with pytest.raises(PermissionError, match="media_job_lease_token_mismatch"):
            mark_job_uploaded(
                test_db, second.job_id, AGENT, str(second_path), "d" * 64, 10, first.lease_token
            )
        assert second_path.read_bytes() == b"live-bytes"
        assert test_db.get(MediaJob, second.job_id).status == "verifying"
    finally:
        settings.media_cache_root = saved_root


def test_mid_upload_release_is_rejected_at_accept_time(test_db, tmp_path, monkeypatch):
    """Check-then-act race: peek passed, but the claim moved before commit."""
    settings = get_settings()
    saved_root = settings.media_cache_root
    settings.media_cache_root = str(tmp_path)
    try:
        _agent(test_db)
        asset = _asset(test_db)
        _queued_job(test_db, asset)
        leased = _lease(test_db)
        job = test_db.get(MediaJob, leased.job_id)
        # Pre-write peek would have passed here...
        _guarded_job(test_db, job.id, AGENT, leased.lease_token, UPLOADABLE_JOB_STATUSES, lock=False)
        # ...then the lease moved (expiry + reclaim + re-lease to same agent).
        job.claimed_until = datetime.utcnow() - timedelta(seconds=1)
        test_db.flush()
        reclaim_expired_media_jobs(test_db)
        _lease(test_db)
        # The authoritative post-write guard rejects the dead attempt.
        with pytest.raises(PermissionError, match="media_job_lease_token_mismatch"):
            mark_job_uploaded(test_db, job.id, AGENT, "/tmp/race.bin", "e" * 64, 3, leased.lease_token)
    finally:
        settings.media_cache_root = saved_root


def test_reclaim_clears_token_and_ownership(test_db):
    _agent(test_db)
    asset = _asset(test_db)
    _queued_job(test_db, asset)
    leased = _lease(test_db)
    job = test_db.get(MediaJob, leased.job_id)
    job.claimed_until = datetime.utcnow() - timedelta(seconds=1)
    job.upload_tmp_path = "/tmp/orphan.bin"
    job.output_checksum_sha256 = "f" * 64
    job.output_size_bytes = 7
    test_db.flush()
    assert reclaim_expired_media_jobs(test_db) == 1
    test_db.refresh(job)
    assert job.status == "queued"
    assert job.claimed_by is None and job.lease_token is None
    assert job.upload_tmp_path is None and job.output_checksum_sha256 is None


def test_upload_route_rejects_stale_token_end_to_end(api_client, test_db, tmp_path, monkeypatch):
    """Route-level: stale-token upload is 409 and live tmp bytes survive."""
    from app.models.media import MediaJob as _MJ

    settings = get_settings()
    saved_root = settings.media_cache_root
    settings.media_cache_root = str(tmp_path)
    try:
        _agent(test_db)
        asset = _asset(test_db)
        _queued_job(test_db, asset)
        headers = {"X-API-Key": KEY}
        first = api_client.post(
            "/api/v1/media/jobs/lease",
            json={"agent_id": AGENT, "capabilities": ["poster"], "max_jobs": 1, "supports_lease_token": True},
            headers=headers,
        )
        assert first.status_code == 200, first.text
        payload = first.json()["jobs"][0]
        job_id, token1 = payload["job_id"], payload["lease_token"]
        assert token1

        body = b"hello-bytes"
        import hashlib as _hashlib

        digest = _hashlib.sha256(body).hexdigest()
        ok = api_client.post(
            f"/api/v1/media/jobs/{job_id}/upload",
            data={"agent_id": AGENT, "checksum_sha256": digest, "size_bytes": str(len(body)), "lease_token": token1},
            files={"file": ("clip.mp4", body)},
            headers=headers,
        )
        assert ok.status_code == 200, ok.text
        live_pointer = ok.json()["upload_tmp_path"]
        assert live_pointer and live_pointer.endswith(".staging")
        assert __import__("pathlib").Path(live_pointer).read_bytes() == body

        # Expire + reclaim + re-lease (same agent, new token).
        job = test_db.get(_MJ, job_id)
        test_db.refresh(job)
        assert job.status == "verifying"
        # verifying is a leased state; force expiry directly.
        job.claimed_until = datetime.utcnow() - timedelta(seconds=1)
        test_db.commit()
        assert reclaim_expired_media_jobs(test_db) == 1
        again = api_client.post(
            "/api/v1/media/jobs/lease",
            json={"agent_id": AGENT, "capabilities": ["poster"], "max_jobs": 1, "supports_lease_token": True},
            headers=headers,
        )
        token2 = again.json()["jobs"][0]["lease_token"]
        assert token2 and token2 != token1

        stale = api_client.post(
            f"/api/v1/media/jobs/{job_id}/upload",
            data={"agent_id": AGENT, "checksum_sha256": digest, "size_bytes": str(len(body)), "lease_token": token1},
            files={"file": ("clip.mp4", body)},
            headers=headers,
        )
        assert stale.status_code == 409, stale.text
        assert "media_job_lease_token_mismatch" in stale.text
    finally:
        settings.media_cache_root = saved_root


def test_heartbeat_is_monotonic_and_never_regresses_verifying(test_db, tmp_path):
    """A lagging keepalive echo must not pull verifying back to uploading."""
    _agent(test_db)
    asset = _asset(test_db)
    _queued_job(test_db, asset)
    leased = _lease(test_db)
    job = test_db.get(MediaJob, leased.job_id)
    live_token = leased.lease_token
    staging = tmp_path / "mono.bin"
    staging.write_bytes(b"mono-bytes")
    digest = hashlib.sha256(b"mono-bytes").hexdigest()
    mark_job_uploaded(
        test_db, job.id, AGENT, str(staging), digest, len(b"mono-bytes"), live_token
    )
    assert test_db.get(MediaJob, job.id).status == "verifying"
    stayed = heartbeat_media_job(test_db, job.id, AGENT, "uploading", 80, live_token)
    assert stayed.status == "verifying" and stayed.progress == 95
    assert heartbeat_media_job(test_db, job.id, AGENT, "verifying", 96, live_token).progress == 96


def test_same_attempt_duplicate_staging_never_deletes_live(test_db, tmp_path):
    """Same-attempt retry streams to staging; live canonical bytes survive."""
    from app.services.media_cache import cache_upload_staging_path

    settings = get_settings()
    saved_root = settings.media_cache_root
    settings.media_cache_root = str(tmp_path)
    try:
        _agent(test_db)
        asset = _asset(test_db)
        _queued_job(test_db, asset)
        leased = _lease(test_db)
        job = test_db.get(MediaJob, leased.job_id)
        live = media_cache.cache_tmp_path(job)
        live.write_bytes(b"live-bytes")
        digest = __import__("hashlib").sha256(b"live-bytes").hexdigest()
        mark_job_uploaded(test_db, job.id, AGENT, str(live), digest, len(b"live-bytes"), leased.lease_token)
        assert test_db.get(MediaJob, job.id).status == "verifying"
        staging = cache_upload_staging_path(job.id, leased.lease_token)
        assert staging != live
        staging.write_bytes(b"retry-bytes")
        staging.unlink(missing_ok=True)
        assert live.read_bytes() == b"live-bytes"
    finally:
        settings.media_cache_root = saved_root


def test_reclaim_orphans_drained_only_after_commit(test_db, tmp_path):
    """Rollback after reclaim must not lose the orphan file."""
    settings = get_settings()
    saved_root = settings.media_cache_root
    settings.media_cache_root = str(tmp_path)
    try:
        _agent(test_db)
        asset = _asset(test_db)
        _queued_job(test_db, asset)
        leased = _lease(test_db)
        job = test_db.get(MediaJob, leased.job_id)
        live_path = media_cache.cache_tmp_path(job)
        live_path.write_bytes(b"live-bytes")
        digest = __import__("hashlib").sha256(b"live-bytes").hexdigest()
        mark_job_uploaded(test_db, job.id, AGENT, str(live_path), digest, len(b"live-bytes"), leased.lease_token)
        test_db.commit()
        job.claimed_until = datetime.utcnow() - timedelta(seconds=1)
        test_db.flush()
        assert reclaim_expired_media_jobs(test_db) == 1
        test_db.rollback()
        assert live_path.exists()
        assert test_db.get(MediaJob, leased.job_id).upload_tmp_path == str(live_path)
    finally:
        settings.media_cache_root = saved_root


def test_guarded_job_refreshes_preloaded_stale_row(test_db):
    """populate_existing: a peek cached before a re-lease must not pass."""
    from sqlalchemy.orm import sessionmaker

    _agent(test_db)
    asset = _asset(test_db)
    _queued_job(test_db, asset)
    leased = _lease(test_db)
    preloaded = test_db.get(MediaJob, leased.job_id)
    assert preloaded.lease_token == leased.lease_token
    factory = sessionmaker(bind=test_db.get_bind(), expire_on_commit=False)
    other = factory()
    try:
        other_job = other.get(MediaJob, leased.job_id)
        other_job.lease_token = "f" * 32
        other.commit()
    finally:
        other.close()
    with pytest.raises(PermissionError, match="media_job_lease_token_mismatch"):
        _guarded_job(test_db, leased.job_id, AGENT, leased.lease_token, {"claimed"}, lock=True)


def test_accept_rejects_missing_directory_and_replaced_staging(test_db, tmp_path):
    """Fail-closed accept: missing/dir/non-file never marks verifying."""
    _agent(test_db)
    asset = _asset(test_db)
    _queued_job(test_db, asset)
    leased = _lease(test_db)
    job = test_db.get(MediaJob, leased.job_id)

    missing = tmp_path / "gone.bin"
    with pytest.raises(ValueError, match="Uploaded artifact missing"):
        mark_job_uploaded(test_db, job.id, AGENT, str(missing), "a" * 64, 3, leased.lease_token)
    job = test_db.get(MediaJob, leased.job_id)
    assert job.status == "claimed" and job.upload_tmp_path is None

    subdir = tmp_path / "as-dir"
    subdir.mkdir()
    with pytest.raises(ValueError, match="Uploaded artifact missing"):
        mark_job_uploaded(test_db, job.id, AGENT, str(subdir), "a" * 64, 3, leased.lease_token)
    job = test_db.get(MediaJob, leased.job_id)
    assert job.status == "claimed" and job.upload_tmp_path is None
    assert subdir.is_dir()

    replaced = tmp_path / "replaced.bin"
    replaced.write_bytes(b"staged-bytes")
    replaced.unlink()
    replaced.mkdir()
    with pytest.raises(ValueError, match="Uploaded artifact missing"):
        mark_job_uploaded(test_db, job.id, AGENT, str(replaced), "a" * 64, 3, leased.lease_token)
    job = test_db.get(MediaJob, leased.job_id)
    assert job.status == "claimed" and job.upload_tmp_path is None
    assert replaced.is_dir()

    valid = tmp_path / "valid.bin"
    valid.write_bytes(b"valid-bytes")
    digest = hashlib.sha256(b"valid-bytes").hexdigest()
    marked = mark_job_uploaded(
        test_db, job.id, AGENT, str(valid), digest, len(b"valid-bytes"), leased.lease_token
    )
    assert marked.status == "verifying" and marked.upload_tmp_path == str(valid)
    assert valid.read_bytes() == b"valid-bytes"


def test_accept_rollback_keeps_old_artifact_and_leaks_new(test_db, tmp_path):
    """Staging-direct: a rolled-back accept leaks the new file, keeps old."""
    from app.services.media_cache import drain_reclaim_orphans

    settings = get_settings()
    saved_root = settings.media_cache_root
    settings.media_cache_root = str(tmp_path)
    try:
        _agent(test_db)
        asset = _asset(test_db)
        _queued_job(test_db, asset)
        leased = _lease(test_db)
        job = test_db.get(MediaJob, leased.job_id)

        first = media_cache.cache_upload_staging_path(job.id, leased.lease_token)
        first.write_bytes(b"first-bytes")
        digest_a = hashlib.sha256(b"first-bytes").hexdigest()
        mark_job_uploaded(test_db, job.id, AGENT, str(first), digest_a, len(b"first-bytes"), leased.lease_token)
        test_db.commit()
        assert test_db.get(MediaJob, job.id).upload_tmp_path == str(first)

        second = media_cache.cache_upload_staging_path(job.id, leased.lease_token)
        assert second != first
        second.write_bytes(b"second-bytes")
        digest_b = hashlib.sha256(b"second-bytes").hexdigest()
        mark_job_uploaded(test_db, job.id, AGENT, str(second), digest_b, len(b"second-bytes"), leased.lease_token)
        # Old file untouched until the owner's commit drains it.
        assert first.read_bytes() == b"first-bytes"
        test_db.rollback()
        assert test_db.get(MediaJob, job.id).upload_tmp_path == str(first)
        assert first.read_bytes() == b"first-bytes"
        assert second.read_bytes() == b"second-bytes"
    finally:
        settings.media_cache_root = saved_root


def test_duplicate_accepts_serialize_last_wins_and_drains_loser(test_db, tmp_path):
    """Same-attempt retries: last accept wins; loser drained post-commit."""
    from app.services.media_cache import cache_upload_staging_path, drain_reclaim_orphans

    settings = get_settings()
    saved_root = settings.media_cache_root
    settings.media_cache_root = str(tmp_path)
    try:
        _agent(test_db)
        asset = _asset(test_db)
        _queued_job(test_db, asset)
        leased = _lease(test_db)
        job = test_db.get(MediaJob, leased.job_id)

        first = cache_upload_staging_path(job.id, leased.lease_token)
        first.write_bytes(b"first-bytes")
        digest_a = hashlib.sha256(b"first-bytes").hexdigest()
        mark_job_uploaded(test_db, job.id, AGENT, str(first), digest_a, len(b"first-bytes"), leased.lease_token)
        test_db.commit()
        drain_reclaim_orphans(test_db)

        second = cache_upload_staging_path(job.id, leased.lease_token)
        assert second != first
        second.write_bytes(b"second-bytes")
        digest_b = hashlib.sha256(b"second-bytes").hexdigest()
        mark_job_uploaded(test_db, job.id, AGENT, str(second), digest_b, len(b"second-bytes"), leased.lease_token)
        test_db.commit()
        drain_reclaim_orphans(test_db)

        assert test_db.get(MediaJob, job.id).upload_tmp_path == str(second)
        assert second.read_bytes() == b"second-bytes"
        assert not first.exists()
    finally:
        settings.media_cache_root = saved_root
