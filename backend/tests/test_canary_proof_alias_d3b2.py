"""Canary proof HQ-alias gate (SQLite, no prod/B2).

PR145 review: ``crosscheck_proof_db`` accepted ``light+poster`` for ANY clip,
so a non-aliased HQ was never proven. Now:

- full ``hq+light+poster`` passes (all provided slots DB SHA/size + checks);
- non-aliased ``light+poster`` (READY hq exists) is rejected (HQ required);
- true producer alias ``light+poster`` passes ONLY with a valid current pin:
  web_package job finalized_slots pin matches proof source/revision/version,
  hq_aliased_to == light, same artifact SHAs, job ready, plus resolver
  still validates the alias;
- forged alias / missing job / stale source version are rejected;
- phase-2 fresh proof reload calls the same requirement.
"""

import datetime
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from app.config import get_settings
from app.models.media import MediaJob
from app.models.media_backbone import MediaBlob, MediaBlobLocation, MediaDerivative, MediaRevision
from app.models.photos_asset import PhotosAsset

OPS_TOOL = Path(__file__).resolve().parents[2] / "ops" / "canary_web_package.py"
TV = "ffmpeg-h264-web-v1"


def _load_ops():
    spec = importlib.util.spec_from_file_location("canary_web_package_alias", OPS_TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _seed_source(db, video_uuid, raw=b"camera-bytes-v1", width=1280, height=720, duration=10.0):
    settings = get_settings()
    sha = _sha(raw + video_uuid.encode())
    db.add(PhotosAsset(video_uuid=video_uuid))
    db.flush()
    db.add(MediaBlob(sha256=sha, byte_size=len(raw), storage_backend="b2",
                     bucket=settings.media_backbone_prod_bucket,
                     object_key=f"blobs/sha256/{sha[:2]}/{sha}",
                     width=width, height=height, duration_seconds=duration))
    db.add(MediaBlobLocation(blob_sha256=sha, environment="prod", storage_backend="b2",
                             bucket=settings.media_backbone_prod_bucket,
                             object_key=f"blobs/sha256/{sha[:2]}/{sha}", verified=True))
    db.add(MediaRevision(video_uuid=video_uuid, blob_sha256=sha,
                         rendition_semantics="photos_edited_rendition"))
    db.commit()
    return sha


def _seed_ready_derivative(db, video_uuid, source_sha, role, nbytes):
    dsha = _sha(f"{video_uuid}{role}".encode())
    settings = get_settings()
    db.add(MediaBlob(sha256=dsha, byte_size=nbytes, storage_backend="b2",
                     bucket=settings.media_backbone_prod_bucket,
                     object_key=f"blobs/sha256/{dsha[:2]}/{dsha}"))
    db.add(MediaBlobLocation(blob_sha256=dsha, environment="prod", storage_backend="b2",
                             bucket=settings.media_backbone_prod_bucket,
                             object_key=f"blobs/sha256/{dsha[:2]}/{dsha}", verified=True))
    db.add(MediaRevision(video_uuid=video_uuid, blob_sha256=dsha,
                         rendition_semantics=f"derived_{role}"))
    db.add(MediaDerivative(video_uuid=video_uuid, source_blob_sha256=source_sha,
                           role=role, transform_version=TV,
                           derivative_blob_sha256=dsha, status="ready"))
    db.commit()
    return dsha


def _proof_for(db, video_uuid, source_sha, rev_id, roles_sizes):
    from app.services.derivative_publisher import resolve_canonical_source_revision
    rev, _, _ = resolve_canonical_source_revision(db, video_uuid)
    assert int(rev.id) == int(rev_id)
    slots = {}
    for role, (dsha, nbytes) in roles_sizes.items():
        slots[role] = {"derivative_sha256": dsha, "byte_size": nbytes}
    ops = _load_ops()
    proof = {
        "video_uuid": video_uuid, "source_sha256": source_sha,
        "source_revision_id": int(rev.id), "transform_version": TV,
        "slots": slots,
        "checks": {n: True for n in ops.PROOF_REQUIRED_CHECKS},
        "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "operator": "op",
    }
    video_roles = [r for r in slots if r in ("hq", "light")]
    if video_roles:
        proof["cadence_evidence"] = {
            "source_sha256": source_sha,
            "source_frames": 600,
            "source_fps": 60.0,
            "source_duration": 10.0,
            "outputs": {r: {"frames": 600, "fps": 60.0, "duration": 10.0}
                        for r in video_roles},
            "vfr": False,
            "pts_exact_claimed": False,
        }
    return ops, proof


def _seed_alias_job(db, video_uuid, source_sha, rev_id, light_sha, poster_sha,
                    light_n=1000, poster_n=500, status="ready", hq_aliased_to="light",
                    width=640, height=480):
    asset = db.query(PhotosAsset).filter(PhotosAsset.video_uuid == video_uuid).one()
    job = MediaJob(
        photos_asset_id=asset.id,
        media_key=f"canary-{video_uuid}",
        rendition="web_package",
        status=status,
        finalized_slots={
            "source_sha256": source_sha,
            "source_revision_id": int(rev_id),
            "source_width": width,
            "source_height": height,
            "transform_version": TV,
            "hq_aliased_to": hq_aliased_to,
            "slots": {
                "light": {"derivative_sha256": light_sha, "size_bytes": light_n},
                "poster": {"derivative_sha256": poster_sha, "size_bytes": poster_n},
            },
        },
    )
    db.add(job)
    db.commit()
    return job


def test_nonaliased_light_poster_rejected_when_hq_ready(test_db):
    ops = _load_ops()
    src = _seed_source(test_db, "clip-nonalias-1", width=1920, height=1080)
    hq = _seed_ready_derivative(test_db, "clip-nonalias-1", src, "hq", 2000)
    light = _seed_ready_derivative(test_db, "clip-nonalias-1", src, "light", 1000)
    poster = _seed_ready_derivative(test_db, "clip-nonalias-1", src, "poster", 500)
    assert hq
    from app.services.derivative_publisher import resolve_canonical_source_revision as _rcr
    _rev, _, _ = _rcr(test_db, "clip-nonalias-1")
    _, proof = _proof_for(test_db, "clip-nonalias-1", src, int(_rev.id),
                          {"light": (light, 1000), "poster": (poster, 500)})
    norm = ops.validate_proof_record(proof)
    with pytest.raises(ValueError, match="HQ proof required"):
        ops.crosscheck_proof_db(test_db, norm)


def test_full_hq_light_poster_accepted(test_db):
    ops = _load_ops()
    src = _seed_source(test_db, "clip-full-1", width=1920, height=1080)
    hq = _seed_ready_derivative(test_db, "clip-full-1", src, "hq", 2000)
    light = _seed_ready_derivative(test_db, "clip-full-1", src, "light", 1000)
    poster = _seed_ready_derivative(test_db, "clip-full-1", src, "poster", 500)
    from app.services.derivative_publisher import resolve_canonical_source_revision as _rcr2
    _rev2, _, _ = _rcr2(test_db, "clip-full-1")
    _, proof = _proof_for(test_db, "clip-full-1", src, int(_rev2.id),
                          {"hq": (hq, 2000), "light": (light, 1000), "poster": (poster, 500)})
    norm = ops.validate_proof_record(proof)
    ops.crosscheck_proof_db(test_db, norm)


def test_true_producer_alias_accepted_only_valid_current_pin(test_db):
    ops = _load_ops()
    src = _seed_source(test_db, "clip-alias-1", width=640, height=480)
    light = _seed_ready_derivative(test_db, "clip-alias-1", src, "light", 1000)
    poster = _seed_ready_derivative(test_db, "clip-alias-1", src, "poster", 500)
    from app.services.derivative_publisher import resolve_canonical_source_revision
    rev, _, _ = resolve_canonical_source_revision(test_db, "clip-alias-1")
    _seed_alias_job(test_db, "clip-alias-1", src, int(rev.id), light, poster,
                    width=640, height=480, status="ready")
    _, proof = _proof_for(test_db, "clip-alias-1", src, int(rev.id),
                          {"light": (light, 1000), "poster": (poster, 500)})
    norm = ops.validate_proof_record(proof)
    ops.crosscheck_proof_db(test_db, norm)


def test_forged_alias_rejected(test_db):
    ops = _load_ops()
    src = _seed_source(test_db, "clip-forged-1", width=1920, height=1080)
    hq = _seed_ready_derivative(test_db, "clip-forged-1", src, "hq", 2000)
    light = _seed_ready_derivative(test_db, "clip-forged-1", src, "light", 1000)
    poster = _seed_ready_derivative(test_db, "clip-forged-1", src, "poster", 500)
    assert hq
    from app.services.derivative_publisher import resolve_canonical_source_revision
    rev, _, _ = resolve_canonical_source_revision(test_db, "clip-forged-1")
    # Forged job claims alias even though a distinct READY HQ exists.
    _seed_alias_job(test_db, "clip-forged-1", src, int(rev.id), light, poster,
                    width=1920, height=1080, status="ready")
    _, proof = _proof_for(test_db, "clip-forged-1", src, int(rev.id),
                          {"light": (light, 1000), "poster": (poster, 500)})
    norm = ops.validate_proof_record(proof)
    with pytest.raises(ValueError, match="HQ proof required|not validated"):
        ops.crosscheck_proof_db(test_db, norm)


def test_missing_job_alias_rejected(test_db):
    ops = _load_ops()
    src = _seed_source(test_db, "clip-nojob-1", width=640, height=480)
    light = _seed_ready_derivative(test_db, "clip-nojob-1", src, "light", 1000)
    poster = _seed_ready_derivative(test_db, "clip-nojob-1", src, "poster", 500)
    from app.services.derivative_publisher import resolve_canonical_source_revision
    rev, _, _ = resolve_canonical_source_revision(test_db, "clip-nojob-1")
    _, proof = _proof_for(test_db, "clip-nojob-1", src, int(rev.id),
                          {"light": (light, 1000), "poster": (poster, 500)})
    norm = ops.validate_proof_record(proof)
    with pytest.raises(ValueError, match="HQ proof required"):
        ops.crosscheck_proof_db(test_db, norm)


def test_stale_source_version_alias_rejected(test_db):
    ops = _load_ops()
    src = _seed_source(test_db, "clip-stalealias-1", width=640, height=480)
    light = _seed_ready_derivative(test_db, "clip-stalealias-1", src, "light", 1000)
    poster = _seed_ready_derivative(test_db, "clip-stalealias-1", src, "poster", 500)
    from app.services.derivative_publisher import resolve_canonical_source_revision
    rev, _, _ = resolve_canonical_source_revision(test_db, "clip-stalealias-1")
    _seed_alias_job(test_db, "clip-stalealias-1", src, int(rev.id), light, poster,
                    width=640, height=480, status="ready")
    # Source moves after the pin: new canonical revision.
    settings = get_settings()
    new_sha = _sha(b"camera-bytes-v2-clip-stalealias-1")
    test_db.add(MediaBlob(sha256=new_sha, byte_size=18, storage_backend="b2",
                          bucket=settings.media_backbone_prod_bucket,
                          object_key=f"blobs/sha256/{new_sha[:2]}/{new_sha}",
                          width=640, height=480, duration_seconds=10.0))
    test_db.add(MediaBlobLocation(blob_sha256=new_sha, environment="prod", storage_backend="b2",
                                  bucket=settings.media_backbone_prod_bucket,
                                  object_key=f"blobs/sha256/{new_sha[:2]}/{new_sha}", verified=True))
    from app.models.media_backbone import MediaRevision as _MR
    test_db.add(_MR(video_uuid="clip-stalealias-1", blob_sha256=new_sha,
                    rendition_semantics="photos_edited_rendition"))
    test_db.commit()
    from app.services.derivative_publisher import resolve_canonical_source_revision as _rcr_new
    new_rev, _, _ = _rcr_new(test_db, "clip-stalealias-1")
    _, proof = _proof_for(test_db, "clip-stalealias-1", new_sha, int(new_rev.id),
                          {"light": (light, 1000), "poster": (poster, 500)})
    # Proof references the NEW source but the job pin + ledger rows are stale.
    norm = ops.validate_proof_record(proof)
    with pytest.raises(ValueError):
        ops.crosscheck_proof_db(test_db, norm)


def test_size_mismatch_rejected(test_db):
    ops = _load_ops()
    src = _seed_source(test_db, "clip-size-1", width=1920, height=1080)
    hq = _seed_ready_derivative(test_db, "clip-size-1", src, "hq", 2000)
    light = _seed_ready_derivative(test_db, "clip-size-1", src, "light", 1000)
    poster = _seed_ready_derivative(test_db, "clip-size-1", src, "poster", 500)
    from app.services.derivative_publisher import resolve_canonical_source_revision as _rcr3
    _rev3, _, _ = _rcr3(test_db, "clip-size-1")
    _, proof = _proof_for(test_db, "clip-size-1", src, int(_rev3.id),
                          {"hq": (hq, 2000), "light": (light, 9999), "poster": (poster, 500)})
    norm = ops.validate_proof_record(proof)
    with pytest.raises(ValueError, match="size mismatch"):
        ops.crosscheck_proof_db(test_db, norm)


def test_phase2_fresh_reload_enforces_alias(test_db, tmp_path):
    ops = _load_ops()
    src = _seed_source(test_db, "clip-p1-alias-1", width=640, height=480)
    light = _seed_ready_derivative(test_db, "clip-p1-alias-1", src, "light", 1000)
    poster = _seed_ready_derivative(test_db, "clip-p1-alias-1", src, "poster", 500)
    from app.services.derivative_publisher import resolve_canonical_source_revision
    rev, _, _ = resolve_canonical_source_revision(test_db, "clip-p1-alias-1")
    # No job pin -> fresh reload must refuse light+poster (HQ required).
    _, proof = _proof_for(test_db, "clip-p1-alias-1", src, int(rev.id),
                          {"light": (light, 1000), "poster": (poster, 500)})
    proofs_dir = tmp_path / "proofs"
    proofs_dir.mkdir(parents=True)
    (proofs_dir / "proof-clip-p1-alias-1.json").write_text(json.dumps(proof))
    with pytest.raises(ValueError, match="HQ proof required|stale proof"):
        ops._require_fresh_phase1_proofs(test_db, tmp_path, ["clip-p1-alias-1"])
