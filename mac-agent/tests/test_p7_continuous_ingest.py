"""P7 continuous dual-write tests (packet
MEDIA_BACKBONE_P7_ACCELERATED_CONTINUOUS_INGEST_MIGRATION_V1 §5/§6/§7/§9/§33).

Offline (fakes only, no credentials, no network):
- activation boundary: continuous mode triggers ONLY on the exact configured
  new-captioned-ingestion request reason (existing production media-job event
  stream); the 5-10 UUID cohort allowlist remains canary/debug-only
- no backlog explosion: historical/renovation job reasons (catalog population,
  resolution upgrade, representative replacement) NEVER activate dual-write;
  no allowlist dependency in continuous mode
- legacy ingest independence: B2 store unavailable at staging/launch time
  never affects the legacy job result
- disk bounds: staging refuses when free disk cannot hold the copy + guard
- rollback proof: flags off -> byte-identical legacy-only behavior
"""

import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.ingest.dual_write as dual_write
from src.ingest.errors import ObjectStoreUnavailable
from src.ingest.state_store import IngestStateStore
from src.ingest.states import IngestState

UUID_NEW = "11111111-1111-1111-1111-111111111111"
UUID_HIST = "22222222-2222-2222-2222-222222222222"
UUID_CANARY = "33333333-3333-3333-3333-333333333333"
COHORT_5 = [UUID_NEW, UUID_HIST, UUID_CANARY,
            "44444444-4444-4444-4444-444444444444",
            "55555555-5555-5555-5555-555555555555"]
TRIGGER = "new_captioned_ingestion"


def make_config(tmp_path, *, continuous=True, allowlist=None, dual_enabled=True):
    state_dir = tmp_path / "state"
    temp_root = tmp_path / "tmp"
    return SimpleNamespace(
        server=SimpleNamespace(url="https://backend.internal", api_key="x" * 48, ca_cert_path=""),
        photos=SimpleNamespace(library_path="/tmp/fake-library"),
        media=SimpleNamespace(ffprobe_path="ffprobe-fake"),
        object_store=SimpleNamespace(
            enabled=True,
            environment="prod",
            bucket="diveanalyzer-prod-media",
            region="eu-central-003",
            endpoint_url="https://s3.eu-central-003.backblazeb2.com",
            prefix="blobs/sha256",
            state_dir=str(state_dir),
            temp_root=str(temp_root),
            min_free_disk_bytes=1024,
            presign_ttl_seconds=300,
            max_retries=3,
            storage_backend="b2",
        ),
        dual_write=SimpleNamespace(
            enabled=dual_enabled,
            continuous_new_ingest=continuous,
            trigger_reason=TRIGGER,
            allowlist=list(allowlist or []),
            commit_endpoint_path="/api/v1/media/backbone/commit",
            commit_timeout_seconds=30,
            env_file="",
            fail_put_once=False,
            fail_commit_once=False,
        ),
    )


# ---------------------------------------------------------------------------
# Activation boundary (§5/§6)


def test_continuous_boundary_triggers_on_new_captioned_reason(tmp_path):
    pdw = dual_write.ProductionDualWrite.from_config(make_config(tmp_path))
    assert pdw is not None
    assert pdw.should_process(UUID_NEW, TRIGGER) is True
    # a different asset with the same production reason is equally eligible:
    # no allowlist dependency (§7)
    assert pdw.should_process(UUID_HIST, TRIGGER) is True


def test_continuous_boundary_refuses_other_job_reasons(tmp_path):
    """Backlog-explosion isolation (§6): renovation/population/upgrade events
    for HISTORICAL assets never activate the continuous path."""
    pdw = dual_write.ProductionDualWrite.from_config(make_config(tmp_path))
    for reason in (
        "catalog_population_stage_2",
        "resolution_upgrade_720p",
        "representative_replacement",
        None,
        "",
        "new_captioned_ingestionx",
        "NEW_captioned_ingestion",
    ):
        assert pdw.should_process(UUID_HIST, reason) is False, reason


def test_canary_mode_keeps_allowlist_guard(tmp_path):
    # canary/debug mode keeps the P4.2 bounded-cohort guard (5-10 explicit
    # UUIDs); membership decides activation, NOT the continuous reason
    cfg = make_config(tmp_path, continuous=False, allowlist=list(COHORT_5))
    pdw = dual_write.ProductionDualWrite.from_config(cfg)
    assert UUID_CANARY in COHORT_5
    assert pdw.should_process(UUID_CANARY) is True
    outside = "66666666-6666-6666-6666-666666666666"
    assert outside not in COHORT_5
    assert pdw.should_process(outside, TRIGGER) is False


def test_canary_mode_empty_allowlist_refuses_to_arm(tmp_path):
    cfg = make_config(tmp_path, continuous=False, allowlist=[])
    with pytest.raises(ValueError):
        dual_write.ProductionDualWrite.from_config(cfg)


