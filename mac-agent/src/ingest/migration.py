"""P7 historical media migration engine (copy-only, DB-driven, additive).

Packet: MEDIA_BACKBONE_P7_ACCELERATED_CONTINUOUS_INGEST_MIGRATION_V1.

Scope authority: ONLY existing Dive Analyzer logical media whose
deterministic chain MediaRevision/video_uuid -> dives (UNIQUE video_uuid) ->
diver_id resolves to a bootstrapped OWNER diver. The backend DB/domain graph
defines the queue (authenticated inventory endpoint, agent API key); Photos is
a source/materialization provider, never the migration inventory authority.
No Photos-library crawl, ever.

Source priority per item (cheapest authoritative source preserving the
accepted edited-rendition identity):
  1. already verified PROD B2            -> skip (no byte ops, no uploads)
  2. PROD object present (HEAD) but location not committed
                                          -> full PROD GET verify -> commit
  3. verified DEV B2 replica (same SHA)  -> bounded-temp DEV GET -> SHA verify
                                            -> PROD PUT -> full PROD GET verify
     DEV read and PROD ingest are SEPARATE bucket-scoped credentials; no
     account-wide cross-bucket credential; no provider-side cross-bucket
     authority is relied upon.
  4. checksum-validated canonical local/vault bytes -> PROD upload
  5. targeted Photos edited-rendition materialization (production GUI-launchd
     runtime context, one asset at a time, bounded timeout/disk)

Invariants:
- copy-only: no remote delete/hide is callable from this module (the guarded
  delete primitive lives on the store adapter and is never imported here)
- every new PROD replica: source SHA A -> PUT -> full PROD GET -> SHA B,
  require A == B (byte_size too); ETags never substituted; mismatch ->
  QUARANTINED, batch continues
- idempotent: PROD HEAD before any PUT; verified-DB-location short-circuit;
  identical rerun converges with zero duplicate rows/objects/uploads
- caption authority: the EXACT provider caption string is required — reused
  from the original ingest receipts where available, else read fresh from the
  exact Photos provider; NEVER manufactured from normalized legacy text;
  unavailable -> DEFERRED/QUARANTINED with explicit reason
- restart safety: one durable per-blob journal (0600, atomic persist) is the
  ONLY orchestration authority; RETRYABLE resumes at the recorded state
- backpressure: strictly one active item, sequential, bounded waves, no RAM
  queue, no materializer/transcoder fanout; temp cleaned after verified commit
- legacy media and legacy authority untouched; no deletion of any kind
"""

import hashlib
import json
import logging
import os
import shutil
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from .canary import (
    build_stable_provider,
    edit_fingerprint,
    ffprobe_metadata,
    get_photos_db,
    load_env_file,
    parse_caption_metadata,
    photo_provenance,
    utcnow,
)
from .content_addr import object_key_for_sha, sha256_bytes
from .errors import (
    ConfigValidationError,
    ObjectStoreUnavailable,
    ObjectStoreVerificationError,
)
from .media_content_type import video_content_type
from .objectstore.b2 import B2Config, BackblazeB2Store

logger = logging.getLogger(__name__)

MIGRATION_JOURNAL_VERSION = "media_backbone_p7_migration_v1"
MIGRATION_COMMIT_IMPL_VERSION = "media_backbone_v1"
RENDITION_SEMANTICS = "photos_edited_rendition"
INGEST_RECEIPT_SUFFIXES = (".commit_input.json", ".mutation_input.json")
DEFAULT_EXTENSION = "mov"


class MigrationState(str, Enum):
    INVENTORIED = "INVENTORIED"
    SOURCE_READY = "SOURCE_READY"
    LOCAL_VERIFIED = "LOCAL_VERIFIED"
    PROD_UPLOAD_STARTED = "PROD_UPLOAD_STARTED"
    PROD_UPLOADED = "PROD_UPLOADED"
    PROD_VERIFIED = "PROD_VERIFIED"
    DB_COMMITTED = "DB_COMMITTED"
    CLEANED = "CLEANED"
    RETRYABLE = "RETRYABLE"
    QUARANTINED = "QUARANTINED"
    DEFERRED_INTERACTIVE = "DEFERRED_INTERACTIVE"
    SKIPPED_ALREADY_PROD = "SKIPPED_ALREADY_PROD"


TERMINAL_STATES = {
    MigrationState.CLEANED,
    MigrationState.SKIPPED_ALREADY_PROD,
    MigrationState.QUARANTINED,
    MigrationState.DEFERRED_INTERACTIVE,
}


class MigrationClassification(str, Enum):
    ALREADY_PROD = "A"
    DEV_ONLY = "B"
    LOCAL_SOURCE = "C"
    PHOTOS_ICLOUD = "D"
    CONFLICT = "E"
    MISSING = "F"


class MigrationPayloadUnavailable(Exception):
    """Exact caption authority could not be established (never manufactured)."""


