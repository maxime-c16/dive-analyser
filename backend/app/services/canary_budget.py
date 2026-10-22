"""Bounded canary admission + publication budget preflight (D3b2 next slice).

Local-only, reviewable, no network/prod/B2. This module is the single
place that names the night-canary bounds so the ops tool, the slot
publish guard, and the tests share one contract:

- FIRST wave <= 5 clips; only on 100% proof may <= 25 more follow
  (fleet total <= 30).
- New B2 bytes HARD cumulative <= 2 GiB, counting EVERY attempted
  unique upload including safe orphans (durable reservation ledger,
  content-addressed by SHA-256, monotonic, never deleted). Estimates are
  preflight ONLY and never promise the bound -- the bound is enforced
  server-side at publish time by ``check_publish_budget`` (fast
  fail-closed pre-check) AND ``reserve_canary_upload`` (authoritative
  atomic reservation BEFORE B2 bytes stream). Retry of the SAME bytes
  dedupes on the unique SHA (no double charge); same SHA with a
  different size fails closed (corrupt claim).
- ONE package job active fleet-wide (lease already enforces this; the
  tool additionally admits serially: at most one new queue per run,
  and never while an active package exists; concurrent admits serialize
  on a PG advisory lock + a local state-dir file lock, held only for
  the short DB decision -- never across network).
- Canary jobs never outrank interactive work: priority >= 60
  (numerically; lower = claimed first, interactive = 5/6/10).
- Stop admission on: Mac Data free < 8 GiB, server cache volume free
  < 25 GiB, Mac memory pressure != normal, host facts older than
  15 minutes (operator-provided facts file -- this module never SSHes
  anywhere), repeated errors, or unknown source (dims/size/duration).

Scope: CANARY ONLY. The 2 GiB reservation bound applies only to
web_package canary slot publishes and the canary ops tool. It is not
a permanent global cap on all future packages.

Non-goals / residuals (fail closed, documented -- not hidden):

- A claimed SHA that fails validation (size/SHA mismatch, ffprobe
  refusal) keeps its reservation row: conservative over-count, never
  under-count. The budget therefore fails closed on corrupt claims.
- The server stores coded dims only (no SAR/display-dims provenance,
  see PR143). Anamorphic SAR!=1 honest output fails the alias/exact
  check closed at publish (safe orphan, reservation retained) but still
  spent uplink + orphan bytes. The tool mitigates by requiring dims-known
  sources and preferring phone-camera (SAR==1) clips.
- Frame counts are encoder-proven, never server-proven. The server
  proves container/codec/tags/faststart/decode-ability + exact dims;
  cadence proof is a post-publish verification step (runbook), not an
  admission claim.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

CANARY_PHASE1_MAX_CLIPS = 5
CANARY_PHASE2_ADDITIONAL_MAX_CLIPS = 25
CANARY_TOTAL_MAX_CLIPS = 30

CANARY_BUDGET_BYTES = 2 * 1024 * 1024 * 1024

#: Canary package jobs queue at backfill priority: interactive
#: (5/6) and ingestion (10) always win the lease ordering.
CANARY_JOB_PRIORITY = 60
CANARY_JOB_MAX_ATTEMPTS = 2

MIN_MAC_DATA_FREE_BYTES = 8 * 1024 * 1024 * 1024
MIN_SERVER_CACHE_FREE_BYTES = 25 * 1024 * 1024 * 1024

#: Host facts freshness: operator-provided facts older than this refuse
#: --apply (stale facts fail closed; the tool never probes hosts itself).
HOST_FACTS_MAX_AGE_SECONDS = 15 * 60

#: Bounded inventory: the tool never lists more than this many
#: candidates per run (manifest itself is capped at TOTAL_MAX).
MAX_CANDIDATES_PER_RUN = CANARY_TOTAL_MAX_CLIPS

#: HQ encoder ceiling (mac-agent package_encoder HQ_MAXRATE): 12 Mbit/s.
HQ_MAXRATE_BPS = 12_000_000
#: Light estimate factor at constant CRF23 (pixel ratio (720/1080)^2
#: rounded up) + container/faststart overhead on every slot.
_LIGHT_BYTE_FACTOR = 0.5
_POSTER_MAX_BYTES = 2 * 1024 * 1024
_SLOT_OVERHEAD_FACTOR = 1.10

#: Strict per-slot artifact caps (claimed size refused above these
#: BEFORE any byte streams; canary-only, fail closed). HQ ceiling is
#: generous (12 Mbit/s * 600 s + overhead) so small canary clips pass
#: with wide margin; abuse/oversize claims fail fast.
CANARY_SLOT_MAX_BYTES = {
    "hq": 1_200_000_000,
    "light": 700_000_000,
    "poster": 8 * 1024 * 1024,
}

#: PG advisory lock keys (xact-scoped, held only for the short
#: reservation/admit decision -- never across network).
_CANARY_BUDGET_LOCK = (73125, 7)
_CANARY_ADMIT_LOCK = (73125, 8)


class CanaryBudgetExceeded(ValueError):
    """Raised when a publish/admission would exceed the hard 2 GiB cap."""


def validate_manifest_uuids(clips: list[str]) -> list[str]:
    """Strict allowlist UUID shape (mirrors derivative key rules, no DB)."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in clips:
        if not isinstance(raw, str):
            raise ValueError("manifest clip must be a string video_uuid")
        if raw != raw.strip() or not raw.strip():
            raise ValueError(f"manifest clip has surrounding whitespace/empty: {raw!r}")
        if "|" in raw:
            raise ValueError(f"manifest clip must not contain '|': {raw!r}")
        if len(raw) > 100:
            raise ValueError(f"manifest clip too long (>100): {raw!r}")
        if raw in seen:
            raise ValueError(f"manifest clip duplicated: {raw!r}")
        seen.add(raw)
        cleaned.append(raw)
    if len(cleaned) > CANARY_TOTAL_MAX_CLIPS:
        raise ValueError(
            f"manifest lists {len(cleaned)} clips; canary total max is {CANARY_TOTAL_MAX_CLIPS}"
        )
    return cleaned


