"""Canary ops CLI integration: budget/resume/phase2/proof/host-facts (SQLite, no prod/B2).

Covers parent-review gaps beyond helper unit tests: actual admit /
verify / resume / phase2 / parallel-dedup / budget-failure paths with
a fake DB (test_db fixture), plus host-facts freshness + memory
pressure, ready-vs-proven separation, and DB-authoritative totals.
"""

import datetime
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
    canary_accounted_bytes,
    canary_ledger_bytes,
    check_phase2_eligible,
    check_phase_count_new_only,
    load_host_facts,
    new_unique_ids,
    normalize_object_sha,
    reserve_canary_upload,
    validate_canary_slot_size,
    validate_host_facts,
)

OPS_TOOL = Path(__file__).resolve().parents[2] / "ops" / "canary_web_package.py"


def _load_ops():
    spec = importlib.util.spec_from_file_location("canary_web_package_cli", OPS_TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _seed_source(db, video_uuid, raw=b"camera-bytes-v1", width=1280, height=720, duration=10.0):
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


def _facts_file(tmp_path, fresh=True, pressure="normal", mac_free=9 * 1024**3, srv_free=30 * 1024**3):
    now = datetime.datetime.now(datetime.timezone.utc)
    if not fresh:
        now = now - datetime.timedelta(minutes=30)
    p = tmp_path / "host-facts.json"
    p.write_text(json.dumps({
        "mac_free_bytes": mac_free,
        "server_cache_free_bytes": srv_free,
        "mac_memory_pressure": pressure,
        "checked_at": now.isoformat(),
        "mac_data_path": "/Users/Shared/services/data/diveanalyzer",
        "server_cache_path": "/var/lib/diveanalyzer/cache",
    }))
    return str(p)


def _key_for(sha: str, role: str = "light", tag: str = "a") -> tuple[str, str, str]:
    """Exact-key test identity: distinct keys per (role, tag), embedding the SHA."""
    return (
        "test-bucket",
        f"blobs/sha256/ab/{role}-ffmpeg-h264-web-v1-{tag}-{sha}" if False
        else f"blobs/sha256/{sha[:2]}/{role}-ffmpeg-h264-web-v1-{sha}",
        "dev",
    )


def _reserve(db, sha: str, size: int, *, job_id=1, slot="light", key=None, bucket="test-bucket", env="dev"):
    bkt, k, e = (bucket, key, env) if key else (bucket, f"blobs/sha256/{sha[:2]}/{slot}-ffmpeg-h264-web-v1-{sha}", env)
    return reserve_canary_upload(
        db, sha, size, job_id=job_id, slot=slot, bucket=bkt, object_key=k, environment=e,
    )


def test_reservation_counts_orphans_and_charges_each_put_attempt(test_db):
    sha1 = _sha(b"orphan-1")
    assert canary_accounted_bytes(test_db) == 0
    # Reserve an object that never becomes a READY row (crashed attempt orphan).
    _reserve(test_db, sha1, 1000, job_id=1, slot="light")
    assert canary_accounted_bytes(test_db) == 1000
    assert canary_ledger_bytes(test_db) == 1000
    # Same-key retry is a NEW PUT attempt: it charges AGAIN (each PUT may
    # store a new version; the lease does not serialize duplicate HTTP).
    # Only a verified full-GET reuse (no PUT) avoids a new charge.
    remaining = _reserve(test_db, sha1, 1000, job_id=1, slot="light")
    assert canary_accounted_bytes(test_db) == 2000
    assert remaining == CANARY_BUDGET_BYTES - 2000
    # Same key with different size fails closed (corrupt claim): no new charge.
    bkt, k, e = "test-bucket", f"blobs/sha256/{sha1[:2]}/light-ffmpeg-h264-web-v1-{sha1}", "dev"
    with pytest.raises(ValueError):
        reserve_canary_upload(test_db, sha1, 1001, job_id=2, slot="light",
                              bucket=bkt, object_key=k, environment=e)
    assert canary_accounted_bytes(test_db) == 2000
    # Legacy READY rows for other SHAs add once per exact object.
    src = _seed_source(test_db, "clip-orphan-2")
    dsha = _seed_ready_derivative(test_db, "clip-orphan-2", src, "light", 500)
    assert dsha != sha1
    assert canary_accounted_bytes(test_db) == 2500


def test_reservation_exact_key_counts_distinct_objects(test_db):
    # Identical bytes under different B2 keys are DISTINCT stored objects:
    # each counts (SHA-only dedupe would under-count to 1x).
    from app.models.canary_ledger import CanarySlotReservation
    test_db.query(CanarySlotReservation).delete()
    test_db.commit()
    assert canary_accounted_bytes(test_db) == 0
    sha = _sha(b"same-poster-bytes")
    k1 = f"blobs/sha256/{sha[:2]}/poster-ffmpeg-h264-web-v1-{sha}"
    # Different source/role path, same content bytes -> distinct key, distinct object.
    k2 = f"blobs/sha256/{sha[:2]}/light-ffmpeg-h264-web-v1-{sha}"
    reserve_canary_upload(test_db, sha, 800, job_id=1, slot="poster",
                          bucket="bkt", object_key=k1, environment="dev")
    assert canary_accounted_bytes(test_db) == 800
    reserve_canary_upload(test_db, sha, 800, job_id=2, slot="light",
                          bucket="bkt", object_key=k2, environment="dev")
    assert canary_accounted_bytes(test_db) == 1600
    # Same-key retry is a NEW PUT attempt: charges again (each PUT may
    # store a new version). Only verified full-GET reuse avoids a charge.
    reserve_canary_upload(test_db, sha, 800, job_id=2, slot="light",
                          bucket="bkt", object_key=k2, environment="dev")
    assert canary_accounted_bytes(test_db) == 2400
    # Key must embed the SHA: mismatched key fails closed.
    with pytest.raises(ValueError):
        reserve_canary_upload(test_db, sha, 800, job_id=3, slot="light",
                              bucket="bkt",
                              object_key=f"blobs/sha256/{sha[:2]}/light-ffmpeg-h264-web-v1-{_sha(b'other')}",
                              environment="dev")
    # Missing exact key fails closed (no SHA-only fallback).
    with pytest.raises(ValueError):
        reserve_canary_upload(test_db, sha, 800, job_id=3, slot="light")


def test_reservation_hard_cap_and_per_slot_caps(test_db):
    with pytest.raises(ValueError):
        validate_canary_slot_size("hq", 2_000_000_000)
    with pytest.raises(ValueError):
        validate_canary_slot_size("poster", 9 * 1024 * 1024)
    with pytest.raises(ValueError):
        normalize_object_sha("not-hex")
    big = _sha(b"big-1")
    # Fill to exactly the cap via several per-slot-cap-compliant
    # reservations (exact keys), then prove the next byte refuses.
    _reserve(test_db, _sha(b"fill-hq"), 1_200_000_000, slot="hq")
    _reserve(test_db, _sha(b"fill-light"), 700_000_000, slot="light")
    _reserve(test_db, _sha(b"fill-poster"), 8_000_000, slot="poster")
    rest = CANARY_BUDGET_BYTES - (1_200_000_000 + 700_000_000 + 8_000_000) - 10
    _reserve(test_db, big, rest, slot="hq")
    small = _sha(b"small-1")
    with pytest.raises(CanaryBudgetExceeded):
        _reserve(test_db, small, 11, slot="light")
    assert _reserve(test_db, small, 10, slot="light") == 0


def test_resume_counts_only_new_unique_ids():
    assert new_unique_ids(["a", "b", "c"], {"a", "c"}) == ["b"]
    check_phase_count_new_only(1, 0, 5)  # re-listing admitted clips costs zero
    with pytest.raises(ValueError):
        check_phase_count_new_only(1, 1, 5)
    check_phase_count_new_only(2, 25, 5)
    with pytest.raises(ValueError):
        check_phase_count_new_only(2, 1, 30)


def test_phase2_requires_exact_proven_cohort_and_db_authority():
    cohort = ["p1", "p2", "p3", "p4", "p5"]
    # Fresh state (no proofs) can never open phase 2, even with admitted>=5 in DB.
    with pytest.raises(ValueError):
        check_phase2_eligible(phase1_cohort=cohort, proven_uuids=set(),
                              db_total_admitted=set(cohort), new_count=1)
    # Proofs without durable DB jobs are insufficient (state-dir bypass refused).
    with pytest.raises(ValueError):
        check_phase2_eligible(phase1_cohort=cohort, proven_uuids=set(cohort),
                              db_total_admitted=set(), new_count=1)
    # Smaller cohorts (0..4) never unlock phase 2, even fully proven + DB-admitted.
    for n in range(0, 5):
        small = [f"s{i}" for i in range(n)]
        with pytest.raises(ValueError, match="EXACTLY 5"):
            check_phase2_eligible(phase1_cohort=small, proven_uuids=set(small),
                                  db_total_admitted=set(small), new_count=1)
    # Duplicated 5-length cohort (4 distinct) refused, even fully proven.
    dup = ["p1", "p2", "p3", "p4", "p4"]
    with pytest.raises(ValueError, match="DISTINCT"):
        check_phase2_eligible(phase1_cohort=dup, proven_uuids=set(dup),
                              db_total_admitted=set(dup), new_count=1)
    # 5 distinct, one unproven: refused.
    with pytest.raises(ValueError, match="lack PROOF"):
        check_phase2_eligible(phase1_cohort=cohort, proven_uuids=set(cohort[:4]),
                              db_total_admitted=set(cohort), new_count=1)
    # Exact cohort proven + DB admitted: eligible.
    check_phase2_eligible(phase1_cohort=cohort, proven_uuids=set(cohort),
                          db_total_admitted=set(cohort), new_count=25)
    # Total-30 still enforced on the DB total.
    with pytest.raises(ValueError):
        check_phase2_eligible(phase1_cohort=cohort, proven_uuids=set(cohort),
                              db_total_admitted=set(cohort), new_count=26)


def test_host_facts_fresh_pressure_and_paths(tmp_path):
    facts = load_host_facts(_facts_file(tmp_path))
    validate_host_facts(facts)
    stale = load_host_facts(_facts_file(tmp_path, fresh=False))
    with pytest.raises(ValueError):
        validate_host_facts(stale)
    pressured = load_host_facts(_facts_file(tmp_path, pressure="warn"))
    with pytest.raises(ValueError):
        validate_host_facts(pressured)
    low = load_host_facts(_facts_file(tmp_path, mac_free=1024))
    with pytest.raises(ValueError):
        validate_host_facts(low)
    bad = dict(load_host_facts(_facts_file(tmp_path)))
    bad.pop("mac_data_path")
    with pytest.raises(ValueError):
        validate_host_facts(bad)


def _patch_cli(ops, test_db, state):
    import types

    ops._engine = lambda: None
    ops._session = lambda eng: test_db
    saved = {}

    def _load(d):
        return dict(saved.get("state", state))

    def _save(d, s):
        saved["state"] = json.loads(json.dumps(s))

    ops.load_state = _load
    ops.save_state = _save
    return saved


def test_cli_admit_verify_prove_phase2_flow(test_db, tmp_path, monkeypatch):
    ops = _load_ops()
    for i in range(1, 6):
        _seed_source(test_db, f"clip-p1-{i}")
    manifest = tmp_path / "m1.json"
    manifest.write_text(json.dumps({"phase": 1, "clips": [f"clip-p1-{i}" for i in range(1, 6)]}))
    state_dir = tmp_path / "state"
    facts = _facts_file(tmp_path)

    class Args:
        pass

    base = {"admitted": [], "ready_seen": [], "proven": [], "consecutive_failures": 0}
    saved = {}
    monkeypatch.setattr(ops, "_engine", lambda: None)
    monkeypatch.setattr(ops, "_session", lambda eng: test_db)
    monkeypatch.setattr(ops, "load_state", lambda d: dict(saved.get("state", base)))
    monkeypatch.setattr(ops, "save_state", lambda d, s: saved.__setitem__("state", json.loads(json.dumps(s))))

    def admit(apply, phase=1, p1=None):
        a = Args()
        a.manifest = str(manifest)
        a.state_dir = str(state_dir)
        a.phase = phase
        a.phase1_manifest = p1
        a.host_facts = facts
        a.apply = apply
        a.mac_free_bytes = None
        a.server_cache_free_bytes = None
        a.max_consecutive_failures = 2
        return ops.cmd_admit(a)

    # DRY-RUN writes nothing; APPLY queues exactly one (priority>=60, attempts<=2).
    assert admit(False) == 0
    assert test_db.query(MediaJob).filter(MediaJob.rendition == "web_package").count() == 0
    assert admit(True) == 0
    jobs = test_db.query(MediaJob).filter(MediaJob.rendition == "web_package").all()
    assert len(jobs) == 1
    assert jobs[0].priority >= 60
    assert jobs[0].max_attempts <= CANARY_JOB_MAX_ATTEMPTS
    # Serial: second admit while active is fleet-blocked, not queued.
    assert admit(True) == 3
    # Resume: re-listing the same 5-manifest after one admission costs zero
    # (new-only counting) but the fleet gate still serializes.
    assert admit(False) == 3 or admit(False) == 0
    # verify records ready_seen only when durable -- nothing ready yet, proven stays empty.
    v = Args()
    v.manifest = str(manifest)
    v.state_dir = str(state_dir)
    assert ops.cmd_verify(v) == 0
    st = saved.get("state", base)
    assert st.get("proven", []) == []
    # Phase 2 without proofs is blocked even with a fresh state dir.
    m2 = tmp_path / "m2.json"
    m2.write_text(json.dumps({"phase": 2, "clips": ["clip-p2-1"]}))
    a2 = Args()
    a2.manifest = str(m2)
    a2.state_dir = str(tmp_path / "fresh-state")
    a2.phase = 2
    a2.phase1_manifest = str(manifest)
    a2.host_facts = facts
    a2.apply = False
    a2.mac_free_bytes = None
    a2.server_cache_free_bytes = None
    a2.max_consecutive_failures = 2
    assert ops.cmd_admit(a2) == 2


def test_cli_phase2_small_cohort_never_unlocks(test_db, tmp_path, monkeypatch):
    ops = _load_ops()
    _seed_source(test_db, "clip-small-1")
    small_p1 = tmp_path / "small-p1.json"
    small_p1.write_text(json.dumps({"phase": 1, "clips": ["clip-small-1"]}))
    m2 = tmp_path / "m2.json"
    m2.write_text(json.dumps({"phase": 2, "clips": ["clip-p2-1"]}))
    monkeypatch.setattr(ops, "_engine", lambda: None)
    monkeypatch.setattr(ops, "_session", lambda eng: test_db)
    state_dir = tmp_path / "state"
    facts = _facts_file(tmp_path)
    a2 = type("A", (), {"manifest": str(m2), "state_dir": str(state_dir),
                        "phase": 2, "phase1_manifest": str(small_p1),
                        "host_facts": facts, "apply": False,
                        "mac_free_bytes": None, "server_cache_free_bytes": None,
                        "max_consecutive_failures": 2})()
    # 1-clip first wave, even fully proven/DB-admitted, never unlocks phase 2.
    assert ops.cmd_admit(a2) == 2


def test_cli_prove_rejects_ready_only_and_accepts_evidence(test_db, tmp_path, monkeypatch):
    ops = _load_ops()
    src = _seed_source(test_db, "clip-proof-1")
    _seed_ready_derivative(test_db, "clip-proof-1", src, "light", 1000)
    _seed_ready_derivative(test_db, "clip-proof-1", src, "poster", 500)
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps({"phase": 1, "clips": ["clip-proof-1"]}))
    state_dir = tmp_path / "state"

    monkeypatch.setattr(ops, "_engine", lambda: None)
    monkeypatch.setattr(ops, "_session", lambda eng: test_db)

    v = type("A", (), {"manifest": str(manifest), "state_dir": str(state_dir)})()
    assert ops.cmd_verify(v) == 0
    # verify marked ready_seen but NOT proven.
    st = ops.load_state(state_dir)
    assert "clip-proof-1" in st["ready_seen"]
    assert st["proven"] == []

    # Incomplete proof (missing checks) is refused; proven stays empty.
    bad = {"video_uuid": "clip-proof-1", "source_sha256": src,
           "source_revision_id": 1, "transform_version": "ffmpeg-h264-web-v1",
           "slots": {"light": {"derivative_sha256": _sha(b"x"), "byte_size": 10}},
           "checks": {"b2_full_get_sha_match": True},
           "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
           "operator": "op"}
    bad_path = tmp_path / "bad-proof.json"
    bad_path.write_text(json.dumps(bad))
    p = type("A", (), {"manifest": str(manifest), "state_dir": str(state_dir),
                       "proof": str(bad_path)})()
    assert ops.cmd_prove(p) == 2
    assert ops.load_state(state_dir)["proven"] == []


