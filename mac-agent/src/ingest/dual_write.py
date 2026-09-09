"""P4 production dual-write: additive object-store ingest for the legacy path.

Architecture (packet MEDIA_BACKBONE_P4_PRODUCTION_DUAL_WRITE_CANARY_V1):

    legacy media job succeeds
        │  (already-materialized edited rendition bytes, ONE Photos export)
        ▼
    stage copy (local I/O only — lifetime-safe against legacy cleanup)
        │
        ├─ legacy path: continues unchanged (transcode → upload → finalize)
        └─ background dual-write:
              evidence (exact caption + shadow parity + provenance)
              → content SHA
              → B2 PROD object (bucket-scoped, private)
              → full remote GET, SHA equality (roundtrip verification)
              → HTTP commit to authenticated backend endpoint
                (POST /api/v1/media/backbone/commit, X-API-Key)
              → local journal commit → cleanup

Invariants:
- legacy success never depends on object-store success; failure semantics:
  LEGACY_SUCCESS + OBJECT_STORE_PENDING_RETRY (journal keeps retryable state)
- hard prod allowlist: exactly ONE Photos UUID (count != 1 → refuse to start)
- ONE materialization: the legacy export is reused; no second Photos export
- max one active dual-write materialization (backpressure)
- metrics snapshots are run-unique and immutable (never overwrite evidence)
- this module NEVER prints caption text, credentials, or presigned URLs
"""

import json
import logging
import os
import re
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .canary import (
    ffprobe_metadata,
    get_photos_db,
    load_env_file,
    parse_caption_metadata,
    photo_provenance,
    stage_commit_document,
    utcnow,
)
from .caption import (
    CaptionResult,
    PhotosDbCaptionProviderShadow,
    compare_caption_providers,
)
from .coordinator import ObjectStoreIngestCoordinator
from .errors import ObjectStoreUnavailable
from .objectstore.b2 import B2Config, BackblazeB2Store
from .state_store import IngestStateStore
from .states import IngestState
from ..sync_client import _curl_post

logger = logging.getLogger(__name__)

UUID_PATTERN = re.compile(
    r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
)
PROD_ALLOWLIST_REQUIRED_COUNT = 1
METRICS_VERSION = "media_backbone_p4_v1"
DEFAULT_COMMIT_ENDPOINT_PATH = "/api/v1/media/backbone/commit"
MAX_PASSES_PER_TRIGGER = 5
RETRY_BACKOFF_SECONDS = 5.0


def validate_prod_allowlist(allowlist: list[str]) -> None:
    """P4 hard guard (packet §19): exactly ONE Photos UUID.

    Any other count (0, or more than one) refuses production dual-write.
    """
    if not isinstance(allowlist, (list, tuple)):
        raise ValueError("prod dual-write allowlist must be a list of UUIDs")
    if len(allowlist) != PROD_ALLOWLIST_REQUIRED_COUNT:
        raise ValueError(
            f"prod dual-write allowlist guard violation: {len(allowlist)} entries; "
            f"exactly {PROD_ALLOWLIST_REQUIRED_COUNT} canary UUID is authorized"
        )
    seen: list[str] = []
    for entry in allowlist:
        if not isinstance(entry, str) or not UUID_PATTERN.match(entry):
            raise ValueError(f"allowlist entry is not a valid UUID: {entry!r}")
        normalized = entry.upper()
        if normalized in seen:
            raise ValueError(f"allowlist contains duplicate uuid: {normalized}")
        seen.append(normalized)


class _CountingStore:
    """Wrapper that counts operations/bytes; optional one-shot put failure.

    The remote store is never harmed: the injection raises a retryable error
    before the real PUT happens (controlled failure-injection test only).
    Duck-typed against the ObjectStore protocol like the P3 runner wrappers.
    """

    def __init__(self, inner, fail_put_once: bool = False):
        self._inner = inner
        self._fail_put_once = bool(fail_put_once)
        self.put_count = 0
        self.put_bytes = 0
        self.head_count = 0
        self.get_count = 0
        self.get_bytes = 0
        self.commit_attempts = 0

    def put(self, key: str, source):
        if self._fail_put_once:
            self._fail_put_once = False
            raise ObjectStoreUnavailable(
                "injected first-put failure (P4 controlled test)"
            )
        self.put_count += 1
        result = self._inner.put(key, source)
        self.put_bytes += result.byte_size
        return result

    def head(self, key: str):
        self.head_count += 1
        return self._inner.head(key)

    def get(self, key: str) -> bytes:
        data = self._inner.get(key)
        self.get_count += 1
        self.get_bytes += len(data)
        return data

    def presign_get(self, key: str, ttl_seconds: int) -> str:
        return self._inner.presign_get(key, ttl_seconds)


