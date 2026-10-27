"""Bounded, opt-in post-ingest Photos cleanup. No library discovery or B2 deletion."""
import fcntl
import hashlib
import itertools
import json
import math
import os
import re
import tempfile
import time
import subprocess
import sys
from pathlib import Path

from .sync_client import _curl_post

UUID_RE = re.compile(r"^[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}$")
# Bound per-request work and memory: the pending queue never grows past this.
MAX_PENDING = 100


def atomic_json(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".cleanup-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(document, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class PhotoKitLibrary:
    """Supported PhotoKit calls only; import lazily for portable tests."""

    def __init__(self):
        import Photos
        self.api = Photos
        if Photos.PHPhotoLibrary.authorizationStatusForAccessLevel_(Photos.PHAccessLevelReadWrite) != 3:
            raise RuntimeError("photos_read_write_permission_required")

    def asset(self, uuid):
        # UUID alone is not a full PhotoKit localIdentifier on macOS.
        result = self.api.PHAsset.fetchAssetsWithLocalIdentifiers_options_([uuid + "/L0/001"], None)
        return result.firstObject()

    def version(self, uuid):
        asset = self.asset(uuid)
        if asset is None:
            return None
        if asset.mediaType() != self.api.PHAssetMediaTypeVideo:
            raise RuntimeError("not_a_video")
        date = asset.modificationDate()
        if date is None:
            raise RuntimeError("asset_version_unavailable")
        return float(date.timeIntervalSince1970())

    def remove(self, uuid, expected_version):
        self.remove_many([(uuid, expected_version)])

    def remove_many(self, assets):
        # Keep a native Photos prompt/hang outside the daemon. Killing this
        # helper does not authorize a retry without rechecking the asset.
        try:
            result = subprocess.run(
                [sys.executable, "-m", "src.photos_cleanup", "--batch"],
                cwd=Path(__file__).resolve().parent.parent,
                input=json.dumps(assets), capture_output=True, text=True, timeout=55)
        except subprocess.TimeoutExpired:
            raise RuntimeError("photos_removal_timeout") from None
        if result.returncode:
            raise RuntimeError("photos_removal_refused")

    def _remove_in_helper(self, uuid, expected_version):
        self._remove_batch_in_helper([(uuid, expected_version)])

    def _remove_batch_in_helper(self, assets):
        completed = []
        refused = []

        def changes():
            # Refetch inside the change block, including the version check.
            selected = []
            for uuid, expected_version in assets:
                asset = self.asset(uuid)
                if asset is None or self.version(uuid) != expected_version:
                    refused.append(True)
                    return
                selected.append(asset)
            if os.environ.get("DIVE_PHOTOS_AUTOMATION_DIR"):
                if len(assets) != 1 or len(sys.argv) != 3 or sys.argv[1] != "--automated-batch":
                    raise RuntimeError("invalid_automated_batch")
                nonce = sys.argv[2]
                if not re.fullmatch(r"[a-f0-9]{32}", nonce):
                    raise RuntimeError("invalid_automation_nonce")
                atomic_json(Path(os.environ["DIVE_PHOTOS_AUTOMATION_DIR"]) / f"{nonce}.armed",
                            {"nonce": nonce, "pid": os.getpid(), "count": 1, "created_at": time.time()})
            self.api.PHAssetChangeRequest.deleteAssets_(selected)

        self.api.PHPhotoLibrary.sharedPhotoLibrary().performChanges_completionHandler_(
            changes, lambda success, error: completed.append(
                (bool(success), str(error.domain()) if error else None, int(error.code()) if error else None)))
        from Foundation import NSDate, NSRunLoop
        deadline = time.monotonic() + 45
        while not completed and time.monotonic() < deadline:
            NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.1))
        if refused:
            raise RuntimeError("asset_changed")
        if not completed:
            raise RuntimeError("photos_removal_timeout")
        if not completed[0][0] or completed[0][1] is not None:
            raise RuntimeError(f"photos_removal_failed:{completed[0][1]}:{completed[0][2]}")


