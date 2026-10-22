#!/usr/bin/env python3
"""Bounded read-only canary proof collector (no auth minting, no writes to prod).

Fetches operator-supplied authorized Library playback bytes with the
OPERATOR's own private session cookies and proves them fail-closed:

- full GET (streamed SHA-256 + size vs expected ledger values);
- authorized route behavior (302 to presigned B2 with explicit expiry);
- Range 206 with content-type;
- logged-out (no-cookie) request denied (401/403/404 only);
- measured expired-grant replay denial for the EXACT object;
- ffprobe clean (container/codec/faststart) + SOURCE-BOUND frame
  cadence for video (hq/light: operator-supplied current canonical
  original presigned URL via private ``--source-storage-url-file``
  (0600, OUTSIDE repo, same validated ``--storage-origin``) fetched
  credential-free with a bounded full GET AFTER the derivative GET;
  actual B2 original bytes hashed and MUST equal the DB-canonical
  ``--expected-source-sha``/``--expected-source-size``; the downloaded
  B2 source temp is reused for the bounded ``-count_frames`` census on
  both files -- exact decoded frame count plus fps/duration tolerance,
  VFR preserved by count+duration with per-frame PTS exact explicitly
  NOT claimed; local ``--source-reference`` alone never proves B2
  bytes and unknown/missing reference fails closed, output-only counts
  never pass) / single still for poster (video cadence explicitly N/A,
  recorded as still scope).

  Source integrity (fail closed): ``source_bytes_sha_match`` and
  ``original_storage_integrity_checked`` are true ONLY after an actual
  B2 re-read of the canonical original (this tool never mints presigns:
  the operator supplies the existing authorized presigned URL; the tool
  only GETs it). DB verified-replica rows are metadata and never suffice
  alone. Success emits ``source_integrity_evidence`` as
  ``{sha, size, measured_at, method: 'full_get_after_publication'}``
  with NO URL/secrets.

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
import re
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

# Strict per-slot content types for the Range probe (and full-GET).
# Any other non-empty type (including text/html error pages) fails closed.
EXPECTED_CONTENT_TYPES = {
    "hq": {"video/mp4"},
    "light": {"video/mp4"},
    "poster": {"image/jpeg"},
}

# Strict Range probe: first bytes of the object (bounded, no extra fetch).
# The request is always bytes=0-1023; the EXPECTED response end is
# min(1023, verified_size - 1) so tiny files (< probe) are handled
# gracefully with an exact shorter prefix.
RANGE_PROBE_FIRST = 0
RANGE_PROBE_LAST = 1023

# Cadence tolerances for output-vs-source timing (frame count itself is
# EXACT; fps/duration may differ only within container rounding).
CADENCE_DURATION_TOL_S = 0.15
CADENCE_FPS_REL_TOL = 0.02
CADENCE_FPS_ABS_TOL = 0.15

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


def _safe_bare_origin(u: urllib.parse.SplitResult) -> str:
    """Query-free, path-free origin for diagnostics (never a credential)."""
    scheme = u.scheme.lower()
    host = (u.hostname or "").lower()
    try:
        port = u.port
    except ValueError:
        port = None
    default = 443 if scheme == "https" else 80
    if port and port != default:
        return f"{scheme}://{host}:{port}"
    return f"{scheme}://{host}"


def _check_mode_0600(path: Path, what: str) -> None:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        return
    if mode & 0o077:
        raise SystemExit(
            f"REFUSED: {what} {path} has mode {oct(mode)} (expected 0600); "
            "fix with: chmod 600 " + str(path)
        )


def _load_source_storage_url(
    path: Path,
    *,
    library_origin: tuple[str, str, int],
    storage_origins: set[tuple[str, str, int]],
) -> str:
    """Load the operator-supplied canonical-original presigned URL (no minting).

    Private 0600 file OUTSIDE the repo containing exactly the existing
    authorized presigned URL (single line). The URL is validated like any
    storage URL (allowlisted origin, distinct from the Library, no
    userinfo/private host) but NEVER printed/logged/persisted: callers
    must not include it in stdout, details, or evidence.
    """
    _refuse_inside_git(path, "source storage URL file")
    _check_mode_0600(path, "source storage URL file")
    try:
        raw = path.read_text().strip()
    except FileNotFoundError:
        raise _Refused("source storage URL file not found (export the current original grant first)")
    if not raw:
        raise _Refused("source storage URL file is empty")
    # First non-empty non-comment line only; extra lines refused (ambiguous).
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if len(lines) != 1:
        raise _Refused("source storage URL file must hold exactly one URL line")
    url = lines[0]
    if len(url) > 8192:
        raise _Refused("source storage URL implausibly long; refusing")
    _validate_storage_url(
        url,
        library_origin=library_origin,
        storage_origins=storage_origins,
        what="source storage URL",
    )
    return url


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


def _read_bounded(fp, limit: int = SMALL_BODY_LIMIT) -> bytes:
    """Bounded read: NEVER buffers an unbounded body.

    Reads in 64 KiB chunks and refuses (fail closed) as soon as the
    cumulative total exceeds ``limit``. Callers close the response on
    refusal. Exact-cap bodies (total == limit) are allowed; limit+1
    refuses. Works for success responses and HTTPError bodies alike
    (a logged-out GET may return huge video bytes, or a Range-ignored
    200 may return the full object).
    """
    total = 0
    parts: list[bytes] = []
    while True:
        chunk = fp.read(64 * 1024)
        if not chunk:
            break
        if isinstance(chunk, str):
            chunk = chunk.encode("utf-8", "replace")
        total += len(chunk)
        if total > limit:
            raise _Refused(f"response body exceeds {limit} bytes bound; refusing")
        parts.append(chunk)
    return b"".join(parts)


def _get_once(
    url: str, *, headers: dict[str, str], timeout: int
) -> tuple[int, dict, bytes]:
    """One HTTP GET with NO redirect following. Sends ONLY the headers
    given. Library probes pass the session Cookie here (after origin
    validation); storage callers must use _storage_get /
    _storage_stream_to_file, which forbid credential headers.

    Bodies are bounded via _read_bounded (SMALL_BODY_LIMIT) with early
    close on BOTH success and HTTPError paths: a logged-out GET may
    return huge video bytes and a Range-ignored 200 may return the full
    object, so no response is ever fully buffered into memory.
    """
    req = urllib.request.Request(url)
    for k, v in headers.items():
        req.add_header(k, v)
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        resp = opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        try:
            try:
                body = _read_bounded(exc, SMALL_BODY_LIMIT)
            except _Refused:
                try:
                    exc.close()
                except Exception:
                    pass
                raise
            try:
                hdrs = {k.lower(): v for k, v in (exc.headers.items() if exc.headers else [])}
            except Exception:
                hdrs = {}
            return int(exc.code), hdrs, body
        finally:
            try:
                exc.close()
            except Exception:
                pass
    try:
        status = int(getattr(resp, "status", 200))
        hdrs = {k.lower(): v for k, v in resp.getheaders()}
        try:
            body = _read_bounded(resp, SMALL_BODY_LIMIT)
        except _Refused:
            try:
                resp.close()
            except Exception:
                pass
            raise
        return status, hdrs, body
    finally:
        try:
            resp.close()
        except Exception:
            pass


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


def _parse_content_range(raw: str) -> tuple[int, int, int] | None:
    """Strictly parse ``Content-Range: bytes <start>-<end>/<total>``.

    Returns ``(start, end, total)`` or ``None`` on ANY deviation
    (wrong unit, missing parts, non-numeric, negative, end < start).
    Callers additionally require start == 0 and end/total to match
    the verified object size. No URL/secret material is involved.
    """
    m = re.match(r"^bytes (\d+)-(\d+)/(\d+)$", (raw or "").strip())
    if not m:
        return None
    try:
        start, end, total = int(m.group(1)), int(m.group(2)), int(m.group(3))
    except ValueError:
        return None
    if end < start:
        return None
    return (start, end, total)


# Strict same-instant tolerance when BOTH a URL expiry and an explicit
# --expired-at are supplied: the URL is authoritative, and a conflicting
# manual timestamp is refused. Up to 5 s covers second-rounding between
# ISO-8601 and epoch/S3 formats; anything larger is a conflict.
_EXPIRY_CONFLICT_TOL_S = 5.0


def _parse_url_expiry(raw_query: str) -> datetime | None:
    """Parse the authoritative expiry from a raw URL query string.

    Fail closed on ambiguity: duplicate params with differing values, or
    a mix of SigV2 (Expires) + SigV4 (X-Amz-Date/X-Amz-Expires), are
    refused. Returns None when the URL carries NO parseable expiry.
    Never logs/returns the URL itself -- only the moment.
    """
    pairs = urllib.parse.parse_qsl(raw_query or "", keep_blank_values=True)
    grouped: dict[str, list[str]] = {}
    for k, v in pairs:
        lk = (k or "").strip().lower()
        if not lk:
            continue
        grouped.setdefault(lk, []).append((v or "").strip())
    for lk, vals in grouped.items():
        if len(vals) > 1 and len(set(vals)) > 1:
            raise _Refused(
                f"expired URL has duplicate '{lk}' params with differing values; refusing"
            )
    has_expires = "expires" in grouped and any(v != "" for v in grouped["expires"])
    has_amz_exp = "x-amz-expires" in grouped and any(v != "" for v in grouped["x-amz-expires"])
    has_amz_date = "x-amz-date" in grouped and any(v != "" for v in grouped["x-amz-date"])
    if has_expires and (has_amz_exp or has_amz_date):
        raise _Refused(
            "expired URL mixes Expires + X-Amz-Date/X-Amz-Expires; refusing (ambiguous)"
        )
    if has_expires:
        vals = [v for v in grouped["expires"] if v != ""]
        exp = vals[0]
        if exp.isdigit():
            return datetime.fromtimestamp(int(exp), tz=timezone.utc)
        return None
    if has_amz_exp and has_amz_date:
        amz_date = [v for v in grouped["x-amz-date"] if v != ""][0]
        amz_exp = [v for v in grouped["x-amz-expires"] if v != ""][0]
        if not amz_exp.isdigit():
            return None
        try:
            base = datetime.strptime(amz_date, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
        try:
            return base + timedelta(seconds=int(amz_exp))
        except (OverflowError, ValueError):
            return None
    return None


def _parse_expiry_moment(
    explicit: str | None,
    query: dict[str, str],
    raw_query: str | None = None,
) -> datetime | None:
    """Return the grant's expiry moment, or None when no PROVABLE past
    timestamp exists. Mere parameter presence never counts.

    Authority rule (fail closed): the URL's own parseable expiry is
    AUTHORITATIVE. An explicit --expired-at is used ONLY when the URL
    carries NO parseable expiry. When both exist they must agree
    (within a small rounding tolerance); a conflict is refused. A
    future-dated URL paired with a past manual timestamp (even with a
    401/403/404 replay) therefore FAILS -- it never marks expiry
    checked. Never persists signed URLs -- only the moment.
    """
    url_moment: datetime | None = None
    if raw_query is not None:
        url_moment = _parse_url_expiry(raw_query)
    else:
        # Dict fallback (no duplicate visibility): still fail closed on
        # mixed SigV2+SigV4 styles.
        lowered = {(k or "").strip().lower(): (v or "").strip() for k, v in (query or {}).items()}
        has_exp = bool(lowered.get("expires", "").strip())
        has_ax = bool(lowered.get("x-amz-expires", "").strip())
        has_ad = bool(lowered.get("x-amz-date", "").strip())
        if has_exp and (has_ax or has_ad):
            raise _Refused(
                "expired URL mixes Expires + X-Amz-Date/X-Amz-Expires; refusing (ambiguous)"
            )
        exp = (query.get("Expires") or query.get("expires") or "").strip() if query else ""
        if exp.isdigit():
            url_moment = datetime.fromtimestamp(int(exp), tz=timezone.utc)
        else:
            amz_date = (query.get("X-Amz-Date") or query.get("x-amz-date") or "").strip() if query else ""
            amz_exp = (query.get("X-Amz-Expires") or query.get("x-amz-expires") or "").strip() if query else ""
            if amz_date and amz_exp.isdigit():
                try:
                    base = datetime.strptime(amz_date, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
                except ValueError:
                    base = None
                if base is not None:
                    try:
                        url_moment = base + timedelta(seconds=int(amz_exp))
                    except (OverflowError, ValueError):
                        url_moment = None
    explicit_moment: datetime | None = None
    if explicit and explicit.strip():
        try:
            dt = datetime.fromisoformat(explicit.strip().replace("Z", "+00:00"))
        except ValueError:
            raise _Refused("--expired-at must be ISO-8601")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        explicit_moment = dt
    if url_moment is not None:
        if explicit_moment is not None:
            if abs((explicit_moment - url_moment).total_seconds()) > _EXPIRY_CONFLICT_TOL_S:
                raise _Refused(
                    "conflicting expiry: URL expiry is authoritative; "
                    "--expired-at disagrees with the URL; refusing"
                )
        return url_moment
    return explicit_moment


def _ffprobe(path: Path, slot: str, timeout: int) -> tuple[bool, bool, dict]:
    """Returns (clean, cadence_ok, summary). False-closed when ffprobe missing/fails.

    For hq/light the returned cadence flag is a POSITIVE-COUNT signal
    ONLY (frames > 0) and MUST NOT be treated as a source match: the
    caller verifies it against a SHA-pinned ``--source-reference`` via
    ``_verify_video_cadence`` and leaves ``frame_cadence_match`` false
    until that comparison passes. For poster the flag means "single
    still present" (video cadence N/A -- see details scope).
    """
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


def _parse_fps(raw: str) -> float:
    try:
        s = str(raw or "").strip()
        if "/" in s:
            num, den = s.split("/", 1)
            den_f = float(den)
            if not den_f:
                return 0.0
            return float(num) / den_f
        return float(s) if s else 0.0
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _sha256_file(path: Path, max_bytes: int) -> tuple[str, int]:
    """Streamed SHA-256 of a local file (bounded; no full read into RAM)."""
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > int(max_bytes):
                raise _Refused(f"source reference exceeds max-bytes {max_bytes}")
            digest.update(chunk)
    return digest.hexdigest(), size


def _ffprobe_video_info(path: Path, timeout: int) -> dict:
    """Bounded decoded-frame census for one video file (no frame list).

    Uses ``ffprobe -count_frames`` (decode + count, single summary JSON)
    -- NEVER ``-show_frames``/``-show_packets`` (unbounded per-frame
    lists that can exhaust memory on long clips). Returns
    ``{frames, avg_fps, r_fps, duration, codec, vfr}`` or
    ``{error}`` fail-closed.
    """
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-count_frames",
             "-select_streams", "v:0",
             "-show_entries", "stream=nb_read_frames,avg_frame_rate,r_frame_rate,duration,codec_name,width,height",
             "-show_entries", "format=duration,size",
             "-print_format", "json", str(path)],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        return {"error": "ffprobe not installed"}
    except subprocess.TimeoutExpired:
        return {"error": "ffprobe timed out"}
    if proc.returncode != 0:
        return {"error": f"ffprobe refused input: {(proc.stderr or '')[:300]}"}
    try:
        info = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return {"error": "ffprobe output not JSON"}
    try:
        streams = info.get("streams", []) or []
        fmt = info.get("format", {}) or {}
        s0 = streams[0] if streams else {}
        frames = int(s0.get("nb_read_frames") or 0)
        avg_fps = _parse_fps(s0.get("avg_frame_rate", ""))
        r_fps = _parse_fps(s0.get("r_frame_rate", ""))
        dur = s0.get("duration") or fmt.get("duration") or 0
        duration = float(dur or 0)
        if frames <= 0 or avg_fps <= 0 or duration <= 0:
            return {"error": f"unmeasurable video census (frames={frames} fps={avg_fps} dur={duration})"}
        vfr = abs(r_fps - avg_fps) > max(CADENCE_FPS_ABS_TOL, CADENCE_FPS_REL_TOL * max(avg_fps, 1e-6)) if r_fps > 0 else False
        return {
            "frames": frames,
            "avg_fps": avg_fps,
            "r_fps": r_fps,
            "duration": duration,
            "codec": str(s0.get("codec_name", ""))[:32],
            "vfr": bool(vfr),
        }
    except (TypeError, ValueError):
        return {"error": "unparseable ffprobe census"}


def _compare_cadence_video(source: dict, output: dict) -> tuple[bool, dict]:
    """Exact frame-count + timing-tolerance comparison (fail closed).

    Requires output decoded frames EXACTLY equal source frames (a
    nominal 60->30 transcode MUST fail even though the output count is
    positive). fps/duration must match within container-rounding
    tolerance (VFR preserved by count+duration, NOT by per-frame PTS:
    ``pts_exact_claimed`` is always False -- per-frame PTS exactness is
    NOT claimed without dedicated proof).
    """
    if "error" in source:
        return False, {"reason": f"source census failed: {source['error']}"}
    if "error" in output:
        return False, {"reason": f"output census failed: {output['error']}"}
    try:
        sf, of = int(source["frames"]), int(output["frames"])
        sfps, ofps = float(source["avg_fps"]), float(output["avg_fps"])
        sdur, odur = float(source["duration"]), float(output["duration"])
    except (KeyError, TypeError, ValueError):
        return False, {"reason": "unmeasurable census fields"}
    evidence: dict = {
        "source_frames": sf,
        "source_fps": sfps,
        "source_duration": sdur,
        "output_frames": of,
        "output_fps": ofps,
        "output_duration": odur,
        "vfr": bool(source.get("vfr") or output.get("vfr")),
        # Honest scope: count+timing verified; per-frame PTS exactness
        # is NOT proven by this census (would need bounded PTS series).
        "pts_exact_claimed": False,
    }
    if of != sf:
        evidence["reason"] = f"frame count mismatch (source={sf} output={of}); 60->30 must fail"
        return False, evidence
    if abs(odur - sdur) > max(CADENCE_DURATION_TOL_S, 0.01 * max(sdur, 1e-6)):
        evidence["reason"] = f"duration drift (source={sdur:.3f}s output={odur:.3f}s)"
        return False, evidence
    if abs(ofps - sfps) > max(CADENCE_FPS_ABS_TOL, CADENCE_FPS_REL_TOL * max(sfps, 1e-6)):
        evidence["reason"] = f"fps drift (source={sfps:.3f} output={ofps:.3f})"
        return False, evidence
    evidence["reason"] = "exact frame count + timing tolerance hold; per-frame PTS exact NOT claimed"
    return True, evidence


def _verify_video_cadence(
    output_path: Path,
    source_ref: str | None,
    expected_source_sha: str | None,
    timeout: int,
    max_bytes: int,
) -> tuple[bool, dict]:
    """Source-bound video cadence verification (fail closed).

    - Missing ``--source-reference``/``--expected-source-sha`` -> False
      (unknown reference never passes; output-only metadata is NEVER
      inferred as a match).
    - Source file must sit OUTSIDE any git checkout (private operator
      file, like cookies) and its streamed SHA-256 must equal the
      DB-canonical ``--expected-source-sha`` (claims never trusted).
    - Bounded ``_ffprobe_video_info`` census on BOTH files, then
      ``_compare_cadence_video`` (exact frames + timing tolerance).
    """
    details: dict = {"video_cadence_applicable": True}
    if not source_ref or not str(source_ref).strip():
        details["reason"] = "no --source-reference supplied; unknown reference fails closed"
        return False, details
    if not expected_source_sha or not str(expected_source_sha).strip():
        details["reason"] = "no --expected-source-sha supplied; unknown reference fails closed"
        return False, details
    exp = str(expected_source_sha).strip().lower()
    if len(exp) != 64 or any(c not in "0123456789abcdef" for c in exp):
        details["reason"] = "--expected-source-sha must be 64 lower-hex"
        return False, details
    src_path = Path(str(source_ref))
    try:
        _refuse_inside_git(src_path, "source reference")
    except SystemExit as exc:
        details["reason"] = str(exc)
        return False, details
    try:
        _check_mode_0600(src_path, "source reference")
    except SystemExit as exc:
        details["reason"] = str(exc)
        return False, details
    try:
        got_sha, src_size = _sha256_file(src_path, max_bytes)
    except _Refused as exc:
        details["reason"] = str(exc)
        return False, details
    except FileNotFoundError:
        details["reason"] = f"source reference not found: {src_path}"
        return False, details
    except OSError as exc:
        details["reason"] = f"source reference unreadable: {type(exc).__name__}"
        return False, details
    details["source_sha256"] = got_sha
    details["source_bytes"] = src_size
    if got_sha != exp:
        details["reason"] = f"source reference SHA mismatch (got {got_sha[:12]}...)"
        return False, details
    src_info = _ffprobe_video_info(src_path, timeout)
    out_info = _ffprobe_video_info(output_path, timeout)
    ok, cmp_ev = _compare_cadence_video(src_info, out_info)
    details.update(cmp_ev)
    details["source_census_error"] = src_info.get("error", "")
    details["output_census_error"] = out_info.get("error", "")
    return ok, details


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
    ap.add_argument("--source-reference", default=None,
                    help="legacy local source-original file OUTSIDE repo (0600); "
                         "proves the LOCAL copy only, never B2 bytes -- "
                         "insufficient alone for source_bytes_sha_match (fail closed). "
                         "Poster never uses it (video cadence N/A).")
    ap.add_argument("--expected-source-sha", default=None,
                    help="DB-canonical source blob SHA-256 (64 hex); the B2-re-read "
                         "original bytes are hashed and MUST match (claims never trusted). "
                         "REQUIRED for hq/light.")
    ap.add_argument("--expected-source-size", default=None, type=int,
                    help="DB-canonical source blob byte_size; the B2-re-read "
                         "original size MUST match. REQUIRED with --source-storage-url-file.")
    ap.add_argument("--source-storage-url-file", default=None,
                    help="private file OUTSIDE repo (0600) holding exactly the "
                         "operator-supplied current canonical-original presigned URL "
                         "(existing authorized access; this tool never mints presigns). "
                         "Same validated --storage-origin, credential-free bounded "
                         "full GET after the derivative GET. REQUIRED for hq/light "
                         "source proof (fail closed when missing). Never printed.")
    ap.add_argument("--source-max-bytes", type=int, default=1_200_000_000,
                    help="max source-reference bytes hashed (bounded, default %(default)s)")
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
    # Video slots additionally prove clip-level source integrity via an
    # actual B2 re-read of the canonical original (poster stills never
    # fake this: the keys stay absent for poster and the proof-level
    # check is satisfied by the video slots + DB cross-check instead).
    # Local --source-reference alone NEVER sets these: it proves the
    # local copy only, not B2 current bytes.
    if args.slot in ("hq", "light"):
        checks["source_bytes_sha_match"] = False
        checks["original_storage_integrity_checked"] = False
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
        # NEVER persist the raw Location: presigned storage redirects carry
        # bearer query credentials (X-Amz-Signature/Credential, tokens).
        # Record only the redirect class + a query-free bare origin.
        loc_origin = ""
        try:
            if loc2:
                try:
                    loc_origin = _safe_bare_origin(_checked_split(loc2, "logged-out redirect"))
                except _Refused:
                    loc_origin = ""
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
            if loc_origin:
                details["logged_out_origin"] = loc_origin
        except _Refused:
            # Unparseable / userinfo / private-scheme redirect target:
            # NOT a denial either.
            details["logged_out_location_class"] = "untrusted-redirect"
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
            moment = _parse_expiry_moment(args.expired_at, exp_flat, raw_query=exp_u.query)
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

    # 4. Strict Range 206 probe -- from STORAGE, credential-free.
    #    The request is always bytes=0-1023; the EXPECTED response is
    #    bytes 0-<min(1023, verified_size-1)>/<verified_size> with a body
    #    of EXACTLY end+1 bytes equal to the prefix of the SHA-verified
    #    full GET (compared in section 5 AFTER verification -- range_206
    #    is NEVER marked true here). No extra network read: the bounded
    #    probe body (<=1024 B) is compared against the local verified
    #    temp file. A 200 (ignored Range) never passes.
    try:
        st3, hdrs3, body3, _final3 = _storage_get(
            live_grant, library_origin=library_origin,
            storage_origins=storage_origins, timeout=15,
            extra_headers={"Range": f"bytes={RANGE_PROBE_FIRST}-{RANGE_PROBE_LAST}"},
        )
    except _Refused as exc:
        print(f"REFUSED: {exc}")
        _write_out(out_path, args, checks, details)
        return 2
    except Exception as exc:
        print(f"REFUSED: range request failed: {type(exc).__name__}")
        _write_out(out_path, args, checks, details)
        return 2
    want_ct = EXPECTED_CONTENT_TYPES.get(args.slot, set())
    expected_total = int(args.expected_size)
    expected_end = min(RANGE_PROBE_LAST, expected_total - 1)
    expected_len = expected_end + 1
    cr = (hdrs3.get("content-range") or "")
    ct3 = (hdrs3.get("content-type") or "").split(";")[0].strip().lower()
    parsed = _parse_content_range(cr)
    range_fail: str | None = None
    if st3 != 206:
        range_fail = f"range request returned HTTP {st3} (expected 206 with Content-Range)"
    elif parsed is None:
        range_fail = "range Content-Range is not an exact byte range (expected 'bytes 0-<end>/<total>')"
    elif parsed[0] != RANGE_PROBE_FIRST or parsed[1] != expected_end or parsed[2] != expected_total:
        range_fail = (
            f"range Content-Range mismatch (expected 'bytes "
            f"{RANGE_PROBE_FIRST}-{expected_end}/{expected_total}')"
        )
    elif len(body3) != expected_len:
        range_fail = (
            f"range body length mismatch (got {len(body3)} bytes, expected {expected_len})"
        )
    elif "content-length" in hdrs3:
        try:
            if int(str(hdrs3["content-length"]).strip()) != len(body3):
                range_fail = "range Content-Length does not match body length"
        except (TypeError, ValueError):
            range_fail = "range Content-Length is not a number"
    if range_fail is None and ct3 not in want_ct:
        range_fail = f"range content-type {ct3!r} is not {sorted(want_ct)} for slot {args.slot}"
    if range_fail is not None:
        print(f"REFUSED: {range_fail}")
        _write_out(out_path, args, checks, details)
        return 2
    # Header/shape checks passed; the byte-prefix proof below (after the
    # full GET is SHA-verified) finally marks range_206 true.
    details["range_content_type"] = ct3
    details["range_content_range"] = f"bytes {RANGE_PROBE_FIRST}-{expected_end}/{expected_total}"

    # 5. Full GET + SHA + size -- from STORAGE, credential-free, streamed, bounded.
    tmp = None
    src_tmp = None
    try:
        fd, tmppath = tempfile.mkstemp(prefix="canary-proof-", suffix=".bin")
        os.close(fd)
        tmp = Path(tmppath)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        got_sha, size, ctype, _final = _storage_stream_to_file(
            live_grant, tmp, library_origin=library_origin,
            storage_origins=storage_origins, timeout=args.timeout,
            max_bytes=int(args.max_bytes),
        )
        details.update({"byte_size": size, "sha256": got_sha, "content_type": ctype})
        if ctype not in want_ct:
            print(f"REFUSED: full-GET content-type {ctype!r} is not {sorted(want_ct)} for slot {args.slot}")
            _write_out(out_path, args, checks, details)
            return 2
        checks["b2_full_get_sha_match"] = (got_sha == sha and size == int(args.expected_size))
        if not checks["b2_full_get_sha_match"]:
            print(f"REFUSED: full-GET sha/size mismatch (got {got_sha[:12]}.../{size})")
            _write_out(out_path, args, checks, details)
            return 2
        # 5b. Strict Range byte proof: the bounded probe body MUST equal
        #     the prefix of the SHA-verified owned file. Local bounded
        #     read only (no extra network fetch, no unbounded buffering).
        try:
            with open(tmp, "rb") as _pfh:
                _prefix = _pfh.read(expected_len)
        except OSError:
            print("REFUSED: verified bytes unreadable for range comparison")
            _write_out(out_path, args, checks, details)
            return 2
        if len(_prefix) != expected_len or _prefix != body3:
            print(
                "REFUSED: range bytes do not match the verified full-GET prefix "
                f"(expected {expected_len} prefix bytes)"
            )
            _write_out(out_path, args, checks, details)
            return 2
        checks["range_206"] = True
        # 6. ffprobe clean on the downloaded bytes; cadence is
        #    SOURCE-BOUND below (output-only counts never pass video).
        clean, positive, summary = _ffprobe(tmp, args.slot, timeout=args.ffprobe_timeout)
        details["ffprobe"] = summary
        checks["ffprobe_clean"] = clean
        if not clean:
            checks["frame_cadence_match"] = False
            print("REFUSED: ffprobe clean check failed (see output ffprobe summary)")
            _write_out(out_path, args, checks, details)
            return 2
        if args.slot == "poster":
            # Poster is a still: video cadence is explicitly NOT
            # applicable (never faked true as a video match). The still
            # check (positive) passes; scope is recorded honestly.
            details["frame_cadence_scope"] = "poster-still (video cadence N/A)"
            details["video_cadence_applicable"] = False
            checks["frame_cadence_match"] = bool(positive)
            if not checks["frame_cadence_match"]:
                print("REFUSED: poster still check failed (see output ffprobe summary)")
                _write_out(out_path, args, checks, details)
                return 2
        else:
            # 6b. B2 source re-read AFTER the derivative GET (credential-free,
            # bounded, same validated storage origin). The operator supplies
            # the current canonical-original presigned URL via a private
            # 0600 file; this tool never mints presigns (existing authorized
            # access only). Local --source-reference alone NEVER passes:
            # it proves the local copy, not B2 current bytes.
            exp_src_sha = str(getattr(args, "expected_source_sha", "") or "").strip().lower()
            exp_src_size_raw = getattr(args, "expected_source_size", None)
            src_url_file = str(getattr(args, "source_storage_url_file", "") or "").strip()
            src_max = int(getattr(args, "source_max_bytes", args.max_bytes))
            if not exp_src_sha or len(exp_src_sha) != 64 or any(
                c not in "0123456789abcdef" for c in exp_src_sha
            ):
                print("REFUSED: --expected-source-sha (64 hex, DB-canonical) is required for hq/light")
                _write_out(out_path, args, checks, details)
                return 2
            if exp_src_size_raw is None:
                print("REFUSED: --expected-source-size (DB-canonical) is required with B2 source re-read")
                _write_out(out_path, args, checks, details)
                return 2
            try:
                exp_src_size = int(exp_src_size_raw)
            except (TypeError, ValueError):
                print("REFUSED: --expected-source-size must be a positive int")
                _write_out(out_path, args, checks, details)
                return 2
            if exp_src_size <= 0:
                print("REFUSED: --expected-source-size must be > 0")
                _write_out(out_path, args, checks, details)
                return 2
            if exp_src_size > src_max:
                print(f"REFUSED: expected source size {exp_src_size} > source max-bytes {src_max}")
                _write_out(out_path, args, checks, details)
                return 2
            if not src_url_file:
                print("REFUSED: --source-storage-url-file is required for hq/light "
                      "(B2 source re-read; local --source-reference alone is insufficient)")
                _write_out(out_path, args, checks, details)
                return 2
            try:
                src_url = _load_source_storage_url(
                    Path(src_url_file),
                    library_origin=library_origin,
                    storage_origins=storage_origins,
                )
            except SystemExit as exc:
                # Mode/inside-git refusals: fail closed without persisting secrets.
                print(f"REFUSED: {exc}")
                _write_out(out_path, args, checks, details)
                return 2
            # Credential-free bounded full GET of the ACTUAL B2 original,
            # hashed while streaming. Reuses the downloaded bytes as the
            # cadence source temp (no second original transfer).
            fd2, src_tmppath = tempfile.mkstemp(prefix="canary-source-", suffix=".bin")
            os.close(fd2)
            src_tmp = Path(src_tmppath)
            try:
                os.chmod(src_tmp, 0o600)
            except OSError:
                pass
            try:
                src_sha, src_size, _src_ctype, _src_final = _storage_stream_to_file(
                    src_url, src_tmp, library_origin=library_origin,
                    storage_origins=storage_origins, timeout=args.timeout,
                    max_bytes=src_max,
                )
            except _Refused as exc:
                print(f"REFUSED: {exc}")
                _write_out(out_path, args, checks, details)
                return 2
            except _StorageStatus as exc:
                print("REFUSED: source full GET denied/unavailable "
                      f"(HTTP {exc.status}; B2 re-read required)")
                _write_out(out_path, args, checks, details)
                return 2
            # Never persist the URL/query: evidence is sha/size/method only.
            if src_sha != exp_src_sha or int(src_size) != int(exp_src_size):
                print(f"REFUSED: B2 source sha/size mismatch (got {src_sha[:12]}.../{src_size})")
                _write_out(out_path, args, checks, details)
                return 2
            measured_at = datetime.now(timezone.utc).isoformat()
            details["source_integrity_evidence"] = {
                "sha": src_sha,
                "size": int(src_size),
                "measured_at": measured_at,
                "method": "full_get_after_publication",
            }
            details["expected_source_sha256"] = exp_src_sha
            details["expected_source_size"] = int(exp_src_size)
            checks["source_bytes_sha_match"] = True
            checks["original_storage_integrity_checked"] = True
            # Source-bound cadence on the RE-READ B2 bytes (not the local
            # scratch copy): bounded census on both files, exact frames +
            # timing tolerance, VFR by count+duration, PTS exact NOT claimed.
            src_info = _ffprobe_video_info(src_tmp, args.ffprobe_timeout)
            out_info = _ffprobe_video_info(tmp, args.ffprobe_timeout)
            ok, cmp_ev = _compare_cadence_video(src_info, out_info)
            details["frame_cadence_scope"] = "video-exact (source-bound, B2 re-read)"
            details["video_cadence_applicable"] = True
            details["cadence"] = cmp_ev
            details["cadence"]["source_sha256"] = exp_src_sha
            details["cadence"]["source_bytes"] = int(src_size)
            # Machine-readable cadence evidence for the proof record:
            # the operator copies this block into the multi-slot proof's
            # `cadence_evidence` (see canary_web_package validation).
            if ok:
                details["cadence_evidence"] = {
                    "source_sha256": exp_src_sha,
                    "source_frames": int(cmp_ev.get("source_frames", 0)),
                    "source_fps": float(cmp_ev.get("source_fps", 0.0) or 0.0),
                    "source_duration": float(cmp_ev.get("source_duration", 0.0) or 0.0),
                    "outputs": {
                        str(args.slot): {
                            "frames": int(cmp_ev.get("output_frames", 0)),
                            "fps": float(cmp_ev.get("output_fps", 0.0) or 0.0),
                            "duration": float(cmp_ev.get("output_duration", 0.0) or 0.0),
                        }
                    },
                    "vfr": bool(cmp_ev.get("vfr", False)),
                    "pts_exact_claimed": False,
                }
            checks["frame_cadence_match"] = bool(ok)
            if not ok:
                print(f"REFUSED: source-bound cadence failed: {cmp_ev.get('reason', 'mismatch')}")
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
        for _p in (tmp, src_tmp):
            try:
                if _p is not None and _p.exists():
                    _p.unlink()
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
