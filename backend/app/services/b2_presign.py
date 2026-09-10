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
from typing import Optional

from app.config import get_settings

MIN_TTL_SECONDS = 1
# P5 production ceiling: Dive Analyzer clips are short; grants are refreshed
# from the authenticated route, never extended. 300s absolute max.
MAX_TTL_SECONDS = 300

SERVICE = "s3"


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
    settings = get_settings()
    ttl = clamp_ttl(ttl_seconds)
    key_id = (settings.b2_playback_key_id or "").strip()
    secret = (settings.b2_playback_key_secret or "").strip()
    if not key_id or not secret:
        raise PresignUnavailable("playback presign credential not configured")
    region = (settings.b2_playback_region or "").strip()
    if not region:
        raise PresignUnavailable("playback presign region not configured")
    endpoint = (
        settings.b2_playback_endpoint_url
        or f"https://s3.{region}.backblazeb2.com"
    ).strip()
    import boto3  # lazy: unit tests inject fakes instead

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=region,
        aws_access_key_id=key_id,
        aws_secret_access_key=secret,
    )
    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": object_key},
        ExpiresIn=ttl,
    )
    return PresignResult(
        url=url, ttl_seconds=ttl, storage_location_id=storage_location_id
    )
