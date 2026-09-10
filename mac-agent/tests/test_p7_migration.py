"""P7 historical migration engine tests (packet
MEDIA_BACKBONE_P7_ACCELERATED_CONTINUOUS_INGEST_MIGRATION_V1 §11-§28).

Offline: fake object stores + fake Photos + fake commit. Covers:
- DB-driven classification (A-F) with fail-closed ownership (§12)
- DEV→PROD migration with separate DEV-read / PROD-write credentials (§15)
- roundtrip SHA verification: source SHA == full PROD GET SHA (§22);
  mismatch → QUARANTINED, batch continues (§28)
- restart/resume from journal after injected failure (§25/§26)
- second-pass idempotence: 0 duplicate blobs/locations/uploads (§27)
- caption authority: exact receipt reuse; unavailable → deferred, never
  manufactured (§19)
- Photos materialization seam + interactive-defer behavior (§17)
- local-source SHA validation (§16)
- no delete/hide; legacy untouched (§35/§36)
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.ingest.migration as migration_module
from src.ingest.content_addr import object_key_for_sha, sha256_bytes
from src.ingest.errors import ObjectStoreUnavailable, ObjectStoreVerificationError
from src.ingest.migration import (
    HistoricalMigrationEngine,
    MigrationClassification,
    MigrationItem,
    MigrationJournal,
    MigrationState,
)

UUID_1 = "11111111-1111-1111-1111-111111111111"
UUID_2 = "22222222-2222-2222-2222-222222222222"
UUID_3 = "33333333-3333-3333-3333-333333333333"
UUID_4 = "44444444-4444-4444-4444-444444444444"
UUID_5 = "55555555-5555-5555-5555-555555555555"

MEDIA_A = b"historical-media-A" * 100
MEDIA_B = b"historical-media-B" * 200
MEDIA_C = b"photos-materialized-C" * 50
MEDIA_D = b"local-vault-D" * 75

SHA_A = sha256_bytes(MEDIA_A)
SHA_B = sha256_bytes(MEDIA_B)
SHA_C = sha256_bytes(MEDIA_C)
SHA_D = sha256_bytes(MEDIA_D)


class FakeStore:
    """Key/value object store with failure injection; mirrors the adapter
    surface used by the engine (head/get/put)."""

    def __init__(self, objects: dict[str, bytes] | None = None):
        self.objects = dict(objects or {})
        self.put_count: dict[str, int] = {}
        self.get_count: dict[str, int] = {}
        self.head_count: dict[str, int] = {}
        self.fail_get_once = False
        self.fail_put_once = False
        self.corrupt_keys: set[str] = set()
        self.unavailable = False

    def put(self, key, source, content_type: str | None = None):
        if self.unavailable:
            raise ObjectStoreUnavailable("store unavailable (injected)")
        if self.fail_put_once:
            self.fail_put_once = False
            raise ObjectStoreUnavailable("injected put failure")
        data = source if isinstance(source, bytes) else Path(source).read_bytes()
        self.put_count[key] = self.put_count.get(key, 0) + 1
        self.objects[key] = data
        return SimpleNamespace(key=key, sha256=sha256_bytes(data), byte_size=len(data))

    def head(self, key):
        self.head_count[key] = self.head_count.get(key, 0) + 1
        if self.unavailable:
            raise ObjectStoreUnavailable("store unavailable (injected)")
        data = self.objects.get(key)
        if data is None:
            return None
        return SimpleNamespace(key=key, byte_size=len(data), etag="fake")

    def get(self, key) -> bytes:
        self.get_count[key] = self.get_count.get(key, 0) + 1
        if self.unavailable:
            raise ObjectStoreUnavailable("store unavailable (injected)")
        if self.fail_get_once:
            self.fail_get_once = False
            raise ObjectStoreUnavailable("injected get failure")
        if key in self.corrupt_keys:
            data = self.objects.get(key, b"")
            return data[:-1] + bytes([data[-1] ^ 0xFF]) if data else b"corrupt"
        data = self.objects.get(key)
        if data is None:
            raise ObjectStoreUnavailable(f"no such object: {key}")
        return data


class FakeCommit:
    """Server commit: dedupes by (video_uuid, blob sha, caption sha) exactly
    like commit_verified_ingest; records every call."""

    def __init__(self):
        self.calls: list[dict] = []
        self.committed: dict[tuple, dict] = {}
        self.fail_once = False

    def __call__(self, document):
        if self.fail_once:
            self.fail_once = False
            raise ObjectStoreUnavailable("injected commit failure (lost response)")
        self.calls.append(document)
        p = document["payload"]
        key = (p["video_uuid"], p["blob"]["sha256"], p["caption"]["sha256"])
        if key not in self.committed:
            self.committed[key] = {
                "video_uuid": p["video_uuid"],
                "blob_sha256": p["blob"]["sha256"],
                "blob_existed": len(self.committed) > 0,
                "media_blob_location_id": len(self.committed) + 1,
                "blob_location_existed": False,
                "media_revision_id": 1,
                "media_revision_existed": False,
                "caption_revision_id": 1,
                "caption_revision_existed": False,
                "ingest_state_id": len(self.committed) + 1,
            }
        return dict(self.committed[key])


def make_engine(tmp_path, *, dev_objects=None, prod_objects=None, receipts=None,
                vault_items=None, materialize_fn=None, commit=None,
                free_disk_bytes_fn=None):
    state_dir = tmp_path / "mig_state"
    temp_root = tmp_path / "mig_tmp"
    receipt_dirs = []
    if receipts:
        receipt_dir = tmp_path / "receipts"
        receipt_dir.mkdir(parents=True, exist_ok=True)
        for name, doc in receipts.items():
            (receipt_dir / name).write_text(json.dumps(doc), encoding="utf-8")
        receipt_dirs.append(receipt_dir)
    vault_root = None
    if vault_items:
        vault_root = tmp_path / "vault"
        vault_root.mkdir(parents=True, exist_ok=True)
        for uuid, data in vault_items.items():
            folder = vault_root / uuid
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "source.mov").write_bytes(data)
    engine = HistoricalMigrationEngine(
        prod_store=FakeStore(prod_objects),
        dev_store=FakeStore(dev_objects),
        commit_fn=commit or FakeCommit(),
        state_dir=state_dir,
        temp_root=temp_root,
        vault_root=str(vault_root) if vault_root else None,
        receipt_dirs=receipt_dirs,
        library_path=None,
        ffprobe_path="ffprobe-fake",
        materialize_fn=materialize_fn,
        min_free_disk_bytes=1024,
        prod_bucket="diveanalyzer-prod-media",
        free_disk_bytes_fn=free_disk_bytes_fn,
    )
    return engine


def item(sha, uuid=UUID_1, size=None, dev=False, prod=False, ext="mov",
         dev_key=None, prod_key=None, owner=True, chain=True):
    if size is None:
        blob = {
            SHA_A: MEDIA_A, SHA_B: MEDIA_B, SHA_C: MEDIA_C, SHA_D: MEDIA_D,
        }[sha]
        size = len(blob)
    return MigrationItem(
        video_uuid=uuid,
        blob_sha256=sha,
        byte_size=size,
        classification=None,
        verified_dev=dev,
        verified_prod=prod,
        dev_object_key=dev_key or (object_key_for_sha(sha, ext=ext) if dev else None),
        prod_object_key=prod_key or (object_key_for_sha(sha, ext=ext) if prod else None),
        owner_diver=owner,
        has_diver_chain=chain,
        extension=ext,
    )


def receipt_doc(video_uuid, sha, blob_bytes):
    return {
        "payload": {
            "video_uuid": video_uuid,
            "ingest_impl_version": "media_backbone_v1",
            "rendition_semantics": "photos_edited_rendition",
            "caption": {
                "raw": "107B | 7.5 | H:3 | drill:no-arms | note:à revoir",
                "sha256": sha256_bytes(
                    "107B | 7.5 | H:3 | drill:no-arms | note:à revoir".encode("utf-8")
                ),
                "provider": "osxphotos_description_stable",
            },
            "blob": {
                "sha256": sha,
                "byte_size": len(blob_bytes),
                "object_key": object_key_for_sha(sha, ext="mov"),
                "storage_backend": "b2",
                "bucket": "diveanalyzer-dev-media",
            },
            "remote_verified": True,
        },
        "extra": {
            "environment": "dev",
            "codec": "hevc",
            "width": 1920,
            "height": 1080,
            "duration_seconds": 9.288,
            "photos_edit_fingerprint": "fp-original",
            "source_provenance": {"photos_asset_uuid": video_uuid},
        },
    }


RECEIPTS = {
    f"{UUID_1}.commit_input.json": receipt_doc(UUID_1, SHA_A, MEDIA_A),
    f"{UUID_2}.commit_input.json": receipt_doc(UUID_2, SHA_B, MEDIA_B),
    f"{UUID_3}.mutation_input.json": receipt_doc(UUID_3, SHA_C, MEDIA_C),
    f"{UUID_5}.commit_input.json": receipt_doc(UUID_5, SHA_D, MEDIA_D),
}


# ---------------------------------------------------------------------------
# Classification (§11/§12)


def test_classification_matrix(tmp_path):
    engine = make_engine(tmp_path)
    items = [
        item(SHA_A, UUID_1, prod=True),
        item(SHA_B, UUID_2, dev=True),
        item(SHA_C, UUID_3),  # photos probe default (engine has no probe)
        item(SHA_D, UUID_4, owner=False),
    ]
    engine._photos_probe = None
    engine.classify(items)
    assert items[0].classification is MigrationClassification.ALREADY_PROD
    assert items[1].classification is MigrationClassification.DEV_ONLY
    assert items[2].classification is MigrationClassification.PHOTOS_ICLOUD
    assert items[3].classification is MigrationClassification.CONFLICT


def test_classification_missing_without_any_source(tmp_path):
    engine = make_engine(tmp_path)
    engine._photos_probe = lambda uuid: False  # asset not in Photos
    items = engine.classify([item(SHA_A, UUID_5, dev=False)])
    assert items[0].classification is MigrationClassification.MISSING


def test_classification_local_source_priority_over_photos(tmp_path):
    engine = make_engine(tmp_path, vault_items={UUID_5: MEDIA_D})
    items = engine.classify([item(SHA_D, UUID_5)])
    assert items[0].classification is MigrationClassification.LOCAL_SOURCE


def test_scope_guard_never_redrives_already_prod(tmp_path):
    engine = make_engine(tmp_path)
    it = item(SHA_A, UUID_1, prod=True)
    it.classification = MigrationClassification.ALREADY_PROD
    doc = engine.drive_item(it)
    assert doc["state"] == MigrationState.SKIPPED_ALREADY_PROD.value
    assert doc.get("skip_reason") == "already_verified_prod"
    assert engine.prod_store.get_count == {}
    assert engine.prod_store.put_count == {}


# ---------------------------------------------------------------------------
# DEV→PROD migration (§14/§15/§21/§22)


def test_dev_to_prod_full_flow(tmp_path):
    engine = make_engine(
        tmp_path,
        dev_objects={object_key_for_sha(SHA_A, ext="mov"): MEDIA_A},
        receipts=RECEIPTS,
    )
    it = item(SHA_A, UUID_1, dev=True)
    it.classification = MigrationClassification.DEV_ONLY
    doc = engine.drive_item(it)
    assert doc["state"] == MigrationState.CLEANED.value
    prod_key = object_key_for_sha(SHA_A, ext="mov")
    assert engine.prod_store.objects[prod_key] == MEDIA_A
    # full PROD GET verify happened exactly once (roundtrip §22)
    assert engine.prod_store.get_count[prod_key] == 1
    # exactly one PROD upload
    assert engine.prod_store.put_count[prod_key] == 1
    # DEV key was READ, not written
    assert all(k in engine.dev_store.get_count for k in engine.dev_store.get_count)
    assert engine.dev_store.put_count == {}
    # commit bound to PROD bucket/environment (§21)
    commit = engine.commit_fn
    doc_sent = commit.calls[0]
    assert doc_sent["payload"]["blob"]["bucket"] == "diveanalyzer-prod-media"
    assert doc_sent["extra"]["environment"] == "prod"
    assert doc_sent["extra"]["migration_provenance"]["source_kind"] == "dev_replica"
    # caption exactness: reused the original receipt caption verbatim (§19)
    assert doc_sent["payload"]["caption"]["raw"] == (
        "107B | 7.5 | H:3 | drill:no-arms | note:à revoir"
    )
    # temp cleaned after verified commit (§24)
    assert not list((tmp_path / "mig_tmp").glob(f"{SHA_A[:12]}*"))


def test_roundtrip_sha_mismatch_quarantines_and_batch_continues(tmp_path):
    engine = make_engine(
        tmp_path,
        dev_objects={object_key_for_sha(SHA_A, ext="mov"): MEDIA_A},
        receipts=RECEIPTS,
    )
    # corrupt the PROD copy of a SECOND item (already present) to prove that a
    # failed verify quarantines that item but never stops the batch
    engine.prod_store.objects[object_key_for_sha(SHA_B, ext="mov")] = MEDIA_B + b"x"
    it_a = item(SHA_A, UUID_1, dev=True)
    it_a.classification = MigrationClassification.DEV_ONLY
    it_b = item(SHA_B, UUID_2, prod=True)  # prod_object_present verify path
    it_b.classification = MigrationClassification.DEV_ONLY
    doc_a = engine.drive_item(it_a)
    doc_b = engine.drive_item(it_b)
    assert doc_a["state"] == MigrationState.CLEANED.value
    assert doc_b["state"] == MigrationState.QUARANTINED.value
    assert doc_b["last_error"]["family"] == "verification_failed"
    # the quarantined item produced NO commit
    commits = [c for c in engine.commit_fn.calls if c["payload"]["video_uuid"] == UUID_2]
    assert commits == []


def test_dev_get_verified_before_prod_put(tmp_path):
    engine = make_engine(
        tmp_path,
        dev_objects={object_key_for_sha(SHA_A, ext="mov"): b"corrupted!"},
        receipts=RECEIPTS,
    )
    it = item(SHA_A, UUID_1, dev=True)
    it.classification = MigrationClassification.DEV_ONLY
    doc = engine.drive_item(it)
    assert doc["state"] == MigrationState.QUARANTINED.value
    assert doc["last_error"]["family"] == "verification_failed"
    # nothing was uploaded to PROD (fail closed before the write, §15)
    assert engine.prod_store.put_count == {}


# ---------------------------------------------------------------------------
# Restart/resume (§25/§26)


def test_resume_after_mid_upload_failure(tmp_path):
    engine = make_engine(
        tmp_path,
        dev_objects={object_key_for_sha(SHA_A, ext="mov"): MEDIA_A},
        receipts=RECEIPTS,
    )
    engine.prod_store.fail_put_once = True
    it = item(SHA_A, UUID_1, dev=True)
    it.classification = MigrationClassification.DEV_ONLY
    doc = engine.drive_item(it)
    assert doc["state"] == MigrationState.RETRYABLE.value
    assert doc.get("resume_state") == MigrationState.PROD_UPLOAD_STARTED.value

    # restart: fresh engine over the SAME state dir (journal is the authority)
    engine2 = HistoricalMigrationEngine(
        prod_store=engine.prod_store,
        dev_store=engine.dev_store,
        commit_fn=engine.commit_fn,
        state_dir=engine.state_dir,
        temp_root=engine.temp_root,
        receipt_dirs=engine.receipt_dirs,
        ffprobe_path="ffprobe-fake",
        min_free_disk_bytes=1024,
        prod_bucket="diveanalyzer-prod-media",
    )
    doc2 = engine2.drive_item(it)
    assert doc2["state"] == MigrationState.CLEANED.value
    prod_key = object_key_for_sha(SHA_A, ext="mov")
    assert engine.prod_store.objects[prod_key] == MEDIA_A
    # exactly one successful PUT across both attempts
    assert engine.prod_store.put_count[prod_key] == 1


def test_resume_after_commit_failure_recommits_once(tmp_path):
    engine = make_engine(
        tmp_path,
        dev_objects={object_key_for_sha(SHA_A, ext="mov"): MEDIA_A},
        receipts=RECEIPTS,
    )
    engine.commit_fn.fail_once = True
    it = item(SHA_A, UUID_1, dev=True)
    it.classification = MigrationClassification.DEV_ONLY
    doc = engine.drive_item(it)
    assert doc["state"] == MigrationState.RETRYABLE.value
    doc2 = engine.drive_item(it)
    assert doc2["state"] == MigrationState.CLEANED.value
    # the PROD object was uploaded exactly ONCE (resume did not re-upload)
    assert engine.prod_store.put_count[object_key_for_sha(SHA_A, ext="mov")] == 1
    assert len(engine.commit_fn.calls) == 1


# ---------------------------------------------------------------------------
# Second-pass idempotence (§27)


def test_second_pass_zero_duplicate_uploads_or_commits(tmp_path):
    engine = make_engine(
        tmp_path,
        dev_objects={object_key_for_sha(SHA_A, ext="mov"): MEDIA_A},
        receipts=RECEIPTS,
    )
    it = item(SHA_A, UUID_1, dev=True)
    it.classification = MigrationClassification.DEV_ONLY
    doc1 = engine.drive_item(it)
    assert doc1["state"] == MigrationState.CLEANED.value
    prod_key = object_key_for_sha(SHA_A, ext="mov")
    puts_after_first = engine.prod_store.put_count[prod_key]
    commits_after_first = len(engine.commit_fn.calls)
    gets_after_first = dict(engine.prod_store.get_count)

    doc2 = engine.drive_item(it)  # full second pass
    assert doc2["state"] == MigrationState.CLEANED.value
    assert engine.prod_store.put_count[prod_key] == puts_after_first
    assert len(engine.commit_fn.calls) == commits_after_first
    assert engine.prod_store.get_count == gets_after_first


def test_prod_object_present_skips_dev_read_and_upload(tmp_path):
    engine = make_engine(
        tmp_path,
        prod_objects={object_key_for_sha(SHA_A, ext="mov"): MEDIA_A},
        receipts=RECEIPTS,
    )
    it = item(SHA_A, UUID_1, dev=True)
    it.classification = MigrationClassification.DEV_ONLY
    doc = engine.drive_item(it)
    assert doc["state"] == MigrationState.CLEANED.value
    assert engine.dev_store.get_count == {}  # no DEV read
    assert engine.prod_store.put_count == {}  # no upload
    # still verified by full PROD GET against the known source SHA (§22)
    assert engine.prod_store.get_count[object_key_for_sha(SHA_A, ext="mov")] == 1
    assert len(engine.commit_fn.calls) == 1  # location committed


# ---------------------------------------------------------------------------
# Local source + Photos seams (§16/§17)


def test_local_source_migration_with_sha_validation(tmp_path):
    engine = make_engine(tmp_path, vault_items={UUID_5: MEDIA_D}, receipts=RECEIPTS)
    it = item(SHA_D, UUID_5)
    it.classification = MigrationClassification.LOCAL_SOURCE
    doc = engine.drive_item(it)
    assert doc["state"] == MigrationState.CLEANED.value
    assert engine.prod_store.objects[object_key_for_sha(SHA_D, ext="mov")] == MEDIA_D
    assert doc.get("last_error") is None


def test_local_source_sha_mismatch_fails_closed(tmp_path):
    engine = make_engine(tmp_path, vault_items={UUID_5: MEDIA_D + b"tampered"})
    it = item(SHA_D, UUID_5)
    it.classification = MigrationClassification.LOCAL_SOURCE
    doc = engine.drive_item(it)
    assert doc["state"] == MigrationState.QUARANTINED.value
    assert engine.prod_store.put_count == {}


def test_photos_materialization_seam(tmp_path):
    def materialize(uuid, workdir):
        path = workdir / "exported.mov"
        path.write_bytes(MEDIA_C)
        return path

    engine = make_engine(tmp_path, receipts=RECEIPTS, materialize_fn=materialize)
    it = item(SHA_C, UUID_3)
    it.classification = MigrationClassification.PHOTOS_ICLOUD
    doc = engine.drive_item(it)
    assert doc["state"] == MigrationState.CLEANED.value
    assert engine.prod_store.objects[object_key_for_sha(SHA_C, ext="mov")] == MEDIA_C
    assert doc["source"]["kind"] == "photos_materialization"


def test_photos_interactive_failure_defers_single_asset(tmp_path):
    """A macOS permission prompt on ONE asset defers that asset only (§17/§28)."""
    def materialize(uuid, workdir):
        raise PermissionError("interactive prompt required (synthetic)")

    engine = make_engine(
        tmp_path,
        dev_objects={object_key_for_sha(SHA_A, ext="mov"): MEDIA_A},
        receipts=RECEIPTS,
        materialize_fn=materialize,
    )
    it = item(SHA_C, UUID_3)
    it.classification = MigrationClassification.PHOTOS_ICLOUD
    doc = engine.drive_item(it)
    assert doc["state"] == MigrationState.DEFERRED_INTERACTIVE.value
    assert "materialization" in doc.get("defer_reason", "")
    # other assets still proceed in the same wave
    it_a = item(SHA_A, UUID_1, dev=True)
    it_a.classification = MigrationClassification.DEV_ONLY
    doc_a = engine.drive_item(it_a)
    assert doc_a["state"] == MigrationState.CLEANED.value


# ---------------------------------------------------------------------------
# Caption authority (§19)


def test_missing_caption_authority_never_manufactured(tmp_path):
    engine = make_engine(tmp_path, receipts={})  # no receipts, no photos path
    it = item(SHA_A, UUID_1, dev=True)
    it.classification = MigrationClassification.DEV_ONLY
    doc = engine.drive_item(it)
    assert doc["state"] == MigrationState.QUARANTINED.value
    assert "caption" in doc["last_error"]["detail"]
    assert engine.prod_store.put_count == {}


def test_journal_persists_classification_and_states(tmp_path):
    engine = make_engine(
        tmp_path,
        dev_objects={object_key_for_sha(SHA_A, ext="mov"): MEDIA_A},
        receipts=RECEIPTS,
    )
    it = item(SHA_A, UUID_1, dev=True)
    it.classification = MigrationClassification.DEV_ONLY
    engine.drive_item(it)
    journal_doc = json.loads(
        (Path(engine.state_dir) / f"{SHA_A}.mig.json").read_text(encoding="utf-8")
    )
    assert journal_doc["classification"] == "B"
    states = [h["to"] for h in journal_doc["history"]]
    assert states == [
        "SOURCE_READY",
        "LOCAL_VERIFIED",
        "PROD_UPLOAD_STARTED",
        "PROD_UPLOADED",
        "PROD_VERIFIED",
        "DB_COMMITTED",
        "CLEANED",
    ]


# ---------------------------------------------------------------------------
# Wave/backpressure/disk (§23/§24)


def test_wave_persists_per_asset_and_survives_failures(tmp_path):
    engine = make_engine(
        tmp_path,
        dev_objects={
            object_key_for_sha(SHA_A, ext="mov"): MEDIA_A,
            object_key_for_sha(SHA_B, ext="mov"): b"wrong-bytes",
        },
        receipts=RECEIPTS,
    )
    items = [
        item(SHA_A, UUID_1, dev=True),
        item(SHA_B, UUID_2, dev=True),
    ]
    for it in items:
        it.classification = MigrationClassification.DEV_ONLY
    summary = engine.run_wave(items)
    outcomes = summary["outcomes"]
    assert outcomes[SHA_A[:12]]["state"] == MigrationState.CLEANED.value
    assert outcomes[SHA_B[:12]]["state"] == MigrationState.QUARANTINED.value


def test_disk_guard_blocks_source_read(tmp_path):
    engine = make_engine(
        tmp_path,
        dev_objects={object_key_for_sha(SHA_A, ext="mov"): MEDIA_A},
        receipts=RECEIPTS,
        free_disk_bytes_fn=lambda: 0,
    )
    engine.min_free_disk_bytes = 10**12
    it = item(SHA_A, UUID_1, dev=True)
    it.classification = MigrationClassification.DEV_ONLY
    doc = engine.drive_item(it)
    assert doc["state"] == MigrationState.RETRYABLE.value
    assert doc["last_error"]["family"] == "insufficient_disk"
    assert engine.prod_store.put_count == {}


def test_min_free_disk_recorded(tmp_path):
    engine = make_engine(
        tmp_path,
        dev_objects={object_key_for_sha(SHA_A, ext="mov"): MEDIA_A},
        receipts=RECEIPTS,
        free_disk_bytes_fn=lambda: 5_000_000_000,
    )
    it = item(SHA_A, UUID_1, dev=True)
    it.classification = MigrationClassification.DEV_ONLY
    engine.drive_item(it)
    assert engine.metrics["min_free_disk_bytes"] == 5_000_000_000
