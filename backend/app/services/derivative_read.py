"""D5 shared durable-derivative read contract (read-only).

Single backend selector for the durable ``hq`` / ``light`` / ``poster``
web renditions. Every consumer (Library status + player, evaluation
status) derives its derivative URLs from here instead of local
precedence hacks.

Selection rules (fail closed, never a "ready" lie):

* ONLY a ``media_derivatives`` row with ``status == 'ready'`` whose
  ``(video_uuid, source_blob_sha256, role, transform_version)`` matches
  the clip's CURRENT canonical camera-original source revision AND the
  current ``MEDIA_DERIVATIVE_TRANSFORM_VERSION`` is servable. Any other
  row state (``verifying`` / ``stale`` / ``superseded`` / absent) is
  reported honestly and yields NO playback URL.
* The derivative bytes must have EXACTLY ONE verified location in the
  serving environment's allowlisted bucket (PROD by default). Zero
  locations, several locations, a non-B2 backend or a wrong bucket all
  report ``unavailable`` — DEV-only publishes never count as ready.
* NO fallback to an arbitrary newest-original or newest-derivative row:
  a ready derivative of an OLD source is ``stale`` data once the source
  moves, never served as current.
* Small-source HQ alias: when no distinct HQ was encoded (source short
  side below the HQ floor) the HQ choice resolves to the durable light
  proof and reports ``aliased_to == 'light'``. Unknown source dims
  refuse the alias fail-closed (HQ stays missing).
* Read-only: no jobs, no conversions, no cache/ledger writes, no
  backfill. Playback URLs are the EXISTING revision-bound grant route
  (``GET /api/v1/media/revisions/{id}/play``); authZ, presign TTL,
  grant ledger and no-store 302 semantics are that route's, unchanged.

Poster uses the same revision route (302 to a presigned B2 JPEG); grid
tiles intentionally stay local-only (batch endpoint unchanged) so a
scroll mints no grants.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.config import get_settings

DERIVATIVE_ROLES = ("hq", "light", "poster")

# Source short side below this floor means the encoder never produced a
# distinct HQ (no upscale); the HQ choice aliases the durable light proof.
HQ_SHORT_SIDE_FLOOR = 1080

# States with a playback_url: only "ready" (distinct bytes or an honest
# light alias). Every other state is reported without a URL.
SERVABLE_STATES = frozenset({"ready"})


@dataclass(frozen=True)
class DerivativeDecision:
    """One role's honest read state for the current source + transform."""

    role: str
    state: str  # ready|aliased-missing... see below
    revision_id: Optional[int] = None
    playback_url: Optional[str] = None
    derivative_id: Optional[int] = None
    source_revision_id: Optional[int] = None
    aliased_to: Optional[str] = None
    # Machine reason for non-servable states (missing|preparing|stale|
    # superseded|unavailable|no-source). Never user-facing verbatim.
    reason: Optional[str] = None


@dataclass(frozen=True)
class ClipDerivatives:
    """Whole-clip derivative read for one canonical source + transform."""

    video_uuid: str
    source_revision_id: Optional[int] = None
    source_sha256: Optional[str] = None
    transform_version: Optional[str] = None
    roles: dict = field(default_factory=dict)
    # Honest choice hints. `start` is the default starter (light for a
    # fast first frame); `recommended` the explicit quality pick.
    start: Optional[str] = None
    recommended: Optional[str] = None

    def to_status_payload(self) -> dict[str, Any]:
        return {
            "source_revision_id": self.source_revision_id,
            "transform_version": self.transform_version,
            "start": self.start,
            "recommended": self.recommended,
            "hq": _role_payload(self.roles.get("hq")),
            "light": _role_payload(self.roles.get("light")),
            "poster": _role_payload(self.roles.get("poster")),
        }


def _role_payload(decision: Optional[DerivativeDecision]) -> dict[str, Any]:
    if decision is None:
        return {"state": "missing", "playback_url": None, "revision_id": None, "aliased_to": None}
    return {
        "state": decision.state,
        "playback_url": decision.playback_url,
        "revision_id": decision.revision_id,
        "aliased_to": decision.aliased_to,
    }


def _current_transform_version(explicit: Optional[str] = None) -> str:
    if explicit:
        return explicit
    return get_settings().media_derivative_transform_version


