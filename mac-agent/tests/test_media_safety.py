"""Mac media safety defaults and exporter behavior."""

import asyncio
import os
import shutil
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.config import MediaConfig
from src.media_exporter import MediaExporter, MediaUnavailableError
from src.media_materializer import MIN_VIDEO_BYTES, MediaMaterializer, MaterializationError, classify_osxphotos_failure
from src.transcoder import RenditionArtifact, Transcoder
from src.media_jobs import MediaJobProcessor


class FakeReader:
    def __init__(self, video):
        self.video = video

    async def get_video_by_uuid(self, video_uuid):
        return self.video


def test_media_config_defaults_disable_risky_behavior():
    cfg = MediaConfig()

    assert cfg.enabled is False
    assert cfg.fail_unimplemented_jobs is True
    assert cfg.allow_original is False
    assert cfg.allow_icloud_download is False
    assert cfg.allow_single_asset_materialization is False
    assert cfg.materialization_cleanup_after_success is True
    assert "original" not in cfg.capabilities


def test_missing_media_config_resolves_icloud_download_false():
    cfg = MediaConfig(enabled=True)

    assert cfg.allow_icloud_download is False


def test_non_local_asset_does_not_trigger_download_when_disabled():
    exporter = MediaExporter(FakeReader({"path": None}), allow_icloud_download=False)

    with pytest.raises(MediaUnavailableError) as exc:
        asyncio.run(exporter.resolve_local_asset("25963981-122D-4E01-8C00-57DD0164EEBE"))

    assert str(exc.value) == "photos_asset_not_local_materialization_disabled"


def test_default_materialization_disabled():
    cfg = MediaConfig()

    assert cfg.allow_single_asset_materialization is False


def test_distinct_leased_jobs_run_concurrently():
    config = SimpleNamespace(
        agent=SimpleNamespace(id="mac-media-01"),
        media=SimpleNamespace(
            enabled=True,
            enforce_storage_thresholds=False,
            source_vault=SimpleNamespace(enabled=False),
            capabilities=["poster", "proxy_360p"],
            max_jobs=2,
            interval_seconds=30,
            fail_unimplemented_jobs=False,
        ),
    )
    sync_client = SimpleNamespace(
        lease_media_jobs=AsyncMock(return_value={"jobs": [
            {"job_id": 1, "video_uuid": "a", "canonical_video_uuid": "a", "rendition": "poster", "media_key": "a"},
            {"job_id": 2, "video_uuid": "b", "canonical_video_uuid": "b", "rendition": "poster", "media_key": "b"},
        ]}),
        heartbeat_media_job=AsyncMock(),
    )
    processor = MediaJobProcessor(config, sync_client)

    async def slow_job(_job):
        await asyncio.sleep(0.05)

    processor._process_job = slow_job
    started = time.monotonic()
    assert asyncio.run(processor.process_once()) == 2
    assert time.monotonic() - started < 0.09
    assert sync_client.heartbeat_media_job.await_count == 2


def test_materialization_keepalive_renews_existing_job_lease(monkeypatch):
    config = SimpleNamespace(
        agent=SimpleNamespace(id="mac-media-01"),
        media=SimpleNamespace(source_vault=SimpleNamespace(enabled=False)),
    )
    sync_client = SimpleNamespace(heartbeat_media_job=AsyncMock())
    processor = MediaJobProcessor(config, sync_client)
    monkeypatch.setattr("src.media_jobs.MATERIALIZATION_LEASE_HEARTBEAT_SECONDS", 0.01)

    async def run_keepalive():
        task = asyncio.create_task(processor._keep_materialization_lease_alive(99))
        await asyncio.sleep(0.03)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run_keepalive())
    assert sync_client.heartbeat_media_job.await_count >= 1
    sync_client.heartbeat_media_job.assert_awaited_with(99, "mac-media-01", "materializing", 5)


def test_missing_local_asset_fails_cleanly_when_materialization_disabled():
    exporter = MediaExporter(FakeReader({"path": None}), allow_single_asset_materialization=False)

    with pytest.raises(MediaUnavailableError) as exc:
        asyncio.run(exporter.resolve_local_asset("25963981-122D-4E01-8C00-57DD0164EEBE"))

    assert str(exc.value) == "photos_asset_not_local_materialization_disabled"


def test_exact_uuid_override_works():
    root = Path("~/.diveanalyzer/manual_asset_exports").expanduser()
    override_dir = root / "test-override-uuid"
    override_dir.mkdir(parents=True, exist_ok=True)
    override_file = override_dir / "asset.mov"
    override_file.write_bytes(b"video")
    exporter = MediaExporter(
        FakeReader(None),
        local_asset_overrides={"test-override-uuid": str(override_file)},
    )

    resolved = asyncio.run(exporter.resolve_local_asset("test-override-uuid"))

    assert resolved == override_file.resolve()


