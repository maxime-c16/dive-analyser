"""Deterministic media cache key generation."""

import hashlib

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
