"""PR145 bot 6330849970 (run 39708380326) - DB-authoritative phase caps.

The phase caps unioned the local state file with the DB cohort, but the
candidate loop could still queue a state-only UUID. With 30 DB-admitted
clips and a stale state file listing a new candidate as admitted,
``new_ids`` was empty (cap passed) yet ``clip_readiness`` saw no DB job
and queued clip 31. Fix: DB is the ONLY authority for admitted totals,
NEW-unique counting and idempotency. A state-only UUID NEVER discounts a
candidate (counts as NEW) unless the DB confirms a job row. Orphan hints
are ignored for the gate and reconciled (dropped) on the successful queue
commit. Cohort counts only canary jobs (request_reason), never unrelated
global web_package jobs.

Covers:
- phase-1 DB 5 + state-hint 6th (no DB job) -> REFUSE 2, no queue.
- phase-2 DB 30 + state-hint 31st (no DB job) -> REFUSE 2, no queue.
- stale hint with capacity -> allowed, counted NEW (not deduped), reconciled.
- real DB resume (re-list admitted) -> idempotent 0, no extra queue.
- state reset (empty) cannot bypass DB totals.
- canary-reason cohort: unrelated web_package jobs never count.
- exact-5 distinct phase-1 fresh proof still required for phase 2.
"""

import datetime
import hashlib
import importlib.util
import json
from pathlib import Path

from app.models.media import MediaJob
from app.models.photos_asset import PhotosAsset

CLI = Path(__file__).resolve().parents[2] / "ops" / "canary_web_package.py"


def _load(p, name):
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _seed_source(db, video_uuid, raw=b"camera-bytes-v1", width=1280, height=720, duration=10.0):
    from app.config import get_settings
    from app.models.media_backbone import MediaBlob, MediaBlobLocation, MediaRevision

    sha = _sha(raw + video_uuid.encode())
    db.add(PhotosAsset(video_uuid=video_uuid))
    db.flush()
    s = get_settings()
    db.add(MediaBlob(sha256=sha, byte_size=len(raw), storage_backend="b2",
                     bucket=s.media_backbone_prod_bucket,
                     object_key=f"blobs/sha256/{sha[:2]}/{sha}",
                     width=width, height=height, duration_seconds=duration))
    db.add(MediaBlobLocation(blob_sha256=sha, environment="prod", storage_backend="b2",
                             bucket=s.media_backbone_prod_bucket,
                             object_key=f"blobs/sha256/{sha[:2]}/{sha}", verified=True))
    db.add(MediaRevision(video_uuid=video_uuid, blob_sha256=sha,
                         rendition_semantics="photos_edited_rendition"))
    db.commit()
    return sha


def _seed_ready_derivative(db, video_uuid, source_sha, role, nbytes):
    from app.config import get_settings
    from app.models.media_backbone import MediaBlob, MediaBlobLocation, MediaDerivative, MediaRevision

    dsha = _sha(f"{video_uuid}{role}".encode())
    s = get_settings()
    db.add(MediaBlob(sha256=dsha, byte_size=nbytes, storage_backend="b2",
                     bucket=s.media_backbone_prod_bucket,
                     object_key=f"blobs/sha256/{dsha[:2]}/{dsha}"))
    db.add(MediaBlobLocation(blob_sha256=dsha, environment="prod", storage_backend="b2",
                             bucket=s.media_backbone_prod_bucket,
                             object_key=f"blobs/sha256/{dsha[:2]}/{dsha}", verified=True))
    db.add(MediaRevision(video_uuid=video_uuid, blob_sha256=dsha,
                         rendition_semantics=f"derived_{role}"))
    db.add(MediaDerivative(video_uuid=video_uuid, source_blob_sha256=source_sha,
                           role=role, transform_version="ffmpeg-h264-web-v1",
                           derivative_blob_sha256=dsha, status="ready"))
    db.commit()
    return dsha


_CTR = {"n": 0}


def _ctr():
    _CTR["n"] += 1
    return _CTR["n"]


def _mk_canary_job(db, video_uuid, status, reason="canary_web_package"):
    from app.services.media_jobs import WEB_PACKAGE_RENDITION

    asset = db.query(PhotosAsset).filter(PhotosAsset.video_uuid == video_uuid).first()
    if asset is None:
        asset = PhotosAsset(video_uuid=video_uuid)
        db.add(asset)
        db.flush()
    job = MediaJob(photos_asset_id=asset.id, media_key=f"mk-{video_uuid}-{status}-{_ctr()}",
                   rendition=WEB_PACKAGE_RENDITION, status=status,
                   request_reason=reason, priority=60,
                   attempts=1 if status in ("failed", "unavailable") else 0, max_attempts=2)
    db.add(job)
    db.commit()
    return job