def test_wrong_uuid_does_not_use_override():
    root = Path("~/.diveanalyzer/manual_asset_exports").expanduser()
    override_dir = root / "right-uuid"
    override_dir.mkdir(parents=True, exist_ok=True)
    override_file = override_dir / "asset.mov"
    override_file.write_bytes(b"video")
    exporter = MediaExporter(
        FakeReader(None),
        local_asset_overrides={"right-uuid": str(override_file)},
    )

    with pytest.raises(MediaUnavailableError) as exc:
        asyncio.run(exporter.resolve_local_asset("wrong-uuid"))

    assert str(exc.value) == "photos_asset_not_found"


def test_missing_override_file_fails_cleanly():
    missing = Path("~/.diveanalyzer/manual_asset_exports/missing/asset.mov").expanduser()
    exporter = MediaExporter(FakeReader(None), local_asset_overrides={"uuid": str(missing)})

    with pytest.raises(MediaUnavailableError) as exc:
        asyncio.run(exporter.resolve_local_asset("uuid"))

    assert str(exc.value) == "local_override_file_missing"


def test_override_outside_allowed_roots_is_rejected(tmp_path: Path):
    outside = tmp_path / "asset.mov"
    outside.write_bytes(b"video")
    exporter = MediaExporter(FakeReader(None), local_asset_overrides={"uuid": str(outside)})

    with pytest.raises(MediaUnavailableError) as exc:
        asyncio.run(exporter.resolve_local_asset("uuid"))

    assert str(exc.value) == "local_override_outside_allowed_roots"


def test_original_request_blocked_unless_enabled(tmp_path: Path):
    source = tmp_path / "source.mov"
    source.write_bytes(b"video")
    exporter = MediaExporter(FakeReader({"path": str(source)}), allow_original=False)

    with pytest.raises(MediaUnavailableError) as exc:
        asyncio.run(exporter.source_for_job("uuid", "original"))

    assert str(exc.value) == "original_rendition_disabled"


def test_proxy_360p_allowed_only_if_capability_present():
    cfg = MediaConfig(capabilities=["poster"])

    assert "proxy_360p" not in cfg.capabilities


def test_proxy_transcode_ignores_photos_metadata_streams(tmp_path: Path):
    transcoder = Transcoder(str(tmp_path), ffmpeg_path="/usr/local/bin/ffmpeg")
    cmd = transcoder._proxy_cmd(tmp_path / "source.mov", tmp_path / "out.mp4", 360, 28, "96k", audio_stream_index=2)

    assert "-ignore_unknown" in cmd
    map_values = [cmd[index + 1] for index, item in enumerate(cmd) if item == "-map"]
    assert map_values == ["0:v:0", "0:2"]
    assert "-an" not in cmd
    assert "-sn" in cmd
    assert "-dn" in cmd
    assert "-map_metadata" in cmd
    assert "-c:a" in cmd
    assert cmd[cmd.index("-c:a") + 1] == "aac"
    assert any("format=yuv420p" in part for part in cmd)
    assert any("out_range=tv" in part for part in cmd)
    assert "-pix_fmt" in cmd
    assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"
    assert "-color_range" in cmd
    assert cmd[cmd.index("-color_range") + 1] == "tv"
    assert "-colorspace" in cmd
    assert cmd[cmd.index("-colorspace") + 1] == "bt709"


def test_proxy_transcode_falls_back_to_no_audio_without_real_audio(tmp_path: Path):
    transcoder = Transcoder(str(tmp_path), ffmpeg_path="/usr/local/bin/ffmpeg")
    cmd = transcoder._proxy_cmd(tmp_path / "source.mov", tmp_path / "out.mp4", 360, 28, "96k")

    map_values = [cmd[index + 1] for index, item in enumerate(cmd) if item == "-map"]
    assert map_values == ["0:v:0"]
    assert "-an" in cmd
    assert "-c:a" not in cmd


def test_empty_uuid_materialization_rejected(tmp_path: Path):
    materializer = MediaMaterializer(str(tmp_path), osxphotos_path="/bin/echo")

    with pytest.raises(MaterializationError) as exc:
        asyncio.run(materializer.materialize(""))

    assert str(exc.value) == "empty_uuid"