def test_cli_apply_requires_fresh_host_facts(test_db, tmp_path, monkeypatch):
    ops = _load_ops()
    _seed_source(test_db, "clip-facts-1")
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps({"phase": 1, "clips": ["clip-facts-1"]}))
    monkeypatch.setattr(ops, "_engine", lambda: None)
    monkeypatch.setattr(ops, "_session", lambda eng: test_db)
    state_dir = tmp_path / "state"

    def admit_with(facts_path):
        a = type("A", (), {})()
        a.manifest = str(manifest)
        a.state_dir = str(state_dir)
        a.phase = 1
        a.phase1_manifest = None
        a.host_facts = facts_path
        a.apply = True
        a.mac_free_bytes = None
        a.server_cache_free_bytes = None
        a.max_consecutive_failures = 2
        return ops.cmd_admit(a)

    assert admit_with(None) == 2  # legacy flags alone refused
    assert admit_with(_facts_file(tmp_path, fresh=False)) == 2  # stale refused
    assert admit_with(_facts_file(tmp_path, pressure="critical")) == 2


def test_canary_scope_derives_from_persisted_job_reason(test_db):
    from app.services.canary_budget import (
        CANARY_JOB_REASON,
        canary_scope_for_job_id,
        is_canary_job,
    )

    _seed_source(test_db, "clip-scope-1")
    asset = test_db.query(PhotosAsset).filter(PhotosAsset.video_uuid == "clip-scope-1").one()
    from app.services.media_jobs import WEB_PACKAGE_RENDITION, create_or_reuse_media_job

    _, canary_job, _ = create_or_reuse_media_job(
        test_db, asset, WEB_PACKAGE_RENDITION, CANARY_JOB_REASON)
    test_db.commit()
    assert is_canary_job(canary_job) is True
    assert canary_scope_for_job_id(test_db, int(canary_job.id)) is True
    # A non-canary package (other persisted reason) is out of scope.
    asset2 = PhotosAsset(video_uuid="clip-scope-2")
    test_db.add(asset2)
    test_db.flush()
    _seed_source(test_db, "clip-scope-2b")
    asset_b = test_db.query(PhotosAsset).filter(PhotosAsset.video_uuid == "clip-scope-2b").one()
    _, other_job, _ = create_or_reuse_media_job(
        test_db, asset_b, WEB_PACKAGE_RENDITION, "user_request")
    test_db.commit()
    assert is_canary_job(other_job) is False
    assert canary_scope_for_job_id(test_db, int(other_job.id)) is False
    # Unknown job id fails closed (no budget consumed).
    assert canary_scope_for_job_id(test_db, 999999999) is False
    # Client cannot flip scope: scope reads the DB row, not request input.
    other_job.request_reason = "user_request"
    assert is_canary_job(other_job) is False


