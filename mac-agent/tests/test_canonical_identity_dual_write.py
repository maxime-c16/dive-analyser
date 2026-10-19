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
LOCAL2 = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"  # valid UUID, absent from Photos
NEW = "BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB"  # valid UUID, added to Photos per-test
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
        config=config, state_dir=state_dir, temp_root=temp_root, commit_calls=commit_calls,
        db=db,
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


# ---------------------------------------------------------------------------
# Retry/identity consistency (round-2 review findings)
#
# Rule: a valid explicit local UUID overrides the pin and persists for future
# retries; an omitted argument retains the pin; malformed values raise a
# typed error before any file/state mutation — never a silent fallback to
# an unrelated canonical Photos lookup.


def test_stage_copy_explicit_correction_overrides_stale_pin(env):
    """A valid explicit local UUID corrects the pin and persists."""
    pdw = dual_write.ProductionDualWrite.from_config(env.config)
    source = make_media_file(env.temp_root)
    staged = pdw.stage_copy(CANON, source, TRIGGER, agent_local_uuid=LOCAL)
    assert staged is not None
    assert pdw._read_stage_meta(CANON)["agent_local_uuid"] == LOCAL
    pdw._release(CANON)

    staged2 = pdw.stage_copy(CANON, source, TRIGGER, agent_local_uuid=LOCAL2)
    assert staged2 is not None
    meta = pdw._read_stage_meta(CANON)
    # Correction persisted; original trigger provenance untouched.
    assert meta["agent_local_uuid"] == LOCAL2
    assert meta["request_reason"] == TRIGGER
    assert meta["activation"] == "continuous"
    assert "triggered_at" in meta
    pdw._release(CANON)


def test_drive_explicit_correction_overrides_pin_and_drives_reads(env):
    """_drive with an explicit local UUID persists it and reads through it.

    LOCAL2 is absent from Photos, so the drive must fail on the LOCAL2
    lookup — proving the explicit identity was actually used for reads and
    persisted, not silently replaced by the stale pin.
    """
    pdw = dual_write.ProductionDualWrite.from_config(env.config)
    source = make_media_file(env.temp_root)
    staged = pdw.stage_copy(CANON, source, TRIGGER, agent_local_uuid=LOCAL)
    assert staged is not None

    with pytest.raises(ObjectStoreUnavailable, match="asset not found"):
        pdw._drive(CANON, staged, LOCAL2)
    assert pdw._read_stage_meta(CANON)["agent_local_uuid"] == LOCAL2
    assert env.commit_calls == []
    pdw._release(CANON)


def test_mode_run_omitted_local_reuses_pin_and_merges_provenance(env, capsys):
    """One-shot retry without --agent-local-uuid reuses the pin and merges."""
    pdw = dual_write.ProductionDualWrite.from_config(env.config)
    source = make_media_file(env.temp_root)
    staged = pdw.stage_copy(CANON, source, TRIGGER, agent_local_uuid=LOCAL)
    assert staged is not None
    meta_before = pdw._read_stage_meta(CANON)
    pdw._release(CANON)

    rc = dual_write.mode_run(env.config, CANON, None, TRIGGER)
    assert rc == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["outcome"] == "driven"

    # Commit under canonical; provenance merged, not replaced.
    assert len(env.commit_calls) == 1
    assert env.commit_calls[0]["video_uuid"] == CANON
    meta_after = pdw._read_stage_meta(CANON)
    assert meta_after["triggered_at"] == meta_before["triggered_at"]
    assert meta_after["request_reason"] == TRIGGER
    assert meta_after["activation"] == "continuous"
    assert meta_after["agent_local_uuid"] == LOCAL
    assert meta_after["run_mode"] == "one_shot_production_runtime"


def test_malformed_explicit_local_rejected_before_mutation(env):
    """Malformed explicit identity: typed error, no files, no lookups."""
    pdw = dual_write.ProductionDualWrite.from_config(env.config)
    source = make_media_file(env.temp_root)
    with pytest.raises(ValueError, match="malformed agent_local_uuid"):
        pdw.stage_copy(CANON, source, TRIGGER, agent_local_uuid="not-a-uuid")
    assert not (env.state_dir / f"{CANON}.stage.json").exists()
    assert not (env.temp_root / "dual_write_staging" / CANON).exists()

    with pytest.raises(ValueError, match="malformed agent_local_uuid"):
        pdw._drive(CANON, env.temp_root / "source.mov", "not-a-uuid")
    assert not (env.state_dir / "metrics").exists()
    assert not (env.state_dir / f"{CANON}.json").exists()
    assert not (env.state_dir / f"{CANON}.evidence.json").exists()


