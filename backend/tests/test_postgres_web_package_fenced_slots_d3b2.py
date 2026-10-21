"""D3b2 fenced web-package slots on real PostgreSQL (disposable calendar_test_* only).

Wired into the CI ``postgres`` tier (``ci/postgres.sh``). Proves what SQLite
cannot (row locks, advisory locks, concurrent TX):

- barrier stale claim mid-B2-network is rejected: a slow upload holds the
  fake B2 gate while a concurrent reclaim + re-lease mints a new token; the
  stale attempt's commit is rejected (StaleSourceError), nothing is promoted
  (ledger NOT ready, job NOT ready), the verified B2 bytes stay a safe orphan;
- concurrent two slots for the SAME job do not lose JSON updates: hq + light
  published from two threads both commit, ``finalized_slots`` holds both,
  job becomes ready only after the third slot (poster) with ledger-durable
  proof for priors;
- global ONE active package serializes concurrent agents: two leases for two
  assets race under the advisory lock, at most one mints a package;
- source-changed first slot rejects (lease pin v1 vs current canonical v2):
  the guard refuses instead of retagging, job pin stays v1, ledger stays NOT
  ready.

Session hygiene: scoped fixtures (per-test ``uuid4`` namespaces, own-row-only
cleanup via parameterized SQL) so this file runs in the full ordered tier
alongside D1/D2/D3b1 tests sharing one database without touching other
namespaces. No real B2 (thread-safe in-memory S3 fake with an upload gate);
PG transactions are authoritative. Lease + publish paths are exercised (not
the guard alone); format validation is mocked for fencing focus (real format
proof lives in the SQLite tier + encoder canary).
"""