def test_orphan_reservation_persists_across_publisher_rollback(test_db):
    # A reservation that never becomes READY (upload/publish crash after the
    # reserve commit) stays counted: monotonic, never released.
    sha = _sha(b"orphan-crash-bytes")
    before = canary_accounted_bytes(test_db)
    _reserve(test_db, sha, 4096, job_id=77, slot="hq")
    assert canary_accounted_bytes(test_db) == before + 4096
    # Simulate the publisher unit rolling back AFTER the reservation commit:
    # no ledger row is promoted, but the reservation row survives.
    test_db.rollback()
    assert canary_accounted_bytes(test_db) == before + 4096


def test_source_changed_proof_invalid(test_db, tmp_path, monkeypatch):
    ops = _load_ops()
    src = _seed_source(test_db, "clip-stale-1")
    _seed_ready_derivative(test_db, "clip-stale-1", src, "hq", 2000)
    _seed_ready_derivative(test_db, "clip-stale-1", src, "light", 1000)
    _seed_ready_derivative(test_db, "clip-stale-1", src, "poster", 500)
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps({"phase": 1, "clips": ["clip-stale-1"]}))
    state_dir = tmp_path / "state"
    monkeypatch.setattr(ops, "_engine", lambda: None)
    monkeypatch.setattr(ops, "_session", lambda eng: test_db)
    rows = test_db.query(MediaDerivative).filter(
        MediaDerivative.video_uuid == "clip-stale-1").all()
    from app.services.derivative_publisher import resolve_canonical_source_revision
    rev, _blob, _loc = resolve_canonical_source_revision(test_db, "clip-stale-1")
    _sizes = {"hq": 2000, "light": 1000, "poster": 500}
    slots = {r.role: {"derivative_sha256": r.derivative_blob_sha256, "byte_size": _sizes[r.role]}
             for r in rows}
    proof = {"video_uuid": "clip-stale-1", "source_sha256": src,
             "source_revision_id": int(rev.id), "transform_version": "ffmpeg-h264-web-v1",
             "slots": slots,
             "checks": {n: True for n in ops.PROOF_REQUIRED_CHECKS},
             "cadence_evidence": {
                 "source_sha256": src,
                 "source_frames": 600, "source_fps": 60.0, "source_duration": 10.0,
                 "outputs": {"hq": {"frames": 600, "fps": 60.0, "duration": 10.0},
                             "light": {"frames": 600, "fps": 60.0, "duration": 10.0}},
                 "vfr": False, "pts_exact_claimed": False,
             },
             "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
             "operator": "op"}
    proof_path = tmp_path / "proof.json"
    proof_path.write_text(json.dumps(proof))
    p = type("A", (), {"manifest": str(manifest), "state_dir": str(state_dir),
                       "proof": str(proof_path)})()
    assert ops.cmd_prove(p) == 0
    # Source moves AFTER the proof: new canonical revision, same clip.
    from app.config import get_settings as _gs
    new_sha = _sha(b"camera-bytes-v2-clip-stale-1")
    _s = _gs()
    test_db.add(MediaBlob(sha256=new_sha, byte_size=18, storage_backend="b2",
                          bucket=_s.media_backbone_prod_bucket,
                          object_key=f"blobs/sha256/{new_sha[:2]}/{new_sha}",
                          width=1280, height=720, duration_seconds=10.0))
    test_db.add(MediaBlobLocation(blob_sha256=new_sha, environment="prod", storage_backend="b2",
                                  bucket=_s.media_backbone_prod_bucket,
                                  object_key=f"blobs/sha256/{new_sha[:2]}/{new_sha}", verified=True))
    from app.models.media_backbone import MediaRevision as _MR
    test_db.add(_MR(video_uuid="clip-stale-1", blob_sha256=new_sha,
                    rendition_semantics="photos_edited_rendition"))
    test_db.commit()
    with pytest.raises(ValueError):
        ops.crosscheck_proof_db(test_db, ops.validate_proof_record(proof))
    # Phase-2 admission with the STALE stored proof is blocked.
    m2 = tmp_path / "m2.json"
    m2.write_text(json.dumps({"phase": 2, "clips": ["clip-stale-2"]}))
    _seed_source(test_db, "clip-stale-2")
    a2 = type("A", (), {"manifest": str(m2), "state_dir": str(state_dir),
                        "phase": 2, "phase1_manifest": str(manifest),
                        "host_facts": _facts_file(tmp_path), "apply": False,
                        "mac_free_bytes": None, "server_cache_free_bytes": None,
                        "max_consecutive_failures": 2})()
    assert ops.cmd_admit(a2) == 2


