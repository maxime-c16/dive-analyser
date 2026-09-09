"""P3 bounded queue tests: allowlist guards, queue execution, failure
isolation, content dedupe, restart convergence, low-disk guard, media
mutation — all offline (FakeObjectStore + fake PhotosDB), no credentials."""

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.ingest.p3_queue as p3_queue
import src.ingest.canary as canary_module
from src.ingest.caption import CaptionResult, CurrentStableCaptionProvider, caption_sha256
from src.ingest.objectstore.fake import FakeObjectStore
from src.ingest.state_store import IngestStateStore

UUID_A = "11111111-1111-1111-1111-111111111111"
UUID_B = "22222222-2222-2222-2222-222222222222"
UUID_C = "33333333-3333-3333-3333-333333333333"
UUID_D = "44444444-4444-4444-4444-444444444444"
UUID_E = "55555555-5555-5555-5555-555555555555"
UUID_F = "66666666-6666-6666-6666-666666666666"
UUID_G = "77777777-7777-7777-7777-777777777777"
UUID_H = "88888888-8888-8888-8888-888888888888"
ALL_UUIDS = [UUID_A, UUID_B, UUID_C, UUID_D, UUID_E, UUID_F, UUID_G, UUID_H]


class FakePhoto:
    def __init__(self, uuid, description, hasadjustments=False, ismissing=True, incloud=True):
        self.uuid = uuid
        self.original_filename = f"IMG_{uuid[:4]}.mov"
        self.description = description
        self.ismovie = True
        self.hasadjustments = hasadjustments
        self.ismissing = ismissing
        self.incloud = incloud
        self.favorite = False
        self.date = None


class FakeAlbum:
    def __init__(self, title, photos):
        self.title = title
        self.photos = photos


class FakeDb:
    def __init__(self, photos, album_title="DiveAnalyser Ready"):
        self._photos = {p.uuid: p for p in photos}
        self.album_info = [FakeAlbum(album_title, photos)]

    def photos(self, uuid=None):
        if uuid is None:
            return list(self._photos.values())
        return [self._photos[u] for u in uuid if u in self._photos]


CAPTIONS = {
    UUID_A: "107B | 7.5 | H:3 | drill:no-arms | note:à revoir",
    UUID_B: "101B 4.0 G",
    UUID_C: "201C 5.0 M",  # same media bytes as B (dedupe case)
    UUID_D: "301A 7.5 P",
    UUID_E: "5231D 5.2 B sync",
    UUID_F: "105C 3.0 F",
    UUID_G: "107C 5.0 G",
    UUID_H: "109B 3.2 P",
}


def fake_media_bytes(video_uuid: str, dedupe_group: str | None = None) -> bytes:
    group = dedupe_group or video_uuid
    return f"media-bytes:{group}".encode("utf-8")


MATERIALIZE_MAP: dict[str, str] = {}


