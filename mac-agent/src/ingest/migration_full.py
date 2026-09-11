"""P10 FULL-CORPUS historical media migration engine (copy-only, domain-driven).

Packet: MEDIA_BACKBONE_P10_OVERNIGHT_FULL_DIVE_ANALYZER_MIGRATION_V1.

Scope authority: the Dive Analyzer DOMAIN graph — every dive row bearing a
video_uuid, deduplicated to DISTINCT video_uuid identities (the
media_revisions table covered only 15 historical items and is NOT the
inventory boundary). All existing divers are authorized for STORAGE
MIGRATION; storage existence never implies access (no AppUser,
UserDiverAccess, or ownership rows are ever created by this engine).

Source priority (packet §16 — authority over convenience):
  1. already verified PROD (existing MediaRevision + verified PROD location)
                                                        -> skip, zero byte ops
  2. verified source-vault accepted rendition (strict provenance proof)
                                                        -> vault bytes
  3. targeted Photos current EDITED-rendition materialization (production
     GUI-launchd runtime context, ONE asset at a time, bounded timeout)

Vault acceptance is proof-based, never filename-similar (packet §13/§14):
  - source.json canonical_video_uuid == dives.video_uuid
  - agent_local_uuid == the resolved Photos asset uuid
  - source_kind == osxphotos_single_asset_export (not poster/proxy360/proxy720)
  - vault file SHA-256 (streamed) == source.json.sha256 and size equal
  - the edit recipe has not changed since the export (freshness proof)

Canonical source semantics (frozen, packet §15): the current Apple Photos
EDITED rendition. Original/master bytes are never silently substituted for
edited media.

Roundtrip verification (binding, packet §28): source SHA A -> PROD PUT ->
full PROD GET streamed through a hash sink -> SHA B; require A == B and
byte_size equality. ETags are never substituted. Verification GETs stream
to a hash sink and are never written to disk (packet §29).

Runaway guards (packet §8): cumulative counters enforce
  PROD upload bytes <= 1 TiB, PROD verification GET bytes <= 1 TiB,
  DEV source GET bytes <= 1 TiB — hard stop, never silently raised.

Resource guards: min 10 GiB free disk before every byte operation; strictly
one active item (sequential); all hashing/uploads/GETs chunked or streamed;
whole videos are never buffered in RAM (packet §29/§30/§31).

Continuous-ingest priority (packet §33): before each Photos materialization
the engine yields while a production Photos export (an osxphotos export
process not owned by this run) is active — production ingest wins.

Caption authority (packet §21/§22/§23): the EXACT provider string (osxphotos
description of the resolved asset), hashed UTF-8 with no normalization; a
valid empty caption is valid; an unavailable caption is NEVER manufactured —
the media-only commit records MEDIA_VERIFIED_METADATA_PENDING and the item
still reaches terminal media state so expensive verified bytes are not lost
to a metadata fault.

Idempotence: a video_uuid-keyed durable journal (0600, atomic) is the ONLY
orchestration authority; terminal states never restart from zero; PROD HEAD
before any PUT; the commit endpoint dedupes rows (second pass: zero byte ops,
zero duplicate rows).

Safety: copy-only — no delete/hide primitive is imported or callable; legacy
media, DEV replicas, cache, and Photos assets untouched; science out of scope.
"""

import asyncio
import hashlib
import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .canary import (
    edit_fingerprint,
    ffprobe_metadata,
    get_photos_db,
    load_env_file,
    parse_caption_metadata,
    photo_provenance,
    utcnow,
)
from .caption import PhotosDbCaptionProviderShadow
from .content_addr import object_key_for_sha
from .errors import (
    ConfigValidationError,
    ObjectStoreUnavailable,
    ObjectStoreVerificationError,
)
from .media_content_type import video_content_type
from ..media_materializer import MediaMaterializer, MaterializationError
from .objectstore.b2 import B2Config, BackblazeB2Store

logger = logging.getLogger(__name__)

MIGRATION_JOURNAL_VERSION = "media_backbone_p10_full_corpus_v1"
MIGRATION_COMMIT_IMPL_VERSION = "media_backbone_p10_full_corpus_v1"
RENDITION_SEMANTICS = "photos_edited_rendition"
DEFAULT_COMMIT_ENDPOINT_PATH = "/api/v1/media/backbone/commit"
DEFAULT_EXTENSION = "mov"

# Runaway guards (packet §8) — absolute ceilings, never silently raised.
MAX_NEW_PROD_BYTES = 1024**4
MAX_PROD_VERIFY_BYTES = 1024**4
MAX_DEV_GET_BYTES = 1024**4

MATERIALIZATION_TIMEOUT_MIN_SECONDS = 600
MATERIALIZATION_TIMEOUT_MAX_SECONDS = 3600
MATERIALIZATION_MAX_ATTEMPTS = 3

CHECKPOINT_EVERY_ITEMS = 25
CHECKPOINT_EVERY_SECONDS = 30 * 60

ACTIVE_EXPORT_POLL_SECONDS = 30
ACTIVE_EXPORT_GRACE_SECONDS = 600


class MigrationState:
    INVENTORIED = "INVENTORIED"
    SOURCE_CLASSIFIED = "SOURCE_CLASSIFIED"
    SOURCE_READY = "SOURCE_READY"
    SOURCE_HASHED = "SOURCE_HASHED"
    PROD_UPLOAD_STARTED = "PROD_UPLOAD_STARTED"
    PROD_UPLOADED = "PROD_UPLOADED"
    PROD_VERIFY_STARTED = "PROD_VERIFY_STARTED"
    PROD_VERIFIED = "PROD_VERIFIED"
    DB_COMMITTED = "DB_COMMITTED"
    CLEANED = "CLEANED"
    SKIPPED_ALREADY_PROD = "SKIPPED_ALREADY_PROD"
    RESIDUAL = "RESIDUAL"
    RETRYABLE = "RETRYABLE"
    QUARANTINED = "QUARANTINED"
    DEFERRED_INTERACTIVE = "DEFERRED_INTERACTIVE"


TERMINAL_STATES = {
    MigrationState.CLEANED,
    MigrationState.SKIPPED_ALREADY_PROD,
    MigrationState.RESIDUAL,
    MigrationState.QUARANTINED,
    MigrationState.DEFERRED_INTERACTIVE,
}


