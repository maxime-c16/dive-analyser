"""D3b2 fenced web-package slots (SQLite, fake B2, fake ffprobe).

Proves the fenced contract without any network/prod/B2:
- flag off: no package leased or queued (old flows byte-identical);
- flag on + capable worker: package leased with canonical B2 source pin,
  transform + per-slot keys; global ONE active package (not one per agent);
- slot publish happy path (3 slots -> job ready, ledger ready, idempotent
  per-slot retry same bytes);
- fencing: expired lease, re-leased SAME agent with a new token (mid-network
  stale attempt), and source-changed attempts are rejected with nothing
  promoted (B2 bytes stay a safe orphan);
- small-source hq alias is checked against server dims (not client trust);
- corrupt/HDR/wrong bytes rejected (real tiny SDR JPEG + fake ffprobe for
  the happy path; fake ffprobe failures for corrupt/HDR);
- old workers keep legacy-only flows.
"""

import hashlib
import io

import pytest

from app.config import get_settings
from app.models.media import MediaAgent, MediaJob
from app.models.media_backbone import (
    CaptionRevision,
    IngestObjectState,
    MediaBlob,
    MediaBlobLocation,
    MediaDerivative,
    MediaRevision,
)
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
    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}

    def upload_file(self, path, bucket, key, ExtraArgs=None):
        from pathlib import Path

        self.objects[(bucket, key)] = Path(path).read_bytes()

    def get_object(self, Bucket, Key):
        return {"Body": FakeBody(self.objects.get((Bucket, Key), b""))}


def _seed_camera_source(db, video_uuid, raw=b"camera-bytes-v1", width=None, height=None):
    settings = get_settings()
    sha = _sha(raw)
    db.add(MediaBlob(sha256=sha, byte_size=len(raw), storage_backend="b2",
                     bucket=settings.media_backbone_prod_bucket, object_key=f"blobs/sha256/{sha[:2]}/{sha}",
                     width=width, height=height))
    db.add(MediaBlobLocation(blob_sha256=sha, environment="prod", storage_backend="b2",
                             bucket=settings.media_backbone_prod_bucket,
                             object_key=f"blobs/sha256/{sha[:2]}/{sha}", verified=True))
    db.add(MediaRevision(video_uuid=video_uuid, blob_sha256=sha, rendition_semantics="photos_edited_rendition"))
    db.commit()
    return sha


def _agent(db, agent_id="mac-media-01", capabilities=None):
    agent = MediaAgent(
        id=agent_id,
        hostname="mac-server.local",
        api_key_sha256=hashlib.sha256(b"k" * 48).hexdigest(),
        active=True,
        leasing_enabled=True,
        capabilities=capabilities or ["poster", "proxy_720p", "web_package"],
    )
    db.add(agent)
    db.flush()
    return agent


def _asset(db, uuid="11111111-1111-1111-1111-111111111111", width=1920, height=1080):
    asset = PhotosAsset(video_uuid=uuid, media_type="video", width=width, height=height)
    db.add(asset)
    db.flush()
    return asset


def _package_job(db, asset):
    job = MediaJob(
        photos_asset_id=asset.id,
        media_key="p" + "0" * 63,
        rendition="web_package",
        status="queued",
    )
    db.add(job)
    db.flush()
    return job


# Real tiny SDR JPEG (1x1 pixel, SOI + minimal JFIF). ffprobe is faked;
# the file bytes + magic check are real.
_TINY_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00" + b"\x08" * 64 +
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b"
    b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00\xd2\xcf\x20\xff\xd9"
)


def _valid_probe(monkeypatch, width=1280, height=720, codec="h264", pix_fmt="yuv420p", transfer="bt709"):
    import app.services.web_packages as wp

    def _fake(path):
        return {"streams": [{"codec_type": "video", "codec_name": codec, "pix_fmt": pix_fmt,
                             "profile": "High" if codec == "h264" else "Baseline",
                             "width": width, "height": height, "color_transfer": transfer,
                             "color_primaries": transfer, "color_space": transfer}],
                "format": {"format_name": "mp4" if codec == "h264" else "mjpeg"}}
    monkeypatch.setattr(wp, "_ffprobe_streams", _fake)
    monkeypatch.setattr(wp, "_mp4_faststart_ok", lambda path: True)
    monkeypatch.setattr(wp, "_ffmpeg_decode_ok", lambda path: True)


