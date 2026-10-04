"""P3 bounded Ready-album queue runner (media-backbone, DEV canary only).

Drives a bounded, explicitly allowlisted set of real clips from the
`DiveAnalyser Ready` album through the SAME verified-ingest flow as the P2
canary (ObjectStoreIngestCoordinator), ONE asset at a time:

  discover (album ∩ allowlist) -> caption (stable + shadow parity)
  -> targeted materialization (Photos edited rendition) -> content hash
  -> private B2 DEV upload (content-dedupe opt-in) -> full-GET roundtrip
  verification -> operator-tunneled verified DB commit (receipt-confirmed)
  -> local cleanup -> next asset.

Safety boundaries (packet MEDIA_BACKBONE_P3_READY_QUEUE_V1):
- ALBUM MEMBERSHIP IS NOT AUTHORIZATION: only allowlisted UUIDs are processed.
- Allowlist hard guard: 1 <= n <= 10 always; the P3 packet additionally
  requires 5 <= n to run (n < 5 is refused with a distinct reason).
- No second daemon, no automatic processing of every Ready asset.
- Sequential: one active materialization/upload at a time.
- Failure isolation: a retryable/quarantined asset never blocks the queue.
- This runner NEVER prints caption text, credentials, or presigned URLs.

Controlled-test injections (explicit CLI flags, never defaults):
- --fail-put-once UUID     first PUT raises a retryable unavailable error
- --fail-get-once UUID     first verification GET raises retryable unavailable
- --corrupt-get-once UUID  first verification GET returns corrupted bytes
                           (remote object itself is untouched; exercises the
                           fail-closed quarantine path safely)
- --low-disk-asset UUID --low-disk-min-free N
                           elevated min_free_disk_bytes for that one asset
                           (refuses/retryable BEFORE materialization)
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .canary import (
    build_b2_store,
    build_stable_provider,
    edit_fingerprint,
    find_ready_album,
    ffprobe_metadata,
    get_photos_db,
    load_canary_config,
    load_env_file,
    make_materialize_fn,
    parse_caption_metadata,
    photo_provenance,
    stage_commit_document,
    utcnow,
)
from .caption import PhotosDbCaptionProviderShadow, compare_caption_providers
from .coordinator import ObjectStoreIngestCoordinator
from .errors import ObjectStoreError, ObjectStoreUnavailable
from .objectstore.base import ObjectStore
from .state_store import IngestStateStore
from .states import IngestState

UUID_PATTERN = re.compile(
    r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
)
ALLOWLIST_HARD_MAX = 10
ALLOWLIST_HARD_MIN = 1
ALLOWLIST_PACKET_MIN = 5
P3_METRICS_VERSION = "media_backbone_p3_v1"


# ---------------------------------------------------------------------------
# Allowlist loading + guards


def load_allowlist(path: str) -> list[str]:
    """Load and validate the explicit P3 allowlist (JSON array of UUIDs).

    Refuses (SystemExit) on: malformed file, non-UUID entries, duplicates,
    or count outside the hard bound 1..10. The packet floor (>=5) is a
    separate, distinct check performed by validate_allowlist_for_run().
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("allowlist")
    if not isinstance(raw, list):
        raise SystemExit(f"allowlist file {path} must be a JSON array of UUIDs")
    uuids: list[str] = []
    for entry in raw:
        if not isinstance(entry, str) or not UUID_PATTERN.match(entry):
            raise SystemExit(f"allowlist entry is not a valid UUID: {entry!r}")
        normalized = entry.upper()
        if normalized in uuids:
            raise SystemExit(f"allowlist contains duplicate uuid: {normalized}")
        uuids.append(normalized)
    if not (ALLOWLIST_HARD_MIN <= len(uuids) <= ALLOWLIST_HARD_MAX):
        raise SystemExit(
            f"allowlist guard violation: {len(uuids)} entries; "
            f"hard bound is {ALLOWLIST_HARD_MIN}..{ALLOWLIST_HARD_MAX} "
            f"(refusing to run — album membership is never P3 authorization)"
        )
    return uuids


def validate_allowlist_for_run(uuids: list[str], min_count: int = ALLOWLIST_PACKET_MIN) -> None:
    """P3 packet floor: a queue run needs 5..10 selected clips (configurable
    only for offline unit tests of the runner mechanics)."""
    if len(uuids) < min_count:
        raise SystemExit(
            f"allowlist guard violation: {len(uuids)} entries; "
            f"this P3 packet requires >= {min_count} selected clips to run"
        )


# ---------------------------------------------------------------------------
# GUI-LaunchAgent materialization (iCloud-only assets need PhotoKit, which is
# only available inside the user's Aqua session — same runtime context class
# as the production agent; one transient launchd job per export, booted out
# after use; not a daemon).