def check_phase_count(phase: int, manifest_count: int, already_admitted: int) -> None:
    """Enforce FIRST<=5, then <=25 additional (total<=30). Fail closed.

    Kept for backward compatibility (cumulative-count form). New code
    should use :func:`check_phase_count_new_only` so resume-after-crash
    (manifest re-listing already-admitted clips) does not false-refuse.
    """
    if phase == 1:
        if manifest_count > CANARY_PHASE1_MAX_CLIPS:
            raise ValueError(
                f"phase 1 admits at most {CANARY_PHASE1_MAX_CLIPS} clips "
                f"(manifest has {manifest_count})"
            )
        if already_admitted + manifest_count > CANARY_PHASE1_MAX_CLIPS:
            raise ValueError(
                f"phase 1 cumulative would be {already_admitted + manifest_count}; "
                f"max is {CANARY_PHASE1_MAX_CLIPS} -- admit fewer or prove phase 1 first"
            )
    elif phase == 2:
        if manifest_count > CANARY_PHASE2_ADDITIONAL_MAX_CLIPS:
            raise ValueError(
                f"phase 2 admits at most {CANARY_PHASE2_ADDITIONAL_MAX_CLIPS} additional clips"
            )
        if already_admitted + manifest_count > CANARY_TOTAL_MAX_CLIPS:
            raise ValueError(
                f"cumulative would be {already_admitted + manifest_count}; "
                f"hard max is {CANARY_TOTAL_MAX_CLIPS}"
            )
    else:
        raise ValueError(f"unknown canary phase {phase!r} (expected 1 or 2)")


def new_unique_ids(clips: list[str], known: set[str]) -> list[str]:
    """Manifest IDs not yet admitted (order-preserving, resume-safe)."""
    return [u for u in clips if u not in known]