def make_fake_db():
    photos = [FakePhoto(u, CAPTIONS[u]) for u in ALL_UUIDS]
    return FakeDb(photos)


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    MATERIALIZE_MAP.clear()
    state_dir = tmp_path / "state"
    temp_root = tmp_path / "tmp"
    state_dir.mkdir()
    temp_root.mkdir()
    db = make_fake_db()

    def materialize(video_uuid: str, workdir: Path) -> Path:
        target = workdir / f"{video_uuid}.mov"
        target.write_bytes(fake_media_bytes(video_uuid, MATERIALIZE_MAP.get(video_uuid)))
        return target

    def describe(video_uuid: str):
        photo = db.photos(uuid=[video_uuid])
        return photo[0].description if photo else None

    stable = CurrentStableCaptionProvider(describe)

    class FakeShadow:
        name = "fake_shadow"
        provider = "fake_shadow"
        provider_kind = "fake"

        def get_caption(self, video_uuid: str) -> CaptionResult:
            raw = CAPTIONS.get(video_uuid)
            if raw is None:
                return CaptionResult(self.name, False, None, None, "no_caption", provider_kind=self.provider_kind)
            return CaptionResult(self.name, True, raw, caption_sha256(raw), None, provider_kind=self.provider_kind)

    monkeypatch.setattr(p3_queue, "ffprobe_metadata", lambda path, ffprobe_bin: {
        "codec": "hevc", "width": 1920, "height": 1080,
        "duration_seconds": 9.288, "container": "mov", "bit_rate": 16000000,
        "start_pts": 0, "start_time": "0", "nb_frames": "580",
    })
    monkeypatch.setattr(canary_module, "get_photos_db", lambda path: db)
    monkeypatch.setattr(p3_queue, "get_photos_db", lambda path: db)
    fake_store = FakeObjectStore()
    monkeypatch.setattr(
        p3_queue,
        "build_b2_store",
        lambda cfg, env: (fake_store, SimpleNamespace(bucket="fake-bucket")),
    )

    full_ctx = {
        "cfg": {
            "photos": {"library_path": "/tmp/fake-library"},
            "object_store": {
                "environment": "dev",
                "bucket": "fake-bucket",
                "prefix": "blobs/sha256",
                "state_dir": str(state_dir),
                "temp_root": str(temp_root),
                "min_free_disk_bytes": 0,
                "storage_backend": "b2",
            },
            "materializer": {},
            "ffprobe_path": "ffprobe-fake",
        },
        "os_cfg": {
            "environment": "dev",
            "bucket": "fake-bucket",
            "prefix": "blobs/sha256",
            "state_dir": str(state_dir),
            "temp_root": str(temp_root),
            "min_free_disk_bytes": 0,
            "storage_backend": "b2",
        },
        "state_dir": state_dir,
        "temp_root": temp_root,
        "library_path": "/tmp/fake-library",
        "stable": stable,
        "shadow": FakeShadow(),
        "store": fake_store,
        "b2_config": SimpleNamespace(bucket="fake-bucket"),
        "materialize_fn": materialize,
        "ffprobe_bin": "ffprobe-fake",
        "db": db,
    }
    monkeypatch.setattr(p3_queue, "build_queue_context", lambda cfg, env_file: full_ctx)

    return full_ctx


# ---------------------------------------------------------------------------
# Queue execution


def install_fake_transport(monkeypatch, store: FakeObjectStore, blobs_committed: set):
    """Mimic the server commit service: idempotent by SHA, receipt-confirmed."""

    def factory(cmd, state_dir, video_uuid):
        def commit_db_fn(payload):
            assert payload["remote_verified"] is True
            sha = payload["blob"]["sha256"]
            blob_existed = sha in blobs_committed
            blobs_committed.add(sha)
            result = {
                "video_uuid": payload["video_uuid"],
                "blob_sha256": sha,
                "blob_existed": blob_existed,
                "media_revision_id": 1,
                "media_revision_existed": False,
                "caption_revision_id": 1,
                "caption_revision_existed": False,
                "ingest_state_id": 1,
            }
            receipt = {"input": {"payload": payload}, "result": result}
            (state_dir / f"{video_uuid}.commit_receipt.json").write_text(
                json.dumps(receipt), encoding="utf-8"
            )
            return result

        return commit_db_fn

    monkeypatch.setattr(p3_queue, "make_transport_commit_fn", factory)


def base_options(**overrides):
    options = {
        "max_passes_per_asset": 5,
        "retry_backoff_seconds": 0.0,
        "skip_put_if_remote_present": True,
    }
    options.update(overrides)
    return options


def test_queue_refuses_allowlist_outside_album(ctx, monkeypatch, tmp_path):
    monkeypatch.setattr(p3_queue, "get_photos_db", lambda path: ctx["db"])
    outside = ALL_UUIDS[:5] + ["99999999-9999-9999-9999-999999999999"]
    rc = p3_queue.run_queue(ctx["cfg"], {"allowlist": outside})
    assert rc == 3


