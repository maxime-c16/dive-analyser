"""Canonical-vs-local identity split for the production dual-write leg.

Regression coverage for the dive-2991 precedent: a Mac agent whose Photos
library carries its own asset identity (agent_local_uuid) must register the
CANONICAL dive UUID server-side (MediaRevision identity), while Photos-bound
reads (evidence capture, caption providers) stay on the agent-local UUID.
A bare canonical substitution would break local Photos lookups; passing the
local UUID as the durable identity orphans the revision under an identity no
dive references.
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
from src.ingest.errors import ObjectStoreUnavailable
from src.ingest.objectstore.fake import FakeObjectStore

CANON = "7BFB4DF6-AE38-4E75-BFC3-1A8AA6F8481A"
LOCAL = "CBE6CF91-9EEA-43BE-ACF4-1A089BB2E8E0"
TRIGGER = "new_captioned_ingestion"
MEDIA_BYTES = b"canonical-identity-media-bytes"

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

CAPTION = "2991 | 12.5 | H:2 | canonical-identity"


class FakePhoto:
    def __init__(self, uuid):
        self.uuid = uuid
        self.original_filename = "IMG_2991.mov"
        self.description = CAPTION
        self.ismovie = True
        self.hasadjustments = True
        self.ismissing = False
        self.incloud = False
        self.favorite = False
        self.date = None
        self.duration = 9.288


class FakeDb:
    """Photos library containing ONLY the agent-local asset.

    The canonical dive UUID deliberately does NOT resolve here — mirroring
    production, where the agent's Photos identity differs from the dive's.
    """

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


@pytest.fixture()
def env(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    temp_root = tmp_path / "tmp"
    state_dir.mkdir()
    temp_root.mkdir()

    db = FakeDb([FakePhoto(LOCAL)])

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
    monkeypatch.setattr(dual_write, "BackblazeB2Store", lambda config: FakeObjectStore())

    commit_calls: list[dict] = []

    def fake_post_commit(self, document, receipt_path):
        commit_calls.append(document["payload"])
        result = {
            "video_uuid": document["payload"]["video_uuid"],
            "blob_sha256": document["payload"]["blob"]["sha256"],
            "media_revision_id": 2951,
            "media_revision_existed": False,
            "caption_revision_id": 1,
            "caption_revision_existed": False,
            "ingest_state_id": 1,
        }
        receipt_path.write_text(json.dumps({"input": document, "result": result}))
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
            allowlist=[],
            commit_endpoint_path="/api/v1/media/backbone/commit",
            commit_timeout_seconds=30,
            env_file="",
            fail_put_once=False,
            fail_commit_once=False,
        ),
    )
    return SimpleNamespace(
        config=config, state_dir=state_dir, temp_root=temp_root, commit_calls=commit_calls
    )


def make_media_file(temp_root: Path) -> Path:
    path = temp_root / "source.mov"
    path.write_bytes(MEDIA_BYTES)
    return path


def test_split_identity_drive_commits_canonical(env):
    """Full drive with distinct identities: canonical commit, local reads."""
    pdw = dual_write.ProductionDualWrite.from_config(env.config)
    source = make_media_file(env.temp_root)
    staged = pdw.stage_copy(CANON, source, TRIGGER, agent_local_uuid=LOCAL)
    assert staged is not None and staged.is_file()

    pdw._drive(CANON, staged, LOCAL)

    # The server-side commit carries the CANONICAL dive UUID — never local.
    assert len(env.commit_calls) == 1
    payload = env.commit_calls[0]
    assert payload["video_uuid"] == CANON
    assert payload["blob"]["sha256"] == sha256_bytes(MEDIA_BYTES)

    # Durable agent state is keyed canonical; no local-keyed journal exists.
    journal = json.loads((env.state_dir / f"{CANON}.json").read_text())
    assert journal["state"] == "CACHE_CLEANED"
    assert not (env.state_dir / f"{LOCAL}.json").exists()
    assert not (env.state_dir / f"{LOCAL}.evidence.json").exists()

    # Evidence was read from the LOCAL Photos asset under the canonical file.
    evidence = json.loads((env.state_dir / f"{CANON}.evidence.json").read_text())
    assert evidence["photo"]["uuid"] == LOCAL
    assert evidence["caption"]["caption_raw"] == CAPTION


def test_canonical_alone_cannot_read_photos(env):
    """Naive canonical-only substitution breaks: Photos has no such asset."""
    pdw = dual_write.ProductionDualWrite.from_config(env.config)
    source = make_media_file(env.temp_root)
    staged = pdw.stage_copy(CANON, source, TRIGGER)
    assert staged is not None
    with pytest.raises(ObjectStoreUnavailable, match="asset not found"):
        pdw._drive(CANON, staged)
    assert env.commit_calls == []


def test_stage_meta_pins_local_uuid_for_redrive(env):
    """A re-drive without an explicit local UUID reuses the pinned identity."""
    pdw = dual_write.ProductionDualWrite.from_config(env.config)
    source = make_media_file(env.temp_root)
    staged = pdw.stage_copy(CANON, source, TRIGGER, agent_local_uuid=LOCAL)
    assert staged is not None
    meta = pdw._read_stage_meta(CANON)
    assert meta["agent_local_uuid"] == LOCAL

    # No explicit local UUID here: the driver falls back to the stage meta.
    pdw._drive(CANON, staged)
    assert len(env.commit_calls) == 1
    assert env.commit_calls[0]["video_uuid"] == CANON


def test_canary_allowlist_accepts_either_identity(tmp_path, monkeypatch):
    """Canary/debug mode: the allowlist names assets, so either identity may
    satisfy it — but the durable key stays canonical."""
    cohort = [
        LOCAL,
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
        "33333333-3333-3333-3333-333333333333",
        "44444444-4444-4444-4444-444444444444",
    ]
    state_dir = tmp_path / "state"
    temp_root = tmp_path / "tmp"
    config = SimpleNamespace(
        server=SimpleNamespace(url="https://b", api_key="x" * 48, ca_cert_path=""),
        photos=SimpleNamespace(library_path="/tmp/fake-library"),
        media=SimpleNamespace(ffprobe_path="ffprobe-fake"),
        object_store=SimpleNamespace(
            enabled=True, environment="prod", bucket="b", region="r",
            endpoint_url="e", prefix="p", state_dir=str(state_dir),
            temp_root=str(temp_root), min_free_disk_bytes=0,
            presign_ttl_seconds=300, max_retries=3, storage_backend="b2",
        ),
        dual_write=SimpleNamespace(
            enabled=True, continuous_new_ingest=False, trigger_reason=TRIGGER,
            allowlist=list(cohort), commit_endpoint_path="/x",
            commit_timeout_seconds=30, env_file="", fail_put_once=False,
            fail_commit_once=False,
        ),
    )
    pdw = dual_write.ProductionDualWrite.from_config(config)
    assert pdw.should_process(CANON, None, LOCAL) is True  # via local membership
    assert pdw.should_process(CANON, None) is False  # canonical alone not listed
    assert pdw.should_process(LOCAL, None) is True
    assert pdw.should_process(CANON, None, "99999999-9999-9999-9999-999999999999") is False


def test_single_identity_behavior_unchanged(env):
    """When both identities are equal, behavior matches the legacy path."""
    pdw = dual_write.ProductionDualWrite.from_config(env.config)
    db_uuid = LOCAL
    source = make_media_file(env.temp_root)
    staged = pdw.stage_copy(db_uuid, source, TRIGGER)
    assert staged is not None
    pdw._drive(db_uuid, staged)
    assert len(env.commit_calls) == 1
    assert env.commit_calls[0]["video_uuid"] == db_uuid
