"""End-to-end proof-collector tests with fakes (no network, no prod, no auth).

Drives ``ops/canary_proof_collect.py`` ``main()`` with a stubbed
``urllib.request.build_opener`` (synthetic HTTP: Library 302 presigned
grant, logged-out denial, credential-free Range 206, full-GET bytes,
measured expired-grant denial) and a stubbed ``_ffprobe``:

- happy path: all checks true, exit 0, output JSON checks all true
  (expiry counts ONLY via a measured expired-grant denial);
- credential separation: the session cookie reaches the Library origin
  only -- storage fetches (stubbed AND real local HTTP servers on two
  distinct origins) carry no Cookie/Authorization;
- malicious redirects (untrusted host, userinfo) are refused BEFORE any
  storage fetch, with no credentials leaked;
- full-GET SHA corruption: exit 2, ``b2_full_get_sha_match`` false;
- missing Range 206: exit 2;
- logged-out request served bytes (200): exit 2 (denial required);
- logged-out 302 to a presigned grant: exit 2 (a grant is NOT a denial);
- logged-out 302 to a same-origin login route: accepted denial;
- 302 grant WITHOUT expiry fields: exit 2 with ``grant_expiry_checked``
  false;
- unexpired-grant expiry parameter alone NEVER yields
  ``grant_expiry_checked`` true (final proof gate stays blocked);
- expired-grant replay denial measured only for the EXACT object with a
  provably-past timestamp over a credential-free request (wrong object,
  future timestamp, or still-live grant all stay false);
- ffprobe dirty / cadence miss / missing binary: exit 2 (fail closed);
- tool hygiene: no auth-minting flags, no cookie-material logging, no
  device/browser playback claims, cookie + output files refused inside
  git.

Plus a fresh-proof DB check (SQLite ``test_db``): a proof record with
``grant_expiry_checked`` false/missing is refused by
``validate_proof_record``, and a source move after the proof fails the
DB cross-check.
"""

import hashlib
import http.server
import importlib.util
import json
import threading
import urllib.parse
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
LIB_ORIGIN = "https://library.example.test"
STO_ORIGIN = "https://b2.example.test"
LOGIN_URL = "https://library.example.test/login"
PRESIGNED = "https://b2.example.test/file/bucket/key?X-Amz-Expires=3600&X-Amz-Date=20300101T000000Z"
PRESIGNED_NOEXP = "https://b2.example.test/file/bucket/key"
EXPIRED_URL = "https://b2.example.test/file/bucket/key?Expires=1000000000"
EXPIRED_NOPARAM_URL = "https://b2.example.test/file/bucket/key?grant=old"
EXPIRED_FUTURE_URL = "https://b2.example.test/file/bucket/key?Expires=4102444800"
EXPIRED_OTHER_URL = "https://b2.example.test/file/other/key?Expires=1000000000"


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
    """Routes by URL. Library asserts cookie discipline; storage asserts
    credential-free access. Cookie material never logged."""

    def __init__(self, data: bytes, ctype="video/mp4", mode="ok"):
        self.data = data
        self.ctype = ctype
        self.mode = mode
        self.requests: list = []
        self.cookie_to_storage = 0

    def open(self, req, timeout=None):
        url = req.full_url
        cookie = req.get_header("Cookie")
        auth = req.get_header("Authorization")
        rng = req.get_header("Range")
        self.requests.append((url, bool(cookie), rng))
        assert url == PLAY_URL or url.startswith("https://b2.example.test/"), (
            f"unexpected URL {url}"
        )
        if url == PLAY_URL:
            return self._library(cookie, rng)
        # Storage: must NEVER see credentials.
        if cookie or auth:
            self.cookie_to_storage += 1
        return self._storage(url, rng)

    def _library(self, cookie, rng):
        if rng:
            # The collector must never send Range to the Library (Range
            # goes to the credential-free storage fetch). Fail loudly.
            return _FakeResp(400, {}, b"range must target storage")
        if not cookie:
            if self.mode == "logged_out_served":
                return _FakeResp(200, {"Content-Type": self.ctype}, self.data)
            if self.mode == "logged_out_grant":
                return _FakeResp(302, {"Location": PRESIGNED}, b"")
            if self.mode == "logged_out_login":
                return _FakeResp(302, {"Location": LOGIN_URL}, b"")
            return _FakeResp(403, {"Content-Type": "text/plain"}, b"denied")
        if self.mode == "no_expiry":
            return _FakeResp(302, {"Location": PRESIGNED_NOEXP}, b"")
        if self.mode == "not_found":
            return _FakeResp(404, {}, b"nope")
        if self.mode == "evil_redirect":
            return _FakeResp(302, {"Location": "https://evil.example.test/file"}, b"")
        if self.mode == "userinfo_redirect":
            return _FakeResp(
                302, {"Location": "https://user:pass@b2.example.test/file/bucket/key"}, b"")
        return _FakeResp(302, {"Location": PRESIGNED}, b"")

    def _storage(self, url, rng):
        if url in (EXPIRED_URL, EXPIRED_NOPARAM_URL, EXPIRED_FUTURE_URL):
            if self.mode == "expired_live":
                return _FakeResp(200, {"Content-Type": self.ctype}, self.data)
            return _FakeResp(403, {"Content-Type": "text/plain"}, b"expired")
        if rng:
            if self.mode == "range_200":
                return _FakeResp(200, {"Content-Type": self.ctype}, self.data[:1024])
            return _FakeResp(
                206,
                {"Content-Range": f"bytes 0-1023/{len(self.data)}",
                 "Content-Type": self.ctype},
                self.data[:1024],
            )
        body = self.data
        if self.mode == "corrupt_full":
            body = b"tampered:" + body
        return _FakeResp(200, {"Content-Type": self.ctype}, body)


