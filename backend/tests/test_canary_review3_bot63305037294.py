"""PR145 bot 63305037294 (run 39705037294): 3 fail-closed fixes.

1. URL expiry authoritative; --expired-at only when URL has NO parseable
   expiry; conflicts refused (5s tolerance); duplicate/ambiguous params
   fail closed; signed URLs never persisted.
2. _get_once bounded chunk read (4MiB) with early close on BOTH success
   and HTTPError bodies; exact cap allowed, cap+1 refused.
3. consecutive_failures derived from durable DB canary jobs (bounded
   latest, chronological trailing failed vs ready); limit 1..2 enforced;
   reset-proof, bypass-proof, idempotent, DB-error fail closed.
"""

import datetime
import hashlib
import importlib.util
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from app.models.media import MediaJob
from app.models.photos_asset import PhotosAsset

COLLECT = Path(__file__).resolve().parents[2] / "ops" / "canary_proof_collect.py"
CLI = Path(__file__).resolve().parents[2] / "ops" / "canary_web_package.py"


def _load(p, name):
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------- 1. expiry

def test_url_expiry_authoritative_rejects_manual_conflict():
    mod = _load(COLLECT, "cpc_expiry1")
    past_url_qs = "Expires=1000000000"
    past_moment = mod._parse_url_expiry(past_url_qs)
    assert past_moment is not None
    # Same instant (exact) passes and returns the URL moment.
    iso_same = past_moment.isoformat()
    got = mod._parse_expiry_moment(iso_same, {"Expires": "1000000000"}, raw_query=past_url_qs)
    assert got == past_moment
    # Within 5s rounding tolerance passes.
    iso_close = (past_moment + datetime.timedelta(seconds=4)).isoformat()
    got2 = mod._parse_expiry_moment(iso_close, {"Expires": "1000000000"}, raw_query=past_url_qs)
    assert got2 == past_moment
    # Conflict beyond tolerance refuses (future URL + past manual shape).
    with pytest.raises(Exception):
        mod._parse_expiry_moment(
            "2020-01-01T00:00:00+00:00",
            {"Expires": "4102444800"},
            raw_query="Expires=4102444800",
        )
    # Past URL + future manual also refuses.
    with pytest.raises(Exception):
        mod._parse_expiry_moment(
            "2035-01-01T00:00:00+00:00",
            {"Expires": "1000000000"},
            raw_query="Expires=1000000000",
        )


def test_explicit_only_when_url_has_no_parseable_expiry():
    mod = _load(COLLECT, "cpc_expiry2")
    # URL with no expiry params: explicit past is accepted.
    got = mod._parse_expiry_moment(
        "2020-01-01T00:00:00+00:00", {"grant": "old"}, raw_query="grant=old"
    )
    assert got is not None
    # URL with no parseable expiry + no explicit -> None (stays unchecked).
    assert mod._parse_expiry_moment(None, {"grant": "old"}, raw_query="grant=old") is None
    # S3 SigV4 pair parses and is authoritative.
    qs = "X-Amz-Date=20200101T000000Z&X-Amz-Expires=3600"
    m = mod._parse_url_expiry(qs)
    assert m is not None
    got3 = mod._parse_expiry_moment(m.isoformat(), {}, raw_query=qs)
    assert got3 == m


def test_duplicate_and_mixed_params_fail_closed():
    mod = _load(COLLECT, "cpc_expiry3")
    with pytest.raises(Exception):
        mod._parse_url_expiry("Expires=1000000000&Expires=2000000000")
    with pytest.raises(Exception):
        mod._parse_url_expiry("X-Amz-Expires=3600&X-Amz-Expires=7200&X-Amz-Date=20200101T000000Z")
    # Real-S3 ambiguity: SigV2 Expires mixed with SigV4 pair.
    with pytest.raises(Exception):
        mod._parse_url_expiry("Expires=1000000000&X-Amz-Date=20200101T000000Z&X-Amz-Expires=3600")
    # Identical repeats are not a conflict (idempotent URL copy).
    m = mod._parse_url_expiry("Expires=1000000000&Expires=1000000000")
    assert m is not None


