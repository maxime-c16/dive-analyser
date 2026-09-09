"""Ingest coordinator: deterministic, restart-safe orchestration.

Consumes already-materialized bytes (no duplicate Photos/iCloud downloads):
the coordinator materializes via the injected materialize_fn exactly once and
hashes once. Persists a transition record before/after each side effect so a
restart converges to ONE logical result (single blob/revision/caption revision,
no duplicate upload, no premature temp deletion).
"""

import shutil
from pathlib import Path
from typing import Any, Callable

from .caption import CaptionProvider
from .content_addr import object_key_for_sha, sha256_bytes, sha256_file, validate_sha256
from .errors import ObjectStoreError, ObjectStoreVerificationError
from .objectstore.base import ObjectStore
from .state_store import IngestStateStore
from .states import IngestState

RENDITION_SEMANTICS = "photos_edited_rendition"
INGEST_IMPL_VERSION = "media_backbone_v1"

RETRYABLE_FAMILIES = {
    "object_store_unavailable",
    "insufficient_disk",
    "db_commit_unavailable",
}
STATE_NEEDS_TEMP = (
    IngestState.MEDIA_MATERIALIZED,
    IngestState.LOCAL_HASHED,
    IngestState.REMOTE_UPLOAD_STARTED,
)


class InjectedCrash(Exception):
    """Simulated process crash for state-machine failure tests."""


class IngestFatalError(Exception):
    """Non-retryable ingest condition: quarantine, do not retry."""