MOVIE_EXTENSIONS = {".mov", ".mp4", ".m4v", ".avi", ".hevc"}
MIN_MATERIALIZED_BYTES = 16 * 1024


def select_materialized_video(target_dir: Path, max_bytes: int) -> Path:
    """Select the materialized rendition: prefer the EDITED rendition file
    (osxphotos '<name>_edited.<ext>') when present, else the largest movie
    file. Enforces the same size bounds as the production materializer.
    Rendition doctrine: the edited/trimmed Photos rendition is the authority
    (osxphotos export without --skip-edited semantics)."""
    candidates: list[Path] = []
    edited: list[Path] = []
    for path in target_dir.rglob("*"):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.lower() not in MOVIE_EXTENSIONS:
            continue
        size = path.stat().st_size
        if size < MIN_MATERIALIZED_BYTES or size > max_bytes:
            continue
        candidates.append(path)
        if "_edited" in path.stem:
            edited.append(path)
    pool = edited or candidates
    if not pool:
        raise p3_MaterializationError("materialization_only_placeholders")
    return max(pool, key=lambda p: (p.stat().st_size, p.name))


class p3_MaterializationError(ObjectStoreError):
    """Retryable materialization failure (coordinator records and re-drives)."""


def make_gui_agent_materialize_fn(cfg: dict):
    import plistlib
    import tempfile

    mat_cfg = cfg["materializer"]
    osxphotos_path = mat_cfg.get("osxphotos_path") or "osxphotos"
    max_bytes = int(mat_cfg.get("max_bytes", 2_000_000_000))
    timeout = int(mat_cfg.get("export_timeout_seconds", 900))
    gui_uid = int(mat_cfg.get("gui_uid", 501))

    def materialize(video_uuid: str, workdir: Path) -> Path:
        workdir.mkdir(parents=True, exist_ok=True)
        label = f"com.diveanalyzer.p3-materialize-{video_uuid[:8].lower()}"
        fd, plist_path = tempfile.mkstemp(prefix=f"{label}.", suffix=".plist")
        stdout_path = workdir / "export.out"
        stderr_path = workdir / "export.err"
        program = [
            osxphotos_path,
            "export",
            str(workdir),
            "--uuid",
            video_uuid,
            "--only-movies",
            "--download-missing",
            "--use-photokit",
            "--update",
            "--verbose",
        ]
        with os.fdopen(fd, "wb") as fh:
            plistlib.dump(
                {
                    "Label": label,
                    "ProgramArguments": program,
                    "RunAtLoad": True,
                    "StandardOutPath": str(stdout_path),
                    "StandardErrorPath": str(stderr_path),
                },
                fh,
            )
        service = f"gui/{gui_uid}/{label}"
        subprocess.run(["launchctl", "bootout", service], capture_output=True)
        boot = subprocess.run(
            ["launchctl", "bootstrap", f"gui/{gui_uid}", plist_path],
            capture_output=True,
            text=True,
        )
        if boot.returncode != 0:
            Path(plist_path).unlink(missing_ok=True)
            raise p3_MaterializationError(f"launchd bootstrap failed: {boot.stderr.strip()}")
        deadline = time.time() + timeout
        done = False
        while time.time() < deadline:
            time.sleep(3)
            out = stdout_path.read_text(encoding="utf-8", errors="replace") if stdout_path.exists() else ""
            if "Do you want to continue?" in out:
                subprocess.run(["launchctl", "bootout", service], capture_output=True)
                Path(plist_path).unlink(missing_ok=True)
                raise p3_MaterializationError(
                    "osxphotos export blocked on an interactive prompt "
                    "(stale export db in workdir); refusing interactive runs"
                )
            if "Elapsed time:" in out or "error:" in out.lower():
                done = True
                break
        try:
            subprocess.run(["launchctl", "bootout", service], capture_output=True)
        finally:
            Path(plist_path).unlink(missing_ok=True)
        if not done:
            raise p3_MaterializationError(f"export timeout after {timeout}s")
        if "error: 0" not in out and "error:" in out.lower():
            raise p3_MaterializationError(f"osxphotos export error: {out[-300:]}")
        return select_materialized_video(workdir, max_bytes)

    return materialize


# ---------------------------------------------------------------------------
# Metrics helpers


def free_disk_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def temp_cache_bytes(temp_root: Path) -> int:
    total = 0
    if not temp_root.exists():
        return 0
    for p in temp_root.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def history_deltas(journal: dict[str, Any], start_len: int) -> dict[str, float]:
    """Latency (seconds) between consecutive state transitions appended to the
    journal history during one queue pass (entries [start_len:])."""
    entries = (journal.get("history") or [])[start_len:]
    stamps: list[tuple[str, float]] = []
    for entry in entries:
        at = entry.get("at")
        if not at:
            continue
        stamps.append((entry["state"], _parse_ts(at)))
    deltas: dict[str, float] = {}
    for (state_a, t_a), (state_b, t_b) in zip(stamps, stamps[1:]):
        deltas[f"{state_a}->{state_b}"] = round(max(t_b - t_a, 0.0), 3)
    return deltas


