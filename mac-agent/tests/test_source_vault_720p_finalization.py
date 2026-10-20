"""Lot B: Mac source vault finalises on 720p (or legacy 360p) + poster.

A mere job request or a failed transcode never finalises a source: only an
explicit mark_media_ready after a verified upload does. Cleanup keeps
skipping unverified, pinned, active or ungated sources.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from src.source_vault import MediaSourceVault

UUID = "3F8C11AA-D4CC-4E68-8A6A-8FFA28147836"
UUID_LEGACY = "4F8C11AA-D4CC-4E68-8A6A-8FFA28147837"


def _vault(tmp_path: Path, monkeypatch, actual_uuid="VOLUME-1"):
    root = tmp_path / "by_uuid"
    root.mkdir()
    monkeypatch.setattr("src.source_vault.validate_video_source", lambda path, ffprobe: (path.stat().st_size, "a" * 64))
    monkeypatch.setattr("src.source_vault.sha256_file", lambda path: "a" * 64)
    return MediaSourceVault(str(root), "VOLUME-1", "/usr/bin/false", volume_uuid_resolver=lambda path: actual_uuid)


def _sidecar(vault, uuid):
    for uuid_dir in Path(vault.root).iterdir():
        if uuid_dir.name == uuid:
            return uuid_dir / "source.json"
    raise AssertionError("missing sidecar")


def test_720p_plus_poster_finalises_with_grace(tmp_path, monkeypatch):
    vault = _vault(tmp_path, monkeypatch)
    source = tmp_path / "source.mov"
    source.write_bytes(b"v" * 2048)
    vault.import_source(UUID, source, source_kind="manual", retention_class="temporary")

    # A mere request (no mark) never finalises.
    data = json.loads(_sidecar(vault, UUID).read_text())
    assert data["durable_outputs_verified"] is False

    # Poster alone is not enough.
    vault.mark_media_ready(UUID, "poster")
    data = json.loads(_sidecar(vault, UUID).read_text())
    assert data["poster_ready"] is True
    assert data["durable_outputs_verified"] is False

    # A failed transcode never calls mark_media_ready: still unverified.
    data = json.loads(_sidecar(vault, UUID).read_text())
    assert data["durable_outputs_verified"] is False

    vault.mark_media_ready(UUID, "proxy_720p")
    data = json.loads(_sidecar(vault, UUID).read_text())
    assert data["proxy_ready"] is True
    assert data["durable_outputs_verified"] is True
    assert data["expires_at"]


def test_legacy_360p_still_finalises_but_is_not_required(tmp_path, monkeypatch):
    vault = _vault(tmp_path, monkeypatch)
    source = tmp_path / "source.mov"
    source.write_bytes(b"v" * 2048)
    vault.import_source(UUID_LEGACY, source, source_kind="manual", retention_class="temporary")
    vault.mark_media_ready(UUID_LEGACY, "poster")
    vault.mark_media_ready(UUID_LEGACY, "proxy_360p")
    data = json.loads(_sidecar(vault, UUID_LEGACY).read_text())
    assert data["durable_outputs_verified"] is True


def test_cleanup_skips_unverified_pinned_and_active(tmp_path, monkeypatch):
    vault = _vault(tmp_path, monkeypatch)
    source = tmp_path / "source.mov"
    source.write_bytes(b"v" * 2048)
    vault.import_source(UUID, source, source_kind="manual", retention_class="temporary")
    sidecar = _sidecar(vault, UUID)
    data = json.loads(sidecar.read_text())
    # Even past expiry, an unverified source is never cleanable.
    data.update(expires_at="2020-01-01T00:00:00+00:00", durable_outputs_verified=False)
    sidecar.write_text(json.dumps(data))
    assert vault.cleanup(dry_run=False, now=datetime.now(timezone.utc))["removed_bytes"] == 0

    # Verified but pinned or active stays protected.
    vault.mark_media_ready(UUID, "poster")
    vault.mark_media_ready(UUID, "proxy_720p")
    data = json.loads(sidecar.read_text())
    data.update(expires_at="2020-01-01T00:00:00+00:00", pinned=True)
    sidecar.write_text(json.dumps(data))
    assert vault.cleanup(dry_run=False)["removed_bytes"] == 0

    data = json.loads(sidecar.read_text())
    data.update(pinned=False, active_job=True)
    sidecar.write_text(json.dumps(data))
    assert vault.cleanup(dry_run=False)["removed_bytes"] == 0