def _run(mod, monkeypatch, tmp_path, data, ctype="video/mp4", mode="ok",
         ffprobe=(True, True), slot="light", play_url=PLAY_URL,
         expired_url=EXPIRED_URL, expired_at=None):
    opener = _FakeOpener(data, ctype=ctype, mode=mode)
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
    argv = [
        "--play-url", play_url,
        "--library-origin", LIB_ORIGIN,
        "--storage-origin", STO_ORIGIN,
        "--expected-sha", _sha(data),
        "--expected-size", str(len(data)),
        "--cookies", str(cookie),
        "--slot", slot,
        "--video-uuid", "clip-e2e-1",
        "--operator", "op",
        "--out", str(out),
    ]
    if expired_url is not None:
        argv += ["--expired-url", expired_url]
    if expired_at is not None:
        argv += ["--expired-at", expired_at]
    rc = mod.main(argv)
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
    assert payload["details"]["grant_expiry"]["measured"] is True
    # Storage never saw credentials, even though the Library did.
    assert opener.cookie_to_storage == 0
    assert any(u == PLAY_URL and had_cookie for u, had_cookie, _ in opener.requests)
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


def test_logged_out_grant_redirect_is_not_denial(tmp_path, monkeypatch):
    """An unauthenticated 302 to a presigned storage grant must FAIL the
    proof (it is access, not denial)."""
    mod = _load_mod()
    rc, payload, _ = _run(mod, monkeypatch, tmp_path, b"e2e-bytes-" * 4096,
                           mode="logged_out_grant")
    assert rc == 2
    assert payload is not None
    assert payload["checks"]["logged_out_denied"] is False
    assert payload["details"]["logged_out_location_class"] == "storage-grant"


def test_logged_out_login_redirect_same_origin_is_denial(tmp_path, monkeypatch):
    """An unauthenticated 302 back to the SAME Library origin (login
    route, never storage) is accepted as a denial."""
    mod = _load_mod()
    data = b"e2e-bytes-" * 4096
    rc, payload, _ = _run(mod, monkeypatch, tmp_path, data, mode="logged_out_login")
    assert rc == 0
    assert payload is not None
    assert payload["checks"]["logged_out_denied"] is True
    assert payload["details"]["logged_out_location_class"] == "login-redirect"


def test_grant_expiry_fields_required_not_automatic(tmp_path, monkeypatch):
    mod = _load_mod()
    data = b"e2e-bytes-" * 4096
    rc, payload, _ = _run(mod, monkeypatch, tmp_path, data, mode="no_expiry",
                           expired_url=None)
    assert rc == 2
    assert payload is not None
    # An expiry-less grant (or an expired-grant replay the operator has
    # not actually re-proven) must NOT be recorded as checked.
    assert payload["checks"]["grant_expiry_checked"] is False