@dataclass
class MigrationItem:
    """One logical media revision queued by the DB-driven inventory."""

    video_uuid: str
    blob_sha256: str
    byte_size: int = 0
    media_revision_id: int | None = None
    classification: MigrationClassification | None = None
    verified_prod: bool = False
    verified_dev: bool = False
    owner_diver: bool = True
    has_diver_chain: bool = True
    caption_provider: str | None = None
    prod_object_key: str | None = None
    dev_object_key: str | None = None
    extension: str = DEFAULT_EXTENSION

    @property
    def sha(self) -> str:
        return self.blob_sha256


class MigrationJournal:
    """Durable per-item migration state (0600, atomic, keyed by blob SHA).

    The ONLY orchestration authority for the migration: restart, resume, and
    rerun all decide from this file alone; the server DB remains the durable
    committed logical result authority.
    """

    def __init__(self, state_dir: Path, blob_sha256: str):
        self.state_dir = Path(state_dir)
        self.path = self.state_dir / f"{blob_sha256}.mig.json"
        self.doc: dict[str, Any] = {}

    def load(self) -> dict[str, Any]:
        if self.path.exists():
            try:
                self.doc = json.loads(self.path.read_text(encoding="utf-8"))
            except ValueError:
                self.doc = {}
        if not self.doc:
            self.doc = {
                "version": MIGRATION_JOURNAL_VERSION,
                "blob_sha256": self.sha,
                "state": MigrationState.INVENTORIED.value,
                "attempts": 0,
                "history": [],
                "created_at": utcnow(),
            }
        return self.doc

    @property
    def sha(self) -> str:
        return self.path.name[: -len(".mig.json")]

    @property
    def state(self) -> MigrationState:
        try:
            return MigrationState(self.doc.get("state"))
        except ValueError:
            return MigrationState.INVENTORIED

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def transition(self, new_state: MigrationState, **evidence) -> None:
        self.doc["history"].append(
            {
                "from": self.state.value,
                "to": new_state.value,
                "at": utcnow(),
                **{k: v for k, v in evidence.items() if v is not None},
            }
        )
        self.doc["state"] = new_state.value
        self.persist()

    def record_error(self, family: str, detail: str, retryable: bool) -> None:
        prior = self.state.value
        self.doc["attempts"] = int(self.doc.get("attempts", 0)) + 1
        self.doc["last_error"] = {
            "family": family,
            "detail": str(detail)[:300],
            "retryable": bool(retryable),
            "at": utcnow(),
        }
        if retryable:
            self.doc["resume_state"] = prior
            self.doc["state"] = MigrationState.RETRYABLE.value
        else:
            self.doc["state"] = MigrationState.QUARANTINED.value
        self.persist()

    def persist(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self.doc, fh, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, self.path)


