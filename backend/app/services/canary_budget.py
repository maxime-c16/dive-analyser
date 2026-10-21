"""Bounded canary admission + publication budget preflight (D3b2 next slice).

Local-only, reviewable, no network/prod/B2. This module is the single
place that names the night-canary bounds so the ops tool, the slot
publish guard, and the tests share one contract:

- FIRST wave <= 5 clips; only on 100% proof may <= 25 more follow
  (fleet total <= 30).
- New B2 derivatives HARD cumulative <= 2 GiB (committed ledger bytes
  + the incoming slot under publish). Estimates are preflight ONLY and
  never promise the bound -- the bound is enforced server-side at
  publish time by ``check_publish_budget`` (authoritative), which the
  slot route calls with the claimed slot size BEFORE streaming bytes.
- ONE package job active fleet-wide (lease already enforces this; the
  tool additionally admits serially: at most one new queue per run,
  and never while an active package exists).
- Canary jobs never outrank interactive work: priority >= 60
  (numerically; lower = claimed first, interactive = 5/6/10).
- Stop admission on: Mac Data free < 8 GiB, server cache volume free
  < 25 GiB (operator-provided host facts -- this module never SSHes
  anywhere), repeated errors, or unknown source (dims/size/duration).

Explicit non-goals / residuals (fail closed, documented -- not hidden):

- B2 orphans from crashed attempts are retained by design (never
  deleted) and have NO ledger row, so they are invisible to
  ``canary_ledger_bytes``. The hard bound therefore covers COMMITTED
  bytes + the single in-flight slot; orphan waste is bounded
  procedurally instead: serial admission, max_attempts=2 per job,
  stop-on-error, and no re-admission while any package is active.
- The server stores coded dims only (no SAR/display-dims provenance,
  see PR143). Anamorphic SAR!=1 honest output fails the alias/exact
  check closed at publish (safe orphan, no promotion) but still spent
  uplink + orphan bytes. The tool mitigates by requiring dims-known
  sources and preferring phone-camera (SAR==1) clips; full
  display-dims provenance is a schema gap (see runbook).
- Frame counts are encoder-proven, never server-proven. The server
  proves container/codec/tags/faststart/decode-ability + exact dims;
  cadence proof is a post-publish verification step (runbook), not an
  admission claim.
"""

from __future__ import annotations

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
    """Enforce FIRST<=5, then <=25 additional (total<=30). Fail closed."""
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


def canary_ledger_bytes(db) -> int:
    """Committed canary-relevant derivative bytes (bounded aggregate, no rows).

    Sums ``MediaBlob.byte_size`` for DISTINCT derivative blobs referenced
    by ``media_derivatives`` rows with status ``ready``. Bounded: the
    ledger identity scan is capped (canary fleet is <= 90 slot rows; the
    cap is a safety rail, not a data window -- exceeding it fails closed
    by raising so growth can never silently slip past the budget).
    """
    from app.models.media_backbone import MediaBlob, MediaDerivative

    cap_rows = 5000
    sha_rows = (
        db.query(MediaDerivative.derivative_blob_sha256)
        .filter(MediaDerivative.status == "ready")
        .limit(cap_rows + 1)
        .all()
    )
    if len(sha_rows) > cap_rows:
        raise CanaryBudgetExceeded(
            f"derivative ledger exceeds bounded scan ({cap_rows} ready rows); "
            "refusing budget proof -- investigate before any canary"
        )
    shas = {str(r[0]).lower() for r in sha_rows if r and r[0]}
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


def remaining_budget_bytes(db) -> int:
    """Authoritative remaining bytes under the hard cap (may be <= 0)."""
    return CANARY_BUDGET_BYTES - canary_ledger_bytes(db)


def check_publish_budget(db, incoming_bytes: int) -> int:
    """Authoritative publish-time guard: refuse overshoot BEFORE bytes stream.

    Call with the slot's CLAIMED size (Form ``size_bytes``). Raises
    ``CanaryBudgetExceeded`` when committed + incoming would exceed
    2 GiB. Returns the remaining bytes after this slot (for logging/
    aggregate status -- never per-object keys). In-flight concurrency
    is bounded by the global one-package lease cap + serial admission,
    so at most one slot is checked at a time per fleet.
    """
    try:
        incoming = int(incoming_bytes)
    except (TypeError, ValueError):
        raise ValueError("slot size must be a positive int")
    if incoming <= 0:
        raise ValueError("slot size must be a positive int")
    committed = canary_ledger_bytes(db)
    if committed + incoming > CANARY_BUDGET_BYTES:
        raise CanaryBudgetExceeded(
            f"canary budget exceeded: committed {committed} + incoming {incoming} "
            f"> {CANARY_BUDGET_BYTES} (2 GiB hard cap)"
        )
    return CANARY_BUDGET_BYTES - (committed + incoming)
