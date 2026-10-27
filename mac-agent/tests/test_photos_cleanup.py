import json
from types import SimpleNamespace as NS

import pytest

from src.config import DualWriteConfig
from src.photos_cleanup import PhotosCleanup, atomic_json

VIDEO = "11111111-1111-1111-1111-111111111111"
LOCAL = "22222222-2222-2222-2222-222222222222"
SHA = "a" * 64
CAPTION = "b" * 64
EDIT = "c" * 64


@pytest.fixture
def cleanup(tmp_path):
    config = NS(dual_write=DualWriteConfig(enabled=True, continuous_new_ingest=True,
                photos_cleanup_mode="delete", photos_cleanup_keeper_diver_id=1),
                object_store=NS(state_dir=str(tmp_path), environment="prod"),
                agent=NS(id="mac-media-01"))
    library = NS(current=123., removed=[])
    library.version = lambda uuid: library.current

    def remove(uuid, expected):
        assert expected == library.current
        library.removed.append(uuid)
        library.current = None

    library.remove = remove
    library.remove_many = lambda assets: [library.remove(uuid, version) for uuid, version in assets]
    snapshot = {"caption_sha256": CAPTION, "edit_fingerprint": EDIT}
    response = {"eligible": True, "video_uuid": VIDEO, "photos_uuid": LOCAL, "blob_sha256": SHA}
    worker = PhotosCleanup(config, lambda: library, lambda uuid: dict(snapshot), lambda req: dict(response))
    blob = {"sha256": SHA, "byte_size": 100, "object_key": "blobs/test.mov", "bucket": "prod"}
    journal = {"video_uuid": VIDEO, "state": "CACHE_CLEANED", "remote": {"verified": True},
               "db_commit": {"committed": True}, "media": blob, "caption": {"sha256": CAPTION}}
    receipt = {"input": {"payload": {"video_uuid": VIDEO, "blob": blob,
               "caption": {"sha256": CAPTION}, "rendition_semantics": "photos_edited_rendition"},
               "extra": {"environment": "prod", "photos_edit_fingerprint": EDIT,
                         "source_provenance": {"photos_asset_uuid": LOCAL}}},
               "result": {"blob_sha256": SHA}}
    atomic_json(tmp_path / f"{VIDEO}.json", journal)
    atomic_json(tmp_path / f"{VIDEO}.commit_receipt.json", receipt)
    atomic_json(tmp_path / f"{VIDEO}.stage.json", {"cleanup_export_guard": {
        "photos_uuid": LOCAL, "source_sha256": SHA, "version": library.current,
        "snapshot": dict(snapshot)}})
    return worker, library, snapshot, response


def test_verified_cleanup_is_idempotent_and_uses_local_identity(cleanup):
    worker, library, *_ = cleanup
    worker.enqueue(VIDEO, LOCAL)
    worker.process_pending()
    worker.process_pending()
    assert library.removed == [LOCAL]
    assert json.loads((worker.queue.parent / "completed" / f"{VIDEO}.json").read_text())["outcome"] == "removed"


def test_off_does_not_inspect_photos_or_proofs(cleanup):
    worker, library, *_ = cleanup
    worker.mode = "off"
    worker.enqueue("not-valid", "not-valid")
    worker.process_pending()
    assert not worker.queue.exists() and not library.removed


def test_dry_run_retains_clip_and_can_later_be_applied(cleanup):
    worker, library, *_ = cleanup
    worker.mode = "dry_run"
    worker.enqueue(VIDEO, LOCAL)
    worker.process_pending()
    path = worker.queue / f"{VIDEO}.json"
    item = json.loads(path.read_text())
    assert item["outcome"] == "would_remove" and not library.removed
    item["last_attempt"] = 0
    atomic_json(path, item)
    worker.mode = "delete"
    worker.process_pending()
    assert library.removed == [LOCAL]


@pytest.mark.parametrize("change", ["unverified", "uncommitted", "wrong_blob", "dev", "wrong_identity", "wrong_caption", "unfinished"])
def test_enqueue_rejects_incomplete_or_mixed_proofs(cleanup, change):
    worker, library, *_ = cleanup
    journal_path = worker.root / f"{VIDEO}.json"
    receipt_path = worker.root / f"{VIDEO}.commit_receipt.json"
    journal, receipt = json.loads(journal_path.read_text()), json.loads(receipt_path.read_text())
    if change == "unverified": journal["remote"]["verified"] = False
    if change == "uncommitted": journal["db_commit"]["committed"] = False
    if change == "wrong_blob": receipt["result"]["blob_sha256"] = "d" * 64
    if change == "dev": receipt["input"]["extra"]["environment"] = "dev"
    if change == "wrong_identity": receipt["input"]["extra"]["source_provenance"]["photos_asset_uuid"] = VIDEO
    if change == "wrong_caption": receipt["input"]["payload"]["caption"]["sha256"] = "e" * 64
    if change == "unfinished": journal["state"] = "REMOTE_VERIFIED"
    atomic_json(journal_path, journal)
    atomic_json(receipt_path, receipt)
    with pytest.raises(ValueError): worker.enqueue(VIDEO, LOCAL)
    assert not library.removed and not worker.queue.exists()