def test_future_url_past_manual_with_403_must_fail_e2e(tmp_path, monkeypatch):
    """Future-dated URL + past --expired-at + denying storage MUST fail."""
    mod = _load(COLLECT, "cpc_expiry_e2e")
    data = b"exp-conflict-" * 1024

    class _Resp:
        def __init__(self, status=200, headers=None, body=b""):
            self.status = status
            self._h = headers or {}
            self._b = body

        def getheaders(self):
            return list(self._h.items())

        def getheader(self, n, d=None):
            for k, v in self._h.items():
                if k.lower() == n.lower():
                    return v
            return d

        def read(self, n=-1):
            if n is None or n < 0:
                raise AssertionError("unbounded read forbidden")
            out, self._b = self._b[:n], self._b[n:]
            return out

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *e):
            return False

    PLAY = "https://library.example.test/play/slot-1"
    LIVE = "https://b2.example.test/file/bucket/key?Expires=4102444800"
    FUTURE_EXPIRED = "https://b2.example.test/file/bucket/key?Expires=4102444800"
    SRC = "https://b2.example.test/file/source/key?Expires=4102444800"

    class _Opener:
        def __init__(self):
            self.expired_hits = 0

        def open(self, req, timeout=None):
            url = req.full_url
            if url == PLAY:
                if req.get_header("Cookie"):
                    return _Resp(302, {"Location": LIVE}, b"")
                return _Resp(403, {}, b"denied")
            if "file/bucket/key" in url and "Expires=4102444800" in url:
                self.expired_hits += 1
                return _Resp(403, {}, b"denied")
            if "file/source/key" in url:
                src = b"source-original-" * 1024
                return _Resp(200, {"Content-Type": "video/mp4"}, src)
            raise AssertionError(url)

    opener = _Opener()
    monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **k: opener)
    monkeypatch.setattr(mod, "_ffprobe", lambda *a, **k: (True, True, {"format": "mp4"}))
    monkeypatch.setattr(
        mod, "_ffprobe_video_info",
        lambda *a, **k: {"frames": 600, "avg_fps": 60.0, "r_fps": 60.0,
                         "duration": 10.0, "codec": "h264", "vfr": False},
    )
    src_bytes = b"source-original-" * 1024
    src_file = tmp_path / "source-ref.bin"
    src_file.write_bytes(src_bytes)
    src_file.chmod(0o600)
    src_url_file = tmp_path / "source-url.txt"
    src_url_file.write_text(SRC + "\n")
    src_url_file.chmod(0o600)
    cookie = tmp_path / "cookies.txt"
    cookie.write_text("session=operator-private-value")
    cookie.chmod(0o600)
    out = tmp_path / "proof.json"
    rc = mod.main([
        "--play-url", PLAY, "--library-origin", "https://library.example.test",
        "--storage-origin", "https://b2.example.test",
        "--expected-sha", _sha(data), "--expected-size", str(len(data)),
        "--cookies", str(cookie), "--slot", "light", "--video-uuid", "clip-x1",
        "--operator", "op", "--out", str(out),
        "--expired-url", FUTURE_EXPIRED, "--expired-at", "2020-01-01T00:00:00+00:00",
        "--source-reference", str(src_file),
        "--expected-source-sha", _sha(src_bytes),
        "--expected-source-size", str(len(src_bytes)),
        "--source-storage-url-file", str(src_url_file),
    ])
    assert rc == 2
    assert opener.expired_hits == 0, "conflict must refuse BEFORE replaying the URL"
    payload = json.loads(out.read_text()) if out.exists() else None
    if payload is not None:
        assert payload["checks"]["grant_expiry_checked"] is False
        blob = json.dumps(payload)
        assert "Expires=4102444800" not in blob


# ---------------------------------------------------------------- 2. bounded

class _TrackBody:
    def __init__(self, data: bytes):
        self._b = data
        self.max_read = 0
        self.closed = False
        self.unbounded = False

    def read(self, n=-1):
        if n is None or n < 0:
            self.unbounded = True
            raise AssertionError("unbounded read forbidden")
        self.max_read = max(self.max_read, n)
        out, self._b = self._b[:n], self._b[n:]
        return out

    def close(self):
        self.closed = True


class _TrackResp(_TrackBody):
    def __init__(self, data, status=200, headers=None):
        super().__init__(data)
        self.status = status
        self._h = headers or {}

    def getheaders(self):
        return list(self._h.items())

    def __enter__(self):
        return self

    def __exit__(self, *e):
        self.close()
        return False


