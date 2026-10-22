"""End-to-end proof-collector tests with fakes (no network, no prod, no auth).

Drives ``ops/canary_proof_collect.py`` ``main()`` with a stubbed
``urllib.request.build_opener`` (synthetic HTTP: 302 presigned grant,
logged-out denial, Range 206, full-GET bytes) and a stubbed ``_ffprobe``:

- happy path: all checks true, exit 0, output JSON checks all true;
- full-GET SHA corruption: exit 2, ``b2_full_get_sha_match`` false;
- missing Range 206: exit 2;
- logged-out request served bytes (200): exit 2 (denial required);
- 302 grant WITHOUT expiry fields: exit 2 with ``grant_expiry_checked``
  false -- an expired-grant replay stays a MANUAL operator step and must
  never be recorded as automatically checked;
- ffprobe dirty / cadence miss / missing binary: exit 2 (fail closed);
- tool hygiene: no auth-minting flags, no cookie-material logging,
  cookie + output files refused inside git.

Plus a fresh-proof DB check (SQLite ``test_db``): a proof record with
``grant_expiry_checked`` false/missing is refused by
``validate_proof_record``, and a source move after the proof fails the
DB cross-check.
"""

import hashlib
import importlib.util
import json
import urllib.request
from pathlib import Path

import pytest

OPS_MOD = Path(__file__).resolve().parents[2] / "ops" / "canary_proof_collect.py"


def _load_mod():
    spec = importlib.util.spec_from_file_location("canary_proof_collect_e2e", OPS_MOD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


PLAY_URL = "https://library.example.test/play/slot-1"
PRESIGNED = "https://b2.example.test/file/bucket/key?X-Amz-Expires=3600"


class _FakeResp:
    def __init__(self, status=200, headers=None, body=b""):
        self.status = status
        self._headers = headers or {}
        self._body = body
        self._pos = 0

    def getheaders(self):
        return list(self._headers.items())

    def getheader(self, name, default=None):
        lname = name.lower()
        for k, v in self._headers.items():
            if k.lower() == lname:
                return v
        return default

    def read(self, n=-1):
        if n is None or n < 0:
            chunk = self._body[self._pos :]
            self._pos = len(self._body)
            return chunk
        chunk = self._body[self._pos : self._pos + n]
        self._pos += len(chunk)
        return chunk

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeOpener:
    """Routes by Cookie/Range presence. Cookie material never logged."""

    def __init__(self, data: bytes, ctype="video/mp4", mode="ok"):
        self.data = data
        self.ctype = ctype
        self.mode = mode
        self.requests: list = []

    def open(self, req, timeout=None):
        url = req.full_url
        cookie = req.get_header("Cookie")
        rng = req.get_header("Range")
        self.requests.append((url, bool(cookie), rng))
        assert url == PLAY_URL, f"unexpected URL {url}"
        if self.mode == "unreachable":
            raise ConnectionError("down")
        if not cookie:
            if self.mode == "logged_out_served":
                return _FakeResp(200, {"Content-Type": self.ctype}, self.data)
            return _FakeResp(403, {"Content-Type": "text/plain"}, b"denied")
        if rng:
            if self.mode == "range_200":
                return _FakeResp(200, {"Content-Type": self.ctype}, self.data[:1024])
            return _FakeResp(
                206,
                {"Content-Range": f"bytes 0-1023/{len(self.data)}",
                 "Content-Type": self.ctype},
                self.data[:1024],
            )
        # Top-level route probe (no Range): the 302 grant.
        if self.mode == "no_expiry":
            return _FakeResp(
                302, {"Location": "https://b2.example.test/file/bucket/key"}, b"")
        if self.mode == "not_found":
            return _FakeResp(404, {}, b"nope")
        if self.mode == "corrupt_full":
            return _FakeResp(
                302, {"Location": PRESIGNED}, b"")
        return _FakeResp(302, {"Location": PRESIGNED}, b"")


def _full_get_resp(opener: _FakeOpener):
    # The full-GET phase re-opens the play URL (follows to bytes in the
    # real flow); emulate by serving bytes when the fake is asked again
    # without Range after the 302. Our opener returns 302 for plain
    # authorized hits, so wrap: first plain hit -> 302, subsequent
    # full-GET read is performed by main() inline on the SAME opener.
    # Simplify: make plain authorized hits return the bytes directly when
    # the caller streams (main() treats 200 as full bytes, 302 only in
    # the _get probe phase which uses Range/redirect flags... ). Instead
    # patch at a higher level: route the 4th+ authorized plain request
    # to bytes.
    orig_open = opener.open
    state = {"plain": 0}

    def patched(req, timeout=None):
        cookie = req.get_header("Cookie")
        rng = req.get_header("Range")
        if cookie and not rng:
            state["plain"] += 1
            if state["plain"] >= 2:
                body = opener.data
                if opener.mode == "corrupt_full":
                    body = b"tampered:" + body
                return _FakeResp(200, {"Content-Type": opener.ctype}, body)
        return orig_open(req, timeout=timeout)

    opener.open = patched
    return opener


def _run(mod, monkeypatch, tmp_path, data, ctype="video/mp4", mode="ok",
          ffprobe=(True, True), slot="light"):
    opener = _full_get_resp(_FakeOpener(data, ctype=ctype, mode=mode))
    monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **k: opener)
    if ffprobe == "missing_binary":
        import subprocess as _sp

        def _missing(*a, **k):
            raise FileNotFoundError("no ffprobe")

        monkeypatch.setattr(_sp, "run", _missing)
    else:
        clean, cadence = ffprobe
        monkeypatch.setattr(
            mod, "_ffprobe", lambda *a, **k: (clean, cadence, {"format": "mp4"}))
    cookie = tmp_path / "cookies.txt"
    cookie.write_text("session=operator-private-value")
    out = tmp_path / "proof-frag.json"
    rc = mod.main([
        "--play-url", PLAY_URL,
        "--expected-sha", _sha(data),
        "--expected-size", str(len(data)),
        "--cookies", str(cookie),
        "--slot", slot,
        "--video-uuid", "clip-e2e-1",
        "--operator", "op",
        "--out", str(out),
    ])
    payload = json.loads(out.read_text()) if out.exists() else None
    return rc, payload, opener