class ProductionDualWrite:
    """Legacy-primary additive object-store ingest for the production agent."""

    def __init__(self, config):
        self.config = config
        self.dual = config.dual_write
        self.os_cfg = config.object_store
        self.library_path = config.photos.library_path
        self.state_dir = Path(self.os_cfg.state_dir).expanduser()
        self.temp_root = Path(self.os_cfg.temp_root).expanduser()
        self.env_file = self.dual.env_file
        self._active_lock = threading.Lock()
        self._active: set[str] = set()
        self._state_dir_ready = False
        self.metrics_snapshots: list[str] = []

    # -- construction -------------------------------------------------------

    @classmethod
    def from_config(cls, config) -> "ProductionDualWrite | None":
        """Return None when the feature is OFF (rollback state by default).

        Both flags are required:
        - object_store.enabled (OBJECT_STORE_INGEST_ENABLED semantics)
        - dual_write.enabled   (OBJECT_STORE_PROD_DUAL_WRITE_ENABLED semantics)
        """
        os_cfg = getattr(config, "object_store", None)
        dual_cfg = getattr(config, "dual_write", None)
        if os_cfg is None or dual_cfg is None:
            return None
        if not dual_cfg.enabled:
            return None
        if not os_cfg.enabled:
            raise ValueError(
                "dual_write.enabled requires object_store.enabled "
                "(OBJECT_STORE_INGEST_ENABLED)"
            )
        if os_cfg.environment != "prod":
            raise ValueError(
                "production dual-write requires object_store.environment == 'prod'"
            )
        validate_prod_allowlist(list(dual_cfg.allowlist or []))
        return cls(config)

    # -- guards -------------------------------------------------------------

    def should_process(self, video_uuid: str) -> bool:
        if not (self.os_cfg.enabled and self.dual.enabled):
            return False
        if not UUID_PATTERN.match(video_uuid or ""):
            return False
        return video_uuid.upper() in {u.upper() for u in self.dual.allowlist}

    def _ensure_dirs(self) -> None:
        if self._state_dir_ready:
            return
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self._state_dir_ready = True

    # -- hook entry points --------------------------------------------------

    def stage_copy(self, video_uuid: str, source_path: Path) -> Path | None:
        """Copy the already-materialized legacy bytes into the dual-write temp
        area while the legacy pipeline still owns them.

        Returns None (skip) when the asset is not allowlisted, the journal is
        already terminal, or the single backpressure slot is occupied.
        Raises on real staging errors (legacy path unaffected either way —
        the caller catches and continues).
        """
        if not self.should_process(video_uuid):
            return None
        self._ensure_dirs()
        state_store = IngestStateStore(self.state_dir / f"{video_uuid}.json")
        state_store.load(video_uuid)
        if state_store.state.is_terminal:
            # clean up a retained staging copy from any previous attempt
            staging = self.temp_root / "dual_write_staging" / video_uuid
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            return None
        with self._active_lock:
            if self._active:
                logger.info(
                    "dual-write backpressure: skipping trigger for %s "
                    "(one active materialization policy)",
                    video_uuid[:8],
                )
                return None
            self._active.add(video_uuid)
        source_path = Path(source_path)
        # Staging lives OUTSIDE the coordinator workdir (temp_root/<uuid>) so
        # the coordinator's workdir lifecycle can never delete it.
        target = (
            self.temp_root
            / "dual_write_staging"
            / video_uuid
            / f"staged{source_path.suffix.lower() or '.bin'}"
        )
        if target.parent.exists():
            shutil.rmtree(target.parent, ignore_errors=True)  # stale attempt
        target.parent.mkdir(parents=True, exist_ok=True)
        started = time.time()
        shutil.copy2(source_path, target)
        copy_seconds = time.time() - started
        self._set_stage_meta(
            video_uuid,
            {
                "staged_path": str(target),
                "staged_bytes": target.stat().st_size,
                "copy_seconds": round(copy_seconds, 3),
            },
        )
        return target

    def launch(self, video_uuid: str, staged_path: Path) -> bool:
        """Start the background verified-ingest for a staged copy."""
        worker = threading.Thread(
            target=self._run_guarded,
            args=(video_uuid, Path(staged_path)),
            name=f"dual-write-{video_uuid[:8].lower()}",
            daemon=True,
        )
        worker.start()
        return True

    def _release(self, video_uuid: str) -> None:
        with self._active_lock:
            self._active.discard(video_uuid)

    def _run_guarded(self, video_uuid: str, staged_path: Path) -> None:
        try:
            self._drive(video_uuid, staged_path)
        except Exception as exc:  # failure isolation: never propagate
            logger.warning("dual-write %s failed: %s", video_uuid[:8], exc)
        finally:
            self._release(video_uuid)

    # -- driver -------------------------------------------------------------

    def _set_stage_meta(self, video_uuid: str, meta: dict) -> None:
        self._ensure_dirs()
        meta_path = self.state_dir / f"{video_uuid}.stage.json"
        fd = os.open(meta_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2, sort_keys=True)

    def _read_stage_meta(self, video_uuid: str) -> dict:
        path = self.state_dir / f"{video_uuid}.stage.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return {}

    def _capture_evidence(self, video_uuid: str) -> None:
        """Exact-caption + shadow parity + provenance evidence (0600).

        Read-only with respect to Photos; no caption authority change.
        """
        db = get_photos_db(self.library_path)
        matches = db.photos(uuid=[video_uuid])
        if not matches:
            raise ObjectStoreUnavailable(f"asset not found in Photos library: {video_uuid}")
        photo = matches[0]
        stable = self._stable_provider()
        shadow = PhotosDbCaptionProviderShadow(self.library_path)
        stable_result = stable.get_caption(video_uuid)
        shadow_result = shadow.get_caption(video_uuid)
        parity = compare_caption_providers([(video_uuid, stable_result, shadow_result)])
        evidence = {
            "captured_at": utcnow(),
            "photo": photo_provenance(photo),
            "edit_fingerprint": self._edit_fingerprint(photo),
            "caption": {
                "provider": stable_result.provider,
                "available": stable_result.available,
                "caption_sha256": stable_result.sha256,
                "caption_length": len(stable_result.raw) if stable_result.raw else 0,
                "caption_utf8_bytes": len(stable_result.raw.encode("utf-8"))
                if stable_result.raw
                else 0,
                "caption_raw": stable_result.raw,
            },
            "shadow": {
                "provider": shadow_result.provider,
                "available": shadow_result.available,
                "shadow_sha256": shadow_result.sha256,
                "shadow_length": len(shadow_result.raw) if shadow_result.raw else 0,
                "shadow_raw": shadow_result.raw,
                "error_family": shadow_result.error_family,
            },
            "parity": parity,
            "parsed": parse_caption_metadata(stable_result.raw or ""),
            "rendition_semantics": "photos_edited_rendition",
        }
        self._write_evidence(video_uuid, evidence)

    def _stable_provider(self):
        from .canary import build_stable_provider

        return build_stable_provider(self.library_path)

    def _edit_fingerprint(self, photo) -> str:
        from .canary import edit_fingerprint

        return edit_fingerprint(photo)

    def _write_evidence(self, video_uuid: str, evidence: dict) -> None:
        path = self.state_dir / f"{video_uuid}.evidence.json"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(evidence, fh, ensure_ascii=False, indent=2, sort_keys=True)

    def _update_evidence(self, video_uuid: str, updater: Callable[[dict], None]) -> None:
        path = self.state_dir / f"{video_uuid}.evidence.json"
        evidence = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        updater(evidence)
        self._write_evidence(video_uuid, evidence)

    def _cfg_dict(self) -> dict:
        """canary-shaped cfg for shared helpers (stage_commit_document)."""
        return {
            "photos": {"library_path": self.library_path},
            "object_store": {
                "environment": self.os_cfg.environment,
                "bucket": self.os_cfg.bucket,
                "region": self.os_cfg.region,
                "endpoint_url": self.os_cfg.endpoint_url,
                "prefix": self.os_cfg.prefix,
                "state_dir": str(self.state_dir),
                "temp_root": str(self.temp_root),
                "presign_ttl_seconds": self.os_cfg.presign_ttl_seconds,
                "max_retries": self.os_cfg.max_retries,
                "storage_backend": "b2",
            },
        }

    def _build_store(self) -> tuple[BackblazeB2Store, B2Config]:
        env = load_env_file(self.env_file) if self.env_file else None
        cfg = self._cfg_dict()
        os_cfg = cfg["object_store"]
        credentials = env or {}
        if credentials:
            os.environ.setdefault("B2_APPLICATION_KEY_ID", credentials["B2_APPLICATION_KEY_ID"])
            os.environ.setdefault("B2_APPLICATION_KEY", credentials["B2_APPLICATION_KEY"])
        config = B2Config(
            environment=os_cfg["environment"],
            bucket=os_cfg["bucket"],
            region=os_cfg.get("region") or None,
            endpoint_url=os_cfg.get("endpoint_url") or None,
            prefix=os_cfg.get("prefix", "blobs/sha256"),
            presign_ttl_seconds=int(os_cfg.get("presign_ttl_seconds", 300)),
            max_retries=int(os_cfg.get("max_retries", 3)),
        )
        return BackblazeB2Store(config), config

    def _post_commit_document(
        self, document: dict, receipt_path: Path
    ) -> dict[str, Any]:
        """POST one commit document to the authenticated backend endpoint and
        persist the P2-convention receipt (0600). Idempotent server-side: a
        retry after a lost response returns the same logical result."""
        server_cfg = self.config.server
        url = server_cfg.url.rstrip("/") + (
            self.dual.commit_endpoint_path or DEFAULT_COMMIT_ENDPOINT_PATH
        )
        status_code, body = _curl_post(
            url,
            document,
            server_cfg.api_key,
            float(self.dual.commit_timeout_seconds),
            server_cfg.ca_cert_path,
        )
        if status_code != 200:
            raise ObjectStoreUnavailable(
                f"commit endpoint returned {status_code}: {body[-200:]}"
            )
        try:
            result = json.loads(body)
        except ValueError as exc:
            raise ObjectStoreUnavailable("commit endpoint returned non-JSON body") from exc
        if not result.get("blob_sha256"):
            raise ObjectStoreUnavailable("commit endpoint response missing blob_sha256")
        receipt = {"input": document, "result": result, "transport": "http"}
        fd = os.open(receipt_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(receipt, fh, ensure_ascii=False, indent=2, sort_keys=True)
        return result

    def make_http_commit_fn(
        self, video_uuid: str, fail_once: bool = False, commit_stats: dict | None = None
    ):
        """Authenticated HTTP commit transport (replaces the P3 operator
        tunnel). Posts the staged document to the backend commit endpoint with
        the EXISTING agent API key (X-API-Key), validates the response, and
        persists the receipt at the P2 convention path (0600) so restart
        convergence stays identical.
        """
        state_dir = self.state_dir
        receipt_path = state_dir / f"{video_uuid}.commit_receipt.json"
        consume_fail_once = bool(fail_once)

        def commit_db_fn(payload: dict[str, Any]) -> dict[str, Any]:
            nonlocal consume_fail_once
            if commit_stats is not None:
                commit_stats["attempts"] = commit_stats.get("attempts", 0) + 1
            if receipt_path.exists():
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                if receipt.get("input", {}).get("payload") != payload:
                    raise ObjectStoreUnavailable(
                        "commit receipt does not match the staged coordinator payload; "
                        "refusing to mark DB_COMMITTED"
                    )
                if not receipt.get("result", {}).get("blob_sha256"):
                    raise ObjectStoreUnavailable("commit receipt missing server result rows")
                return receipt["result"]
            staged = stage_commit_document(self._cfg_dict(), video_uuid)
            if staged.get("payload") != payload:
                raise ObjectStoreUnavailable(
                    "staged commit payload drifted from the coordinator payload; "
                    "refusing to send"
                )
            if consume_fail_once:
                consume_fail_once = False
                raise ObjectStoreUnavailable(
                    "injected first-commit failure (P4 controlled test: lost request/response)"
                )
            return self._post_commit_document(staged, receipt_path)

        return commit_db_fn

    def _drive(self, video_uuid: str, staged_path: Path) -> None:
        self._ensure_dirs()
        run_id = self._new_run_id(video_uuid)
        metrics: dict[str, Any] = {
            "version": METRICS_VERSION,
            "run_id": run_id,
            "video_uuid": video_uuid,
            "environment": self.os_cfg.environment,
            "bucket": self.os_cfg.bucket,
            "started_at": utcnow(),
            "injections": {
                "fail_put_once": bool(self.dual.fail_put_once),
                "fail_commit_once": bool(self.dual.fail_commit_once),
            },
        }
        state_store = IngestStateStore(self.state_dir / f"{video_uuid}.json")
        state_store.load(video_uuid)
        if state_store.state.is_terminal:
            metrics["result"] = "already_terminal"
            metrics["completed_at"] = utcnow()
            self._write_metrics_snapshot(run_id, metrics)
            return

        if not (self.state_dir / f"{video_uuid}.evidence.json").exists():
            self._capture_evidence(video_uuid)
        media_meta = ffprobe_metadata(staged_path, self.config.media.ffprobe_path)
        photos_duration = 0.0
        try:
            evidence = json.loads(
                (self.state_dir / f"{video_uuid}.evidence.json").read_text(encoding="utf-8")
            )
            photos_duration = ((evidence.get("photo") or {}).get("duration_seconds")) or 0.0
        except (OSError, ValueError):
            evidence = {}

        def _finish(ev: dict) -> None:
            duration_match = (
                abs((media_meta.get("duration_seconds") or 0.0) - photos_duration) <= 0.2
                if photos_duration
                else None
            )
            ev["media_metadata"] = media_meta
            ev["rendition_duration_match"] = duration_match

        self._update_evidence(video_uuid, _finish)
        stage_meta = self._read_stage_meta(video_uuid)
        metrics["staging"] = {
            "extra_photos_materializations": 0,
            "reused_legacy_bytes": True,
            "copy_bytes": stage_meta.get("staged_bytes"),
            "copy_seconds": stage_meta.get("copy_seconds"),
        }

        store, b2_config = self._build_store()
        counting = _CountingStore(store, fail_put_once=self.dual.fail_put_once)
        commit_stats: dict = {"attempts": 0}
        commit_db_fn = self.make_http_commit_fn(
            video_uuid,
            fail_once=self.dual.fail_commit_once,
            commit_stats=commit_stats,
        )

        def materialize(asset_uuid: str, workdir: Path) -> Path:
            # ONE-materialization rule: reuse the staged legacy bytes; never
            # trigger a second Photos export from the dual-write path. The
            # byte copy into the coordinator workdir is local I/O only.
            target = workdir / f"staged{staged_path.suffix.lower() or '.bin'}"
            shutil.copy2(staged_path, target)
            return target

        coordinator = ObjectStoreIngestCoordinator(
            video_uuid=video_uuid,
            state_store=state_store,
            object_store=counting,
            materialize_fn=materialize,
            commit_db_fn=commit_db_fn,
            temp_root=self.temp_root,
            caption_provider=self._stable_provider(),
            min_free_disk_bytes=int(self.os_cfg.min_free_disk_bytes),
            storage_backend=self.os_cfg.storage_backend or "b2",
            bucket=b2_config.bucket,
            skip_put_if_remote_present=True,
        )

        final_state = None
        for _pass in range(MAX_PASSES_PER_TRIGGER):
            pass_started = time.time()
            history_len = len(state_store.doc.get("history") or [])
            try:
                final_state = coordinator.run_once()
            except Exception as exc:
                metrics.setdefault("passes", []).append(
                    {
                        "state_at_end": state_store.state.value,
                        "error": str(exc)[:200],
                        "elapsed_seconds": round(time.time() - pass_started, 3),
                    }
                )
                break
            metrics.setdefault("passes", []).append(
                {
                    "state_at_end": state_store.state.value,
                    "ops": {
                        "put_count": counting.put_count,
                        "put_bytes": counting.put_bytes,
                        "head_count": counting.head_count,
                        "get_count": counting.get_count,
                        "get_bytes": counting.get_bytes,
                    },
                    "elapsed_seconds": round(time.time() - pass_started, 3),
                }
            )
            if final_state in (IngestState.CACHE_CLEANED, IngestState.QUARANTINED):
                break
            time.sleep(RETRY_BACKOFF_SECONDS)

        metrics["final_state"] = str(final_state) if final_state else state_store.state.value
        metrics["result"] = {
            str(IngestState.CACHE_CLEANED): "verified_committed",
            str(IngestState.QUARANTINED): "quarantined",
        }.get(metrics["final_state"], "pending_retry")
        if final_state is IngestState.CACHE_CLEANED:
            # committed + verified: release the staging copy (local bytes only;
            # the remote B2 object and DB rows are durable)
            shutil.rmtree(
                self.temp_root / "dual_write_staging" / video_uuid, ignore_errors=True
            )
        metrics["ops_total"] = {
            "put_count": counting.put_count,
            "put_bytes": counting.put_bytes,
            "head_count": counting.head_count,
            "get_count": counting.get_count,
            "get_bytes": counting.get_bytes,
            "commit_attempts": commit_stats.get("attempts", 0),
        }
        metrics["media_sha256"] = (state_store.doc.get("media") or {}).get("sha256")
        metrics["object_key"] = (state_store.doc.get("media") or {}).get("object_key")
        metrics["free_disk_bytes_after"] = shutil.disk_usage(self.temp_root).free
        metrics["completed_at"] = utcnow()
        self._write_metrics_snapshot(run_id, metrics)
        logger.info(
            "dual-write %s result=%s state=%s",
            video_uuid[:8],
            metrics["result"],
            metrics["final_state"],
        )

    # -- metrics (packet §36: immutable, run-unique snapshots) --------------

    def _new_run_id(self, video_uuid: str) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        base = f"{stamp}_{video_uuid[:8].lower()}"
        existing = self._metrics_dir()
        candidate = base
        suffix = 1
        while (existing / f"{candidate}.json").exists():
            suffix += 1
            candidate = f"{base}-{suffix}"
        return candidate

    def _metrics_dir(self) -> Path:
        self._ensure_dirs()
        metrics_dir = self.state_dir / "metrics"
        metrics_dir.mkdir(parents=True, exist_ok=True)
        return metrics_dir

    def _write_metrics_snapshot(self, run_id: str, metrics: dict) -> None:
        path = self._metrics_dir() / f"{run_id}.json"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL  # refuse to overwrite
        try:
            fd = os.open(path, flags, 0o600)
        except FileExistsError:
            raise RuntimeError(
                f"metrics snapshot collision for {run_id}; refusing to overwrite"
            )
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(metrics, fh, ensure_ascii=False, indent=2, sort_keys=True)
        self.metrics_snapshots.append(str(path))


# ---------------------------------------------------------------------------
# Caption-only mutation (packet §32) — one-shot, production runtime context

INGEST_IMPL_VERSION = "media_backbone_v1"
RENDITION_SEMANTICS = "photos_edited_rendition"


def mode_caption_mutation(config, video_uuid: str) -> int:
    """Caption-only update through the normal production transport.

    Gate: Photos edit fingerprint MUST be unchanged (media unchanged).
    Behavior: same media/blob, same MediaRevision, new CaptionRevision,
    ZERO B2 upload (no object-store operations at all). The commit goes
    through the authenticated backend endpoint; server-side idempotence
    makes retries safe.
    """
    pdw = ProductionDualWrite.from_config(config)
    if pdw is None:
        print(json.dumps({"mode": "caption-mutation", "outcome": "refused_flags_off"}))
        return 3
    if not pdw.should_process(video_uuid):
        print(
            json.dumps(
                {"mode": "caption-mutation", "outcome": "refused_not_allowlisted"}
            )
        )
        return 3
    state_dir = pdw.state_dir
    state_store = IngestStateStore(state_dir / f"{video_uuid}.json")
    state_store.load(video_uuid)
    doc = state_store.doc
    media = doc.get("media") or {}
    if not media.get("sha256") or state_store.state is not IngestState.CACHE_CLEANED:
        print(
            json.dumps(
                {
                    "mode": "caption-mutation",
                    "outcome": "refused_journal_not_terminal",
                    "state": state_store.state.value,
                }
            )
        )
        return 3

    evidence = json.loads(
        (state_dir / f"{video_uuid}.evidence.json").read_text(encoding="utf-8")
    )
    db = get_photos_db(pdw.library_path)
    matches = db.photos(uuid=[video_uuid])
    if not matches:
        raise SystemExit(f"asset not found: {video_uuid}")
    photo = matches[0]
    new_fingerprint = pdw._edit_fingerprint(photo)
    if new_fingerprint != evidence.get("edit_fingerprint"):
        print(
            json.dumps(
                {
                    "mode": "caption-mutation",
                    "outcome": "refused_media_changed",
                    "fingerprint_before": evidence.get("edit_fingerprint"),
                    "fingerprint_after": new_fingerprint,
                }
            )
        )
        return 2

    stable = pdw._stable_provider()
    stable_result: CaptionResult = stable.get_caption(video_uuid)
    if not stable_result.available:
        raise SystemExit(f"caption unavailable: {stable_result.error}")
    if stable_result.sha256 == (doc.get("caption") or {}).get("sha256"):
        print(
            json.dumps(
                {
                    "mode": "caption-mutation",
                    "outcome": "unchanged_caption",
                    "caption_sha256": stable_result.sha256,
                }
            )
        )
        return 1

    shadow = PhotosDbCaptionProviderShadow(pdw.library_path)
    shadow_result = shadow.get_caption(video_uuid)
    parity = compare_caption_providers([(video_uuid, stable_result, shadow_result)])
    media_meta = evidence.get("media_metadata") or {}
    parsed = parse_caption_metadata(stable_result.raw or "")
    document = {
        "payload": {
            "video_uuid": video_uuid,
            "ingest_impl_version": INGEST_IMPL_VERSION,
            "rendition_semantics": RENDITION_SEMANTICS,
            "caption": {
                "raw": stable_result.raw,
                "sha256": stable_result.sha256,
                "provider": stable_result.provider,
            },
            "blob": {
                "sha256": media["sha256"],
                "byte_size": media["byte_size"],
                "object_key": media["object_key"],
                "storage_backend": pdw.os_cfg.storage_backend or "b2",
                "bucket": pdw.os_cfg.bucket,
            },
            "remote_verified": True,
        },
        "extra": {
            "environment": pdw.os_cfg.environment,
            "codec": media_meta.get("codec"),
            "width": media_meta.get("width"),
            "height": media_meta.get("height"),
            "duration_seconds": media_meta.get("duration_seconds"),
            "photos_edit_fingerprint": new_fingerprint,
            "source_provenance": {
                "photos_asset_uuid": (evidence.get("photo") or {}).get("uuid"),
                "original_filename": (evidence.get("photo") or {}).get("original_filename"),
                "rendition_semantics": evidence.get("rendition_semantics"),
                "hasadjustments": (evidence.get("photo") or {}).get("hasadjustments"),
                "captured_at": evidence.get("captured_at"),
            },
            "shadow_provider": shadow_result.provider,
            "shadow_raw": shadow_result.raw,
            "shadow_sha256": shadow_result.sha256,
            "shadow_available": shadow_result.available,
            "parser_version": parsed.get("parser"),
            "parsed_json": parsed.get("result"),
            "mutation_kind": "caption_only",
        },
    }
    pdw._update_evidence(
        video_uuid,
        lambda ev: ev.update(
            {
                "edit_fingerprint": new_fingerprint,
                "caption": {
                    "provider": stable_result.provider,
                    "available": True,
                    "caption_sha256": stable_result.sha256,
                    "caption_length": len(stable_result.raw or ""),
                    "caption_utf8_bytes": len((stable_result.raw or "").encode("utf-8")),
                    "caption_raw": stable_result.raw,
                },
                "shadow": {
                    "provider": shadow_result.provider,
                    "available": shadow_result.available,
                    "shadow_sha256": shadow_result.sha256,
                    "shadow_length": len(shadow_result.raw or ""),
                    "shadow_raw": shadow_result.raw,
                    "error_family": shadow_result.error_family,
                },
                "parity": parity,
                "mutation": {
                    "kind": "caption_only",
                    "captured_at": utcnow(),
                    "previous_caption_sha256": (doc.get("caption") or {}).get("sha256"),
                },
            }
        ),
    )
    result = pdw._post_commit_document(
        document, state_dir / f"{video_uuid}.commit_receipt.json"
    )
    # The journal is operational state: record the committed caption so a
    # repeated identical mutation is a no-op. The server DB rows remain the
    # durable authority.
    doc["caption"] = {
        "provider": stable_result.provider,
        "raw": stable_result.raw,
        "sha256": stable_result.sha256,
    }
    state_store.persist()
    run_id = pdw._new_run_id(video_uuid)
    pdw._write_metrics_snapshot(
        run_id,
        {
            "version": METRICS_VERSION,
            "run_id": run_id,
            "video_uuid": video_uuid,
            "environment": pdw.os_cfg.environment,
            "bucket": pdw.os_cfg.bucket,
            "started_at": utcnow(),
            "completed_at": utcnow(),
            "mutation_kind": "caption_only",
            "result": "caption_revision_committed",
            "blob_sha256": result.get("blob_sha256"),
            "caption_revision_existed": result.get("caption_revision_existed"),
            "ops_total": {
                "put_count": 0,
                "put_bytes": 0,
                "head_count": 0,
                "get_count": 0,
                "get_bytes": 0,
                "commit_attempts": 1,
            },
            "zero_b2_upload": True,
        },
    )
    print(
        json.dumps(
            {
                "mode": "caption-mutation",
                "outcome": "committed",
                "caption_revision_existed": result.get("caption_revision_existed"),
                "blob_sha256": result.get("blob_sha256"),
                "zero_b2_upload": True,
            },
            ensure_ascii=False,
        )
    )
    return 0


# ---------------------------------------------------------------------------
# One-shot production-runtime run mode (canary recovery / controlled gates).
# Uses the SAME production config, allowlist guard, store and authenticated
# HTTP commit transport as the daemon hook; materialization reuses the
# production MediaMaterializer primitive (never a second parallel daemon).

RENDITION_SEMANTICS_RUN = RENDITION_SEMANTICS


def mode_run(config, video_uuid: str, env_file: str | None = None) -> int:
    """Drive ONE allowlisted asset through verified object-store ingest,
    running inside the production agent runtime context (same interpreter,
    host, user, Photos TCC) with the authenticated backend commit transport.

    The legacy path for the asset must already be healthy; this mode is the
    additive object-store leg only (and the retry/recovery entry point)."""
    pdw = ProductionDualWrite.from_config(config)
    if pdw is None:
        print(json.dumps({"mode": "dual-write-run", "outcome": "refused_flags_off"}))
        return 3
    if not pdw.should_process(video_uuid):
        print(json.dumps({"mode": "dual-write-run", "outcome": "refused_not_allowlisted"}))
        return 3
    if env_file:
        pdw.env_file = str(Path(env_file).expanduser())
    state_dir = pdw.state_dir
    state_store = IngestStateStore(state_dir / f"{video_uuid}.json")
    state_store.load(video_uuid)
    if state_store.state.is_terminal:
        print(
            json.dumps(
                {
                    "mode": "dual-write-run",
                    "outcome": "already_terminal",
                    "state": state_store.state.value,
                    "zero_new_ops": True,
                }
            )
        )
        return 0
    if not (state_dir / f"{video_uuid}.evidence.json").exists():
        pdw._capture_evidence(video_uuid)

    from ..media_materializer import MediaMaterializer

    materializer = MediaMaterializer(
        str(Path(config.media.materialization_dir).expanduser())
        if hasattr(config.media, "materialization_dir")
        else "~/.diveanalyzer/materialized_assets",
        max_bytes=int(getattr(config.media, "materialization_max_bytes", 2_000_000_000)),
        osxphotos_path=getattr(config.media, "osxphotos_path", "osxphotos"),
        use_photokit=bool(getattr(config.media, "materialization_use_photokit", False)),
    )

    def materialize_from_photos(asset_uuid: str, workdir: Path) -> Path:
        exported = materializer.materialize(asset_uuid)
        target = workdir / f"legacy_rendition{Path(exported).suffix.lower() or '.mov'}"
        shutil.copy2(exported, target)
        try:
            materializer.cleanup_failed_residue(asset_uuid)
        except Exception:
            pass
        return target

    staging_root = pdw.temp_root / "dual_write_run" / video_uuid
    staging_root.mkdir(parents=True, exist_ok=True)
    workdir = staging_root / "work"
    if workdir.exists():
        shutil.rmtree(workdir, ignore_errors=True)
    staged_path = materialize_from_photos(video_uuid, workdir)

    pdw._set_stage_meta(
        video_uuid,
        {
            "staged_path": str(staged_path),
            "staged_bytes": staged_path.stat().st_size,
            "copy_seconds": 0.0,
            "run_mode": "one_shot_production_runtime",
        },
    )
    pdw._ensure_dirs()
    run_started = time.time()
    try:
        pdw._drive(video_uuid, staged_path)
    except ObjectStoreError as exc:
        print(
            json.dumps(
                {
                    "mode": "dual-write-run",
                    "outcome": "retryable_failure",
                    "error_family": type(exc).__name__,
                }
            )
        )
        return 1
    shutil.rmtree(staging_root, ignore_errors=True)
    journal = json.loads((state_dir / f"{video_uuid}.json").read_text(encoding="utf-8"))
    final_state = journal.get("state")
    metrics_files = sorted((state_dir / "metrics").glob("*.json"), key=lambda p: p.stat().st_mtime)
    snapshot = json.loads(metrics_files[-1].read_text()) if metrics_files else {}
    print(
        json.dumps(
            {
                "mode": "dual-write-run",
                "outcome": "driven",
                "final_state": final_state,
                "result": snapshot.get("result"),
                "media_sha256": snapshot.get("media_sha256"),
                "object_key": snapshot.get("object_key"),
                "elapsed_seconds": round(time.time() - run_started, 2),
                "metrics_snapshot": metrics_files[-1].name if metrics_files else None,
            },
            ensure_ascii=False,
        )
    )
    return 0 if final_state == "CACHE_CLEANED" else 1


def main(argv=None) -> int:
    import argparse
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

    parser = argparse.ArgumentParser(description="P4 production dual-write one-shot modes")
    parser.add_argument("--config", required=True)
    parser.add_argument("--env-file")
    parser.add_argument("mode", choices=["caption-mutation", "run"])
    parser.add_argument("--video-uuid", required=True)
    args = parser.parse_args(argv)

    from ..config import Config

    config = Config.from_file(args.config)
    if not config.validate():
        raise SystemExit("invalid config")
    if args.mode == "caption-mutation":
        return mode_caption_mutation(config, args.video_uuid)
    if args.mode == "run":
        return mode_run(config, args.video_uuid, args.env_file)
    return 2


if __name__ == "__main__":
    import sys

    sys.exit(main())