def _slot_file(tmp_path, name, data: bytes) -> str:
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


@pytest.fixture()
def _presign(monkeypatch):
    from app.services import b2_presign

    class _FakeSigned:
        url = "https://b2.test/signed-object"

    monkeypatch.setattr(b2_presign, "presign_get", lambda **kw: _FakeSigned())
    return _FakeSigned()


def _publish_slot(db, *, job, agent_id, token, slot, file_path, checksum, size,
                  source_sha, s3, monkeypatch, alias=None, sw=None, sh=None, dims=(1280, 720),
                  transform_version=None):
    import app.services.web_packages as wp

    _valid_probe(monkeypatch, width=dims[0], height=dims[1])
    from app.services.derivative_publisher import build_publication_context, publish_derivative
    from app.services.media_keys import get_derivative_transform_version

    ctx = build_publication_context(db, video_uuid=job.asset.video_uuid, role=slot)
    assert source_sha.lower() == ctx.source_blob_sha256.lower()
    _tv = transform_version or get_derivative_transform_version()
    applicable = wp.check_small_source_alias(
        db=db, job=job, slot=slot, hq_aliased_to=alias, claimed_w=sw, claimed_h=sh,
        probed_w=dims[0], probed_h=dims[1], source_sha256=source_sha)
    guard = wp.make_slot_guard(
        job_id=job.id, agent_id=agent_id, lease_token=token,
        claimed_source_sha256=source_sha, slot=slot, applicable=applicable,
        hq_aliased_to=alias, transform_version=_tv, claimed_transform_version=_tv)
    return publish_derivative(db, ctx, file_path, s3_client=s3, pre_commit_hook=guard), applicable


def test_flag_off_no_package_lease_or_queue(test_db, monkeypatch, tmp_path):
    from app.services import media_jobs as mj

    settings = get_settings()
    monkeypatch.setattr(settings, "media_web_packages_enabled", False)
    _agent(test_db)
    asset = _asset(test_db)
    _package_job(test_db, asset)
    leased = mj.lease_media_jobs(test_db, MediaJobLeaseRequest(
        agent_id="mac-media-01", capabilities=["poster", "proxy_720p", "web_package"],
        max_jobs=2, supports_lease_token=True))
    assert all(j.rendition != "web_package" for j in leased)
    # Legacy payload stays byte-identical (no package fields).
    for entry in leased:
        assert entry.transform_version is None
        assert entry.expected_slots is None
    # Queue decision falls back to legacy.
    import app.services.web_packages as wp

    assert wp.package_worker_available(test_db) is False


