"""Prestream budget removal: exact reuse at full cap must publish (route, fakes + DB lease pin).

PR145 second finding: media.py route called check_publish_budget(db, size_bytes)
PRESTREAM, rejecting near-cap BEFORE the publisher could verify exact B2
object reuse via full GET (same key already proving same bytes skips PUT +
charge -- NO PUT, no charge). Fix: no prestream budget decision; prestream
keeps canary slot strict size caps + checksum shape + fenced lease peek and
during-stream reject-before-write. Authoritative per-PUT reserve stays AFTER
full-GET reuse MISS (definite 404 only) and BEFORE PUT; provider errors and
corrupt reuse fail closed (no PUT, no charge). Missing ledger blocks new
bytes; verified reuse at full cap commits without new charge. Budget refusal
is 409 (typed), internal stays 500.
"""

import hashlib
import io

import pytest

from app.config import get_settings
from app.models.media import MediaAgent, MediaJob
from app.models.photos_asset import PhotosAsset
from app.schemas.media import MediaJobLeaseRequest


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class FakeBody(io.BytesIO):
    def iter_chunks(self, chunk_size=1024 * 1024):
        while True:
            piece = self.read(chunk_size)
            if not piece:
                break
            yield piece


class FakeS3:
    """In-memory B2 fake: KeyError miss, corrupt/timeout modes for fail-closed."""

    def __init__(self, mode="ok"):
        self.objects: dict = {}
        self.mode = mode
        self.uploads = 0
        self.gets = 0

    def upload_file(self, path, bucket, key, ExtraArgs=None):
        from pathlib import Path as _P

        self.uploads += 1
        if self.mode == "upload_error":
            raise RuntimeError("boom")
        self.objects[(bucket, key)] = _P(path).read_bytes()

    def get_object(self, Bucket, Key):
        self.gets += 1
        if self.mode == "timeout":
            raise RuntimeError("timeout")
        data = self.objects.get((Bucket, Key))
        if data is None:
            raise KeyError(Key)
        if self.mode == "corrupt":
            data = b"corrupt:" + data
        return {"Body": FakeBody(data)}


def _seed_camera_source(db, video_uuid, raw=b"camera-bytes-v1", width=1920, height=1080):
    from app.models.media_backbone import MediaBlob, MediaBlobLocation, MediaRevision

    settings = get_settings()
    sha = _sha(raw + video_uuid.encode())
    db.add(
        MediaBlob(
            sha256=sha, byte_size=len(raw), storage_backend="b2",
            bucket=settings.media_backbone_prod_bucket,
            object_key=f"blobs/sha256/{sha[:2]}/{sha}",
            width=width, height=height, duration_seconds=10.0,
        )
    )
    db.add(
        MediaBlobLocation(
            blob_sha256=sha, environment="prod", storage_backend="b2",
            bucket=settings.media_backbone_prod_bucket,
            object_key=f"blobs/sha256/{sha[:2]}/{sha}", verified=True,
        )
    )
    db.add(
        MediaRevision(
            video_uuid=video_uuid, blob_sha256=sha,
            rendition_semantics="photos_edited_rendition",
        )
    )
    db.commit()
    return sha


def _agent(db, agent_id="mac-media-01"):
    agent = MediaAgent(
        id=agent_id,
        hostname="mac-server.local",
        api_key_sha256=hashlib.sha256(b"k" * 48).hexdigest(),
        active=True,
        leasing_enabled=True,
        capabilities=["poster", "proxy_720p", "proxy_360p", "web_package"],
    )
    db.add(agent)
    db.flush()
    return agent


def _asset(db, uuid):
    asset = PhotosAsset(video_uuid=uuid, media_type="video", width=1920, height=1080)
    db.add(asset)
    db.flush()
    return asset


def _canary_job(db, asset):
    job = MediaJob(
        photos_asset_id=asset.id,
        media_key="p" + "0" * 63,
        rendition="web_package",
        status="queued",
        request_reason="canary_web_package",
    )
    db.add(job)
    db.flush()
    return job