@pytest.mark.parametrize("change", ["version", "caption", "edit", "keeper", "server_no", "server_identity", "server_error"])
def test_changed_or_unconfirmed_clip_is_never_removed(cleanup, change):
    worker, library, snapshot, response = cleanup
    worker.enqueue(VIDEO, LOCAL)
    if change == "version": library.current += 1
    if change == "caption": snapshot["caption_sha256"] = "e" * 64
    if change == "edit": snapshot["edit_fingerprint"] = "e" * 64
    if change == "keeper": worker.options.photos_cleanup_keeper_diver_id = 2
    if change == "server_no": response["eligible"] = False
    if change == "server_identity": response["photos_uuid"] = VIDEO
    if change == "server_error": worker.check = lambda _: (_ for _ in ()).throw(OSError("private-url"))
    worker.process_pending()
    assert not library.removed
    assert "private-url" not in (worker.queue / f"{VIDEO}.json").read_text()


def test_edit_during_server_round_trip_blocks_cleanup(cleanup):
    worker, library, snapshot, response = cleanup
    worker.enqueue(VIDEO, LOCAL)
    def check(_):
        library.current += 1
        return response
    worker.check = check
    worker.process_pending()
    assert not library.removed


def test_pending_removal_retries_and_missing_asset_converges(cleanup):
    worker, library, *_ = cleanup
    worker.enqueue(VIDEO, LOCAL)
    library.remove = lambda *_: (_ for _ in ()).throw(RuntimeError("pending"))
    worker.process_pending()
    path = worker.queue / f"{VIDEO}.json"
    item = json.loads(path.read_text())
    assert item["outcome"] == "deferred"
    library.current = None  # lost response after successful system change
    item["last_attempt"] = 0
    atomic_json(path, item)
    worker.process_pending()
    assert not path.exists()


def test_stale_or_unproven_export_never_arms_cleanup(cleanup):
    worker, library, *_ = cleanup
    path = worker.root / f"{VIDEO}.stage.json"
    document = json.loads(path.read_text())
    document["cleanup_export_guard"]["source_sha256"] = "d" * 64
    atomic_json(path, document)
    with pytest.raises(ValueError, match="fresh_export_unproven"):
        worker.enqueue(VIDEO, LOCAL)
    assert not library.removed


def test_multiple_clips_use_one_native_batch(cleanup):
    worker, library, snapshot, response = cleanup
    worker.enqueue(VIDEO, LOCAL)
    first = json.loads((worker.queue / f"{VIDEO}.json").read_text())
    other = "33333333-3333-3333-3333-333333333333"
    first["request"]["video_uuid"] = other
    atomic_json(worker.queue / f"{other}.json", first)
    worker.check = lambda req: dict(response, video_uuid=req["video_uuid"])
    # Use two distinct local IDs; each must be prechecked and bound separately.
    first["request"]["photos_uuid"] = other
    atomic_json(worker.queue / f"{other}.json", first)
    worker.check = lambda req: dict(response, video_uuid=req["video_uuid"], photos_uuid=req["photos_uuid"])
    batches = []
    def batch(assets):
        batches.append(assets)
        library.current = None
    library.remove_many = batch
    worker.process_pending()
    assert len(batches) == 1 and {uuid for uuid, version in batches[0]} == {LOCAL, other}


def test_edited_export_selects_trimmed_video_instead_of_larger_original(tmp_path):
    from src.media_materializer import MediaMaterializer, MaterializationError
    materializer = MediaMaterializer(str(tmp_path), require_edited=True)
    (tmp_path / "original.mov").write_bytes(b"x" * 100000)
    with pytest.raises(MaterializationError):
        materializer._find_materialized_video(tmp_path)
    edited = tmp_path / "original_edited.mov"
    edited.write_bytes(b"x" * 20000)
    assert materializer._find_materialized_video(tmp_path) == edited