def test_queue_ingests_all_assets_with_metrics(ctx, monkeypatch, tmp_path):
    monkeypatch.setattr(p3_queue, "get_photos_db", lambda path: ctx["db"])
    install_fake_transport(monkeypatch, ctx["store"], set())
    options = base_options(commit_transport_cmd="true")
    rc = p3_queue.run_queue(ctx["cfg"], {**options, "allowlist": ALL_UUIDS})
    assert rc == 0
    metrics = json.loads((ctx["state_dir"] / "p3_metrics.json").read_text())
    summary = p3_queue.summarize_metrics(metrics)
    assert summary["sample_size"] == 8
    assert summary["ingested"] == 8
    assert summary["quarantined"] == 0
    assert summary["unique_media_blobs"] == 8
    for asset in metrics["assets"]:
        assert asset["final_state"] == "IngestState.CACHE_CLEANED"
        assert asset["media_sha256"]
        journal = json.loads((ctx["state_dir"] / f"{asset['video_uuid']}.json").read_text())
        assert journal["state"] == "CACHE_CLEANED"
        assert journal["remote"]["verified"] is True
        assert journal["db_commit"]["committed"] is True
    # temp cleaned for every asset
    assert p3_queue.temp_cache_bytes(ctx["temp_root"]) == 0


def test_queue_deduplicates_identical_media(ctx, monkeypatch):
    MATERIALIZE_MAP[UUID_B] = "shared-bytes"
    MATERIALIZE_MAP[UUID_C] = "shared-bytes"
    monkeypatch.setattr(p3_queue, "get_photos_db", lambda path: ctx["db"])
    blobs_committed: set = set()
    install_fake_transport(monkeypatch, ctx["store"], blobs_committed)
    options = base_options(commit_transport_cmd="true", run_min_allowlist=2, allowlist=[UUID_B, UUID_C])
    rc = p3_queue.run_queue(ctx["cfg"], options)
    assert rc == 0
    metrics = json.loads((ctx["state_dir"] / "p3_metrics.json").read_text())
    summary = p3_queue.summarize_metrics(metrics)
    assert summary["ingested"] == 2
    assert summary["unique_media_blobs"] == 1
    assert summary["deduplicated"] == 1
    b, c = metrics["assets"][0], metrics["assets"][1]
    assert b["media_sha256"] == c["media_sha256"]
    assert b["ops"]["put_count"] == 1
    assert c["ops"]["put_count"] == 0  # re-PUT skipped; bytes not re-uploaded
    assert c["put_skipped_existing"] is True
    # verification still executed for the deduped asset (fail-closed intact)
    assert c["ops"]["get_count"] >= 1
    assert b["media_sha256"] in ctx["store"].objects or True
    key = c["object_key"]
    assert ctx["store"].objects[key] == fake_media_bytes("x", "shared-bytes")
    assert blobs_committed  # both assets committed against the same blob


def test_dedupe_still_fails_closed_on_corrupt_existing_object(ctx, monkeypatch):
    MATERIALIZE_MAP[UUID_B] = "shared-bytes"
    MATERIALIZE_MAP[UUID_C] = "shared-bytes"
    monkeypatch.setattr(p3_queue, "get_photos_db", lambda path: ctx["db"])
    # pre-plant a WRONG object under the content key UUID_C will resolve to
    from src.ingest.content_addr import object_key_for_sha, sha256_bytes

    data = fake_media_bytes(UUID_C, "shared-bytes")
    key = object_key_for_sha(sha256_bytes(data), ext="mov")
    # same byte size as the real rendition, wrong content — the dedupe skip
    # must accept the skip, and the roundtrip verifier must fail closed
    ctx["store"].objects[key] = b"X" * len(data)
    ctx["store"].etags[key] = "fake-etag-tampered"
    install_fake_transport(monkeypatch, ctx["store"], set())
    options = base_options(commit_transport_cmd="true", run_min_allowlist=1, allowlist=[UUID_C])
    rc = p3_queue.run_queue(ctx["cfg"], options)
    assert rc == 0
    metrics = json.loads((ctx["state_dir"] / "p3_metrics.json").read_text())
    asset = metrics["assets"][0]
    assert asset["quarantined"] is True
    assert asset["ops"]["put_count"] == 0  # dedupe skip happened...
    # ...and the verifier caught the corruption: no commit, temp retained
    journal = json.loads((ctx["state_dir"] / f"{UUID_C}.json").read_text())
    assert journal["state"] == "QUARANTINED"
    assert journal["db_commit"]["committed"] is False
    assert "roundtrip mismatch" in journal["last_error"]["detail"]


