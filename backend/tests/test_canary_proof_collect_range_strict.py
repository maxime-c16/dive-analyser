"""Strict HTTP Range 206 byte-proof tests (no network, no prod, no auth).

The collector must prove a 206 Range response is the EXACT prefix of the
SHA-verified full GET -- not just 206 + a plausible Content-Range prefix +
MIME. Covers: correct-metadata/WRONG-bytes refused, empty/truncated/
overlong bodies refused, total/end mismatches refused, exact-prefix pass,
tiny-file (< probe) pass, ignored-Range 200 refused.
"""

import hashlib
import importlib.util
import json
import urllib.request
from pathlib import Path

OPS_MOD = Path(__file__).resolve().parents[2] / "ops" / "canary_proof_collect.py"

PLAY_URL = "https://library.example.test/play/slot-1"
LIB_ORIGIN = "https://library.example.test"
STO_ORIGIN = "https://b2.example.test"
PRESIGNED = "https://b2.example.test/file/bucket/key?X-Amz-Expires=3600&X-Amz-Date=20300101T000000Z"
EXPIRED_URL = "https://b2.example.test/file/bucket/key?Expires=1000000000"


def _load_mod():
    spec = importlib.util.spec_from_file_location("canary_proof_collect_range_strict", OPS_MOD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


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
            chunk = self._body[self._pos:]
            self._pos = len(self._body)
            return chunk
        chunk = self._body[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeOpener:
    """Library 302 + credential-free storage with controllable Range shape."""

    def __init__(self, data: bytes, ctype="image/jpeg", range_mode="ok"):
        self.data = data
        self.ctype = ctype
        self.range_mode = range_mode
        self.requests: list = []

    def open(self, req, timeout=None):
        url = req.full_url
        cookie = req.get_header("Cookie")
        auth = req.get_header("Authorization")
        rng = req.get_header("Range")
        self.requests.append((url, bool(cookie), rng))
        assert url == PLAY_URL or url.startswith("https://b2.example.test/"), url
        if url == PLAY_URL:
            if rng:
                return _FakeResp(400, {}, b"range must target storage")
            if not cookie:
                return _FakeResp(403, {"Content-Type": "text/plain"}, b"denied")
            return _FakeResp(302, {"Location": PRESIGNED}, b"")
        if cookie or auth:
            raise AssertionError("storage fetch carried credentials")
        if url == EXPIRED_URL:
            return _FakeResp(403, {"Content-Type": "text/plain"}, b"expired")
        if rng:
            return self._range()
        return _FakeResp(200, {"Content-Type": self.ctype}, self.data)

    def _range(self):
        n = len(self.data)
        exp_end = min(1023, n - 1)
        exp_len = exp_end + 1
        prefix = self.data[:exp_len]
        cr_ok = f"bytes 0-{exp_end}/{n}"
        mode = self.range_mode
        if mode == "ok":
            return _FakeResp(206, {"Content-Range": cr_ok, "Content-Type": self.ctype}, prefix)
        if mode == "content_length_ok":
            return _FakeResp(
                206,
                {"Content-Range": cr_ok, "Content-Type": self.ctype,
                 "Content-Length": str(exp_len)},
                prefix,
            )
        if mode == "wrong_bytes":
            return _FakeResp(206, {"Content-Range": cr_ok, "Content-Type": self.ctype},
                             b"W" * exp_len)
        if mode == "empty":
            return _FakeResp(206, {"Content-Range": cr_ok, "Content-Type": self.ctype}, b"")
        if mode == "truncated":
            return _FakeResp(206, {"Content-Range": cr_ok, "Content-Type": self.ctype},
                             prefix[:exp_len // 2])
        if mode == "overlong":
            return _FakeResp(206, {"Content-Range": cr_ok, "Content-Type": self.ctype},
                             prefix + b"EXTRA")
        if mode == "total_mismatch":
            return _FakeResp(206, {"Content-Range": f"bytes 0-{exp_end}/{n + 100}",
                                  "Content-Type": self.ctype}, prefix)
        if mode == "end_mismatch":
            bad_end = max(0, exp_end - 512)
            return _FakeResp(206, {"Content-Range": f"bytes 0-{bad_end}/{n}",
                                  "Content-Type": self.ctype},
                             self.data[:bad_end + 1])
        if mode == "range_200":
            return _FakeResp(200, {"Content-Type": self.ctype}, prefix)
        if mode == "content_length_mismatch":
            return _FakeResp(
                206,
                {"Content-Range": cr_ok, "Content-Type": self.ctype,
                 "Content-Length": str(exp_len + 7)},
                prefix,
            )
        raise AssertionError(f"unknown range_mode {mode!r}")


def _run(mod, monkeypatch, tmp_path, data, range_mode="ok", ctype="image/jpeg"):
    opener = _FakeOpener(data, ctype=ctype, range_mode=range_mode)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **k: opener)
    monkeypatch.setattr(mod, "_ffprobe", lambda *a, **k: (True, True, {"format": "jpeg"}))
    cookie = tmp_path / "cookies.txt"
    cookie.write_text("session=operator-private-value")
    cookie.chmod(0o600)
    out = tmp_path / "proof-frag.json"
    argv = [
        "--play-url", PLAY_URL,
        "--library-origin", LIB_ORIGIN,
        "--storage-origin", STO_ORIGIN,
        "--expired-url", EXPIRED_URL,
        "--expected-sha", _sha(data),
        "--expected-size", str(len(data)),
        "--cookies", str(cookie),
        "--slot", "poster",
        "--video-uuid", "clip-range-1",
        "--operator", "op",
        "--out", str(out),
    ]
    rc = mod.main(argv)
    payload = json.loads(out.read_text()) if out.exists() else None
    return rc, payload, opener


def _assert_no_leak(capsys, payload):
    blob = json.dumps(payload, sort_keys=True) if payload else ""
    out = capsys.readouterr()
    hay = blob + out.out + out.err
    assert "X-Amz-" not in hay
    assert "operator-private-value" not in hay
    assert "https://b2.example.test/file" not in hay


def test_exact_prefix_passes(tmp_path, monkeypatch, capsys):
    mod = _load_mod()
    data = b"poster-bytes-" * 1024
    rc, payload, opener = _run(mod, monkeypatch, tmp_path, data, "ok")
    assert rc == 0, payload
    assert payload["checks"]["range_206"] is True
    assert payload["checks"]["b2_full_get_sha_match"] is True
    ranges = [r for _, _, r in opener.requests if r]
    assert ranges and all(r == "bytes=0-1023" for r in ranges)
    _assert_no_leak(capsys, payload)


def test_content_length_match_passes(tmp_path, monkeypatch):
    mod = _load_mod()
    data = b"poster-bytes-" * 1024
    rc, payload, _ = _run(mod, monkeypatch, tmp_path, data, "content_length_ok")
    assert rc == 0, payload
    assert payload["checks"]["range_206"] is True


def test_wrong_bytes_with_correct_metadata_fails(tmp_path, monkeypatch, capsys):
    mod = _load_mod()
    data = b"poster-bytes-" * 1024
    rc, payload, _ = _run(mod, monkeypatch, tmp_path, data, "wrong_bytes")
    assert rc == 2
    assert payload is not None
    assert payload["checks"]["range_206"] is False
    assert payload["checks"]["b2_full_get_sha_match"] is True
    _assert_no_leak(capsys, payload)


def test_empty_body_fails(tmp_path, monkeypatch):
    mod = _load_mod()
    rc, payload, _ = _run(mod, monkeypatch, tmp_path, b"poster-bytes-" * 1024, "empty")
    assert rc == 2
    assert payload["checks"]["range_206"] is False


def test_truncated_body_fails(tmp_path, monkeypatch):
    mod = _load_mod()
    rc, payload, _ = _run(mod, monkeypatch, tmp_path, b"poster-bytes-" * 1024, "truncated")
    assert rc == 2
    assert payload["checks"]["range_206"] is False


def test_overlong_body_fails(tmp_path, monkeypatch):
    mod = _load_mod()
    rc, payload, _ = _run(mod, monkeypatch, tmp_path, b"poster-bytes-" * 1024, "overlong")
    assert rc == 2
    assert payload["checks"]["range_206"] is False


def test_total_mismatch_fails(tmp_path, monkeypatch):
    mod = _load_mod()
    rc, payload, _ = _run(mod, monkeypatch, tmp_path, b"poster-bytes-" * 1024,
                          "total_mismatch")
    assert rc == 2
    assert payload["checks"]["range_206"] is False


def test_end_mismatch_fails(tmp_path, monkeypatch):
    mod = _load_mod()
    rc, payload, _ = _run(mod, monkeypatch, tmp_path, b"poster-bytes-" * 1024,
                          "end_mismatch")
    assert rc == 2
    assert payload["checks"]["range_206"] is False


def test_tiny_file_passes(tmp_path, monkeypatch):
    mod = _load_mod()
    data = b"t" * 500
    rc, payload, opener = _run(mod, monkeypatch, tmp_path, data, "ok")
    assert rc == 0, payload
    assert payload["checks"]["range_206"] is True
    assert payload["details"]["range_content_range"] == "bytes 0-499/500"


def test_ignored_range_200_fails(tmp_path, monkeypatch):
    mod = _load_mod()
    rc, payload, _ = _run(mod, monkeypatch, tmp_path, b"poster-bytes-" * 1024,
                          "range_200")
    assert rc == 2
    assert payload["checks"]["range_206"] is False


def test_content_length_mismatch_fails(tmp_path, monkeypatch):
    mod = _load_mod()
    rc, payload, _ = _run(mod, monkeypatch, tmp_path, b"poster-bytes-" * 1024,
                          "content_length_mismatch")
    assert rc == 2
    assert payload["checks"]["range_206"] is False