def _generic_job(db, asset):
    job = MediaJob(
        photos_asset_id=asset.id,
        media_key="g" + "0" * 63,
        rendition="web_package",
        status="queued",
        request_reason="user_request",
    )
    db.add(job)
    db.flush()
    return job


def _lease(db, agent_id="mac-media-01"):
    from app.services import media_jobs as mj

    leased = mj.lease_media_jobs(
        db,
        MediaJobLeaseRequest(
            agent_id=agent_id,
            capabilities=["web_package"],
            max_jobs=1,
            supports_lease_token=True,
        ),
    )
    assert len(leased) == 1
    db.commit()
    return leased[0]


def _fill_to_cap_minus(db, keep_free: int):
    """Fill accounted bytes to exactly CAP - keep_free with exact-key charges."""
    from app.services.canary_budget import CANARY_BUDGET_BYTES, canary_accounted_bytes
    from app.services.canary_budget import reserve_canary_upload

    assert canary_accounted_bytes(db) == 0
    target = CANARY_BUDGET_BYTES - keep_free
    # One hq fill + light chunks (respect per-slot caps: hq 1.2G, light 700M).
    idx = 0

    def _put(sha, size, slot):
        from app.services.canary_budget import reserve_canary_upload as _r

        _r(
            db, sha, size, job_id=9000 + idx, slot=slot,
            bucket="test-bucket",
            object_key=f"blobs/sha256/{sha[:2]}/{slot}-ffmpeg-h264-web-v1-fill{idx}-{sha}",
            environment="dev",
        )

    hq = min(1_200_000_000, target)
    if hq > 0:
        _put(_sha(f"fill-hq-{idx}".encode()), hq, "hq")
        idx += 1
        target -= hq
    while target > 0:
        chunk = min(target, 700_000_000)
        _put(_sha(f"fill-l-{idx}".encode()), chunk, "light")
        idx += 1
        target -= chunk
    assert canary_accounted_bytes(db) == CANARY_BUDGET_BYTES - keep_free


_ROUTE_KEY = "k" * 48
_ROUTE_AGENT = "mac-media-01"
_ROUTE_HEADERS = {"X-API-Key": _ROUTE_KEY}


@pytest.fixture()
def _presign(monkeypatch):
    from app.services import b2_presign

    class _FakeSigned:
        url = "https://b2.test/signed-object"

    monkeypatch.setattr(b2_presign, "presign_get", lambda **kw: _FakeSigned())
    return _FakeSigned()


def _route_setup(monkeypatch, tmp_path, fake):
    import app.services.derivative_publisher as dp
    import app.services.web_packages as wp

    settings = get_settings()
    saved_root = settings.media_cache_root
    settings.media_cache_root = str(tmp_path / "cache")
    monkeypatch.setattr(settings, "media_web_packages_enabled", True)
    monkeypatch.setattr(settings, "media_jobs_require_lease_token", True)
    monkeypatch.setattr(settings, "b2_upload_key_id", "k")
    monkeypatch.setattr(settings, "b2_upload_key_secret", "s")
    monkeypatch.setattr(settings, "b2_upload_region", "r")
    monkeypatch.setattr(settings, "b2_upload_environment", "prod")
    monkeypatch.setattr(wp, "validate_slot_artifact", lambda **kw: {"width": 1920, "height": 1080})
    monkeypatch.setattr(dp, "_b2_upload_client", lambda: fake)
    return saved_root


def _slot_payload(tmp_path, tag, slot="hq"):
    data = _sha(f"route-{tag}".encode()).encode() * 8  # deterministic ~512B
    # Make it JPEG-magic-free (validate faked) but checksum-real.
    p = tmp_path / f"route-{tag}-{slot}.bin"
    p.write_bytes(data)
    return p, _sha(data), len(data)