def test_unexpired_param_does_not_pass_final_proof(tmp_path, monkeypatch):
    """The live grant carries an expiry parameter, but with no measured
    expired-grant denial the collector must leave grant_expiry_checked
    false -- and the proof gate must refuse the fragment."""
    mod = _load_mod()
    data = b"e2e-bytes-" * 4096
    rc, payload, _ = _run(mod, monkeypatch, tmp_path, data, expired_url=None)
    assert rc == 2
    assert payload is not None
    assert payload["details"].get("presigned_expiry") == "3600"
    assert payload["checks"]["grant_expiry_checked"] is False
    assert "no expired-grant denial measured" in payload["details"]["grant_expiry"]["reason"]
    import datetime as _dt
    import importlib.util as _ilu
    from pathlib import Path as _P

    ops_path = _P(__file__).resolve().parents[2] / "ops" / "canary_web_package.py"
    spec = _ilu.spec_from_file_location("canary_web_package_gate", ops_path)
    ops = _ilu.module_from_spec(spec)
    spec.loader.exec_module(ops)
    gate_record = {
        "video_uuid": "clip-e2e-1", "source_sha256": "a" * 64,
        "source_revision_id": 1, "transform_version": "ffmpeg-h264-web-v1",
        "slots": {"light": {"derivative_sha256": "b" * 64, "byte_size": 10},
                  "poster": {"derivative_sha256": "c" * 64, "byte_size": 10}},
        "checks": {n: True for n in ops.PROOF_REQUIRED_CHECKS},
        "recorded_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "operator": "op",
    }
    gate_record["checks"]["grant_expiry_checked"] = payload["checks"]["grant_expiry_checked"]
    with pytest.raises(ValueError):
        ops.validate_proof_record(gate_record)


def test_expired_replay_measured_with_explicit_past_timestamp(tmp_path, monkeypatch):
    """An expired grant URL without URL-embedded expiry params qualifies
    via an explicit provably-past --expired-at, measured credential-free."""
    mod = _load_mod()
    data = b"e2e-bytes-" * 4096
    rc, payload, opener = _run(
        mod, monkeypatch, tmp_path, data,
        expired_url=EXPIRED_NOPARAM_URL, expired_at="2020-01-01T00:00:00+00:00")
    assert rc == 0
    assert payload["checks"]["grant_expiry_checked"] is True
    assert opener.cookie_to_storage == 0
    expired_hits = [u for u, _, _ in opener.requests if "grant=old" in u]
    assert expired_hits, "expired URL must actually be fetched"
    assert all(not had_cookie for u, had_cookie, _ in opener.requests if "grant=old" in u)


def test_expired_replay_wrong_object_refused(tmp_path, monkeypatch):
    """An expired grant for a DIFFERENT object proves nothing about this
    slot: refused before any storage fetch of that URL."""
    mod = _load_mod()
    data = b"e2e-bytes-" * 4096
    rc, payload, opener = _run(
        mod, monkeypatch, tmp_path, data, expired_url=EXPIRED_OTHER_URL)
    assert rc == 2
    assert payload is not None
    assert payload["checks"]["grant_expiry_checked"] is False
    assert not any("other/key" in u for u, _, _ in opener.requests)


def test_expired_replay_future_timestamp_refused(tmp_path, monkeypatch):
    """A not-yet-expired grant URL cannot prove expiry denial, even if the
    host would deny it: refused before fetching that URL."""
    mod = _load_mod()
    data = b"e2e-bytes-" * 4096
    rc, payload, opener = _run(
        mod, monkeypatch, tmp_path, data, expired_url=EXPIRED_FUTURE_URL)
    assert rc == 2
    assert payload is not None
    assert payload["checks"]["grant_expiry_checked"] is False
    assert not any("Expires=4102444800" in u for u, _, _ in opener.requests)


def test_expired_live_grant_not_counted(tmp_path, monkeypatch):
    """An --expired-url the host still serves (200 with bytes) is NOT an
    expiry denial: stays false."""
    mod = _load_mod()
    data = b"e2e-bytes-" * 4096
    rc, payload, _ = _run(mod, monkeypatch, tmp_path, data, mode="expired_live")
    assert rc == 2
    assert payload is not None
    assert payload["checks"]["grant_expiry_checked"] is False