def check_phase_count_new_only(phase: int, new_count: int, total_admitted: int) -> None:
    """Phase caps counted on NEW unique IDs only (resume-safe).

    ``total_admitted`` is the distinct admitted count (DB ∪ state);
    ``new_count`` is the manifest IDs not in that set. Re-listing an
    already-admitted clip costs zero.
    """
    if phase == 1:
        if total_admitted + new_count > CANARY_PHASE1_MAX_CLIPS:
            raise ValueError(
                f"phase 1 cumulative would be {total_admitted + new_count}; "
                f"max is {CANARY_PHASE1_MAX_CLIPS} (new={new_count})"
            )
    elif phase == 2:
        if new_count > CANARY_PHASE2_ADDITIONAL_MAX_CLIPS:
            raise ValueError(
                f"phase 2 admits at most {CANARY_PHASE2_ADDITIONAL_MAX_CLIPS} additional clips"
            )
        if total_admitted + new_count > CANARY_TOTAL_MAX_CLIPS:
            raise ValueError(
                f"cumulative would be {total_admitted + new_count}; "
                f"hard max is {CANARY_TOTAL_MAX_CLIPS}"
            )
    else:
        raise ValueError(f"unknown canary phase {phase!r} (expected 1 or 2)")


def worst_case_package_bytes(source_bytes: int | None, duration_s: float | None) -> int:
    """Upper-bound estimate for ONE package (hq+light+poster), preflight ONLY.

    Uses the HQ encoder ceiling (12 Mbit/s * duration) when duration is
    known, floored by 2x the source bytes (transcodes of tiny clips can
    exceed the source). Unknown duration/size -> raises (fail closed:
    "source unknown" stops admission -- the estimate must never be
    guessed from nothing).
    """
    if source_bytes is None or source_bytes <= 0:
        raise ValueError("worst-case estimate requires known source byte_size")
    if duration_s is None or duration_s <= 0:
        raise ValueError("worst-case estimate requires known source duration")
    hq = int(HQ_MAXRATE_BPS * float(duration_s) / 8)
    hq = max(hq, int(source_bytes) * 2)
    light = int(hq * _LIGHT_BYTE_FACTOR)
    total = int((hq + light + _POSTER_MAX_BYTES) * _SLOT_OVERHEAD_FACTOR)
    return total


def normalize_object_sha(sha: str) -> str:
    """Validate + normalize a content SHA (64 lower hex). Fail closed."""
    if not isinstance(sha, str):
        raise ValueError("object sha must be a string")
    s = sha.strip().lower()
    if len(s) != 64 or any(c not in "0123456789abcdef" for c in s):
        raise ValueError("object sha must be 64 lower-hex chars")
    return s


def validate_canary_slot_size(slot: str, size_bytes: int) -> int:
    """Strict per-slot artifact cap (canary-only). Returns int size."""
    try:
        size = int(size_bytes)
    except (TypeError, ValueError):
        raise ValueError("slot size must be a positive int")
    if size <= 0:
        raise ValueError("slot size must be a positive int")
    cap = CANARY_SLOT_MAX_BYTES.get(slot)
    if cap is None:
        raise ValueError(f"unknown canary slot {slot!r}")
    if size > cap:
        raise ValueError(
            f"canary slot {slot!r} claimed {size} > cap {cap}; refusing (fail closed)"
        )
    return size


def _is_postgres(db) -> bool:
    try:
        return db.bind is not None and db.bind.dialect.name == "postgresql"
    except Exception:
        return False


def _advisory_xact_lock(db, key: tuple[int, int]) -> None:
    """Best-effort PG advisory xact lock (no-op on SQLite).

    Serializes concurrent slot/admit decisions across API processes.
    Xact-scoped: released at the (short) reservation transaction commit,
    never held across network.
    """
    if not _is_postgres(db):
        return
    from sqlalchemy import text as _text

    db.execute(_text("SELECT pg_advisory_xact_lock(:a, :b)"), {"a": key[0], "b": key[1]})


def canary_reserved_bytes(db) -> int:
    """Sum of the durable reservation ledger (orphans included)."""
    try:
        from app.models.canary_ledger import CanarySlotReservation
    except Exception:
        return 0
    try:
        rows = db.query(CanarySlotReservation.size_bytes).all()
    except Exception:
        # Table missing (migration not yet applied): fail closed at the
        # callers that enforce the budget, but keep this sum helper
        # total-safe for read-only paths.
        return 0
    total = 0
    for r in rows:
        try:
            total += int(r[0] or 0)
        except (TypeError, ValueError):
            continue
    return total


