"""P4.3 connectivity probe + materializer timeout tests (packet §21/§22)."""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import MediaConfig  # noqa: E402
from src.network import NetworkMonitor, is_online  # noqa: E402


def test_probe_offline_reports_curl_exit_and_stderr(caplog):
    """A failing probe surfaces the mechanical cause at WARNING (§21).

    The pre-P4.3 code swallowed the curl exit code and stderr at DEBUG, which
    is what made the intermittent 000s undiagnosable. TLS verification itself
    is untouched (the CA bundle authority is unchanged).
    """
    with caplog.at_level("WARNING"):
        online = asyncio.run(is_online("http://127.0.0.1:9", timeout=2))
    assert online is False
    assert "probe returned" in caplog.text


def test_probe_uses_ca_when_provided(monkeypatch):
    """TLS authority unchanged: --cacert stays on the probe command line."""
    import subprocess

    captured = {}

    def fake_run(cmd, capture_output=True, text=True, timeout=None):
        captured["cmd"] = cmd
        result = type(
            "R",
            (),
            {
                "stdout": "200",
                "stderr": "",
                "returncode": 0,
            },
        )()
        return result

    monkeypatch.setattr(subprocess, "run", fake_run)
    online = asyncio.run(
        is_online(
            "https://backend.internal",
            timeout=5,
            ca_cert_path="/state/diveanalyzer-ca.pem",
        )
    )
    assert online is True
    assert "--cacert" in captured["cmd"]
    assert "/state/diveanalyzer-ca.pem" in captured["cmd"]


def test_network_monitor_propagates_internal_ca(monkeypatch):
    """Repair regression guard: NetworkMonitor must probe WITH the CA.

    The P4.2 finding: NetworkMonitor.check_connectivity() probed without
    ca_cert_path, so HTTPS probes failed at TLS handshake and reported the
    server offline while it was reachable.
    """
    captured = {}

    async def fake_is_online(url, timeout=5.0, ca_cert_path=""):
        captured["url"] = url
        captured["ca_cert_path"] = ca_cert_path
        return True

    monkeypatch.setattr("src.network.is_online", fake_is_online)
    monitor = NetworkMonitor(
        "https://backend.internal", ca_cert_path="/state/diveanalyzer-ca.pem"
    )
    from datetime import datetime, timedelta

    monitor.last_check = datetime.now() - timedelta(hours=1)  # bypass throttle
    assert asyncio.run(monitor.check_connectivity()) is True
    assert captured["ca_cert_path"] == "/state/diveanalyzer-ca.pem"
    assert captured["url"] == "https://backend.internal"


def test_materializer_timeout_default_unchanged():
    cfg = MediaConfig()
    assert cfg.materialization_timeout_seconds == 600  # pre-P4.3 behavior


@pytest.mark.parametrize("bad", [0, 29, 3601, -100])
def test_materializer_timeout_bounded_validation(bad):
    from src.config import Config

    cfg = Config.__new__(Config)
    cfg.media = MediaConfig(
        materialization_timeout_seconds=bad,
        materialization_dir="/tmp/p43-test-materialization",
    )
    cfg._validate_media_config.__func__ if False else None
    import src.config as config_module

    original = config_module.Config._validate_media_config
    # Run ONLY the timeout check by executing the method on a minimal stub:
    # the real validator requires full media/source-vault state, so call the
    # real method but tolerate earlier unrelated failures — the timeout
    # check is independent and raises on its own.
    try:
        cfg._validate_media_config()
        pytest.fail(f"expected ValueError for materialization_timeout_seconds={bad}")
    except ValueError as exc:
        assert "materialization_timeout_seconds" in str(exc)


def test_materializer_timeout_accepted(tmp_path):
    from src.config import Config

    cfg = Config.__new__(Config)
    cfg.media = MediaConfig(
        materialization_timeout_seconds=900,
        materialization_dir="/tmp/p43-test-materialization",
    )
    cfg._validate_media_config()


def test_media_jobs_wires_materializer_timeout(monkeypatch):
    """_build_pipeline passes the configured timeout into MediaMaterializer."""
    import src.media_jobs as media_jobs

    captured = {"materializer": None}

    class _FakeReader:
        def __init__(self, *a, **k):
            pass

    def _fake_exporter(reader, *, allow_original=False, allow_icloud_download=False,
                       local_asset_overrides=None, allow_single_asset_materialization=False,
                       materializer=None, materialization_cleanup_after_success=True,
                       source_vault=None):
        captured["materializer"] = materializer
        return object()

    monkeypatch.setattr(media_jobs, "PhotosReader", _fake_exporter)
    monkeypatch.setattr(media_jobs, "MediaExporter", _fake_exporter)
    monkeypatch.setattr(
        media_jobs, "Transcoder", lambda *a, **k: object()
    )
    monkeypatch.setattr(
        media_jobs, "MediaUploader", lambda *a, **k: object()
    )

    class _MediaCfg:
        allow_single_asset_materialization = True
        materialization_dir = "/tmp/p43-test-materialization"
        materialization_max_bytes = 100
        materialization_timeout_seconds = 900
        materialization_use_photokit = False
        materialization_cleanup_after_success = True
        allow_original = False
        allow_icloud_download = False
        local_asset_overrides = {}
        osxphotos_path = "/usr/bin/false"
        temp_dir = "/tmp/p43-test-materialization"
        ffmpeg_path = "/usr/bin/false"

    class _Cfg:
        media = _MediaCfg()
        photos = type("P", (), {"library_path": "/x"})()

    runner = object.__new__(media_jobs.MediaJobProcessor)
    runner.config = _Cfg()
    runner.source_vault = None
    runner.sync_client = object()
    runner.agent_id = "test-agent"
    runner._build_pipeline()
    materializer = captured["materializer"]
    assert materializer is not None
    assert materializer.export_timeout_seconds == 900
    # An explicit --library keeps osxphotos away from the Photos container
    # plist, whose App Data consent prompt hangs every export under launchd.
    assert materializer.library_path == "/x"
    assert "--library" in materializer._build_command(Path("/tmp/out"), "A" * 8)