def test_malformed_recorded_pin_rejected_not_silently_ignored(env):
    """A corrupt recorded pin raises instead of falling back to canonical."""
    pdw = dual_write.ProductionDualWrite.from_config(env.config)
    pdw._set_stage_meta(CANON, {"agent_local_uuid": "junk"})
    with pytest.raises(ValueError, match="recorded agent_local_uuid"):
        pdw._drive(CANON, env.temp_root / "source.mov", None)
    assert env.commit_calls == []


def test_mode_run_malformed_local_reports_refused(env, capsys):
    """One-shot with a malformed local UUID: structured refusal, no writes."""
    rc = dual_write.mode_run(env.config, CANON, None, TRIGGER, "bad-uuid")
    assert rc == 3
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["outcome"] == "refused_malformed_agent_local_uuid"
    assert not (env.state_dir / f"{CANON}.evidence.json").exists()
    assert not (env.state_dir / f"{CANON}.stage.json").exists()


def test_mode_run_evidence_failure_reports_structured_outcome(env, capsys):
    """Evidence capture failure: retryable_failure, unexpected errors unmasked."""
    # No local UUID anywhere: the canonical UUID does not resolve in Photos.
    rc = dual_write.mode_run(env.config, CANON, None, TRIGGER)
    assert rc == 1
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["outcome"] == "retryable_failure"
    assert out["stage"] == "evidence_capture"
    assert out["error_family"] == "ObjectStoreUnavailable"
    assert env.commit_calls == []


# ---------------------------------------------------------------------------
# Retry identity/evidence consistency (bot finding on head 43d5620)
#
# A retry with a corrected local UUID must not silently reuse canonical
# evidence captured from the old asset while reads/bytes/commit move to the
# new one. All entry points validate the recorded evidence photo.uuid
# against the resolved identity (case-insensitive): safe recapture when no
# staged bytes or journal progress bind the old evidence, explicit refusal
# otherwise. Terminal journals stay idempotent.


def _stage_and_capture_old(env):
    """Stage + capture evidence under the OLD local identity (non-terminal)."""
    pdw = dual_write.ProductionDualWrite.from_config(env.config)
    source = make_media_file(env.temp_root)
    staged = pdw.stage_copy(CANON, source, TRIGGER, agent_local_uuid=LOCAL)
    assert staged is not None
    pdw._capture_evidence(CANON, LOCAL)
    pdw._release(CANON)
    return pdw, staged


def test_drive_correction_with_existing_evidence_refuses(env):
    """_drive with a corrected UUID refuses: old evidence, no mixing."""
    pdw, staged = _stage_and_capture_old(env)
    with pytest.raises(ValueError, match="evidence identity mismatch"):
        pdw._drive(CANON, staged, LOCAL2)
    assert env.commit_calls == []
    # Recorded evidence untouched: still the old asset, no media merged.
    evidence = json.loads((env.state_dir / f"{CANON}.evidence.json").read_text())
    assert evidence["photo"]["uuid"] == LOCAL
    assert "media_metadata" not in evidence
    # The valid correction persists, so retries converge loudly (see next).
    assert pdw._read_stage_meta(CANON)["agent_local_uuid"] == LOCAL2
    # Journal untouched: still fresh, no media identity recorded.
    journal = json.loads((env.state_dir / f"{CANON}.json").read_text())
    assert journal["state"] == "DISCOVERED"
    assert not journal.get("media")


def test_drive_mismatch_pin_reuse_still_refuses(env):
    """Omitted retry reuses the corrected pin and re-refuses (no revert)."""
    pdw, staged = _stage_and_capture_old(env)
    with pytest.raises(ValueError, match="evidence identity mismatch"):
        pdw._drive(CANON, staged, LOCAL2)
    pdw._release(CANON)
    # No explicit UUID: the persisted correction is reused — and refused
    # again, instead of silently reverting to the old asset's evidence.
    with pytest.raises(ValueError, match="evidence identity mismatch"):
        pdw._drive(CANON, staged)
    assert env.commit_calls == []
    evidence = json.loads((env.state_dir / f"{CANON}.evidence.json").read_text())
    assert evidence["photo"]["uuid"] == LOCAL