def _parse_ts(stamp: str) -> float:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()


class CountingObjectStore:
    """Wrapper ObjectStore that counts per-asset operation/byte totals.

    Delegation is complete; the wrapped store semantics (including injected
    failures) are unchanged.
    """

    def __init__(self, inner: ObjectStore):
        self._inner = inner
        self.put_count = 0
        self.put_bytes = 0
        self.head_count = 0
        self.get_count = 0
        self.get_bytes = 0

    def put(self, key: str, source: bytes | Path, content_type: str | None = None):
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


class InjectingObjectStore(CountingObjectStore):
    """Per-asset fault injection wrapper for controlled P3 tests.

    The remote object store itself is never harmed: injections only raise
    retryable errors or alter the bytes RETURNED to the verifier (fail-closed
    quarantine path), never the stored object.
    """

    def __init__(self, inner: ObjectStore, injections: dict[str, int]):
        super().__init__(inner)
        self._injections = dict(injections)  # kind -> remaining count

    def _consume(self, kind: str) -> bool:
        remaining = self._injections.get(kind, 0)
        if remaining > 0:
            self._injections[kind] = remaining - 1
            return True
        return False

    def put(self, key: str, source: bytes | Path, content_type: str | None = None):
        if self._consume("put"):
            raise ObjectStoreUnavailable("injected first-put failure (P3 controlled test)")
        return super().put(key, source, content_type=content_type)

    def get(self, key: str) -> bytes:
        if self._consume("get"):
            raise ObjectStoreUnavailable(
                "injected first-get-verification failure (P3 controlled test)"
            )
        data = super().get(key)
        if self._consume("corrupt") :
            data = b"CORRUPTED-P3-INJECTION" + data[: -len(b"CORRUPTED-P3-INJECTION")]
        return data


# ---------------------------------------------------------------------------
# Evidence capture (read-only; same shape as the P2 canary evidence file)