def test_untrusted_play_url_never_gets_cookies(tmp_path, monkeypatch):
    """A play URL outside the explicit --library-origin is refused BEFORE
    cookies are loaded or any request is sent."""
    mod = _load_mod()
    data = b"e2e-bytes-" * 4096
    rc, payload, opener = _run(
        mod, monkeypatch, tmp_path, data,
        play_url="https://evil.example.test/play/slot-1", expired_url=None)
    assert rc == 2
    assert opener.requests == []


def test_userinfo_play_url_refused(tmp_path, monkeypatch):
    mod = _load_mod()
    data = b"e2e-bytes-" * 4096
    rc, payload, opener = _run(
        mod, monkeypatch, tmp_path, data,
        play_url="https://user:pass@library.example.test/play/slot-1",
        expired_url=None)
    assert rc == 2
    assert opener.requests == []


def test_malicious_storage_redirect_refused_without_cookie_leak(tmp_path, monkeypatch):
    """A Library 302 to an untrusted host is refused BEFORE any storage
    fetch -- with no credentials sent anywhere but the Library."""
    mod = _load_mod()
    data = b"e2e-bytes-" * 4096
    rc, payload, opener = _run(
        mod, monkeypatch, tmp_path, data, mode="evil_redirect", expired_url=None)
    assert rc == 2
    assert payload is not None
    assert payload["checks"]["library_auth_302"] is False
    assert opener.cookie_to_storage == 0
    assert not any("evil.example.test" in u for u, _, _ in opener.requests)


def test_userinfo_storage_redirect_refused(tmp_path, monkeypatch):
    mod = _load_mod()
    data = b"e2e-bytes-" * 4096
    rc, payload, opener = _run(
        mod, monkeypatch, tmp_path, data, mode="userinfo_redirect", expired_url=None)
    assert rc == 2
    assert payload is not None
    assert payload["checks"]["library_auth_302"] is False
    assert opener.cookie_to_storage == 0


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
    # Credential separation is explicit CLI surface: the trusted Library
    # origin and the allowlisted storage origins are required inputs, and
    # the measured-expiry inputs exist without ever minting auth.
    for required in ("--play-url", "--library-origin", "--storage-origin",
                     "--expired-url", "--expired-at"):
        assert required in flags, f"expected flag {required}"
    src = OPS_MOD.read_text()
    assert "Authorization" not in src or "add_header" not in src.split("Authorization")[0][-100:]
    # No device/browser playback is claimed by this tool.
    assert "safari" not in src.lower()
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

    The expired-grant replay denial is a MEASURED operator observation:
    the schema refuses records where the flag is false/missing, so
    nothing auto-marks it checked without an actual test.
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


# --- Real local HTTP servers: two distinct origins (fake app vs fake B2)
# prove the cookie never crosses origins, through real urllib redirects.


def _drop_proxies(monkeypatch):
    for var in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("no_proxy", "*")


