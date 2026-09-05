"""Bounded single-asset Photos materialization via osxphotos."""

import asyncio
import logging
import re
import shutil
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

VIDEO_EXTENSIONS = {".mov", ".mp4", ".m4v", ".avi", ".hevc"}
MIN_VIDEO_BYTES = 16 * 1024
DEFAULT_EXPORT_TIMEOUT_SECONDS = 600


class MaterializationError(RuntimeError):
    """A single Photos asset could not be materialized safely."""

    def __init__(self, code: str, detail: str | None = None, retryable: bool | None = None):
        self.code = code
        self.detail = detail
        if retryable is None:
            retryable = code in {
                "permission_required",
                "photos_access_denied",
                "osxphotos_export_timeout",
                "osxphotos_export_failed",
            }
        self.retryable = retryable
        super().__init__(self.encoded)

    @property
    def encoded(self) -> str:
        if self.detail:
            return f"{self.code}: {self.detail}"
        return self.code


class MediaMaterializer:
    """Materialize exactly one Photos movie asset into a controlled directory."""

    def __init__(
        self,
        materialization_dir: str,
        max_bytes: int = 2_000_000_000,
        osxphotos_path: str | None = None,
        export_timeout_seconds: int = DEFAULT_EXPORT_TIMEOUT_SECONDS,
        use_photokit: bool = False,
    ):
        self.root = Path(materialization_dir).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        self.osxphotos_path = osxphotos_path or _find_osxphotos()
        self.export_timeout_seconds = export_timeout_seconds
        self.use_photokit = use_photokit

    async def materialize(self, video_uuid: str) -> Path:
        """Export exactly one movie UUID and return the local video file path."""
        _validate_uuid(video_uuid)
        target_dir = (self.root / video_uuid).resolve()
        if not _is_relative_to(target_dir, self.root):
            raise MaterializationError("materialization_target_outside_root")
        target_dir.mkdir(parents=True, exist_ok=True)

        cmd = self._build_command(target_dir, video_uuid)
        _validate_command(cmd, video_uuid, target_dir)
        logger.info("Materializing single Photos asset with command: %s", _redact_command(cmd))

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.export_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=10)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
            raise MaterializationError(
                "osxphotos_export_timeout",
                f"single-asset export exceeded {self.export_timeout_seconds}s",
                retryable=True,
            ) from exc
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace")[-1000:] or stdout.decode("utf-8", errors="replace")[-1000:]
            code = classify_osxphotos_failure(detail)
            raise MaterializationError(code, detail, retryable=code != "materialization_only_placeholders")

        path = self._find_materialized_video(target_dir)
        logger.info("Materialized Photos asset %s to %s", video_uuid, path)
        return path

    def _build_command(self, target_dir: Path, video_uuid: str) -> list[str]:
        command = [
            self.osxphotos_path,
            "export",
            str(target_dir),
            "--uuid",
            video_uuid,
            "--only-movies",
            "--download-missing",
            "--update",
            "--verbose",
        ]
        if self.use_photokit:
            command.append("--use-photokit")
        return command

    def _find_materialized_video(self, target_dir: Path) -> Path:
        candidates = []
        for path in target_dir.rglob("*"):
            resolved = path.resolve()
            if not _is_relative_to(resolved, self.root):
                raise MaterializationError("materialized_path_outside_root", retryable=False)
            if not path.is_file():
                continue
            if path.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            size = path.stat().st_size
            if size <= 0:
                logger.warning("Ignoring empty materialized candidate: %s", resolved)
                continue
            if size < MIN_VIDEO_BYTES:
                logger.warning("Ignoring tiny materialized candidate %s (%s bytes)", resolved, size)
                continue
            if size > self.max_bytes:
                logger.warning("Ignoring oversized materialized candidate %s (%s bytes)", resolved, size)
                continue
            candidates.append((size, resolved))

        if not candidates:
            raise MaterializationError("materialization_only_placeholders", retryable=False)

        candidates.sort(reverse=True)
        return candidates[0][1]

    def cleanup_failed_residue(
        self,
        *,
        ttl_hours: int = 24,
        active_uuids: set[str] | None = None,
        retain_failed: bool = True,
    ) -> dict[str, int]:
        """Remove expired diagnostic residue under the materialization root.

        Recent failed exports are useful for diagnosis, so cleanup is TTL-gated
        and never follows symlinks or leaves the configured root.
        """
        if retain_failed:
            return {"removed_dirs": 0, "removed_bytes": 0}
        active_uuids = active_uuids or set()
        cutoff = time.time() - (ttl_hours * 3600)
        removed_dirs = 0
        removed_bytes = 0
        for child in self.root.iterdir():
            resolved = child.resolve()
            if child.name in active_uuids:
                continue
            if not _is_relative_to(resolved, self.root):
                logger.warning("Skipping materialization cleanup outside root: %s", resolved)
                continue
            if child.is_symlink() or not child.is_dir():
                continue
            newest = max((path.stat().st_mtime for path in child.rglob("*") if not path.is_symlink()), default=child.stat().st_mtime)
            if newest > cutoff:
                continue
            size = sum(path.stat().st_size for path in child.rglob("*") if path.is_file() and not path.is_symlink())
            shutil.rmtree(resolved)
            removed_dirs += 1
            removed_bytes += size
            logger.info("Removed expired materialization residue: %s (%s bytes)", resolved, size)
        return {"removed_dirs": removed_dirs, "removed_bytes": removed_bytes}


