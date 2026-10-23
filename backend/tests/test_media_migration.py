"""Historical web-package migration controller (SQLite tier).

Covers inventory, admission gates, the queue bound, budget accounting,
honest completion through the real read contract, pause/resume, source
drift, adoption of other paths' jobs, failure visibility (no silent retry,
breaker respected), crash-before-commit idempotence and legacy isolation.
"""
import hashlib
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.config import get_settings
from app.models.dive import Dive
from app.models.media import MediaAgent, MediaCacheEntry, MediaJob
from app.models.media_backbone import MediaBlob, MediaBlobLocation, MediaDerivative, MediaRevision
from app.models.media_migration import MediaMigrationItem, MediaMigrationRun
from app.schemas.media import MediaJobLeaseRequest
from app.services import automatic_packages as ap
from app.services import media_migration as mm
from app.services.media_keys import get_derivative_transform_version
from backend.tests.test_web_package_fenced_slots_d3b2 import (
    FakeS3,
    _asset,
    _presign,  # noqa: F401  (fixture)
    _fresh_capable_agent,
    _publish_slot,
)

GIB = 1024**3


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _source(db, video_uuid, raw, *, width=1920, height=1080, duration=10.0):
    settings = get_settings()
    sha = _sha(raw)
    key = f"blobs/sha256/{sha[:2]}/{sha}"
    db.add(MediaBlob(sha256=sha, byte_size=len(raw) * 1000, storage_backend="b2",
                     bucket=settings.media_backbone_prod_bucket, object_key=key,
                     width=width, height=height, duration_seconds=duration))
    db.add(MediaBlobLocation(blob_sha256=sha, environment="prod", storage_backend="b2",
                             bucket=settings.media_backbone_prod_bucket, object_key=key, verified=True))
    db.add(MediaRevision(video_uuid=video_uuid, blob_sha256=sha, rendition_semantics="photos_edited_rendition"))
    db.flush()
    return sha


def _clip(db, n, *, source=True, when=None, **kw):
    uuid = f"{n:08d}-0000-4000-8000-000000000000"
    asset = _asset(db, uuid=uuid)
    db.add(Dive(dive_datetime=when or (datetime(2026, 1, 1) + timedelta(days=n)), session_id=1,
                dive_code="101A", performance="G", performance_numeric=3, height="3",
                photos_asset_id=asset.id, video_uuid=uuid))
    sha = _source(db, uuid, f"camera-{n}".encode(), **kw) if source else None
    db.flush()
    return asset, sha


def _ledger(db, video_uuid, source_sha, roles=("hq", "light", "poster"), nbytes=1000):
    settings = get_settings()
    for role in roles:
        dsha = _sha(f"{video_uuid}{source_sha}{role}".encode())
        key = f"blobs/sha256/{dsha[:2]}/{dsha}"
        db.add(MediaBlob(sha256=dsha, byte_size=nbytes, storage_backend="b2",
                         bucket=settings.media_backbone_prod_bucket, object_key=key))
        db.add(MediaBlobLocation(blob_sha256=dsha, environment="prod", storage_backend="b2",
                                 bucket=settings.media_backbone_prod_bucket, object_key=key, verified=True))
        db.add(MediaRevision(video_uuid=video_uuid, blob_sha256=dsha, rendition_semantics=f"derived_{role}"))
        db.add(MediaDerivative(video_uuid=video_uuid, source_blob_sha256=source_sha, role=role,
                               transform_version=get_derivative_transform_version(),
                               derivative_blob_sha256=dsha, status="ready"))
    db.flush()


def _finish(db, job, source_sha, *, ready=True, alias=None, nbytes=1000, ledger=True):
    """Simulate the producer outcome on the job row (+ durable ledger)."""
    roles = ("light", "poster") if alias == "light" else ("hq", "light", "poster")
    job.finalized_slots = {
        "source_sha256": source_sha, "source_revision_id": 1, "source_width": 1920, "source_height": 1080,
        "transform_version": get_derivative_transform_version(), "hq_aliased_to": alias,
        "slots": {r: {"derivative_sha256": _sha(r.encode()), "size_bytes": nbytes} for r in roles} if ready else {},
    }
    job.status = "ready" if ready else "failed"
    job.attempts = max(job.attempts or 0, 1)
    job.last_error = None if ready else "ffmpeg_timeout"
    if ready and ledger:
        _ledger(db, job.asset.video_uuid, source_sha, roles=roles, nbytes=nbytes)
    db.flush()