def _exact_key(source_sha, role, transform_version, derivative_sha):
    from app.services.derivative_publisher import derivative_object_key

    settings = get_settings()
    prefix = (settings.media_backbone_object_prefix or "blobs/sha256").strip().strip("/")
    key = derivative_object_key(
        source_sha256=source_sha, role=role,
        transform_version=transform_version,
        derivative_sha256=derivative_sha, prefix=prefix,
    )
    from app.services.media_backbone import environment_bucket

    env = (settings.b2_upload_environment or "").strip().lower()
    return env, environment_bucket(env), key


def test_route_canary_reuse_at_full_cap_succeeds_no_put_no_charge(
    api_client, test_db, monkeypatch, _presign, tmp_path
):
    """Cap fully spent + exact object already in B2 (uncommitted) => 200, no PUT, no charge."""
    from app.services.canary_budget import (
        CANARY_BUDGET_BYTES,
        canary_accounted_bytes,
        canary_reserved_bytes,
    )

    fake = FakeS3()
    saved = _route_setup(monkeypatch, tmp_path, fake)
    try:
        _agent(test_db)
        asset = _asset(test_db, "aaaaaaaa-1111-1111-1111-111111111111")
        src_sha = _seed_camera_source(test_db, asset.video_uuid)
        job = _canary_job(test_db, asset)
        leased = _lease(test_db)
        assert leased.transform_version
        pin = leased.transform_version
        fpath, digest, size = _slot_payload(tmp_path, "reuse-hit")
        _fill_to_cap_minus(test_db, 0)
        assert canary_accounted_bytes(test_db) == CANARY_BUDGET_BYTES
        # Exact uncommitted object already in B2 (full GET proves same bytes).
        env, bucket, key = _exact_key(src_sha, "hq", pin, digest)
        fake.objects[(bucket, key)] = fpath.read_bytes()
        reserved_before = canary_reserved_bytes(test_db)
        with fpath.open("rb") as fh:
            resp = api_client.post(
                f"/api/v1/media/jobs/{job.id}/package/slots",
                data={
                    "agent_id": _ROUTE_AGENT, "lease_token": leased.lease_token,
                    "slot": "hq", "checksum_sha256": digest,
                    "size_bytes": str(size), "content_type": "video/mp4",
                    "source_sha256": src_sha, "source_width": "1920",
                    "source_height": "1080", "transform_version": pin,
                },
                files={"file": ("hq.mp4", fh, "video/mp4")},
                headers=_ROUTE_HEADERS,
            )
        assert resp.status_code == 200, resp.text
        assert fake.uploads == 0  # NO PUT
        assert fake.gets >= 1  # reuse GET ran
        assert canary_reserved_bytes(test_db) == reserved_before  # no new charge
    finally:
        get_settings().media_cache_root = saved


def test_route_canary_absent_at_full_cap_refuses_409_no_put(
    api_client, test_db, monkeypatch, _presign, tmp_path
):
    """Cap fully spent + object absent (definite 404) => 409, no PUT, no charge."""
    from app.services.canary_budget import (
        CANARY_BUDGET_BYTES,
        canary_accounted_bytes,
        canary_reserved_bytes,
    )

    fake = FakeS3()  # empty: GET misses with KeyError (definite-absent)
    saved = _route_setup(monkeypatch, tmp_path, fake)
    try:
        _agent(test_db)
        asset = _asset(test_db, "bbbbbbbb-2222-2222-2222-222222222222")
        src_sha = _seed_camera_source(test_db, asset.video_uuid)
        job = _canary_job(test_db, asset)
        leased = _lease(test_db)
        pin = leased.transform_version
        fpath, digest, size = _slot_payload(tmp_path, "absent")
        _fill_to_cap_minus(test_db, 0)
        reserved_before = canary_reserved_bytes(test_db)
        assert canary_accounted_bytes(test_db) == CANARY_BUDGET_BYTES
        with fpath.open("rb") as fh:
            resp = api_client.post(
                f"/api/v1/media/jobs/{job.id}/package/slots",
                data={
                    "agent_id": _ROUTE_AGENT, "lease_token": leased.lease_token,
                    "slot": "hq", "checksum_sha256": digest,
                    "size_bytes": str(size), "content_type": "video/mp4",
                    "source_sha256": src_sha, "source_width": "1920",
                    "source_height": "1080", "transform_version": pin,
                },
                files={"file": ("hq.mp4", fh, "video/mp4")},
                headers=_ROUTE_HEADERS,
            )
        assert resp.status_code == 409, resp.text  # budget refusal, NOT 500
        assert fake.uploads == 0  # no PUT streamed
        assert canary_reserved_bytes(test_db) == reserved_before  # no new charge
    finally:
        get_settings().media_cache_root = saved


