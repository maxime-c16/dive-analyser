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
- logged-out 302 to same-origin login AND same-origin playback routes:
  exit 2 (STRICT: NO redirect counts, only 401/403/404);
- logged-out 401/403/404: pass (denial);
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
PLAYBACK_OTHER_URL = "https://library.example.test/play/other-slot"
PRESIGNED = "https://b2.example.test/file/bucket/key?X-Amz-Expires=3600&X-Amz-Date=20300101T000000Z"
PRESIGNED_NOEXP = "https://b2.example.test/file/bucket/key"
EXPIRED_URL = "https://b2.example.test/file/bucket/key?Expires=1000000000"
EXPIRED_NOPARAM_URL = "https://b2.example.test/file/bucket/key?grant=old"
EXPIRED_FUTURE_URL = "https://b2.example.test/file/bucket/key?Expires=4102444800"
EXPIRED_OTHER_URL = "https://b2.example.test/file/other/key?Expires=1000000000"
SOURCE_PRESIGNED = "https://b2.example.test/file/source/key?X-Amz-Expires=3600&X-Amz-Date=20300101T000000Z"
SOURCE_PRESIGNED_CORRUPT = "https://b2.example.test/file/source/key?X-Amz-Expires=3600&X-Amz-Date=20300101T000000Z"


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

    def __init__(self, data: bytes, ctype="video/mp4", mode="ok", source_data: bytes | None = None):
        self.data = data
        self.source_data = source_data if source_data is not None else b"source-original-" * 1024
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
            if self.mode == "logged_out_playback":
                return _FakeResp(302, {"Location": PLAYBACK_OTHER_URL}, b"")
            if self.mode == "logged_out_401":
                return _FakeResp(401, {"Content-Type": "text/plain"}, b"denied")
            if self.mode == "logged_out_404":
                return _FakeResp(404, {"Content-Type": "text/plain"}, b"denied")
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
        # Canonical-original re-read path: distinct source object.
        if "/file/source/key" in urllib.parse.urlsplit(url).path:
            body = self.source_data
            if self.mode == "corrupt_source":
                body = b"tampered-source:" + body
            if rng:
                if self.mode == "range_200":
                    return _FakeResp(200, {"Content-Type": self.ctype}, body[:1024])
                return _FakeResp(
                    206,
                    {"Content-Range": f"bytes 0-1023/{len(body)}",
                     "Content-Type": self.ctype},
                    body[:1024],
                )
            return _FakeResp(200, {"Content-Type": "video/mp4"}, body)
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
         expired_url=EXPIRED_URL, expired_at=None, source_mode="match",
         source_bytes=None, source_url=SOURCE_PRESIGNED,
         expected_source_size=None, source_max_bytes=None):
    src_content = source_bytes if source_bytes is not None else b"source-original-" * 1024
    opener = _FakeOpener(data, ctype=ctype, mode=mode, source_data=src_content)
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
    # Source-bound cadence census stub (bounded count semantics, no frame
    # list): video slots verify against the B2-re-read source temp.
    src_file = tmp_path / "source-ref.bin"
    src_content = source_bytes if source_bytes is not None else b"source-original-" * 1024
    src_file.write_bytes(src_content)
    src_file.chmod(0o600)
    src_sha = _sha(src_content)
    # Operator-supplied B2 original URL file (0600, outside repo, never logged).
    src_url_file = tmp_path / "source-url.txt"
    if source_mode != "missing":
        src_url_file.write_text((source_url or SOURCE_PRESIGNED) + "\n")
        src_url_file.chmod(0o600)
    base_census = {"frames": 600, "avg_fps": 60.0, "r_fps": 60.0,
                   "duration": 10.0, "codec": "h264", "vfr": False}
    ffprobe_positive = True
    if isinstance(ffprobe, tuple):
        try:
            ffprobe_positive = bool(ffprobe[1])
        except IndexError:
            ffprobe_positive = True

    def _fake_video_info(path, timeout=60):
        if source_mode == "census_error":
            return {"error": "unmeasurable video census (frames=0 fps=0.0 dur=0.0)"}
        # A stubbed positive-count miss still fails closed at the
        # source-bound gate (output-only counts never pass video).
        effective = source_mode
        if not ffprobe_positive and effective == "match":
            effective = "output_30fps"
        info = dict(base_census)
        # Distinguish B2 source temp vs derivative output tmp: the B2
        # source temp carries "canary-source-" (or the legacy local
        # reference file); everything else is the derivative output.
        pstr = str(path)
        is_source = ("canary-source-" in pstr) or (pstr == str(src_file)) or ("source" in pstr.lower())
        # The derivative output tmp (canary-proof-) must NOT count as source.
        if "canary-proof-" in pstr:
            is_source = False
        if effective == "match":
            return dict(info)
        if effective == "output_30fps":
            if is_source:
                return dict(info)
            bad = dict(info)
            bad.update({"frames": 300, "avg_fps": 30.0})
            return bad
        if effective == "output_drop":
            if is_source:
                return dict(info)
            bad = dict(info)
            bad.update({"frames": 590})
            return bad
        if effective == "vfr_match":
            v = dict(info)
            v.update({"r_fps": 90.0, "vfr": True})
            return v
        if effective == "edited_mov_rate":
            info.update(frames=302, duration=5.036667 if is_source else 5.038367,
                        avg_fps=31800 / 559 if is_source else 60000 / 1001,
                        r_fps=60000 / 1001, vfr=is_source)
            return info
        return dict(info)

    monkeypatch.setattr(mod, "_ffprobe_video_info", _fake_video_info)
    cookie = tmp_path / "cookies.txt"
    cookie.write_text("session=operator-private-value")
    cookie.chmod(0o600)
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
    if slot in ("hq", "light") and source_mode != "missing":
        argv += ["--source-reference", str(src_file)]
        if source_mode == "wrong_sha":
            argv += ["--expected-source-sha", "b" * 64]
        else:
            argv += ["--expected-source-sha", src_sha]
        argv += ["--source-storage-url-file", str(src_url_file)]
        argv += ["--expected-source-size",
                 str(expected_source_size if expected_source_size is not None else len(src_content))]
        if source_max_bytes is not None:
            argv += ["--source-max-bytes", str(int(source_max_bytes))]
    if expired_url is not None:
        argv += ["--expired-url", expired_url]
    if expired_at is not None:
        argv += ["--expired-at", expired_at]
    rc = mod.main(argv)
    payload = json.loads(out.read_text()) if out.exists() else None
    return rc, payload, opener


