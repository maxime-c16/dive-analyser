"""PR145 bot 6330664756 (run 39707264046) - stale cohort/phase caps TOCTOU.

The cohort + phase caps were computed BEFORE the admission lock and never
refreshed before queueing. If another admitted job became terminal while
this command waited, the fleet check passed and the stale cohort admitted
beyond the phase limit (phase-1 >5, total >30).

Fix: ONE authoritative decision INSIDE the short PG advisory (+ local file)
lock via ``_decide_admission`` -- expire cached rows, reload the state hint,
fresh SQL recompute of the DB cohort, NEW-unique counting, candidate
idempotency, phase counts, exact-5 + fresh source-bound phase-2 proofs,
durable failure streak, fleet blocking, budget + host-facts freshness, and
the source-pin readiness for the queued candidate. Planning (outer) uses the
same helper fail-fast; only the in-lock result authorizes the queue. No
network under the lock; the global per-PUT budget charge stays a separate
short TX in the publisher.

Covers (barrier = racy commit between outer plan and the in-lock decision):
- phase-1 4 (outer pass) -> 5 before lock, candidate would be 6th: REFUSE 2.
- phase-2 total 29 (outer pass) -> 30 before lock, candidate 31st: REFUSE 2.
- phase-2 proof source moves while waiting: REFUSE 2 (fresh cross-check).
- replay of an already-admitted (ready) job: idempotent 0, no extra queue.
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


def _mk_canary_job(db, video_uuid, status):
    from app.services.media_jobs import WEB_PACKAGE_RENDITION

    asset = db.query(PhotosAsset).filter(PhotosAsset.video_uuid == video_uuid).first()
    if asset is None:
        asset = PhotosAsset(video_uuid=video_uuid)
        db.add(asset)
        db.flush()
    job = MediaJob(photos_asset_id=asset.id, media_key=f"mk-{video_uuid}-{status}-{_ctr()}",
                   rendition=WEB_PACKAGE_RENDITION, status=status,
                   request_reason="canary_web_package", priority=60,
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
    rev_id = None
    from app.services.derivative_publisher import resolve_canonical_source_revision
    rev, _b, _l = resolve_canonical_source_revision(test_db, uuid)
    rev_id = int(rev.id)
    proof = {"video_uuid": uuid, "source_sha256": src,
             "source_revision_id": rev_id, "transform_version": "ffmpeg-h264-web-v1",
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


def test_phase1_stale_cohort_4_to_5_refuses_6th(test_db, tmp_path, monkeypatch):
    """Outer sees 4 admitted (pass for 1 new); a 5th lands before the lock.

    In-lock total is 5, the candidate would be 6th -> REFUSE 2, no queue.
    """
    ops = _load(CLI, "cli_cohort_p1")
    monkeypatch.setattr(ops, "_engine", lambda: None)
    monkeypatch.setattr(ops, "_session", lambda eng: test_db)
    for i in range(1, 5):
        _seed_source(test_db, f"clip-c1-{i}")
        _mk_canary_job(test_db, f"clip-c1-{i}", "ready")
    _seed_source(test_db, "clip-c1-new")
    _seed_source(test_db, "clip-c1-race")
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"phase": 1, "clips": ["clip-c1-new"]}))
    facts = _facts(tmp_path)
    state_dir = tmp_path / "state-c1"
    before = test_db.query(MediaJob).filter(MediaJob.rendition == "web_package").count()
    assert before == 4

    orig_lock = ops._pg_admit_lock

    def _racy_lock(db):
        # Concurrent admit commits the 5th distinct clip before our decision.
        _mk_canary_job(db, "clip-c1-race", "ready")
        try:
            db.expire_all()
        except Exception:
            pass
        return orig_lock(db)

    monkeypatch.setattr(ops, "_pg_admit_lock", _racy_lock)
    rc = _admit(ops, test_db, m, state_dir, facts, apply=True)
    assert rc == 2
    after = test_db.query(MediaJob).filter(MediaJob.rendition == "web_package").count()
    # Only the racy worker's job exists; our candidate queued nothing.
    assert after == before + 1


def test_phase1_proof_source_moves_while_waiting_refuses(test_db, tmp_path, monkeypatch):
    """Phase-2 outer proof is fresh; the source moves before the lock.

    The in-lock fresh cross-check must refuse even though the outer plan
    passed and the proven list still claims 5/5.
    """
    ops = _load(CLI, "cli_cohort_proofmove")
    monkeypatch.setattr(ops, "_engine", lambda: None)
    monkeypatch.setattr(ops, "_session", lambda eng: test_db)
    p1 = [f"clip-mv-p1-{i}" for i in range(1, 6)]
    p1m = tmp_path / "p1.json"
    p1m.write_text(json.dumps({"phase": 1, "clips": p1}))
    state_dir = tmp_path / "state-mv"
    for uuid in p1:
        src = _seed_source(test_db, uuid)
        _seed_ready_derivative(test_db, uuid, src, "hq", 2000)
        _seed_ready_derivative(test_db, uuid, src, "light", 1000)
        _seed_ready_derivative(test_db, uuid, src, "poster", 500)
        _mk_canary_job(test_db, uuid, "ready")
    for uuid in p1:
        from app.services.derivative_publisher import resolve_canonical_source_revision
        rev, _b, _l = resolve_canonical_source_revision(test_db, uuid)
        _prove_phase1_clip(ops, test_db, tmp_path, state_dir, p1m, uuid,
                           str(rev.blob_sha256).lower())
    _seed_source(test_db, "clip-mv-new")
    m2 = tmp_path / "m2.json"
    m2.write_text(json.dumps({"phase": 2, "clips": ["clip-mv-new"]}))
    facts = _facts(tmp_path)
    # Outer DRY-RUN passes with fresh proofs.
    assert _admit(ops, test_db, m2, state_dir, facts, phase=2, p1=str(p1m)) == 0

    orig_lock = ops._pg_admit_lock

    def _racy_lock(db):
        # Source moves for one phase-1 clip after the outer proof check.
        from app.config import get_settings as _gs
        from app.models.media_backbone import MediaBlob, MediaBlobLocation, MediaRevision

        victim = p1[0]
        new_sha = _sha(f"moved-{victim}".encode())
        _s = _gs()
        db.add(MediaBlob(sha256=new_sha, byte_size=18, storage_backend="b2",
                         bucket=_s.media_backbone_prod_bucket,
                         object_key=f"blobs/sha256/{new_sha[:2]}/{new_sha}",
                         width=1280, height=720, duration_seconds=10.0))
        db.add(MediaBlobLocation(blob_sha256=new_sha, environment="prod", storage_backend="b2",
                                 bucket=_s.media_backbone_prod_bucket,
                                 object_key=f"blobs/sha256/{new_sha[:2]}/{new_sha}",
                                 verified=True))
        db.add(MediaRevision(video_uuid=victim, blob_sha256=new_sha,
                             rendition_semantics="photos_edited_rendition"))
        db.commit()
        try:
            db.expire_all()
        except Exception:
            pass
        return orig_lock(db)

    monkeypatch.setattr(ops, "_pg_admit_lock", _racy_lock)
    before = test_db.query(MediaJob).filter(MediaJob.rendition == "web_package").count()
    rc = _admit(ops, test_db, m2, state_dir, facts, phase=2, p1=str(p1m), apply=True)
    assert rc == 2
    assert test_db.query(MediaJob).filter(MediaJob.rendition == "web_package").count() == before


def test_phase2_stale_total_29_to_30_refuses_31st(test_db, tmp_path, monkeypatch):
    """Outer sees DB total 29 (pass for +1 = 30); a 30th lands before lock.

    In-lock total is 30, the candidate would be 31st -> REFUSE 2, no queue.
    """
    ops = _load(CLI, "cli_cohort_p2")
    monkeypatch.setattr(ops, "_engine", lambda: None)
    monkeypatch.setattr(ops, "_session", lambda eng: test_db)
    p1 = [f"clip-t2-p1-{i}" for i in range(1, 6)]
    p1m = tmp_path / "p1.json"
    p1m.write_text(json.dumps({"phase": 1, "clips": p1}))
    state_dir = tmp_path / "state-t2"
    for uuid in p1:
        src = _seed_source(test_db, uuid)
        _seed_ready_derivative(test_db, uuid, src, "hq", 2000)
        _seed_ready_derivative(test_db, uuid, src, "light", 1000)
        _seed_ready_derivative(test_db, uuid, src, "poster", 500)
        _mk_canary_job(test_db, uuid, "ready")
    for uuid in p1:
        from app.services.derivative_publisher import resolve_canonical_source_revision
        rev, _b, _l = resolve_canonical_source_revision(test_db, uuid)
        _prove_phase1_clip(ops, test_db, tmp_path, state_dir, p1m, uuid,
                           str(rev.blob_sha256).lower())
    # Fill to DB total 29 (5 phase-1 + 24 others, all terminal ready).
    for i in range(24):
        uuid = f"clip-t2-fill-{i}"
        _seed_source(test_db, uuid)
        _mk_canary_job(test_db, uuid, "ready")
    from app.services.canary_budget import db_admitted_uuids
    assert len(db_admitted_uuids(test_db)) == 29
    _seed_source(test_db, "clip-t2-new")
    _seed_source(test_db, "clip-t2-race")
    m2 = tmp_path / "m2.json"
    m2.write_text(json.dumps({"phase": 2, "clips": ["clip-t2-new"]}))
    facts = _facts(tmp_path)
    assert _admit(ops, test_db, m2, state_dir, facts, phase=2, p1=str(p1m)) == 0

    orig_lock = ops._pg_admit_lock

    def _racy_lock(db):
        _mk_canary_job(db, "clip-t2-race", "ready")
        try:
            db.expire_all()
        except Exception:
            pass
        return orig_lock(db)

    monkeypatch.setattr(ops, "_pg_admit_lock", _racy_lock)
    before = test_db.query(MediaJob).filter(MediaJob.rendition == "web_package").count()
    rc = _admit(ops, test_db, m2, state_dir, facts, phase=2, p1=str(p1m), apply=True)
    assert rc == 2
    assert test_db.query(MediaJob).filter(MediaJob.rendition == "web_package").count() == before + 1


def test_replay_already_admitted_is_idempotent(test_db, tmp_path, monkeypatch):
    """An already-admitted ready clip replays with no extra queue (0)."""
    ops = _load(CLI, "cli_cohort_replay")
    monkeypatch.setattr(ops, "_engine", lambda: None)
    monkeypatch.setattr(ops, "_session", lambda eng: test_db)
    src = _seed_source(test_db, "clip-replay-1")
    _seed_ready_derivative(test_db, "clip-replay-1", src, "hq", 2000)
    _seed_ready_derivative(test_db, "clip-replay-1", src, "light", 1000)
    _seed_ready_derivative(test_db, "clip-replay-1", src, "poster", 500)
    _mk_canary_job(test_db, "clip-replay-1", "ready")
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"phase": 1, "clips": ["clip-replay-1"]}))
    facts = _facts(tmp_path)
    state_dir = tmp_path / "state-replay"
    before = test_db.query(MediaJob).filter(MediaJob.rendition == "web_package").count()
    assert _admit(ops, test_db, m, state_dir, facts, apply=True) == 0
    assert test_db.query(MediaJob).filter(MediaJob.rendition == "web_package").count() == before
    # Second replay stays idempotent.
    assert _admit(ops, test_db, m, state_dir, facts, apply=True) == 0
    assert test_db.query(MediaJob).filter(MediaJob.rendition == "web_package").count() == before