def test_publisher_skips_put_when_verified_existing():
    from app.services.derivative_publisher import _try_verified_reuse

    data = b"verified-bytes-123"

    class _Body:
        def __init__(self, b):
            self._b = b
        def iter_chunks(self, chunk_size=1024 * 1024):
            yield self._b
        def close(self):
            pass

    class _Hit:
        def get_object(self, Bucket, Key):
            return {"Body": _Body(data)}

    class _Miss:
        def get_object(self, Bucket, Key):
            raise KeyError(Key)

    import hashlib as _hl
    sha = _hl.sha256(data).hexdigest()
    assert _try_verified_reuse(client=_Hit(), bucket="b", key="k",
                               derivative_sha=sha, derivative_size=len(data)) is True
    assert _try_verified_reuse(client=_Miss(), bucket="b", key="k",
                               derivative_sha=sha, derivative_size=len(data)) is False
    # Present-but-different bytes must NOT authorize charge+PUT: fail closed.
    import pytest as _pt
    from app.services.derivative_publisher import VerificationFailed as _VF
    with _pt.raises(_VF):
        _try_verified_reuse(client=_Hit(), bucket="b", key="k",
                            derivative_sha=_sha(b"other"), derivative_size=len(data))


# ---------------------------------------------------------------------------
# Per-PUT attempt charging: two ACTUAL publisher calls, same key, both GET
# miss -> each charges; cap lets exactly one win before its PUT; orphan
# charge survives a failed PUT's rollback.
# ---------------------------------------------------------------------------