class HistoricalMigrationEngine:
    """One-shot, sequential, restart-safe historical migration driver.

    Deliberately NOT a daemon component: one-shot invocations only, so the
    migration tooling can never become a second production ingest daemon.
    """

    def __init__(
        self,
        *,
        prod_store,
        dev_store=None,
        commit_fn: Callable[[dict[str, Any]], dict[str, Any]],
        state_dir: Path,
        temp_root: Path,
        vault_root: str | None = None,
        receipt_dirs: list[Path] | None = None,
        library_path: str | None = None,
        ffprobe_path: str = "ffprobe",
        materialize_fn: Callable[[str, Path], Path] | None = None,
        min_free_disk_bytes: int = 10 * 1024 * 1024 * 1024,
        prod_bucket: str = "",
        prod_environment: str = "prod",
        photos_probe: Callable[[str], bool] | None = None,
        free_disk_bytes_fn: Callable[[], int] | None = None,
    ):
        self.prod_store = prod_store
        self.dev_store = dev_store
        self.commit_fn = commit_fn
        self.state_dir = Path(state_dir)
        self.temp_root = Path(temp_root)
        self.vault_root = vault_root
        self.receipt_dirs = [Path(p) for p in (receipt_dirs or [])]
        self.library_path = library_path
        self.ffprobe_path = ffprobe_path
        self.materialize_fn = materialize_fn
        self.min_free_disk_bytes = int(min_free_disk_bytes)
        self.prod_bucket = prod_bucket
        self.prod_environment = prod_environment
        self._photos_probe = photos_probe
        self._free_disk_bytes_fn = free_disk_bytes_fn
        self.metrics: dict[str, Any] = {}
        self._content_types: dict[str, str | None] = {}

    # -- construction -------------------------------------------------------

    @classmethod
    def from_config(cls, config, commit_fn: Callable) -> "HistoricalMigrationEngine":
        cfg = getattr(config, "migration", None)
        os_cfg = config.object_store
        if cfg is None or not cfg.enabled:
            raise ConfigValidationError(
                "migration engine not enabled (migration.enabled=false)"
            )
        if os_cfg.environment != "prod":
            raise ConfigValidationError(
                "historical migration requires object_store.environment == 'prod'"
            )
        if not os_cfg.enabled:
            raise ConfigValidationError("historical migration requires object_store.enabled")
        prod_env = load_env_file(cfg.prod_env_file) if cfg.prod_env_file else {}
        prod_cfg = B2Config(
            environment="prod",
            bucket=os_cfg.bucket,
            region=os_cfg.region or None,
            endpoint_url=os_cfg.endpoint_url or None,
            prefix=os_cfg.prefix,
            presign_ttl_seconds=int(os_cfg.presign_ttl_seconds),
            max_retries=int(os_cfg.max_retries),
            access_key_id=prod_env.get("B2_APPLICATION_KEY_ID") or None,
            secret_access_key=prod_env.get("B2_APPLICATION_KEY") or None,
        )
        prod_store = BackblazeB2Store(prod_cfg)
        dev_store = None
        if cfg.dev_env_file:
            dev_bucket = cfg.dev_bucket
            if not dev_bucket:
                raise ConfigValidationError(
                    "migration.dev_env_file set but no DEV bucket configured"
                )
            dev_env = load_env_file(cfg.dev_env_file)
            dev_cfg = B2Config(
                environment="dev",
                bucket=dev_bucket,
                region=os_cfg.region or None,
                endpoint_url=os_cfg.endpoint_url or None,
                prefix=os_cfg.prefix,
                max_retries=int(os_cfg.max_retries),
                access_key_id=dev_env.get("B2_APPLICATION_KEY_ID") or None,
                secret_access_key=dev_env.get("B2_APPLICATION_KEY") or None,
            )
            dev_store = BackblazeB2Store(dev_cfg)
        return cls(
            prod_store=prod_store,
            dev_store=dev_store,
            commit_fn=commit_fn,
            state_dir=Path(cfg.state_dir).expanduser(),
            temp_root=Path(cfg.temp_root).expanduser(),
            vault_root=cfg.vault_root or None,
            receipt_dirs=cfg.receipt_dirs or [],
            library_path=config.photos.library_path,
            ffprobe_path=config.media.ffprobe_path,
            min_free_disk_bytes=int(cfg.min_free_disk_bytes),
            prod_bucket=prod_cfg.bucket,
        )

    # -- inventory classification ------------------------------------------

    def classify(self, items: list[MigrationItem]) -> list[MigrationItem]:
        """DB-driven classification (fail-closed ownership): ownership/chain
        conflicts -> E; verified PROD -> A; verified DEV -> B; local vault
        candidates -> C; Photos-reachable -> D; else F (missing)."""
        for item in items:
            if not item.has_diver_chain or not item.owner_diver:
                item.classification = MigrationClassification.CONFLICT
            elif item.verified_prod:
                item.classification = MigrationClassification.ALREADY_PROD
            elif item.verified_dev:
                item.classification = MigrationClassification.DEV_ONLY
            elif self._local_source_for(item) is not None:
                item.classification = MigrationClassification.LOCAL_SOURCE
            elif self._photos_probe is None or self._photos_probe(item.video_uuid):
                item.classification = MigrationClassification.PHOTOS_ICLOUD
            else:
                item.classification = MigrationClassification.MISSING
        return items

    def _local_source_for(self, item: MigrationItem) -> Path | None:
        if not self.vault_root:
            return None
        candidate = Path(self.vault_root) / item.video_uuid
        if candidate.is_dir():
            for path in sorted(candidate.glob("*")):
                if path.is_file():
                    return path
        return None

    # -- source selection ---------------------------------------------------

    def _select_source(self, item: MigrationItem) -> dict:
        prod_key = self._prod_key(item)
        head = self._head_prod(item)
        if head is not None:
            if head.byte_size and item.byte_size and head.byte_size != item.byte_size:
                raise ObjectStoreVerificationError(
                    f"PROD object present with conflicting size for {item.sha[:12]}"
                )
            return {"kind": "prod_object_present", "prod_key": prod_key}
        if item.classification is MigrationClassification.DEV_ONLY:
            if self.dev_store is None:
                raise ObjectStoreUnavailable("DEV source requested without DEV store")
            dev_head = self._head_dev(item)
            if dev_head is None:
                raise ObjectStoreUnavailable(
                    f"DEV replica absent for DEV_ONLY item {item.sha[:12]}"
                )
            if dev_head.byte_size and item.byte_size and dev_head.byte_size != item.byte_size:
                raise ObjectStoreVerificationError(
                    f"DEV replica size mismatch for {item.sha[:12]}"
                )
            return {"kind": "dev_replica", "prod_key": prod_key}
        local = self._local_source_for(item)
        if local is not None:
            return {"kind": "local_source", "path": str(local), "prod_key": prod_key}
        if self._photos_probe is None or self._photos_probe(item.video_uuid):
            return {"kind": "photos_materialization", "prod_key": prod_key}
        raise ObjectStoreUnavailable(
            f"no authoritative source for {item.sha[:12]} (missing)"
        )

    # -- drive --------------------------------------------------------------

    def drive_item(self, item: MigrationItem) -> dict[str, Any]:
        journal = MigrationJournal(self.state_dir, item.blob_sha256)
        journal.load()
        journal.doc.setdefault("video_uuid", item.video_uuid)
        journal.doc["classification"] = (
            item.classification.value if item.classification else None
        )
        journal.doc["media_revision_id"] = item.media_revision_id
        journal.doc["byte_size"] = item.byte_size
        journal.persist()
        try:
            self._advance(item, journal)
        except ObjectStoreVerificationError as exc:
            journal.record_error("verification_failed", str(exc), retryable=False)
        except ObjectStoreUnavailable as exc:
            journal.record_error("object_store_unavailable", str(exc), retryable=True)
        except PermissionError as exc:
            journal.record_error("insufficient_disk", str(exc), retryable=True)
        except MigrationPayloadUnavailable as exc:
            if "materialization failed" in str(exc):
                journal.record_error("photos_materialization_deferred", str(exc), retryable=True)
                journal.doc["state"] = MigrationState.DEFERRED_INTERACTIVE.value
                journal.doc["defer_reason"] = str(exc)[:300]
                journal.persist()
            else:
                journal.record_error("caption_authority_unavailable", str(exc), retryable=False)
        except Exception as exc:  # isolation: one asset never stops the batch
            journal.record_error("migration_fatal", str(exc), retryable=False)
        self._record_item_metrics(journal, item)
        return journal.doc

    def _advance(self, item: MigrationItem, journal: MigrationJournal) -> None:
        while not journal.is_terminal:
            state = journal.state
            started = time.time()
            if state is MigrationState.RETRYABLE:
                resume = journal.doc.pop("resume_state", None)
                if resume and resume != MigrationState.RETRYABLE.value:
                    self._resume_into(item, journal, MigrationState(resume))
                    continue
                state = MigrationState.INVENTORIED
            if state is MigrationState.INVENTORIED:
                if item.classification is MigrationClassification.ALREADY_PROD:
                    journal.doc["skip_reason"] = "already_verified_prod"
                    journal.transition(MigrationState.SKIPPED_ALREADY_PROD)
                    continue
                journal.doc["payload"] = self._payload_for(item)
                journal.doc["source"] = self._select_source(item)
                journal.transition(MigrationState.SOURCE_READY)
                continue
            if state is MigrationState.SOURCE_READY:
                self._check_disk(item.byte_size or 0)
                source = journal.doc.get("source") or {}
                kind = source.get("kind")
                if kind == "prod_object_present":
                    data = self._get_prod(item)
                    self._verify_bytes(item, data)
                    self._latency(journal, "verify_seconds", started)
                    journal.transition(MigrationState.PROD_VERIFIED)
                    continue
                if kind == "dev_replica":
                    data = self._get_dev(item)
                    self._verify_bytes(item, data)
                    local_path = self._stage_bytes(item, data)
                    journal.doc["local_temp"] = str(local_path)
                    self._latency(journal, "source_read_seconds", started)
                    journal.transition(MigrationState.LOCAL_VERIFIED)
                    continue
                if kind == "local_source":
                    local_path = Path(source["path"])
                    data = self._read_verified_local(item, local_path)
                    staged = self._stage_bytes(item, data)
                    journal.doc["local_temp"] = str(staged)
                    self._latency(journal, "source_read_seconds", started)
                    journal.transition(MigrationState.LOCAL_VERIFIED)
                    continue
                if kind == "photos_materialization":
                    local_path = self._materialize_from_photos(item)
                    data = self._read_verified_local(item, local_path)
                    staged = self._stage_bytes(item, data)
                    journal.doc["local_temp"] = str(staged)
                    self._latency(journal, "source_read_seconds", started)
                    journal.transition(MigrationState.LOCAL_VERIFIED)
                    continue
                raise ObjectStoreUnavailable(f"unknown source kind: {kind!r}")
            if state is MigrationState.LOCAL_VERIFIED:
                local_path = Path(journal.doc["local_temp"])
                if not local_path.is_file():
                    raise ObjectStoreUnavailable("staged local bytes vanished")
                self._verify_file(item, local_path)
                content_type = self._content_type_for(local_path, item)
                journal.doc["content_type"] = content_type
                self._content_types[item.blob_sha256] = content_type
                journal.transition(MigrationState.PROD_UPLOAD_STARTED)
                continue
            if state is MigrationState.PROD_UPLOAD_STARTED:
                prod_key = self._prod_key(item)
                if self._head_prod(item) is None:
                    self._put_prod(item, Path(journal.doc["local_temp"]))
                journal.doc["prod_key"] = prod_key
                self._latency(journal, "upload_seconds", started)
                journal.transition(MigrationState.PROD_UPLOADED)
                continue
            if state is MigrationState.PROD_UPLOADED:
                data = self._get_prod(item)
                self._verify_bytes(item, data)
                self._latency(journal, "verify_seconds", started)
                journal.transition(MigrationState.PROD_VERIFIED)
                continue
            if state is MigrationState.PROD_VERIFIED:
                payload = journal.doc.get("payload")
                if not payload:
                    raise ObjectStoreUnavailable("PROD_VERIFIED journal missing payload")
                document = self._migration_commit_document(item, journal)
                result = self.commit_fn(document)
                if not result.get("blob_sha256"):
                    raise ObjectStoreUnavailable("commit response missing blob_sha256")
                journal.doc["commit_result"] = result
                journal.transition(MigrationState.DB_COMMITTED)
                continue
            if state is MigrationState.DB_COMMITTED:
                shutil.rmtree(self.temp_root / item.blob_sha256, ignore_errors=True)
                journal.doc.pop("local_temp", None)
                journal.transition(MigrationState.CLEANED)
                continue
            raise ObjectStoreUnavailable(f"unreachable migration state: {state}")

    def _resume_into(
        self, item: MigrationItem, journal: MigrationJournal, target: MigrationState
    ) -> None:
        """Re-validate recorded evidence before resuming a retryable item."""
        journal.doc["state"] = target.value
        journal.doc["history"].append({"resumed_to": target.value, "at": utcnow()})
        journal.persist()
        if target in (
            MigrationState.SOURCE_READY,
            MigrationState.LOCAL_VERIFIED,
            MigrationState.PROD_UPLOAD_STARTED,
            MigrationState.PROD_UPLOADED,
            MigrationState.PROD_VERIFIED,
        ) and (not journal.doc.get("payload") or not journal.doc.get("source")):
            journal.doc["payload"] = self._payload_for(item)
            journal.doc["source"] = self._select_source(item)
            journal.persist()
            journal.doc["state"] = MigrationState.SOURCE_READY.value
            journal.persist()

    # -- payload authority --------------------------------------------------

    def _payload_for(self, item: MigrationItem) -> dict:
        """Exact caption authority (packet §19). Original ingest receipts carry
        the exact provider string; else a fresh exact provider read; NEVER a
        normalized legacy manufacture."""
        receipt = self._find_receipt(item)
        if receipt is not None:
            return receipt
        photos_payload = self._payload_from_photos(item)
        if photos_payload is not None:
            return photos_payload
        raise MigrationPayloadUnavailable(
            f"caption authority unavailable for {item.sha[:12]} "
            f"(no ingest receipt; Photos exact provider caption unavailable)"
        )

    def _find_receipt(self, item: MigrationItem) -> dict | None:
        for directory in self.receipt_dirs:
            directory = Path(directory)
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*")):
                if not path.name.endswith(INGEST_RECEIPT_SUFFIXES):
                    continue
                try:
                    doc = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                payload = doc.get("payload") or {}
                blob = payload.get("blob") or {}
                if (
                    blob.get("sha256") == item.blob_sha256
                    and payload.get("video_uuid") == item.video_uuid
                ):
                    return {"payload": payload, "extra": doc.get("extra") or {}}
        return None

    def _payload_from_photos(self, item: MigrationItem) -> dict | None:
        if not self.library_path:
            return None
        try:
            db = get_photos_db(self.library_path)
            matches = db.photos(uuid=[item.video_uuid])
            if not matches:
                return None
            photo = matches[0]
            provider = build_stable_provider(self.library_path)
            result = provider.get_caption(item.video_uuid)
            if not result.available or not result.raw:
                return None
            fingerprint = edit_fingerprint(photo)
            media_meta = self._probe_rendition(item)
            payload = {
                "video_uuid": item.video_uuid,
                "ingest_impl_version": MIGRATION_COMMIT_IMPL_VERSION,
                "rendition_semantics": RENDITION_SEMANTICS,
                "caption": {
                    "raw": result.raw,
                    "sha256": result.sha256,
                    "provider": result.provider,
                },
                "blob": {
                    "sha256": item.blob_sha256,
                    "byte_size": item.byte_size,
                    "object_key": self._prod_key(item),
                    "storage_backend": "b2",
                    "bucket": self.prod_bucket,
                },
                "remote_verified": True,
            }
            parsed = parse_caption_metadata(result.raw)
            provenance = dict(photo_provenance(photo))
            provenance["photos_edit_fingerprint"] = fingerprint
            extra = {
                "environment": self.prod_environment,
                "codec": media_meta.get("codec"),
                "width": media_meta.get("width"),
                "height": media_meta.get("height"),
                "duration_seconds": media_meta.get("duration_seconds"),
                "photos_edit_fingerprint": fingerprint,
                "source_provenance": provenance,
                "parser_version": parsed.get("parser"),
                "parsed_json": parsed.get("result"),
            }
            return {"payload": payload, "extra": extra}
        except Exception:
            return None

    def _probe_rendition(self, item: MigrationItem) -> dict:
        staged = self.temp_root / item.blob_sha256 / "source.bin"
        if staged.is_file():
            try:
                return ffprobe_metadata(staged, self.ffprobe_path)
            except Exception:
                return {}
        return {}

    def _migration_commit_document(self, item: MigrationItem, journal: MigrationJournal) -> dict:
        """Reuse the authoritative payload; bind the PROD environment/bucket;
        attach explicit migration provenance (packet §20)."""
        wrapper = journal.doc.get("payload") or {}
        inner = wrapper.get("payload") or wrapper
        body = dict(inner)
        body["blob"] = dict(inner.get("blob") or {})
        body["blob"]["bucket"] = self.prod_bucket
        body["blob"].setdefault("storage_backend", "b2")
        body["remote_verified"] = True
        extra = dict(wrapper.get("extra") or {})
        extra["environment"] = self.prod_environment
        extra["migration_provenance"] = {
            "engine": MIGRATION_JOURNAL_VERSION,
            "source_kind": (journal.doc.get("source") or {}).get("kind"),
            "migrated_at": utcnow(),
        }
        return {"payload": body, "extra": extra}

    # -- byte/verification helpers -----------------------------------------

    def _verify_bytes(self, item: MigrationItem, data: bytes) -> None:
        actual = sha256_bytes(data)
        if actual != item.blob_sha256:
            raise ObjectStoreVerificationError(
                f"SHA mismatch for {item.sha[:12]}: got {actual[:12]}"
            )
        if item.byte_size and len(data) != item.byte_size:
            raise ObjectStoreVerificationError(
                f"byte_size mismatch for {item.sha[:12]}: {len(data)} != {item.byte_size}"
            )

    def _verify_file(self, item: MigrationItem, path: Path) -> None:
        digest = hashlib.sha256()
        size = 0
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
        if digest.hexdigest() != item.blob_sha256:
            raise ObjectStoreVerificationError(
                f"staged-file SHA mismatch for {item.sha[:12]}"
            )
        if item.byte_size and size != item.byte_size:
            raise ObjectStoreVerificationError(
                f"staged-file byte_size mismatch for {item.sha[:12]}"
            )

    def _stage_bytes(self, item: MigrationItem, data: bytes) -> Path:
        self._check_disk(len(data))
        temp_dir = self.temp_root / item.blob_sha256
        temp_dir.mkdir(parents=True, exist_ok=True)
        ext = (item.extension or "").lower().lstrip(".")
        path = temp_dir / f"source.{ext or 'bin'}"
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def _read_verified_local(self, item: MigrationItem, path: Path) -> bytes:
        if not path.is_file():
            raise ObjectStoreUnavailable(f"local source vanished: {path}")
        data = path.read_bytes()
        self._verify_bytes(item, data)
        return data

    def _materialize_from_photos(self, item: MigrationItem) -> Path:
        if self.materialize_fn is None:
            raise MigrationPayloadUnavailable(
                "photos materialization seam not configured in this runtime "
                "(run the one-shot inside the production GUI-launchd context)"
            )
        self._check_disk(item.byte_size or 0)
        workdir = self.temp_root / item.blob_sha256
        workdir.mkdir(parents=True, exist_ok=True)
        try:
            return self.materialize_fn(item.video_uuid, workdir)
        except MigrationPayloadUnavailable:
            raise
        except Exception as exc:
            # ONE deferred asset never blocks the batch (§17/§28): interactive
            # macOS permission prompts or individual materialization faults
            # defer/quarantine this item only.
            raise MigrationPayloadUnavailable(
                f"photos materialization failed for {item.sha[:12]}: {exc}"
            ) from exc

    def _check_disk(self, expected_bytes: int) -> None:
        self.temp_root.mkdir(parents=True, exist_ok=True)
        free = (
            self._free_disk_bytes_fn()
            if self._free_disk_bytes_fn
            else shutil.disk_usage(self.temp_root).free
        )
        recorded = self.metrics.get("min_free_disk_bytes")
        self.metrics["min_free_disk_bytes"] = (
            min(recorded, free) if recorded else free
        )
        if free < self.min_free_disk_bytes + max(expected_bytes, 0):
            raise PermissionError(
                f"free disk {free} below guard {self.min_free_disk_bytes} "
                f"+ expected {expected_bytes}"
            )

    def _content_type_for(self, path: Path, item: MigrationItem) -> str | None:
        try:
            meta = ffprobe_metadata(path, self.ffprobe_path)
            return video_content_type(
                meta.get("container"), meta.get("codec"), item.extension
            )
        except Exception:
            return None

    def _latency(self, journal: MigrationJournal, key: str, started: float) -> None:
        journal.doc[key] = round(time.time() - started, 3)

    def _record_item_metrics(self, journal: MigrationJournal, item: MigrationItem) -> None:
        self.metrics[item.blob_sha256] = {
            "video_uuid": item.video_uuid,
            "state": journal.state.value,
            "classification": journal.doc.get("classification"),
            "source_kind": (journal.doc.get("source") or {}).get("kind"),
            "attempts": journal.doc.get("attempts", 0),
            "last_error": journal.doc.get("last_error"),
            "source_read_seconds": journal.doc.get("source_read_seconds"),
            "upload_seconds": journal.doc.get("upload_seconds"),
            "verify_seconds": journal.doc.get("verify_seconds"),
        }

    # -- store wrappers (metrics hooks; the ONLY touch points) --------------

    def _prod_key(self, item: MigrationItem) -> str:
        if item.prod_object_key:
            return item.prod_object_key
        return object_key_for_sha(item.blob_sha256, ext=item.extension)

    def _dev_key(self, item: MigrationItem) -> str:
        if item.dev_object_key:
            return item.dev_object_key
        return object_key_for_sha(item.blob_sha256, ext=item.extension)

    def _head_prod(self, item: MigrationItem):
        return self.prod_store.head(self._prod_key(item))

    def _head_dev(self, item: MigrationItem):
        if self.dev_store is None:
            return None
        return self.dev_store.head(self._dev_key(item))

    def _get_prod(self, item: MigrationItem) -> bytes:
        started = time.time()
        data = self.prod_store.get(self._prod_key(item))
        self.metrics["prod_get_bytes"] = self.metrics.get("prod_get_bytes", 0) + len(data)
        self.metrics["prod_get_seconds"] = round(
            self.metrics.get("prod_get_seconds", 0) + (time.time() - started), 3
        )
        return data

    def _get_dev(self, item: MigrationItem) -> bytes:
        started = time.time()
        data = self.dev_store.get(self._dev_key(item))
        self.metrics["dev_get_bytes"] = self.metrics.get("dev_get_bytes", 0) + len(data)
        self.metrics["dev_get_seconds"] = round(
            self.metrics.get("dev_get_seconds", 0) + (time.time() - started), 3
        )
        return data

    def _put_prod(self, item: MigrationItem, path: Path) -> None:
        started = time.time()
        result = self.prod_store.put(
            self._prod_key(item), path, content_type=self._content_types.get(item.blob_sha256)
        )
        self.metrics["prod_put_bytes"] = self.metrics.get("prod_put_bytes", 0) + result.byte_size
        self.metrics["prod_put_seconds"] = round(
            self.metrics.get("prod_put_seconds", 0) + (time.time() - started), 3
        )

    # -- batch --------------------------------------------------------------

    def run_wave(
        self, items: list[MigrationItem], *, wave_size: int | None = None
    ) -> dict[str, Any]:
        """Bounded wave: one active item at a time, sequential, per-asset
        persistence, no parallel fanout, no unbounded queue."""
        wave = items if wave_size is None else items[:wave_size]
        summary: dict[str, Any] = {
            "started_at": utcnow(),
            "requested": len(wave),
            "outcomes": {},
        }
        for item in wave:
            doc = self.drive_item(item)
            summary["outcomes"][item.blob_sha256[:12]] = {
                "video_uuid": item.video_uuid,
                "state": doc.get("state"),
            }
        summary["completed_at"] = utcnow()
        summary["metrics"] = {
            k: v for k, v in self.metrics.items() if k != "min_free_disk_bytes"
        }
        summary["min_free_disk_bytes"] = self.metrics.get("min_free_disk_bytes")
        self._persist_summary(summary)
        return summary

    def _persist_summary(self, summary: dict) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        path = self.state_dir / f"wave_summary_{stamp}.json"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=2, sort_keys=True)


