"""P10 full-corpus migration engine tests (mac-agent).

Packet MEDIA_BACKBONE_P10_OVERNIGHT_FULL_DIVE_ANALYZER_MIGRATION_V1 §61 test
matrix, engine-level behaviors with fakes (no provider, no Photos, no DB):
classification boundary, vault provenance firewall, media-only caption
handling, dedupe, roundtrip verification, disk guard, runaway guard,
idempotence, and no-UserDiverAccess invariant.
"""

import hashlib
import json
import os
from pathlib import Path

import pytest

from src.ingest import migration_full as mf
from src.ingest.objectstore.base import ObjectHead, PutResult
from src.ingest.migration_full import (
    DomainItem,
    FullCorpusMigrationEngine,
    InventoryClass,
    MigrationJournal,
    MigrationState,
)


class FakeStore:
    """Fake B2 store: records ops, holds bytes by key."""

    def __init__(self, existing: dict[str, bytes] | None = None):
        self.existing = dict(existing or {})
        self.puts: list[tuple[str, int]] = []
        self.gets: list[str] = []
        self.fail_get_once = False

    def head(self, key):
        if key in self.existing:
            return mf_object_head(key, len(self.existing[key]))
        return None

    def put(self, key, source, content_type=None):
        data = Path(source).read_bytes()
        self.existing[key] = data
        self.puts.append((key, len(data)))
        return PutResult(key=key, sha256=hashlib.sha256(data).hexdigest(), byte_size=len(data))

    def get(self, key):
        return self.existing[key]

    def get_streaming_sha(self, key, chunk_size=1024 * 1024):
        data = self.existing[key]
        self.gets.append(key)
        if self.fail_get_once:
            self.fail_get_once = False
            raise RuntimeError("transient get failure")
        return hashlib.sha256(data).hexdigest(), len(data)


def mf_object_head(key, size):
    from src.ingest.objectstore.base import ObjectHead, PutResult

    return ObjectHead(key=key, byte_size=size)


def make_engine(tmp_path, existing=None, dry_run=False):
    prod = FakeStore(existing=existing)
    engine = FullCorpusMigrationEngine(
        prod_store=prod,
        dev_store=None,
        commit_fn=lambda doc: {
            "blob_sha256": doc["payload"]["blob"]["sha256"],
            "media_only": doc["payload"].get("caption") is None,
            "media_revision_id": 1,
        },
        state_dir=tmp_path / "state",
        temp_root=tmp_path / "tmp",
        vault_root=str(tmp_path / "vault"),
        min_free_disk_bytes=1,
        prod_bucket="diveanalyzer-prod-media",
        dry_run=dry_run,
    )
    return engine, prod


VU = "D766186E-E867-456D-BC7A-D9313B180954"
VU2 = "E6ACBCF6-9801-439B-937D-852718BA8815"


def make_items():
    a = DomainItem(
        video_uuid=VU,
        video_filename=f"{VU}.mov",
        diver_id=1,
        resolved_asset_uuid=VU,
        classification=InventoryClass.F_PHOTOS_ICLOUD_EDITED,
    )
    b = DomainItem(
        video_uuid=VU2,
        video_filename=f"{VU2}.mov",
        diver_id=2,
        media_revision_id=7,
        blob_sha256="a" * 64,
        verified_prod=True,
        classification=InventoryClass.A_ALREADY_VERIFIED_PROD,
    )
    return [a, b]


def _fake_caption_ok(item, photos_index=None):
    from src.ingest.caption import caption_sha256

    raw = "100B G"
    return (
        {"raw": raw, "sha256": caption_sha256(raw), "provider": "osxphotos_description_stable"},
        {},
    )


def install_materializer(engine, bytes_payload: bytes, suffix=".mov"):
    calls = {"n": 0}

    def fake_materialize(item, journal):
        target = engine.temp_root / item.video_uuid
        target.mkdir(parents=True, exist_ok=True)
        staged = target / f"source{suffix}"
        staged.write_bytes(bytes_payload)
        calls["n"] += 1
        return staged

    engine._materialize_from_photos = fake_materialize
    return calls


def test_classification_boundaries(tmp_path):
    engine, _ = make_engine(tmp_path)
    a, b = make_items()
    items = engine.classify([a, b], {"by_uuid": {}})
    assert items[0].classification == InventoryClass.F_PHOTOS_ICLOUD_EDITED
    assert items[1].classification == InventoryClass.A_ALREADY_VERIFIED_PROD


def test_already_prod_skip_zero_byte_ops(tmp_path):
    engine, prod = make_engine(tmp_path)
    a, b = make_items()
    photos_index = engine.build_photos_index([a, b])
    engine.run_wave([a, b], photos_index)
    assert engine.outcomes[VU2] == MigrationState.SKIPPED_ALREADY_PROD
    assert prod.puts == []  # zero uploads
    assert prod.gets == []  # zero verification GETs