def _stub_video_match(mod, monkeypatch, tmp_path, name="source-ref.bin"):
    """Stub a B2 source re-read + matching census (test-only)."""
    src = tmp_path / name
    src.write_bytes(b"source-original-" * 1024)
    src.chmod(0o600)
    census = {"frames": 600, "avg_fps": 60.0, "r_fps": 60.0,
              "duration": 10.0, "codec": "h264", "vfr": False}
    monkeypatch.setattr(mod, "_ffprobe_video_info", lambda *a, **k: dict(census))
    url_file = tmp_path / "source-url.txt"
    url_file.write_text(SOURCE_PRESIGNED + "\n")
    url_file.chmod(0o600)
    return ["--source-reference", str(src), "--expected-source-sha", _sha(b"source-original-" * 1024),
            "--source-storage-url-file", str(url_file),
            "--expected-source-size", str(len(b"source-original-" * 1024))]


def _signed_grant_urls(base="https://b2.example.test/file/bucket/key"):
    """Planted bearer-query URLs: must NEVER appear in proof output/logs."""
    return [
        base + "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=AKIAIOSFODNN7EXAMPLE"
               "%2F20300101%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Date=20300101T000000Z"
               "&X-Amz-Expires=3600&X-Amz-SignedHeaders=host&X-Amz-Signature=abc123def456",
        base + "?Expires=1000000000&Signature=planted-sig&X-Amz-Security-Token=planted-token",
        base + "?x-amz-credential=lower-case-plant&session-secret=planted-session-secret",
    ]


def _assert_no_bearer_leak(capsys, payload):
    blob = json.dumps(payload, sort_keys=True) if payload else ""
    out = capsys.readouterr()
    hay = blob + out.out + out.err
    for needle in ("X-Amz-Signature", "X-Amz-Credential", "X-Amz-Security-Token",
                   "x-amz-credential", "planted-sig", "planted-token",
                   "planted-session-secret", "operator-private-value"):
        assert needle.lower() not in hay.lower(), f"leaked {needle} into output/log/report"


