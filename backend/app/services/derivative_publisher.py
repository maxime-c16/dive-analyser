"""D3b1 derivative publisher (UNWIRED internal, no routes/jobs/readers).

SERVER publication primitive for D1 ``hq``/``light``/``poster`` ledger
rows. The caller supplies a local file holding the derivative bytes for
one (video, role) pair (e.g. a D3a ``PackageResult`` ``result_dir``
file); the publisher uploads them content-addressed to B2,
roundtrip-verifies EVERY byte (size + SHA-256 over a full streamed read
— never a client ``verified`` bool or HEAD metadata), then commits the
durable ledger (blob + verified location + ``derived_*`` revision via
``commit_verified_ingest`` + ``media_derivatives`` row) in one DB
transaction.

Caller contract (explicit, NOT "validated input"): the publisher proves
byte identity (SHA-256/size roundtrip), NOT media format validity. The
file is treated as opaque bytes claimed for the role; format/slot
acceptance (is this really playable H.264 / a real JPEG) is D3b2's
verifier, not this slice. Do not rely on this module to reject
wrong-format bytes.

Unwired on purpose: no route, no job mutation, no reader, no backfill,
no retention/LRU/unpin change imports this module. The only entry
points are ``build_publication_context`` (validates identity + resolves
the canonical camera source) and ``publish_derivative`` (requires an
internal ``PublicationContext`` built by that factory — never raw
strings — so the future D3b2 fenced slot API cannot bypass the guard by
calling the commit path directly).

Trust boundary (read carefully): ``PublicationContext`` is an INTERNAL
validated descriptor for trusted in-process callers, NOT an API
authorization boundary. Python types cannot enforce that, so
``publish_derivative`` REVALIDATES everything security-relevant against
current settings and the current database BEFORE any external upload:
D1 identity (via the shared ``build_derivative_media_key`` validator:
UUID shape/whitespace/``|``/length, role, SHA, transform
delimiter/whitespace/length), the canonical source (re-resolved; a
forged or stale ``source_blob_sha256`` lands in the stale path, never
``ready``), and environment/bucket/prefix (recomputed from current
settings; any mismatch or forged bucket fails closed). A forged context
therefore cannot write to an arbitrary bucket.

Explicit limit (not integrated yet): D2 lease-token fencing is NOT
enforced here. ``build_publication_context`` resolves the source
revision but does not validate a ``media_jobs`` claim token; D3b2 must
add ``_guarded_job`` validation inside the builder (same context
shape, so ``publish_derivative`` needs no signature change). Do not
treat this slice as fenced, and do not expose it as a secured API.

Source policy (quality): the canonical source is the newest verified
PROD camera-original revision — every non-derivative semantic EXCEPT
the already-transcoded ``browser_playback`` proxy (i.e.
``browser_original`` raw upload bytes ARE eligible: they are the true
camera bytes for browser clips). ``derived_*`` rows are always excluded
via the shared D1 clause. Existing selectors are untouched; this helper
does not modify playback, guest, download, matchmaking or
``_b2_source`` behavior. The source location must be a verified B2
replica in the allowlisted PROD bucket (``verified_original_clause``
contract); any ambiguity (several verified PROD replicas, a non-B2 or
wrong-bucket replica) fails closed with ``MissingSourceError``.

Environment policy: the source is ALWAYS canonical PROD, but the
publish environment (dev or prod, from ``b2_upload_environment``)
selects the destination bucket via the allowlist. A dev publish commits
its blob location in the DEV bucket only; it never creates a PROD
location, so it can never be served as a prod-ready replica. A later
publish of the same bytes in another env uploads + full-GET verifies in
that env and commits that env's replica before any dedup ``ready``
(including ``IntegrityError`` rival replays). The
``media_derivatives`` ledger row itself carries no environment — it is
a content proof, and env scoping lives on the blob locations (D3b2
readers must resolve locations in their serving environment).

B2 keys: ``<prefix>/derived/<source_sha[:2]>/<role>-<transform>-<derivative_sha>``
with ``prefix`` from ``media_backbone_object_prefix`` and the bucket
from the validated ``b2_upload_environment`` (dev/prod allowlist).
Content is addressed by bytes; the ledger identity is
``(video_uuid, source_blob_sha256, role, transform_version)``.

Transaction policy: the publisher OWNS its DB unit on the
caller-provided session. Both entry points require a clean session (no
pending new/dirty/deleted objects) and fail BEFORE any network upload
otherwise, so caller-owned unrelated work is never committed or rolled
back by this module. On success the unit commits; on ANY failure the
unit rolls back (releasing row locks) and the ledger stays NOT ready.
The network phase (upload + full-byte verify) runs with no row locks
held and no writes pending: revalidation reads are rolled back before
upload so no read snapshot spans the network call. The DB unit then
re-reads everything it needs.

Concurrency policy (read carefully — no linearizable cutover is
claimed): same-identity publishers serialize on the ledger row
(``SELECT ... FOR UPDATE`` on PostgreSQL; the UNIQUE identity index +
``IntegrityError`` rival path on SQLite). The canonical source is
checked AFTER acquiring the row position AND rechecked immediately
before commit, so a source revision that committed between the first
check and the flush cannot produce a false ``ready``. Against the many
unfenced source writers (ingest paths outside this module) this is a
best-effort guard, not a linearizable cutover: the narrow race between
the pre-commit recheck and the commit itself can only be closed by D2
fencing. If the recheck observes drift, the unit rolls back and raises
``StaleSourceError`` with nothing committed.

Failure semantics: any upload, verify or DB failure raises and leaves
the ledger NOT ready; an existing ``ready`` row with the same identity
is NEVER overwritten or downgraded (same bytes = idempotent replay,
different bytes = ``DerivativeIdentityConflict``); B2 orphans from a
crashed attempt are retained (never deleted, never touching other
objects). A source revision that changed between context build and
commit commits ``stale`` (backbone bytes durably recorded,
``media_derivatives`` row ``stale``), never ``ready``, with no
autoqueue (D3b2 owns slot scheduling). Every ``ready`` decision —
including idempotent replays and ``IntegrityError`` rival resolutions —
rechecks the canonical source first.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
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

# Private factory marker: the ONLY valid token lives in this module.
# ``PublicationContext`` construction outside ``build_publication_context``
# is rejected. This is hygiene, not the security boundary — the boundary
# is the revalidation ``publish_derivative`` performs before any upload
# (see module docstring).
_CTX_FACTORY_TOKEN: Any = object()


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


class DirtySessionError(DerivativePublishError):
    """Caller session held pending writes (retryable internal error).

    Distinct from fencing/client errors so routes can return 500 (retryable
    internal) instead of 409 (client-stale). Never a stale lease.
    """


class FencedSlotConflict(DerivativePublishError):
    """Explicit fenced-lease rejection (client-stale, re-lease required).

    Raised ONLY when the D3b2 pre-commit fencing hook rejects the attempt
    (lease owner/expiry/token mismatch, transform/source pin drift, invalid
    slot state for this package): the attempt is stale, the Mac client must
    re-lease, and the verified B2 bytes stay a safe orphan. Deliberately
    distinct from the generic ``DerivativePublishError`` base, which wraps
    unexpected DB/commit/internal failures (retryable 500, sanitized):
    routes map this subclass to 409 and the base to 500.
    """


class CanaryBudgetPublishError(DerivativePublishError):
    """True canary-budget refusal (typed 409, never 500).

    Raised ONLY when the authoritative per-PUT reserve refuses the PUT
    (cap exceeded or reservation ledger unavailable/misconfigured). Routes
    map this subclass to 409. The generic ``DerivativePublishError`` base
    stays 500 (retryable internal), so the classifier must check this
    subclass BEFORE the base. Never raised for provider/reuse/commit
    failures.
    """


class _CommittedStale(StaleSourceError):
    """Internal: stale record was COMMITTED before this was raised.

    Callers observe ``StaleSourceError``; the subclass only tells the
    ``publish_derivative`` handler to re-raise WITHOUT rolling back.
    """


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
    PROD B2 location via the shared ``verified_original_clause`` (exactly
    one verified PROD replica, B2 backend, allowlisted PROD bucket,
    non-empty key). Any ambiguity — several verified replicas, a non-B2
    or wrong-bucket replica, an unverified-only source — raises
    ``MissingSourceError``. Read-only; existing selectors untouched.
    Returns ``(revision, blob, location)``.
    """
    from app.models.media_backbone import MediaBlob, MediaBlobLocation, MediaRevision
    from app.services.matchmaking import verified_original_clause
    from app.services.media_backbone import derived_semantics_exclusion_clause

    if not isinstance(video_uuid, str) or not video_uuid.strip() or len(video_uuid) > 100:
        raise ValueError(f"invalid video_uuid: {video_uuid!r}")
    revision = (
        db.execute(
            select(MediaRevision)
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
    from app.config import get_settings as _get_settings

    prod_bucket = _get_settings().media_backbone_prod_bucket
    # Mirror the allowlist side of verified_original_clause for the
    # replica fetch itself: a verified non-B2 row (or a wrong-bucket row)
    # must never be selected even if the revision matched.
    location = (
        db.execute(
            select(MediaBlobLocation)
            .where(
                MediaBlobLocation.blob_sha256 == revision.blob_sha256,
                MediaBlobLocation.environment == "prod",
                MediaBlobLocation.verified.is_(True),
                MediaBlobLocation.storage_backend == "b2",
                MediaBlobLocation.bucket == prod_bucket,
                MediaBlobLocation.object_key != "",
            )
            .order_by(MediaBlobLocation.verified_at.desc(), MediaBlobLocation.id.desc())
            .limit(1)
        ).scalar_one_or_none()
    )
    blob = db.get(MediaBlob, revision.blob_sha256)
    if blob is None or location is None:
        raise MissingSourceError(f"canonical source bytes not resolved for {video_uuid!r}")
    return revision, blob, location


@dataclass(frozen=True)
class PublicationContext:
    """INTERNAL validated publication descriptor (D3b1, trusted callers).

    Only ``build_publication_context`` constructs this (private factory
    token); direct construction raises. This is hygiene — the actual
    enforcement is ``publish_derivative`` revalidating identity, source,
    environment, bucket and prefix against current settings and the
    current database before any external upload (a forged context
    cannot divert bytes to another bucket).

    D2 tightens the BUILDER (adds ``_guarded_job`` lease checks); this
    shape stays. Do NOT treat this slice as fenced and do NOT expose it
    as an API security boundary.
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
    _factory_token: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._factory_token is not _CTX_FACTORY_TOKEN:
            raise DerivativePublishError(
                "PublicationContext must be built by build_publication_context"
            )


def _require_clean_session(db) -> None:
    """Fail fast when the caller session holds pending writes.

    The publisher owns its DB unit: it must never commit or roll back
    unrelated caller work. Both entry points refuse a dirty session
    BEFORE any network upload.
    """
    if db.new or db.dirty or db.deleted:
        raise DirtySessionError(
            "publish_derivative requires a session with no pending writes; "
            "commit or roll back caller work before publishing"
        )


def _validate_identity(video_uuid: str, role: str, source_sha256: str, transform_version: str) -> None:
    """Shared D1 identity contract (UUID/role/SHA/transform checks).

    Single fail-closed validator for builder and publisher revalidation:
    UUID non-empty, no surrounding whitespace, no ``|`` delimiter,
    ``<= 100`` chars; role allowlisted; source SHA exact lowercase hex;
    transform version non-empty, stripped, ``<= 40`` chars, no ``|``.
    """
    from app.services.media_keys import build_derivative_media_key

    build_derivative_media_key(video_uuid, role, source_sha256, transform_version)


def _current_upload_scope(ctx: PublicationContext) -> tuple[str, str, str]:
    """Recompute environment/bucket/prefix from CURRENT settings.

    Returns ``(environment, bucket)`` and raises when the context no
    longer matches (settings changed since build, or forged fields) —
    fail closed before any external upload. The recomputed values (not
    the context fields) drive the upload.
    """
    from app.services.media_backbone import environment_bucket

    settings = get_settings()
    environment = (settings.b2_upload_environment or "").strip().lower()
    if environment not in ("dev", "prod"):
        raise MissingCredentials("B2 upload environment is not configured correctly")
    bucket = environment_bucket(environment)
    prefix = (settings.media_backbone_object_prefix or "blobs/sha256").strip().strip("/")
    if not prefix:
        raise ValueError("empty media_backbone_object_prefix")
    if (
        ctx.environment != environment
        or ctx.bucket != bucket
        or ctx.object_prefix != prefix
    ):
        raise DerivativePublishError(
            "publication context no longer matches current storage settings; "
            "rebuild the context and retry"
        )
    return environment, bucket, prefix


def build_publication_context(db, *, video_uuid: str, role: str, transform_version: str | None = None) -> PublicationContext:
    """Validate identity + resolve the canonical camera source (no job fencing yet).

    Requires a clean session (no pending writes). Identity is validated
    through the shared D1 validator (early, before any source read), so
    a bad transform version fails here — not late at upload time.

    Explicit non-goal: no ``media_jobs`` lease-token check. D3b2 adds it
    here; callers must not assume fencing from this slice.
    """
    from app.services.media_backbone import _validate_sha  # noqa: SLF — shared fail-closed SHA check
    from app.services.media_backbone import environment_bucket

    _require_clean_session(db)
    if role not in DERIVATIVE_CONTENT_TYPES:
        raise ValueError(f"unknown derivative role {role!r}")
    version = transform_version if transform_version is not None else get_settings().media_derivative_transform_version
    # Identity SHAPE first (UUID delimiter/whitespace/length, role,
    # transform delimiter/whitespace/length) through the shared D1
    # validator — malformed identities fail before any source read. The
    # placeholder SHA carries valid shape only; the real source SHA is
    # validated again below once resolved.
    _validate_identity(video_uuid, role, "0" * 64, version)
    revision, blob, _location = resolve_canonical_source_revision(db, video_uuid)
    source_sha = revision.blob_sha256
    _validate_sha(source_sha)
    # Full D1 identity contract (UUID delimiter/whitespace/length, role,
    # SHA, transform delimiter/whitespace/length) — one shared validator.
    _validate_identity(video_uuid, role, source_sha, version)
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
        _factory_token=_CTX_FACTORY_TOKEN,
    )


def _b2_upload_client():
    """Build the private B2 upload (S3) client from runtime config only.

    Provider-level failures are raised sanitized (``from None``): raw
    provider exceptions can echo endpoint/credential material and must
    never propagate to callers or logs.
    """
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
    try:
        import boto3  # lazy: unit tests inject fakes instead
        from botocore.config import Config

        return boto3.client(
            "s3",
            region_name=settings.b2_upload_region,
            endpoint_url=settings.b2_upload_endpoint_url
            or f"https://s3.{settings.b2_upload_region}.backblazeb2.com",
            aws_access_key_id=settings.b2_upload_key_id,
            aws_secret_access_key=settings.b2_upload_key_secret,
            config=Config(connect_timeout=10, read_timeout=120, retries={"total_max_attempts": 2}),
        )
    except MissingCredentials:
        raise
    except Exception:
        raise MissingCredentials("Video storage client could not be created") from None


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
    attempt_reuse: bool = False,
) -> None:
    """Upload bytes then stream-read the object back and compare ALL bytes.

    Never trusts a client ``verified`` bool or HEAD metadata: the proof is
    a full GET with streamed SHA-256 + size equality against the local
    artifact hashed just before upload. Any mismatch, truncation, wrong
    size, missing body or provider error raises ``VerificationFailed`` and
    commits nothing. Secrets never appear in messages.

    Versioning bound (hard, canary only): the canary caller runs
    ``_try_verified_reuse`` (full GET proving same bytes under the same
    key) BEFORE charging or PUTting -- a hit skips both (verified reuse,
    no new B2 version, no new charge). On a miss the caller charges this
    PUT attempt first, then PUTs with ``attempt_reuse=False``. A
    same-key retry after a successful PUT therefore takes the no-charge
    reuse path; concurrent same-key races that both miss each charge
    and each PUT (bounded to in-flight parallelism: fleet one-package
    + serial admit -> at most one extra version). Non-canary publishes
    pass attempt_reuse=False (no extra GET).
    """
    if attempt_reuse and _try_verified_reuse(
        client=client,
        bucket=bucket,
        key=key,
        derivative_sha=derivative_sha,
        derivative_size=derivative_size,
    ):
        return
    try:
        client.upload_file(
            str(local_path),
            bucket,
            key,
            ExtraArgs={"ContentType": content_type, "Metadata": {"sha256": derivative_sha}},
        )
    except Exception:
        raise VerificationFailed("derivative upload failed; please retry") from None
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
    except Exception:
        raise VerificationFailed("derivative storage verification failed; please retry") from None
    if digest.hexdigest() != derivative_sha or size != derivative_size:
        raise VerificationFailed("derivative storage verification failed; please retry")


def _is_definite_not_found(exc: Exception) -> bool:
    """True only when the provider proves the object is absent (no overwrite risk).

    Definite-absent signals (fail-open to charge+PUT path):
    - test fakes: ``KeyError`` / ``FileNotFoundError`` (miss fallback);
    - typed provider not-found: ``NoSuchKey`` / ``NotFound`` / HTTP 404
      (botocore ``ClientError`` ``response`` shape or exception class name).
    Every other provider failure (500, timeout, auth, throttling,
    corrupt stream, truncated body) is AMBIGUOUS: the object may exist,
    so overwriting it cannot be authorized -- the caller must FAIL
    CLOSED. Never inspects secrets; checks codes/status only.
    """
    if isinstance(exc, (KeyError, FileNotFoundError)):
        return True
    try:
        resp = getattr(exc, "response", None)
        if isinstance(resp, dict):
            err = resp.get("Error") or {}
            code = str(err.get("Code") or "").strip()
            meta = resp.get("ResponseMetadata") or {}
            try:
                status = int(meta.get("HTTPStatusCode") or 0)
            except (TypeError, ValueError):
                status = 0
            if code in ("NoSuchKey", "NotFound", "404") or status == 404:
                return True
            # S3-style 404 wrapped without response metadata.
            if "NoSuchKey" in code or "NotFound" in code:
                return True
    except Exception:
        pass
    try:
        name = type(exc).__name__ or ""
        if name in ("NoSuchKey", "NotFound", "NotFoundException", "NoSuchBucket"):
            # NoSuchBucket also proves no object exists at the key.
            return True
    except Exception:
        pass
    return False


def _try_verified_reuse(*, client: Any, bucket: str, key: str,
                          derivative_sha: str, derivative_size: int) -> bool:
    """Full-GET reuse check: True when the same key already proves same bytes.

    Streams the existing object and compares SHA-256 + size (never HEAD
    metadata). Returns True on verified match (skip PUT + charge) and
    False ONLY on definite-absent proof (``_is_definite_not_found``:
    typed NoSuchKey/404 or fake KeyError/FileNotFound -- safe to
    charge + PUT). Any other provider failure (500/timeout/auth),
    truncated/corrupt stream, body-read error, or a successful GET whose
    bytes do NOT match the expected SHA/size raises
    ``VerificationFailed`` (sanitized, ``from None``): an unverifiable
    reuse or a present-but-different object cannot authorize overwriting,
    so the caller fails closed with no PUT and no new charge, preserving
    monotonic accounting. Only a definite not-found response permits PUT.
    Secrets never appear in messages.
    """
    import hashlib as _hashlib

    try:
        response = client.get_object(Bucket=bucket, Key=key)
        body = response["Body"]
        digest = _hashlib.sha256()
        size = 0
        try:
            chunks = body.iter_chunks(chunk_size=1024 * 1024) if hasattr(body, "iter_chunks") else None
            if chunks is None:
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
    except Exception as exc:
        if _is_definite_not_found(exc):
            return False
        raise VerificationFailed(
            "derivative reuse check failed; refusing overwrite"
        ) from None
    if digest.hexdigest() != derivative_sha or size != derivative_size:
        raise VerificationFailed(
            "derivative reuse check found different bytes; refusing overwrite"
        ) from None
    return True


def _is_postgres(db) -> bool:
    try:
        return db.bind is not None and db.bind.dialect.name == "postgresql"
    except Exception:
        return False


def _read_existing_ledger_row(db, ctx: PublicationContext, *, for_update: bool):
    """Current ledger row for the context identity (or None).

    ``populate_existing`` defeats a stale caller-side identity map: the
    decision below always reflects the latest committed row, not a
    cached copy. ``for_update`` takes the PG row lock that serializes
    same-identity publishers (SQLite has no FOR UPDATE; the UNIQUE
    index + IntegrityError path serializes there).
    """
    from app.models.media_backbone import MediaDerivative

    query = (
        select(MediaDerivative)
        .where(
            MediaDerivative.video_uuid == ctx.video_uuid,
            MediaDerivative.source_blob_sha256 == ctx.source_blob_sha256,
            MediaDerivative.role == ctx.role,
            MediaDerivative.transform_version == ctx.transform_version,
        )
        .execution_options(populate_existing=True)
    )
    if for_update and _is_postgres(db):
        query = query.with_for_update()
    return db.execute(query).scalar_one_or_none()


def _resolve_current_source_sha(db, video_uuid: str) -> tuple[str | None, bool]:
    """Canonical source SHA right now, or (None, drifted=True) when gone.

    Returns ``(sha, False)`` when the canonical revision resolves,
    ``(None, True)`` when no verified PROD camera-original exists
    (source deleted/unverifiable counts as drift).
    """
    try:
        current, _blob, _loc = resolve_canonical_source_revision(db, video_uuid)
    except MissingSourceError:
        return None, True
    return current.blob_sha256, False


def _ensure_current_env_backbone(db, ctx, *, derivative_sha, derivative_size, key, bucket, environment) -> None:
    """Flush blob + verified location + revision for the current env (no commit).

    The ``media_derivatives`` ledger identity carries no environment — it
    is a content proof — so an idempotent replay (or an ``IntegrityError``
    rival replay) with the same bytes must still record THIS environment's
    verified replica before returning ``ready``. A DEV publish therefore
    never counts as PROD proof: a later PROD publish of the same bytes
    commits its own PROD location/revision here and only then dedups.
    Caller commits; this only flushes. Never touches the ledger row.
    """
    from app.services.media_backbone import DERIVATIVE_ROLE_TO_SEMANTICS
    from app.services.media_backbone import commit_verified_ingest

    semantics = DERIVATIVE_ROLE_TO_SEMANTICS.get(ctx.role, f"derived_{ctx.role}")
    commit_verified_ingest(
        db,
        video_uuid=ctx.video_uuid,
        blob_sha256=derivative_sha,
        byte_size=derivative_size,
        object_key=key,
        storage_backend="b2",
        bucket=bucket,
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
        environment=environment,
        commit=False,
    )


def publish_derivative(
    db,
    ctx: PublicationContext,
    local_path: str | Path,
    *,
    s3_client: Any | None = None,
    pre_commit_hook: Any | None = None,
    canary_scope: bool = False,
) -> dict[str, Any]:
    """Publish one derivative artifact (upload → verify → commit).

    Requires an internal ``PublicationContext`` from
    ``build_publication_context`` (type + factory token checked), then
    REVALIDATES identity, canonical source, environment, bucket and
    prefix against current settings and the current database BEFORE any
    external upload, so a forged or stale context cannot write to an
    arbitrary bucket.

    Requires a clean caller session (no pending writes): fails BEFORE
    any network upload otherwise, and never commits or rolls back
    caller-owned unrelated work. Owns its DB unit: commits on success,
    rolls back on any failure (releasing row locks).

    Network first (upload + full-byte verify, no row locks held and no
    writes pending — revalidation reads are rolled back before the
    upload), then ONE DB transaction: position on the ledger identity →
    source-drift check → fenced guard (optional ``pre_commit_hook``) →
    backbone commit + ledger upsert, with a second source recheck
    immediately before commit. Any drift commits ``stale``, never
    ``ready``; an existing ``ready`` row is never modified. B2 orphans
    are retained. The hook runs with the ledger row lock held, inside
    the committing unit: a fencing rejection there rolls back without
    promoting anything (D3b2 lease-token + source recheck + slot commit).
    """
    from app.services.media_backbone import DERIVATIVE_ROLE_TO_SEMANTICS
    from app.services.media_backbone import commit_verified_ingest

    if not isinstance(ctx, PublicationContext) or getattr(ctx, "_factory_token", None) is not _CTX_FACTORY_TOKEN:
        raise DerivativePublishError("publish_derivative requires a validated PublicationContext")
    if ctx.role not in DERIVATIVE_CONTENT_TYPES:
        raise DerivativePublishError(f"unknown derivative role {ctx.role!r}")
    _require_clean_session(db)
    # D1 identity contract revalidation (builder used the same validator):
    # a forged context with a bad UUID/role/SHA/transform fails here.
    _validate_identity(ctx.video_uuid, ctx.role, ctx.source_blob_sha256, ctx.transform_version)
    # Recompute the upload scope from CURRENT settings; mismatch (settings
    # changed since build, or forged fields) fails closed before upload.
    # The recomputed values drive the upload, never the context fields.
    environment, bucket, prefix = _current_upload_scope(ctx)
    path = Path(local_path)
    if not path.is_file():
        raise DerivativePublishError(f"derivative artifact missing: {path!s}")
    try:
        derivative_sha, derivative_size = _sha256_file(path)
    except DerivativePublishError:
        raise
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        raise DerivativePublishError("derivative artifact could not be read") from exc
    if derivative_size <= 0:
        raise DerivativePublishError("derivative artifact is empty")
    # Resolve the exact B2 namespace FIRST (pure, no DB txn, no network):
    # the reservation identity is (bucket, object_key), computed from the
    # trusted ctx pin + the ACTUAL bytes just hashed -- never from an
    # untrusted client claim. Identical bytes under different keys are
    # distinct stored objects (no SHA-only dedupe).
    key = derivative_object_key(
        source_sha256=ctx.source_blob_sha256,
        role=ctx.role,
        transform_version=ctx.transform_version,
        derivative_sha256=derivative_sha,
        prefix=prefix,
    )
    content_type = DERIVATIVE_CONTENT_TYPES[ctx.role]
    # Canary-only hard budget (scoped: canary_scope=True, derived by the
    # route from the SERVER-PERSISTED job reason -- never a client bool;
    # generic callers never pay the canary cap). Per-slot size is
    # validated here (fail before network); the durable per-PUT charge
    # happens AFTER the pre-PUT full-GET reuse check misses and BEFORE
    # the PUT streams (see network phase below): a verified reuse skips
    # both the charge and the PUT, but every actual PUT attempt charges
    # its own row -- even a same-key retry/racer that also missed the
    # GET. The charge commits before the PUT so orphans/failed PUTs stay
    # counted (monotonic, never refunded).
    _is_canary_slot = bool(canary_scope and ctx.role in ("hq", "light", "poster"))
    if _is_canary_slot:
        try:
            from app.services.canary_budget import validate_canary_slot_size

            validate_canary_slot_size(ctx.role, int(derivative_size))
        except ValueError as exc:
            try:
                db.rollback()
            except Exception:
                pass
            raise DerivativePublishError(str(exc) or "canary slot refused") from exc

    # Close the revalidation read snapshot before the network phase so no
    # read transaction spans the upload. The session is still clean here
    # (entry check passed; only reads happened since) — recheck cheaply
    # rather than risk discarding caller work.
    _require_clean_session(db)
    try:
        db.rollback()
    except Exception:
        pass

    # Preflight (best-effort, rechecked after the upload): an obvious
    # identity conflict — existing READY row, different bytes, source
    # still current — fails BEFORE spending a network upload. Anything
    # else proceeds; the post-upload unit re-decides from scratch.
    try:
        pre_existing = _read_existing_ledger_row(db, ctx, for_update=False)
        if (
            pre_existing is not None
            and pre_existing.status == "ready"
            and pre_existing.derivative_blob_sha256 != derivative_sha
        ):
            _pre_sha, pre_drifted = _resolve_current_source_sha(db, ctx.video_uuid)
            if not pre_drifted and _pre_sha == ctx.source_blob_sha256:
                try:
                    db.rollback()
                except Exception:
                    pass
                raise DerivativeIdentityConflict(
                    "derivative identity already ready with different bytes; refusing overwrite"
                )
    except DerivativeIdentityConflict:
        raise
    except DerivativePublishError:
        raise
    except Exception:
        # Preflight is advisory only: any unexpected read failure falls
        # through to the authoritative post-upload unit.
        try:
            db.rollback()
        except Exception:
            pass

    client = s3_client if s3_client is not None else _b2_upload_client()
    try:
        if _is_canary_slot:
            # Reuse check FIRST (full-GET proof, no charge): the same key
            # already proving the same bytes skips both charge and PUT.
            # Only a DEFINITE-absent GET (NoSuchKey/404) is a miss that
            # authorizes charge+PUT; any other GET failure raises fail-closed
            # (no PUT, no charge, monotonic preserved).
            # On a definite miss, charge this PUT attempt NOW (cap-checked under
            # the PG advisory lock, committed before the PUT -- never
            # held across the network), then stream the PUT. Two racers
            # that both miss each charge; each PUT may store its own
            # version, so per-attempt charging is the bound (the
            # one-package lease does NOT serialize duplicate HTTP).
            if _try_verified_reuse(
                client=client,
                bucket=bucket,
                key=key,
                derivative_sha=derivative_sha,
                derivative_size=derivative_size,
            ):
                pass
            else:
                try:
                    from app.services.canary_budget import (
                        CanaryBudgetExceeded,
                        reserve_canary_upload,
                    )

                    reserve_canary_upload(
                        db,
                        derivative_sha,
                        int(derivative_size),
                        job_id=None,
                        slot=ctx.role,
                        bucket=bucket,
                        object_key=key,
                        environment=environment,
                    )
                except CanaryBudgetExceeded as exc:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    raise CanaryBudgetPublishError(str(exc) or "canary budget exceeded") from exc
                except ValueError as exc:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    raise DerivativePublishError(str(exc) or "canary slot refused") from exc
                except DerivativePublishError:
                    raise
                except Exception as exc:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    raise DerivativePublishError("derivative publish failed; ledger unchanged") from exc
                _upload_and_roundtrip_verify(
                    client=client,
                    bucket=bucket,
                    key=key,
                    local_path=path,
                    content_type=content_type,
                    derivative_sha=derivative_sha,
                    derivative_size=derivative_size,
                    attempt_reuse=False,
                )
        else:
            _upload_and_roundtrip_verify(
                client=client,
                bucket=bucket,
                key=key,
                local_path=path,
                content_type=content_type,
                derivative_sha=derivative_sha,
                derivative_size=derivative_size,
                attempt_reuse=False,
            )
    except DerivativePublishError:
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
        raise DerivativePublishError("derivative publish failed; ledger unchanged") from None

    # DB unit: position on the ledger identity (locking on PG) →
    # source-drift check → backbone commit + ledger upsert → pre-commit
    # source recheck → commit. Every ready decision passes the drift
    # check; an existing ready row is never modified.
    from sqlalchemy.exc import IntegrityError

    try:
        existing = _read_existing_ledger_row(db, ctx, for_update=True)
        current_sha, drifted = _resolve_current_source_sha(db, ctx.video_uuid)
        if drifted or current_sha != ctx.source_blob_sha256:
            _commit_stale_attempt(
                db,
                ctx,
                existing=existing,
                derivative_sha=derivative_sha,
                derivative_size=derivative_size,
                key=key,
                bucket=bucket,
                environment=environment,
            )
            # NOT REACHED — _commit_stale_attempt commits then raises.

        if pre_commit_hook is not None:
            # D3b2 fenced guard: runs with the ledger row lock held, inside
            # the committing unit, BEFORE any ready decision (including
            # idempotent replays). A stale lease / source mismatch raises
            # here; the unit rolls back and the verified B2 bytes stay a
            # safe orphan. The hook may also stage the job's finalized_slots
            # in the same transaction (committed atomically with the ledger
            # below).
            try:
                pre_commit_hook(
                    db,
                    ctx,
                    derivative_sha=derivative_sha,
                    derivative_size=derivative_size,
                    object_key=key,
                    bucket=bucket,
                    environment=environment,
                )
            except _CommittedStale:
                raise
            except (DerivativePublishError, StaleSourceError, DerivativeIdentityConflict):
                try:
                    db.rollback()
                except Exception:
                    pass
                raise
            except PermissionError as exc:
                try:
                    db.rollback()
                except Exception:
                    pass
                raise FencedSlotConflict(str(exc) or "fenced claim rejected") from exc
            except ValueError as exc:
                try:
                    db.rollback()
                except Exception:
                    pass
                raise FencedSlotConflict(str(exc) or "fenced claim rejected") from exc

        if existing is not None and existing.status == "ready":
            if existing.derivative_blob_sha256 == derivative_sha:
                # Idempotent replay: same bytes already durable. The
                # source was rechecked above, so this ready is current.
                # The ledger carries no env, but readers resolve replicas
                # per-env: commit THIS env's verified location/revision
                # before deduping, so DEV-ready never serves as PROD
                # proof without a PROD upload + full-GET verify (done
                # above) and a PROD replica commit (done here).
                _ensure_current_env_backbone(
                    db,
                    ctx,
                    derivative_sha=derivative_sha,
                    derivative_size=derivative_size,
                    key=key,
                    bucket=bucket,
                    environment=environment,
                )
                db.commit()
                return {
                    "video_uuid": ctx.video_uuid,
                    "role": ctx.role,
                    "source_blob_sha256": ctx.source_blob_sha256,
                    "derivative_blob_sha256": derivative_sha,
                    "byte_size": derivative_size,
                    "object_key": key,
                    "bucket": bucket,
                    "environment": environment,
                    "status": "ready",
                    "deduplicated": True,
                    "media_derivative_id": existing.id,
                }
            try:
                db.rollback()
            except Exception:
                pass
            raise DerivativeIdentityConflict(
                "derivative identity already ready with different bytes; refusing overwrite"
            )

        _commit_ready_attempt(
            db,
            ctx,
            existing=existing,
            derivative_sha=derivative_sha,
            derivative_size=derivative_size,
            key=key,
            bucket=bucket,
            environment=environment,
        )
        derivative_id = existing.id if existing is not None else _fresh_derivative_id(db, ctx)
        # Pre-commit source recheck: a source revision that committed
        # between the drift check and the flushes must not become ready.
        # (Best-effort guard, not a linearizable cutover — see module
        # docstring. D2 fencing closes the residual race.)
        recheck_sha, recheck_drifted = _resolve_current_source_sha(db, ctx.video_uuid)
        if recheck_drifted or recheck_sha != ctx.source_blob_sha256:
            try:
                db.rollback()
            except Exception:
                pass
            raise StaleSourceError(
                "canonical source changed during commit; recorded nothing, not ready"
            )
        db.commit()
        return {
            "video_uuid": ctx.video_uuid,
            "role": ctx.role,
            "source_blob_sha256": ctx.source_blob_sha256,
            "derivative_blob_sha256": derivative_sha,
            "byte_size": derivative_size,
            "object_key": key,
            "bucket": bucket,
            "environment": environment,
            "status": "ready",
            "deduplicated": False,
            "media_derivative_id": derivative_id,
        }
    except _CommittedStale:
        # Stale record already committed; re-raise WITHOUT rollback.
        raise
    except (DerivativeIdentityConflict, StaleSourceError):
        # Pre-commit failures: nothing committed above (conflict rolls
        # back its row lock before raising; the commit-race stale rolls
        # back before raising). Re-raise as-is.
        raise
    except IntegrityError:
        try:
            db.rollback()
        except Exception:
            pass
        # Concurrent same-identity winner: re-read the rival UNDER the ledger
        # row lock (FOR UPDATE on PG) AND recheck the source, then run the
        # fenced hook in the SAME TX before any ready decision (a drifted
        # source never resolves to ready, even for an idempotent replay).
        # Lock ordering stays ledger -> job (never job -> ledger) so two
        # concurrent slots for one job (different ledger rows, one job row)
        # serialize without deadlock. No ready (including dedup) returns
        # without the D2 current-claim + source authoritative check.
        rival = _read_existing_ledger_row(db, ctx, for_update=True)
        rival_sha, rival_drifted = _resolve_current_source_sha(db, ctx.video_uuid)
        if rival_drifted or rival_sha != ctx.source_blob_sha256:
            try:
                db.rollback()
            except Exception:
                pass
            raise StaleSourceError(
                "canonical source changed during commit; recorded nothing, not ready"
            ) from None
        if pre_commit_hook is not None:
            try:
                pre_commit_hook(
                    db,
                    ctx,
                    derivative_sha=derivative_sha,
                    derivative_size=derivative_size,
                    object_key=key,
                    bucket=bucket,
                    environment=environment,
                )
            except _CommittedStale:
                raise
            except (DerivativePublishError, StaleSourceError, DerivativeIdentityConflict):
                try:
                    db.rollback()
                except Exception:
                    pass
                raise
            except PermissionError as exc:
                try:
                    db.rollback()
                except Exception:
                    pass
                raise FencedSlotConflict(str(exc) or "fenced claim rejected") from exc
            except ValueError as exc:
                try:
                    db.rollback()
                except Exception:
                    pass
                raise FencedSlotConflict(str(exc) or "fenced claim rejected") from exc
        if (
            rival is not None
            and rival.derivative_blob_sha256 == derivative_sha
            and rival.status == "ready"
        ):
            # Same-bytes rival won the ledger race: this env still needs
            # its own verified replica (upload + full-GET verify already
            # proved THESE bytes in THIS bucket above). Commit it before
            # deduping so DEV-ready never counts as PROD proof.
            rival_id = rival.id
            _ensure_current_env_backbone(
                db,
                ctx,
                derivative_sha=derivative_sha,
                derivative_size=derivative_size,
                key=key,
                bucket=bucket,
                environment=environment,
            )
            db.commit()
            return {
                "video_uuid": ctx.video_uuid,
                "role": ctx.role,
                "source_blob_sha256": ctx.source_blob_sha256,
                "derivative_blob_sha256": derivative_sha,
                "byte_size": derivative_size,
                "object_key": key,
                "bucket": bucket,
                "environment": environment,
                "status": "ready",
                "deduplicated": True,
                "media_derivative_id": rival_id,
            }
        raise DerivativeIdentityConflict(
            "derivative identity concurrently committed; refusing overwrite"
        ) from None
    except DerivativePublishError:
        try:
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


def _commit_stale_attempt(db, ctx, *, existing, derivative_sha, derivative_size, key, bucket, environment) -> None:
    """Commit the drifted attempt as stale, then raise (never returns).

    Backbone bytes are durably recorded (``media_only`` stale revision);
    the ledger gains a ``stale`` row for a fresh identity, or a
    non-ready row is moved to ``stale`` (same or new bytes — nothing
    verified is overwritten). An existing ``ready`` row is NEVER
    touched: the old derivation keeps serving until D3b2 supersedes it.
    Commits, then raises ``_CommittedStale`` (observed as
    ``StaleSourceError``).
    """
    from app.models.media_backbone import MediaDerivative
    from app.services.media_backbone import DERIVATIVE_ROLE_TO_SEMANTICS
    from app.services.media_backbone import commit_verified_ingest

    semantics = DERIVATIVE_ROLE_TO_SEMANTICS.get(ctx.role, f"derived_{ctx.role}")
    commit_verified_ingest(
        db,
        video_uuid=ctx.video_uuid,
        blob_sha256=derivative_sha,
        byte_size=derivative_size,
        object_key=key,
        storage_backend="b2",
        bucket=bucket,
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
        environment=environment,
        commit=False,
    )
    if existing is None:
        db.add(
            MediaDerivative(
                video_uuid=ctx.video_uuid,
                source_blob_sha256=ctx.source_blob_sha256,
                role=ctx.role,
                transform_version=ctx.transform_version,
                derivative_blob_sha256=derivative_sha,
                status="stale",
                verified_at=None,
            )
        )
        db.flush()
    elif existing.status != "ready":
        # Non-ready row (verifying/stale/superseded, same or new bytes):
        # record the drifted bytes as stale. Nothing verified is
        # destroyed. (Same-bytes rows are set stale explicitly — a
        # drifted derivation is not current even when bytes match.)
        existing.derivative_blob_sha256 = derivative_sha
        existing.status = "stale"
        db.add(existing)
        db.flush()
    # else: existing ready row untouched by design (old policy served).
    db.commit()
    raise _CommittedStale("canonical source changed before commit; recorded stale, not ready")


def _commit_ready_attempt(db, ctx, *, existing, derivative_sha, derivative_size, key, bucket, environment) -> None:
    """Flush the ready backbone + ledger upsert (no commit; caller rechecks)."""
    from app.services.media_backbone import DERIVATIVE_ROLE_TO_SEMANTICS
    from app.services.media_backbone import commit_verified_ingest

    semantics = DERIVATIVE_ROLE_TO_SEMANTICS.get(ctx.role, f"derived_{ctx.role}")
    commit_verified_ingest(
        db,
        video_uuid=ctx.video_uuid,
        blob_sha256=derivative_sha,
        byte_size=derivative_size,
        object_key=key,
        storage_backend="b2",
        bucket=bucket,
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
        environment=environment,
        commit=False,
    )
    from app.models.media_backbone import MediaDerivative

    if existing is None:
        db.add(
            MediaDerivative(
                video_uuid=ctx.video_uuid,
                source_blob_sha256=ctx.source_blob_sha256,
                role=ctx.role,
                transform_version=ctx.transform_version,
                derivative_blob_sha256=derivative_sha,
                status="ready",
                verified_at=datetime.utcnow(),
            )
        )
        db.flush()
    else:
        # Non-ready row with same or new bytes: promote to ready.
        existing.derivative_blob_sha256 = derivative_sha
        existing.status = "ready"
        existing.verified_at = datetime.utcnow()
        db.add(existing)
        db.flush()


def _fresh_derivative_id(db, ctx: PublicationContext):
    """Ledger id of the row just flushed for a fresh identity.

    Read BEFORE commit so the id is valid regardless of the caller
    session's ``expire_on_commit`` setting.
    """
    from app.models.media_backbone import MediaDerivative

    row = (
        db.execute(
            select(MediaDerivative)
            .where(
                MediaDerivative.video_uuid == ctx.video_uuid,
                MediaDerivative.source_blob_sha256 == ctx.source_blob_sha256,
                MediaDerivative.role == ctx.role,
                MediaDerivative.transform_version == ctx.transform_version,
            )
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
    )
    return row.id if row is not None else None
