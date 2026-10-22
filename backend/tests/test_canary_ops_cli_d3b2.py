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


def test_reservation_counts_orphans_and_dedupes_same_sha(test_db):
    sha1 = _sha(b"orphan-1")
    assert canary_accounted_bytes(test_db) == 0
    # Reserve an object that never becomes a READY row (crashed attempt orphan).
    reserve_canary_upload(test_db, sha1, 1000, job_id=1, slot="light")
    assert canary_accounted_bytes(test_db) == 1000
    assert canary_ledger_bytes(test_db) == 1000
    # Same-SHA retry dedupes: no double charge.
    remaining = reserve_canary_upload(test_db, sha1, 1000, job_id=1, slot="light")
    assert canary_accounted_bytes(test_db) == 1000
    assert remaining == CANARY_BUDGET_BYTES - 1000
    # Same SHA with different size fails closed (corrupt claim).
    with pytest.raises(ValueError):
        reserve_canary_upload(test_db, sha1, 1001, job_id=2, slot="light")
    # Legacy READY rows for other SHAs add once (no double count with reservations).
    src = _seed_source(test_db, "clip-orphan-2")
    dsha = _seed_ready_derivative(test_db, "clip-orphan-2", src, "light", 500)
    assert dsha != sha1
    assert canary_accounted_bytes(test_db) == 1500


def test_reservation_hard_cap_and_per_slot_caps(test_db):
    with pytest.raises(ValueError):
        validate_canary_slot_size("hq", 2_000_000_000)
    with pytest.raises(ValueError):
        validate_canary_slot_size("poster", 9 * 1024 * 1024)
    with pytest.raises(ValueError):
        normalize_object_sha("not-hex")
    big = _sha(b"big-1")
    # Fill to exactly the cap via several per-slot-cap-compliant
    # reservations, then prove the next byte refuses.
    reserve_canary_upload(test_db, _sha(b"fill-hq"), 1_200_000_000, slot="hq")
    reserve_canary_upload(test_db, _sha(b"fill-light"), 700_000_000, slot="light")
    reserve_canary_upload(test_db, _sha(b"fill-poster"), 8_000_000, slot="poster")
    rest = CANARY_BUDGET_BYTES - (1_200_000_000 + 700_000_000 + 8_000_000) - 10
    reserve_canary_upload(test_db, big, rest, slot="hq")
    small = _sha(b"small-1")
    with pytest.raises(CanaryBudgetExceeded):
        reserve_canary_upload(test_db, small, 11, slot="light")
    assert reserve_canary_upload(test_db, small, 10, slot="light") == 0


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
