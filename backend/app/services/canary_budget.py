"""Bounded canary admission + publication budget preflight (D3b2 next slice).

Local-only, reviewable, no network/prod/B2. This module is the single
place that names the night-canary bounds so the ops tool, the slot
publish guard, and the tests share one contract:

- FIRST wave <= 5 clips (a smaller first wave may run but NEVER unlocks
  phase 2); only on 100% proof of EXACTLY 5 distinct phase-1 clips
  (5/5 proven) may <= 25 more follow
  (fleet total <= 30).
- New B2 bytes HARD cumulative <= 2 GiB, counting EVERY attempted
  PUT including safe orphans (durable per-PUT charge ledger keyed by
  EXACT B2 namespace bucket+object_key -- identical bytes under
  different keys are distinct objects and count separately; the SAME
  key retried charges PER ATTEMPT -- monotonic, never deleted, never
  refunded). A verified full-GET reuse (same key already proves the
  same bytes) skips the PUT and charges nothing new; a DEFINITE-absent
  reuse GET (typed NoSuchKey/404, or fake KeyError/FileNotFound) is the
  only miss that authorizes charge+PUT -- any other GET failure
  (500/timeout/auth/corrupt read) fails closed with no PUT and no new
  charge, preserving monotonic accounting; but once the GET
  definitely misses, the attempt MUST charge before the PUT, so two concurrent
  racers that both miss each charge. Estimates are
  preflight ONLY and never promise the bound -- the bound is enforced
  server-side at publish time by ``check_publish_budget`` (fast
  fail-closed pre-check on CLAIMED size, no row, no lock) AND
  ``reserve_canary_upload`` (authoritative per-PUT charge of the
  ACTUAL bytes with the exact B2 key AFTER the reuse GET misses and
  BEFORE the PUT streams, inside a short PG transaction under an
  advisory lock -- never held across network, committed before the
  PUT so orphans/failed PUTs stay counted). Same bucket+key with a
  different SHA/size fails closed (corrupt claim); same key, same
  SHA/size retried charges again (each PUT may store a new version --
  over-counting replays is the safe direction).
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
- The single package lease does NOT serialize duplicate HTTP or stale
  in-flight B2 attempts: concurrent same-key publishers may each stream
  a PUT. The cap holds because EVERY PUT attempt charges separately
  before streaming (PG advisory lock + cumulative check), never because
  the lease prevents the second PUT.
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

#: Server-persisted job reason marking a canary package. The slot route and
#: the publisher derive the canary budget scope from this DB-persisted value
#: ONLY -- never from any client-supplied bool, form field, or query param.
#: Any other reason (including NULL) is a NON-canary package and never pays
#: the canary cap.
CANARY_JOB_REASON = "canary_web_package"

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


def is_canary_job(job) -> bool:
    """Server-trusted canary scope: DB-persisted job reason ONLY.

    Returns True only when ``job.request_reason == "canary_web_package"``.
    Never consults client input: the slot route passes the lease/agent
    fields from the request, but the scope decision reads the persisted
    job row. Non-canary web_package jobs are unaffected by the canary cap.
    """
    try:
        return str(getattr(job, "request_reason", "") or "") == CANARY_JOB_REASON
    except Exception:
        return False


def canary_scope_for_job_id(db, job_id: int) -> bool:
    """Re-read the persisted job reason for a scope decision (fail closed).

    Used by the slot route AFTER the lease peek: the scope comes from the
    current DB row, so a client cannot flip a job into (or out of) the
    canary budget. Unknown/missing job -> False (no budget consumed).
    Any DB/schema error raises (never a false False that would let a
    canary PUT stream without charge on a misconfigured DB).
    """
    from app.models.media import MediaJob

    try:
        job = db.get(MediaJob, int(job_id))
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        if _is_missing_schema_error(exc):
            raise CanaryBudgetExceeded(
                "canary scope unavailable (media_jobs table missing); refusing"
            ) from exc
        raise
    if job is None:
        return False
    return is_canary_job(job)


def canonical_canary_key(
    *,
    source_sha256: str,
    role: str,
    transform_version: str,
    derivative_sha256: str,
    bucket: str,
    environment: str,
    prefix: str | None = None,
) -> tuple[str, str, str]:
    """Trusted exact-B2-key computation (pure, no DB txn, no network).

    Returns ``(bucket, object_key, environment)`` where ``object_key`` is
    the content-addressed derivative key
    ``<prefix>/derived/<source[:2]>/<role>-<version>-<derivative_sha>``.
    All inputs are validated fail-closed; the key embeds the source, role,
    version AND output SHA so identical bytes under different
    clips/roles/versions are distinct keys (distinct stored objects).
    Callers reserve on this exact namespace, never on content SHA alone.
    """
    from app.services.derivative_publisher import derivative_object_key

    sha = normalize_object_sha(derivative_sha256)
    src = normalize_object_sha(source_sha256)
    if role not in CANARY_SLOT_MAX_BYTES:
        raise ValueError(f"unknown canary slot {role!r}")
    tv = str(transform_version or "").strip()
    if not tv or len(tv) > 40 or "|" in tv:
        raise ValueError("transform version must be non-empty (<=40, no '|')")
    bkt = str(bucket or "").strip()
    if not bkt:
        raise ValueError("canary reservation requires a bucket")
    env = str(environment or "").strip().lower()
    if env not in ("dev", "prod"):
        raise ValueError("canary reservation requires environment dev|prod")
    key = derivative_object_key(
        source_sha256=src,
        role=role,
        transform_version=tv,
        derivative_sha256=sha,
        prefix=prefix,
    )
    if not key.endswith(sha):
        raise ValueError("canary key does not embed the content SHA; refusing")
    return bkt, key, env


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


#: Bounded proof rails (consistent everywhere): no ledger/baseline scan
#: may silently aggregate an unbounded table. 5000 rows is far above the
#: canary fleet (<= 30) and keeps SUM/COUNT bounded on every backend.
_CANARY_LEDGER_CAP_ROWS = 5000
_CANARY_READY_CAP_ROWS = 5000


def _is_missing_schema_error(exc: Exception) -> bool:
    """True when the DB reports a missing table/column (migration not applied)."""
    msg = str(exc).lower()
    return (
        "no such table" in msg
        or "no such column" in msg
        or "does not exist" in msg
        or "undefinedtable" in msg
        or "undefinedcolumn" in msg
    )


def _missing_ledger_error() -> CanaryBudgetExceeded:
    return CanaryBudgetExceeded(
        "canary reservation ledger unavailable "
        "(apply backend/migrations/add_canary_slot_reservations.sql + "
        "add_canary_slot_reservation_exact_key.sql + "
        "add_canary_put_attempt_charges.sql BEFORE any canary); refusing"
    )


def _missing_baseline_error() -> CanaryBudgetExceeded:
    return CanaryBudgetExceeded(
        "canary READY baseline unavailable (media_derivatives/media_blobs "
        "tables or columns missing -- apply pending migrations BEFORE any "
        "canary); refusing budget proof"
    )


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
    """Sum of the durable reservation ledger (orphans included). FAIL CLOSED.

    Bounded SQL aggregate: COUNT first (rail at 5000 rows), then a
    NULL/negative guard, then COALESCE(SUM). Never loads all rows.
    Missing ledger table/columns, any DB error, or any NULL/non-positive
    size raises (no silent 0): an unverifiable ledger must refuse the
    PUT, never authorize beyond the cap. Returns 0 ONLY when the table
    exists and is verified empty (COUNT == 0).
    """
    from sqlalchemy import func as _func

    from app.models.canary_ledger import CanarySlotReservation

    try:
        count = db.query(_func.count(CanarySlotReservation.id)).scalar()
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        if _is_missing_schema_error(exc):
            raise _missing_ledger_error() from exc
        raise
    try:
        count_n = int(count or 0)
    except (TypeError, ValueError):
        raise CanaryBudgetExceeded("canary ledger count unreadable; refusing")
    if count_n > _CANARY_LEDGER_CAP_ROWS:
        raise CanaryBudgetExceeded(
            f"reservation ledger exceeds bounded scan ({_CANARY_LEDGER_CAP_ROWS} rows); "
            "refusing budget proof -- investigate before any canary"
        )
    if count_n == 0:
        return 0
    try:
        bad = (
            db.query(_func.count(CanarySlotReservation.id))
            .filter(
                (CanarySlotReservation.size_bytes.is_(None))
                | (CanarySlotReservation.size_bytes <= 0)
            )
            .scalar()
        )
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        if _is_missing_schema_error(exc):
            raise _missing_ledger_error() from exc
        raise
    if int(bad or 0) > 0:
        raise CanaryBudgetExceeded(
            "canary ledger holds NULL/non-positive size_bytes; "
            "refusing budget proof -- investigate before any canary"
        )
    try:
        total = (
            db.query(_func.coalesce(_func.sum(CanarySlotReservation.size_bytes), 0)).scalar()
        )
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        if _is_missing_schema_error(exc):
            raise _missing_ledger_error() from exc
        raise
    try:
        total_n = int(total or 0)
    except (TypeError, ValueError):
        raise CanaryBudgetExceeded("canary ledger sum unreadable; refusing")
    if total_n < 0:
        raise CanaryBudgetExceeded("canary ledger sum negative; refusing")
    return total_n


def canary_legacy_ready_bytes(db) -> int:
    """Pre-charge READY baseline, counted per exact object (no SHA dedupe). FAIL CLOSED.

    Sums ``MediaBlob.byte_size`` once per READY ``media_derivatives``
    row (each row is an exact stored object: its B2 key embeds
    source+role+version+SHA, so the same content SHA under two
    identities is two objects and counts twice). The baseline ALWAYS
    counts every READY row, PLUS the durable per-PUT charge ledger
    (``canary_reserved_bytes``) counts every attempted PUT -- a
    successful canary PUT therefore counts TWICE by design (once as a
    charge, once as READY baseline). This intentional conservative
    over-count keeps the 2 GiB bound STRICTER than actual stored bytes:
    accounted bytes never under-count, so actual stored bytes never
    exceed the budget when the proof passes (monotonic, never UNCOUNTs
    a pre-existing baseline row, even when a later charge reuses the
    same bucket/key after an unverifiable reuse GET). A READY row with
    no/invalid blob size fails closed (refuses the proof rather than
    silently under-counting). Bounded scan (cap 5000 ready rows,
    consistent with the ledger rail).

    Returns 0 ONLY when the derivatives table exists and holds zero
    READY rows (verified empty history). Missing tables/columns, any
    DB error, or any NULL/non-positive blob size raises: an
    unverifiable baseline must refuse the PUT, never authorize it.
    The SAVEPOINT isolates the probe so a baseline failure never
    poisons the caller's transaction -- it re-raises fail-closed
    instead of returning a false 0.
    """
    from sqlalchemy import func as _func

    from app.models.media_backbone import MediaDerivative

    cap_rows = _CANARY_READY_CAP_ROWS
    try:
        with db.begin_nested():
            ready_count = (
                db.query(_func.count(MediaDerivative.id))
                .filter(MediaDerivative.status == "ready")
                .scalar()
            )
            try:
                ready_n = int(ready_count or 0)
            except (TypeError, ValueError):
                raise CanaryBudgetExceeded("canary baseline count unreadable; refusing")
            if ready_n > cap_rows:
                raise CanaryBudgetExceeded(
                    f"derivative ledger exceeds bounded scan ({cap_rows} ready rows); "
                    "refusing budget proof -- investigate before any canary"
                )
            if ready_n == 0:
                rows: list = []
            else:
                rows = (
                    db.query(
                        MediaDerivative.source_blob_sha256,
                        MediaDerivative.role,
                        MediaDerivative.transform_version,
                        MediaDerivative.derivative_blob_sha256,
                    )
                    .filter(MediaDerivative.status == "ready")
                    .limit(cap_rows + 1)
                    .all()
                )
    except CanaryBudgetExceeded:
        raise
    except Exception as exc:
        if _is_missing_schema_error(exc):
            raise _missing_baseline_error() from exc
        raise
    if len(rows) > cap_rows:
        raise CanaryBudgetExceeded(
            f"derivative ledger exceeds bounded scan ({cap_rows} ready rows); "
            "refusing budget proof -- investigate before any canary"
        )
    if not rows:
        return 0
    # Monotonic baseline: ALWAYS count every READY row (no ledger
    # exclusion). A successful canary PUT charges first, then promotes,
    # so it counts twice by design (charge + baseline) -- intentional
    # conservative over-count, never under-count. A pre-existing READY
    # row whose later reuse GET fails unverifiably therefore never
    # disappears from accounting even when the retry charges again.
    from app.models.media_backbone import MediaBlob

    # Per exact object: same SHA in N rows is N objects (count each).
    pending: list[str] = []
    for _src_sha, _role, _version, dsha in rows:
        d = str(dsha or "").strip().lower()
        if not d:
            raise CanaryBudgetExceeded(
                "READY derivative row has no artifact SHA; "
                "refusing budget proof -- investigate before any canary"
            )
        pending.append(d)
    need_shas = sorted(set(pending))
    sizes: dict[str, int] = {}
    try:
        for i in range(0, len(need_shas), 500):
            chunk = need_shas[i : i + 500]
            blob_rows = db.query(MediaBlob.sha256, MediaBlob.byte_size).filter(
                MediaBlob.sha256.in_(chunk)
            ).all()
            for sha, size in blob_rows:
                try:
                    size_n = int(size) if size is not None else None
                except (TypeError, ValueError):
                    raise CanaryBudgetExceeded(
                        "canary baseline blob size unreadable; refusing budget proof"
                    )
                if size_n is None or size_n <= 0:
                    raise CanaryBudgetExceeded(
                        "canary baseline blob holds NULL/non-positive byte_size; "
                        "refusing budget proof -- investigate before any canary"
                    )
                sizes[str(sha).lower()] = size_n
    except CanaryBudgetExceeded:
        raise
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        if _is_missing_schema_error(exc):
            raise _missing_baseline_error() from exc
        raise
    total = 0
    for d in pending:
        if d not in sizes:
            raise CanaryBudgetExceeded(
                f"READY derivative {d[:12]}... has no blob size; "
                "refusing budget proof -- investigate before any canary"
            )
        size_n = sizes[d]
        if size_n is None or int(size_n) <= 0:
            raise CanaryBudgetExceeded(
                "canary baseline blob holds NULL/non-positive byte_size; refusing"
            )
        total += int(size_n)
    return total


def canary_reserved_shas(db) -> set[str]:
    """Distinct reserved object SHAs (bounded). FAIL CLOSED.

    Raises on any DB/schema error or when any row carries a NULL/empty
    SHA: an unverifiable set must refuse, never look empty.
    """
    from sqlalchemy import func as _func

    from app.models.canary_ledger import CanarySlotReservation

    try:
        count = db.query(_func.count(CanarySlotReservation.id)).scalar()
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        if _is_missing_schema_error(exc):
            raise _missing_ledger_error() from exc
        raise
    if int(count or 0) > _CANARY_LEDGER_CAP_ROWS:
        raise CanaryBudgetExceeded("reservation ledger exceeds bounded scan; refusing")
    if int(count or 0) == 0:
        return set()
    try:
        rows = db.query(CanarySlotReservation.object_sha256).limit(_CANARY_LEDGER_CAP_ROWS + 1).all()
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        if _is_missing_schema_error(exc):
            raise _missing_ledger_error() from exc
        raise
    if len(rows) > _CANARY_LEDGER_CAP_ROWS:
        raise CanaryBudgetExceeded("reservation ledger exceeds bounded scan; refusing")
    out: set[str] = set()
    for r in rows:
        sha = r[0] if r else None
        if not sha or not str(sha).strip():
            raise CanaryBudgetExceeded(
                "canary ledger holds NULL/empty object_sha256; refusing"
            )
        out.add(str(sha).lower())
    return out


def canary_accounted_bytes(db) -> int:
    """Authoritative canary bytes: per-PUT charges + READY baseline. FAIL CLOSED.

    Counts EVERY attempted PUT (orphans included), once per attempt row
    -- the same key retried counts again (each PUT may store a new
    version). Plus the pre-charge READY baseline, counted per exact
    derivative object (not per SHA), ALWAYS (no ledger exclusion).
    A successful canary PUT therefore counts TWICE by design (charge +
    baseline): intentional conservative over-count, never under-count.
    Actual stored bytes never exceed accounted bytes, so passing the
    2 GiB proof guarantees stored bytes stay under the cap (stricter,
    monotonic, never UNCOUNTs). Monotonic (never decreases);
    replay/double-record over-counts (safe) rather than under-counts.

    Raises on any unverifiable proof (missing tables, unavailable
    baseline/reservation, invalid sizes, unbounded scan). Returns 0
    ONLY when both the ledger and the READY baseline are verified
    empty. Callers must treat any exception as "budget unknown --
    refuse the PUT".
    """
    reserved = canary_reserved_bytes(db)
    legacy = canary_legacy_ready_bytes(db)
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
    """Publish-time pre-check: refuse overshoot BEFORE bytes stream.

    Fast fail-closed gate on CLAIMED size (read-only: no row, no lock, no
    reservation). The route calls this prestream as a size-cap only; the
    AUTHORITATIVE per-PUT charge happens in :func:`reserve_canary_upload`
    on the ACTUAL bytes with the exact B2 key, after the pre-PUT
    full-GET reuse check misses and immediately before the PUT streams
    inside the publisher (short TX on PG under an advisory lock, never
    held across network, committed before the PUT so orphans stay
    counted). Untrusted route claims therefore never consume
    committed budget for another job. In-flight concurrency is bounded by
    the global one-package lease cap + serial admission + the atomic
    per-attempt charge, so overshoot fails one racer before its PUT.
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