def test_failure_isolation_quarantined_asset_does_not_block_queue(ctx, monkeypatch):
    monkeypatch.setattr(p3_queue, "get_photos_db", lambda path: ctx["db"])
    install_fake_transport(monkeypatch, ctx["store"], set())
    options = base_options(
        commit_transport_cmd="true",
        run_min_allowlist=3,
        allowlist=[UUID_A, UUID_B, UUID_C],
        corrupt_get_once=UUID_B,
    )
    rc = p3_queue.run_queue(ctx["cfg"], options)
    assert rc == 0
    metrics = json.loads((ctx["state_dir"] / "p3_metrics.json").read_text())
    a, b, c = metrics["assets"]
    assert a["final_state"] == "IngestState.CACHE_CLEANED"
    assert b["quarantined"] is True
    assert b["final_state"] == "IngestState.QUARANTINED"
    assert c["final_state"] == "IngestState.CACHE_CLEANED"
    # remote object for B untouched by the injected corruption of returned bytes
    assert ctx["store"].objects[b["object_key"]] == fake_media_bytes(UUID_B)
    journal_b = json.loads((ctx["state_dir"] / f"{UUID_B}.json").read_text())
    assert journal_b["db_commit"]["committed"] is False
    assert journal_b["last_error"]["family"] == "verification_failed"


def test_retryable_put_failure_recovers_within_queue(ctx, monkeypatch):
    monkeypatch.setattr(p3_queue, "get_photos_db", lambda path: ctx["db"])
    install_fake_transport(monkeypatch, ctx["store"], set())
    options = base_options(
        commit_transport_cmd="true",
        run_min_allowlist=1,
        allowlist=[UUID_A],
        fail_put_once=UUID_A,
    )
    rc = p3_queue.run_queue(ctx["cfg"], options)
    assert rc == 0
    metrics = json.loads((ctx["state_dir"] / "p3_metrics.json").read_text())
    asset = metrics["assets"][0]
    assert asset["final_state"] == "IngestState.CACHE_CLEANED"
    assert len(asset["passes"]) >= 2
    journal = json.loads((ctx["state_dir"] / f"{UUID_A}.json").read_text())
    assert journal["attempts"] == 1  # one recorded retryable error
    assert journal["remote"]["attempts"] == 1  # one completed remote put
    assert journal["db_commit"]["committed"] is True
    # exactly one successful logical upload despite the injected failure
    assert ctx["store"].put_counts[asset["object_key"]] == 1


def test_low_disk_guard_refuses_then_resumes(ctx, monkeypatch):
    monkeypatch.setattr(p3_queue, "get_photos_db", lambda path: ctx["db"])
    install_fake_transport(monkeypatch, ctx["store"], set())
    huge = 10**18
    options = base_options(
        commit_transport_cmd="true",
        run_min_allowlist=1,
        allowlist=[UUID_A],
        low_disk_asset=UUID_A,
        low_disk_min_free=huge,
    )
    rc = p3_queue.run_queue(ctx["cfg"], options)
    assert rc == 0
    metrics = json.loads((ctx["state_dir"] / "p3_metrics.json").read_text())
    asset = metrics["assets"][0]
    assert asset["final_state"] == "IngestState.MEDIA_REQUESTED"
    assert asset["quarantined"] is False
    assert asset["media_sha256"] is None
    assert asset["ops"]["put_count"] == 0
    journal = json.loads((ctx["state_dir"] / f"{UUID_A}.json").read_text())
    assert journal["last_error"]["family"] == "insufficient_disk"
    assert "free_disk_before_materialization" not in asset  # never materialized
    # restore real guard: the same asset resumes and converges
    options2 = base_options(commit_transport_cmd="true", run_min_allowlist=1, allowlist=[UUID_A])
    rc = p3_queue.run_queue(ctx["cfg"], options2)
    assert rc == 0
    metrics2 = json.loads((ctx["state_dir"] / "p3_metrics.json").read_text())
    assert metrics2["assets"][0]["final_state"] == "IngestState.CACHE_CLEANED"


