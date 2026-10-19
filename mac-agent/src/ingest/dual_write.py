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
- activation boundary (packet MEDIA_BACKBONE_P7 §5/§6): normal production
  triggers are the EXISTING media-job events whose request_reason marks a
  genuinely new captioned production clip (`continuous_new_ingest` +
  `trigger_reason`); the fixed 5-10 UUID cohort allowlist remains ONLY as
  the canary/debug mode (dual_write.continuous_new_ingest=false). Enabling
  continuous dual-write adds NO discovery/scanning of Photos, the DB, or
  the library: historical media is reached exclusively by the dedicated
  migration engine (P7), never by the continuous path.
- ONE materialization: the legacy export is reused; no second Photos export
- max one active dual-write materialization (backpressure); triggers arriving
  while the slot is busy are refused with a bounded pending marker (no staged
  byte accumulation), recoverable via the one-shot run mode
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
from .media_content_type import video_content_type
from .errors import ObjectStoreError, ObjectStoreUnavailable
from .objectstore.b2 import B2Config, BackblazeB2Store
from .state_store import IngestStateStore
from .states import IngestState
from ..sync_client import _curl_post

logger = logging.getLogger(__name__)

UUID_PATTERN = re.compile(
    r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
)
PROD_ALLOWLIST_MIN_COUNT = 5
PROD_ALLOWLIST_MAX_COUNT = 10
METRICS_VERSION = "media_backbone_p4_v1"
DEFAULT_COMMIT_ENDPOINT_PATH = "/api/v1/media/backbone/commit"
MAX_PASSES_PER_TRIGGER = 5
RETRY_BACKOFF_SECONDS = 5.0