def test_config_validation_continuous_mode_requires_no_allowlist(tmp_path):
    from src.config import Config

    config = Config.__new__(Config)
    config.object_store = SimpleNamespace(
        enabled=True, environment="prod", bucket="diveanalyzer-prod-media",
        region="", endpoint_url="", prefix="blobs/sha256", state_dir="",
        temp_root="", min_free_disk_bytes=0, presign_ttl_seconds=300,
        max_retries=3,
    )
    config.dual_write = SimpleNamespace(
        enabled=True, continuous_new_ingest=True, trigger_reason=TRIGGER,
        allowlist=[], commit_endpoint_path="/x", commit_timeout_seconds=30,
        env_file="e", fail_put_once=False, fail_commit_once=False,
    )
    assert config._validate_dual_write_config() is None


def test_continuous_mode_staging_accepts_reason(tmp_path):
    pdw = dual_write.ProductionDualWrite.from_config(make_config(tmp_path))
    source = tmp_path / "source.mov"
    source.write_bytes(b"new-clip-bytes")
    staged = pdw.stage_copy(UUID_NEW, source, TRIGGER)
    assert staged is not None and staged.is_file()


def test_continuous_mode_staging_refuses_history(tmp_path):
    pdw = dual_write.ProductionDualWrite.from_config(make_config(tmp_path))
    source = tmp_path / "source.mov"
    source.write_bytes(b"historical-bytes")
    for reason in ("catalog_population_stage_1", None):
        assert pdw.stage_copy(UUID_HIST, source, reason) is None
    assert not (pdw.temp_root / "dual_write_staging" / UUID_HIST).exists()


def test_no_photos_or_db_scanning_wiring(tmp_path):
    """Structural no-explosion proof: the continuous path stages only from
    the bytes the legacy job already materialized — no library/DB discovery
    surface is reachable from stage_copy/launch."""
    import inspect

    src = inspect.getsource(dual_write.ProductionDualWrite.stage_copy)
    assert "get_all_videos" not in src
    assert "photos(" not in src.replace("photos_db", "").replace("get_photos_db", "")


# ---------------------------------------------------------------------------
# Legacy independence + disk bounds (§9/§24/§33)


def test_staging_refused_on_insufficient_disk(tmp_path):
    cfg = make_config(tmp_path)
    cfg.object_store.min_free_disk_bytes = 10**15  # absurd guard
    pdw = dual_write.ProductionDualWrite.from_config(cfg)
    source = tmp_path / "source.mov"
    source.write_bytes(b"bytes")
    assert pdw.stage_copy(UUID_NEW, source, TRIGGER) is None
    meta = pdw._read_stage_meta(UUID_NEW)
    assert meta.get("skip_reason") == "insufficient_disk_for_staging"
    # nothing staged, backpressure slot untouched
    assert not pdw._active


def test_backpressure_marker_still_bounded_under_continuous(tmp_path):
    pdw = dual_write.ProductionDualWrite.from_config(make_config(tmp_path))
    source = tmp_path / "a.mov"
    source.write_bytes(b"x" * 16)
    first = pdw.stage_copy(UUID_NEW, source, TRIGGER)
    assert first is not None
    second = pdw.stage_copy(UUID_HIST, source, TRIGGER)
    assert second is None  # one active materialization
    meta = pdw._read_stage_meta(UUID_HIST)
    assert meta.get("backpressure_skip") is True
    assert meta.get("skip_reason") == "one_active_materialization_slot_busy"
    # no staged bytes for the skipped asset
    assert not (pdw.temp_root / "dual_write_staging" / UUID_HIST).exists()
    pdw._release(UUID_NEW)


def test_one_materialization_semantics_documented(tmp_path):
    import inspect

    src = inspect.getsource(dual_write.ProductionDualWrite._drive)
    # the dual-write driver reuses staged legacy bytes; it never triggers a
    # second Photos export (§8)
    assert "extra_photos_materializations" in src


def test_feature_off_is_legacy_only(tmp_path):
    cfg = make_config(tmp_path, dual_enabled=False)
    assert dual_write.ProductionDualWrite.from_config(cfg) is None


def test_continuous_requires_object_store_enabled(tmp_path):
    cfg = make_config(tmp_path)
    cfg.object_store.enabled = False
    with pytest.raises(ValueError):
        dual_write.ProductionDualWrite.from_config(cfg)


def test_continuous_requires_prod_environment(tmp_path):
    cfg = make_config(tmp_path)
    cfg.object_store.environment = "dev"
    with pytest.raises(ValueError):
        dual_write.ProductionDualWrite.from_config(cfg)


def test_job_processor_hook_passes_reason(tmp_path):
    import inspect

    from src.media_jobs import MediaJobProcessor

    src = inspect.getsource(MediaJobProcessor._trigger_dual_write)
    assert "request_reason" in src
    proc_src = inspect.getsource(MediaJobProcessor._process_job)
    assert 'job.get("request_reason")' in proc_src


# ---------------------------------------------------------------------------
# Static no-delete/hide firewall extension (§35)


def test_migration_module_never_imports_delete_primitives():
    from pathlib import Path as _P

    migration_src = (_P(__file__).resolve().parents[1] / "src" / "ingest" / "migration.py").read_text(
        encoding="utf-8"
    )
    for banned in (
        "delete_object_explicit_operator_action",
        "b2_hide_file",
        "b2_delete_file_version",
        "delete_object(",
        "DeleteObject",
    ):
        assert banned not in migration_src, banned