def test_signed_query_never_persisted_success_and_failure(capsys, tmp_path, monkeypatch):
    """Planted bearer query params must not leak via JSON/stdout/stderr."""
    import urllib.request as _urllib_request

    mod = _load_mod()
    data = b"leak-bytes-" * 4096
    for grant in _signed_grant_urls():
        opener = _FakeOpener(data, ctype="video/mp4", mode="ok")
        # Override the authorized 302 Location with the planted grant.
        orig_library = opener._library

        def _planted_library(cookie, rng, _orig=orig_library, _grant=grant):
            if not cookie:
                return _FakeResp(403, {"Content-Type": "text/plain"}, b"denied")
            return _FakeResp(302, {"Location": _grant}, b"")

        opener._library = _planted_library
        monkeypatch.setattr(_urllib_request, "build_opener", lambda *a, **k: opener)
        monkeypatch.setattr(mod, "_ffprobe", lambda *a, **k: (True, True, {"format": "mp4"}))
        src_argv = _stub_video_match(mod, monkeypatch, tmp_path)
        cookie = tmp_path / "cookies.txt"
        cookie.write_text("session=operator-private-value")
        cookie.chmod(0o600)
        out = tmp_path / "proof-frag.json"
        expired = "https://b2.example.test/file/bucket/key?Expires=1000000000"
        rc = mod.main([
            "--play-url", PLAY_URL, "--library-origin", LIB_ORIGIN,
            "--storage-origin", STO_ORIGIN, "--expected-sha", _sha(data),
            "--expected-size", str(len(data)), "--cookies", str(cookie),
            "--slot", "light", "--video-uuid", "clip-leak-1", "--operator", "op",
            "--out", str(out), "--expired-url", expired,
            *src_argv,
        ])
        payload = json.loads(out.read_text()) if out.exists() else None
        # Success path still proves bytes without persisting bearer query.
        assert rc == 0, payload
        _assert_no_bearer_leak(capsys, payload)
        # No raw query-bearing field survives in details.
        for key, value in (payload.get("details") or {}).items():
            assert "X-Amz-" not in str(value) and "Signature" not in str(value), key
            assert "planted" not in str(value).lower(), key
        # Failure path: corrupt full GET, still no leak.
        opener2 = _FakeOpener(data, ctype="video/mp4", mode="corrupt_full")
        opener2._library = _planted_library
        monkeypatch.setattr(_urllib_request, "build_opener", lambda *a, **k: opener2)
        monkeypatch.setattr(mod, "_ffprobe", lambda *a, **k: (True, True, {"format": "mp4"}))
        monkeypatch.setattr(mod, "_ffprobe_video_info",
                            lambda *a, **k: {"frames": 600, "avg_fps": 60.0, "r_fps": 60.0,
                                             "duration": 10.0, "codec": "h264", "vfr": False})
        out2 = tmp_path / "proof-frag-fail.json"
        rc2 = mod.main([
            "--play-url", PLAY_URL, "--library-origin", LIB_ORIGIN,
            "--storage-origin", STO_ORIGIN, "--expected-sha", _sha(data),
            "--expected-size", str(len(data)), "--cookies", str(cookie),
            "--slot", "light", "--video-uuid", "clip-leak-1", "--operator", "op",
            "--out", str(out2), "--expired-url", expired,
            *src_argv,
        ])
        assert rc2 == 2
        payload2 = json.loads(out2.read_text()) if out2.exists() else None
        _assert_no_bearer_leak(capsys, payload2)


def test_logged_out_storage_grant_has_no_query_or_url_field(capsys, tmp_path, monkeypatch):
    """Logged-out 302 to a signed storage grant: fail closed, status+class
    only, bare origin at most -- no raw Location/query/URL field."""
    mod = _load_mod()
    data = b"leak-bytes-" * 4096
    grant = _signed_grant_urls()[0]

    class _LoggedOutSigned(_FakeOpener):
        def _library(self, cookie, rng):
            if not cookie:
                return _FakeResp(302, {"Location": grant}, b"")
            return super()._library(cookie, rng)

    import urllib.request as _urllib_request

    opener = _LoggedOutSigned(data, ctype="video/mp4", mode="ok")
    monkeypatch.setattr(_urllib_request, "build_opener", lambda *a, **k: opener)
    monkeypatch.setattr(mod, "_ffprobe", lambda *a, **k: (True, True, {"format": "mp4"}))
    cookie = tmp_path / "cookies.txt"
    cookie.write_text("session=operator-private-value")
    cookie.chmod(0o600)
    out = tmp_path / "proof-frag.json"
    rc = mod.main([
        "--play-url", PLAY_URL, "--library-origin", LIB_ORIGIN,
        "--storage-origin", STO_ORIGIN, "--expected-sha", _sha(data),
        "--expected-size", str(len(data)), "--cookies", str(cookie),
        "--slot", "light", "--video-uuid", "clip-leak-2", "--operator", "op",
        "--out", str(out), "--expired-url", EXPIRED_URL,
    ])
    assert rc == 2
    payload = json.loads(out.read_text())
    assert payload["checks"]["logged_out_denied"] is False
    assert payload["details"]["logged_out_location_class"] == "storage-grant"
    assert payload["details"]["logged_out_status"] == 302
    assert "logged_out_location" not in payload["details"], "raw Location must not persist"
    for key, value in payload["details"].items():
        assert "?" not in str(value) or key in ("grant_expiry",), f"query in {key}"
        assert "X-Amz-" not in str(value), key
    origin = payload["details"].get("logged_out_origin", "")
    assert origin in ("", "https://b2.example.test"), origin
    _assert_no_bearer_leak(capsys, payload)


def test_group_readable_cookie_file_refused_before_read(tmp_path, monkeypatch):
    """Group/world-readable cookie files are refused BEFORE reading/sending."""
    import urllib.request as _urllib_request

    mod = _load_mod()
    data = b"cookie-mode-" * 1024
    opener = _FakeOpener(data, mode="ok")
    monkeypatch.setattr(_urllib_request, "build_opener", lambda *a, **k: opener)
    monkeypatch.setattr(mod, "_ffprobe", lambda *a, **k: (True, True, {"format": "mp4"}))
    cookie = tmp_path / "cookies.txt"
    cookie.write_text("session=operator-private-value")
    cookie.chmod(0o640)
    out = tmp_path / "proof-frag.json"
    with __import__("pytest").raises(SystemExit):
        mod._load_cookies(cookie)
    assert opener.requests == [], "no request may precede the mode refusal"
    rc = None
    try:
        rc = mod.main([
            "--play-url", PLAY_URL, "--library-origin", LIB_ORIGIN,
            "--storage-origin", STO_ORIGIN, "--expected-sha", _sha(data),
            "--expected-size", str(len(data)), "--cookies", str(cookie),
            "--slot", "light", "--video-uuid", "clip-cookie-mode", "--operator", "op",
            "--out", str(out),
        ])
    except SystemExit as exc:
        rc = exc.code
    assert rc != 0
    assert opener.requests == []


