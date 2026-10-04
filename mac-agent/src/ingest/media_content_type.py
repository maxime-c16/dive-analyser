"""Evidence-based media Content-Type mapping for future object uploads (P5).

Existing PROD objects carry Content-Type: binary/octet-stream. Historical
objects are NOT rewritten (packet P5 §20: no historical rewrite); this
helper repairs FUTURE uploads only: new media objects receive the correct
video Content-Type derived from ffprobe/container evidence, never from a
bare filename guess, and fall closed to binary/octet-stream when the
evidence is insufficient.
"""

from typing import Optional

# ffprobe format_name family strings (demuxer lists, not single values).
_MOV_FAMILY_TOKENS = ("mov",)
_MP4_FAMILY_TOKENS = ("mp4", "m4v", "isom", "mp42", "mp41", "dash")
_WEBM_TOKENS = ("webm",)
_MKV_TOKENS = ("matroska", "mkv")

DEFAULT_CONTENT_TYPE = "binary/octet-stream"

_VIDEO_CODEC_TOKENS = (
    "h264",
    "hevc",
    "h265",
    "av1",
    "vp8",
    "vp9",
    "prores",
    "mpeg2video",
    "mpeg4",
    "mjpeg",
)


def _is_video_codec(codec: Optional[str]) -> bool:
    if not codec:
        return False
    c = codec.strip().lower()
    return any(token in c for token in _VIDEO_CODEC_TOKENS)


def video_content_type(
    container: Optional[str],
    codec: Optional[str],
    staged_ext: Optional[str] = None,
) -> str:
    """Map ffprobe container/codec evidence to a wire Content-Type.

    Evidence required: a container family string from ffprobe (the demuxer
    family, e.g. "mov,mp4,m4a,3gp,3g2,mj2") plus the staged container
    extension recorded from the actual staged file. Audio-only containers
    are NOT mapped to video types (fail closed to the default).
    """
    if not _is_video_codec(codec):
        return DEFAULT_CONTENT_TYPE
    fmt = (container or "").strip().lower()
    ext = (staged_ext or "").strip().lower().lstrip(".")
    if fmt and any(tok in fmt for tok in _MOV_FAMILY_TOKENS) and ext in ("mov",):
        return "video/quicktime"
    if fmt and any(tok in fmt for tok in _MP4_FAMILY_TOKENS) and ext in ("mp4", "m4v"):
        return "video/mp4"
    if fmt and any(tok in fmt for tok in _WEBM_TOKENS) and ext == "webm":
        return "video/webm"
    if fmt and any(tok in fmt for tok in _MKV_TOKENS) and ext in ("mkv",):
        return "video/x-matroska"
    return DEFAULT_CONTENT_TYPE