def canary_legacy_ready_bytes(db, exclude_shas: set[str] | None = None) -> int:
    """Committed READY derivative bytes not already reserved (upgrade path).

    Sums ``MediaBlob.byte_size`` for DISTINCT derivative blobs with a
    ``ready`` row, skipping SHAs already counted in the reservation
    ledger so the same object is never double-charged.
    """
    from app.models.media_backbone import MediaBlob, MediaDerivative

    exclude = {s.lower() for s in (exclude_shas or set()) if s}
    cap_rows = 5000
    try:
        sha_rows = (
            db.query(MediaDerivative.derivative_blob_sha256)
            .filter(MediaDerivative.status == "ready")
            .limit(cap_rows + 1)
            .all()
        )
    except Exception:
        return 0
    if len(sha_rows) > cap_rows:
        raise CanaryBudgetExceeded(
            f"derivative ledger exceeds bounded scan ({cap_rows} ready rows); "
            "refusing budget proof -- investigate before any canary"
        )
    shas = {str(r[0]).lower() for r in sha_rows if r and r[0]} - exclude
    if not shas:
        return 0
    total = 0
    shas_list = sorted(shas)
    for i in range(0, len(shas_list), 500):
        chunk = shas_list[i : i + 500]
        rows = db.query(MediaBlob.byte_size).filter(MediaBlob.sha256.in_(chunk)).all()
        for r in rows:
            try:
                total += int(r[0] or 0)
            except (TypeError, ValueError):
                continue
    return total


def canary_reserved_shas(db) -> set[str]:
    """Distinct reserved object SHAs (bounded)."""
    try:
        from app.models.canary_ledger import CanarySlotReservation
    except Exception:
        return set()
    try:
        rows = db.query(CanarySlotReservation.object_sha256).limit(5001).all()
    except Exception:
        return set()
    if len(rows) > 5000:
        raise CanaryBudgetExceeded("reservation ledger exceeds bounded scan; refusing")
    return {str(r[0]).lower() for r in rows if r and r[0]}


def canary_accounted_bytes(db) -> int:
    """Authoritative canary bytes: reservations + legacy ready not reserved.

    Counts EVERY attempted unique upload (orphans included) exactly once
    per content SHA. Monotonic (never decreases).
    """
    reserved = canary_reserved_bytes(db)
    shas = canary_reserved_shas(db)
    legacy = canary_legacy_ready_bytes(db, exclude_shas=shas)
    return reserved + legacy


def canary_ledger_bytes(db) -> int:
    """Committed-or-attempted canary bytes (reservation-inclusive).

    Backward-compatible name: previously summed READY rows only
    (orphan-invisible). Now returns :func:`canary_accounted_bytes` so
    every caller enforces the hard bound on ALL attempted unique bytes.
    """
    return canary_accounted_bytes(db)


def remaining_budget_bytes(db) -> int:
    """Authoritative remaining bytes under the hard cap (may be <= 0)."""
    return CANARY_BUDGET_BYTES - canary_accounted_bytes(db)


def check_publish_budget(db, incoming_bytes: int) -> int:
    """Authoritative publish-time pre-check: refuse overshoot BEFORE bytes stream.

    Fast fail-closed gate on CLAIMED size (no reservation, no lock).
    The authoritative reservation happens in
    :func:`reserve_canary_upload` immediately after (same short TX on
    PG under an advisory lock). In-flight concurrency is bounded by
    the global one-package lease cap + serial admission + the atomic
    reservation, so overshoot is limited to at most one refused slot.
    """
    try:
        incoming = int(incoming_bytes)
    except (TypeError, ValueError):
        raise ValueError("slot size must be a positive int")
    if incoming <= 0:
        raise ValueError("slot size must be a positive int")
    committed = canary_accounted_bytes(db)
    if committed + incoming > CANARY_BUDGET_BYTES:
        raise CanaryBudgetExceeded(
            f"canary budget exceeded: accounted {committed} + incoming {incoming} "
            f"> {CANARY_BUDGET_BYTES} (2 GiB hard cap, orphans included)"
        )
    return CANARY_BUDGET_BYTES - (committed + incoming)


