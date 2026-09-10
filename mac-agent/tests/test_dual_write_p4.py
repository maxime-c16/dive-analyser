"""P4 production dual-write tests: allowlist guard, feature flags, one-
materialization rule, failure isolation (B2 + backend commit), idempotent
re-drive, lost-response retry convergence, metrics snapshot immutability,
caption-only mutation — all offline (FakeObjectStore + fake PhotosDB),
no credentials, no network.

P4.2 additions (MEDIA_BACKBONE_P4_2_PRODUCTION_COHORT_V1): bounded cohort
allowlist guard (5-10 explicit UUIDs, REFUSE TO ARM outside), backpressure
pending marker (no staged byte accumulation), static no-delete/hide
firewall over the ingestion path.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.ingest.canary as canary_module
import src.ingest.dual_write as dual_write
from src.ingest.caption import CaptionResult, CurrentStableCaptionProvider, caption_sha256
from src.ingest.content_addr import sha256_bytes
from src.ingest.objectstore.fake import FakeObjectStore
from src.ingest.state_store import IngestStateStore
from src.ingest.states import IngestState

UUID_A = "11111111-1111-1111-1111-111111111111"
UUID_B = "22222222-2222-2222-2222-222222222222"  # NOT allowlisted
UUID_C = "33333333-3333-3333-3333-333333333333"
UUID_D = "44444444-4444-4444-4444-444444444444"
UUID_E = "55555555-5555-5555-5555-555555555555"
UUID_F = "66666666-6666-6666-6666-666666666666"
UUID_G = "77777777-7777-7777-7777-777777777777"
UUID_H = "88888888-8888-8888-8888-888888888888"
UUID_I = "99999999-9999-9999-9999-999999999999"
UUID_MALFORMED = "not-a-uuid"
# P4.2 cohort shape: 8 explicit UUIDs (target = 8, bounds [5, 10])
COHORT_8 = [UUID_A, UUID_C, UUID_D, UUID_E, UUID_F, UUID_G, UUID_H, UUID_I]
COHORT_5 = COHORT_8[:5]
COHORT_4 = COHORT_8[:4]
COHORT_11 = COHORT_8 + [UUID_B] + [
    "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA",
    "BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB",
]
MEDIA_BYTES = b"p4-canary-media-bytes"

FFPROBE_FAKE = {
    "codec": "hevc",
    "width": 1920,
    "height": 1080,
    "duration_seconds": 9.288,
    "container": "mov",
    "bit_rate": 16000000,
    "start_pts": 0,
    "start_time": "0",
    "nb_frames": "580",
}


class FakePhoto:
    def __init__(self, uuid, description, hasadjustments=True, ismissing=False, incloud=False):
        self.uuid = uuid
        self.original_filename = "IMG_9999.mov"
        self.description = description
        self.ismovie = True
        self.hasadjustments = hasadjustments
        self.ismissing = ismissing
        self.incloud = incloud
        self.favorite = False
        self.date = None
        self.duration = 9.288


class FakeDb:
    def __init__(self, photos):
        self._photos = {p.uuid: p for p in photos}

    def photos(self, uuid=None):
        if uuid is None:
            return list(self._photos.values())
        return [self._photos[u] for u in uuid if u in self._photos]


class FakeShadow:
    name = "fake_shadow"
    provider = "fake_shadow"
    provider_kind = "fake"

    def __init__(self, library_path=None, db=None):
        self.db = db

    def get_caption(self, video_uuid: str) -> CaptionResult:
        raw = self.db.photos(uuid=[video_uuid])[0].description
        return CaptionResult(
            self.name, True, raw, caption_sha256(raw), None, provider_kind=self.provider_kind
        )


CAPTION_INITIAL = "107B | 7.5 | H:3 | p4-canary"
CAPTION_MUTATED = "107B | 7.5 | H:3 | p4-canary | note:revised"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    temp_root = tmp_path / "tmp"
    state_dir.mkdir()
    temp_root.mkdir()

    photo = FakePhoto(UUID_A, CAPTION_INITIAL)
    db = FakeDb([photo])

    monkeypatch.setattr(dual_write, "get_photos_db", lambda path: db)
    monkeypatch.setattr(canary_module, "get_photos_db", lambda path: db)
    monkeypatch.setattr(
        dual_write,
        "ffprobe_metadata",
        lambda path, ffprobe_bin: dict(FFPROBE_FAKE),
    )

    def fake_build_stable_provider(library_path):
        def describe(video_uuid):
            matches = db.photos(uuid=[video_uuid])
            return matches[0].description if matches else None

        return CurrentStableCaptionProvider(describe)

    monkeypatch.setattr(
        canary_module, "build_stable_provider", fake_build_stable_provider
    )
    monkeypatch.setattr(
        dual_write, "PhotosDbCaptionProviderShadow", lambda library_path: FakeShadow(db=db)
    )

    fake_store = FakeObjectStore()
    monkeypatch.setattr(
        dual_write, "BackblazeB2Store", lambda config: fake_store
    )

    # Fake authenticated commit endpoint: idempotent by payload identity.
    committed: dict[str, dict] = {}
    commit_calls: list[dict] = []

    def fake_post_commit(self, document, receipt_path):
        payload = document["payload"]
        commit_calls.append(payload)
        key = (payload["video_uuid"], payload["blob"]["sha256"], payload["caption"]["sha256"])
        if key not in committed:
            committed[key] = {
                "video_uuid": payload["video_uuid"],
                "blob_sha256": payload["blob"]["sha256"],
                "blob_existed": any(
                    c["blob"]["sha256"] == payload["blob"]["sha256"] for c in commit_calls[:-1]
                ),
                "media_revision_id": 1,
                "media_revision_existed": any(
                    c["blob"]["sha256"] == payload["blob"]["sha256"] for c in commit_calls[:-1]
                ),
                "caption_revision_id": len([k for k in committed if k[0] == key[0]]) + 1,
                "caption_revision_existed": key in committed,
                "ingest_state_id": 1,
            }
        receipt = {"input": document, "result": committed[key], "transport": "fake"}
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        return committed[key]

    monkeypatch.setattr(dual_write.ProductionDualWrite, "_post_commit_document", fake_post_commit)

    config = SimpleNamespace(
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
            min_free_disk_bytes=0,
            presign_ttl_seconds=300,
            max_retries=3,
            storage_backend="b2",
        ),
        dual_write=SimpleNamespace(
            enabled=True,
            allowlist=list(COHORT_8),
            commit_endpoint_path="/api/v1/media/backbone/commit",
            commit_timeout_seconds=30,
            env_file="",
            fail_put_once=False,
            fail_commit_once=False,
        ),
    )

    return SimpleNamespace(
        config=config,
        state_dir=state_dir,
        temp_root=temp_root,
        db=db,
        photo=photo,
        fake_store=fake_store,
        committed=committed,
        commit_calls=commit_calls,
    )


def make_media_file(temp_root: Path, name="source.mov") -> Path:
    path = temp_root / name
    path.write_bytes(MEDIA_BYTES)
    return path


def build_pdw(env) -> dual_write.ProductionDualWrite:
    return dual_write.ProductionDualWrite.from_config(env.config)


# ---------------------------------------------------------------------------
# Allowlist guard + flags (packet §18/§19)


def test_allowlist_guard_counts():
    # REFUSE TO ARM: empty, below minimum, above maximum, duplicates,
    # malformed, non-list
    for bad in (
        [],
        [UUID_A, UUID_B],
        COHORT_4,
        COHORT_11,
        [UUID_A] * 5,
        [UUID_MALFORMED] * 5,
        "single",
    ):
        with pytest.raises(ValueError):
            dual_write.validate_prod_allowlist(list(bad) if isinstance(bad, str) else bad)
    # Authorized: explicit bounded cohort at the boundaries and the target
    dual_write.validate_prod_allowlist(COHORT_5)
    dual_write.validate_prod_allowlist(COHORT_8)
    dual_write.validate_prod_allowlist(
        COHORT_8
        + ["AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"]
        + ["BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB"]
    )  # 10 = max authorized


def test_from_config_requires_both_flags(env):
    env.config.dual_write.enabled = False
    assert dual_write.ProductionDualWrite.from_config(env.config) is None
    env.config.dual_write.enabled = True
    env.config.object_store.enabled = False
    with pytest.raises(ValueError):
        dual_write.ProductionDualWrite.from_config(env.config)
    env.config.object_store.enabled = True
    env.config.object_store.environment = "dev"
    with pytest.raises(ValueError):
        dual_write.ProductionDualWrite.from_config(env.config)
    env.config.object_store.environment = "prod"
    env.config.dual_write.allowlist = [UUID_A, UUID_B]
    with pytest.raises(ValueError):
        dual_write.ProductionDualWrite.from_config(env.config)
    env.config.dual_write.allowlist = list(COHORT_8)
    assert isinstance(dual_write.ProductionDualWrite.from_config(env.config), dual_write.ProductionDualWrite)


def test_config_validate_dual_write_errors(tmp_path):
    from src.config import Config

    config = Config.__new__(Config)
    config.object_store = SimpleNamespace(enabled=False, environment="dev", bucket="", region="", endpoint_url="", prefix="blobs/sha256", state_dir="", temp_root="", min_free_disk_bytes=0, presign_ttl_seconds=300, max_retries=3)
    config.dual_write = SimpleNamespace(
        enabled=True, allowlist=[UUID_A], commit_endpoint_path="", commit_timeout_seconds=30, env_file="", fail_put_once=False, fail_commit_once=False
    )
    with pytest.raises(ValueError) as exc:
        config._validate_dual_write_config()
    assert "object_store.enabled" in str(exc.value)


def test_should_process_gated_by_flags_and_allowlist(env):
    pdw = build_pdw(env)
    assert pdw.should_process(UUID_A) is True
    assert pdw.should_process(UUID_B) is False
    assert pdw.should_process(UUID_MALFORMED) is False
    pdw.config.dual_write.enabled = False
    assert pdw.should_process(UUID_A) is False


# ---------------------------------------------------------------------------
# One-materialization + backpressure (packet §16/§41)


def test_stage_copy_and_materialize_reuses_legacy_bytes(env):
    pdw = build_pdw(env)
    source = make_media_file(env.temp_root)
    staged = pdw.stage_copy(UUID_A, source)
    assert staged is not None
    assert staged.read_bytes() == MEDIA_BYTES

    pdw._drive(UUID_A, staged)
    journal = json.loads((env.state_dir / f"{UUID_A}.json").read_text())
    assert journal["media"]["sha256"] == sha256_bytes(MEDIA_BYTES)
    metrics_files = list((env.state_dir / "metrics").glob("*.json"))
    assert len(metrics_files) == 1
    snapshot = json.loads(metrics_files[0].read_text())
    assert snapshot["staging"]["extra_photos_materializations"] == 0
    assert snapshot["staging"]["reused_legacy_bytes"] is True
    assert snapshot["result"] == "verified_committed"


def test_stage_copy_skips_when_not_allowlisted_or_terminal(env):
    pdw = build_pdw(env)
    source = make_media_file(env.temp_root)
    assert pdw.stage_copy(UUID_B, source) is None
    # backpressure: one active asset blocks a second trigger
    pdw._active.add(UUID_B)
    assert pdw.stage_copy(UUID_A, source) is None
    pdw._active.clear()
    assert pdw.stage_copy(UUID_A, source) is not None


def test_stage_copy_backpressure_records_bounded_pending_marker(env):
    """P4.2 §19: when the single slot is busy the trigger is refused WITHOUT
    staging media bytes; only a tiny bounded pending marker is persisted so
    the asset stays recoverable (one-shot run mode). Staged full-media bytes
    exist for at most ONE asset."""
    pdw = build_pdw(env)
    source = make_media_file(env.temp_root)
    source_b = make_media_file(env.temp_root, "source_b.mov")
    staged_a = pdw.stage_copy(UUID_A, source)  # occupies the slot
    assert staged_a is not None
    assert pdw.stage_copy(UUID_C, source_b) is None  # busy → refused
    marker = env.state_dir / f"{UUID_C}.stage.json"
    assert marker.exists()
    meta = json.loads(marker.read_text())
    assert meta["backpressure_skip"] is True
    assert meta["skip_reason"] == "one_active_materialization_slot_busy"
    # NO staged media bytes for the skipped asset
    staging_c = env.temp_root / "dual_write_staging" / UUID_C
    assert not staging_c.exists()
    # only ONE asset has staged full-media bytes
    staged_dirs = [
        d for d in (env.temp_root / "dual_write_staging").iterdir() if d.is_dir()
    ]
    assert [d.name for d in staged_dirs] == [UUID_A]


# ---------------------------------------------------------------------------
# Happy path + unchanged rerun (packet §31)


def test_full_drive_and_unchanged_rerun(env):
    pdw = build_pdw(env)
    source = make_media_file(env.temp_root)
    staged = pdw.stage_copy(UUID_A, source)
    pdw._drive(UUID_A, staged)
    key = json.loads((env.state_dir / f"{UUID_A}.json").read_text())["media"]["object_key"]
    assert key in env.fake_store.objects
    ops_after_first = dict(env.fake_store.put_counts)
    commits_after_first = list(env.commit_calls)

    # unchanged rerun: stage_copy refuses (journal terminal), re-drive is a
    # no-op, zero new uploads, same remote object, same durable commit
    source2 = make_media_file(env.temp_root, "source2.mov")
    assert pdw.stage_copy(UUID_A, source2) is None
    pdw2 = build_pdw(env)
    pdw2._drive(UUID_A, staged)
    assert env.fake_store.put_counts == ops_after_first
    assert env.commit_calls == commits_after_first
    assert env.fake_store.objects[key] == MEDIA_BYTES


# ---------------------------------------------------------------------------
# B2 failure injection (packet §25)


def test_b2_put_transient_failure_retries_and_converges(env, monkeypatch):
    """First PUT fails retryably; the very next attempt succeeds: exactly one
    remote blob, one logical backbone result, legacy unaffected."""
    monkeypatch.setattr(dual_write, "RETRY_BACKOFF_SECONDS", 0.0)
    pdw = build_pdw(env)
    pdw.config.dual_write.fail_put_once = True
    source = make_media_file(env.temp_root)
    staged = pdw.stage_copy(UUID_A, source)
    pdw._drive(UUID_A, staged)
    journal = json.loads((env.state_dir / f"{UUID_A}.json").read_text())
    assert journal["state"] == "CACHE_CLEANED"
    # exactly ONE remote object stored despite the failed first attempt
    assert sum(env.fake_store.put_counts.values()) == 1
    keys = list(env.fake_store.objects.keys())
    assert len(keys) == 1
    assert env.fake_store.objects[keys[0]] == MEDIA_BYTES
    assert len(env.committed) == 1
    metrics_files = sorted((env.state_dir / "metrics").glob("*.json"))
    snapshot = json.loads(metrics_files[-1].read_text())
    assert snapshot["result"] == "verified_committed"
    assert snapshot["injections"]["fail_put_once"] is True


def test_b2_persistent_failure_isolated_then_recovers(env, monkeypatch):
    """Persistent store outage during the first drive: state stays retryable
    (LEGACY_SUCCESS + OBJECT_STORE_PENDING_RETRY); a later drive converges."""
    pdw = build_pdw(env)
    source = make_media_file(env.temp_root)
    staged = pdw.stage_copy(UUID_A, source)

    outage = {"active": True}
    original_put = FakeObjectStore.put

    def outaged_put(self, key, src, *args, **kwargs):
        if outage["active"]:
            raise dual_write.ObjectStoreUnavailable("simulated B2 outage")
        return original_put(self, key, src, *args, **kwargs)

    monkeypatch.setattr(FakeObjectStore, "put", outaged_put)
    monkeypatch.setattr(dual_write, "RETRY_BACKOFF_SECONDS", 0.0)

    pdw._drive(UUID_A, staged)
    journal = json.loads((env.state_dir / f"{UUID_A}.json").read_text())
    assert journal["state"] != "CACHE_CLEANED"
    assert not env.committed  # nothing committed while unverified
    metrics_files = sorted((env.state_dir / "metrics").glob("*.json"))
    snapshot = json.loads(metrics_files[-1].read_text())
    assert snapshot["result"] == "pending_retry"

    outage["active"] = False
    pdw2 = build_pdw(env)
    pdw2._drive(UUID_A, staged)
    journal = json.loads((env.state_dir / f"{UUID_A}.json").read_text())
    assert journal["state"] == "CACHE_CLEANED"
    keys = list(env.fake_store.objects.keys())
    assert len(keys) == 1
    assert env.fake_store.objects[keys[0]] == MEDIA_BYTES
    assert len(env.committed) == 1


# ---------------------------------------------------------------------------
# Backend commit failure injection (packet §26)


def test_backend_commit_transient_failure_retries_without_duplicates(env, monkeypatch):
    """First commit attempt fails (lost request/response); retry converges
    to the same logical result with zero duplicate rows; legacy unaffected."""
    monkeypatch.setattr(dual_write, "RETRY_BACKOFF_SECONDS", 0.0)
    pdw = build_pdw(env)
    pdw.config.dual_write.fail_commit_once = True
    source = make_media_file(env.temp_root)
    staged = pdw.stage_copy(UUID_A, source)

    original_post = dual_write.ProductionDualWrite._post_commit_document

    def flaky_post(self, document, receipt_path):
        if self.config.dual_write.fail_commit_once:
            self.config.dual_write.fail_commit_once = False
            raise dual_write.ObjectStoreUnavailable(
                "injected first-commit failure (lost response)"
            )
        return original_post(self, document, receipt_path)

    dual_write.ProductionDualWrite._post_commit_document = flaky_post

    try:
        pdw._drive(UUID_A, staged)
    finally:
        dual_write.ProductionDualWrite._post_commit_document = original_post

    journal = json.loads((env.state_dir / f"{UUID_A}.json").read_text())
    assert journal["state"] == "CACHE_CLEANED"
    assert list(env.fake_store.objects.keys()), "B2 object uploaded"
    assert sum(env.fake_store.put_counts.values()) == 1
    assert len(env.committed) == 1  # zero duplicate commits


def test_backend_commit_persistent_failure_keeps_remote_and_recovers(env, monkeypatch):
    """Commit endpoint unreachable for the whole first drive: B2 object is
    RETAINED, journal stays REMOTE_VERIFIED (pending retry), legacy (external)
    unaffected. A later drive converges with zero duplicates."""
    pdw = build_pdw(env)
    source = make_media_file(env.temp_root)
    staged = pdw.stage_copy(UUID_A, source)

    outage = {"active": True}
    original_post = dual_write.ProductionDualWrite._post_commit_document

    def outaged_post(self, document, receipt_path):
        if outage["active"]:
            raise dual_write.ObjectStoreUnavailable("commit endpoint unreachable")
        return original_post(self, document, receipt_path)

    dual_write.ProductionDualWrite._post_commit_document = outaged_post
    monkeypatch.setattr(dual_write, "RETRY_BACKOFF_SECONDS", 0.0)
    try:
        pdw._drive(UUID_A, staged)
    finally:
        dual_write.ProductionDualWrite._post_commit_document = original_post

    journal = json.loads((env.state_dir / f"{UUID_A}.json").read_text())
    assert journal["state"] == "REMOTE_VERIFIED"  # remote object retained
    assert list(env.fake_store.objects.keys())
    assert not env.committed

    pdw2 = build_pdw(env)
    pdw2._drive(UUID_A, staged)
    journal = json.loads((env.state_dir / f"{UUID_A}.json").read_text())
    assert journal["state"] == "CACHE_CLEANED"
    assert sum(env.fake_store.put_counts.values()) == 1
    assert len(env.committed) == 1


# ---------------------------------------------------------------------------
# Metrics snapshot immutability (packet §36)


def test_metrics_snapshots_run_unique_and_immutable(env):
    pdw = build_pdw(env)
    run_id = pdw._new_run_id(UUID_A)
    pdw._write_metrics_snapshot(run_id, {"run_id": run_id, "marker": 1})
    path = pdw._metrics_dir() / f"{run_id}.json"
    before = path.read_bytes()
    with pytest.raises(RuntimeError):
        pdw._write_metrics_snapshot(run_id, {"run_id": run_id, "marker": 2})
    assert path.read_bytes() == before
    run_id2 = pdw._new_run_id(UUID_A)
    assert run_id2 != run_id
    pdw._write_metrics_snapshot(run_id2, {"run_id": run_id2})
    assert len(list(pdw._metrics_dir().glob("*.json"))) == 2


# ---------------------------------------------------------------------------
# Caption-only mutation (packet §32)


def test_caption_only_mutation_zero_upload(env):
    pdw = build_pdw(env)
    source = make_media_file(env.temp_root)
    staged = pdw.stage_copy(UUID_A, source)
    pdw._drive(UUID_A, staged)
    puts_before = dict(env.fake_store.put_counts)
    objects_before = dict(env.fake_store.objects)

    # The user edits ONLY the caption in Photos.
    env.photo.description = CAPTION_MUTATED
    outcome = dual_write.mode_caption_mutation(env.config, UUID_A)
    assert outcome == 0
    # ZERO B2 upload; remote object byte-identical.
    assert env.fake_store.put_counts == puts_before
    assert env.fake_store.objects == objects_before
    # Backbone DB: new caption revision (caption key distinct), same blob.
    journal = json.loads((env.state_dir / f"{UUID_A}.json").read_text())
    blob_sha = journal["media"]["sha256"]
    caption_keys = [k for k in env.committed if k[0] == UUID_A and k[1] == blob_sha]
    assert len(caption_keys) == 2  # two caption revisions, same media blob
    assert {k[2] for k in caption_keys} == {
        caption_sha256(CAPTION_INITIAL),
        caption_sha256(CAPTION_MUTATED),
    }
    # Idempotent: rerunning the mutation is a no-op (unchanged caption now).
    outcome2 = dual_write.mode_caption_mutation(env.config, UUID_A)
    assert outcome2 == 1


def test_caption_mutation_refuses_media_changed(env):
    pdw = build_pdw(env)
    source = make_media_file(env.temp_root)
    staged = pdw.stage_copy(UUID_A, source)
    pdw._drive(UUID_A, staged)
    # Media edit changes BOTH the fingerprint and the caption -> refused.
    env.photo.description = CAPTION_MUTATED
    env.photo.duration = 5.158  # trim changes fingerprint material
    outcome = dual_write.mode_caption_mutation(env.config, UUID_A)
    assert outcome == 2


def test_caption_mutation_refused_when_flags_off(env):
    env.config.dual_write.enabled = False
    assert dual_write.mode_caption_mutation(env.config, UUID_A) == 3


def test_caption_mutation_refused_not_allowlisted(env):
    assert dual_write.mode_caption_mutation(env.config, UUID_B) == 3


# ---------------------------------------------------------------------------
# No-delete / no-hide firewall (P4.2 packet §4/§23) — static invariant

INGEST_PATH_MODULES = [
    "src/ingest/coordinator.py",
    "src/ingest/dual_write.py",
    "src/ingest/states.py",
    "src/ingest/state_store.py",
    "src/ingest/p3_queue.py",
    "src/media_jobs.py",
]

FORBIDDEN_DELETE_TOKENS = [
    "delete_object",
    "DeleteObject",
    "delete_file_version",
    "b2_hide_file",
    "hide_file",
]


def _repo_file(relpath: str) -> Path:
    return Path(__file__).resolve().parents[1] / relpath


def test_no_delete_or_hide_primitives_in_ingestion_path():
    """The ingestion path may only PUT/HEAD/GET/LIST. Every remote destructive
    visibility operation (delete/hide/purge/delete-file-version) is absent
    from every ingest/orchestration module (static invariant)."""
    for relpath in INGEST_PATH_MODULES:
        text = _repo_file(relpath).read_text(encoding="utf-8")
        for token in FORBIDDEN_DELETE_TOKENS:
            assert token not in text, (
                f"{relpath} must not reference {token!r} "
                "(no-delete/hide firewall)"
            )


def test_delete_capability_is_operator_explicit_and_uncalled_by_ingest():
    """The ONLY delete-capable symbol is the intentionally verbose
    `delete_object_explicit_operator_action` on store adapters; it has no
    callers inside the ingest/orchestration path (the single historical
    caller is the canary b2-preflight operator diagnostic, which cleans only
    its own SYNTHETIC probe and is never part of the daemon/ingest loops;
    not invoked in production P2/P3/P4/P4.1/P4.2)."""
    ingest_text = "".join(
        _repo_file(rel).read_text(encoding="utf-8") for rel in INGEST_PATH_MODULES
    )
    assert "delete_object_explicit_operator_action" not in ingest_text

    b2_text = _repo_file("src/ingest/objectstore/b2.py").read_text(encoding="utf-8")
    assert "def delete_object_explicit_operator_action" in b2_text
    # the adapter's delete is documented as non-ingest
    assert "NOT" in b2_text and "ingest" in b2_text


def test_ingest_state_machine_has_no_destructive_transition():
    """The state machine contains no destructive/visibility-removal state:
    the only cleanup transition is CACHE_CLEANED (LOCAL temp bytes, strictly
    after remote verification + DB commit)."""
    destructive = {"DELETE", "HIDE", "PURGE", "REMOVE", "DESTROY"}
    members = {state.name for state in IngestState}
    assert not (members & destructive), "destructive state in ingest machine"