@pytest.mark.parametrize("mode,expect", [("corrupt", 502), ("timeout", 502)])
def test_route_canary_mismatch_and_timeout_no_put(
    api_client, test_db, monkeypatch, _presign, tmp_path, mode, expect
):
    """Present-but-different bytes and provider timeout both fail closed with no PUT."""
    from app.services.canary_budget import canary_accounted_bytes

    fake = FakeS3(mode=mode)
    saved = _route_setup(monkeypatch, tmp_path, fake)
    try:
        _agent(test_db)
        uuid = f"ccccccc-{mode}-3333-4444-555555555555"[:36]
        asset = _asset(test_db, uuid)
        src_sha = _seed_camera_source(test_db, asset.video_uuid, raw=f"cam-{mode}".encode())
        job = _canary_job(test_db, asset)
        leased = _lease(test_db)
        pin = leased.transform_version
        fpath, digest, size = _slot_payload(tmp_path, f"bad-{mode}")
        env, bucket, key = _exact_key(src_sha, "hq", pin, digest)
        if mode == "corrupt":
            fake.objects[(bucket, key)] = b"different-bytes:" + fpath.read_bytes()
        before = canary_accounted_bytes(test_db)
        with fpath.open("rb") as fh:
            resp = api_client.post(
                f"/api/v1/media/jobs/{job.id}/package/slots",
                data={
                    "agent_id": _ROUTE_AGENT, "lease_token": leased.lease_token,
                    "slot": "hq", "checksum_sha256": digest,
                    "size_bytes": str(size), "content_type": "video/mp4",
                    "source_sha256": src_sha, "source_width": "1920",
                    "source_height": "1080", "transform_version": pin,
                },
                files={"file": ("hq.mp4", fh, "video/mp4")},
                headers=_ROUTE_HEADERS,
            )
        assert resp.status_code == expect, f"{mode}: {resp.status_code} {resp.text}"
        assert fake.uploads == 0, mode
        assert canary_accounted_bytes(test_db) == before, mode
        test_db.rollback()
    finally:
        get_settings().media_cache_root = saved


def test_route_canary_streaming_oversize_cleanup(api_client, test_db, monkeypatch, _presign, tmp_path):
    """During-stream oversize is rejected before write with staging cleanup (same as before)."""
    fake = FakeS3()
    saved = _route_setup(monkeypatch, tmp_path, fake)
    try:
        _agent(test_db)
        asset = _asset(test_db, "dddddddd-4444-4444-4444-444444444444")
        src_sha = _seed_camera_source(test_db, asset.video_uuid)
        job = _canary_job(test_db, asset)
        leased = _lease(test_db)
        pin = leased.transform_version
        fpath, digest, size = _slot_payload(tmp_path, "oversize")
        real = fpath.read_bytes()
        claimed = size - 10  # claim smaller: stream must abort before write
        assert claimed > 0
        with fpath.open("rb") as fh:
            resp = api_client.post(
                f"/api/v1/media/jobs/{job.id}/package/slots",
                data={
                    "agent_id": _ROUTE_AGENT, "lease_token": leased.lease_token,
                    "slot": "hq", "checksum_sha256": digest,
                    "size_bytes": str(claimed), "content_type": "video/mp4",
                    "source_sha256": src_sha, "source_width": "1920",
                    "source_height": "1080", "transform_version": pin,
                },
                files={"file": ("hq.mp4", fh, "video/mp4")},
                headers=_ROUTE_HEADERS,
            )
        assert resp.status_code == 400, resp.text
        assert fake.uploads == 0
        # Staging for THIS request is gone; real bytes len != claimed so no commit.
        assert len(real) != claimed
        from app.services.media_cache import cache_upload_staging_path

        assert not cache_upload_staging_path(job.id, leased.lease_token).exists()
    finally:
        get_settings().media_cache_root = saved