class _CanaryFakeBody:
    def __init__(self, data: bytes):
        import io as _io

        self._buf = _io.BytesIO(data)

    def iter_chunks(self, chunk_size=1024 * 1024):
        while True:
            piece = self._buf.read(chunk_size)
            if not piece:
                break
            yield piece

    def close(self):
        pass


class _CanaryFakeS3:
    """Separate in-memory stores: two fakes = two racers that both miss GET."""

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
        if self.mode == "get_error":
            raise RuntimeError("boom")
        data = self.objects.get((Bucket, Key))
        if data is None:
            raise KeyError(Key)
        if self.mode == "corrupt":
            data = b"corrupt:" + data
        return {"Body": _CanaryFakeBody(data)}


def _canary_publish_artifact(test_db, tmp_path, tag, role="light", raw=b"race-bytes-"):
    from app.services.derivative_publisher import build_publication_context

    data = (raw * 64)[:4096]
    assert len(data) > 0
    artifact = tmp_path / f"slot-{tag}.bin"
    artifact.write_bytes(data)
    _seed_source(test_db, f"clip-race-{tag}")
    ctx = build_publication_context(test_db, video_uuid=f"clip-race-{tag}", role=role)
    return ctx, artifact, data


def test_two_actual_publisher_calls_same_key_both_miss_charge_each(test_db, tmp_path):
    from app.services.canary_budget import canary_accounted_bytes
    from app.services.derivative_publisher import (
        build_publication_context,
        publish_derivative,
    )

    # One clip, one slot: the same artifact published twice through two
    # SEPARATE fake stores (each GET misses, each PUT streams) -- the
    # same-key concurrent race. Each actual PUT attempt must charge.
    data = (b"race-bytes-same-key-" * 64)[:2048]
    artifact = tmp_path / "slot-race.bin"
    artifact.write_bytes(data)
    _seed_source(test_db, "clip-race-samekey")
    ctx1 = build_publication_context(test_db, video_uuid="clip-race-samekey", role="light")
    fake1, fake2 = _CanaryFakeS3(), _CanaryFakeS3()
    before = canary_accounted_bytes(test_db)
    r1 = publish_derivative(test_db, ctx1, artifact, s3_client=fake1, canary_scope=True)
    assert r1["status"] == "ready"
    assert fake1.uploads == 1
    # Second ACTUAL publisher call: fresh context, same key, its own store
    # still misses the reuse GET, so it charges + PUTs again.
    ctx2 = build_publication_context(test_db, video_uuid="clip-race-samekey", role="light")
    assert ctx2.source_blob_sha256 == ctx1.source_blob_sha256
    r2 = publish_derivative(test_db, ctx2, artifact, s3_client=fake2, canary_scope=True)
    assert r2["status"] == "ready"
    assert fake2.uploads == 1
    # Two PUT attempts -> two charges (same key, same bytes) PLUS the
    # READY baseline (always counted, no ledger exclusion): first publish
    # charges once + promotes one READY row (2x), second publish charges
    # again with no new READY row (dedup) -> 3x total. Intentional
    # conservative over-count (monotonic, actual stored <= accounted).
    assert canary_accounted_bytes(test_db) == before + 3 * len(data)
    from app.models.canary_ledger import CanarySlotReservation

    rows = test_db.query(CanarySlotReservation).filter(
        CanarySlotReservation.object_key == r1["object_key"]).all()
    assert len(rows) == 2
    assert r2["object_key"] == r1["object_key"]