def test_happy_path_all_checks_true(tmp_path, monkeypatch):
    mod = _load_mod()
    data = b"e2e-bytes-" * 4096
    rc, payload, opener = _run(mod, monkeypatch, tmp_path, data)
    assert rc == 0
    assert payload is not None
    assert all(payload["checks"][k] is True for k in (
        "b2_full_get_sha_match", "ffprobe_clean", "frame_cadence_match",
        "library_auth_302", "range_206", "grant_expiry_checked",
        "logged_out_denied", "source_bytes_sha_match",
        "original_storage_integrity_checked")), payload["checks"]
    assert payload["details"]["cadence_evidence"]["source_frames"] == 600
    assert payload["details"]["cadence_evidence"]["outputs"]["light"]["frames"] == 600
    assert payload["details"]["cadence_evidence"]["pts_exact_claimed"] is False
    assert payload["details"]["byte_size"] == len(data)
    assert payload["details"]["sha256"] == _sha(data)
    assert payload["details"].get("presigned_expiry") == "3600"
    assert payload["details"]["grant_expiry"]["measured"] is True
    # B2 source re-read evidence: sha/size/method only, no URL/secrets.
    ev = payload["details"].get("source_integrity_evidence") or {}
    assert ev.get("sha") == _sha(b"source-original-" * 1024)
    assert ev.get("size") == len(b"source-original-" * 1024)
    assert ev.get("method") == "full_get_after_publication"
    assert ev.get("measured_at"), "measured_at required"
    assert "url" not in {k.lower() for k in ev}, ev
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


def test_logged_out_login_redirect_same_origin_is_not_denial_strict(tmp_path, monkeypatch):
    """STRICT: even an unauthenticated 302 back to the SAME Library
    origin (login route) is NOT a denial -- only 401/403/404 pass."""
    mod = _load_mod()
    data = b"e2e-bytes-" * 4096
    rc, payload, _ = _run(mod, monkeypatch, tmp_path, data, mode="logged_out_login")
    assert rc == 2
    assert payload is not None
    assert payload["checks"]["logged_out_denied"] is False
    assert payload["details"]["logged_out_location_class"] == "login-redirect"


def test_logged_out_playback_redirect_same_origin_is_not_denial(tmp_path, monkeypatch):
    """STRICT: a same-origin redirect to another playback route must NOT
    pass -- it could still grant storage access on follow."""
    mod = _load_mod()
    data = b"e2e-bytes-" * 4096
    rc, payload, _ = _run(mod, monkeypatch, tmp_path, data, mode="logged_out_playback")
    assert rc == 2
    assert payload is not None
    assert payload["checks"]["logged_out_denied"] is False
    assert payload["details"]["logged_out_location_class"] == "login-redirect"


