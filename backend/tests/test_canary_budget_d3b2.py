"""Bounded canary admission + 2 GiB publication budget (SQLite, no prod/B2).

Proves the night-canary contract without any network, prod query, B2
write, job lease, or deploy:

- manifest shape (explicit UUIDs, dupes/total refused);
- phase caps (phase1 <= 5 cumulative, phase2 <= 25 additional, total <= 30);
- worst-case estimate is bounded and refuses unknown size/duration;
- ledger byte accounting is a bounded aggregate (distinct ready SHAs);
- publish guard refuses overshoot authoritatively (not an estimate);
- serial gate: one active fleet package blocks a second admission;
- admit tool: DRY-RUN writes nothing, --apply queues exactly ONE job
  at priority>=60 with max_attempts<=2, idempotent rerun admits nothing
  new while the first is active.
"""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from app.config import get_settings
from app.models.media import MediaJob
from app.models.media_backbone import MediaBlob, MediaBlobLocation, MediaDerivative, MediaRevision
from app.models.photos_asset import PhotosAsset
from app.services.canary_budget import (
    CANARY_BUDGET_BYTES,
    CANARY_JOB_MAX_ATTEMPTS,
    CANARY_JOB_PRIORITY,
    CanaryBudgetExceeded,
    canary_ledger_bytes,
    check_phase_count,
    check_publish_budget,
    validate_manifest_uuids,
    worst_case_package_bytes,
)

OPS_TOOL = Path(__file__).resolve().parents[2] / "ops" / "canary_web_package.py"


