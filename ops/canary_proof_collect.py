#!/usr/bin/env python3
"""Bounded read-only canary proof collector (no auth minting, no writes to prod).

Fetches operator-supplied authorized Library playback bytes with the
OPERATOR's own private session cookies and proves them fail-closed:

- full GET (streamed SHA-256 + size vs expected ledger values);
- authorized route behavior (302 to presigned B2 with explicit expiry);
- Range 206 with content-type;
- logged-out (no-cookie) request denied (401/403/404 only);
- measured expired-grant replay denial for the EXACT object;
- ffprobe clean (container/codec/faststart) + frame cadence > 0 (video) /
  single still (poster).

Credential separation (fail closed): the session cookie is sent ONLY to
the explicit, validated ``--library-origin`` (https; http is allowed
solely for loopback test origins). The authorized request NEVER follows
redirects: the 302 ``Location`` is validated as an explicitly
allowlisted ``--storage-origin`` (https, no userinfo, no private /
untrusted host, origin distinct from the Library) and the storage bytes
(Range probe, full GET, expired-grant replay) are fetched in SEPARATE
requests that carry NO Cookie/Authorization headers at all. Storage
redirects are followed manually, hop by hop, with every hop
re-validated and still credential-free; anything else is refused before
any further fetch. Proof URLs from user args are never trusted for
cookie targeting: a play URL whose origin differs from the explicit
``--library-origin`` is refused without sending cookies anywhere.

The operator performs the browser login themselves (their own browser
session) and exports their session cookie to a PRIVATE file OUTSIDE the
repo (0600, e.g. ``~/.config/diveanalyzer/canary-cookies.txt`` in curl
``-b`` ``name=value`` form). This script NEVER mints auth (no
login/token/API-key flags, no credential endpoints) and NEVER prints
cookie material. All network calls are bounded read-only GETs (no
POST/PUT/DELETE); any check that cannot be performed fails CLOSED
(false + exit 2).

``grant_expiry_checked`` is NEVER derived from the mere presence of an
expiry parameter on the live grant. It is true ONLY when an
operator-supplied expired grant URL for the EXACT same object
(``--expired-url``, same storage origin + path, expiry timestamp
provably in the past via ``--expired-at`` or the URL's own
Expires/X-Amz-Date+X-Amz-Expires fields) is replayed WITHOUT
credentials and the storage host denies it (401/403/404). There is no
wait loop: a live grant's TTL (default 120 s) is never waited out. Omit
``--expired-url`` and the check stays false -- an unexpired grant's
expiry parameter alone never passes the final proof gate.

Output: a structured JSON fragment (checks + details) written OUTSIDE
the repo, suitable for embedding in the manual proof record validated
by ``ops/canary_proof_check.py`` / ``prove``. Fakes only in tests;
never run this against prod B2 in CI. Device/browser playback (e.g. a
physical-device pass) is NOT claimed by this tool.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import stat
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

DENIED_STATUSES = (401, 403, 404)
REDIRECT_STATUSES = (301, 302, 303, 307, 308)
MAX_STORAGE_HOPS = 4
SMALL_BODY_LIMIT = 4 * 1024 * 1024

_CREDENTIAL_HEADERS = ("cookie", "authorization", "proxy-authorization")


class _Refused(Exception):
    """Fail-closed validation refusal (message is safe to print: no secrets)."""


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


def _is_loopback_host(host: str) -> bool:
    h = host.strip().lower().rstrip(".")
    if h == "localhost":
        return True
    try:
        return ipaddress.ip_address(h.strip("[]")).is_loopback
    except ValueError:
        return False


def _is_non_loopback_private_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return bool(
        (ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast)
        and not ip.is_loopback
    )


def _checked_split(url: str, what: str) -> urllib.parse.SplitResult:
    try:
        u = urllib.parse.urlsplit((url or "").strip())
    except ValueError as exc:
        raise _Refused(f"{what}: unparseable URL ({exc})")
    if u.username or u.password:
        raise _Refused(f"{what}: URL embeds userinfo; refusing (credential leak risk)")
    scheme = u.scheme.lower()
    host = (u.hostname or "").lower()
    if not host:
        raise _Refused(f"{what}: URL has no host; refusing")
    if scheme == "https":
        pass
    elif scheme == "http" and _is_loopback_host(host):
        pass  # explicit local-test allowance only
    else:
        raise _Refused(
            f"{what}: scheme must be https (http is allowed only for loopback test origins)"
        )
    if _is_non_loopback_private_ip(host):
        raise _Refused(f"{what}: private/link-local host; refusing")
    return u


def _origin_tuple(u: urllib.parse.SplitResult) -> tuple[str, str, int]:
    scheme = u.scheme.lower()
    host = (u.hostname or "").lower()
    try:
        port = u.port
    except ValueError:
        raise _Refused("URL has an invalid port; refusing")
    return (scheme, host, port or (443 if scheme == "https" else 80))


def _parse_origin_flag(value: str, what: str) -> tuple[str, str, int]:
    raw = (value or "").strip()
    u = _checked_split(raw, what)
    if u.path not in ("", "/") or u.query or u.fragment:
        raise _Refused(f"{what}: must be a bare origin (scheme://host[:port]); refusing")
    return _origin_tuple(u)


def _validate_library_url(url: str, library_origin: tuple[str, str, int]):
    """Validate the play URL: only an exact match of the explicit Library
    origin may receive the session cookie."""
    u = _checked_split(url, "play URL")
    if _origin_tuple(u) != library_origin:
        raise _Refused(
            "play URL origin does not match the explicit --library-origin; "
            "refusing to attach cookies to an untrusted origin"
        )
    return u


def _validate_storage_url(
    url: str,
    *,
    library_origin: tuple[str, str, int],
    storage_origins: set[tuple[str, str, int]],
    what: str = "presigned URL",
):
    """Validate a storage URL: allowlisted origin, distinct from the
    Library, no userinfo/private/untrusted host."""
    u = _checked_split(url, what)
    origin = _origin_tuple(u)
    if origin == library_origin:
        raise _Refused(f"{what}: points back at the Library origin (expected storage); refusing")
    if origin not in storage_origins:
        raise _Refused(f"{what}: host is not in the explicit --storage-origin allowlist; refusing")
    return u


def _get_once(
    url: str, *, headers: dict[str, str], timeout: int
) -> tuple[int, dict, bytes]:
    """One HTTP GET with NO redirect following. Sends ONLY the headers
    given. Library probes pass the session Cookie here (after origin
    validation); storage callers must use _storage_get /
    _storage_stream_to_file, which forbid credential headers."""
    req = urllib.request.Request(url)
    for k, v in headers.items():
        req.add_header(k, v)
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", 200))
            hdrs = {k.lower(): v for k, v in resp.getheaders()}
            return status, hdrs, resp.read()
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read()
        except Exception:
            body = b""
        try:
            hdrs = {k.lower(): v for k, v in (exc.headers.items() if exc.headers else [])}
        except Exception:
            hdrs = {}
        return int(exc.code), hdrs, body


def _storage_get(
    url: str,
    *,
    library_origin: tuple[str, str, int],
    storage_origins: set[tuple[str, str, int]],
    timeout: int,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, dict, bytes, str]:
    """Credential-free GET of a validated storage URL. Follows redirects
    manually, re-validating EVERY hop as allowlisted storage; never sends
    Cookie/Authorization. Returns (status, headers, body, final_url)."""
    current = url
    for _ in range(MAX_STORAGE_HOPS):
        _validate_storage_url(
            current,
            library_origin=library_origin,
            storage_origins=storage_origins,
            what="storage URL",
        )
        status, hdrs, body = _get_once(current, headers=dict(extra_headers or {}), timeout=timeout)
        if status in REDIRECT_STATUSES:
            loc = (hdrs.get("location") or "").strip()
            if not loc:
                raise _Refused("storage redirect without Location; refusing")
            current = urllib.parse.urljoin(current, loc)
            continue
        if len(body) > SMALL_BODY_LIMIT:
            raise _Refused("storage probe body exceeds bound; refusing")
        return status, hdrs, body, current
    raise _Refused("too many storage redirects; refusing")


class _StorageStatus(Exception):
    def __init__(self, status: int):
        super().__init__(f"storage returned HTTP {status}")
        self.status = status


def _storage_stream_to_file(
    url: str,
    path: Path,
    *,
    library_origin: tuple[str, str, int],
    storage_origins: set[tuple[str, str, int]],
    timeout: int,
    max_bytes: int,
    extra_headers: dict[str, str] | None = None,
) -> tuple[str, int, str, str]:
    """Credential-free streamed GET of validated storage bytes to `path`
    while hashing. Returns (sha256, size, content_type, final_url)."""
    headers = dict(extra_headers or {})
    for k in headers:
        if k.lower() in _CREDENTIAL_HEADERS:
            raise _Refused(f"refusing to send credential header {k!r} on a storage fetch")
    current = url
    for _ in range(MAX_STORAGE_HOPS):
        _validate_storage_url(
            current,
            library_origin=library_origin,
            storage_origins=storage_origins,
            what="storage URL",
        )
        req = urllib.request.Request(current)
        for k, v in headers.items():
            req.add_header(k, v)
        opener = urllib.request.build_opener(_NoRedirect())
        try:
            resp = opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            code = int(exc.code)
            if code in REDIRECT_STATUSES:
                try:
                    loc = (exc.headers.get("Location") or "").strip() if exc.headers else ""
                except Exception:
                    loc = ""
                try:
                    exc.close()
                except Exception:
                    pass
                if not loc:
                    raise _Refused("storage redirect without Location; refusing")
                current = urllib.parse.urljoin(current, loc)
                continue
            raise _StorageStatus(code)
        try:
            status = int(getattr(resp, "status", 200))
            if status in REDIRECT_STATUSES:
                loc = (resp.getheader("Location") or "").strip()
                if not loc:
                    raise _Refused("storage redirect without Location; refusing")
                current = urllib.parse.urljoin(current, loc)
                continue
            if status not in (200, 206):
                raise _StorageStatus(status)
            ctype = (resp.getheader("Content-Type") or "").split(";")[0].strip().lower()
            digest = hashlib.sha256()
            size = 0
            with open(path, "wb") as fh:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        raise _Refused(f"download exceeded max-bytes {max_bytes}")
                    digest.update(chunk)
                    fh.write(chunk)
            return digest.hexdigest(), size, ctype, current
        finally:
            try:
                resp.close()
            except Exception:
                pass
    raise _Refused("too many storage redirects; refusing")


def _parse_expiry_moment(
    explicit: str | None, query: dict[str, str]
) -> datetime | None:
    """Return the grant's expiry moment, or None when no PROVABLE past
    timestamp exists. Mere parameter presence never counts."""
    if explicit and explicit.strip():
        try:
            dt = datetime.fromisoformat(explicit.strip().replace("Z", "+00:00"))
        except ValueError:
            raise _Refused("--expired-at must be ISO-8601")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    exp = (query.get("Expires") or "").strip()
    if exp.isdigit():
        return datetime.fromtimestamp(int(exp), tz=timezone.utc)
    amz_date = (query.get("X-Amz-Date") or "").strip()
    amz_exp = (query.get("X-Amz-Expires") or "").strip()
    if amz_date and amz_exp.isdigit():
        try:
            base = datetime.strptime(amz_date, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
        try:
            return base + timedelta(seconds=int(amz_exp))
        except (OverflowError, ValueError):
            return None
    return None


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
    ap.add_argument("--play-url", required=True, help="authorized Library play URL (302 to presigned storage)")
    ap.add_argument("--library-origin", required=True,
                    help="explicit trusted Library origin (scheme://host[:port]); "
                         "the ONLY origin that ever receives the session cookie")
    ap.add_argument("--storage-origin", required=True, action="append",
                    help="explicit allowlisted storage origin (repeat or comma-separate); "
                         "presigned URLs and every redirect hop must match one")
    ap.add_argument("--expired-url", default=None,
                    help="operator-supplied EXPIRED grant URL for the EXACT same object "
                         "(same storage origin + path); replayed WITHOUT credentials to "
                         "measure denial. Omit and grant_expiry_checked stays false.")
    ap.add_argument("--expired-at", default=None,
                    help="ISO-8601 expiry moment of --expired-url (proves it is past); "
                         "optional when the URL itself carries Expires/X-Amz-Date+X-Amz-Expires")
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
    try:
        library_origin = _parse_origin_flag(args.library_origin, "--library-origin")
        storage_origins: set[tuple[str, str, int]] = set()
        for raw in (args.storage_origin or []):
            for piece in str(raw).split(","):
                if piece.strip():
                    storage_origins.add(_parse_origin_flag(piece, "--storage-origin"))
        if not storage_origins:
            raise _Refused("--storage-origin: at least one allowlisted storage origin is required")
        if library_origin in storage_origins:
            raise _Refused("--storage-origin must not include the Library origin")
    except _Refused as exc:
        print(f"REFUSED: {exc}")
        return 2
    try:
        _validate_library_url(args.play_url, library_origin)
    except _Refused as exc:
        # Never attach cookies to an untrusted origin: refuse BEFORE loading them.
        print(f"REFUSED: {exc}")
        return 2
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
    details: dict = {
        "slot": args.slot,
        "video_uuid": args.video_uuid,
        "cookie_scope": "library-origin-only (storage fetches carry no Cookie/Authorization)",
        "library_origin": args.library_origin.strip(),
    }

    # 1. Authorized route must 302 to an allowlisted presigned storage URL.
    #    Cookie goes ONLY to the validated Library origin; redirects are
    #    NEVER followed automatically (urllib would forward the Cookie).
    try:
        st, hdrs, _ = _get_once(args.play_url, headers={"Cookie": cookie}, timeout=15)
    except _Refused as exc:
        print(f"REFUSED: {exc}")
        return 2
    except Exception as exc:
        print(f"REFUSED: play URL unreachable: {type(exc).__name__}")
        return 2
    location = (hdrs.get("location") or "").strip()
    live_grant = ""
    if st == 302 and location:
        try:
            grant_u = _validate_storage_url(
                location, library_origin=library_origin,
                storage_origins=storage_origins, what="presigned URL",
            )
            live_grant = urllib.parse.urlunsplit(grant_u)
        except _Refused as exc:
            print(f"REFUSED: {exc}")
            _write_out(out_path, args, checks, details)
            return 2
        checks["library_auth_302"] = True
        details["presigned_host"] = grant_u.hostname or ""
        q = urllib.parse.parse_qs(grant_u.query)
        flat = {k: (v[0] if v else "") for k, v in q.items()}
        expiry = (
            flat.get("X-Amz-Expires") or flat.get("Expires") or flat.get("expires") or ""
        )
        # Informational only: parameter presence NEVER marks expiry checked.
        details["presigned_expiry"] = str(expiry)[:64]
        details["grant_expiry"] = {
            "measured": False,
            "reason": "no expired-grant denial measured yet "
                      "(replay an expired grant for the exact object via --expired-url)",
        }
    else:
        print(f"REFUSED: play URL returned HTTP {st} (expected 302 to presigned storage)")
        _write_out(out_path, args, checks, details)
        return 2

    # 2. Logged-out request (no cookies) must be denied with 401/403/404.
    #    STRICT: NO redirect counts as a denial -- not a storage grant,
    #    not a same-Library-origin login/playback redirect, not anything
    #    else. Only 401/403/404 pass.
    try:
        st2, hdrs2, body2 = _get_once(args.play_url, headers={}, timeout=15)
    except _Refused as exc:
        print(f"REFUSED: {exc}")
        _write_out(out_path, args, checks, details)
        return 2
    except Exception:
        st2, hdrs2, body2 = 0, {}, b""
    details["logged_out_status"] = st2
    if st2 in DENIED_STATUSES:
        checks["logged_out_denied"] = True
        details["logged_out_location_class"] = "denial"
    elif st2 in REDIRECT_STATUSES:
        loc2 = (hdrs2.get("location") or "").strip()
        loc_class = "untrusted-redirect"
        try:
            if loc2 and _origin_tuple(_checked_split(loc2, "logged-out redirect")) == library_origin:
                # STRICT: same-Library-origin redirect (login, playback, or
                # any other path) is NOT a denial -- fail closed.
                _validate_library_url(loc2, library_origin)
                loc_class = "login-redirect"
            elif loc2:
                try:
                    _validate_storage_url(
                        loc2, library_origin=library_origin,
                        storage_origins=storage_origins,
                        what="logged-out redirect",
                    )
                    # Redirect hands an unauthenticated caller a storage
                    # grant: NOT a denial.
                    loc_class = "storage-grant"
                except _Refused:
                    loc_class = "untrusted-redirect"
            details["logged_out_location_class"] = loc_class
            if loc2:
                details["logged_out_location"] = loc2[:200]
        except _Refused:
            # Unparseable / userinfo / private-scheme redirect target:
            # NOT a denial either.
            details["logged_out_location_class"] = "untrusted-redirect"
            if loc2:
                details["logged_out_location"] = loc2[:200]
    elif st2 == 200 and body2:
        details["logged_out_location_class"] = "served-bytes"
    else:
        details["logged_out_location_class"] = "other"
    if not checks["logged_out_denied"]:
        print(f"REFUSED: logged-out play URL returned HTTP {st2} (expected 401/403/404 denial)")
        _write_out(out_path, args, checks, details)
        return 2

    # 3. Expired-grant replay denial, measured -- never assumed.
    if args.expired_url:
        try:
            exp_u = _validate_storage_url(
                args.expired_url, library_origin=library_origin,
                storage_origins=storage_origins, what="--expired-url",
            )
            live_u = urllib.parse.urlsplit(live_grant)
            if _origin_tuple(exp_u) != _origin_tuple(live_u) or exp_u.path != live_u.path:
                raise _Refused(
                    "--expired-url is not the exact object of the live grant "
                    "(same storage origin + path required)"
                )
            exp_q = urllib.parse.parse_qs(exp_u.query)
            exp_flat = {k: (v[0] if v else "") for k, v in exp_q.items()}
            moment = _parse_expiry_moment(args.expired_at, exp_flat)
            if moment is None:
                raise _Refused(
                    "--expired-url carries no provable expiry timestamp "
                    "(supply --expired-at ISO-8601 or a URL with Expires / "
                    "X-Amz-Date+X-Amz-Expires); refusing to mark expiry checked"
                )
            if moment >= datetime.now(timezone.utc):
                raise _Refused("--expired-url is not yet expired; refusing to mark expiry checked")
            exp_url = urllib.parse.urlunsplit(exp_u)
            dst, _, _, _ = _storage_get(
                exp_url, library_origin=library_origin,
                storage_origins=storage_origins, timeout=15,
            )
            if dst in DENIED_STATUSES:
                checks["grant_expiry_checked"] = True
                details["grant_expiry"] = {
                    "measured": True,
                    "reason": "expired grant for the exact object replayed "
                              "without credentials and denied",
                    "expired_at": moment.isoformat(),
                    "denial_status": dst,
                    "credentials_sent": False,
                }
            else:
                print(f"REFUSED: expired-grant replay returned HTTP {dst} (expected denial)")
                details["grant_expiry"] = {
                    "measured": False,
                    "reason": f"expired-grant replay returned HTTP {dst}, not a denial",
                }
                _write_out(out_path, args, checks, details)
                return 2
        except _Refused as exc:
            print(f"REFUSED: {exc}")
            _write_out(out_path, args, checks, details)
            return 2
        except Exception as exc:
            print(f"REFUSED: expired-grant replay failed: {type(exc).__name__}")
            _write_out(out_path, args, checks, details)
            return 2

    # 4. Range 206 with content-type -- from STORAGE, credential-free.
    try:
        st3, hdrs3, _body3, _final3 = _storage_get(
            live_grant, library_origin=library_origin,
            storage_origins=storage_origins, timeout=15,
            extra_headers={"Range": "bytes=0-1023"},
        )
    except _Refused as exc:
        print(f"REFUSED: {exc}")
        _write_out(out_path, args, checks, details)
        return 2
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

    # 5. Full GET + SHA + size -- from STORAGE, credential-free, streamed, bounded.
    tmp = None
    try:
        fd, tmppath = tempfile.mkstemp(prefix="canary-proof-", suffix=".bin")
        os.close(fd)
        tmp = Path(tmppath)
        got_sha, size, ctype, _final = _storage_stream_to_file(
            live_grant, tmp, library_origin=library_origin,
            storage_origins=storage_origins, timeout=args.timeout,
            max_bytes=int(args.max_bytes),
        )
        details.update({"byte_size": size, "sha256": got_sha, "content_type": ctype})
        checks["b2_full_get_sha_match"] = (got_sha == sha and size == int(args.expected_size))
        if not checks["b2_full_get_sha_match"]:
            print(f"REFUSED: full-GET sha/size mismatch (got {got_sha[:12]}.../{size})")
            _write_out(out_path, args, checks, details)
            return 2
        # 6. ffprobe clean + frame cadence on the downloaded bytes.
        clean, cadence, summary = _ffprobe(tmp, args.slot, timeout=args.ffprobe_timeout)
        details["ffprobe"] = summary
        checks["ffprobe_clean"] = clean
        checks["frame_cadence_match"] = cadence
        if not (clean and cadence):
            print("REFUSED: ffprobe checks failed (see output ffprobe summary)")
            _write_out(out_path, args, checks, details)
            return 2
    except _Refused as exc:
        print(f"REFUSED: {exc}")
        _write_out(out_path, args, checks, details)
        return 2
    except _StorageStatus as exc:
        print(f"REFUSED: full GET returned HTTP {exc.status}")
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