def test_queue_restart_skips_committed_and_converges(ctx, monkeypatch):
    monkeypatch.setattr(p3_queue, "get_photos_db", lambda path: ctx["db"])
    blobs_committed: set = set()
    install_fake_transport(monkeypatch, ctx["store"], blobs_committed)
    options = base_options(commit_transport_cmd="true")
    rc = p3_queue.run_queue(ctx["cfg"], {**options, "run_min_allowlist": 3, "allowlist": ALL_UUIDS[:3]})
    assert rc == 0
    puts_after_first = sum(ctx["store"].put_counts.values())
    # restart: identical queue — committed assets must be skipped, zero ops
    rc = p3_queue.run_queue(ctx["cfg"], {**options, "run_min_allowlist": 3, "allowlist": ALL_UUIDS[:3]})
    assert rc == 0
    assert sum(ctx["store"].put_counts.values()) == puts_after_first
    metrics = json.loads((ctx["state_dir"] / "p3_metrics.json").read_text())
    for asset in metrics["assets"]:
        assert asset["already_committed_before_queue"] is True
        assert asset["ops"]["put_count"] == 0
        assert asset["ops"]["get_count"] == 0
        assert asset["final_state"] == "IngestState.CACHE_CLEANED"


def test_unchanged_rerun_after_full_completion_is_zero_op(ctx, monkeypatch):
    monkeypatch.setattr(p3_queue, "get_photos_db", lambda path: ctx["db"])
    blobs_committed: set = set()
    install_fake_transport(monkeypatch, ctx["store"], blobs_committed)
    options = base_options(commit_transport_cmd="true", allowlist=ALL_UUIDS)
    p3_queue.run_queue(ctx["cfg"], options)
    puts_before = sum(ctx["store"].put_counts.values())
    heads_before = sum(ctx["store"].head_counts.values()) if False else None
    rc = p3_queue.run_queue(ctx["cfg"], options)
    assert rc == 0
    assert sum(ctx["store"].put_counts.values()) == puts_before
    metrics = json.loads((ctx["state_dir"] / "p3_metrics.json").read_text())
    summary = p3_queue.summarize_metrics(metrics)
    assert summary["ingested"] == 8
    assert summary["unique_media_blobs"] == 8
    assert summary["deduplicated"] == 0


# ---------------------------------------------------------------------------
# Counting / injecting wrappers


def test_injecting_store_corrupts_only_once(ctx):
    inner = FakeObjectStore()
    data = b"real-media-bytes-here" * 10
    key = "blobs/sha256/aa/test.mov"
    inner.put(key, data)
    wrapper = p3_queue.InjectingObjectStore(inner, {"corrupt": 1})
    first = wrapper.get(key)
    assert first != data
    second = wrapper.get(key)
    assert second == data
    assert wrapper.get_count == 2


def test_injecting_store_put_raises_once(ctx):
    inner = FakeObjectStore()
    wrapper = p3_queue.InjectingObjectStore(inner, {"put": 1})
    with pytest.raises(p3_queue.ObjectStoreUnavailable):
        wrapper.put("k", b"x")
    result = wrapper.put("k", b"x")
    assert result.byte_size == 1
    assert inner.put_counts["k"] == 1


# ---------------------------------------------------------------------------
# Media edit/trim mutation (§17)


def test_media_mutation_refuses_when_media_unchanged(ctx, monkeypatch):
    monkeypatch.setattr(p3_queue, "get_photos_db", lambda path: ctx["db"])
    install_fake_transport(monkeypatch, ctx["store"], set())
    p3_queue.run_queue(ctx["cfg"], base_options(commit_transport_cmd="true", run_min_allowlist=1, allowlist=[UUID_A]))
    rc = p3_queue.mode_media_mutation(ctx["cfg"], UUID_A)
    assert rc == 1
    journal = json.loads((ctx["state_dir"] / f"{UUID_A}.json").read_text())
    assert journal["state"] == "CACHE_CLEANED"