def reserve_canary_upload(db, sha256: str, size_bytes: int, *, job_id=None, slot=None) -> int:
    """Atomically reserve budget for one unique object BEFORE B2 bytes stream.

    - Validates SHA (64 hex) + size (>0, per-slot cap when slot known).
    - Same-SHA retry dedupes: an existing row must carry the SAME size
      (mismatch fails closed -- corrupt claim) and costs nothing new.
    - New SHA: checks accounted + incoming <= 2 GiB under a PG advisory
      xact lock, then inserts the reservation row in the SAME short
      transaction (no network held). SQLite serializes on the UNIQUE
      index (IntegrityError -> re-read winner, dedupe or budget error).
    - Commits the reservation transaction before returning so the row
      is durable even if the later upload/publish fails (orphan stays
      counted -- monotonic, never released).
    - Returns remaining budget after this object.

    CANARY ONLY. Raises ``CanaryBudgetExceeded`` on overshoot,
    ``ValueError`` on malformed identity/size.
    """
    from sqlalchemy.exc import IntegrityError, OperationalError

    from app.models.canary_ledger import CanarySlotReservation

    def _missing_table(exc: Exception) -> bool:
        msg = str(exc).lower()
        return "no such table" in msg or "does not exist" in msg or "undefinedtable" in msg

    sha = normalize_object_sha(sha256)
    size = validate_canary_slot_size(slot, size_bytes) if slot else int(size_bytes or 0)
    if not slot:
        try:
            size = int(size_bytes)
        except (TypeError, ValueError):
            raise ValueError("slot size must be a positive int")
        if size <= 0:
            raise ValueError("slot size must be a positive int")
    if job_id is not None:
        try:
            job_id = int(job_id)
        except (TypeError, ValueError):
            raise ValueError("job_id must be an int")

    _advisory_xact_lock(db, _CANARY_BUDGET_LOCK)

    try:
        existing = (
            db.query(CanarySlotReservation)
            .filter(CanarySlotReservation.object_sha256 == sha)
            .limit(1)
            .first()
        )
    except OperationalError as exc:
        try:
            db.rollback()
        except Exception:
            pass
        if _missing_table(exc):
            raise CanaryBudgetExceeded(
                "canary reservation ledger missing (apply add_canary_slot_reservations.sql "
                "BEFORE any canary); refusing"
            ) from exc
        raise
    if existing is not None:
        try:
            prev_size = int(existing.size_bytes or 0)
        except (TypeError, ValueError):
            prev_size = -1
        if prev_size != int(size):
            raise ValueError(
                f"canary reservation conflict for {sha[:12]}...: "
                f"existing size {prev_size} != claimed {int(size)}; refusing"
            )
        return CANARY_BUDGET_BYTES - canary_accounted_bytes(db)

    accounted = canary_accounted_bytes(db)
    if accounted + int(size) > CANARY_BUDGET_BYTES:
        try:
            db.rollback()
        except Exception:
            pass
        raise CanaryBudgetExceeded(
            f"canary budget exceeded: accounted {accounted} + incoming {int(size)} "
            f"> {CANARY_BUDGET_BYTES} (2 GiB hard cap, orphans included)"
        )
    row = CanarySlotReservation(
        object_sha256=sha, size_bytes=int(size), job_id=job_id, slot=slot, status="reserved"
    )
    db.add(row)
    try:
        db.flush()
    except OperationalError as exc:
        try:
            db.rollback()
        except Exception:
            pass
        if _missing_table(exc):
            raise CanaryBudgetExceeded(
                "canary reservation ledger missing (apply add_canary_slot_reservations.sql "
                "BEFORE any canary); refusing"
            ) from exc
        raise
    except IntegrityError:
        # Lost a same-SHA race (SQLite or PG): re-read the winner.
        try:
            db.rollback()
        except Exception:
            pass
        winner = (
            db.query(CanarySlotReservation)
            .filter(CanarySlotReservation.object_sha256 == sha)
            .limit(1)
            .first()
        )
        if winner is None:
            raise CanaryBudgetExceeded("canary reservation race lost; please retry")
        try:
            prev_size = int(winner.size_bytes or 0)
        except (TypeError, ValueError):
            prev_size = -1
        if prev_size != int(size):
            raise ValueError(
                f"canary reservation conflict for {sha[:12]}...: "
                f"existing size {prev_size} != claimed {int(size)}; refusing"
            )
        return CANARY_BUDGET_BYTES - canary_accounted_bytes(db)
    try:
        db.commit()
    except OperationalError as exc:
        try:
            db.rollback()
        except Exception:
            pass
        if _missing_table(exc):
            raise CanaryBudgetExceeded(
                "canary reservation ledger missing (apply add_canary_slot_reservations.sql "
                "BEFORE any canary); refusing"
            ) from exc
        raise
    except IntegrityError:
        try:
            db.rollback()
        except Exception:
            pass
        winner = (
            db.query(CanarySlotReservation)
            .filter(CanarySlotReservation.object_sha256 == sha)
            .limit(1)
            .first()
        )
        if winner is None:
            raise CanaryBudgetExceeded("canary reservation race lost; please retry")
        return CANARY_BUDGET_BYTES - canary_accounted_bytes(db)
    return CANARY_BUDGET_BYTES - canary_accounted_bytes(db)