def validate_prod_allowlist(allowlist: list[str]) -> None:
    """P4.2 hard guard (packet §6): bounded production cohort allowlist.

    EXPLICIT ALLOWLIST ONLY: 5 <= len(allowlist) <= 10, all entries valid
    unique Photos UUIDs. Any other count (0..4 or >10), duplicate, or
    malformed entry REFUSES TO ARM production dual-write. Implicit
    readiness (whole library, whole album, all captioned clips) is
    structurally impossible: the count must be supplied explicitly.
    """
    if not isinstance(allowlist, (list, tuple)):
        raise ValueError("prod dual-write allowlist must be a list of UUIDs")
    if not (
        PROD_ALLOWLIST_MIN_COUNT
        <= len(allowlist)
        <= PROD_ALLOWLIST_MAX_COUNT
    ):
        raise ValueError(
            f"prod dual-write allowlist guard violation: {len(allowlist)} entries; "
            f"a bounded production cohort of {PROD_ALLOWLIST_MIN_COUNT}-"
            f"{PROD_ALLOWLIST_MAX_COUNT} explicit UUIDs is authorized "
            f"(REFUSE TO ARM outside this range)"
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

    def put(self, key: str, source, content_type: str | None = None):
        if self._fail_put_once:
            self._fail_put_once = False
            raise ObjectStoreUnavailable(
                "injected first-put failure (P4 controlled test)"
            )
        self.put_count += 1
        result = self._inner.put(key, source, content_type=content_type)
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


class _PinnedCaptionProvider:
    """Pin Photos-bound caption reads to the agent-local asset UUID.
    The coordinator is keyed by the canonical dive UUID (journal, workdir,
    commit payload), but caption providers query the Photos library, where
    only the agent-local asset UUID resolves. This adapter keeps the
    canonical identity for everything durable while serving caption bytes
    from the local asset — mirroring the migration engine, which commits
    item.video_uuid (canonical) with captions read via resolved_asset_uuid.
    """

    def __init__(self, inner, photos_uuid: str):
        self._inner = inner
        self._photos_uuid = photos_uuid

    def get_caption(self, _video_uuid: str):
        return self._inner.get_caption(self._photos_uuid)


def _resolve_agent_local_uuid(
    video_uuid: str,
    explicit: str | None,
    recorded: str | None,
) -> str | None:
    """Resolve the Photos-bound local identity with consistent retry rules.

    - A valid explicit UUID always wins and (via _pin_agent_local_uuid)
      persists, so a correction converges future retries on one identity.
    - An omitted argument retains the pinned identity, if any.
    - Malformed explicit OR recorded values raise ValueError (typed error)
      instead of silently falling back to an unrelated canonical Photos
      lookup. Single-identity callers pass neither and resolve to None,
      preserving the legacy behavior exactly.
    """
    if explicit is not None:
        if not isinstance(explicit, str) or not UUID_PATTERN.match(explicit):
            raise ValueError(
                f"malformed agent_local_uuid for {video_uuid[:8]}: {explicit!r}"
            )
        return explicit
    if recorded is not None:
        if not isinstance(recorded, str) or not UUID_PATTERN.match(recorded):
            raise ValueError(
                f"recorded agent_local_uuid for {video_uuid[:8]} is malformed: "
                f"{recorded!r}; refusing to fall back to an unrelated "
                "canonical Photos lookup"
            )
        return recorded
    return None


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
        if not dual_cfg.continuous_new_ingest:
            # Canary/debug mode: the bounded explicit cohort allowlist is
            # mandatory (P4.2 packet §6). Continuous production semantics
            # (P7 packet §5/§7) never require hand-edited UUID lists; an
            # allowlist may still be supplied as an additional debug filter.
            validate_prod_allowlist(list(dual_cfg.allowlist or []))
        return cls(config)

    # -- guards -------------------------------------------------------------

    def should_process(
        self,
        video_uuid: str,
        request_reason: str | None = None,
        agent_local_uuid: str | None = None,
    ) -> bool:
        """Activation boundary (P7 packet §5/§6).

        Two disjoint triggers:
        - continuous production: the caller presents the exact configured
          new-captioned-ingestion request reason (an existing production
          media-job event stream — no scanning, no backlog sweep);
        - canary/debug: explicit allowlist membership (unchanged P4.2 guard).

        Identity rule: `video_uuid` is the CANONICAL dive UUID (durable
        journal/commit identity). `agent_local_uuid` is the Photos asset
        UUID the Mac agent resolved locally; it may differ from canonical
        whenever the agent's Photos library carries its own asset identity.
        The canary allowlist names assets, so either identity may satisfy it;
        the journal/commit key is always the canonical UUID.
        """
        if not (self.os_cfg.enabled and self.dual.enabled):
            return False
        if not UUID_PATTERN.match(video_uuid or ""):
            return False
        if self.dual.continuous_new_ingest:
            if (request_reason or "") == (self.dual.trigger_reason or ""):
                return True
        candidates = {video_uuid.upper()}
        if isinstance(agent_local_uuid, str) and UUID_PATTERN.match(agent_local_uuid):
            candidates.add(agent_local_uuid.upper())
        return any(
            u in {a.upper() for a in self.dual.allowlist} for u in candidates
        )

    def _ensure_dirs(self) -> None:
        if self._state_dir_ready:
            return
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self._state_dir_ready = True

    # -- hook entry points --------------------------------------------------

    def stage_copy(
        self,
        video_uuid: str,
        source_path: Path,
        request_reason: str | None = None,
        agent_local_uuid: str | None = None,
    ) -> Path | None:
        """Copy the already-materialized legacy bytes into the dual-write temp
        area while the legacy pipeline still owns them.

        `video_uuid` is the CANONICAL dive UUID: journal files, stage
        metadata and (via _drive) the commit payload are keyed by it, so the
        server registers MediaRevisions under the dive identity — never under
        a Mac-local Photos asset UUID. `agent_local_uuid` (when different)
        is recorded in the stage metadata and used ONLY for Photos-bound
        reads (evidence capture, caption providers). When omitted, the
        single-identity legacy behavior is unchanged.

        Returns None (skip) when the asset is not activated (continuous
        reason or canary allowlist), the journal is already terminal, the
        single backpressure slot is occupied (a tiny bounded pending marker
        is recorded in the latter case; no staged media bytes accumulate),
        or free disk cannot hold the staged copy plus the guard margin.
        Raises on real staging errors (legacy path unaffected either way -
        the caller catches and continues).
        """
        if not self.should_process(video_uuid, request_reason, agent_local_uuid):
            return None
        # Identity rule (retry-safe): a valid explicit local UUID overrides
        # the pin and persists; an omitted argument retains the pinned
        # identity. The chosen identity is validated BEFORE any file or state
        # mutation, so a malformed value can never trigger an unrelated
        # canonical Photos lookup or be persisted.
        photos_local = _resolve_agent_local_uuid(
            video_uuid,
            agent_local_uuid,
            self._read_stage_meta(video_uuid).get("agent_local_uuid"),
        )
        self._ensure_dirs()
        # Pin the validated identity BEFORE every early return below, so an
        # omitted retry keeps converging on the corrected identity instead of
        # silently reverting to a canonical Photos lookup.
        self._pin_agent_local_uuid(video_uuid, photos_local)
        try:
            source_bytes = Path(source_path).stat().st_size
        except OSError as exc:
            raise ObjectStoreUnavailable(
                f"staging source vanished before dual-write copy: {exc}"
            ) from exc
        free_bytes = shutil.disk_usage(self.temp_root).free
        margin = int(getattr(self.os_cfg, "min_free_disk_bytes", 0) or 0)
        if free_bytes - source_bytes < margin:
            logger.warning(
                "dual-write staging refused for %s: free=%s staged=%s guard=%s",
                video_uuid[:8],
                free_bytes,
                source_bytes,
                margin,
            )
            # Merge refusal fields into the existing meta: a wholesale
            # replace would drop the just-pinned agent_local_uuid and the
            # original trigger provenance (triggered_at/request_reason).
            existing_meta = self._read_stage_meta(video_uuid)
            existing_meta.update(
                {
                    "staging_refused": True,
                    "skip_reason": "insufficient_disk_for_staging",
                    "free_bytes": free_bytes,
                    "source_bytes": source_bytes,
                    "refused_at": utcnow(),
                }
            )
            self._set_stage_meta(video_uuid, existing_meta)
            return None
        # Read-only terminal check BEFORE any journal load/mutation:
        # a terminal journal stays an idempotent skip even with a corrected
        # identity, and a refusal must never create the journal file.
        terminal, _ = self._journal_terminal_readonly(video_uuid)
        if terminal:
            # clean up a retained staging copy from any previous attempt
            staging = self.temp_root / "dual_write_staging" / video_uuid
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            return None
        # Evidence/identity consistency: a corrected local UUID must not
        # silently reuse canonical evidence captured from the old asset.
        # Any mismatch refuses BEFORE any evidence/byte/journal mutation and
        # retains the recorded evidence for operator-reviewed recovery —
        # never auto-invalidate (an early backpressure skip or a failed copy
        # after invalidation would let a later retry capture fresh evidence
        # for stale bytes). Terminal journals returned above (idempotent
        # skip); the pin persists above so corrections keep converging
        # retries on an explicit refusal.
        self._ensure_evidence_identity_consistent(
            video_uuid, photos_local or video_uuid,
            context="stage_copy", ignore_staged=True,
        )
        state_store = IngestStateStore(self.state_dir / f"{video_uuid}.json")
        state_store.load(video_uuid)
        if state_store.state.is_terminal:
            # Race: journal turned terminal between the read-only check and
            # the load above; same idempotent skip, no evidence mutation.
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
                # Bounded backlog policy (P4.2 packet §19): NO staged bytes are
                # retained for skipped triggers — only a tiny pending marker
                # so the asset remains discoverable for a bounded re-drive via
                # the one-shot run mode. Staged full-media copies exist for at
                # most ONE asset (the active one) at any moment. Any previous
                # staging metadata for this asset is preserved.
                existing_meta = self._read_stage_meta(video_uuid)
                existing_meta.update(
                    {
                        "backpressure_skip": True,
                        "skip_reason": "one_active_materialization_slot_busy",
                        "skipped_at": utcnow(),
                    }
                )
                self._set_stage_meta(video_uuid, existing_meta)
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
        # P9-B passive capture: the trigger provenance is recorded ONCE (first
        # trigger wins) and never clobbered, so a later observation of the
        # stage metadata can reconstruct WHEN the natural ingest was seen and
        # under which activation boundary it was armed.
        # Both identities are recorded: the canonical UUID keys every durable
        # file, while the agent-local UUID is kept for Photos-bound reads.
        # First trigger wins for provenance (P9-B). A valid explicit local
        # UUID overrides a stale pin and persists, so corrections converge
        # future retries on one identity — never silent divergence.
        meta = self._read_stage_meta(video_uuid)
        meta.setdefault("triggered_at", utcnow())
        meta.setdefault("request_reason", request_reason or "")
        meta.setdefault(
            "activation",
            "continuous"
            if (request_reason or "") == (self.dual.trigger_reason or "")
            else "allowlist",
        )
        if photos_local is not None:
            previous = meta.get("agent_local_uuid")
            meta["agent_local_uuid"] = photos_local
            if (
                previous is not None
                and isinstance(previous, str)
                and previous.upper() != photos_local.upper()
            ):
                logger.info(
                    "dual-write %s: agent-local UUID correction %s -> %s persists for retries",
                    video_uuid[:8],
                    previous,
                    photos_local,
                )
        meta.update(
            {
                "staged_path": str(target),
                "staged_bytes": target.stat().st_size,
                "copy_seconds": round(copy_seconds, 3),
            }
        )
        self._set_stage_meta(video_uuid, meta)
        return target

    def launch(
        self, video_uuid: str, staged_path: Path, agent_local_uuid: str | None = None
    ) -> bool:
        """Start the background verified-ingest for a staged copy.

        `video_uuid` is the canonical dive UUID; `agent_local_uuid` is the
        Photos asset UUID for Photos-bound reads (evidence, captions).
        """
        worker = threading.Thread(
            target=self._run_guarded,
            args=(video_uuid, Path(staged_path), agent_local_uuid),
            name=f"dual-write-{video_uuid[:8].lower()}",
            daemon=True,
        )
        worker.start()
        return True

    def _release(self, video_uuid: str) -> None:
        with self._active_lock:
            self._active.discard(video_uuid)

    def _run_guarded(
        self, video_uuid: str, staged_path: Path, agent_local_uuid: str | None = None
    ) -> None:
        try:
            self._drive(video_uuid, staged_path, agent_local_uuid)
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

    def _pin_agent_local_uuid(self, video_uuid: str, photos_local: str | None) -> None:
        """Persist a resolved local identity without clobbering provenance.

        Merge-only: records the validated local UUID when it is new or a
        correction (case-insensitive compare, explicit value wins), and is a
        no-op when nothing is resolved or the pin already matches. Never
        touches triggered_at/request_reason/activation or staged bytes.
        """
        if photos_local is None:
            return
        meta = self._read_stage_meta(video_uuid)
        previous = meta.get("agent_local_uuid")
        if (
            isinstance(previous, str)
            and previous.upper() == photos_local.upper()
        ):
            return
        if previous is not None:
            logger.info(
                "dual-write %s: agent-local UUID correction %s -> %s persists for retries",
                video_uuid[:8],
                previous,
                photos_local,
            )
        meta["agent_local_uuid"] = photos_local
        self._set_stage_meta(video_uuid, meta)

    def _read_evidence_doc(self, video_uuid: str) -> dict | None:
        """Read the canonical evidence file without side effects.

        Returns None when no evidence file exists or it is unreadable —
        the caller then follows the normal capture path.
        """
        path = self.state_dir / f"{video_uuid}.evidence.json"
        if not path.exists():
            return None
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return doc if isinstance(doc, dict) else None

    def _journal_terminal_readonly(self, video_uuid: str) -> tuple[bool, str | None]:
        """Read-only terminal check that never creates or repairs the journal.

        Returns (is_terminal, state_or_None). Absent, unreadable, or
        malformed journals report (False, None-or-state) so the caller can
        run the evidence gate BEFORE any IngestStateStore.load() that would
        create/overwrite the file on a refusal path. Only the two terminal
        states from the existing journal schema count as terminal.
        """
        journal_path = self.state_dir / f"{video_uuid}.json"
        if not journal_path.exists():
            return False, None
        try:
            doc = json.loads(journal_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False, None
        if not isinstance(doc, dict):
            return False, None
        state = doc.get("state")
        if state in (
            IngestState.CACHE_CLEANED.value,
            IngestState.QUARANTINED.value,
        ):
            return True, state
        return False, state if isinstance(state, str) else None

    def _journal_progress_present(self, video_uuid: str) -> tuple[bool, str]:
        """Read-only check whether durable progress binds the recorded evidence.

        Returns (True, reason) when the journal advanced past DISCOVERED,
        carries media identity, a commit receipt exists, or the evidence
        already gained media metadata — i.e. recapturing evidence alone
        would combine one asset's evidence with another asset's
        bytes/commit. Creates no files (unlike IngestStateStore.load).
        """
        if (self.state_dir / f"{video_uuid}.commit_receipt.json").exists():
            return True, "commit receipt present"
        journal_path = self.state_dir / f"{video_uuid}.json"
        if journal_path.exists():
            try:
                doc = json.loads(journal_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return True, "journal unreadable"
            if not isinstance(doc, dict):
                return True, "journal malformed"
            if (doc.get("state") or "DISCOVERED") != "DISCOVERED":
                return True, f"journal state {doc.get('state')}"
            if doc.get("media"):
                return True, "journal carries media identity"
        evidence = self._read_evidence_doc(video_uuid)
        if isinstance(evidence, dict) and "media_metadata" in evidence:
            return True, "evidence already bound to staged media"
        return False, ""

    def _staged_copy_present(self, video_uuid: str) -> bool:
        """Whether a staged byte copy from a previous attempt is retained."""
        recorded = self._read_stage_meta(video_uuid).get("staged_path")
        return bool(recorded) and Path(recorded).is_file()

    def _ensure_evidence_identity_consistent(
        self,
        video_uuid: str,
        photos_uuid: str,
        *,
        context: str,
        ignore_staged: bool = False,
        recapture: bool = True,
    ) -> bool:
        """Validate existing canonical evidence against the resolved identity.

        Case-insensitive UUID compare. Absent evidence or a match returns
        False (nothing to do). A mismatch ALWAYS raises ValueError BEFORE any
        evidence/byte/journal mutation — never combine evidence from one
        asset with bytes/commit from another, and never auto-invalidate the
        recorded evidence. Auto-invalidation is unsafe: stage_copy may return
        early (backpressure) or fail the byte copy after the evidence was
        dropped, and mode_run may fail evidence capture after the drop — a
        later retry would then capture fresh evidence for stale bytes (or
        reuse the production vault bytes validated for the old asset). A
        mismatch therefore requires operator-reviewed recovery with the
        recorded evidence retained for inspection.

        `ignore_staged` / `recapture` are retained for call compatibility and
        ignored: no caller recaptures in place.

        The caller persists the (valid) pin first, so a correction keeps
        converging retries on one identity — an omitted retry re-hits this
        explicit refusal instead of silently reverting to the old asset.
        """
        evidence = self._read_evidence_doc(video_uuid)
        if evidence is None:
            return False
        recorded = (evidence.get("photo") or {}).get("uuid")
        if isinstance(recorded, str) and recorded.upper() == photos_uuid.upper():
            return False
        progress, reason = self._journal_progress_present(video_uuid)
        staged = self._staged_copy_present(video_uuid)
        detail = reason or ("staged bytes present" if staged else "fresh journal")
        raise ValueError(
            f"evidence identity mismatch for {video_uuid[:8]} ({context}): "
            f"recorded photo.uuid {recorded!r} != resolved {photos_uuid!r} "
            f"({detail}); refusing to combine evidence from one asset with "
            "bytes/commit from another. Evidence retained; requires "
            "operator-reviewed recovery for this canonical UUID."
        )

    def _capture_evidence(self, video_uuid: str, photos_uuid: str | None = None) -> None:
        """Exact-caption + shadow parity + provenance evidence (0600).

        Read-only with respect to Photos; no caption authority change.

        `video_uuid` is the canonical dive UUID (evidence file identity);
        `photos_uuid` is the agent-local Photos asset UUID actually queried
        in the library. A bare canonical substitution here would break: the
        canonical UUID does not resolve in Photos when the agent carries its
        own asset identity.
        """
        if photos_uuid is not None and (
            not isinstance(photos_uuid, str) or not UUID_PATTERN.match(photos_uuid)
        ):
            raise ValueError(
                f"malformed photos_uuid for evidence capture of {video_uuid[:8]}: "
                f"{photos_uuid!r}"
            )
        lookup_uuid = photos_uuid or video_uuid
        db = get_photos_db(self.library_path)
        matches = db.photos(uuid=[lookup_uuid])
        if not matches:
            raise ObjectStoreUnavailable(f"asset not found in Photos library: {lookup_uuid}")
        photo = matches[0]
        stable = self._stable_provider()
        shadow = PhotosDbCaptionProviderShadow(self.library_path)
        stable_result = stable.get_caption(lookup_uuid)
        shadow_result = shadow.get_caption(lookup_uuid)
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

    def _drive(
        self, video_uuid: str, staged_path: Path, agent_local_uuid: str | None = None
    ) -> None:
        """Drive one asset through verified ingest under its canonical UUID.

        `video_uuid` keys the journal, workdir, evidence file and commit
        payload (server-side MediaRevision identity). Photos-bound reads
        (evidence capture, caption provider) use `agent_local_uuid` when it
        differs — the canonical UUID need not resolve in the local Photos
        library. A valid explicit value overrides the pin and persists, so
        corrections converge future retries; an omitted value retains the
        pin. Malformed values raise ValueError before any file/state
        mutation — never a silent fallback to canonical Photos lookup.
        """
        photos_local = _resolve_agent_local_uuid(
            video_uuid,
            agent_local_uuid,
            self._read_stage_meta(video_uuid).get("agent_local_uuid"),
        )
        self._pin_agent_local_uuid(video_uuid, photos_local)
        photos_uuid = photos_local or video_uuid
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
        # Read-only terminal check BEFORE the evidence gate and BEFORE any
        # journal load: a terminal journal stays idempotent even with a
        # corrected identity, and load() would otherwise create/overwrite
        # the journal on a refusal path.
        terminal_readonly, _ = self._journal_terminal_readonly(video_uuid)
        if terminal_readonly:
            state_store.load(video_uuid)
            if state_store.state.is_terminal:
                metrics["result"] = "already_terminal"
                metrics["completed_at"] = utcnow()
                self._write_metrics_snapshot(run_id, metrics)
                return

        # Evidence/identity consistency: a corrected local UUID keeps any
        # existing canonical evidence file, so an existence check alone
        # would combine the old asset's evidence with the new identity's
        # reads/bytes/commit. Any mismatch refuses here — before capture,
        # ffprobe, and the coordinator — with the recorded evidence retained
        # (typed error, no journal mutation beyond the persisted pin).
        # Terminal journals returned above, preserving idempotence.
        self._ensure_evidence_identity_consistent(
            video_uuid, photos_uuid, context="drive",
        )
        state_store.load(video_uuid)
        if state_store.state.is_terminal:
            # Race: journal turned terminal between the read-only check and
            # the load above; same idempotent outcome, no evidence mutation.
            metrics["result"] = "already_terminal"
            metrics["completed_at"] = utcnow()
            self._write_metrics_snapshot(run_id, metrics)
            return
        if not (self.state_dir / f"{video_uuid}.evidence.json").exists():
            self._capture_evidence(video_uuid, photos_uuid)
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
        # P9-B passive capture: durable trigger provenance in every run's
        # metrics snapshot (request_reason only — never caption content).
        metrics["trigger"] = {
            "request_reason": stage_meta.get("request_reason"),
            "triggered_at": stage_meta.get("triggered_at"),
            "activation": stage_meta.get("activation"),
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
            # Pin the Photos-bound caption read to the agent-local asset;
            # the coordinator's canonical video_uuid still keys the journal
            # and the commit payload.
            caption_provider=_PinnedCaptionProvider(
                self._stable_provider(), photos_uuid
            ),
            min_free_disk_bytes=int(self.os_cfg.min_free_disk_bytes),
            storage_backend=self.os_cfg.storage_backend or "b2",
            bucket=b2_config.bucket,
            skip_put_if_remote_present=True,
            # P5 §20 (future-ingest Content-Type): ffprobe evidence, never a
            # filename guess; no historical object is rewritten.
            content_type=video_content_type(
                media_meta.get("container"),
                media_meta.get("codec"),
                staged_path.suffix.lstrip("."),
            ),
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
        # P9-B passive capture: when the commit receipt exists, record the
        # durable server-side identity summary (ids only, no caption bytes).
        receipt_path = self.state_dir / f"{video_uuid}.commit_receipt.json"
        if receipt_path.exists():
            try:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                result = receipt.get("result") or {}
                metrics["commit"] = {
                    "transport": (receipt.get("transport") or "http"),
                    "environment": result.get("environment"),
                    "blob_sha256": result.get("blob_sha256"),
                    "media_blob_location_id": result.get("media_blob_location_id"),
                    "media_revision_id": result.get("media_revision_id"),
                    "caption_revision_id": result.get("caption_revision_id"),
                    "ingest_state_id": result.get("ingest_state_id"),
                    "blob_location_existed": result.get("blob_location_existed"),
                    "media_revision_existed": result.get("media_revision_existed"),
                }
            except (OSError, ValueError):
                metrics["commit"] = {"error": "receipt_unreadable"}
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


def mode_caption_mutation(
    config,
    video_uuid: str,
    request_reason: str | None = None,
    agent_local_uuid: str | None = None,
) -> int:
    """Caption-only update through the normal production transport.

    Gate: Photos edit fingerprint MUST be unchanged (media unchanged).
    Behavior: same media/blob, same MediaRevision, new CaptionRevision,
    ZERO B2 upload (no object-store operations at all). The commit goes
    through the authenticated backend endpoint; server-side idempotence
    makes retries safe.

    `video_uuid` is the canonical dive UUID (journal/commit identity);
    `agent_local_uuid` is the Photos asset UUID for library reads when it
    differs from canonical.
    """
    pdw = ProductionDualWrite.from_config(config)
    if pdw is None:
        print(json.dumps({"mode": "caption-mutation", "outcome": "refused_flags_off"}))
        return 3
    if not pdw.should_process(video_uuid, request_reason, agent_local_uuid):
        print(
            json.dumps(
                {"mode": "caption-mutation", "outcome": "refused_not_activated"}
            )
        )
        return 3
    try:
        photos_local = _resolve_agent_local_uuid(
            video_uuid,
            agent_local_uuid,
            pdw._read_stage_meta(video_uuid).get("agent_local_uuid"),
        )
    except ValueError as exc:
        print(
            json.dumps(
                {
                    "mode": "caption-mutation",
                    "outcome": "refused_malformed_agent_local_uuid",
                    "error": str(exc),
                }
            )
        )
        return 3
    # Persist a valid explicit correction so retries need not retype it;
    # resolving the pin first means an omitted argument reuses the recorded
    # identity instead of falling back to canonical.
    pdw._pin_agent_local_uuid(video_uuid, photos_local)
    photos_uuid = photos_local or video_uuid
    try:
        pdw._ensure_evidence_identity_consistent(
            video_uuid, photos_uuid,
            context="caption-mutation", recapture=False,
        )
    except ValueError as exc:
        # Caption-mutation consumes the SAVED evidence (fingerprint gate,
        # caption bytes, commit provenance): a corrected identity must never
        # mix new reads with old saved evidence. Refuse, never recapture in
        # place — recapture would erase the before/after fingerprint gate.
        print(
            json.dumps(
                {
                    "mode": "caption-mutation",
                    "outcome": "refused_evidence_identity_mismatch",
                    "error": str(exc)[:300],
                }
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
    matches = db.photos(uuid=[photos_uuid])
    if not matches:
        raise SystemExit(f"asset not found: {photos_uuid}")
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
    stable_result: CaptionResult = stable.get_caption(photos_uuid)
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
    shadow_result = shadow.get_caption(photo.uuid)
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


def mode_run(
    config,
    video_uuid: str,
    env_file: str | None = None,
    request_reason: str | None = None,
    agent_local_uuid: str | None = None,
) -> int:
    """Drive ONE allowlisted asset through verified object-store ingest,
    running inside the production agent runtime context (same interpreter,
    host, user, Photos TCC) with the authenticated backend commit transport.

    The legacy path for the asset must already be healthy; this mode is the
    additive object-store leg only (and the retry/recovery entry point).

    `video_uuid` is the canonical dive UUID (journal/vault/commit identity);
    `agent_local_uuid` is the Photos asset UUID for library reads and
    Photos materialization when it differs from canonical. An omitted
    argument reuses the pinned identity from a previous trigger; a valid
    explicit value corrects the pin and persists for future retries."""
    pdw = ProductionDualWrite.from_config(config)
    if pdw is None:
        print(json.dumps({"mode": "dual-write-run", "outcome": "refused_flags_off"}))
        return 3
    if not pdw.should_process(video_uuid, request_reason, agent_local_uuid):
        print(json.dumps({"mode": "dual-write-run", "outcome": "refused_not_activated"}))
        return 3
    try:
        photos_local = _resolve_agent_local_uuid(
            video_uuid,
            agent_local_uuid,
            pdw._read_stage_meta(video_uuid).get("agent_local_uuid"),
        )
    except ValueError as exc:
        print(
            json.dumps(
                {
                    "mode": "dual-write-run",
                    "outcome": "refused_malformed_agent_local_uuid",
                    "error": str(exc),
                }
            )
        )
        return 3
    pdw._pin_agent_local_uuid(video_uuid, photos_local)
    photos_uuid = photos_local or video_uuid
    if env_file:
        pdw.env_file = str(Path(env_file).expanduser())
    state_dir = pdw.state_dir
    # Read-only terminal check BEFORE the evidence gate and BEFORE any
    # journal load: load() would otherwise create/overwrite the journal on
    # a refusal path (absent/corrupt journal + evidence mismatch).
    terminal_readonly, terminal_state = pdw._journal_terminal_readonly(video_uuid)
    if terminal_readonly:
        print(
            json.dumps(
                {
                    "mode": "dual-write-run",
                    "outcome": "already_terminal",
                    "state": terminal_state,
                    "zero_new_ops": True,
                }
            )
        )
        return 0
    try:
        pdw._ensure_evidence_identity_consistent(
            video_uuid, photos_uuid, context="dual-write-run",
        )
    except ValueError as exc:
        print(
            json.dumps(
                {
                    "mode": "dual-write-run",
                    "outcome": "refused_evidence_identity_mismatch",
                    "error": str(exc)[:300],
                }
            )
        )
        return 3
    # The evidence gate passed with no journal mutation; now load (which may
    # create a fresh journal) and re-check terminal for a post-gate race.
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
        try:
            pdw._capture_evidence(video_uuid, photos_uuid)
        except ObjectStoreError as exc:
            # Structured recovery response, same shape as the drive
            # failures below: retryable without masking unexpected errors
            # (only ObjectStoreError is caught here).
            print(
                json.dumps(
                    {
                        "mode": "dual-write-run",
                        "outcome": "retryable_failure",
                        "error_family": type(exc).__name__,
                        "stage": "evidence_capture",
                    }
                )
            )
            return 1

    # Preferred source of canonical bytes: an existing staging copy produced
    # by the legacy pipeline hook (§16 — reuse already-materialized legacy
    # bytes; no second Photos materialization). Only when absent, acquire
    # through the production vault / MediaMaterializer primitives.
    stage_meta = pdw._read_stage_meta(video_uuid)
    staged_path: Path | None = None
    existing = stage_meta.get("staged_path")
    expected_bytes = stage_meta.get("staged_bytes")
    if existing:
        candidate = Path(existing)
        if (
            candidate.is_file()
            and expected_bytes
            and candidate.stat().st_size == int(expected_bytes)
        ):
            staged_path = candidate
    if staged_path is None:
        acquired = False
        # Production vault: the legacy pipeline's checksum-validated
        # materialization source (same bytes the transcoder consumed).
        # Reached only after the identity gate above refused any evidence
        # mismatch, so vault/staged bytes and evidence share one identity.
        try:
            sv_cfg = getattr(config.media, "source_vault", None)
            if (
                sv_cfg is not None
                and getattr(sv_cfg, "enabled", False)
            ):
                from ..source_vault import MediaSourceVault

                vault = MediaSourceVault(
                    sv_cfg.root,
                    getattr(sv_cfg, "volume_uuid", ""),
                    getattr(config.media, "ffprobe_path", "ffprobe"),
                    policy=sv_cfg,
                )
                recalled = vault.resolve(video_uuid)
                if recalled is not None:
                    staged_path = recalled.path
                    acquired = True
        except Exception:
            acquired = False
        if not acquired:
            from ..media_materializer import MediaMaterializer

            materializer = MediaMaterializer(
                str(Path(config.media.materialization_dir).expanduser())
                if hasattr(config.media, "materialization_dir")
                else "~/.diveanalyzer/materialized_assets",
                max_bytes=int(getattr(config.media, "materialization_max_bytes", 2_000_000_000)),
                osxphotos_path=getattr(config.media, "osxphotos_path", "osxphotos"),
                use_photokit=bool(getattr(config.media, "materialization_use_photokit", False)),
                library_path=config.photos.library_path,
            )

            import asyncio as _asyncio

            def materialize_from_photos(asset_uuid: str, workdir: Path) -> Path:
                exported = _asyncio.run(materializer.materialize(asset_uuid))
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
            staged_path = materialize_from_photos(photos_uuid, workdir)

    # Merge into the existing stage metadata: provenance (triggered_at,
    # request_reason, activation) and the pinned local identity (written
    # above, before evidence capture) survive; only the staged-bytes fields
    # and run mode are refreshed. A wholesale replace would silently drop
    # the original trigger provenance and the split pin the evidence above
    # was captured under.
    merged = dict(stage_meta)
    merged.update(
        {
            "staged_path": str(staged_path),
            "staged_bytes": staged_path.stat().st_size,
            "copy_seconds": stage_meta.get("copy_seconds", 0.0),
            "run_mode": "one_shot_production_runtime",
        }
    )
    pdw._set_stage_meta(video_uuid, merged)
    pdw._ensure_dirs()
    run_started = time.time()
    try:
        pdw._drive(video_uuid, staged_path, photos_local)
    except ValueError as exc:
        # Evidence/identity race refused inside the drive (evidence changed
        # between the pre-stage check above and the drive's own gate):
        # structured refusal, no partial commit.
        print(
            json.dumps(
                {
                    "mode": "dual-write-run",
                    "outcome": "refused_evidence_identity_mismatch",
                    "error": str(exc)[:300],
                }
            )
        )
        return 3
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
    if stage_meta.get("run_mode") == "one_shot_production_runtime":
        shutil.rmtree(
            pdw.temp_root / "dual_write_run" / video_uuid, ignore_errors=True
        )
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
    parser.add_argument(
        "--request-reason",
        default=None,
        help="Present the production trigger reason to the continuous "
        "activation boundary (required for non-allowlisted assets when "
        "dual_write.continuous_new_ingest is enabled).",
    )
    parser.add_argument(
        "--agent-local-uuid",
        default=None,
        help="Photos asset UUID for library reads (evidence, captions, "
        "Photos materialization) when it differs from the canonical "
        "--video-uuid dive identity. Omit when both identities are equal.",
    )
    args = parser.parse_args(argv)

    from ..config import Config

    config = Config.from_file(args.config)
    if not config.validate():
        raise SystemExit("invalid config")
    if args.mode == "caption-mutation":
        return mode_caption_mutation(
            config, args.video_uuid, args.request_reason, args.agent_local_uuid
        )
    if args.mode == "run":
        return mode_run(
            config, args.video_uuid, args.env_file, args.request_reason,
            args.agent_local_uuid,
        )
    return 2


if __name__ == "__main__":
    import sys

    sys.exit(main())