def test_invalid_uuid_materialization_rejected(tmp_path: Path):
    materializer = MediaMaterializer(str(tmp_path), osxphotos_path="/bin/echo")

    with pytest.raises(MaterializationError) as exc:
        asyncio.run(materializer.materialize("not-a-uuid"))

    assert str(exc.value) == "invalid_uuid"


def test_single_uuid_materialization_command_is_correctly_scoped(tmp_path: Path):
    materializer = MediaMaterializer(str(tmp_path), osxphotos_path="/usr/local/bin/osxphotos")
    uuid = "25963981-122D-4E01-8C00-57DD0164EEBE"
    target = (tmp_path / uuid).resolve()
    cmd = materializer._build_command(target, uuid)

    assert isinstance(cmd, list)
    assert cmd.count("--uuid") == 1
    assert cmd[cmd.index("--uuid") + 1] == uuid
    assert "--only-movies" in cmd
    assert "--download-missing" in cmd
    assert "--album" not in cmd
    assert "--query" not in cmd


def test_photokit_materialization_remains_single_uuid_scoped(tmp_path: Path):
    materializer = MediaMaterializer(
        str(tmp_path),
        osxphotos_path="/usr/local/bin/osxphotos",
        use_photokit=True,
    )
    uuid = "25963981-122D-4E01-8C00-57DD0164EEBE"
    cmd = materializer._build_command((tmp_path / uuid).resolve(), uuid)

    assert "--use-photokit" in cmd
    assert cmd.count("--uuid") == 1
    assert "--only-movies" in cmd
    assert "--download-missing" in cmd


def test_no_shell_true_used_for_osxphotos_command(tmp_path: Path, monkeypatch):
    calls = {}

    async def fake_exec(*cmd, **kwargs):
        calls["cmd"] = cmd
        calls["kwargs"] = kwargs

        class Process:
            returncode = 0

            async def communicate(self):
                output = tmp_path / "25963981-122D-4E01-8C00-57DD0164EEBE" / "asset.mp4"
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"0" * MIN_VIDEO_BYTES)
                return b"", b""

        return Process()

    monkeypatch.setattr("src.media_materializer.asyncio.create_subprocess_exec", fake_exec)
    materializer = MediaMaterializer(str(tmp_path), osxphotos_path="/usr/local/bin/osxphotos")

    resolved = asyncio.run(materializer.materialize("25963981-122D-4E01-8C00-57DD0164EEBE"))

    assert resolved.name == "asset.mp4"
    assert "shell" not in calls["kwargs"]
    assert calls["cmd"][0] == "/usr/local/bin/osxphotos"


def test_materialization_path_outside_dir_rejected(tmp_path: Path, monkeypatch):
    materializer = MediaMaterializer(str(tmp_path), osxphotos_path="/usr/local/bin/osxphotos")

    def fake_find(_target):
        outside = tmp_path.parent / "outside.mp4"
        outside.write_bytes(b"video")
        resolved = outside.resolve()
        if not str(resolved).startswith(str(materializer.root)):
            raise MaterializationError("materialized_path_outside_root")
        return resolved

    async def fake_exec(*cmd, **kwargs):
        class Process:
            returncode = 0

            async def communicate(self):
                return b"", b""

        return Process()

    monkeypatch.setattr("src.media_materializer.asyncio.create_subprocess_exec", fake_exec)
    monkeypatch.setattr(materializer, "_find_materialized_video", fake_find)

    with pytest.raises(MaterializationError) as exc:
        asyncio.run(materializer.materialize("25963981-122D-4E01-8C00-57DD0164EEBE"))

    assert str(exc.value) == "materialized_path_outside_root"


def test_materialized_file_inside_dir_accepted(tmp_path: Path):
    materializer = MediaMaterializer(str(tmp_path), osxphotos_path="/bin/echo")
    target = tmp_path / "25963981-122D-4E01-8C00-57DD0164EEBE"
    target.mkdir()
    asset = target / "asset.mp4"
    asset.write_bytes(b"0" * MIN_VIDEO_BYTES)

    resolved = materializer._find_materialized_video(target)

    assert resolved == asset.resolve()


def test_materialized_tiny_placeholder_file_rejected(tmp_path: Path):
    materializer = MediaMaterializer(str(tmp_path), osxphotos_path="/bin/echo")
    target = tmp_path / "25963981-122D-4E01-8C00-57DD0164EEBE"
    target.mkdir()
    asset = target / "asset.mp4"
    asset.write_bytes(b"placeholder")

    with pytest.raises(MaterializationError) as exc:
        materializer._find_materialized_video(target)

    assert str(exc.value) == "materialization_only_placeholders"
    assert exc.value.retryable is False