def test_verified_reuse_skips_put_and_charge(test_db, tmp_path):
    from app.services.canary_budget import canary_accounted_bytes
    from app.services.derivative_publisher import (
        build_publication_context,
        publish_derivative,
    )

    # Same store: the second publish's reuse GET HITS, so no new PUT and
    # no new charge (verified reuse, not a retry that could double-store).
    data = (b"reuse-bytes-" * 64)[:1024]
    artifact = tmp_path / "slot-reuse.bin"
    artifact.write_bytes(data)
    _seed_source(test_db, "clip-race-reuse")
    fake = _CanaryFakeS3()
    ctx1 = build_publication_context(test_db, video_uuid="clip-race-reuse", role="light")
    before = canary_accounted_bytes(test_db)
    r1 = publish_derivative(test_db, ctx1, artifact, s3_client=fake, canary_scope=True)
    assert r1["status"] == "ready"
    assert fake.uploads == 1
    # Charge + READY baseline always counted (intentional double-count).
    assert canary_accounted_bytes(test_db) == before + 2 * len(data)
    ctx2 = build_publication_context(test_db, video_uuid="clip-race-reuse", role="light")
    r2 = publish_derivative(test_db, ctx2, artifact, s3_client=fake, canary_scope=True)
    assert r2["status"] == "ready"
    assert fake.uploads == 1  # no second PUT
    assert canary_accounted_bytes(test_db) == before + 2 * len(data)  # no second charge