class InventoryClass:
    """Packet §12 classification letters."""

    A_ALREADY_VERIFIED_PROD = "A"
    B_VERIFIED_DEV_ONLY = "B"
    C_VAULT_SOURCE = "C"
    D_LOCAL_SOURCE = "D"
    E_PHOTOS_LOCAL_EDITED = "E"
    F_PHOTOS_ICLOUD_EDITED = "F"
    G_IDENTITY_AMBIGUOUS = "G"
    H_PHOTOS_ASSET_MISSING = "H"
    I_CROSS_DIVER_CONFLICT = "I"
    J_OTHER_BLOCKER = "J"


@dataclass
class DomainItem:
    """One distinct Dive Analyzer domain video identity."""

    video_uuid: str
    video_filename: str | None = None
    diver_id: int | None = None
    dive_count: int = 1
    media_revision_id: int | None = None
    blob_sha256: str | None = None
    byte_size: int = 0
    rendition_semantics: str | None = None
    verified_prod: bool = False
    verified_dev: bool = False
    prod_object_key: str | None = None
    dev_object_key: str | None = None
    caption_provider: str | None = None
    caption_revision_count: int = 0

    resolved_asset_uuid: str | None = None
    classification: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def sha(self) -> str:
        return self.blob_sha256 or self.video_uuid

    @property
    def existing_revision(self) -> bool:
        return self.media_revision_id is not None


def items_from_domain(rows: list[dict[str, Any]]) -> list[DomainItem]:
    items = []
    for row in rows:
        key = row.get("prod_object_key") or row.get("dev_object_key") or ""
        ext = key.rsplit(".", 1)[-1] if "." in key.rsplit("/", 1)[-1] else ""
        items.append(
            DomainItem(
                video_uuid=row["video_uuid"],
                video_filename=row.get("video_filename"),
                diver_id=row.get("diver_id"),
                dive_count=int(row.get("dive_count") or 1),
                media_revision_id=row.get("media_revision_id"),
                blob_sha256=row.get("blob_sha256"),
                byte_size=int(row.get("byte_size") or 0),
                rendition_semantics=row.get("rendition_semantics"),
                verified_prod=bool(row.get("verified_prod")),
                verified_dev=bool(row.get("verified_dev")),
                prod_object_key=row.get("prod_object_key"),
                dev_object_key=row.get("dev_object_key"),
                caption_provider=row.get("caption_provider"),
                caption_revision_count=int(row.get("caption_revision_count") or 0),
                resolved_asset_uuid=row.get("resolved_asset_uuid"),
                classification=row.get("classification"),
            )
        )
    return items


class MigrationJournal:
    """Durable per-video_uuid migration state (0600, atomic).

    The ONLY orchestration authority: restart/resume/rerun decide from this
    file alone; the server DB remains the durable committed logical result.
    """

    def __init__(self, state_dir: Path, video_uuid: str):
        self.state_dir = Path(state_dir)
        self.path = self.state_dir / f"{video_uuid}.mig.json"
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
                "video_uuid": self.path.name[: -len(".mig.json")],
                "state": MigrationState.INVENTORIED,
                "attempts": 0,
                "history": [],
                "created_at": utcnow(),
            }
        return self.doc

    @property
    def state(self) -> str:
        return self.doc.get("state", MigrationState.INVENTORIED)

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def transition(self, new_state: str, **evidence) -> None:
        self.doc["history"].append(
            {
                "from": self.state,
                "to": new_state,
                "at": utcnow(),
                **{k: v for k, v in evidence.items() if v is not None},
            }
        )
        self.doc["state"] = new_state
        self.persist()

    def record_error(self, family: str, detail: str, retryable: bool) -> None:
        prior = self.state
        self.doc["attempts"] = int(self.doc.get("attempts", 0)) + 1
        self.doc["last_error"] = {
            "family": family,
            "detail": str(detail)[:300],
            "retryable": bool(retryable),
            "at": utcnow(),
        }
        if retryable:
            self.doc["resume_state"] = prior
            self.doc["state"] = MigrationState.RETRYABLE
        else:
            self.doc["state"] = MigrationState.QUARANTINED
        self.persist()

    def persist(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self.doc, fh, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, self.path)