@pytest.mark.parametrize("mode", ["logged_out_401", "ok", "logged_out_404"])
def test_logged_out_denial_statuses_pass(tmp_path, monkeypatch, mode):
    """Logged-out 401/403/404 all count as denial (strict allowlist)."""
    mod = _load_mod()
    data = b"e2e-bytes-" * 4096
    rc, payload, _ = _run(mod, monkeypatch, tmp_path, data, mode=mode)
    assert rc == 0
    assert payload is not None
    assert payload["checks"]["logged_out_denied"] is True
    assert payload["details"]["logged_out_location_class"] == "denial"


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
        "cadence_evidence": {
            "source_sha256": "a" * 64,
            "source_frames": 600, "source_fps": 60.0, "source_duration": 10.0,
            "outputs": {"light": {"frames": 600, "fps": 60.0, "duration": 10.0}},
            "vfr": False, "pts_exact_claimed": False,
        },
        "source_integrity_evidence": {
            "sha": "a" * 64, "size": 18,
            "measured_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "method": "full_get_after_publication",
        },
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
    # the measured-expiry inputs exist without ever minting auth. The B2
    # source re-read is operator-supplied via a private file (never minted).
    for required in ("--play-url", "--library-origin", "--storage-origin",
                     "--expired-url", "--expired-at",
                     "--source-reference", "--expected-source-sha",
                     "--source-storage-url-file", "--expected-source-size"):
        assert required in flags, f"expected flag {required}"
    # No presign-minting: the tool only GETs operator-supplied URLs.
    for banned in ("--mint", "--presign", "--sign-url"):
        assert banned not in flags, f"presign-minting flag {banned} must not exist"
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
        "cadence_evidence": {
            "source_sha256": "a" * 64,
            "source_frames": 600, "source_fps": 60.0, "source_duration": 10.0,
            "outputs": {"light": {"frames": 600, "fps": 60.0, "duration": 10.0}},
            "vfr": False, "pts_exact_claimed": False,
        },
        "source_integrity_evidence": {
            "sha": "a" * 64, "size": 18,
            "measured_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "method": "full_get_after_publication",
        },
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
                   past_expires=1000000000, source_data: bytes | None = None):
    """Launch fake app (Library) + B2 (storage) [+ evil] origins on
    127.0.0.1 with distinct ports. Returns (urls, hits, shutdown)."""
    _drop_proxies(monkeypatch)
    hits = {"app": [], "b2": [], "evil": []}
    refs: dict = {}
    src_bytes = source_data if source_data is not None else b"source-original-" * 1024

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
            if parts.path == "/file/source/key":
                if self.headers.get("Range"):
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes 0-1023/{len(src_bytes)}")
                    self.send_header("Content-Type", "video/mp4")
                    self.end_headers()
                    try:
                        self.wfile.write(src_bytes[:1024])
                    except BrokenPipeError:
                        pass
                    return
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(len(src_bytes)))
                self.end_headers()
                try:
                    self.wfile.write(src_bytes)
                except BrokenPipeError:
                    pass
                return
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
    refs["source_url"] = (
        f"http://127.0.0.1:{b2_port}/file/source/key?live=1&Expires={future_expires}")
    refs["evil_url"] = f"http://127.0.0.1:{evil_port}/evil"
    refs["userinfo_url"] = f"http://user:pass@127.0.0.1:{b2_port}/file/key?live=1"
    urls = {
        "play": f"http://127.0.0.1:{app_port}/play/slot-1",
        "library_origin": f"http://127.0.0.1:{app_port}",
        "storage_origin": f"http://127.0.0.1:{b2_port}",
        "expired": refs["expired_url"],
        "source_url": refs["source_url"],
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
    monkeypatch_video = getattr(mod, "_ffprobe_video_info")
    _ = monkeypatch_ffprobe
    mod._ffprobe = lambda *a, **k: (True, True, {"format": "mp4"})
    mod._ffprobe_video_info = lambda *a, **k: {"frames": 600, "avg_fps": 60.0,
                                               "r_fps": 60.0, "duration": 10.0,
                                               "codec": "h264", "vfr": False}
    try:
        cookie = tmp_path / "cookies.txt"
        cookie.write_text("session=operator-private-value")
        cookie.chmod(0o600)
        src = tmp_path / "source-ref.bin"
        src.write_bytes(b"source-original-" * 1024)
        src.chmod(0o600)
        src_url_file = tmp_path / "source-url.txt"
        src_url_file.write_text(urls["source_url"] + "\n")
        src_url_file.chmod(0o600)
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
            "--source-reference", str(src),
            "--expected-source-sha", _sha(b"source-original-" * 1024),
            "--expected-source-size", str(len(b"source-original-" * 1024)),
            "--source-storage-url-file", str(src_url_file),
            *extra_argv,
        ]
        rc = mod.main(argv)
        payload = json.loads(out.read_text()) if out.exists() else None
        return rc, payload
    finally:
        mod._ffprobe = monkeypatch_ffprobe
        mod._ffprobe_video_info = monkeypatch_video


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
            cookie.chmod(0o600)
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
            cookie.chmod(0o600)
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


# --- Source-bound cadence (PR145 6330236485): exact frames + timing,
# fail closed without a SHA-pinned reference; poster N/A; strict types.

def test_cadence_60_preserved_pass_30_reject(tmp_path, monkeypatch):
    """Synthetic 60fps source: identical 60fps output passes, nominal
    60->30 output FAILS even though its frame count is positive."""
    mod = _load_mod()
    data = b"e2e-bytes-" * 4096
    rc, payload, _ = _run(mod, monkeypatch, tmp_path, data, source_mode="match")
    assert rc == 0, payload
    assert payload["checks"]["frame_cadence_match"] is True
    assert payload["checks"]["source_bytes_sha_match"] is True
    assert payload["checks"]["original_storage_integrity_checked"] is True
    rc2, payload2, _ = _run(mod, monkeypatch, tmp_path, data, source_mode="output_30fps")
    assert rc2 == 2
    assert payload2 is not None
    assert payload2["checks"]["frame_cadence_match"] is False
    # B2 bytes themselves still matched; only the cadence failed.
    assert payload2["checks"]["source_bytes_sha_match"] is True
    assert payload2["checks"]["original_storage_integrity_checked"] is True


def test_cadence_missing_reference_fails_closed(tmp_path, monkeypatch):
    """No B2 source URL: unknown reference fails closed (local scratch
    alone never proves B2; output-only metadata is never inferred)."""
    mod = _load_mod()
    data = b"e2e-bytes-" * 4096
    rc, payload, _ = _run(mod, monkeypatch, tmp_path, data, source_mode="missing")
    assert rc == 2
    assert payload is not None
    assert payload["checks"]["frame_cadence_match"] is False
    assert payload["checks"]["source_bytes_sha_match"] is False
    assert payload["checks"]["original_storage_integrity_checked"] is False


