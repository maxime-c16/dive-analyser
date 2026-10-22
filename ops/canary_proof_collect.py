#!/usr/bin/env python3
"""Bounded read-only canary proof collector (no auth minting, no writes to prod).

Fetches operator-supplied authorized Library playback bytes with the
OPERATOR's own private session cookies and proves them fail-closed:

- full GET (streamed SHA-256 + size vs expected ledger values);
- authorized route behavior (302 to presigned B2 with explicit expiry);
- Range 206 with content-type;
- logged-out (no-cookie) request denied;
- ffprobe clean (container/codec/faststart) + frame cadence > 0 (video) /
  single still (poster).

The operator performs the browser login themselves (device Safari, normal
session) and exports their session cookie to a PRIVATE file OUTSIDE the repo
(0600, e.g. ``~/.config/diveanalyzer/canary-cookies.txt`` in curl ``-b``
``name=value`` form). This script NEVER mints auth (no login/token/API-key
flags, no credential endpoints) and NEVER prints cookie material. All
network calls are bounded read-only GETs (no POST/PUT/DELETE); any check
that cannot be performed fails CLOSED (false + exit 2).

Output: a structured JSON fragment (checks + details) written OUTSIDE the
repo, suitable for embedding in the manual proof record validated by
``ops/canary_proof_check.py`` / ``prove``. Fakes only in tests; never run
this against prod B2 in CI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_302_HOSTS = ("b2", "backblaze", "s3")


def _refuse_inside_git(path: Path, what: str) -> None:
    p = path.resolve()
    for parent in [p] + list(p.parents):
        if (parent / ".git").exists():
            raise SystemExit(
                f"REFUSED: {what} {p} sits inside a git checkout "
                f"({parent}/.git). Keep operator secrets outside the repo."
            )


def _check_mode_0600(path: Path, what: str) -> None:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        return
    if mode & 0o077:
        print(
            f"WARNING: {what} {path} has mode {oct(mode)} (expected 0600); "
            "fix with: chmod 600 " + str(path),
            file=sys.stderr,
        )


def _load_cookies(path: Path) -> str:
    _refuse_inside_git(path, "cookie file")
    _check_mode_0600(path, "cookie file")
    try:
        raw = path.read_text().strip()
    except FileNotFoundError:
        raise SystemExit(f"REFUSED: cookie file not found: {path}")
    if not raw:
        raise SystemExit("REFUSED: cookie file is empty (export your session cookie first)")
    # Accept either raw `name=value[; ...]` or a Netscape jar (extract last fields).
    parts: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:
            fields = line.split("\t")
            if len(fields) >= 7:
                parts.append(f"{fields[-2].strip()}={fields[-1].strip()}")
            continue
        parts.append(line.rstrip(";"))
    header = "; ".join(p for p in parts if p)
    if not header or "=" not in header:
        raise SystemExit("REFUSED: cookie file has no usable name=value pair")
    if len(header) > 8192:
        raise SystemExit("REFUSED: cookie header implausibly long; refusing")
    return header


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _get(url: str, cookie: str | None, timeout: int, range_hdr: str | None = None,
         follow_redirects: bool = True) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url)
    if cookie:
        req.add_header("Cookie", cookie)
    if range_hdr:
        req.add_header("Range", range_hdr)
    if follow_redirects:
        opener = urllib.request.build_opener()
    else:
        opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", 200))
            headers = {k.lower(): v for k, v in resp.getheaders()}
            body = resp.read()
            return status, headers, body
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read()
        except Exception:
            body = b""
        headers = {k.lower(): v for k, v in (exc.headers.items() if exc.headers else [])}
        return int(exc.code), headers, body


def _stream_hash(url: str, cookie: str, timeout: int, max_bytes: int) -> tuple[str, int, str]:
    """Streamed full GET: returns (sha256, size, content_type). Bounded."""
    req = urllib.request.Request(url)
    req.add_header("Cookie", cookie)
    opener = urllib.request.build_opener()
    digest = hashlib.sha256()
    size = 0
    ctype = ""
    with opener.open(req, timeout=timeout) as resp:
        status = int(getattr(resp, "status", 200))
        if status not in (200, 206):
            raise ValueError(f"full GET returned HTTP {status} (expected 200)")
        ctype = (resp.getheader("Content-Type") or "").split(";")[0].strip().lower()
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                raise ValueError(f"GET exceeded max-bytes {max_bytes}; refusing")
            digest.update(chunk)
    return digest.hexdigest(), size, ctype


def _ffprobe(path: Path, slot: str, timeout: int) -> tuple[bool, bool, dict]:
    """Returns (clean, cadence_ok, summary). False-closed when ffprobe missing/fails."""
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_format", "-show_streams",
             "-print_format", "json", str(path)],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        return False, False, {"error": "ffprobe not installed"}
    except subprocess.TimeoutExpired:
        return False, False, {"error": "ffprobe timed out"}
    if proc.returncode != 0:
        out = (proc.stderr or "")[:500]
        return False, False, {"error": f"ffprobe refused input: {out}"}
    try:
        info = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return False, False, {"error": "ffprobe output not JSON"}
    streams = info.get("streams", []) or []
    fmt = info.get("format", {}) or {}
    fmt_name = str(fmt.get("format_name", "") or "").lower()
    clean = bool(streams)
    if slot == "poster":
        clean = clean and ("mjpeg" in fmt_name or "jpeg" in fmt_name or "image" in fmt_name
                           or any("mjpeg" in str(s.get("codec_name", "")).lower()
                                   or "jpeg" in str(s.get("codec_name", "")).lower()
                                   for s in streams))
        cadence = clean and len(streams) >= 1
    else:
        vstreams = [s for s in streams if str(s.get("codec_type", "")).lower() == "video"]
        codecs = {str(s.get("codec_name", "")).lower() for s in vstreams}
        clean = clean and bool(vstreams) and ("h264" in codecs or "avc" in codecs)
        clean = clean and ("mp4" in fmt_name or "mov" in fmt_name)
        frames = 0
        try:
            for s in vstreams:
                for k in ("nb_frames", "nb_read_frames"):
                    v = s.get(k)
                    if v is not None:
                        frames = max(frames, int(v))
        except (TypeError, ValueError):
            frames = 0
        if frames <= 0:
            try:
                dur = float(fmt.get("duration") or 0)
                rfr = str((vstreams[0].get("r_frame_rate") if vstreams else "") or "")
                if "/" in rfr:
                    num, den = rfr.split("/", 1)
                    fps = float(num) / float(den) if float(den) else 0
                    frames = int(dur * fps)
            except (TypeError, ValueError, ZeroDivisionError):
                frames = 0
        cadence = clean and frames > 0
    summary = {
        "format": fmt_name[:80],
        "nb_streams": len(streams),
        "duration": str(fmt.get("duration", ""))[:32],
        "size": str(fmt.get("size", ""))[:32],
    }
    return clean, cadence, summary


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Collect read-only canary proof evidence (no auth minting).")
    ap.add_argument("--play-url", required=True, help="authorized Library play URL (302 to presigned B2)")
    ap.add_argument("--expected-sha", required=True, help="ledger derivative_blob_sha256 (64 hex)")
    ap.add_argument("--expected-size", required=True, type=int, help="ledger byte_size")
    ap.add_argument("--cookies", required=True, help="private cookie file OUTSIDE repo (0600, your session)")
    ap.add_argument("--slot", required=True, choices=["hq", "light", "poster"])
    ap.add_argument("--video-uuid", required=True)
    ap.add_argument("--operator", required=True)
    ap.add_argument("--out", required=True, help="output JSON path OUTSIDE repo")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--max-bytes", type=int, default=1_200_000_000)
    ap.add_argument("--ffprobe-timeout", type=int, default=60)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    sha = str(args.expected_sha or "").strip().lower()
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        print("REFUSED: --expected-sha must be 64 lower-hex")
        return 2
    if int(args.expected_size) <= 0:
        print("REFUSED: --expected-size must be > 0")
        return 2
    cookie_path = Path(args.cookies)
    out_path = Path(args.out)
    _refuse_inside_git(out_path, "output file")
    cookie = _load_cookies(cookie_path)
    if not args.operator.strip():
        print("REFUSED: --operator is required")
        return 2

    checks = {
        "b2_full_get_sha_match": False,
        "ffprobe_clean": False,
        "frame_cadence_match": False,
        "library_auth_302": False,
        "range_206": False,
        "grant_expiry_checked": False,
        "logged_out_denied": False,
    }
    details: dict = {"slot": args.slot, "video_uuid": args.video_uuid}

    # 1. Authorized route must 302 to a presigned B2 URL (no redirects followed).
    try:
        st, hdrs, _ = _get(args.play_url, cookie, timeout=15, follow_redirects=False)
    except Exception as exc:
        print(f"REFUSED: play URL unreachable: {type(exc).__name__}")
        return 2
    location = (hdrs.get("location") or "").strip()
    if st == 302 and location.lower().startswith("https://"):
        checks["library_auth_302"] = True
        details["presigned_host"] = urllib.parse.urlparse(location).hostname or ""
        q = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
        flat = {k: (v[0] if v else "") for k, v in q.items()}
        expiry = (
            flat.get("X-Amz-Expires") or flat.get("Expires") or flat.get("expires") or ""
        )
        details["presigned_expiry"] = str(expiry)[:64]
        # Hard gate: the presigned URL must carry an explicit expiry; an
        # everlasting grant URL fails closed (expired-replay denial stays a
        # manual operator step recorded in the final proof record).
        checks["grant_expiry_checked"] = bool(str(expiry).strip())
    else:
        print(f"REFUSED: play URL returned HTTP {st} (expected 302 to presigned B2)")
        _write_out(out_path, args, checks, details)
        return 2

    # 2. Logged-out request (no cookies) must be denied (never 200 with bytes).
    try:
        st2, _, body2 = _get(args.play_url, None, timeout=15, follow_redirects=False)
    except Exception:
        st2, body2 = 0, b""
    checks["logged_out_denied"] = st2 in (401, 403, 404) or (st2 in (302, 307) and True) and st2 != 200
    if st2 == 200 and body2:
        checks["logged_out_denied"] = False
    if not checks["logged_out_denied"]:
        print(f"REFUSED: logged-out play URL returned HTTP {st2} (expected denial)")
        _write_out(out_path, args, checks, details)
        return 2

    # 3. Range 206 with content-type (authorized).
    try:
        st3, hdrs3, body3 = _get(args.play_url, cookie, timeout=15, range_hdr="bytes=0-1023")
    except Exception as exc:
        print(f"REFUSED: range request failed: {type(exc).__name__}")
        _write_out(out_path, args, checks, details)
        return 2
    cr = (hdrs3.get("content-range") or "")
    ct3 = (hdrs3.get("content-type") or "").split(";")[0].strip().lower()
    if st3 == 206 and cr.startswith("bytes 0-1023/") and ct3:
        checks["range_206"] = True
        details["range_content_type"] = ct3
    else:
        print(f"REFUSED: range request returned HTTP {st3} (expected 206 with Content-Range)")
        _write_out(out_path, args, checks, details)
        return 2

    # 4. Full GET + SHA + size (authorized, streamed, bounded).
    tmp = None
    try:
        fd, tmppath = tempfile.mkstemp(prefix="canary-proof-", suffix=".bin")
        os.close(fd)
        tmp = Path(tmppath)
        # Stream to file while hashing (bounded): reuse _stream_hash logic inline.
        req = urllib.request.Request(args.play_url)
        req.add_header("Cookie", cookie)
        digest = hashlib.sha256()
        size = 0
        ctype = ""
        opener = urllib.request.build_opener()
        with opener.open(req, timeout=args.timeout) as resp:
            status = int(getattr(resp, "status", 200))
            if status not in (200, 206):
                print(f"REFUSED: full GET returned HTTP {status} (expected 200)")
                _write_out(out_path, args, checks, details)
                return 2
            ctype = (resp.getheader("Content-Type") or "").split(";")[0].strip().lower()
            with open(tmp, "wb") as fh:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > int(args.max_bytes):
                        print(f"REFUSED: download exceeded --max-bytes {args.max_bytes}")
                        _write_out(out_path, args, checks, details)
                        return 2
                    digest.update(chunk)
                    fh.write(chunk)
        got_sha = digest.hexdigest()
        details.update({"byte_size": size, "sha256": got_sha, "content_type": ctype})
        checks["b2_full_get_sha_match"] = (got_sha == sha and size == int(args.expected_size))
        if not checks["b2_full_get_sha_match"]:
            print(f"REFUSED: full-GET sha/size mismatch (got {got_sha[:12]}.../{size})")
            _write_out(out_path, args, checks, details)
            return 2
        # 5. ffprobe clean + frame cadence on the downloaded bytes.
        clean, cadence, summary = _ffprobe(tmp, args.slot, timeout=args.ffprobe_timeout)
        details["ffprobe"] = summary
        checks["ffprobe_clean"] = clean
        checks["frame_cadence_match"] = cadence
        if not (clean and cadence):
            print("REFUSED: ffprobe checks failed (see output ffprobe summary)")
            _write_out(out_path, args, checks, details)
            return 2
    except urllib.error.HTTPError as exc:
        print(f"REFUSED: full GET returned HTTP {exc.code}")
        _write_out(out_path, args, checks, details)
        return 2
    except Exception as exc:
        print(f"REFUSED: full GET failed: {type(exc).__name__}")
        _write_out(out_path, args, checks, details)
        return 2
    finally:
        try:
            if tmp is not None and tmp.exists():
                tmp.unlink()
        except Exception:
            pass

    _write_out(out_path, args, checks, details)
    missing = [k for k, v in checks.items() if v is not True]
    if missing:
        print(f"REFUSED: checks false: {missing}")
        return 2
    print(f"PROOF-COLLECT OK slot={args.slot} bytes={details.get('byte_size')} "
          f"sha={sha[:12]}... checks=all-true -> {out_path}")
    return 0


def _write_out(out_path: Path, args, checks: dict, details: dict) -> None:
    payload = {
        "video_uuid": args.video_uuid,
        "slot": args.slot,
        "expected_sha256": str(args.expected_sha).lower(),
        "expected_size": int(args.expected_size),
        "checks": dict(checks),
        "details": details,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "operator": args.operator,
        "tool": "canary_proof_collect",
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    os.chmod(tmp, 0o600)
    os.replace(tmp, out_path)


if __name__ == "__main__":
    raise SystemExit(main())
