"""Mac-agent background worker for cutting kept session-clip candidates.

Uses HTTP Range input-seeking (`ffmpeg -ss <start> -i <presigned_url> -t <dur>`)
so only the ~10-20 second slice is read from Backblaze B2 (never the full
3-8 GB session video).
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import shutil
from pathlib import Path
from typing import Any

from .config import Config
from .sync_client import SyncClient

logger = logging.getLogger(__name__)

CUT_HEARTBEAT_SECONDS = 45
CUT_TIMEOUT_SECONDS = 300
MIN_CLIP_SPAN_S = 0.5
MAX_CLIP_SPAN_S = 60.0
MAX_CLIP_UPLOAD_BYTES = 250 * 1024 * 1024  # Matches backend MAX_CUT_UPLOAD_BYTES
TARGET_MAX_CLIP_BYTES = 220 * 1024 * 1024  # ~88% ceiling leaves headroom for VBV & container muxing
FALLBACK_TARGET_CLIP_BYTES = 180 * 1024 * 1024
AUDIO_BITRATE_KBPS = 128
MAX_VIDEO_BITRATE_KBPS = 40_000
MIN_VIDEO_BITRATE_KBPS = 500
MAX_UPLOAD_RETRY_ATTEMPTS = 3
UPLOAD_RETRY_BACKOFF_S = 2.0
HDR_TRANSFERS = ("smpte2084", "arib-std-b67")
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def compute_max_video_kbps(duration_s: float, target_bytes: int = TARGET_MAX_CLIP_BYTES) -> int:
    """Compute a VBV video bitrate ceiling (kbps) so the encoded MP4 fits within target_bytes."""
    safe_dur = max(MIN_CLIP_SPAN_S, float(duration_s))
    total_kbps = int((target_bytes * 8) / (safe_dur * 1000.0))
    video_kbps = total_kbps - AUDIO_BITRATE_KBPS
    return max(MIN_VIDEO_BITRATE_KBPS, min(MAX_VIDEO_BITRATE_KBPS, video_kbps))


def sanitize_cut_error(message: str, source_url: str | None = None) -> str:
    """Strip presigned URLs and query credentials from logs and error reports."""
    text = str(message or "").strip()
    if source_url:
        text = text.replace(source_url, "<source-url>")
    text = _URL_RE.sub("<url>", text)
    text = " ".join(text.split())
    return (text or "Clip cut failed")[:240]


def _format_if_match_header(source_etag: str | None) -> str | None:
    if not source_etag:
        return None
    clean = str(source_etag).strip().strip('"').replace("\r", "").replace("\n", "")
    if not clean:
        return None
    return f'If-Match: "{clean}"\r\n'


def validate_cut_window(start_s: Any, end_s: Any) -> tuple[float, float]:
    """Validate finite clip bounds within [0.5s, 60s]."""
    try:
        start = float(start_s)
        end = float(end_s)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid clip bounds") from exc
    if not (math.isfinite(start) and math.isfinite(end)):
        raise ValueError("Non-finite clip bounds")
    if start < 0.0 or end <= start:
        raise ValueError("Clip end must be greater than start")
    span = end - start
    if span < MIN_CLIP_SPAN_S or span > MAX_CLIP_SPAN_S:
        raise ValueError(
            f"Clip span {span:.2f}s outside allowed range [{MIN_CLIP_SPAN_S}s, {MAX_CLIP_SPAN_S}s]"
        )
    return start, end


def build_cut_ffmpeg_command(
    *,
    ffmpeg_path: str,
    source_url: str,
    start_s: float,
    end_s: float,
    mp4_path: Path,
    color_transfer: str | None = None,
    source_etag: str | None = None,
    crf: int = 19,
    max_output_bytes: int = TARGET_MAX_CLIP_BYTES,
    max_width: int | None = None,
) -> list[str]:
    """Build the ffmpeg command for cutting a web-safe SDR MP4 bounded to fit MAX_CLIP_UPLOAD_BYTES."""
    start, end = validate_cut_window(start_s, end_s)
    duration = end - start
    is_hdr = (color_transfer or "").strip().lower() in HDR_TRANSFERS
    max_video_kbps = compute_max_video_kbps(duration, max_output_bytes)
    bufsize_kbps = max(2000, min(max_video_kbps * 2, 60_000))

    filters: list[str] = []
    color_args: list[str] = []
    if is_hdr:
        filters.extend(
            [
                "zscale=t=linear:npl=100",
                "format=gbrpf32le",
                "zscale=p=bt709",
                "tonemap=tonemap=hable:desat=0",
                "zscale=t=bt709:m=bt709:r=tv",
            ]
        )
        color_args = [
            "-color_range",
            "tv",
            "-colorspace",
            "bt709",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
        ]
    if max_width is not None and max_width > 0:
        filters.append(f"scale='min({int(max_width)},iw)':-2")
    filters.extend(["scale=trunc(iw/2)*2:trunc(ih/2)*2", "format=yuv420p"])

    header_args: list[str] = []
    if_match_hdr = _format_if_match_header(source_etag)
    if if_match_hdr:
        header_args = ["-headers", if_match_hdr]

    # Input-seek (-ss before -i) lets ffmpeg use HTTP Range reads over B2.
    # Strip all container metadata and chapters so GPS coordinates never survive.
    return [
        ffmpeg_path,
        "-y",
        "-nostdin",
        "-v",
        "error",
        *header_args,
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        source_url,
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-vf",
        ",".join(filters),
        "-c:v",
        "libx264",
        "-profile:v",
        "main",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "veryfast",
        "-crf",
        str(int(crf)),
        "-maxrate",
        f"{max_video_kbps}k",
        "-bufsize",
        f"{bufsize_kbps}k",
        "-c:a",
        "aac",
        "-b:a",
        f"{AUDIO_BITRATE_KBPS}k",
        "-movflags",
        "+faststart",
        *color_args,
        str(mp4_path),
    ]


async def _terminate_proc(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    try:
        proc.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            return
        await proc.wait()


async def _probe_color_transfer_async(
    ffprobe_path: str,
    source_url: str,
    source_etag: str | None = None,
) -> str | None:
    """Fallback probe when server job omits color_transfer metadata."""
    header_args: list[str] = []
    if_match_hdr = _format_if_match_header(source_etag)
    if if_match_hdr:
        header_args = ["-headers", if_match_hdr]
    proc = await asyncio.create_subprocess_exec(
        ffprobe_path,
        "-v",
        "error",
        *header_args,
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=color_transfer",
        "-of",
        "json",
        source_url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=20.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        await _terminate_proc(proc)
        raise
    if proc.returncode != 0:
        return None
    try:
        data = json.loads((stdout or b"{}").decode("utf-8", errors="replace"))
        streams = data.get("streams") or []
        val = streams[0].get("color_transfer") if streams else None
        return str(val).strip().lower() if val else None
    except Exception:
        return None


class _CutError(RuntimeError):
    """Error produced by local ffmpeg/ffprobe execution (distinct from server API errors)."""


async def _run_ffmpeg_to_path(cmd: list[str], out_path: Path, source_url: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=CUT_TIMEOUT_SECONDS)
    except asyncio.TimeoutError as exc:
        await _terminate_proc(proc)
        raise _CutError(f"Clip cut timed out after {CUT_TIMEOUT_SECONDS}s") from exc
    except asyncio.CancelledError:
        await _terminate_proc(proc)
        raise

    if proc.returncode != 0 or not out_path.is_file() or out_path.stat().st_size == 0:
        raw_err = (stderr or b"").decode("utf-8", errors="replace").strip()
        err = sanitize_cut_error(raw_err or f"ffmpeg exit {proc.returncode}", source_url)
        raise _CutError(f"Clip cut failed: {err}")


async def _cut_clip_async(
    *,
    ffmpeg_path: str,
    ffprobe_path: str,
    source_url: str,
    start_s: float,
    end_s: float,
    out_dir: Path,
    color_transfer: str | None = None,
    source_etag: str | None = None,
) -> Path:
    """Cut `[start_s, end_s]` from a presigned HTTP Range URL into a <=250 MiB H.264 SDR MP4."""
    start, end = validate_cut_window(start_s, end_s)
    duration = end - start
    transfer = color_transfer
    if not transfer:
        try:
            transfer = await _probe_color_transfer_async(ffprobe_path, source_url, source_etag)
        except asyncio.CancelledError:
            raise
        except Exception:
            transfer = None

    mp4_path = out_dir / "clip.mp4"
    cmd = build_cut_ffmpeg_command(
        ffmpeg_path=ffmpeg_path,
        source_url=source_url,
        start_s=start,
        end_s=end,
        mp4_path=mp4_path,
        color_transfer=transfer,
        source_etag=source_etag,
    )
    await _run_ffmpeg_to_path(cmd, mp4_path, source_url)

    size_bytes = mp4_path.stat().st_size
    if size_bytes > MAX_CLIP_UPLOAD_BYTES:
        # Rare VBV overshoot on complex 4K clips: re-encode locally from the already-cut SDR clip
        # at a stricter bitrate/1080p cap so it fits safely under MAX_CLIP_UPLOAD_BYTES.
        logger.warning(
            "Cut clip size %s bytes exceeds %s byte upload limit; running bounded 1080p fit pass",
            size_bytes,
            MAX_CLIP_UPLOAD_BYTES,
        )
        fitted_path = out_dir / "clip-fitted.mp4"
        fit_cmd = build_cut_ffmpeg_command(
            ffmpeg_path=ffmpeg_path,
            source_url=str(mp4_path),
            start_s=0.0,
            end_s=duration,
            mp4_path=fitted_path,
            color_transfer="bt709",
            source_etag=None,
            crf=24,
            max_output_bytes=FALLBACK_TARGET_CLIP_BYTES,
            max_width=1920,
        )
        await _run_ffmpeg_to_path(fit_cmd, fitted_path, source_url)
        fitted_path.replace(mp4_path)
        size_bytes = mp4_path.stat().st_size
        if size_bytes > MAX_CLIP_UPLOAD_BYTES:
            raise _CutError(
                f"Cut clip size ({size_bytes} bytes) exceeds {MAX_CLIP_UPLOAD_BYTES} byte upload limit"
            )

    return mp4_path


def _http_status_code(exc: Exception) -> int | None:
    """Extract structured HTTP status code from SyncHTTPError (never from response body text)."""
    if isinstance(exc, _CutError):
        return None
    code = getattr(exc, "status_code", None)
    return code if isinstance(code, int) else None


def _is_server_lease_dead(exc: Exception) -> bool:
    """Classify server 404/409 lease loss strictly from structured status_code."""
    return _http_status_code(exc) in (404, 409)


def _is_transient_upload_busy(exc: Exception) -> bool:
    """Classify transient server backpressure strictly from structured status_code."""
    return _http_status_code(exc) in (429, 502, 503, 504, 507)


MAX_CONSECUTIVE_HB_FAILURES = 3


async def _heartbeat_loop(
    sync_client: SyncClient,
    *,
    candidate_id: int,
    agent_id: str,
    lease_token: str,
    cut_revision: int,
    stop: asyncio.Event,
    lease_lost: asyncio.Event,
) -> None:
    consecutive_failures = 0
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=CUT_HEARTBEAT_SECONDS)
            return
        except asyncio.TimeoutError:
            pass
        try:
            await sync_client.heartbeat_clip_cut(
                candidate_id, agent_id, lease_token, cut_revision
            )
            consecutive_failures = 0
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "Clip cut %s heartbeat failed: %s",
                candidate_id,
                sanitize_cut_error(str(exc)),
            )
            if _is_server_lease_dead(exc):
                lease_lost.set()
                return
            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_HB_FAILURES:
                return


async def _upload_with_backoff(
    sync_client: SyncClient,
    *,
    candidate_id: int,
    agent_id: str,
    lease_token: str,
    cut_revision: int,
    mp4_path: Path,
    lease_lost: asyncio.Event,
) -> dict[str, Any]:
    """Retry bounded transient server backpressure (429/507/502/503) without burning cut attempts."""
    for attempt in range(MAX_UPLOAD_RETRY_ATTEMPTS):
        if lease_lost.is_set():
            raise RuntimeError("clip cut lease lost before upload")
        try:
            return await sync_client.complete_clip_cut(
                candidate_id=candidate_id,
                agent_id=agent_id,
                lease_token=lease_token,
                cut_revision=cut_revision,
                mp4_path=str(mp4_path),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if _is_transient_upload_busy(exc) and attempt < MAX_UPLOAD_RETRY_ATTEMPTS - 1:
                await asyncio.sleep(UPLOAD_RETRY_BACKOFF_S * (attempt + 1))
                continue
            raise
    raise RuntimeError("clip cut upload exhausted retries")


async def process_clip_cut_once(
    config: Config,
    sync_client: SyncClient,
    agent_id: str,
) -> int:
    """Lease and process at most one kept session-clip cut job."""
    jobs = await sync_client.lease_clip_cuts(agent_id, limit=1)
    if not jobs:
        return 0

    processed = 0
    for job in jobs:
        candidate_id = int(job["candidate_id"])
        lease_token = str(job["lease_token"])
        cut_revision = int(job["cut_revision"])
        source_url = job.get("source_url")
        source_etag = job.get("source_etag")
        if not source_url:
            await sync_client.fail_clip_cut(
                candidate_id,
                agent_id,
                lease_token,
                cut_revision,
                "Missing presigned source_url from server",
            )
            continue

        try:
            start_s, end_s = validate_cut_window(job.get("start_s"), job.get("end_s"))
        except ValueError as exc:
            await sync_client.fail_clip_cut(
                candidate_id,
                agent_id,
                lease_token,
                cut_revision,
                sanitize_cut_error(str(exc), source_url),
            )
            continue

        out_dir = (
            Path(config.media.temp_dir).expanduser()
            / f"clip-cut-{candidate_id}-r{cut_revision}-{lease_token[:8]}"
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        stop_hb = asyncio.Event()
        lease_lost = asyncio.Event()
        hb_task = asyncio.create_task(
            _heartbeat_loop(
                sync_client,
                candidate_id=candidate_id,
                agent_id=agent_id,
                lease_token=lease_token,
                cut_revision=cut_revision,
                stop=stop_hb,
                lease_lost=lease_lost,
            )
        )
        try:
            await sync_client.heartbeat_clip_cut(
                candidate_id, agent_id, lease_token, cut_revision
            )
            mp4_path = await _cut_clip_async(
                ffmpeg_path=config.media.ffmpeg_path,
                ffprobe_path=config.media.ffprobe_path,
                source_url=source_url,
                start_s=start_s,
                end_s=end_s,
                out_dir=out_dir,
                color_transfer=job.get("color_transfer"),
                source_etag=source_etag,
            )
            if lease_lost.is_set():
                logger.warning("Clip cut %s lease lost mid-cut; abandoning upload", candidate_id)
                continue
            cut_size = mp4_path.stat().st_size
            if cut_size > MAX_CLIP_UPLOAD_BYTES:
                raise _CutError(
                    f"Cut clip size ({cut_size} bytes) exceeds {MAX_CLIP_UPLOAD_BYTES} byte upload limit"
                )
            result = await _upload_with_backoff(
                sync_client,
                candidate_id=candidate_id,
                agent_id=agent_id,
                lease_token=lease_token,
                cut_revision=cut_revision,
                mp4_path=mp4_path,
                lease_lost=lease_lost,
            )
            logger.info(
                "Clip cut %s complete (status=%s dive_id=%s)",
                candidate_id,
                result.get("extraction_status"),
                result.get("dive_id"),
            )
            processed += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            safe_err = sanitize_cut_error(str(exc), source_url)
            logger.warning("Clip cut %s failed: %s", candidate_id, safe_err)
            if not lease_lost.is_set() and not _is_server_lease_dead(exc):
                try:
                    await sync_client.fail_clip_cut(
                        candidate_id, agent_id, lease_token, cut_revision, safe_err
                    )
                except Exception:
                    pass
        finally:
            stop_hb.set()
            hb_task.cancel()
            try:
                await hb_task
            except asyncio.CancelledError:
                pass
            shutil.rmtree(out_dir, ignore_errors=True)
    return processed