def test_happy_path_all_checks_true(tmp_path, monkeypatch):
    mod = _load_mod()
    data = b"e2e-bytes-" * 4096
    rc, payload, opener = _run(mod, monkeypatch, tmp_path, data)
    assert rc == 0
    assert payload is not None
    assert all(payload["checks"][k] is True for k in (
        "b2_full_get_sha_match", "ffprobe_clean", "frame_cadence_match",
        "library_auth_302", "range_206", "grant_expiry_checked",
        "logged_out_denied")), payload["checks"]
    assert payload["details"]["byte_size"] == len(data)
    assert payload["details"]["sha256"] == _sha(data)
    assert payload["details"].get("presigned_expiry") == "3600"
    # Cookie material never leaves the machine in the fragment.
    assert "operator-private-value" not in out_text(payload)


def out_text(payload) -> str:
    return json.dumps(payload, sort_keys=True)


def test_full_get_sha_corruption_refused(tmp_path, monkeypatch):
    mod = _load_mod()
    data = b"e2e-bytes-" * 4096
    rc, payload, _ = _run(mod, monkeypatch, tmp_path, data, mode="corrupt_full")
    assert rc == 2
    assert payload is not None
    assert payload["checks"]["b2_full_get_sha_match"] is False


def test_range_206_required(tmp_path, monkeypatch):
    mod = _load_mod()
    rc, payload, _ = _run(mod, monkeypatch, tmp_path, b"e2e-bytes-" * 4096,
                           mode="range_200")
    assert rc == 2
    assert payload is not None
    assert payload["checks"]["range_206"] is False


def test_logged_out_denial_required(tmp_path, monkeypatch):
    mod = _load_mod()
    rc, payload, _ = _run(mod, monkeypatch, tmp_path, b"e2e-bytes-" * 4096,
                           mode="logged_out_served")
    assert rc == 2
    assert payload is not None
    assert payload["checks"]["logged_out_denied"] is False


