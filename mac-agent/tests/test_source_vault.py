from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.source_vault import MediaSourceVault, SourceVaultError


UUID = "2F8C11AA-D4CC-4E68-8A6A-8FFA28147836"


def _vault(tmp_path: Path, monkeypatch, actual_uuid="VOLUME-1"):
    root = tmp_path / "by_uuid"
    root.mkdir()
    monkeypatch.setattr("src.source_vault.validate_video_source", lambda path, ffprobe: (path.stat().st_size, "a" * 64))
    monkeypatch.setattr("src.source_vault.sha256_file", lambda path: "a" * 64)
    return MediaSourceVault(str(root), "VOLUME-1", "/usr/bin/false", volume_uuid_resolver=lambda path: actual_uuid)


def test_source_vault_rejects_wrong_volume(tmp_path, monkeypatch):
    vault = _vault(tmp_path, monkeypatch, actual_uuid="OTHER")
    with pytest.raises(SourceVaultError, match="source_vault_volume_uuid_mismatch"):
        vault.validate_mount()


def test_source_vault_import_and_resolve_precedes_photos(tmp_path, monkeypatch):
    vault = _vault(tmp_path, monkeypatch)
    source = tmp_path / "source.mov"
    source.write_bytes(b"v" * 2048)
    imported = vault.import_source(UUID, source, source_kind="manual_photos_export", retention_class="recent")
    resolved = vault.resolve(UUID)
    assert resolved is not None
    assert resolved.path == imported.path
    assert resolved.video_uuid == UUID
    assert resolved.retention_class == "recent"


def test_source_vault_rejects_symlink_source(tmp_path, monkeypatch):
    vault = _vault(tmp_path, monkeypatch)
    real = tmp_path / "real.mov"
    real.write_bytes(b"v" * 2048)
    link = tmp_path / "link.mov"
    link.symlink_to(real)
    with pytest.raises(SourceVaultError, match="source_file_invalid"):
        vault.import_source(UUID, link, source_kind="manual", retention_class="temporary")


def test_cleanup_is_dry_run_and_preserves_pinned(tmp_path, monkeypatch):
    vault = _vault(tmp_path, monkeypatch)
    source = tmp_path / "source.mov"
    source.write_bytes(b"v" * 2048)
    imported = vault.import_source(UUID, source, source_kind="manual", retention_class="temporary")
    sidecar = imported.path.parent / "source.json"
    data = __import__("json").loads(sidecar.read_text())
    data["expires_at"] = "2020-01-01T00:00:00+00:00"
    data["durable_outputs_verified"] = True
    sidecar.write_text(__import__("json").dumps(data))
    result = vault.cleanup(dry_run=True, now=datetime.now(timezone.utc))
    assert result["removed_bytes"] == 2048
    assert imported.path.exists()
    vault.cleanup(dry_run=False, now=datetime.now(timezone.utc))
    assert not imported.path.exists()


def test_storage_gates_quota_and_peak_estimate(tmp_path, monkeypatch):
    from types import SimpleNamespace
    vault = _vault(tmp_path, monkeypatch)
    vault.policy = SimpleNamespace(
        managed_quota_bytes=20 * 1024**3,
        internal_warning_free_bytes=35 * 1024**3,
        internal_pause_free_bytes=30 * 1024**3,
        internal_auto_pause_free_bytes=24 * 1024**3,
        internal_stop_free_bytes=18 * 1024**3,
        cleanup_max_items=20,
        cleanup_max_bytes=5 * 1024**3,
        max_source_bytes=1024**3,
        recent_retention_days=30,
    )
    monkeypatch.setattr("src.source_vault.shutil.disk_usage", lambda path: SimpleNamespace(free=40*1024**3,total=100*1024**3))
    status = vault.storage_status(additional_bytes=11 * 1024**3)
    assert status["internal"]["historical_recall_paused"] is True
    assert status["internal"]["processing_stopped"] is False
    assert MediaSourceVault.estimate_peak_bytes(None) == 1_250_000_000


def test_cleanup_bounds_and_protects_unverified_and_pinned(tmp_path, monkeypatch):
    vault = _vault(tmp_path, monkeypatch)
    source = tmp_path / "source.mov"
    source.write_bytes(b"v" * 2048)
    imported = vault.import_source(UUID, source, source_kind="manual", retention_class="temporary")
    sidecar = imported.path.parent / "source.json"
    data = __import__("json").loads(sidecar.read_text())
    data.update(expires_at="2020-01-01T00:00:00+00:00", durable_outputs_verified=False)
    sidecar.write_text(__import__("json").dumps(data))
    assert vault.cleanup(dry_run=False)["removed_bytes"] == 0
    data.update(durable_outputs_verified=True, pinned=True)
    sidecar.write_text(__import__("json").dumps(data))
    assert vault.cleanup(dry_run=False, max_items=1, max_bytes=2048)["removed_bytes"] == 0


def test_mark_media_ready_starts_temporary_grace(tmp_path, monkeypatch):
    vault = _vault(tmp_path, monkeypatch)
    source = tmp_path / "source.mov"
    source.write_bytes(b"v" * 2048)
    imported = vault.import_source(UUID, source, source_kind="manual", retention_class="temporary")
    vault.mark_media_ready(UUID, "poster")
    vault.mark_media_ready(UUID, "proxy_360p")
    data = __import__("json").loads((imported.path.parent / "source.json").read_text())
    assert data["durable_outputs_verified"] is True
    assert data["expires_at"]