def reserve_canary_upload(
    db,
    sha256: str,
    size_bytes: int,
    *,
    job_id=None,
    slot=None,
    bucket=None,
    object_key=None,
    environment=None,
) -> int:
    """Charge one PUT attempt BEFORE its bytes stream (durable, monotonic).

    Identity is the EXACT B2 namespace ``(bucket, object_key)`` -- never
    content SHA alone. Identical bytes under different keys (different
    clip/source/role/version) are distinct objects and count separately.
    The key must embed the content SHA (``...-<sha>``); compute it with
    :func:`canonical_canary_key` (pure, no DB txn, no network) from the
    trusted ctx pin -- never from an untrusted client claim.

    - Validates SHA (64 hex) + size (>0, per-slot cap when slot known).
    - EVERY call inserts its own charge row: the same bucket+key retried
      (same SHA/size) charges AGAIN -- each PUT may store a new B2
      version, and a concurrent same-key race that both missed the
      pre-PUT full-GET reuse check PUTs twice, so both attempts must
      count. Idempotent replay over-counts (safe); the exact same
      attempt is never silently free while another PUT could happen.
    - Same key with a DIFFERENT SHA/size fails closed (corrupt claim):
      no new charge, no PUT.
    - New charge: checks accounted + incoming <= 2 GiB under a PG
      advisory xact lock, then inserts + commits the charge row in the
      SAME short transaction (no network held). SQLite has no advisory
      lock; the short commit still keeps the charge durable.
    - Commits before returning so the row is durable even if the later
      PUT/publish fails (orphan stays counted -- monotonic, never
      released or refunded; stale in-flight attempts count once
      committed, and uncommitted in-flight attempts serialize on the
      advisory lock so combined overshoot fails one of them).
    - Returns remaining budget after this charge.

    Call AFTER the pre-PUT full-GET reuse check misses and BEFORE the
    PUT streams: a verified reuse (same key already proves the same
    bytes) skips both the charge and the PUT. Do NOT hold the DB lock
    across the network.

    B2 versioning bound (hard, documented): the publisher skips the PUT
    when a full GET of the same key already proves the same bytes
    (verified reuse, no new version). A same-key retry after a
    successful PUT therefore creates no new stored version and takes
    this no-charge path; concurrent same-key races that both miss the
    GET each charge and each PUT (bounded to in-flight parallelism:
    fleet one-package + serial admit -> at most one extra version).

    CANARY ONLY. Raises ``CanaryBudgetExceeded`` on overshoot,
    ``ValueError`` on malformed identity/size/key.
    """
    from sqlalchemy.exc import OperationalError

    from app.models.canary_ledger import CanarySlotReservation

    def _missing_table(exc: Exception) -> bool:
        msg = str(exc).lower()
        return "no such table" in msg or "does not exist" in msg or "undefinedtable" in msg

    def _missing_column(exc: Exception) -> bool:
        msg = str(exc).lower()
        return "no such column" in msg or "does not exist" in msg or "undefinedcolumn" in msg

    def _fail_missing_schema(exc: Exception) -> CanaryBudgetExceeded:
        return CanaryBudgetExceeded(
            "canary reservation ledger missing exact-key columns "
            "(apply add_canary_slot_reservation_exact_key.sql BEFORE any canary); refusing"
        )

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
    # Exact-key identity is REQUIRED (no SHA-only fallback: SHA-only
    # dedupe under-counts distinct B2 objects).
    bkt = str(bucket or "").strip()
    key = str(object_key or "").strip()
    env = str(environment or "").strip().lower() if environment is not None else None
    if not bkt or not key:
        raise ValueError("canary reservation requires exact B2 bucket + object_key")
    if len(key) > 1024:
        raise ValueError("canary object_key too long (>1024)")
    if env is not None and env not in ("dev", "prod"):
        raise ValueError("canary environment must be dev|prod")
    if not key.endswith(sha):
        raise ValueError(
            "canary reservation key does not embed the content SHA; refusing"
        )

    _advisory_xact_lock(db, _CANARY_BUDGET_LOCK)

    try:
        clashing = (
            db.query(CanarySlotReservation)
            .filter(
                CanarySlotReservation.bucket == bkt,
                CanarySlotReservation.object_key == key,
                (CanarySlotReservation.object_sha256 != sha)
                | (CanarySlotReservation.size_bytes != int(size)),
            )
            .limit(1)
            .first()
        )
    except OperationalError as exc:
        try:
            db.rollback()
        except Exception:
            pass
        if _missing_table(exc) or _missing_column(exc):
            raise _fail_missing_schema(exc) from exc
        raise
    if clashing is not None:
        try:
            db.rollback()
        except Exception:
            pass
        raise ValueError(
            f"canary reservation conflict for {bkt}/{key[-24:]}: "
            f"existing sha/size != claimed; refusing"
        )

    accounted = None
    try:
        accounted = canary_accounted_bytes(db)
    except (CanaryBudgetExceeded, ValueError):
        try:
            db.rollback()
        except Exception:
            pass
        raise
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise
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
        object_sha256=sha,
        size_bytes=int(size),
        bucket=bkt,
        object_key=key,
        environment=env,
        job_id=job_id,
        slot=slot,
        status="reserved",
    )
    db.add(row)
    try:
        db.commit()
    except OperationalError as exc:
        try:
            db.rollback()
        except Exception:
            pass
        if _missing_table(exc) or _missing_column(exc):
            raise _fail_missing_schema(exc) from exc
        raise
    return CANARY_BUDGET_BYTES - canary_accounted_bytes(db)


