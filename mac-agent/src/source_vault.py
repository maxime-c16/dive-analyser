"""Validated recalled-source vault with mount and cleanup guardrails."""

import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Callable


UUID_RE = re.compile(r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$")
PERMANENT_RETENTION = {"permanent_representative", "pinned"}


class SourceVaultError(RuntimeError):
    pass


@dataclass(frozen=True)
class VaultSource:
    video_uuid: str
    path: Path
    source_kind: str
    size_bytes: int
    checksum_sha256: str
    volume_uuid: str
    retention_class: str
    validated_at: str


class MediaSourceVault:
    def __init__(
        self,
        root: str,
        expected_volume_uuid: str,
        ffprobe_path: str,
        *,
        enabled: bool = True,
        volume_uuid_resolver: Callable[[Path], str] | None = None,
        policy=None,
    ):
        self.root = Path(root).expanduser().resolve()
        self.expected_volume_uuid = expected_volume_uuid.upper()
        self.ffprobe_path = ffprobe_path
        self.enabled = enabled
        self._volume_uuid_resolver = volume_uuid_resolver or volume_uuid_for_path
        self.policy = policy

    def validate_mount(self) -> dict:
        if not self.enabled:
            return {"mounted": False, "status": "disabled"}
        if not self.root.exists() or not self.root.is_dir():
            raise SourceVaultError("source_vault_root_missing")
        if self.root.is_symlink():
            raise SourceVaultError("source_vault_root_symlink_rejected")
        actual_uuid = self._volume_uuid_resolver(self.root).upper()
        if not self.expected_volume_uuid or actual_uuid != self.expected_volume_uuid:
            raise SourceVaultError("source_vault_volume_uuid_mismatch")
        if not os.access(self.root, os.W_OK):
            raise SourceVaultError("source_vault_read_only")
        usage = shutil.disk_usage(self.root)
        return {
            "mounted": True,
            "status": "ok",
            "volume_uuid": actual_uuid,
            "free_bytes": usage.free,
            "total_bytes": usage.total,
            "free_percent": (usage.free / usage.total * 100) if usage.total else 0,
        }

    def resolve(self, video_uuid: str) -> VaultSource | None:
        if not self.enabled:
            return None
        validate_uuid(video_uuid)
        mount = self.validate_mount()
        uuid_dir = self._safe_uuid_dir(video_uuid)
        sidecar = uuid_dir / "source.json"
        if not sidecar.is_file() or sidecar.is_symlink():
            return None
        data = json.loads(sidecar.read_text())
        source_path = (uuid_dir / data["filename"]).resolve()
        self._validate_path(source_path, uuid_dir)
        size, checksum = validate_video_source(source_path, self.ffprobe_path)
        if size != int(data["size_bytes"]) or checksum != data["sha256"]:
            raise SourceVaultError("source_vault_checksum_or_size_mismatch")
        if data.get("volume_uuid", "").upper() != mount["volume_uuid"]:
            raise SourceVaultError("source_vault_sidecar_volume_mismatch")
        return VaultSource(
            video_uuid=video_uuid.upper(),
            path=source_path,
            source_kind=data["source_kind"],
            size_bytes=size,
            checksum_sha256=checksum,
            volume_uuid=mount["volume_uuid"],
            retention_class=data["retention_class"],
            validated_at=data["validated_at"],
        )

    def import_source(
        self,
        video_uuid: str,
        source: Path,
        *,
        source_kind: str,
        retention_class: str,
        canonical_video_uuid: str | None = None,
        agent_local_uuid: str | None = None,
        dive_id: int | None = None,
        pinned: bool = False,
    ) -> VaultSource:
        validate_uuid(video_uuid)
        mount = self.validate_mount()
        source = source.expanduser()
        if source.is_symlink() or not source.is_file():
            raise SourceVaultError("source_file_invalid")
        source = source.resolve()
        size, checksum = validate_video_source(source, self.ffprobe_path)
        if self.policy and size > self.policy.max_source_bytes:
            raise SourceVaultError("source_exceeds_automatic_size_limit")
        if self.policy:
            gate = self.storage_status(additional_bytes=size)
            if gate["internal"]["processing_stopped"] or gate["managed_sources"]["quota_exceeded"]:
                raise SourceVaultError("source_vault_storage_gate_closed")
        uuid_dir = self._safe_uuid_dir(video_uuid)
        uuid_dir.mkdir(parents=True, exist_ok=True)
        destination = (uuid_dir / f"source{source.suffix.lower() or '.mov'}").resolve()
        self._validate_path(destination, uuid_dir, must_exist=False)
        temporary = destination.with_suffix(destination.suffix + ".partial")
        shutil.copy2(source, temporary)
        if sha256_file(temporary) != checksum:
            temporary.unlink(missing_ok=True)
            raise SourceVaultError("source_copy_checksum_mismatch")
        temporary.replace(destination)
        validated_at = datetime.now(timezone.utc).isoformat()
        metadata = {
            "video_uuid": video_uuid.upper(),
            "canonical_video_uuid": (canonical_video_uuid or video_uuid).upper(),
            "agent_local_uuid": (agent_local_uuid or video_uuid).upper(),
            "dive_id": dive_id,
            "filename": destination.name,
            "source_kind": source_kind,
            "size_bytes": size,
            "sha256": checksum,
            "volume_uuid": mount["volume_uuid"],
            "retention_class": retention_class,
            "validated_at": validated_at,
            "created_at": validated_at,
            "last_accessed_at": validated_at,
            "poster_ready": False,
            "proxy_ready": False,
            "durable_outputs_verified": False,
            "pinned": pinned,
            "active_job": False,
        }
        if retention_class == "recent" and self.policy:
            metadata["expires_at"] = (datetime.now(timezone.utc) + timedelta(days=self.policy.recent_retention_days)).isoformat()
        sidecar_tmp = uuid_dir / "source.json.partial"
        sidecar_tmp.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
        sidecar_tmp.replace(uuid_dir / "source.json")
        return VaultSource(video_uuid.upper(), destination, source_kind, size, checksum, mount["volume_uuid"], retention_class, validated_at)

    def storage_status(self, *, additional_bytes: int = 0) -> dict:
        mount = self.validate_mount()
        usage = {key: 0 for key in ("permanent", "recent", "temporary", "diagnostic", "quarantine")}
        total = 0
        for uuid_dir in self.root.iterdir():
            sidecar = uuid_dir / "source.json"
            if uuid_dir.is_symlink() or not sidecar.is_file() or sidecar.is_symlink():
                continue
            try:
                data = json.loads(sidecar.read_text())
                size = int(data.get("size_bytes", 0))
                retention = data.get("retention_class", "temporary")
                bucket = "permanent" if retention in PERMANENT_RETENTION else "diagnostic" if retention == "failed_diagnostic" else retention
                if bucket in usage:
                    usage[bucket] += size
                total += size
            except (ValueError, OSError, json.JSONDecodeError):
                continue
        # Account for the complete managed working set, not only validated
        # sources. Export duplicates and failed diagnostics are often the peak
        # disk consumers while a recall is in progress.
        managed_root = self.root.parent.parent
        for relative, bucket in (
            ("incoming", "temporary"),
            ("media_tmp", "temporary"),
            ("failed_diagnostics", "diagnostic"),
            ("quarantine", "quarantine"),
        ):
            directory = (managed_root / relative).resolve()
            if _is_relative_to(directory, managed_root) and directory.is_dir() and not directory.is_symlink():
                tree_bytes = _safe_tree_size(directory)
                usage[bucket] += tree_bytes
                total += tree_bytes
        free = mount["free_bytes"]
        policy = self.policy
        quota = policy.managed_quota_bytes if policy else 20 * 1024**3
        warning = policy.internal_warning_free_bytes if policy else 35 * 1024**3
        historical = policy.internal_pause_free_bytes if policy else 30 * 1024**3
        automatic = policy.internal_auto_pause_free_bytes if policy else 24 * 1024**3
        stop = policy.internal_stop_free_bytes if policy else 18 * 1024**3
        projected_free = free - additional_bytes
        return {
            "internal": {"free_bytes": free, "projected_free_bytes": projected_free,
                "warning": projected_free < warning, "historical_recall_paused": projected_free < historical,
                "automatic_recall_paused": projected_free < automatic, "processing_stopped": projected_free < stop},
            "managed_sources": {"total_bytes": total, "projected_total_bytes": total + additional_bytes,
                "quota_bytes": quota, "quota_exceeded": total + additional_bytes > quota,
                "permanent_bytes": usage["permanent"], "recent_bytes": usage["recent"],
                "temporary_bytes": usage["temporary"], "diagnostic_bytes": usage["diagnostic"],
                "quarantine_bytes": usage["quarantine"]},
        }

    def mark_media_ready(self, video_uuid: str, rendition: str) -> None:
        """Record durable Debian output completion and start temporary grace."""
        validate_uuid(video_uuid)
        uuid_dir = self._safe_uuid_dir(video_uuid)
        sidecar = uuid_dir / "source.json"
        if not sidecar.is_file() or sidecar.is_symlink():
            return
        data = json.loads(sidecar.read_text())
        if rendition == "poster":
            data["poster_ready"] = True
        elif rendition == "proxy_360p":
            data["proxy_ready"] = True
        data["last_accessed_at"] = datetime.now(timezone.utc).isoformat()
        if data.get("poster_ready") and data.get("proxy_ready"):
            data["durable_outputs_verified"] = True
            if data.get("retention_class") == "temporary":
                grace_hours = self.policy.temporary_grace_hours if self.policy else 24
                data["expires_at"] = (datetime.now(timezone.utc) + timedelta(hours=grace_hours)).isoformat()
        temporary = sidecar.with_suffix(".json.partial")
        temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        temporary.replace(sidecar)

    @staticmethod
    def estimate_peak_bytes(source_bytes: int | None) -> int:
        return int((source_bytes or 500_000_000) * 2.5)

    def cleanup(self, *, dry_run: bool = True, now: datetime | None = None,
                max_items: int | None = None, max_bytes: int | None = None) -> dict:
        """Remove only eligible sources in deterministic bounded order."""
        before = self.storage_status()
        now = now or datetime.now(timezone.utc)
        max_items = max_items or (self.policy.cleanup_max_items if self.policy else 20)
        max_bytes = max_bytes or (self.policy.cleanup_max_bytes if self.policy else 5 * 1024**3)
        candidates = []
        rank = {"quarantine": 0, "failed_diagnostic": 1, "temporary": 2, "recent": 3}
        for uuid_dir in self.root.iterdir():
            if uuid_dir.is_symlink() or not uuid_dir.is_dir() or not UUID_RE.fullmatch(uuid_dir.name):
                continue
            sidecar = uuid_dir / "source.json"
            if not sidecar.is_file() or sidecar.is_symlink():
                continue
            data = json.loads(sidecar.read_text())
            if data.get("retention_class") in PERMANENT_RETENTION or data.get("pinned") or data.get("active_job"):
                continue
            if not data.get("durable_outputs_verified", False):
                continue
            expires_at = data.get("expires_at")
            if not expires_at or datetime.fromisoformat(expires_at) > now:
                continue
            source = (uuid_dir / data["filename"]).resolve()
            self._validate_path(source, uuid_dir)
            candidates.append((rank.get(data.get("retention_class"), 9), expires_at, uuid_dir, source, data))
        removed, removed_bytes = [], 0
        for _, _, uuid_dir, source, data in sorted(candidates):
            size = source.stat().st_size
            if len(removed) >= max_items or removed_bytes + size > max_bytes:
                break
            removed.append({"path": str(source), "video_uuid": data.get("video_uuid"),
                "retention_class": data.get("retention_class"), "size_bytes": size, "reason": "retention_expired"})
            removed_bytes += size
            if not dry_run:
                source.unlink()
                (uuid_dir / "source.json").unlink()
                uuid_dir.rmdir()
        after_free = before["internal"]["free_bytes"] if dry_run else self.storage_status()["internal"]["free_bytes"]
        return {"dry_run": dry_run, "removed": removed, "removed_paths": [item["path"] for item in removed],
            "removed_bytes": removed_bytes, "free_bytes_before": before["internal"]["free_bytes"],
            "free_bytes_after": after_free, "max_items": max_items, "max_bytes": max_bytes}

    def _safe_uuid_dir(self, video_uuid: str) -> Path:
        path = (self.root / video_uuid.upper()).resolve()
        if not _is_relative_to(path, self.root):
            raise SourceVaultError("source_vault_path_escape")
        return path

    def _validate_path(self, path: Path, uuid_dir: Path, *, must_exist: bool = True) -> None:
        if not _is_relative_to(path, uuid_dir) or not _is_relative_to(path, self.root):
            raise SourceVaultError("source_vault_path_escape")
        if path.is_symlink():
            raise SourceVaultError("source_vault_symlink_rejected")
        if must_exist and not path.is_file():
            raise SourceVaultError("source_vault_file_missing")


def validate_uuid(video_uuid: str) -> None:
    if not UUID_RE.fullmatch(video_uuid or ""):
        raise SourceVaultError("invalid_video_uuid")


def validate_video_source(path: Path, ffprobe_path: str) -> tuple[int, str]:
    if not path.is_file() or path.is_symlink():
        raise SourceVaultError("source_file_invalid")
    size = path.stat().st_size
    if size < 1024:
        raise SourceVaultError("source_file_placeholder")
    result = subprocess.run(
        [ffprobe_path, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_type,duration", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise SourceVaultError("source_no_valid_video_stream")
    payload = json.loads(result.stdout or "{}")
    if not payload.get("streams"):
        raise SourceVaultError("source_no_valid_video_stream")
    return size, sha256_file(path)


def volume_uuid_for_path(path: Path) -> str:
    # `diskutil info <nested-directory>` is inconsistent across macOS releases.
    # Resolve the mounted device first, then ask diskutil for that device's UUID.
    mounted = subprocess.run(
        ["/bin/df", "-P", str(path)],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    lines = [line for line in mounted.stdout.splitlines() if line.strip()]
    if len(lines) < 2:
        raise SourceVaultError("source_vault_device_unavailable")
    device = lines[-1].split()[0]
    result = subprocess.run(
        ["/usr/sbin/diskutil", "info", "-plist", device],
        capture_output=True,
        timeout=10,
        check=True,
    )
    payload = plistlib.loads(result.stdout)
    value = payload.get("VolumeUUID")
    if not value:
        raise SourceVaultError("source_vault_volume_uuid_unavailable")
    return str(value)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _safe_tree_size(root: Path) -> int:
    """Count regular files without following symlinks."""
    total = 0
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(directory)
        dirnames[:] = [name for name in dirnames if not (base / name).is_symlink()]
        for name in filenames:
            path = base / name
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
    return total
