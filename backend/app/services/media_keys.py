"""Deterministic media cache key generation."""

import hashlib
import re

from app.config import get_settings


def build_media_key(video_uuid: str, rendition: str) -> str:
    """Return deterministic cache/job key for one asset rendition."""
    settings = get_settings()
    raw = ":".join([
        video_uuid,
        rendition,
        settings.media_transform_version,
        settings.media_export_policy_version,
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# D1 durable derivatives (HQ/light/poster): roles and transform identity.
#
# `DERIVATIVE_TRANSFORM_VERSION_DEFAULT` is the transform version for NEW
# derivative keys only (`ffmpeg-h264-web-v1` = the single-pass SDR/H.264
# chain: zscale→hable→BT.709, short-side scale, High@CRF23, GOP 1s,
# faststart, AAC). It MUST NOT replace `media_transform_version`
# (`ffmpeg-h264-v1`, a legacy `build_media_key` input): changing the legacy
# default would invalidate existing cache/job keys. Derivative keys carry
# their own version, resolved from
# `Settings.media_derivative_transform_version` (env
# `MEDIA_DERIVATIVE_TRANSFORM_VERSION`, same default).
DERIVATIVE_ROLES = frozenset({"hq", "light", "poster"})

DERIVATIVE_TRANSFORM_VERSION_DEFAULT = "ffmpeg-h264-web-v1"

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def get_derivative_transform_version() -> str:
    """Return the configured transform version for new derivative keys."""
    return get_settings().media_derivative_transform_version


def build_derivative_media_key(
    video_uuid: str,
    role: str,
    source_sha256: str,
    transform_version: str | None = None,
) -> str:
    """Return the deterministic cache key for one durable derivative.

    Derivation identity is
    ``(video_uuid, role, source_blob_sha256, transform_version)`` — the new
    renditions are tied to their source revision (unlike legacy rows), so a
    source change retires the old derivation instead of silently reusing it.

    Validation is fail-closed: empty video UUIDs, unknown roles, malformed
    source SHAs and empty transform versions raise ``ValueError`` before any
    hashing, so no caller can mint a key for an identity the ledger would
    reject.

    Encoding contract (D1, no existing rows): fields are joined with ``|``
    under the ``derivative-v1`` domain prefix. ``|`` is therefore rejected
    in ``video_uuid`` and ``transform_version`` so the encoded identity stays
    unambiguous. Surrounding whitespace is rejected (it would otherwise
    produce distinct keys for the same logical identity), ``video_uuid`` is
    capped at 100 chars (the ``media_derivatives.video_uuid`` DB contract)
    and ``transform_version`` at 40 chars (the ledger column contract).
    ``source_sha256`` must be an exact 64-char lowercase hex SHA-256.
    """
    if not isinstance(video_uuid, str) or not video_uuid.strip():
        raise ValueError("video_uuid must be a non-empty string")
    if video_uuid != video_uuid.strip():
        raise ValueError(f"video_uuid must not have surrounding whitespace: {video_uuid!r}")
    if "|" in video_uuid:
        raise ValueError(f"video_uuid must not contain '|': {video_uuid!r}")
    if len(video_uuid) > 100:
        raise ValueError(f"video_uuid must be <= 100 chars (media_derivatives.video_uuid contract): {len(video_uuid)}")
    if role not in DERIVATIVE_ROLES:
        raise ValueError(
            f"unknown derivative role {role!r}; expected one of {sorted(DERIVATIVE_ROLES)}"
        )
    if not isinstance(source_sha256, str) or not _SHA256_HEX_RE.fullmatch(source_sha256):
        raise ValueError(f"malformed source_sha256: {source_sha256!r}")
    version = transform_version if transform_version is not None else get_derivative_transform_version()
    if not isinstance(version, str) or not version.strip() or len(version) > 40:
        raise ValueError(f"invalid transform_version: {transform_version!r}")
    if version != version.strip():
        raise ValueError(f"transform_version must not have surrounding whitespace: {transform_version!r}")
    if "|" in version:
        raise ValueError(f"transform_version must not contain '|': {transform_version!r}")
    raw = "|".join(["derivative-v1", video_uuid, role, source_sha256, version])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