def canary_reserved_keys(db) -> set[tuple[str, str]]:
    """Distinct reserved (bucket, object_key) pairs (bounded). FAIL CLOSED.

    Legacy rows carry NULL bucket/object_key and are skipped (they still
    count in bytes via :func:`canary_reserved_bytes`). Any DB/schema
    error raises: an unverifiable exclusion set must refuse, never look
    empty (empty would over-count baseline -- safe direction -- but the
    authoritative path treats unknown as refusal for explicitness).
    """
    from sqlalchemy import func as _func

    from app.models.canary_ledger import CanarySlotReservation

    try:
        count = db.query(_func.count(CanarySlotReservation.id)).scalar()
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        if _is_missing_schema_error(exc):
            raise _missing_ledger_error() from exc
        raise
    if int(count or 0) > _CANARY_LEDGER_CAP_ROWS:
        raise CanaryBudgetExceeded("reservation ledger exceeds bounded scan; refusing")
    if int(count or 0) == 0:
        return set()
    try:
        rows = db.query(
            CanarySlotReservation.bucket, CanarySlotReservation.object_key
        ).limit(_CANARY_LEDGER_CAP_ROWS + 1).all()
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        if _is_missing_schema_error(exc):
            raise _missing_ledger_error() from exc
        raise
    if len(rows) > _CANARY_LEDGER_CAP_ROWS:
        raise CanaryBudgetExceeded("reservation ledger exceeds bounded scan; refusing")
    out: set[tuple[str, str]] = set()
    for bkt, key in rows:
        if bkt and key:
            out.add((str(bkt), str(key)))
    return out


