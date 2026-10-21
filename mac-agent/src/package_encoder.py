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
- Timeouts/cancel (D2 semantics): kill + reap the ffmpeg process, remove ALL
  new package outputs, never touch the source. A partial output set is never
  reported ready.
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
import re
import subprocess
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
    duration_s: float | None
    audio_index: int | None


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
    """Lower-cased set of decoder codec names, or empty set if unprovable."""
    try:
        out = subprocess.check_output(
            [ffmpeg_path, "-hide_banner", "-decoders"],
            stderr=subprocess.DEVNULL,
            timeout=30,
        ).decode(errors="replace")
    except Exception:
        return set()
    names: set[str] = set()
    for line in out.splitlines():
        parts = line.split()
        # Lines look like: " A....D apac  Marian's A-pac audio"
        if len(parts) >= 2 and len(parts[0]) == 6 and parts[0][0] in "VASD.":
            names.add(parts[1].lower())
    return names


def select_decodable_audio_index(
    streams: list[dict],
    available_decoders: set[str] | None = None,
) -> int | None:
    """First audio stream with a usable decoder, else None (video-only).

    Skips tracks with no name, ``none``, or a denylisted codec (``apac``).
    When ``available_decoders`` (lower-cased ffmpeg ``-decoders`` names) is
    supplied, a named codec with no local decoder is also skipped. Without
    that map we only apply the denylist and never claim an allowlist
    guarantees decoding — callers that need certainty should pass
    ``ffmpeg_decoder_names(ffmpeg)``.
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
        dw, dh = (h, w) if rotation in (90, 270) else (w, h)  # ffmpeg autorotates
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


@dataclass
class PackagePlan:
    display_w: int
    display_h: int
    is_hdr: bool
    gop: int
    hq_applicable: bool
    hq_dims: tuple[int, int] | None
    hq_aliased_to: str | None  # "light" when HQ is honestly absent
    light_dims: tuple[int, int]
    poster_dims: tuple[int, int]
    poster_needs_select: bool  # duration >= 1s so a t>=1s frame exists
    audio_index: int | None


def plan_package(info: SourceInfo) -> PackagePlan:
    short = min(info.display_w, info.display_h)
    is_hdr = (info.transfer or "") in HDR_TRANSFERS
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
    needs_select = (info.duration_s or 0.0) >= 1.0
    return PackagePlan(
        display_w=info.display_w, display_h=info.display_h, is_hdr=is_hdr, gop=gop,
        hq_applicable=hq_applicable, hq_dims=hq_dims, hq_aliased_to=alias,
        light_dims=light_dims, poster_dims=poster_dims,
        poster_needs_select=needs_select, audio_index=info.audio_index,
    )


# ---------------------------------------------------------------------------
# Command construction (pure; no ffmpeg execution)
# ---------------------------------------------------------------------------

def _scale_branch(w: int, h: int) -> str:
    return f"scale={w}:{h}:flags=bicubic:out_range=tv,format=yuv420p,{SETPARAMS_BT709}"


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
    head = "[0:v]" + (",".join(TONEMAP_FILTERS + [f"split={n_splits}"]) if plan.is_hdr else f"split={n_splits}")
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
    if plan.poster_needs_select:
        graph_parts.append(f"{labels[idx]}select='gte(t\\,1)',{_scale_branch(pw, ph)}[po]")
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
    transfer_in: str | None
    hq: OutputMeta | None
    hq_aliased_to: str | None
    light: OutputMeta
    poster: OutputMeta
    media_keys: dict[str, str]
    encode_seconds: float
    validation: dict = field(default_factory=dict)
    ready: bool = False


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

    Raises ``TranscodeError`` (fail-closed) on any problem; on failure ALL
    new package outputs are removed and the source is never touched. A
    returned result with ``ready=True`` passed every ffprobe check.
    """
    if not isinstance(source_sha256, str) or not _SHA256_HEX_RE.fullmatch(source_sha256):
        raise ValueError(f"malformed source_sha256: {source_sha256!r}")
    version = transform_version if transform_version is not None else DERIVATIVE_TRANSFORM_VERSION_DEFAULT
    if not isinstance(version, str) or not version.strip() or len(version) > 40 or "|" in version:
        raise ValueError(f"invalid transform_version: {transform_version!r}")
    if threads_per_variant < 1:
        raise ValueError("threads_per_variant must be >= 1")
    probe_bin = ffprobe_path or _ffprobe_path(ffmpeg_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    info = await asyncio.to_thread(probe_source, source, probe_bin)
    # Re-resolve the audio choice against ACTUAL local decoder capability
    # (small scope): a named codec with no decoder is skipped. If the
    # decoder list is unprovable (empty), keep the probe-time denylist-only
    # choice rather than failing open or closed on audio.
    try:
        raw_streams = json.loads(subprocess.check_output(
            [probe_bin, "-v", "quiet", "-show_entries",
             "stream=index,codec_type,codec_name", "-of", "json", str(source)],
            timeout=30,
        ).decode()).get("streams", [])
        decoders = await asyncio.to_thread(ffmpeg_decoder_names, ffmpeg_path)
        if decoders:
            info = SourceInfo(**{**info.__dict__, "audio_index": select_decodable_audio_index(raw_streams, decoders)})
    except Exception:
        pass

    plan = plan_package(info)
    if plan.is_hdr and not await asyncio.to_thread(ffmpeg_has_filter, ffmpeg_path, "zscale"):
        raise TranscodeError(
            "package_encoder: HDR source requires zscale tone-map but this ffmpeg lacks zscale; "
            "refusing to emit SDR-relabeled HDR-black bytes (fail-closed)"
        )

    hq_out = out_dir / "hq.mp4" if plan.hq_applicable else None
    light_out = out_dir / "light.mp4"
    poster_out = out_dir / "poster.jpg"
    outputs = [p for p in (hq_out, light_out, poster_out) if p is not None]
    cmd = build_package_cmd(
        source, hq_out, light_out, poster_out, plan,
        ffmpeg_path=ffmpeg_path, threads_per_variant=threads_per_variant,
    )

    import time as _time

    started = _time.monotonic()
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        await _kill_and_reap(process)
        for p in outputs:
            p.unlink(missing_ok=True)
        raise TranscodeError(f"ffmpeg_timeout after {timeout_seconds}s package={' '.join(cmd)}") from None
    except asyncio.CancelledError:
        await _kill_and_reap(process)
        for p in outputs:
            p.unlink(missing_ok=True)
        raise
    elapsed = _time.monotonic() - started
    if process.returncode != 0:
        for p in outputs:
            p.unlink(missing_ok=True)
        detail = stderr.decode("utf-8", errors="replace")[-1000:] if stderr else ""
        raise TranscodeError(f"ffmpeg_failed package={' '.join(cmd)}\n{detail}")

    try:
        source_frames = await asyncio.to_thread(count_frames, source, probe_bin)
        report = await asyncio.to_thread(
            validate_package_outputs,
            hq_out=hq_out, light_out=light_out, poster_out=poster_out,
            plan=plan, source_frames=source_frames,
            source_duration_s=info.duration_s, ffprobe_path=probe_bin,
        )
    except Exception:
        for p in outputs:
            p.unlink(missing_ok=True)
        raise
    if not report.get("ready"):
        for p in outputs:
            p.unlink(missing_ok=True)
        raise TranscodeError(f"package validation failed: {report.get('checks')}")

    def meta(role: str, path: Path) -> OutputMeta:
        data = _ffprobe_streams(path, probe_bin)
        video = next(s for s in data["streams"] if s.get("codec_type") == "video")
        return OutputMeta(
            role=role, path=path, sha256=_sha256(path), size_bytes=path.stat().st_size,
            width=int(video["width"]), height=int(video["height"]),
        )

    try:
        hq_meta = meta("hq", hq_out) if (hq_out is not None and plan.hq_applicable) else None
        light_meta = meta("light", light_out)
        poster_meta = meta("poster", poster_out)
    except Exception as exc:
        for p in outputs:
            p.unlink(missing_ok=True)
        raise TranscodeError(f"package metadata failed: {exc}") from exc

    keys = {
        role: build_derivative_media_key(video_uuid, role, source_sha256, version)
        for role in (["hq", "light", "poster"] if plan.hq_applicable else ["light", "poster"])
    }
    return PackageResult(
        video_uuid=video_uuid, source_sha256=source_sha256, transform_version=version,
        source_w=info.display_w, source_h=info.display_h, source_frames=source_frames,
        nominal_fps=info.nominal_fps, transfer_in=info.transfer,
        hq=hq_meta, hq_aliased_to=plan.hq_aliased_to,
        light=light_meta, poster=poster_meta, media_keys=keys,
        encode_seconds=round(elapsed, 2), validation=report, ready=True,
    )