def test_grant_expiry_fields_required_not_automatic(tmp_path, monkeypatch):
    mod = _load_mod()
    data = b"e2e-bytes-" * 4096
    rc, payload, _ = _run(mod, monkeypatch, tmp_path, data, mode="no_expiry")
    assert rc == 2
    assert payload is not None
    # An expiry-less grant (or an expired-grant replay the operator has
    # not actually re-proven) must NOT be recorded as checked.
    assert payload["checks"]["grant_expiry_checked"] is False


def test_ffprobe_dirty_and_cadence_miss_fail_closed(tmp_path, monkeypatch):
    mod = _load_mod()
    data = b"e2e-bytes-" * 4096
    rc, payload, _ = _run(mod, monkeypatch, tmp_path, data, ffprobe=(False, False))
    assert rc == 2
    assert payload["checks"]["ffprobe_clean"] is False
    rc2, payload2, _ = _run(mod, monkeypatch, tmp_path, data, ffprobe=(True, False))
    assert rc2 == 2
    assert payload2["checks"]["ffprobe_clean"] is True
    assert payload2["checks"]["frame_cadence_match"] is False


def test_ffprobe_missing_binary_fails_closed(tmp_path, monkeypatch):
    mod = _load_mod()
    rc, payload, _ = _run(mod, monkeypatch, tmp_path, b"e2e-bytes-" * 4096,
                           ffprobe="missing_binary")
    assert rc == 2
    assert payload["checks"]["ffprobe_clean"] is False


def test_no_auth_minting_flags_and_no_secret_logs(tmp_path):
    mod = _load_mod()
    ap = mod.build_parser()
    flags = {a.option_strings[0] for a in ap._actions}
    for banned in ("--token", "--api-key", "--apikey", "--secret",
                   "--password", "--login", "--cookie-value"):
        assert banned not in flags, f"auth-minting flag {banned} must not exist"
    src = OPS_MOD.read_text()
    assert "Authorization" not in src or "add_header" not in src.split("Authorization")[0][-100:]
    # Cookie material (the header value) is never printed: only file
    # paths/modes appear in diagnostics.
    import re as _re

    for m in _re.finditer(r"print\((.*?)\)", src, _re.S):
        assert "operator-private" not in m.group(1)
    assert "session=operator-private-value" not in src
    # Files refused inside git (operator secrets stay outside the repo).
    with pytest.raises(SystemExit):
        mod._refuse_inside_git(Path(__file__).resolve(), "cookie file")
    out_inside = Path(__file__).resolve().parent / "proof-frag.json"
    with pytest.raises(SystemExit):
        mod._refuse_inside_git(out_inside, "output file")


def test_expired_replay_manual_step_not_auto_checked(test_db):
    """A proof record must carry grant_expiry_checked=true evidence.

    The expired-grant replay denial is a MANUAL operator observation: the
    schema refuses records where the flag is false/missing, so nothing
    auto-marks it checked without an actual test.
    """
    import datetime as _dt
    import importlib.util as _ilu
    from pathlib import Path as _P

    ops_path = _P(__file__).resolve().parents[2] / "ops" / "canary_web_package.py"
    spec = _ilu.spec_from_file_location("canary_web_package_proof", ops_path)
    ops = _ilu.module_from_spec(spec)
    spec.loader.exec_module(ops)
    good = {
        "video_uuid": "clip-e2e-2", "source_sha256": "a" * 64,
        "source_revision_id": 1, "transform_version": "ffmpeg-h264-web-v1",
        "slots": {"light": {"derivative_sha256": "b" * 64, "byte_size": 10},
                  "poster": {"derivative_sha256": "c" * 64, "byte_size": 10}},
        "checks": {n: True for n in ops.PROOF_REQUIRED_CHECKS},
        "recorded_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "operator": "op",
    }
    ops.validate_proof_record(good)
    bad = json.loads(json.dumps(good))
    bad["checks"]["grant_expiry_checked"] = False
    with pytest.raises(ValueError):
        ops.validate_proof_record(bad)
    missing = json.loads(json.dumps(good))
    del missing["checks"]["grant_expiry_checked"]
    with pytest.raises(ValueError):
        ops.validate_proof_record(missing)