def db_admitted_uuids(db, limit: int = 100) -> set[str]:
    """Distinct video_uuids with ANY web_package job (durable DB cohort).

    Bounded scan (canary fleet <= 30; cap is a safety rail -- exceeding
    it fails closed). Uses the DB, never the private state dir, so a
    reset state dir cannot bypass the total-30 cap.
    """
    from app.models.media import MediaJob
    from app.models.photos_asset import PhotosAsset

    cap = max(int(limit), 1)
    try:
        rows = (
            db.query(PhotosAsset.video_uuid)
            .join(MediaJob, MediaJob.photos_asset_id == PhotosAsset.id)
            .filter(MediaJob.rendition == "web_package")
            .limit(cap + 1)
            .all()
        )
    except Exception:
        return set()
    if len(rows) > cap:
        raise CanaryBudgetExceeded(
            f"web_package cohort exceeds bounded scan ({cap}); refusing -- investigate"
        )
    return {str(r[0]) for r in rows if r and r[0]}


def check_phase2_eligible(
    *,
    phase1_cohort: list[str],
    proven_uuids: set[str],
    db_total_admitted: set[str],
    new_count: int,
) -> None:
    """Phase-2 gate: exact phase-1 cohort fully proven + durable totals.

    - ``phase1_cohort``: the EXACT expected phase-1 UUIDs (<= 5,
      from ``--phase1-manifest``).
    - Every phase-1 UUID must be in ``proven_uuids`` (explicit proof
      records, never auto-ready) AND durably admitted in the DB.
    - ``len(db_total_admitted) + new_count`` must stay <= 30 (DB is
      authoritative for the total; a reset state dir cannot bypass it).
    """
    if not phase1_cohort:
        raise ValueError("phase 2 requires --phase1-manifest (exact phase-1 cohort, <= 5)")
    if len(phase1_cohort) > CANARY_PHASE1_MAX_CLIPS:
        raise ValueError(
            f"phase-1 cohort has {len(phase1_cohort)} clips; max is {CANARY_PHASE1_MAX_CLIPS}"
        )
    missing_proof = [u for u in phase1_cohort if u not in set(proven_uuids or set())]
    if missing_proof:
        raise ValueError(
            f"phase 2 blocked: {len(missing_proof)}/{len(phase1_cohort)} phase-1 clips "
            f"lack PROOF (ready != proven): e.g. {missing_proof[0][:8]}..."
        )
    missing_db = [u for u in phase1_cohort if u not in set(db_total_admitted or set())]
    if missing_db:
        raise ValueError(
            f"phase 2 blocked: {len(missing_db)} phase-1 clips have no durable DB job "
            f"(e.g. {missing_db[0][:8]}...); state-dir alone never suffices"
        )
    if len(set(db_total_admitted or set())) + int(new_count) > CANARY_TOTAL_MAX_CLIPS:
        raise ValueError(
            f"phase 2 blocked: DB total {len(set(db_total_admitted or set()))} + "
            f"new {int(new_count)} > {CANARY_TOTAL_MAX_CLIPS}"
        )