def test_stage_copy_correction_restages_and_invalidates_evidence(env):
    """stage_copy with correction replaces bytes + invalidates old evidence.

    The staged copy is rebuilt wholesale from the new asset's bytes while
    the journal is still fresh, so dropping the superseded evidence and
    restaging converges the retry on one identity (daemon path).
    """
    env.db._photos[NEW] = FakePhoto(NEW)
    pdw, _staged = _stage_and_capture_old(env)
    restaged = pdw.stage_copy(CANON, make_media_file(env.temp_root), TRIGGER,
                              agent_local_uuid=NEW)
    assert restaged is not None and restaged.is_file()
    meta = pdw._read_stage_meta(CANON)
    assert meta["agent_local_uuid"] == NEW
    assert meta["request_reason"] == TRIGGER  # provenance preserved
    assert "triggered_at" in meta
    # Superseded evidence invalidated for recapture (not silently reused).
    assert not (env.state_dir / f"{CANON}.evidence.json").exists()
    pdw._release(CANON)

    # The drive recaptures under NEW and commits canonical: one identity.
    pdw._drive(CANON, restaged, NEW)
    assert len(env.commit_calls) == 1
    assert env.commit_calls[0]["video_uuid"] == CANON
    evidence = json.loads((env.state_dir / f"{CANON}.evidence.json").read_text())
    assert evidence["photo"]["uuid"] == NEW


def test_stage_copy_correction_with_bound_evidence_refuses(env):
    """stage_copy refuses a correction once progress binds the old evidence."""
    pdw, staged = _stage_and_capture_old(env)
    old_bytes = staged.read_bytes()
    # Simulate a drive that proceeded under the old identity: the evidence
    # is already bound to staged media, so restaging alone cannot heal it.
    pdw._update_evidence(CANON, lambda ev: ev.update({"media_metadata": {"container": "mov"}}))
    with pytest.raises(ValueError, match="evidence identity mismatch"):
        pdw.stage_copy(CANON, make_media_file(env.temp_root), TRIGGER,
                       agent_local_uuid=LOCAL2)
    # No mutation beyond the persisted pin: old bytes and evidence intact.
    assert staged.is_file() and staged.read_bytes() == old_bytes
    evidence = json.loads((env.state_dir / f"{CANON}.evidence.json").read_text())
    assert evidence["photo"]["uuid"] == LOCAL
    assert env.commit_calls == []
    assert pdw._active == set()  # refusal happened before slot acquisition


def test_stage_copy_correction_after_commit_skips_idempotent(env):
    """stage_copy after a commit keeps the terminal skip (no raise, no copy)."""
    pdw = dual_write.ProductionDualWrite.from_config(env.config)
    source = make_media_file(env.temp_root)
    staged = pdw.stage_copy(CANON, source, TRIGGER, agent_local_uuid=LOCAL)
    assert staged is not None
    pdw._drive(CANON, staged, LOCAL)  # terminal
    assert len(env.commit_calls) == 1
    assert pdw.stage_copy(CANON, source, TRIGGER, agent_local_uuid=LOCAL2) is None
    assert len(env.commit_calls) == 1


def test_stage_copy_correction_recaptures_when_fresh(env):
    """Evidence-only state + correction: restage converges on one identity."""
    env.db._photos[NEW] = FakePhoto(NEW)
    pdw = dual_write.ProductionDualWrite.from_config(env.config)
    # Evidence-only state: captured under OLD, no staged bytes, fresh journal.
    pdw._set_stage_meta(
        CANON,
        {"agent_local_uuid": LOCAL, "request_reason": TRIGGER,
         "activation": "continuous", "triggered_at": "2026-10-19T00:00:00Z"},
    )
    pdw._capture_evidence(CANON, LOCAL)
    assert not pdw._staged_copy_present(CANON)

    staged = pdw.stage_copy(CANON, make_media_file(env.temp_root), TRIGGER,
                            agent_local_uuid=NEW)
    assert staged is not None and staged.is_file()
    meta = pdw._read_stage_meta(CANON)
    assert meta["agent_local_uuid"] == NEW
    # Superseded evidence invalidated for recapture (not silently reused).
    assert not (env.state_dir / f"{CANON}.evidence.json").exists()
    pdw._release(CANON)

    # The drive recaptures under NEW and commits canonical: one identity.
    pdw._drive(CANON, staged, NEW)
    assert len(env.commit_calls) == 1
    assert env.commit_calls[0]["video_uuid"] == CANON
    evidence = json.loads((env.state_dir / f"{CANON}.evidence.json").read_text())
    assert evidence["photo"]["uuid"] == NEW