def test_export_guard_binds_exact_bytes_and_refuses_intervening_edit(cleanup, tmp_path):
    from src.ingest.content_addr import sha256_file
    worker, library, snapshot, _ = cleanup
    source = tmp_path / "export.mov"
    source.write_bytes(b"verified edited video")
    guard = {"photos_uuid": LOCAL, "version": library.current, "snapshot": dict(snapshot)}
    assert worker.finish_export_guard(guard, source)["source_sha256"] == sha256_file(source)
    library.current += 1
    with pytest.raises(RuntimeError, match="asset_changed"):
        worker.finish_export_guard(guard, source)


def test_native_batch_rechecks_every_version_before_requesting_removal(monkeypatch):
    import sys
    from src.photos_cleanup import PhotoKitLibrary
    monkeypatch.setitem(sys.modules, "Foundation", NS(NSDate=NS(), NSRunLoop=NS()))
    removed = []
    library = object.__new__(PhotoKitLibrary)
    library.asset = lambda uuid: uuid
    library.version = lambda uuid: 123.
    def perform(changes, completed):
        changes()
        completed(True, None)
    library.api = NS(PHAssetChangeRequest=NS(deleteAssets_=lambda assets: removed.append(assets)),
                     PHPhotoLibrary=NS(sharedPhotoLibrary=lambda: NS(performChanges_completionHandler_=perform)))
    with pytest.raises(RuntimeError, match="asset_changed"):
        library._remove_batch_in_helper([(VIDEO, 123.), (LOCAL, 124.)])
    assert removed == []
    library._remove_batch_in_helper([(VIDEO, 123.), (LOCAL, 123.)])
    assert removed == [[VIDEO, LOCAL]]


@pytest.mark.parametrize("options", [dict(photos_cleanup_mode="typo"),
    dict(photos_cleanup_mode="delete"),
    dict(enabled=True, continuous_new_ingest=True, photos_cleanup_mode="delete", photos_cleanup_keeper_diver_id=True)])
def test_configuration_fails_closed(options):
    with pytest.raises(ValueError): DualWriteConfig(**options)


def test_native_success_without_absence_does_not_mark_completed(cleanup):
    worker, library, *_ = cleanup
    worker.enqueue(VIDEO, LOCAL)
    library.remove_many = lambda assets: None
    worker.process_pending()
    assert json.loads((worker.queue / f"{VIDEO}.json").read_text())["outcome"] == "deferred"
    assert not (worker.queue.parent / "completed" / f"{VIDEO}.json").exists()


def test_authorization_is_rechecked_after_unlock(cleanup):
    worker, library, snapshot, response = cleanup
    worker.enqueue(VIDEO, LOCAL)
    item = json.loads((worker.queue / f"{VIDEO}.json").read_text())
    worker._revalidate([(None,item)])
    response["eligible"] = False
    with pytest.raises(RuntimeError, match="authorization_changed"):
        worker._revalidate([(None,item)])
    assert not library.removed


def test_corrupt_retry_timestamp_does_not_starve_valid_queue(cleanup):
    worker, library, *_ = cleanup
    worker.enqueue(VIDEO, LOCAL)
    atomic_json(worker.queue / '00000000-0000-0000-0000-000000000000.json',
                {'attempts':0,'last_attempt':'corrupt'})
    worker.process_pending()
    assert library.removed==[LOCAL]


@pytest.mark.parametrize('pending_count', [99, 100, 101])
def test_queue_admission_respects_the_100_entry_boundary(cleanup, pending_count):
    worker, library, *_ = cleanup
    worker.queue.mkdir(parents=True)
    for index in range(pending_count):
        (worker.queue / f'fixture-{index}.json').write_text('{}')
    if pending_count < 100:
        worker.enqueue(VIDEO, LOCAL)
        assert len(list(worker.queue.glob('*.json'))) == 100
    else:
        with pytest.raises(ValueError, match='cleanup_queue_full'):
            worker.enqueue(VIDEO, LOCAL)
        assert not (worker.queue / f'{VIDEO}.json').exists()
    assert not library.removed


def test_reenqueue_existing_clip_is_idempotent_at_capacity(cleanup):
    worker, library, *_ = cleanup
    worker.enqueue(VIDEO, LOCAL)
    path = worker.queue / f'{VIDEO}.json'
    original = path.read_bytes()
    for index in range(99):
        (worker.queue / f'fixture-{index}.json').write_text('{}')
    worker.enqueue(VIDEO, LOCAL)
    assert path.read_bytes() == original
    assert len(list(worker.queue.glob('*.json'))) == 100
    assert not library.removed