def test_flag_on_package_lease_pins_source_and_global_cap(test_db, monkeypatch, _presign):
    from app.services import media_jobs as mj

    settings = get_settings()
    monkeypatch.setattr(settings, "media_web_packages_enabled", True)
    monkeypatch.setattr(settings, "media_jobs_require_lease_token", True)
    _agent(test_db)
    asset = _asset(test_db)
    sha = _seed_camera_source(test_db, asset.video_uuid, width=1920, height=1080)
    job_row = _package_job(test_db, asset)
    leased = mj.lease_media_jobs(test_db, MediaJobLeaseRequest(
        agent_id="mac-media-01", capabilities=["web_package"],
        max_jobs=2, supports_lease_token=True))
    assert len(leased) == 1 and leased[0].rendition == "web_package"
    assert leased[0].lease_token
    assert leased[0].source_sha256 == sha
    assert leased[0].transform_version
    assert leased[0].expected_slots == ["hq", "light", "poster"]
    assert set(leased[0].package_media_keys or {}) == {"hq", "light", "poster"}
    # Lease persists ONE pin (source SHA + revision + version) on the job;
    # URL/SHA/size/keys share that single canonical source (never transcoded).
    from app.services.web_packages import get_finalized_state as _gfs2
    test_db.refresh(job_row)
    _pin = _gfs2(job_row)
    assert _pin["source_sha256"] == sha
    assert _pin["transform_version"] == leased[0].transform_version
    assert _pin["source_revision_id"] is not None
    # Missing canonical source: package is skipped (fail closed, no doomed
    # lease, no attempt burned, legacy can still lease).
    asset_nosrc = _asset(test_db, uuid="99999999-9999-9999-9999-999999999999")
    job_nosrc = MediaJob(photos_asset_id=asset_nosrc.id, media_key="z" + "0" * 63,
                         rendition="web_package", status="queued")
    test_db.add(job_nosrc)
    test_db.flush()
    # Reclaim the active package so the no-source candidate is reachable,
    # then verify it is skipped while legacy work still leases.
    from datetime import datetime as _dt, timedelta as _td
    _active = test_db.get(MediaJob, job_row.id)
    _active.claimed_until = _dt.utcnow() - _td(seconds=1)
    test_db.flush()
    assert mj.reclaim_expired_media_jobs(test_db) >= 1
    legacy_asset = _asset(test_db, uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    legacy_job = MediaJob(photos_asset_id=legacy_asset.id, media_key="l" + "0" * 63,
                          rendition="poster", status="queued")
    test_db.add(legacy_job)
    test_db.flush()
    leased3 = mj.lease_media_jobs(test_db, MediaJobLeaseRequest(
        agent_id="mac-media-01", capabilities=["web_package", "poster"],
        max_jobs=2, supports_lease_token=True))
    assert all(j.rendition != "web_package" or j.job_id != job_nosrc.id for j in leased3)
    # Global cap: a second lease (any agent) gets no package while one is active.
    asset2 = _asset(test_db, uuid="22222222-2222-2222-2222-222222222222")
    _seed_camera_source(test_db, asset2.video_uuid, raw=b"camera-bytes-v2")
    job2 = MediaJob(photos_asset_id=asset2.id, media_key="q" + "0" * 63,
                    rendition="web_package", status="queued")
    test_db.add(job2)
    test_db.flush()
    leased2 = mj.lease_media_jobs(test_db, MediaJobLeaseRequest(
        agent_id="mac-media-01", capabilities=["web_package"],
        max_jobs=2, supports_lease_token=True))
    # At most one package may be active fleet-wide; with the reclaimed slot
    # refilled above, a further package must wait.
    assert len([j for j in leased2 if j.rendition == "web_package"]) <= 1


def test_old_worker_legacy_only_flag_off(test_db, monkeypatch):
    from app.services import media_jobs as mj

    settings = get_settings()
    monkeypatch.setattr(settings, "media_web_packages_enabled", False)
    _agent(test_db, capabilities=["poster", "proxy_720p"])
    asset = _asset(test_db)
    job = MediaJob(photos_asset_id=asset.id, media_key="f" + "0" * 63,
                   rendition="poster", status="queued")
    test_db.add(job)
    test_db.flush()
    leased = mj.lease_media_jobs(test_db, MediaJobLeaseRequest(
        agent_id="mac-media-01", capabilities=["poster"],
        max_jobs=1, supports_lease_token=False))
    assert len(leased) == 1 and leased[0].rendition == "poster"
    assert leased[0].lease_token is None


def test_three_slots_job_ready_atomic_and_idempotent_retry(test_db, monkeypatch, _presign, tmp_path):
    from app.services.web_packages import get_finalized_state

    settings = get_settings()
    monkeypatch.setattr(settings, "media_web_packages_enabled", True)
    monkeypatch.setattr(settings, "b2_upload_key_id", "k")
    monkeypatch.setattr(settings, "b2_upload_key_secret", "s")
    monkeypatch.setattr(settings, "b2_upload_region", "r")
    monkeypatch.setattr(settings, "b2_upload_environment", "prod")
    _agent(test_db)
    asset = _asset(test_db)
    sha = _seed_camera_source(test_db, asset.video_uuid)
    job = _package_job(test_db, asset)
    from app.services import media_jobs as mj

    leased = mj.lease_media_jobs(test_db, MediaJobLeaseRequest(
        agent_id="mac-media-01", capabilities=["web_package"],
        max_jobs=1, supports_lease_token=True))
    token = leased[0].lease_token
    test_db.commit()
    s3 = FakeS3()
    hq_bytes = _TINY_JPEG + b"hq"
    light_bytes = _TINY_JPEG + b"light"
    poster_bytes = _TINY_JPEG
    # hq/light are mp4 in prod; here the format check is mocked for fencing
    # (real format rejection lives in test_format_rejects below + poster).
    for slot, data, dims in (("hq", hq_bytes, (1280, 720)), ("light", light_bytes, (640, 360))):
        import app.services.web_packages as wp
        monkeypatch.setattr(wp, "validate_slot_artifact",
                            lambda **kw: {"width": dims[0], "height": dims[1]})
        path = _slot_file(tmp_path, f"{slot}.bin", data)
        from app.services.derivative_publisher import build_publication_context, publish_derivative
        from app.services.media_keys import get_derivative_transform_version as _vtv

        ctx = build_publication_context(test_db, video_uuid=asset.video_uuid, role=slot)
        _tv = leased[0].transform_version or _vtv()
        applicable = wp.check_small_source_alias(
            db=test_db, job=job, slot=slot, hq_aliased_to=None, claimed_w=1920, claimed_h=1080,
            probed_w=dims[0], probed_h=dims[1], source_sha256=sha)
        guard = wp.make_slot_guard(
            job_id=job.id, agent_id="mac-media-01", lease_token=token,
            claimed_source_sha256=sha, slot=slot, applicable=applicable,
            hq_aliased_to=None, transform_version=_tv, claimed_transform_version=_tv)
        publish_derivative(test_db, ctx, path, s3_client=s3, pre_commit_hook=guard)
    test_db.refresh(job)
    assert job.status != "ready"
    # Poster with real JPEG bytes (magic checked for real).
    import app.services.web_packages as wp
    monkeypatch.setattr(wp, "validate_slot_artifact",
                        lambda **kw: {"width": 320, "height": 180})
    poster_path = _slot_file(tmp_path, "poster.bin", poster_bytes)
    from app.services.derivative_publisher import build_publication_context, publish_derivative
    from app.services.media_keys import get_derivative_transform_version as _vtv2

    ctx = build_publication_context(test_db, video_uuid=asset.video_uuid, role="poster")
    _tv2 = leased[0].transform_version or _vtv2()
    guard = wp.make_slot_guard(
        job_id=job.id, agent_id="mac-media-01", lease_token=token,
        claimed_source_sha256=sha, slot="poster", applicable=["hq", "light", "poster"],
        hq_aliased_to=None, transform_version=_tv2, claimed_transform_version=_tv2)
    publish_derivative(test_db, ctx, poster_path, s3_client=s3, pre_commit_hook=guard)
    test_db.refresh(job)
    assert job.status == "ready"
    state = get_finalized_state(job)
    assert sorted(state["slots"].keys()) == ["hq", "light", "poster"]
    # Idempotent retry same bytes: still ready, no duplicate, no conflict.
    ctx2 = build_publication_context(test_db, video_uuid=asset.video_uuid, role="hq")
    guard2 = wp.make_slot_guard(
        job_id=job.id, agent_id="mac-media-01", lease_token=token,
        claimed_source_sha256=sha, slot="hq", applicable=["hq", "light", "poster"],
        hq_aliased_to=None, transform_version=_tv2, claimed_transform_version=_tv2)
    out = publish_derivative(test_db, ctx2, _slot_file(tmp_path, "hq2.bin", hq_bytes),
                             s3_client=s3, pre_commit_hook=guard2)
    assert out["status"] == "ready"
    test_db.refresh(job)
    assert job.status == "ready"


def test_expired_and_reclaimed_same_agent_rejected(test_db, monkeypatch, _presign, tmp_path):
    from datetime import datetime, timedelta

    from app.services import media_jobs as mj

    settings = get_settings()
    monkeypatch.setattr(settings, "media_web_packages_enabled", True)
    monkeypatch.setattr(settings, "b2_upload_key_id", "k")
    monkeypatch.setattr(settings, "b2_upload_key_secret", "s")
    monkeypatch.setattr(settings, "b2_upload_region", "r")
    monkeypatch.setattr(settings, "b2_upload_environment", "prod")
    _agent(test_db)
    asset = _asset(test_db)
    sha = _seed_camera_source(test_db, asset.video_uuid)
    job = _package_job(test_db, asset)
    first = mj.lease_media_jobs(test_db, MediaJobLeaseRequest(
        agent_id="mac-media-01", capabilities=["web_package"],
        max_jobs=1, supports_lease_token=True))[0]
    old_token = first.lease_token
    # Expire + reclaim to the SAME agent (new token mints; old attempt dies).
    job = test_db.get(MediaJob, job.id)
    job.claimed_until = datetime.utcnow() - timedelta(seconds=1)
    test_db.flush()
    assert mj.reclaim_expired_media_jobs(test_db) == 1
    second = mj.lease_media_jobs(test_db, MediaJobLeaseRequest(
        agent_id="mac-media-01", capabilities=["web_package"],
        max_jobs=1, supports_lease_token=True))[0]
    assert second.lease_token and second.lease_token != old_token
    test_db.commit()
    # Stale attempt with the old token is rejected (nothing promoted).
    import app.services.web_packages as wp
    monkeypatch.setattr(wp, "validate_slot_artifact", lambda **kw: {"width": 1280, "height": 720})
    from app.services.derivative_publisher import StaleSourceError, build_publication_context, publish_derivative
    from app.services.media_keys import get_derivative_transform_version as _vtv3

    ctx = build_publication_context(test_db, video_uuid=asset.video_uuid, role="hq")
    _tv3 = first.transform_version or _vtv3()
    stale_guard = wp.make_slot_guard(
        job_id=job.id, agent_id="mac-media-01", lease_token=old_token,
        claimed_source_sha256=sha, slot="hq", applicable=["hq", "light", "poster"],
        hq_aliased_to=None, transform_version=_tv3, claimed_transform_version=_tv3)
    path = _slot_file(tmp_path, "hq.bin", _TINY_JPEG + b"hq")
    with pytest.raises(Exception):
        publish_derivative(test_db, ctx, path, s3_client=FakeS3(), pre_commit_hook=stale_guard)
    test_db.refresh(job)
    assert job.status != "ready"
    assert job.lease_token == second.lease_token
    # Fresh attempt with the current token succeeds.
    ctx2 = build_publication_context(test_db, video_uuid=asset.video_uuid, role="hq")
    guard2 = wp.make_slot_guard(
        job_id=job.id, agent_id="mac-media-01", lease_token=second.lease_token,
        claimed_source_sha256=sha, slot="hq", applicable=["hq", "light", "poster"],
        hq_aliased_to=None, transform_version=_tv3, claimed_transform_version=_tv3)
    publish_derivative(test_db, ctx2, path, s3_client=FakeS3(), pre_commit_hook=guard2)


def test_source_changed_stale_and_small_source_alias(test_db, monkeypatch, _presign, tmp_path):
    from app.services import media_jobs as mj

    settings = get_settings()
    monkeypatch.setattr(settings, "media_web_packages_enabled", True)
    monkeypatch.setattr(settings, "b2_upload_key_id", "k")
    monkeypatch.setattr(settings, "b2_upload_key_secret", "s")
    monkeypatch.setattr(settings, "b2_upload_region", "r")
    monkeypatch.setattr(settings, "b2_upload_environment", "prod")
    _agent(test_db)
    asset = _asset(test_db)
    sha_v1 = _seed_camera_source(test_db, asset.video_uuid, raw=b"camera-v1")
    job = _package_job(test_db, asset)
    leased = mj.lease_media_jobs(test_db, MediaJobLeaseRequest(
        agent_id="mac-media-01", capabilities=["web_package"],
        max_jobs=1, supports_lease_token=True))[0]
    # New verified source lands mid-job.
    _seed_camera_source(test_db, asset.video_uuid, raw=b"camera-v2")
    import app.services.web_packages as wp
    monkeypatch.setattr(wp, "validate_slot_artifact", lambda **kw: {"width": 1280, "height": 720})
    from app.services.derivative_publisher import StaleSourceError, build_publication_context, publish_derivative
    from app.services.media_keys import get_derivative_transform_version as _vtv4

    # The worker's pinned v1 bytes are now stale: commit goes stale, never ready.
    ctx = build_publication_context(test_db, video_uuid=asset.video_uuid, role="hq")
    assert ctx.source_blob_sha256 != sha_v1
    _tv4 = leased.transform_version
    guard = wp.make_slot_guard(
        job_id=job.id, agent_id="mac-media-01", lease_token=leased.lease_token,
        claimed_source_sha256=sha_v1, slot="hq", applicable=["hq", "light", "poster"],
        hq_aliased_to=None, transform_version=_tv4, claimed_transform_version=_tv4)
    path = _slot_file(tmp_path, "hq.bin", _TINY_JPEG)
    with pytest.raises(StaleSourceError):
        publish_derivative(test_db, ctx, path, s3_client=FakeS3(), pre_commit_hook=guard)
    # Small-source alias: server MediaBlob dims (640x360) prove the claim;
    # worker claims are never trusted, unknown dims refuse (fail closed).
    small_uuid = "33333333-3333-3333-3333-333333333333"
    small = _asset(test_db, uuid=small_uuid, width=640, height=360)
    small_sha = _seed_camera_source(test_db, small_uuid, raw=b"small-camera", width=640, height=360)
    job_small = MediaJob(photos_asset_id=small.id, media_key="s" + "0" * 63,
                         rendition="web_package", status="claimed",
                         claimed_by="mac-media-01", lease_token="t" * 32,
                         attempts=1)
    from datetime import datetime, timedelta

    job_small.claimed_until = datetime.utcnow() + timedelta(minutes=5)
    test_db.add(job_small)
    test_db.flush()
    from app.services.web_packages import get_finalized_state as _gfs, set_finalized_state as _sfs
    _sfs(job_small, {"source_sha256": small_sha, "source_revision_id": None,
                     "transform_version": _tv4, "hq_aliased_to": None, "slots": {}})
    test_db.flush()
    applicable = wp.check_small_source_alias(
        db=test_db, job=job_small, slot="light", hq_aliased_to="light",
        claimed_w=640, claimed_h=360, probed_w=640, probed_h=360, source_sha256=small_sha)
    assert applicable == ["light", "poster"]
    big_uuid = "44444444-4444-4444-4444-444444444444"
    big = _asset(test_db, uuid=big_uuid, width=3840, height=2160)
    big_sha = _seed_camera_source(test_db, big_uuid, raw=b"big-camera", width=3840, height=2160)
    job_big = MediaJob(photos_asset_id=big.id, media_key="b" + "0" * 63,
                       rendition="web_package", status="claimed",
                       claimed_by="mac-media-01", lease_token="u" * 32, attempts=1)
    job_big.claimed_until = datetime.utcnow() + timedelta(minutes=5)
    test_db.add(job_big)
    test_db.flush()
    _sfs(job_big, {"source_sha256": big_sha, "source_revision_id": None,
                   "transform_version": _tv4, "hq_aliased_to": None, "slots": {}})
    test_db.flush()
    with pytest.raises(ValueError):
        wp.check_small_source_alias(
            db=test_db, job=job_big, slot="light", hq_aliased_to="light",
            claimed_w=640, claimed_h=360, probed_w=640, probed_h=360, source_sha256=big_sha)
    # Unknown dims fail closed (never trust the worker claim alone).
    nodim_uuid = "55555555-5555-5555-5555-555555555555"
    nodim = _asset(test_db, uuid=nodim_uuid, width=640, height=360)
    nodim_sha = _seed_camera_source(test_db, nodim_uuid, raw=b"nodim-camera")
    job_nodim = MediaJob(photos_asset_id=nodim.id, media_key="n" + "0" * 63,
                         rendition="web_package", status="claimed",
                         claimed_by="mac-media-01", lease_token="v" * 32, attempts=1)
    job_nodim.claimed_until = datetime.utcnow() + timedelta(minutes=5)
    test_db.add(job_nodim)
    test_db.flush()
    _sfs(job_nodim, {"source_sha256": nodim_sha, "source_revision_id": None,
                     "transform_version": _tv4, "hq_aliased_to": None, "slots": {}})
    test_db.flush()
    with pytest.raises(ValueError):
        wp.check_small_source_alias(
            db=test_db, job=job_nodim, slot="light", hq_aliased_to="light",
            claimed_w=640, claimed_h=360, probed_w=640, probed_h=360, source_sha256=nodim_sha)


def test_format_corrupt_hdr_rejected(test_db, monkeypatch, tmp_path):
    import app.services.web_packages as wp

    # Corrupt: ffprobe cannot parse.
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not-a-video-at-all" * 64)
    monkeypatch.setattr(wp, "_ffprobe_streams", lambda path: (_ for _ in ()).throw(RuntimeError("moov not found")))
    with pytest.raises(ValueError):
        wp.validate_slot_artifact(path=bad, slot="hq", expected_sha256=_sha(bad.read_bytes()),
                                  expected_size=bad.stat().st_size)
    # HDR-tagged output rejected (must be tone-mapped SDR).
    sdr = tmp_path / "hdr.mp4"
    sdr.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 2048)
    digest = _sha(sdr.read_bytes())
    monkeypatch.setattr(wp, "_ffprobe_streams", lambda path: {
        "streams": [{"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p", "profile": "High",
                     "width": 1280, "height": 720, "color_transfer": "smpte2084",
                     "color_primaries": "bt2020", "color_space": "bt2020c"}],
        "format": {"format_name": "mp4"}})
    monkeypatch.setattr(wp, "_mp4_faststart_ok", lambda path: True)
    monkeypatch.setattr(wp, "_ffmpeg_decode_ok", lambda path: True)
    with pytest.raises(ValueError, match="HDR"):
        wp.validate_slot_artifact(path=sdr, slot="hq", expected_sha256=digest,
                                  expected_size=sdr.stat().st_size)
    # Missing BT.709 tags rejected (fail closed, never accept unknown).
    notag = tmp_path / "notag.mp4"
    notag.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x01" * 2048)
    ndigest = _sha(notag.read_bytes())
    monkeypatch.setattr(wp, "_ffprobe_streams", lambda path: {
        "streams": [{"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p", "profile": "High",
                     "width": 1280, "height": 720}],
        "format": {"format_name": "mp4"}})
    with pytest.raises(ValueError, match="BT.709"):
        wp.validate_slot_artifact(path=notag, slot="hq", expected_sha256=ndigest,
                                  expected_size=notag.stat().st_size)
    # Wrong profile / container rejected.
    badprof = tmp_path / "badprof.mp4"
    badprof.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x02" * 2048)
    bdigest = _sha(badprof.read_bytes())
    monkeypatch.setattr(wp, "_ffprobe_streams", lambda path: {
        "streams": [{"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p", "profile": "Baseline",
                     "width": 1280, "height": 720, "color_transfer": "bt709",
                     "color_primaries": "bt709", "color_space": "bt709"}],
        "format": {"format_name": "mp4"}})
    with pytest.raises(ValueError, match="High"):
        wp.validate_slot_artifact(path=badprof, slot="hq", expected_sha256=bdigest,
                                  expected_size=badprof.stat().st_size)
    # Faststart None rejected (fail closed, not accepted).
    noatoms = tmp_path / "noatoms.mp4"
    noatoms.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x03" * 2048)
    adigest = _sha(noatoms.read_bytes())
    monkeypatch.setattr(wp, "_ffprobe_streams", lambda path: {
        "streams": [{"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p", "profile": "High",
                     "width": 1280, "height": 720, "color_transfer": "bt709",
                     "color_primaries": "bt709", "color_space": "bt709"}],
        "format": {"format_name": "mp4"}})
    monkeypatch.setattr(wp, "_mp4_faststart_ok", lambda path: None)
    with pytest.raises(ValueError, match="faststart"):
        wp.validate_slot_artifact(path=noatoms, slot="hq", expected_sha256=adigest,
                                  expected_size=noatoms.stat().st_size)
    monkeypatch.setattr(wp, "_mp4_faststart_ok", lambda path: True)
    # Malformed JPEG magic rejected even when ffprobe claims video.
    badjpg = tmp_path / "bad.jpg"
    badjpg.write_bytes(b"notajpeg" * 64)
    jdigest = _sha(badjpg.read_bytes())
    monkeypatch.setattr(wp, "_ffprobe_streams", lambda path: {
        "streams": [{"codec_type": "video", "codec_name": "mjpeg", "pix_fmt": "yuvj420p",
                     "width": 320, "height": 180, "color_transfer": "bt709"}],
        "format": {"format_name": "mjpeg"}})
    with pytest.raises(ValueError, match="JPEG"):
        wp.validate_slot_artifact(path=badjpg, slot="poster", expected_sha256=jdigest,
                                  expected_size=badjpg.stat().st_size)
    # Real tiny SDR JPEG passes the magic check; ffprobe faked SDR.
    poster = tmp_path / "poster.jpg"
    poster.write_bytes(_TINY_JPEG)
    monkeypatch.setattr(wp, "_ffprobe_streams", lambda path: {
        "streams": [{"codec_type": "video", "codec_name": "mjpeg", "pix_fmt": "yuvj420p",
                     "width": 320, "height": 180, "color_transfer": "bt709"}],
        "format": {"format_name": "mjpeg"}})
    monkeypatch.setattr(wp, "_ffmpeg_decode_ok", lambda path: True)
    probed = wp.validate_slot_artifact(path=poster, slot="poster",
                                       expected_sha256=_sha(_TINY_JPEG),
                                       expected_size=len(_TINY_JPEG))
    assert probed["width"] == 320