def test_route_generic_noncanary_unchanged_at_full_cap(
    api_client, test_db, monkeypatch, _presign, tmp_path
):
    """Non-canary web_package at fully-spent cap still publishes (no budget gate)."""
    from app.services.canary_budget import CANARY_BUDGET_BYTES, canary_accounted_bytes

    fake = FakeS3()
    saved = _route_setup(monkeypatch, tmp_path, fake)
    try:
        _agent(test_db)
        asset = _asset(test_db, "eeeeeeee-5555-5555-5555-555555555555")
        src_sha = _seed_camera_source(test_db, asset.video_uuid)
        job = _generic_job(test_db, asset)
        leased = _lease(test_db)
        pin = leased.transform_version
        fpath, digest, size = _slot_payload(tmp_path, "generic")
        _fill_to_cap_minus(test_db, 0)  # cap fully spent
        assert canary_accounted_bytes(test_db) == CANARY_BUDGET_BYTES
        with fpath.open("rb") as fh:
            resp = api_client.post(
                f"/api/v1/media/jobs/{job.id}/package/slots",
                data={
                    "agent_id": _ROUTE_AGENT, "lease_token": leased.lease_token,
                    "slot": "hq", "checksum_sha256": digest,
                    "size_bytes": str(size), "content_type": "video/mp4",
                    "source_sha256": src_sha, "source_width": "1920",
                    "source_height": "1080", "transform_version": pin,
                },
                files={"file": ("hq.mp4", fh, "video/mp4")},
                headers=_ROUTE_HEADERS,
            )
        assert resp.status_code == 200, resp.text
        assert fake.uploads == 1  # generic streams normally
    finally:
        get_settings().media_cache_root = saved


def test_slot_publish_http_error_budget_409_vs_internal_500():
    """Typed budget classifier is 409; generic wrapped failure stays 500."""
    from app.api.v1.media import _slot_publish_http_error
    from app.services.derivative_publisher import (
        CanaryBudgetPublishError,
        DerivativePublishError,
    )
    from app.services.canary_budget import CanaryBudgetExceeded

    assert _slot_publish_http_error(CanaryBudgetPublishError("cap spent")).status_code == 409
    assert _slot_publish_http_error(CanaryBudgetExceeded("cap spent")).status_code == 409
    assert _slot_publish_http_error(DerivativePublishError("boom")).status_code == 500
    assert _slot_publish_http_error(RuntimeError("boom")).status_code == 500


def test_missing_ledger_blocks_new_bytes_but_reuse_path_needs_no_charge(test_db):
    """Missing reservation ledger: new PUT blocked; accounting fails closed."""
    from app.services.canary_budget import CanaryBudgetExceeded, canary_accounted_bytes
    from app.services.derivative_publisher import _try_verified_reuse

    # Simulate missing table by dropping it (SQLite): accounted must raise, not 0.
    from app.models.canary_ledger import CanarySlotReservation

    test_db.execute(__import__("sqlalchemy").text("DROP TABLE canary_slot_reservations"))
    test_db.commit()
    with pytest.raises(CanaryBudgetExceeded):
        canary_accounted_bytes(test_db)
    # Reuse HIT check itself is pure-provider (no ledger): still provable.
    data = b"reuse-still-provable"
    sha = _sha(data)

    class _Hit:
        def get_object(self, Bucket, Key):
            return {"Body": FakeBody(data)}

    assert _try_verified_reuse(client=_Hit(), bucket="b", key="k",
                               derivative_sha=sha, derivative_size=len(data)) is True