def db_admitted_uuids(db, limit: int = 100) -> set[str]:
    """Distinct video_uuids with ANY web_package job (durable DB cohort). FAIL CLOSED.

    Bounded scan (canary fleet <= 30; cap is a safety rail -- exceeding
    it fails closed). Uses the DB, never the private state dir, so a
    reset state dir cannot bypass the total-30 cap. Any DB/schema error
    raises (never a false empty set that would bypass the total cap).
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
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        if _is_missing_schema_error(exc):
            raise CanaryBudgetExceeded(
                "web_package cohort unavailable (migrations missing); refusing"
            ) from exc
        raise
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
    """Phase-2 gate: EXACTLY 5 distinct phase-1 clips fully proven + durable totals.

    - ``phase1_cohort``: the EXACT 5 distinct expected phase-1 UUIDs
      (from ``--phase1-manifest``). A smaller first wave (<= 5) may run,
      but NEVER unlocks phase 2 -- phase 2 requires all 5 completed/proven.
    - Every phase-1 UUID must be in ``proven_uuids`` (explicit proof
      records, never auto-ready) AND durably admitted in the DB, plus a
      fresh stored-proof cross-check at the call site.
    - ``len(db_total_admitted) + new_count`` must stay <= 30 (DB is
      authoritative for the total; a reset state dir cannot bypass it).
    """
    if len(phase1_cohort) != CANARY_PHASE1_MAX_CLIPS:
        raise ValueError(
            f"phase 2 requires EXACTLY {CANARY_PHASE1_MAX_CLIPS} distinct phase-1 clips "
            f"(got {len(phase1_cohort)}); a smaller first wave never unlocks phase 2"
        )
    if len(set(phase1_cohort)) != CANARY_PHASE1_MAX_CLIPS:
        raise ValueError(
            f"phase 2 requires {CANARY_PHASE1_MAX_CLIPS} DISTINCT phase-1 clips "
            "(duplicate UUIDs refused)"
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