def _facts(tmp_path, fresh=True, pressure="normal"):
    import datetime as _dt

    now = _dt.datetime.now(_dt.timezone.utc)
    if not fresh:
        now = now - _dt.timedelta(minutes=30)
    p = tmp_path / "host-facts.json"
    p.write_text(json.dumps({
        "mac_free_bytes": 9 * 1024**3, "server_cache_free_bytes": 30 * 1024**3,
        "mac_memory_pressure": pressure, "checked_at": now.isoformat(),
        "mac_data_path": "/Users/Shared/services/data/diveanalyzer",
        "server_cache_path": "/var/lib/diveanalyzer/cache",
    }))
    return str(p)


def _admit(ops, test_db, manifest, state_dir, facts, phase=1, p1=None, maxfail=2, apply=False):
    a = type("A", (), {})()
    a.manifest = str(manifest)
    a.state_dir = str(state_dir)
    a.phase = phase
    a.phase1_manifest = p1
    a.host_facts = facts
    a.apply = apply
    a.mac_free_bytes = None
    a.server_cache_free_bytes = None
    a.max_consecutive_failures = maxfail
    return ops.cmd_admit(a)


def _prove_phase1_clip(ops, test_db, tmp_path, state_dir, manifest_path, uuid, src):
    from app.models.media_backbone import MediaDerivative

    rows = test_db.query(MediaDerivative).filter(MediaDerivative.video_uuid == uuid).all()
    sizes = {"hq": 2000, "light": 1000, "poster": 500}
    slots = {r.role: {"derivative_sha256": r.derivative_blob_sha256,
                      "byte_size": sizes[r.role]} for r in rows}
    from app.services.derivative_publisher import resolve_canonical_source_revision
    rev, _b, _l = resolve_canonical_source_revision(test_db, uuid)
    proof = {"video_uuid": uuid, "source_sha256": src,
             "source_revision_id": int(rev.id), "transform_version": "ffmpeg-h264-web-v1",
             "slots": slots,
             "checks": {n: True for n in ops.PROOF_REQUIRED_CHECKS},
             "cadence_evidence": {
                 "source_sha256": src, "source_frames": 600, "source_fps": 60.0,
                 "source_duration": 10.0,
                 "outputs": {"hq": {"frames": 600, "fps": 60.0, "duration": 10.0},
                             "light": {"frames": 600, "fps": 60.0, "duration": 10.0}},
                 "vfr": False, "pts_exact_claimed": False},
             "source_integrity_evidence": {
                 "sha": src, "size": len(b"camera-bytes-v1"),
                 "measured_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                 "method": "full_get_after_publication"},
             "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
             "operator": "op"}
    pp = tmp_path / f"proof-{uuid}.json"
    pp.write_text(json.dumps(proof))
    pv = type("A", (), {"manifest": str(manifest_path),
                        "state_dir": str(state_dir),
                        "proof": str(pp)})()
    assert ops.cmd_prove(pv) == 0


def _canary_count(db):
    from app.services.media_jobs import WEB_PACKAGE_RENDITION
    return db.query(MediaJob).filter(
        MediaJob.rendition == WEB_PACKAGE_RENDITION,
        MediaJob.request_reason == "canary_web_package",
    ).count()


def test_phase1_db5_state_hint_6th_refuses(test_db, tmp_path, monkeypatch):
    """DB has 5 canary jobs; state hints a 6th with no DB job -> REFUSE, no queue."""
    ops = _load(CLI, "cli_dbcap_p1")
    monkeypatch.setattr(ops, "_engine", lambda: None)
    monkeypatch.setattr(ops, "_session", lambda eng: test_db)
    for i in range(1, 6):
        _seed_source(test_db, f"clip-db5-{i}")
        _mk_canary_job(test_db, f"clip-db5-{i}", "ready")
    _seed_source(test_db, "clip-db5-6")
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"phase": 1, "clips": ["clip-db5-6"]}))
    facts = _facts(tmp_path)
    state_dir = tmp_path / "state-db5"
    state_dir.mkdir(parents=True, exist_ok=True)
    # Stale hint: local file claims the 6th is already admitted (no DB job).
    (state_dir / "canary-state.json").write_text(json.dumps({
        "admitted": ["clip-db5-6"], "ready_seen": [], "proven": [],
        "consecutive_failures": 0}))
    import os
    try:
        os.chmod(state_dir / "canary-state.json", 0o600)
    except OSError:
        pass
    before = _canary_count(test_db)
    assert before == 5
    rc = _admit(ops, test_db, m, state_dir, facts, apply=True)
    assert rc == 2
    assert _canary_count(test_db) == before


