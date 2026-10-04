"""P9-B natural-ingest evidence tests (packet
MEDIA_BACKBONE_P9_PRODUCTION_READINESS_AND_EXTERNAL_ACCESS_V1 §4/§6/§43).

Offline (FakeObjectStore + fake PhotosDB, no credentials, no network):
- stage metadata durably records the trigger provenance ONCE (first trigger
  wins; never clobbered by later staging events)
- every dual-write run's metrics snapshot carries the trigger provenance and
  (when a commit receipt exists) the durable server-side identity summary
- the observation record composes stage/journal/evidence/receipt/metrics into
  one privacy-safe JSON (NO raw caption text anywhere in the record)
- the completeness gate covers: exact request reason, trigger timestamp,
  legacy success (no staging refusal), legacy-byte reuse, zero extra Photos
  materializations, media SHA, PROD location commit, terminal journal state
- CLI: --latest composes the newest evidence; exit 3 when nothing observed
- read-only: composition never mutates the underlying artifacts
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
from src.ingest.natural_ingest_evidence import (
    build_natural_ingest_evidence,
    capture,
    is_natural_ingest_complete,
    latest_video_uuid,
    main as evidence_main,
)
from src.ingest.objectstore.fake import FakeObjectStore

UUID_A = "11111111-1111-1111-1111-111111111111"
UUID_B = "22222222-2222-2222-2222-222222222222"
UUID_NOT_STAGED = "33333333-3333-3333-3333-333333333333"
TRIGGER = "new_captioned_ingestion"
OTHER_REASON = "catalog_population"
MEDIA_BYTES = b"p9-natural-ingest-bytes"

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

CAPTION_RAW = "107B | 7.5 | H:3 | p9-observation"


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
    """Shadow provider fake (mirrors the P4 harness)."""

    name = "fake_shadow"
    provider = "fake_shadow"
    provider_kind = "fake"

    def __init__(self, library_path=None, db=None):
        self.db = db

    def get_caption(self, video_uuid: str) -> CaptionResult:
        raw = self.db.photos(uuid=[video_uuid])[0].description
        return CaptionResult(
            self.name, True, raw, caption_sha256(raw), None,
            provider_kind=self.provider_kind,
        )


@pytest.fixture()
def env(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    temp_root = tmp_path / "tmp"
    state_dir.mkdir()
    temp_root.mkdir()

    photo = FakePhoto(UUID_A, CAPTION_RAW)
    db = FakeDb([photo])

    monkeypatch.setattr(dual_write, "get_photos_db", lambda path: db)
    monkeypatch.setattr(canary_module, "get_photos_db", lambda path: db)
    monkeypatch.setattr(
        dual_write, "ffprobe_metadata", lambda path, ffprobe_bin: dict(FFPROBE_FAKE)
    )

    def fake_build_stable_provider(library_path):
        def describe(video_uuid):
            matches = db.photos(uuid=[video_uuid])
            return matches[0].description if matches else None

        return CurrentStableCaptionProvider(describe)

    monkeypatch.setattr(canary_module, "build_stable_provider", fake_build_stable_provider)
    monkeypatch.setattr(
        dual_write, "PhotosDbCaptionProviderShadow", lambda library_path: FakeShadow(db=db)
    )

    fake_store = FakeObjectStore()
    monkeypatch.setattr(dual_write, "BackblazeB2Store", lambda config: fake_store)

    def fake_post_commit(self, document, receipt_path):
        payload = document["payload"]
        result = {
            "video_uuid": payload["video_uuid"],
            "environment": "prod",
            "blob_sha256": payload["blob"]["sha256"],
            "blob_existed": False,
            "media_blob_location_id": 42,
            "blob_location_existed": False,
            "media_revision_id": 7,
            "media_revision_existed": False,
            "caption_revision_id": 9,
            "caption_revision_existed": False,
            "ingest_state_id": 11,
        }
        receipt = {"input": document, "result": result, "transport": "fake"}
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        return result

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
            continuous_new_ingest=True,
            trigger_reason=TRIGGER,
            allowlist=[UUID_A, UUID_B],
            commit_endpoint_path="/api/v1/media/backbone/commit",
            commit_timeout_seconds=30,
            env_file="",
            fail_put_once=False,
            fail_commit_once=False,
        ),
    )
    return SimpleNamespace(
        config=config, state_dir=state_dir, temp_root=temp_root, db=db, photo=photo
    )


def make_media_file(temp_root: Path, name="source.mov") -> Path:
    path = temp_root / name
    path.write_bytes(MEDIA_BYTES)
    return path


def build_pdw(env) -> dual_write.ProductionDualWrite:
    return dual_write.ProductionDualWrite.from_config(env.config)


# ---------------------------------------------------------------------------
# Stage metadata trigger provenance (P9-B §6)


def test_stage_meta_records_trigger_provenance(env):
    pdw = build_pdw(env)
    source = make_media_file(env.temp_root)
    staged = pdw.stage_copy(UUID_A, source, TRIGGER)
    assert staged is not None
    meta = json.loads((env.state_dir / f"{UUID_A}.stage.json").read_text())
    assert meta["request_reason"] == TRIGGER
    assert meta["activation"] == "continuous"
    assert meta["triggered_at"]
    assert meta["staged_bytes"] == len(MEDIA_BYTES)


def test_stage_meta_first_trigger_wins_and_activation_allowlist(env):
    pdw = build_pdw(env)
    source = make_media_file(env.temp_root)
    # A refused (backpressure) trigger records skip metadata; a later
    # successful staging must NOT clobber the original trigger timestamp.
    first = pdw.stage_copy(UUID_A, source, TRIGGER)
    meta1 = json.loads((env.state_dir / f"{UUID_A}.stage.json").read_text())
    triggered_at = meta1["triggered_at"]
    assert first is not None
    # second asset via a fresh instance (the backpressure slot is per
    # instance): non-continuous reason -> allowlist activation
    pdw_allow = build_pdw(env)
    second = pdw_allow.stage_copy(
        UUID_B, make_media_file(env.temp_root, "b.mov"), OTHER_REASON
    )
    assert second is not None
    meta2 = json.loads((env.state_dir / f"{UUID_B}.stage.json").read_text())
    assert meta2["activation"] == "allowlist"
    assert meta2["request_reason"] == OTHER_REASON
    # re-drive the first asset (terminal journal -> staging returns None but
    # must not erase trigger provenance)
    pdw2 = build_pdw(env)
    pdw2.stage_copy(UUID_A, source, TRIGGER)
    meta1b = json.loads((env.state_dir / f"{UUID_A}.stage.json").read_text())
    assert meta1b["triggered_at"] == triggered_at


# ---------------------------------------------------------------------------
# Metrics snapshots carry trigger + commit identity


def _latest_metrics(env) -> dict:
    files = sorted((env.state_dir / "metrics").glob("*.json"))
    assert files
    return json.loads(files[-1].read_text())


def test_drive_metrics_include_trigger_and_commit(env):
    pdw = build_pdw(env)
    staged = pdw.stage_copy(UUID_A, make_media_file(env.temp_root), TRIGGER)
    pdw._drive(UUID_A, staged)
    snapshot = _latest_metrics(env)
    assert snapshot["trigger"]["request_reason"] == TRIGGER
    assert snapshot["trigger"]["activation"] == "continuous"
    assert snapshot["trigger"]["triggered_at"]
    commit = snapshot["commit"]
    assert commit["environment"] == "prod"
    assert commit["media_blob_location_id"] == 42
    assert commit["media_revision_id"] == 7
    assert commit["blob_sha256"] == snapshot["media_sha256"] == sha256_bytes(MEDIA_BYTES)
    assert snapshot["result"] == "verified_committed"


# ---------------------------------------------------------------------------
# Observation record composition + privacy


def test_record_composition_and_privacy(env):
    pdw = build_pdw(env)
    staged = pdw.stage_copy(UUID_A, make_media_file(env.temp_root), TRIGGER)
    pdw._drive(UUID_A, staged)
    record = build_natural_ingest_evidence(env.state_dir, UUID_A)
    complete, missing = is_natural_ingest_complete(record)
    assert complete, missing
    dumped = json.dumps(record)
    assert CAPTION_RAW not in dumped
    assert "caption_raw" not in dumped
    assert record["trigger"]["request_reason"] == TRIGGER
    assert record["commit"]["media_blob_location_id"] == 42
    assert record["media"]["sha256"] == sha256_bytes(MEDIA_BYTES)
    assert record["dual_write"]["extra_photos_materializations"] == 0
    assert record["dual_write"]["reused_legacy_bytes"] is True
    assert record["playback"]["prod_location_committed"] is True
    assert record["caption_summary"]["caption_sha256"]
    assert record["caption_summary"]["provider"]


def test_record_is_read_only_and_persisted_0600(env):
    pdw = build_pdw(env)
    staged = pdw.stage_copy(UUID_A, make_media_file(env.temp_root), TRIGGER)
    pdw._drive(UUID_A, staged)
    before = {
        "journal": (env.state_dir / f"{UUID_A}.json").read_text(),
        "stage": (env.state_dir / f"{UUID_A}.stage.json").read_text(),
    }
    path, record = capture(env.state_dir, UUID_A)
    assert (env.state_dir / f"{UUID_A}.json").read_text() == before["journal"]
    assert (env.state_dir / f"{UUID_A}.stage.json").read_text() == before["stage"]
    mode = path.stat().st_mode & 0o777
    assert mode == 0o600
    persisted = json.loads(path.read_text())
    assert persisted["complete"] is True
    assert persisted["video_uuid"] == UUID_A


def test_gate_refuses_incomplete_record(tmp_path):
    record = build_natural_ingest_evidence(tmp_path, UUID_NOT_STAGED)
    complete, missing = is_natural_ingest_complete(record)
    assert not complete
    assert "request_reason=new_captioned_ingestion" in missing
    assert "media sha" in missing
    assert "PROD location commit" in missing


def test_staging_refusal_blocks_gate(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    stage = state_dir / f"{UUID_A}.stage.json"
    stage.write_text(
        json.dumps(
            {
                "triggered_at": "2026-09-10T00:00:00Z",
                "request_reason": TRIGGER,
                "activation": "continuous",
                "staging_refused": True,
                "skip_reason": "insufficient_disk_for_staging",
            }
        ),
        encoding="utf-8",
    )
    record = build_natural_ingest_evidence(state_dir, UUID_A)
    complete, missing = is_natural_ingest_complete(record)
    assert not complete
    assert any("legacy succeeded" in m for m in missing)


def test_latest_video_uuid_and_cli(env):
    pdw = build_pdw(env)
    staged = pdw.stage_copy(UUID_A, make_media_file(env.temp_root), TRIGGER)
    pdw._drive(UUID_A, staged)
    assert latest_video_uuid(env.state_dir) == UUID_A
    rc = evidence_main(["--state-dir", str(env.state_dir), "--latest"])
    assert rc == 0
    with pytest.raises(SystemExit):
        evidence_main(["--state-dir", str(env.state_dir)])  # neither uuid nor --latest
    # an empty state dir reports "nothing observed yet" (exit 3)
    empty = env.temp_root / "empty-state"
    empty.mkdir()
    rc3 = evidence_main(["--state-dir", str(empty), "--latest"])
    assert rc3 == 3


def test_no_caption_content_in_cli_output(env, capsys):
    pdw = build_pdw(env)
    staged = pdw.stage_copy(UUID_A, make_media_file(env.temp_root), TRIGGER)
    pdw._drive(UUID_A, staged)
    evidence_main(["--state-dir", str(env.state_dir), "--latest"])
    out = capsys.readouterr().out
    assert CAPTION_RAW not in out