def _facts(db, **overrides):
    facts = {"available": True, "scratch_free_bytes": 15 * GIB, "memory_pressure": "0",
             "measured_at": datetime.utcnow().isoformat()}
    facts.update(overrides)
    agent = db.get(MediaAgent, "mac-media-01")
    agent.storage_status = {"internal": {}, "package_resources": facts}
    db.flush()


@pytest.fixture
def env(test_db, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "media_web_packages_enabled", True)
    monkeypatch.setattr(ap.shutil, "disk_usage", lambda _: SimpleNamespace(free=36 * GIB))
    _fresh_capable_agent(test_db)
    _facts(test_db)
    return test_db


def _start(db, **kw):
    kw.setdefault("budget_bytes", 10 * GIB)
    run = mm.start_run(db, **kw)
    db.commit()
    return run


def _items(db):
    return {i.video_uuid[:8]: i for i in db.query(MediaMigrationItem).all()}


def _jobs(db):
    return db.query(MediaJob).filter_by(rendition="web_package").order_by(MediaJob.id).all()


def test_start_then_tick_admits_only_queue_depth_background_jobs(env):
    for n in range(1, 6):
        _clip(env, n)
    run = _start(env)
    assert env.query(MediaMigrationItem).count() == 5
    result = mm.tick(env)
    env.commit()
    assert result["blocked_gates"] == [] and result["admission"]["admitted"] == 2
    jobs = _jobs(env)
    assert [(j.priority, j.max_attempts, j.request_reason) for j in jobs] == [(70, 2, "historical_migration")] * 2
    # Most recent dives first.
    assert sorted(j.asset.video_uuid[:8] for j in jobs) == ["00000004", "00000005"]
    # Idempotent: a second tick with a full queue creates nothing.
    assert mm.tick(env)["admission"]["stopped"] == "queue_full"
    env.commit()
    assert len(_jobs(env)) == 2 and run.admitted_jobs == 2


def test_already_valid_package_is_skipped_without_job(env):
    asset, sha = _clip(env, 1)
    _ledger(env, asset.video_uuid, sha)
    _start(env)
    result = mm.tick(env)
    env.commit()
    assert result["admission"]["skipped_complete"] == 1 and _jobs(env) == []
    item = _items(env)["00000001"]
    assert item.status == "skipped_complete" and item.source_sha256 == sha and item.settled_bytes == 0


def test_small_source_alias_needs_producer_pin(env, test_db):
    a1, s1 = _clip(env, 1, width=1280, height=720)
    _ledger(env, a1.video_uuid, s1, roles=("light", "poster"))
    a2, s2 = _clip(env, 2, width=1280, height=720)
    _ledger(env, a2.video_uuid, s2, roles=("light", "poster"))
    pinned = MediaJob(photos_asset_id=a2.id, media_key="pin" + "0" * 61, rendition="web_package", status="queued")
    env.add(pinned)
    env.flush()
    _finish(env, pinned, s2, alias="light", ledger=False)
    version = get_derivative_transform_version()
    assert mm.package_state(env, a1.video_uuid, version)["reason"] == "hq_alias_unconfirmed"
    st = mm.package_state(env, a2.video_uuid, version)
    assert st["state"] == "complete" and st["hq_aliased_to"] == "light"


def test_missing_source_is_blocked_then_unblocked_when_repaired(env):
    asset, _ = _clip(env, 1, source=False)
    _start(env)
    mm.tick(env)
    env.commit()
    item = _items(env)["00000001"]
    assert item.status == "blocked" and item.reason == "no_canonical_source" and _jobs(env) == []
    report = mm.status_report(env)
    assert {"status": "blocked", "reason": "no_canonical_source", "count": 1} in report["blocked_or_failed_by_reason"]
    assert report["done"] is True  # nothing admissible remains; blocked is reported, not "complete"
    assert report["items"].get("complete", 0) == 0
    _source(env, asset.video_uuid, b"repaired")
    mm.tick(env)  # sweep unblocks, admission (same tick) queues it
    env.commit()
    assert _items(env)["00000001"].status == "queued" and len(_jobs(env)) == 1