def test_phase2_db30_state_hint_31st_refuses(test_db, tmp_path, monkeypatch):
    """DB has 30 canary jobs; state hints a 31st with no DB job -> REFUSE."""
    ops = _load(CLI, "cli_dbcap_p2")
    monkeypatch.setattr(ops, "_engine", lambda: None)
    monkeypatch.setattr(ops, "_session", lambda eng: test_db)
    p1 = [f"clip-h31-p1-{i}" for i in range(1, 6)]
    p1m = tmp_path / "p1.json"
    p1m.write_text(json.dumps({"phase": 1, "clips": p1}))
    state_dir = tmp_path / "state-h31"
    for uuid in p1:
        src = _seed_source(test_db, uuid)
        _seed_ready_derivative(test_db, uuid, src, "hq", 2000)
        _seed_ready_derivative(test_db, uuid, src, "light", 1000)
        _seed_ready_derivative(test_db, uuid, src, "poster", 500)
        _mk_canary_job(test_db, uuid, "ready")
    for uuid in p1:
        from app.services.derivative_publisher import resolve_canonical_source_revision
        rev, _, _ = resolve_canonical_source_revision(test_db, uuid)
        _prove_phase1_clip(ops, test_db, tmp_path, state_dir, p1m, uuid,
                           str(rev.blob_sha256).lower())
    for i in range(25):
        uuid = f"clip-h31-fill-{i}"
        _seed_source(test_db, uuid)
        _mk_canary_job(test_db, uuid, "ready")
    from app.services.canary_budget import db_admitted_uuids
    assert len(db_admitted_uuids(test_db)) == 30
    _seed_source(test_db, "clip-h31-31")
    # Stale hint lists the 31st as admitted (no DB job for it).
    st = json.loads((state_dir / "canary-state.json").read_text())
    st["admitted"] = sorted(set(st.get("admitted", [])) | {"clip-h31-31"})
    (state_dir / "canary-state.json").write_text(json.dumps(st))
    m2 = tmp_path / "m2.json"
    m2.write_text(json.dumps({"phase": 2, "clips": ["clip-h31-31"]}))
    facts = _facts(tmp_path)
    before = _canary_count(test_db)
    rc = _admit(ops, test_db, m2, state_dir, facts, phase=2, p1=str(p1m), apply=True)
    assert rc == 2
    assert _canary_count(test_db) == before


def test_stale_hint_with_capacity_counts_new_and_reconciles(test_db, tmp_path, monkeypatch):
    """Orphan hint with headroom: admitted as NEW (not deduped), state reconciled."""
    ops = _load(CLI, "cli_dbcap_stale_ok")
    monkeypatch.setattr(ops, "_engine", lambda: None)
    monkeypatch.setattr(ops, "_session", lambda eng: test_db)
    for i in (1, 2):
        _seed_source(test_db, f"clip-stale-{i}")
        _mk_canary_job(test_db, f"clip-stale-{i}", "ready")
    _seed_source(test_db, "clip-stale-3")
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"phase": 1, "clips": ["clip-stale-3"]}))
    facts = _facts(tmp_path)
    state_dir = tmp_path / "state-stale"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "canary-state.json").write_text(json.dumps({
        "admitted": ["clip-stale-3", "clip-stale-orphan"], "ready_seen": [],
        "proven": [], "consecutive_failures": 0}))
    import os
    try:
        os.chmod(state_dir / "canary-state.json", 0o600)
    except OSError:
        pass
    before = _canary_count(test_db)
    rc = _admit(ops, test_db, m, state_dir, facts, apply=True)
    assert rc == 0
    assert _canary_count(test_db) == before + 1
    st = json.loads((state_dir / "canary-state.json").read_text())
    # Reconciled: DB cohort + new UUID, orphan hint dropped.
    assert "clip-stale-orphan" not in set(st.get("admitted", []))
    assert "clip-stale-3" in set(st.get("admitted", []))