def _verified_prod_location(db: Session, derivative_sha: str, environment: str):
    """Exactly-one verified replica in the allowlisted bucket, or a reason.

    Mirrors the playback route's storage authority: zero verified
    locations, several, or a non-B2 / wrong-bucket single are all
    fail-closed (never served as ready).
    """
    from app.models.media_backbone import MediaBlobLocation

    settings = get_settings()
    expected_bucket = (
        settings.media_backbone_prod_bucket if environment == "prod" else settings.media_backbone_dev_bucket
    )
    locations = (
        db.query(MediaBlobLocation)
        .filter_by(blob_sha256=derivative_sha, environment=environment, verified=True)
        # Bounded probe: 0 -> missing, 1 -> candidate, >= 2 -> ambiguous.
        # We only need to distinguish 0/1/many, never the full replica set.
        .limit(2)
        .all()
    )
    if len(locations) == 0:
        return None, "no_verified_location"
    if len(locations) > 1:
        return None, "ambiguous_location"
    location = locations[0]
    if (location.storage_backend or "").lower() != "b2" or (location.bucket or "").strip().lower() != (
        expected_bucket or ""
    ).strip().lower():
        return None, "untrusted_location"
    if not (location.object_key or ""):
        return None, "empty_object_key"
    return location, None


def _derived_revision(db: Session, video_uuid: str, derivative_sha: str, role: str):
    """Backbone revision carrying this derivative's bytes, or None."""
    from app.models.media_backbone import MediaRevision
    from app.services.media_backbone import DERIVATIVE_ROLE_TO_SEMANTICS

    semantics = DERIVATIVE_ROLE_TO_SEMANTICS.get(role, f"derived_{role}")
    return (
        db.query(MediaRevision)
        .filter(
            MediaRevision.video_uuid == video_uuid,
            MediaRevision.blob_sha256 == derivative_sha,
            MediaRevision.rendition_semantics == semantics,
        )
        .order_by(MediaRevision.id.desc())
        .first()
    )


def _short_side(blob) -> Optional[int]:
    try:
        width = int(blob.width) if blob.width is not None else None
        height = int(blob.height) if blob.height is not None else None
    except (TypeError, ValueError):
        return None
    if not width or not height or width <= 0 or height <= 0:
        return None
    return min(width, height)