def _find_osxphotos() -> str:
    found = shutil.which("osxphotos")
    if found:
        return found

    venv_cli = Path(sys.executable).resolve().parent / "osxphotos"
    if venv_cli.exists():
        return str(venv_cli)

    agent_venv_cli = Path("~/.diveanalyzer/venv/bin/osxphotos").expanduser()
    if agent_venv_cli.exists():
        return str(agent_venv_cli)

    return "osxphotos"


def _validate_uuid(video_uuid: str) -> None:
    if not video_uuid:
        raise MaterializationError("empty_uuid", retryable=False)
    if not UUID_RE.fullmatch(video_uuid):
        raise MaterializationError("invalid_uuid", retryable=False)


def _validate_command(cmd: list[str], video_uuid: str, target_dir: Path) -> None:
    if not isinstance(cmd, list):
        raise MaterializationError("materialization_command_must_be_argv", retryable=False)
    if cmd.count("--uuid") != 1:
        raise MaterializationError("materialization_requires_exactly_one_uuid", retryable=False)
    if cmd[cmd.index("--uuid") + 1] != video_uuid:
        raise MaterializationError("materialization_uuid_mismatch", retryable=False)
    if "--only-movies" not in cmd:
        raise MaterializationError("materialization_requires_only_movies", retryable=False)
    forbidden = {"--album", "--folder", "--keyword", "--person", "--query", "--regex", "--selected"}
    if any(item in forbidden for item in cmd):
        raise MaterializationError("materialization_command_contains_broad_selector", retryable=False)
    if Path(cmd[2]).resolve() != target_dir:
        raise MaterializationError("materialization_target_mismatch", retryable=False)


def _redact_command(cmd: list[str]) -> str:
    return " ".join(cmd)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def classify_osxphotos_failure(detail: str) -> str:
    """Map osxphotos output to retry-aware operational categories."""
    lowered = (detail or "").lower()
    permission_markers = (
        "not authorized",
        "not authorised",
        "authorization",
        "authorisation",
        "tcc",
        "privacy",
        "permission",
        "operation not permitted",
        "automation",
        "photos access",
    )
    denied_markers = (
        "access denied",
        "denied",
        "not allowed",
    )
    timeout_markers = (
        "timed out",
        "timeout",
    )
    if any(marker in lowered for marker in permission_markers):
        return "permission_required"
    if any(marker in lowered for marker in denied_markers):
        return "photos_access_denied"
    if any(marker in lowered for marker in timeout_markers):
        return "osxphotos_export_timeout"
    return "osxphotos_export_failed"
