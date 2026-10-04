"""ffmpeg-based rendition generation for media jobs."""

import asyncio
import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


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

    def __init__(self, temp_dir: str, ffmpeg_path: str = "ffmpeg"):
        self.temp_dir = Path(temp_dir).expanduser()
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.ffmpeg_path = ffmpeg_path

    async def build(self, source: Path, media_key: str, rendition: str) -> RenditionArtifact:
        """Generate the requested rendition."""
        if rendition == "poster":
            output = self.temp_dir / f"{media_key}.jpg"
            cmd = [
                self.ffmpeg_path, "-y", "-ignore_unknown", "-i", str(source),
                "-map", "0:v:0", "-an", "-sn", "-dn", "-map_metadata", "-1",
                "-ss", "00:00:01", "-frames:v", "1",
                str(output),
            ]
            content_type = "image/jpeg"
        elif rendition == "proxy_360p":
            output = self.temp_dir / f"{media_key}.mp4"
            cmd = self._proxy_cmd(source, output, 360, 28, "96k", self._real_audio_stream_index(source))
            content_type = "video/mp4"
        elif rendition == "proxy_720p":
            output = self.temp_dir / f"{media_key}.mp4"
            cmd = self._proxy_cmd(source, output, 720, 25, "128k", self._real_audio_stream_index(source))
            content_type = "video/mp4"
        elif rendition == "original":
            return _artifact(source, "application/octet-stream", is_temporary=False)
        else:
            raise TranscodeError(f"Unsupported rendition: {rendition}")

        await self._run(cmd)
        return _artifact(output, content_type)

    def _proxy_cmd(
        self,
        source: Path,
        output: Path,
        max_height: int,
        crf: int,
        audio_bitrate: str,
        audio_stream_index: int | None = None,
    ) -> list[str]:
        cmd = [
            self.ffmpeg_path, "-y", "-ignore_unknown", "-i", str(source),
            "-map", "0:v:0",
        ]
        if audio_stream_index is None:
            cmd.extend(["-an"])
        else:
            cmd.extend(["-map", f"0:{audio_stream_index}"])
        cmd.extend([
            "-sn", "-dn", "-map_metadata", "-1", "-map_chapters", "-1",
            "-vf", f"scale=-2:{max_height}:out_range=tv,format=yuv420p",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
            "-profile:v", "main", "-pix_fmt", "yuv420p",
            "-color_range", "tv", "-colorspace", "bt709",
            "-color_primaries", "bt709", "-color_trc", "bt709",
            "-tag:v", "avc1",
        ])
        if audio_stream_index is not None:
            cmd.extend(["-c:a", "aac", "-b:a", audio_bitrate])
        cmd.extend(["-movflags", "+faststart", str(output)])
        return cmd

    def _real_audio_stream_index(self, source: Path) -> int | None:
        ffprobe_path = str(Path(self.ffmpeg_path).with_name("ffprobe")) if "/" in self.ffmpeg_path else "ffprobe"
        try:
            result = subprocess.run(
                [
                    ffprobe_path,
                    "-v", "error",
                    "-show_entries", "stream=index,codec_type,codec_name",
                    "-of", "json",
                    str(source),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except Exception:
            return None

        try:
            streams = json.loads(result.stdout).get("streams", [])
        except json.JSONDecodeError:
            return None

        for stream in streams:
            if stream.get("codec_type") != "audio":
                continue
            codec_name = stream.get("codec_name")
            if not codec_name or codec_name == "none":
                continue
            index = stream.get("index")
            if isinstance(index, int):
                return index
        return None

    async def _run(self, cmd: list[str]) -> None:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace")[-1000:] or stdout.decode("utf-8", errors="replace")[-1000:]
            raise TranscodeError(f"ffmpeg_failed command={' '.join(cmd)}\n{detail}")


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