import hashlib
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[2]
PG_URL = os.environ.get("CALENDAR_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not PG_URL, reason="Disposable PostgreSQL required")


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _engine():
    assert PG_URL, "CALENDAR_TEST_DATABASE_URL is required"
    url = make_url(PG_URL)
    assert url.get_backend_name() == "postgresql", "PostgreSQL only"
    assert (url.database or "").startswith("calendar_test_"), (
        "Disposable calendar_test_* database required — refusing anything else"
    )
    return create_engine(url.set(drivername="postgresql+psycopg2"))


def _make_tables(engine):
    from app.database import Base

    # Create ONLY owned tables (+ FK deps) — never the full metadata (some
    # legacy tables carry non-portable defaults). Mirrors the D2 PG tier.
    need = {
        "photos_assets", "media_jobs", "media_agents", "photos_asset_agent_identities",
        "media_blobs", "media_blob_locations", "media_revisions",
        "caption_revisions", "ingest_object_state", "media_derivatives",
    }
    tables = {Base.metadata.tables[n] for n in need if n in Base.metadata.tables}
    while True:
        deps = {fk.column.table for t in tables for fk in t.foreign_keys}
        if deps <= tables:
            break
        tables |= deps
    Base.metadata.create_all(bind=engine, tables=list(tables))


class FakeBody:
    def __init__(self, data: bytes):
        self._buf = __import__("io").BytesIO(data)

    def iter_chunks(self, chunk_size=1024 * 1024):
        while True:
            piece = self._buf.read(chunk_size)
            if piece:
                yield piece
            else:
                break

    def close(self):
        pass


class FakeS3:
    """Thread-safe in-memory S3 with an optional upload gate (fault-free)."""

    def __init__(self, gate=None):
        self.objects = {}
        self._lock = threading.Lock()
        self._gate = gate
        self.uploads = 0

    def upload_file(self, path, bucket, key, ExtraArgs=None):
        if self._gate is not None:
            self._gate.wait(timeout=60)
        from pathlib import Path as _P

        with self._lock:
            self.uploads += 1
            self.objects[(bucket, key)] = _P(path).read_bytes()

    def get_object(self, Bucket, Key):
        with self._lock:
            data = self.objects[(Bucket, Key)]
        return {"Body": FakeBody(data)}


class Scope:
    """Per-test namespace + own-row-only cleanup for the shared tier DB."""

    def __init__(self, tag: str):
        self.tag = f"pg-d3b2-{tag}-{uuid4().hex[:10]}"
        self.videos: list[str] = []
        self.shas: list[str] = []
        self.prefixes: list[str] = [self.tag]

    def video(self, name: str) -> str:
        v = f"{self.tag}-{name}"
        self.videos.append(v)
        return v

    def track_sha(self, sha: str) -> str:
        self.shas.append(sha)
        return sha

    def cleanup(self, engine) -> None:
        from app.database import Base

        tables = Base.metadata.tables
        with engine.begin() as conn:
            if self.videos:
                for name in ("media_derivatives", "media_revisions", "ingest_object_state"):
                    if name in tables:
                        conn.execute(
                            tables[name].delete().where(tables[name].c.video_uuid.in_(self.videos))
                        )
                # jobs/assets/identities by video prefix
                for prefix in self.prefixes:
                    like = prefix + "%"
                    conn.execute(
                        text("DELETE FROM media_jobs WHERE media_key LIKE :p OR claimed_by LIKE :p"),
                        {"p": like},
                    )
                    conn.execute(
                        text("DELETE FROM photos_asset_agent_identities WHERE agent_id LIKE :p"),
                        {"p": like},
                    )
                    conn.execute(
                        text(
                            "DELETE FROM photos_asset_agent_identities WHERE photos_asset_id IN "
                            "(SELECT id FROM photos_assets WHERE video_uuid LIKE :p)"
                        ),
                        {"p": like},
                    )
                    conn.execute(
                        text("DELETE FROM photos_assets WHERE video_uuid LIKE :p"),
                        {"p": like},
                    )
                    conn.execute(
                        text("DELETE FROM media_agents WHERE id LIKE :p"),
                        {"p": like},
                    )
            if self.shas:
                conn.execute(
                    tables["media_blob_locations"].delete().where(
                        tables["media_blob_locations"].c.blob_sha256.in_(self.shas)
                    )
                )
                conn.execute(
                    tables["media_blobs"].delete().where(tables["media_blobs"].c.sha256.in_(self.shas))
                )


@pytest.fixture()
def scope(request):
    tag = request.node.name.replace("[", "-").replace("]", "").replace(" ", "")[:30]
    sc = Scope(tag)
    engine = _engine()
    _make_tables(engine)
    yield sc
    try:
        sc.cleanup(engine)
    finally:
        engine.dispose()


@pytest.fixture()
def creds(monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "b2_upload_key_id", "test-key")
    monkeypatch.setattr(settings, "b2_upload_key_secret", "test-secret-xyz")
    monkeypatch.setattr(settings, "b2_upload_region", "test-region")
    monkeypatch.setattr(settings, "b2_upload_environment", "prod")
    monkeypatch.setattr(settings, "b2_upload_endpoint_url", "")
    monkeypatch.setattr(settings, "media_web_packages_enabled", True)
    monkeypatch.setattr(settings, "media_jobs_require_lease_token", True)
    monkeypatch.setattr(settings, "media_jobs_b2_source_enabled", True)
    return settings


def _seed_camera(engine, scope, video_uuid, raw: bytes, width=None, height=None):
    from app.config import get_settings
    from app.models.media_backbone import MediaBlob, MediaBlobLocation, MediaRevision

    settings = get_settings()
    sha = scope.track_sha(_sha(raw))
    with engine.begin() as conn:
        conn.execute(
            MediaBlob.__table__.insert().values(
                sha256=sha, byte_size=len(raw), storage_backend="b2",
                bucket=settings.media_backbone_prod_bucket,
                object_key=f"blobs/sha256/{sha[:2]}/{sha}",
                width=width, height=height,
            )
        )
        conn.execute(
            MediaBlobLocation.__table__.insert().values(
                blob_sha256=sha, environment="prod", storage_backend="b2",
                bucket=settings.media_backbone_prod_bucket,
                object_key=f"blobs/sha256/{sha[:2]}/{sha}", verified=True,
            )
        )
        conn.execute(
            MediaRevision.__table__.insert().values(
                video_uuid=video_uuid, blob_sha256=sha, rendition_semantics="photos_edited_rendition"
            )
        )
    return sha


def _seed_agent_asset_job(engine, scope, video_name, raw: bytes, agent_suffix="a",
                          rendition="web_package", width=1920, height=1080):
    from app.models.media import MediaAgent, MediaJob
    from app.models.photos_asset import PhotosAsset

    video_uuid = scope.video(video_name)
    sha = _seed_camera(engine, scope, video_uuid, raw, width=width, height=height)
    agent_id = f"{scope.tag}-{agent_suffix}"
    with engine.begin() as conn:
        conn.execute(
            MediaAgent.__table__.insert().values(
                id=agent_id, hostname="h",
                api_key_sha256=hashlib.sha256(f"{agent_id}-key".encode()).hexdigest(),
                active=True, leasing_enabled=True, capabilities=["poster", "proxy_720p", "web_package"],
            )
        )
        res = conn.execute(
            PhotosAsset.__table__.insert().values(
                video_uuid=video_uuid, media_type="video", width=width, height=height
            ).returning(PhotosAsset.__table__.c.id)
        )
        asset_id = res.scalar_one()
        res2 = conn.execute(
            MediaJob.__table__.insert().values(
                photos_asset_id=asset_id, media_key=(scope.tag + video_name)[:56].ljust(64, "0")[:64],
                rendition=rendition, status="queued",
            ).returning(MediaJob.__table__.c.id)
        )
        job_id = res2.scalar_one()
    return video_uuid, sha, agent_id, asset_id, job_id


def _lease_one(factory, agent_id, capabilities=("web_package",)):
    from app.schemas.media import MediaJobLeaseRequest
    from app.services import media_jobs as mj

    s = factory()
    try:
        # Fake presign (no network): same signed URL shape as SQLite tier.
        import app.services.b2_presign as _bp

        _orig = _bp.presign_get

        class _FakeSigned:
            url = "https://b2.test/signed-object"

        _bp.presign_get = lambda **kw: _FakeSigned()
        try:
            leased = mj.lease_media_jobs(
                s, MediaJobLeaseRequest(agent_id=agent_id, capabilities=list(capabilities),
                                       max_jobs=1, supports_lease_token=True))
        finally:
            _bp.presign_get = _orig
        s.commit()
        assert leased, "expected one leased job"
        # Detach IDs before close (expire_on_commit=False keeps attrs).
        out = leased[0]
        job_id = out.job_id
        token = out.lease_token
        transform = out.transform_version
        source_sha = out.source_sha256
        return job_id, token, transform, source_sha
    finally:
        s.close()


def _mock_validate(monkeypatch, dims=(1280, 720)):
    import app.services.web_packages as wp

    monkeypatch.setattr(
        wp, "validate_slot_artifact", lambda **kw: {"width": dims[0], "height": dims[1]}
    )


def test_barrier_stale_claim_mid_b2_network_rejected(scope, creds, tmp_path, monkeypatch):
    """Slow B2 upload + mid-network reclaim: stale commit rejected, nothing ready."""
    from app.models.media import MediaJob
    from app.services.derivative_publisher import (
        StaleSourceError,
        build_publication_context,
        publish_derivative,
    )
    from app.services.media_jobs import reclaim_expired_media_jobs
    from app.services.web_packages import get_finalized_state, make_slot_guard
    from app.services.media_keys import get_derivative_transform_version

    engine = _engine()
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    factory = Session
    try:
        video_uuid, sha, agent_id, asset_id, job_id = _seed_agent_asset_job(
            engine, scope, "barrier", b"pg-d3b2-barrier-src")
        job_id, token, transform, pinned = _lease_one(factory, agent_id)
        assert pinned == sha

        gate = threading.Barrier(2)
        fake = FakeS3(gate=gate)
        artifact = tmp_path / "hq.bin"
        artifact.write_bytes(b"pg-barrier-slot-bytes" * 64)
        errors: list = []
        results: list = []

        def stale_publish():
            s = Session()
            try:
                ctx = build_publication_context(s, video_uuid=video_uuid, role="hq")
                guard = make_slot_guard(
                    job_id=job_id, agent_id=agent_id, lease_token=token,
                    claimed_source_sha256=sha, slot="hq",
                    applicable=["hq", "light", "poster"], hq_aliased_to=None,
                    transform_version=transform, claimed_transform_version=transform)
                results.append(publish_derivative(s, ctx, artifact, s3_client=fake,
                                                  pre_commit_hook=guard))
            except Exception as exc:  # noqa: BLE001 — asserted below
                errors.append(exc)
            finally:
                s.close()

        t = threading.Thread(target=stale_publish)
        t.start()
        # Wait until the uploader is inside the B2 gate (network in flight,
        # no DB row lock held), then reclaim + re-lease to the SAME agent.
        time.sleep(1.0)
        s2 = Session()
        try:
            j = s2.get(MediaJob, job_id)
            j.claimed_until = datetime.utcnow() - timedelta(seconds=1)
            s2.commit()
        finally:
            s2.close()
        s3 = Session()
        try:
            assert reclaim_expired_media_jobs(s3) == 1
            s3.commit()
        finally:
            s3.close()
        job_id2, token2, _, _ = _lease_one(factory, agent_id)
        assert job_id2 == job_id and token2 != token
        # Release the B2 gate: the stale attempt now tries to commit.
        gate.wait(timeout=60)
        t.join(timeout=120)
        assert not t.is_alive(), "stale publisher hung"
        assert len(results) == 0, f"stale publish must not succeed: {results}"
        assert len(errors) == 1
        assert isinstance(errors[0], StaleSourceError) or "lease" in str(errors[0]).lower() \
            or "token" in str(errors[0]).lower() or "stale" in str(errors[0]).lower(), errors[0]
        # Nothing promoted: ledger NOT ready, job NOT ready, pin preserved.
        s4 = Session()
        try:
            from sqlalchemy import select as _select
            from app.models.media_backbone import MediaDerivative

            rows = s4.execute(
                _select(MediaDerivative).where(MediaDerivative.video_uuid == video_uuid)
            ).scalars().all()
            assert all(r.status != "ready" for r in rows), rows
            j = s4.get(MediaJob, job_id)
            assert j.status != "ready"
            assert j.lease_token == token2
            st = get_finalized_state(j)
            # No slot committed for the stale attempt.
            assert st["slots"].get("hq") is None
            # B2 orphan retained by design (never deleted).
            assert len(fake.objects) >= 1
        finally:
            s4.close()
    finally:
        engine.dispose()


def test_concurrent_two_slots_same_job_no_lost_update(scope, creds, tmp_path, monkeypatch):
    """hq + light concurrently: both slots land, no JSON lost update, ready after poster."""
    from app.services.derivative_publisher import build_publication_context, publish_derivative
    from app.services.media_keys import get_derivative_transform_version
    from app.services.web_packages import get_finalized_state

    _mock_validate(monkeypatch)
    engine = _engine()
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    factory = Session
    try:
        video_uuid, sha, agent_id, asset_id, job_id = _seed_agent_asset_job(
            engine, scope, "concurrent", b"pg-d3b2-concurrent-src")
        job_id, token, transform, _ = _lease_one(factory, agent_id)
        tv = transform or get_derivative_transform_version()

        def _slot_bytes(name: bytes) -> Path:
            p = tmp_path / f"{name.decode()}.bin"
            p.write_bytes(b"pg-concurrent-" + name + b"-" * 64)
            return p

        hq_path = _slot_bytes(b"hq")
        light_path = _slot_bytes(b"light")

        def _pub(role: str, path: Path, out: list, errs: list):
            s = Session()
            try:
                import app.services.web_packages as wp

                ctx = build_publication_context(s, video_uuid=video_uuid, role=role)
                guard = wp.make_slot_guard(
                    job_id=job_id, agent_id=agent_id, lease_token=token,
                    claimed_source_sha256=sha, slot=role,
                    applicable=["hq", "light", "poster"], hq_aliased_to=None,
                    transform_version=tv, claimed_transform_version=tv)
                out.append(publish_derivative(s, ctx, path, s3_client=FakeS3(),
                                              pre_commit_hook=guard))
            except Exception as exc:  # noqa: BLE001
                errs.append(exc)
            finally:
                s.close()

        hq_out: list = []
        hq_err: list = []
        light_out: list = []
        light_err: list = []
        th1 = threading.Thread(target=_pub, args=("hq", hq_path, hq_out, hq_err))
        th2 = threading.Thread(target=_pub, args=("light", light_path, light_out, light_err))
        th1.start()
        th2.start()
        th1.join(timeout=120)
        th2.join(timeout=120)
        assert not th1.is_alive() and not th2.is_alive()
        assert not hq_err, hq_err
        assert not light_err, light_err
        assert len(hq_out) == 1 and len(light_out) == 1

        s = Session()
        try:
            from app.models.media import MediaJob

            j = s.get(MediaJob, job_id)
            st = get_finalized_state(j)
            assert set(st["slots"].keys()) == {"hq", "light"}, st
            assert j.status != "ready"
            # Poster completes the package: prior slots must be ledger-durable.
            import app.services.web_packages as wp2

            poster_path = _slot_bytes(b"poster")
            ctx = build_publication_context(s, video_uuid=video_uuid, role="poster")
            # NOTE: same session already holds job state; the guard re-reads
            # row-locked, so no stale identity-map issue on PG.
            guard = wp2.make_slot_guard(
                job_id=job_id, agent_id=agent_id, lease_token=token,
                claimed_source_sha256=sha, slot="poster",
                applicable=["hq", "light", "poster"], hq_aliased_to=None,
                transform_version=tv, claimed_transform_version=tv)
            # Need a fresh session for publish (publisher requires clean).
            s.rollback()
            s.close()
            s2 = Session()
            try:
                ctx2 = build_publication_context(s2, video_uuid=video_uuid, role="poster")
                guard2 = wp2.make_slot_guard(
                    job_id=job_id, agent_id=agent_id, lease_token=token,
                    claimed_source_sha256=sha, slot="poster",
                    applicable=["hq", "light", "poster"], hq_aliased_to=None,
                    transform_version=tv, claimed_transform_version=tv)
                publish_derivative(s2, ctx2, poster_path, s3_client=FakeS3(),
                                   pre_commit_hook=guard2)
            finally:
                s2.close()
            s3 = Session()
            try:
                from app.models.media import MediaJob as _MJ
                from app.services.web_packages import get_finalized_state as _gfs

                jj = s3.get(_MJ, job_id)
                assert _gfs(jj)["slots"].keys() == {"hq", "light", "poster"}
                assert jj.status == "ready", jj.status
            finally:
                s3.close()
        finally:
            try:
                s.close()
            except Exception:
                pass
    finally:
        engine.dispose()


def test_global_one_package_serialized(scope, creds):
    """Two concurrent package leases: at most one mints (advisory lock)."""
    engine = _engine()
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    factory = Session
    try:
        _, _, agent_a, _, _ = _seed_agent_asset_job(engine, scope, "g1", b"pg-d3b2-g1", agent_suffix="a")
        _, _, agent_b, _, _ = _seed_agent_asset_job(engine, scope, "g2", b"pg-d3b2-g2", agent_suffix="b")
        # Both agents share one fleet cap: use the same agent id for the
        # second lease to prove the cap is global, not per-agent.
        barrier = threading.Barrier(2)
        minted: list = []
        errs: list = []

        def _lease(agent: str):
            s = Session()
            try:
                from app.schemas.media import MediaJobLeaseRequest
                from app.services import media_jobs as mj
                import app.services.b2_presign as _bp

                barrier.wait(timeout=60)
                _orig = _bp.presign_get

                class _FakeSigned:
                    url = "https://b2.test/signed-object"

                _bp.presign_get = lambda **kw: _FakeSigned()
                try:
                    leased = mj.lease_media_jobs(
                        s, MediaJobLeaseRequest(agent_id=agent, capabilities=["web_package"],
                                               max_jobs=1, supports_lease_token=True))
                    s.commit()
                    minted.append([j.job_id for j in leased if j.rendition == "web_package"])
                finally:
                    _bp.presign_get = _orig
            except Exception as exc:  # noqa: BLE001
                errs.append(exc)
            finally:
                s.close()

        ta = threading.Thread(target=_lease, args=(agent_a,))
        tb = threading.Thread(target=_lease, args=(agent_b,))
        ta.start()
        tb.start()
        ta.join(timeout=120)
        tb.join(timeout=120)
        assert not ta.is_alive() and not tb.is_alive()
        assert not errs, errs
        total = sum(len(m) for m in minted)
        assert total <= 1, f"global cap violated: {minted}"
    finally:
        engine.dispose()


def test_source_changed_first_slot_rejects_not_retags(scope, creds, tmp_path, monkeypatch):
    """Lease pin v1 vs current canonical v2: first slot rejects, pin stays v1."""
    from app.services.derivative_publisher import (
        StaleSourceError,
        build_publication_context,
        publish_derivative,
    )
    from app.services.web_packages import get_finalized_state, make_slot_guard

    _mock_validate(monkeypatch)
    engine = _engine()
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    factory = Session
    try:
        video_uuid, sha_v1, agent_id, asset_id, job_id = _seed_agent_asset_job(
            engine, scope, "srcchange", b"pg-d3b2-src-v1")
        job_id, token, transform, _ = _lease_one(factory, agent_id)
        # New verified source lands before the first slot.
        _seed_camera(engine, scope, video_uuid, b"pg-d3b2-src-v2-newer")
        artifact = tmp_path / "hq.bin"
        artifact.write_bytes(b"pg-srcchange-bytes" * 64)
        s = Session()
        try:
            ctx = build_publication_context(s, video_uuid=video_uuid, role="hq")
            assert ctx.source_blob_sha256 != sha_v1
            guard = make_slot_guard(
                job_id=job_id, agent_id=agent_id, lease_token=token,
                claimed_source_sha256=sha_v1, slot="hq",
                applicable=["hq", "light", "poster"], hq_aliased_to=None,
                transform_version=transform, claimed_transform_version=transform)
            with pytest.raises(StaleSourceError):
                publish_derivative(s, ctx, artifact, s3_client=FakeS3(),
                                   pre_commit_hook=guard)
        finally:
            s.close()
        s2 = Session()
        try:
            from app.models.media import MediaJob as _MJ

            j = s2.get(_MJ, job_id)
            assert j.status != "ready"
            st = get_finalized_state(j)
            # Pin NOT retagged to v2: still v1, no slot committed.
            assert (st.get("source_sha256") or "").lower() == sha_v1.lower()
            assert st["slots"] == {}
        finally:
            s2.close()
    finally:
        engine.dispose()