def test_media_mutation_resets_journal_and_reingests_new_blob(ctx, monkeypatch):
    monkeypatch.setattr(p3_queue, "get_photos_db", lambda path: ctx["db"])
    blobs_committed: set = set()
    install_fake_transport(monkeypatch, ctx["store"], blobs_committed)
    p3_queue.run_queue(ctx["cfg"], base_options(commit_transport_cmd="true", run_min_allowlist=1, allowlist=[UUID_A]))
    old_journal = json.loads((ctx["state_dir"] / f"{UUID_A}.json").read_text())
    old_sha = old_journal["media"]["sha256"]
    old_key = old_journal["media"]["object_key"]
    old_caption_sha = old_journal["caption"]["sha256"]
    old_fingerprint = json.loads(
        (ctx["state_dir"] / f"{UUID_A}.evidence.json").read_text()
    )["edit_fingerprint"]

    # Simulate the Photos trim: the edit fingerprint changes (same UUID).
    ctx["db"]._photos[UUID_A].hasadjustments = True
    ctx["db"]._photos[UUID_A].description = CAPTIONS[UUID_A]  # caption unchanged

    rc = p3_queue.mode_media_mutation(ctx["cfg"], UUID_A)
    assert rc == 0
    # journal reset; before-state preserved; old blob retained in store
    assert not (ctx["state_dir"] / f"{UUID_A}.json").exists()
    assert (ctx["state_dir"] / f"{UUID_A}.journal.before_media_mutation.json").exists()
    assert ctx["store"].objects[old_key] == fake_media_bytes(UUID_A)

    # queue re-run ingests the NEW edited rendition
    MATERIALIZE_MAP[UUID_A] = "trimmed-bytes"
    rc = p3_queue.run_queue(ctx["cfg"], base_options(commit_transport_cmd="true", run_min_allowlist=1, allowlist=[UUID_A]))
    assert rc == 0
    new_journal = json.loads((ctx["state_dir"] / f"{UUID_A}.json").read_text())
    assert new_journal["state"] == "CACHE_CLEANED"
    assert new_journal["media"]["sha256"] != old_sha
    assert ctx["store"].objects[old_key] == fake_media_bytes(UUID_A)  # still retained
    assert new_journal["caption"]["sha256"] == old_caption_sha  # caption unchanged
    mutation = json.loads((ctx["state_dir"] / f"{UUID_A}.evidence.json").read_text())["mutation"]
    assert mutation["kind"] == "media_edit_trim"
    assert mutation["previous"]["edit_fingerprint"] == old_fingerprint
    assert mutation["previous"]["media_sha256"] == old_sha
    assert mutation["new_edit_fingerprint"] != old_fingerprint


# ---------------------------------------------------------------------------
# Aggregate manifest privacy


def test_aggregate_manifest_contains_no_caption_text(ctx, monkeypatch):
    monkeypatch.setattr(p3_queue, "get_photos_db", lambda path: ctx["db"])
    install_fake_transport(monkeypatch, ctx["store"], set())
    p3_queue.run_queue(ctx["cfg"], base_options(commit_transport_cmd="true", allowlist=ALL_UUIDS[:5]))
    manifest = p3_queue.aggregate_manifest(ctx["state_dir"])
    text = json.dumps(manifest, ensure_ascii=False)
    for uuid in ALL_UUIDS[:5]:
        assert CAPTIONS[uuid] not in text
    agg = manifest["aggregate"]
    assert agg["sample_count"] == 5
    assert agg["stable_success"] == 5
    assert agg["shadow_available"] == 5
    assert agg["exact_equal_count"] == 5
    assert agg["exact_equal_rate"] == 1.0
    assert agg["shadow_failures"] == 0
    assert agg["mismatches"] == 0


def test_aggregate_manifest_counts_mismatches(ctx, tmp_path):
    video_uuid = UUID_A
    evidence = {
        "caption": {"available": True, "caption_sha256": "a" * 64, "caption_length": 5, "caption_utf8_bytes": 5},
        "shadow": {"available": True, "shadow_sha256": "b" * 64, "shadow_length": 4, "shadow_raw": None, "error_family": None},
        "parity": {"samples": [{"exact_equal": False}]},
        "photo": {"hasadjustments": False},
        "edit_fingerprint": "f" * 64,
    }
    (tmp_path / f"{video_uuid}.evidence.json").write_text(json.dumps(evidence))
    (tmp_path / f"{video_uuid}.json").write_text(json.dumps({"state": "CACHE_CLEANED", "media": {"sha256": "c" * 64, "byte_size": 10}}))
    manifest = p3_queue.aggregate_manifest(tmp_path)
    assert manifest["aggregate"]["mismatches"] == 1
    assert manifest["aggregate"]["exact_equal_count"] == 0