# ---------------------------------------------------------------------------
# Operator host facts (freshness + memory pressure, no live probing here)
# ---------------------------------------------------------------------------

def load_host_facts(path: str | Path) -> dict:
    """Load + validate the operator host-facts file (private JSON, 0600).

    Expected shape::

        {"mac_free_bytes": 123, "server_cache_free_bytes": 456,
         "mac_memory_pressure": "normal",
         "checked_at": "2026-10-21T20:00:00+00:00",
         "mac_data_path": "/Users/Shared/services/...",
         "server_cache_path": "/var/lib/..."}
    """
    p = Path(str(path)).expanduser()
    try:
        raw = json.loads(p.read_text())
    except FileNotFoundError:
        raise ValueError(f"host facts not found: {p} (required for --apply)")
    except json.JSONDecodeError as exc:
        raise ValueError(f"host facts are not valid JSON: {exc}")
    if not isinstance(raw, dict):
        raise ValueError("host facts must be a JSON object")
    return raw


def validate_host_facts(facts: dict, *, now=None) -> dict:
    """Enforce fresh host facts + free-space + memory pressure. Fail closed."""
    if not isinstance(facts, dict):
        raise ValueError("host facts must be a JSON object")
    try:
        mac_free = int(facts.get("mac_free_bytes"))
    except (TypeError, ValueError):
        raise ValueError("host facts: mac_free_bytes must be an int")
    try:
        srv_free = int(facts.get("server_cache_free_bytes"))
    except (TypeError, ValueError):
        raise ValueError("host facts: server_cache_free_bytes must be an int")
    pressure = str(facts.get("mac_memory_pressure") or "").strip().lower()
    if pressure != "normal":
        raise ValueError(
            f"host facts: mac_memory_pressure={pressure!r} (expected 'normal'); "
            "stop new admissions on memory pressure"
        )
    checked_raw = str(facts.get("checked_at") or "").strip()
    if not checked_raw:
        raise ValueError("host facts: checked_at (ISO-8601) is required")
    try:
        checked = datetime.fromisoformat(checked_raw.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("host facts: checked_at must be ISO-8601")
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=timezone.utc)
    ref = now or datetime.now(timezone.utc)
    age = (ref - checked).total_seconds()
    if age < -60:
        raise ValueError("host facts: checked_at is in the future; refusing")
    if age > HOST_FACTS_MAX_AGE_SECONDS:
        raise ValueError(
            f"host facts stale: {int(age)}s old (max {HOST_FACTS_MAX_AGE_SECONDS}s); "
            "re-check host disks/memory before --apply"
        )
    if mac_free < MIN_MAC_DATA_FREE_BYTES:
        raise ValueError(f"Mac Data free {mac_free} < {MIN_MAC_DATA_FREE_BYTES} (8 GiB)")
    if srv_free < MIN_SERVER_CACHE_FREE_BYTES:
        raise ValueError(
            f"server cache volume free {srv_free} < {MIN_SERVER_CACHE_FREE_BYTES} (25 GiB)"
        )
    for key in ("mac_data_path", "server_cache_path"):
        val = str(facts.get(key) or "").strip()
        if not val or not val.startswith("/"):
            raise ValueError(f"host facts: {key} must be an absolute path (runbook)")
    return {
        "mac_free_bytes": mac_free,
        "server_cache_free_bytes": srv_free,
        "mac_memory_pressure": pressure,
        "checked_at": checked.isoformat(),
        "age_seconds": int(age),
    }
