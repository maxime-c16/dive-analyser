"""Media backbone commit service.

The single write path for verified object-store ingest: idempotent inserts of
content-addressed blobs, physical storage locations, media revisions and
caption revisions. Re-calling with the same content returns the existing rows
(no duplicates). No endpoint is wired in this packet; the P2 canary will call
this.

STORAGE AUTHORITY (P4.3): content dedupe and storage-location dedupe are
SEPARATE operations.

- get_or_create MediaBlob by SHA            → content identity
- get_or_create MediaBlobLocation by
  (blob SHA, environment, backend, bucket, object_key) → physical replica

Consequences, all tested:
- repeated identical commit in one environment  → 0 duplicate rows
- DEV → PROD commit of the same SHA            → 0 duplicate blobs
                                                  + 1 new PROD location
- same location key with a conflicting SHA     → rejected (fail closed)
- environment → bucket mismatch                → rejected (fail closed)

P5 lookup precondition: `resolve_verified_location` gives the deterministic
verified physical location of a blob in a given environment.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models.media_backbone import (
    CaptionRevision,
    IngestObjectState,
    MediaBlob,
    MediaBlobLocation,
    MediaRevision,
)

RENDITION_SEMANTICS_DEFAULT = "photos_edited_rendition"
CAPTION_HASH_ENCODING = "utf-8"
SUPPORTED_ENVIRONMENTS = ("dev", "prod")

# D1 durable derivatives (HQ/light/poster): rendition semantics for ledger
# rows committed through `commit_verified_ingest`, and the derivation roles
# they map from. All derivative semantics share the `derived_` prefix; the
# shared original-selector policy excludes that prefix (never an allowlist
# of camera originals, which differs per selector — see below).
DERIVED_RENDITION_SEMANTICS = ("derived_hq", "derived_light", "derived_poster")

DERIVATIVE_ROLES = ("hq", "light", "poster")

DERIVATIVE_ROLE_TO_SEMANTICS = {
    "hq": "derived_hq",
    "light": "derived_light",
    "poster": "derived_poster",
}

DERIVATIVE_STATUSES = ("verifying", "ready", "stale", "superseded")


def is_derived_rendition_semantics(value: str | None) -> bool:
    """Python-side check: is this rendition semantics a durable derivative?"""
    return isinstance(value, str) and value.startswith("derived_")


def derived_semantics_exclusion_clause(column):
    """SQLAlchemy clause excluding durable-derivative rendition semantics.

    Prefix-based (not an explicit triple) so a future role added under the
    same `derived_` convention is excluded automatically. Applied ON TOP of
    each selector's existing filter: selectors that already exclude
    `browser_original` keep that exclusion; selectors that serve the newest
    revision regardless keep that behavior for every non-derivative row.
    With no `derived_*` rows present (the whole of D1), the clause is a
    strict no-op.
    """
    return column.notlike(r"derived\_%", escape="\\")


def newest_original_revision(db: Session, video_uuid: str) -> MediaRevision | None:
    """Newest non-derivative revision for one clip (guest/download pick).

    Shared helper behind the guest-stream and download endpoints: newest
    revision by (observed_at DESC, id DESC) with the D1
    `derived_semantics_exclusion_clause` applied on top of the legacy
    newest-first behavior. With no `derived_*` rows this is exactly the
    pre-D1 pick; once derivatives exist they are skipped so guest/download
    stay the camera original (including `browser_original` when it is
    newest — the true camera bytes for browser clips).
    """
    return (
        db.query(MediaRevision)
        .filter(
            MediaRevision.video_uuid == video_uuid,
            derived_semantics_exclusion_clause(MediaRevision.rendition_semantics),
        )
        .order_by(MediaRevision.observed_at.desc(), MediaRevision.id.desc())
        .first()
    )


def caption_sha256(persisted_raw: str) -> str:
    """SHA-256 over the exact persisted caption representation (UTF-8 bytes).

    No normalization of any kind is applied before hashing.
    """
    import hashlib

    return hashlib.sha256(persisted_raw.encode(CAPTION_HASH_ENCODING)).hexdigest()


def _validate_sha(sha: str) -> str:
    if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise ValueError(f"malformed sha256: {sha!r}")
    return sha


def _validate_environment(environment: str) -> str:
    if environment not in SUPPORTED_ENVIRONMENTS:
        raise ValueError(f"unsupported environment: {environment!r}")
    return environment


def environment_bucket(environment: str) -> str:
    """Allowlisted physical bucket for a commit environment (fail closed).

    ENVIRONMENT AUTHORITY: the environment belongs to the physical
    storage/commit context. environment=dev commits may only reference the
    DEV bucket; environment=prod only the PROD bucket; anything else is a
    422-grade ValueError at the service boundary.
    """
    from app.config import get_settings

    settings = get_settings()
    bucket = (
        settings.media_backbone_prod_bucket
        if environment == "prod"
        else settings.media_backbone_dev_bucket
    ) or ""
    bucket = bucket.strip().lower()
    if not bucket:
        raise ValueError(
            f"environment {environment!r} has no allowlisted bucket configured"
        )
    return bucket


def _validate_location(
    *,
    environment: str,
    storage_backend: str,
    bucket: str,
    object_key: str,
) -> tuple[str, str, str]:
    _validate_environment(environment)
    if not storage_backend:
        raise ValueError("missing storage_backend")
    bucket = (bucket or "").strip().lower()
    if not bucket:
        raise ValueError("missing bucket")
    if not object_key:
        raise ValueError("missing object_key")
    expected_bucket = environment_bucket(environment)
    if bucket != expected_bucket:
        raise ValueError(
            f"environment {environment!r} must reference the {expected_bucket!r} "
            f"bucket, got {bucket!r}"
        )
    return storage_backend, bucket, object_key


def _get_or_create_location(
    db: Session,
    *,
    blob_sha256: str,
    environment: str,
    storage_backend: str,
    bucket: str,
    object_key: str,
    remote_object_id: str | None = None,
    verified: bool = True,
    verified_at: datetime | None = None,
) -> tuple[MediaBlobLocation, bool]:
    """get_or_create one physical storage replica for a content blob.

    Idempotent on the full replica identity; rejects a location key that is
    already bound to a DIFFERENT content SHA (fail closed, never overwrite).
    """
    _validate_sha(blob_sha256)
    backend, bucket, object_key = _validate_location(
        environment=environment,
        storage_backend=storage_backend,
        bucket=bucket,
        object_key=object_key,
    )
    location = (
        db.query(MediaBlobLocation)
        .filter_by(
            storage_backend=backend,
            bucket=bucket,
            object_key=object_key,
        )
        .one_or_none()
    )
    if location is not None:
        if location.blob_sha256 != blob_sha256:
            raise ValueError(
                f"object key {object_key!r} in {bucket!r} is already bound to "
                f"blob {location.blob_sha256!r}; refusing conflicting SHA "
                f"{blob_sha256!r}"
            )
        return location, True
    location = MediaBlobLocation(
        blob_sha256=blob_sha256,
        environment=environment,
        storage_backend=backend,
        bucket=bucket,
        object_key=object_key,
        remote_object_id=remote_object_id,
        verified=verified,
        verified_at=verified_at or (datetime.utcnow() if verified else None),
    )
    db.add(location)
    return location, False


def resolve_verified_location(
    db: Session, blob_sha256: str, environment: str
) -> MediaBlobLocation | None:
    """P5 storage-location lookup: verified replica of a blob in an environment.

    Deterministic: environment and bucket are allowlist-bound, so the
    (blob SHA, environment) pair yields exactly one verified location in the
    accepted deployment model; if a future deployment ever holds several
    verified replicas of one blob inside one environment, the newest
    verified one wins deterministically (verified_at DESC, id DESC).
    Locations with verified=False are NEVER returned (not playback-eligible).
    """
    _validate_sha(blob_sha256)
    _validate_environment(environment)
    return (
        db.query(MediaBlobLocation)
        .filter_by(blob_sha256=blob_sha256, environment=environment, verified=True)
        .order_by(MediaBlobLocation.verified_at.desc(), MediaBlobLocation.id.desc())
        .first()
    )


def resolve_media_revision_location(
    db: Session, video_uuid: str, environment: str
) -> MediaBlobLocation | None:
    """P5 lookup: "where is the verified PROD object for this MediaRevision?".

    media_revisions carry the logical clip revision (content, not location);
    the blob's physical replica is resolved through content identity only.
    """
    revision = (
        db.query(MediaRevision)
        .filter_by(video_uuid=video_uuid)
        .order_by(MediaRevision.id.desc())
        .first()
    )
    if revision is None:
        return None
    return resolve_verified_location(db, revision.blob_sha256, environment)


def commit_verified_ingest(
    db: Session,
    *,
    video_uuid: str,
    blob_sha256: str,
    byte_size: int,
    object_key: str,
    storage_backend: str,
    bucket: str,
    caption_raw: str | None = None,
    caption_sha: str | None = None,
    caption_provider: str | None = None,
    verified: bool = True,
    media_only: bool = False,
    media_only_reason: str | None = None,
    rendition_semantics: str = RENDITION_SEMANTICS_DEFAULT,
    codec: str | None = None,
    width: int | None = None,
    height: int | None = None,
    duration_seconds: float | None = None,
    photos_edit_fingerprint: str | None = None,
    source_provenance: dict[str, Any] | None = None,
    shadow_provider: str | None = None,
    shadow_raw: str | None = None,
    shadow_sha256: str | None = None,
    shadow_available: bool | None = None,
    parser_version: str | None = None,
    parsed_json: dict[str, Any] | None = None,
    ingest_impl_version: str = "media_backbone_v1",
    environment: str = "dev",
    commit: bool = True,
) -> dict[str, Any]:
    if not verified:
        raise ValueError("refusing to commit unverified ingest (roundtrip verification required)")
    _validate_sha(blob_sha256)
    if media_only:
        # P10 media-only mode: verified media bytes + truthful MediaRevision
        # baseline WITHOUT a fabricated CaptionRevision. The caption authority
        # is explicitly unresolved; the ledger records
        # MEDIA_VERIFIED_METADATA_PENDING so the residual stays visible and
        # repairable without re-downloading media bytes.
        if not media_only_reason or not media_only_reason.strip():
            raise ValueError(
                "media_only commit requires a non-empty media_only_reason"
            )
        if caption_raw is not None or caption_sha is not None or caption_provider is not None:
            raise ValueError(
                "media_only commit must not carry caption data"
            )
    else:
        if caption_raw is None or caption_sha is None or caption_provider is None:
            raise ValueError(
                "caption authority required unless media_only mode is declared"
            )
        _validate_sha(caption_sha)
        if caption_sha != caption_sha256(caption_raw):
            raise ValueError(
                "caption_sha256 does not match the persisted caption_raw UTF-8 bytes"
            )
    if byte_size <= 0:
        raise ValueError(f"invalid byte_size: {byte_size}")
    _validate_environment(environment)

    blob = db.get(MediaBlob, blob_sha256)
    blob_existed = blob is not None
    if blob is None:
        blob = MediaBlob(
            sha256=blob_sha256,
            byte_size=byte_size,
            codec=codec,
            width=width,
            height=height,
            duration_seconds=(
                Decimal(str(duration_seconds)) if duration_seconds is not None else None
            ),
            rendition_semantics=rendition_semantics,
            # Transitional first-seen location fields (non-authoritative).
            storage_backend=storage_backend,
            bucket=bucket,
            object_key=object_key,
            ingest_impl_version=ingest_impl_version,
        )
        db.add(blob)

    # Storage-location dedupe is separate from content dedupe (P4.3): a blob
    # that already exists still gains its physical replica for THIS
    # environment if it does not have one yet (e.g. same SHA previously
    # committed in DEV now verified in PROD). Legacy location columns on the
    # content row are intentionally left untouched.
    location, location_existed = _get_or_create_location(
        db,
        blob_sha256=blob_sha256,
        environment=environment,
        storage_backend=storage_backend,
        bucket=bucket,
        object_key=object_key,
        verified=True,
    )

    media_revision = (
        db.query(MediaRevision)
        .filter_by(video_uuid=video_uuid, blob_sha256=blob_sha256)
        .one_or_none()
    )
    media_revision_existed = media_revision is not None
    if media_revision is None:
        media_revision = MediaRevision(
            video_uuid=video_uuid,
            blob_sha256=blob_sha256,
            photos_edit_fingerprint=photos_edit_fingerprint,
            rendition_semantics=rendition_semantics,
            source_provenance=dict(source_provenance or {}),
            observed_at=datetime.utcnow(),
        )
        db.add(media_revision)

    caption_revision_existed = False
    caption_revision_id: int | None = None
    caption_revision: CaptionRevision | None = None
    if not media_only:
        caption_revision = (
            db.query(CaptionRevision)
            .filter_by(video_uuid=video_uuid, caption_sha256=caption_sha)
            .one_or_none()
        )
        caption_revision_existed = caption_revision is not None
        if caption_revision is None:
            caption_revision = CaptionRevision(
                video_uuid=video_uuid,
                caption_raw=caption_raw,
                caption_sha256=caption_sha,
                caption_provider=caption_provider,
                parser_version=parser_version,
                parsed_json=dict(parsed_json) if parsed_json else None,
                shadow_provider=shadow_provider,
                shadow_raw=shadow_raw,
                shadow_sha256=shadow_sha256,
                shadow_available=shadow_available,
                exact_equal=(
                    (shadow_sha256 == caption_sha)
                    if (shadow_available and shadow_sha256)
                    else None
                ),
                observed_at=datetime.utcnow(),
            )
            db.add(caption_revision)

    # Ledger identity is (video_uuid, environment, object_key): the same
    # content-addressed key committed in DEV and PROD is two logical ingest
    # events (P4.3), not one.
    ledger_state = "DB_COMMITTED" if not media_only else "MEDIA_VERIFIED_METADATA_PENDING"
    state = (
        db.query(IngestObjectState)
        .filter_by(video_uuid=video_uuid, environment=environment, object_key=object_key)
        .one_or_none()
    )
    if state is None:
        state = IngestObjectState(
            video_uuid=video_uuid,
            object_key=object_key,
            state=ledger_state,
            blob_sha256=blob_sha256,
            caption_sha256=caption_sha,
            verified=verified,
            db_committed_at=datetime.utcnow(),
            environment=environment,
            storage_backend=storage_backend,
        )
        db.add(state)
    elif media_only and state.state == "DB_COMMITTED" and state.caption_sha256 is None:
        # Upgrade a prior media-only record whose caption authority later
        # resolved through a separate caption path; never downgrade.
        pass

    if commit:
        db.commit()
    else:
        db.flush()
    return {
        "video_uuid": video_uuid,
        "blob_sha256": blob.sha256,
        "blob_existed": blob_existed,
        "media_blob_location_id": location.id,
        "blob_location_existed": location_existed,
        "environment": environment,
        "media_revision_id": media_revision.id,
        "media_revision_existed": media_revision_existed,
        "caption_revision_id": (
            caption_revision.id if caption_revision is not None else None
        ),
        "caption_revision_existed": caption_revision_existed,
        "media_only": bool(media_only),
        "ingest_state_id": state.id,
        "ledger_state": ledger_state,
    }


TRUSTED_REPLICA_PROBE = 8


def trusted_prod_location(db: Session, blob_sha256: str, bucket: str, environment: str = "prod"):
    """The verified B2 replica (PROD by default) to serve for a blob, or (None, reason).

    Identical bytes may live under several verified keys (the publisher
    keys derivatives per source, so two clips with a byte-identical poster
    own one blob with two replicas). Every replica was full-GET verified
    against the same SHA, so they are interchangeable: serve the oldest
    one deterministically. Fail closed when ANY verified PROD replica is
    outside the allowlisted B2 bucket or has no key, or when the replica
    set exceeds the bounded probe.
    """
    locations = (
        db.query(MediaBlobLocation)
        .filter_by(blob_sha256=blob_sha256, environment=environment, verified=True)
        .order_by(MediaBlobLocation.id.asc())
        .limit(TRUSTED_REPLICA_PROBE + 1)
        .all()
    )
    if not locations:
        return None, "not_found"
    if len(locations) > TRUSTED_REPLICA_PROBE:
        return None, "ambiguous"
    expected = (bucket or "").strip().lower()
    for location in locations:
        # A lone bad replica is plain untrusted; one among several makes
        # the set ambiguous (callers then refuse any fallback too).
        if (location.storage_backend or "").lower() != "b2" or (location.bucket or "").strip().lower() != expected:
            return None, "ambiguous" if len(locations) > 1 else "untrusted"
        if not (location.object_key or ""):
            return None, "ambiguous" if len(locations) > 1 else "empty_object_key"
    return locations[0], None