def test_mode_run_correction_with_staged_bytes_refuses_structured(env, capsys):
    """One-shot retry with correction: structured refusal, nothing combined."""
    pdw, _staged = _stage_and_capture_old(env)
    rc = dual_write.mode_run(env.config, CANON, None, TRIGGER, LOCAL2)
    assert rc == 3
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["outcome"] == "refused_evidence_identity_mismatch"
    assert env.commit_calls == []
    evidence = json.loads((env.state_dir / f"{CANON}.evidence.json").read_text())
    assert evidence["photo"]["uuid"] == LOCAL
    assert "media_metadata" not in evidence
    assert pdw._read_stage_meta(CANON)["agent_local_uuid"] == LOCAL2


def test_mode_run_mismatch_pin_reuse_still_refuses(env, capsys):
    """One-shot retry WITHOUT --agent-local-uuid reuses the pin, refuses."""
    pdw, _staged = _stage_and_capture_old(env)
    assert dual_write.mode_run(env.config, CANON, None, TRIGGER, LOCAL2) == 3
    capsys.readouterr()
    # Omitted: the persisted correction is reused — still an explicit
    # refusal, never a silent revert to the old asset.
    rc = dual_write.mode_run(env.config, CANON, None, TRIGGER)
    assert rc == 3
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["outcome"] == "refused_evidence_identity_mismatch"
    assert env.commit_calls == []


def test_caption_mutation_correction_refuses_structured(env, capsys):
    """Caption-mutation consumes SAVED evidence: correction refuses, no write."""
    pdw = dual_write.ProductionDualWrite.from_config(env.config)
    source = make_media_file(env.temp_root)
    staged = pdw.stage_copy(CANON, source, TRIGGER, agent_local_uuid=LOCAL)
    assert staged is not None
    pdw._drive(CANON, staged, LOCAL)  # terminal: committed under LOCAL reads
    assert len(env.commit_calls) == 1
    journal_before = json.loads((env.state_dir / f"{CANON}.json").read_text())
    caption_before = journal_before["caption"]["sha256"]

    rc = dual_write.mode_caption_mutation(env.config, CANON, TRIGGER, LOCAL2)
    assert rc == 3
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["outcome"] == "refused_evidence_identity_mismatch"
    # No new commit, no evidence rewrite, no journal caption change.
    assert len(env.commit_calls) == 1
    evidence = json.loads((env.state_dir / f"{CANON}.evidence.json").read_text())
    assert evidence["photo"]["uuid"] == LOCAL
    journal_after = json.loads((env.state_dir / f"{CANON}.json").read_text())
    assert journal_after["caption"]["sha256"] == caption_before


def test_evidence_uuid_compare_is_case_insensitive(env):
    """Recorded photo.uuid in another case still matches (no false refuse)."""
    pdw, staged = _stage_and_capture_old(env)
    evidence_path = env.state_dir / f"{CANON}.evidence.json"
    evidence = json.loads(evidence_path.read_text())
    evidence["photo"]["uuid"] = LOCAL.lower()
    evidence_path.write_text(json.dumps(evidence))

    pdw._drive(CANON, staged)  # omitted: pin LOCAL matches lowercase record
    assert len(env.commit_calls) == 1
    assert env.commit_calls[0]["video_uuid"] == CANON


def test_terminal_redrive_with_correction_stays_idempotent(env):
    """Committed journal + corrected UUID: idempotent, no new commit."""
    pdw = dual_write.ProductionDualWrite.from_config(env.config)
    source = make_media_file(env.temp_root)
    staged = pdw.stage_copy(CANON, source, TRIGGER, agent_local_uuid=LOCAL)
    assert staged is not None
    pdw._drive(CANON, staged, LOCAL)
    assert len(env.commit_calls) == 1

    pdw._drive(CANON, staged, LOCAL2)  # must not raise, must not recommit
    assert len(env.commit_calls) == 1
    snapshots = sorted((env.state_dir / "metrics").glob("*.json"))
    assert json.loads(snapshots[-1].read_text())["result"] == "already_terminal"
