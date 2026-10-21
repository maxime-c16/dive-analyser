"""Single-pass durable web package encoder (D3a, UNWIRED).

Produces the ``hq`` / ``light`` / ``poster`` triple from one decode in one
ffmpeg process: one tone-map (HDR only), a split, per-branch short-side
scales, two x264 encodes plus one JPEG. SDR sources skip the tone-map
entirely.

This module is deliberately UNWIRED: nothing here is called by
``media_jobs.py``, ingestion, or any server route. It is a reusable producer
the later publication slice (B2 verified publish, then queue cutover) can
call. ``Transcoder.build`` legacy behavior is unchanged.

Contract (quality annex sections 6+8, bench ``single_pass.py``):
- H.264 High, 8-bit SDR BT.709, ``-fps_mode passthrough`` (all source frames,
  VFR preserved, never forced to 30fps), faststart, CRF 23, GOP ~1 s at the
  source nominal cadence, ``maxrate 12M`` / ``bufsize 24M`` on HQ only.
- Short side: HQ ``min(source, 1080)``, light ``min(source, 720)``. Never
  upscale. Portrait yields 720x1280 / 1080x1920 (not 406x720): the scale is
  applied to the SHORT side whatever the orientation, using display
  dimensions (rotation-adjusted).
- Small sources: when the HQ target equals the light target (or the source
  is below a role floor), only ONE video encode runs; HQ is reported
  honestly as absent-aliased-to-light, never as a duplicate byte stream.
- Audio: first actually-decodable track (skip unnamed / ``none`` / ``apac``,
  plus any codec with no local ffmpeg decoder when a decoder map is
  supplied); else explicit video-only. Source bytes are never modified.
- HDR (HLG ``arib-std-b67`` / PQ ``smpte2084``) tone-maps once via
  zscale->hable->BT.709. If the ffmpeg build lacks ``zscale``, fail CLOSED
  (raise before encoding) rather than publishing HDR-black SDR bytes.
- Timeouts/cancel (D2 semantics): kill + reap the ffmpeg process, remove
  ONLY the owned attempt dir, never touch the source, siblings,
  pre-existing files, or another build's dir. A partial output set is
  never reported ready.
- Ownership: NO shared finals. Each build renames its attempt dir to a
  UNIQUE owned ``pkg-*`` result dir and returns paths inside it; the dir
  is an immutable local artifact until the future publisher verifies B2
  and calls ``PackageResult.cleanup()`` (owned dir only). ``ready=True``
  means LOCAL-VALIDATED, not durable B2.
- Memory: each x264 encode is bounded to ``threads_per_variant`` (default 2,
  mirroring the worker). One package runs two encoders concurrently; two
  package jobs would run four. Do NOT enable two package slots in production
  until a real Mac memory test passes (8 GiB box).

Source identity ties to D1: every result carries
``(video_uuid, source_sha256, transform_version)`` and per-role derivative
media keys using the exact D1 ``derivative-v1`` encoding (mirrored here so
the Mac agent needs no backend import; parity is unit-tested).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .transcoder import (
    DEFAULT_TRANSCODE_TIMEOUT_SECONDS,
    REAP_TIMEOUT_SECONDS,
    TranscodeError,
)

# ---------------------------------------------------------------------------
# Identity (D1 mirror)
# ---------------------------------------------------------------------------

#: Transform version for the web chain. MUST match backend
#: ``DERIVATIVE_TRANSFORM_VERSION_DEFAULT`` / ``MEDIA_DERIVATIVE_TRANSFORM_VERSION``.
DERIVATIVE_TRANSFORM_VERSION_DEFAULT = "ffmpeg-h264-web-v1"

DERIVATIVE_ROLES = frozenset({"hq", "light", "poster"})

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

HDR_TRANSFERS = frozenset({"smpte2084", "arib-std-b67"})

#: Codecs known to have no working ffmpeg decoder in our builds. ``apac``
#: (iPhone spatial audio) arrives as the first audio track with a name but
#: fails at decode time (quality annex Q2). Matched case-insensitively.
UNDECODABLE_AUDIO_CODECS = frozenset({"apac"})

# Chain constants (bench-measured, annex section 6).
HQ_SHORT_SIDE = 1080
LIGHT_SHORT_SIDE = 720
PACKAGE_CRF = 23
HQ_MAXRATE = "12M"
HQ_BUFSIZE = "24M"
PACKAGE_PRESET = "medium"
PACKAGE_PROFILE = "high"
AUDIO_BITRATE = "128k"
POSTER_QUALITY = 3  # ffmpeg -q:v for mjpeg (2-5 broadcast range; 3 = high)
POSTER_SHORT_SIDE = 720

TONEMAP_FILTERS = [
    "zscale=t=linear:npl=100",
    "format=gbrpf32le",
    "zscale=p=bt709",
    "tonemap=tonemap=hable:desat=0",
    "zscale=t=bt709:m=bt709:r=tv",
]

SETPARAMS_BT709 = (
    "setparams=range=limited:color_primaries=bt709"
    ":color_trc=bt709:colorspace=bt709"
)


def build_derivative_media_key(
    video_uuid: str,
    role: str,
    source_sha256: str,
    transform_version: str | None = None,
) -> str:
    """Mirror of backend ``build_derivative_media_key`` (D1 contract).

    Encoding ``derivative-v1|<uuid>|<role>|<sha>|<version>`` hashed with
    sha256. Same fail-closed validation as the backend: empty/whitespacey
    UUIDs, ``|`` in UUID/version, unknown roles, malformed SHAs and empty or
    over-long versions raise ``ValueError`` before any hashing.
    """
    if not isinstance(video_uuid, str) or not video_uuid.strip():
        raise ValueError("video_uuid must be a non-empty string")
    if video_uuid != video_uuid.strip():
        raise ValueError(f"video_uuid must not have surrounding whitespace: {video_uuid!r}")
    if "|" in video_uuid:
        raise ValueError(f"video_uuid must not contain '|': {video_uuid!r}")
    if len(video_uuid) > 100:
        raise ValueError(f"video_uuid must be <= 100 chars: {len(video_uuid)}")
    if role not in DERIVATIVE_ROLES:
        raise ValueError(f"unknown derivative role {role!r}; expected one of {sorted(DERIVATIVE_ROLES)}")
    if not isinstance(source_sha256, str) or not _SHA256_HEX_RE.fullmatch(source_sha256):
        raise ValueError(f"malformed source_sha256: {source_sha256!r}")
    version = transform_version if transform_version is not None else DERIVATIVE_TRANSFORM_VERSION_DEFAULT
    if not isinstance(version, str) or not version.strip() or len(version) > 40:
        raise ValueError(f"invalid transform_version: {transform_version!r}")
    if version != version.strip():
        raise ValueError(f"transform_version must not have surrounding whitespace: {transform_version!r}")
    if "|" in version:
        raise ValueError(f"transform_version must not contain '|': {transform_version!r}")
    raw = "|".join(["derivative-v1", video_uuid, role, source_sha256, version])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Probing
# ---------------------------------------------------------------------------

@dataclass
class SourceInfo:
    coded_w: int
    coded_h: int
    display_w: int
    display_h: int
    rotation: int
    r_frame_rate: str
    nominal_fps: float
    avg_fps: float | None
    transfer: str | None
    color_space: str | None = None
    color_primaries: str | None = None
    pix_fmt: str | None = None
    sar: str | None = None
    duration_s: float | None = None
    audio_index: int | None = None


def _ffprobe_path(ffmpeg_path: str) -> str:
    return str(Path(ffmpeg_path).with_name("ffprobe")) if "/" in ffmpeg_path else "ffprobe"


def ffmpeg_has_filter(ffmpeg_path: str, filt: str) -> bool:
    try:
        out = subprocess.check_output(
            [ffmpeg_path, "-hide_banner", "-filters"],
            stderr=subprocess.DEVNULL,
            timeout=30,
        ).decode(errors="replace")
    except Exception:
        return False
    return filt in out


def _stream_rotation(video: dict) -> int:
    for x in video.get("side_data_list", []) or []:
        if "rotation" in x:
            try:
                return abs(int(x.get("rotation", 0)))
            except (TypeError, ValueError):
                pass
    return 0


def _first_frame_rotation(source: Path, ffprobe_path: str) -> int:
    """Frame-level rotation fallback (cheap: decodes one frame).

    Real iPhone sources carry rotation in the track displaymatrix (found
    above), but SEI-only rotation would otherwise slip through and the
    explicit-scale graph would stretch the picture. Any probe failure here
    means 0 — detection is best-effort, the graph never guesses.
    """
    try:
        out = subprocess.check_output(
            [ffprobe_path, "-v", "quiet", "-print_format", "json",
             "-show_frames", "-read_intervals", "%+#1",
             "-select_streams", "v:0", str(source)],
            timeout=60,
        ).decode()
        for frame in json.loads(out).get("frames", []) or []:
            for x in frame.get("side_data_list", []) or []:
                if "rotation" in x:
                    return abs(int(x.get("rotation", 0)))
    except Exception:
        pass
    return 0


def ffmpeg_decoder_names(ffmpeg_path: str) -> set[str]:
    """Lower-cased set of decoder names AND decodable codec names.

    ``ffmpeg -decoders`` lists decoder implementations (e.g. ``mp3float``)
    with a ``(codec mp3)`` suffix naming the codec they decode. The old
    helper returned only the implementation name, so a codec whose only
    local decoder is an alias (``mp3`` via ``mp3float``) looked
    undecodable and its audio was silently dropped. We now also index
    the parenthesised codec name(s), so the returned set answers
    "can this codec be decoded here?" directly. Empty set = unprovable
    (ffmpeg call failed); callers must not claim decodability from it.
    """
    try:
        out = subprocess.check_output(
            [ffmpeg_path, "-hide_banner", "-decoders"],
            stderr=subprocess.DEVNULL,
            timeout=30,
        ).decode(errors="replace")
    except Exception:
        return set()
    return _parse_decoder_names(out)


def _parse_decoder_names(decoders_output: str) -> set[str]:
    """Parse ``ffmpeg -decoders`` text into decodable codec names.

    Pure (no subprocess) so unit tests can pin the ``mp3float`` alias
    shape without depending on the local build.
    """
    names: set[str] = set()
    for line in decoders_output.splitlines():
        parts = line.split()
        # Lines look like: " A....D apac  Marian's A-pac audio"
        if len(parts) >= 2 and len(parts[0]) == 6 and parts[0][0] in "VASD.":
            names.add(parts[1].lower())
            for m in re.finditer(r"\(codec ([^)]+)\)", line, re.IGNORECASE):
                for codec in re.split(r"[,\s]+", m.group(1).strip()):
                    if codec:
                        names.add(codec.lower())
    return names


def ffmpeg_decoder_codec_map(ffmpeg_path: str) -> dict[str, set[str]]:
    """Map decodable codec -> decoder implementations (lower-cased).

    Empty dict = unprovable. Exposed for tests/diagnostics; selection
    itself uses :func:`ffmpeg_decoder_names` (which already folds the
    mapping in) so callers keep passing one set.
    """
    try:
        out = subprocess.check_output(
            [ffmpeg_path, "-hide_banner", "-decoders"],
            stderr=subprocess.DEVNULL,
            timeout=30,
        ).decode(errors="replace")
    except Exception:
        return {}
    mapping: dict[str, set[str]] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and len(parts[0]) == 6 and parts[0][0] in "VASD.":
            decoder = parts[1].lower()
            for m in re.finditer(r"\(codec ([^)]+)\)", line, re.IGNORECASE):
                for codec in re.split(r"[,\s]+", m.group(1).strip()):
                    if codec:
                        mapping.setdefault(codec.lower(), set()).add(decoder)
    return mapping


def select_decodable_audio_index(
    streams: list[dict],
    available_decoders: set[str] | None = None,
) -> int | None:
    """First audio stream with a usable decoder, else None (video-only).

    Skips tracks with no name, ``none``, or a denylisted codec (``apac``).
    When ``available_decoders`` (lower-cased ffmpeg ``-decoders`` names as
    returned by :func:`ffmpeg_decoder_names`, alias-folded so ``mp3`` is
    present when only ``mp3float`` exists) is supplied, a named codec with
    no local decoder is also skipped. Without that map we only apply the
    denylist and never claim an allowlist guarantees decoding — callers
    that need certainty should pass ``ffmpeg_decoder_names(ffmpeg)``.
    An EMPTY set means the inventory call failed (unprovable): the
    caller keeps the denylist-only choice and lets the encode fail
    closed rather than claiming decodability.
    """
    for stream in streams:
        if stream.get("codec_type") != "audio":
            continue
        codec = stream.get("codec_name")
        if not codec or not isinstance(codec, str):
            continue
        low = codec.lower()
        if low == "none" or low in UNDECODABLE_AUDIO_CODECS:
            continue
        if available_decoders is not None and low not in available_decoders:
            continue
        index = stream.get("index")
        if isinstance(index, int):
            return index
    return None


def _parse_sar(sar: object) -> float | None:
    """Parse ``sample_aspect_ratio`` (``"N:D"``) to a float, else None."""
    if not isinstance(sar, str) or ":" not in sar:
        return None
    try:
        n, d = sar.split(":", 1)
        n_f, d_f = float(n), float(d)
    except (ValueError, TypeError):
        return None
    if not d_f or n_f <= 0 or d_f <= 0:
        return None
    return n_f / d_f


def probe_source(source: Path, ffprobe_path: str = "ffprobe") -> SourceInfo:
    try:
        result = subprocess.run(
            [
                ffprobe_path, "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", str(source),
            ],
            check=True, capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
    except Exception:
        raise TranscodeError("Unable to probe source streams") from None
    try:
        streams = data.get("streams", [])
        video = next(s for s in streams if s.get("codec_type") == "video")
        w, h = int(video["width"]), int(video["height"])
        rotation = _stream_rotation(video)
        if not rotation:
            try:
                rotation = abs(int((video.get("tags", {}) or {}).get("rotate", 0)))
            except (TypeError, ValueError):
                rotation = 0
        if not rotation:
            rotation = _first_frame_rotation(source, ffprobe_path)
        sar_raw = video.get("sample_aspect_ratio")
        sar_f = _parse_sar(sar_raw)
        # Anamorphic sources store non-square pixels: display width is
        # coded width x SAR. Outputs always use square pixels (setsar=1
        # in every video branch), so the plan works from SAR-adjusted
        # display dims. SAR 0/unknown/invalid = assume 1:1 (recorded).
        if sar_f is not None and sar_f != 1.0:
            disp_w_pre, disp_h_pre = round(w * sar_f), h
        else:
            disp_w_pre, disp_h_pre = w, h
        dw, dh = (disp_h_pre, disp_w_pre) if rotation in (90, 270) else (disp_w_pre, disp_h_pre)  # ffmpeg autorotates
        rfr = video.get("r_frame_rate") or "0/1"
        n, d = rfr.split("/")
        nominal = float(n) / float(d) if float(d) else 0.0
        afr = video.get("avg_frame_rate") or "0/1"
        an, ad = afr.split("/")
        avg = float(an) / float(ad) if float(ad) else None
        fmt = data.get("format", {})
        duration = float(fmt["duration"]) if fmt.get("duration") else None
        audio_index = select_decodable_audio_index(streams)
        return SourceInfo(
            coded_w=w, coded_h=h, display_w=dw, display_h=dh, rotation=rotation,
            r_frame_rate=rfr, nominal_fps=nominal, avg_fps=avg,
            transfer=video.get("color_transfer"),
            color_space=video.get("color_space"),
            color_primaries=video.get("color_primaries"),
            pix_fmt=video.get("pix_fmt"),
            sar=(sar_raw if isinstance(sar_raw, str) else None),
            duration_s=duration, audio_index=audio_index,
        )
    except (StopIteration, KeyError, ValueError, TypeError, AttributeError):
        raise TranscodeError("Unable to read source video metadata") from None


def count_frames(path: Path, ffprobe_path: str = "ffprobe") -> int:
    """Decoded (presented) frame count — packet counts lie under Photos edit lists."""
    try:
        out = subprocess.check_output(
            [ffprobe_path, "-v", "quiet", "-count_frames", "-select_streams", "v:0",
             "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(path)],
            timeout=120,
        ).decode().strip().strip(",")
        return int(out or 0)
    except Exception:
        raise TranscodeError(f"Unable to count frames in {path}") from None


# ---------------------------------------------------------------------------
# Planning (pure; no ffmpeg)
# ---------------------------------------------------------------------------

def _even_ceil(value: float) -> int:
    return max(2, int(2 * math.ceil(value / 2)))


def short_side_target_dims(display_w: int, display_h: int, short_target: int) -> tuple[int, int]:
    """Target (w, h) for a short-side target, never upscaling, always even.

    Policy: scale the long side proportionally, ``ceil`` to even (so the
    short side reaches at least the target when the source allows it), then
    step down by 2 if the ceil overshoots the source (odd-edge no-upscale
    guard). When the source short side is at or below the target, return the
    source dims rounded DOWN to even (no upscale, aspect preserved to 1px).
    """
    if display_w < 2 or display_h < 2:
        raise ValueError(f"invalid display dims {display_w}x{display_h}")
    short = min(display_w, display_h)
    long = max(display_w, display_h)
    portrait = display_h > display_w
    if short_target >= short:
        w = display_w - (display_w % 2)
        h = display_h - (display_h % 2)
        return (w, h)
    long_t = _even_ceil(long * short_target / short)
    if long_t > long - (long % 2):
        long_t = long - (long % 2)  # ceil overshoot guard: never exceed source
    if portrait:
        return (short_target if short_target % 2 == 0 else short_target - 1, long_t)
    return (long_t, short_target if short_target % 2 == 0 else short_target - 1)


def nominal_gop(r_frame_rate: str, avg_fps: float | None = None) -> int:
    """GOP length for ~1 s at the source nominal cadence (VFR-safe)."""
    try:
        n, d = r_frame_rate.split("/")
        fps = float(n) / float(d) if float(d) else 0.0
    except (ValueError, AttributeError):
        fps = 0.0
    if not fps and avg_fps:
        fps = avg_fps
    if not fps:
        fps = 60.0
    return max(1, min(600, int(round(fps))))


#: Color space/primaries values that need a real gamut conversion
#: (matrix-only scale conversion is not enough). Any 2020 variant lands
#: here; anything else narrow/unknown is handled by the scale matrix.
WIDE_GAMUT_MARKERS = frozenset({"bt2020", "bt2020nc", "bt2020c", "2020"})


def _is_wide_gamut(info: SourceInfo) -> bool:
    for marker in ((info.color_space or ""), (info.color_primaries or "")):
        if marker and marker.lower() in WIDE_GAMUT_MARKERS:
            return True
    return False


def _poster_thumb_time(duration_s: float | None, nominal_fps: float) -> float | None:
    """Thumbnail timestamp that always lies inside the frame interval.

    The old ``duration >= 1 -> select gte(t,1)`` emitted an empty poster
    for exact-1.0 s clips (last frame < 1 s) and for unknown durations.
    Now: no select (first frame) when the duration is unknown or under
    1 s; otherwise the latest safe time at-or-before 1 s, backed off by
    one frame interval so the selected frame provably exists even for
    exact-length or VFR sources.
    """
    if duration_s is None or duration_s < 1.0:
        return None
    fps = nominal_fps if nominal_fps and nominal_fps > 0 else 60.0
    # Back off ~2.5 frame intervals from the duration edge so the select
    # provably matches a real frame even for exact-length clips (the old
    # one-interval backoff landed just past the last frame timestamp:
    # 1.0 s @ 30 fps ends at 0.9667 < 0.967 -> empty poster -> EOF fail).
    # Long clips still pin at ~1 s, avoiding black leaders.
    thumb_t = min(1.0, max(0.0, duration_s - 2.5 / fps))
    if thumb_t <= 0.0:
        return None
    return round(thumb_t, 3)


@dataclass
class PackagePlan:
    display_w: int
    display_h: int
    is_hdr: bool
    wide_gamut_sdr: bool  # SDR but bt2020-family: needs zscale gamut convert
    requires_zscale: bool  # is_hdr or wide_gamut_sdr
    gop: int
    hq_applicable: bool
    hq_dims: tuple[int, int] | None
    hq_aliased_to: str | None  # "light" when HQ is honestly absent
    light_dims: tuple[int, int]
    poster_dims: tuple[int, int]
    poster_needs_select: bool  # legacy flag (= poster_thumb_t is not None)
    poster_thumb_t: float | None  # safe select timestamp, None = first frame
    audio_index: int | None


def plan_package(info: SourceInfo) -> PackagePlan:
    short = min(info.display_w, info.display_h)
    is_hdr = (info.transfer or "") in HDR_TRANSFERS
    wide_sdr = (not is_hdr) and _is_wide_gamut(info)
    gop = nominal_gop(info.r_frame_rate, info.avg_fps)
    light_dims = short_side_target_dims(info.display_w, info.display_h, LIGHT_SHORT_SIDE)
    if short >= HQ_SHORT_SIDE:
        hq_dims: tuple[int, int] | None = short_side_target_dims(info.display_w, info.display_h, HQ_SHORT_SIDE)
        hq_applicable = hq_dims != light_dims
        alias = None if hq_applicable else "light"
        if not hq_applicable:
            hq_dims = None
    else:
        hq_applicable = False
        hq_dims = None
        alias = "light"
    poster_dims = light_dims  # poster rides the light-scale branch size
    thumb_t = _poster_thumb_time(info.duration_s, info.nominal_fps)
    return PackagePlan(
        display_w=info.display_w, display_h=info.display_h, is_hdr=is_hdr,
        wide_gamut_sdr=wide_sdr, requires_zscale=(is_hdr or wide_sdr), gop=gop,
        hq_applicable=hq_applicable, hq_dims=hq_dims, hq_aliased_to=alias,
        light_dims=light_dims, poster_dims=poster_dims,
        poster_needs_select=(thumb_t is not None), poster_thumb_t=thumb_t,
        audio_index=info.audio_index,
    )


# ---------------------------------------------------------------------------
# Command construction (pure; no ffmpeg execution)
# ---------------------------------------------------------------------------

def _scale_branch(w: int, h: int) -> str:
    """SDR scale branch: explicit matrix convert + square pixels + BT.709 tags.

    ``out_color_matrix=bt709`` asks the scale filter to actually convert
    from the input matrix (auto-detected per frame: bt601/bt709/...) to
    BT.709 instead of just relabelling colours as converted. ``setsar=1``
    normalises anamorphic inputs to square pixels (the plan already works
    from SAR-adjusted display dims).
    """
    return (
        f"scale={w}:{h}:flags=bicubic:out_range=tv:out_color_matrix=bt709,"
        f"format=yuv420p,setsar=1,{SETPARAMS_BT709}"
    )


#: Gamut pre-conversion for wide-gamut SDR (bt2020-family transfer is SDR
#: but primaries need a real conversion scale cannot do). Runs before the
#: split when zscale is available; otherwise the build fails closed.
ZSCALE_GAMUT_TO_BT709 = "zscale=p=bt709:m=bt709:r=tv"


def _x264_args(gop: int, threads: int, hq: bool) -> list[str]:
    args = [
        "-c:v", "libx264", "-threads", str(threads), "-preset", PACKAGE_PRESET,
        "-profile:v", PACKAGE_PROFILE, "-crf", str(PACKAGE_CRF),
    ]
    if hq:
        args += ["-maxrate", HQ_MAXRATE, "-bufsize", HQ_BUFSIZE]
    args += [
        "-pix_fmt", "yuv420p", "-g", str(gop), "-keyint_min", str(gop),
        "-color_range", "tv", "-colorspace", "bt709",
        "-color_primaries", "bt709", "-color_trc", "bt709",
        "-tag:v", "avc1", "-movflags", "+faststart",
    ]
    return args


def build_package_cmd(
    source: Path,
    hq_out: Path | None,
    light_out: Path,
    poster_out: Path,
    plan: PackagePlan,
    *,
    ffmpeg_path: str = "ffmpeg",
    threads_per_variant: int = 2,
) -> list[str]:
    """Single ffmpeg command: one decode, one tone-map, split to outputs."""
    if threads_per_variant < 1:
        raise ValueError("threads_per_variant must be >= 1")
    n_video = 2 if plan.hq_applicable else 1
    n_splits = n_video + 1  # + poster
    labels = (["[a]", "[b]", "[c]"] if n_splits == 3 else ["[a]", "[b]"])
    if plan.is_hdr:
        head = "[0:v]" + ",".join(TONEMAP_FILTERS + [f"split={n_splits}"])
    elif plan.wide_gamut_sdr:
        # SDR but bt2020-family primaries: real gamut convert first
        # (matrix-only scale conversion would mistint), then split.
        head = f"[0:v]{ZSCALE_GAMUT_TO_BT709},split={n_splits}"
    else:
        head = f"[0:v]split={n_splits}"
    graph_parts = [head + "".join(labels)]
    idx = 0
    if plan.hq_applicable:
        assert plan.hq_dims is not None and hq_out is not None
        w, h = plan.hq_dims
        graph_parts.append(f"{labels[idx]}{_scale_branch(w, h)}[hq]")
        idx += 1
    lw, lh = plan.light_dims
    graph_parts.append(f"{labels[idx]}{_scale_branch(lw, lh)}[lt]")
    idx += 1
    pw, ph = plan.poster_dims
    if plan.poster_thumb_t is not None:
        t = f"{plan.poster_thumb_t:.3f}"
        graph_parts.append(f"{labels[idx]}select='gte(t\\,{t})',{_scale_branch(pw, ph)}[po]")
    else:
        graph_parts.append(f"{labels[idx]}{_scale_branch(pw, ph)}[po]")
    graph = ";".join(graph_parts)

    audio = (
        ["-map", f"0:{plan.audio_index}", "-c:a", "aac", "-b:a", AUDIO_BITRATE]
        if plan.audio_index is not None else ["-an"]
    )
    # Per-output audio mapping: duplicate the selected track into each mp4.
    cmd: list[str] = [
        ffmpeg_path, "-y", "-ignore_unknown", "-threads", "2", "-i", str(source),
        "-filter_complex", graph, "-filter_threads", "1",
    ]
    if plan.hq_applicable:
        assert hq_out is not None
        cmd += ["-map", "[hq]", *audio, "-sn", "-dn", "-map_metadata", "-1",
                "-fps_mode", "passthrough", *_x264_args(plan.gop, threads_per_variant, hq=True),
                str(hq_out)]
    cmd += ["-map", "[lt]", *audio, "-sn", "-dn", "-map_metadata", "-1",
            "-fps_mode", "passthrough", *_x264_args(plan.gop, threads_per_variant, hq=False),
            str(light_out)]
    cmd += ["-map", "[po]", "-an", "-sn", "-dn", "-map_metadata", "-1",
            "-frames:v", "1", "-q:v", str(POSTER_QUALITY), str(poster_out)]
    return cmd


# ---------------------------------------------------------------------------
# Execution + validation
# ---------------------------------------------------------------------------

@dataclass
class OutputMeta:
    role: str
    path: Path
    sha256: str
    size_bytes: int
    width: int
    height: int


@dataclass
class PackageResult:
    video_uuid: str
    source_sha256: str
    transform_version: str
    source_w: int
    source_h: int
    source_frames: int
    nominal_fps: float
    avg_fps: float | None = None
    transfer_in: str | None = None
    hq: OutputMeta | None = None
    hq_aliased_to: str | None = None
    light: OutputMeta | None = None  # type: ignore[assignment]
    poster: OutputMeta | None = None  # type: ignore[assignment]
    media_keys: dict[str, str] = field(default_factory=dict)
    encode_seconds: float = 0.0
    validation: dict = field(default_factory=dict)
    ready: bool = False
    # Owned immutable local package directory holding the validated
    # hq/light/poster bytes. ``ready=True`` means LOCAL-VALIDATED only,
    # NOT durable B2: the future publisher uploads from here, verifies,
    # then calls ``cleanup()``. Until then the producer owns this dir and
    # nothing else may write, replace, or delete inside it.
    result_dir: Path | None = None

    def cleanup(self) -> None:
        """Remove ONLY the owned ``result_dir``. Idempotent.

        Never deletes the source, siblings, ``out_dir`` itself, or any
        other build's directory. Refuses anything that does not look
        like an owned ``pkg-*`` result dir inside its own parent.
        Local cleanup is not a retention policy and never a broad
        source cleanup — the future publisher calls this after a
        verified B2 commit.
        """
        owned = self.result_dir
        if owned is None:
            return
        try:
            name = Path(owned).name
            if not name.startswith("pkg-"):
                return
            target = Path(owned)
            if not target.is_dir() or target.is_symlink():
                return
            shutil.rmtree(target, ignore_errors=True)
        except Exception:
            pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def _kill_and_reap(process: "asyncio.subprocess.Process") -> None:
    try:
        process.kill()
    except ProcessLookupError:
        pass
    with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError):
        await asyncio.wait_for(asyncio.shield(process.wait()), timeout=REAP_TIMEOUT_SECONDS)


def _atom_order(path: Path) -> list[str]:
    atoms: list[str] = []
    with open(path, "rb") as f:
        pos, total = 0, path.stat().st_size
        while pos < total:
            f.seek(pos)
            header = f.read(16)
            if len(header) < 8:
                break
            size = int.from_bytes(header[:4], "big")
            kind = header[4:8].decode("latin1")
            if size == 1:
                size = int.from_bytes(header[8:16], "big")
            elif size == 0:
                size = total - pos
            if size <= 0:
                break
            atoms.append(kind)
            pos += size
    return atoms


def _is_faststart(path: Path) -> bool | None:
    try:
        atoms = _atom_order(path)
    except OSError:
        return None
    if "moov" in atoms and "mdat" in atoms:
        return atoms.index("moov") < atoms.index("mdat")
    return None


def _ffprobe_streams(path: Path, ffprobe_path: str) -> dict:
    out = subprocess.check_output(
        [ffprobe_path, "-v", "quiet", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        timeout=60,
    ).decode()
    return json.loads(out)


def _keyframe_times_s(path: Path, ffprobe_path: str) -> list[float] | None:
    try:
        out = subprocess.check_output(
            [ffprobe_path, "-v", "quiet", "-select_streams", "v:0",
             "-skip_frame", "nokey", "-show_entries", "frame=pts_time",
             "-of", "csv=p=0", str(path)],
            timeout=60,
        ).decode().split()
        return sorted(float(v.strip(",")) for v in out if v.strip(","))
    except Exception:
        return None


def _median_keyframe_gap_s(path: Path, ffprobe_path: str) -> tuple[float | None, int]:
    times = _keyframe_times_s(path, ffprobe_path)
    if not times:
        return None, 0
    import statistics as _st

    gaps = [b - a for a, b in zip(times, times[1:]) if b > a]
    if not gaps:
        return None, len(times)
    return round(_st.median(gaps), 3), len(times)


def validate_package_outputs(
    *,
    hq_out: Path | None,
    light_out: Path,
    poster_out: Path,
    plan: PackagePlan,
    source_frames: int,
    source_duration_s: float | None = None,
    ffprobe_path: str = "ffprobe",
) -> dict:
    """Probe actual outputs; return ``{"ready": bool, "checks": {...}}``."""
    checks: dict[str, object] = {}

    def check_mp4(role: str, path: Path, dims: tuple[int, int], is_hq: bool) -> bool:
        ok = True
        try:
            data = _ffprobe_streams(path, ffprobe_path)
        except Exception as exc:
            checks[f"{role}.probe"] = f"FAIL unreadable: {exc}"
            return False
        streams = data.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        if video is None:
            checks[f"{role}.video_stream"] = "FAIL missing"
            return False
        exp_w, exp_h = dims
        tests = {
            f"{role}.codec": video.get("codec_name") == "h264",
            f"{role}.profile": (video.get("profile") or "") == "High",
            f"{role}.pix_fmt": (video.get("pix_fmt") or "") == "yuv420p",
            f"{role}.dims": (video.get("width"), video.get("height")) == (exp_w, exp_h),
            f"{role}.transfer": (video.get("color_transfer") or "") == "bt709",
            f"{role}.primaries": (video.get("color_primaries") or "") == "bt709",
            f"{role}.matrix": (video.get("color_space") or "") == "bt709",
        }
        for name, passed in tests.items():
            checks[name] = "ok" if passed else f"FAIL got={name}"
            ok = ok and passed
        try:
            frames = count_frames(path, ffprobe_path)
        except TranscodeError as exc:
            checks[f"{role}.frames"] = f"FAIL {exc}"
            return False
        same = frames == source_frames
        checks[f"{role}.frames"] = "ok" if same else f"FAIL got={frames} want={source_frames}"
        ok = ok and same
        fs = _is_faststart(path)
        checks[f"{role}.faststart"] = "ok" if fs else f"FAIL faststart={fs}"
        ok = ok and bool(fs)
        gap, n_keys = _median_keyframe_gap_s(path, ffprobe_path)
        checks[f"{role}.gop_median_s"] = gap
        checks[f"{role}.keyframes"] = n_keys
        if gap is not None:
            # GOP is ~1 s at the source nominal cadence by construction;
            # generous VFR-tolerant window. Records evidence, fails only if wild.
            in_window = 0.4 <= gap <= 2.5
            checks[f"{role}.gop_window"] = "ok" if in_window else f"FAIL gap={gap}"
            ok = ok and in_window
        elif n_keys >= 1 and (source_duration_s or 0.0) < 2.0:
            # Short clip: a single keyframe is the correct GOP shape.
            checks[f"{role}.gop_window"] = "ok-single-keyframe-short-clip"
        else:
            checks[f"{role}.gop_window"] = f"FAIL keys={n_keys}"
            ok = False
        audios = [s for s in streams if s.get("codec_type") == "audio"]
        if plan.audio_index is not None:
            has_aac = any((s.get("codec_name") or "") == "aac" for s in audios)
            checks[f"{role}.audio"] = "ok" if has_aac else f"FAIL audio={audios}"
            ok = ok and has_aac
        else:
            checks[f"{role}.audio"] = "ok" if not audios else f"FAIL unexpected-audio"
            ok = ok and not audios
        _ = is_hq
        return ok

    ready = True
    if plan.hq_applicable:
        assert hq_out is not None and plan.hq_dims is not None
        ready = check_mp4("hq", hq_out, plan.hq_dims, True) and ready
    else:
        checks["hq.applicability"] = f"absent aliased-to={plan.hq_aliased_to}"
    ready = check_mp4("light", light_out, plan.light_dims, False) and ready

    # Poster: JPEG, shared-branch dims, SDR (never HLG/PQ-tagged), decodable.
    try:
        data = _ffprobe_streams(poster_out, ffprobe_path)
        pvideo = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
        if pvideo is None:
            checks["poster.video_stream"] = "FAIL missing"
            ready = False
        else:
            pw, ph = plan.poster_dims
            ptests = {
                "poster.codec": (pvideo.get("codec_name") or "") in ("mjpeg", "jpg", "jpeg"),
                "poster.dims": (pvideo.get("width"), pvideo.get("height")) == (pw, ph),
                "poster.not_hdr": (pvideo.get("color_transfer") or "bt709") not in HDR_TRANSFERS,
            }
            for name, passed in ptests.items():
                checks[name] = "ok" if passed else "FAIL"
                ready = ready and passed
        with open(poster_out, "rb") as f:
            magic = f.read(3)
        is_jpeg = magic[:2] == b"\xff\xd8"
        checks["poster.jpeg_magic"] = "ok" if is_jpeg else "FAIL"
        ready = ready and is_jpeg
    except Exception as exc:
        checks["poster.probe"] = f"FAIL {exc}"
        ready = False
    return {"ready": ready, "checks": checks}


def _early_identity_check(video_uuid: str, version: str, source_sha256: str) -> None:
    """Fail fast on bad identity BEFORE any probe/encode or output.

    Late ``ValueError`` (after ffmpeg) previously wasted a full encode
    and left outputs behind for the error path to clean. Validating the
    exact D1 key encoding up front costs microseconds.
    """
    build_derivative_media_key(video_uuid, "light", source_sha256, version)


def _stat_snapshot(path: Path) -> tuple[int, int]:
    st = path.stat()
    return (st.st_size, st.st_mtime_ns)


def _cleanup_attempt_dir(attempt_dir: Path | None) -> None:
    """Remove ONLY the owned per-attempt scratch dir. Never touches finals."""
    if attempt_dir is None:
        return
    with contextlib.suppress(Exception):
        shutil.rmtree(attempt_dir, ignore_errors=True)


def _sanitize_uuid_for_dir(video_uuid: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", video_uuid)[:50].strip("._-")
    return safe or "clip"


def _rename_attempt_to_result_sync(
    attempt_dir: Path, out_dir: Path, video_uuid: str
) -> Path:
    """Rename the owned attempt dir to a UNIQUE owned result dir (atomic).

    Single ``os.rename`` of the whole directory: no shared stable
    ``hq.mp4``/``light.mp4``/``poster.jpg`` finals exist, so concurrent
    builds can never overwrite each other's returned paths, a partial
    multi-file replace cannot mix old/new finals, and a small-source
    build has no shared HQ to delete. The suffix comes from the
    mkdtemp-unique attempt name, so two builds with the same uuid still
    land in distinct dirs. Raises on failure without touching any other
    dir or any pre-existing file.
    """
    name = attempt_dir.name
    suffix = name[len(".pkg-attempt-"):] if name.startswith(".pkg-attempt-") else None
    if not suffix:
        import uuid as _uuid

        suffix = _uuid.uuid4().hex[:8]
    safe = _sanitize_uuid_for_dir(video_uuid)
    for _ in range(5):
        candidate = out_dir / f"pkg-{safe}-{suffix}"
        try:
            os.rename(attempt_dir, candidate)
            return candidate
        except FileExistsError:
            import uuid as _uuid

            suffix = _uuid.uuid4().hex[:8]
            continue
    # Last attempt lets the error propagate (fail-closed, own attempt kept
    # for the caller to clean; nothing else touched).
    os.rename(attempt_dir, out_dir / f"pkg-{safe}-{suffix}")
    raise TranscodeError("package_encoder: could not claim unique result dir")


async def _shield_await(task: "asyncio.Task") -> object:
    """Await a thread-owned task to completion, preserving cancellation.

    ``await asyncio.to_thread(...)`` inline lets ``CancelledError``
    (a ``BaseException``, not ``Exception``) propagate while the thread
    is still reading outputs — the old ``except Exception`` cleanup then
    skipped, left outputs behind, and ``rmtree`` could race the live
    probe. Shielding waits the thread out before re-raising so cleanup
    never unlinks files out from under an active probe.
    """
    try:
        return await asyncio.shield(task)
    except BaseException:
        with contextlib.suppress(BaseException):
            await task
        raise


def _resolve_owned_paths(source: Path, out_dir: Path) -> tuple[Path, Path]:
    """Resolve source/out_dir and refuse source-inside-outputs (fail-closed).

    Compares fully resolved (symlink-free) paths: the source must be a
    real file OUTSIDE the output tree. This closes the old hole where
    ``source == out_dir/light.mp4`` was overwritten by ``ffmpeg -y``
    and the failure cleanup then unlinked the SOURCE.
    """
    src_resolved = Path(os.path.realpath(source))
    out_resolved = Path(os.path.realpath(out_dir))
    if src_resolved == out_resolved or src_resolved.is_relative_to(out_resolved):
        raise TranscodeError(
            f"package_encoder: source {source} resolves inside out_dir {out_dir}; "
            "refusing to encode (would overwrite the source)"
        )
    return src_resolved, out_resolved


def frame_pts_times_s(path: Path, ffprobe_path: str = "ffprobe") -> list[float] | None:
    """Presented-frame PTS list (seconds) for VFR/cadence honesty checks."""
    try:
        out = subprocess.check_output(
            [ffprobe_path, "-v", "quiet", "-select_streams", "v:0",
             "-show_entries", "frame=pts_time",
             "-of", "csv=p=0", str(path)],
            timeout=60,
        ).decode().split()
        return sorted(float(v.strip(",")) for v in out if v.strip(","))
    except Exception:
        return None


async def build_package(
    source: Path,
    out_dir: Path,
    *,
    video_uuid: str,
    source_sha256: str,
    transform_version: str | None = None,
    ffmpeg_path: str = "ffmpeg",
    ffprobe_path: str | None = None,
    threads_per_variant: int = 2,
    timeout_seconds: int = DEFAULT_TRANSCODE_TIMEOUT_SECONDS,
) -> PackageResult:
    """Run the single-pass package encode and validate actual outputs.

    Fail-closed throughout: any problem raises ``TranscodeError`` (bad
    identity raises ``ValueError`` before any work), partial outputs are
    confined to an owned per-attempt scratch dir that is removed on
    failure, pre-existing ``out_dir`` files are never written, replaced,
    or deleted on success OR failure, and the source is never written
    or unlinked. There are NO shared stable finals: each build renames
    its own attempt dir to a UNIQUE owned ``pkg-*`` result dir and
    returns paths inside it. The retained dir is an immutable local
    package artifact owned by the producer until the future publisher
    verifies B2 and calls ``PackageResult.cleanup()`` (owned dir only).
    A returned result with ``ready=True`` means LOCAL-VALIDATED (every
    ffprobe check passed on the final bytes), NOT durable B2. All
    blocking I/O runs in threads so the worker heartbeat stays
    responsive.
    """
    if not isinstance(source_sha256, str) or not _SHA256_HEX_RE.fullmatch(source_sha256):
        raise ValueError(f"malformed source_sha256: {source_sha256!r}")
    version = transform_version if transform_version is not None else DERIVATIVE_TRANSFORM_VERSION_DEFAULT
    if not isinstance(version, str) or not version.strip() or len(version) > 40 or "|" in version:
        raise ValueError(f"invalid transform_version: {transform_version!r}")
    if threads_per_variant < 1:
        raise ValueError("threads_per_variant must be >= 1")
    # Early identity check: invalid UUID/version fails BEFORE probe,
    # hash, ffmpeg, or any output — the old late ValueError wasted a
    # full encode and left outputs behind.
    _early_identity_check(video_uuid, version, source_sha256)
    probe_bin = ffprobe_path or _ffprobe_path(ffmpeg_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    src_path = Path(source)
    if not src_path.is_file():
        raise TranscodeError(f"package_encoder: source not found: {source}")
    _resolve_owned_paths(src_path, out_dir)
    src_resolved = Path(os.path.realpath(src_path))

    # Owned per-attempt scratch dir, unique inside out_dir: concurrent
    # package builds on the same out_dir encode in isolation. On success
    # the WHOLE dir is renamed to a UNIQUE owned pkg-* result dir and
    # retained as the immutable artifact; pre-existing out_dir files are
    # NEVER written/replaced/deleted, and failure/cancel removes ONLY
    # the owned attempt.
    attempt_dir = Path(tempfile.mkdtemp(prefix=".pkg-attempt-", dir=str(out_dir)))
    result_dir: Path | None = None
    attempt_claimed = False
    process: "asyncio.subprocess.Process | None" = None
    import time as _time

    try:
        # Source integrity: hash ACTUAL bytes off-loop and compare to the
        # caller-provided SHA before encoding. The old code trusted the
        # string syntactically, so ready keys could bind the wrong revision.
        # Stat snapshot guards against the file changing under us.
        stat_before = _stat_snapshot(src_resolved)
        actual_sha_task = asyncio.create_task(asyncio.to_thread(_sha256, src_resolved))
        try:
            actual_sha = await asyncio.shield(actual_sha_task)
        except BaseException:
            with contextlib.suppress(BaseException):
                await actual_sha_task
            raise
        stat_after_hash = _stat_snapshot(src_resolved)
        if stat_before != stat_after_hash:
            raise TranscodeError("package_encoder: source changed during hash; refusing to encode")
        if actual_sha != source_sha256.lower():
            raise TranscodeError(
                "package_encoder: source_sha256 mismatch: caller-provided does not match "
                "actual source bytes; refusing to encode (fail-closed)"
            )

        info_task = asyncio.create_task(asyncio.to_thread(probe_source, src_resolved, probe_bin))
        try:
            info = await asyncio.shield(info_task)
        except BaseException:
            with contextlib.suppress(BaseException):
                await info_task
            raise
        # Re-resolve the audio choice against ACTUAL local decoder
        # capability. The names set is alias-folded (mp3 via mp3float
        # counts), so usable audio is preserved. Empty = unprovable:
        # keep the probe-time denylist-only choice and let the encode
        # fail closed rather than claiming decodability.
        try:
            raw_task = asyncio.create_task(
                asyncio.to_thread(
                    subprocess.check_output,
                    [probe_bin, "-v", "quiet", "-show_entries",
                     "stream=index,codec_type,codec_name", "-of", "json", str(src_resolved)],
                    timeout=30,
                )
            )
            try:
                raw_out = await asyncio.shield(raw_task)
            except BaseException:
                with contextlib.suppress(BaseException):
                    await raw_task
                raise
            raw_streams = json.loads(raw_out.decode()).get("streams", [])
            dec_task = asyncio.create_task(asyncio.to_thread(ffmpeg_decoder_names, ffmpeg_path))
            try:
                decoders = await asyncio.shield(dec_task)
            except BaseException:
                with contextlib.suppress(BaseException):
                    await dec_task
                raise
            if decoders:
                info = SourceInfo(**{**info.__dict__, "audio_index": select_decodable_audio_index(raw_streams, decoders)})
        except (TranscodeError, asyncio.CancelledError):
            raise
        except Exception:
            pass
        # Source must not have changed while probing.
        if _stat_snapshot(src_resolved) != stat_before:
            raise TranscodeError("package_encoder: source changed during probe; refusing to encode")

        plan = plan_package(info)
        has_zscale_task = asyncio.create_task(asyncio.to_thread(ffmpeg_has_filter, ffmpeg_path, "zscale"))
        try:
            has_zscale = await asyncio.shield(has_zscale_task)
        except BaseException:
            with contextlib.suppress(BaseException):
                await has_zscale_task
            raise
        if plan.requires_zscale and not has_zscale:
            kind = "HDR" if plan.is_hdr else "wide-gamut SDR"
            raise TranscodeError(
                f"package_encoder: {kind} source requires zscale tone-map/gamut conversion "
                "but this ffmpeg lacks zscale; refusing to emit mistinted bytes (fail-closed)"
            )

        hq_tmp = attempt_dir / "hq.mp4" if plan.hq_applicable else None
        light_tmp = attempt_dir / "light.mp4"
        poster_tmp = attempt_dir / "poster.jpg"
        cmd = build_package_cmd(
            src_resolved, hq_tmp, light_tmp, poster_tmp, plan,
            ffmpeg_path=ffmpeg_path, threads_per_variant=threads_per_variant,
        )

        started = _time.monotonic()
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            await _kill_and_reap(process)
            process = None
            raise TranscodeError(f"ffmpeg_timeout after {timeout_seconds}s package={' '.join(cmd)}") from None
        except BaseException:
            await _kill_and_reap(process)
            process = None
            raise
        elapsed = _time.monotonic() - started
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace")[-1000:] if stderr else ""
            raise TranscodeError(f"ffmpeg_failed package={' '.join(cmd)}\n{detail}")

        try:
            # Source must be unchanged after the encode too; outputs bind
            # (video_uuid, source_sha) so a mid-build swap must fail closed.
            if _stat_snapshot(src_resolved) != stat_before:
                raise TranscodeError("package_encoder: source changed during encode; refusing ready")
            frames_task = asyncio.create_task(asyncio.to_thread(count_frames, src_resolved, probe_bin))
            try:
                source_frames = await _shield_await(frames_task)
            except BaseException:
                raise
            val_task = asyncio.create_task(asyncio.to_thread(
                validate_package_outputs,
                hq_out=hq_tmp, light_out=light_tmp, poster_out=poster_tmp,
                plan=plan, source_frames=source_frames,
                source_duration_s=info.duration_s, ffprobe_path=probe_bin,
            ))
            try:
                report = await _shield_await(val_task)
            except BaseException:
                raise
        except BaseException:
            raise
        if not report.get("ready"):
            raise TranscodeError(f"package validation failed: {report.get('checks')}")

        def _meta_sync(role: str, path: Path) -> OutputMeta:
            data = _ffprobe_streams(path, probe_bin)
            video = next(s for s in data["streams"] if s.get("codec_type") == "video")
            return OutputMeta(
                role=role, path=path, sha256=_sha256(path), size_bytes=path.stat().st_size,
                width=int(video["width"]), height=int(video["height"]),
            )

        try:
            meta_task = asyncio.create_task(asyncio.to_thread(
                lambda: (
                    (_meta_sync("hq", hq_tmp) if (hq_tmp is not None and plan.hq_applicable) else None),
                    _meta_sync("light", light_tmp),
                    _meta_sync("poster", poster_tmp),
                )
            ))
            try:
                hq_meta_tmp, light_meta_tmp, poster_meta_tmp = await _shield_await(meta_task)
            except BaseException:
                raise
        except Exception as exc:
            raise TranscodeError(f"package metadata failed: {exc}") from exc

        # Publish: NO shared finals. Rename the WHOLE owned attempt dir to
        # a UNIQUE owned result dir (single atomic rename). The returned
        # paths live inside that immutable artifact; concurrent builds
        # never overwrite each other, a partial replace cannot mix
        # old/new finals, and there is no shared HQ for a small-source
        # build to delete. Pre-existing out_dir files are never touched.
        rename_task = asyncio.create_task(asyncio.to_thread(
            _rename_attempt_to_result_sync, attempt_dir, out_dir, video_uuid,
        ))
        try:
            result_dir = await _shield_await(rename_task)
        except BaseException:
            raise
        assert isinstance(result_dir, Path)
        # Attempt dir is now the result dir: do not rmtree it below.
        attempt_claimed = True

        def _final(role: str, meta: OutputMeta | None) -> OutputMeta | None:
            if meta is None:
                return None
            name = "hq.mp4" if role == "hq" else ("light.mp4" if role == "light" else "poster.jpg")
            return OutputMeta(role=meta.role, path=result_dir / name, sha256=meta.sha256,
                              size_bytes=meta.size_bytes, width=meta.width, height=meta.height)

        keys = {
            role: build_derivative_media_key(video_uuid, role, actual_sha, version)
            for role in (["hq", "light", "poster"] if plan.hq_applicable else ["light", "poster"])
        }

        hq_meta = _final("hq", hq_meta_tmp) if plan.hq_applicable else None
        light_meta = _final("light", light_meta_tmp)
        poster_meta = _final("poster", poster_meta_tmp)
        assert light_meta is not None and poster_meta is not None
        result = PackageResult(
            video_uuid=video_uuid, source_sha256=actual_sha, transform_version=version,
            source_w=info.display_w, source_h=info.display_h, source_frames=source_frames,
            nominal_fps=info.nominal_fps, avg_fps=info.avg_fps, transfer_in=info.transfer,
            hq=hq_meta, hq_aliased_to=plan.hq_aliased_to,
            light=light_meta, poster=poster_meta, media_keys=keys,
            encode_seconds=round(elapsed, 2), validation=report, ready=True,
            result_dir=result_dir,
        )
        return result
    except BaseException as _exc:
        if process is not None and process.returncode is None:
            with contextlib.suppress(Exception):
                await _kill_and_reap(process)
        # Failure/cancel removes ONLY the owned attempt; if the atomic
        # rename already succeeded, remove ONLY the owned result dir —
        # never another build's dir, never pre-existing files, never the
        # source. If the result was never returned (cancel at the publish
        # boundary), this is the only cleanup; siblings are untouched.
        if attempt_claimed and isinstance(result_dir, Path):
            with contextlib.suppress(Exception):
                if result_dir.is_dir() and result_dir.name.startswith("pkg-"):
                    shutil.rmtree(result_dir, ignore_errors=True)
        else:
            _cleanup_attempt_dir(attempt_dir)
        raise
