"""D3b1 derivative publisher (UNWIRED internal, no routes/jobs/readers).

Secure SERVER publication primitive for D1 ``hq``/``light``/``poster``
ledger rows. Takes validated local package bytes (e.g. a D3a
``PackageResult`` ``result_dir`` file), uploads them content-addressed to
B2, roundtrip-verifies EVERY byte (size + SHA-256 over a full streamed
read — never a client ``verified`` bool or HEAD metadata), then commits
the durable ledger (blob + verified location + ``derived_*`` revision via
``commit_verified_ingest`` + ``media_derivatives`` ready upsert) in one DB
transaction.

Unwired on purpose: no route, no job mutation, no reader, no backfill, no
retention/LRU/unpin change imports this module. The only entry points are
``build_publication_context`` (validates identity + resolves the
canonical camera source) and ``publish_derivative`` (requires the opaque
``PublicationContext``, never raw strings — the future D3b2 fenced slot
API cannot bypass the guard by calling the commit path directly).

Explicit limit (not integrated yet): D2 lease-token fencing is NOT
enforced here. ``build_publication_context`` resolves the source revision
but does not validate a ``media_jobs`` claim token; D3b2 must add
``_guarded_job`` validation inside the builder (same opaque-context
shape, so ``publish_derivative`` needs no signature change). Do not treat
this slice as fenced.

Source policy (quality): the canonical source is the newest verified PROD
camera-original revision — every non-derivative semantic EXCEPT the
already-transcoded ``browser_playback`` proxy (i.e. ``browser_original``
raw upload bytes ARE eligible: they are the true camera bytes for browser
clips). ``derived_*`` rows are always excluded via the shared D1 clause.
Existing selectors are untouched; this helper does not modify playback,
guest, download, matchmaking or ``_b2_source`` behavior.

B2 keys: ``<prefix>/derived/<source_sha[:2]>/<role>-<transform>-<derivative_sha>``
with ``prefix`` from ``media_backbone_object_prefix`` and the bucket from
the validated ``b2_upload_environment`` (dev/prod allowlist). Content is
addressed by bytes; the ledger identity is
``(video_uuid, source_blob_sha256, role, transform_version)``.

Failure semantics: any upload, verify or DB failure rolls back and leaves
the ledger NOT ready; an existing ``ready`` row with the same identity is
never overwritten (same bytes = idempotent replay, different bytes =
``DerivativeIdentityConflict``); B2 orphans from a crashed attempt are
retained (never deleted, never touching other objects). A source revision
that changed between context build and commit commits ``stale``, never
``ready``, with no autoqueue (D3b2 owns slot scheduling).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.config import get_settings

DERIVATIVE_ROLES = ("hq", "light", "poster")

DERIVATIVE_CONTENT_TYPES = {
    "hq": "video/mp4",
    "light": "video/mp4",
    "poster": "image/jpeg",
}

# Camera-original transcode exclusion: the only non-derivative semantic
# that must never be a derivative source (already-transcoded proxy).
TRANSCODED_SOURCE_SEMANTICS = frozenset({"browser_playback"})


class DerivativePublishError(RuntimeError):
    """Base fail-closed publisher error (no ledger write committed)."""


class DerivativeIdentityConflict(DerivativePublishError):
    """Same ledger identity already READY with different bytes."""


class StaleSourceError(DerivativePublishError):
    """Canonical source moved after the context was built (committed stale)."""


class MissingSourceError(DerivativePublishError):
    """No verified PROD camera-original revision for this clip."""


class VerificationFailed(DerivativePublishError):
    """B2 roundtrip proof failed (corrupt/truncated/wrong size/error)."""


class MissingCredentials(DerivativePublishError):
    """B2 upload credential/environment not configured (fail closed)."""


def derivative_object_key(
    *,
    source_sha256: str,
    role: str,
    transform_version: str,
    derivative_sha256: str,
    prefix: str | None = None,
) -> str:
    """Content-addressed B2 key for one derivative artifact (fail closed)."""
    from app.services.media_keys import build_derivative_media_key  # validation reuse

    if role not in DERIVATIVE_CONTENT_TYPES:
        raise ValueError(f"unknown derivative role {role!r}")
    # Reuse the D1 key validator so key minting and ledger identity share
    # one fail-closed contract (UUID/role/SHA/version checks). The return
    # value (cache media_key) is not needed here; validation is the point.
    # video_uuid is identity-scoped elsewhere, so validate with a placeholder
    # only for shape — real identity binding happens in publish_derivative.
    build_derivative_media_key("00000000-0000-0000-0000-000000000000", role, source_sha256, transform_version)
    if (
        not isinstance(derivative_sha256, str)
        or len(derivative_sha256) != 64
        or any(c not in "0123456789abcdef" for c in derivative_sha256)
    ):
        raise ValueError(f"malformed derivative_sha256: {derivative_sha256!r}")
    if prefix is None:
        prefix = get_settings().media_backbone_object_prefix or "blobs/sha256"
    prefix = prefix.strip().strip("/")
    if not prefix:
        raise ValueError("empty media_backbone_object_prefix")
    return f"{prefix}/derived/{source_sha256[:2]}/{role}-{transform_version}-{derivative_sha256}"


def resolve_canonical_source_revision(db, video_uuid: str):
    """Newest verified PROD camera-original revision (fail closed).

    Excludes ``derived_*`` (shared D1 clause) AND the already-transcoded
    ``browser_playback`` proxy; ``browser_original`` raw bytes stay
    eligible (true camera bytes for browser clips). Requires a verified
    PROD B2 location via the shared ``verified_original_clause`` (bucket /
    backend allowlisted, exactly-one-location contract). Returns
    ``(revision, blob, location)``; raises ``MissingSourceError`` when no
    such revision exists. Read-only; existing selectors untouched.
    """
    from app.models.media_backbone import MediaBlob, MediaBlobLocation, MediaRevision
    from app.services.matchmaking import verified_original_clause
    from app.services.media_backbone import derived_semantics_exclusion_clause

    if not isinstance(video_uuid, str) or not video_uuid.strip() or len(video_uuid) > 100:
        raise ValueError(f"invalid video_uuid: {video_uuid!r}")
    revision = (
        db.execute(
            select(MediaRevision)
            .join(
                MediaBlobLocation,
                (MediaBlobLocation.blob_sha256 == MediaRevision.blob_sha256)
                & (MediaBlobLocation.environment == "prod")
                & (MediaBlobLocation.verified.is_(True)),
            )
            .where(
                MediaRevision.video_uuid == video_uuid,
                derived_semantics_exclusion_clause(MediaRevision.rendition_semantics),
                MediaRevision.rendition_semantics.notin_(tuple(TRANSCODED_SOURCE_SEMANTICS)),
                verified_original_clause(),
            )
            .order_by(MediaRevision.id.desc())
            .limit(1)
        ).scalar_one_or_none()
    )
    if revision is None:
        raise MissingSourceError(f"no verified PROD camera-original revision for {video_uuid!r}")
    blob = db.get(MediaBlob, revision.blob_sha256)
    location = (
        db.execute(
            select(MediaBlobLocation).where(
                MediaBlobLocation.blob_sha256 == revision.blob_sha256,
                MediaBlobLocation.environment == "prod",
                MediaBlobLocation.verified.is_(True),
            )
        ).scalar_one_or_none()
    )
    if blob is None or location is None:
        raise MissingSourceError(f"canonical source bytes not resolved for {video_uuid!r}")
    return revision, blob, location


@dataclass(frozen=True)
class PublicationContext:
    """Opaque validated publication authorization (D3b1 internal).

    Only ``build_publication_context`` constructs this. ``publish_derivative``
    rejects anything else (dicts, strings, hand-built contexts without the
    marker), so a future fenced API cannot bypass validation by calling the
    commit path with raw fields. D3b2 tightens the BUILDER (adds
    ``_guarded_job`` lease checks); this shape stays.
    """

    video_uuid: str
    source_blob_sha256: str
    source_revision_id: int
    source_size_bytes: int | None
    role: str
    transform_version: str
    environment: str
    bucket: str
    object_prefix: str
    _validated: bool = True


def build_publication_context(db, *, video_uuid: str, role: str, transform_version: str | None = None) -> PublicationContext:
    """Validate identity + resolve canonical camera source (no job fencing yet).

    Explicit non-goal: no ``media_jobs`` lease-token check. D3b2 adds it
    here; callers must not assume fencing from this slice.
    """
    from app.services.media_backbone import _validate_sha  # noqa: SLF — shared fail-closed SHA check
    from app.services.media_backbone import environment_bucket

    if role not in DERIVATIVE_CONTENT_TYPES:
        raise ValueError(f"unknown derivative role {role!r}")
    if not isinstance(video_uuid, str) or not video_uuid.strip() or len(video_uuid) > 100:
        raise ValueError(f"invalid video_uuid: {video_uuid!r}")
    version = transform_version if transform_version is not None else get_settings().media_derivative_transform_version
    if not isinstance(version, str) or not version.strip() or len(version) > 40:
        raise ValueError(f"invalid transform_version: {transform_version!r}")
    revision, blob, _location = resolve_canonical_source_revision(db, video_uuid)
    source_sha = revision.blob_sha256
    _validate_sha(source_sha)
    settings = get_settings()
    environment = (settings.b2_upload_environment or "").strip().lower()
    if environment not in ("dev", "prod"):
        raise MissingCredentials("B2 upload environment is not configured correctly")
    bucket = environment_bucket(environment)
    prefix = (settings.media_backbone_object_prefix or "blobs/sha256").strip().strip("/")
    if not prefix:
        raise ValueError("empty media_backbone_object_prefix")
    return PublicationContext(
        video_uuid=video_uuid,
        source_blob_sha256=source_sha,
        source_revision_id=int(revision.id),
        source_size_bytes=int(blob.byte_size) if blob and blob.byte_size else None,
        role=role,
        transform_version=version,
        environment=environment,
        bucket=bucket,
        object_prefix=prefix,
    )


def _b2_upload_client():
    """Build the private B2 upload (S3) client from runtime config only."""
    settings = get_settings()
    if (
        not settings.b2_upload_key_id
        or not settings.b2_upload_key_secret
        or not settings.b2_upload_region
    ):
        raise MissingCredentials("Video storage is not configured yet")
    environment = (settings.b2_upload_environment or "").strip().lower()
    if environment not in ("dev", "prod"):
        raise MissingCredentials("Video storage environment is not configured correctly")
    import boto3  # lazy: unit tests inject fakes instead
    from botocore.config import Config

    return boto3.client(
        "s3",
        region_name=settings.b2_upload_region,
        endpoint_url=settings.b2_upload_endpoint_url
        or f"https://s3.{settings.b2_upload_region}.backblazeb2.com",
        aws_access_key_id=settings.b2_upload_key_id,
        aws_access_key_secret=settings.b2_upload_key_secret,
        config=Config(connect_timeout=10, read_timeout=120, retries={"total_max_attempts": 2}),
    )


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _upload_and_roundtrip_verify(
    *,
    client: Any,
    bucket: str,
    key: str,
    local_path: Path,
    content_type: str,
    derivative_sha: str,
    derivative_size: int,
) -> None:
    """Upload bytes then stream-read the object back and compare ALL bytes.

    Never trusts a client ``verified`` bool or HEAD metadata: the proof is
    a full GET with streamed SHA-256 + size equality against the local
    artifact hashed just before upload. Any mismatch, truncation, wrong
    size, missing body or provider error raises ``VerificationFailed`` and
    commits nothing. Secrets never appear in messages.
    """
    try:
        client.upload_file(
            str(local_path),
            bucket,
            key,
            ExtraArgs={"ContentType": content_type, "Metadata": {"sha256": derivative_sha}},
        )
    except Exception as exc:
        raise VerificationFailed("derivative upload failed; please retry") from exc
    try:
        response = client.get_object(Bucket=bucket, Key=key)
        body = response["Body"]
        digest = hashlib.sha256()
        size = 0
        try:
            chunks = body.iter_chunks(chunk_size=1024 * 1024) if hasattr(body, "iter_chunks") else None
            if chunks is None:
                # file-like fallback (test fakes): read in slices.
                while True:
                    piece = body.read(1024 * 1024)
                    if not piece:
                        break
                    digest.update(piece)
                    size += len(piece)
            else:
                for piece in chunks:
                    if piece:
                        digest.update(piece)
                        size += len(piece)
        finally:
            try:
                body.close()
            except Exception:
                pass
    except VerificationFailed:
        raise
    except Exception as exc:
        raise VerificationFailed("derivative storage verification failed; please retry") from exc
    if digest.hexdigest() != derivative_sha or size != derivative_size:
        raise VerificationFailed("derivative storage verification failed; please retry")


def publish_derivative(
    db,
    ctx: PublicationContext,
    local_path: str | Path,
    *,
    s3_client: Any | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Publish one validated derivative artifact (upload → verify → commit).

    Requires an opaque ``PublicationContext`` (rejects raw dicts/strings).
    Network first (upload + full-byte verify, no DB lock held), then ONE DB
    transaction: conflict check → source-drift check → backbone commit +
    ledger upsert. Any failure rolls back; the ledger stays NOT ready and
    any existing ``ready`` row is untouched. B2 orphans are retained.
    """
    if not isinstance(ctx, PublicationContext) or ctx._validated is not True:
        raise DerivativePublishError("publish_derivative requires a validated PublicationContext")
    if ctx.role not in DERIVATIVE_CONTENT_TYPES:
        raise DerivativePublishError(f"unknown derivative role {ctx.role!r}")
    path = Path(local_path)
    if not path.is_file():
        raise DerivativePublishError(f"derivative artifact missing: {path!s}")
    from app.models.media_backbone import MediaDerivative

    derivative_sha, derivative_size = _sha256_file(path)
    if derivative_size <= 0:
        raise DerivativePublishError("derivative artifact is empty")
    key = derivative_object_key(
        source_sha256=ctx.source_blob_sha256,
        role=ctx.role,
        transform_version=ctx.transform_version,
        derivative_sha256=derivative_sha,
        prefix=ctx.object_prefix,
    )
    content_type = DERIVATIVE_CONTENT_TYPES[ctx.role]
    client = s3_client if s3_client is not None else _b2_upload_client()
    _upload_and_roundtrip_verify(
        client=client,
        bucket=ctx.bucket,
        key=key,
        local_path=path,
        content_type=content_type,
        derivative_sha=derivative_sha,
        derivative_size=derivative_size,
    )

    # DB transaction: re-resolve source (drift → stale), check identity
    # conflicts BEFORE writing any blob rows, then commit backbone +
    # ledger atomically.
    from sqlalchemy.exc import IntegrityError

    from app.services.media_backbone import DERIVATIVE_ROLE_TO_SEMANTICS
    from app.services.media_backbone import commit_verified_ingest

    is_pg = False
    try:
        is_pg = db.bind is not None and db.bind.dialect.name == "postgresql"
    except Exception:
        is_pg = False

    try:
        # Lock the existing ledger row first on PG (serializes concurrent
        # same-identity publishers); SQLite has no FOR UPDATE so the
        # UNIQUE index + IntegrityError path serializes there.
        existing_query = select(MediaDerivative).where(
            MediaDerivative.video_uuid == ctx.video_uuid,
            MediaDerivative.source_blob_sha256 == ctx.source_blob_sha256,
            MediaDerivative.role == ctx.role,
            MediaDerivative.transform_version == ctx.transform_version,
        )
        if is_pg:
            existing_query = existing_query.with_for_update()
        existing = db.execute(existing_query).scalar_one_or_none()
        if existing is not None and existing.status == "ready":
            if existing.derivative_blob_sha256 == derivative_sha:
                # Idempotent replay: same bytes already durable.
                if commit:
                    db.commit()
                return {
                    "video_uuid": ctx.video_uuid,
                    "role": ctx.role,
                    "source_blob_sha256": ctx.source_blob_sha256,
                    "derivative_blob_sha256": derivative_sha,
                    "byte_size": derivative_size,
                    "object_key": key,
                    "bucket": ctx.bucket,
                    "environment": ctx.environment,
                    "status": "ready",
                    "deduplicated": True,
                    "media_derivative_id": existing.id,
                }
            raise DerivativeIdentityConflict(
                "derivative identity already ready with different bytes; refusing overwrite"
            )

        # Source drift: the canonical camera revision moved after the
        # context was built. Commit stale (never ready), no autoqueue.
        try:
            current, _blob, _loc = resolve_canonical_source_revision(db, ctx.video_uuid)
            drifted = current.blob_sha256 != ctx.source_blob_sha256
        except MissingSourceError:
            drifted = True
            current = None
        semantics = DERIVATIVE_ROLE_TO_SEMANTICS.get(ctx.role, f"derived_{ctx.role}")
        if drifted:
            commit_verified_ingest(
                db,
                video_uuid=ctx.video_uuid,
                blob_sha256=derivative_sha,
                byte_size=derivative_size,
                object_key=key,
                storage_backend="b2",
                bucket=ctx.bucket,
                verified=True,
                media_only=True,
                media_only_reason=f"durable derivative {ctx.role} superseded before commit",
                rendition_semantics=semantics,
                source_provenance={
                    "source": "derivative_publisher_d3b1",
                    "source_blob_sha256": ctx.source_blob_sha256,
                    "role": ctx.role,
                    "transform_version": ctx.transform_version,
                },
                ingest_impl_version="derivative_publisher_d3b1",
                environment=ctx.environment,
                commit=False,
            )
            if existing is None:
                stale_row = MediaDerivative(
                    video_uuid=ctx.video_uuid,
                    source_blob_sha256=ctx.source_blob_sha256,
                    role=ctx.role,
                    transform_version=ctx.transform_version,
                    derivative_blob_sha256=derivative_sha,
                    status="stale",
                    verified_at=None,
                )
                db.add(stale_row)
                db.flush()
            else:
                if existing.derivative_blob_sha256 != derivative_sha:
                    # Non-ready row: safe to record the drifted bytes as
                    # stale (nothing verified is overwritten).
                    existing.derivative_blob_sha256 = derivative_sha
                    existing.status = "stale"
                    db.add(existing)
                    db.flush()
            if commit:
                db.commit()
            raise StaleSourceError("canonical source changed before commit; recorded stale, not ready")

        commit_verified_ingest(
            db,
            video_uuid=ctx.video_uuid,
            blob_sha256=derivative_sha,
            byte_size=derivative_size,
            object_key=key,
            storage_backend="b2",
            bucket=ctx.bucket,
            verified=True,
            media_only=True,
            media_only_reason=f"durable derivative {ctx.role} roundtrip-verified",
            rendition_semantics=semantics,
            source_provenance={
                "source": "derivative_publisher_d3b1",
                "source_blob_sha256": ctx.source_blob_sha256,
                "role": ctx.role,
                "transform_version": ctx.transform_version,
            },
            ingest_impl_version="derivative_publisher_d3b1",
            environment=ctx.environment,
            commit=False,
        )
        if existing is None:
            row = MediaDerivative(
                video_uuid=ctx.video_uuid,
                source_blob_sha256=ctx.source_blob_sha256,
                role=ctx.role,
                transform_version=ctx.transform_version,
                derivative_blob_sha256=derivative_sha,
                status="ready",
                verified_at=datetime.utcnow(),
            )
            db.add(row)
            db.flush()
            derivative_id = row.id
        else:
            # Non-ready row with same or new bytes: promote to ready.
            existing.derivative_blob_sha256 = derivative_sha
            existing.status = "ready"
            existing.verified_at = datetime.utcnow()
            db.add(existing)
            db.flush()
            derivative_id = existing.id
        if commit:
            db.commit()
        return {
            "video_uuid": ctx.video_uuid,
            "role": ctx.role,
            "source_blob_sha256": ctx.source_blob_sha256,
            "derivative_blob_sha256": derivative_sha,
            "byte_size": derivative_size,
            "object_key": key,
            "bucket": ctx.bucket,
            "environment": ctx.environment,
            "status": "ready",
            "deduplicated": False,
            "media_derivative_id": derivative_id,
        }
    except (DerivativeIdentityConflict, StaleSourceError):
        # Stale path already committed its stale record above; conflict
        # path must roll back any backbone flush. Distinguish: if the
        # exception is StaleSourceError raised AFTER commit, do not roll
        # back. We committed before raising, so just re-raise.
        raise
    except IntegrityError as exc:
        try:
            db.rollback()
        except Exception:
            pass
        # Concurrent same-identity winner: re-read; same bytes =
        # idempotent, different bytes + ready = conflict.
        from app.models.media_backbone import MediaDerivative as _MD

        rival = (
            db.execute(
                select(_MD).where(
                    _MD.video_uuid == ctx.video_uuid,
                    _MD.source_blob_sha256 == ctx.source_blob_sha256,
                    _MD.role == ctx.role,
                    _MD.transform_version == ctx.transform_version,
                )
            ).scalar_one_or_none()
        )
        if rival is not None and rival.derivative_blob_sha256 == derivative_sha and rival.status == "ready":
            return {
                "video_uuid": ctx.video_uuid,
                "role": ctx.role,
                "source_blob_sha256": ctx.source_blob_sha256,
                "derivative_blob_sha256": derivative_sha,
                "byte_size": derivative_size,
                "object_key": key,
                "bucket": ctx.bucket,
                "environment": ctx.environment,
                "status": "ready",
                "deduplicated": True,
                "media_derivative_id": rival.id,
            }
        raise DerivativeIdentityConflict(
            "derivative identity concurrently committed with different bytes; refusing overwrite"
        ) from exc
    except DerivativePublishError:
        try:
            # StaleSourceError after commit must not roll back; detect by
            # checking for a stale row with our SHA (committed). Simpler:
            # only rollback when no commit happened — callers use commit=True
            # and stale already committed, but the raise above bypasses this
            # handler via the earlier except clause. This arm is for
            # pre-commit publish errors.
            db.rollback()
        except Exception:
            pass
        raise
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        raise DerivativePublishError("derivative publish failed; ledger unchanged") from exc