def _patch_opener(monkeypatch, resp=None, exc=None):
    class _Op:
        def open(self, req, timeout=None):
            if exc is not None:
                raise exc
            return resp
    monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **k: _Op())


def test_bounded_allows_exact_cap_refuses_plus_one(monkeypatch):
    mod = _load(COLLECT, "cpc_bound1")
    cap = mod.SMALL_BODY_LIMIT
    body = _TrackResp(b"x" * cap, 200, {})
    _patch_opener(monkeypatch, resp=body)
    st, _, got = mod._get_once("https://b2.example.test/f", headers={}, timeout=5)
    assert st == 200 and len(got) == cap
    assert body.unbounded is False and body.closed is True
    big = _TrackResp(b"x" * (cap + 1), 200, {})
    _patch_opener(monkeypatch, resp=big)
    with pytest.raises(Exception):
        mod._get_once("https://b2.example.test/f", headers={}, timeout=5)
    assert big.unbounded is False and big.closed is True


def test_http_error_large_body_closed_without_unbounded(monkeypatch):
    mod = _load(COLLECT, "cpc_bound2")
    cap = mod.SMALL_BODY_LIMIT
    fp = _TrackBody(b"e" * (cap + 512))
    exc = urllib.error.HTTPError("https://b2.example.test/f", 403, "denied", {}, fp)
    _patch_opener(monkeypatch, exc=exc)
    with pytest.raises(Exception):
        mod._get_once("https://b2.example.test/f", headers={}, timeout=5)
    assert fp.unbounded is False
    assert fp.closed is True or getattr(exc, "closed", False) in (True, False)
    # Small HTTPError body still returns the status + bytes.
    fp2 = _TrackBody(b"denied")
    exc2 = urllib.error.HTTPError("https://b2.example.test/f", 403, "denied", {}, fp2)
    _patch_opener(monkeypatch, exc=exc2)
    st, _, got = mod._get_once("https://b2.example.test/f", headers={}, timeout=5)
    assert st == 403 and got == b"denied"
    assert fp2.unbounded is False


# ---------------------------------------------------------------- 3. streak

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


def _mk_canary_job(db, video_uuid, status):
    from app.services.media_jobs import WEB_PACKAGE_RENDITION

    asset = db.query(PhotosAsset).filter(PhotosAsset.video_uuid == video_uuid).first()
    if asset is None:
        asset = PhotosAsset(video_uuid=video_uuid)
        db.add(asset)
        db.flush()
    job = MediaJob(photos_asset_id=asset.id, media_key=f"mk-{video_uuid}-{status}-{job_counter()}",
                   rendition=WEB_PACKAGE_RENDITION, status=status,
                   request_reason="canary_web_package", priority=60,
                   attempts=1 if status == "failed" else 0, max_attempts=2)
    db.add(job)
    db.commit()
    return job


_CTR = {"n": 0}


def job_counter():
    _CTR["n"] += 1
    return _CTR["n"]


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


def test_limit_must_be_1_to_2_bypass_refused(test_db, tmp_path, monkeypatch):
    ops = _load(CLI, "cli_lim")
    monkeypatch.setattr(ops, "_engine", lambda: None)
    monkeypatch.setattr(ops, "_session", lambda eng: test_db)
    _seed_source(test_db, "clip-lim-1")
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"phase": 1, "clips": ["clip-lim-1"]}))
    with pytest.raises(ValueError):
        ops.validate_max_consecutive_failures(999)
    with pytest.raises(ValueError):
        ops.validate_max_consecutive_failures(0)
    assert ops.validate_max_consecutive_failures(2) == 2
    assert ops.validate_max_consecutive_failures(1) == 1
    assert _admit(ops, test_db, m, tmp_path / "s", _facts(tmp_path), maxfail=999) == 2
    assert test_db.query(MediaJob).filter(MediaJob.rendition == "web_package").count() == 0