def test_end_to_end_lease_publish_complete_with_real_guard(env, monkeypatch, tmp_path, _presign):
    from app.services import media_jobs as mj

    monkeypatch.setattr(get_settings(), "media_jobs_require_lease_token", True)
    monkeypatch.setattr(get_settings(), "b2_upload_environment", "prod")
    asset, sha = _clip(env, 1)
    _start(env, queue_depth=1)
    mm.tick(env)
    env.commit()
    leased = mj.lease_media_jobs(env, MediaJobLeaseRequest(
        agent_id="mac-media-01", capabilities=["web_package"], max_jobs=1, supports_lease_token=True))
    env.commit()
    assert len(leased) == 1 and leased[0].source_sha256 == sha
    job = env.get(MediaJob, leased[0].job_id)
    s3 = FakeS3()
    sizes = {}
    for slot in ("hq", "light", "poster"):
        path = tmp_path / f"{slot}.bin"
        payload = f"{slot}-bytes".encode() * (3 if slot == "hq" else 1)
        path.write_bytes(b"\xff\xd8" + payload if slot == "poster" else payload)
        sizes[slot] = path.stat().st_size
        dims = (1280, 720) if slot != "hq" else (1920, 1080)
        _publish_slot(env, job=job, agent_id="mac-media-01", token=leased[0].lease_token, slot=slot,
                      file_path=path, checksum=_sha(path.read_bytes()), size=sizes[slot],
                      source_sha=sha, s3=s3, monkeypatch=monkeypatch, dims=dims)
    env.refresh(job)
    assert job.status == "ready"
    result = mm.tick(env)
    env.commit()
    assert result["refresh"]["completed"] == 1
    item = _items(env)["00000001"]
    assert item.status == "complete" and item.published_objects == 3
    assert item.published_bytes == sum(sizes.values()) == item.settled_bytes
    report = mm.status_report(env)
    assert report["published"] == {"objects": 3, "bytes": sum(sizes.values())}
    assert report["throughput"]["completed_last_hour"] == 1 and report["done"] is True


def test_ready_job_without_durable_ledger_is_not_complete(env):
    asset, sha = _clip(env, 1)
    _start(env, queue_depth=1)
    mm.tick(env)
    _finish(env, _jobs(env)[0], sha, ledger=False)
    mm.tick(env)
    env.commit()
    item = _items(env)["00000001"]
    assert item.status == "failed" and item.reason == "ready_job_not_servable"
    assert mm.status_report(env)["items"].get("complete", 0) == 0


def test_failed_job_is_visible_never_silently_retried(env):
    asset, sha = _clip(env, 1)
    _start(env, queue_depth=1)
    mm.tick(env)
    job = _jobs(env)[0]
    job.attempts = 2
    _finish(env, job, sha, ready=False)
    mm.tick(env)
    mm.tick(env)
    env.commit()
    item = _items(env)["00000001"]
    assert item.status == "failed" and item.reason == "job_failed" and "ffmpeg_timeout" in item.last_error
    assert len(_jobs(env)) == 1
    # Conservative settle: estimate * attempts (orphan uploads possible).
    assert item.estimated_bytes == mm._estimate(env.get(MediaBlob, sha)) > 0
    assert item.settled_bytes == item.estimated_bytes * 2
    assert mm.accounted_bytes(env, env.query(MediaMigrationRun).one()) == item.settled_bytes
    report = mm.status_report(env)
    assert report["recent_failures"][0]["job_id"] == job.id
    # Explicit operator retry admits one new job (gates still apply).
    mm.retry_item(env, asset.video_uuid, "investigated: transient B2 timeout")
    mm.tick(env)
    env.commit()
    assert len(_jobs(env)) == 2 and _items(env)["00000001"].status == "queued"


def test_prior_failed_package_for_same_source_is_not_requeued(env):
    asset, sha = _clip(env, 1)
    other = MediaJob(photos_asset_id=asset.id, media_key="old" + "0" * 61, rendition="web_package",
                     status="queued", request_reason="new_captioned_ingestion", priority=60)
    env.add(other)
    env.flush()
    _finish(env, other, sha, ready=False)
    _start(env)
    mm.tick(env)
    env.commit()
    item = _items(env)["00000001"]
    assert item.status == "failed" and item.reason == "prior_package_failed" and len(_jobs(env)) == 1


def test_breaker_blocks_admission_and_retry_cannot_bypass(env):
    for n in (1, 2, 3):
        _clip(env, n)
    _start(env, queue_depth=2)
    mm.tick(env)
    for job in _jobs(env):
        _finish(env, job, mm.package_state(env, job.asset.video_uuid, get_derivative_transform_version())["source_sha256"],
                ready=False)
    result = mm.tick(env)
    env.commit()
    assert "package_breaker" in result["blocked_gates"]
    mm.retry_item(env, _jobs(env)[0].asset.video_uuid, "operator")
    assert "package_breaker" in mm.tick(env)["blocked_gates"]
    env.commit()
    assert len(_jobs(env)) == 2