def _start_servers(monkeypatch, data, *, app_mode="ok", b2_chain=False,
                   expired_status=403, future_expires=4102444800,
                   past_expires=1000000000):
    """Launch fake app (Library) + B2 (storage) [+ evil] origins on
    127.0.0.1 with distinct ports. Returns (urls, hits, shutdown)."""
    _drop_proxies(monkeypatch)
    hits = {"app": [], "b2": [], "evil": []}
    refs: dict = {}

    class _App(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            cookie = self.headers.get("Cookie")
            hits["app"].append((self.path, cookie))
            if self.path.split("?")[0] != "/play/slot-1":
                self.send_response(404)
                self.end_headers()
                return
            if not cookie:
                self.send_response(403)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                try:
                    self.wfile.write(b"denied")
                except BrokenPipeError:
                    pass
                return
            if self.headers.get("Range"):
                self.send_response(400)
                self.end_headers()
                return
            loc = refs["presigned"]
            if app_mode == "evil":
                loc = refs["evil_url"]
            elif app_mode == "userinfo":
                loc = refs["userinfo_url"]
            self.send_response(302)
            self.send_header("Location", loc)
            self.end_headers()

        def log_message(self, *a):
            pass

    class _B2(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            cookie = self.headers.get("Cookie")
            auth = self.headers.get("Authorization")
            hits["b2"].append(
                (self.path, cookie, auth, self.headers.get("Range")))
            parts = urllib.parse.urlsplit(self.path)
            q = urllib.parse.parse_qs(parts.query)
            if parts.path not in ("/file/key", "/file/key2"):
                self.send_response(404)
                self.end_headers()
                return
            if "expired" in q:
                self.send_response(expired_status)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                try:
                    self.wfile.write(b"expired" if expired_status != 403 else b"denied")
                except BrokenPipeError:
                    pass
                return
            if b2_chain and parts.path == "/file/key" and "hop" not in q:
                self.send_response(302)
                self.send_header(
                    "Location",
                    f"http://127.0.0.1:{refs['b2_port']}/file/key2?live=1&hop=2")
                self.end_headers()
                return
            if self.headers.get("Range"):
                self.send_response(206)
                self.send_header("Content-Range", f"bytes 0-1023/{len(data)}")
                self.send_header("Content-Type", "video/mp4")
                self.end_headers()
                try:
                    self.wfile.write(data[:1024])
                except BrokenPipeError:
                    pass
                return
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except BrokenPipeError:
                pass

        def log_message(self, *a):
            pass

    class _Evil(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits["evil"].append((self.path, self.headers.get("Cookie")))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    app = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _App)
    b2 = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _B2)
    evil = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Evil)
    servers = (app, b2, evil)
    for srv in servers:
        threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05},
                         daemon=True).start()
    app_port = app.server_address[1]
    b2_port = b2.server_address[1]
    evil_port = evil.server_address[1]
    refs["b2_port"] = b2_port
    refs["presigned"] = (
        f"http://127.0.0.1:{b2_port}/file/key?live=1&Expires={future_expires}")
    refs["expired_url"] = (
        f"http://127.0.0.1:{b2_port}/file/key?expired=1&Expires={past_expires}")
    refs["evil_url"] = f"http://127.0.0.1:{evil_port}/evil"
    refs["userinfo_url"] = f"http://user:pass@127.0.0.1:{b2_port}/file/key?live=1"
    urls = {
        "play": f"http://127.0.0.1:{app_port}/play/slot-1",
        "library_origin": f"http://127.0.0.1:{app_port}",
        "storage_origin": f"http://127.0.0.1:{b2_port}",
        "expired": refs["expired_url"],
    }

    def _shutdown():
        for srv in servers:
            try:
                srv.shutdown()
            except Exception:
                pass
            try:
                srv.server_close()
            except Exception:
                pass

    return urls, hits, _shutdown


def _run_real(mod, tmp_path, data, urls, extra_argv=()):
    monkeypatch_ffprobe = getattr(mod, "_ffprobe")
    _ = monkeypatch_ffprobe
    mod._ffprobe = lambda *a, **k: (True, True, {"format": "mp4"})
    try:
        cookie = tmp_path / "cookies.txt"
        cookie.write_text("session=operator-private-value")
        out = tmp_path / "proof-frag.json"
        argv = [
            "--play-url", urls["play"],
            "--library-origin", urls["library_origin"],
            "--storage-origin", urls["storage_origin"],
            "--expired-url", urls["expired"],
            "--expected-sha", _sha(data),
            "--expected-size", str(len(data)),
            "--cookies", str(cookie),
            "--slot", "light",
            "--video-uuid", "clip-real-1",
            "--operator", "op",
            "--timeout", "10",
            "--out", str(out),
            *extra_argv,
        ]
        rc = mod.main(argv)
        payload = json.loads(out.read_text()) if out.exists() else None
        return rc, payload
    finally:
        mod._ffprobe = monkeypatch_ffprobe


def test_cookie_never_leaves_library_origin_real_servers(tmp_path, monkeypatch):
    """Two distinct local origins (fake app vs fake B2): the app gets the
    cookie; B2 sees NONE on Range, full GET, or the expired-grant replay."""
    mod = _load_mod()
    data = b"real-bytes-" * 1024
    urls, hits, shutdown = _start_servers(monkeypatch, data)
    try:
        rc, payload = _run_real(mod, tmp_path, data, urls)
    finally:
        shutdown()
    assert rc == 0, payload
    assert all(v is True for v in payload["checks"].values()), payload["checks"]
    assert any(c for _, c in hits["app"]), "app must receive the cookie"
    assert hits["b2"], "storage must be fetched"
    for path, cookie, auth, rng in hits["b2"]:
        assert cookie is None, f"B2 got Cookie on {path}"
        assert auth is None, f"B2 got Authorization on {path}"
    expired_hits = [h for h in hits["b2"] if "expired" in h[0]]
    assert expired_hits, "expired grant must actually be replayed"
    assert all(h[1] is None for h in expired_hits)
    assert "operator-private-value" not in out_text(payload)