def _load_ops():
    spec = importlib.util.spec_from_file_location("canary_web_package", OPS_TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _seed_source(db, video_uuid, raw=b"camera-bytes-v1", width=1280, height=720,
                 duration=10.0):
    settings = get_settings()
    sha = _sha(raw + video_uuid.encode())
    db.add(PhotosAsset(video_uuid=video_uuid))
    db.flush()
    db.add(MediaBlob(sha256=sha, byte_size=len(raw), storage_backend="b2",
                     bucket=settings.media_backbone_prod_bucket,
                     object_key=f"blobs/sha256/{sha[:2]}/{sha}",
                     width=width, height=height, duration_seconds=duration))
    db.add(MediaBlobLocation(blob_sha256=sha, environment="prod", storage_backend="b2",
                             bucket=settings.media_backbone_prod_bucket,
                             object_key=f"blobs/sha256/{sha[:2]}/{sha}", verified=True))
    db.add(MediaRevision(video_uuid=video_uuid, blob_sha256=sha,
                         rendition_semantics="photos_edited_rendition"))
    db.commit()
    return sha


def _seed_ready_derivative(db, video_uuid, source_sha, role, nbytes):
    dsha = _sha(f"{video_uuid}{role}".encode())
    settings = get_settings()
    db.add(MediaBlob(sha256=dsha, byte_size=nbytes, storage_backend="b2",
                     bucket=settings.media_backbone_prod_bucket,
                     object_key=f"blobs/sha256/{dsha[:2]}/{dsha}"))
    db.add(MediaBlobLocation(blob_sha256=dsha, environment="prod", storage_backend="b2",
                             bucket=settings.media_backbone_prod_bucket,
                             object_key=f"blobs/sha256/{dsha[:2]}/{dsha}", verified=True))
    db.add(MediaRevision(video_uuid=video_uuid, blob_sha256=dsha,
                         rendition_semantics=f"derived_{role}"))
    db.add(MediaDerivative(video_uuid=video_uuid, source_blob_sha256=source_sha,
                           role=role, transform_version="ffmpeg-h264-web-v1",
                           derivative_blob_sha256=dsha, status="ready"))
    db.commit()
    return dsha


def test_manifest_shape_strict():
    assert validate_manifest_uuids(["a", "b"]) == ["a", "b"]
    with pytest.raises(ValueError):
        validate_manifest_uuids(["a", "a"])
    with pytest.raises(ValueError):
        validate_manifest_uuids([" a"])
    with pytest.raises(ValueError):
        validate_manifest_uuids(["a|b"])
    with pytest.raises(ValueError):
        validate_manifest_uuids(["x" * 101])
    with pytest.raises(ValueError):
        validate_manifest_uuids([f"clip-{i}" for i in range(31)])


def test_phase_caps():
    check_phase_count(1, 5, 0)
    with pytest.raises(ValueError):
        check_phase_count(1, 6, 0)
    with pytest.raises(ValueError):
        check_phase_count(1, 1, 5)
    check_phase_count(2, 25, 5)
    with pytest.raises(ValueError):
        check_phase_count(2, 26, 0)
    with pytest.raises(ValueError):
        check_phase_count(2, 1, 30)
    with pytest.raises(ValueError):
        check_phase_count(3, 1, 0)


def test_worst_case_estimate_bounded_and_fail_closed():
    est = worst_case_package_bytes(100_000_000, 10.0)
    # HQ ceiling 12Mbit/s * 10s = 15MB; floored at 2x source = 200MB here.
    assert est > 200_000_000
    with pytest.raises(ValueError):
        worst_case_package_bytes(None, 10.0)
    with pytest.raises(ValueError):
        worst_case_package_bytes(100, None)
    with pytest.raises(ValueError):
        worst_case_package_bytes(0, 10.0)


def test_ledger_bytes_bounded_aggregate(test_db):
    assert canary_ledger_bytes(test_db) == 0
    sha = _seed_source(test_db, "clip-ledger-1")
    _seed_ready_derivative(test_db, "clip-ledger-1", sha, "light", 1_000)
    _seed_ready_derivative(test_db, "clip-ledger-1", sha, "poster", 500)
    assert canary_ledger_bytes(test_db) == 1500


def test_publish_guard_hard_cap(test_db):
    # Fits: empty ledger + 1 byte slot.
    remaining = check_publish_budget(test_db, 1)
    assert remaining == CANARY_BUDGET_BYTES - 1
    # Overshoot: seed ~ledger then exceed.
    sha = _seed_source(test_db, "clip-cap-1")
    _seed_ready_derivative(test_db, "clip-cap-1", sha, "hq", CANARY_BUDGET_BYTES - 10)
    with pytest.raises(CanaryBudgetExceeded):
        check_publish_budget(test_db, 11)
    # Exact fit still allowed.
    assert check_publish_budget(test_db, 10) == 0
    with pytest.raises(ValueError):
        check_publish_budget(test_db, 0)


def test_serial_gate_and_admit_apply_one_job(test_db, tmp_path, monkeypatch):
    ops = _load_ops()
    _seed_source(test_db, "clip-admit-1")
    _seed_source(test_db, "clip-admit-2")
    manifest_path = tmp_path / "canary-manifest.json"
    manifest_path.write_text(json.dumps({"phase": 1, "clips": ["clip-admit-1", "clip-admit-2"]}))
    state_path = tmp_path / "canary-state"
    free_mac = 9 * 1024**3
    free_srv = 30 * 1024**3

    class Args:
        manifest = str(manifest_path)
        state_dir = str(state_path)
        phase = 1
        apply = False
        mac_free_bytes = free_mac
        server_cache_free_bytes = free_srv
        max_consecutive_failures = 2

    # Patch the tool's engine/session to reuse the SQLite test_db session.
    monkeypatch.setattr(ops, "_engine", lambda: None)
    monkeypatch.setattr(ops, "_session", lambda eng: test_db)
    monkeypatch.setattr(ops, "save_state", lambda d, s: None)
    monkeypatch.setattr(ops, "load_state",
                        lambda d: {"admitted": [], "verified": [], "consecutive_failures": 0})

    # DRY-RUN: plans one job, writes nothing.
    assert ops.cmd_admit(Args()) == 0
    assert test_db.query(MediaJob).filter(MediaJob.rendition == "web_package").count() == 0
    test_db.rollback()

    # APPLY: queues exactly one job at the canary contract.
    Args.apply = True
    assert ops.cmd_admit(Args()) == 0
    jobs = test_db.query(MediaJob).filter(MediaJob.rendition == "web_package").all()
    assert len(jobs) == 1
    assert jobs[0].priority == CANARY_JOB_PRIORITY
    assert jobs[0].priority >= 60
    assert jobs[0].max_attempts <= CANARY_JOB_MAX_ATTEMPTS
    test_db.rollback()

    # Serial: second run while the first is active admits nothing new.
    rc = ops.cmd_admit(Args())
    assert rc == 3  # fleet-blocked
    assert test_db.query(MediaJob).filter(MediaJob.rendition == "web_package").count() == 1


def test_dims_unknown_skips_clip(test_db, monkeypatch):
    ops = _load_ops()
    settings = get_settings()
    test_db.add(PhotosAsset(video_uuid="clip-nodims"))
    test_db.flush()
    raw = b"nodims-bytes"
    sha = _sha(raw)
    test_db.add(MediaBlob(sha256=sha, byte_size=len(raw), storage_backend="b2",
                          bucket=settings.media_backbone_prod_bucket,
                          object_key=f"blobs/sha256/{sha[:2]}/{sha}"))
    test_db.add(MediaBlobLocation(blob_sha256=sha, environment="prod", storage_backend="b2",
                                  bucket=settings.media_backbone_prod_bucket,
                                  object_key=f"blobs/sha256/{sha[:2]}/{sha}", verified=True))
    test_db.add(MediaRevision(video_uuid="clip-nodims", blob_sha256=sha,
                              rendition_semantics="photos_edited_rendition"))
    test_db.commit()
    r = ops.clip_readiness(test_db, "clip-nodims")
    assert r["ok"] is False
    assert r["status"] in ("dims_unknown", "source_unknown")