class PhotosCleanup:
    def __init__(self, config, library_factory=None, snapshot=None, check=None):
        self.config = config
        self.options = config.dual_write
        self.mode = getattr(self.options, "photos_cleanup_mode", "off")
        if self.mode not in ("off", "dry_run", "delete"):
            raise ValueError("invalid_cleanup_mode")
        self.root = Path(config.object_store.state_dir).expanduser()
        self.queue = self.root / "photos_cleanup" / "pending"
        self.automated = getattr(self.options, "photos_cleanup_automated", False)
        if library_factory is None:
            library_factory = PhotoKitLibrary
        self.library_factory = library_factory
        self.snapshot = snapshot or self._snapshot
        self.check = check or self._check

    def _snapshot(self, uuid):
        from .ingest.canary import get_photos_db, edit_fingerprint
        matches = get_photos_db(self.config.photos.library_path).photos(uuid=[uuid])
        if len(matches) != 1 or not matches[0].ismovie:
            raise RuntimeError("asset_unknown_or_not_video")
        photo = matches[0]
        # An adjusted clip must have a readable recipe: the legacy fingerprint
        # can otherwise fall back to just duration and miss a same-length edit.
        if photo.hasadjustments:
            recipe = getattr(photo, "adjustments_path", None)
            if not recipe or not Path(recipe).is_file():
                raise RuntimeError("edit_recipe_unavailable")
            Path(recipe).read_bytes()
        return {"caption_sha256": hashlib.sha256((photo.description or "").encode()).hexdigest(),
                "edit_fingerprint": edit_fingerprint(photo)}

    def _check(self, request):
        server = self.config.server
        status, body = _curl_post(server.url.rstrip("/") + "/api/v1/media/backbone/photos-cleanup/check",
                                  request, server.api_key, 30, server.ca_cert_path)
        if status != 200:
            raise RuntimeError("server_check_unavailable")
        return json.loads(body)

    def capture_export_guard(self, uuid):
        from .ingest.canary import get_photos_db
        library = self.library_factory()
        version = library.version(uuid)
        snapshot = self.snapshot(uuid)
        matches = get_photos_db(self.config.photos.library_path).photos(uuid=[uuid])
        if version is None or len(matches) != 1 or library.version(uuid) != version:
            raise RuntimeError("asset_changed")
        return {"photos_uuid": uuid, "version": version, "snapshot": snapshot,
                "edited": bool(matches[0].hasadjustments)}

    def finish_export_guard(self, guard, source):
        from .ingest.content_addr import sha256_file
        if (self.library_factory().version(guard["photos_uuid"]) != guard["version"]
                or self.snapshot(guard["photos_uuid"]) != guard["snapshot"]):
            raise RuntimeError("asset_changed")
        return dict(guard, source_sha256=sha256_file(source))

    def enqueue(self, video_uuid, photos_uuid):
        if self.mode == "off":
            return
        if not UUID_RE.fullmatch(video_uuid) or not UUID_RE.fullmatch(photos_uuid):
            raise ValueError("invalid_cleanup_identity")
        if (not self.options.continuous_new_ingest
                or self.config.object_store.environment != "prod"):
            raise ValueError("cleanup_requires_continuous_prod_ingest")
        journal = json.loads((self.root / f"{video_uuid}.json").read_text())
        receipt = json.loads((self.root / f"{video_uuid}.commit_receipt.json").read_text())
        payload = receipt["input"]["payload"]
        extra = receipt["input"]["extra"]
        media = journal["media"]
        stage = json.loads((self.root / f"{video_uuid}.stage.json").read_text())
        guard = stage.get("cleanup_export_guard") or {}
        if (guard.get("photos_uuid") != photos_uuid
                or guard.get("source_sha256") != media["sha256"]):
            raise ValueError("cleanup_fresh_export_unproven")
        if (journal.get("video_uuid") != video_uuid or journal.get("state") != "CACHE_CLEANED"
                or journal.get("remote", {}).get("verified") is not True
                or journal.get("db_commit", {}).get("committed") is not True
                or payload.get("video_uuid") != video_uuid
                or extra.get("environment") != "prod"
                or payload.get("rendition_semantics") != "photos_edited_rendition"
                or receipt["result"].get("blob_sha256") != media["sha256"]
                or payload["blob"]["sha256"] != media["sha256"]
                or payload["blob"]["byte_size"] != media["byte_size"]
                or payload["blob"]["object_key"] != media["object_key"]
                or payload["caption"]["sha256"] != journal["caption"]["sha256"]
                or extra.get("source_provenance", {}).get("photos_asset_uuid", "").upper() != photos_uuid.upper()):
            raise ValueError("cleanup_ingest_proof_mismatch")
        request = {"video_uuid": video_uuid, "photos_uuid": photos_uuid,
                   "agent_id": self.config.agent.id,
                   "keeper_diver_id": self.options.photos_cleanup_keeper_diver_id,
                   "blob_sha256": media["sha256"], "byte_size": media["byte_size"],
                   "object_key": media["object_key"], "bucket": payload["blob"]["bucket"],
                   "caption_sha256": payload["caption"]["sha256"],
                   "edit_fingerprint": extra["photos_edit_fingerprint"]}
        # Pin the PhotoKit version now, so a later edit (even reverted) blocks cleanup.
        library = self.library_factory()
        version = library.version(photos_uuid)
        if (version is None or version != guard.get("version")
                or guard.get("snapshot") != {
                    "caption_sha256": request["caption_sha256"], "edit_fingerprint": request["edit_fingerprint"]}
                or self.snapshot(photos_uuid) != {
                "caption_sha256": request["caption_sha256"], "edit_fingerprint": request["edit_fingerprint"]}):
            raise ValueError("cleanup_asset_changed")
        path = self.queue / f"{video_uuid}.json"
        if not path.exists():
            if self.queue.exists():
                pending = sum(1 for _ in zip(self.queue.glob("*.json"), range(MAX_PENDING + 1)))
                if pending > MAX_PENDING:
                    raise ValueError("cleanup_queue_full")
            atomic_json(path, {"request": request, "version": version,
                               "created_at": time.time(), "attempts": 0})

    def process_pending(self):
        if self.mode == "off" or not self.queue.exists():
            return
        with (self.queue.parent / "worker.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            # Bounded work, no historical journal scanning. Retry with cooldown.
            # Never enumerate more than the cap plus one batch: enqueue refuses
            # beyond MAX_PENDING, so this covers the whole queue in steady state
            # while keeping memory bounded even for a legacy oversized backlog.
            paths = sorted(itertools.islice(self.queue.glob("*.json"), MAX_PENDING + 5))
            count = 0
            prepared = []
            for path in paths:
                try:
                    item = json.loads(path.read_text())
                    if (not isinstance(item, dict) or type(item.get("attempts")) is not int
                            or item["attempts"] < 0 or type(item.get("last_attempt", 0)) not in (int, float)
                            or not math.isfinite(item.get("last_attempt", 0))):
                        continue
                except (OSError, ValueError):
                    continue  # one damaged item must not starve the remaining queue
                if time.time() - item.get("last_attempt", 0) < 300:
                    continue
                self._process(path, item, prepared)
                count += 1
                if count >= (1 if self.automated and self.mode == "delete" else 5):
                    break
            if prepared:
                try:
                    assets = [(item["request"]["photos_uuid"], item["version"]) for path, item in prepared]
                    if self.automated:
                        from .photos_automation import PhotosAutomation
                        PhotosAutomation(self.root).remove_many(assets, lambda: self._revalidate(prepared))
                    else:
                        self.library_factory().remove_many(assets)
                    if any(self.library_factory().version(uuid) is not None for uuid, _ in assets):
                        raise RuntimeError("photos_removal_not_confirmed")
                    for path, item in prepared:
                        item["outcome"] = "removed"
                        atomic_json(self.queue.parent / "completed" / path.name, item)
                        path.unlink()
                except Exception as exc:
                    allowed = {"cleanup_automation_deferred:" + phase for phase in (
                        "authentication", "unlock", "ui_preflight", "revalidation", "native_start", "confirmation", "native_completion")}
                    allowed |= {"cleanup_unlock_blocked", "cleanup_ui_helper_missing", "cleanup_operator_connected",
                                "cleanup_keychain_unavailable", "cleanup_console_session_unavailable"}
                    reason = str(exc) if str(exc) in allowed else "photos_batch_pending_or_refused"
                    for path, item in prepared:
                        item["outcome"] = "deferred"
                        item["reason"] = reason
                        atomic_json(path, item)

    def _revalidate(self, prepared):
        # Unlock/Keychain/UI preparation may take seconds. Refresh server identity
        # and local metadata after that wait, before starting the native request.
        for _, item in prepared:
            request = item["request"]
            result = self.check(request)
            if result.get("eligible") is not True or any(
                    result.get(key) != request[key] for key in ("video_uuid", "photos_uuid", "blob_sha256")):
                raise RuntimeError("cleanup_authorization_changed")
            if self.library_factory().version(request["photos_uuid"]) != item["version"] or self.snapshot(request["photos_uuid"]) != {
                    "caption_sha256": request["caption_sha256"], "edit_fingerprint": request["edit_fingerprint"]}:
                raise RuntimeError("asset_changed")

    def _process(self, path, item, prepared):
        item["last_attempt"] = time.time()
        item["attempts"] += 1
        try:
            request = item["request"]
            uuid = request["photos_uuid"]
            if (not UUID_RE.fullmatch(uuid) or not UUID_RE.fullmatch(request["video_uuid"])
                    or path.stem != request["video_uuid"]
                    or request["keeper_diver_id"] != self.options.photos_cleanup_keeper_diver_id
                    or not self.options.continuous_new_ingest
                    or self.config.object_store.environment != "prod"):
                raise ValueError("cleanup_configuration_changed")
            library = self.library_factory()
            version = library.version(uuid)
            if version is None:
                outcome = "already_absent"
            else:
                if version != item["version"] or self.snapshot(uuid) != {
                        "caption_sha256": request["caption_sha256"], "edit_fingerprint": request["edit_fingerprint"]}:
                    raise ValueError("asset_changed")
                result = self.check(request)
                if result.get("eligible") is not True:
                    if result.get("reason") in {"person_not_exclusive", "kept_or_unknown_diver", "ambiguous_person", "ambiguous_dive",
                                                "metadata_changed", "revision_changed_or_missing"}:
                        item["outcome"] = "kept"
                        item["reason"] = result["reason"]
                        atomic_json(self.queue.parent / "completed" / path.name, item)
                        path.unlink()
                        return
                    # Recheck a server refusal later: metadata may still be syncing.
                    raise RuntimeError("server_refused:" + str(result.get("reason", "unknown")))
                if any(result.get(key) != request[key] for key in ("video_uuid", "photos_uuid", "blob_sha256")):
                    raise ValueError("server_identity_mismatch")
                if self.mode == "dry_run":
                    item["outcome"] = "would_remove"
                    atomic_json(path, item)
                    return
                # Close the server-check window with fresh Photos reads.
                if library.version(uuid) != version or self.snapshot(uuid) != {
                        "caption_sha256": request["caption_sha256"], "edit_fingerprint": request["edit_fingerprint"]}:
                    raise ValueError("asset_changed")
                # One native request per batch: one system confirmation.
                prepared.append((path, item))
                atomic_json(path, item)
                return
            item["outcome"] = outcome
            atomic_json(self.queue.parent / "completed" / path.name, item)
            path.unlink()
        except Exception as exc:
            # Record only controlled reasons; never captions, URLs, or credentials.
            item["outcome"] = "deferred"
            reasons = {"asset_changed", "server_identity_mismatch", "cleanup_configuration_changed"}
            server_reasons = {"keeper_not_primary", "asset_unknown", "local_identity_unconfirmed", "ambiguous_dive",
                "person_not_exclusive", "kept_or_unknown_diver", "ambiguous_person", "metadata_changed",
                "revision_changed_or_missing", "durable_backup_unconfirmed", "backup_location_changed"}
            detail = str(exc)
            item["reason"] = detail if detail in reasons or detail in {"server_refused:" + r for r in server_reasons} else type(exc).__name__
            atomic_json(path, item)


async def run_photos_cleanup_loop(config, stop_event):
    import asyncio
    import logging
    if getattr(config.dual_write, "photos_cleanup_mode", "off") == "off":
        return
    worker = PhotosCleanup(config)
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(worker.process_pending)
        except Exception:
            logging.getLogger(__name__).warning("Photos cleanup deferred")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=300)
        except asyncio.TimeoutError:
            pass


