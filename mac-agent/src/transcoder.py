"""ffmpeg-based rendition generation for media jobs."""

import asyncio
import contextlib
import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


# D2 publication integrity: no unbounded ffmpeg subprocess, ever. One
# transcode may legitimately take a long time (large 4K60 source on a
# loaded Mac), so the default bound is generous (45 min) and
# config-overridable — but it is always enforced: timeout kills the
# process, reaps it, removes the partial output, and fails the job with
# `ffmpeg_timeout`. Mirrors backend `media_transcoder_timeout_seconds`
# (same default; the D4 server fallback reuses that bound).
DEFAULT_TRANSCODE_TIMEOUT_SECONDS = 2700
# Upper bound for reaping a killed ffmpeg before giving up the wait (the
# SIGKILL is already issued; this only bounds teardown, never the encode).
REAP_TIMEOUT_SECONDS = 30


@dataclass
class RenditionArtifact:
    path: Path
    content_type: str
    checksum_sha256: str
    size_bytes: int
    is_temporary: bool = True

    def cleanup(self) -> None:
        """Remove generated artifact after successful upload/finalize."""
        if self.is_temporary:
            self.path.unlink(missing_ok=True)


class TranscodeError(RuntimeError):
    """ffmpeg rendition generation failed."""


class Transcoder:
    """Generate poster/proxy artifacts with ffmpeg."""

    def __init__(self, temp_dir: str, ffmpeg_path: str = "ffmpeg", timeout_seconds: int = DEFAULT_TRANSCODE_TIMEOUT_SECONDS):
        self.temp_dir = Path(temp_dir).expanduser()
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.ffmpeg_path = ffmpeg_path
        self.timeout_seconds = timeout_seconds

    async def build(self, source: Path, media_key: str, rendition: str) -> RenditionArtifact:
        """Generate the requested rendition."""
        streams = self._probe_streams(source) if rendition.startswith("proxy_") else []
        if rendition == "poster":
            output = self.temp_dir / f"{media_key}.jpg"
            cmd = [
                self.ffmpeg_path, "-y", "-ignore_unknown", "-threads", "2", "-i", str(source),
                "-map", "0:v:0", "-an", "-sn", "-dn", "-map_metadata", "-1",
                "-ss", "00:00:01", "-frames:v", "1",
                str(output),
            ]
            content_type = "image/jpeg"
        elif rendition == "proxy_360p":
            output = self.temp_dir / f"{media_key}.mp4"
            cmd = self._proxy_cmd(source, output, 360, 28, "96k", self._real_audio_stream_index(source, streams), self._video_transfer(streams))
            content_type = "video/mp4"
        elif rendition == "proxy_720p":
            output = self.temp_dir / f"{media_key}.mp4"
            cmd = self._proxy_cmd(source, output, 720, 25, "128k", self._real_audio_stream_index(source, streams), self._video_transfer(streams))
            content_type = "video/mp4"
        elif rendition == "original":
            return _artifact(source, "application/octet-stream", is_temporary=False)
        else:
            raise TranscodeError(f"Unsupported rendition: {rendition}")

        await self._run(cmd, output)
        return _artifact(output, content_type)

    def _proxy_cmd(
        self,
        source: Path,
        output: Path,
        max_height: int,
        crf: int,
        audio_bitrate: str,
        audio_stream_index: int | None = None,
        color_transfer: str | None = None,
    ) -> list[str]:
        filters = []
        if color_transfer in ("smpte2084", "arib-std-b67"):
            # HDR must be linearized and tone mapped before writing SDR tags.
            filters.extend([
                "zscale=t=linear:npl=100", "format=gbrpf32le",
                "zscale=p=bt709", "tonemap=tonemap=hable:desat=0",
                "zscale=t=bt709:m=bt709:r=tv",
            ])
        filters.append(f"scale=-2:{max_height}:out_range=tv,format=yuv420p")
        filters.append("setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709")
        cmd = [
            self.ffmpeg_path, "-y", "-ignore_unknown", "-threads", "2", "-i", str(source),
            "-map", "0:v:0",
        ]
        if audio_stream_index is None:
            cmd.extend(["-an"])
        else:
            cmd.extend(["-map", f"0:{audio_stream_index}"])
        cmd.extend([
            "-sn", "-dn", "-map_metadata", "-1", "-map_chapters", "-1",
            "-vf", ",".join(filters),
            "-filter_threads", "1", "-c:v", "libx264", "-threads", "2", "-preset", "veryfast", "-crf", str(crf),
            "-profile:v", "main", "-pix_fmt", "yuv420p",
            "-color_range", "tv", "-colorspace", "bt709",
            "-color_primaries", "bt709", "-color_trc", "bt709",
            "-tag:v", "avc1",
        ])
        if audio_stream_index is not None:
            cmd.extend(["-c:a", "aac", "-b:a", audio_bitrate])
        cmd.extend(["-movflags", "+faststart", str(output)])
        return cmd

    def _probe_streams(self, source: Path) -> list[dict]:
        ffprobe_path = str(Path(self.ffmpeg_path).with_name("ffprobe")) if "/" in self.ffmpeg_path else "ffprobe"
        try:
            result = subprocess.run(
                [
                    ffprobe_path,
                    "-v", "error",
                    "-show_entries", "stream=index,codec_type,codec_name,color_transfer",
                    "-of", "json",
                    str(source),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception:
            raise TranscodeError("Unable to probe source streams") from None

        try:
            streams = json.loads(result.stdout).get("streams", [])
            if not isinstance(streams, list) or not any(s.get("codec_type") == "video" for s in streams):
                raise ValueError("Missing video stream")
            return streams
        except (ValueError, TypeError, AttributeError):
            raise TranscodeError("Unable to read source video metadata") from None

    @staticmethod
    def _video_transfer(streams: list[dict]) -> str | None:
        return next((s.get("color_transfer") for s in streams if s.get("codec_type") == "video"), None)

    def _real_audio_stream_index(self, source: Path, streams: list[dict] | None = None) -> int | None:
        for stream in streams if streams is not None else self._probe_streams(source):
            if stream.get("codec_type") != "audio":
                continue
            codec_name = stream.get("codec_name")
            if not codec_name or codec_name == "none":
                continue
            index = stream.get("index")
            if isinstance(index, int):
                return index
        return None

    async def _run(self, cmd: list[str], output: Path) -> None:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout_seconds)
        except asyncio.TimeoutError:
            await _kill_and_reap(process)
            # The partial output of a timed-out encode is useless and must
            # not linger for a later attempt to mistake for a result. Only
            # the generated output is removed — the source is never touched.
            output.unlink(missing_ok=True)
            raise TranscodeError(
                f"ffmpeg_timeout after {self.timeout_seconds}s command={' '.join(cmd)}"
            ) from None
        except asyncio.CancelledError:
            await _kill_and_reap(process)
            output.unlink(missing_ok=True)
            raise
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace")[-1000:] or stdout.decode("utf-8", errors="replace")[-1000:]
            raise TranscodeError(f"ffmpeg_failed command={' '.join(cmd)}\n{detail}")


async def _kill_and_reap(process: "asyncio.subprocess.Process") -> None:
    """SIGKILL a runaway/cancelled ffmpeg and wait until it is reaped.

    The wait is shielded so repeated cancellation cannot strand a zombie,
    and bounded so teardown cannot hang forever (the kill is already
    issued; worst case init reaps the child).
    """
    try:
        process.kill()
    except ProcessLookupError:
        pass
    with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError):
        await asyncio.wait_for(asyncio.shield(process.wait()), timeout=REAP_TIMEOUT_SECONDS)


def _artifact(path: Path, content_type: str, is_temporary: bool = True) -> RenditionArtifact:
    return RenditionArtifact(
        path=path,
        content_type=content_type,
        checksum_sha256=_sha256(path),
        size_bytes=path.stat().st_size,
        is_temporary=is_temporary,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