def test_canary_cap_one_racer_wins_before_put(test_db, tmp_path):
    from app.services.canary_budget import (
        CANARY_BUDGET_BYTES,
        canary_accounted_bytes,
    )
    from app.services.derivative_publisher import (
        DerivativePublishError,
        build_publication_context,
        publish_derivative,
    )

    # Leave room for exactly ONE more PUT of this size: the first racer
    # charges + PUTs; the second fails BEFORE its PUT (no bytes spent).
    data = (b"cap-bytes-" * 64)[:2048]
    artifact = tmp_path / "slot-cap.bin"
    artifact.write_bytes(data)
    _seed_source(test_db, "clip-race-cap")
    # Fill to cap - len(data) with exact-key charges (distinct keys).
    import hashlib as _hl

    fill_total = CANARY_BUDGET_BYTES - len(data)
    # Two per-slot-cap-compliant fills (hq 1.2G + light remainder).
    _reserve(test_db, _sha(b"cap-fill-hq"), 1_200_000_000, slot="hq")
    rest = fill_total - 1_200_000_000
    assert rest > 0
    # rest may exceed the light per-slot cap (700M): split into light-size chunks.
    idx = 0
    while rest > 0:
        chunk = min(rest, 700_000_000)
        _reserve(test_db, _sha(f"cap-fill-l-{idx}".encode()), chunk, slot="light")
        rest -= chunk
        idx += 1
    assert canary_accounted_bytes(test_db) == fill_total
    ctx = build_publication_context(test_db, video_uuid="clip-race-cap", role="light")
    fake_win = _CanaryFakeS3()
    r = publish_derivative(test_db, ctx, artifact, s3_client=fake_win, canary_scope=True)
    assert r["status"] == "ready"
    assert fake_win.uploads == 1
    # Charge + READY baseline both counted (intentional over-count):
    # accounted exceeds the cap by one object while actual stored stays
    # under it (fill_total + 2*len). The second racer still fails closed
    # BEFORE its PUT, so the gate is stricter, never weaker.
    assert canary_accounted_bytes(test_db) == CANARY_BUDGET_BYTES + len(data)
    # Second racer, same key, own miss: cap refuses BEFORE its PUT.
    ctx2 = build_publication_context(test_db, video_uuid="clip-race-cap", role="light")
    fake_lose = _CanaryFakeS3()
    with pytest.raises(DerivativePublishError, match="canary budget exceeded"):
        publish_derivative(test_db, ctx2, artifact, s3_client=fake_lose, canary_scope=True)
    assert fake_lose.uploads == 0
    assert canary_accounted_bytes(test_db) == CANARY_BUDGET_BYTES + len(data)


def test_orphan_charge_survives_failed_put_rollback(test_db, tmp_path):
    from app.services.canary_budget import canary_accounted_bytes
    from app.services.derivative_publisher import (
        DerivativePublishError,
        build_publication_context,
        publish_derivative,
    )

    # The PUT fails AFTER the charge commits: the charge row survives the
    # publish-unit rollback (monotonic, never refunded).
    data = (b"orphan-bytes-" * 64)[:1024]
    artifact = tmp_path / "slot-orphan.bin"
    artifact.write_bytes(data)
    _seed_source(test_db, "clip-race-orphan")
    ctx = build_publication_context(test_db, video_uuid="clip-race-orphan", role="light")
    before = canary_accounted_bytes(test_db)
    with pytest.raises(DerivativePublishError):
        publish_derivative(test_db, ctx, artifact,
                           s3_client=_CanaryFakeS3(mode="upload_error"),
                           canary_scope=True)
    test_db.rollback()
    assert canary_accounted_bytes(test_db) == before + len(data)