def test_osxphotos_failure_classification_distinguishes_permission_and_placeholder_classes():
    assert classify_osxphotos_failure("Operation not permitted by macOS Privacy") == "permission_required"
    assert classify_osxphotos_failure("Access denied to Photos library") == "photos_access_denied"
    assert classify_osxphotos_failure("export timed out waiting for Photos") == "osxphotos_export_timeout"
    assert classify_osxphotos_failure("unexpected export failure") == "osxphotos_export_failed"


def test_materialization_cleanup_removes_source_after_success(tmp_path: Path):
    root = tmp_path / "materialized"
    source_dir = root / "25963981-122D-4E01-8C00-57DD0164EEBE"
    source_dir.mkdir(parents=True)
    source = source_dir / "asset.mp4"
    sidecar = source_dir / ".osxphotos_export.db"
    source.write_bytes(b"video")
    sidecar.write_bytes(b"db")
    materializer = MediaMaterializer(str(root), osxphotos_path="/bin/echo")
    exporter = MediaExporter(
        FakeReader(None),
        allow_single_asset_materialization=True,
        materializer=materializer,
        materialization_cleanup_after_success=True,
    )
    exporter._materialized_sources.add(source.resolve())

    exporter.cleanup_source_after_success(source)

    assert not source.exists()
    assert not sidecar.exists()
    assert not source_dir.exists()


def test_vault_import_removes_duplicate_materialization_but_keeps_vault_copy(tmp_path: Path):
    uuid = "25963981-122D-4E01-8C00-57DD0164EEBE"
    materialization_root = tmp_path / "incoming"
    source_dir = materialization_root / uuid
    source_dir.mkdir(parents=True)
    source = source_dir / "asset.mov"
    source.write_bytes(b"video")
    (source_dir / ".osxphotos_export.db").write_bytes(b"db")
    vault_path = tmp_path / "vault" / uuid / "source.mov"

    materializer = MediaMaterializer(str(materialization_root), osxphotos_path="/bin/echo")

    async def materialize(_uuid):
        return source.resolve()

    materializer.materialize = materialize

    class FakeVault:
        def resolve(self, _uuid):
            return None

        def import_source(self, *_args, **_kwargs):
            vault_path.parent.mkdir(parents=True)
            shutil.copy2(source, vault_path)
            return SimpleNamespace(path=vault_path.resolve())

    exporter = MediaExporter(
        FakeReader({"path": None}),
        allow_single_asset_materialization=True,
        materializer=materializer,
        materialization_cleanup_after_success=True,
        source_vault=FakeVault(),
    )

    resolved = asyncio.run(exporter.resolve_local_asset(uuid))

    assert resolved == vault_path.resolve()
    assert vault_path.read_bytes() == b"video"
    assert not source_dir.exists()


def test_failed_materialization_ttl_cleanup_is_bounded(tmp_path: Path):
    root = tmp_path / "materialized"
    stale = root / "25963981-122D-4E01-8C00-57DD0164EEBE"
    fresh = root / "35963981-122D-4E01-8C00-57DD0164EEBE"
    stale.mkdir(parents=True)
    fresh.mkdir(parents=True)
    (stale / "placeholder.mov").write_bytes(b"tiny")
    (fresh / "placeholder.mov").write_bytes(b"tiny")
    old = time.time() - 49 * 3600
    os.utime(stale / "placeholder.mov", (old, old))
    os.utime(stale, (old, old))
    materializer = MediaMaterializer(str(root), osxphotos_path="/bin/echo")

    retained = materializer.cleanup_failed_residue(retain_failed=True)
    removed = materializer.cleanup_failed_residue(retain_failed=False, ttl_hours=24)

    assert retained == {"removed_dirs": 0, "removed_bytes": 0}
    assert removed["removed_dirs"] == 1
    assert not stale.exists()
    assert fresh.exists()


def test_temporary_artifact_cleanup_removes_generated_file(tmp_path: Path):
    artifact_path = tmp_path / "poster.jpg"
    artifact_path.write_bytes(b"poster")
    artifact = RenditionArtifact(
        path=artifact_path,
        content_type="image/jpeg",
        checksum_sha256="0" * 64,
        size_bytes=6,
    )

    artifact.cleanup()

    assert not artifact_path.exists()


def test_original_artifact_cleanup_does_not_delete_source(tmp_path: Path):
    source = tmp_path / "source.mov"
    source.write_bytes(b"video")
    artifact = RenditionArtifact(
        path=source,
        content_type="application/octet-stream",
        checksum_sha256="0" * 64,
        size_bytes=5,
        is_temporary=False,
    )

    artifact.cleanup()

    assert source.exists()