def test_cadence_source_sha_mismatch_fails(tmp_path, monkeypatch):
    """B2 source bytes not matching the DB-canonical SHA: claims never
    trusted, fail closed (no evidence emitted)."""
    mod = _load_mod()
    data = b"e2e-bytes-" * 4096
    rc, payload, _ = _run(mod, monkeypatch, tmp_path, data, source_mode="wrong_sha")
    assert rc == 2
    assert payload is not None
    assert payload["checks"]["source_bytes_sha_match"] is False
    assert payload["checks"]["original_storage_integrity_checked"] is False
    assert payload["checks"]["frame_cadence_match"] is False
    assert "source_integrity_evidence" not in payload["details"]


def test_cadence_vfr_preserved_pass_drop_reject(tmp_path, monkeypatch):
    """VFR census preserved (count+duration) passes with pts_exact
    explicitly NOT claimed; a dropped frame fails."""
    mod = _load_mod()
    data = b"e2e-bytes-" * 4096
    rc, payload, _ = _run(mod, monkeypatch, tmp_path, data, source_mode="vfr_match")
    assert rc == 0, payload
    assert payload["checks"]["frame_cadence_match"] is True
    assert payload["details"]["cadence"]["vfr"] is True
    assert payload["details"]["cadence_evidence"]["pts_exact_claimed"] is False
    rc2, payload2, _ = _run(mod, monkeypatch, tmp_path, data, source_mode="output_drop")
    assert rc2 == 2
    assert payload2["checks"]["frame_cadence_match"] is False


def test_compare_cadence_units_no_frame_list():
    """Unit-level: exact frames required; 60->30 and drops fail; VFR
    passes only with pts_exact false."""
    mod = _load_mod()
    src = {"frames": 600, "avg_fps": 60.0, "r_fps": 60.0, "duration": 10.0}
    ok, ev = mod._compare_cadence_video(dict(src), dict(src))
    assert ok is True
    assert ev["pts_exact_claimed"] is False
    bad30 = {"frames": 300, "avg_fps": 30.0, "r_fps": 30.0, "duration": 10.0}
    ok2, _ = mod._compare_cadence_video(dict(src), bad30)
    assert ok2 is False
    drop = {"frames": 599, "avg_fps": 60.0, "r_fps": 60.0, "duration": 10.0}
    ok3, _ = mod._compare_cadence_video(dict(src), drop)
    assert ok3 is False


def test_edited_mov_rate_uses_decoded_timeline(tmp_path, monkeypatch):
    """Canary MOV rate metadata counts a different sample population.
    Source/output decode 302 frames over the same presented timeline."""
    mod = _load_mod()
    rc, payload, _ = _run(mod, monkeypatch, tmp_path, b"e2e-bytes-" * 4096,
                          source_mode="edited_mov_rate")
    assert rc == 0, payload
    ev = payload["details"]["cadence"]
    assert ev["source_reported_avg_fps"] == 31800 / 559
    assert ev["rate_basis"] == "decoded_frames_per_second"
    assert ev["source_fps"] == 302 / 5.036667
    assert ev["pts_exact_claimed"] is False
    source = {"frames": 302, "duration": 5.036667, "avg_fps": 31800 / 559}
    for bad in ({"frames": 301, "duration": 5.038367},
                {"frames": 151, "duration": 5.038367},
                {"frames": 302, "duration": 6.0},
                {"frames": 302, "duration": float("nan")},
                {"frames": 302, "duration": 0}):
        assert mod._compare_cadence_video(source, bad)[0] is False


def test_poster_cadence_na_explicit(tmp_path, monkeypatch):
    """Poster never fakes a video cadence boolean: still passes with an
    explicit N/A scope, and no source reference is required."""
    mod = _load_mod()
    data = b"poster-bytes-" * 1024
    rc, payload, _ = _run(mod, monkeypatch, tmp_path, data,
                           ctype="image/jpeg", slot="poster")
    assert rc == 0, payload
    assert payload["checks"]["frame_cadence_match"] is True
    assert payload["details"].get("video_cadence_applicable") is False
    assert "N/A" in str(payload["details"].get("frame_cadence_scope", ""))
    assert "source_bytes_sha_match" not in payload["checks"]


def test_range_content_type_strict(tmp_path, monkeypatch):
    """Range 206 with text/html (error page) is NOT proof: hq/light
    require video/mp4, poster requires image/jpeg."""
    mod = _load_mod()
    data = b"e2e-bytes-" * 4096
    rc, payload, _ = _run(mod, monkeypatch, tmp_path, data, ctype="text/html")
    assert rc == 2
    assert payload is not None
    assert payload["checks"]["range_206"] is False
    rc2, payload2, _ = _run(mod, monkeypatch, tmp_path, data,
                             ctype="image/jpeg", slot="poster")
    assert rc2 == 0, payload2
    assert payload2["checks"]["range_206"] is True