def journal_content_type(engine: "HistoricalMigrationEngine", item: MigrationItem):
    """Deferred content-type resolution for the PUT: reads the ffprobe-evidence
    MIME recorded on the journal when the staged bytes were hashed."""
    doc_path = engine.state_dir / f"{item.blob_sha256}.mig.json"
    try:
        doc = json.loads(doc_path.read_text(encoding="utf-8"))
        return doc.get("content_type")
    except (OSError, ValueError):
        return None



# ---------------------------------------------------------------------------
# One-shot production-runtime CLI (distinct from the daemon; never a loop).

def build_http_commit_fn(config) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Authenticated HTTP commit transport (same endpoint/credential as the
    P4 dual-write commit path). Retries are safe: the server dedupes."""
    server = config.server
    endpoint = (
        getattr(config.dual_write, "commit_endpoint_path", None)
        or DEFAULT_COMMIT_ENDPOINT_PATH
    )
    url = server.url.rstrip("/") + endpoint
    timeout = float(getattr(config.dual_write, "commit_timeout_seconds", 120))
    from ..sync_client import _curl_post

    def commit(document: dict[str, Any]) -> dict[str, Any]:
        status_code, body = _curl_post(
            url,
            document,
            server.api_key,
            timeout,
            server.ca_cert_path,
        )
        if status_code != 200:
            raise ObjectStoreUnavailable(
                f"commit endpoint returned {status_code}: {str(body)[-200:]}"
            )
        try:
            result = json.loads(body)
        except ValueError as exc:
            raise ObjectStoreUnavailable("commit endpoint returned non-JSON") from exc
        if not result.get("blob_sha256"):
            raise ObjectStoreUnavailable("commit response missing blob_sha256")
        return result

    return commit


def fetch_backend_inventory(config) -> list[dict[str, Any]]:
    """GET the agent-key-gated backend migration inventory (read-only)."""
    import subprocess

    server = config.server
    url = server.url.rstrip("/") + "/api/v1/media/backbone/migration/inventory"
    cmd = [
        "curl", "-s",
        "-H", f"X-API-Key: {server.api_key}",
        "-w", "\n%{http_code}",
        "--max-time", "60",
    ]
    if server.ca_cert_path:
        cmd.extend(["--cacert", server.ca_cert_path])
    cmd.append(url)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=65)
    output = result.stdout.strip()
    lines = output.rsplit("\n", 1)
    body = lines[0] if len(lines) == 2 else output
    status_str = lines[1] if len(lines) == 2 else "0"
    if status_str != "200":
        raise ObjectStoreUnavailable(
            f"inventory endpoint returned {status_str}: {str(body)[-200:]}"
        )
    items = json.loads(body)
    if not isinstance(items, list):
        raise ObjectStoreUnavailable("inventory endpoint returned non-list body")
    return items


def items_from_backend(rows: list[dict[str, Any]]) -> list[MigrationItem]:
    items = []
    for row in rows:
        key = row.get("dev_object_key") or row.get("prod_object_key") or ""
        ext = key.rsplit(".", 1)[-1] if "." in key.rsplit("/", 1)[-1] else ""
        items.append(
            MigrationItem(
                video_uuid=row["video_uuid"],
                blob_sha256=row["blob_sha256"],
                byte_size=int(row.get("byte_size") or 0),
                media_revision_id=row.get("media_revision_id"),
                verified_prod=bool(row.get("verified_prod")),
                verified_dev=bool(row.get("verified_dev")),
                owner_diver=bool(row.get("owner_diver")),
                has_diver_chain=bool(row.get("has_diver_chain")),
                caption_provider=row.get("caption_provider"),
                prod_object_key=row.get("prod_object_key"),
                dev_object_key=row.get("dev_object_key"),
                extension=ext or DEFAULT_EXTENSION,
            )
        )
    return items


def mode_inventory(config) -> int:
    """Fetch + classify + persist the migration inventory report.

    The report contains NO captions and NO media text: counts, classes,
    SHAs, sizes, source kinds only (packet §13).
    """
    engine = HistoricalMigrationEngine.from_config(config, commit_fn=build_http_commit_fn(config))
    rows = fetch_backend_inventory(config)
    items = engine.classify(items_from_backend(rows))
    counts: dict[str, int] = {}
    bytes_by_class: dict[str, int] = {}
    for item in items:
        cls = item.classification.value
        counts[cls] = counts.get(cls, 0) + 1
        bytes_by_class[cls] = bytes_by_class.get(cls, 0) + (item.byte_size or 0)
    report = {
        "generated_at": utcnow(),
        "total_revisions": len(items),
        "counts": counts,
        "bytes_by_class": bytes_by_class,
        "items": [
            {
                "media_revision_id": item.media_revision_id,
                "video_uuid": item.video_uuid,
                "blob_sha256": item.blob_sha256,
                "byte_size": item.byte_size,
                "class": item.classification.value if item.classification else None,
                "verified_prod": item.verified_prod,
                "verified_dev": item.verified_dev,
                "prod_object_key": item.prod_object_key,
                "dev_object_key": item.dev_object_key,
                "owner_diver": item.owner_diver,
                "has_diver_chain": item.has_diver_chain,
            }
            for item in items
        ],
    }
    engine.state_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    path = engine.state_dir / f"inventory_{stamp}.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2, sort_keys=True)
    print(
        json.dumps(
            {
                "mode": "migration-inventory",
                "report_path": str(path),
                "total": len(items),
                "counts": counts,
            }
        )
    )
    return 0


def mode_drive(config, classes: list[str] | None = None, wave_size: int | None = None) -> int:
    engine = HistoricalMigrationEngine.from_config(config, commit_fn=build_http_commit_fn(config))
    rows = fetch_backend_inventory(config)
    items = engine.classify(items_from_backend(rows))
    if classes:
        allowed = {c.strip().upper() for c in classes}
        items = [
            i
            for i in items
            if i.classification and i.classification.value in allowed
        ]
    summary = engine.run_wave(items, wave_size=wave_size or int(config.migration.wave_size))
    print(
        json.dumps(
            {
                "mode": "migration-drive",
                "requested": summary["requested"],
                "outcomes": summary["outcomes"],
                "metrics": summary["metrics"],
                "min_free_disk_bytes": summary.get("min_free_disk_bytes"),
            },
            ensure_ascii=False,
        )
    )
    return 0


def mode_status(config) -> int:
    state_dir = Path(config.migration.state_dir).expanduser()
    journals = sorted(state_dir.glob("*.mig.json"))
    out = []
    for path in journals:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append(
            {
                "blob_sha256": doc.get("blob_sha256", path.name[: -len(".mig.json")]),
                "video_uuid": doc.get("video_uuid"),
                "state": doc.get("state"),
                "classification": doc.get("classification"),
                "attempts": doc.get("attempts", 0),
                "last_error": doc.get("last_error"),
            }
        )
    print(json.dumps({"mode": "migration-status", "items": out}, ensure_ascii=False))
    return 0


def main(argv=None) -> int:
    import argparse
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

    parser = argparse.ArgumentParser(description="P7 historical migration one-shot modes")
    parser.add_argument("--config", required=True)
    sub = parser.add_mutually_exclusive_group(required=True)
    sub.add_argument("--inventory", action="store_true")
    sub.add_argument("--drive", metavar="CLASSES", help="e.g. B or B,C")
    sub.add_argument("--status", action="store_true")
    parser.add_argument("--wave-size", type=int, default=None)
    args = parser.parse_args(argv)

    from ..config import Config

    config = Config.from_file(args.config)
    if not config.validate():
        raise SystemExit("invalid config")
    if args.inventory:
        return mode_inventory(config)
    if args.drive:
        classes = [c for c in args.drive.split(",") if c]
        return mode_drive(config, classes, args.wave_size)
    if args.status:
        return mode_status(config)
    return 2


if __name__ == "__main__":
    import sys

    sys.exit(main())