@pytest.mark.parametrize("case", [
    "facts_missing", "scratch_low", "pressure", "pressure_unknown", "agent_stale", "server_low",
    "server_unknown", "packages_off", "transform_changed", "paused", "no_worker",
])
def test_gates_fail_closed(env, monkeypatch, case):
    _clip(env, 1)
    _start(env)
    agent = env.get(MediaAgent, "mac-media-01")
    if case == "facts_missing":
        agent.storage_status = {"internal": {}}
    if case == "scratch_low":
        _facts(env, scratch_free_bytes=8 * GIB - 1)
    if case == "pressure":
        _facts(env, memory_pressure="1")
    if case == "pressure_unknown":
        _facts(env, memory_pressure=None)
    if case == "agent_stale":
        agent.last_seen_at = datetime.utcnow() - timedelta(minutes=20)
    if case == "server_low":
        monkeypatch.setattr(ap.shutil, "disk_usage", lambda _: SimpleNamespace(free=25 * GIB - 1))
    if case == "server_unknown":
        monkeypatch.setattr(ap.shutil, "disk_usage", lambda _: (_ for _ in ()).throw(OSError()))
    if case == "packages_off":
        monkeypatch.setattr(get_settings(), "media_web_packages_enabled", False)
    if case == "transform_changed":
        monkeypatch.setattr(get_settings(), "media_derivative_transform_version", "ffmpeg-h264-web-v2")
    if case == "paused":
        mm.pause_run(env, "operator")
    if case == "no_worker":
        agent.leasing_enabled = False
    env.flush()
    result = mm.tick(env)
    env.commit()
    assert result["blocked_gates"] and result["admission"]["admitted"] == 0
    assert _jobs(env) == [] and _items(env)["00000001"].status == "pending"


def test_budget_is_explicit_and_conservative(env):
    _clip(env, 1)
    _clip(env, 2)
    estimate = mm._estimate(env.query(MediaBlob).first())
    _start(env, budget_bytes=estimate * 2 + 1, queue_depth=2)  # one in-flight job (x max_attempts)
    result = mm.tick(env)
    env.commit()
    assert result["admission"]["admitted"] == 1 and result["admission"]["stopped"] == "budget"
    report = mm.status_report(env)
    assert report["budget"]["accounted_bytes"] == estimate * 2


def test_admission_cap_bounds_first_lot(env):
    for n in range(1, 5):
        _clip(env, n)
    _start(env, admission_cap=1, queue_depth=3)
    result = mm.tick(env)
    env.commit()
    assert result["admission"]["admitted"] == 1 and len(_jobs(env)) == 1
    assert "admission_cap" in mm.tick(env)["blocked_gates"]
    mm.update_run(env, clear_admission_cap=True)
    mm.tick(env)
    env.commit()
    assert len(_jobs(env)) == 3


def test_pause_withdraws_unleased_keeps_leased_and_resume_continues(env):
    for n in (1, 2, 3):
        _clip(env, n)
    _start(env, queue_depth=2)
    mm.tick(env)
    leased, queued = _jobs(env)
    leased.status, leased.claimed_by, leased.attempts = "claimed", "mac-media-01", 1
    env.flush()
    out = mm.pause_run(env, "maintenance")
    env.commit()
    assert out["cancelled_queued_jobs"] == 1
    assert queued.status == "cancelled" and leased.status == "claimed"
    assert mm.tick(env)["admission"]["stopped"] == "gates"
    mm.resume_run(env)
    mm.tick(env)
    env.commit()
    active = [j for j in _jobs(env) if j.status in mm.ACTIVE_STATUSES]
    assert len(active) == 2 and len(_jobs(env)) == 3


def test_source_drift_requeues_completed_item(env):
    asset, sha = _clip(env, 1)
    _start(env, queue_depth=1)
    mm.tick(env)
    _finish(env, _jobs(env)[0], sha)
    mm.tick(env)
    env.commit()
    assert _items(env)["00000001"].status == "complete"
    _source(env, asset.video_uuid, b"edited-again")
    mm.tick(env)  # sweep detects drift -> pending -> admitted for the new source
    env.commit()
    item = _items(env)["00000001"]
    assert item.source_changes == 1 and item.status == "queued" and len(_jobs(env)) == 2


def test_failed_job_after_source_change_is_requeued_not_failed(env):
    asset, sha = _clip(env, 1)
    _start(env, queue_depth=1)
    mm.tick(env)
    job = _jobs(env)[0]
    _source(env, asset.video_uuid, b"new-source")
    _finish(env, job, sha, ready=False)
    mm.tick(env)
    env.commit()
    item = _items(env)["00000001"]
    assert item.source_changes == 1 and item.status == "queued" and len(_jobs(env)) == 2