class ObjectStoreIngestCoordinator:
    def __init__(
        self,
        video_uuid: str,
        state_store: IngestStateStore,
        object_store: ObjectStore,
        materialize_fn: Callable[[str, Path], Path],
        commit_db_fn: Callable[[dict[str, Any]], Any],
        temp_root: Path,
        caption_provider: CaptionProvider | None = None,
        min_free_disk_bytes: int = 0,
        free_disk_bytes_fn: Callable[[], int] | None = None,
        failpoints: dict[str, str] | None = None,
        storage_backend: str = "b2",
        bucket: str = "",
        skip_put_if_remote_present: bool = False,
    ):
        self.video_uuid = video_uuid
        self.store = state_store
        self.object_store = object_store
        self.materialize_fn = materialize_fn
        self.commit_db_fn = commit_db_fn
        self.caption_provider = caption_provider
        self.temp_root = Path(temp_root)
        self.workdir = self.temp_root / video_uuid
        self.min_free_disk_bytes = int(min_free_disk_bytes)
        self._free_disk_bytes_fn = free_disk_bytes_fn
        self.failpoints = failpoints or {}
        self.storage_backend = storage_backend
        self.bucket = bucket
        self.skip_put_if_remote_present = bool(skip_put_if_remote_present)
        self.store.load(video_uuid)
        if self.store.state is IngestState.DISCOVERED:
            self._remove_workdir()

    def run_once(self) -> IngestState:
        if self.store.state.is_terminal:
            return self.store.state
        self._reconcile_stale_temp()
        while not self.store.state.is_terminal:
            state = self.store.state
            try:
                self._step(state)
            except InjectedCrash:
                raise
            except IngestFatalError as exc:
                self.store.quarantine("ingest_fatal", str(exc))
                return self.store.state
            except ObjectStoreVerificationError as exc:
                self.store.quarantine("verification_failed", str(exc))
                return self.store.state
            except ObjectStoreError as exc:
                self.store.record_retryable_error("object_store_unavailable", str(exc))
                return self.store.state
            except PermissionError as exc:
                self.store.record_retryable_error("insufficient_disk", str(exc))
                return self.store.state
        return self.store.state

    def _step(self, state: IngestState) -> None:
        if state is IngestState.DISCOVERED:
            self._failpoint(f"{state.value}:before_effect")
            self._capture_caption()
            self._failpoint(f"{state.value}:after_effect")
            self._transition(IngestState.CAPTION_CAPTURED)
        elif state is IngestState.CAPTION_CAPTURED:
            self._failpoint(f"{state.value}:before_effect")
            self._transition(IngestState.MEDIA_REQUESTED)
        elif state is IngestState.MEDIA_REQUESTED:
            self._failpoint(f"{state.value}:before_effect")
            self._check_free_disk()
            path = self._materialize()
            self._failpoint(f"{state.value}:after_effect")
            self._transition(
                IngestState.MEDIA_MATERIALIZED,
                media={"temp_path": str(path), "byte_size": path.stat().st_size},
            )
        elif state is IngestState.MEDIA_MATERIALIZED:
            self._failpoint(f"{state.value}:before_effect")
            path = Path(self.store.doc["media"]["temp_path"])
            digest = sha256_file(path)
            ext = path.suffix.lstrip(".").lower() or None
            key = object_key_for_sha(digest, ext=ext)
            self._failpoint(f"{state.value}:after_effect")
            media = dict(self.store.doc.get("media") or {})
            media["sha256"] = digest
            media["object_key"] = key
            self._transition(IngestState.LOCAL_HASHED, media=media)
        elif state is IngestState.LOCAL_HASHED:
            self._failpoint(f"{state.value}:before_effect")
            self._transition(IngestState.REMOTE_UPLOAD_STARTED)
        elif state is IngestState.REMOTE_UPLOAD_STARTED:
            self._failpoint(f"{state.value}:before_effect")
            media = self.store.doc["media"]
            remote = dict(self.store.doc.get("remote") or {})
            put_skipped = False
            # Content-dedupe opt-in (P3): if a verified content-addressed object
            # with the same key AND size already exists, skip the re-PUT. The
            # full-GET roundtrip verification below still proves integrity
            # (fail closed on any mismatch), so no verification is weakened.
            if self.skip_put_if_remote_present:
                head = self.object_store.head(media["object_key"])
                if head is not None and head.byte_size == media["byte_size"]:
                    put_skipped = True
            if not put_skipped:
                path = Path(media["temp_path"])
                result = self.object_store.put(media["object_key"], path)
                remote["last_put_sha256"] = result.sha256
            remote["attempts"] = int(remote.get("attempts", 0)) + 1
            remote["last_put_skipped_existing"] = put_skipped
            self._failpoint(f"{state.value}:after_effect")
            self._transition(IngestState.REMOTE_UPLOADED, remote=remote)
        elif state is IngestState.REMOTE_UPLOADED:
            self._failpoint(f"{state.value}:before_effect")
            self._verify_remote()
            self._failpoint(f"{state.value}:after_effect")
            remote = dict(self.store.doc.get("remote") or {})
            remote["verified"] = True
            self._transition(IngestState.REMOTE_VERIFIED, remote=remote)
        elif state is IngestState.REMOTE_VERIFIED:
            self._failpoint(f"{state.value}:before_effect")
            self.commit_db_fn(self._db_payload())
            self._failpoint(f"{state.value}:after_effect")
            self._transition(IngestState.DB_COMMITTED, db_commit={"committed": True})
        elif state is IngestState.DB_COMMITTED:
            self._failpoint(f"{state.value}:before_effect")
            self._cleanup_temp()
            self._failpoint(f"{state.value}:after_effect")
            self._transition(IngestState.CACHE_CLEANED, media_cleaned=True)
        else:
            raise ObjectStoreError(f"unknown ingest state: {state}")

    def _capture_caption(self) -> None:
        if self.caption_provider is None:
            raise ObjectStoreError("caption provider not configured")
        result = self.caption_provider.get_caption(self.video_uuid)
        if (
            not result.available
            or not result.sha256
            or result.effectively_empty
        ):
            raise IngestFatalError(
                f"caption_unavailable: {result.provider}:{result.error}"
            )
        validate_sha256(result.sha256)
        self.store.doc["caption"] = {
            "provider": result.provider,
            "raw": result.raw,
            "sha256": result.sha256,
        }
        self.store.persist()

    def _check_free_disk(self) -> None:
        if self.min_free_disk_bytes <= 0:
            return
        free = (
            self._free_disk_bytes_fn()
            if self._free_disk_bytes_fn
            else shutil.disk_usage(self.temp_root).free
        )
        if free < self.min_free_disk_bytes:
            raise PermissionError(
                f"min_free_disk_bytes guard: {free} < {self.min_free_disk_bytes}"
            )

    def _materialize(self) -> Path:
        self.workdir.mkdir(parents=True, exist_ok=True)
        path = self.materialize_fn(self.video_uuid, self.workdir)
        if not path or not Path(path).is_file() or Path(path).stat().st_size == 0:
            raise ObjectStoreError("materialization produced no usable file")
        return Path(path)

    def _verify_remote(self) -> None:
        media = self.store.doc["media"]
        remote_bytes = self.object_store.get(media["object_key"])
        remote_sha = sha256_bytes(remote_bytes)
        if remote_sha != media["sha256"] or len(remote_bytes) != media["byte_size"]:
            raise ObjectStoreVerificationError(
                f"roundtrip mismatch: local={media['sha256']} remote={remote_sha}"
            )

    def _cleanup_temp(self) -> None:
        if self.store.doc.get("db_commit", {}).get("committed") and self.store.doc.get(
            "remote", {}
        ).get("verified"):
            self._remove_workdir()

    def _db_payload(self) -> dict[str, Any]:
        doc = self.store.doc
        media = doc["media"]
        caption = doc["caption"]
        return {
            "video_uuid": self.video_uuid,
            "ingest_impl_version": INGEST_IMPL_VERSION,
            "rendition_semantics": RENDITION_SEMANTICS,
            "caption": {
                "raw": caption["raw"],
                "sha256": caption["sha256"],
                "provider": caption["provider"],
            },
            "blob": {
                "sha256": media["sha256"],
                "byte_size": media["byte_size"],
                "object_key": media["object_key"],
                "storage_backend": self.storage_backend,
                "bucket": self.bucket,
            },
            "remote_verified": bool((doc.get("remote") or {}).get("verified")),
        }

    def _transition(self, next_state: IngestState, **fields: Any) -> None:
        self.store.transition(next_state, **fields)

    def _reconcile_stale_temp(self) -> None:
        doc = self.store.doc
        media = doc.get("media")
        if self.store.state in STATE_NEEDS_TEMP and media:
            temp_path = media.get("temp_path")
            if not temp_path or not Path(temp_path).is_file():
                self.store.reconcile_to_media_requested("stale_temp_rematerialize")

    def _remove_workdir(self) -> None:
        if self.workdir.exists():
            shutil.rmtree(self.workdir, ignore_errors=True)

    def _failpoint(self, name: str) -> None:
        if self.failpoints.get(name) == "raise":
            raise InjectedCrash(name)