if __name__ == "__main__":
    import math
    if sys.argv[1:] != ["--batch"] and not (len(sys.argv) == 3 and sys.argv[1] == "--automated-batch" and re.fullmatch(r"[a-f0-9]{32}", sys.argv[2])):
        raise SystemExit("expected --batch with bounded JSON on stdin")
    assets = json.loads(sys.stdin.read(4096))
    if not isinstance(assets, list) or not 1 <= len(assets) <= 5:
        raise SystemExit("invalid Photos batch")
    for uuid, version in assets:
        if not UUID_RE.fullmatch(uuid) or not isinstance(version, (int, float)) or not math.isfinite(version) or version <= 0:
            raise SystemExit("invalid Photos asset/version")
    if len({uuid.upper() for uuid, _ in assets}) != len(assets):
        raise SystemExit("duplicate Photos asset")
    if sys.argv[1] == "--automated-batch" and (len(assets) != 1 or not os.environ.get("DIVE_PHOTOS_AUTOMATION_DIR")):
        raise SystemExit("invalid automated batch")
    try:
        PhotoKitLibrary()._remove_batch_in_helper(assets)
    except Exception as exc:
        if sys.argv[1] == "--automated-batch":
            atomic_json(Path(os.environ["DIVE_PHOTOS_AUTOMATION_DIR"]) / f"{sys.argv[2]}.failure",
                        {"error_type": type(exc).__name__, "reason": str(exc) if str(exc) in {
                            "photos_read_write_permission_required", "asset_changed", "photos_removal_timeout"} else "native_refused"})
        raise SystemExit(1)