def test_adopts_active_job_from_new_ingest_without_charge_or_reprioritizing(env):
    asset, sha = _clip(env, 1)
    from app.services.media_jobs import create_or_reuse_media_job

    _, auto, _ = create_or_reuse_media_job(env, asset, "web_package", "new_captioned_ingestion")
    auto.priority, auto.max_attempts = 60, 2
    env.flush()
    _start(env)
    mm.tick(env)
    env.commit()
    item = _items(env)["00000001"]
    assert item.status == "queued" and item.media_job_id == auto.id and item.job_owned is False
    assert auto.priority == 60 and len(_jobs(env)) == 1
    _finish(env, auto, sha)
    mm.tick(env)
    env.commit()
    item = _items(env)["00000001"]
    assert item.status == "complete" and item.settled_bytes == 0


def test_queued_job_whose_source_vanished_is_withdrawn_and_blocked(env):
    asset, sha = _clip(env, 1)
    _start(env, queue_depth=1)
    mm.tick(env)
    env.query(MediaBlobLocation).filter_by(blob_sha256=sha).update({"verified": False})
    env.flush()
    mm.tick(env)
    env.commit()
    assert _jobs(env)[0].status == "cancelled"
    assert _items(env)["00000001"].status == "blocked"


def test_crash_before_commit_leaves_no_partial_state(env):
    for n in (1, 2):
        _clip(env, n)
    _start(env)
    mm.tick(env)
    env.rollback()  # process killed before commit
    assert _jobs(env) == [] and {i.status for i in env.query(MediaMigrationItem)} == {"pending"}
    mm.tick(env)
    env.commit()
    mm.tick(env)
    env.commit()
    assert len(_jobs(env)) == 2


def test_sync_is_bounded_newest_first_and_converges(env, monkeypatch):
    for n in range(1, 8):
        _clip(env, n)
    monkeypatch.setattr(mm, "SYNC_BATCH", 3)
    run = mm.start_run(env, budget_bytes=GIB)
    assert sync_ids(env) == ["00000005", "00000006", "00000007"]
    assert mm.status_report(env)["unsynced_dives"] == 4 and mm.status_report(env)["done"] is False
    assert mm.sync_items(env, run, batch=3) == 3
    assert mm.sync_items(env, run, batch=3) == 1
    assert mm.sync_items(env, run, batch=3) == 0
    assert mm.status_report(env)["unsynced_dives"] == 0 and len(sync_ids(env)) == 7


def sync_ids(db):
    return sorted(i.video_uuid[:8] for i in db.query(MediaMigrationItem).all())


def test_new_dives_are_synced_and_single_open_run(env):
    _clip(env, 1)
    _start(env)
    with pytest.raises(mm.MigrationError):
        mm.start_run(env, budget_bytes=GIB)
    env.rollback()
    _clip(env, 2)
    assert mm.tick(env)["synced"] == 1


def test_lease_order_interactive_then_new_ingest_then_migration(env, monkeypatch, _presign):
    from app.services import media_jobs as mj

    a1, _ = _clip(env, 1)
    a2, _ = _clip(env, 2)
    a3, _ = _clip(env, 3)
    _start(env, queue_depth=1)
    mm.tick(env)  # migration job for clip 3 (most recent), priority 70
    new = MediaJob(photos_asset_id=a1.id, media_key="n" + "0" * 63, rendition="web_package",
                   status="queued", priority=60, request_reason="new_captioned_ingestion", max_attempts=2)
    env.add(new)
    env.flush()
    leased = mj.lease_media_jobs(env, MediaJobLeaseRequest(
        agent_id="mac-media-01", capabilities=["web_package"], max_jobs=1, supports_lease_token=True))
    assert leased[0].job_id == new.id


def test_legacy_rows_untouched(env):
    asset, _ = _clip(env, 1)
    legacy = MediaJob(photos_asset_id=asset.id, media_key="l" + "0" * 63, rendition="proxy_720p", status="ready")
    entry = MediaCacheEntry(photos_asset_id=asset.id, media_key="c" + "0" * 63, rendition="proxy_720p",
                            storage_path="/x", size_bytes=10, pinned=True, status="ready")
    env.add_all([legacy, entry])
    env.flush()
    _start(env)
    mm.tick(env)
    mm.pause_run(env, "x")
    env.commit()
    assert legacy.status == "ready" and entry.pinned is True and entry.status == "ready"


def test_status_report_carries_no_urls(env, _presign):
    _clip(env, 1)
    _start(env)
    mm.tick(env)
    env.commit()
    blob = repr(mm.status_report(env))
    assert "https://" not in blob and "signed" not in blob