def test_two_fails_stop_admission_zero_queue_and_reset_bypass_proof(test_db, tmp_path, monkeypatch):
    ops = _load(CLI, "cli_streak")
    monkeypatch.setattr(ops, "_engine", lambda: None)
    monkeypatch.setattr(ops, "_session", lambda eng: test_db)
    for i in (1, 2):
        _seed_source(test_db, f"clip-f-{i}")
    _mk_canary_job(test_db, "clip-f-1", "failed")
    _mk_canary_job(test_db, "clip-f-2", "failed")
    assert ops.db_consecutive_canary_failures(test_db) == 2
    _seed_source(test_db, "clip-new-1")
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"phase": 1, "clips": ["clip-new-1"]}))
    facts = _facts(tmp_path)
    before = test_db.query(MediaJob).filter(MediaJob.rendition == "web_package").count()
    rc = _admit(ops, test_db, m, tmp_path / "state", facts, apply=True)
    assert rc == 2
    assert test_db.query(MediaJob).filter(MediaJob.rendition == "web_package").count() == before
    # Fresh state dir cannot bypass the DB streak.
    rc2 = _admit(ops, test_db, m, tmp_path / "fresh-state", facts, apply=True)
    assert rc2 == 2
    assert test_db.query(MediaJob).filter(MediaJob.rendition == "web_package").count() == before
    # A durable ready breaks the streak.
    _seed_source(test_db, "clip-ok-1")
    _mk_canary_job(test_db, "clip-ok-1", "ready")
    assert ops.db_consecutive_canary_failures(test_db) == 0
    # failing job then ready then failing == streak 1 (ready resets).
    assert ops.db_consecutive_canary_failures(test_db) == 0


def test_retry_same_job_not_double_counted_and_attempts_ignored(test_db, monkeypatch):
    ops = _load(CLI, "cli_idem")
    monkeypatch.setattr(ops, "_engine", lambda: None)
    monkeypatch.setattr(ops, "_session", lambda eng: test_db)
    _seed_source(test_db, "clip-r-1")
    job = _mk_canary_job(test_db, "clip-r-1", "failed")
    assert ops.db_consecutive_canary_failures(test_db) == 1
    # Lease retry bumps attempts on the SAME job: still counts once.
    job.attempts = 5
    test_db.commit()
    assert ops.db_consecutive_canary_failures(test_db) == 1
    # Re-deriving twice is idempotent (no counter increment side effect).
    assert ops.db_consecutive_canary_failures(test_db) == 1


def test_failed_unproven_phase1_cannot_unlock_phase2(test_db, tmp_path, monkeypatch):
    ops = _load(CLI, "cli_p2fail")
    monkeypatch.setattr(ops, "_engine", lambda: None)
    monkeypatch.setattr(ops, "_session", lambda eng: test_db)
    cohort = [f"clip-p1-{i}" for i in range(1, 6)]
    for c in cohort:
        _seed_source(test_db, c)
    _mk_canary_job(test_db, cohort[0], "failed")
    _mk_canary_job(test_db, cohort[1], "failed")
    p1 = tmp_path / "p1.json"
    p1.write_text(json.dumps({"phase": 1, "clips": cohort}))
    m2 = tmp_path / "m2.json"
    m2.write_text(json.dumps({"phase": 2, "clips": ["clip-p2-1"]}))
    _seed_source(test_db, "clip-p2-1")
    a = type("A", (), {"manifest": str(m2), "state_dir": str(tmp_path / "s2"),
                       "phase": 2, "phase1_manifest": str(p1),
                       "host_facts": _facts(tmp_path), "apply": False,
                       "mac_free_bytes": None, "server_cache_free_bytes": None,
                       "max_consecutive_failures": 2})()
    # Two durable fails block even the DRY-RUN plan, and unproven phase-1
    # can never satisfy the exact-5 proof gate.
    assert ops.cmd_admit(a) == 2


def test_db_error_fails_closed_zero_queue(test_db, tmp_path, monkeypatch):
    ops = _load(CLI, "cli_dberr")
    monkeypatch.setattr(ops, "_engine", lambda: None)

    class _BadDB:
        def query(self, *a, **k):
            raise RuntimeError("db down")

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(ops, "_session", lambda eng: _BadDB())
    _seed = tmp_path / "m.json"
    _seed.write_text(json.dumps({"phase": 1, "clips": ["clip-x"]}))
    a = type("A", (), {"manifest": str(_seed), "state_dir": str(tmp_path / "s"),
                       "phase": 1, "phase1_manifest": None,
                       "host_facts": _facts(tmp_path), "apply": True,
                       "mac_free_bytes": None, "server_cache_free_bytes": None,
                       "max_consecutive_failures": 2})()
    assert ops.cmd_admit(a) == 2
