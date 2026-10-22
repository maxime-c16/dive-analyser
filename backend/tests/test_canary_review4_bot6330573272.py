"""PR145 bot 6330573272 (run 39706513342) - failure-streak TOCTOU.

The admission gate read ``consecutive_failures`` BEFORE the advisory
lock. An active job failing after that read turned the in-lock fleet
check terminal while the stale streak still passed, queueing another
job despite 2 durable fails.

Fix: recompute the authoritative DB streak INSIDE the admission lock
after a fresh fleet read (identity map expired), enforce the same
1..2 gate, persist state only after the consistent in-lock decision.

Covers: known-2-fail refusal (no queue), TOCTOU race (mutate between
outer read and lock -> NO new job + counter updated), idempotent
re-run (no change), fresh-state reset cannot bypass (DB authoritative).
"""

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


def _seed_source(db, video_uuid, raw=b"camera-bytes-v1"):
    from app.config import get_settings

    sha = _sha(raw + video_uuid.encode())
    db.add(PhotosAsset(video_uuid=video_uuid))
    db.flush()
    s = get_settings()
    from app.models.media_backbone import MediaBlob, MediaBlobLocation, MediaRevision

    db.add(MediaBlob(sha256=sha, byte_size=len(raw), storage_backend="b2",
                     bucket=s.media_backbone_prod_bucket,
                     object_key=f"blobs/sha256/{sha[:2]}/{sha}",
                     width=1280, height=720, duration_seconds=10.0))
    db.add(MediaBlobLocation(blob_sha256=sha, environment="prod", storage_backend="b2",
                             bucket=s.media_backbone_prod_bucket,
                             object_key=f"blobs/sha256/{sha[:2]}/{sha}", verified=True))
    db.add(MediaRevision(video_uuid=video_uuid, blob_sha256=sha,
                         rendition_semantics="photos_edited_rendition"))
    db.commit()
    return sha


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
                   attempts=1 if status == "failed" else 0, max_attempts=2)
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


def test_known_two_fails_refuse_no_queue(test_db, tmp_path, monkeypatch):
    ops = _load(CLI, "cli_toctou_known2")
    monkeypatch.setattr(ops, "_engine", lambda: None)
    monkeypatch.setattr(ops, "_session", lambda eng: test_db)
    for i in (1, 2):
        _seed_source(test_db, f"clip-k2-{i}")
    _mk_canary_job(test_db, "clip-k2-1", "failed")
    _mk_canary_job(test_db, "clip-k2-2", "failed")
    assert ops.db_consecutive_canary_failures(test_db) == 2
    _seed_source(test_db, "clip-k2-new")
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"phase": 1, "clips": ["clip-k2-new"]}))
    facts = _facts(tmp_path)
    before = test_db.query(MediaJob).filter(MediaJob.rendition == "web_package").count()
    rc = _admit(ops, test_db, m, tmp_path / "state", facts, apply=True)
    assert rc == 2
    assert test_db.query(MediaJob).filter(MediaJob.rendition == "web_package").count() == before


def test_toctou_race_second_failure_between_read_and_lock(test_db, tmp_path, monkeypatch):
    """Outer sees streak 1 (pass); a concurrent failure lands before the
    in-lock re-check -> must REFUSE with NO new job and counter -> 2."""
    ops = _load(CLI, "cli_toctou_race")
    monkeypatch.setattr(ops, "_engine", lambda: None)
    monkeypatch.setattr(ops, "_session", lambda eng: test_db)
    _seed_source(test_db, "clip-r1-f1")
    _mk_canary_job(test_db, "clip-r1-f1", "failed")
    assert ops.db_consecutive_canary_failures(test_db) == 1
    _seed_source(test_db, "clip-r1-new")
    # Seed the racy second failure's source now; the job row lands in-lock.
    _seed_source(test_db, "clip-r1-f2")
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"phase": 1, "clips": ["clip-r1-new"]}))
    facts = _facts(tmp_path)
    state_dir = tmp_path / "state-race"
    before = test_db.query(MediaJob).filter(MediaJob.rendition == "web_package").count()
    assert before == 1

    orig_lock = ops._pg_admit_lock

    def _racy_lock(db):
        # Simulate a worker committing failed AFTER the outer streak read
        # but BEFORE the in-lock authoritative re-check.
        _mk_canary_job(db, "clip-r1-f2", "failed")
        try:
            db.expire_all()
        except Exception:
            pass
        return orig_lock(db)

    monkeypatch.setattr(ops, "_pg_admit_lock", _racy_lock)
    rc = _admit(ops, test_db, m, state_dir, facts, apply=True)
    assert rc == 2
    # NO new admission job: only the 2 durable fails exist.
    after = test_db.query(MediaJob).filter(MediaJob.rendition == "web_package").count()
    assert after == before + 1  # the racy worker failure only, no admission
    # Counter persisted to the authoritative value.
    st = json.loads((state_dir / "canary-state.json").read_text())
    assert int(st.get("consecutive_failures", -1)) == 2
    # Idempotent re-run: still refused, no queue change.
    before2 = test_db.query(MediaJob).filter(MediaJob.rendition == "web_package").count()
    rc2 = _admit(ops, test_db, m, state_dir, facts, apply=True)
    assert rc2 == 2
    assert test_db.query(MediaJob).filter(MediaJob.rendition == "web_package").count() == before2
    # Fresh state dir cannot bypass: DB is authoritative, gets re-synced to 2.
    fresh = tmp_path / "fresh-state"
    rc3 = _admit(ops, test_db, m, fresh, facts, apply=True)
    assert rc3 == 2
    assert test_db.query(MediaJob).filter(MediaJob.rendition == "web_package").count() == before2
    stf = json.loads((fresh / "canary-state.json").read_text())
    assert int(stf.get("consecutive_failures", -1)) == 2