def test_cli_roundtrip_exit_codes(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import app.models  # noqa: F401
    from app.database import Base
    from backend.scripts import media_migration as cli

    url = f"sqlite:///{tmp_path / 'db.sqlite'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(ap.shutil, "disk_usage", lambda _: SimpleNamespace(free=36 * GIB))
    assert cli.main(["--database-url", url, "status"]) == 2
    assert cli.main(["--database-url", url, "start", "--budget-gib", "1"]) == 0
    assert cli.main(["--database-url", url, "start", "--budget-gib", "1"]) == 2
    assert cli.main(["--database-url", url, "start", "--budget-gib", "1", "--priority", "10"]) == 2
    assert cli.main(["--database-url", url, "tick"]) == 0
    assert cli.main(["--database-url", url, "pause", "--reason", "test"]) == 0
    assert cli.main(["--database-url", url, "status", "--json"]) == 0
    assert cli.main(["--database-url", url, "resume"]) == 0
    assert cli.main(["--database-url", url, "inventory"]) == 0
    with sessionmaker(bind=engine)() as db:
        assert db.query(MediaMigrationRun).one().status == "active"


def test_repaired_asset_binding_is_refreshed_on_unblock(env):
    asset, _ = _clip(env, 1)
    dive = env.query(Dive).filter_by(video_uuid=asset.video_uuid).one()
    dive.photos_asset_id = None
    env.flush()
    _start(env)
    mm.tick(env)
    env.commit()
    item = _items(env)["00000001"]
    assert item.status == "blocked" and item.reason == "no_photos_asset" and item.photos_asset_id is None
    dive.photos_asset_id = asset.id  # binding repaired
    env.flush()
    mm.tick(env)  # sweep unblocks with the CURRENT binding, admission queues it
    env.commit()
    item = _items(env)["00000001"]
    assert item.photos_asset_id == asset.id and item.status == "queued" and len(_jobs(env)) == 1


def test_adopted_jobs_consume_queue_slots_and_refresh_is_bounded(env, monkeypatch):
    from app.services.media_jobs import create_or_reuse_media_job

    for n in range(1, 7):
        asset, _ = _clip(env, n)
        _, job, _ = create_or_reuse_media_job(env, asset, "web_package", "new_captioned_ingestion")
        job.priority = 60
    env.flush()
    _start(env, queue_depth=2)
    mm.tick(env)
    env.commit()
    items = env.query(MediaMigrationItem).all()
    assert sum(i.status == "queued" for i in items) == 2  # adoption bounded by queue_depth
    assert len(_jobs(env)) == 6  # no migration job created while adopted slots are full
    monkeypatch.setattr(mm, "REFRESH_BATCH", 1)
    for job in _jobs(env):
        job.status = "failed"
    env.flush()
    first = mm.refresh_queued(env, env.query(MediaMigrationRun).one(), datetime.utcnow() + timedelta(seconds=1))
    assert first["failed"] == 1
    second = mm.refresh_queued(env, env.query(MediaMigrationRun).one(), datetime.utcnow() + timedelta(seconds=2))
    assert second["failed"] == 1


def test_inventory_is_batched_exact_and_read_only(env):
    a1, s1 = _clip(env, 1)
    _ledger(env, a1.video_uuid, s1)
    _clip(env, 2, source=False)
    for n in range(3, 6):
        _clip(env, n)
    env.commit()
    full = mm.inventory(env, batch=2)
    assert full["clips"] == 5
    assert full["classes"] == {"already_complete": 1, "blocked:no_canonical_source": 1, "to_convert": 3}
    assert mm.inventory(env, batch=500) == full
    assert mm.inventory(env, batch=2, limit=3)["clips"] == 3
    assert env.query(MediaMigrationRun).count() == 0 and _jobs(env) == []


def test_batched_inventory_equals_per_clip_read_contract(env):
    """Bulk lookups must agree with the authoritative per-clip path."""
    settings = get_settings()
    a1, s1 = _clip(env, 1)
    _ledger(env, a1.video_uuid, s1)                      # complete
    a2, s2 = _clip(env, 2)
    _ledger(env, a2.video_uuid, s2, roles=("light",))    # ledger but incomplete
    _clip(env, 3, source=False)                          # no source
    a4, s4 = _clip(env, 4)                               # ambiguous: two verified PROD replicas
    env.add(MediaBlobLocation(blob_sha256=s4, environment="prod", storage_backend="b2",
                              bucket=settings.media_backbone_prod_bucket, object_key="dup/" + s4, verified=True))
    a5, s5 = _clip(env, 5)                               # newest revision unverified, older verified
    newer = _sha(b"unverified-newer")
    env.add(MediaBlob(sha256=newer, byte_size=10, storage_backend="b2", width=1920, height=1080,
                      duration_seconds=5))
    env.add(MediaBlobLocation(blob_sha256=newer, environment="prod", storage_backend="b2",
                              bucket=settings.media_backbone_prod_bucket, object_key="n/" + newer, verified=False))
    env.add(MediaRevision(video_uuid=a5.video_uuid, blob_sha256=newer, rendition_semantics="photos_edited_rendition"))
    a6, s6 = _clip(env, 6)                               # only a browser_playback revision
    env.query(MediaRevision).filter_by(video_uuid=a6.video_uuid).update({"rendition_semantics": "browser_playback"})
    a7, s7 = _clip(env, 7)                               # prior failed package for this source
    failed = MediaJob(photos_asset_id=a7.id, media_key="f" + "0" * 63, rendition="web_package", status="queued")
    env.add(failed)
    env.flush()
    _finish(env, failed, s7, ready=False)
    a8, s8 = _clip(env, 8, duration=None)                # unknown duration
    a9, s9 = _clip(env, 9, width=1280, height=720)       # small source, alias confirmed by pin
    _ledger(env, a9.video_uuid, s9, roles=("light", "poster"))
    pin9 = MediaJob(photos_asset_id=a9.id, media_key="a" + "0" * 63, rendition="web_package", status="queued")
    env.add(pin9)
    env.flush()
    _finish(env, pin9, s9, alias="light", ledger=False)
    a10, s10 = _clip(env, 10, width=1280, height=720)    # small source, alias NOT confirmed
    _ledger(env, a10.video_uuid, s10, roles=("light", "poster"))
    a11, s11 = _clip(env, 11)                            # ledger ready but light revision missing
    _ledger(env, a11.video_uuid, s11)
    env.query(MediaRevision).filter_by(video_uuid=a11.video_uuid, rendition_semantics="derived_light").delete()
    a12, s12 = _clip(env, 12)                            # hq replica in a wrong bucket
    _ledger(env, a12.video_uuid, s12)
    hq12 = env.query(MediaDerivative).filter_by(video_uuid=a12.video_uuid, role="hq").one()
    env.query(MediaBlobLocation).filter_by(blob_sha256=hq12.derivative_blob_sha256).update({"bucket": "other-bucket"})
    a13, s13 = _clip(env, 13)                            # stale poster row
    _ledger(env, a13.video_uuid, s13)
    env.query(MediaDerivative).filter_by(video_uuid=a13.video_uuid, role="poster").update({"status": "stale"})
    a14, s14 = _clip(env, 14)                            # failed package hidden behind > 10 newer jobs
    old = MediaJob(photos_asset_id=a14.id, media_key="o" + "0" * 63, rendition="web_package", status="queued")
    env.add(old)
    env.flush()
    _finish(env, old, s14, ready=False)
    for k in range(11):
        newer_job = MediaJob(photos_asset_id=a14.id, media_key=f"h{k:02d}" + "0" * 61, rendition="web_package",
                             status="queued")
        env.add(newer_job)
        env.flush()
        _finish(env, newer_job, _sha(f"other-source-{k}".encode()), ledger=False)
    a16, s16 = _clip(env, 16)                            # complete, plus history of an older source/transform
    _ledger(env, a16.video_uuid, _sha(b"old-source-16"))
    env.query(MediaDerivative).filter_by(video_uuid=a16.video_uuid).update({"transform_version": "ffmpeg-h264-web-v0"})
    _ledger(env, a16.video_uuid, s16)
    a15, s15 = _clip(env, 15)                            # failed package within the window
    recent = MediaJob(photos_asset_id=a15.id, media_key="r" + "0" * 63, rendition="web_package", status="queued")
    env.add(recent)
    env.flush()
    _finish(env, recent, s15, ready=False)
    env.commit()
    version = get_derivative_transform_version()
    reference = {}
    out = {"estimated_worst_case_bytes": 0, "source_bytes_to_convert": 0}
    for asset in (a1, a2, a4, a5, a6, a7, a8, a9, a10, a11, a12, a13, a14, a15, a16):
        cls = mm._classify_clip(env, asset.video_uuid, asset.id, version, out)
        reference[cls] = reference.get(cls, 0) + 1
    reference["blocked:no_canonical_source"] = reference.get("blocked:no_canonical_source", 0) + 1  # clip 3
    batched = mm.inventory(env, batch=3)
    assert batched["classes"] == dict(sorted(reference.items()))
    assert batched["estimated_worst_case_bytes"] == out["estimated_worst_case_bytes"]
    assert batched["classes"]["already_complete"] == 3 and batched["classes"]["prior_failed"] == 2
    assert mm.package_state(env, a9.video_uuid, version)["hq_aliased_to"] == "light"
    sources = mm._bulk_canonical_sources(env, [a.video_uuid for a in (a1, a4, a9, a10, a11, a12, a13, a16)])
    bulk = mm._bulk_package_complete(env, sources, version)
    for asset in (a1, a9, a10, a11, a12, a13, a16):
        assert bulk[asset.video_uuid]["complete"] == (
            mm.package_state(env, asset.video_uuid, version)["state"] == "complete"), asset.video_uuid


def test_inventory_batch_query_count_is_constant(env):
    """Statements per batch must not grow with the number of clips (no N+1)."""
    from sqlalchemy import event

    def count_for(n_clips, start):
        for n in range(start, start + n_clips):
            asset, sha = _clip(env, n)
            job = MediaJob(photos_asset_id=asset.id, media_key=f"q{n:04d}" + "0" * 59,
                           rendition="web_package", status="queued")
            env.add(job)
            env.flush()
            _finish(env, job, sha, alias="light" if n % 2 else None, ledger=bool(n % 3))
        env.commit()
        statements = []
        listener = lambda *args: statements.append(1)  # noqa: E731
        event.listen(env.bind, "before_cursor_execute", listener)
        try:
            report = mm.inventory(env, batch=500)
        finally:
            event.remove(env.bind, "before_cursor_execute", listener)
        return len(statements), report["clips"]

    small, clips_small = count_for(3, 100)
    large, clips_large = count_for(12, 200)
    assert clips_large == clips_small + 12
    assert large == small, (small, large)


def _infra_fail(db, job, error="lease_expired", when=None):
    job.status, job.attempts, job.last_error = "failed", max(job.attempts or 0, 1), error
    job.updated_at = when or datetime.utcnow()
    db.flush()


def test_infra_failures_never_open_the_breaker_and_self_heal(env):
    for n in (1, 2, 3):
        _clip(env, n)
    _start(env, queue_depth=2)
    mm.tick(env)
    a, b = _jobs(env)
    # A server restart kills both in-flight packages.
    _infra_fail(env, a, "lease_expired")
    _infra_fail(env, b, "heartbeat media job failed: 0 000")
    assert ap.package_breaker_job_ids(env) == []
    result = mm.tick(env)
    env.commit()
    assert "package_breaker" not in result["blocked_gates"]
    # Both clips were re-admitted automatically with fresh jobs.
    active = [j for j in _jobs(env) if j.status == "queued"]
    assert {j.asset.video_uuid for j in active} == {a.asset.video_uuid, b.asset.video_uuid}


def test_infra_retry_is_bounded_per_clip(env):
    _clip(env, 1)
    _start(env, queue_depth=1)
    old = datetime.utcnow() - timedelta(hours=2)  # outside the storm window
    for _ in range(mm.INFRA_RETRY_LIMIT):
        mm.tick(env)
        job = [j for j in _jobs(env) if j.status == "queued"][0]
        _infra_fail(env, job, when=old)
    mm.tick(env)
    env.commit()
    item = _items(env)["00000001"]
    assert item.status == "failed" and len(_jobs(env)) == mm.INFRA_RETRY_LIMIT


def test_infra_storm_opens_breaker_then_clears_by_itself(env):
    for n in (1, 2, 3):
        _clip(env, n)
    _start(env, queue_depth=3)
    mm.tick(env)
    for job in _jobs(env):
        _infra_fail(env, job)
    assert len(ap.package_breaker_job_ids(env)) == 3
    later = datetime.utcnow() + ap.INFRA_STORM_WINDOW + timedelta(minutes=1)
    assert ap.package_breaker_job_ids(env, now=later) == []


def test_real_failures_still_open_breaker_through_infra_noise(env):
    for n in (1, 2, 3):
        _clip(env, n)
    _start(env, queue_depth=3)
    mm.tick(env)
    a, b, c = _jobs(env)
    sha = lambda j: mm.package_state(env, j.asset.video_uuid, get_derivative_transform_version())["source_sha256"]
    _finish(env, a, sha(a), ready=False)
    _infra_fail(env, b)
    _finish(env, c, sha(c), ready=False)
    assert ap.package_breaker_job_ids(env) == [c.id, a.id]