def test_db_resume_idempotent_and_reset_cannot_bypass(test_db, tmp_path, monkeypatch):
    """Re-listing DB-admitted clips costs zero; wiping state never bypasses caps."""
    ops = _load(CLI, "cli_dbcap_resume")
    monkeypatch.setattr(ops, "_engine", lambda: None)
    monkeypatch.setattr(ops, "_session", lambda eng: test_db)
    for i in range(1, 6):
        uuid = f"clip-rs-{i}"
        src = _seed_source(test_db, uuid)
        _seed_ready_derivative(test_db, uuid, src, "hq", 2000)
        _seed_ready_derivative(test_db, uuid, src, "light", 1000)
        _seed_ready_derivative(test_db, uuid, src, "poster", 500)
        _mk_canary_job(test_db, uuid, "ready")
    m = tmp_path / "m.json"
    clips = [f"clip-rs-{i}" for i in range(1, 6)]
    m.write_text(json.dumps({"phase": 1, "clips": clips}))
    facts = _facts(tmp_path)
    state_dir = tmp_path / "state-rs"
    before = _canary_count(test_db)
    # Resume: all 5 already in DB -> nothing to queue, exit 0.
    assert _admit(ops, test_db, m, state_dir, facts, apply=True) == 0
    assert _canary_count(test_db) == before
    # Reset: fresh empty state dir still sees DB 5 -> 6th refused.
    _seed_source(test_db, "clip-rs-6")
    m6 = tmp_path / "m6.json"
    m6.write_text(json.dumps({"phase": 1, "clips": ["clip-rs-6"]}))
    fresh = tmp_path / "fresh-state"
    assert _admit(ops, test_db, m6, fresh, facts, apply=True) == 2
    assert _canary_count(test_db) == before


def test_cohort_counts_only_canary_reason(test_db, tmp_path, monkeypatch):
    """Unrelated global web_package jobs never count toward the canary cohort."""
    ops = _load(CLI, "cli_dbcap_reason")
    monkeypatch.setattr(ops, "_engine", lambda: None)
    monkeypatch.setattr(ops, "_session", lambda eng: test_db)
    from app.services.canary_budget import db_admitted_uuids
    for i in range(3):
        _seed_source(test_db, f"clip-nc-{i}")
        _mk_canary_job(test_db, f"clip-nc-{i}", "ready", reason="nightly_package")
    assert len(db_admitted_uuids(test_db)) == 0
    # 5 non-canary + 0 canary: phase-1 canary admission still has headroom.
    _seed_source(test_db, "clip-canary-new")
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"phase": 1, "clips": ["clip-canary-new"]}))
    facts = _facts(tmp_path)
    state_dir = tmp_path / "state-reason"
    assert _admit(ops, test_db, m, state_dir, facts, apply=True) == 0
    assert len(db_admitted_uuids(test_db)) == 1


def test_phase2_still_requires_exact5_fresh_proof(test_db, tmp_path, monkeypatch):
    """Exact-5 distinct phase-1 fresh proof gate unchanged (smaller wave refused)."""
    ops = _load(CLI, "cli_dbcap_exact5")
    monkeypatch.setattr(ops, "_engine", lambda: None)
    monkeypatch.setattr(ops, "_session", lambda eng: test_db)
    small = ["clip-ex5-1", "clip-ex5-2"]
    small_m = tmp_path / "small.json"
    small_m.write_text(json.dumps({"phase": 1, "clips": small}))
    state_dir = tmp_path / "state-ex5"
    for uuid in small:
        src = _seed_source(test_db, uuid)
        _seed_ready_derivative(test_db, uuid, src, "hq", 2000)
        _seed_ready_derivative(test_db, uuid, src, "light", 1000)
        _seed_ready_derivative(test_db, uuid, src, "poster", 500)
        _mk_canary_job(test_db, uuid, "ready")
    for uuid in small:
        from app.services.derivative_publisher import resolve_canonical_source_revision
        rev, _, _ = resolve_canonical_source_revision(test_db, uuid)
        _prove_phase1_clip(ops, test_db, tmp_path, state_dir, small_m, uuid,
                           str(rev.blob_sha256).lower())
    _seed_source(test_db, "clip-ex5-new")
    m2 = tmp_path / "m2.json"
    m2.write_text(json.dumps({"phase": 2, "clips": ["clip-ex5-new"]}))
    facts = _facts(tmp_path)
    rc = _admit(ops, test_db, m2, state_dir, facts, phase=2, p1=str(small_m), apply=True)
    assert rc == 2