def resolve_clip_derivatives(
    db: Session,
    video_uuid: str,
    *,
    transform_version: Optional[str] = None,
    environment: str = "prod",
) -> ClipDerivatives:
    """Resolve the servable durable derivatives for one clip (read-only)."""
    from app.models.media_backbone import MediaDerivative
    from app.services.derivative_publisher import MissingSourceError, resolve_canonical_source_revision

    version = _current_transform_version(transform_version)
    try:
        source_revision, source_blob, _source_location = resolve_canonical_source_revision(db, video_uuid)
    except MissingSourceError:
        missing = {
            role: DerivativeDecision(role=role, state="missing", reason="no_canonical_source")
            for role in DERIVATIVE_ROLES
        }
        return ClipDerivatives(
            video_uuid=video_uuid,
            transform_version=version,
            roles=missing,
            start=None,
            recommended=None,
        )
    except ValueError:
        missing = {
            role: DerivativeDecision(role=role, state="missing", reason="invalid_video_uuid")
            for role in DERIVATIVE_ROLES
        }
        return ClipDerivatives(
            video_uuid=video_uuid,
            transform_version=version,
            roles=missing,
            start=None,
            recommended=None,
        )

    source_sha = source_revision.blob_sha256
    source_revision_id = int(source_revision.id)
    short_side = _short_side(source_blob)

    decisions: dict[str, DerivativeDecision] = {}
    for role in DERIVATIVE_ROLES:
        row = (
            db.query(MediaDerivative)
            .filter(
                MediaDerivative.video_uuid == video_uuid,
                MediaDerivative.source_blob_sha256 == source_sha,
                MediaDerivative.role == role,
                MediaDerivative.transform_version == version,
            )
            .order_by(MediaDerivative.id.desc())
            .first()
        )
        if row is None:
            decisions[role] = DerivativeDecision(
                role=role,
                state="missing",
                source_revision_id=source_revision_id,
                reason="no_derivative_row",
            )
            continue
        if row.status != "ready":
            state = {
                "verifying": "preparing",
                "stale": "stale",
                "superseded": "superseded",
            }.get(row.status, "unavailable")
            decisions[role] = DerivativeDecision(
                role=role,
                state=state,
                derivative_id=row.id,
                source_revision_id=source_revision_id,
                reason=f"ledger_{row.status}",
            )
            continue
        revision = _derived_revision(db, video_uuid, row.derivative_blob_sha256, role)
        if revision is None:
            decisions[role] = DerivativeDecision(
                role=role,
                state="unavailable",
                derivative_id=row.id,
                source_revision_id=source_revision_id,
                reason="ledger_ready_without_backbone_revision",
            )
            continue
        _location, deny = _verified_prod_location(db, row.derivative_blob_sha256, environment)
        if deny is not None:
            decisions[role] = DerivativeDecision(
                role=role,
                state="unavailable",
                derivative_id=row.id,
                source_revision_id=source_revision_id,
                reason=deny,
            )
            continue
        decisions[role] = DerivativeDecision(
            role=role,
            state="ready",
            revision_id=int(revision.id),
            playback_url=f"/api/v1/media/revisions/{int(revision.id)}/play",
            derivative_id=row.id,
            source_revision_id=source_revision_id,
        )

    # Small-source HQ alias: ONLY when the producer never recorded a
    # distinct HQ for this source + transform (no ledger row at all) and
    # the coded short side is below the floor does the HQ choice resolve
    # to the durable light proof. A recorded HQ row that is not servable
    # (stale/superseded/verifying/unavailable) is NEVER aliased: it proves
    # a distinct HQ was attempted, so serving light as HQ would hide the
    # honest ledger state (and the coded-dims inference is unreliable for
    # anamorphic SAR-adjusted or rotated sources — the encoder plans from
    # SAR-adjusted display dims, see PR143 SAR!=1 residual). Unknown dims
    # refuse the alias fail-closed.
    hq = decisions["hq"]
    light = decisions["light"]
    if hq.reason == "no_derivative_row" and light.state == "ready":
        if short_side is not None and short_side < HQ_SHORT_SIDE_FLOOR:
            decisions["hq"] = DerivativeDecision(
                role="hq",
                state="ready",
                revision_id=light.revision_id,
                playback_url=light.playback_url,
                derivative_id=light.derivative_id,
                source_revision_id=source_revision_id,
                aliased_to="light",
            )

    hq_ready = decisions["hq"].state == "ready"
    light_ready = decisions["light"].state == "ready"
    if light_ready:
        start, recommended = "light", ("hq" if hq_ready else "light")
    elif hq_ready:
        start, recommended = "hq", "hq"
    else:
        start, recommended = "original", "original"

    return ClipDerivatives(
        video_uuid=video_uuid,
        source_revision_id=source_revision_id,
        source_sha256=source_sha,
        transform_version=version,
        roles=decisions,
        start=start,
        recommended=recommended,
    )


def _is_missing_ledger_table(exc: BaseException) -> bool:
    """Whether this DB error is the absent pre-D1 derivative ledger.

    SQLite reports ``no such table: media_derivatives`` (OperationalError);
    Postgres reports undefined-table ``42P01`` ... does not exist
    (ProgrammingError). Anything else — a dead connection, a bad row, a
    bug — is NOT an old schema and must propagate.
    """
    orig = getattr(exc, "orig", None)
    if orig is not None:
        if getattr(orig, "pgcode", None) == "42P01":
            return True
        text = str(orig).lower()
        if "media_derivatives" in text and (
            "does not exist" in text or "no such table" in text or "undefined" in text
        ):
            return True
    text = str(exc).lower()
    return "media_derivatives" in text and (
        "no such table" in text or "does not exist" in text or "undefined" in text
    )


def safe_resolve_clip_derivatives(
    db: Session,
    video_uuid: str,
    *,
    transform_version: Optional[str] = None,
    environment: str = "prod",
) -> Optional[ClipDerivatives]:
    """Old-schema-tolerant wrapper around :func:`resolve_clip_derivatives`.

    Returns ``None`` ONLY when the derivative ledger table itself is
    absent (pre-D1 database): legacy status keeps serving, derivatives
    stay undisclosed. Any other DB error propagates — unrelated failures
    must never masquerade as "no derivatives".

    The probe runs in a SAVEPOINT so the aborted statement does not leave
    the caller's transaction broken (on Postgres a failed statement
    poisons the whole transaction until rollback; without the savepoint
    every legacy query after the probe would fail).
    """
    from sqlalchemy.exc import OperationalError, ProgrammingError

    savepoint = db.begin_nested()
    try:
        clip = resolve_clip_derivatives(
            db, video_uuid, transform_version=transform_version, environment=environment
        )
    except (OperationalError, ProgrammingError) as exc:
        savepoint.rollback()
        if _is_missing_ledger_table(exc):
            return None
        raise
    else:
        savepoint.commit()
        return clip