def capture_evidence(
    cfg: dict,
    state_dir: Path,
    video_uuid: str,
    stable,
    shadow: PhotosDbCaptionProviderShadow,
    db,
) -> dict:
    matches = db.photos(uuid=[video_uuid])
    if not matches:
        raise SystemExit(f"asset not found in Photos library: {video_uuid}")
    photo = matches[0]
    stable_result = stable.get_caption(video_uuid)
    shadow_result = shadow.get_caption(video_uuid)
    parity = compare_caption_providers([(video_uuid, stable_result, shadow_result)])
    evidence = {
        "captured_at": utcnow(),
        "ready_album_title": find_ready_album(db)[0],
        "photo": photo_provenance(photo),
        "edit_fingerprint": edit_fingerprint(photo),
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
    write_evidence(state_dir, video_uuid, evidence)
    return evidence


def write_evidence(state_dir: Path, video_uuid: str, evidence: dict) -> None:
    evidence_path = state_dir / f"{video_uuid}.evidence.json"
    fd = os.open(evidence_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(evidence, fh, ensure_ascii=False, indent=2, sort_keys=True)


def read_evidence(state_dir: Path, video_uuid: str) -> dict | None:
    path = state_dir / f"{video_uuid}.evidence.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Commit transport (operator-tunneled, receipt-confirmed — same as P2)


def make_transport_commit_fn(cmd: str, cfg: dict, state_dir: Path, video_uuid: str):
    """Run the staged commit document through an operator-provided transport
    command (stdin: document JSON, stdout: receipt JSON), persist the receipt
    at the P2 convention path, and validate it exactly like the P2 runner.
    The document includes the full P2-style 'extra' block (media metadata,
    edit fingerprint, shadow parity) built by stage_commit_document."""

    def commit_db_fn(payload: dict[str, Any]) -> dict[str, Any]:
        staged = stage_commit_document(cfg, video_uuid)
        if staged.get("payload") != payload:
            raise ObjectStoreUnavailable(
                "staged commit payload drifted from the coordinator payload; "
                "refusing to send"
            )
        document = json.dumps({"payload": payload, "extra": staged.get("extra")}, ensure_ascii=False)
        proc = subprocess.run(
            cmd,
            shell=True,
            input=document,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if proc.returncode != 0:
            raise ObjectStoreUnavailable(
                f"commit transport failed rc={proc.returncode}: {proc.stderr[-300:]}"
            )
        try:
            receipt = json.loads(proc.stdout)
        except ValueError:
            raise ObjectStoreUnavailable("commit transport returned a non-JSON receipt")
        if receipt.get("input", {}).get("payload") != payload:
            raise ObjectStoreUnavailable(
                "commit receipt does not match the staged coordinator payload; "
                "refusing to mark DB_COMMITTED"
            )
        if not receipt.get("result", {}).get("blob_sha256"):
            raise ObjectStoreUnavailable("commit receipt missing server result rows")
        receipt_path = state_dir / f"{video_uuid}.commit_receipt.json"
        fd = os.open(receipt_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(receipt, fh, ensure_ascii=False, indent=2, sort_keys=True)
        return receipt["result"]

    return commit_db_fn


# ---------------------------------------------------------------------------
# Queue execution


def build_queue_context(cfg: dict, env_file: str | None):
    os_cfg = cfg["object_store"]
    state_dir = Path(os_cfg["state_dir"]).expanduser()
    temp_root = Path(os_cfg["temp_root"]).expanduser()
    state_dir.mkdir(parents=True, exist_ok=True)
    temp_root.mkdir(parents=True, exist_ok=True)
    library_path = cfg["photos"]["library_path"]
    stable = build_stable_provider(library_path)
    shadow = PhotosDbCaptionProviderShadow(library_path)
    env = load_env_file(env_file) if env_file else None
    store, b2_config = build_b2_store(cfg, env)
    if cfg.get("materializer", {}).get("use_gui_launchagent"):
        raw_materialize_fn = make_gui_agent_materialize_fn(cfg)
    else:
        raw_materialize_fn = make_materialize_fn(cfg)
    ffprobe_bin = cfg.get("ffprobe_path") or "ffprobe"
    return {
        "cfg": cfg,
        "os_cfg": os_cfg,
        "state_dir": state_dir,
        "temp_root": temp_root,
        "library_path": library_path,
        "stable": stable,
        "shadow": shadow,
        "store": store,
        "b2_config": b2_config,
        "materialize_fn": raw_materialize_fn,
        "ffprobe_bin": ffprobe_bin,
    }


def process_asset(
    ctx: dict, video_uuid: str, options: dict[str, Any], photos_db=None
) -> dict[str, Any]:
    """Drive ONE allowlisted asset to a terminal state (or a recorded stop).

    Returns a per-asset metrics record; never raises for retryable/quarantined
    outcomes (failure isolation). Controlled crashes (InjectedCrash) propagate
    to the caller intentionally for the restart test.
    """
    cfg = ctx["cfg"]
    os_cfg = ctx["os_cfg"]
    state_dir: Path = ctx["state_dir"]
    temp_root: Path = ctx["temp_root"]
    library_path = ctx["library_path"]
    stable = ctx["stable"]
    shadow = ctx["shadow"]

    record: dict[str, Any] = {"video_uuid": video_uuid, "passes": []}
    record["free_disk_before"] = free_disk_bytes(temp_root)
    db = photos_db if photos_db is not None else get_photos_db(library_path)

    state_store = IngestStateStore(state_dir / f"{video_uuid}.json")
    state_store.load(video_uuid)
    already_committed = state_store.state in (
        IngestState.CACHE_CLEANED,
        IngestState.DB_COMMITTED,
    )
    record["already_committed_before_queue"] = already_committed

    if not already_committed:
        evidence = read_evidence(state_dir, video_uuid)
        if evidence is None:
            evidence = capture_evidence(cfg, state_dir, video_uuid, stable, shadow, db)
        record["edit_fingerprint"] = evidence.get("edit_fingerprint")
        record["caption_sha256"] = (evidence.get("caption") or {}).get("caption_sha256")

    materialize_fn = ctx["materialize_fn"]

    def wrapped_materialize(asset_uuid: str, workdir: Path) -> Path:
        free_before_mat = free_disk_bytes(temp_root)
        record["free_disk_before_materialization"] = free_before_mat
        started_at = utcnow()
        path = materialize_fn(asset_uuid, workdir)
        finished_at = utcnow()
        media_meta = ffprobe_metadata(path, ctx["ffprobe_bin"])

        def _finish(ev: dict) -> None:
            photos_duration = ((ev.get("photo") or {}).get("duration_seconds")) or 0.0
            duration_match = (
                abs((media_meta.get("duration_seconds") or 0.0) - photos_duration) <= 0.2
                if photos_duration
                else None
            )
            ev.update(
                {
                    "materialization": {
                        "started_at": started_at,
                        "finished_at": finished_at,
                        "byte_size": path.stat().st_size,
                    },
                    "media_metadata": media_meta,
                    "rendition_duration_match": duration_match,
                }
            )

        _update_evidence(state_dir, asset_uuid, _finish)
        record["free_disk_after_materialization"] = free_disk_bytes(temp_root)
        return path

    max_passes = int(options.get("max_passes_per_asset", 5))
    backoff = float(options.get("retry_backoff_seconds", 5.0))
    min_free_default = int(os_cfg.get("min_free_disk_bytes", 0))
    low_disk_asset = options.get("low_disk_asset")
    low_disk_min_free = int(options.get("low_disk_min_free") or 0)
    min_free_for_asset = (
        low_disk_min_free if (video_uuid == low_disk_asset and low_disk_min_free) else min_free_default
    )

    commit_receipt_path = state_dir / f"{video_uuid}.commit_receipt.json"
    transport_cmd = options.get("commit_transport_cmd")
    if options.get("commit_receipt_path"):
        # pre-existing receipt (operator-tunneled restart convergence)
        commit_receipt_path = Path(options["commit_receipt_path"])

    if transport_cmd:
        commit_db_fn = make_transport_commit_fn(transport_cmd, cfg, state_dir, video_uuid)
    else:
        def commit_db_fn(payload: dict[str, Any]) -> dict[str, Any]:
            if commit_receipt_path.exists():
                receipt = json.loads(commit_receipt_path.read_text(encoding="utf-8"))
                if receipt.get("input", {}).get("payload") != payload:
                    raise ObjectStoreUnavailable(
                        "commit receipt does not match the staged coordinator payload; "
                        "refusing to mark DB_COMMITTED"
                    )
                if not receipt.get("result", {}).get("blob_sha256"):
                    raise ObjectStoreUnavailable("commit receipt missing server result rows")
                return receipt["result"]
            raise ObjectStoreUnavailable(
                "db_commit_transport_unavailable: P3 commits are tunneled by the "
                "operator through the server commit service"
            )

    injections: dict[str, int] = {}
    if options.get("fail_put_once") == video_uuid:
        injections["put"] = 1
    if options.get("fail_get_once") == video_uuid:
        injections["get"] = 1
    if options.get("corrupt_get_once") == video_uuid:
        injections["corrupt"] = 1
    counting = InjectingObjectStore(ctx["store"], injections)
    record["injections_active"] = sorted(k for k, v in injections.items() if v > 0)

    coordinator = ObjectStoreIngestCoordinator(
        video_uuid=video_uuid,
        state_store=state_store,
        object_store=counting,
        materialize_fn=wrapped_materialize,
        commit_db_fn=commit_db_fn,
        temp_root=temp_root,
        caption_provider=stable,
        min_free_disk_bytes=min_free_for_asset,
        storage_backend=os_cfg.get("storage_backend", "b2"),
        bucket=ctx["b2_config"].bucket,
        skip_put_if_remote_present=bool(options.get("skip_put_if_remote_present", True)),
    )

    final_state = None
    crash = None
    for _pass in range(max_passes):
        history_len = len(state_store.doc.get("history") or [])
        pass_started = time.time()
        try:
            final_state = coordinator.run_once()
        except Exception as exc:  # InjectedCrash and unexpected crashes alike
            crash = repr(exc)
            record["passes"].append(_pass_record(state_store, counting, history_len, pass_started, crash=crash))
            break
        record["passes"].append(_pass_record(state_store, counting, history_len, pass_started))
        if final_state is IngestState.CACHE_CLEANED:
            break
        if final_state is IngestState.QUARANTINED:
            break
        if final_state is IngestState.REMOTE_VERIFIED and not commit_receipt_path.exists():
            # Operator commit tunnel required before convergence continues:
            # persist the staged document (P2 convention) and stop this asset;
            # the queue continues with the next allowlisted asset.
            staged = stage_commit_document(cfg, video_uuid)
            staged_path = state_dir / f"{video_uuid}.commit_input.json"
            fd = os.open(staged_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(staged, fh, ensure_ascii=False, indent=2, sort_keys=True)
            record["staged_commit"] = True
            break
        # retryable: back off then re-drive the same asset
        time.sleep(backoff)

    record["final_state"] = str(final_state) if final_state else state_store.state.value
    record["quarantined"] = final_state is IngestState.QUARANTINED or state_store.state is IngestState.QUARANTINED
    record["last_error"] = state_store.doc.get("last_error")
    record["media_sha256"] = (state_store.doc.get("media") or {}).get("sha256")
    record["media_byte_size"] = (state_store.doc.get("media") or {}).get("byte_size")
    record["object_key"] = (state_store.doc.get("media") or {}).get("object_key")
    record["put_skipped_existing"] = (state_store.doc.get("remote") or {}).get(
        "last_put_skipped_existing"
    )
    record["ops"] = {
        "put_count": counting.put_count,
        "put_bytes": counting.put_bytes,
        "head_count": counting.head_count,
        "get_count": counting.get_count,
        "get_bytes": counting.get_bytes,
    }
    record["free_disk_after"] = free_disk_bytes(temp_root)
    record["temp_cache_bytes_after"] = temp_cache_bytes(temp_root)
    return record


def _pass_record(state_store, counting, history_len: int, started: float, crash: str | None = None) -> dict:
    return {
        "state_at_end": state_store.state.value,
        "history_deltas": history_deltas(state_store.doc, history_len),
        "ops": {
            "put_count": counting.put_count,
            "put_bytes": counting.put_bytes,
            "head_count": counting.head_count,
            "get_count": counting.get_count,
            "get_bytes": counting.get_bytes,
        },
        "elapsed_seconds": round(time.time() - started, 3),
        **({"crash": crash} if crash else {}),
    }


def _update_evidence(state_dir: Path, video_uuid: str, updater) -> None:
    evidence = read_evidence(state_dir, video_uuid) or {}
    updater(evidence)
    write_evidence(state_dir, video_uuid, evidence)


def run_queue(cfg: dict, options: dict[str, Any]) -> int:
    ctx = build_queue_context(cfg, options.get("env_file"))
    library_path = ctx["library_path"]
    db = get_photos_db(library_path)
    title, album = find_ready_album(db)
    if album is None:
        print(json.dumps({"mode": "queue", "outcome": "refused", "reason": "ready_album_not_found"}))
        return 3
    album_uuids = {p.uuid for p in album.photos if p.ismovie}
    allowlist = options["allowlist"]
    validate_allowlist_for_run(
        allowlist, min_count=int(options.get("run_min_allowlist", ALLOWLIST_PACKET_MIN))
    )
    outside = [u for u in allowlist if u not in album_uuids]
    if outside:
        print(
            json.dumps(
                {
                    "mode": "queue",
                    "outcome": "refused",
                    "reason": "allowlist_entries_outside_ready_album",
                    "count": len(outside),
                }
            )
        )
        return 3

    metrics: dict[str, Any] = {
        "version": P3_METRICS_VERSION,
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f"),
        "started_at": utcnow(),
        "ready_album_title": title,
        "ready_album_size": len(album_uuids),
        "allowlist_count": len(allowlist),
        "assets": [],
        "peak_temp_cache_bytes": 0,
        "min_free_disk_bytes_observed": None,
    }
    peak_cache = 0
    min_free: int | None = None

    for video_uuid in allowlist:
        record = process_asset(ctx, video_uuid, options, photos_db=db)
        metrics["assets"].append(record)
        peak_cache = max(peak_cache, record.get("temp_cache_bytes_after") or 0)
        for key in (
            "free_disk_before",
            "free_disk_before_materialization",
            "free_disk_after_materialization",
            "free_disk_after",
        ):
            value = record.get(key)
            if isinstance(value, int):
                min_free = value if min_free is None else min(min_free, value)
        metrics["peak_temp_cache_bytes"] = peak_cache
        metrics["min_free_disk_bytes_observed"] = min_free
        _write_metrics(ctx["state_dir"], metrics)
        print(
            json.dumps(
                {
                    "mode": "queue",
                    "asset": video_uuid,
                    "final_state": record["final_state"],
                    "quarantined": record["quarantined"],
                    "media_sha256": record.get("media_sha256"),
                    "put_skipped_existing": record.get("put_skipped_existing"),
                },
                ensure_ascii=False,
            )
        )

    metrics["finished_at"] = utcnow()
    _write_metrics(ctx["state_dir"], metrics)
    print(json.dumps(summarize_metrics(metrics), ensure_ascii=False))
    return 0


def _write_metrics(state_dir: Path, metrics: dict) -> None:
    """Run-unique snapshot (packet §36): metrics/<run_id>.json, never
    overwriting prior-run evidence. The same run's file is atomically
    rewritten while that run is in progress; distinct runs get distinct
    files (suffix -2, -3, ... on same-second collisions)."""
    metrics_dir = state_dir / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    run_id = metrics.get("run_id") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    candidate = f"p3_{run_id}"
    suffix = 1
    while (metrics_dir / f"{candidate}.json").exists() and metrics.get("run_id") is None:
        suffix += 1
        candidate = f"p3_{run_id}-{suffix}"
    path = metrics_dir / f"{candidate}.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(metrics, fh, ensure_ascii=False, indent=2, sort_keys=True)


# ---------------------------------------------------------------------------
# Aggregation (machine-readable manifest; no raw captions)


def summarize_metrics(metrics: dict) -> dict:
    assets = metrics.get("assets") or []
    ingested = sum(
        1 for a in assets if a.get("final_state") == "IngestState.CACHE_CLEANED"
    )
    quarantined = sum(1 for a in assets if a.get("quarantined"))
    retried = sum(1 for a in assets if len(a.get("passes") or []) > 1)
    deduped = sum(1 for a in assets if a.get("put_skipped_existing"))
    put_bytes = sum((a.get("ops") or {}).get("put_bytes") or 0 for a in assets)
    unique_blobs = len({a.get("media_sha256") for a in assets if a.get("media_sha256")})
    return {
        "sample_size": len(assets),
        "ingested": ingested,
        "quarantined": quarantined,
        "retried": retried,
        "deduplicated": deduped,
        "unique_media_blobs": unique_blobs,
        "bytes_uploaded": put_bytes,
        "bytes_roundtrip_verified": sum(
            (a.get("ops") or {}).get("get_bytes") or 0 for a in assets
        ),
    }


def aggregate_manifest(state_dir: Path) -> dict:
    """Shadow parity + per-asset aggregates across the P3 sample."""
    sample_count = 0
    stable_success = 0
    shadow_available = 0
    exact_equal = 0
    shadow_failures = 0
    mismatches = 0
    assets: list[dict] = []
    for evidence_path in sorted(state_dir.glob("*.evidence.json")):
        video_uuid = evidence_path.name.replace(".evidence.json", "")
        ev = json.loads(evidence_path.read_text(encoding="utf-8"))
        caption = ev.get("caption") or {}
        shadow_res = ev.get("shadow") or {}
        parity = ev.get("parity") or {}
        sample_count += 1
        if caption.get("available"):
            stable_success += 1
        if shadow_res.get("available"):
            shadow_available += 1
            if parity.get("samples"):
                sample = parity["samples"][0]
                if sample.get("exact_equal"):
                    exact_equal += 1
                else:
                    mismatches += 1
        else:
            shadow_failures += 1
        journal_path = state_dir / f"{video_uuid}.json"
        journal = json.loads(journal_path.read_text(encoding="utf-8")) if journal_path.exists() else {}
        assets.append(
            {
                "video_uuid": video_uuid,
                "state": journal.get("state"),
                "media_sha256": (journal.get("media") or {}).get("sha256"),
                "media_byte_size": (journal.get("media") or {}).get("byte_size"),
                "caption_sha256": caption.get("caption_sha256"),
                "caption_length": caption.get("caption_length"),
                "caption_utf8_bytes": caption.get("caption_utf8_bytes"),
                "caption_non_ascii": bool(caption.get("caption_utf8_bytes") and caption.get("caption_length") and caption.get("caption_utf8_bytes") != caption.get("caption_length")),
                "hasadjustments": (ev.get("photo") or {}).get("hasadjustments"),
                "incloud": (ev.get("photo") or {}).get("incloud"),
                "ismissing": (ev.get("photo") or {}).get("ismissing"),
                "edit_fingerprint": ev.get("edit_fingerprint"),
                "shadow_available": shadow_res.get("available"),
                "exact_equal": (
                    (parity.get("samples") or [{}])[0].get("exact_equal")
                    if parity.get("samples")
                    else None
                ),
                "media_metadata": ev.get("media_metadata"),
            }
        )
    return {
        "version": P3_METRICS_VERSION,
        "aggregate": {
            "sample_count": sample_count,
            "stable_success": stable_success,
            "shadow_available": shadow_available,
            "exact_equal_count": exact_equal,
            "exact_equal_rate": round(exact_equal / stable_success, 4) if stable_success else None,
            "shadow_failures": shadow_failures,
            "mismatches": mismatches,
        },
        "assets": assets,
    }


# ---------------------------------------------------------------------------
# Media edit/trim mutation (§17/§18) — operator-triggered complement


def mode_media_mutation(cfg: dict, video_uuid: str) -> int:
    os_cfg = cfg["object_store"]
    state_dir = Path(os_cfg["state_dir"]).expanduser()
    library_path = cfg["photos"]["library_path"]
    journal_path = state_dir / f"{video_uuid}.json"
    if not journal_path.exists():
        raise SystemExit(f"no journal for {video_uuid}; nothing was ingested yet")
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    if journal.get("state") != "CACHE_CLEANED":
        raise SystemExit(f"journal not terminal ({journal.get('state')}); refuse media mutation")
    before_evidence = read_evidence(state_dir, video_uuid) or {}
    before_fingerprint = before_evidence.get("edit_fingerprint")
    before = {
        "edit_fingerprint": before_fingerprint,
        "media_sha256": (journal.get("media") or {}).get("sha256"),
        "media_byte_size": (journal.get("media") or {}).get("byte_size"),
        "media_metadata": before_evidence.get("media_metadata"),
        "caption_sha256": (journal.get("caption") or {}).get("sha256"),
    }
    db = get_photos_db(library_path)
    matches = db.photos(uuid=[video_uuid])
    if not matches:
        raise SystemExit(f"asset not found: {video_uuid}")
    new_fingerprint = edit_fingerprint(matches[0])
    if new_fingerprint == before_fingerprint:
        print(
            json.dumps(
                {
                    "mode": "media-mutation",
                    "outcome": "refused_unchanged_media",
                    "edit_fingerprint": new_fingerprint,
                }
            )
        )
        return 1
    # Preserve before-state, reset the journal for a fresh verified re-ingest.
    # The server DB retains all prior content-addressed rows (append-only);
    # the journal is operational state only.
    shutil.copy2(
        state_dir / f"{video_uuid}.evidence.json",
        state_dir / f"{video_uuid}.evidence.before_media_mutation.json",
    )
    shutil.copy2(journal_path, state_dir / f"{video_uuid}.journal.before_media_mutation.json")
    stable = build_stable_provider(library_path)
    shadow = PhotosDbCaptionProviderShadow(library_path)
    os.unlink(journal_path)
    # stale operational commit artifacts must not survive a journal reset:
    # an old receipt/commit_input would no longer match the fresh payload
    for suffix in ("commit_receipt.json", "commit_input.json"):
        stale = state_dir / f"{video_uuid}.{suffix}"
        if stale.exists():
            stale.unlink()
    evidence = capture_evidence(cfg, state_dir, video_uuid, stable, shadow, db)
    evidence["mutation"] = {
        "kind": "media_edit_trim",
        "captured_at": utcnow(),
        "previous": before,
        "new_edit_fingerprint": evidence.get("edit_fingerprint"),
    }
    write_evidence(state_dir, video_uuid, evidence)
    print(
        json.dumps(
            {
                "mode": "media-mutation",
                "outcome": "journal_reset_for_fresh_reingest",
                "previous_fingerprint": before_fingerprint,
                "new_fingerprint": evidence.get("edit_fingerprint"),
                "previous_media_sha256": before["media_sha256"],
                "previous_byte_size": before["media_byte_size"],
            },
            ensure_ascii=False,
        )
    )
    return 0


# ---------------------------------------------------------------------------
# CLI


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="P3 bounded Ready-album queue runner")
    parser.add_argument("--config", required=True)
    parser.add_argument("--env-file")
    parser.add_argument("--allowlist")
    parser.add_argument("--commit-transport-cmd")
    parser.add_argument("--max-passes-per-asset", type=int, default=5)
    parser.add_argument("--retry-backoff-seconds", type=float, default=5.0)
    parser.add_argument("--no-skip-put", action="store_true", help="disable content-dedupe skip")
    parser.add_argument("--fail-put-once")
    parser.add_argument("--fail-get-once")
    parser.add_argument("--corrupt-get-once")
    parser.add_argument("--low-disk-asset")
    parser.add_argument("--low-disk-min-free", type=int)
    parser.add_argument("mode", choices=["check", "queue", "media-mutation", "aggregate"])
    parser.add_argument("--video-uuid")
    args = parser.parse_args(argv)

    cfg = load_canary_config(args.config)
    options = {
        "env_file": args.env_file,
        "commit_transport_cmd": args.commit_transport_cmd,
        "max_passes_per_asset": args.max_passes_per_asset,
        "retry_backoff_seconds": args.retry_backoff_seconds,
        "skip_put_if_remote_present": not args.no_skip_put,
        "fail_put_once": args.fail_put_once,
        "fail_get_once": args.fail_get_once,
        "corrupt_get_once": args.corrupt_get_once,
        "low_disk_asset": args.low_disk_asset,
        "low_disk_min_free": args.low_disk_min_free,
    }

    if args.mode == "check":
        allowlist = load_allowlist(args.allowlist)
        db = get_photos_db(cfg["photos"]["library_path"])
        title, album = find_ready_album(db)
        album_uuids = {p.uuid for p in album.photos if p.ismovie} if album else set()
        result = {
            "mode": "check",
            "ready_album_found": album is not None,
            "ready_album_title": title,
            "ready_album_size": len(album_uuids),
            "allowlist_count": len(allowlist),
            "outside_album": [u for u in allowlist if u not in album_uuids],
            "packet_floor_ok": len(allowlist) >= ALLOWLIST_PACKET_MIN,
        }
        print(json.dumps(result, ensure_ascii=False))
        return 0 if album and not result["outside_album"] else 3

    if args.mode == "queue":
        allowlist = load_allowlist(args.allowlist)
        options["allowlist"] = allowlist
        return run_queue(cfg, options)

    if args.mode == "media-mutation":
        if not args.video_uuid:
            raise SystemExit("media-mutation requires --video-uuid")
        return mode_media_mutation(cfg, args.video_uuid)

    if args.mode == "aggregate":
        state_dir = Path(cfg["object_store"]["state_dir"]).expanduser()
        print(json.dumps(aggregate_manifest(state_dir), ensure_ascii=False))
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
