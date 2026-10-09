"""B2 S3-compatible presigned GET authority (P5 playback grant).

The backend presigns short-lived GET URLs against the PROD media bucket
using a dedicated runtime credential that is NEVER in Git, never logged,
and never sent to the browser. Presigned URLs are returned to no one as
data: they are used exclusively as the Location of an HTTP redirect and
must never be persisted or logged (§15/§16 of the packet).

boto3 is imported lazily so unit tests can inject fakes and the rest of
the suite never requires it.
"""

from dataclasses import dataclass
from time import monotonic
from typing import Optional
import threading

from app.config import get_settings

MIN_TTL_SECONDS = 1
# P5 production ceiling: Dive Analyzer clips are short; grants are refreshed
# from the authenticated route, never extended. 300s absolute max.
MAX_TTL_SECONDS = 300

SERVICE = "s3"

# Provider-side call bounds: a replay of playback must fail fast to the
# legacy-fallback policy instead of hanging the caller. boto3's default
# retry storm (5 attempts, ~25s worst case) is unacceptable here.
B2_CONNECT_TIMEOUT_SECONDS = 3
B2_READ_TIMEOUT_SECONDS = 10
B2_TOTAL_ATTEMPTS = 2

_credentials_client_lock = threading.Lock()
_presign_client: Optional[object] = None
_presign_client_fingerprint: Optional[tuple] = None


class PresignUnavailable(Exception):
    """Raised when presigning cannot be performed (missing configuration)."""


@dataclass(frozen=True)
class PresignResult:
    url: str
    ttl_seconds: int
    storage_location_id: Optional[int] = None


def clamp_ttl(ttl_seconds: Optional[int] = None) -> int:
    settings = get_settings()
    configured = (
        ttl_seconds
        if ttl_seconds is not None
        else settings.media_playback_presign_ttl_seconds
    )
    try:
        ttl = int(configured)
    except (TypeError, ValueError):
        ttl = settings.media_playback_presign_ttl_seconds
    return max(MIN_TTL_SECONDS, min(MAX_TTL_SECONDS, ttl))


def _b2_client_fingerprint() -> Optional[tuple]:
    settings = get_settings()
    key_id = (settings.b2_playback_key_id or "").strip()
    secret = (settings.b2_playback_key_secret or "").strip()
    if not key_id or not secret:
        return None
    region = (settings.b2_playback_region or "").strip()
    if not region:
        return None
    endpoint = (
        settings.b2_playback_endpoint_url
        or f"https://s3.{region}.backblazeb2.com"
    ).strip()
    return key_id, secret, region, endpoint


def _build_b2_client(fingerprint: tuple) -> object:
    import boto3  # lazy: unit tests inject fakes instead
    from botocore.config import Config  # lazy, same reason

    key_id, secret, region, endpoint = fingerprint
    # Bounded retries/timeouts: see B2_* constants above.
    config = Config(
        connect_timeout=B2_CONNECT_TIMEOUT_SECONDS,
        read_timeout=B2_READ_TIMEOUT_SECONDS,
        retries={"total_max_attempts": B2_TOTAL_ATTEMPTS},
    )
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=region,
        aws_access_key_id=key_id,
        aws_secret_access_key=secret,
        config=config,
    )


def _b2_client():
    """Cached S3-compatible client for the dedicated read-only playback key.

    The playback credential is least-privilege readFiles on the PROD bucket
    only; it is configured directly with the known endpoint/bucket so no
    account-level listing is ever needed. Raises PresignUnavailable when
    not configured.

    The boto3 client itself is safe to reuse across requests and building
    one is expensive (credential resolution, endpoint discovery), so the
    client is cached and rebuilt only when the credential fingerprint
    changes (settings monkeypatched by tests, hot-reloaded env, etc.).
    """
    global _presign_client, _presign_client_fingerprint
    fingerprint = _b2_client_fingerprint()
    if fingerprint is None:
        raise PresignUnavailable("playback presign credential not configured")
    if _presign_client is None or _presign_client_fingerprint != fingerprint:
        with _credentials_client_lock:
            if _presign_client is None or _presign_client_fingerprint != fingerprint:
                _presign_client = _build_b2_client(fingerprint)
                _presign_client_fingerprint = fingerprint
    return _presign_client


# Successful HEADs, keyed by (credential fingerprint, bucket, key) -> expiry. The
# proof is reused only briefly: one provider round trip less per replay of a
# clip (~0.5-1.7 s), while failures are never cached and authorization still
# runs on every request. A rotated credential has a new fingerprint and so
# misses the cache.
_HEAD_CACHE_MAX_ENTRIES = 4096
_head_ok_cache: dict = {}
_head_ok_lock = threading.Lock()


def head_object(bucket: str, object_key: str) -> bool:
    """Provider-side health proof for one playback grant (P6 §13/§29).

    boto3 presigning is a LOCAL signing operation: an invalid, revoked, or
    expired playback credential still produces a syntactically valid URL
    that the provider then rejects — handing the browser a dead redirect.
    This HEAD proves the credential can actually read the object RIGHT
    NOW; any provider rejection/failure raises PresignUnavailable so the
    caller can apply the B2_TEMPORARY_FAILURE policy (authorized legacy
    fallback, or explicit 503 — never a dead Location). A success is reused
    for media_playback_head_cache_seconds (failures never are).
    """
    client = _b2_client()
    ttl = get_settings().media_playback_head_cache_seconds
    cache_key = (_presign_client_fingerprint, bucket, object_key)
    if ttl > 0:
        with _head_ok_lock:
            expiry = _head_ok_cache.get(cache_key)
        if expiry is not None and monotonic() < expiry:
            return True
    try:
        client.head_object(Bucket=bucket, Key=object_key)
    except PresignUnavailable:
        raise
    except Exception as exc:
        raise PresignUnavailable(
            f"playback credential/object unusable: {type(exc).__name__}"
        ) from exc
    if ttl > 0:
        with _head_ok_lock:
            _head_ok_cache[cache_key] = monotonic() + ttl
            if len(_head_ok_cache) > _HEAD_CACHE_MAX_ENTRIES:
                # Drop the soonest-expiring proofs first.
                for stale in sorted(_head_ok_cache, key=_head_ok_cache.get)[: len(_head_ok_cache) - _HEAD_CACHE_MAX_ENTRIES]:
                    del _head_ok_cache[stale]
    return True


def presign_get(
    bucket: str,
    object_key: str,
    ttl_seconds: Optional[int] = None,
    storage_location_id: Optional[int] = None,
) -> PresignResult:
    """Presign a GET for one object. Returns (url, ttl) — url is transient.

    Raises PresignUnavailable when the playback credential is not
    configured; callers MUST map that to an explicit provider-failure
    response, never to a fallback or a redirect to an arbitrary location.
    """
    ttl = clamp_ttl(ttl_seconds)
    client = _b2_client()
    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": object_key},
        ExpiresIn=ttl,
    )
    return PresignResult(
        url=url, ttl_seconds=ttl, storage_location_id=storage_location_id
    )