def test_ffprobe_bounded_no_unbounded_frame_list():
    """Bounded census uses -count_frames; never -show_frames/-show_packets
    (unbounded per-frame memory)."""
    import re as _re
    src = OPS_MOD.read_text()
    assert "-count_frames" in src
    # No actual ffprobe invocation may list per-frame entries (docstring
    # mentions are fine -- check only subprocess arg lists).
    for m in _re.finditer(r"subprocess\.run\(\[(.*?)\]", src, _re.S):
        assert "-show_frames" not in m.group(1)
        assert "-show_packets" not in m.group(1)


def test_source_integrity_proof_gate():
    """Proof gate: source_bytes_sha_match + original_storage_integrity_checked
    required; cadence_evidence + source_integrity_evidence required for
    video (exact frames, bound SHA, no PTS fabrication, poster never
    listed, B2 re-read method exact)."""
    import datetime as _dt
    import importlib.util as _ilu
    from pathlib import Path as _P

    ops_path = _P(__file__).resolve().parents[2] / "ops" / "canary_web_package.py"
    spec = _ilu.spec_from_file_location("canary_web_package_srcgate", ops_path)
    ops = _ilu.module_from_spec(spec)
    spec.loader.exec_module(ops)

    def _base():
        return {
            "video_uuid": "clip-src-1", "source_sha256": "a" * 64,
            "source_revision_id": 1, "transform_version": "ffmpeg-h264-web-v1",
            "slots": {"light": {"derivative_sha256": "b" * 64, "byte_size": 10},
                      "poster": {"derivative_sha256": "c" * 64, "byte_size": 10}},
            "checks": {n: True for n in ops.PROOF_REQUIRED_CHECKS},
            "cadence_evidence": {
                "source_sha256": "a" * 64,
                "source_frames": 600, "source_fps": 60.0, "source_duration": 10.0,
                "outputs": {"light": {"frames": 600, "fps": 60.0, "duration": 10.0}},
                "vfr": False, "pts_exact_claimed": False,
            },
            "source_integrity_evidence": {
                "sha": "a" * 64, "size": 18,
                "measured_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                "method": "full_get_after_publication",
            },
            "recorded_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "operator": "op",
        }

    ops.validate_proof_record(_base())
    no_src = _base()
    no_src["checks"]["source_bytes_sha_match"] = False
    with pytest.raises(ValueError):
        ops.validate_proof_record(no_src)
    no_storage = _base()
    no_storage["checks"]["original_storage_integrity_checked"] = False
    with pytest.raises(ValueError):
        ops.validate_proof_record(no_storage)
    no_integrity = _base()
    del no_integrity["source_integrity_evidence"]
    with pytest.raises(ValueError):
        ops.validate_proof_record(no_integrity)
    bad_method = _base()
    bad_method["source_integrity_evidence"] = dict(
        bad_method["source_integrity_evidence"], method="local_hash")
    with pytest.raises(ValueError):
        ops.validate_proof_record(bad_method)
    bad_sha = _base()
    bad_sha["source_integrity_evidence"] = dict(
        bad_sha["source_integrity_evidence"], sha="b" * 64)
    with pytest.raises(ValueError):
        ops.validate_proof_record(bad_sha)
    leak = _base()
    leak["source_integrity_evidence"] = dict(
        leak["source_integrity_evidence"], presigned_url="https://b2.example.test/x")
    with pytest.raises(ValueError):
        ops.validate_proof_record(leak)
    no_ev = _base()
    del no_ev["cadence_evidence"]
    with pytest.raises(ValueError):
        ops.validate_proof_record(no_ev)
    downgrade = _base()
    downgrade["cadence_evidence"]["outputs"]["light"]["frames"] = 300
    with pytest.raises(ValueError):
        ops.validate_proof_record(downgrade)
    fab_pts = _base()
    fab_pts["cadence_evidence"]["pts_exact_claimed"] = True
    with pytest.raises(ValueError):
        ops.validate_proof_record(fab_pts)
    poster_listed = _base()
    poster_listed["cadence_evidence"]["outputs"]["poster"] = {
        "frames": 1, "fps": 1.0, "duration": 1.0}
    with pytest.raises(ValueError):
        ops.validate_proof_record(poster_listed)
    unbound = _base()
    unbound["cadence_evidence"]["source_sha256"] = "c" * 64
    with pytest.raises(ValueError):
        ops.validate_proof_record(unbound)


