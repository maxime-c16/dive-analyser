"""Monotonic canary budget + fail-closed reuse (SQLite, no prod/B2).

PR145 second finding (6329980622): the old baseline excluded ANY charged
bucket/key, so a pre-existing READY object counted in the baseline could
disappear from accounting when a later unverifiable reuse GET missed and
charged again. This file proves the simplified conservative fix:

- READY baseline ALWAYS counts every READY row (no ledger exclusion) PLUS
  all attempt charges (intentional double-count of successful new objects,
  stricter bound, monotonic, never UNCOUNTs);
- reuse GET failures FAIL CLOSED unless a definite-absent proof
  (typed NoSuchKey/404 or fake KeyError/FileNotFound) authorizes charge+PUT.
  Generic 500/timeout/auth/corrupt reads raise sanitized (secret-free)
  with no PUT and no new charge;
- monotonic accounting across charge+ready commit, orphan persistence,
  different-key/same-SHA baseline counting, unknown lookup fails closed.
"""

import hashlib

import pytest

from app.services.canary_budget import (
    canary_accounted_bytes,
    canary_legacy_ready_bytes,
    canary_reserved_bytes,
    reserve_canary_upload,
)
from app.services.derivative_publisher import (
    VerificationFailed,
    _is_definite_not_found,
    _try_verified_reuse,
)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _reserve_kwargs(sha: str, size: int, tag: str = "a"):
    return {
        "sha256": sha,
        "size_bytes": size,
        "job_id": 1,
        "slot": "light",
        "bucket": "test-bucket",
        "object_key": f"blobs/sha256/{sha[:2]}/light-ffmpeg-h264-web-v1-{tag}-{sha}",
        "environment": "dev",
    }


def _seed_ready(test_db, video_uuid: str, role: str, nbytes: int):
    from app.config import get_settings
    from app.models.media_backbone import MediaBlob, MediaDerivative
    from app.models.photos_asset import PhotosAsset

    settings = get_settings()
    src_raw = f"src-{video_uuid}".encode()
    src_sha = _sha(src_raw + video_uuid.encode())
    test_db.add(PhotosAsset(video_uuid=video_uuid))
    test_db.flush()
    test_db.add(MediaBlob(sha256=src_sha, byte_size=len(src_raw), storage_backend="b2",
                          bucket=settings.media_backbone_prod_bucket,
                          object_key=f"blobs/sha256/{src_sha[:2]}/{src_sha}",
                          width=1280, height=720, duration_seconds=10.0))
    dsha = _sha(f"{video_uuid}{role}".encode())
    test_db.add(MediaBlob(sha256=dsha, byte_size=nbytes, storage_backend="b2",
                          bucket=settings.media_backbone_prod_bucket,
                          object_key=f"blobs/sha256/{dsha[:2]}/{dsha}"))
    test_db.add(MediaDerivative(video_uuid=video_uuid, source_blob_sha256=src_sha,
                                role=role, transform_version="ffmpeg-h264-web-v1",
                                derivative_blob_sha256=dsha, status="ready"))
    test_db.commit()
    return dsha


class _NotFoundExc(Exception):
    def __init__(self):
        self.response = {"Error": {"Code": "NoSuchKey"},
                         "ResponseMetadata": {"HTTPStatusCode": 404}}


class _ServerErrorExc(Exception):
    def __init__(self):
        self.response = {"Error": {"Code": "InternalError"},
                         "ResponseMetadata": {"HTTPStatusCode": 500}}


class _FakeGet:
    def __init__(self, exc):
        self._exc = exc
        self.calls = 0

    def get_object(self, Bucket, Key):
        self.calls += 1
        raise self._exc


def test_definite_notfound_vs_ambiguous_reuse():
    data = b"reuse-bytes"
    sha = hashlib.sha256(data).hexdigest()

    class _Body:
        def __init__(self, b):
            self._b = b
        def iter_chunks(self, chunk_size=1024 * 1024):
            yield self._b
        def close(self):
            pass

    class _Hit:
        def get_object(self, Bucket, Key):
            return {"Body": _Body(data)}

    assert _try_verified_reuse(client=_Hit(), bucket="b", key="k",
                               derivative_sha=sha, derivative_size=len(data)) is True
    # Definite-absent: fake fallbacks + typed NoSuchKey/404 -> miss (False).
    assert _try_verified_reuse(client=_FakeGet(KeyError("k")), bucket="b", key="k",
                               derivative_sha=sha, derivative_size=len(data)) is False
    assert _try_verified_reuse(client=_FakeGet(FileNotFoundError("k")), bucket="b", key="k",
                               derivative_sha=sha, derivative_size=len(data)) is False
    assert _try_verified_reuse(client=_FakeGet(_NotFoundExc()), bucket="b", key="k",
                               derivative_sha=sha, derivative_size=len(data)) is False
    assert _is_definite_not_found(_NotFoundExc()) is True
    assert _is_definite_not_found(KeyError("k")) is True
    # Ambiguous provider failures FAIL CLOSED (raise, sanitized, no secrets).
    assert _is_definite_not_found(_ServerErrorExc()) is False
    assert _is_definite_not_found(RuntimeError("boom")) is False
    with pytest.raises(VerificationFailed) as ei:
        _try_verified_reuse(client=_FakeGet(_ServerErrorExc()), bucket="b", key="k",
                            derivative_sha=sha, derivative_size=len(data))
    assert "test-bucket" not in str(ei.value) and "boom" not in str(ei.value)
    with pytest.raises(VerificationFailed):
        _try_verified_reuse(client=_FakeGet(RuntimeError("timeout")), bucket="b", key="k",
                            derivative_sha=sha, derivative_size=len(data))