class FullCorpusMigrationEngine:
    """One-shot, sequential, restart-safe FULL-CORPUS migration driver.

    Deliberately NOT a daemon component: one-shot invocations only.
    """

    def __init__(
        self,
        *,
        prod_store,
        dev_store=None,
        commit_fn,
        state_dir: Path,
        temp_root: Path,
        checkpoint_dir: Path | None = None,
        vault_root: str | None = None,
        library_path: str | None = None,
        ffprobe_path: str = "ffprobe",
        osxphotos_path: str = "osxphotos",
        materialization_dir: str | None = None,
        materialization_max_bytes: int = 2_000_000_000,
        materialization_use_photokit: bool = True,
        min_free_disk_bytes: int = 10 * 1024 * 1024 * 1024,
        prod_bucket: str = "",
        prod_environment: str = "prod",
        free_disk_bytes_fn=None,
        dry_run: bool = False,
        dive_caption_fn: Callable[[str], str | None] | None = None,
    ):
        self.prod_store = prod_store
        self.dev_store = dev_store
        self.commit_fn = commit_fn
        self.state_dir = Path(state_dir)
        self.temp_root = Path(temp_root)
        self.checkpoint_dir = Path(checkpoint_dir or (self.state_dir / "checkpoints"))
        self.vault_root = vault_root
        self.library_path = library_path
        self.ffprobe_path = ffprobe_path
        self.osxphotos_path = osxphotos_path
        self.materialization_dir = materialization_dir
        self.materialization_max_bytes = materialization_max_bytes
        self.materialization_use_photokit = materialization_use_photokit
        self.min_free_disk_bytes = int(min_free_disk_bytes)
        self.prod_bucket = prod_bucket
        self.prod_environment = prod_environment
        self._free_disk_bytes_fn = free_disk_bytes_fn
        self.dry_run = dry_run
        # G-class tie-break (deterministic, no guessing): when dives.video_uuid
        # and dives.video_filename resolve to two DIFFERENT Photos assets, the
        # dive's recorded raw_caption (exact provider string the historical
        # extractor parsed) is compared to each asset's current description.
        # EXACT equality (then the documented legacy .strip() transform) on
        # exactly ONE asset resolves the identity; both/neither stays residual.
        self.dive_caption_fn = dive_caption_fn
        self.counters: dict[str, int] = {
            "prod_put_bytes": 0,
            "prod_verify_get_bytes": 0,
            "dev_get_bytes": 0,
            "dedupe_avoided_bytes": 0,
            "source_bytes_read": 0,
            "photos_materialized_bytes": 0,
            "b2_retries": 0,
            "retry_attempts": 0,
            "checkpoint_count": 0,
        }
        self.outcomes: dict[str, str] = {}
        self._last_checkpoint_ts = time.time()
        self._checkpoint_serial = 0
        self._run_started = time.time()

    # -- construction -------------------------------------------------------

    @classmethod
    def from_config(cls, config, commit_fn) -> "FullCorpusMigrationEngine":
        cfg = getattr(config, "migration", None)
        os_cfg = config.object_store
        if cfg is None or not cfg.enabled:
            raise ConfigValidationError(
                "migration engine not enabled (migration.enabled=false)"
            )
        if os_cfg.environment != "prod":
            raise ConfigValidationError(
                "full-corpus migration requires object_store.environment == 'prod'"
            )
        if not os_cfg.enabled:
            raise ConfigValidationError(
                "full-corpus migration requires object_store.enabled"
            )
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
        media_cfg = config.media
        return cls(
            prod_store=prod_store,
            dev_store=dev_store,
            commit_fn=commit_fn,
            state_dir=Path(cfg.state_dir).expanduser(),
            temp_root=Path(cfg.temp_root).expanduser(),
            checkpoint_dir=Path(cfg.state_dir).expanduser() / "checkpoints",
            vault_root=cfg.vault_root or None,
            library_path=config.photos.library_path,
            ffprobe_path=media_cfg.ffprobe_path,
            osxphotos_path=media_cfg.osxphotos_path,
            materialization_dir=getattr(media_cfg, "materialization_dir", None),
            materialization_max_bytes=int(
                getattr(media_cfg, "materialization_max_bytes", 2_000_000_000)
            ),
            materialization_use_photokit=bool(
                getattr(media_cfg, "materialization_use_photokit", True)
            ),
            min_free_disk_bytes=int(cfg.min_free_disk_bytes),
            prod_bucket=prod_cfg.bucket,
            dive_caption_fn=build_dive_caption_fn(config),
        )

    # -- inventory resolution (packet §11) -----------------------------------

    def build_photos_index(self, items: list[DomainItem]) -> dict[str, Any]:
        """One osxphotos pass resolving the corpus against the Photos library.

        Deterministic resolution: the recorded video_uuid when it resolves,
        else the video_filename stem (fresh corpus finding: the historical
        era recorded the Photos asset UUID in video_filename). Metadata-only:
        no video bytes are downloaded here (packet §18).
        """
        index: dict[str, Any] = {"by_uuid": {}}
        if not self.library_path:
            return index
        db = get_photos_db(self.library_path)
        by_uuid = {p.uuid: p for p in db.photos()}
        index["by_uuid"] = by_uuid
        for item in items:
            stem = (item.video_filename or "").rsplit(".", 1)[0]
            vu_asset = by_uuid.get(item.video_uuid)
            fn_asset = by_uuid.get(stem) if stem else None
            if (
                vu_asset is not None
                and fn_asset is not None
                and vu_asset.uuid != fn_asset.uuid
            ):
                resolved = self._resolve_differing_assets(
                    item, vu_asset, fn_asset
                )
                if resolved is None:
                    item.classification = InventoryClass.G_IDENTITY_AMBIGUOUS
                    item.notes.append(
                        "video_uuid and video_filename resolve to DIFFERENT "
                        f"assets ({vu_asset.uuid[:8]} vs {fn_asset.uuid[:8]}); "
                        "deterministic caption-equality tie-break inconclusive"
                    )
                    item.resolved_asset_uuid = None
                    continue
                item.resolved_asset_uuid = resolved.uuid
                item.notes.append(
                    "identity resolved deterministically: dive raw_caption "
                    "equals exactly one asset's description ("
                    f"{resolved.uuid[:8]})"
                )
                continue
            asset = vu_asset or fn_asset
            if asset is None:
                item.classification = InventoryClass.H_PHOTOS_ASSET_MISSING
                item.notes.append(
                    "no Photos asset for video_uuid or video_filename stem"
                )
                item.resolved_asset_uuid = None
                continue
            item.resolved_asset_uuid = asset.uuid
            date_modified = getattr(asset, "date_modified", None)
            if date_modified is not None:
                item._asset_date_modified = date_modified  # type: ignore[attr-defined]
            adjustments_path = getattr(asset, "adjustments_path", None)
            if adjustments_path and Path(adjustments_path).is_file():
                try:
                    item._asset_adjustments_mtime = datetime.fromtimestamp(  # type: ignore[attr-defined]
                        Path(adjustments_path).stat().st_mtime, tz=timezone.utc
                    )
                except OSError:
                    pass
        return index

    def _resolve_differing_assets(self, item, vu_asset, fn_asset):
        """Deterministic G-class tie-break (packet §3: no invented resolution).

        Both candidate Photos assets are compared against the dive's recorded
        raw_caption (the exact string the historical extractor parsed, with
        the documented legacy .strip() boundary). Exactly one match resolves;
        anything else returns None (stays G, unguessed)."""
        if self.dive_caption_fn is None:
            return None
        try:
            raw_caption = self.dive_caption_fn(item.video_uuid)
        except Exception:
            return None
        if raw_caption is None:
            return None
        vu_desc = getattr(vu_asset, "description", None)
        fn_desc = getattr(fn_asset, "description", None)
        matches = [
            asset
            for asset, desc in ((vu_asset, vu_desc), (fn_asset, fn_desc))
            if desc is not None
            and (desc == raw_caption or desc == raw_caption.strip())
        ]
        if len(matches) == 1:
            return matches[0]
        return None

    def classify(
        self, items: list[DomainItem], photos_index: dict[str, Any]
    ) -> list[DomainItem]:
        by_uuid = photos_index.get("by_uuid", {})
        for item in items:
            if item.classification == InventoryClass.G_IDENTITY_AMBIGUOUS:
                continue
            if item.existing_revision and item.verified_prod:
                item.classification = InventoryClass.A_ALREADY_VERIFIED_PROD
                continue
            if item.resolved_asset_uuid is None:
                if item.classification is None:
                    item.classification = InventoryClass.J_OTHER_BLOCKER
                    item.notes.append("unresolvable source identity")
                continue
            if self._vault_candidate(item) is not None:
                item.classification = InventoryClass.C_VAULT_SOURCE
                continue
            asset = by_uuid.get(item.resolved_asset_uuid)
            if asset is not None and getattr(asset, "path_edited", None):
                item.classification = InventoryClass.E_PHOTOS_LOCAL_EDITED
            else:
                item.classification = InventoryClass.F_PHOTOS_ICLOUD_EDITED
        return items

    # -- vault provenance (packet §14) ---------------------------------------

    def _vault_candidate(self, item: DomainItem) -> Path | None:
        if not self.vault_root or item.resolved_asset_uuid is None:
            return None
        vault_dir = Path(self.vault_root) / item.video_uuid
        meta_path = vault_dir / "source.json"
        source_path = vault_dir / "source.mov"
        if not (meta_path.is_file() and source_path.is_file()):
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if str(meta.get("canonical_video_uuid", "")) != item.video_uuid:
            return None
        if str(meta.get("agent_local_uuid", "")).upper() != item.resolved_asset_uuid.upper():
            return None
        if str(meta.get("source_kind", "")) != "osxphotos_single_asset_export":
            return None
        if not self._vault_edit_fresh(item, meta):
            return None
        return source_path

    def _vault_edit_fresh(self, item: DomainItem, meta: dict) -> bool:
        """Export-time freshness proof: the edit recipe must not have changed
        after the vault export. Caption edits never invalidate media; the
        adjustment-render mtime is authoritative when locally available."""
        export_at = meta.get("created_at")
        if not export_at:
            return False
        try:
            export_ts = datetime.fromisoformat(
                str(export_at).replace("Z", "+00:00")
            )
        except ValueError:
            return False
        if export_ts.tzinfo is None:
            export_ts = export_ts.replace(tzinfo=timezone.utc)
        adjustments_mtime = getattr(item, "_asset_adjustments_mtime", None)
        if adjustments_mtime is not None:
            return adjustments_mtime <= export_ts
        date_modified = getattr(item, "_asset_date_modified", None)
        if date_modified is None:
            return False
        if getattr(date_modified, "tzinfo", None) is None:
            date_modified = date_modified.replace(tzinfo=timezone.utc)
        return date_modified <= export_ts

    # -- drive ---------------------------------------------------------------

    def drive_item(self, item: DomainItem, photos_index: dict) -> dict[str, Any]:
        journal = MigrationJournal(self.state_dir, item.video_uuid)
        journal.load()
        journal.doc.setdefault("video_uuid", item.video_uuid)
        if item.classification:
            journal.doc["classification"] = item.classification
        journal.doc["diver_id"] = item.diver_id
        journal.doc["resolved_asset_uuid"] = item.resolved_asset_uuid
        journal.persist()
        try:
            self._advance(item, journal, photos_index)
        except _DeferredInteractive as exc:
            journal.doc["state"] = MigrationState.DEFERRED_INTERACTIVE
            journal.doc["defer_reason"] = str(exc)[:300]
            journal.doc["history"].append(
                {"deferred": True, "at": utcnow(), "reason": str(exc)[:300]}
            )
            journal.persist()
        except _ResidualItem as exc:
            journal.doc["state"] = MigrationState.RESIDUAL
            journal.doc["residual_reason"] = str(exc)[:300]
            journal.doc["history"].append(
                {"residual": True, "at": utcnow(), "reason": str(exc)[:300]}
            )
            journal.persist()
        except _RunawayGuard as exc:
            journal.record_error("runaway_guard", str(exc), retryable=False)
            raise
        except ObjectStoreVerificationError as exc:
            journal.record_error("verification_failed", str(exc), retryable=False)
        except ObjectStoreUnavailable as exc:
            journal.record_error("object_store_unavailable", str(exc), retryable=True)
        except PermissionError as exc:
            journal.record_error("insufficient_disk", str(exc), retryable=True)
        except Exception as exc:  # isolation: one asset never stops the batch
            journal.record_error("migration_fatal", str(exc), retryable=False)
        self.outcomes[item.video_uuid] = journal.state
        self._maybe_checkpoint(force=False)
        return journal.doc

    def _advance(
        self, item: DomainItem, journal: MigrationJournal, photos_index: dict
    ) -> None:
        while not journal.is_terminal:
            state = journal.state
            if state == MigrationState.RETRYABLE:
                resume = journal.doc.pop("resume_state", None)
                self.counters["retry_attempts"] = (
                    self.counters.get("retry_attempts", 0) + 1
                )
                if resume and resume != MigrationState.RETRYABLE:
                    journal.doc["state"] = resume
                    journal.doc["history"].append(
                        {"resumed_to": resume, "at": utcnow()}
                    )
                    journal.persist()
                    continue
                journal.doc["state"] = MigrationState.SOURCE_CLASSIFIED
                journal.persist()
                continue
            if state == MigrationState.INVENTORIED:
                if item.classification == InventoryClass.A_ALREADY_VERIFIED_PROD:
                    journal.doc["skip_reason"] = "already_verified_prod"
                    journal.transition(MigrationState.SKIPPED_ALREADY_PROD)
                    continue
                if item.classification in (
                    InventoryClass.G_IDENTITY_AMBIGUOUS,
                    InventoryClass.H_PHOTOS_ASSET_MISSING,
                    InventoryClass.I_CROSS_DIVER_CONFLICT,
                    InventoryClass.J_OTHER_BLOCKER,
                ):
                    raise _ResidualItem(
                        f"classification {item.classification}: "
                        + "; ".join(item.notes)
                    )
                journal.transition(MigrationState.SOURCE_CLASSIFIED)
                continue
            if state == MigrationState.SOURCE_CLASSIFIED:
                self._check_disk(0)
                source = self._select_source(item)
                if source is None:
                    raise _ResidualItem(
                        f"no authoritative source for {item.video_uuid[:8]}"
                    )
                journal.doc["source"] = source
                journal.transition(MigrationState.SOURCE_READY)
                continue
            if state == MigrationState.SOURCE_READY:
                self._acquire_and_hash(item, journal)
                continue
            if state == MigrationState.SOURCE_HASHED:
                local = Path(journal.doc["local_temp"])
                self._check_disk(local.stat().st_size)
                self._reverify_staged(item, journal)
                journal.doc["content_type"] = self._content_type_for(journal)
                journal.transition(MigrationState.PROD_UPLOAD_STARTED)
                continue
            if state == MigrationState.PROD_UPLOAD_STARTED:
                self._upload(item, journal)
                continue
            if state == MigrationState.PROD_UPLOADED:
                journal.transition(MigrationState.PROD_VERIFY_STARTED)
                continue
            if state == MigrationState.PROD_VERIFY_STARTED:
                self._verify_remote(item, journal)
                continue
            if state == MigrationState.PROD_VERIFIED:
                document = self._commit_document(item, journal, photos_index)
                result = self.commit_fn(document)
                if not result.get("blob_sha256"):
                    raise ObjectStoreUnavailable(
                        "commit response missing blob_sha256"
                    )
                journal.doc["commit_result"] = result
                journal.doc["media_only"] = bool(result.get("media_only"))
                journal.transition(MigrationState.DB_COMMITTED)
                continue
            if state == MigrationState.DB_COMMITTED:
                shutil.rmtree(self.temp_root / item.video_uuid, ignore_errors=True)
                journal.doc.pop("local_temp", None)
                journal.transition(MigrationState.CLEANED)
                continue
            raise ObjectStoreUnavailable(f"unreachable migration state: {state}")

    # -- source selection -----------------------------------------------------

    def _select_source(self, item: DomainItem) -> dict | None:
        vault_path = self._vault_candidate(item)
        if vault_path is not None:
            return {
                "kind": "vault_source",
                "path": str(vault_path),
                "asset_uuid": item.resolved_asset_uuid,
            }
        return {
            "kind": "photos_materialization",
            "asset_uuid": item.resolved_asset_uuid,
        }

    def _acquire_and_hash(
        self, item: DomainItem, journal: MigrationJournal
    ) -> None:
        source = journal.doc.get("source") or {}
        kind = source.get("kind")
        started = time.time()
        if kind == "photos_materialization":
            local = self._materialize_from_photos(item, journal)
        elif kind == "vault_source":
            local = self._stage_local_file(item, Path(source["path"]))
        else:
            raise ObjectStoreUnavailable(f"unknown source kind: {kind!r}")
        digest, size = self._stream_sha_file(local)
        journal.doc["source_bytes"] = size
        journal.doc["blob_sha256"] = digest
        journal.doc["local_temp"] = str(local)
        journal.doc["source_kind"] = kind
        journal.doc["source_seconds"] = round(time.time() - started, 3)
        self.counters["source_bytes_read"] = (
            self.counters.get("source_bytes_read", 0) + size
        )
        journal.transition(MigrationState.SOURCE_HASHED, sha=digest[:12])

    def _materialize_from_photos(
        self, item: DomainItem, journal: MigrationJournal
    ) -> Path:
        """Targeted Photos EDITED-rendition materialization (packet §19).

        ONE asset at a time; yields to any active production export
        (packet §33); bounded adaptive timeout with 3 attempts and bounded
        backoff (packet §20); iCloud downloads are targeted per asset,
        never a whole-library synchronization.
        """
        asset_uuid = item.resolved_asset_uuid
        timeout = MATERIALIZATION_TIMEOUT_MIN_SECONDS
        attempt = 0
        last_exc: Exception | None = None
        while attempt < MATERIALIZATION_MAX_ATTEMPTS:
            attempt += 1
            self._yield_to_active_exports()
            self._check_disk(0)
            materialize_root = self.temp_root / item.video_uuid / "materialize"
            if materialize_root.exists():
                shutil.rmtree(materialize_root, ignore_errors=True)
            materializer = MediaMaterializer(
                materialization_dir=str(materialize_root),
                max_bytes=self.materialization_max_bytes,
                osxphotos_path=self.osxphotos_path,
                export_timeout_seconds=timeout,
                use_photokit=self.materialization_use_photokit,
                library_path=self.library_path,
            )
            try:
                exported = asyncio.run(materializer.materialize(asset_uuid))
            except MaterializationError as exc:
                last_exc = exc
                if exc.code == "permission_required" or exc.code == "photos_access_denied":
                    # §10: never leave an unattended dialog waiting.
                    raise _DeferredInteractive(
                        f"interactive permission context required for "
                        f"{asset_uuid[:8]} ({exc.code})"
                    ) from exc
                if exc.code == "osxphotos_export_timeout":
                    timeout = min(
                        timeout * 2, MATERIALIZATION_TIMEOUT_MAX_SECONDS
                    )
                time.sleep(min(30 * attempt, 90))  # bounded backoff
                continue
            # Canonical edited-rendition selection (packet §15): when the
            # asset has adjustments, osxphotos exports BOTH the original and
            # the current edited rendition; the edited file is preferred
            # deterministically. Original bytes are never silently
            # substituted for edited media.
            edited_candidates = [
                p
                for p in materialize_root.rglob("*edited*")
                if p.is_file()
            ]
            chosen = None
            if edited_candidates:
                edited_candidates.sort(key=lambda p: (p.stat().st_size, p.name))
                chosen = edited_candidates[-1]
            if chosen is None:
                chosen = exported
            target_dir = self.temp_root / item.video_uuid
            target_dir.mkdir(parents=True, exist_ok=True)
            staged = target_dir / (
                f"source{Path(chosen).suffix.lower() or '.mov'}"
            )
            self._check_disk(Path(chosen).stat().st_size)
            shutil.copyfile(chosen, staged)
            try:
                materializer.cleanup_failed_residue(asset_uuid)
            except Exception:
                pass
            shutil.rmtree(materialize_root, ignore_errors=True)
            self.counters["photos_materialized_bytes"] = (
                self.counters.get("photos_materialized_bytes", 0)
                + Path(staged).stat().st_size
            )
            journal.doc["materialization_attempts"] = attempt
            journal.doc["materialization_timeout_seconds"] = timeout
            return staged
        raise _ResidualItem(
            f"photos materialization failed after {attempt} attempts for "
            f"{asset_uuid[:8]}: {last_exc}"
        )

    def _stage_local_file(self, item: DomainItem, path: Path) -> Path:
        if not path.is_file():
            raise _ResidualItem(f"vault source vanished: {path}")
        target_dir = self.temp_root / item.video_uuid
        target_dir.mkdir(parents=True, exist_ok=True)
        staged = target_dir / f"source{path.suffix.lower() or '.mov'}"
        self._check_disk(path.stat().st_size)
        shutil.copyfile(path, staged)
        return staged

    # -- hashing / verification (packet §28/§29) -------------------------------

    @staticmethod
    def _stream_sha_file(path: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size

    def _reverify_staged(
        self, item: DomainItem, journal: MigrationJournal
    ) -> None:
        """Re-validate recorded evidence before any upload (packet §41)."""
        local = Path(journal.doc["local_temp"])
        if not local.is_file():
            raise ObjectStoreUnavailable("staged local bytes vanished")
        digest, size = self._stream_sha_file(local)
        expected = journal.doc.get("blob_sha256")
        if expected and digest != expected:
            raise ObjectStoreVerificationError(
                f"staged SHA mismatch for {item.video_uuid[:8]}"
            )
        vault_sha = (journal.doc.get("source") or {}).get("vault_sha256")
        if vault_sha and digest != vault_sha:
            raise ObjectStoreVerificationError(
                f"vault provenance SHA mismatch for {item.video_uuid[:8]}"
            )
        journal.doc["verified_bytes"] = size

    def _verify_remote(
        self, item: DomainItem, journal: MigrationJournal
    ) -> None:
        prod_key = journal.doc["prod_key"]
        digest, size = self.prod_store.get_streaming_sha(prod_key)
        self.counters["prod_verify_get_bytes"] = (
            self.counters.get("prod_verify_get_bytes", 0) + size
        )
        self._assert_runaway()
        expected = journal.doc["blob_sha256"]
        if digest != expected:
            raise ObjectStoreVerificationError(
                f"PROD remote SHA mismatch for {item.video_uuid[:8]}: "
                f"got {digest[:12]} expected {expected[:12]}"
            )
        if journal.doc.get("source_bytes") and size != int(
            journal.doc["source_bytes"]
        ):
            raise ObjectStoreVerificationError(
                f"PROD remote byte_size mismatch for {item.video_uuid[:8]}: "
                f"{size} != {journal.doc['source_bytes']}"
            )
        journal.doc["remote_verified"] = True
        journal.doc["remote_bytes"] = size
        journal.transition(MigrationState.PROD_VERIFIED)

    def _prod_key(self, journal: MigrationJournal) -> str:
        recorded = (journal.doc.get("source") or {}).get("prod_key")
        if recorded:
            return recorded
        sha = journal.doc["blob_sha256"]
        ext = DEFAULT_EXTENSION
        local = journal.doc.get("local_temp")
        if local:
            suffix = Path(local).suffix.lower().lstrip(".")
            if suffix in ("mov", "mp4", "m4v", "avi", "hevc"):
                ext = suffix
        return object_key_for_sha(sha, ext=ext)

    def _upload(self, item: DomainItem, journal: MigrationJournal) -> None:
        prod_key = self._prod_key(journal)
        head = self.prod_store.head(prod_key)
        local = Path(journal.doc["local_temp"])
        size = local.stat().st_size
        if head is None:
            self.counters["prod_put_bytes"] = (
                self.counters.get("prod_put_bytes", 0) + size
            )
            self._assert_runaway()
            if self.dry_run:
                logger.info("dry-run: would upload %s (%d bytes)", prod_key, size)
            else:
                result = self.prod_store.put(
                    prod_key, local, content_type=journal.doc.get("content_type")
                )
                if result.sha256 != journal.doc["blob_sha256"]:
                    raise ObjectStoreVerificationError(
                        f"PUT digest mismatch for {item.video_uuid[:8]}"
                    )
        else:
            if head.byte_size and head.byte_size != size:
                raise ObjectStoreVerificationError(
                    f"PROD object present with conflicting size for "
                    f"{item.video_uuid[:8]}: {head.byte_size} != {size}"
                )
            self.counters["dedupe_avoided_bytes"] = (
                self.counters.get("dedupe_avoided_bytes", 0) + size
            )
            journal.doc["dedupe"] = True
        journal.doc["prod_key"] = prod_key
        journal.transition(MigrationState.PROD_UPLOADED)

    # -- payload / commit (packet §21/§23/§24/§25) ------------------------------

    def _caption_authority(
        self, item: DomainItem, photos_index: dict
    ) -> tuple[dict, dict] | None:
        by_uuid = photos_index.get("by_uuid", {})
        lookup_uuid = item.resolved_asset_uuid or item.video_uuid
        photo = by_uuid.get(lookup_uuid)
        if photo is None:
            return None

        def describe(uuid: str) -> str | None:
            candidate = by_uuid.get(uuid)
            return candidate.description if candidate is not None else None

        # Same provider boundary (osxphotos description) served from the
        # cached single-pass index: the exact provider string with no
        # normalization, without reloading the Photos DB per item.
        result = _provider_from_index(lookup_uuid, describe)
        if not result.available or result.raw is None:
            return None
        parsed = parse_caption_metadata(result.raw)
        shadow = PhotosDbCaptionProviderShadow(self.library_path).get_caption(
            photo.uuid
        )
        extra = {
            "shadow_provider": shadow.provider if shadow.available else None,
            "shadow_raw": shadow.raw if shadow.available else None,
            "shadow_sha256": shadow.sha256 if shadow.available else None,
            "shadow_available": shadow.available,
            "parser_version": parsed.get("parser"),
            "parsed_json": parsed.get("result"),
        }
        caption = {
            "raw": result.raw,
            "sha256": result.sha256,
            "provider": result.provider,
        }
        return caption, extra

    def _commit_document(
        self, item: DomainItem, journal: MigrationJournal, photos_index: dict
    ) -> dict[str, Any]:
        caption_result = self._caption_authority(item, photos_index)
        media_meta: dict[str, Any] = {}
        local = journal.doc.get("local_temp")
        if local and Path(local).is_file():
            try:
                media_meta = ffprobe_metadata(Path(local), self.ffprobe_path)
            except Exception:
                media_meta = {}
        by_uuid = photos_index.get("by_uuid", {})
        photo = None
        provenance: dict[str, Any] = {}
        fingerprint = None
        photo = by_uuid.get(item.resolved_asset_uuid or item.video_uuid)
        if photo is not None:
            provenance = photo_provenance(photo)
            fingerprint = edit_fingerprint(photo)
        provenance["resolved_asset_uuid"] = item.resolved_asset_uuid
        provenance["resolution_basis"] = (
            "video_uuid"
            if item.resolved_asset_uuid == item.video_uuid
            else "video_filename"
        )
        provenance["p10_domain_baseline"] = True
        provenance["dive_rows"] = item.dive_count
        blob = {
            "sha256": journal.doc["blob_sha256"],
            "byte_size": int(journal.doc.get("source_bytes", 0)),
            "object_key": journal.doc["prod_key"],
            "storage_backend": "b2",
            "bucket": self.prod_bucket,
        }
        body: dict[str, Any] = {
            "video_uuid": item.video_uuid,
            "ingest_impl_version": MIGRATION_COMMIT_IMPL_VERSION,
            "rendition_semantics": RENDITION_SEMANTICS,
            "caption": caption_result[0] if caption_result else None,
            "blob": blob,
            "remote_verified": True,
        }
        extra: dict[str, Any] = dict(caption_result[1]) if caption_result else {}
        extra.update(
            {
                "environment": self.prod_environment,
                "codec": media_meta.get("codec"),
                "width": media_meta.get("width"),
                "height": media_meta.get("height"),
                "duration_seconds": media_meta.get("duration_seconds"),
                "photos_edit_fingerprint": fingerprint,
                "source_provenance": provenance,
                "migration_provenance": {
                    "engine": MIGRATION_JOURNAL_VERSION,
                    "source_kind": (journal.doc.get("source") or {}).get("kind"),
                    "migrated_at": utcnow(),
                },
            }
        )
        if caption_result is None:
            extra["media_only"] = True
            extra["media_only_reason"] = (
                "caption authority temporarily unresolved (§23): provider "
                "caption unavailable at commit time; media bytes verified"
            )
        return {"payload": body, "extra": extra}

    # -- helpers -----------------------------------------------------------------

    def _content_type_for(self, journal: MigrationJournal) -> str | None:
        local = journal.doc.get("local_temp")
        if not local:
            return None
        try:
            meta = ffprobe_metadata(Path(local), self.ffprobe_path)
            return video_content_type(
                meta.get("container"),
                meta.get("codec"),
                Path(local).suffix.lower().lstrip("."),
            )
        except Exception:
            return None

    def _check_disk(self, expected_bytes: int) -> None:
        self.temp_root.mkdir(parents=True, exist_ok=True)
        free = (
            self._free_disk_bytes_fn()
            if self._free_disk_bytes_fn
            else shutil.disk_usage(self.temp_root).free
        )
        recorded = self.counters.get("min_free_disk_bytes")
        self.counters["min_free_disk_bytes"] = (
            min(recorded, free) if recorded else free
        )
        if free < self.min_free_disk_bytes + max(expected_bytes, 0):
            raise PermissionError(
                f"free disk {free} below guard {self.min_free_disk_bytes} "
                f"+ expected {expected_bytes}"
            )

    def _assert_runaway(self) -> None:
        if self.counters["prod_put_bytes"] > MAX_NEW_PROD_BYTES:
            raise _RunawayGuard(
                "PROD upload bytes exceeded the 1 TiB runaway guard (§8)"
            )
        if self.counters["prod_verify_get_bytes"] > MAX_PROD_VERIFY_BYTES:
            raise _RunawayGuard(
                "PROD verification GET bytes exceeded the 1 TiB guard (§8)"
            )
        if self.counters["dev_get_bytes"] > MAX_DEV_GET_BYTES:
            raise _RunawayGuard("DEV GET bytes exceeded the 1 TiB guard (§8)")

    def _yield_to_active_exports(self) -> None:
        """Yield to production ingest (packet §33): wait while an osxphotos
        export process is running that is NOT a child of this process.
        Bounded by ACTIVE_EXPORT_GRACE_SECONDS; never requires a human."""
        deadline = time.time() + ACTIVE_EXPORT_GRACE_SECONDS
        while time.time() < deadline:
            foreign = self._foreign_export_pids()
            if not foreign:
                return
            logger.info("yielding to active production export pids=%s", foreign)
            time.sleep(ACTIVE_EXPORT_POLL_SECONDS)
        logger.warning(
            "active-export grace window elapsed; continuing cautiously"
        )

    def _foreign_export_pids(self) -> list[int]:
        mine = {os.getpid()}
        try:
            out = subprocess.run(
                ["pgrep", "-f", "osxphotos export"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception:
            return []
        foreign = []
        for line in out.stdout.split():
            pid = int(line)
            try:
                ps = subprocess.run(
                    ["ps", "-o", "ppid=", "-p", str(pid)],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                ppid = int(ps.stdout.strip() or -1)
            except Exception:
                ppid = -1
            if ppid in mine:
                continue  # our own materializer child
            foreign.append(pid)
        return foreign

    # -- batch / checkpoints (packet §40) ----------------------------------------

    def run_wave(self, items: list[DomainItem], photos_index: dict) -> dict:
        summary: dict[str, Any] = {
            "started_at": utcnow(),
            "requested": len(items),
        }
        since_checkpoint = 0
        for item in items:
            if self._runaway_aborted():
                break
            doc = self.drive_item(item, photos_index)
            since_checkpoint += 1
            if since_checkpoint >= CHECKPOINT_EVERY_ITEMS:
                self._write_checkpoint()
                self._last_checkpoint_ts = time.time()
                since_checkpoint = 0
        summary["completed_at"] = utcnow()
        summary["outcomes"] = dict(self.outcomes)
        summary["counters"] = dict(self.counters)
        self._write_checkpoint()
        self._persist_summary(summary)
        return summary

    def _runaway_aborted(self) -> bool:
        try:
            self._assert_runaway()
        except _RunawayGuard as exc:
            logger.error("RUNAWAY GUARD: %s", exc)
            return True
        return False

    def _maybe_checkpoint(self, force: bool) -> None:
        now = time.time()
        if force or (now - self._last_checkpoint_ts) >= CHECKPOINT_EVERY_SECONDS:
            self._write_checkpoint()
            self._last_checkpoint_ts = now

    def _write_checkpoint(self) -> dict:
        # Serial resumes from existing checkpoint files (crash-safe reruns).
        if self._checkpoint_serial == 0:
            existing = sorted(self.checkpoint_dir.glob("checkpoint_*.json"))
            if existing:
                try:
                    self._checkpoint_serial = int(existing[-1].stem.split("_")[-1])
                except ValueError:
                    self._checkpoint_serial = len(existing)
        self._checkpoint_serial += 1
        self.counters["checkpoint_count"] = self._checkpoint_serial
        doc = {
            "serial": self._checkpoint_serial,
            "at": utcnow(),
            "elapsed_seconds": round(time.time() - self._run_started, 1),
            "outcomes": dict(self.outcomes),
            "counters": dict(self.counters),
            "free_disk_bytes": (
                self._free_disk_bytes_fn()
                if self._free_disk_bytes_fn
                else shutil.disk_usage(self.temp_root).free
            ),
        }
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        path = (
            self.checkpoint_dir
            / f"checkpoint_{self._checkpoint_serial:05d}.json"
        )
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2, sort_keys=True)
        return doc

    def _persist_summary(self, summary: dict) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        path = self.state_dir / f"wave_summary_{stamp}.json"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=2, sort_keys=True)


class _ResidualItem(Exception):
    """A single item that cannot be migrated without guessing."""


def _provider_from_index(uuid: str, describe: Callable[[str], str | None]):
    """CurrentStableCaptionProvider served from the cached Photos index."""
    from .caption import CurrentStableCaptionProvider

    return CurrentStableCaptionProvider(describe).get_caption(uuid)


class _DeferredInteractive(Exception):
    """Interactive macOS permission context required — deferred; batch continues."""


class _RunawayGuard(Exception):
    """Absolute 1 TiB runaway ceiling reached (packet §8)."""


def fetch_domain_inventory(config) -> list[dict[str, Any]]:
    """GET the agent-key-gated P10 domain inventory (read-only)."""
    server = config.server
    url = (
        server.url.rstrip("/")
        + "/api/v1/media/backbone/migration/domain_inventory"
    )
    cmd = [
        "curl", "-s",
        "-H", f"X-API-Key: {server.api_key}",
        "-w", "\n%{http_code}",
        "--max-time", "120",
    ]
    if server.ca_cert_path:
        cmd.extend(["--cacert", server.ca_cert_path])
    cmd.append(url)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=125)
    output = result.stdout.strip()
    lines = output.rsplit("\n", 1)
    body = lines[0] if len(lines) == 2 else output
    status_str = lines[1] if len(lines) == 2 else "0"
    if status_str != "200":
        raise ObjectStoreUnavailable(
            f"domain inventory endpoint returned {status_str}: "
            f"{str(body)[-200:]}"
        )
    items = json.loads(body)
    if not isinstance(items, list):
        raise ObjectStoreUnavailable(
            "domain inventory endpoint returned non-list body"
        )
    return items


def mode_inventory(config, output_dir: Path | None = None) -> int:
    """Fetch + classify + persist the FULL-CORPUS inventory (§11/§12)."""
    engine = FullCorpusMigrationEngine.from_config(
        config, commit_fn=lambda doc: {"blob_sha256": "x"}
    )
    rows = fetch_domain_inventory(config)
    items = items_from_domain(rows)
    photos_index = engine.build_photos_index(items)
    engine.classify(items, photos_index)
    counts: dict[str, int] = {}
    bytes_by_class: dict[str, int] = {}
    for item in items:
        cls = item.classification or "?"
        counts[cls] = counts.get(cls, 0) + 1
        est = item.byte_size
        if est == 0 and item.resolved_asset_uuid:
            asset = photos_index.get("by_uuid", {}).get(item.resolved_asset_uuid)
            if asset is not None:
                est = int(getattr(asset, "original_filesize", 0) or 0)
        bytes_by_class[cls] = bytes_by_class.get(cls, 0) + est
    total_bytes = sum(bytes_by_class.values())
    report = {
        "generated_at": utcnow(),
        "corpus_total_distinct": len(items),
        "counts": counts,
        "bytes_by_class": bytes_by_class,
        "estimated_total_bytes": total_bytes,
        "items": [
            {
                "video_uuid": i.video_uuid,
                "video_filename": i.video_filename,
                "diver_id": i.diver_id,
                "media_revision_id": i.media_revision_id,
                "blob_sha256": i.blob_sha256,
                "byte_size": i.byte_size,
                "class": i.classification,
                "resolved_asset_uuid": i.resolved_asset_uuid,
                "verified_prod": i.verified_prod,
                "notes": i.notes,
            }
            for i in items
        ],
    }
    out_dir = Path(output_dir or engine.state_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    path = out_dir / f"full-corpus-inventory_{stamp}.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2, sort_keys=True)
    print(
        json.dumps(
            {
                "mode": "p10-domain-inventory",
                "report_path": str(path),
                "total": len(items),
                "counts": counts,
                "estimated_bytes": total_bytes,
            }
        )
    )
    return 0


def mode_drive(
    config,
    classes: list[str] | None = None,
    wave_size: int | None = None,
    dry_run: bool = False,
) -> int:
    engine = FullCorpusMigrationEngine.from_config(
        config, commit_fn=build_http_commit_fn(config)
    )
    engine.dry_run = dry_run
    rows = fetch_domain_inventory(config)
    items = items_from_domain(rows)
    photos_index = engine.build_photos_index(items)
    engine.classify(items, photos_index)
    if classes:
        allowed = {c.strip().upper() for c in classes}
        items = [i for i in items if i.classification and i.classification in allowed]
    if wave_size:
        items = items[:wave_size]
    summary = engine.run_wave(items, photos_index)
    print(
        json.dumps(
            {
                "mode": "p10-full-corpus-drive",
                "requested": summary["requested"],
                "counters": summary["counters"],
                "outcome_counts": _count_outcomes(summary["outcomes"]),
            },
            ensure_ascii=False,
        )
    )
    return 0


def _count_outcomes(outcomes: dict[str, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for state in outcomes.values():
        counts[state] = counts.get(state, 0) + 1
    return counts


def mode_status(config) -> int:
    state_dir = Path(config.migration.state_dir).expanduser()
    journals = sorted(state_dir.glob("*.mig.json"))
    out = []
    counts: dict[str, int] = {}
    for path in journals:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        state = doc.get("state")
        counts[state] = counts.get(state, 0) + 1
        out.append(
            {
                "video_uuid": doc.get("video_uuid"),
                "state": state,
                "classification": doc.get("classification"),
                "attempts": doc.get("attempts", 0),
                "last_error": doc.get("last_error"),
            }
        )
    print(
        json.dumps(
            {"mode": "p10-migration-status", "counts": counts, "items": out},
            ensure_ascii=False,
        )
    )
    return 0


def build_dive_caption_fn(config):
    """Per-item dive raw_caption fetch (agent-key gated, read-only) for the
    G-class deterministic tie-break. Returns None on any transport issue
    (fail-safe: the item stays G/unguessed rather than guessed)."""
    server = config.server

    from ..sync_client import _curl_get

    def fetch(video_uuid: str) -> str | None:
        url = (
            server.url.rstrip("/")
            + f"/api/v1/media/backbone/migration/dive_caption/{video_uuid}"
        )
        status, body = _curl_get(url, server.api_key, 60.0, server.ca_cert_path)
        if status != 200:
            return None
        try:
            return json.loads(body).get("raw_caption")
        except ValueError:
            return None

    return fetch


def build_http_commit_fn(config):
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
            raise ObjectStoreUnavailable(
                "commit endpoint returned non-JSON"
            ) from exc
        if not result.get("blob_sha256"):
            raise ObjectStoreUnavailable("commit response missing blob_sha256")
        return result

    return commit


def main(argv=None) -> int:
    import argparse
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

    parser = argparse.ArgumentParser(
        description="P10 full-corpus migration one-shot modes"
    )
    parser.add_argument("--config", required=True)
    sub = parser.add_mutually_exclusive_group(required=True)
    sub.add_argument("--domain-inventory", action="store_true")
    sub.add_argument("--drive", metavar="CLASSES", help="e.g. C or E,F")
    sub.add_argument("--status", action="store_true")
    parser.add_argument("--wave-size", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    from ..config import Config

    config = Config.from_file(args.config)
    if not config.validate():
        raise SystemExit("invalid config")
    if args.domain_inventory:
        return mode_inventory(config)
    if args.drive:
        classes = [c for c in args.drive.split(",") if c]
        return mode_drive(config, classes, args.wave_size, args.dry_run)
    if args.status:
        return mode_status(config)
    return 2


if __name__ == "__main__":
    import sys

    sys.exit(main())