def test_real_ffmpeg_synthetic_60_preserved_and_30_reject(tmp_path):
    """Actual ffmpeg synthetic bytes: 60fps source vs identical 60fps
    output passes the bounded census; a 30fps transcode fails."""
    import shutil
    import subprocess

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe not installed")
    mod = _load_mod()
    src = tmp_path / "src60.mp4"
    out60 = tmp_path / "out60.mp4"
    out30 = tmp_path / "out30.mp4"
    try:
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", "testsrc=size=64x64:rate=60:duration=1",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart", str(src)],
                       check=True, timeout=120)
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-i", str(src),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "60",
                        "-movflags", "+faststart", str(out60)],
                       check=True, timeout=120)
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-i", str(src),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
                        "-movflags", "+faststart", str(out30)],
                       check=True, timeout=120)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"synthetic encode unavailable: {exc}")
    s_info = mod._ffprobe_video_info(src, 60)
    o60 = mod._ffprobe_video_info(out60, 60)
    o30 = mod._ffprobe_video_info(out30, 60)
    assert "error" not in s_info, s_info
    assert "error" not in o60, o60
    assert "error" not in o30, o30
    ok, _ = mod._compare_cadence_video(s_info, o60)
    assert ok is True
    ok2, ev2 = mod._compare_cadence_video(s_info, o30)
    assert ok2 is False, ev2


# --- B2 source re-read (actual stored original, not local scratch) ---

def test_b2_source_sha_wrong_refused(tmp_path, monkeypatch, capsys):
    """Fake-HTTP source bytes not matching the canonical SHA: B2 re-read
    fails closed, no evidence emitted, no secrets leaked."""
    mod = _load_mod()
    data = b"e2e-bytes-" * 4096
    rc, payload, opener = _run(mod, monkeypatch, tmp_path, data, mode="corrupt_source")
    assert rc == 2
    assert payload is not None
    assert payload["checks"]["source_bytes_sha_match"] is False
    assert payload["checks"]["original_storage_integrity_checked"] is False
    assert "source_integrity_evidence" not in payload["details"]
    assert opener.cookie_to_storage == 0
    blob = json.dumps(payload, sort_keys=True)
    out = capsys.readouterr()
    hay = blob + out.out + out.err
    assert "X-Amz-" not in hay
    assert SOURCE_PRESIGNED not in hay
    assert "operator-private-value" not in hay


def test_b2_source_url_missing_refuses(tmp_path, monkeypatch):
    """Missing --source-storage-url-file: local reference alone never
    proves B2; both source checks stay false (fail closed)."""
    mod = _load_mod()
    data = b"e2e-bytes-" * 4096
    rc, payload, opener = _run(mod, monkeypatch, tmp_path, data, source_mode="missing")
    assert rc == 2
    assert payload is not None
    assert payload["checks"]["source_bytes_sha_match"] is False
    assert payload["checks"]["original_storage_integrity_checked"] is False
    assert payload["checks"]["frame_cadence_match"] is False
    assert "source_integrity_evidence" not in payload["details"]
    assert opener.cookie_to_storage == 0


def test_b2_expected_source_size_over_limit_fails(tmp_path, monkeypatch):
    """Expected canonical size above the bounded fetch cap: refuse before
    any second original transfer (fail closed)."""
    mod = _load_mod()
    data = b"e2e-bytes-" * 4096
    src_len = len(b"source-original-" * 1024)
    rc, payload, opener = _run(
        mod, monkeypatch, tmp_path, data,
        expected_source_size=src_len + 1, source_max_bytes=src_len,
    )
    assert rc == 2
    assert payload is not None
    assert payload["checks"]["source_bytes_sha_match"] is False
    assert payload["checks"]["original_storage_integrity_checked"] is False
    # Bounded: the oversized expectation is refused without fetching source bytes.
    assert not any("/file/source/key" in u for u, _, _ in opener.requests)


def test_b2_source_good_after_output_download_passes(tmp_path, monkeypatch, capsys):
    """Actual good B2 source AFTER the derivative GET (hashed + reference
    cross-checked): evidence emitted, temp reused, no secrets serialized,
    storage stays credential-free."""
    mod = _load_mod()
    data = b"e2e-bytes-" * 4096
    rc, payload, opener = _run(mod, monkeypatch, tmp_path, data, source_mode="match")
    assert rc == 0, payload
    assert payload["checks"]["source_bytes_sha_match"] is True
    assert payload["checks"]["original_storage_integrity_checked"] is True
    ev = payload["details"]["source_integrity_evidence"]
    assert ev["sha"] == _sha(b"source-original-" * 1024)
    assert ev["size"] == len(b"source-original-" * 1024)
    assert ev["method"] == "full_get_after_publication"
    assert ev["measured_at"]
    # No URL/secrets serialized.
    blob = json.dumps(payload, sort_keys=True)
    assert SOURCE_PRESIGNED not in blob
    assert "X-Amz-" not in blob
    assert "operator-private-value" not in blob
    out = capsys.readouterr()
    assert SOURCE_PRESIGNED not in (out.out + out.err)
    # Derivative GET happened before the source re-read (order preserved).
    urls = [u for u, _, _ in opener.requests]
    assert any("/file/bucket/key" in u for u in urls)
    assert any("/file/source/key" in u for u in urls)
    first_deriv = next(i for i, u in enumerate(urls) if "/file/bucket/key" in u)
    first_source = next(i for i, u in enumerate(urls) if "/file/source/key" in u)
    assert first_deriv < first_source, "B2 source re-read must follow the derivative GET"
    # Credential-free storage (derivative + source + expiry replay).
    assert opener.cookie_to_storage == 0