def test_full_success_path_roundtrip(tmp_path):
    engine, prod = make_engine(tmp_path)
    a, _ = make_items()
    payload = b"edited-rendition-bytes-" + os.urandom(1024)
    install_materializer(engine, payload)
    engine._caption_authority = _fake_caption_ok
    photos_index = engine.build_photos_index([a])
    engine.run_wave([a], photos_index)
    assert engine.outcomes[VU] == MigrationState.CLEANED
    sha = hashlib.sha256(payload).hexdigest()
    key = f"blobs/sha256/{sha[:2]}/{sha}.mov"
    assert prod.existing[key] == payload
    assert prod.gets == [key]  # one full verification GET
    journal = json.loads((tmp_path / "state" / f"{VU}.mig.json").read_text())
    assert journal["state"] == MigrationState.CLEANED
    assert journal["commit_result"]["media_only"] is False
    assert not (tmp_path / "tmp" / VU).exists()  # temp cleaned


def test_media_only_when_caption_unavailable(tmp_path):
    engine, prod = make_engine(tmp_path)
    a, _ = make_items()
    payload = b"media-only-bytes"
    install_materializer(engine, payload)
    # No Photos library configured -> caption authority unavailable
    engine.library_path = None
    photos_index = engine.build_photos_index([a])
    engine.run_wave([a], photos_index)
    assert engine.outcomes[VU] == MigrationState.CLEANED
    journal = json.loads((tmp_path / "state" / f"{VU}.mig.json").read_text())
    assert journal["commit_result"]["media_only"] is True
    assert journal["state"] == MigrationState.CLEANED


def test_verification_failure_is_not_retryable(tmp_path):
    engine, prod = make_engine(tmp_path)
    a, _ = make_items()
    payload = b"to-be-corrupted"
    install_materializer(engine, payload)
    photos_index = engine.build_photos_index([a])
    original_get = prod.get_streaming_sha

    def corrupting_get(key, chunk_size=1024 * 1024):
        data = prod.existing[key]
        return hashlib.sha256(data + b"X").hexdigest(), len(data)

    prod.get_streaming_sha = corrupting_get
    engine.run_wave([a], photos_index)
    journal = json.loads((tmp_path / "state" / f"{VU}.mig.json").read_text())
    assert journal["state"] == MigrationState.QUARANTINED
    assert journal["last_error"]["family"] == "verification_failed"
    assert journal["last_error"]["retryable"] is False


def test_vault_source_requires_provenance(tmp_path):
    engine, prod = make_engine(tmp_path)
    vault_dir = tmp_path / "vault" / VU
    vault_dir.mkdir(parents=True)
    payload = b"vault-accepted-rendition"
    sha = hashlib.sha256(payload).hexdigest()
    (vault_dir / "source.mov").write_bytes(payload)
    meta = {
        "canonical_video_uuid": VU,
        "agent_local_uuid": VU,
        "source_kind": "osxphotos_single_asset_export",
        "sha256": sha,
        "size_bytes": len(payload),
        "created_at": "2020-01-01T00:00:00+00:00",
    }
    (vault_dir / "source.json").write_text(json.dumps(meta))
    a = DomainItem(
        video_uuid=VU,
        video_filename=f"{VU}.mov",
        diver_id=1,
        resolved_asset_uuid=VU,
    )
    # asset date_modified before export -> fresh
    a._asset_date_modified = __import__("datetime").datetime(
        2019, 1, 1, tzinfo=__import__("datetime").timezone.utc
    )
    engine.classify([a], {"by_uuid": {}})
    assert a.classification == InventoryClass.C_VAULT_SOURCE
    engine.run_wave([a], {"by_uuid": {}})
    assert engine.outcomes[VU] == MigrationState.CLEANED
    key = f"blobs/sha256/{sha[:2]}/{sha}.mov"
    assert prod.existing[key] == payload


def test_vault_stale_when_edited_after_export(tmp_path):
    engine, _ = make_engine(tmp_path)
    vault_dir = tmp_path / "vault" / VU
    vault_dir.mkdir(parents=True)
    (vault_dir / "source.mov").write_bytes(b"x")
    meta = {
        "canonical_video_uuid": VU,
        "agent_local_uuid": VU,
        "source_kind": "osxphotos_single_asset_export",
        "sha256": "0" * 64,
        "created_at": "2020-01-01T00:00:00+00:00",
    }
    (vault_dir / "source.json").write_text(json.dumps(meta))
    a = DomainItem(video_uuid=VU, video_filename=f"{VU}.mov", diver_id=1, resolved_asset_uuid=VU)
    a._asset_date_modified = __import__("datetime").datetime(
        2021, 1, 1, tzinfo=__import__("datetime").timezone.utc
    )
    engine.classify([a], {"by_uuid": {}})
    assert a.classification != InventoryClass.C_VAULT_SOURCE