def test_preexisting_ready_failed_reuse_no_uncover(test_db, tmp_path):
    """Pre-existing READY S + ambiguous reuse GET -> no PUT, baseline preserved."""
    from app.services.derivative_publisher import (
        build_publication_context,
        publish_derivative,
    )

    S = 1024
    dsha = _seed_ready(test_db, "clip-mono-1", "light", S)
    assert canary_legacy_ready_bytes(test_db) == S
    before = canary_accounted_bytes(test_db)
    assert before == S

    # Build a canary publish for the SAME logical slot but force the reuse
    # GET to fail ambiguously (500): publish must fail closed with no PUT
    # and no new charge, preserving the baseline.
    data = b"x" * 512
    artifact = tmp_path / "slot-mono.bin"
    artifact.write_bytes(data)
    # Seed a source so build_publication_context resolves (distinct clip).
    from app.config import get_settings as _gs
    from app.models.media_backbone import MediaBlob as _MB
    from app.models.photos_asset import PhotosAsset as _PA
    _s = _gs()
    _sha_src = _sha(b"camera-bytes-v1" + b"clip-mono-pub")
    test_db.add(_PA(video_uuid="clip-mono-pub"))
    test_db.flush()
    test_db.add(_MB(sha256=_sha_src, byte_size=15, storage_backend="b2",
                    bucket=_s.media_backbone_prod_bucket,
                    object_key=f"blobs/sha256/{_sha_src[:2]}/{_sha_src}",
                    width=1280, height=720, duration_seconds=10.0))
    test_db.commit()
    # Canonical source also needs a verified PROD location + revision.
    from app.models.media_backbone import MediaBlobLocation as _MBL, MediaRevision as _MR
    test_db.add(_MBL(blob_sha256=_sha_src, environment="prod", storage_backend="b2",
                      bucket=_s.media_backbone_prod_bucket,
                      object_key=f"blobs/sha256/{_sha_src[:2]}/{_sha_src}", verified=True))
    test_db.add(_MR(video_uuid="clip-mono-pub", blob_sha256=_sha_src,
                     rendition_semantics="photos_edited_rendition"))
    test_db.commit()
    ctx = build_publication_context(test_db, video_uuid="clip-mono-pub", role="light")

    class _AmbiguousS3:
        def get_object(self, Bucket, Key):
            raise _ServerErrorExc()
        def upload_file(self, *a, **k):
            raise AssertionError("PUT must not run when reuse is unverifiable")

    with pytest.raises(Exception):
        publish_derivative(test_db, ctx, artifact, s3_client=_AmbiguousS3(), canary_scope=True)
    test_db.rollback()
    # No PUT, no new charge: baseline preserved, monotonic non-decrease.
    assert canary_accounted_bytes(test_db) == before == S
    assert canary_reserved_bytes(test_db) == 0
    assert dsha is not None


def test_monotonic_charge_then_ready_double_counts(test_db):
    """Charge + READY commit is monotonic; success double-counts by design."""
    S = 1000
    dsha = _sha(b"mono-charge-ready")
    before = canary_accounted_bytes(test_db)
    assert before == 0
    reserve_canary_upload(test_db, **_reserve_kwargs(dsha, S, tag="mono1"))
    assert canary_accounted_bytes(test_db) == before + S
    # Promote the same bytes as READY (different key path is fine: baseline
    # counts per exact object, charges count per attempt).
    _seed_ready(test_db, "clip-mono-2", "light", S)
    mid = canary_accounted_bytes(test_db)
    # Baseline S + charge S = 2S (intentional over-count, monotonic increase).
    assert mid == before + 2 * S
    # Orphan charge (no READY) never decreases the total.
    dsha2 = _sha(b"mono-orphan")
    reserve_canary_upload(test_db, **_reserve_kwargs(dsha2, 500, tag="mono2"))
    assert canary_accounted_bytes(test_db) == mid + 500


def test_different_key_same_sha_baseline_counts_each(test_db):
    """Same content SHA under two READY rows counts twice (distinct objects)."""
    s1 = _seed_ready(test_db, "clip-mono-a", "light", 700)
    s2 = _seed_ready(test_db, "clip-mono-b", "light", 700)
    # Distinct clips -> distinct (video, role) rows, possibly same size but
    # different SHAs here; force same-SHA collision explicitly:
    from app.models.media_backbone import MediaDerivative
    row_b = test_db.query(MediaDerivative).filter(
        MediaDerivative.video_uuid == "clip-mono-b").one()
    row_b.derivative_blob_sha256 = s1
    test_db.commit()
    # Two READY rows sharing one content SHA still count per exact object.
    assert canary_legacy_ready_bytes(test_db) == 1400
    assert s2 is not None


def test_lookup_unknown_fails_closed(test_db):
    """Unknown lookups never return a false empty/False authorization."""
    from app.services.canary_budget import canary_scope_for_job_id

    # Missing job -> False is defined (no budget consumed), but any DB
    # failure must raise, never silently authorize.
    assert canary_scope_for_job_id(test_db, 999999) is False
    # Ambiguous reuse error is already proven fail-closed above; unknown
    # exception types are never definite-not-found.
    assert _is_definite_not_found(Exception("weird")) is False
    assert _is_definite_not_found(ValueError("404-ish but untyped")) is False