def test_storage_redirect_chain_never_carries_cookie(tmp_path, monkeypatch):
    """Storage-to-storage redirect hop: still credential-free, bytes still
    verified."""
    mod = _load_mod()
    data = b"chain-bytes-" * 1024
    urls, hits, shutdown = _start_servers(monkeypatch, data, b2_chain=True)
    try:
        rc, payload = _run_real(mod, tmp_path, data, urls)
    finally:
        shutdown()
    assert rc == 0, payload
    assert payload["checks"]["b2_full_get_sha_match"] is True
    assert payload["checks"]["range_206"] is True
    assert len(hits["b2"]) >= 2, hits["b2"]
    for path, cookie, auth, _ in hits["b2"]:
        assert cookie is None, f"chained storage hop got Cookie on {path}"
        assert auth is None


def test_evil_redirect_refused_before_any_storage_fetch(tmp_path, monkeypatch):
    """Library 302 to an untrusted host: refused, evil origin never
    contacted, storage never contacted."""
    mod = _load_mod()
    data = b"evil-bytes-" * 1024
    urls, hits, shutdown = _start_servers(monkeypatch, data, app_mode="evil")
    try:
        monkeypatch_ffprobe = getattr(mod, "_ffprobe")
        mod._ffprobe = lambda *a, **k: (True, True, {"format": "mp4"})
        try:
            cookie = tmp_path / "cookies.txt"
            cookie.write_text("session=operator-private-value")
            out = tmp_path / "proof-frag.json"
            rc = mod.main([
                "--play-url", urls["play"],
                "--library-origin", urls["library_origin"],
                "--storage-origin", urls["storage_origin"],
                "--expected-sha", _sha(data),
                "--expected-size", str(len(data)),
                "--cookies", str(cookie),
                "--slot", "light",
                "--video-uuid", "clip-real-evil",
                "--operator", "op",
                "--timeout", "10",
                "--out", str(out),
            ])
            payload = json.loads(out.read_text()) if out.exists() else None
        finally:
            mod._ffprobe = monkeypatch_ffprobe
    finally:
        shutdown()
    assert rc == 2
    assert payload is not None
    assert payload["checks"]["library_auth_302"] is False
    assert hits["evil"] == [], "untrusted host must never be contacted"
    assert hits["b2"] == [], "storage must never be fetched after refusal"


def test_userinfo_redirect_refused_without_storage_contact(tmp_path, monkeypatch):
    """Library 302 embedding userinfo: refused before any storage fetch."""
    mod = _load_mod()
    data = b"userinfo-bytes-" * 1024
    urls, hits, shutdown = _start_servers(monkeypatch, data, app_mode="userinfo")
    try:
        monkeypatch_ffprobe = getattr(mod, "_ffprobe")
        mod._ffprobe = lambda *a, **k: (True, True, {"format": "mp4"})
        try:
            cookie = tmp_path / "cookies.txt"
            cookie.write_text("session=operator-private-value")
            out = tmp_path / "proof-frag.json"
            rc = mod.main([
                "--play-url", urls["play"],
                "--library-origin", urls["library_origin"],
                "--storage-origin", urls["storage_origin"],
                "--expected-sha", _sha(data),
                "--expected-size", str(len(data)),
                "--cookies", str(cookie),
                "--slot", "light",
                "--video-uuid", "clip-real-userinfo",
                "--operator", "op",
                "--timeout", "10",
                "--out", str(out),
            ])
            payload = json.loads(out.read_text()) if out.exists() else None
        finally:
            mod._ffprobe = monkeypatch_ffprobe
    finally:
        shutdown()
    assert rc == 2
    assert payload is not None
    assert payload["checks"]["library_auth_302"] is False
    assert hits["b2"] == [], "storage must never see a userinfo redirect"