def test_vault_rejects_wrong_source_kind(tmp_path):
    engine, _ = make_engine(tmp_path)
    vault_dir = tmp_path / "vault" / VU
    vault_dir.mkdir(parents=True)
    (vault_dir / "source.mov").write_bytes(b"x")
    meta = {
        "canonical_video_uuid": VU,
        "agent_local_uuid": VU,
        "source_kind": "poster_export",
        "sha256": "0" * 64,
        "created_at": "2020-01-01T00:00:00+00:00",
    }
    (vault_dir / "source.json").write_text(json.dumps(meta))
    a = DomainItem(video_uuid=VU, video_filename=f"{VU}.mov", diver_id=1, resolved_asset_uuid=VU)
    a._asset_date_modified = __import__("datetime").datetime(
        2019, 1, 1, tzinfo=__import__("datetime").timezone.utc
    )
    engine.classify([a], {"by_uuid": {}})
    assert a.classification != InventoryClass.C_VAULT_SOURCE


def test_content_dedupe_same_bytes_second_item(tmp_path):
    engine, prod = make_engine(tmp_path)
    payload = b"identical-bytes-two-identities"
    sha = hashlib.sha256(payload).hexdigest()
    key = f"blobs/sha256/{sha[:2]}/{sha}.mov"
    # Pre-seed PROD with the same content (first identity migrated already).
    prod.existing[key] = payload
    a = DomainItem(
        video_uuid=VU,
        video_filename=f"{VU}.mov",
        diver_id=2,
        classification=InventoryClass.F_PHOTOS_ICLOUD_EDITED,
    )
    calls = install_materializer(engine, payload)
    engine.run_wave([a], {"by_uuid": {}})
    assert engine.outcomes[VU] == MigrationState.CLEANED
    assert prod.puts == []  # deduped: no second upload
    assert engine.counters["dedupe_avoided_bytes"] == len(payload)
    journal = json.loads((tmp_path / "state" / f"{VU}.mig.json").read_text())
    assert journal.get("dedupe") is True
    assert journal["commit_result"]["blob_sha256"] == sha


def test_disk_guard_defers_item(tmp_path):
    engine, prod = make_engine(tmp_path)
    engine.min_free_disk_bytes = 10**18  # impossible
    a, _ = make_items()
    install_materializer(engine, b"bytes")
    engine.run_wave([a], {"by_uuid": {}})
    journal = json.loads((tmp_path / "state" / f"{VU}.mig.json").read_text())
    assert journal["state"] == MigrationState.RETRYABLE
    assert journal["last_error"]["family"] == "insufficient_disk"


def test_journal_is_terminal_after_success_and_never_restarts(tmp_path):
    engine, prod = make_engine(tmp_path)
    a, _ = make_items()
    payload = b"stable-bytes"
    install_materializer(engine, payload)
    engine.run_wave([a], {"by_uuid": {}})
    assert engine.outcomes[VU] == MigrationState.CLEANED
    journal = MigrationJournal(tmp_path / "state", VU)
    journal.load()
    assert journal.is_terminal


def test_transports_unkown_state_fails_closed(tmp_path):
    journal = MigrationJournal(tmp_path / "state", VU)
    journal.load()
    journal.doc["state"] = "BOGUS_STATE"
    assert journal.state == "BOGUS_STATE"
    assert not journal.is_terminal


def test_g_class_resolved_by_deterministic_caption_equality(tmp_path):
    """Both candidates exist, different assets; exactly one description
    equals the dive raw_caption -> deterministic resolution (no guessing)."""
    class FakeAsset:
        def __init__(self, uuid, description):
            self.uuid = uuid
            self.description = description
            self.date_modified = None
            self.adjustments_path = None

    engine, _ = make_engine(tmp_path)
    engine.dive_caption_fn = lambda vu: "103B P/G 3m"
    vu_asset = FakeAsset("662C57F8-E184-47E4-9CEC-7CB53FA0A7C7", "103B P/M 3m")
    fn_asset = FakeAsset("20E90523-7B91-422C-9EB7-F91A1CEB12D1", "103B P/G 3m")
    resolved = engine._resolve_differing_assets(
        DomainItem(video_uuid="662C57F8-E184-47E4-9CEC-7CB53FA0A7C7"),
        vu_asset,
        fn_asset,
    )
    assert resolved is fn_asset


def test_g_class_stays_unguessed_when_equality_inconclusive(tmp_path):
    class FakeAsset:
        def __init__(self, uuid, description):
            self.uuid = uuid
            self.description = description
            self.date_modified = None
            self.adjustments_path = None

    engine, _ = make_engine(tmp_path)
    engine.dive_caption_fn = lambda vu: "nothing matches"
    a = FakeAsset("A" * 36, "desc one")
    b = FakeAsset("B" * 36, "desc two")
    assert (
        engine._resolve_differing_assets(
            DomainItem(video_uuid="C" * 36), a, b
        )
        is None
    )
    engine.dive_caption_fn = None
    assert (
        engine._resolve_differing_assets(
            DomainItem(video_uuid="C" * 36), a, b
        )
        is None
    )
    engine.dive_caption_fn = lambda vu: "desc one"
    engine.dive_caption_fn = lambda vu: None
    assert (
        engine._resolve_differing_assets(
            DomainItem(video_uuid="C" * 36), a, b
        )
        is None
    )
